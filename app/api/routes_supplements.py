"""Supplement adherence and — the important half — the protocol change log."""

from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db, require_token
from app.models import ProtocolChange, Supplement, SupplementLog, Workout
from app.schemas.supplements import (
    ProtocolChangeIn,
    ProtocolChangeOut,
    SupplementChecklist,
    SupplementChecklistItem,
    SupplementLogIn,
    SupplementOut,
)
from app.services.ingest import ensure_day
from app.services.supplements import adherence_7d, scheduled_on
from app.services.timeutil import local_date, utcnow

router = APIRouter(
    prefix="/supplements", tags=["supplements"], dependencies=[Depends(require_token)]
)


@router.get("", response_model=list[SupplementOut])
def list_supplements(session: Session = Depends(db)) -> list[Supplement]:
    return list(session.execute(select(Supplement).order_by(Supplement.name)).scalars())


@router.get("/checklist", response_model=SupplementChecklist)
def checklist(day: Date | None = None, session: Session = Depends(db)) -> SupplementChecklist:
    """Only what is scheduled today. Workout-day items appear only on workout days."""
    day = day or local_date(utcnow())

    workout_logged = (
        session.execute(select(func.count(Workout.id)).where(Workout.date == day)).scalar_one() > 0
    )

    supplements = list(
        session.execute(
            select(Supplement).where(Supplement.is_active.is_(True)).order_by(Supplement.name)
        ).scalars()
    )
    # The same rule the adherence figure uses, from the same function: two
    # definitions of "scheduled" is how the checklist and the percentage
    # beside it would come to disagree.
    scheduled = scheduled_on(supplements, day, {day} if workout_logged else set())

    logs = {
        row.supplement_id: row
        for row in session.execute(select(SupplementLog).where(SupplementLog.date == day)).scalars()
    }

    def item(s: Supplement) -> SupplementChecklistItem:
        return SupplementChecklistItem(
            supplement=SupplementOut.model_validate(s),
            taken=bool(logs.get(s.id) and logs[s.id].taken),
            taken_at=logs[s.id].taken_at if s.id in logs else None,
        )

    # Workout-day items are offered before the workout is known about. Hevy
    # syncs once, early in the morning, so an evening session is not in the
    # database until the next day — and without this the pre- and
    # post-workout items could never be ticked on the day they were taken,
    # then counted as missed once the workout synced. A tick here is stored
    # like any other and only counts toward adherence if a workout is later
    # logged for the day (`adherence_7d` counts scheduled pairs only), so
    # ticking one on a rest day inflates nothing.
    scheduled_ids = {s.id for s in scheduled}
    if_training = [s for s in supplements if s.id not in scheduled_ids]

    return SupplementChecklist(
        date=day,
        items=[item(s) for s in scheduled],
        workout_logged=workout_logged,
        adherence_7d_pct=adherence_7d(session, day),
        if_training=[item(s) for s in if_training],
    )


@router.post("/log", status_code=204)
def log_supplement(payload: SupplementLogIn, session: Session = Depends(db)) -> None:
    day = payload.date or local_date(utcnow())
    if session.get(Supplement, payload.supplement_id) is None:
        raise HTTPException(404, "Unknown supplement")
    ensure_day(session, day)

    row = session.get(SupplementLog, (day, payload.supplement_id))
    if row is None:
        row = SupplementLog(date=day, supplement_id=payload.supplement_id)
        session.add(row)
    row.taken = payload.taken
    row.taken_at = utcnow() if payload.taken else None
    row.dose_override = payload.dose_override
    session.commit()


@router.post("/log/all", status_code=204)
def log_all(day: Date | None = None, session: Session = Depends(db)) -> None:
    """The two-tap path: 'all taken' for everything scheduled today."""
    day = day or local_date(utcnow())
    ensure_day(session, day)
    for item in checklist(day=day, session=session).items:
        row = session.get(SupplementLog, (day, item.supplement.id))
        if row is None:
            row = SupplementLog(date=day, supplement_id=item.supplement.id)
            session.add(row)
        row.taken = True
        row.taken_at = row.taken_at or utcnow()
    session.commit()


@router.post("/protocol-changes", response_model=ProtocolChangeOut, status_code=201)
def add_protocol_change(
    payload: ProtocolChangeIn, session: Session = Depends(db)
) -> ProtocolChange:
    """Plan C5: this table, not the daily checklist, is what makes
    before/after analysis possible."""
    row = ProtocolChange(
        changed_at=payload.changed_at or utcnow(),
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        change_type=payload.change_type,
        old_value=payload.old_value,
        new_value=payload.new_value,
        rationale=payload.rationale,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.get("/protocol-changes", response_model=list[ProtocolChangeOut])
def list_protocol_changes(session: Session = Depends(db)) -> list[ProtocolChange]:
    return list(
        session.execute(
            select(ProtocolChange).order_by(ProtocolChange.changed_at.desc()).limit(200)
        ).scalars()
    )
