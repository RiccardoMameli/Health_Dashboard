#!/usr/bin/env python3
"""Resolve the exercise ids in your history to muscle groups.

    python scripts/sync_exercise_templates.py

One request per distinct exercise you have actually performed — a few dozen,
throttled — and only for ids not already cached, so re-running is cheap. This
is what makes the recovery figure possible: every set already carries an
`exercise_template_id`, and this turns those into Hevy's own muscle-group
vocabulary rather than a mapping guessed from exercise names here.

Needs network access to api.hevyapp.com and HEVY_API_KEY, so it runs wherever
the backfill runs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.adapters.hevy import HevyAdapter  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import ExerciseTemplate, WorkoutSet  # noqa: E402
from app.services.ingest import sync_run  # noqa: E402


def main() -> int:
    if not get_settings().hevy_api_key:
        print("HEVY_API_KEY is not set. Put it in .env (not .env.example).")
        return 2

    with session_scope() as session:
        distinct = session.execute(
            select(func.count(func.distinct(WorkoutSet.exercise_template_id)))
        ).scalar_one()
        cached = session.execute(select(func.count(ExerciseTemplate.id))).scalar_one()
    print(f"{distinct} distinct exercises in your history, {cached} already resolved")

    try:
        with session_scope() as session:
            with sync_run(session, "hevy") as run:
                result = HevyAdapter().sync_exercise_templates(session)
                run.records_ingested = result.records_ingested
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"  resolved {result.records_ingested}, skipped {result.records_skipped}")
    for note in result.notes:
        print(f"  note: {note}")

    with session_scope() as session:
        rows = session.execute(
            select(ExerciseTemplate.primary_muscle_group, func.count(ExerciseTemplate.id))
            .group_by(ExerciseTemplate.primary_muscle_group)
            .order_by(func.count(ExerciseTemplate.id).desc())
        ).all()
    if rows:
        print("\n  exercises by primary muscle group:")
        for group, count in rows:
            print(f"    {group or '(none)':16} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
