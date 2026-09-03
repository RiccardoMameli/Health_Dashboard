"""Unit tests for the readiness score (plan 6.3).

The refusals get as much coverage as the arithmetic. A score that appears on
a day the system could not see would be worse than no score at all, so
`insufficient_data` and the missing-component handling are tested first.
"""

import pytest

from app.metrics.readiness import (
    CONFIDENCE_FULL,
    CONFIDENCE_REDUCED,
    STATUS_AMBER,
    STATUS_GREEN,
    STATUS_INSUFFICIENT,
    STATUS_RED,
    ReadinessInput,
    ReadinessWeights,
    compute_readiness,
)

NEUTRAL = dict(
    sleep_duration_z=0.0,
    sleep_efficiency_z=0.0,
    rhr_deviation_z=0.0,
    sleep_debt_14d_min=0.0,
    acwr=1.0,
    subjective_z=0.0,
)


def test_no_score_below_the_completeness_floor():
    out = compute_readiness(ReadinessInput(data_completeness_pct=59.9, **NEUTRAL))
    assert out.score is None
    assert out.status == STATUS_INSUFFICIENT
    assert out.components == []
    assert "below" in out.note


def test_score_is_produced_at_the_floor():
    out = compute_readiness(ReadinessInput(data_completeness_pct=60.0, **NEUTRAL))
    assert out.score is not None


def test_a_neutral_day_scores_one_hundred():
    out = compute_readiness(ReadinessInput(data_completeness_pct=100.0, **NEUTRAL))
    assert out.score == pytest.approx(100.0)
    assert out.status == STATUS_GREEN


def test_hrv_absence_reduces_confidence_and_redistributes_its_weight():
    out = compute_readiness(ReadinessInput(data_completeness_pct=100.0, **NEUTRAL))
    assert out.confidence == CONFIDENCE_REDUCED
    assert "HRV" in out.note

    # w4 goes to w1-w3 in proportion, so a bad night now costs more, not less.
    weights = ReadinessWeights()
    bad_sleep = dict(NEUTRAL, sleep_duration_z=-1.0)
    out = compute_readiness(ReadinessInput(data_completeness_pct=100.0, **bad_sleep))
    receivers = weights.sleep_duration + weights.sleep_efficiency + weights.rhr_deviation
    expected = weights.sleep_duration * (1 + weights.hrv_deviation / receivers)
    assert out.score == pytest.approx(100.0 - expected)


def test_hrv_present_keeps_full_confidence():
    out = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, hrv_deviation_z=0.0, **NEUTRAL)
    )
    assert out.confidence == CONFIDENCE_FULL
    assert out.note is None
    assert out.score == pytest.approx(100.0)


def test_a_missing_component_contributes_nothing_and_says_so():
    out = compute_readiness(
        ReadinessInput(
            data_completeness_pct=100.0,
            sleep_duration_z=-1.0,
            rhr_deviation_z=None,
            sleep_debt_14d_min=None,
            acwr=None,
        )
    )
    by_factor = {c.factor: c for c in out.components}
    assert by_factor["rhr_deviation"].available is False
    assert by_factor["rhr_deviation"].impact == 0.0
    assert by_factor["sleep_debt_14d"].available is False
    # Every factor is always present in the breakdown, available or not.
    assert len(out.components) == 7


def test_elevated_resting_hr_lowers_the_score():
    out = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, rhr_deviation_z=2.0))
    )
    assert out.score < 100.0
    assert out.top_contributors()[0].factor == "rhr_deviation"


def test_sleep_debt_penalty_saturates():
    weights = ReadinessWeights()
    huge = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, sleep_debt_14d_min=100_000.0))
    )
    debt_impact = next(c.impact for c in huge.components if c.factor == "sleep_debt_14d")
    assert debt_impact == pytest.approx(-weights.sleep_debt)


def test_z_scores_are_clamped_so_one_freak_night_cannot_dominate():
    at_clamp = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, sleep_duration_z=-2.0))
    )
    beyond = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, sleep_duration_z=-50.0))
    )
    assert at_clamp.score == pytest.approx(beyond.score)


def test_score_stays_inside_zero_to_one_hundred():
    awful = compute_readiness(
        ReadinessInput(
            data_completeness_pct=100.0,
            sleep_duration_z=-3.0,
            sleep_efficiency_z=-3.0,
            rhr_deviation_z=3.0,
            sleep_debt_14d_min=5000.0,
            acwr=3.0,
            subjective_z=-3.0,
        )
    )
    # Every penalty at once lands near the floor but keeps some resolution:
    # the scale is not so steep that two bad readings exhaust it.
    assert 0.0 <= awful.score < 15.0
    assert awful.status == STATUS_RED

    # And the floor itself holds when the weights are turned up.
    floored = compute_readiness(
        ReadinessInput(
            data_completeness_pct=100.0,
            sleep_duration_z=-3.0,
            sleep_efficiency_z=-3.0,
            rhr_deviation_z=3.0,
            sleep_debt_14d_min=5000.0,
            acwr=3.0,
            subjective_z=-3.0,
        ),
        ReadinessWeights(sleep_duration=40.0, rhr_deviation=40.0, hrv_deviation=0.0),
    )
    assert floored.score == 0.0

    great = compute_readiness(
        ReadinessInput(
            data_completeness_pct=100.0,
            sleep_duration_z=3.0,
            sleep_efficiency_z=3.0,
            rhr_deviation_z=-3.0,
            sleep_debt_14d_min=0.0,
            acwr=1.0,
            subjective_z=3.0,
        )
    )
    assert great.score == 100.0


def test_top_contributors_are_ranked_and_exclude_neutral_factors():
    out = compute_readiness(
        ReadinessInput(
            data_completeness_pct=100.0,
            sleep_duration_z=-0.5,
            sleep_efficiency_z=0.0,
            rhr_deviation_z=2.0,
            sleep_debt_14d_min=420.0,
            acwr=1.0,
            subjective_z=0.0,
        )
    )
    factors = [c.factor for c in out.top_contributors()]
    assert factors == ["rhr_deviation", "sleep_debt_14d"]
    assert "sleep_efficiency" not in factors  # neutral is not a contributor


def test_bands_map_score_to_status():
    """A day has to be genuinely off baseline before it stops being green."""

    def status_for(**overrides: float) -> str:
        return compute_readiness(
            ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, **overrides))
        ).status

    assert status_for() == STATUS_GREEN
    assert status_for(sleep_duration_z=-0.5, rhr_deviation_z=0.5) == STATUS_GREEN
    # One SD short on sleep, one SD up on resting HR, half the debt ceiling.
    assert status_for(sleep_duration_z=-1.0, rhr_deviation_z=1.0, sleep_debt_14d_min=210.0) == (
        STATUS_AMBER
    )
    assert status_for(sleep_duration_z=-2.0, rhr_deviation_z=2.0, sleep_debt_14d_min=420.0) == (
        STATUS_RED
    )


def test_weights_are_injectable_not_hardcoded():
    doubled = ReadinessWeights(sleep_duration=12.0, hrv_deviation=0.0)
    out = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, sleep_duration_z=-1.0)),
        doubled,
    )
    assert out.score == pytest.approx(88.0)


def test_as_dict_is_serialisable_and_carries_the_breakdown():
    out = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, rhr_deviation_z=2.0))
    )
    payload = out.as_dict()
    assert payload["status"] in {STATUS_GREEN, STATUS_AMBER, STATUS_RED}
    assert len(payload["components"]) == 7
    assert payload["top_contributors"][0]["factor"] == "rhr_deviation"
    assert isinstance(payload["score"], float)
