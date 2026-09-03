"""Hevy adapter (plan 3.1).

    GET /v1/workouts                     paginated, pageSize caps at 10
    GET /v1/workouts/events?since=<ISO>  incremental — use this after backfill
    Auth: header  api-key: <uuid>

Backfill is many sequential requests because of the page-size cap, so it
throttles and backs off on 429. There is no documented rate limit; being
conservative costs a few minutes once.
"""

from __future__ import annotations

import logging
import time
from datetime import date as Date
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import Adapter, SyncResult
from app.config import get_settings
from app.models import SyncRun, Workout, WorkoutSet
from app.services.ingest import ensure_day, store_raw
from app.services.timeutil import local_date, to_utc, utcnow

log = logging.getLogger(__name__)

SOURCE = "hevy"
PAGE_SIZE = 10  # API maximum for /v1/workouts
REQUEST_DELAY_SEC = 0.35
MAX_RETRIES = 5


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _volume_kg(sets: list[dict[str, Any]]) -> float:
    """Volume load = sum(weight x reps), warm-up sets excluded.

    Warm-ups are excluded deliberately: including them makes a deload week
    with long warm-ups look like a hard week.
    """
    total = 0.0
    for s in sets:
        if (s.get("type") or "normal") == "warmup":
            continue
        weight = s.get("weight_kg")
        reps = s.get("reps")
        if weight is not None and reps is not None:
            total += float(weight) * int(reps)
    return round(total, 2)


class HevyClient:
    def __init__(self, api_key: str, base_url: str, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"api-key": api_key, "Accept": "application/json"},
            timeout=30.0,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(MAX_RETRIES):
            response = self._client.get(path, params=params)
            if response.status_code == 429:
                backoff = 2**attempt
                log.warning("Hevy rate limited; sleeping %ss", backoff)
                time.sleep(backoff)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"Hevy rate limit not cleared after {MAX_RETRIES} attempts")

    def close(self) -> None:
        self._client.close()


class HevyAdapter(Adapter):
    source = SOURCE

    def __init__(self, client: HevyClient | None = None):
        settings = get_settings()
        if client is None:
            if not settings.hevy_api_key:
                raise RuntimeError("HEVY_API_KEY is not set")
            client = HevyClient(settings.hevy_api_key, settings.hevy_base_url)
        self.client = client

    # -- public API ------------------------------------------------------

    def backfill(self, session: Session, *, since: Date | None = None) -> SyncResult:
        result = SyncResult(source=SOURCE)
        page = 1
        while True:
            payload = self.client.get("/v1/workouts", params={"page": page, "pageSize": PAGE_SIZE})
            workouts = payload.get("workouts") or []
            if not workouts:
                break
            for raw in workouts:
                self._ingest_workout(session, raw, result)
            page_count = payload.get("page_count")
            if page_count is not None and page >= int(page_count):
                break
            page += 1
            time.sleep(REQUEST_DELAY_SEC)
        session.flush()
        return result

    def incremental(self, session: Session) -> SyncResult:
        result = SyncResult(source=SOURCE)
        since = self._last_success(session)
        page = 1
        while True:
            payload = self.client.get(
                "/v1/workouts/events",
                params={"since": since.isoformat(), "page": page, "pageSize": PAGE_SIZE},
            )
            events = payload.get("events") or []
            if not events:
                break
            for event in events:
                kind = event.get("type")
                if kind == "updated":
                    self._ingest_workout(session, event.get("workout") or {}, result)
                elif kind == "deleted":
                    self._delete_workout(session, str(event.get("id")), result)
            page_count = payload.get("page_count")
            if page_count is not None and page >= int(page_count):
                break
            page += 1
            time.sleep(REQUEST_DELAY_SEC)
        session.flush()
        return result

    # -- internals -------------------------------------------------------

    def _last_success(self, session: Session) -> datetime:
        """Resume point: the start of the last successful run, minus nothing.

        Using started_at rather than finished_at means a workout logged while
        the previous sync was mid-flight is picked up next time instead of
        falling through the gap.
        """
        row = session.execute(
            select(SyncRun)
            .where(SyncRun.source == SOURCE, SyncRun.status == "success")
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return datetime(1970, 1, 1, tzinfo=utcnow().tzinfo)
        return row.started_at

    def _delete_workout(self, session: Session, source_id: str, result: SyncResult) -> None:
        existing = session.execute(
            select(Workout).where(Workout.source == SOURCE, Workout.source_record_id == source_id)
        ).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            result.notes.append(f"deleted workout {source_id}")

    def _ingest_workout(
        self, session: Session, raw: dict[str, Any], result: SyncResult
    ) -> Workout | None:
        source_id = raw.get("id")
        if not source_id:
            result.records_skipped += 1
            return None
        source_id = str(source_id)

        start_at = _parse_dt(raw.get("start_time"))
        end_at = _parse_dt(raw.get("end_time"))
        if start_at is None:
            result.records_skipped += 1
            return None

        store_raw(
            session,
            source=SOURCE,
            source_record_id=source_id,
            record_type="workout",
            payload=raw,
        )

        flat_sets: list[dict[str, Any]] = []
        for exercise in raw.get("exercises") or []:
            for index, s in enumerate(exercise.get("sets") or []):
                flat_sets.append(
                    {
                        "exercise_name": exercise.get("title") or "Unknown",
                        "exercise_template_id": exercise.get("exercise_template_id"),
                        "set_index": s.get("index", index),
                        "type": s.get("type") or "normal",
                        "weight_kg": s.get("weight_kg"),
                        "reps": s.get("reps"),
                        "rpe": s.get("rpe"),
                        "distance_m": s.get("distance_meters"),
                        "duration_sec": s.get("duration_seconds"),
                    }
                )

        day = local_date(start_at)
        ensure_day(session, day)

        duration_min = None
        if end_at is not None:
            duration_min = round((end_at - start_at).total_seconds() / 60, 1)

        workout = session.execute(
            select(Workout).where(Workout.source == SOURCE, Workout.source_record_id == source_id)
        ).scalar_one_or_none()

        fields = {
            "date": day,
            "start_at": start_at,
            "end_at": end_at,
            "type": "strength",
            "duration_min": duration_min,
            "title": raw.get("title"),
            "notes": raw.get("description"),
            "total_volume_kg": _volume_kg(flat_sets),
            "set_count": len([s for s in flat_sets if s["type"] != "warmup"]),
        }

        if workout is None:
            workout = Workout(source=SOURCE, source_record_id=source_id, **fields)
            session.add(workout)
        else:
            for key, value in fields.items():
                setattr(workout, key, value)
            # Sets are replaced wholesale: Hevy sends the full workout on
            # every update, and diffing set-by-set buys nothing.
            workout.sets.clear()
            session.flush()

        session.flush()
        for s in flat_sets:
            workout.sets.append(
                WorkoutSet(
                    exercise_name=s["exercise_name"],
                    exercise_template_id=s["exercise_template_id"],
                    set_index=s["set_index"],
                    set_type=s["type"],
                    weight_kg=s["weight_kg"],
                    reps=s["reps"],
                    rpe=s["rpe"],
                    distance_m=s["distance_m"],
                    duration_sec=s["duration_sec"],
                )
            )
        result.records_ingested += 1
        return workout
