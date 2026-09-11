#!/usr/bin/env python3
"""Why did the sleep file parse to nothing?

    python scripts/diagnose_samsung_sleep.py "C:\\path\\to\\Samsung Health Export"

The importer refuses when it cannot read the sleep file, which is correct but
does not say *which* assumption broke. This prints what the parser actually
sees — the filename it matched, the first few raw lines, which line it chose
as the header, and whether the two columns the basis check needs are there.

It reads only. It prints column names in full and truncates every data value,
so the output is safe to paste back.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.samsung_export import (  # noqa: E402
    SLEEP_FILE,
    decode,
    load_export,
    parse_naive,
    parse_offset,
    read_rows,
)

START = "com.samsung.health.sleep.start_time"
OFFSET = "com.samsung.health.sleep.time_offset"

#: Values are clipped rather than printed whole. The point is the shape of the
#: file, and a sleep record is still personal data.
CLIP = 40


def clip(value: str) -> str:
    value = value.strip()
    return value if len(value) <= CLIP else value[:CLIP] + "..."


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    files = load_export(Path(sys.argv[1]))
    print(f"=== {len(files)} CSV files ===\n")

    matches = sorted(n for n in files if n.startswith(SLEEP_FILE + "."))
    near = sorted(n for n in files if "sleep" in n.lower() and n not in matches)
    print(f"matched {SLEEP_FILE}.* :")
    for name in matches or ["  (none)"]:
        print(f"  {name}")
    if near:
        print("\nother sleep-ish files in the export (not read):")
        for name in near:
            print(f"  {name}")
    if not matches:
        print("\n-> nothing matched. That is the problem.")
        return 1

    raw = files[matches[0]]
    lines = decode(raw).splitlines()
    print(f"\n=== {matches[0]}: {len(lines):,} lines ===")
    for index, line in enumerate(lines[:4]):
        print(f"  [{index}] {len(line.split(','))} fields | {clip(line)}")

    rows = read_rows(raw)
    print(f"\n=== read_rows returned {len(rows):,} rows ===")
    if not rows:
        print("-> the header was not found. The lines above are what it chose from.")
        return 1

    columns = sorted(rows[0])
    print(f"  {len(columns)} columns:")
    for name in columns:
        print(f"    {name}")

    print("\n=== the two columns the basis check needs ===")
    for wanted in (START, OFFSET):
        present = wanted in rows[0]
        print(f"  {wanted}: {'present' if present else 'MISSING'}")

    print("\n=== first three rows, as the parser reads them ===")
    for row in rows[:3]:
        start, offset = row.get(START), row.get(OFFSET)
        print(f"  start={clip(start or '')!r:<46} -> {parse_naive(start)}")
        print(f"  offset={clip(offset or '')!r:<45} -> {parse_offset(offset)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
