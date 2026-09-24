"""Supplement adherence (plan 8.2).

Extracted from the route so the metrics engine and the brief can ask the same
question and get the same answer. Two definitions of adherence would drift.
"""

from datetime import date as Date
from datetime import timedelta

from sqlalchemy import select
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


def adherence_7d(session: Session, day: Date) -> float | None:
    """Scheduled doses taken over the trailing week, as a percentage.

    None when nothing was scheduled. There is no adherence to report against
    an empty schedule, and 0% says "took none of them", which is a different
    and alarming claim.

    Only logs that answer a *scheduled* dose count. This used to count every
    taken log in the window against the scheduled total, so creatine logged on
    rest days — scheduled post-workout, taken daily — or a supplement since
    stopped would fill in for doses that were actually missed. Measured: a
    stack taken on three of seven days reported 100%. The cap at 100% that
    was there hid the overcount rather than preventing it.
    """
    start = day - timedelta(days=6)
    active = list(
        session.execute(select(Supplement).where(Supplement.is_active.is_(True))).scalars()
    )
    if not active:
        return None

    workout_days = _workout_days(session, start, day)
    expected = {
        (start + timedelta(days=offset), s.id)
        for offset in range(7)
        for s in scheduled_on(active, start + timedelta(days=offset), workout_days)
    }
    if not expected:
        return None

    taken = set(
        session.execute(
            select(SupplementLog.date, SupplementLog.supplement_id).where(
                SupplementLog.date >= start,
                SupplementLog.date <= day,
                SupplementLog.taken.is_(True),
            )
        ).tuples()
    )
    return round(len(expected & taken) / len(expected) * 100, 1)


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
