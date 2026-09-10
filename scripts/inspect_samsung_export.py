#!/usr/bin/env python3
"""Report the structure of a Samsung Health export, without dumping the data.

    python scripts/inspect_samsung_export.py "C:\\path\\to\\export.zip"
    python scripts/inspect_samsung_export.py "C:\\path\\to\\samsunghealth_folder"
    python scripts/inspect_samsung_export.py <path> --full-rows   # if asked for

Accepts the zip or the extracted folder. Prints an inventory, then for the
files that matter: which line the real header is on, the column names, and
**one example value per column** rather than whole rows — enough to see the
timestamp format, the units and the sentinel values, which is what a parser
has to get right, without shipping a year of sleep records into a chat.

Written before any parser exists, deliberately. The Hevy adapter was built
against a hand-written guess at the payload and four of its assumptions turned
out to be wrong; the only reason that was cheap to find was looking at the real
thing first. Same method here.

Nothing is written and nothing is uploaded — it reads and prints.
"""

import argparse
import csv
import sys
import zipfile
from pathlib import Path

#: The files that carry the four fields readiness is waiting on, plus the ones
#: worth knowing about. Matched as substrings of the filename, because Samsung
#: prefixes with a package name and suffixes with a timestamp.
INTERESTING = [
    ("sleep", "sleep — the backbone of the whole system"),
    ("heart_rate", "heart rate, including resting HR"),
    ("pedometer", "steps"),
    ("step_count", "steps"),
    ("floors", "stairs climbed"),
    ("exercise", "workouts (Hevy is the source of truth; useful for cardio)"),
    ("weight", "weight, if the scale ever wrote here"),
    ("body_composition", "body composition"),
    ("food", "nutrition"),
    ("nutrition", "nutrition"),
    ("stress", "stress"),
    ("oxygen", "SpO2"),
]

#: Samsung writes a metadata line above the real header on most exports. Reading
#: line 1 as the header is the single easiest way to build a parser that looks
#: like it works and silently mislabels every column.
MAX_HEADER_SCAN = 4


def decode(raw: bytes) -> str:
    """Samsung exports have appeared as UTF-8, UTF-8-BOM and UTF-16."""
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\x00" not in text:
            return text
    return raw.decode("utf-8", errors="replace")


def find_header(lines: list[str]) -> tuple[int, list[str]]:
    """The header is the first line that parses into several non-empty names.

    A metadata line is typically one or two fields; the real header is a dozen
    or more. Returns the index and the parsed names.
    """
    best = (0, [])
    for i, line in enumerate(lines[:MAX_HEADER_SCAN]):
        fields = next(csv.reader([line]), [])
        named = [f.strip() for f in fields if f.strip()]
        if len(named) > len(best[1]):
            best = (i, named)
    return best


def example_values(rows: list[list[str]], columns: list[str]) -> dict[str, str]:
    """The first non-empty value seen for each column.

    One value per column, not whole rows: it shows the format — the timestamp
    shape, the units, whether a gap is empty or a sentinel — which is what a
    parser needs, at a fraction of the exposure.
    """
    out: dict[str, str] = {}
    for row in rows:
        for index, name in enumerate(columns):
            if name in out or index >= len(row):
                continue
            value = row[index].strip()
            if value:
                out[name] = value[:60]
    return out


def describe(name: str, raw: bytes, why: str, full_rows: bool) -> None:
    text = decode(raw)
    lines = text.splitlines()
    header_line, columns = find_header(lines)

    body = list(csv.reader(lines[header_line + 1 :]))
    body = [r for r in body if any(f.strip() for f in r)]

    print(f"\n{'─' * 70}\n{name}\n  ({why})")
    print(f"  bytes {len(raw):,} · {len(body):,} data rows")
    if header_line:
        print(f"  ! the real header is on line {header_line + 1}, not line 1")
        print(f"    line 1 reads: {lines[0][:90]!r}")
    print(f"  {len(columns)} columns:")
    samples = example_values(body[:200], columns)
    for column in columns:
        value = samples.get(column, "(never populated in the first 200 rows)")
        print(f"    {column:44} = {value}")
    if full_rows and body:
        print("\n  first 3 rows verbatim:")
        for row in body[:3]:
            print(f"    {row}")


def collect(path: Path) -> list[tuple[str, bytes]]:
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            return [
                (info.filename, archive.read(info))
                for info in archive.infolist()
                if not info.is_dir()
            ]
    if path.is_dir():
        return [
            (str(f.relative_to(path)), f.read_bytes())
            for f in sorted(path.rglob("*"))
            if f.is_file()
        ]
    sys.exit(f"Not a zip or a folder: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="the export .zip or the extracted folder")
    parser.add_argument("--full-rows", action="store_true",
                        help="also print three whole rows per file (more data; only if asked)")
    args = parser.parse_args()

    files = collect(args.path)
    if not files:
        print("Nothing found at that path.")
        return 1

    print(f"=== inventory: {len(files)} files ===")
    for name, raw in sorted(files, key=lambda f: -len(f[1])):
        print(f"  {len(raw):>12,}  {name}")

    print("\n\n=== structure of the files that matter ===")
    seen = set()
    for keyword, why in INTERESTING:
        for name, raw in files:
            lower = name.lower()
            if keyword in lower and name not in seen and lower.endswith(".csv"):
                seen.add(name)
                try:
                    describe(name, raw, why, args.full_rows)
                except Exception as exc:   # a malformed file should not stop the report
                    print(f"\n{name}\n  ! could not parse: {type(exc).__name__}: {exc}")

    if not seen:
        print("  none matched. Paste the inventory above and I will work from the real names.")

    jsons = [n for n, _ in files if n.lower().endswith(".json")]
    if jsons:
        print(f"\n\n=== {len(jsons)} JSON files ===")
        print("  Samsung puts per-night sleep-stage detail here, too nested for CSV.")
        for name in jsons[:5]:
            print(f"    {name}")
        if len(jsons) > 5:
            print(f"    ... and {len(jsons) - 5} more")

    print("\n\nNothing was written or uploaded. Read the output before sending it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
