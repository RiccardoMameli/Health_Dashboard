# Health Dashboard — working agreement

Personal health dashboard for a single user (Ricky). Aggregates Samsung Health,
Hevy, Withings and MyFitnessPal into one canonical store, computes metrics
deterministically, and layers an AI narration on top.

**The full specification is `docs/health-dashboard-plan.md`. Read it before
making architectural decisions.** `docs/build-log.md` records what has actually
been built, newest entry first — append to it at the end of a working session.

## Current state

Phase 1 complete: schema, ingestion, Hevy and Withings adapters, check-in and
supplement APIs, data health.

Phase 2 code complete: metrics engine (`app/metrics/`, pure functions),
readiness score, the DB assembler (`app/services/metrics_engine.py`), the
daily brief with its traceability guard (`app/ai/`), email delivery, and the
06:30 job (`scripts/daily_brief.py`). 139 tests passing.

The Hevy adapter is verified against the live API (10 Sep 2026, 274 workouts)
and its fixture is real scrubbed data. The metrics engine has now run over
that real history too (`scripts/verify_metrics.py`). Withings and the
readiness score have still only ever seen fixtures.

`GET /ui` serves the Today screen against live data, with the per-muscle
recovery figure (plan §14.1 F1).
Every tile with data behind it is wired (24 Sep 2026 review), and the
supplements card ticks for real; only energy balance (O2) is a placeholder.

**The sleep target is 8h** (`SLEEP_TARGET_MIN=480`, changed from 7h30 on
24 Sep 2026). A `.env` copied from the old example still says 450 and
overrides the default — check it.

The Samsung Health export parser (`app/adapters/samsung_export.py`,
`scripts/import_samsung_export.py`) is **verified against the real export and
imported** (11 Sep 2026): 461 sleep sessions, 1,950 days of steps, 63 weight
readings and 159 nights of derived resting HR, spanning Feb 2021 to Sep 2026.
236 tests passing.

It **proves whether the timestamps are local or UTC and refuses to write
anything if the data cannot settle it.** The answer for the sleep file turned
out to be UTC, against the inference that had been carried until then — the
export mixes conventions per file, the pedometer's `day_time` being local
midnight. The check is made across a daylight-saving change rather than
across the seasons, because seasonal bedtime drift is the same size as the
error being looked for.

The check-in form is built and live at `GET /ui/checkin` — one tap for a valid
check-in, everything else optional.

**Readiness was reworked on 14 Sep 2026 and no longer matches plan 6.3's
formula.** It is a weighted mean over the components that could be computed,
not a sum of deductions from 100. The plan's formula gave a component with no
data a contribution of zero, which is what a component sitting exactly on its
baseline contributes — so the less the system knew, the better the day looked.
A real morning scored 94 and green on five hours' sleep and a 3/10 self-rating.

What follows from the mean: **coverage — the share of weight that could
actually be evaluated — is now the gate, at 10%**, not field completeness.
Completeness counts fields *recorded*; a recorded value with no baseline has
no deviation to score, so a day could read 71% complete with nothing
computable. The floor is deliberately low because the owner does not wear a
watch every night and a dashboard that goes blank when he forgets is one that
stops being opened. Every partial score carries its coverage and a sentence
naming what it rests on.

**Baselines prefer 30 days and widen to 180 when too sparse** (set 15 Sep
2026). Measured over all 2,041 days (`scripts/verify_readiness.py`): 30 days
alone gives a reportable sleep baseline on 27.4% of days, 90 gives 30.8%,
**180 gives 36.1%**, 365 gives 46.2%.

180 and not 365 because six months stays inside one seasonal half where a year
blends summer and winter sleep. Safe because his norm is stable — 2024 and
2025, the only years with enough nights to judge, sit 16 minutes apart — and
because on the days a wider cap adds, the alternative is not a fresher
baseline but **no score at all**.

**The honesty mechanism is `span_days`**, shown on the Today screen's sleep
tile as "25 nights over 151 days". A baseline reaching five months back is
fine as long as it says so.

Do not quote a coverage figure for this that did not come from a run against
his database. Three wrong ones have been published already — 69.9% from a
model, then 19.5% and "widening past 90 buys nothing" from an 87-day
synthetic fixture.

**Consequence: most days still cannot be scored.** 752 of 2,041 days score,
1,289 refuse at 0% coverage.

**Green means measured and good.** Sleep debt and ACWR are penalties with no
credit, so a day carried by those alone has the neutral score as a ceiling:
the best it can say is "nothing adverse is visible". That described 47% of
scored days, 113 of which sat exactly on neutral and rendered green. Since
15 Sep the band is **capped at amber when no two-sided component is
available** — the number is untouched, only its colour and wording change.

**Samsung Health is historical only as of 15 Sep 2026 (plan D14).** The
overnight sensor becomes a **Fitbit Air**, and sleep, resting HR, HRV and SpO2
will arrive over the **Google Health API** (`health.googleapis.com/v4/`,
Google OAuth2) — a cloud endpoint, which Health Connect never had. That takes
the companion app off the critical path: the nightly feed becomes a
server-side adapter like Hevy's, not a phone app.

Two unknowns gate it, and the first is serious: **every Google Health API
scope is Restricted**, and an unverified app stays in Testing where refresh
tokens expire after seven days — a weekly silent break on a daily cron
(plan R14). Settle that before building. Second, it is unconfirmed whether the
API serves third-party data that reached Google Health via Health Connect;
nothing is designed to depend on it.

Until that adapter exists, sleep stops at the date of the last export.

Phase 2's *gate* is not met and cannot be met by writing code: it needs seven
consecutive days of an accurate brief against real data. Same for Phase 1's
gate — seven days of check-ins and a full Hevy/Withings import.

## Invariants — do not break these

**The LLM never does arithmetic.** The metrics engine computes every number in
tested code. The AI layer receives a compact pre-computed JSON summary and only
prioritises, explains and writes. Never pass a raw time-series to a model. This
is the single most important decision in the system; violating it produces
confident fabrication that is very hard to detect.

This is *enforced*, not trusted: `app/ai/verify.py` checks every number in a
generated brief against the input snapshot, retries once naming the offending
figures, and flags the brief if it still does not trace. A unit conversion
counts as a violation — "5h42m" from a stored 342 minutes is arithmetic.

**Phase-locked language.** Briefs carry a `phase` field. In `baseline` (first
six weeks) causal claims are forbidden — facts and deviations only. In
`associative` every claim carries a sample size and a hedge. Only in
`experimental`, and only for a completed experiment with a computed effect
size, may anything be stated as established. Enforce this in the prompt
contract, not in the model's judgement.

**Missing data is a first-class concept.** A null is a null, never a zero, and
never an interpolation. Never explain a day the system cannot see, and never
let a gap read as normality — silence and "exactly average" must not produce
the same number. This will happen regularly: the watch is not worn every
night, and that is expected.

The gate is **coverage**, not completeness, and it is 10% (changed 14 Sep
2026; the old rule was completeness below 60%). Below it emit
`insufficient_data`; above it emit a score that states what it rests on. The
change was made because the old floor measured fields recorded rather than
components computable, and a day could pass it with nothing to compare against
— which is how a five-hour night scored 94.

**Sleep belongs to the day it ends**, in local time. Store UTC, render
Europe/London. Tested against both 2026 BST/GMT transitions. The failure mode
here is silent.

**Everything is idempotent** on `(source, source_record_id)`. Re-running any
sync must always be safe. Raw payloads are retained forever, including through
deletes.

**Nulls never overwrite existing data.** A source with nothing to say about a
field must not erase what another source supplied.

**Failed syncs are recorded, not swallowed.** Construct adapters inside the
sync-run bookkeeping. Silent ingestion failure is the most common way a
self-hosted dashboard rots.

**No medical advice.** No diagnosis, no dosing instructions, no interaction
advice. Sustained abnormalities produce a plain statement that it warrants a GP
conversation and no attempt to explain it. Never suggest intake or weight
targets that trend toward restriction.

## Conventions

- Migrations via Alembic only. Never hand-edit tables.
- Every metric is a pure function with unit tests against fixtures.
- Adapters implement `Adapter` (`backfill` / `incremental`).
- Secrets come from the environment. Never commit a key; gitleaks runs pre-commit.
- Run `pytest -q` and `ruff check app tests` before committing.
- Weights, thresholds and windows live in `app/config.py` or as named module
  constants with a comment saying why that number. No bare magic numbers.

## Delivery

**Merge to `main` as soon as CI is green** (decided 10 Sep 2026). Work is
pushed to the feature branch, CI is verified there, and then merged straight
to `main` unless the owner says otherwise. He stays on `main` permanently and
only ever pulls.

This is not a style preference. Three separate times, work sat on a feature
branch while he was on `main`, and each time the symptom was a confusing
failure — a missing script, then a 404 — that cost a round trip to diagnose.
A single-user project where the owner is the only reviewer gains nothing from
a long-lived branch and loses a working session to it.

## Phase gates

Do not start a phase until the previous one's acceptance test passes. The gates
are in §14 of the plan. They exist because scope creep is the most likely way
this project dies (R7).

## Open items

**`docs/comments-to-revisit.md` is the maybe pile** — things noticed and
deliberately not acted on. Not commitments; deleting one is a fine outcome.

**`docs/outstanding.md` is the full list** — what is deferred, what is blocked
on a key, what is waiting on elapsed time, and what is simply unbuilt. Read it
at the start of a session. Note that Withings is deferred as of 10 Sep 2026,
so **Phase 1's gate cannot close** and any further work is past an open gate,
deliberately.


- **O2**: MyFitnessPal does not sync macros. Decide before Phase 3 whether to
  switch to Cronometer or MacroFactor. `protein_g_per_kg` stays NULL until then.
- **O5**: The long record (plan §14.1 F2) — coverage by month, weight against
  training volume, sleep by weekday and season, resting HR over years, with an
  export to hand to a GP. Wanted 14 Sep 2026. Reads only what is already
  imported, so it is blocked on nothing but a decision to start.
- **O4**: Per-muscle-group recovery view (plan §14.1 F1). Recorded, not
  scheduled — earliest Phase 4. Muscle groups are resolvable from Hevy's
  exercise templates using data already imported; steps and stairs need Phase
  3. A "% recovered" per muscle would be fabricated precision from a lookup
  table, so the design shows hours-since-stimulus and volume as facts with the
  recovery window as a labelled population band.
- **HRV/SpO2** availability via Health Connect is unverified. Until it is
  tested on a real device, assume the fallback readiness formula (sleep,
  resting HR, subjective).
