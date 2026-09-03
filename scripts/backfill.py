#!/usr/bin/env python3
"""One-off deep history import (plan 3.5, D9).

    python scripts/backfill.py --source all
    python scripts/backfill.py --source withings --since 2020-01-01

Hevy pages at 10 workouts per request, so a deep backfill is slow. That is
fine; it runs once. Run it before Phase 2 so baselines are meaningful from
week one rather than week six.
"""

import argparse
import sys
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.adapters.hevy import HevyAdapter  # noqa: E402
from app.adapters.withings import WithingsAdapter  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.services.ingest import sync_run  # noqa: E402

ADAPTERS = {"hevy": HevyAdapter, "withings": WithingsAdapter}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="all", choices=[*ADAPTERS, "all"])
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    targets = list(ADAPTERS) if args.source == "all" else [args.source]
    failed = False

    for name in targets:
        print(f"\n=== {name} backfill ===")
        try:
            with session_scope() as session:
                with sync_run(session, name) as run:
                    result = ADAPTERS[name]().backfill(session, since=args.since)
                    run.records_ingested = result.records_ingested
            print(f"  ingested {result.records_ingested}, skipped {result.records_skipped}")
            for note in result.notes:
                print(f"  note: {note}")
        except Exception as exc:
            failed = True
            print(f"  FAILED: {type(exc).__name__}: {exc}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
