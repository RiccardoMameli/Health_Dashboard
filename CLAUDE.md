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
06:30 job (`scripts/daily_brief.py`). 126 tests passing.

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
never an interpolation. If completeness is below 60%, emit `insufficient_data`
rather than a score. Never explain a day the system cannot see. This will
happen regularly — the watch is not worn every night, and that is expected.

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

## Phase gates

Do not start a phase until the previous one's acceptance test passes. The gates
are in §14 of the plan. They exist because scope creep is the most likely way
this project dies (R7).

## Open items

- **O2**: MyFitnessPal does not sync macros. Decide before Phase 3 whether to
  switch to Cronometer or MacroFactor. `protein_g_per_kg` stays NULL until then.
- **HRV/SpO2** availability via Health Connect is unverified. Until it is
  tested on a real device, assume the fallback readiness formula (sleep,
  resting HR, subjective).
