"""Parse a Samsung Health export (plan §3.5, D9).

There is no Samsung cloud API (§3.3), so deep history arrives as a one-off
export: a zip of CSVs, one per data type, written by the phone. This module
turns those into records the canonical schema can hold. It is not an `Adapter`
— there is nothing to poll — it reads a file that a human produced.

Three things about the format matter more than the rest, all of them found by
inspecting a real 744 MB export rather than by assuming:

1. **The real header is on line 2.** Line 1 carries the package name and a
   version. Reading line 1 as the header produces a parser that runs happily
   and mislabels every column.

2. **Timestamps are wall-clock, with the offset in a separate column.** A row
   reads `2022-07-22 23:10:00.000` alongside `UTC+0100`. Which of those two is
   the instant depends on whether Samsung wrote local time or UTC, and the
   difference is invisible for the half of the year the offset is zero. That
   question is not assumed here — `detect_timestamp_basis` answers it from the
   data, and the importer refuses to run if the answer is not clear.

3. **A zero can mean "not measured".** `efficiency` is `0.0` on sessions that
   have no efficiency, while `original_efficiency` carries the real figure on
   the ones that do. Storing the zero would put a fabricated 0% into a column
   the metrics engine reads as measured — the "a null is a null" invariant
   failing in the one direction that is hard to see.
"""

from __future__ import annotations

import csv
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean

#: Samsung exports have appeared as UTF-8, UTF-8 with a BOM, and UTF-16.
ENCODINGS = ("utf-8-sig", "utf-8", "utf-16")

#: Line 1 is metadata; the header is below it. Scanned rather than assumed
#: fixed, because the depth has moved between app versions.
MAX_HEADER_SCAN = 4

OFFSET_RE = re.compile(r"^UTC([+-])(\d{2})(\d{2})$")

#: The metadata line reads like `com.samsung.shealth.sleep,7006011,11`: a
#: package name and two integers. Recognising it directly matters because the
#: fallback rule — the line whose width the data rows agree with — cannot tell
#: it apart from a header that happens to have three columns, and the
#: heart-rate file is exactly that shape.
METADATA_RE = re.compile(r"^[a-z][\w.]*\.[\w]+$", re.I)

#: A column name: an identifier, optionally dotted. Data values are numbers,
#: timestamps, `UTC+0000` and hyphenated uuids, none of which match.
COLUMN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")

#: How much of a line must read as column names before it is treated as the
#: header. A real header scores 1.0. A data row scores near zero — the only
#: values that can match are a package name or a bare alphanumeric token, and
#: a row is not made of those. 0.8 leaves room for an export that puts a
#: stray value in a header cell without letting a data row through.
HEADER_NAME_FRACTION = 0.8

#: Below this a line is too short to judge by that fraction: one identifier in
#: a one-cell line is 100% and means nothing.
MIN_HEADER_CELLS = 2

#: A daylight-saving step. The seasonal pair of offsets is the pair this far
#: apart, which is what distinguishes it from a pair of travel offsets.
DST_STEP_MINUTES = 60

#: How far either side of a clock change the test looks. Bedtimes drift with
#: the season — later in summer for most people, earlier for some — and a
#: whole-season comparison cannot separate that drift from a timezone error,
#: because both move the summer group. The direction decides which way it
#: lies: a later summer bedtime biases towards `local`, an earlier one
#: towards `utc`. Across six weeks the drift is minutes, while a timezone
#: error is still the full hour, because one is gradual and the other is a
#: step at the transition instant.
DST_WINDOW_DAYS = 21

#: Two records bracketing an offset change locate the change only if they are
#: close together. Further apart than this and the transition date is not
#: known well enough to centre a window on.
MAX_TRANSITION_BRACKET_DAYS = 14

#: Records at the epoch are sentinels, not observations. The real export has
#: one in the HRV file. Stored, it would sit in every baseline window forever.
EPOCH_CUTOFF = datetime(1990, 1, 1, tzinfo=UTC)

BASIS_LOCAL = "local"
BASIS_UTC = "utc"


def decode(raw: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\x00" not in text:
            return text
    return raw.decode("utf-8", errors="replace")


def read_rows(raw: bytes) -> list[dict[str, str]]:
    """Rows as dicts, with the header found rather than assumed."""
    lines = decode(raw).splitlines()
    if not lines:
        return []

    # The header is identified by what it is made of, not by how many fields
    # it has. Width-based rules have failed here three times, and the last
    # one failed on the real export: its sleep header has 62 fields and every
    # data row has 63, so "the width the data rows agree with" scored the
    # header at zero, elected a data row, and produced a table whose column
    # names were `0`, `UTC+0000` and a uuid. Nothing threw.
    #
    # Column names are identifiers. Values are numbers, timestamps, offsets
    # and uuids. That difference does not depend on the widths lining up.
    candidates: list[tuple[int, list[str]]] = []
    for index, line in enumerate(lines[:MAX_HEADER_SCAN]):
        fields = [f.strip() for f in next(csv.reader([line]), [])]
        if not fields:
            continue
        if (
            len(fields) <= 3
            and METADATA_RE.match(fields[0] or "")
            and all(f.isdigit() for f in fields[1:] if f)
        ):
            continue                       # the package-and-version line
        candidates.append((index, fields))

    best_index, best_columns = 0, []
    for index, fields in candidates:
        named = [f for f in fields if f]
        if len(named) < MIN_HEADER_CELLS:
            continue
        looks_like_names = sum(1 for f in named if COLUMN_NAME_RE.match(f)) / len(named)
        if looks_like_names >= HEADER_NAME_FRACTION:
            best_index, best_columns = index, fields
            break                          # the earliest such line is the header
    else:
        # No line reads as column names. Fall back to the old width rule
        # rather than returning nothing, so an export shaped in a way this
        # has not seen still parses instead of silently yielding zero rows.
        best_agreement = -1
        for index, fields in candidates:
            agreement = sum(
                1
                for row in csv.reader(lines[index + 1 : index + 40])
                if len(row) == len(fields)
            )
            if agreement > best_agreement:
                best_index, best_columns, best_agreement = index, fields, agreement
    # Blank column names are dropped *after* zipping, never before. Removing
    # them from the header first shifts every later name onto the previous
    # column's value, which produces a dict with all the right keys and all
    # the wrong values — the failure that looks like working code.
    if not any(best_columns):
        return []
    return [
        {name: value for name, value in zip(best_columns, row, strict=False) if name}
        for row in csv.reader(lines[best_index + 1 :])
        if any(f.strip() for f in row)
    ]


def parse_offset(value: str | None) -> int | None:
    """"UTC+0100" to minutes east of UTC."""
    if not value:
        return None
    match = OFFSET_RE.match(value.strip())
    if not match:
        return None
    sign, hours, minutes = match.groups()
    total = int(hours) * 60 + int(minutes)
    return -total if sign == "-" else total


def parse_naive(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def to_utc(naive: datetime | None, offset_min: int | None, basis: str) -> datetime | None:
    """Resolve a wall-clock reading and its offset into a real instant."""
    if naive is None:
        return None
    if basis == BASIS_UTC or offset_min is None:
        return naive.replace(tzinfo=UTC)
    return (naive - timedelta(minutes=offset_min)).replace(tzinfo=UTC)


def number(value: str | None, *, zero_is_null: bool = False) -> float | None:
    """A blank is None. With zero_is_null, so is an exact zero.

    `efficiency` is 0.0 on sessions that never measured it; `sleep_duration` is
    blank on the same rows. Only the first of those is dangerous, because only
    the first parses.
    """
    if value is None or not str(value).strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if zero_is_null and parsed == 0:
        return None
    return parsed


# ── the timezone question ───────────────────────────────────────────────────


@dataclass(frozen=True)
class BasisVerdict:
    """Which reading of the timestamps is coherent, and the evidence for it."""

    basis: str | None
    shift_if_local_hours: float
    shift_if_utc_hours: float
    standard_count: int
    daylight_count: int
    note: str
    #: "clock change" when the verdict came from the narrow windows either
    #: side of a transition, "whole seasons" when it fell back to comparing
    #: winter against summer. The fallback is confoundable by seasonal
    #: bedtime drift and a caller should say so rather than present the two
    #: as equally proven.
    window: str = "whole seasons"

    @property
    def confident(self) -> bool:
        return self.basis is not None


def _circular_mean_hour(hours: list[float]) -> float:
    """Mean of clock hours that straddle midnight.

    A bedtime set of 23:30 and 00:30 averages to midnight, not to noon, so
    early-morning hours are treated as late on the previous day before
    averaging — the same trick sleep_midpoint_minutes uses.
    """
    return mean(h + 24 if h < 12 else h for h in hours) % 24


def format_offset(minutes: int) -> str:
    """`60` back to `UTC+0100`, so a message names what the file contains."""
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}"


def _transitions(
    samples: list[tuple[datetime, int | None]], standard: int, daylight: int
) -> list[datetime]:
    """When the clock changed, located from the records rather than assumed.

    Two consecutive records whose offset differs bracket a transition. If they
    are far apart the date is not pinned down well enough to be useful, so
    that transition is dropped rather than guessed at.
    """
    seasonal = sorted(
        (naive, offset) for naive, offset in samples if offset in (standard, daylight)
    )
    out: list[datetime] = []
    for (before, offset_before), (after, offset_after) in zip(
        seasonal, seasonal[1:], strict=False
    ):
        if offset_before == offset_after:
            continue
        if after - before > timedelta(days=MAX_TRANSITION_BRACKET_DAYS):
            continue
        out.append(before + (after - before) / 2)
    return out


def detect_timestamp_basis(
    samples: list[tuple[datetime, int | None]],
    *,
    min_per_group: int = 20,
    decisive_hours: float = 0.5,
) -> BasisVerdict:
    """Decide whether Samsung's timestamps are local wall-clock or UTC.

    The test plays the two sides of a clock change against each other. Under
    the correct reading a bedtime is the same on the Saturday and the Sunday.
    Under the wrong one every record after the change shifts by exactly the
    daylight-saving hour.

    It is deliberately measured across a clock change and not across the
    seasons. Bedtimes drift with the season by something approaching an hour,
    and a winter-against-summer comparison cannot separate that drift from the
    error being looked for, because both move the summer group. Which way it
    lies depends on the sleeper: going to bed later in summer biases the
    answer towards `local`, going to bed earlier biases it towards `utc`.
    Three weeks either side of a transition the drift is minutes while the
    timezone error is still the whole hour, because one is gradual and the
    other is a step.

    Where a transition cannot be located, or too few records sit near one,
    this falls back to the whole-season comparison and says so in `window`,
    because that answer is the confoundable one and should not be presented
    as equally proven. If neither reading is clearly better, or either group
    is too thin, it returns no verdict — guessing here is how sleep silently
    lands on the wrong day for half of every year.
    """
    offsets = [o for _, o in samples if o is not None]
    if not offsets:
        return BasisVerdict(None, 0.0, 0.0, 0, 0, "no usable offsets in the sample")

    counts = Counter(offsets)
    if len(counts) == 1:
        return BasisVerdict(
            None, 0.0, 0.0, len(offsets), 0,
            "every sample shares one offset, so the seasons cannot be compared",
        )

    # The seasonal pair is the two offsets an hour apart that the most records
    # sit in — not the extremes of the range. Taking min and max compared a
    # holiday against a different holiday: on the real export it found six
    # records at one end and three at the other and ignored several hundred
    # GMT and BST nights in between. A trip does not tell you when someone
    # goes to bed at home.
    pairs = [
        (counts[low] + counts[low + DST_STEP_MINUTES], low)
        for low in counts
        if low + DST_STEP_MINUTES in counts
    ]
    if pairs:
        standard_offset = max(pairs)[1]
        daylight_offset = standard_offset + DST_STEP_MINUTES
    else:
        # No pair an hour apart. Fall back to the two most populated offsets
        # so an export from somewhere with a different rule still gets a
        # verdict rather than a refusal it cannot act on.
        common = sorted(o for o, _ in counts.most_common(2))
        standard_offset, daylight_offset = common[0], common[1]

    def gap(
        basis: str, population: list[tuple[datetime, int | None]]
    ) -> tuple[float, int, int]:
        groups: dict[int, list[float]] = {standard_offset: [], daylight_offset: []}
        for naive, offset in population:
            if offset not in groups:
                continue
            instant = to_utc(naive, offset, basis)
            local = instant + timedelta(minutes=offset)
            groups[offset].append(local.hour + local.minute / 60)
        standard, daylight = groups[standard_offset], groups[daylight_offset]
        if len(standard) < min_per_group or len(daylight) < min_per_group:
            return float("nan"), len(standard), len(daylight)
        # Circular: 23:00 and 00:00 are an hour apart, not twenty-three.
        raw_difference = _circular_mean_hour(daylight) - _circular_mean_hour(standard)
        difference = (raw_difference + 12) % 24 - 12
        return abs(difference), len(standard), len(daylight)

    # The records within three weeks of a clock change, which is the
    # comparison that is not confounded by summer bedtimes. Everything else is
    # the fallback.
    changes = _transitions(samples, standard_offset, daylight_offset)
    span = timedelta(days=DST_WINDOW_DAYS)
    near = [s for s in samples if any(abs(s[0] - change) <= span for change in changes)]

    window = "clock change"
    local_gap, standard_n, daylight_n = gap(BASIS_LOCAL, near)
    if local_gap != local_gap:                      # NaN: not enough near a change
        window = "whole seasons"
        local_gap, standard_n, daylight_n = gap(BASIS_LOCAL, samples)
        utc_gap, _, _ = gap(BASIS_UTC, samples)
    else:
        utc_gap, _, _ = gap(BASIS_UTC, near)

    if local_gap != local_gap or utc_gap != utc_gap:  # NaN: too few in a group
        return BasisVerdict(
            None, local_gap, utc_gap, standard_n, daylight_n,
            f"need {min_per_group} samples either side of a daylight-saving "
            f"change; {format_offset(standard_offset)} has {standard_n} and "
            f"{format_offset(daylight_offset)} has {daylight_n}",
            window,
        )

    if abs(local_gap - utc_gap) < decisive_hours:
        return BasisVerdict(
            None, local_gap, utc_gap, standard_n, daylight_n,
            "the two readings fit the data equally well, so neither is proven",
            window,
        )

    basis = BASIS_LOCAL if local_gap < utc_gap else BASIS_UTC
    measured = (
        "across the clock change"
        if window == "clock change"
        else "across whole seasons, which summer bedtimes can confound"
    )
    return BasisVerdict(
        basis, local_gap, utc_gap, standard_n, daylight_n,
        f"reading them as {basis} leaves a {min(local_gap, utc_gap):.2f}h gap "
        f"{measured} against {max(local_gap, utc_gap):.2f}h for the alternative",
        window,
    )


# ── files ───────────────────────────────────────────────────────────────────


def load_export(path: Path) -> dict[str, bytes]:
    """Every CSV in the export, keyed by filename. Zip or extracted folder."""
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            return {
                Path(info.filename).name: archive.read(info)
                for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".csv")
            }
    if path.is_dir():
        return {f.name: f.read_bytes() for f in path.rglob("*.csv")}
    raise FileNotFoundError(f"not a zip or a folder: {path}")


def find(files: dict[str, bytes], stem: str) -> bytes | None:
    """The export suffixes every filename with a timestamp."""
    for name, raw in files.items():
        if name.startswith(stem + "."):
            return raw
    return None


# ── records ─────────────────────────────────────────────────────────────────

SLEEP_FILE = "com.samsung.shealth.sleep"
HEART_FILE = "com.samsung.shealth.tracker.heart_rate"
STEPS_FILE = "com.samsung.shealth.tracker.pedometer_day_summary"
WEIGHT_FILE = "com.samsung.health.weight"

#: Samsung's stage codes, from the real export's sleep_stage file.
STAGE_AWAKE, STAGE_LIGHT, STAGE_DEEP, STAGE_REM = "40001", "40002", "40003", "40004"


@dataclass(frozen=True)
class SleepRecord:
    source_record_id: str
    start_at: datetime
    end_at: datetime
    duration_min: int
    efficiency_pct: float | None
    deep_min: int | None
    rem_min: int | None
    light_min: int | None
    score: float | None


def parse_sleep(raw: bytes, basis: str) -> list[SleepRecord]:
    """Sleep sessions.

    Duration is computed from the two timestamps rather than read: the records
    before 2024 carry no `sleep_duration` at all, and a session that has a start
    and an end has a duration whether or not the phone wrote one down.

    Efficiency comes from `original_efficiency`, falling back to `efficiency`
    with zero treated as absent — see the module docstring.
    """
    out: list[SleepRecord] = []
    for row in read_rows(raw):
        start = to_utc(
            parse_naive(row.get("com.samsung.health.sleep.start_time")),
            parse_offset(row.get("com.samsung.health.sleep.time_offset")),
            basis,
        )
        end = to_utc(
            parse_naive(row.get("com.samsung.health.sleep.end_time")),
            parse_offset(row.get("com.samsung.health.sleep.time_offset")),
            basis,
        )
        identifier = (row.get("com.samsung.health.sleep.datauuid") or "").strip()
        if start is None or end is None or end <= start or not identifier:
            continue
        if start < EPOCH_CUTOFF:
            continue
        efficiency = number(row.get("original_efficiency"))
        if efficiency is None:
            efficiency = number(row.get("efficiency"), zero_is_null=True)
        out.append(
            SleepRecord(
                source_record_id=identifier,
                start_at=start,
                end_at=end,
                duration_min=int((end - start).total_seconds() // 60),
                efficiency_pct=efficiency,
                deep_min=_as_int(row.get("total_deep_duration")),
                rem_min=_as_int(row.get("total_rem_duration")),
                light_min=_as_int(row.get("total_light_duration")),
                score=number(row.get("sleep_score"), zero_is_null=True),
            )
        )
    return out


def _as_int(value: str | None) -> int | None:
    parsed = number(value)
    return None if parsed is None else int(parsed)


def parse_heart_samples(raw: bytes, basis: str) -> list[tuple[datetime, float]]:
    """Every heart-rate reading as (instant, bpm). Resting HR is derived from
    these by `app.metrics.derived.resting_hr_from_samples`; the export has no
    resting-HR field of its own."""
    out: list[tuple[datetime, float]] = []
    for row in read_rows(raw):
        instant = to_utc(
            parse_naive(row.get("com.samsung.health.heart_rate.start_time")),
            parse_offset(row.get("com.samsung.health.heart_rate.time_offset")),
            basis,
        )
        bpm = number(row.get("com.samsung.health.heart_rate.heart_rate"), zero_is_null=True)
        if instant is None or bpm is None or instant < EPOCH_CUTOFF:
            continue
        out.append((instant, bpm))
    return out


def parse_steps(raw: bytes) -> dict:
    """Daily step totals, keyed by local date.

    `day_time` is local midnight — that is what settled the basis question in
    the first place — so the date is read straight off it and no offset applies.
    """
    out: dict = {}
    for row in read_rows(raw):
        day = parse_naive(row.get("day_time"))
        steps = number(row.get("step_count"))
        if day is None or steps is None or day < EPOCH_CUTOFF.replace(tzinfo=None):
            continue
        active_ms = number(row.get("active_time"))
        out[day.date()] = {
            "steps": int(steps),
            "distance_m": number(row.get("distance")),
            "active_energy_kcal": number(row.get("calorie")),
            "active_minutes": None if active_ms is None else int(active_ms / 60000),
        }
    return out


def parse_weight(raw: bytes, basis: str) -> dict:
    """Weight and body composition, latest reading per local date."""
    out: dict = {}
    for row in read_rows(raw):
        offset = parse_offset(row.get("time_offset"))
        instant = to_utc(parse_naive(row.get("start_time")), offset, basis)
        weight = number(row.get("weight"), zero_is_null=True)
        if instant is None or weight is None or instant < EPOCH_CUTOFF:
            continue
        local = instant + timedelta(minutes=offset or 0)
        out[local.date()] = {
            "weight_kg": weight,
            "body_fat_pct": number(row.get("body_fat"), zero_is_null=True),
            "muscle_mass_kg": number(row.get("muscle_mass"), zero_is_null=True),
            "water_pct": number(row.get("total_body_water"), zero_is_null=True),
        }
    return out
