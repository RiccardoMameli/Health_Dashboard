#!/usr/bin/env python3
"""Verify the Hevy adapter against the real API, and capture a fixture.

Run this on a machine that can reach `api.hevyapp.com` with `HEVY_API_KEY`
set (the build container cannot — see the 10 September build-log entry).

    python scripts/verify_hevy.py                      # report only
    python scripts/verify_hevy.py --write-fixture      # also replace the fixture
    python scripts/verify_hevy.py --pages 3            # sample instead of all

It answers the questions the hand-written fixture cannot:

  * how many workouts, over what date range, and does that agree with
    `/v1/workouts/count`;
  * does every field the adapter reads exist, with the name and shape it
    expects, across the whole history rather than one specimen;
  * does the volume-load arithmetic reproduce by hand, with warm-ups excluded;
  * what happens to workouts near local midnight, and across a BST/GMT
    transition, where date attribution is silently wrong or silently right.

Nothing here writes to the database. `scripts/backfill.py` does that.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.hevy import PAGE_SIZE, HevyAdapter, _volume_kg  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.timeutil import local_date, to_local, to_utc  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hevy_workouts.json"

#: Every key the adapter reads, by level. Anything missing here is a field the
#: adapter asks for and the API does not supply; anything the API supplies that
#: is not here is retained in `raw_records` but never normalised.
READS = {
    "workout": ["id", "title", "description", "start_time", "end_time", "exercises"],
    "exercise": ["title", "exercise_template_id", "sets"],
    "set": ["index", "type", "weight_kg", "reps", "rpe", "distance_meters", "duration_seconds"],
}

#: Set types the adapter has an opinion about. `warmup` is excluded from volume
#: and the working-set count; everything else counts. A type outside this list
#: would be counted as working volume by default, which is worth knowing about.
KNOWN_SET_TYPES = {"normal", "warmup", "dropset", "failure"}

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def fetch_all(adapter: HevyAdapter, max_pages: int | None) -> tuple[list[dict], int | None]:
    """Page through /v1/workouts, and ask the API how many there should be."""
    try:
        declared = int(adapter.client.get("/v1/workouts/count").get("workout_count"))
    except Exception as exc:  # count is a cross-check, not a dependency
        print(f"  ! /v1/workouts/count failed: {type(exc).__name__}: {exc}")
        declared = None

    workouts: list[dict] = []
    page = 1
    while True:
        payload = adapter.client.get("/v1/workouts", params={"page": page, "pageSize": PAGE_SIZE})
        batch = payload.get("workouts") or []
        if not batch:
            break
        workouts.extend(batch)
        print(f"\r  fetched page {page} ({len(workouts)} workouts)", end="", flush=True)
        page_count = payload.get("page_count")
        if page_count is not None and page >= int(page_count):
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1
    print()
    return workouts, declared


def check_fields(workouts: list[dict]) -> None:
    """Does every field the adapter reads exist, with the shape it expects?"""
    missing: Counter[str] = Counter()
    extra: Counter[str] = Counter()
    types: dict[str, Counter] = {k: Counter() for k in ("weight_kg", "reps", "rpe")}
    set_types: Counter[str] = Counter()
    non_int_reps: list[str] = []

    for w in workouts:
        for key in READS["workout"]:
            if key not in w:
                missing[f"workout.{key}"] += 1
        for key in w:
            if key not in READS["workout"]:
                extra[f"workout.{key}"] += 1
        for ex in w.get("exercises") or []:
            for key in READS["exercise"]:
                if key not in ex:
                    missing[f"exercise.{key}"] += 1
            for key in ex:
                if key not in READS["exercise"]:
                    extra[f"exercise.{key}"] += 1
            for s in ex.get("sets") or []:
                for key in READS["set"]:
                    if key not in s:
                        missing[f"set.{key}"] += 1
                for key in s:
                    if key not in READS["set"]:
                        extra[f"set.{key}"] += 1
                set_types[s.get("type") or "<absent>"] += 1
                for key in types:
                    types[key][type(s.get(key)).__name__] += 1
                reps = s.get("reps")
                if isinstance(reps, float) and reps != int(reps):
                    non_int_reps.append(f"{w.get('id')} {ex.get('title')} reps={reps}")

    print("\n--- fields the adapter reads ---")
    if missing:
        for key, n in missing.most_common():
            print(f"  MISSING  {key}  (absent on {n} records)")
    else:
        print("  all present on every record")

    print("\n--- fields the API sends that the adapter does not normalise ---")
    print("  (retained in raw_records, never in a typed column)")
    for key, n in extra.most_common() or [("none", 0)]:
        print(f"  {key}  ({n})" if n else "  none")

    print("\n--- observed types ---")
    for key, counts in types.items():
        print(f"  {key}: {dict(counts)}")
    if non_int_reps:
        print(f"\n  ! reps is fractional on {len(non_int_reps)} sets — int(reps) truncates:")
        for line in non_int_reps[:5]:
            print(f"      {line}")

    print("\n--- set types ---")
    for name, n in set_types.most_common():
        flag = "" if name in KNOWN_SET_TYPES else "   <-- UNKNOWN, counted as working volume"
        counted = "excluded from volume" if name == "warmup" else "counted toward volume"
        print(f"  {name:10} {n:6}  {counted}{flag}")


def hand_verify_volume(workouts: list[dict]) -> None:
    """Reproduce total_volume_kg by hand on the workout with the most warm-ups.

    Picking the workout with the most warm-up sets is deliberate: it is the one
    where an adapter that forgot to exclude them would be most obviously wrong.
    """
    def warmups(w: dict) -> int:
        return sum(
            1
            for ex in w.get("exercises") or []
            for s in ex.get("sets") or []
            if (s.get("type") or "normal") == "warmup"
        )

    candidates = [w for w in workouts if warmups(w) > 0] or workouts
    if not candidates:
        print("\n--- volume hand-check ---\n  no workouts")
        return
    w = max(candidates, key=warmups)

    flat = [
        {"exercise_name": ex.get("title"), **s}
        for ex in w.get("exercises") or []
        for s in ex.get("sets") or []
    ]
    print("\n--- volume hand-check ---")
    print(f"  workout {w.get('id')}  {w.get('title')!r}  {w.get('start_time')}")
    by_hand = 0.0
    excluded = 0.0
    for s in flat:
        kind = s.get("type") or "normal"
        weight, reps = s.get("weight_kg"), s.get("reps")
        if weight is None or reps is None:
            print(f"    {kind:8} {s['exercise_name'][:28]:28} weight={weight} reps={reps}"
                  f"   -> contributes 0 (no weight x reps)")
            continue
        product = float(weight) * int(reps)
        if kind == "warmup":
            excluded += product
            print(f"    {kind:8} {s['exercise_name'][:28]:28} {weight} x {reps} = {product:9.2f}"
                  f"   EXCLUDED")
        else:
            by_hand += product
            print(f"    {kind:8} {s['exercise_name'][:28]:28} {weight} x {reps} = {product:9.2f}")

    adapter_says = _volume_kg(
        [{"type": s.get("type") or "normal", "weight_kg": s.get("weight_kg"), "reps": s.get("reps")}
         for s in flat]
    )
    print(f"\n  by hand (working sets only) : {round(by_hand, 2)}")
    print(f"  adapter _volume_kg()        : {adapter_says}")
    print(f"  warm-up volume excluded     : {round(excluded, 2)}")
    ok = abs(adapter_says - round(by_hand, 2)) < 0.01
    print(f"  MATCH: {ok}" + ("" if ok else "   <-- ADAPTER AND HAND ARITHMETIC DISAGREE"))
    if excluded == 0:
        print("  ! no warm-up sets in this history — exclusion is unproven against real data")


def check_date_attribution(workouts: list[dict]) -> None:
    """Where a workout lands, in local time, and where that is contestable.

    A workout is attributed to the local date it STARTED. Only sleep belongs to
    the day it ends. Near midnight and across a BST/GMT transition are the two
    places that rule is silently wrong if it is wrong at all.
    """
    print("\n--- date attribution ---")
    print("  rule: local_date(start_at) — the day the session BEGAN")
    near_midnight = []
    crosses_midnight = []
    for w in workouts:
        raw_start = w.get("start_time")
        if not raw_start:
            continue
        start = to_utc(datetime.fromisoformat(raw_start.replace("Z", "+00:00")))
        local_start = to_local(start)
        day = local_date(start)
        if local_start.hour >= 22 or local_start.hour < 4:
            near_midnight.append((w, local_start, day))
        raw_end = w.get("end_time")
        if raw_end:
            end = to_utc(datetime.fromisoformat(raw_end.replace("Z", "+00:00")))
            if local_date(end) != day:
                crosses_midnight.append((w, local_start, to_local(end), day))

    if near_midnight:
        print(f"\n  {len(near_midnight)} workout(s) starting 22:00-04:00 local:")
        for w, local_start, day in near_midnight[:10]:
            print(f"    {w.get('id')}  start {local_start.isoformat()}  -> attributed {day}")
    else:
        print("\n  none starting between 22:00 and 04:00 local")

    if crosses_midnight:
        print(f"\n  {len(crosses_midnight)} workout(s) that END on a different local day:")
        print("  these are the ones where 'the day it started' is a real choice, not a formality")
        for w, ls, le, day in crosses_midnight[:10]:
            print(f"    {w.get('id')}  {ls.isoformat()} -> {le.isoformat()}  attributed {day}")
    else:
        print("  none spanning local midnight")

    # BST/GMT transitions: the offset changes, and a UTC-naive reading is off
    # by an hour on one side of them.
    offsets = Counter()
    for w in workouts:
        raw = w.get("start_time")
        if raw:
            start = to_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            offsets[to_local(start).strftime("%z")] += 1
    print(f"\n  local UTC offsets seen: {dict(offsets)}")
    if len(offsets) < 2:
        print("  ! history sits entirely inside one offset — the BST/GMT boundary is untested here")


def summarise(workouts: list[dict], declared: int | None) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  workouts fetched          : {len(workouts)}")
    print(f"  /v1/workouts/count says   : {declared}")
    if declared is not None and declared != len(workouts):
        print("  ! MISMATCH — the backfill would be incomplete or double-counting")

    dates = sorted(
        local_date(to_utc(datetime.fromisoformat(w["start_time"].replace("Z", "+00:00"))))
        for w in workouts
        if w.get("start_time")
    )
    if dates:
        span = (dates[-1] - dates[0]).days + 1
        print(f"  date range (local)        : {dates[0]} to {dates[-1]}  ({span} days)")
        print(f"  distinct training days    : {len(set(dates))}")
    ids = [w.get("id") for w in workouts]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    print(f"  duplicate ids             : {dupes or 'none'}")
    no_uuid = [i for i in ids if i and not UUID_RE.fullmatch(str(i))]
    if no_uuid:
        print(f"  ! ids that are not UUIDs  : {no_uuid[:5]}")


def scrub(workouts: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Make a real response committable.

    Identifiers become stable synthetic ones so the fixture stays internally
    consistent; free text is dropped because it is the only place personal
    content lives. Timestamps, weights, reps and RPE are kept — they are the
    measurements the tests exist to check, and they are not secrets.
    """
    mapping: dict[str, str] = {}

    def fake(real: str | None, prefix: str) -> str | None:
        if real is None:
            return None
        if real not in mapping:
            mapping[real] = f"{prefix}-{len(mapping) + 1:04d}-0000-0000-000000000000"
        return mapping[real]

    out = []
    for i, w in enumerate(json.loads(json.dumps(workouts))):
        w["id"] = fake(w.get("id"), "00000000")
        if w.get("routine_id"):
            w["routine_id"] = fake(w["routine_id"], "11111111")
        if w.get("title"):
            w["title"] = f"Workout {i + 1}"
        if w.get("description"):
            w["description"] = "[redacted]"
        for ex in w.get("exercises") or []:
            if ex.get("notes"):
                ex["notes"] = "[redacted]"
        out.append(w)
    return out, mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=None, help="stop after N pages")
    parser.add_argument("--write-fixture", action="store_true")
    parser.add_argument("--show-raw", type=int, default=1, help="how many full payloads to print")
    args = parser.parse_args()

    if not get_settings().hevy_api_key:
        print("HEVY_API_KEY is not set. Put it in .env (NOT .env.example, which is committed).")
        return 2

    adapter = HevyAdapter()
    print("=== fetching ===")
    workouts, declared = fetch_all(adapter, args.pages)
    if not workouts:
        print("No workouts returned.")
        return 1

    summarise(workouts, declared)

    for w in workouts[: args.show_raw]:
        print("\n--- one full raw payload, exactly as the API sent it ---")
        print(json.dumps(w, indent=2))

    check_fields(workouts)
    hand_verify_volume(workouts)
    check_date_attribution(workouts)

    if args.write_fixture:
        scrubbed, mapping = scrub(workouts)
        payload = {"page": 1, "page_count": 1, "workouts": scrubbed}
        FIXTURE.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\n--- fixture written ---\n  {FIXTURE}")
        print(f"  {len(scrubbed)} workouts, {len(mapping)} identifiers replaced")
        print("  titles renamed, descriptions and exercise notes redacted")
        print("  timestamps, weights, reps and RPE kept — read it before committing")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
