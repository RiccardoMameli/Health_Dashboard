"""Supplement adherence.

The number has to answer "of the doses I was supposed to take, how many did
I?". It was answering "how many logs are there, capped at 100%", which is a
different question with a flattering answer.
"""

from datetime import date, timedelta

import pytest

from app.models import Supplement, SupplementLog, Workout
from app.services.ingest import ensure_day
from app.services.supplements import adherence_7d, missed_on

DAY = date(2026, 9, 24)


def _week(session):
    for i in range(7):
        ensure_day(session, DAY - timedelta(days=i))


def test_nothing_scheduled_is_not_zero_adherence(session):
    """0% says "took none of them". With nothing scheduled there is nothing
    to have taken, and the honest answer is no answer."""
    _week(session)
    session.commit()
    assert adherence_7d(session, DAY) is None


def test_unscheduled_logs_cannot_stand_in_for_missed_doses(session):
    """The regression. Vitamin D taken on 3 of 7 days is 42.9%. Creatine
    scheduled post-workout but logged on rest days, and a supplement since
    stopped, used to fill the gap and report 100%."""
    _week(session)
    daily = Supplement(name="Vitamin D", schedule="daily", is_active=True)
    creatine = Supplement(name="Creatine", schedule="post", is_active=True)
    stopped = Supplement(name="Old thing", schedule="daily", is_active=False)
    session.add_all([daily, creatine, stopped])
    session.commit()
    for i in range(7):
        day = DAY - timedelta(days=i)
        if i < 3:
            session.add(SupplementLog(date=day, supplement_id=daily.id, taken=True))
        session.add(SupplementLog(date=day, supplement_id=creatine.id, taken=True))
        session.add(SupplementLog(date=day, supplement_id=stopped.id, taken=True))
    session.commit()

    assert adherence_7d(session, DAY) == pytest.approx(3 / 7 * 100, abs=0.1)


def test_a_workout_day_supplement_counts_on_workout_days(session):
    """The same creatine does count on the days it was actually scheduled."""
    from datetime import UTC, datetime

    _week(session)
    creatine = Supplement(name="Creatine", schedule="post", is_active=True)
    session.add(creatine)
    session.commit()
    for i in (0, 2):
        day = DAY - timedelta(days=i)
        start = datetime(day.year, day.month, day.day, 18, tzinfo=UTC)
        session.add(Workout(date=day, start_at=start, source="hevy",
                            source_record_id=f"w{i}", title="Push", type="strength"))
        session.add(SupplementLog(date=day, supplement_id=creatine.id, taken=True))
    session.commit()

    assert adherence_7d(session, DAY) == pytest.approx(100.0)


def test_days_before_tracking_began_are_not_missed_doses(session):
    """The first morning of ticking used to read 14%: six untracked days
    counted as six days of everything missed. Before the first log nothing
    was being recorded, and an unrecorded dose is not a missed one."""
    _week(session)
    daily = Supplement(name="Vitamin D", schedule="daily", is_active=True)
    session.add(daily)
    session.flush()
    assert adherence_7d(session, DAY) is None  # never logged: no claim at all

    session.add(SupplementLog(date=DAY, supplement_id=daily.id, taken=True))
    session.commit()
    assert adherence_7d(session, DAY) == 100.0

    # Once tracking has begun, an unticked day is a miss like any other.
    assert adherence_7d(session, DAY + timedelta(days=1)) == 50.0


def test_nothing_is_missed_before_tracking_began(session):
    """The brief is told what was missed yesterday. With nothing ever logged
    it was told the whole stack, every morning."""
    _week(session)
    daily = Supplement(name="Vitamin D", schedule="daily", is_active=True)
    session.add(daily)
    session.commit()
    assert missed_on(session, DAY - timedelta(days=1)) == []

    session.add(SupplementLog(date=DAY, supplement_id=daily.id, taken=True))
    session.commit()
    assert missed_on(session, DAY - timedelta(days=1)) == []  # still before it began
    assert missed_on(session, DAY) == []                        # taken
    assert missed_on(session, DAY + timedelta(days=1)) == ["Vitamin D"]
