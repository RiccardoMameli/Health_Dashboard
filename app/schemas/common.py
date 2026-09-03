from datetime import date as Date
from datetime import datetime

from pydantic import BaseModel


class SyncRunOut(BaseModel):
    source: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    records_ingested: int
    error_message: str | None

    model_config = {"from_attributes": True}


class SourceHealth(BaseModel):
    """One row of the Data Health screen (plan 10.1 screen 7)."""

    source: str
    configured: bool
    last_success_at: datetime | None
    last_status: str | None
    last_error: str | None
    records_last_run: int | None
    stale: bool


class DataHealthOut(BaseModel):
    generated_at: datetime
    sources: list[SourceHealth]
    overnight_wear_rate_7d: float | None
    checkin_completion_rate_30d: float
    days_with_data: int


class WorkoutSetOut(BaseModel):
    exercise_name: str
    set_index: int
    set_type: str | None
    weight_kg: float | None
    reps: int | None
    rpe: float | None

    model_config = {"from_attributes": True}


class WorkoutOut(BaseModel):
    id: int
    date: Date
    start_at: datetime
    type: str
    title: str | None
    duration_min: float | None
    total_volume_kg: float | None
    set_count: int | None
    source: str
    sets: list[WorkoutSetOut] = []

    model_config = {"from_attributes": True}


class BodyMeasurementOut(BaseModel):
    date: Date
    weight_kg: float | None
    body_fat_pct: float | None
    muscle_mass_kg: float | None
    water_pct: float | None
    source: str | None

    model_config = {"from_attributes": True}
