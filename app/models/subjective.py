"""The subjective check-in (plan 7). The system's centre of gravity."""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy import Date as SADate
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Confounder tags, included from day one despite D6 (plan 7.2).
CONFOUNDER_TAGS = [
    "alcohol",
    "late_meal",
    "late_caffeine",
    "poor_sleep_env",
    "work_stress",
    "travel",
    "illness",
    "hangover",
    "late_screen",
    "dehydrated",
    "no_watch",
    "headache",
    "sore_throat",
]


class Checkin(Base):
    """Only overall_1_10 is required. A partial submission beats none (plan 7.1)."""

    __tablename__ = "checkins"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    submitted_at: Mapped[datetime]
    submitted_late: Mapped[bool] = mapped_column(Boolean, default=False)

    energy_1_5: Mapped[int | None] = mapped_column(Integer)
    mood_1_5: Mapped[int | None] = mapped_column(Integer)
    sleep_quality_1_5: Mapped[int | None] = mapped_column(Integer)
    soreness_1_5: Mapped[int | None] = mapped_column(Integer)
    motivation_1_5: Mapped[int | None] = mapped_column(Integer)
    focus_1_5: Mapped[int | None] = mapped_column(Integer)
    stress_1_5: Mapped[int | None] = mapped_column(Integer)

    overall_1_10: Mapped[int] = mapped_column(Integer)

    # Stored as JSON for Postgres/SQLite portability; semantically a string set.
    tags: Mapped[list | None]
    free_text: Mapped[str | None] = mapped_column(Text)
