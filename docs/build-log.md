# Build log

Running record of what has actually been built, against the phases in
`docs/health-dashboard-plan.md`. Newest entry first. Append an entry at the end
of each working session.

---

## 10 September 2026 — status check, and the first attempt at real Hevy data

**No application code changed.** Environment set up, migrations and seed run
against a local SQLite database, and the Hevy adapter audited against the
published API specification. **The real import did not happen** — two blockers,
below.

### Where the project actually stands

- Repo unchanged since the two commits of 3 September; both are now on GitHub.
- **Keys held: Hevy only.** No Withings, Supabase, Anthropic or Resend.
- Overnight watch wear is patchy, and the one-off Samsung Health export has
  still not been run.
- Nothing is deployed.
- **Phase 1's acceptance gate is not passed** and has not moved: it needs seven
  consecutive days of check-ins plus a full, correct Hevy and Withings import.
  Withings cannot start at all without its credentials, so the gate is blocked
  on key collection, not on code.

Phase 0's gate is likewise still half-met — schema builds, no production
health check — for the same reason.

### Local environment

Python 3.11.15, `.venv`, `pip install -e ".[dev]"`. `alembic upgrade head`
builds all 20 tables on SQLite; the seed creates the eight-item supplement
stack. 126 tests pass, `ruff check app tests` clean. `.env` written with
`DATABASE_URL=sqlite+pysqlite:///./health.db` and every key left blank.

### Blocker 1 — the Hevy API is not reachable from the build environment

`api.hevyapp.com` is refused at the egress proxy (403 to CONNECT). This is an
environment policy, not a code fault and not something to route around, so the
"verify against the real API rather than the fixture" work cannot be done from
here regardless of the key. It needs either a host that can reach the API or a
scrubbed real response captured elsewhere and committed as the fixture.

### Blocker 2 — the key is not in the environment

`.env` carries `HEVY_API_KEY=` with a comment saying where to paste it. Until
it is set the backfill fails, which it did:

```
=== hevy backfill ===
  FAILED: RuntimeError: HEVY_API_KEY is not set
```

Worth recording that this is the *correct* failure. The `sync_runs` table has
the row — `status=failed`, `error_message=RuntimeError: HEVY_API_KEY is not
set` — rather than a silent skip. That is the R6 failure mode the 3 September
session fixed, verified against a real missing key for the first time.

### What the audit against the OpenAPI spec found

The adapter was checked field by field against the published Hevy
specification. This is weaker than a real response but stronger than the
hand-written fixture, which is the only thing it had been checked against.

**Every field the adapter reads exists with the name and shape it expects.**
Envelope (`workouts`, `events`, `page_count`), workout (`id`, `title`,
`description`, `start_time`, `end_time`, `exercises`), exercise (`title`,
`exercise_template_id`, `sets`) and set (`index`, `type`, `weight_kg`, `reps`,
`rpe`, `distance_meters`, `duration_seconds`) all match, as do the `updated`
and `deleted` event shapes. The `pageSize` cap of 10 is confirmed.

Four things the fixture does not cover, in rough order of how much they matter:

1. **Volume load is not the primary load definition, and nothing says so.**
   `session_load` prefers `duration x RPE` and falls back to volume. But
   `Workout.perceived_exertion_1_10` is **never written** — the Hevy adapter
   does not set it, and no other writer exists. Hevy carries RPE *per set*,
   which the adapter stores on `workout_sets` and never aggregates. So for
   every Hevy workout the primary branch is dead code and training load runs
   entirely on the fallback. ACWR, and through it readiness, currently rests
   on a definition the plan treats as the second choice.
2. **A bodyweight or cardio session records as zero load, not as unknown.**
   `_volume_kg` returns `0.0` when no set has both a weight and reps — which
   is exactly what pull-ups, dips, planks and treadmill work look like in
   Hevy. `session_load`'s docstring says an unquantifiable session "must not
   silently count as zero load", and its `None` guard is defeated because the
   adapter writes `0.0` rather than `None`. A real training day would land in
   the chronic-load window as a rest day.
3. **`dropset` and `failure` set types are untested.** The spec lists four set
   types; the fixture has two. The adapter counts both toward volume and the
   working-set count, which is probably right, but it is untested and unstated.
4. **The fixture is thinner than a real payload.** It omits `routine_id`,
   `updated_at`, `created_at`, per-exercise `notes` and `supersets_id`, and
   per-set `custom_metric`; real sets send `distance_meters` and
   `duration_seconds` as explicit nulls rather than omitting them. The adapter
   uses `.get()` throughout so none of this breaks, but the fixture's `id`
   ends `tc001` and is not a valid UUID, which is a fair summary of how
   hand-written it is.

Also noted: `/v1/workouts/count` exists and is unused. It is the cheap
cross-check that a backfill imported everything, and the backfill should
assert against it.

**None of 1–4 has been changed.** They are findings, not fixes; 1 and 2 are
decisions about what training load means, which is not a call to make silently
inside an adapter.

### Not verified, and still open

Date attribution near midnight, the total-volume hand-check on a real workout,
and the workout count and date range all need the real data. Note for when it
arrives: a workout is attributed to the local date it **started**
(`local_date(start_at)`), which is deliberate but written down nowhere — only
sleep belongs to the day it ends. A session starting 23:50 and ending 00:40
counts to the day it began.

### Next session

Get a real Hevy response, from a machine that can reach the API. Then the
backfill, the count and date-range check, the hand-verified volume figure, and
a scrubbed real payload committed as the fixture. Decide 1 and 2 above before
readiness is trusted against real training data.

---

## 3 September 2026 — UI preview made deployable and explorable

`docs/ui/glacier-today.html` now renders from a data object rather than fixed
markup, with a switcher for four mornings: accumulating, nothing unusual,
overreached, and watch-not-worn. The last one is the point of the exercise —
`insufficient_data` renders as an absent arc, an em-dash and "no score", with
both the sleep and resting-HR tiles showing gaps and the brief refusing to make
a training recommendation. Claiming the design handles that is cheap; looking
at it is not.

`netlify.toml` publishes `docs/ui` as a static site. **The backend cannot go on
Netlify** — there is no Python runtime for Netlify Functions — so FastAPI still
needs Fly.io or Render per §4.3.

Two bugs found by rendering the states rather than reasoning about them:

1. **An unscoped `.bar` rule.** The sleep chart's `.bar{flex:1}` also claimed
   the brief caveat's 2px amber rule, stretching it into a wide filled block.
   Scoped to `.bars .bar`. It had been wrong since the design was first drawn.
2. **A zero-length arc still paints its round cap**, leaving a coloured dot on
   the no-score gauge that read as a very low score. The arc is now hidden
   outright when there is nothing to draw.

And one found by running the suite on a machine that finally had a real key in
`.env`: **the tests were not hermetic.** `Settings` reads `.env`, so a live
`HEVY_API_KEY` turned two "this source is unconfigured" assertions red locally
and nowhere else — CI has no `.env` and stayed green. The dotenv path is now
`ENV_FILE`, which `conftest.py` sets to empty. Verified both ways: 126 pass
with a populated `.env` present and with none at all.

---

## 3 September 2026 — Phase 2: metrics engine, readiness, the brief

**Status: Phase 2 code complete. The phase *gate* is not met and cannot be met
by writing code — it needs seven consecutive days of an accurate brief against
real data.** 126 tests passing.

### What exists

- **`app/metrics/`** — pure functions, no database, no clock. Baselines
  (30-day rolling median, withheld below 14 observations, D3 wear-bias guard),
  derived metrics (sleep debt, midpoint variance, session/acute/chronic load,
  ACWR, weight EWMA and trend, protein g/kg, completeness, volume
  progression), and the §6.3 readiness score with its component breakdown.
- **`app/services/metrics_engine.py`** — the only module that knows both SQL
  and the metrics. Windows the data, drops excluded days, persists
  `daily_metrics`, and renders the §9.1 input contract.
- **`app/ai/`** — the phase-locked system prompt, the structured output
  contract, the Anthropic call, and the traceability guard.
- **`app/services/email.py`** — the brief rendered in the Glacier language,
  restricted to what mail clients support.
- **`scripts/daily_brief.py`** and a step in the sync workflow — the 06:30 job,
  idempotent, with meaningful exit codes.
- Endpoints: `POST /brief`, `GET /brief/{day}`, `GET /brief/input/{day}`,
  `GET /brief/{day}/preview`, `POST /brief/{id}/feedback`, `GET /metrics/{day}`.
  `/today` now carries real readiness.

### The traceability guard

Plan §14's Phase 2 gate is "every number in it traces back to the input JSON".
That is now checked in code rather than trusted: every numeric token in a
generated brief is matched against the input snapshot, with one retry naming
the offending figures, and the brief is stored flagged if it still does not
trace. A unit conversion counts as a violation — "5h42m" from a stored 342
minutes is arithmetic the model was told not to do, and it reads exactly like
a measurement. The guard caught two of its own test fixtures during the build.

### Four things found by looking at real output

1. **ACWR of 4.0.** Four sessions in an otherwise empty month gave a ratio
   that was arithmetically correct and meaningless. ACWR is now withheld until
   the chronic window holds at least eight training days.
2. **A single bad reading took a third of the scale.** Z-scores are now
   clamped at ±2 SD rather than ±3: past two, the difference between bad and
   very bad on one metric is not information the score should act on.
3. **SD floors were too tight.** A 15-minute floor on night-to-night sleep
   variation made an ordinary short night a three-sigma outlier. Raised to
   values that are plausible minimums rather than implausible ones.
4. **Two definitions of "weight trend".** The Today endpoint had its own
   7-vs-7 average difference, contradicting the engine's EWMA slope. Deleted;
   there is now one definition. Supplement adherence had the same problem and
   moved to `app/services/supplements.py`.

### Decisions worth recording

- **Readiness lands in Phase 2, not Phase 4.** §14 lists it under Phase 4, but
  the §9.1 input contract carries `readiness`, so the brief cannot be built
  without it. Noted in the plan.
- **Weights are provisional and configurable.** Scaled so a single bad night
  stays amber while an accumulating pattern goes red. Nothing in six weeks of
  baseline data can validate them.
- **The phase never promotes itself.** `BRIEF_PHASE` is config and stays on
  `baseline` until deliberately changed. A brief must not start making causal
  claims because six weeks elapsed.
- **No template fallback.** With no API key the job fails loudly rather than
  sending something that looks generated.

### Outstanding, not code

1. Keys: Anthropic, Resend, plus the Phase 0 set still outstanding.
2. **The readiness score has never seen real data.** Every number above was
   checked against seeded fixtures and a simulation with realistic variance.
3. Phase 1's gate is still open: seven days of check-ins, and a full Hevy and
   Withings import.

### Next session

Phase 3 is gated on Phase 2's acceptance test, so the useful work before then
is the eval set (§9.4: ~15 hand-picked days including a no-watch day and a
missing-macros day) and the Expo app's Today screen against `docs/ui/`.

---

## 3 September 2026 — UI design language locked

**No application code changed. Documentation and one static reference file.**

Settled the visual direction before Phase 2 starts, so the brief renderer and
the Expo app are built against a decided language rather than an improvised one.

- **Plan §10.3 — "Glacier"** added: colour tokens for both themes, the three
  type roles, materials and grid, component specs (readiness gauge, brief,
  metric tile, micro-charts, gaps, chips, phase pill), motion and accessibility.
- **`docs/ui/glacier-today.html`** — the reference implementation. The Today
  screen from §10.1, in both themes, rendered from the §9.1 example payload
  (readiness 62 amber with reduced confidence, sleep 342 min against a 430
  baseline, RHR 58 vs 52, ACWR 1.27, weight EWMA 84.2). Static HTML, no build
  step. Also published as an artifact:
  <https://claude.ai/code/artifact/6cd4ddae-46e7-4fe4-b70a-f7f37dd87b95>

### The decision that matters

Four of the invariants are now enforced by the visual system rather than left
to the copy: a missing night is a hatched dashed column and an unavailable
metric is an em-dash with its reason; the phase pill is permanent chrome; status
colour is separated from the accent and always carries its word; every figure is
tappable to its definition. `insufficient_data` has a designed appearance — the
empty dashed arc — which is what stops a placeholder score ever being invented
for it.

### Not yet designed

The other six screens (Trends, Training, Body, Supplements, Experiments, Data
health) inherit the tokens but have no composition. The phone layout is
specified as an ordering, not drawn. Both are Phase 3 work.

---

## 3 September 2026 — Phase 0 + Phase 1 backend

**Status: both phase gates met, with one caveat (below).**

### Decisions taken this session

| Item | Decision |
|---|---|
| O1 — frontend | Expo, one codebase (plan default) |
| O2 — nutrition app | Stay on MyFitnessPal, calories only. Protein reports as unavailable. Revisit before Phase 3. |
| O3 — sleep target | 7h30 (450 min), in config as `SLEEP_TARGET_MIN` |
| Keys | None held yet — built against fixtures; adapters are live code, not stubs |
| Scope | Backend only. No UI this session. |

### What exists

FastAPI backend, 41 tests passing.

- **Schema** — all 20 tables from plan §5.2, one Alembic migration
  (`0001_initial_schema`). Verified to build and tear down on SQLite and to
  render correct DDL for Postgres (JSONB, `TIMESTAMP WITH TIME ZONE`).
- **Ingestion** — raw payloads retained forever with provenance; idempotent
  upsert on `(source, source_record_id)`; `sync_runs` bookkeeping.
- **Hevy adapter** — paged backfill and incremental sync via
  `/workouts/events`, handling both update and delete events. Volume load
  excludes warm-up sets.
- **Withings adapter** — OAuth2 authorisation-code flow, `Measure - Getmeas`
  parsing with unit-exponent scaling, and rotated-refresh-token persistence.
- **Check-in API** — partial submissions accepted, all 13 confounder tags live
  from day one, 3-day backfill flagged `submitted_late`, streak and 30-day
  completion rate.
- **Supplements** — the eight-item stack seeded with dated protocol-start
  rows, schedule-aware daily checklist, protocol change log.
- **Data health** — per-source staleness, overnight wear rate, check-in
  completion. Failed syncs are recorded, not swallowed.
- **Ops** — CI workflow, daily-sync cron with a Healthchecks dead-man's
  switch, gitleaks pre-commit hook, Dockerfile, full JSON export endpoint.

### Two bugs found and fixed during the build

1. **Naive datetimes from SQLite.** Postgres preserves the offset, SQLite
   discards it, so any comparison against an aware datetime raised. Fixed with
   a `TZDateTime` type decorator that normalises on the way in and out — the
   test database now behaves identically to production, and a naive datetime
   reaching the database raises loudly rather than being silently stored.
2. **Adapter construction outside the sync-run bookkeeping.** A missing API
   key produced a bare 500 with no `sync_runs` row, so the Data Health screen
   would have reported nothing wrong. Adapters are now constructed inside the
   run. This is exactly the R6 failure mode.

### Caveat on the Phase 0 acceptance test

The plan's Phase 0 gate is "`alembic upgrade head` builds the full schema **and
a health-check endpoint returns 200 in production**". The first half passes.
The second cannot until a Supabase project and a host exist.

### What is deliberately absent

`sleep_sessions`, `heart_metrics` and `activity_daily` have tables and no
writer. They fill in Phase 3 via Health Connect. Creating them now means the
migration history does not need rewriting later.

`/api/v1/today` returns `readiness: null` rather than a placeholder score.
Phase 2 owns the metrics engine.

### Outstanding, not code

1. Phase 0 key collection: Hevy (`hevy.com/settings?developer`), Withings
   developer app, Supabase project, Anthropic API key, Resend, Healthchecks.
2. **Run the Samsung Health export.** Ten minutes, does not expire, and it is
   what makes baselines meaningful from week one rather than week six.
3. **Start wearing the watch overnight, 5+ nights a week.** The baseline clock
   starts when the data does, not when the code ships.

### Next session

Phase 2: the metrics engine (baselines, deviations, sleep debt, training load,
weight EWMA), the readiness score with component breakdown, the daily brief
against the §9 contracts phase-locked to `baseline`, and email delivery.
