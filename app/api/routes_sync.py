"""Sync triggers, Withings OAuth handshake, and the Data Health view."""

import secrets
from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.hevy import HevyAdapter
from app.adapters.withings import WithingsAdapter
from app.api.deps import db, require_token
from app.config import get_settings
from app.models import Checkin, Day, SyncRun
from app.schemas.common import DataHealthOut, SourceHealth, SyncRunOut
from app.services.ingest import sync_run
from app.services.timeutil import local_date, utcnow

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[Depends(require_token)])
public = APIRouter(prefix="/withings", tags=["withings"])

ADAPTERS = {"hevy": HevyAdapter, "withings": WithingsAdapter}
STALE_AFTER_HOURS = 36


@router.post("/{source}")
def run_sync(
    source: str,
    mode: str = Query("incremental", pattern="^(incremental|backfill)$"),
    since: Date | None = None,
    session: Session = Depends(db),
) -> dict:
    if source not in ADAPTERS:
        raise HTTPException(404, f"Unknown source '{source}'")

    # The adapter is constructed INSIDE the run so a configuration failure
    # (missing key, no stored OAuth token) is recorded as a failed run rather
    # than vanishing into a 500. A sync that dies without a trace makes the
    # Data Health screen lie, which is worse than the failure itself.
    try:
        with sync_run(session, source) as run:
            adapter = ADAPTERS[source]()
            result = (
                adapter.backfill(session, since=since)
                if mode == "backfill"
                else adapter.incremental(session)
            )
            run.records_ingested = result.records_ingested
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"{source} sync failed: {exc}") from exc
    return {
        "source": source,
        "mode": mode,
        "records_ingested": result.records_ingested,
        "records_skipped": result.records_skipped,
        "notes": result.notes,
    }


@router.get("/runs", response_model=list[SyncRunOut])
def list_runs(session: Session = Depends(db)) -> list[SyncRun]:
    return list(
        session.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(50)).scalars()
    )


@router.get("/health", response_model=DataHealthOut)
def data_health(session: Session = Depends(db)) -> DataHealthOut:
    """Plan 10.1 screen 7. Unglamorous, and the reason this still works in a year."""
    settings = get_settings()
    now = utcnow()
    today = local_date(now)

    configured = {
        "hevy": settings.hevy_enabled,
        "withings": settings.withings_enabled,
        "health_connect": False,  # Phase 3
    }

    sources: list[SourceHealth] = []
    for name, is_configured in configured.items():
        last = session.execute(
            select(SyncRun)
            .where(SyncRun.source == name)
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        last_success = session.execute(
            select(SyncRun)
            .where(SyncRun.source == name, SyncRun.status == "success")
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        stale = is_configured and (
            last_success is None
            or (now - last_success.started_at) > timedelta(hours=STALE_AFTER_HOURS)
        )
        sources.append(
            SourceHealth(
                source=name,
                configured=is_configured,
                last_success_at=last_success.started_at if last_success else None,
                last_status=last.status if last else None,
                last_error=last.error_message if last else None,
                records_last_run=last.records_ingested if last else None,
                stale=stale,
            )
        )

    # Overnight wear rate (plan 6.1 wear-bias guard). Until Health Connect
    # lands in Phase 3 the only signal is the check-in's `no_watch` tag, so
    # this is derived from check-ins and will be replaced by sleep_sessions.
    window_start = today - timedelta(days=6)
    recent = list(session.execute(select(Checkin).where(Checkin.date >= window_start)).scalars())
    wear_rate = None
    if recent:
        worn = sum(1 for c in recent if "no_watch" not in (c.tags or []))
        wear_rate = round(worn / 7 * 100, 1)

    completed_30d = session.execute(
        select(func.count(Checkin.date)).where(Checkin.date >= today - timedelta(days=29))
    ).scalar_one()

    return DataHealthOut(
        generated_at=now,
        sources=sources,
        overnight_wear_rate_7d=wear_rate,
        checkin_completion_rate_30d=round(completed_30d / 30 * 100, 1),
        days_with_data=session.execute(select(func.count(Day.date))).scalar_one(),
    )


# -- Withings OAuth ------------------------------------------------------
# The callback is unauthenticated because Withings calls it, but it is
# CSRF-protected by the state parameter issued at /authorize.

_pending_states: set[str] = set()


@public.get("/authorize", dependencies=[Depends(require_token)])
def withings_authorize() -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    _pending_states.add(state)
    return RedirectResponse(WithingsAdapter().authorize_url(state))


@public.get("/callback")
def withings_callback(code: str, state: str, session: Session = Depends(db)) -> dict:
    if state not in _pending_states:
        raise HTTPException(400, "Unrecognised OAuth state")
    _pending_states.discard(state)
    WithingsAdapter().exchange_code(session, code)
    return {"status": "connected", "next": "POST /api/v1/sync/withings?mode=backfill"}
