"""Workouts and sets. Hevy is the source for strength training (plan 3.1)."""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


class ExerciseTemplate(Base):
    """Hevy's catalogue entry for an exercise, cached locally.

    `workout_sets.exercise_template_id` is on every set already; this is what
    turns that id into a muscle group. Hevy serves it from
    `GET /v1/exercise_templates/{id}` one template at a time, and the catalogue
    barely changes, so it is fetched once and kept.

    Muscle groups come from Hevy's own fixed vocabulary rather than a mapping
    invented here: guessing "Chest Press (Machine)" trains the chest is easy,
    and guessing wrong on the fiftieth exercise is silent.
    """

    __tablename__ = "exercise_templates"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(32))
    primary_muscle_group: Mapped[str | None] = mapped_column(String(32), index=True)
    #: Hevy returns an array; stored as JSON because a set of secondaries has
    #: no natural column and is only ever read whole.
    secondary_muscle_groups: Mapped[list | None] = mapped_column(JSON)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime | None]
