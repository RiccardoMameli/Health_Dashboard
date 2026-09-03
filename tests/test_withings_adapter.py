"""Withings: measurement parsing and — the one that matters — token rotation."""

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.adapters.withings import WithingsAdapter, WithingsClient
from app.models import BodyMeasurement, OAuthToken
from app.services.timeutil import utcnow
from tests.conftest import FIXTURES


def _adapter(handler) -> WithingsAdapter:
    transport = httpx.MockTransport(handler)
    client = WithingsClient(
        "https://wbsapi.withings.net",
        client=httpx.Client(transport=transport, base_url="https://wbsapi.withings.net"),
    )
    return WithingsAdapter(client)


@pytest.fixture
def measures():
    return json.loads((FIXTURES / "withings_getmeas.json").read_text())


def _seed_token(session, *, expired: bool = False) -> OAuthToken:
    token = OAuthToken(
        provider="withings",
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=utcnow() - timedelta(minutes=5) if expired else utcnow() + timedelta(hours=2),
        scope="user.metrics",
        updated_at=utcnow(),
    )
    session.add(token)
    session.commit()
    return token


def test_measures_are_scaled_by_their_unit_exponent(session, measures):
    """value 84230 with unit -3 is 84.230 kg, not 84230."""
    _seed_token(session)
    adapter = _adapter(lambda r: httpx.Response(200, json=measures))
    result = adapter.incremental(session)
    session.commit()

    assert result.records_ingested == 2
    rows = list(session.execute(select(BodyMeasurement).order_by(BodyMeasurement.date)).scalars())
    latest = rows[-1]
    assert latest.weight_kg == 84.23
    assert latest.body_fat_pct == 18.12
    assert latest.muscle_mass_kg == 68.95
    assert latest.bone_mass_kg == 3.42
    assert latest.water_pct == 55.4


def test_body_fat_is_derived_when_only_fat_mass_is_reported(session, measures):
    """Some Withings scales report fat mass rather than a percentage. Deriving
    it beats dropping the day."""
    _seed_token(session)
    _adapter(lambda r: httpx.Response(200, json=measures)).incremental(session)
    session.commit()

    rows = list(session.execute(select(BodyMeasurement).order_by(BodyMeasurement.date)).scalars())
    earlier = rows[0]
    assert earlier.weight_kg == 84.61
    # 15.34 / 84.61 * 100
    assert earlier.body_fat_pct == pytest.approx(18.13, abs=0.01)
    assert earlier.muscle_mass_kg == pytest.approx(69.27, abs=0.01)


def test_expired_token_is_refreshed_and_the_rotated_pair_is_persisted(session, measures):
    """Plan R10. Withings invalidates the old refresh token immediately; if the
    new one is not persisted, sync dies silently about a fortnight later."""
    _seed_token(session, expired=True)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "/v2/oauth2" in str(request.url):
            calls.append("refresh")
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "body": {
                        "access_token": "access-2",
                        "refresh_token": "refresh-2",
                        "expires_in": 10800,
                        "scope": "user.metrics",
                    },
                },
            )
        calls.append("measure")
        assert "access-2" in body, "measure call must use the refreshed access token"
        return httpx.Response(200, json=measures)

    _adapter(handler).incremental(session)
    session.commit()

    assert calls == ["refresh", "measure"]
    token = session.get(OAuthToken, "withings")
    session.refresh(token)
    assert token.access_token == "access-2"
    assert token.refresh_token == "refresh-2", "rotated refresh token was not persisted"
    assert token.expires_at > utcnow()


def test_valid_token_is_not_refreshed(session, measures):
    _seed_token(session)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append("refresh" if "/v2/oauth2" in str(request.url) else "measure")
        return httpx.Response(200, json=measures)

    _adapter(handler).incremental(session)
    assert calls == ["measure"]


def test_non_zero_status_is_raised_not_swallowed(session):
    """Withings returns HTTP 200 with an error status in the body. Treating
    that as success is how a broken sync reports itself as healthy."""
    from app.adapters.withings import WithingsAuthError

    _seed_token(session)
    adapter = _adapter(
        lambda r: httpx.Response(200, json={"status": 401, "error": "invalid_token"})
    )
    with pytest.raises(WithingsAuthError):
        adapter.incremental(session)


def test_ingestion_is_idempotent(session, measures):
    _seed_token(session)
    adapter = _adapter(lambda r: httpx.Response(200, json=measures))
    adapter.incremental(session)
    session.commit()
    adapter.incremental(session)
    session.commit()
    assert len(session.execute(select(BodyMeasurement)).scalars().all()) == 2
