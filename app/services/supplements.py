"""Supplement adherence (plan 8.2).

Extracted from the route so the metrics engine and the brief can ask the same
question and get the same answer. Two definitions of adherence would drift.
"""

from datetime import date as Date
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Supplement, SupplementLog, Workout

#: Schedules that only apply on days a workout was actually logged.
WORKOUT_ONLY_SCHEDULES = {"workout_day", "pre", "post"}


def _workout_days(session: Session, start: Date, end: Date) -> set[Date]:
    return set(
        session.execute(
            select(Workout.date).where(Workout.date >= start, Workout.date <= end)
        ).scalars()
    )


def scheduled_on(
    supplements: list[Supplement], day: Date, workout_days: set[Date]
) -> list[Supplement]:
    """The stack expected on one day. Workout-day items need a logged workout."""
    return [
        s for s in supplements if s.schedule not in WORKOUT_ONLY_SCHEDULES or day in workout_days
    ]


def adherence_7d(session: Session, day: Date) -> float:
    """Taken / expected over the trailing week, as a percentage."""
    start = day - timedelta(days=6)
    active = list(
        session.execute(select(Supplement).where(Supplement.is_active.is_(True))).scalars()
    )
    if not active:
        return 0.0

    workout_days = _workout_days(session, start, day)
    expected = sum(
        len(scheduled_on(active, start + timedelta(days=offset), workout_days))
        for offset in range(7)
    )
    if expected == 0:
        return 0.0

    taken = session.execute(
        select(func.count(SupplementLog.supplement_id)).where(
            SupplementLog.date >= start,
            SupplementLog.date <= day,
            SupplementLog.taken.is_(True),
        )
    ).scalar_one()
    return round(min(taken / expected, 1.0) * 100, 1)


def missed_on(session: Session, day: Date) -> list[str]:
    """Names of supplements that were scheduled on a day and not logged.

    Only meaningful for a day that is over: an empty checklist this morning
    means "not yet", not "missed".
    """
    active = list(
        session.execute(
            select(Supplement).where(Supplement.is_active.is_(True)).order_by(Supplement.name)
        ).scalars()
    )
    if not active:
        return []

    scheduled = scheduled_on(active, day, _workout_days(session, day, day))
    taken_ids = set(
        session.execute(
            select(SupplementLog.supplement_id).where(
                SupplementLog.date == day, SupplementLog.taken.is_(True)
            )
        ).scalars()
    )
    return [s.name for s in scheduled if s.id not in taken_ids]
