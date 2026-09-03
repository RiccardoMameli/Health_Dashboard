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
