"""Read endpoints backing the Today, Training and Body screens."""

from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import db, require_token
from app.models import BodyMeasurement, Checkin, Workout
from app.schemas.common import BodyMeasurementOut, WorkoutOut
from app.services import brief as brief_service
from app.services.metrics_engine import compute_day
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
        "phase": "baseline",  # locked until 6 weeks of data exist (D8)
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
        "weight": {
            # EWMA and its slope, from the metrics engine. Raw daily weight is
            # never shown as a trend (plan 6.2), and there is exactly one
            # definition of "trend" in the system.
            "latest_kg": recent_weights[0].weight_kg if recent_weights else None,
            "ewma_kg": computed.weight_ewma_kg,
            "trend_kg_per_week": computed.weight_trend_kg_per_week,
            "observations": len(recent_weights),
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
            "debt_14d_min": computed.sleep_debt_14d_min,
        },
        "resting_hr": {
            "value": computed.resting_hr,
            "baseline": computed.rhr_baseline.median if computed.rhr_baseline else None,
            "deviation_bpm": computed.rhr_deviation_bpm,
        },
        "training": {"acwr": computed.acwr, "days_since_rest": computed.days_since_rest},
        "brief": (
            {
                "id": brief_row.id,
                "status": (brief_row.output or {}).get("status"),
                "headline": (brief_row.output or {}).get("headline"),
                "feedback_rating": brief_row.feedback_rating,
            }
            if brief_row is not None
            else None
        ),
    }


@router.get("/export")
def export_all(session: Session = Depends(db)) -> dict:
    """Full JSON export (plan 13). You should be able to get everything out."""
    from app.models import (
        ActivityDaily,
        HeartMetric,
        NutritionDaily,
        ProtocolChange,
        SleepSession,
        Supplement,
        SupplementLog,
    )

    def dump(model: type) -> list[dict]:
        rows = session.execute(select(model)).scalars()
        return [
            {
                c.name: (v.isoformat() if hasattr(v, "isoformat") else v)
                for c in model.__table__.columns
                if (v := getattr(row, c.name)) is not None
            }
            for row in rows
        ]

    return {
        "exported_at": utcnow().isoformat(),
        "checkins": dump(Checkin),
        "workouts": dump(Workout),
        "body_measurements": dump(BodyMeasurement),
        "sleep_sessions": dump(SleepSession),
        "heart_metrics": dump(HeartMetric),
        "activity_daily": dump(ActivityDaily),
        "nutrition_daily": dump(NutritionDaily),
        "supplements": dump(Supplement),
        "supplement_log": dump(SupplementLog),
        "protocol_changes": dump(ProtocolChange),
    }
