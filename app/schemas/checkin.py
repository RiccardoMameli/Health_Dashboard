"""Check-in request/response contracts (plan 7.2)."""

from datetime import date as Date
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import CONFOUNDER_TAGS


class CheckinIn(BaseModel):
    """Only overall_1_10 is required. Everything else may be omitted."""

    date: Date | None = None  # defaults to today, local time

    energy_1_5: int | None = Field(None, ge=1, le=5)
    mood_1_5: int | None = Field(None, ge=1, le=5)
    sleep_quality_1_5: int | None = Field(None, ge=1, le=5)
    soreness_1_5: int | None = Field(None, ge=1, le=5)
    motivation_1_5: int | None = Field(None, ge=1, le=5)
    focus_1_5: int | None = Field(None, ge=1, le=5)
    stress_1_5: int | None = Field(None, ge=1, le=5)

    overall_1_10: int = Field(..., ge=1, le=10)

    tags: list[str] = Field(default_factory=list)
    free_text: str | None = None

    @field_validator("tags")
    @classmethod
    def known_tags(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(CONFOUNDER_TAGS))
        if unknown:
            raise ValueError(f"Unknown tags: {', '.join(unknown)}")
        return sorted(set(value))


class CheckinOut(BaseModel):
    date: Date
    submitted_at: datetime
    submitted_late: bool
    energy_1_5: int | None = None
    mood_1_5: int | None = None
    sleep_quality_1_5: int | None = None
    soreness_1_5: int | None = None
    motivation_1_5: int | None = None
    focus_1_5: int | None = None
    stress_1_5: int | None = None
    overall_1_10: int
    tags: list[str] = Field(default_factory=list)
    free_text: str | None = None

    model_config = {"from_attributes": True}


class CheckinStatus(BaseModel):
    """Drives the Today screen's prompt and the streak counter (plan 7.3)."""

    date: Date
    submitted: bool
    streak_days: int
    completion_rate_30d: float
    prefill: CheckinOut | None = None
