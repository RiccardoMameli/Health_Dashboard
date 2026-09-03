"""Ingestion primitives shared by every adapter.

Plan 4.1: normalise -> validate -> idempotent upsert -> retain raw.
Re-running any sync must be safe. That property is worth more than it looks:
it is what lets you fix an adapter bug and simply run it again.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date as Date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Day, RawRecord, SyncRun
from app.services.timeutil import utcnow


@contextmanager
def sync_run(session: Session, source: str) -> Iterator[SyncRun]:
    """Bookkeep one adapter invocation. Failures are recorded, not swallowed."""
    run = SyncRun(source=source, started_at=utcnow(), status="running", records_ingested=0)
    session.add(run)
    session.flush()
    try:
        yield run
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = utcnow()
        session.commit()
        raise
    else:
        run.status = "success"
        run.finished_at = utcnow()
        session.commit()


def store_raw(
    session: Session,
    *,
    source: str,
    source_record_id: str,
    record_type: str,
    payload: dict[str, Any],
) -> RawRecord:
    """Idempotent on (source, source_record_id). Later payloads overwrite earlier."""
    existing = session.execute(
        select(RawRecord).where(
            RawRecord.source == source,
            RawRecord.source_record_id == source_record_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.payload = payload
        existing.record_type = record_type
        existing.ingested_at = utcnow()
        return existing

    record = RawRecord(
        source=source,
        source_record_id=source_record_id,
        record_type=record_type,
        payload=payload,
        ingested_at=utcnow(),
    )
    session.add(record)
    return record


def ensure_day(session: Session, day: Date) -> Day:
    """Every dated row needs its `days` parent to exist first."""
    existing = session.get(Day, day)
    if existing is not None:
        return existing
    row = Day(date=day, is_excluded=False)
    session.add(row)
    session.flush()
    return row


def upsert(session: Session, model: type, pk: dict[str, Any], values: dict[str, Any]) -> Any:
    """Update-or-insert on a primary key, skipping None values.

    Nulls are never written over existing data: a source that has nothing to
    say about protein should not erase protein another source supplied.
    """
    obj = session.get(model, tuple(pk.values()) if len(pk) > 1 else next(iter(pk.values())))
    if obj is None:
        obj = model(**pk, **{k: v for k, v in values.items() if v is not None})
        session.add(obj)
        session.flush()
        return obj
    for key, value in values.items():
        if value is not None:
            setattr(obj, key, value)
    return obj
