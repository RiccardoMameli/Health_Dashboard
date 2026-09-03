"""Unit tests for the pure metrics engine (plan 6.1, 6.2).

Every metric is a pure function, so every one of these runs on plain values
with no database. The tests that matter most are the ones asserting that a
null stays a null: silent zero-filling is the failure mode that would make
every downstream number quietly wrong.
"""

from datetime import date, timedelta

import pytest

from app.metrics.baselines import (
    STATUS_ESTABLISHING,
    STATUS_OK,
    STATUS_POTENTIALLY_BIASED,
    Baseline,
    deviation,
    relative_deviation,
    rolling_baseline,
    sleep_baseline,
    wear_nights_ok,
    z_score,
)
from app.metrics.derived import (
    acute_load,
    acwr,
    acwr_penalty,
    chronic_load,
    daily_load,
    data_completeness_pct,
    protein_g_per_kg,
    session_load,
    sleep_debt,
    sleep_midpoint_variance,
    volume_progression_slope,
    weight_ewma_series,
    weight_trend_kg_per_week,
)

# ── baselines ────────────────────────────────────────────────────────────


def test_baseline_withheld_below_fourteen_observations():
    base = rolling_baseline([420.0] * 13)
    assert base.median is None
    assert base.n == 13
    assert base.status == STATUS_ESTABLISHING
    assert base.reportable is False


def test_baseline_reported_at_fourteen_observations():
    base = rolling_baseline([400.0] * 7 + [440.0] * 7)
    assert base.status == STATUS_OK
    assert base.median == 420.0
    assert base.n == 14


def test_nulls_are_dropped_never_zero_filled():
    """The whole invariant in one assertion: a missing night is not a 0."""
    values = [420.0] * 14 + [None] * 10
    base = rolling_baseline(values)
    assert base.n == 14
    assert base.median == 420.0  # would be ~0 if None became 0


def test_sleep_baseline_flags_wear_bias():
    # 14 nights worn, then a run where only three nights in seven produced data.
    values = [420.0] * 14 + [None, 430.0, None, None, 410.0, None, 400.0]
    base = sleep_baseline(values)
    assert base.status == STATUS_POTENTIALLY_BIASED
    assert base.median is not None  # flagged, not suppressed


def test_sleep_baseline_clean_when_watch_worn():
    base = sleep_baseline([420.0] * 20)
    assert base.status == STATUS_OK


def test_sleep_baseline_respects_explicit_wear_flags():
    """A night can be slept without being measured — no_watch says so."""
    values = [420.0] * 20
    worn = [True] * 13 + [False] * 7
    assert sleep_baseline(values, worn=worn).status == STATUS_POTENTIALLY_BIASED


def test_wear_guard_cannot_fail_on_a_short_history():
    assert wear_nights_ok([True, False, False]) is True


def test_deviation_propagates_none():
    base = rolling_baseline([52.0] * 14)
    assert deviation(58.0, base) == 6.0
    assert deviation(None, base) is None
    assert deviation(58.0, Baseline(None, None, 3, STATUS_ESTABLISHING)) is None


def test_relative_deviation_is_a_fraction():
    base = rolling_baseline([50.0] * 14)
    assert relative_deviation(40.0, base) == pytest.approx(-0.2)


def test_z_score_floor_stops_a_tight_window_exploding():
    base = rolling_baseline([52.0] * 13 + [52.5])
    # SD here is tiny; without the floor this z would be enormous.
    assert z_score(58.0, base, sd_floor=2.0) == pytest.approx(3.0, abs=0.05)


# ── sleep ────────────────────────────────────────────────────────────────


def test_sleep_debt_floors_each_night_at_zero():
    debt, nights = sleep_debt([400.0, 500.0, 300.0], target_min=450.0)
    assert debt == 200.0  # 50 + 0 + 150, the long night does not pay off the short
    assert nights == 3


def test_sleep_debt_skips_unmeasured_nights():
    debt, nights = sleep_debt([400.0, None, None], target_min=450.0)
    assert debt == 50.0  # an unknown night is not a full night of debt
    assert nights == 1


def test_sleep_midpoint_variance_needs_enough_nights():
    assert sleep_midpoint_variance([1500.0] * 4) is None
    assert sleep_midpoint_variance([1500.0, 1500.0, 1500.0, 1500.0, 1560.0]) == pytest.approx(
        26.83, abs=0.01
    )


# ── training load ────────────────────────────────────────────────────────


def test_session_load_prefers_duration_times_rpe():
    assert session_load(duration_min=60.0, rpe=8.0, volume_kg=9840.0) == 480.0


def test_session_load_falls_back_to_volume_without_rpe():
    assert session_load(duration_min=None, rpe=None, volume_kg=9840.0) == pytest.approx(98.4)


def test_session_load_is_none_when_unquantifiable():
    assert session_load(duration_min=60.0, rpe=None, volume_kg=None) is None


def test_rest_day_is_a_real_zero():
    assert daily_load([]) == 0.0


def test_acute_and_chronic_load():
    loads = [10.0] * 28
    assert acute_load(loads) == 70.0
    assert chronic_load(loads) == 70.0
    assert acwr(loads) == pytest.approx(1.0)


def test_acwr_detects_a_spike():
    loads = [10.0] * 21 + [20.0] * 7
    assert acwr(loads) == pytest.approx(1.6)


def test_acwr_withheld_without_history():
    assert acwr([10.0] * 20) is None


def test_acwr_withheld_when_chronic_is_zero():
    assert acwr([0.0] * 28) is None


def test_acwr_penalty_is_one_sided_and_ramped():
    assert acwr_penalty(0.6) == 0.0  # a light week is not a readiness problem
    assert acwr_penalty(1.3) == 0.0
    assert acwr_penalty(1.55) == pytest.approx(0.5)
    assert acwr_penalty(2.4) == 1.0
    assert acwr_penalty(None) == 0.0


# ── body ─────────────────────────────────────────────────────────────────


def test_weight_ewma_smooths_at_alpha_point_one():
    series = weight_ewma_series(
        [(date(2026, 9, 1), 86.0), (date(2026, 9, 2), 85.0), (date(2026, 9, 3), 84.0)]
    )
    assert [round(v, 3) for _, v in series] == [86.0, 85.9, 85.71]


def test_weight_ewma_sorts_by_date():
    series = weight_ewma_series([(date(2026, 9, 3), 84.0), (date(2026, 9, 1), 86.0)])
    assert series[0][0] == date(2026, 9, 1)


def test_weight_trend_is_kg_per_week():
    ewma = [(date(2026, 9, 1) + timedelta(days=i), 85.0 - 0.05 * i) for i in range(14)]
    assert weight_trend_kg_per_week(ewma) == pytest.approx(-0.35)


def test_weight_trend_withheld_on_thin_data():
    ewma = [(date(2026, 9, 1), 85.0), (date(2026, 9, 8), 84.5)]
    assert weight_trend_kg_per_week(ewma) is None


def test_protein_per_kg_is_null_without_macros():
    assert protein_g_per_kg(None, 84.2) is None
    assert protein_g_per_kg(160.0, None) is None
    assert protein_g_per_kg(160.0, 80.0) == pytest.approx(2.0)


# ── completeness and progression ─────────────────────────────────────────


def test_data_completeness_counts_expected_fields_only():
    present = {
        "sleep_duration_min": True,
        "sleep_efficiency_pct": True,
        "resting_hr": True,
        "steps": True,
        "weight_kg": True,
        "calories_kcal": True,
        "checkin_overall": False,
    }
    assert data_completeness_pct(present) == pytest.approx(85.71, abs=0.01)


def test_unknown_field_counts_as_missing():
    assert data_completeness_pct({}) == 0.0


def test_volume_progression_drops_unobserved_weeks():
    # Not training a lift is not the same as failing to progress it.
    assert volume_progression_slope([1000.0, None, 1200.0, 1400.0]) == pytest.approx(
        128.57, abs=0.01
    )
    assert volume_progression_slope([1000.0, None, None]) is None


def test_acwr_withheld_when_the_chronic_window_is_nearly_empty():
    """Four sessions in the last week of an empty month is not a 4.0 spike —
    it is a person who has just started training."""
    loads = [0.0] * 24 + [480.0] * 4
    assert acwr(loads) is None

    # Once training is regular, the ratio means something again.
    regular = [480.0 if day % 2 else 0.0 for day in range(28)]
    assert acwr(regular) is not None
