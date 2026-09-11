#!/usr/bin/env python3
"""Import a Samsung Health export into the canonical store (plan §3.5, D9).

    python scripts/import_samsung_export.py "C:\\path\\to\\export.zip"
    python scripts/import_samsung_export.py <path> --dry-run
    python scripts/import_samsung_export.py <path> --basis local   # only if asked

**It checks the timezone question before it writes anything.** Samsung records
wall-clock times with the offset in a separate column, and whether the clock
reading is local or UTC decides where every night lands. Getting it wrong is
invisible for the half of the year the offset is zero and puts sleep on the
wrong day for the other half — the silent failure the plan calls out.

So the importer derives the answer from the export's own bedtimes rather than
assuming it, and **refuses to run if the data cannot settle it**. --basis
overrides that, and should only be used when someone has established the
answer another way.

Idempotent on (source, source_record_id) like every other ingestion path, so
re-running after a later export is safe.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.adapters.samsung_export import (  # noqa: E402
    BASIS_LOCAL,
    BASIS_UTC,
    HEART_FILE,
    SLEEP_FILE,
    STEPS_FILE,
    WEIGHT_FILE,
    detect_timestamp_basis,
    find,
    format_offset,
    load_export,
    parse_heart_samples,
    parse_naive,
    parse_offset,
    parse_sleep,
    parse_steps,
    parse_weight,
    read_rows,
)
from app.db import session_scope  # noqa: E402
from app.metrics.derived import (  # noqa: E402
    MIN_SAMPLES_FOR_RESTING_HR,
    resting_hr_from_samples,
)
from app.models import ActivityDaily, BodyMeasurement, HeartMetric, SleepSession  # noqa: E402
from app.services.ingest import ensure_day, store_raw, sync_run, upsert  # noqa: E402
from app.services.timeutil import sleep_day  # noqa: E402

SOURCE = "samsung_health"

#: The two columns the basis check reads. Named because the diagnostic script
#: reports against them and the two must not drift apart.
SLEEP_START_COLUMN = "com.samsung.health.sleep.start_time"
SLEEP_OFFSET_COLUMN = "com.samsung.health.sleep.time_offset"

#: Which source rows are kept verbatim, and the columns that identify one.
#: The first column present and non-empty wins, so an export that carries
#: Samsung's own uuid uses it and one that does not falls back to the
#: timestamp, which is unique per row in all three of these files.
#:
#: Sleep keeps the bare uuid so a `raw_records` row lines up with its
#: `sleep_sessions` row; the other two are prefixed because their natural key
#: is a date and would otherwise collide across streams.
RAW_STREAMS: list[tuple[str, str, tuple[str, ...], str]] = [
    (SLEEP_FILE, "sleep", ("com.samsung.health.sleep.datauuid",), ""),
    (STEPS_FILE, "steps_day", ("day_time",), "steps:"),
    (WEIGHT_FILE, "weight", ("com.samsung.health.weight.datauuid", "start_time"), "weight:"),
]

#: Heart-rate readings are deliberately *not* retained row by row. Three years
#: of a worn watch is hundreds of thousands of readings and the canonical store
#: is not the place for them; resting HR is recomputed by re-running this
#: importer against the export file, which is a file the owner keeps. This is
#: the one stream where the raw-retention rule is traded off, and it is traded
#: off knowingly rather than by omission.
RAW_SKIPPED = "heart rate"


def retain_raw(session, files: dict) -> tuple[int, int]:
    """Keep the source rows, so a wrong reading can be fixed without a re-export.

    Rows are collapsed by key before anything is written. The pedometer file
    carries several rows for one day — one per device that counted — so the
    same key arrives more than once, and the session does not autoflush, which
    means `store_raw`'s lookup cannot see a row queued a moment earlier. Two
    inserts for one key then reach the database together and it rejects the
    pair. Last row wins, which is what `store_raw` does for a key it has seen
    before.
    """
    latest: dict[tuple[str, str], dict] = {}
    duplicates = 0
    for stem, record_type, id_columns, prefix in RAW_STREAMS:
        raw = find(files, stem)
        if raw is None:
            continue
        for row in read_rows(raw):
            identifier = next(
                (row[c].strip() for c in id_columns if (row.get(c) or "").strip()), None
            )
            if identifier is None:
                continue
            key = (record_type, f"{prefix}{identifier}")
            if key in latest:
                duplicates += 1
            latest[key] = row

    for (record_type, source_record_id), row in latest.items():
        store_raw(
            session,
            source=SOURCE,
            source_record_id=source_record_id,
            record_type=record_type,
            payload=row,
        )
    return len(latest), duplicates


def nights_with_resting_hr(sessions: list, samples: list) -> dict:
    """Resting HR per night: the low percentile of the readings taken inside
    each sleep session (app.metrics.derived). Not exported by Samsung."""
    samples = sorted(samples)
    out: dict = {}
    for session in sessions:
        inside = [bpm for at, bpm in samples if session.start_at <= at <= session.end_at]
        value = resting_hr_from_samples(inside)
        if value is not None:
            out[sleep_day(session.end_at)] = value
    return out


def heart_coverage(sessions: list, samples: list) -> tuple[int, int, float]:
    """How much heart rate there actually is inside the sleep windows.

    Resting HR comes out of these readings, so a low night count is worth
    explaining before it is blamed on anything. It is usually the watch: the
    reading is only taken while it is worn and the continuous mode is on.

    Note what this does *not* do. Heart rate inherits the sleep file's basis,
    which is an assumption — the export mixes conventions per file, the
    pedometer's `day_time` being local while the sleep file is UTC. Trying to
    settle it by overlap does not work, and an export built with sleep in UTC
    and heart rate in local was measured to confirm that: a one-hour shift on
    a seven-hour window leaves nearly every reading still inside it, so both
    readings scored identically. The saving grace is that the same insensitivity
    makes the assumption cheap — a fifth percentile over a whole night barely
    moves when an hour of it is traded for an adjacent hour.
    """
    samples = sorted(samples)
    per_night = [
        sum(1 for at, _ in samples if session.start_at <= at <= session.end_at)
        for session in sessions
    ]
    with_any = sum(1 for count in per_night if count)
    usable = sum(1 for count in per_night if count >= MIN_SAMPLES_FOR_RESTING_HR)
    counted = [c for c in per_night if c]
    return with_any, usable, median(counted) if counted else 0.0


def _other(basis: str) -> str:
    return BASIS_UTC if basis == BASIS_LOCAL else BASIS_LOCAL


def establish_basis(files: dict, override: str | None) -> str | None:
    """Which reading of the timestamps the data supports."""
    if override:
        print(f"  basis forced to {override!r} — the check was skipped")
        return override

    raw = find(files, SLEEP_FILE)
    if raw is None:
        print(f"  ! no {SLEEP_FILE} in the export; cannot establish the basis")
        return None

    # Three different failures used to arrive here as the same sentence. A
    # file that parses to nothing is a format problem, not an ambiguous
    # timezone, and saying "no usable offsets" about it sends the reader
    # looking in the wrong place.
    rows = read_rows(raw)
    if not rows:
        print(f"  ! {SLEEP_FILE} parsed to zero rows — the header was not found")
        print("    Run scripts/diagnose_samsung_sleep.py against the export.")
        return None

    samples = [
        (
            parse_naive(row.get(SLEEP_START_COLUMN)),
            parse_offset(row.get(SLEEP_OFFSET_COLUMN)),
        )
        for row in rows
    ]
    samples = [(n, o) for n, o in samples if n is not None]
    if not samples:
        print(f"  ! {len(rows):,} rows parsed, but none carried a readable "
              f"{SLEEP_START_COLUMN}")
        print(f"    Columns present: {', '.join(sorted(rows[0])[:6])}...")
        print("    Run scripts/diagnose_samsung_sleep.py against the export.")
        return None

    # Without this, a refusal names two counts and no reason for them. The
    # real export refused on 6 against 3 because those were the extremes of a
    # range that included holidays; seeing the whole distribution is what
    # made that obvious.
    spread = Counter(o for _, o in samples if o is not None)
    print("  offsets present: "
          + ", ".join(f"{format_offset(o)} x{n}" for o, n in spread.most_common(6)))
    if len(spread) > 6:
        print(f"  ({len(spread) - 6} rarer offsets not shown)")

    verdict = detect_timestamp_basis(samples)

    print(f"  {len(samples)} sleep records, "
          f"{verdict.standard_count} in standard time and {verdict.daylight_count} in daylight")
    print(f"  compared {verdict.window}")
    print(f"  reading them as local leaves a {verdict.shift_if_local_hours:.2f}h shift")
    print(f"  reading them as UTC   leaves a {verdict.shift_if_utc_hours:.2f}h shift")
    print(f"  -> {verdict.note}")
    if verdict.window != "clock change":
        print("     ! no clock change had enough records either side, so this")
        print("       rests on winter against summer, which seasonal bedtime")
        print("       drift can bias in either direction.")
    return verdict.basis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--basis", choices=[BASIS_LOCAL, BASIS_UTC], default=None,
                        help="skip the check and force a reading (use sparingly)")
    args = parser.parse_args()

    files = load_export(args.path)
    print(f"=== {len(files)} CSV files in the export ===\n")

    print("=== are the timestamps local or UTC? ===")
    basis = establish_basis(files, args.basis)
    if basis is None:
        print("\nRefusing to import: the basis is not established, and guessing it")
        print("would put sleep on the wrong day for half of every year.")
        print("Re-run with --basis once it is known another way.")
        return 2
    print(f"\n  using: {basis}\n")

    sleep_raw = find(files, SLEEP_FILE)
    sessions = parse_sleep(sleep_raw, basis) if sleep_raw else []
    steps_raw = find(files, STEPS_FILE)
    days = parse_steps(steps_raw) if steps_raw else {}
    weight_raw = find(files, WEIGHT_FILE)
    weights = parse_weight(weight_raw, basis) if weight_raw else {}
    # Weight inherits the sleep basis too, but there the question usually does
    # not arise: an hour only changes a reading's date if the reading is
    # within an hour of midnight. Rather than assume that, count them.
    if weight_raw is not None:
        other = parse_weight(weight_raw, _other(basis))
        moved = sum(1 for day in set(weights) | set(other) if day not in weights
                    or day not in other)
        if moved:
            print(f"  ! {moved} weight reading(s) change date under the other "
                  f"reading of the timestamps — taken near midnight")
        else:
            print("  weight dates are the same under either reading")
    heart_raw = find(files, HEART_FILE)
    samples = parse_heart_samples(heart_raw, basis) if heart_raw else []

    print("=== parsed ===")
    print(f"  {len(sessions):>7,} sleep sessions")
    print(f"  {len(days):>7,} days of steps")
    print(f"  {len(weights):>7,} weight readings")
    print(f"  {len(samples):>7,} heart-rate samples")
    if sessions:
        print(f"  sleep spans {min(s.start_at for s in sessions).date()} "
              f"to {max(s.end_at for s in sessions).date()}")

    resting = nights_with_resting_hr(sessions, samples)
    print(f"  {len(resting):>7,} nights with a derivable resting HR")
    if sessions and samples:
        with_any, usable, typical = heart_coverage(sessions, samples)
        print(f"  {with_any:>7,} nights have any heart rate at all, "
              f"{usable:,} have the {MIN_SAMPLES_FOR_RESTING_HR} a percentile needs")
        print(f"  {typical:>7,.0f} readings on a typical night that has any")
        print("          (the rest are nights the watch was not worn, or was worn")
        print("           without continuous heart rate on — not a parser problem)")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    with session_scope() as session:
        with sync_run(session, SOURCE) as run:
            kept, duplicates = retain_raw(session, files)
            print(f"\n  retained {kept:,} source rows verbatim "
                  f"({RAW_SKIPPED} excepted — see RAW_SKIPPED)")
            if duplicates:
                print(f"  {duplicates:,} rows shared a key with another and were "
                      f"collapsed to the last")
            written = 0
            for record in sessions:
                day = sleep_day(record.end_at)
                ensure_day(session, day)
                existing = session.execute(
                    select(SleepSession).where(
                        SleepSession.source == SOURCE,
                        SleepSession.source_record_id == record.source_record_id,
                    )
                ).scalar_one_or_none()
                fields = {
                    "date": day, "start_at": record.start_at, "end_at": record.end_at,
                    "duration_min": record.duration_min,
                    "efficiency_pct": record.efficiency_pct,
                    "deep_min": record.deep_min, "rem_min": record.rem_min,
                    "light_min": record.light_min,
                }
                if existing is None:
                    session.add(SleepSession(
                        source=SOURCE, source_record_id=record.source_record_id, **fields))
                else:
                    for key, value in fields.items():
                        setattr(existing, key, value)
                written += 1

            for day, values in days.items():
                ensure_day(session, day)
                upsert(session, ActivityDaily, {"date": day}, {**values, "source": SOURCE})
            for day, value in resting.items():
                ensure_day(session, day)
                upsert(session, HeartMetric, {"date": day},
                       {"resting_hr": value, "source": SOURCE})
            for day, values in weights.items():
                ensure_day(session, day)
                upsert(session, BodyMeasurement, {"date": day}, {**values, "source": SOURCE})

            run.records_ingested = written + len(days) + len(resting) + len(weights)
            print(f"  ingested {run.records_ingested:,} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
