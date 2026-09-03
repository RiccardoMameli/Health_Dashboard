"""Timezone and day-boundary rules.

Plan 5.1 and R12. Two rules, both of which have to be right or every join in
the system is quietly wrong:

1. Everything is stored in UTC and rendered in Europe/London.
2. A sleep session belongs to the day it ENDS on, in local time.

The second rule is the one that breaks on BST/GMT transitions, so it is
unit-tested against both 2026 transition dates.
"""

from datetime import UTC, datetime, time, timedelta
from datetime import date as Date
from zoneinfo import ZoneInfo

from app.config import get_settings

UTC = UTC


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def to_utc(dt: datetime) -> datetime:
    """Normalise any datetime to timezone-aware UTC.

    A naive datetime is interpreted as local time, not as UTC. Guessing UTC
    for naive input is how off-by-one-hour errors get into the database.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt.astimezone(UTC)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(local_tz())


def local_date(dt: datetime) -> Date:
    """The calendar date this instant falls on, in local time."""
    return to_local(dt).date()


def sleep_day(end_at: datetime) -> Date:
    """The day a sleep session is attributed to: the local date it ends on.

    A session running 23:40 Tuesday to 07:10 Wednesday belongs to Wednesday,
    because that is the morning it produced.
    """
    return local_date(end_at)


def day_bounds_utc(day: Date) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day, expressed in UTC.

    On the spring-forward day this span is 23 hours and on the autumn
    fall-back day it is 25. Computing it as start + 24h would be wrong twice
    a year, so it is computed from the two local midnights instead.
    """
    tz = local_tz()
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def sleep_midpoint_minutes(start_at: datetime, end_at: datetime) -> float:
    """Sleep midpoint as minutes past local midnight, for circadian regularity.

    Returned on a continuous scale where a 00:30 midpoint reads as 1470
    (24h30) rather than 30, so the standard deviation of a set of midpoints
    is not destroyed by the wrap at midnight.
    """
    mid_utc = start_at + (end_at - start_at) / 2
    mid_local = to_local(mid_utc)
    minutes = mid_local.hour * 60 + mid_local.minute + mid_local.second / 60
    if minutes < 12 * 60:  # early-morning midpoint: treat as "late" the previous day
        minutes += 24 * 60
    return minutes


def utcnow() -> datetime:
    return datetime.now(UTC)
