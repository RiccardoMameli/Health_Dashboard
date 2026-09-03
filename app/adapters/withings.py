"""Withings adapter (plan 3.2).

OAuth2 authorisation code flow against the Public Health Data API, free tier.
Weight and body composition come from Measure - Getmeas.

Plan R10 is the thing to get right here: Withings rotates the refresh token
on every refresh, and the old one dies immediately. Persist the new pair in
the same transaction as the request that produced it, or sync silently stops
working a fortnight from now with no error anywhere.
"""

from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.adapters.base import Adapter, SyncResult
from app.config import get_settings
from app.models import BodyMeasurement, OAuthToken
from app.services.ingest import ensure_day, store_raw, upsert
from app.services.timeutil import local_date, utcnow

log = logging.getLogger(__name__)

SOURCE = "withings"
PROVIDER = "withings"

# Withings measure type codes -> our column names, with the unit conversion
# each one needs. Values arrive as (value, unit) where real = value * 10**unit.
MEASURE_TYPES: dict[int, str] = {
    1: "weight_kg",
    5: "fat_free_mass_kg",  # not stored directly; used to derive muscle mass
    6: "body_fat_pct",
    8: "fat_mass_kg",  # not stored directly
    76: "muscle_mass_kg",
    77: "water_pct",
    88: "bone_mass_kg",
}

SCOPE = "user.metrics"


class WithingsAuthError(RuntimeError):
    pass


class WithingsClient:
    """Thin transport. Token lifecycle is handled by the adapter."""

    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self._client = client or httpx.Client(base_url=base_url, timeout=30.0)

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, data=data)
        response.raise_for_status()
        payload = response.json()
        # Withings returns HTTP 200 with a non-zero status field on failure.
        if payload.get("status") not in (0, None):
            raise WithingsAuthError(
                f"Withings API status {payload.get('status')}: {payload.get('error')}"
            )
        return payload

    def close(self) -> None:
        self._client.close()


class WithingsAdapter(Adapter):
    source = SOURCE

    def __init__(self, client: WithingsClient | None = None):
        self.settings = get_settings()
        self.client = client or WithingsClient(self.settings.withings_base_url)

    # -- OAuth -----------------------------------------------------------

    def authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.withings_client_id or "",
            "scope": SCOPE,
            "redirect_uri": self.settings.withings_redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
        return f"{self.settings.withings_auth_url}?{query}"

    def exchange_code(self, session: Session, code: str) -> OAuthToken:
        payload = self.client.post(
            "/v2/oauth2",
            {
                "action": "requesttoken",
                "grant_type": "authorization_code",
                "client_id": self.settings.withings_client_id,
                "client_secret": self.settings.withings_client_secret,
                "code": code,
                "redirect_uri": self.settings.withings_redirect_uri,
            },
        )
        return self._persist_token(session, payload["body"])

    def _persist_token(self, session: Session, body: dict[str, Any]) -> OAuthToken:
        """Write the rotated pair immediately. See module docstring / R10."""
        expires_at = utcnow() + timedelta(seconds=int(body.get("expires_in", 3600)))
        token = session.get(OAuthToken, PROVIDER)
        if token is None:
            token = OAuthToken(provider=PROVIDER)
            session.add(token)
        token.access_token = body["access_token"]
        token.refresh_token = body["refresh_token"]
        token.expires_at = expires_at
        token.scope = body.get("scope")
        token.updated_at = utcnow()
        session.commit()
        return token

    def _access_token(self, session: Session) -> str:
        token = session.get(OAuthToken, PROVIDER)
        if token is None:
            raise WithingsAuthError(
                "No Withings token stored. Visit /api/v1/withings/authorize to connect."
            )
        # Refresh a minute early rather than racing the expiry.
        if token.expires_at <= utcnow() + timedelta(seconds=60):
            payload = self.client.post(
                "/v2/oauth2",
                {
                    "action": "requesttoken",
                    "grant_type": "refresh_token",
                    "client_id": self.settings.withings_client_id,
                    "client_secret": self.settings.withings_client_secret,
                    "refresh_token": token.refresh_token,
                },
            )
            token = self._persist_token(session, payload["body"])
        return token.access_token

    # -- sync ------------------------------------------------------------

    def backfill(self, session: Session, *, since: Date | None = None) -> SyncResult:
        start = since or Date(2010, 1, 1)
        return self._pull(
            session, startdate=int(datetime.combine(start, datetime.min.time()).timestamp())
        )

    def incremental(self, session: Session) -> SyncResult:
        lastupdate = int((utcnow() - timedelta(days=7)).timestamp())
        return self._pull(session, lastupdate=lastupdate)

    def _pull(self, session: Session, **window: int) -> SyncResult:
        result = SyncResult(source=SOURCE)
        access_token = self._access_token(session)

        params: dict[str, Any] = {
            "action": "getmeas",
            "meastypes": ",".join(str(k) for k in MEASURE_TYPES),
            "category": 1,  # real measurements, not user objectives
        }
        if "startdate" in window:
            params["startdate"] = window["startdate"]
            params["enddate"] = int(utcnow().timestamp())
        else:
            params["lastupdate"] = window["lastupdate"]

        offset = 0
        while True:
            if offset:
                params["offset"] = offset
            payload = self.client.post(
                "/measure",
                {**params, "access_token": access_token},
            )
            body = payload.get("body") or {}
            for group in body.get("measuregrps") or []:
                self._ingest_group(session, group, result)
            if not body.get("more"):
                break
            offset = int(body.get("offset", 0))
            if offset == 0:
                break
        session.flush()
        return result

    def _ingest_group(self, session: Session, group: dict[str, Any], result: SyncResult) -> None:
        group_id = group.get("grpid")
        if group_id is None:
            result.records_skipped += 1
            return
        group_id = str(group_id)

        store_raw(
            session,
            source=SOURCE,
            source_record_id=group_id,
            record_type="measuregrp",
            payload=group,
        )

        taken_at = datetime.fromtimestamp(int(group["date"]), tz=utcnow().tzinfo)
        day = local_date(taken_at)
        ensure_day(session, day)

        values: dict[str, float] = {}
        for measure in group.get("measures") or []:
            field = MEASURE_TYPES.get(int(measure["type"]))
            if field is None:
                continue
            values[field] = float(measure["value"]) * (10 ** int(measure["unit"]))

        # Withings reports fat-free mass on some scales and muscle mass on
        # others. Derive whichever is missing rather than dropping the day.
        weight = values.get("weight_kg")
        if "muscle_mass_kg" not in values and weight and "fat_mass_kg" in values:
            values["muscle_mass_kg"] = round(weight - values["fat_mass_kg"], 3)
        if "body_fat_pct" not in values and weight and "fat_mass_kg" in values:
            values["body_fat_pct"] = round(values["fat_mass_kg"] / weight * 100, 2)

        upsert(
            session,
            BodyMeasurement,
            {"date": day},
            {
                "weight_kg": _round(values.get("weight_kg"), 3),
                "body_fat_pct": _round(values.get("body_fat_pct"), 2),
                "muscle_mass_kg": _round(values.get("muscle_mass_kg"), 3),
                "bone_mass_kg": _round(values.get("bone_mass_kg"), 3),
                "water_pct": _round(values.get("water_pct"), 2),
                "source": SOURCE,
            },
        )
        result.records_ingested += 1


def _round(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)
