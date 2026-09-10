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


def test_backfill_parses_workout_and_sets(session, workouts_payload):
    adapter = HevyAdapter(_client(lambda r: httpx.Response(200, json=workouts_payload)))
    result = adapter.backfill(session)
    session.commit()

    assert result.records_ingested == 1
    workout = session.execute(select(Workout)).scalar_one()
    assert workout.title == "Push A"
    assert workout.duration_min == 75.0
    assert workout.source == "hevy"
    assert len(workout.sets) == 4  # warm-up retained as a row...
    assert workout.set_count == 3  # ...but excluded from the working set count


def test_volume_load_excludes_warmups(session, workouts_payload):
    """80x8 + 80x7 + 45x10 = 1650. The 40x10 warm-up must not count, or a
    deload week with long warm-ups looks like a hard week."""
    adapter = HevyAdapter(_client(lambda r: httpx.Response(200, json=workouts_payload)))
    adapter.backfill(session)
    session.commit()
    workout = session.execute(select(Workout)).scalar_one()
    assert workout.total_volume_kg == 1650.0


def test_raw_payload_is_retained(session, workouts_payload):
    adapter = HevyAdapter(_client(lambda r: httpx.Response(200, json=workouts_payload)))
    adapter.backfill(session)
    session.commit()
    raw = session.execute(select(RawRecord)).scalar_one()
    assert raw.source == "hevy"
    assert raw.record_type == "workout"
    assert raw.payload["title"] == "Push A"


def test_backfill_is_idempotent(session, workouts_payload):
    """Re-running a sync must never duplicate. This property is what lets you
    fix an adapter bug and simply run it again."""
    adapter = HevyAdapter(_client(lambda r: httpx.Response(200, json=workouts_payload)))
    adapter.backfill(session)
    session.commit()
    adapter.backfill(session)
    session.commit()

    assert session.execute(select(Workout)).scalars().all().__len__() == 1
    assert len(session.execute(select(WorkoutSet)).scalars().all()) == 4
    assert len(session.execute(select(RawRecord)).scalars().all()) == 1


def test_updated_workout_replaces_its_sets(session, workouts_payload):
    adapter = HevyAdapter(_client(lambda r: httpx.Response(200, json=workouts_payload)))
    adapter.backfill(session)
    session.commit()

    edited = json.loads(json.dumps(workouts_payload))
    edited["workouts"][0]["exercises"][0]["sets"] = [
        {"index": 0, "type": "normal", "weight_kg": 85, "reps": 5, "rpe": 9}
    ]
    edited["workouts"][0]["title"] = "Push A (edited)"

    events = {
        "page": 1,
        "page_count": 1,
        "events": [{"type": "updated", "workout": edited["workouts"][0]}],
    }
    adapter2 = HevyAdapter(_client(lambda r: httpx.Response(200, json=events)))
    adapter2.incremental(session)
    session.commit()

    workout = session.execute(select(Workout)).scalar_one()
    assert workout.title == "Push A (edited)"
    assert len(workout.sets) == 2  # 1 bench + 1 overhead press
    assert workout.total_volume_kg == 85 * 5 + 45 * 10


def test_deleted_event_removes_the_workout(session, workouts_payload):
    adapter = HevyAdapter(_client(lambda r: httpx.Response(200, json=workouts_payload)))
    adapter.backfill(session)
    session.commit()

    events = {
        "page": 1,
        "page_count": 1,
        "events": [{"type": "deleted", "id": "b459cba5-cd7c-463c-bd8d-tc001"}],
    }
    HevyAdapter(_client(lambda r: httpx.Response(200, json=events))).incremental(session)
    session.commit()

    assert session.execute(select(Workout)).scalars().all() == []
    # Raw provenance survives the delete, deliberately.
    assert len(session.execute(select(RawRecord)).scalars().all()) == 1


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
