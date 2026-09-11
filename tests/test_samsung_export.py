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


def test_a_blank_column_name_does_not_shift_the_ones_after_it():
    """Samsung's wider files carry empty header cells. Dropping a blank name
    from the header before zipping slides every later name onto the previous
    column's value: a dict with the right keys and the wrong values, which is
    indistinguishable from working code until a date fails to parse."""
    raw = csv_bytes(
        "com.samsung.shealth.sleep",
        ["com.samsung.health.sleep.start_time", "", "com.samsung.health.sleep.end_time"],
        [["2024-01-28 22:47:00.000", "junk", "2024-01-29 06:31:00.000"]],
    )
    assert read_rows(raw) == [
        {
            "com.samsung.health.sleep.start_time": "2024-01-28 22:47:00.000",
            "com.samsung.health.sleep.end_time": "2024-01-29 06:31:00.000",
        }
    ]


def test_the_header_wins_even_when_the_data_rows_are_wider():
    """The real export's sleep header has 62 fields and every data row has 63.
    Scoring candidates by the width the data rows agree with gave the header
    zero and elected a data row, producing a table whose column names were
    `0`, `UTC+0000` and a uuid — 460 rows, none of them readable."""
    header = ["com.samsung.health.sleep.start_time", "com.samsung.health.sleep.time_offset"]
    rows = [
        ["2021-02-07 21:50:00.000", "UTC+0000", ""],   # one field wider
        ["2021-02-09 22:04:00.000", "UTC+0000", ""],
        ["2021-02-10 23:11:00.000", "UTC+0000", ""],
    ]
    parsed = read_rows(csv_bytes("com.samsung.shealth.sleep", header, rows))
    assert len(parsed) == 3
    assert parsed[0]["com.samsung.health.sleep.start_time"] == "2021-02-07 21:50:00.000"
    assert parsed[0]["com.samsung.health.sleep.time_offset"] == "UTC+0000"


def test_a_data_row_of_values_is_never_mistaken_for_a_header():
    """Every value on the losing line is the kind the real export produced: a
    zero, a timestamp, an offset, a token and a uuid."""
    raw = csv_bytes(
        "com.samsung.shealth.sleep",
        ["start_time", "time_offset", "efficiency"],
        [
            ["2021-02-07 21:50:00.000", "UTC+0000", "0.0"],
            ["f8553b66-d057-4fe4-be09-0aaed967a4dc", "UTC+0000", "0"],
        ],
    )
    assert list(read_rows(raw)[0]) == ["start_time", "time_offset", "efficiency"]


def test_holidays_do_not_become_the_seasonal_pair():
    """The real export refused because min(offsets) and max(offsets) were two
    different holidays — six records against three — while several hundred GMT
    and BST nights sat between them unused. The pair is the populated one."""
    samples = []
    for index in range(60):                       # winter, at home
        samples.append((datetime(2024, 1, 1) + timedelta(days=index, hours=23), GMT))
    for index in range(60):                       # summer, at home
        samples.append((datetime(2024, 6, 1) + timedelta(days=index, hours=23), BST))
    for index in range(6):                        # a week in New York
        samples.append((datetime(2024, 3, 1) + timedelta(days=index, hours=23), -300))
    for index in range(3):                        # a long weekend in Tokyo
        samples.append((datetime(2024, 9, 1) + timedelta(days=index, hours=23), 540))

    verdict = detect_timestamp_basis(samples)
    assert verdict.basis == BASIS_LOCAL
    assert verdict.standard_count == 60
    assert verdict.daylight_count == 60


def test_travel_alone_cannot_produce_a_verdict():
    """Two holidays and nothing else is not a seasonal comparison. It has to
    refuse rather than compare one trip against another."""
    samples = [
        (datetime(2024, 3, 1) + timedelta(days=i, hours=23), -300) for i in range(6)
    ] + [
        (datetime(2024, 9, 1) + timedelta(days=i, hours=23), 540) for i in range(3)
    ]
    assert detect_timestamp_basis(samples).basis is None


def _uk_offset(when: datetime) -> int:
    """BST between the last Sunday in March and the last in October, near
    enough for a fixture."""
    return BST if datetime(when.year, 3, 31) <= when <= datetime(when.year, 10, 27) else GMT


def _nights(start: datetime, count: int, bedtime, *, step: int = 1):
    """One record per `step` days, bedtime a function of the date."""
    out = []
    for index in range(count):
        day = start + timedelta(days=index * step)
        hour, minute = bedtime(day)
        out.append((day.replace(hour=hour, minute=minute), _uk_offset(day)))
    return out


def test_seasonal_bedtime_drift_does_not_move_the_verdict():
    """Bedtime drifts from 22:30 in midwinter to 23:30 at midsummer, ordinary
    behaviour, and the timestamps are local. The drift is noise on the
    comparison either way — a later summer bedtime biases towards `local` and
    an earlier one towards `utc` — and across a clock change it is minutes,
    so the verdict rests on the hour and not on the habit."""
    def drifting(day: datetime) -> tuple[int, int]:
        # Peaks at midsummer, troughs at midwinter: a full hour, smoothly.
        from math import cos, pi
        day_of_year = day.timetuple().tm_yday
        fraction = (1 - cos(2 * pi * (day_of_year - 172) / 365)) / 2
        minutes = int(22 * 60 + 30 + 60 * (1 - fraction))
        return minutes // 60, minutes % 60

    samples = _nights(datetime(2022, 1, 1), 700, drifting, step=2)
    verdict = detect_timestamp_basis(samples)
    assert verdict.window == "clock change"
    assert verdict.basis == BASIS_LOCAL


def test_utc_timestamps_are_still_called_utc_across_the_clock_change():
    """The sharp test must not simply always answer 'local'. Same drifting
    sleeper, but the file stores UTC, so each record's wall clock is the local
    bedtime minus the offset."""
    def drifting(day: datetime) -> tuple[int, int]:
        from math import cos, pi
        day_of_year = day.timetuple().tm_yday
        fraction = (1 - cos(2 * pi * (day_of_year - 172) / 365)) / 2
        minutes = int(22 * 60 + 30 + 60 * (1 - fraction))
        return minutes // 60, minutes % 60

    samples = [
        (naive - timedelta(minutes=offset), offset)
        for naive, offset in _nights(datetime(2022, 1, 1), 700, drifting, step=2)
    ]
    verdict = detect_timestamp_basis(samples)
    assert verdict.window == "clock change"
    assert verdict.basis == BASIS_UTC


def test_it_says_when_it_fell_back_to_the_confoundable_comparison():
    """Records nowhere near a clock change can only be compared season to
    season, and the verdict has to carry that caveat rather than read as
    proven."""
    samples = (
        _nights(datetime(2024, 1, 5), 40, lambda d: (23, 0))        # deep winter
        + _nights(datetime(2024, 6, 5), 40, lambda d: (23, 0))      # deep summer
    )
    verdict = detect_timestamp_basis(samples)
    assert verdict.window == "whole seasons"
    assert "confound" in verdict.note


def test_an_earlier_summer_bedtime_does_not_forge_a_utc_verdict():
    """This is the direction that can actually invert the answer. Bedtime
    moves an hour *earlier* by midsummer with local timestamps, which under a
    whole-season comparison looks exactly like a file storing UTC and would
    push every summer night onto the wrong day. The clock-change window has to
    return `local` regardless."""
    from math import cos, pi

    def earlier_in_summer(day: datetime) -> tuple[int, int]:
        day_of_year = day.timetuple().tm_yday
        fraction = (1 - cos(2 * pi * (day_of_year - 172) / 365)) / 2
        minutes = int(22 * 60 + 30 + 60 * fraction)   # inverted against the drift test
        return minutes // 60, minutes % 60

    samples = _nights(datetime(2022, 1, 1), 700, earlier_in_summer, step=2)
    verdict = detect_timestamp_basis(samples)
    assert verdict.window == "clock change"
    assert verdict.basis == BASIS_LOCAL
