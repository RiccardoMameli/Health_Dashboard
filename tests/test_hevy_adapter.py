"""Hevy ingestion: parsing, volume load, idempotency, and deletions."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.adapters.hevy import HevyAdapter, HevyClient
from app.models import RawRecord, Workout, WorkoutSet
from tests.conftest import FIXTURES


def _client(handler) -> HevyClient:
    transport = httpx.MockTransport(handler)
    return HevyClient(
        "fake-key",
        "https://api.hevyapp.com",
        client=httpx.Client(transport=transport, base_url="https://api.hevyapp.com"),
    )


@pytest.fixture
def workouts_payload():
    return json.loads((FIXTURES / "hevy_workouts.json").read_text())


# The fixture is eight real workouts captured from the account on 10 Sep 2026
# and scrubbed (synthetic ids, renamed titles, redacted notes). They were
# chosen to carry between them a warm-up set, bodyweight sets, fractional
# weights, a near-midnight start, and one session from each of GMT and BST.
# Weights, reps and timestamps are untouched, so every number below is real.

LEGS = "00000000-0001-0000-0000-000000000000"       # the only workout with a warm-up
LATE = "00000000-0004-0000-0000-000000000000"       # starts 22:43 local
TOTAL_WORKOUTS = 8
TOTAL_SETS = 107


def _backfill(session, payload) -> None:
    HevyAdapter(_client(lambda r: httpx.Response(200, json=payload))).backfill(session)
    session.commit()


def _by_id(session, source_id: str) -> Workout:
    return session.execute(
        select(Workout).where(Workout.source_record_id == source_id)
    ).scalar_one()


def test_backfill_parses_every_workout_and_set(session, workouts_payload):
    _backfill(session, workouts_payload)

    assert len(session.execute(select(Workout)).scalars().all()) == TOTAL_WORKOUTS
    assert len(session.execute(select(WorkoutSet)).scalars().all()) == TOTAL_SETS

    legs = _by_id(session, LEGS)
    assert legs.source == "hevy"
    assert legs.duration_min == 37.4
    assert len(legs.sets) == 12  # warm-up retained as a row...
    assert legs.set_count == 11  # ...but excluded from the working set count


def test_volume_load_excludes_warmups(session, workouts_payload):
    """The one warm-up in the whole fixture: 50kg x 10 on a leg extension.
    Counting it would report 20790 instead of 20290 — and would make a deload
    week with long warm-ups look like a hard week."""
    _backfill(session, workouts_payload)
    assert _by_id(session, LEGS).total_volume_kg == 20290.0


def test_raw_payload_is_retained(session, workouts_payload):
    _backfill(session, workouts_payload)
    raws = session.execute(select(RawRecord)).scalars().all()
    assert len(raws) == TOTAL_WORKOUTS
    assert {r.source for r in raws} == {"hevy"}
    assert {r.record_type for r in raws} == {"workout"}
    # The payload is kept whole, including the fields the adapter never reads.
    legs = next(r for r in raws if r.source_record_id == LEGS)
    assert legs.payload["exercises"][0]["sets"][0]["custom_metric"] is None
    assert "created_at" in legs.payload


def test_backfill_is_idempotent(session, workouts_payload):
    """Re-running a sync must never duplicate. This property is what lets you
    fix an adapter bug and simply run it again — which this branch did, three
    times, against the live account."""
    _backfill(session, workouts_payload)
    _backfill(session, workouts_payload)

    assert len(session.execute(select(Workout)).scalars().all()) == TOTAL_WORKOUTS
    assert len(session.execute(select(WorkoutSet)).scalars().all()) == TOTAL_SETS
    assert len(session.execute(select(RawRecord)).scalars().all()) == TOTAL_WORKOUTS


def test_a_workout_is_attributed_to_the_local_day_it_started(session, workouts_payload):
    """21:43 UTC on 31 May 2024 is 22:43 BST — still the 31st. Only sleep
    belongs to the day it ends; a workout belongs to the day it began."""
    _backfill(session, workouts_payload)
    assert _by_id(session, LATE).date.isoformat() == "2024-05-31"


def test_updated_workout_replaces_its_sets(session, workouts_payload):
    _backfill(session, workouts_payload)

    edited = json.loads(json.dumps(workouts_payload))
    target = next(w for w in edited["workouts"] if w["id"] == LEGS)
    target["exercises"] = [
        {
            "index": 0,
            "title": "Leg Press Horizontal (Machine)",
            "notes": "",
            "exercise_template_id": "TPL0001",
            "superset_id": None,
            "sets": [
                {
                    "index": 0,
                    "type": "normal",
                    "weight_kg": 200,
                    "reps": 5,
                    "distance_meters": None,
                    "duration_seconds": None,
                    "rpe": 9,
                    "custom_metric": None,
                }
            ],
        }
    ]
    target["title"] = "Legs (edited)"

    events = {"page": 1, "page_count": 1, "events": [{"type": "updated", "workout": target}]}
    HevyAdapter(_client(lambda r: httpx.Response(200, json=events))).incremental(session)
    session.commit()

    legs = _by_id(session, LEGS)
    assert legs.title == "Legs (edited)"
    assert len(legs.sets) == 1
    assert legs.total_volume_kg == 1000.0
    assert legs.perceived_exertion_1_10 == 9.0  # now the edit carries an RPE
    # The other seven are untouched by an event that did not mention them.
    assert len(session.execute(select(Workout)).scalars().all()) == TOTAL_WORKOUTS


def test_deleted_event_removes_the_workout(session, workouts_payload):
    _backfill(session, workouts_payload)

    events = {"page": 1, "page_count": 1, "events": [{"type": "deleted", "id": LEGS}]}
    HevyAdapter(_client(lambda r: httpx.Response(200, json=events))).incremental(session)
    session.commit()

    remaining = session.execute(select(Workout)).scalars().all()
    assert len(remaining) == TOTAL_WORKOUTS - 1
    assert LEGS not in {w.source_record_id for w in remaining}
    # Raw provenance survives the delete, deliberately.
    assert len(session.execute(select(RawRecord)).scalars().all()) == TOTAL_WORKOUTS


# --- shapes the hand-written fixture never had -------------------------------
#
# Everything below is modelled on the real API response captured on 10 Sep
# 2026 (274 workouts, 4331 sets): `+00:00` offsets rather than `Z`, `""` for
# an unset description, `superset_id` (singular — the published OpenAPI spec
# says `supersets_id`, which is wrong), `custom_metric` on every set, and
# `weight_kg: null` on bodyweight work.


def _workout(sets_by_exercise, *, title="Upper body", description="", wid="tc-real-001"):
    return {
        "page": 1,
        "page_count": 1,
        "workouts": [
            {
                "id": wid,
                "title": title,
                "routine_id": None,
                "description": description,
                "start_time": "2026-09-08T19:28:37+00:00",
                "end_time": "2026-09-08T20:07:42+00:00",
                "updated_at": "2026-09-08T20:07:46.894Z",
                "created_at": "2026-09-08T20:07:46.894Z",
                "exercises": [
                    {
                        "index": i,
                        "title": name,
                        "notes": "",
                        "exercise_template_id": f"TPL{i:05X}",
                        "superset_id": None,
                        "sets": [
                            {
                                "index": j,
                                "type": s.get("type", "normal"),
                                "weight_kg": s.get("weight_kg"),
                                "reps": s.get("reps"),
                                "distance_meters": None,
                                "duration_seconds": None,
                                "rpe": s.get("rpe"),
                                "custom_metric": None,
                            }
                            for j, s in enumerate(sets)
                        ],
                    }
                    for i, (name, sets) in enumerate(sets_by_exercise)
                ],
            }
        ],
    }


def _ingest(session, payload):
    HevyAdapter(_client(lambda r: httpx.Response(200, json=payload))).backfill(session)
    session.commit()
    return session.execute(select(Workout)).scalar_one()


def test_bodyweight_only_session_has_unknown_volume_not_zero(session):
    """Dips and pull-ups record weight_kg as null. A session made only of them
    has an unknown volume, not a zero one — a 0.0 would flow into the chronic
    window and make a session that happened look like a rest day."""
    workout = _ingest(
        session,
        _workout([("Chest Dip", [{"weight_kg": None, "reps": 15}] * 3)]),
    )
    assert workout.total_volume_kg is None
    assert workout.set_count == 3  # the sets happened; only the volume is unknown


def test_unweighted_sets_do_not_stop_the_rest_counting(session):
    """A mixed session still reports the volume it can compute. 80x10 + 82x8
    = 1456; the two null-weight dip sets contribute nothing and must not
    turn the whole session's volume into None."""
    workout = _ingest(
        session,
        _workout(
            [
                ("Chest Press (Machine)", [{"weight_kg": 80, "reps": 10}, {"weight_kg": 82, "reps": 8}]),
                ("Chest Dip", [{"weight_kg": None, "reps": 15}] * 2),
            ]
        ),
    )
    assert workout.total_volume_kg == 1456.0


def test_session_rpe_is_the_mean_of_working_sets(session):
    """Hevy logs RPE per set; session_load wants one number. Mean of the
    working sets: (8 + 9 + 10) / 3 = 9.0, with the warm-up's 4 excluded — a
    light warm-up must not drag the session's rating down."""
    workout = _ingest(
        session,
        _workout(
            [
                (
                    "Chest Press (Machine)",
                    [
                        {"weight_kg": 40, "reps": 10, "rpe": 4, "type": "warmup"},
                        {"weight_kg": 80, "reps": 10, "rpe": 8},
                        {"weight_kg": 82, "reps": 10, "rpe": 9},
                        {"weight_kg": 82, "reps": 8, "rpe": 10},
                    ],
                )
            ]
        ),
    )
    assert workout.perceived_exertion_1_10 == 9.0


def test_session_rpe_is_null_when_none_was_logged(session):
    """The entire history before September 2026. Never 0, which would read as
    an effortless session rather than an unrecorded one."""
    workout = _ingest(
        session,
        _workout([("Chest Press (Machine)", [{"weight_kg": 80, "reps": 10}])]),
    )
    assert workout.perceived_exertion_1_10 is None


def test_blank_description_is_stored_as_null(session):
    """Hevy sends "" for an unset description, never null. Storing the empty
    string would put a falsy non-null into a column read as "present"."""
    workout = _ingest(session, _workout([("Chest Dip", [{"weight_kg": None, "reps": 15}])]))
    assert workout.notes is None
    assert workout.title == "Upper body"


def test_offset_timestamps_parse_and_attribute_locally(session):
    """The real API sends +00:00, not the Z the old fixture used. 19:28 UTC on
    8 September is 20:28 BST, so the session belongs to the 8th either way —
    but the parse has to succeed for that to mean anything."""
    workout = _ingest(session, _workout([("Chest Dip", [{"weight_kg": None, "reps": 15}])]))
    assert workout.date.isoformat() == "2026-09-08"
    assert workout.duration_min == 39.1
