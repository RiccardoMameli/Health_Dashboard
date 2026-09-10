# Build log

Running record of what has actually been built, against the phases in
`docs/health-dashboard-plan.md`. Newest entry first. Append an entry at the end
of each working session.

---

## 10 September 2026 — the Hevy adapter, verified against the real API

**The first session with real data in it.** 274 workouts, 4331 sets, 31 July
2023 to 8 September 2026. The adapter had only ever been checked against a
hand-written fixture; this replaces that with the account's own history and
fixes what the comparison exposed. 139 tests passing.

### Where the project stands

- **Keys held: Hevy only.** No Withings, Supabase, Anthropic or Resend.
- Overnight watch wear is patchy; the Samsung Health export has not been run.
- Nothing is deployed.
- **Phase 1's gate is still open.** It needs seven consecutive days of
  check-ins *and* a full Hevy and Withings import. Hevy's history is now
  proven importable but has not been imported into a real database, and
  Withings cannot start without credentials. The gate is blocked on key
  collection and a host, not on code.

### The build environment cannot reach Hevy

`api.hevyapp.com` is refused at this environment's egress proxy (403 to
CONNECT). Not a code fault and not something to route around, so the
verification runs on the owner's machine instead. `scripts/verify_hevy.py`
exists for that: it packages the whole check — count against
`/v1/workouts/count`, field-by-field conformance across the entire history,
the volume arithmetic reproduced by hand, date attribution near midnight and
across a BST/GMT boundary — so it produces the same report wherever it runs,
and captures a scrubbed fixture with `--write-fixture`.

That split is worth keeping in mind for Phase 3: **anything needing a real
credential has to run somewhere the credential and the network both are.**

### What the real payload said

Every field the adapter reads exists on every record, with the shape it
expects. The count agrees at 274, there are no duplicate ids, and the volume
hand-check reproduces exactly: 20290.0 both ways on the 7 April legs session,
with 500.0 of warm-up excluded.

Three places reality differed from the fixture, and one from the spec:

1. **Timestamps carry `+00:00`, not `Z`.** The adapter handled both; the
   fixture had been testing a format the account never sends.
2. **`description` and `notes` are `""`, never null.**
3. **`weight_kg` is null on 463 of 4331 sets** — 11%, all bodyweight work.
4. **The published OpenAPI spec is wrong.** It documents `supersets_id`; the
   API sends `superset_id`. Nothing reads it, but it is a reminder that the
   spec is not the territory, which is the whole reason this was checked
   against the live API.

### The finding that mattered

**RPE was null on all 4331 sets.** The owner had never logged it. So
`session_load`'s primary `duration x RPE` branch was unreachable, and three
years of training load came entirely from the volume fallback — with
`Workout.perceived_exertion_1_10` never written by anything, so even a
logged RPE would have gone nowhere.

That is worse than "the second-choice definition". Volume load is dominated
by absolute weight, so it systematically overweights machine leg work:

| Session | Volume load | As duration x RPE |
|---|---|---|
| Upper body, 8 Sep (39 min) | 5024 kg → 50 units | ~313 units |
| Legs, 7 Apr | 20290 kg → 203 units | ~320 units |

Volume ranks the leg day four times harder. It was not. The signal driving
ACWR — and through it readiness — has largely been *"did he train legs?"*
rather than *"how hard did he train?"*. Compounding it, **136 of 274 sessions
(half) contain unweighted sets volume cannot see at all.**

The owner has started logging RPE as a result. That is the fix; no estimation
of bodyweight loads is planned, because `duration x RPE` does not care
whether the load was external, and an estimate built from a bodyweight series
that does not exist yet would be machinery producing a guess.

### Changes

- **Session RPE is aggregated and stored** — the mean of working sets that
  carry one, warm-ups excluded. Not Foster's sRPE; close enough to drive the
  same formula and what per-set logging supports.
- **`_volume_kg` returns None, not 0.0**, when no working set has both a
  weight and reps. Its own docstring said an unquantifiable session must not
  count as zero load; the guard was defeated by the adapter never producing a
  None. As it happens **0 of 274 sessions hit this** — a latent bug, not a
  live one, and worth fixing before a bodyweight-only session abroad finds it.
- **Blank descriptions store as null.**
- **ACWR is withheld across a change of load definition.** The fortnight after
  RPE logging starts, the acute window is RPE-based while the chronic window
  is still volume-based, so the ratio measures the units changing rather than
  the training. Simulated on the real training shape: ACWR 2.80 in week one
  (a full 9-point readiness penalty), 1.75 in week two, back to normal by
  week four. Two weeks of the score marked down for a spike that never
  happened, and a brief obliged to explain it — R2 arriving through the back
  door of a units change. `acwr` now takes a per-day set of load bases and
  declines when the chronic window holds more than one, which is the pattern
  it already used for a too-short window or a zero chronic load.
- **The fixture is eight real scrubbed workouts**, chosen to carry between
  them a warm-up, bodyweight sets, fractional weights, a near-midnight start,
  and one session each from GMT and BST. The six fixture-based tests are
  rewritten against real numbers, and the delete test now proves the other
  seven survive — something a one-workout fixture could not test.

### Two process notes

The first version of `verify_hevy.py` **crashed on Windows** before printing
anything useful: PowerShell writes cp1252, Hevy titles carry emoji, and the
volume hand-check prints titles through `repr()`. Reproduced under
`PYTHONIOENCODING=cp1252` and fixed by forcing UTF-8 on stdout. The report
died on a decorative character rather than on anything it measured.

The raw report files were committed alongside the fixture by accident. They
carry the **unscrubbed** payload — real ids, titles and notes — which defeats
the point of scrubbing the fixture beside them. Removed and gitignored; they
remain in the history of `caba164`, which is cosmetic in a private repo but
worth knowing.

### Next

Withings needs credentials before Phase 1's gate can move, and the Hevy
import needs somewhere to run with both the key and network access. The
readiness score has still never seen real data end to end — every number in
it remains checked against fixtures and simulation.

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
