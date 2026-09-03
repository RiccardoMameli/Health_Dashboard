"""Brief and metrics endpoints (plan 9, 10.1).

The generate endpoint is the one the 06:30 job calls. It is idempotent: the
day's brief is upserted, so a retry after a network failure produces one
brief, not two.
"""

from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai.client import BriefGenerationError
from app.api.deps import db, require_token
from app.config import Settings, get_settings
from app.services import brief as brief_service
from app.services.email import EmailDeliveryError, mark_delivered, render_html, send_brief
from app.services.metrics_engine import build_brief_input, compute_day, persist
from app.services.timeutil import local_date, utcnow

router = APIRouter(prefix="/brief", tags=["brief"], dependencies=[Depends(require_token)])
metrics_router = APIRouter(
    prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_token)]
)


def _serialise(row) -> dict:
    return {
        "id": row.id,
        "date": row.date.isoformat(),
        "phase": row.phase,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "delivered_via": row.delivered_via,
        "feedback_rating": row.feedback_rating,
        "output": row.output,
        "input_snapshot": row.input_snapshot,
    }


@metrics_router.get("/{day}")
def metrics_for_day(day: Date, session: Session = Depends(db)) -> dict:
    """Every computed number for one morning, with its baselines.

    This is what makes "no number is a black box" true: the Today screen can
    show the definition and inputs behind any figure it renders.
    """
    computed = compute_day(session, day)
    persist(session, computed)
    return {
        "date": day.isoformat(),
        "readiness": computed.readiness.as_dict() if computed.readiness else None,
        "completeness": {
            "pct": round(computed.data_completeness_pct, 1),
            "fields": computed.present,
        },
        "sleep": {
            "duration_min": computed.sleep_duration_min,
            "efficiency_pct": computed.sleep_efficiency_pct,
            "baseline_min": computed.sleep_baseline.median if computed.sleep_baseline else None,
            "baseline_n": computed.sleep_baseline.n if computed.sleep_baseline else 0,
            "baseline_status": computed.sleep_baseline.status if computed.sleep_baseline else None,
            "debt_14d_min": computed.sleep_debt_14d_min,
            "debt_nights_observed": computed.sleep_debt_nights,
            "midpoint_variance_min": computed.sleep_midpoint_variance_min,
        },
        "cardio": {
            "resting_hr": computed.resting_hr,
            "baseline_rhr": computed.rhr_baseline.median if computed.rhr_baseline else None,
            "deviation_bpm": computed.rhr_deviation_bpm,
            "hrv_ms": computed.hrv_ms,
            "hrv_deviation_pct": computed.hrv_deviation_pct,
        },
        "training": {
            "acute_load_7d": computed.acute_load_7d,
            "chronic_load_28d": computed.chronic_load_28d,
            "acwr": computed.acwr,
            "days_since_rest": computed.days_since_rest,
        },
        "body": {
            "weight_ewma_kg": computed.weight_ewma_kg,
            "trend_kg_per_week": computed.weight_trend_kg_per_week,
            "protein_g_per_kg": computed.protein_g_per_kg,
        },
    }


@router.get("/input/{day}")
def brief_input(
    day: Date, session: Session = Depends(db), settings: Settings = Depends(get_settings)
) -> dict:
    """The exact payload the model would receive. Useful before spending a call."""
    computed = compute_day(session, day, settings)
    return build_brief_input(session, computed, phase=settings.brief_phase)


@router.post("", status_code=201)
def generate(
    day: Date | None = None,
    send: bool = Query(default=False, description="Deliver by email after generating"),
    session: Session = Depends(db),
) -> dict:
    """Generate (and optionally deliver) the day's brief."""
    day = day or local_date(utcnow())
    try:
        row = brief_service.generate_and_store(session, day)
    except BriefGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payload = _serialise(row)
    if send:
        try:
            payload["delivery"] = {"id": send_brief(row), "status": "sent"}
            mark_delivered(session, row, "email")
        except EmailDeliveryError as exc:
            # The brief exists and is stored; only delivery failed. Say which.
            payload["delivery"] = {"status": "failed", "error": str(exc)}
    return payload


@router.get("/{day}")
def read(day: Date, session: Session = Depends(db)) -> dict:
    row = brief_service.get(session, day)
    if row is None:
        raise HTTPException(status_code=404, detail="No brief for that day")
    return _serialise(row)


@router.get("/{day}/preview", response_class=None)
def preview(day: Date, session: Session = Depends(db)) -> dict:
    """The rendered email, for checking it before it is sent."""
    row = brief_service.get(session, day)
    if row is None:
        raise HTTPException(status_code=404, detail="No brief for that day")
    return {"html": render_html(row, checkin_url=get_settings().checkin_url)}


@router.post("/{brief_id}/feedback", status_code=204)
def feedback(
    brief_id: int,
    rating: str = Query(pattern="^(useful|not_useful)$"),
    note: str | None = None,
    session: Session = Depends(db),
) -> None:
    """One tap. The ground-truth signal for prompt evaluation (plan 9.4)."""
    if brief_service.record_feedback(session, brief_id, rating, note) is None:
        raise HTTPException(status_code=404, detail="Unknown brief")
