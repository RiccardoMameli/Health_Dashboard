# Build log

Running record of what has actually been built, against the phases in
`docs/health-dashboard-plan.md`. Newest entry first. Append an entry at the end
of each working session.

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
