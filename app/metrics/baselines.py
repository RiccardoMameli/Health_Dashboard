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

#: The window a baseline prefers to stand on. Recent enough to track real
#: change rather than average it away.
BASELINE_WINDOW_DAYS = 30

#: How far back it may reach when the preferred window is too sparse.
#:
#: A fixed 30-day window silently assumes the watch is worn most nights. The
#: owner's real history is 461 nights across 2,042 days — 23% wear — and 14
#: observations inside any 30 days needs 47% wear sustained across that
#: window. Measured against his actual pattern, the fixed window produced a
#: reportable sleep baseline on **2.8% of days**: five and a half years of
#: imported history, almost none of it usable.
#:
#: Reaching back to 90 days when 30 is not enough takes that to **69.9%**. It
#: is the same statistical requirement — still 14 real observations, still no
#: interpolation — it simply stops also demanding they be recent. The cost is
#: real and is reported rather than hidden: `span_days` says how far back the
#: observations actually reach, which at this wear rate is a median of 62
#: days, so the baseline moves slower than a 30-day one would.
BASELINE_MAX_WINDOW_DAYS = 90

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
    #: How many days back the observations behind this baseline reach. 30 when
    #: the preferred window was enough; more when it had to widen; 0 when the
    #: baseline is not reportable. A consumer that shows the median should be
    #: able to say how old it is.
    span_days: int = 0

    @property
    def reportable(self) -> bool:
        return self.median is not None


def rolling_baseline(
    values: Sequence[float | None],
    *,
    min_observations: int = MIN_OBSERVATIONS,
    preferred_days: int = BASELINE_WINDOW_DAYS,
    max_days: int = BASELINE_MAX_WINDOW_DAYS,
) -> Baseline:
    """Median and spread of the observed values, over the shortest window that
    holds enough of them.

    `values` is one slot per day, oldest first, `None` where there is no
    observation. The preferred window is tried first; only if it is too sparse
    does the window widen, one day at a time, up to `max_days`. So a stretch
    of nightly wear gets a responsive 30-day baseline and a patchy one still
    gets a baseline, rather than the patchy case getting nothing at all.

    Below `min_observations` even at full width the baseline is withheld and
    reported as `establishing` — a median of four nights is not a baseline,
    and treating it as one would put a confident number in front of noise.
    """
    tail = list(values)[-max_days:]
    preferred = tail[-preferred_days:]

    if len([v for v in preferred if v is not None]) >= min_observations:
        chosen, span = preferred, min(len(preferred), preferred_days)
    else:
        chosen, span = tail, len(tail)

    observed = [v for v in chosen if v is not None]
    n = len(observed)
    if n < min_observations:
        return Baseline(median=None, sd=None, n=n, status=STATUS_ESTABLISHING)

    # Trim the span to the oldest observation actually used, so a baseline
    # that found its fourteenth night on day 61 does not claim to span 90.
    first = next(i for i, v in enumerate(chosen) if v is not None)
    span = len(chosen) - first

    sd = _stdev(observed) if n >= 2 else None
    return Baseline(
        median=float(_median(observed)), sd=sd, n=n, status=STATUS_OK, span_days=span
    )


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
    # The guard reads the window the baseline actually used, not the whole
    # series it was handed. Those differ now that the window widens when it
    # has to: judging the wear behind a 30-day baseline by 90 days of history
    # would flag it on nights that never entered it.
    flags = list(worn) if worn is not None else [v is not None for v in values]
    flags = flags[-base.span_days :] if base.span_days else flags
    if wear_nights_ok(flags):
        return base
    return Baseline(
        median=base.median, sd=base.sd, n=base.n,
        status=STATUS_POTENTIALLY_BIASED, span_days=base.span_days,
    )


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
