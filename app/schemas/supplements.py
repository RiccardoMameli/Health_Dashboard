from datetime import date as Date
from datetime import datetime

from pydantic import BaseModel, Field


class SupplementOut(BaseModel):
    id: int
    name: str
    dose_amount: float | None
    dose_unit: str | None
    form: str | None
    schedule: str
    is_active: bool
    notes: str | None

    model_config = {"from_attributes": True}


class SupplementChecklistItem(BaseModel):
    supplement: SupplementOut
    taken: bool
    taken_at: datetime | None


class SupplementChecklist(BaseModel):
    """Renders only what is scheduled today (plan 8.2)."""

    date: Date
    items: list[SupplementChecklistItem]
    workout_logged: bool
    adherence_7d_pct: float


class SupplementLogIn(BaseModel):
    date: Date | None = None
    supplement_id: int
    taken: bool = True
    dose_override: float | None = None


class ProtocolChangeIn(BaseModel):
    entity_type: str = Field(..., pattern="^(supplement|training|sleep|diet)$")
    entity_id: int | None = None
    change_type: str = Field(..., pattern="^(start|stop|dose_change|timing_change)$")
    old_value: str | None = None
    new_value: str | None = None
    rationale: str | None = None
    changed_at: datetime | None = None


class ProtocolChangeOut(ProtocolChangeIn):
    id: int
    changed_at: datetime

    model_config = {"from_attributes": True}
