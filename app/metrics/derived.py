"""Derived metrics (plan 6.2).

Pure functions over plain values. Each one is unit-tested against fixtures.

The distinction that matters throughout: **an absent measurement is None; an
absent event is zero.** A night the watch was not worn contributes no sleep
debt and no baseline observation. A day with no training contributes a real
zero to training load, because not training is a fact about the day rather
than a gap in the record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date as Date
from statistics import stdev as _stdev

#: Sleep debt at which the readiness penalty saturates (plan 6.3, w5).
SLEEP_DEBT_FULL_PENALTY_MIN = 420.0

#: Sleep midpoint variance needs a few nights before its SD means anything.
MIN_MIDPOINT_OBSERVATIONS = 5

#: Strength volume converted to load units when no RPE was recorded. Volume-kg
#: and duration x RPE are not the same quantity; this constant makes them
#: roughly commensurate so one acute-load sum is possible. It is a heuristic
#: feeding a heuristic (ACWR), and is documented as such in plan 6.2.
VOLUME_KG_PER_LOAD_UNIT = 100.0

ACUTE_WINDOW_DAYS = 7
CHRONIC_WINDOW_DAYS = 28

#: ACWR is meaningless until the chronic window is mostly filled.
MIN_DAYS_FOR_ACWR = 21

#: ...and until there is actually training in it. Four sessions crammed into
#: the last week of an otherwise empty month produce a ratio of 4.0, which is
#: arithmetically correct and tells you nothing: there is no chronic load to
#: compare against yet. Two sessions a week over the window is the floor for
#: the ratio meaning anything.
MIN_TRAINING_DAYS_FOR_ACWR = 8

#: ACWR below this is unpenalised; the penalty ramps to 1.0 at the ceiling.
ACWR_PENALTY_FLOOR = 1.3
ACWR_PENALTY_CEILING = 1.8

#: Fields the system expects to see for a complete day. Fields that are known
#: to be unavailable (protein under MyFitnessPal, O2; HRV until verified on a
#: real device) are excluded from the denominator rather than counted missing
#: — otherwise completeness is permanently docked for a gap already known and
#: reported, and the brief's confidence signal stops meaning anything.
EXPECTED_DAILY_FIELDS = (
    "sleep_duration_min",
    "sleep_efficiency_pct",
    "resting_hr",
    "steps",
    "weight_kg",
    "calories_kcal",
    "checkin_overall",
)

#: Added to the expected set only once HRV is confirmed available (plan 3.3).
HRV_FIELD = "hrv_ms"


def sleep_debt(
    durations_min: Sequence[float | None],
    *,
    target_min: float,
) -> tuple[float, int]:
    """Accumulated shortfall against the sleep target (plan 6.2).

    Floored at zero per night, so a long night does not pay off a short one.
    Nights with no measurement are skipped entirely — they are unknown, not
    debt-free. Returns the debt and the number of nights it stands on, so a
    consumer can say "265 minutes over 9 observed nights" rather than
    implying a full fortnight of evidence.
    """
    observed = [d for d in durations_min if d is not None]
    debt = sum(max(0.0, target_min - d) for d in observed)
    return debt, len(observed)


def sleep_midpoint_variance(
    midpoints_min: Sequence[float | None],
    *,
    min_observations: int = MIN_MIDPOINT_OBSERVATIONS,
) -> float | None:
    """SD of sleep midpoint — circadian regularity (plan 6.2).

    Midpoints must already be on the continuous scale produced by
    `app.services.timeutil.sleep_midpoint_minutes`, where a 00:30 midpoint
    reads as 1470 rather than 30. Feeding raw minutes-past-midnight here
    would make a perfectly regular sleeper look wildly erratic.
    """
    observed = [m for m in midpoints_min if m is not None]
    if len(observed) < min_observations:
        return None
    return _stdev(observed)


def session_load(
    *,
    duration_min: float | None,
    rpe: float | None,
    volume_kg: float | None = None,
    volume_kg_per_load_unit: float = VOLUME_KG_PER_LOAD_UNIT,
) -> float | None:
    """Load for one session: duration x RPE, or volume-load as a fallback.

    Duration x RPE is the primary definition and applies to any modality.
    Volume-load is used only when RPE was not recorded, scaled into the same
    rough range. Returns None when the session supports neither — an
    unquantifiable session must not silently count as zero load.
    """
    if duration_min is not None and rpe is not None:
        return duration_min * rpe
    if volume_kg is not None and volume_kg_per_load_unit > 0:
        return volume_kg / volume_kg_per_load_unit
    return None


def daily_load(session_loads: Sequence[float | None]) -> float:
    """Total load for one day. No sessions is a genuine zero (a rest day)."""
    return sum(load for load in session_loads if load is not None)


def acute_load(daily_loads: Sequence[float], *, window: int = ACUTE_WINDOW_DAYS) -> float:
    """7-day rolling sum of daily load. `daily_loads` ends with today."""
    return float(sum(daily_loads[-window:]))


def chronic_load(daily_loads: Sequence[float], *, window: int = CHRONIC_WINDOW_DAYS) -> float:
    """28-day rolling average of *weekly* load, so it compares with acute."""
    return float(sum(daily_loads[-window:])) / (window / 7)


def acwr(
    daily_loads: Sequence[float],
    *,
    min_days: int = MIN_DAYS_FOR_ACWR,
    min_training_days: int = MIN_TRAINING_DAYS_FOR_ACWR,
) -> float | None:
    """Acute:chronic workload ratio (plan 6.2).

    None until there is enough history for the chronic window to mean
    anything, and None when chronic load is zero — a ratio against nothing is
    not an infinite spike, it is an unanswerable question. Reporting a
    spurious 4.0 to the brief would be worse than reporting nothing, because
    the brief would then have to explain it.
    """
    if len(daily_loads) < min_days:
        return None
    window = daily_loads[-CHRONIC_WINDOW_DAYS:]
    if sum(1 for load in window if load > 0) < min_training_days:
        return None
    chronic = chronic_load(daily_loads)
    if chronic <= 0:
        return None
    return acute_load(daily_loads) / chronic


def acwr_penalty(
    ratio: float | None,
    *,
    floor: float = ACWR_PENALTY_FLOOR,
    ceiling: float = ACWR_PENALTY_CEILING,
) -> float:
    """0.0 to 1.0, ramping between the floor and the ceiling.

    One-sided by design: a low ratio means a light week, which is not a
    readiness problem and must not be scored as one.
    """
    if ratio is None or ratio <= floor:
        return 0.0
    if ratio >= ceiling:
        return 1.0
    return (ratio - floor) / (ceiling - floor)


def weight_ewma_series(
    observations: Sequence[tuple[Date, float]],
    *,
    alpha: float = 0.1,
) -> list[tuple[Date, float]]:
    """Exponentially weighted weight series (plan 6.2, alpha = 0.1).

    Smoothing runs over observations in date order, not over calendar days —
    a missed weigh-in is not a data point and must not decay the average
    toward nothing. Raw daily weight is never shown as a trend.
    """
    out: list[tuple[Date, float]] = []
    current: float | None = None
    for day, kg in sorted(observations, key=lambda o: o[0]):
        current = kg if current is None else alpha * kg + (1 - alpha) * current
        out.append((day, current))
    return out


def weight_trend_kg_per_week(
    ewma: Sequence[tuple[Date, float]],
    *,
    window_days: int = 14,
    min_observations: int = 5,
    min_span_days: int = 7,
) -> float | None:
    """Least-squares slope of the smoothed series, in kg per week.

    Regressed against real dates rather than observation index, so a gap in
    weighing does not compress the timeline and exaggerate the slope.
    """
    if not ewma:
        return None
    points = sorted(ewma, key=lambda p: p[0])
    last_day = points[-1][0]
    window = [(d, kg) for d, kg in points if (last_day - d).days <= window_days]
    if len(window) < min_observations:
        return None
    span = (window[-1][0] - window[0][0]).days
    if span < min_span_days:
        return None

    xs = [float((d - window[0][0]).days) for d, _ in window]
    ys = [kg for _, kg in window]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope_per_day = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope_per_day /= denominator
    return slope_per_day * 7


def protein_g_per_kg(protein_g: float | None, weight_ewma_kg: float | None) -> float | None:
    """Protein relative to bodyweight. NULL under MyFitnessPal (O2)."""
    if protein_g is None or not weight_ewma_kg:
        return None
    return protein_g / weight_ewma_kg


def data_completeness_pct(
    present: Mapping[str, bool],
    *,
    expected: Sequence[str] = EXPECTED_DAILY_FIELDS,
) -> float:
    """Percentage of the expected fields that actually arrived.

    Drives brief confidence (plan 6.2) and the `insufficient_data` cutoff
    (plan 6.3). A field absent from `present` counts as missing.
    """
    if not expected:
        return 0.0
    got = sum(1 for field in expected if present.get(field, False))
    return 100.0 * got / len(expected)


def volume_progression_slope(
    weekly_volume_kg: Sequence[float | None],
    *,
    min_weeks: int = 3,
) -> float | None:
    """Slope of per-exercise weekly volume-load — is overload happening.

    Weeks with no observation of the exercise are dropped rather than read as
    zero volume: not training a lift is not the same as failing to progress
    it, and only one of those is a training signal.
    """
    points = [(i, v) for i, v in enumerate(weekly_volume_kg) if v is not None]
    if len(points) < min_weeks:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
