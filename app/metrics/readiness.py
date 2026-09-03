"""The readiness score (plan 6.3).

A 0-100 composite that is **always** reported with its component breakdown.
Pure: weights come in as an argument so they can live in config rather than
in code, and nothing here reads a database or a clock.

Three refusals are built in, and all three matter more than the number:

- Below the completeness floor the score is not computed at all. The system
  emits `insufficient_data` rather than scoring a day it cannot see.
- A component with no input contributes nothing and is reported as
  unavailable, never as a neutral zero dressed up as a measurement.
- With HRV missing, its weight is redistributed and the confidence is marked
  `reduced`, so a fallback score is never mistaken for a full one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.metrics.derived import SLEEP_DEBT_FULL_PENALTY_MIN, acwr_penalty

#: The score the formula starts from (plan 6.3: `readiness = 100 + ...`).
#: Note the consequence: at 100, every positive contribution is clipped, so an
#: exceptional day and an ordinary one both read 100 and the score is purely a
#: deduction scale. Lowering this to ~85 would give good days headroom at the
#: cost of no longer matching the plan's formula. Left at the plan's value.
BASELINE_SCORE = 100.0

#: Below this, emit no score (plan 6.3).
MIN_COMPLETENESS_PCT = 60.0

#: Z-scores are clamped before weighting. Two SD, not three: past two, the
#: difference between "bad" and "very bad" on one metric is not information
#: the score should act on, and letting it through means a single reading
#: takes a third of the scale on its own. What should push a day further down
#: is more things being wrong, not one thing being extremely wrong.
Z_CLAMP = 2.0

#: Score bands for the readiness ring. Amber is deliberately wide — in the
#: baseline phase the score is a prompt to look, not a verdict.
GREEN_AT = 75.0
AMBER_AT = 55.0

STATUS_GREEN = "green"
STATUS_AMBER = "amber"
STATUS_RED = "red"
STATUS_INSUFFICIENT = "insufficient_data"

CONFIDENCE_FULL = "full"
CONFIDENCE_REDUCED = "reduced"
CONFIDENCE_INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class ReadinessWeights:
    """Plan 6.3 w1-w7. Defaults are a starting point, not a finding.

    They are in config precisely because they are unvalidated: nothing in six
    weeks of baseline data can justify them, and they should be revisited
    once there is enough history to check the score against how days
    actually felt.

    They are scaled so the bands mean something. With HRV missing (the
    current fallback), a day one SD short on sleep with resting HR one SD up
    and half the sleep-debt ceiling lands around 70 — amber, a prompt to
    look; the same day at two SD lands near 30 — red; a single bad night on
    an otherwise clean fortnight stays amber rather than red, because the
    14-day pattern carries more weight than any one night.
    """

    sleep_duration: float = 8.0
    sleep_efficiency: float = 4.0
    rhr_deviation: float = 8.0
    hrv_deviation: float = 7.0
    sleep_debt: float = 18.0
    acwr: float = 9.0
    subjective: float = 7.0


@dataclass(frozen=True)
class ReadinessInput:
    """Everything the score needs, already computed by the metrics engine.

    Any field may be None. None means "not measured" and is handled as such.
    """

    data_completeness_pct: float
    sleep_duration_z: float | None = None
    sleep_efficiency_z: float | None = None
    rhr_deviation_z: float | None = None
    hrv_deviation_z: float | None = None
    sleep_debt_14d_min: float | None = None
    acwr: float | None = None
    subjective_z: float | None = None


@dataclass(frozen=True)
class Component:
    """One term of the score, named so the brief can quote it verbatim."""

    factor: str
    impact: float
    available: bool


@dataclass(frozen=True)
class Readiness:
    score: float | None
    status: str
    confidence: str
    components: list[Component] = field(default_factory=list)
    note: str | None = None

    def top_contributors(self, limit: int = 2) -> list[Component]:
        """The components that moved the score most, largest first.

        Only available components with a non-zero impact qualify: "sleep was
        neutral" is not a contributor, and neither is a metric that is
        missing.
        """
        movers = [c for c in self.components if c.available and c.impact != 0]
        return sorted(movers, key=lambda c: abs(c.impact), reverse=True)[:limit]

    def as_dict(self) -> dict:
        return {
            "score": None if self.score is None else round(self.score, 1),
            "status": self.status,
            "confidence": self.confidence,
            "note": self.note,
            "components": [
                {"factor": c.factor, "impact": round(c.impact, 1), "available": c.available}
                for c in self.components
            ],
            "top_contributors": [
                {"factor": c.factor, "impact": round(c.impact, 1)} for c in self.top_contributors()
            ],
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamped_z(z: float | None) -> float | None:
    return None if z is None else _clamp(z, -Z_CLAMP, Z_CLAMP)


def _band(score: float) -> str:
    if score >= GREEN_AT:
        return STATUS_GREEN
    if score >= AMBER_AT:
        return STATUS_AMBER
    return STATUS_RED


def _redistribute_hrv_weight(weights: ReadinessWeights) -> ReadinessWeights:
    """Spread w4 across w1-w3 in proportion to their existing weights (6.3)."""
    receivers = weights.sleep_duration + weights.sleep_efficiency + weights.rhr_deviation
    if receivers <= 0 or weights.hrv_deviation <= 0:
        return weights
    scale = 1 + weights.hrv_deviation / receivers
    return ReadinessWeights(
        sleep_duration=weights.sleep_duration * scale,
        sleep_efficiency=weights.sleep_efficiency * scale,
        rhr_deviation=weights.rhr_deviation * scale,
        hrv_deviation=0.0,
        sleep_debt=weights.sleep_debt,
        acwr=weights.acwr,
        subjective=weights.subjective,
    )


def compute_readiness(
    data: ReadinessInput,
    weights: ReadinessWeights | None = None,
    *,
    sleep_debt_full_penalty_min: float = SLEEP_DEBT_FULL_PENALTY_MIN,
    min_completeness_pct: float = MIN_COMPLETENESS_PCT,
    baseline_score: float = BASELINE_SCORE,
) -> Readiness:
    """Score the day, or refuse to.

    Returns a `Readiness` whose score is None whenever the day is too sparse
    to judge. Callers must render that refusal rather than substituting a
    number of their own.
    """
    weights = weights or ReadinessWeights()

    if data.data_completeness_pct < min_completeness_pct:
        return Readiness(
            score=None,
            status=STATUS_INSUFFICIENT,
            confidence=CONFIDENCE_INSUFFICIENT,
            components=[],
            note=(
                f"Data completeness {data.data_completeness_pct:.0f}% is below the "
                f"{min_completeness_pct:.0f}% floor. No score for this day."
            ),
        )

    hrv_available = data.hrv_deviation_z is not None
    effective = weights if hrv_available else _redistribute_hrv_weight(weights)

    components: list[Component] = []

    def add(factor: str, weight: float, signal: float | None) -> None:
        """`signal` is already signed so that positive means better."""
        components.append(
            Component(
                factor=factor,
                impact=0.0 if signal is None else weight * signal,
                available=signal is not None,
            )
        )

    add("sleep_duration", effective.sleep_duration, _clamped_z(data.sleep_duration_z))
    add("sleep_efficiency", effective.sleep_efficiency, _clamped_z(data.sleep_efficiency_z))

    rhr_z = _clamped_z(data.rhr_deviation_z)
    add("rhr_deviation", effective.rhr_deviation, None if rhr_z is None else -rhr_z)

    hrv_z = _clamped_z(data.hrv_deviation_z)
    add("hrv_deviation", effective.hrv_deviation, hrv_z)

    debt = data.sleep_debt_14d_min
    debt_signal = None if debt is None else -_clamp(debt / sleep_debt_full_penalty_min, 0.0, 1.0)
    add("sleep_debt_14d", effective.sleep_debt, debt_signal)

    acwr_signal = None if data.acwr is None else -acwr_penalty(data.acwr)
    add("acwr", effective.acwr, acwr_signal)

    add("subjective_yesterday", effective.subjective, _clamped_z(data.subjective_z))

    raw = baseline_score + sum(c.impact for c in components)
    score = _clamp(raw, 0.0, 100.0)

    confidence = CONFIDENCE_FULL if hrv_available else CONFIDENCE_REDUCED
    note = (
        None
        if hrv_available
        else "HRV unavailable — its weight was redistributed across sleep and resting HR."
    )
    return Readiness(
        score=score,
        status=_band(score),
        confidence=confidence,
        components=components,
        note=note,
    )
