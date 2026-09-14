# Comments still to look at

Things noticed in passing and deliberately *not* acted on, with enough context
to pick each one up cold. Nothing here is a commitment. Deleting an entry
because it turned out not to matter is a perfectly good outcome — the point is
that the decision to skip it stays visible instead of evaporating.

Distinct from `outstanding.md`, which tracks work that is *going* to happen and
is blocked on something. This is the maybe pile.

**Last reviewed: 14 September 2026.**

---

## From the 11 Sep review (deferred by the owner, 14 Sep)

| # | Item | Why it was raised | What it would take |
|---|---|---|---|
| R1 | **The Samsung import scans 61M sample pairs, twice** | `nights_with_resting_hr` walks all 133,344 heart-rate samples once per sleep session, and `heart_coverage` does it again. This is why the import is slow | `bisect` on the already-sorted samples. Perhaps 20 lines. No behaviour change |
| R2 | **`no_watch` is collected and never used** | The tag exists specifically to separate "slept badly" from "did not measure" (plan 7.2), but the wear-bias guard infers wear from whether a value exists, so a tagged night is indistinguishable from one the parser missed | Pass the tag through to `sleep_baseline(worn=...)`, which already accepts it |
| R3 | **`WEIGHT_FRESHNESS_DAYS = 1`** | Sensible for a scale that syncs daily; harsh for manual weigh-ins. 63 readings across five years count on 63 days out of 2,042 | Decide what "fresh" means for a weight taken every week or two. A judgement, not a bug |
| R4 | **The daily sync pulls Hevy and Withings only** | Sleep is frozen at the last export date and will silently go stale; the brief keeps narrating mornings with no sleep behind them. Nothing is wrong with the workflow — the gap simply is not visible anywhere | Either surface staleness on the screen, or wait for the Phase 3 companion app (A3), which is the real fix |
| R5 | **`routes_brief.py` sits at 61% coverage** | The lowest in the codebase, and it is the path that sends email | Tests for the send path and the feedback endpoint |

---

## Noticed while reworking readiness (14 Sep)

- **`SUBJECTIVE_ANCHOR = 7.0` is a prior, not a finding.** It decides what a
  self-rating means before fourteen check-ins exist. If his real median turns
  out to be 5, every early morning reads below par until the baseline takes
  over. Self-correcting and clearly labelled, but worth checking against the
  first month of real check-ins rather than leaving on trust.

- **The readiness weights have never been validated.** They were a starting
  point in plan 6.3 and they still are. Now that the score is a mean, the
  weights decide how much each component pulls the average — a more direct
  role than they had as deduction sizes. Worth revisiting once there is enough
  history to check scores against how days actually felt.

- **A 90-day baseline responds slowly.** At 23% wear the observations behind a
  baseline span a median of 62 days, so a genuine change in sleep takes about
  two months to move the median it is measured against. `span_days` is
  reported for exactly this reason, but nothing on the screen shows it yet.

- **`potentially_biased` is now the normal state, not the exception.** At this
  wear rate almost every sleep baseline will carry the flag. A warning that
  fires constantly is a warning nobody reads; it may need to become a
  quantity ("14 nights across 62 days") rather than a flag.

---

## Answered, kept for the record

- **Does the readiness score need extrapolating when data is thin?** No.
  Renormalising the weights and taking a weighted mean are the same equation,
  so there is one honest formula and no choice to make. Settled 14 Sep.
