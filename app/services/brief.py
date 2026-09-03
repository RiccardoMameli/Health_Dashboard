"""Generate, store and retrieve the daily brief (plan 9).

The order is fixed and it matters: compute every number first, hand the model
the computed summary, validate what comes back, then store the input snapshot
alongside the output so the morning can be audited or re-run later.
"""

from __future__ import annotations

import logging
from datetime import date as Date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import GeneratedBrief, generate_brief
from app.config import Settings, get_settings
from app.models import Brief
from app.services.metrics_engine import build_brief_input, compute_day, persist
from app.services.timeutil import utcnow

log = logging.getLogger(__name__)

BRIEF_TYPE_DAILY = "daily"


def prepare_input(session: Session, day: Date, settings: Settings | None = None) -> dict:
    """Compute the day, persist its metrics, and render the §9.1 contract."""
    settings = settings or get_settings()
    computed = compute_day(session, day, settings)
    persist(session, computed)
    return build_brief_input(session, computed, phase=settings.brief_phase)


def store(
    session: Session,
    day: Date,
    payload: dict,
    generated: GeneratedBrief,
    *,
    phase: str,
) -> Brief:
    """Upsert the day's brief. Re-running the morning job is always safe."""
    row = session.execute(
        select(Brief).where(Brief.date == day, Brief.type == BRIEF_TYPE_DAILY)
    ).scalar_one_or_none()
    if row is None:
        row = Brief(date=day, type=BRIEF_TYPE_DAILY)
        session.add(row)

    row.model = generated.model
    row.prompt_version = generated.prompt_version
    row.phase = phase
    row.input_snapshot = payload
    row.output = {
        **generated.output.model_dump(),
        # Kept with the brief, not in a log file: if the model quoted a number
        # the engine never produced, that fact belongs next to the brief.
        "verification": {
            "numbers_traceable": generated.verified,
            "untraceable_numbers": generated.untraceable_numbers,
            "attempts": generated.attempts,
        },
    }
    row.generated_at = utcnow()
    session.commit()
    return row


def generate_and_store(
    session: Session,
    day: Date,
    *,
    settings: Settings | None = None,
    client=None,
) -> Brief:
    """The whole morning job for one day, minus delivery."""
    settings = settings or get_settings()
    payload = prepare_input(session, day, settings)
    generated = generate_brief(
        payload, phase=settings.brief_phase, settings=settings, client=client
    )
    if not generated.verified:
        log.error(
            "Brief for %s quoted numbers absent from its input: %s",
            day,
            generated.untraceable_numbers,
        )
    return store(session, day, payload, generated, phase=settings.brief_phase)


def get(session: Session, day: Date) -> Brief | None:
    return session.execute(
        select(Brief).where(Brief.date == day, Brief.type == BRIEF_TYPE_DAILY)
    ).scalar_one_or_none()


def record_feedback(
    session: Session, brief_id: int, rating: str, note: str | None = None
) -> Brief | None:
    """One tap, stored. This is the ground-truth signal (plan 9.4)."""
    row = session.get(Brief, brief_id)
    if row is None:
        return None
    row.feedback_rating = rating
    row.feedback_note = note
    session.commit()
    return row
