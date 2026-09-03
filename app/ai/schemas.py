"""The brief's output contract (plan 9.1).

Structured output, validated on arrival. The frontend renders these fields;
nothing downstream parses prose.
"""

from typing import Literal

from pydantic import BaseModel, Field

#: Plan 9.2 rule 4.
MAX_DO_TODAY = 3

Status = Literal["green", "amber", "red", "insufficient_data"]
Confidence = Literal["high", "medium", "low"]
Verdict = Literal["train_hard", "train_light", "active_recovery", "rest"]


class Why(BaseModel):
    """One observation and the evidence for it, with an honest confidence."""

    observation: str
    evidence: str
    confidence: Confidence


class Action(BaseModel):
    action: str
    rationale: str
    priority: int = Field(ge=1, le=MAX_DO_TODAY)


class TrainingRecommendation(BaseModel):
    verdict: Verdict
    rationale: str


class BriefOutput(BaseModel):
    """Plan 9.1 output contract."""

    headline: str
    status: Status
    why: list[Why] = Field(default_factory=list, max_length=5)
    do_today: list[Action] = Field(default_factory=list, max_length=MAX_DO_TODAY)
    avoid_today: list[str] = Field(default_factory=list, max_length=3)
    watch_items: list[str] = Field(default_factory=list, max_length=3)
    training_recommendation: TrainingRecommendation | None = None
    supplement_note: str | None = None
    data_caveats: list[str] = Field(default_factory=list, max_length=5)
    proposed_experiment: str | None = None
