"""Per-muscle-group recovery state (plan §14.1 F1).

Answers "what is ready to be trained again" from two measured facts — how long
ago a muscle group was last worked, and how much work it took — and one
population estimate, the window over which that group typically recovers.

**Deliberately not a percentage.** Recovery rate varies with proximity to
failure, training age, absolute volume, sleep, nutrition and age, and the
published windows are population figures rather than measurements of this
user. A "chest: 60% recovered" reads as measured and is not; it would be the
same confident fabrication the AI layer is forbidden from producing, arriving
from a lookup table instead of a model. Four states is roughly the resolution
population data honestly supports.

The one thing here that *is* personal is the volume weighting: a session is
compared against this user's own median for that muscle group, which is a
measurement. Three sets of curls and ten sets of squats are not the same
stimulus, and scaling the window by observed effort is the difference between
a generic table and something that reflects how he actually trains.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Typical recovery windows in hours, by muscle group. Population estimates,
#: grouped by size and by how much eccentric loading the group typically takes:
#: small muscles worked with short levers recover fastest, large muscles and
#: the posterior chain slowest. These are the numbers the screen must label as
#: population figures rather than present as this user's own.
FAST_HOURS = 36.0  # biceps, triceps, forearms, calves, abdominals, neck
MEDIUM_HOURS = 54.0  # chest, shoulders, lats, upper back, traps
SLOW_HOURS = 72.0  # quadriceps, hamstrings, glutes, lower back, adductors

RECOVERY_HOURS: dict[str, float] = {
    "biceps": FAST_HOURS,
    "triceps": FAST_HOURS,
    "forearms": FAST_HOURS,
    "calves": FAST_HOURS,
    "abdominals": FAST_HOURS,
    "neck": FAST_HOURS,
    "chest": MEDIUM_HOURS,
    "shoulders": MEDIUM_HOURS,
    "lats": MEDIUM_HOURS,
    "upper_back": MEDIUM_HOURS,
    "traps": MEDIUM_HOURS,
    "quadriceps": SLOW_HOURS,
    "hamstrings": SLOW_HOURS,
    "glutes": SLOW_HOURS,
    "lower_back": SLOW_HOURS,
    "adductors": SLOW_HOURS,
    "abductors": SLOW_HOURS,
}

#: A secondary muscle group takes a fraction of the stimulus the primary does.
#: Triceps in a bench press are worked, but not as the chest is.
SECONDARY_WEIGHT = 0.4

#: How far the user's own volume may stretch or shrink the window. Bounded
#: because the relationship is not linear and a single enormous session should
#: not imply a week of recovery.
VOLUME_SCALE_MIN = 0.7
VOLUME_SCALE_MAX = 1.4

#: Fractions of the (volume-adjusted) window at which the state changes.
WORKED_FRACTION = 0.4
READY_FRACTION = 1.5

STATE_WORKED = "worked"
STATE_RECOVERING = "recovering"
STATE_LIKELY_READY = "likely_ready"
STATE_READY = "ready"
STATE_UNKNOWN = "unknown"

#: What each state is called on screen. Status colour never signals alone
#: (plan §10.3), so every state carries its word.
STATE_LABELS = {
    STATE_WORKED: "Worked",
    STATE_RECOVERING: "Recovering",
    STATE_LIKELY_READY: "Likely ready",
    STATE_READY: "Ready",
    STATE_UNKNOWN: "Not trained",
}


@dataclass(frozen=True)
class MuscleRecovery:
    """One muscle group's state. `hours_since` and `volume_kg` are measured;
    `window_hours` is a population estimate and is reported so the screen can
    say so."""

    group: str
    state: str
    hours_since: float | None
    volume_kg: float | None
    window_hours: float | None

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "state": self.state,
            "label": STATE_LABELS[self.state],
            "hours_since": None if self.hours_since is None else round(self.hours_since, 1),
            "volume_kg": None if self.volume_kg is None else round(self.volume_kg, 1),
            "window_hours": self.window_hours,
        }


def _volume_scale(volume_kg: float | None, median_kg: float | None) -> float:
    """How this session compares to the user's own typical work for the group."""
    if not volume_kg or not median_kg or median_kg <= 0:
        return 1.0
    ratio = volume_kg / median_kg
    return max(VOLUME_SCALE_MIN, min(VOLUME_SCALE_MAX, ratio))


def recovery_state(
    *,
    hours_since: float | None,
    volume_kg: float | None = None,
    median_volume_kg: float | None = None,
    window_hours: float | None = None,
) -> tuple[str, float | None]:
    """The state for one group, and the window it was judged against.

    `hours_since` of None means the group was not trained inside the lookback
    at all — reported as `unknown` rather than `ready`, because "no record of
    working it" and "worked it and recovered" are different statements and only
    one of them is a measurement.
    """
    if hours_since is None or window_hours is None:
        return STATE_UNKNOWN, window_hours
    window = window_hours * _volume_scale(volume_kg, median_volume_kg)
    if hours_since < window * WORKED_FRACTION:
        return STATE_WORKED, window
    if hours_since < window:
        return STATE_RECOVERING, window
    if hours_since < window * READY_FRACTION:
        return STATE_LIKELY_READY, window
    return STATE_READY, window


def muscle_recovery(
    stimuli: dict[str, tuple[float, float]],
    *,
    median_volumes: dict[str, float] | None = None,
) -> list[MuscleRecovery]:
    """Recovery state for every group in the vocabulary.

    `stimuli` maps a group to (hours_since_last_worked, volume_kg). Groups
    absent from it are reported as `unknown`: the figure shows every muscle
    either way, and a group with no record must not be shaded as recovered.
    """
    medians = median_volumes or {}
    out: list[MuscleRecovery] = []
    for group in sorted(RECOVERY_HOURS):
        window = RECOVERY_HOURS[group]
        hours, volume = stimuli.get(group, (None, None))
        state, adjusted = recovery_state(
            hours_since=hours,
            volume_kg=volume,
            median_volume_kg=medians.get(group),
            window_hours=window,
        )
        out.append(
            MuscleRecovery(
                group=group,
                state=state,
                hours_since=hours,
                volume_kg=volume,
                window_hours=None if adjusted is None else round(adjusted, 1),
            )
        )
    return out
