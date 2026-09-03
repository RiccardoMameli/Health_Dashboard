"""Sleep, cardiovascular, activity, body composition and nutrition."""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import Date as SADate
from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SleepSession(Base):
    """A single sleep session.

    Plan 5.1: a session belongs to the day it ENDS on. See app/services/timeutil.py.
    """

    __tablename__ = "sleep_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), index=True)
    start_at: Mapped[datetime]
    end_at: Mapped[datetime]
    duration_min: Mapped[int | None] = mapped_column(Integer)
    time_in_bed_min: Mapped[int | None] = mapped_column(Integer)
    efficiency_pct: Mapped[float | None] = mapped_column(Float)
    deep_min: Mapped[int | None] = mapped_column(Integer)
    rem_min: Mapped[int | None] = mapped_column(Integer)
    light_min: Mapped[int | None] = mapped_column(Integer)
    awake_min: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    min_hr: Mapped[float | None] = mapped_column(Float)
    avg_hrv_ms: Mapped[float | None] = mapped_column(Float)
    avg_spo2: Mapped[float | None] = mapped_column(Float)
    respiratory_rate: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[str] = mapped_column(String(16), default="high")


class HeartMetric(Base):
    __tablename__ = "heart_metrics"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    resting_hr: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float)
    vo2max: Mapped[float | None] = mapped_column(Float)
    stress_avg: Mapped[float | None] = mapped_column(Float)
    energy_score: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(32))


class ActivityDaily(Base):
    __tablename__ = "activity_daily"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Float)
    active_energy_kcal: Mapped[float | None] = mapped_column(Float)
    total_energy_kcal: Mapped[float | None] = mapped_column(Float)
    active_minutes: Mapped[int | None] = mapped_column(Integer)
    floors: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String(32))


class BodyMeasurement(Base):
    """Withings scale output (plan 3.2), plus manual tape measurements."""

    __tablename__ = "body_measurements"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    muscle_mass_kg: Mapped[float | None] = mapped_column(Float)
    bone_mass_kg: Mapped[float | None] = mapped_column(Float)
    water_pct: Mapped[float | None] = mapped_column(Float)
    waist_cm: Mapped[float | None] = mapped_column(Float)
    chest_cm: Mapped[float | None] = mapped_column(Float)
    arm_cm: Mapped[float | None] = mapped_column(Float)
    thigh_cm: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(32))


class NutritionDaily(Base):
    """Macros are NULL under MyFitnessPal (plan 3.4). completeness_pct must say so."""

    __tablename__ = "nutrition_daily"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    calories_kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    fibre_g: Mapped[float | None] = mapped_column(Float)
    sodium_mg: Mapped[float | None] = mapped_column(Float)
    water_ml: Mapped[float | None] = mapped_column(Float)
    # Deferred per D6; columns exist now and sit NULL.
    alcohol_units: Mapped[float | None] = mapped_column(Float)
    caffeine_mg: Mapped[float | None] = mapped_column(Float)
    last_caffeine_at: Mapped[datetime | None]
    last_meal_at: Mapped[datetime | None]
    source: Mapped[str | None] = mapped_column(String(32))
    completeness_pct: Mapped[float | None] = mapped_column(Float)
