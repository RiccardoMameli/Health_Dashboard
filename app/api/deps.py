"""Shared dependencies. Single-user bearer auth (plan 13)."""

import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session

SessionDep = Depends(get_session)


def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """No registration endpoint, one token, constant-time comparison.

    This is the whole auth model. It removes essentially all of the attack
    surface a multi-user system would carry.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    supplied = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(supplied, settings.api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def db(session: Session = SessionDep) -> Session:
    return session
