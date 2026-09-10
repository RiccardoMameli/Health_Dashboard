# Build log

Running record of what has actually been built, against the phases in
`docs/health-dashboard-plan.md`. Newest entry first. Append an entry at the end
of each working session.

---

## 10 September 2026 — the data reaches a screen

The morning's session got real Hevy data in. This one put it in front of a
reader, and found that most of what was wrong was in the parts nobody had
looked at yet. 163 tests passing.

### The screen exists

`GET /ui` serves the Glacier reference from the backend, fetching
`/api/v1/today` on load. The four hand-written mornings are gone — an example
on a screen whose job is showing what is yours is worse than a blank — so the
live view is the only view. The page is unauthenticated because it is markup;
the browser holds the bearer token for the data behind it.

**Pointing the design at real data broke it four times**, none of which the
four designed mornings could expose, because all four carry data in every
field:

1. `renderTraining` called `acwr.toFixed(2)` unguarded. ACWR is null more often
   than not for this account, so the live view threw on arrival.
2. `renderWeight` took `vals[vals.length - 1].toFixed(1)` on an empty series
   and aborted the whole render, leaving the page half-drawn — which is why
   the first screenshot showed a mix of correct and stale values.
3. `renderRhr` on an all-null series computed `Math.min` of nothing, put NaN
   in a circle's `cy`, and the browser rejected it.
4. The intro roll-up animation writes `#score` every frame for 1.1s after
   load, counting to a hard-coded 62. Click into a no-score morning inside
   that window and it painted 62 back over the em-dash — **a fabricated
   readiness score sitting under a "no score" label**, on the screen whose
   entire purpose is to never do that. It had been there since the design was
   drawn on 3 September and only surfaced because an automated click was
   faster than a human usually is.

### A splice that duplicated half the page

Removing the design-language section searched for `"MyFitnessPal"` to find the
end of a row and matched an earlier occurrence — "MyFitnessPal does not sync
macros", further up. End landed before start, so `t[:a] + t[b:]` concatenated
the overlap instead of removing it, and the entire tile block rendered twice.

Nothing threw. `getElementById` returns the first match, so the live render
updated one copy and left the other showing the design's hand-written values:
a second set of entirely plausible tiles. Two things stop it recurring: every
splice now searches for its closing marker from the opening marker's position
and asserts `end > start`, and **a test asserts every id on the page is
unique**. The assertion caught the same class of bug again during the rebuild.

### Layout, and what the screen refuses to claim

Twelve cards of equal weight meant nothing said where to look. Split into
*This morning* — readiness, brief, yesterday's session, weight, sleep trend —
and *The record* below it. Three new tiles drawn and marked Coming soon, every
value an em-dash: sleep consistency as nights-at-target out of seven rather
than a mean, which would hide exactly the inconsistency worth seeing; steps;
and energy balance as two bars on one shared scale, because the gap between
them is what is being read.

Everything invented is gone — a "day 12 of 42" phase counter, a 93% supplement
adherence rate, an 11-day streak, an 87% completion figure, four made-up sync
timestamps. What is not built is greyed and labelled rather than hidden. Dates
are DD-MM-YYYY; the API keeps ISO because it sorts unambiguously.

### The metrics engine, against real data for the first time

`scripts/verify_metrics.py` runs the engine over the real backfill. What it
found, on 274 workouts:

- **The load-definition problem, confirmed by the owner's own workout titles.**
  A 13.0x spread between heaviest and lightest session against 4.1x in
  duration. The three heaviest are "Big leg day + abs", "Legs + abs", "Legs";
  the three lightest "Quick chest day", "Quick chest day", "Quick Push day".
  "Legs + abs" ran 18% longer than "Quick chest day" and scored 8.8x the load.
- **ACWR flagged 27% of assessable days**, 27 of them at the full penalty, in
  consecutive clusters — consistent with leg days bunching, not with
  overreaching.
- **ACWR could not compute on 638 of 1109 days.** It needs 8 training days per
  28; the history averages 1.69 sessions a week. It will be unavailable more
  often than not, so readiness leans on sleep and subjective more than the
  design assumed.
- **Volume progression is flat.** Every slope is under half a percent of the
  weekly mean — `+13 kg/wk` on calf extension reads like progress and is 0.19%.
- **The ACWR-of-4.0 guard fired on real data.** On 8 September acute was 50.24
  against chronic 12.56 — exactly 4.0, the spurious value the 3 September
  session fixed against fixtures. It returned None, because only one training
  day sat in the window.

### Qualifying a number rather than suppressing it

The tempting response to a 27% flag rate was to withhold ACWR while load is
volume-derived. The owner's call was the better one: *build for the data you
intend to feed, not the data you have.* RPE logging has started, and in a
month the same code path carries the definition it was designed for.

So `load_quality` reports which definition produced the chronic window —
`rpe_based`, `volume_based`, `mixed` — and travels with acute, chronic and
ACWR through the §9.1 contract, `/today`, and a new `daily_metrics` column so
a stored ratio is still readable a year on. **The caveat wording lives in
tested code**, and prompt rule 4 requires the model to reproduce it verbatim
rather than compose its own: a caveat the model writes is a caveat it can
soften on a day it wants a cleaner story. Migration 0002, nullable with no
backfill — rows computed before the column existed genuinely do not know their
basis, and backfilling "volume_based" would be an assumption dressed as a
record.

### The recovery figure (§14.1 F1)

Two schematic silhouettes beside the readiness gauge, each muscle group shaded
by how recently and how hard it was worked. The data path already existed:
every set carries an `exercise_template_id`, and Hevy's
`/v1/exercise_templates/{id}` returns its own muscle-group vocabulary. A new
`exercise_templates` table caches them (migration 0003); the sync walks only
the distinct ids present in `workout_sets`.

**Four states, no percentage.** "Chest: 60% recovered" reads as measured and is
not. Windows vary by group — 36h for biceps and calves against 72h for quads
and the posterior chain — and stretch with volume relative to the owner's own
median for that group, which *is* a measurement. On real data the separation
shows: triceps read likely ready while chest is still recovering from the same
session. A group never worked reports "not trained", not "ready".

**The existing "no time series" test earned its place.** `muscle_recovery` is
seventeen rows of hours and volumes, and it went into `build_brief_input`
before the test caught it. It now reaches `/today` only.

Two follow-ups came from the owner looking at it. The empty-figure note blamed
setup regardless of cause, so a genuine rest week would have read as a broken
install; `muscle_recovery_status` now distinguishes unmapped, no recent
training, and ok. And the template sync — 166 distinct exercises on this
account — gave a silent minute of terminal and committed nothing until the
end, so an interrupted run discarded everything. It now reports progress and
commits every 20; verified by killing a run on its 55th request and watching
40 templates survive and the re-run resume.

### The finding that decides what happens next

Readiness needs 5 of 7 fields to clear the 60% completeness floor. Samsung
Health supplies 4 of them — sleep duration, sleep efficiency, resting HR,
steps. Withings, MyFitnessPal and the check-in supply one each.

**Without Samsung the ceiling is 3 of 7, or 43%.** Every other source
connected, a perfect check-in streak, and the score still reads
`insufficient_data` forever. With Samsung plus any one other source it works.

The dashboard is a good training dashboard. It is not yet a health dashboard,
and no further code changes that.

### Also

`docs/outstanding.md` records everything deferred, grouped by what would
actually unblock it — six items are free signups, three cannot be compressed
by writing any code. Merging to `main` on green is now the working agreement:
three times work sat on a feature branch while the owner was on `main`, and
each time the symptom was a confusing failure rather than an obvious one.

Removed `metrics-report.txt`, committed before the gitignore pattern covering
it landed — gitignore does not untrack a tracked file.

### Next

The Samsung Health export, or the check-in form and somewhere to host it so
the seven-day clock starts. Neither is blocked by code.

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
