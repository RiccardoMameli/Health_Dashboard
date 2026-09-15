"""The readiness score.

A 0-100 composite that is **always** reported with its component breakdown
and with how much of the picture it stands on. Pure: weights come in as an
argument so they can live in config rather than in code, and nothing here
reads a database or a clock.

**The score is a weighted mean of the components that could be computed, not
a sum of deductions from a perfect start.** That is a deliberate departure
from plan 6.3's `readiness = 100 + ...`, made on 14 Sep 2026 because the
plan's formula fails in the one way this project cannot tolerate: a component
with no data contributed zero, which is arithmetically identical to a
component sitting exactly on its baseline, so the less the system knew the
better the day looked. A real morning — five hours' sleep, 71% efficiency,
resting HR eight over, self-rated 3/10 — scored 94 and green, because no
baseline was established and six of the seven components were silently
treated as fine.

The mean fixes that without the opposite error. Missing components leave the
numerator *and* the denominator, so they neither flatter the score nor punish
it: the answer becomes "as far as sleep can tell, this is a 62", and the
coverage that answer rests on is reported next to it. Summing credits upward
from zero was considered and does not work — with only sleep measured the
attainable maximum would be sleep's share of the weight, so a perfect night
would read 13/100. Rescaling by what is available is unavoidable, and once
rescaled, counting up from zero and counting down from full are the same
equation with the sign flipped.

Three refusals are built in, and all three matter more than the number:

- Below the *coverage* floor no score is computed. Coverage is the share of
  weight that could actually be evaluated, which is the question that decides
  whether a day is judgeable. Field completeness is reported alongside but no
  longer gates the score: a field can be recorded and still contribute
  nothing, because a value without an established baseline has no deviation
  to score.
- A component with no input is reported as unavailable and excluded from the
  mean, never as a neutral zero dressed up as a measurement.
- Confidence is derived from coverage, so a score resting on one component is
  never presented like one resting on seven.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.metrics.derived import SLEEP_DEBT_FULL_PENALTY_MIN, acwr_penalty

#: An ordinary day: every available component sitting exactly on its own
#: baseline. Not 100, so that a genuinely good day has somewhere to go — under
#: the old deduction-only scale an exceptional morning and an unremarkable one
#: both read 100, which made the top of the range meaningless.
NEUTRAL_SCORE = 75.0

#: Points per unit of weighted-mean signal. Set so a day with every component
#: at its worst lands near 5, which is where the old formula bottomed out:
#: 75 - 45 x 1.557 = 5. Keeping the floor in the same place means historical
#: scores stay roughly comparable even though the formula changed.
SIGNAL_SPAN = 45.0

#: Components whose signal can only ever be negative. There is no such thing
#: as less than no sleep debt, and a well-judged training load earns no
#: credit — both subtract or do nothing.
#:
#: This matters because of what it does to the top of the scale. A day whose
#: only available components are these cannot score above `NEUTRAL_SCORE`
#: however well it actually went, so a clean reading from them means "nothing
#: adverse is visible", not "this was a good morning". Measured over the real
#: history on 15 Sep 2026, that described **47% of scored days**, with 113 of
#: them landing exactly on the neutral score and rendering green —
#: indistinguishable from a fully measured good day.
ONE_SIDED_FACTORS = frozenset({"sleep_debt_14d", "acwr"})

#: Nights of observed sleep before an accumulated debt is worth scoring. One
#: short night is a fact about one night, not a fortnight's debt.
MIN_NIGHTS_FOR_SLEEP_DEBT = 3

#: The window the debt ceiling is calibrated for.
SLEEP_DEBT_WINDOW_NIGHTS = 14

#: Coverage — the share of total weight that could actually be evaluated — is
#: what gates the score. Below this, the day is not judgeable and no number is
#: emitted.
#:
#: Deliberately low, and low on purpose rather than by accident. The owner
#: does not wear a watch every night and has said plainly that a dashboard
#: which goes blank whenever a night is missed is one that stops being opened.
#: At 10% any single real component still produces a number — including a
#: lone check-in, which at 11.5% of the weight is the thinnest basis that
#: matters, and the one available on a morning when the watch stayed on the
#: bedside table. Every such score carries its coverage and a sentence naming
#: what it rests on, which is the honest trade: a thin answer that admits it
#: is thin beats no answer. The refusal that survived scrutiny is the one
#: this still makes — when nothing at all could be computed.
MIN_COVERAGE_PCT = 10.0

#: Field completeness is still computed and still reported — it answers "how
#: much did the sources supply today", which is a real question. It no longer
#: gates the score, because it answers the *wrong* question for that purpose:
#: a recorded value with no established baseline has no deviation to score, so
#: completeness can read 71% while nothing at all is computable.
MIN_COMPLETENESS_PCT = 60.0

#: Z-scores are clamped before weighting. Two SD, not three: past two, the
#: difference between "bad" and "very bad" on one metric is not information
#: the score should act on, and letting it through means a single reading
#: takes a third of the scale on its own. What should push a day further down
#: is more things being wrong, not one thing being extremely wrong.
Z_CLAMP = 2.0

#: Score bands for the readiness ring. Amber is deliberately wide — in the
#: baseline phase the score is a prompt to look, not a verdict.
#:
#: Re-fitted when the formula became a mean, which is more sensitive around
#: neutral than the old sum was: half an SD down on two metrics costs about
#: seven points, where before it cost fifteen. With green starting at 70 an
#: ordinary day sat five points above the boundary and flickered amber on
#: trivial variation. At 65 a minor wobble stays green (68), one SD down on
#: two metrics plus half the debt ceiling is amber (54), and two SD with a
#: full debt ceiling is red (33).
GREEN_AT = 65.0
AMBER_AT = 40.0

STATUS_GREEN = "green"
STATUS_AMBER = "amber"
STATUS_RED = "red"
STATUS_INSUFFICIENT = "insufficient_data"

CONFIDENCE_FULL = "full"
CONFIDENCE_REDUCED = "reduced"
CONFIDENCE_PARTIAL = "partial"
CONFIDENCE_INSUFFICIENT = "insufficient"

#: Coverage at or above this reads as a full picture; at or above the second,
#: a reduced one. Below that it is partial and the note says so in words.
FULL_COVERAGE_PCT = 80.0
REDUCED_COVERAGE_PCT = 50.0


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
    #: How many nights the debt above was actually summed over. Required to
    #: score it: a debt is a sum, so a fortnight with three observed nights
    #: reports a smaller number than the same fortnight fully measured, and
    #: scoring that against a fourteen-night ceiling rewards not measuring.
    #: Zero nights produced a debt of 0.0, which is the "null became a zero"
    #: failure the whole project is built to refuse — an empty database
    #: scored 75 and green on the strength of it.
    sleep_debt_nights: int | None = None
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
    #: Share of the total weight that could actually be evaluated. This is the
    #: number that says how much the score is worth, and it belongs next to
    #: the score everywhere the score is shown.
    coverage_pct: float = 0.0
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
            "coverage_pct": round(self.coverage_pct, 1),
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


# `_redistribute_hrv_weight` is gone. It existed to stop a missing HRV from
# silently shrinking the score, by hand-spreading w4 across sleep and resting
# HR. Taking a mean over the available weight does that for every component at
# once, and does it proportionally rather than by a rule that only knew about
# one of them.


#: How each component reads in a sentence, for the note that explains what a
#: partial score rests on. Named here so the wording is one edit, not seven.
FACTOR_NAMES = {
    "sleep_duration": "sleep length",
    "sleep_efficiency": "sleep efficiency",
    "rhr_deviation": "resting heart rate",
    "hrv_deviation": "HRV",
    "sleep_debt_14d": "sleep debt",
    "acwr": "training load",
    "subjective_yesterday": "how you rated the day",
}


def _phrase(factors: list[str], limit: int = 3) -> str:
    """"sleep length, resting heart rate and 2 more"."""
    names = [FACTOR_NAMES.get(f, f.replace("_", " ")) for f in factors]
    if len(names) > limit:
        head, rest = names[:limit], len(names) - limit
        return ", ".join(head) + f" and {rest} more"
    if len(names) > 1:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return names[0] if names else "nothing"


def compute_readiness(
    data: ReadinessInput,
    weights: ReadinessWeights | None = None,
    *,
    sleep_debt_full_penalty_min: float = SLEEP_DEBT_FULL_PENALTY_MIN,
    min_coverage_pct: float = MIN_COVERAGE_PCT,
    neutral_score: float = NEUTRAL_SCORE,
    signal_span: float = SIGNAL_SPAN,
) -> Readiness:
    """Score the day over what could be measured, or refuse to.

    Returns a `Readiness` whose score is None whenever too little of the
    picture was computable to judge. Callers must render that refusal rather
    than substituting a number of their own.
    """
    weights = weights or ReadinessWeights()

    #: (factor, weight, signal) — signal already signed so positive is better,
    #: and None where the component could not be computed.
    rhr_z = _clamped_z(data.rhr_deviation_z)

    # A debt summed over part of a fortnight is compared against part of the
    # ceiling, so three short nights out of three read as badly as fourteen
    # out of fourteen rather than a fifth as badly. Below the minimum the
    # debt is not scored at all and the component reports as unavailable.
    nights = data.sleep_debt_nights
    debt = data.sleep_debt_14d_min
    debt_signal: float | None = None
    if debt is not None and nights is not None and nights >= MIN_NIGHTS_FOR_SLEEP_DEBT:
        observed_fraction = min(nights, SLEEP_DEBT_WINDOW_NIGHTS) / SLEEP_DEBT_WINDOW_NIGHTS
        ceiling = sleep_debt_full_penalty_min * observed_fraction
        debt_signal = -_clamp(debt / ceiling, 0.0, 1.0) if ceiling > 0 else None
    terms: list[tuple[str, float, float | None]] = [
        ("sleep_duration", weights.sleep_duration, _clamped_z(data.sleep_duration_z)),
        ("sleep_efficiency", weights.sleep_efficiency, _clamped_z(data.sleep_efficiency_z)),
        ("rhr_deviation", weights.rhr_deviation, None if rhr_z is None else -rhr_z),
        ("hrv_deviation", weights.hrv_deviation, _clamped_z(data.hrv_deviation_z)),
        ("sleep_debt_14d", weights.sleep_debt, debt_signal),
        ("acwr", weights.acwr, None if data.acwr is None else -acwr_penalty(data.acwr)),
        ("subjective_yesterday", weights.subjective, _clamped_z(data.subjective_z)),
    ]

    total_weight = sum(w for _, w, _ in terms)
    available = [(f, w, s) for f, w, s in terms if s is not None]
    available_weight = sum(w for _, w, _ in available)
    coverage = 0.0 if total_weight <= 0 else available_weight / total_weight * 100.0

    missing = [f for f, _, s in terms if s is None]
    present = [f for f, _, s in available]

    # `impact` stays in the same units the brief already quotes: the points
    # this component moved the final score by. With the mean, that is its
    # share of the available weight rather than its share of the whole.
    components = [
        Component(
            factor=factor,
            impact=(
                0.0
                if signal is None or available_weight <= 0
                else signal_span * weight * signal / available_weight
            ),
            available=signal is not None,
        )
        for factor, weight, signal in terms
    ]

    if coverage < min_coverage_pct:
        return Readiness(
            score=None,
            status=STATUS_INSUFFICIENT,
            confidence=CONFIDENCE_INSUFFICIENT,
            components=components,
            coverage_pct=coverage,
            note=(
                "Nothing could be measured or compared against a baseline this "
                "morning, so no score is given."
                if not present
                else (
                    f"Only {_phrase(present)} could be measured, which is "
                    f"{coverage:.0f}% of what the score weighs. Too little to "
                    f"judge the morning, so no number is given."
                )
            ),
        )

    score = _clamp(neutral_score + sum(c.impact for c in components), 0.0, 100.0)

    if coverage >= FULL_COVERAGE_PCT:
        confidence = CONFIDENCE_FULL
    elif coverage >= REDUCED_COVERAGE_PCT:
        confidence = CONFIDENCE_REDUCED
    else:
        confidence = CONFIDENCE_PARTIAL

    # HRV carries a seventh of the weight, so its absence alone still leaves
    # coverage high enough to read as full. The plan calls the HRV-less
    # formula a fallback and it should not present as the complete one, so
    # its absence caps confidence regardless of what coverage says.
    if data.hrv_deviation_z is None and confidence == CONFIDENCE_FULL:
        confidence = CONFIDENCE_REDUCED

    # Green has to mean "measured and good". When every available component is
    # one-sided the score's ceiling is the neutral point, so the best it can
    # report is an absence of penalties — which is a weaker claim and should
    # not wear the same colour as a good morning that was actually measured.
    # The number is untouched; only what it is called changes.
    status = _band(score)
    one_sided_only = bool(present) and set(present) <= ONE_SIDED_FACTORS
    if one_sided_only and status == STATUS_GREEN:
        status = STATUS_AMBER

    if one_sided_only:
        note = (
            f"Nothing adverse showing in {_phrase(present)} — but that is "
            f"{coverage:.0f}% of the picture, and none of it can tell you a "
            f"morning went *well*, only that it did not go badly."
        )
    elif missing:
        note = (
            f"Based on {_phrase(present)} — {coverage:.0f}% of the full picture. "
            f"No reading for {_phrase(missing)}, so this is what today's data "
            f"can say, not the whole story."
        )
    else:
        note = None

    return Readiness(
        score=score,
        status=status,
        confidence=confidence,
        components=components,
        coverage_pct=coverage,
        note=note,
    )
