# Comments still to look at

Things noticed in passing and deliberately *not* acted on, with enough context
to pick each one up cold. Nothing here is a commitment. Deleting an entry
because it turned out not to matter is a perfectly good outcome — the point is
that the decision to skip it stays visible instead of evaporating.

Distinct from `outstanding.md`, which tracks work that is *going* to happen and
is blocked on something. This is the maybe pile.

**Last reviewed: 15 September 2026** (after the readiness verification sweep).

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

- **A 90-day baseline responds slowly** — but measurement on 15 Sep says this
  worry was misplaced. The real median span is **30 days**, not 62: most
  reportable baselines come from the preferred window, and the widening fires
  on a minority. `span_days` is still unshown on any screen.

- ~~**`potentially_biased` is now the normal state, not the exception.**~~
  **Measured 15 Sep against the real history: 425 biased against 204 ok, so
  67.6% — not the ~100% a synthetic run suggested.** The flag does carry
  information. Leave it alone. Recorded because the synthetic inference was
  wrong and the correction is worth more than the original note.

---

## Open after the 15 Sep verification sweep

- **2023 has no sleep data at all**, and 2026 holds 19 nights against 2024's
  250. Worth knowing before reading anything into year-over-year figures.

- **2026's median is 396 min against 455 and 471 in the two years before it.**
  On 19 nights that is probably noise, but if it is real it is an hour less
  sleep a night and by far the most interesting thing in the dataset. Worth
  re-checking once the Air produces a denser sample.

- **The 10% coverage floor never fires.** Zero days across five years were
  refused with partial coverage below it; every refusal was at 0% coverage.
  The constant is currently decorative. Harmless, but it means the floor is
  not doing the job it was reasoned about, and a future change to the weights
  could silently make it bite.

---

## Answered, kept for the record

- **Did widening the baseline window to 90 days work?** Partly. It was
  predicted to take sleep-baseline availability from 2.8% to 69.9% of days;
  measured against the real history on 15 Sep it gives **30.8%**. The
  prediction came from a model of his wear pattern that got the cluster
  structure wrong — real wear is dense streaks separated by long dead periods,
  and outside a streak even 90 days does not hold 14 nights. The change is a
  real improvement and is keeping, but the figure quoted in CLAUDE.md and the
  build log was wrong and is corrected.

- **Should a one-sided component be allowed to carry a day on its own?** Yes,
  but not to award green. Measured on 15 Sep: 47% of scored days had nothing
  available but sleep debt and ACWR, both penalties with no credit, so their
  ceiling was the neutral score — and 113 of them landed exactly on it and
  rendered green beside fully measured good days. Fixed the same day by
  capping the band at amber when no two-sided component is available. The
  number is untouched; only what it is called changes. Withholding the score
  entirely was rejected: it would have blanked 352 days, against the owner's
  standing instruction that the dashboard stay useful when he forgets to
  measure.

- **Should the baseline cap move past 90 days?** Yes, to 180. Done 15 Sep.
  Coverage 27.4 / 30.8 / 36.1 / 46.2% for 30 / 90 / 180 / 365. Safe because
  the norm is stable (2024 and 2025 sixteen minutes apart) and because on the
  days it adds the alternative was no score at all. Stopped at 180 rather than
  365 so the window stays inside one seasonal half. `span_days` now shows on
  the sleep tile, so a baseline reaching five months back says so.

- **Does the readiness score need extrapolating when data is thin?** No.
  Renormalising the weights and taking a weighted mean are the same equation,
  so there is one honest formula and no choice to make. Settled 14 Sep.
