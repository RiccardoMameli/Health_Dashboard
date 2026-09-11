# Outstanding

Everything known to be needed and not done, with what actually unblocks each
item. Kept separate from `build-log.md`, which records what *has* been built.

**Last reviewed: 11 September 2026** (Samsung export imported).

Nothing here is forgotten work — it is deferred work, and the difference is
that this file exists. Review it at the start of a working session.

---

## The gate situation, stated plainly

Phase 1's acceptance test is *seven consecutive days of check-ins **and** a
full Hevy and Withings import* (plan §14). Hevy is done — 274 workouts,
verified against the live API and imported. **Withings is deferred as of 10
Sep 2026, so Phase 1's gate cannot close.**

That is a deliberate decision, not an oversight. The consequence is that any
Phase 2+ work from here is being done past an open gate, which plan §14 and
R7 both warn against. Recorded so the decision stays visible rather than
becoming an accident.

Phase 0's gate is also half-open: `alembic upgrade head` builds the schema,
but no health-check endpoint returns 200 in production because nothing is
deployed.

---

## A. Deferred by decision (10 Sep 2026)

| # | Item | Why deferred | What unblocks it |
|---|---|---|---|
| A1 | **Withings integration** | No developer credentials; OAuth2 flow needs a browser redirect | Register a personal app at developer.withings.com, put client id/secret in `.env`, complete the OAuth flow once |
| A2 | ~~**Samsung Health export**~~ | **Done 11 Sep 2026.** 461 sleep sessions, 1,950 days of steps, 63 weight readings, 159 nights of resting HR, Feb 2021 to Sep 2026 | Nothing. Re-run the importer against a fresh export whenever more history is wanted; it is idempotent |
| A3 | **Sleep ingestion, ongoing** | Needs the Phase 3 companion app; no cloud API exists (plan §3.3). History is covered by A2; the nightly feed is not | The Expo dev build. Until then sleep stops at the date of the last export |

The Samsung parser deliberately leaves HRV, sleep stages as a series, stress,
SpO2, skin temperature, respiratory rate, floors and Samsung's own exercise
records unread. HRV is the one worth returning to: the values sit inside
`binning_data` JSON blobs rather than a column. None of them is in
`EXPECTED_DAILY_FIELDS`, so none of them moves completeness.

Two things the real export taught that the fixtures could not: the sleep file
stores UTC while the pedometer's `day_time` is local midnight, so a basis
established on one file must not be assumed for another; and the pedometer
carries about 2.7 rows per day, one per device that counted, so a day's step
figure is a choice between them rather than a reading.

**The adapters for A1 exist as live code and have never seen a real response.**
That is exactly where the Hevy adapter was on the morning of 10 Sep, before
checking it against reality found four wrong assumptions. Assume the same is
true of Withings until proven otherwise.

---

## B. Blocked on an account or a key

| # | Item | Needed for | Cost |
|---|---|---|---|
| B1 | Withings developer app | A1 | Free |
| B2 | Supabase project | Postgres in production; Phase 0's gate | Free tier |
| B3 | A host (Fly.io or Render) | Anything reachable from a phone; Phase 0's gate | Free-to-hobby tier |
| B4 | Anthropic API key | The daily brief. Without it the job fails loudly rather than sending a template | Usage-based, ~2 calls/day |
| B5 | Resend key + verified sender | Email delivery of the brief | Free tier |
| B6 | Healthchecks.io | The dead-man's switch on the daily sync | Free |

None of these is expensive. All of them are ten-minute signups. They are the
single largest blocker on the project and none of them is code.

---

## C. Blocked on elapsed time and habit

These cannot be compressed by writing anything. The clock starts when the
behaviour starts, not when the code ships.

| # | Item | Why it takes real time |
|---|---|---|
| C1 | **Seven consecutive check-ins** | Half of Phase 1's gate. Day one cannot happen retroactively |
| C2 | **Overnight watch wear, 5+ nights/week** | Baselines are a 30-day rolling median withheld below 14 observations, so nothing can be computed for at least two weeks after wear begins. Sporadic wear is worse than none: it biases the baseline every deviation is measured against (§3.3, S6) |
| C3 | **Seven days of accurate briefs** | Phase 2's gate. Cannot begin until Phase 1 closes and B4 exists |

---

## D. Needs building, not blocked by anything

**Direction set 10 Sep 2026:** get to a working MVP and iterate on the UI
before adding integrations that cannot pay off until the sleep stream exists.
The Today screen came first for that reason.

| # | Item | Phase | Notes |
|---|---|---|---|
| D1 | **Check-in form** | 1 | **Now the binding constraint on the whole score.** Samsung supplies 4 of the 7 completeness fields, which is 57.1% against a 60% floor — 2.9 points short, so a fully-measured night still reads `insufficient_data`. One subjective field typed by hand crosses it. Deferred on 10 Sep for want of a screen and sleep data; both now exist, and C1 cannot start until it does |
| D2 | ~~Minimal Today screen~~ | 1 | **Done 10 Sep 2026.** `GET /ui` serves the Glacier reference from the backend with a "Live — my data" view reading `/api/v1/today`. Half the screen is still hand-written placeholder markup — the check-in card, supplements, source timestamps and header date — and says so in live mode |
| D3 | Wire the remaining live tiles | 1–2 | Check-in state, supplement adherence and source timestamps are still design markup. Needs D1 and a data-health call. Sleep and RHR sparklines need a short series on `/today`, which is pointless until there is sleep data (A2/A3) |
| D4 | Eval set for the brief (§9.4) | 2 | ~15 hand-picked days including a no-watch day and a missing-macros day |

---

## E. Verified unknowns

| # | Item | Resolution |
|---|---|---|
| E1 | **HRV and SpO2 via Health Connect** | Samsung confirms sleep, heart rate, steps and exercise reach Health Connect. It does not confirm HRV, SpO2 or body composition. `HRV_AVAILABLE=false` until tested on the actual watch |
| E2 | Hevy API rate limits | Undocumented. The adapter throttles at 0.35s and backs off on 429; 28 sequential pages completed without incident on 10 Sep |
| E3 | Free-tier limits for B2–B6 | Researched 3 Sep 2026; re-verify at signup |

---

## F. Open items carried from the plan

- **O2** — MyFitnessPal does not sync macros. Decide before Phase 3 whether to
  switch to Cronometer or MacroFactor. `protein_g_per_kg` stays NULL until then.
- **O4** — Per-muscle-group recovery view (plan §14.1 F1). Recorded, not
  scheduled; earliest Phase 4.

---

## G. Known cosmetic debt

- `hevy-report*.txt` remain in the history of commit `caba164`. Unscrubbed
  training data in a private repo. Removable only by rewriting history; judged
  not worth it, recorded so the judgement is visible rather than forgotten.
