# Health Dashboard — API

Personal health aggregation with a deterministic metrics engine and an AI
narration layer. Built to the spec in `docs/health-dashboard-plan.md` (v1.0).

**Status: Phase 1 complete.** Ingestion, check-in, supplements and data health
are working. The metrics engine, readiness score and daily brief are Phase 2.

## The one rule that shapes everything

The metrics engine computes every number in tested code; the LLM receives a
compact pre-computed JSON summary and only prioritises, explains and writes.
Let a model do arithmetic over raw rows and you get plausible fabrication.
Nothing in `app/` sends a time-series to an LLM, and nothing should.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env          # then fill in what you have
alembic upgrade head
python -m app.seed.run        # seeds your supplement stack + protocol start rows
uvicorn app.main:app --reload
```

Interactive docs at http://localhost:8000/docs.

SQLite works out of the box for local development. Production is Supabase
Postgres — set `DATABASE_URL` and the same migrations apply.

## What is here

| Path | What it does |
|---|---|
| `app/models/` | Canonical schema, all 20 tables from plan §5.2 |
| `app/adapters/hevy.py` | Backfill + incremental sync via `/workouts/events` |
| `app/adapters/withings.py` | OAuth2, weight and body composition, token rotation |
| `app/services/ingest.py` | Idempotent upsert, raw provenance, sync bookkeeping |
| `app/services/timeutil.py` | UTC storage, London rendering, sleep-day boundary |
| `app/api/` | Check-in, supplements, sync, data health, export |
| `alembic/` | Migrations. Never hand-edit tables. |
| `scripts/backfill.py` | One-off deep history import |

## Endpoints

```
GET    /health                              public liveness probe
POST   /api/v1/checkin                      submit (only overall_1_10 required)
GET    /api/v1/checkin/status               streak, completion rate, prefill
GET    /api/v1/supplements/checklist        today's scheduled items only
POST   /api/v1/supplements/log/all          the two-tap path
POST   /api/v1/supplements/protocol-changes the important half — dated changes
GET    /api/v1/withings/authorize           start the OAuth handshake
POST   /api/v1/sync/{source}?mode=backfill  trigger a sync
GET    /api/v1/sync/health                  data health: staleness, wear rate
GET    /api/v1/today                        Today screen payload
GET    /api/v1/export                       full JSON export
```

All `/api/v1` routes take `Authorization: Bearer $API_TOKEN`. Single user, no
registration endpoint — that alone removes most of the attack surface.

## Connecting your sources

**Hevy** — generate a key at `hevy.com/settings?developer` (needs Pro), set
`HEVY_API_KEY`, then `python scripts/backfill.py --source hevy`. Workouts page
at 10 per request, so a deep backfill is slow. It runs once.

**Withings** — register a personal app at developer.withings.com, set the
client ID/secret and redirect URI, then visit `/api/v1/withings/authorize` and
approve. Follow with `--source withings` for full history.

Withings rotates the refresh token on every refresh and kills the old one
immediately. The adapter persists the new pair in the same transaction; if you
touch that code, keep that property or sync dies silently in a fortnight.

## Design decisions worth knowing before you change something

**Sleep belongs to the day it ends.** A session running 23:40 Tuesday to 07:10
Wednesday is Wednesday's. This is unit-tested against both 2026 BST/GMT
transitions because the failure mode is silent — a session filed against the
wrong day just quietly decorrelates sleep from how you felt.

**Warm-up sets are excluded from volume load.** Otherwise a deload week with
long warm-ups reads as a hard week.

**Nulls are never written over existing data.** A source with nothing to say
about protein must not erase protein another source supplied.

**Everything is idempotent on `(source, source_record_id)`.** Re-running any
sync is always safe, which is what lets you fix an adapter and simply run it
again. Raw payloads are retained forever, including through deletes.

**A failed sync is recorded, not swallowed.** Adapters are constructed inside
the sync-run bookkeeping so a missing key shows up on the Data Health screen
rather than vanishing into a 500. Silent ingestion failure is the most common
way a self-hosted dashboard rots.

**No number the system cannot compute.** `/api/v1/today` returns
`readiness: null` in Phase 1 rather than a placeholder score.

## Testing

```bash
pytest -q      # 41 tests
ruff check app tests
```

CI runs the suite, lints, and verifies migrations build the schema from
scratch and tear back down.

## Not done yet

Phase 2: metrics engine (baselines, deviations, sleep debt, training load,
weight EWMA), readiness score with component breakdown, the daily brief and
email delivery.

Phase 3: the Expo app, Health Connect ingestion, push notifications, and the
Samsung Health historical import.

`sleep_sessions`, `heart_metrics` and `activity_daily` have tables and no
writer until Phase 3 — that is deliberate, so the migration history does not
need rewriting later.

## Open items

- **O2**: MyFitnessPal does not sync macros. Decide before Phase 3 whether to
  switch to Cronometer or MacroFactor. Protein g/kg stays NULL until then.
- **HRV/SpO2** availability via Health Connect is unverified. The fallback
  readiness formula (sleep + resting HR + subjective) is the assumption until
  it is tested on a real device.
