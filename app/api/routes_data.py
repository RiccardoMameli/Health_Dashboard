"""Read endpoints backing the Today, Training and Body screens."""

from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import db, require_token
from app.config import get_settings
from app.models import ActivityDaily, BodyMeasurement, Checkin, HeartMetric, Workout
from app.schemas.common import BodyMeasurementOut, WorkoutOut
from app.services import brief as brief_service
from app.services.metrics_engine import _nights, compute_day
from app.services.timeutil import local_date, utcnow

router = APIRouter(tags=["data"], dependencies=[Depends(require_token)])


@router.get("/workouts", response_model=list[WorkoutOut])
def list_workouts(
    start: Date | None = None,
    end: Date | None = None,
    limit: int = 50,
    session: Session = Depends(db),
) -> list[Workout]:
    stmt = (
        select(Workout)
        .options(selectinload(Workout.sets))
        .order_by(Workout.start_at.desc())
        .limit(min(limit, 200))
    )
    if start:
        stmt = stmt.where(Workout.date >= start)
    if end:
        stmt = stmt.where(Workout.date <= end)
    return list(session.execute(stmt).scalars())


@router.get("/body", response_model=list[BodyMeasurementOut])
def list_body(days: int = 90, session: Session = Depends(db)) -> list[BodyMeasurement]:
    start = local_date(utcnow()) - timedelta(days=days)
    return list(
        session.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.date >= start)
            .order_by(BodyMeasurement.date)
        ).scalars()
    )


#: Days drawn in the Today screen's sleep and resting-HR tiles.
TILE_DAYS = 7


def _latest_source(rows) -> str | None:
    """Where the most recent of these rows came from, so a tile names its
    real source rather than one written into the markup."""
    latest = max(rows, key=lambda r: r.date, default=None)
    return latest.source if latest is not None else None


@router.get("/today")
def today(session: Session = Depends(db)) -> dict:
    """The Today screen payload (plan 10.1).

    Readiness comes from the metrics engine and is None whenever the day is
    too sparse to score — the screen renders that refusal rather than
    substituting a number.
    """
    day = local_date(utcnow())
    computed = compute_day(session, day)
    brief_row = brief_service.get(session, day)

    last_workout = session.execute(
        select(Workout).order_by(Workout.start_at.desc()).limit(1)
    ).scalar_one_or_none()

    # A week of the two nightly tiles, oldest first, None where nothing was
    # recorded. The screen used to receive none of this and drew every tile
    # as "no data" whatever the database held — a placeholder from before
    # there was any data, which outlived the data arriving. `_nights` is the
    # engine's own definition of "the night" (the longest session on a date),
    # used here so the tile and the score can never disagree about it.
    week = [day - timedelta(days=offset) for offset in range(TILE_DAYS - 1, -1, -1)]
    nights = _nights(session, week[0], day)
    hearts = {
        row.date: row
        for row in session.execute(
            select(HeartMetric).where(HeartMetric.date >= week[0], HeartMetric.date <= day)
        ).scalars()
    }

    # Steps belong to the daytime, and at 07:00 today's count is a fraction of
    # a day — so the tile shows the seven completed days ending yesterday.
    step_days = [day - timedelta(days=offset) for offset in range(TILE_DAYS, 0, -1)]
    activity = {
        row.date: row
        for row in session.execute(
            select(ActivityDaily).where(
                ActivityDaily.date >= step_days[0], ActivityDaily.date <= step_days[-1]
            )
        ).scalars()
    }

    recent_weights = list(
        session.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.weight_kg.is_not(None))
            .order_by(BodyMeasurement.date.desc())
            .limit(14)
        ).scalars()
    )
    subjective = list(
        session.execute(
            select(Checkin).where(Checkin.date >= day - timedelta(days=29)).order_by(Checkin.date)
        ).scalars()
    )

    return {
        "date": day.isoformat(),
        # From config, not a literal: BRIEF_PHASE is the single source of truth
        # and promotion out of baseline is a deliberate act (D8), so a hard-coded
        # "baseline" here would keep saying so after the config had moved on.
        "phase": get_settings().brief_phase,
        "checkin_submitted": session.get(Checkin, day) is not None,
        "last_workout": (
            {
                "date": last_workout.date.isoformat(),
                "title": last_workout.title,
                "volume_kg": last_workout.total_volume_kg,
                "duration_min": last_workout.duration_min,
            }
            if last_workout
            else None
        ),
        "activity": {
            "last_7": [
                {"date": d.isoformat(),
                 "steps": activity[d].steps if d in activity else None}
                for d in step_days
            ],
            "source": _latest_source(a for a in activity.values() if a.steps is not None),
        },
        "weight": {
            # EWMA and its slope, from the metrics engine. Raw daily weight is
            # never shown as a trend (plan 6.2), and there is exactly one
            # definition of "trend" in the system.
            "latest_kg": recent_weights[0].weight_kg if recent_weights else None,
            "ewma_kg": computed.weight_ewma_kg,
            "trend_kg_per_week": computed.weight_trend_kg_per_week,
            "observations": len(recent_weights),
            # The smoothed series the engine computed, not the raw weigh-ins.
            "ewma_series": [
                {"date": d.isoformat(), "kg": round(kg, 2)}
                for d, kg in computed.weight_ewma_series
            ],
            "source": recent_weights[0].source if recent_weights else None,
        },
        "subjective_30d": [
            {"date": c.date.isoformat(), "overall": c.overall_1_10} for c in subjective
        ],
        "readiness": (computed.readiness.as_dict()["score"] if computed.readiness else None),
        "readiness_detail": computed.readiness.as_dict() if computed.readiness else None,
        "data_completeness_pct": round(computed.data_completeness_pct, 1),
        "sleep": {
            "duration_min": computed.sleep_duration_min,
            "baseline_min": (computed.sleep_baseline.median if computed.sleep_baseline else None),
            # How many nights the baseline stands on and how far back they
            # reach. With the window widened to 180 days a comparison can rest
            # on nights from months ago, and a screen that shows the deviation
            # without showing its age is overstating what it knows.
            "baseline_nights": (computed.sleep_baseline.n if computed.sleep_baseline else None),
            "baseline_span_days": (
                computed.sleep_baseline.span_days if computed.sleep_baseline else None
            ),
            "debt_14d_min": computed.sleep_debt_14d_min,
            "last_7": [
                {"date": d.isoformat(),
                 "duration_min": nights[d].duration_min if d in nights else None}
                for d in week
            ],
            "source": _latest_source(nights.values()),
            # For the Sleep trend tile: the target the debt is measured
            # against (one setting, so the tile and the score agree), the
            # median bedtime, and how much the sleep midpoint wanders.
            "target_min": get_settings().sleep_target_min,
            "typical_bedtime_min": computed.typical_bedtime_min,
            "midpoint_variance_min": computed.sleep_midpoint_variance_min,
        },
        "resting_hr": {
            "value": computed.resting_hr,
            "baseline": computed.rhr_baseline.median if computed.rhr_baseline else None,
            "deviation_bpm": computed.rhr_deviation_bpm,
            "last_7": [
                {"date": d.isoformat(),
                 "bpm": hearts[d].resting_hr if d in hearts else None}
                for d in week
            ],
            "source": _latest_source(h for h in hearts.values() if h.resting_hr is not None),
        },
        "training": {
            "acwr": computed.acwr,
            "load_quality": computed.load_quality,
            "load_quality_note": computed.load_quality_note,
            "days_since_rest": computed.days_since_rest,
            "muscle_recovery": [m.as_dict() for m in computed.muscle_recovery],
            "muscle_recovery_status": computed.muscle_recovery_status,
        },
        "brief": (
            {
                "id": brief_row.id,
                "status": (brief_row.output or {}).get("status"),
                # The fields the Today card renders. It used to receive only
                # the headline, so "why" and "do today" were always empty and
                # the card filled the space with placeholder text.
                "headline": (brief_row.output or {}).get("headline"),
                "why": (brief_row.output or {}).get("why") or [],
                "do_today": (brief_row.output or {}).get("do_today") or [],
                "training_recommendation": (brief_row.output or {}).get(
                    "training_recommendation"
                ),
                "data_caveats": (brief_row.output or {}).get("data_caveats") or [],
                "feedback_rating": brief_row.feedback_rating,
            }
            if brief_row is not None
            else None
        ),
    }


#: Tables deliberately left out of the export. Only one, and for a reason:
#: `oauth_tokens` holds live Withings (and later Google) refresh tokens, and an
#: export is a file that gets emailed, uploaded to a model, handed to a GP.
EXPORT_EXCLUDED = frozenset({"oauth_tokens"})


@router.get("/export")
def export_all(session: Session = Depends(db)) -> dict:
    """Full JSON export (plan 13). You should be able to get everything out.

    Every table except `EXPORT_EXCLUDED`, discovered from the schema rather than
    listed by hand. It used to be an allow-list of ten tables, and every table
    added after it was written quietly fell out of it — including
    `workout_sets`, which is every set, rep and weight from Hevy and the bulk
    of the training record. A deny-list fails the other way: a new table is
    exported unless someone decides it should not be.

    Nulls are kept. Dropping them made "not measured" indistinguishable from
    "no such field", which is exactly the distinction this project exists to
    preserve.
    """
    from app.models import Base

    def plain(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    tables = {}
    for table in Base.metadata.sorted_tables:
        if table.name in EXPORT_EXCLUDED:
            continue
        rows = session.execute(select(table)).mappings()
        tables[table.name] = [{k: plain(v) for k, v in row.items()} for row in rows]

    return {"exported_at": utcnow().isoformat(), "excluded": sorted(EXPORT_EXCLUDED), **tables}
