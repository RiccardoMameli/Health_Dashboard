"""Plan R12: timezone and sleep-boundary bugs corrupt every join in the system.

These tests exist because the failure mode is silent. A sleep session filed
against the wrong day does not raise anything; it just quietly decorrelates
sleep from how you felt the next morning.
"""

from datetime import UTC, date, datetime, timedelta

from app.services.timeutil import (
    day_bounds_utc,
    local_date,
    sleep_day,
    sleep_midpoint_minutes,
    to_utc,
)


def test_sleep_belongs_to_the_day_it_ends():
    start = datetime(2026, 3, 10, 23, 40, tzinfo=UTC)
    end = datetime(2026, 3, 11, 7, 10, tzinfo=UTC)
    assert sleep_day(end) == date(2026, 3, 11)
    assert local_date(start) == date(2026, 3, 10)


def test_naive_datetime_is_interpreted_as_local_not_utc():
    # 00:30 local on a BST date is 23:30 UTC the previous day.
    naive = datetime(2026, 7, 1, 0, 30)
    assert to_utc(naive) == datetime(2026, 6, 30, 23, 30, tzinfo=UTC)


def test_spring_forward_day_is_23_hours():
    # BST begins 29 March 2026 at 01:00 GMT.
    start, end = day_bounds_utc(date(2026, 3, 29))
    assert (end - start) == timedelta(hours=23)


def test_autumn_fall_back_day_is_25_hours():
    # GMT resumes 25 October 2026 at 02:00 BST.
    start, end = day_bounds_utc(date(2026, 10, 25))
    assert (end - start) == timedelta(hours=25)


def test_ordinary_day_is_24_hours():
    start, end = day_bounds_utc(date(2026, 9, 3))
    assert (end - start) == timedelta(hours=24)


def test_sleep_ending_just_after_local_midnight_belongs_to_the_new_day():
    # 00:20 BST on 2 September = 23:20 UTC on 1 September.
    end = datetime(2026, 9, 1, 23, 20, tzinfo=UTC)
    assert sleep_day(end) == date(2026, 9, 2)


def test_midpoint_does_not_wrap_at_midnight():
    """A 23:00-07:00 night has a 03:00 midpoint. Reported on a continuous
    scale as 27h, so its SD against a 02:00 night is one hour, not 23."""
    a = sleep_midpoint_minutes(
        datetime(2026, 9, 1, 22, 0, tzinfo=UTC), datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    )
    b = sleep_midpoint_minutes(
        datetime(2026, 9, 2, 21, 0, tzinfo=UTC), datetime(2026, 9, 3, 5, 0, tzinfo=UTC)
    )
    assert abs(a - b) == 60
    assert a > 24 * 60  # past midnight, expressed as >24h not <1h
