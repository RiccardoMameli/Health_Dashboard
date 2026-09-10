#!/usr/bin/env python3
"""Run the metrics engine over real imported data and report what it computes.

Run on a machine whose DATABASE_URL points at a database with a real Hevy
backfill in it:

    python scripts/verify_metrics.py
    python scripts/verify_metrics.py --exercise "Bench Press (Dumbbell)"

The companion to `scripts/verify_hevy.py`. That one checked the adapter
against the real API; this one checks the metrics engine against the real
data the adapter produced. Neither can be done from the build container, and
both exist because the same lesson keeps repeating: code that reads correctly
and passes its fixtures still says surprising things when real history goes
through it.

Read-only. It computes and prints; `scripts/daily_brief.py` is what persists.
"""

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date as Date
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.metrics.derived import (  # noqa: E402  # noqa: E402
    ACWR_PENALTY_CEILING,
    ACWR_PENALTY_FLOOR,
    CHRONIC_WINDOW_DAYS,
    LOAD_BASIS_RPE,
    LOAD_BASIS_VOLUME,
    MIN_TRAINING_DAYS_FOR_ACWR,
    acwr,
    acwr_penalty,
    session_load_and_basis,
    volume_progression_slope,
)
from app.models import RawRecord, SyncRun, Workout, WorkoutSet  # noqa: E402
from app.services.metrics_engine import LOAD_WINDOW_DAYS, compute_day  # noqa: E402
from app.services.metrics_engine import _daily_loads as daily_loads  # noqa: E402

#: A day's ACWR needs the 28 days behind it, so the series only becomes
#: meaningful this far in. Matches MIN_DAYS_FOR_ACWR inside `acwr`.
WARMUP_DAYS = LOAD_WINDOW_DAYS


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def whats_in_the_database(session) -> tuple[Date, Date] | None:
    section("what is actually in the database")
    n_workouts = session.execute(select(func.count(Workout.id))).scalar_one()
    n_sets = session.execute(select(func.count(WorkoutSet.id))).scalar_one()
    n_raw = session.execute(select(func.count(RawRecord.id))).scalar_one()
    print(f"  workouts     : {n_workouts}")
    print(f"  sets         : {n_sets}")
    print(f"  raw records  : {n_raw}")
    if n_workouts == 0:
        print("\n  Nothing imported. Run: python scripts/backfill.py --source hevy")
        return None
    if n_raw != n_workouts:
        print(f"  ! raw records ({n_raw}) != workouts ({n_workouts}) — provenance is incomplete")

    first, last = session.execute(select(func.min(Workout.date), func.max(Workout.date))).one()
    span = (last - first).days + 1
    print(f"  date range   : {first} to {last}  ({span} days)")
    print(f"  training days: {len(set(session.execute(select(Workout.date)).scalars()))}")

    for run in session.execute(
        select(SyncRun).order_by(SyncRun.id.desc()).limit(3)
    ).scalars():
        note = f"  {run.error_message}" if run.error_message else ""
        print(f"  sync_run     : {run.source} {run.status} ingested={run.records_ingested}{note}")
    return first, last


def how_load_is_being_computed(session) -> None:
    """Which definition every session's load came from, and what it produced."""
    section("session load: which definition, and what it says")
    rows = []
    for w in session.execute(select(Workout).order_by(Workout.date)).scalars():
        load, basis = session_load_and_basis(
            duration_min=w.duration_min,
            rpe=w.perceived_exertion_1_10,
            volume_kg=w.total_volume_kg,
        )
        rows.append((w, load, basis))

    by_basis: defaultdict[str, list[float]] = defaultdict(list)
    unquantifiable = []
    for w, load, basis in rows:
        if basis is None:
            unquantifiable.append(w)
        else:
            by_basis[basis].append(load)

    for basis in (LOAD_BASIS_RPE, LOAD_BASIS_VOLUME):
        loads = by_basis.get(basis, [])
        if not loads:
            print(f"  {basis:14}: 0 sessions")
            continue
        print(
            f"  {basis:14}: {len(loads):4} sessions   "
            f"median {statistics.median(loads):8.1f}   "
            f"min {min(loads):8.1f}   max {max(loads):9.1f}"
        )
    print(f"  {'unquantifiable':14}: {len(unquantifiable):4} sessions"
          "   (no RPE and no weighted set — load withheld, not zeroed)")
    for w in unquantifiable[:5]:
        print(f"       {w.date}  {w.title!r}  {w.set_count} working sets")

    if by_basis.get(LOAD_BASIS_VOLUME) and not by_basis.get(LOAD_BASIS_RPE):
        print("\n  Every session is volume-based, so load is a proxy for absolute weight")
        print("  moved rather than for effort. The spread below is the consequence:")
        # key= is load-bearing: two sessions can tie on load, and without it
        # the sort falls through to comparing Workout objects and raises.
        ranked = sorted(
            ((load, w) for w, load, b in rows if b == LOAD_BASIS_VOLUME),
            key=lambda pair: pair[0],
            reverse=True,
        )
        print("    heaviest by this measure:")
        for load, w in ranked[:3]:
            print(f"       {w.date}  load {load:8.1f}  {w.duration_min or 0:5.1f} min  {w.title!r}")
        print("    lightest by this measure:")
        for load, w in ranked[-3:]:
            print(f"       {w.date}  load {load:8.1f}  {w.duration_min or 0:5.1f} min  {w.title!r}")
        span = ranked[0][0] / ranked[-1][0] if ranked[-1][0] else float("inf")
        print(f"    ratio heaviest:lightest = {span:.1f}x")
        durations = [w.duration_min for _, w in ranked if w.duration_min]
        if durations:
            print(f"    session duration ranges {min(durations):.0f}-{max(durations):.0f} min, "
                  f"a {max(durations) / min(durations):.1f}x spread")
            print("    A load measure spread far wider than duration is measuring exercise")
            print("    selection more than it is measuring training stress.")


def acwr_across_the_history(session, first: Date, last: Date) -> None:
    """Walk the whole history and see what ACWR would have reported each day."""
    section("ACWR across the whole history")
    loads, bases = daily_loads(session, first, last)
    days = [first + timedelta(days=i) for i in range(len(loads))]

    computed: list[tuple[Date, float]] = []
    withheld_short = withheld_sparse = withheld_mixed = 0
    for i in range(len(loads)):
        if i + 1 < WARMUP_DAYS:
            continue
        window_loads = loads[: i + 1]
        window_bases = bases[: i + 1]
        value = acwr(window_loads, daily_bases=window_bases)
        if value is not None:
            computed.append((days[i], value))
            continue
        # Why not — the three reasons `acwr` declines, told apart.
        chronic_window = window_loads[-CHRONIC_WINDOW_DAYS:]
        seen: set[str] = set()
        for b in window_bases[-CHRONIC_WINDOW_DAYS:]:
            seen |= b
        if len(seen) > 1:
            withheld_mixed += 1
        elif sum(1 for x in chronic_window if x > 0) < MIN_TRAINING_DAYS_FOR_ACWR:
            withheld_sparse += 1
        else:
            withheld_short += 1

    total = len(loads) - WARMUP_DAYS + 1
    print(f"  days assessable        : {total}")
    print(f"  ACWR computed          : {len(computed)}")
    print(f"  withheld, too few days : {withheld_sparse}"
          f"   (under {MIN_TRAINING_DAYS_FOR_ACWR} training days in the 28-day window)")
    print(f"  withheld, mixed units  : {withheld_mixed}")
    print(f"  withheld, other        : {withheld_short}")

    if not computed:
        print("\n  ACWR never computed over this history.")
        return

    values = [v for _, v in computed]
    print(f"\n  median {statistics.median(values):.2f}   "
          f"min {min(values):.2f}   max {max(values):.2f}")
    over_floor = [(d, v) for d, v in computed if v > ACWR_PENALTY_FLOOR]
    over_ceiling = [(d, v) for d, v in computed if v >= ACWR_PENALTY_CEILING]
    pct = 100 * len(over_floor) / len(computed)
    print(f"  above the {ACWR_PENALTY_FLOOR} penalty floor : "
          f"{len(over_floor)} days ({pct:.1f}%)")
    print(f"  at or above the {ACWR_PENALTY_CEILING} ceiling: {len(over_ceiling)} days"
          "   (full ACWR penalty)")
    if over_ceiling:
        print("    worst:")
        for d, v in sorted(over_ceiling, key=lambda x: -x[1])[:5]:
            print(f"       {d}  ACWR {v:.2f}  ->  -{acwr_penalty(v) * 9:.1f} readiness points")
    if pct > 25:
        print("\n  ! Flagged over a quarter of days. Either the training really is that")
        print("    spiky, or the load definition is too sensitive to exercise selection.")


def volume_progression(session, exercise: str | None) -> None:
    """Is overload actually happening, per exercise, over the whole history."""
    section("volume progression by exercise")
    rows = session.execute(
        select(WorkoutSet.exercise_name, Workout.date, WorkoutSet.weight_kg, WorkoutSet.reps)
        .join(Workout, WorkoutSet.workout_id == Workout.id)
        .where(WorkoutSet.set_type != "warmup")
    ).all()

    weekly: defaultdict[str, defaultdict[Date, float]] = defaultdict(lambda: defaultdict(float))
    for name, day, weight, reps in rows:
        if weight is None or reps is None:
            continue
        monday = day - timedelta(days=day.weekday())
        weekly[name][monday] += float(weight) * int(reps)

    ranked = sorted(weekly.items(), key=lambda kv: -sum(kv[1].values()))
    targets = [(exercise, weekly.get(exercise, {}))] if exercise else ranked[:8]
    if exercise and not targets[0][1]:
        print(f"  no weighted sets recorded for {exercise!r}")
        return

    print(f"  {'exercise':38} {'weeks':>5} {'total kg':>11} {'slope kg/wk':>12}")
    for name, by_week in targets:
        if not by_week:
            continue
        weeks = sorted(by_week)
        full = [
            by_week.get(weeks[0] + timedelta(weeks=i))
            for i in range(((weeks[-1] - weeks[0]).days // 7) + 1)
        ]
        slope = volume_progression_slope(full)
        shown = "withheld" if slope is None else f"{slope:+.0f}"
        print(f"  {name[:38]:38} {len(weeks):5} {sum(by_week.values()):11,.0f} {shown:>12}")
    print("\n  Weeks in which an exercise was not trained are dropped, not read as zero:")
    print("  not training a lift is not the same as failing to progress it.")


def what_the_brief_would_see(session, last: Date) -> None:
    """The whole engine on the most recent day with data, gaps and all."""
    section(f"the full engine on {last} (the most recent training day)")
    computed = compute_day(session, last)
    print(f"  data completeness : {computed.data_completeness_pct:.0f}%")
    present = ", ".join(k for k, v in sorted(computed.present.items()) if v) or "nothing"
    missing = ", ".join(k for k, v in sorted(computed.present.items()) if not v) or "nothing"
    print(f"  present           : {present}")
    print(f"  missing           : {missing}")
    print(f"  acute load 7d     : {computed.acute_load_7d}")
    print(f"  chronic load 28d  : {computed.chronic_load_28d}")
    print(f"  acwr              : {computed.acwr}")
    print(f"  days since rest   : {computed.days_since_rest}")
    readiness = computed.readiness
    if readiness is None:
        print("  readiness         : None")
    else:
        print(f"  readiness         : {getattr(readiness, 'score', None)} "
              f"({getattr(readiness, 'status', '?')})")
    print("\n  With no sleep, heart or check-in data this should refuse to score rather")
    print("  than invent one. A number here would be the bug.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise", default=None, help="drill into one exercise by name")
    args = parser.parse_args()

    print(f"database: {get_settings().database_url}")
    with session_scope() as session:
        span = whats_in_the_database(session)
        if span is None:
            return 1
        first, last = span
        how_load_is_being_computed(session)
        acwr_across_the_history(session, first, last)
        volume_progression(session, args.exercise)
        what_the_brief_would_see(session, last)
    print("\nRead-only: nothing above was written to the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
