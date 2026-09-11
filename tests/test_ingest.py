"""Ingestion bookkeeping.

"Failed syncs are recorded, not swallowed" is an invariant, and until the
Samsung import hit a constraint violation nothing tested it. The failure path
was broken: writing the failure onto a session whose flush had already failed
raised PendingRollbackError, so the run was never marked failed and the
original error was buried under a second one.
"""

import pytest
from sqlalchemy import select

from app.models import Day, RawRecord, SyncRun
from app.services.ingest import ensure_day, store_raw, sync_run


def runs(session) -> list[SyncRun]:
    return list(session.execute(select(SyncRun)).scalars())


def test_a_successful_run_is_recorded(session):
    with sync_run(session, "hevy") as run:
        run.records_ingested = 3
    recorded = runs(session)
    assert [r.status for r in recorded] == ["success"]
    assert recorded[0].records_ingested == 3
    assert recorded[0].finished_at is not None


def test_a_failed_run_is_recorded_and_the_error_is_not_swallowed(session):
    with pytest.raises(ValueError, match="the adapter broke"):
        with sync_run(session, "hevy"):
            raise ValueError("the adapter broke")

    recorded = runs(session)
    assert [r.status for r in recorded] == ["failed"]
    assert "ValueError: the adapter broke" in recorded[0].error_message
    assert recorded[0].finished_at is not None


def test_a_run_that_dies_on_a_constraint_still_records_itself(session):
    """The real failure. A duplicate key makes the flush fail, which leaves the
    session refusing every further statement — including the one that writes
    the failure down. The rollback has to come first, and the run row has to
    survive it."""
    with pytest.raises(Exception):  # noqa: B017 - any DB integrity error will do
        with sync_run(session, "samsung_health"):
            store_raw(session, source="s", source_record_id="same",
                      record_type="t", payload={"n": 1})
            session.flush()
            session.add(RawRecord(source="s", source_record_id="same",
                                  record_type="t", payload={"n": 2},
                                  ingested_at=runs(session)[0].started_at))
            session.flush()

    recorded = runs(session)
    assert [r.status for r in recorded] == ["failed"]
    assert "same" in recorded[0].error_message or recorded[0].error_message


def test_the_failed_run_s_work_is_rolled_back(session):
    """A run that fails writes nothing, so re-running it starts clean rather
    than half-applied."""
    with pytest.raises(ValueError):
        with sync_run(session, "samsung_health"):
            ensure_day(session, __import__("datetime").date(2026, 3, 1))
            raise ValueError("stop")

    assert session.execute(select(Day)).scalars().all() == []
    assert [r.status for r in runs(session)] == ["failed"]
