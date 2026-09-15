#!/usr/bin/env python3
"""Run the reworked readiness score over the whole imported history.

    python scripts/verify_readiness.py
    python scripts/verify_readiness.py --since 2024-01-01
    python scripts/verify_readiness.py --stride 7      # every 7th day, quick pass

The formula changed on 14 Sep 2026 (plan D12) and the baseline window with it
(D13). Both changes were tested against fixtures and against a synthetic
export shaped like the real one. **Neither has ever run over the real 461
nights**, and this project's record on that distinction is not good: pointing
the Today screen at real data broke it four times in one session, and the
Samsung parser died on four assumptions no fixture caught.

Two specific claims are checked here rather than trusted:

1. That the adaptive baseline window takes sleep-baseline availability from
   2.8% of days to about 70%. That figure came from *modelling* his wear
   pattern, not from measuring it.
2. That the new score behaves sensibly across five years — no cliff at the
   coverage floor, no pile-up on the neutral score, no silent clamping.

Read-only. It computes and prints; nothing is written.
"""

import argparse
import sys
from collections import Counter
from datetime import date as Date
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.metrics.baselines import (  # noqa: E402
    BASELINE_MAX_WINDOW_DAYS,
    STATUS_POTENTIALLY_BIASED,
    rolling_baseline,
)
from app.metrics.readiness import (  # noqa: E402
    MIN_COVERAGE_PCT,
    NEUTRAL_SCORE,
    STATUS_INSUFFICIENT,
)
from app.models import SleepSession  # noqa: E402
from app.services.metrics_engine import compute_day  # noqa: E402

#: The prediction this script exists to check, from the 14 Sep modelling.
PREDICTED_BASELINE_COVERAGE_PCT = 69.9
PREVIOUS_BASELINE_COVERAGE_PCT = 2.8

#: Below this many days there is not enough history to say anything.
MIN_DAYS_TO_REPORT = 30

#: Nights in a calendar year before that year's median is allowed to vote on
#: whether the sleep norm drifts. Without it a year holding nineteen nights
#: carries the same weight as one holding two hundred and fifty, and the thin
#: one decides — which is how a small sample gets promoted into a design
#: decision.
MIN_NIGHTS_TO_WEIGH = 50

#: Components whose signal can only ever be negative: there is no such thing
#: as *less than no* sleep debt, or a training load so well judged it earns
#: credit. A day whose only available components are these cannot score above
#: the neutral point no matter how well it went, so if that describes most
#: days the score is systematically pessimistic for a reason that has nothing
#: to do with how the owner is actually doing.
ONE_SIDED_FACTORS = {"sleep_debt_14d", "acwr"}


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def bar(count: int, total: int, width: int = 34) -> str:
    if total <= 0:
        return ""
    filled = round(width * count / total)
    return "#" * filled + "." * (width - filled)


def histogram(counts: Counter, order: list[str], total: int) -> None:
    for key in order:
        n = counts.get(key, 0)
        print(f"  {key:<20} {n:>6,}  {n / total * 100 if total else 0:5.1f}%  {bar(n, total)}")


def compare_windows(session, first: Date, last: Date) -> None:
    """What the widening actually bought, measured rather than modelled.

    Reads only the sleep table and applies both rules to the same series, so
    it costs nothing next to the full walk and answers the question the walk
    raises: the baselines it reports reach back a median of 30 days, which
    means most of them came from the preferred window and the widening never
    fired. That is worth a number rather than an inference.
    """
    section("what widening the baseline window actually bought")
    rows = session.execute(
        select(SleepSession.date, SleepSession.duration_min)
        .where(SleepSession.duration_min.is_not(None))
        .order_by(SleepSession.date)
    ).all()
    by_date: dict[Date, float] = {}
    for day, duration in rows:
        # The engine takes the longest session per date; for a coverage count
        # any one of them is enough to make the night an observation.
        by_date.setdefault(day, float(duration))

    span = (last - first).days + 1
    series = [by_date.get(first + timedelta(days=i)) for i in range(span)]

    # The staleness cost has to be measured on the days a rule *adds*, not on
    # all of its days. A median over everything sits inside his dense stretches
    # where 30 days always sufficed, so it reads 30 for every rule including
    # the 365-day one and says nothing at all — which is exactly what the first
    # version of this table did.
    results = {}
    previous: set[int] = set()
    print(f"  {'rule':<26} {'days':>6}  {'cover':>6}   {'days this rule adds':>28}")
    for label, preferred, longest in (
        ("30-day window only", 30, 30),
        ("prefer 30, widen to 90", 30, BASELINE_MAX_WINDOW_DAYS),
        ("prefer 30, widen to 180", 30, 180),
        ("prefer 30, widen to 365", 30, 365),
    ):
        usable: set[int] = set()
        spans: dict[int, int] = {}
        for end in range(span):
            window = series[max(0, end - longest + 1) : end + 1]
            base = rolling_baseline(window, preferred_days=preferred, max_days=longest)
            if base.reportable:
                usable.add(end)
                spans[end] = base.span_days
        results[label] = len(usable) / span * 100

        added = sorted(spans[d] for d in usable - previous)
        if added:
            note = (f"{len(added):>5,}, reaching back "
                    f"{added[len(added) // 2]:>3}-{added[-1]:>3} days")
        else:
            note = f"{0:>5}"
        print(f"  {label:<26} {len(usable):>6,}  {results[label]:5.1f}%   {note:>28}")
        previous = usable

    gain = results["prefer 30, widen to 90"] - results["30-day window only"]
    print(f"\n  widening to 90 buys {gain:+.1f} points over a plain 30-day window")
    print("  the last column is the cost: how far back the baselines are on the")
    print("  days each rule adds, which is where the staleness actually lives")

    # Whether a wide window is *safe* is a different question from whether it
    # is available, and it has an answer in the data: if the sleep norm barely
    # moves from year to year then a year-old median is a fair comparator, and
    # if it drifts then reaching back that far measures the drift rather than
    # last night.
    print("\n  is a wide window safe? — sleep median by calendar year:")
    by_year: dict[int, list[float]] = {}
    for day, duration in by_date.items():
        by_year.setdefault(day.year, []).append(duration)

    # A year of 19 nights and a year of 250 are not comparable evidence, and
    # letting the thin one set the verdict is how a small sample gets promoted
    # into a design decision. Thin years are shown and excluded from the sum.
    weighed = []
    for year in range(min(by_year), max(by_year) + 1):
        values = sorted(by_year.get(year, []))
        if not values:
            print(f"    {year}   {0:>4} nights   (nothing recorded at all)")
            continue
        median = values[len(values) // 2]
        thin = len(values) < MIN_NIGHTS_TO_WEIGH
        print(f"    {year}   {len(values):>4} nights   median {median:6.0f} min "
              f"({median / 60:.1f}h)"
              f"{'   too thin to weigh' if thin else ''}")
        if not thin:
            weighed.append((year, median))

    if len(weighed) >= 2:
        medians = [m for _, m in weighed]
        drift = max(medians) - min(medians)
        years = ", ".join(str(y) for y, _ in weighed)
        print(f"\n    across the years with enough nights to judge ({years}): "
              f"{drift:.0f} min apart")
        if drift <= 30:
            print("    -> stable. A baseline reaching months back would compare him")
            print("       against much the same norm, so a wider cap looks safe.")
        else:
            print("    -> it drifts, and a wide window would partly be measuring")
            print("       that drift rather than last night.")
    else:
        print("\n    not enough well-sampled years to say either way")


def main() -> int:
    # The console this runs on is Windows and defaults to cp1252. Two separate
    # scripts in this project have already died printing a box character.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=Date.fromisoformat, default=None)
    parser.add_argument("--stride", type=int, default=1,
                        help="sample every Nth day; 1 (default) walks every day")
    args = parser.parse_args()

    with session_scope() as session:
        first, last = session.execute(
            select(func.min(SleepSession.date), func.max(SleepSession.date))
        ).one()
        if first is None:
            print("No sleep sessions in the database. Import an export first.")
            return 2

        start = max(first, args.since) if args.since else first
        # Nothing before the first night can produce a baseline, and the first
        # weeks cannot either, but they are walked anyway: "how long until the
        # score starts working" is one of the questions.
        days = [start + timedelta(days=i)
                for i in range(0, (last - start).days + 1, args.stride)]

        print(f"sleep history : {first} to {last}  ({(last - first).days + 1:,} days)")
        print(f"walking       : {len(days):,} days from {start}"
              f"{'' if args.stride == 1 else f', every {args.stride}'}")
        print("this recomputes every metric per day and is not fast; progress below")

        compare_windows(session, first, last)

        scores: list[float] = []
        coverages: list[float] = []
        spans: list[int] = []
        bands: Counter = Counter()
        confidences: Counter = Counter()
        baseline_status: Counter = Counter()
        available_counts: Counter = Counter()
        factor_available: Counter = Counter()
        anchored = 0
        one_sided_only = 0
        completeness_without_coverage = 0
        clamped_low = clamped_high = 0
        exactly_neutral = 0

        for index, day in enumerate(days, 1):
            if index % 100 == 0 or index == len(days):
                print(f"  {index:,}/{len(days):,}", end="\r", flush=True)
            computed = compute_day(session, day)
            r = computed.readiness

            if computed.sleep_baseline is None:
                baseline_status["no baseline object"] += 1
            elif computed.sleep_baseline.reportable:
                baseline_status[
                    "biased" if computed.sleep_baseline.status == STATUS_POTENTIALLY_BIASED
                    else "ok"
                ] += 1
                spans.append(computed.sleep_baseline.span_days)
            else:
                baseline_status["establishing"] += 1

            if getattr(computed, "subjective_anchored", False):
                anchored += 1

            coverages.append(r.coverage_pct)
            confidences[r.confidence] += 1
            bands[r.status] += 1
            live = [c.factor for c in r.components if c.available]
            available_counts[len(live)] += 1
            for factor in live:
                factor_available[factor] += 1
            if live and set(live) <= ONE_SIDED_FACTORS:
                one_sided_only += 1

            if r.score is None:
                # The old bug's signature: plenty of fields recorded, nothing
                # comparable. If this is common, completeness was never the
                # right gate and the change was worth making.
                if computed.data_completeness_pct >= 60.0:
                    completeness_without_coverage += 1
            else:
                scores.append(r.score)
                if r.score <= 0.01:
                    clamped_low += 1
                if r.score >= 99.99:
                    clamped_high += 1
                if abs(r.score - NEUTRAL_SCORE) < 0.01:
                    exactly_neutral += 1

        print(" " * 30, end="\r")
        total = len(days)
        scored = len(scores)

        section("did the baseline change do what was predicted")
        reportable = baseline_status["ok"] + baseline_status["biased"]
        pct = reportable / total * 100 if total else 0
        histogram(baseline_status, ["ok", "biased", "establishing", "no baseline object"], total)
        print(f"\n  reportable sleep baseline on {pct:.1f}% of days")
        print(f"  the 30-day window gave {PREVIOUS_BASELINE_COVERAGE_PCT}% "
              f"(modelled); the prediction for this change was "
              f"{PREDICTED_BASELINE_COVERAGE_PCT}%")
        if pct >= PREDICTED_BASELINE_COVERAGE_PCT - 10:
            print("  -> the prediction holds")
        elif pct > PREVIOUS_BASELINE_COVERAGE_PCT * 2:
            print("  -> better than before, but well short of the prediction.")
            print("     The model assumed a wear pattern; the real one differs.")
        else:
            print("  -> THE CHANGE DID NOT WORK. Investigate before trusting any score.")

        if spans:
            spans.sort()
            print(f"\n  those baselines reach back a median of {spans[len(spans) // 2]} days "
                  f"(90th percentile {spans[int(len(spans) * 0.9)]})")
            print("  a baseline spanning months moves slowly; that is the cost of the change")

        section("what the score actually does across the history")
        print(f"  {scored:,} of {total:,} days scored ({scored / total * 100:.1f}%), "
              f"{total - scored:,} refused")
        histogram(bands, ["green", "amber", "red", STATUS_INSUFFICIENT], total)

        if scores:
            scores.sort()
            def q(p): return scores[min(int(len(scores) * p), len(scores) - 1)]
            print(f"\n  score       min {scores[0]:5.1f}   p25 {q(.25):5.1f}   "
                  f"median {q(.5):5.1f}   p75 {q(.75):5.1f}   max {scores[-1]:5.1f}")
            print(f"  exactly the neutral score ({NEUTRAL_SCORE:.0f}): {exactly_neutral:,}")
            print(f"  clamped at 0: {clamped_low:,}      clamped at 100: {clamped_high:,}")
            if clamped_high > scored * 0.05:
                print("  ! more than 5% pinned at 100 — the top of the scale is compressed")
            if exactly_neutral > scored * 0.10:
                print("    (expected: these are days carried by sleep debt and ACWR with")
                print("     nothing to penalise. They read amber, not green, since the")
                print("     band cap — an absence of penalties is not a good morning)")

        section("how much of the picture each day had")
        coverages.sort()
        def cq(p): return coverages[min(int(len(coverages) * p), len(coverages) - 1)]
        print(f"  coverage    min {coverages[0]:5.1f}%  p25 {cq(.25):5.1f}%  "
              f"median {cq(.5):5.1f}%  p75 {cq(.75):5.1f}%  max {coverages[-1]:5.1f}%")
        histogram(confidences, ["full", "reduced", "partial", "insufficient"], total)

        print("\n  components available per day:")
        for n in sorted(available_counts):
            n_days = available_counts[n]
            print(f"    {n} of 7   {n_days:>6,}  {bar(n_days, total)}")

        print("\n  how often each component could be computed:")
        for factor, n in factor_available.most_common():
            print(f"    {factor:<22} {n:>6,}  {n / total * 100:5.1f}%")

        section("checks that would mean something is wrong")
        near_floor = sum(1 for c in coverages if 0 < c < MIN_COVERAGE_PCT)
        print(f"  days refused with some coverage but under the {MIN_COVERAGE_PCT:.0f}% floor: "
              f"{near_floor:,}")
        print("  days that would have passed the OLD completeness floor with "
              f"nothing computable: {completeness_without_coverage:,}")
        if completeness_without_coverage:
            print("    (each of these is a day the old formula would have scored")
            print("     from thin air — the reason completeness stopped being the gate)")
        print(f"  days whose self-rating used the scale anchor, no personal median: {anchored:,}")

        share = one_sided_only / total * 100 if total else 0
        print(f"\n  days scored ONLY from components that cannot push the score up: "
              f"{one_sided_only:,} ({share:.1f}%)")
        print(f"    ({', '.join(sorted(ONE_SIDED_FACTORS))} are penalties with no credit)")
        if share > 25:
            print("    ! On these days the score's ceiling is the neutral point, so it")
            print("      can only report neutral-or-worse. If this is most days, the")
            print("      median score is being dragged down by which components happen")
            print("      to be available rather than by how the mornings actually went.")
            print("      Worth deciding whether a one-sided component should be allowed")
            print("      to carry a day on its own.")

        biased = baseline_status["biased"]
        if reportable and biased / reportable > 0.9:
            print(f"\n  ! {biased:,} of {reportable:,} reportable sleep baselines are flagged")
            print("    'potentially biased'. A warning that fires on essentially every")
            print("    baseline carries no information. It probably needs to become a")
            print("    quantity — '14 nights across 62 days' — rather than a flag.")

        if total < MIN_DAYS_TO_REPORT:
            print(f"\n  ! only {total} days walked; treat all of the above as indicative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
