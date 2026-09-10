"""Per-muscle-group recovery (plan §14.1 F1).

The tests that matter most here are the ones asserting what the metric
*refuses* to say: a group with no record is not "recovered", and no state
carries a percentage.
"""

import pytest

from app.metrics.recovery import (
    FAST_HOURS,
    RECOVERY_HOURS,
    SLOW_HOURS,
    STATE_LABELS,
    STATE_LIKELY_READY,
    STATE_READY,
    STATE_RECOVERING,
    STATE_UNKNOWN,
    STATE_WORKED,
    muscle_recovery,
    recovery_state,
)


def test_states_progress_with_time_since_the_session():
    """36-hour window: worked under 14.4h, recovering to 36h, likely ready to
    54h, ready beyond."""
    for hours, expected in [
        (2, STATE_WORKED),
        (13, STATE_WORKED),
        (20, STATE_RECOVERING),
        (35, STATE_RECOVERING),
        (40, STATE_LIKELY_READY),
        (53, STATE_LIKELY_READY),
        (60, STATE_READY),
    ]:
        state, _ = recovery_state(hours_since=hours, window_hours=FAST_HOURS)
        assert state == expected, f"{hours}h gave {state}"


def test_a_group_never_trained_is_unknown_not_ready():
    """"No record of working it" and "worked it and recovered" are different
    statements, and only one of them is a measurement."""
    state, _ = recovery_state(hours_since=None, window_hours=FAST_HOURS)
    assert state == STATE_UNKNOWN
    assert STATE_LABELS[STATE_UNKNOWN] == "Not trained"


def test_large_muscle_groups_get_longer_windows():
    """The part that actually reflects the literature: quads are not biceps."""
    assert RECOVERY_HOURS["quadriceps"] == SLOW_HOURS
    assert RECOVERY_HOURS["biceps"] == FAST_HOURS
    assert RECOVERY_HOURS["quadriceps"] > RECOVERY_HOURS["biceps"]

    # 48h out: recovered for a small group, still recovering for a large one.
    assert recovery_state(hours_since=48, window_hours=FAST_HOURS)[0] == STATE_LIKELY_READY
    assert recovery_state(hours_since=48, window_hours=SLOW_HOURS)[0] == STATE_RECOVERING


def test_a_heavier_than_usual_session_stretches_the_window():
    """Volume is compared against the user's own median, which is a
    measurement rather than a population guess."""
    medium = 54.0
    light = recovery_state(
        hours_since=40, volume_kg=2_000, median_volume_kg=8_000, window_hours=medium
    )
    heavy = recovery_state(
        hours_since=40, volume_kg=20_000, median_volume_kg=8_000, window_hours=medium
    )
    assert light[1] < heavy[1]                       # the window itself moved
    assert light[0] == STATE_LIKELY_READY            # ...and so did the verdict
    assert heavy[0] == STATE_RECOVERING


def test_the_volume_stretch_is_bounded():
    """One enormous leg day must not imply a week of recovery."""
    absurd = recovery_state(hours_since=1, volume_kg=10_000_000, median_volume_kg=1,
                            window_hours=SLOW_HOURS)
    assert absurd[1] <= SLOW_HOURS * 1.4


def test_every_group_is_reported_even_with_no_history():
    """The figure shades every muscle either way; a group with no record must
    not be left looking recovered."""
    rows = muscle_recovery({})
    assert len(rows) == len(RECOVERY_HOURS)
    assert {r.state for r in rows} == {STATE_UNKNOWN}


def test_a_worked_group_reports_its_measured_facts():
    rows = {r.group: r for r in muscle_recovery({"chest": (6.0, 5_024.0)})}
    chest = rows["chest"]
    assert chest.state == STATE_WORKED
    assert chest.hours_since == 6.0
    assert chest.volume_kg == 5_024.0
    assert rows["quadriceps"].state == STATE_UNKNOWN


def test_no_state_is_a_percentage():
    """A "% recovered" reads as measured and is not. Four labelled states are
    the resolution population data honestly supports."""
    for row in muscle_recovery({"chest": (6.0, 1_000.0)}):
        payload = row.as_dict()
        assert isinstance(payload["label"], str)
        assert "%" not in payload["label"]
        assert set(payload) == {"group", "state", "label", "hours_since", "volume_kg",
                                "window_hours"}


@pytest.mark.parametrize("state", [STATE_WORKED, STATE_RECOVERING, STATE_LIKELY_READY,
                                   STATE_READY, STATE_UNKNOWN])
def test_every_state_carries_a_word(state):
    """Status colour never signals alone (plan §10.3)."""
    assert STATE_LABELS[state]
