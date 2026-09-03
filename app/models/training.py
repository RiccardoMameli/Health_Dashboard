"""Workouts and sets. Hevy is the source for strength training (plan 3.1)."""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Date as SADate
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Workout(Base):
    __tablename__ = "workouts"
    __table_args__ = (UniqueConstraint("source", "source_record_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), index=True)
    start_at: Mapped[datetime]
    end_at: Mapped[datetime | None]
    type: Mapped[str] = mapped_column(String(16))  # strength | cardio | sport
    duration_min: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    perceived_exertion_1_10: Mapped[float | None] = mapped_column(Float)
    total_volume_kg: Mapped[float | None] = mapped_column(Float)
    set_count: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    energy_kcal: Mapped[float | None] = mapped_column(Float)

    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout", cascade="all, delete-orphan"
    )


class WorkoutSet(Base):
    __tablename__ = "workout_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), index=True
    )
    exercise_name: Mapped[str] = mapped_column(String(255), index=True)
    exercise_template_id: Mapped[str | None] = mapped_column(String(128), index=True)
    set_index: Mapped[int] = mapped_column(Integer)
    set_type: Mapped[str | None] = mapped_column(String(24))  # normal | warmup | dropset | failure
    weight_kg: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int | None] = mapped_column(Integer)
    rpe: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    is_pr: Mapped[bool] = mapped_column(Boolean, default=False)

    workout: Mapped[Workout] = relationship(back_populates="sets")
