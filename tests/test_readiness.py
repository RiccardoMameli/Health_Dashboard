"""Unit tests for the readiness score.

The refusals get as much coverage as the arithmetic, and the first test is
the one that matters most: a day the system could not measure must not score
well. Under the previous deduction-only formula it scored *perfectly* — a
missing component contributed zero, which is what a component sitting exactly
on its baseline contributes, so the less was known the better the day looked.
"""

import pytest

from app.metrics.readiness import (
    CONFIDENCE_FULL,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_PARTIAL,
    CONFIDENCE_REDUCED,
    MIN_COVERAGE_PCT,
    NEUTRAL_SCORE,
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
    sleep_debt_nights=14,
    acwr=1.0,
    subjective_z=0.0,
)


def score_for(**overrides):
    """Completeness is passed but no longer gates anything; coverage does."""
    return compute_readiness(ReadinessInput(data_completeness_pct=100.0, **overrides))


# ── the refusal that matters most ───────────────────────────────────────────


def test_a_day_with_nothing_computable_is_refused_not_scored():
    """The regression this formula exists for. Five hours' sleep, 71%
    efficiency, resting HR eight over and a 3/10 self-rating scored 94 and
    green, because no baseline was established and six of seven components
    were silently treated as sitting on it."""
    out = score_for()
    assert out.score is None
    assert out.status == STATUS_INSUFFICIENT
    assert out.confidence == CONFIDENCE_INSUFFICIENT
    assert out.coverage_pct == 0.0


def test_an_unmeasured_component_is_not_the_same_as_an_average_one():
    """The precise fault: silence and 'exactly normal' must not be equal."""
    measured = score_for(**NEUTRAL)
    partial = score_for(sleep_duration_z=0.0)
    assert measured.score == pytest.approx(NEUTRAL_SCORE)
    assert partial.coverage_pct < measured.coverage_pct
    assert partial.confidence != measured.confidence


def test_field_completeness_no_longer_gates_the_score():
    """A field can be recorded and still contribute nothing, because a value
    with no established baseline has no deviation to score. Coverage answers
    the question completeness was being asked and could not."""
    out = compute_readiness(ReadinessInput(data_completeness_pct=0.0, **NEUTRAL))
    assert out.score is not None


# ── the scale ───────────────────────────────────────────────────────────────


def test_an_ordinary_day_sits_at_the_neutral_score_with_headroom_above_it():
    out = score_for(**NEUTRAL)
    assert out.score == pytest.approx(NEUTRAL_SCORE)
    assert out.status == STATUS_GREEN

    great = score_for(
        sleep_duration_z=3.0, sleep_efficiency_z=3.0, rhr_deviation_z=-3.0,
        hrv_deviation_z=3.0, sleep_debt_14d_min=0.0, acwr=1.0, subjective_z=3.0,
    )
    assert great.score > out.score, "a good day must beat an ordinary one"
    assert great.score <= 100.0


def test_the_worst_possible_day_lands_near_the_floor_without_hitting_it():
    awful = score_for(
        sleep_duration_z=-3.0, sleep_efficiency_z=-3.0, rhr_deviation_z=3.0,
        hrv_deviation_z=-3.0, sleep_debt_14d_min=5000.0, sleep_debt_nights=14, acwr=3.0, subjective_z=-3.0,
    )
    assert 0.0 <= awful.score < 15.0
    assert awful.status == STATUS_RED


def test_the_score_is_clamped_to_its_range_whatever_the_weights():
    floored = compute_readiness(
        ReadinessInput(
            data_completeness_pct=100.0, sleep_duration_z=-3.0, sleep_efficiency_z=-3.0,
            rhr_deviation_z=3.0, sleep_debt_14d_min=5000.0, sleep_debt_nights=14, acwr=3.0, subjective_z=-3.0,
        ),
        ReadinessWeights(sleep_duration=400.0, rhr_deviation=400.0, hrv_deviation=0.0),
    )
    assert floored.score == 0.0


def test_z_scores_are_clamped_so_one_freak_night_cannot_dominate():
    at_clamp = score_for(**dict(NEUTRAL, sleep_duration_z=-2.0))
    beyond = score_for(**dict(NEUTRAL, sleep_duration_z=-50.0))
    assert at_clamp.score == pytest.approx(beyond.score)


def test_sleep_debt_penalty_saturates():
    weights = ReadinessWeights()
    huge = score_for(**dict(NEUTRAL, sleep_debt_14d_min=100_000.0, sleep_debt_nights=14))
    debt = next(c.impact for c in huge.components if c.factor == "sleep_debt_14d")
    available = (weights.sleep_duration + weights.sleep_efficiency + weights.rhr_deviation
                 + weights.sleep_debt + weights.acwr + weights.subjective)
    assert debt == pytest.approx(-45.0 * weights.sleep_debt / available)


def test_elevated_resting_hr_lowers_the_score():
    out = score_for(**dict(NEUTRAL, rhr_deviation_z=2.0))
    assert out.score < NEUTRAL_SCORE
    assert out.top_contributors()[0].factor == "rhr_deviation"


# ── partial days stay useful ────────────────────────────────────────────────


def test_a_sleep_only_day_still_gets_a_score_and_says_what_it_rests_on():
    """The owner does not wear a watch every night and will not use a
    dashboard that goes blank when he forgets. A thin answer that admits it
    is thin beats no answer."""
    out = score_for(sleep_duration_z=0.6, sleep_efficiency_z=0.8, sleep_debt_14d_min=0.0, sleep_debt_nights=14)
    assert out.score is not None
    assert out.score > NEUTRAL_SCORE
    assert out.confidence == CONFIDENCE_PARTIAL
    assert "sleep length" in out.note
    assert "% of the full picture" in out.note


def test_a_day_with_no_watch_at_all_is_still_scored_from_what_is_left():
    """Training load and the check-in need no wearable."""
    out = score_for(acwr=1.45, subjective_z=-0.8)
    assert out.score is not None
    assert out.coverage_pct >= MIN_COVERAGE_PCT


def test_the_same_evidence_scores_the_same_whether_or_not_the_rest_is_missing():
    """Missing components leave the numerator and the denominator, so they
    neither flatter the score nor punish it."""
    alone = score_for(sleep_duration_z=-1.0, sleep_debt_14d_min=0.0, sleep_debt_nights=14)
    with_neutral_company = score_for(
        sleep_duration_z=-1.0, sleep_debt_14d_min=0.0, sleep_debt_nights=14,
        sleep_efficiency_z=0.0, rhr_deviation_z=0.0,
    )
    assert alone.score < NEUTRAL_SCORE
    assert with_neutral_company.score > alone.score, (
        "company that is exactly average should dilute a lone bad signal"
    )


def test_below_the_coverage_floor_there_is_no_number_at_all():
    thin = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, sleep_duration_z=-1.0),
        ReadinessWeights(sleep_duration=1.0),
    )
    assert thin.coverage_pct < MIN_COVERAGE_PCT
    assert thin.score is None
    assert "Too little to judge" in thin.note


def test_confidence_tracks_how_much_of_the_picture_was_measured():
    full = score_for(**dict(NEUTRAL, hrv_deviation_z=0.0))
    reduced = score_for(**NEUTRAL)
    partial = score_for(sleep_duration_z=0.0, sleep_efficiency_z=0.0, sleep_debt_14d_min=0.0, sleep_debt_nights=14)
    assert full.confidence == CONFIDENCE_FULL
    assert full.coverage_pct == pytest.approx(100.0)
    assert reduced.confidence == CONFIDENCE_REDUCED
    assert partial.confidence == CONFIDENCE_PARTIAL
    assert full.coverage_pct > reduced.coverage_pct > partial.coverage_pct


def test_a_missing_component_is_reported_as_missing_not_omitted():
    out = score_for(sleep_duration_z=-1.0, sleep_efficiency_z=0.5, subjective_z=0.0)
    by_factor = {c.factor: c for c in out.components}
    assert by_factor["rhr_deviation"].available is False
    assert by_factor["rhr_deviation"].impact == 0.0
    assert len(out.components) == 7, "every factor appears, available or not"


# ── presentation ────────────────────────────────────────────────────────────


def test_top_contributors_are_ranked_and_exclude_neutral_factors():
    out = score_for(
        sleep_duration_z=-0.5, sleep_efficiency_z=0.0, rhr_deviation_z=2.0,
        sleep_debt_14d_min=420.0, sleep_debt_nights=14, acwr=1.0, subjective_z=0.0,
    )
    # Sleep debt carries the largest weight (18 of 61), so a saturated debt
    # outranks a two-SD resting HR. That ordering is the weights speaking.
    factors = [c.factor for c in out.top_contributors()]
    assert factors == ["sleep_debt_14d", "rhr_deviation"]
    assert "sleep_efficiency" not in factors


def test_bands_map_score_to_status():
    """A day has to be genuinely off baseline before it stops being green."""

    def status_for(**overrides):
        return score_for(**dict(NEUTRAL, **overrides)).status

    assert status_for() == STATUS_GREEN
    assert status_for(sleep_duration_z=-0.5, rhr_deviation_z=0.5) == STATUS_GREEN
    assert status_for(sleep_duration_z=-1.0, rhr_deviation_z=1.0,
                      sleep_debt_14d_min=210.0) == STATUS_AMBER
    assert status_for(sleep_duration_z=-2.0, rhr_deviation_z=2.0,
                      sleep_debt_14d_min=420.0) == STATUS_RED


def test_weights_are_injectable_not_hardcoded():
    light = score_for(**dict(NEUTRAL, sleep_duration_z=-1.0))
    heavy = compute_readiness(
        ReadinessInput(data_completeness_pct=100.0, **dict(NEUTRAL, sleep_duration_z=-1.0)),
        ReadinessWeights(sleep_duration=40.0),
    )
    assert heavy.score < light.score


def test_as_dict_is_serialisable_and_carries_the_breakdown_and_coverage():
    out = score_for(**dict(NEUTRAL, rhr_deviation_z=2.0))
    payload = out.as_dict()
    assert payload["status"] in {STATUS_GREEN, STATUS_AMBER, STATUS_RED}
    assert len(payload["components"]) == 7
    assert payload["top_contributors"][0]["factor"] == "rhr_deviation"
    assert isinstance(payload["score"], float)
    assert payload["coverage_pct"] == pytest.approx(out.coverage_pct, abs=0.05)
