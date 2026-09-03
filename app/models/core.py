"""Provenance, ingestion bookkeeping, and the calendar-day join key."""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy import Date as SADate
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncRun(Base):
    """One row per adapter invocation. The Data Health screen reads this."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|failed
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawRecord(Base):
    """Untouched source payload, retained forever.

    Plan 5.1: store raw, compute derived. A bad adapter can be fixed and
    re-run against these rows without going back to the source API.
    """

    __tablename__ = "raw_records"
    __table_args__ = (UniqueConstraint("source", "source_record_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_record_id: Mapped[str] = mapped_column(String(128))
    record_type: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict]
    ingested_at: Mapped[datetime]


class Day(Base):
    """One row per calendar date. Everything else hangs off this."""

    __tablename__ = "days"

    date: Mapped[Date] = mapped_column(SADate, primary_key=True)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
