"""Read endpoints backing the Today, Training and Body screens."""

from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import db, require_token
from app.models import BodyMeasurement, Checkin, Workout
from app.schemas.common import BodyMeasurementOut, WorkoutOut
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
    """The minimal Today screen payload for Phase 1.

    Deliberately thin. Readiness, the brief and the metrics engine land in
    Phase 2; nothing here fabricates a number it cannot compute yet.
    """
    day = local_date(utcnow())

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
    weight_trend = None
    if len(recent_weights) >= 8:
        newest = sum(w.weight_kg for w in recent_weights[:7]) / 7
        oldest = sum(w.weight_kg for w in recent_weights[7:14]) / len(recent_weights[7:14])
        weight_trend = round(newest - oldest, 2)

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
        "weight": (
            {
                "latest_kg": recent_weights[0].weight_kg if recent_weights else None,
                "trend_kg_per_week": weight_trend,
                "observations": len(recent_weights),
            }
        ),
        "subjective_30d": [
            {"date": c.date.isoformat(), "overall": c.overall_1_10} for c in subjective
        ],
        "readiness": None,
        "readiness_note": "Readiness lands in Phase 2 with the metrics engine.",
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
