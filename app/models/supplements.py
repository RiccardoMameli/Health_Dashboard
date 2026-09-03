"""Supplement stack, daily adherence, and the protocol change log (plan 8).

Plan C5: intake tracking is low value, CHANGE tracking is high value. The
protocol_changes table is the important half — it is what makes before/after
analysis and the experiment engine possible.
"""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Date as SADate
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SCHEDULES = ("daily", "workout_day", "pre", "post", "bedtime")


class Supplement(Base):
    __tablename__ = "supplements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    dose_amount: Mapped[float | None] = mapped_column(Float)
    dose_unit: Mapped[str | None] = mapped_column(String(24))
    form: Mapped[str | None] = mapped_column(String(32))
    schedule: Mapped[str] = mapped_column(String(24), default="daily")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text)


class SupplementLog(Base):
    __tablename__ = "supplement_log"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    supplement_id: Mapped[int] = mapped_column(ForeignKey("supplements.id"), primary_key=True)
    taken: Mapped[bool] = mapped_column(Boolean, default=False)
    taken_at: Mapped[datetime | None]
    dose_override: Mapped[float | None] = mapped_column(Float)


class ProtocolChange(Base):
    """Every start, stop, dose change or timing change, dated, with a rationale."""

    __tablename__ = "protocol_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    changed_at: Mapped[datetime]
    entity_type: Mapped[str] = mapped_column(String(24))  # supplement|training|sleep|diet
    entity_id: Mapped[int | None] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(24))  # start|stop|dose_change|timing_change
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"))
