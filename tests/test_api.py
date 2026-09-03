"""API behaviour: auth, check-in rules, supplements, data health."""

from datetime import timedelta

from app.db import session_scope
from app.seed.run import main as seed
from app.services.timeutil import local_date, utcnow


def test_health_endpoint_is_public(client):
    assert client.get("/health").json()["status"] == "ok"


def test_endpoints_require_a_token(client):
    assert client.get("/api/v1/checkin/status").status_code == 401
    assert (
        client.get("/api/v1/checkin/status", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_submit_and_read_back_a_checkin(client, auth):
    payload = {
        "overall_1_10": 7,
        "energy_1_5": 3,
        "stress_1_5": 4,
        "tags": ["work_stress", "late_screen"],
        "free_text": "Busy day.",
    }
    response = client.post("/api/v1/checkin", json=payload, headers=auth)
    assert response.status_code == 201
    body = response.json()
    assert body["overall_1_10"] == 7
    assert body["submitted_late"] is False
    assert body["tags"] == ["late_screen", "work_stress"]

    status = client.get("/api/v1/checkin/status", headers=auth).json()
    assert status["submitted"] is True
    assert status["streak_days"] == 1


def test_partial_submission_is_accepted(client, auth):
    """Plan 7.1: only overall_1_10 is required. A partial beats none."""
    response = client.post("/api/v1/checkin", json={"overall_1_10": 4}, headers=auth)
    assert response.status_code == 201
    assert response.json()["energy_1_5"] is None


def test_unknown_tags_are_rejected(client, auth):
    response = client.post(
        "/api/v1/checkin", json={"overall_1_10": 5, "tags": ["hungover"]}, headers=auth
    )
    assert response.status_code == 422


def test_out_of_range_scores_are_rejected(client, auth):
    assert (
        client.post("/api/v1/checkin", json={"overall_1_10": 11}, headers=auth).status_code == 422
    )
    assert (
        client.post(
            "/api/v1/checkin", json={"overall_1_10": 5, "energy_1_5": 9}, headers=auth
        ).status_code
        == 422
    )


def test_backfill_within_three_days_is_flagged_late(client, auth):
    day = local_date(utcnow()) - timedelta(days=2)
    response = client.post(
        "/api/v1/checkin", json={"overall_1_10": 6, "date": day.isoformat()}, headers=auth
    )
    assert response.status_code == 201
    assert response.json()["submitted_late"] is True


def test_backfill_beyond_three_days_is_refused(client, auth):
    day = local_date(utcnow()) - timedelta(days=5)
    response = client.post(
        "/api/v1/checkin", json={"overall_1_10": 6, "date": day.isoformat()}, headers=auth
    )
    assert response.status_code == 400


def test_future_checkin_is_refused(client, auth):
    day = local_date(utcnow()) + timedelta(days=1)
    response = client.post(
        "/api/v1/checkin", json={"overall_1_10": 6, "date": day.isoformat()}, headers=auth
    )
    assert response.status_code == 400


def test_resubmitting_the_same_day_updates_rather_than_duplicates(client, auth):
    client.post("/api/v1/checkin", json={"overall_1_10": 3}, headers=auth)
    client.post("/api/v1/checkin", json={"overall_1_10": 8}, headers=auth)
    rows = client.get("/api/v1/checkin", headers=auth).json()
    assert len(rows) == 1
    assert rows[0]["overall_1_10"] == 8


def test_streak_counts_consecutive_days(client, auth):
    today = local_date(utcnow())
    for offset in (2, 1, 0):
        client.post(
            "/api/v1/checkin",
            json={"overall_1_10": 6, "date": (today - timedelta(days=offset)).isoformat()},
            headers=auth,
        )
    assert client.get("/api/v1/checkin/status", headers=auth).json()["streak_days"] == 3


def test_seeded_stack_and_checklist(client, auth):
    seed()
    supplements = client.get("/api/v1/supplements", headers=auth).json()
    assert len(supplements) == 8
    assert {s["name"] for s in supplements} >= {"Creatine", "Magnesium complex", "BCAA"}

    checklist = client.get("/api/v1/supplements/checklist", headers=auth).json()
    names = {i["supplement"]["name"] for i in checklist["items"]}
    # No workout logged today, so workout-day items are hidden (plan 8.2).
    assert "BCAA" not in names
    assert "Beta-alanine" not in names
    assert "Creatine" in names
    assert checklist["workout_logged"] is False


def test_seed_is_idempotent(client, auth):
    seed()
    seed()
    assert len(client.get("/api/v1/supplements", headers=auth).json()) == 8


def test_seeding_records_a_protocol_start_for_each_supplement(client, auth):
    """Without a dated start there is no 'before' for any later comparison."""
    seed()
    changes = client.get("/api/v1/supplements/protocol-changes", headers=auth).json()
    assert len(changes) == 8
    assert all(c["change_type"] == "start" for c in changes)


def test_log_all_marks_todays_scheduled_items(client, auth):
    seed()
    assert client.post("/api/v1/supplements/log/all", headers=auth).status_code == 204
    checklist = client.get("/api/v1/supplements/checklist", headers=auth).json()
    assert all(item["taken"] for item in checklist["items"])
    assert checklist["adherence_7d_pct"] > 0


def test_protocol_change_can_be_recorded(client, auth):
    seed()
    response = client.post(
        "/api/v1/supplements/protocol-changes",
        json={
            "entity_type": "supplement",
            "change_type": "dose_change",
            "old_value": "420 mg",
            "new_value": "210 mg",
            "rationale": "Testing whether the full dose is needed",
        },
        headers=auth,
    )
    assert response.status_code == 201
    assert response.json()["change_type"] == "dose_change"


def test_data_health_reports_unconfigured_sources_without_pretending(client, auth):
    body = client.get("/api/v1/sync/health", headers=auth).json()
    sources = {s["source"]: s for s in body["sources"]}
    assert sources["hevy"]["configured"] is False
    assert sources["hevy"]["last_success_at"] is None
    # Not configured is not the same as stale; don't alarm on a source you
    # have not connected yet.
    assert sources["hevy"]["stale"] is False
    assert body["checkin_completion_rate_30d"] == 0.0


def test_overnight_wear_rate_uses_the_no_watch_tag(client, auth):
    today = local_date(utcnow())
    for offset, tags in enumerate([[], ["no_watch"], [], []]):
        client.post(
            "/api/v1/checkin",
            json={
                "overall_1_10": 6,
                "date": (today - timedelta(days=min(offset, 3))).isoformat(),
                "tags": tags,
            },
            headers=auth,
        )
    body = client.get("/api/v1/sync/health", headers=auth).json()
    assert body["overnight_wear_rate_7d"] is not None


def test_today_screen_does_not_invent_a_readiness_score(client, auth):
    """Plan C2/C6: no number the system cannot yet compute."""
    body = client.get("/api/v1/today", headers=auth).json()
    assert body["readiness"] is None
    assert body["phase"] == "baseline"
    assert body["checkin_submitted"] is False


def test_export_returns_every_table(client, auth):
    seed()
    client.post("/api/v1/checkin", json={"overall_1_10": 7}, headers=auth)
    body = client.get("/api/v1/export", headers=auth).json()
    assert len(body["checkins"]) == 1
    assert len(body["supplements"]) == 8
    assert "sleep_sessions" in body


def test_unknown_sync_source_is_404(client, auth):
    assert client.post("/api/v1/sync/fitbit", headers=auth).status_code == 404


def test_sync_failure_is_recorded_as_a_failed_run(client, auth):
    """A sync that dies must leave a trace, or the Data Health screen lies."""
    response = client.post("/api/v1/sync/hevy", headers=auth)
    assert response.status_code == 502
    with session_scope() as session:
        from sqlalchemy import select

        from app.models import SyncRun

        run = session.execute(select(SyncRun)).scalar_one()
        assert run.status == "failed"
        assert "HEVY_API_KEY" in run.error_message
