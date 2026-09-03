"""Rolling baselines (plan 6.1).

Pure functions: no database, no clock, no I/O. Every one of them takes plain
values and returns plain values, so they can be tested against fixtures.

Two rules run through all of this:

- **A null is a null.** A missing observation is dropped from the window, never
  replaced with a zero or an interpolation. `n` always reports how many real
  observations the baseline stands on.
- **Excluded days never enter a baseline.** Filtering them is the caller's job
  (`app.services.metrics_engine` does it); these functions only see the
  values they are handed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median as _median
from statistics import stdev as _stdev

#: A baseline is not reported until it stands on this many observations.
MIN_OBSERVATIONS = 14

#: The rolling window baselines are computed over.
BASELINE_WINDOW_DAYS = 30

#: Wear-bias guard (D3): fewer than this many nights worn in any rolling 7
#: makes the sleep baseline a baseline of the nights you chose to measure.
MIN_WEAR_NIGHTS_PER_7 = 4

STATUS_OK = "ok"
STATUS_ESTABLISHING = "establishing"
STATUS_POTENTIALLY_BIASED = "potentially_biased"


@dataclass(frozen=True)
class Baseline:
    """A rolling baseline and the evidence behind it.

    `median` is None whenever the baseline is not yet reportable — never a
    stand-in value. Callers must handle None rather than defaulting.
    """

    median: float | None
    sd: float | None
    n: int
    status: str

    @property
    def reportable(self) -> bool:
        return self.median is not None


def rolling_baseline(
    values: Sequence[float | None],
    *,
    min_observations: int = MIN_OBSERVATIONS,
) -> Baseline:
    """Median and spread of the observed values in a window.

    Below `min_observations` the baseline is withheld and reported as
    `establishing` — a median of four nights is not a baseline, and treating
    it as one would put a confident number in front of noise.
    """
    observed = [v for v in values if v is not None]
    n = len(observed)
    if n < min_observations:
        return Baseline(median=None, sd=None, n=n, status=STATUS_ESTABLISHING)
    sd = _stdev(observed) if n >= 2 else None
    return Baseline(median=float(_median(observed)), sd=sd, n=n, status=STATUS_OK)


def wear_nights_ok(
    worn: Sequence[bool],
    *,
    min_per_7: int = MIN_WEAR_NIGHTS_PER_7,
) -> bool:
    """True when every rolling 7-night window contains enough worn nights.

    A window shorter than 7 nights cannot fail this test — there is not yet
    enough history to say the watch was skipped rather than simply not owned.
    """
    if len(worn) < 7:
        return True
    return all(sum(worn[i : i + 7]) >= min_per_7 for i in range(len(worn) - 6))


def sleep_baseline(
    values: Sequence[float | None],
    *,
    worn: Sequence[bool] | None = None,
    min_observations: int = MIN_OBSERVATIONS,
) -> Baseline:
    """A sleep baseline with the wear-bias guard applied (D3).

    The guard flags rather than suppresses: the median is still the best
    estimate available, but a consumer that reports it must say it may be
    biased. A night is treated as worn when it produced a value, unless the
    caller knows better and passes `worn` explicitly (the `no_watch` check-in
    tag distinguishes "slept badly" from "did not measure").
    """
    base = rolling_baseline(values, min_observations=min_observations)
    if not base.reportable:
        return base
    flags = list(worn) if worn is not None else [v is not None for v in values]
    if wear_nights_ok(flags):
        return base
    return Baseline(median=base.median, sd=base.sd, n=base.n, status=STATUS_POTENTIALLY_BIASED)


def deviation(today: float | None, baseline: Baseline) -> float | None:
    """Today's value minus the baseline median, in the metric's own units."""
    if today is None or baseline.median is None:
        return None
    return today - baseline.median


def relative_deviation(today: float | None, baseline: Baseline) -> float | None:
    """Deviation as a fraction of the baseline median (plan 6.2, HRV)."""
    if today is None or not baseline.median:
        return None
    return (today - baseline.median) / baseline.median


def z_score(today: float | None, baseline: Baseline, *, sd_floor: float) -> float | None:
    """Standardised deviation, with a floor under the spread.

    A very tight window can produce a near-zero SD, which would turn a
    trivial difference into a huge z. The floor is per-metric and belongs to
    the caller, because 1 bpm and 1 minute are not comparable quantities.
    """
    if today is None or baseline.median is None or baseline.sd is None:
        return None
    return (today - baseline.median) / max(baseline.sd, sd_floor)
