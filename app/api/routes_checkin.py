"""Check-in endpoints.

Plan 7: under 30 seconds, partial submissions accepted, backfill up to 3 days
flagged submitted_late so recall bias can be tested for later. R1 says
adherence here is the difference between the project working and not.
"""

from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db, require_token
from app.models import Checkin
from app.schemas.checkin import CheckinIn, CheckinOut, CheckinStatus
from app.services.ingest import ensure_day
from app.services.timeutil import local_date, utcnow

router = APIRouter(prefix="/checkin", tags=["checkin"], dependencies=[Depends(require_token)])

MAX_BACKFILL_DAYS = 3


@router.post("", response_model=CheckinOut, status_code=201)
def submit_checkin(payload: CheckinIn, session: Session = Depends(db)) -> Checkin:
    today = local_date(utcnow())
    day = payload.date or today

    if day > today:
        raise HTTPException(400, "Cannot check in for a future date")
    if (today - day).days > MAX_BACKFILL_DAYS:
        raise HTTPException(
            400,
            f"Backfill is limited to {MAX_BACKFILL_DAYS} days. "
            "Older recall is not reliable enough to correlate against.",
        )

    ensure_day(session, day)
    row = session.get(Checkin, day)
    if row is None:
        row = Checkin(date=day)
        session.add(row)

    data = payload.model_dump(exclude={"date"})
    for key, value in data.items():
        setattr(row, key, value)
    row.submitted_at = utcnow()
    row.submitted_late = day < today

    session.commit()
    session.refresh(row)
    return row


@router.get("/status", response_model=CheckinStatus)
def checkin_status(session: Session = Depends(db)) -> CheckinStatus:
    today = local_date(utcnow())
    todays = session.get(Checkin, today)

    # Streak: consecutive days back from today (or yesterday if today is
    # still outstanding, so an unfinished morning does not zero the streak).
    anchor = today if todays is not None else today - timedelta(days=1)
    streak = 0
    cursor = anchor
    while session.get(Checkin, cursor) is not None:
        streak += 1
        cursor -= timedelta(days=1)

    window_start = today - timedelta(days=29)
    completed = session.execute(
        select(func.count(Checkin.date)).where(Checkin.date >= window_start)
    ).scalar_one()

    prefill = todays
    if prefill is None:
        prefill = session.execute(
            select(Checkin).order_by(Checkin.date.desc()).limit(1)
        ).scalar_one_or_none()

    return CheckinStatus(
        date=today,
        submitted=todays is not None,
        streak_days=streak,
        completion_rate_30d=round(completed / 30 * 100, 1),
        prefill=CheckinOut.model_validate(prefill) if prefill else None,
    )


@router.get("", response_model=list[CheckinOut])
def list_checkins(
    start: Date | None = None,
    end: Date | None = None,
    session: Session = Depends(db),
) -> list[Checkin]:
    stmt = select(Checkin).order_by(Checkin.date.desc())
    if start:
        stmt = stmt.where(Checkin.date >= start)
    if end:
        stmt = stmt.where(Checkin.date <= end)
    return list(session.execute(stmt.limit(400)).scalars())


@router.get("/{day}", response_model=CheckinOut)
def get_checkin(day: Date, session: Session = Depends(db)) -> Checkin:
    row = session.get(Checkin, day)
    if row is None:
        raise HTTPException(404, "No check-in for that date")
    return row
