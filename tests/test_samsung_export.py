"""Parsing a Samsung Health export.

The tests that matter most are the ones about ambiguity: whether a timestamp
is local or UTC, and whether a zero is a measurement. Both are invisible when
wrong — the first for half of every year, the second always.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.samsung_export import (
    BASIS_LOCAL,
    BASIS_UTC,
    detect_timestamp_basis,
    number,
    parse_naive,
    parse_offset,
    parse_sleep,
    parse_steps,
    parse_weight,
    read_rows,
    to_utc,
)

GMT, BST = 0, 60


def csv_bytes(package: str, header: list[str], rows: list[list[str]], encoding="utf-8-sig") -> bytes:
    lines = [f"{package},7006011,11", ",".join(header)]
    lines += [",".join(r) for r in rows]
    return "\n".join(lines).encode(encoding)


# ── the format's traps ──────────────────────────────────────────────────────


def test_the_header_is_found_not_assumed():
    """Line 1 is a package name and a version. Reading it as the header gives a
    parser that runs and mislabels every column."""
    raw = csv_bytes("com.samsung.shealth.sleep", ["start_time", "efficiency"],
                    [["2024-01-28 22:47:00.000", "91.0"]])
    rows = read_rows(raw)
    assert rows == [{"start_time": "2024-01-28 22:47:00.000", "efficiency": "91.0"}]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "utf-16"])
def test_every_encoding_the_export_has_appeared_as(encoding):
    raw = csv_bytes("com.samsung.health.weight", ["weight"], [["76.0"]], encoding=encoding)
    assert read_rows(raw) == [{"weight": "76.0"}]


def test_a_zero_efficiency_is_absence_not_a_measurement():
    """The real export has efficiency=0.0 on every pre-2024 session, with the
    real value in original_efficiency when there is one. Storing the zero puts a
    fabricated 0% into a column the metrics engine reads as measured."""
    assert number("0.0", zero_is_null=True) is None
    assert number("0.0") == 0.0          # only where a zero is meaningful
    assert number("91.0", zero_is_null=True) == 91.0
    assert number("", zero_is_null=True) is None


def test_offsets_parse_in_both_directions():
    assert parse_offset("UTC+0100") == 60
    assert parse_offset("UTC+0000") == 0
    assert parse_offset("UTC-0500") == -300
    assert parse_offset("") is None
    assert parse_offset("nonsense") is None


# ── the question the whole parser rests on ──────────────────────────────────


def _bedtimes(basis_of_the_data: str, nights: int = 120) -> list[tuple[datetime, int | None]]:
    """Nights at a steady 23:00 local, half in GMT and half in BST, written to
    the file under the given basis. This is what a real export looks like if
    the owner's bedtime never changes — which is the property the detector
    leans on."""
    samples = []
    for index in range(nights):
        winter = index % 2 == 0
        offset = GMT if winter else BST
        local = datetime(2025, 1 if winter else 7, (index % 27) + 1, 23, 0)
        written = local if basis_of_the_data == BASIS_LOCAL else local - timedelta(minutes=offset)
        samples.append((written, offset))
    return samples


def test_it_identifies_local_timestamps():
    verdict = detect_timestamp_basis(_bedtimes(BASIS_LOCAL))
    assert verdict.basis == BASIS_LOCAL
    assert verdict.confident
    assert verdict.shift_if_local_hours < verdict.shift_if_utc_hours


def test_it_identifies_utc_timestamps():
    verdict = detect_timestamp_basis(_bedtimes(BASIS_UTC))
    assert verdict.basis == BASIS_UTC
    assert verdict.shift_if_utc_hours < verdict.shift_if_local_hours


def test_the_wrong_reading_shifts_summer_by_exactly_the_daylight_hour():
    """Which is the signal the test is built on: under a wrong reading every
    summer record moves an hour and the seasons separate."""
    verdict = detect_timestamp_basis(_bedtimes(BASIS_LOCAL))
    assert verdict.shift_if_utc_hours == pytest.approx(1.0, abs=0.05)
    assert verdict.shift_if_local_hours == pytest.approx(0.0, abs=0.05)


def test_it_refuses_to_guess_from_one_season():
    """An export covering only winter cannot answer the question, and a verdict
    there would be a coin toss that silently breaks every summer."""
    winter_only = [(datetime(2025, 1, d % 27 + 1, 23, 0), GMT) for d in range(80)]
    verdict = detect_timestamp_basis(winter_only)
    assert verdict.basis is None
    assert not verdict.confident
    assert "one offset" in verdict.note


def test_it_refuses_to_guess_from_too_few_nights():
    verdict = detect_timestamp_basis(_bedtimes(BASIS_LOCAL, nights=10))
    assert verdict.basis is None
    assert "samples either side" in verdict.note


def test_it_refuses_when_bedtimes_are_too_scattered_to_tell():
    """Random bedtimes carry no seasonal signal, so neither reading fits better
    and the honest answer is no answer."""
    import random

    rng = random.Random(1)
    scattered = [
        (datetime(2025, 1 if i % 2 == 0 else 7, i % 27 + 1, rng.randrange(24), 0),
         GMT if i % 2 == 0 else BST)
        for i in range(200)
    ]
    assert detect_timestamp_basis(scattered).basis is None


def test_bedtimes_either_side_of_midnight_do_not_average_to_noon():
    """23:30 and 00:30 average to midnight. A plain mean says 12:00 and would
    make every reading look equally wrong."""
    around_midnight = []
    for index in range(120):
        winter = index % 2 == 0
        offset = GMT if winter else BST
        hour, minute = (23, 30) if index % 4 < 2 else (0, 30)
        local = datetime(2025, 1 if winter else 7, (index % 27) + 1, hour, minute)
        around_midnight.append((local, offset))
    assert detect_timestamp_basis(around_midnight).basis == BASIS_LOCAL


# ── resolving an instant ────────────────────────────────────────────────────


def test_local_timestamps_resolve_to_the_right_instant():
    naive = parse_naive("2022-07-22 23:10:00.000")
    assert to_utc(naive, BST, BASIS_LOCAL) == datetime(2022, 7, 22, 22, 10, tzinfo=UTC)
    assert to_utc(naive, BST, BASIS_UTC) == datetime(2022, 7, 22, 23, 10, tzinfo=UTC)


def test_winter_hides_the_difference():
    """Why the question cannot be settled by looking at one record: with a zero
    offset the two readings are identical, and half the export is like that."""
    naive = parse_naive("2024-01-28 22:47:00.000")
    assert to_utc(naive, GMT, BASIS_LOCAL) == to_utc(naive, GMT, BASIS_UTC)


# ── records ─────────────────────────────────────────────────────────────────

SLEEP_HEADER = [
    "com.samsung.health.sleep.start_time", "com.samsung.health.sleep.end_time",
    "com.samsung.health.sleep.time_offset", "com.samsung.health.sleep.datauuid",
    "efficiency", "original_efficiency", "sleep_duration", "sleep_score",
    "total_rem_duration", "total_light_duration",
]


def test_sleep_duration_is_computed_not_read():
    """Every session before 2024 has an empty sleep_duration. A session with a
    start and an end has a duration whether or not the phone wrote one."""
    raw = csv_bytes("com.samsung.shealth.sleep", SLEEP_HEADER, [
        ["2022-07-22 23:10:00.000", "2022-07-23 07:00:00.000", "UTC+0100",
         "uuid-old", "0.0", "", "", "", "", ""],
    ])
    session = parse_sleep(raw, BASIS_LOCAL)[0]
    assert session.duration_min == 470
    assert session.efficiency_pct is None      # the 0.0 is absence, not 0%
    assert session.score is None


def test_sleep_prefers_original_efficiency():
    raw = csv_bytes("com.samsung.shealth.sleep", SLEEP_HEADER, [
        ["2024-01-28 22:47:00.000", "2024-01-29 06:38:00.000", "UTC+0000",
         "uuid-new", "0.0", "91.0", "433", "84", "119", "282"],
    ])
    session = parse_sleep(raw, BASIS_LOCAL)[0]
    assert session.efficiency_pct == 91.0
    assert session.score == 84.0
    assert session.rem_min == 119


def test_sleep_rejects_the_unusable():
    raw = csv_bytes("com.samsung.shealth.sleep", SLEEP_HEADER, [
        ["", "2024-01-29 06:38:00.000", "UTC+0000", "a", "", "", "", "", "", ""],
        ["2024-01-29 06:38:00.000", "2024-01-28 22:47:00.000", "UTC+0000", "b", "", "", "", "", "", ""],
        ["1970-01-01 00:00:00.000", "1970-01-01 08:00:00.000", "UTC+0000", "c", "", "", "", "", "", ""],
        ["2024-01-28 22:47:00.000", "2024-01-29 06:38:00.000", "UTC+0000", "", "", "", "", "", "", ""],
    ])
    # no start; end before start; an epoch sentinel; no id
    assert parse_sleep(raw, BASIS_LOCAL) == []


def test_steps_are_keyed_by_the_local_day_samsung_wrote():
    """day_time is local midnight — that is the observation that settled the
    basis question — so no offset is applied to it."""
    raw = csv_bytes("com.samsung.shealth.tracker.pedometer_day_summary",
                    ["day_time", "step_count", "distance", "calorie", "active_time"],
                    [["2021-05-04 00:00:00.000", "6861", "5194.83", "238.16", "3766650"]])
    days = parse_steps(raw)
    assert list(days) == [datetime(2021, 5, 4).date()]
    assert days[datetime(2021, 5, 4).date()]["steps"] == 6861
    assert days[datetime(2021, 5, 4).date()]["active_minutes"] == 62


def test_weight_carries_body_composition():
    raw = csv_bytes("com.samsung.health.weight",
                    ["start_time", "time_offset", "weight", "body_fat",
                     "muscle_mass", "total_body_water"],
                    [["2024-05-01 05:37:20.084", "UTC+0100", "77.7", "17.6", "54.81", "47.6"]])
    days = parse_weight(raw, BASIS_LOCAL)
    entry = days[datetime(2024, 5, 1).date()]
    assert entry["weight_kg"] == 77.7
    assert entry["body_fat_pct"] == 17.6


def test_the_metadata_line_is_recognised_even_when_it_is_the_same_width():
    """The heart-rate file's real header has many columns, but a three-column
    file makes the metadata line indistinguishable by width alone — and the
    importer silently parsed zero heart-rate samples until this was handled."""
    raw = csv_bytes(
        "com.samsung.shealth.tracker.heart_rate",
        ["com.samsung.health.heart_rate.start_time",
         "com.samsung.health.heart_rate.time_offset",
         "com.samsung.health.heart_rate.heart_rate"],
        [["2024-01-28 13:00:29.233", "UTC+0000", "66.0"]],
    )
    rows = read_rows(raw)
    assert rows[0]["com.samsung.health.heart_rate.heart_rate"] == "66.0"
