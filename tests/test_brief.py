"""The AI layer (plan 9).

No test here calls the API. What is tested is everything around the call:
the traceability guard, the retry, the phase lock, what gets stored, and what
the email renders — which is where the failures that matter would actually
happen.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.ai.client import BriefGenerationError, generate_brief
from app.ai.prompts import PHASE_CLAUSES, PROMPT_VERSION, system_prompt
from app.ai.schemas import BriefOutput
from app.ai.verify import untraceable_numbers
from app.config import Settings
from app.services import brief as brief_service
from app.services.email import EmailDeliveryError, render_html, send_brief
from tests.test_metrics_engine import TODAY, seed_history

PAYLOAD = {
    "date": "2026-09-04",
    "phase": "baseline",
    "data_completeness_pct": 87,
    "readiness": {"score": 62.0, "status": "amber"},
    "sleep": {"duration_min": 342, "baseline_min": 430, "efficiency_pct": 81},
    "cardio": {"resting_hr": 58, "baseline_rhr": 52, "hrv_ms": None},
    "training": {"acwr": 1.27, "yesterday": {"title": "Push A", "volume_kg": 9840}},
}


def brief(**overrides) -> BriefOutput:
    base = {
        "headline": "Sleep was 342 minutes against a baseline of 430 minutes.",
        "status": "amber",
        "why": [
            {
                "observation": "Resting heart rate is 58 bpm.",
                "evidence": "baseline 52 bpm",
                "confidence": "high",
            }
        ],
        "do_today": [{"action": "Log the check-in.", "rationale": "Not yet in.", "priority": 1}],
        "data_caveats": ["HRV was not measured."],
    }
    return BriefOutput.model_validate({**base, **overrides})


def plain(headline: str) -> BriefOutput:
    """A brief whose only number is the one under test."""
    return BriefOutput.model_validate({"headline": headline, "status": "amber"})


def seeded_brief(**overrides) -> BriefOutput:
    """A brief quoting the numbers the seeded month actually produces."""
    base = {
        "headline": "Sleep was 450 minutes, in line with the 450-minute baseline.",
        "status": "green",
        "why": [
            {
                "observation": "Resting heart rate is 52 bpm.",
                "evidence": "baseline 52 bpm",
                "confidence": "high",
            }
        ],
        "do_today": [{"action": "Log the check-in.", "rationale": "Not yet in.", "priority": 1}],
        "data_caveats": ["HRV was not measured."],
    }
    return BriefOutput.model_validate({**base, **overrides})


class FakeMessages:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed_output=self.outputs.pop(0),
            stop_reason="end_turn",
            stop_details=None,
            model="claude-opus-5",
        )


class FakeClient:
    def __init__(self, *outputs):
        self.messages = FakeMessages(outputs)


# ── the traceability guard ───────────────────────────────────────────────


def test_quoted_values_are_traceable():
    assert untraceable_numbers(brief(), PAYLOAD) == []


def test_a_unit_conversion_is_caught():
    """342 minutes is in the input. "5h42m" is arithmetic the model was told
    not to do, and reads exactly like a measurement."""
    bad = brief(headline="You slept 5h42m last night.")
    assert untraceable_numbers(bad, PAYLOAD) == ["5", "42"]


def test_an_invented_number_is_caught():
    bad = brief(headline="Your sleep efficiency has fallen 14% this week.")
    assert untraceable_numbers(bad, PAYLOAD) == ["14"]


def test_rounding_a_stored_value_is_traceable():
    payload = {"body": {"weight_ewma_kg": 84.23}}
    assert untraceable_numbers(plain("Weight trend sits at 84.2 kg."), payload) == []


def test_a_date_is_not_treated_as_a_measurement():
    assert (
        untraceable_numbers(brief(headline="On 2026-09-04 sleep was 342 minutes."), PAYLOAD) == []
    )


def test_numbers_quoted_from_a_string_field_are_allowed():
    payload = {"training": {"yesterday": {"title": "Push A2"}}}
    assert untraceable_numbers(plain("Yesterday was Push A2."), payload) == []


def test_every_readable_field_is_scanned():
    bad = brief(watch_items=["Resting HR above 65 bpm for three days."])
    assert "65" in untraceable_numbers(bad, PAYLOAD)


# ── generation ───────────────────────────────────────────────────────────


def test_generation_requires_a_key():
    with pytest.raises(BriefGenerationError, match="ANTHROPIC_API_KEY"):
        generate_brief(PAYLOAD, phase="baseline", settings=Settings(anthropic_api_key=None))


def test_a_clean_brief_is_returned_on_the_first_attempt():
    client = FakeClient(brief())
    result = generate_brief(PAYLOAD, phase="baseline", client=client)

    assert result.verified is True
    assert result.attempts == 1
    assert result.prompt_version == PROMPT_VERSION


def test_an_untraceable_number_triggers_one_correction():
    client = FakeClient(brief(headline="You slept 5h42m."), brief())
    result = generate_brief(PAYLOAD, phase="baseline", client=client)

    assert result.attempts == 2
    assert result.verified is True
    # The retry names the offending numbers rather than repeating the rule.
    correction = client.messages.calls[1]["messages"][-1]["content"]
    assert "5" in correction and "42" in correction


def test_a_brief_that_keeps_inventing_is_stored_but_flagged():
    """Never silently accepted, and never silently dropped either."""
    client = FakeClient(brief(headline="You slept 5h42m."), brief(headline="Down 3.4 kg."))
    result = generate_brief(PAYLOAD, phase="baseline", client=client)

    assert result.attempts == 2
    assert result.verified is False
    assert result.untraceable_numbers == ["3.4"]


def test_the_request_carries_the_phase_lock_and_caches_the_prompt():
    client = FakeClient(brief())
    generate_brief(PAYLOAD, phase="baseline", client=client)

    call = client.messages.calls[0]
    assert "PHASE: baseline" in call["system"][0]["text"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["model"] == "claude-opus-5"


def test_a_refusal_is_an_error_not_a_brief():
    class Refusing:
        messages = SimpleNamespace(
            parse=lambda **kw: SimpleNamespace(
                parsed_output=None, stop_reason="refusal", stop_details="policy", model="m"
            )
        )

    with pytest.raises(BriefGenerationError, match="declined"):
        generate_brief(PAYLOAD, phase="baseline", client=Refusing())


# ── the phase lock ───────────────────────────────────────────────────────


def test_baseline_forbids_causal_language_explicitly():
    prompt = system_prompt("baseline")
    assert "may NOT state, imply or hint at a cause" in prompt
    assert "because" in prompt


def test_each_phase_has_its_own_clause():
    assert set(PHASE_CLAUSES) == {"baseline", "associative", "experimental"}
    assert "sample size" in PHASE_CLAUSES["associative"]
    assert "effect size" in PHASE_CLAUSES["experimental"]


def test_an_unknown_phase_fails_closed_to_baseline():
    assert system_prompt("something-new") == system_prompt("baseline")


def test_the_hard_rules_are_all_in_the_prompt():
    prompt = system_prompt("baseline")
    for fragment in [
        "NEVER state a number",
        "A null is a null",
        "At most three do_today",
        "No medical advice",
        'Prefer "I don\'t know"',
        "No motivational filler",
        "restriction",
    ]:
        assert fragment in prompt


def test_the_output_contract_caps_do_today_at_three():
    with pytest.raises(ValueError):
        brief(do_today=[{"action": f"a{i}", "rationale": "r", "priority": 1} for i in range(4)])


# ── storage and delivery ─────────────────────────────────────────────────


def test_generate_and_store_keeps_the_input_snapshot(session):
    seed_history(session)
    row = brief_service.generate_and_store(
        session,
        TODAY,
        settings=Settings(anthropic_api_key="test"),
        client=FakeClient(seeded_brief()),
    )

    assert row.phase == "baseline"
    assert row.prompt_version == PROMPT_VERSION
    assert row.input_snapshot["sleep"]["duration_min"] == 450
    assert row.output["verification"]["numbers_traceable"] is True
    assert row.generated_at is not None


def test_regenerating_a_day_replaces_rather_than_duplicates(session):
    seed_history(session)
    settings = Settings(anthropic_api_key="test")
    for _ in range(2):
        brief_service.generate_and_store(
            session, TODAY, settings=settings, client=FakeClient(seeded_brief())
        )

    from app.models import Brief

    assert session.query(Brief).count() == 1


def test_feedback_is_recorded(session):
    seed_history(session)
    row = brief_service.generate_and_store(
        session,
        TODAY,
        settings=Settings(anthropic_api_key="test"),
        client=FakeClient(seeded_brief()),
    )
    brief_service.record_feedback(session, row.id, "useful", "accurate on the sleep debt")

    assert brief_service.get(session, TODAY).feedback_rating == "useful"


def test_email_renders_the_stored_brief(session):
    seed_history(session)
    row = brief_service.generate_and_store(
        session,
        TODAY,
        settings=Settings(anthropic_api_key="test"),
        client=FakeClient(seeded_brief()),
    )
    html = render_html(row, checkin_url="https://example.test/checkin")

    assert "450 minutes" in html
    assert "green" in html
    assert "https://example.test/checkin" in html
    assert "Not a medical device" in html


def test_email_escapes_model_output(session):
    seed_history(session)
    row = brief_service.generate_and_store(
        session,
        TODAY,
        settings=Settings(anthropic_api_key="test"),
        client=FakeClient(seeded_brief(headline="<script>alert(1)</script>")),
    )
    assert "<script>" not in render_html(row)


def test_delivery_without_a_key_is_an_error_not_a_silent_skip(session):
    seed_history(session)
    row = brief_service.generate_and_store(
        session,
        TODAY,
        settings=Settings(anthropic_api_key="test"),
        client=FakeClient(seeded_brief()),
    )
    with pytest.raises(EmailDeliveryError, match="RESEND_API_KEY"):
        send_brief(row, Settings(resend_api_key=None))


# ── the endpoints ────────────────────────────────────────────────────────


def test_metrics_endpoint_exposes_the_breakdown(session, client, auth):
    seed_history(session)
    response = client.get(f"/api/v1/metrics/{TODAY.isoformat()}", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["readiness"]["score"] == 100.0
    assert len(body["readiness"]["components"]) == 7
    assert body["completeness"]["fields"]["sleep_duration_min"] is True
    assert body["sleep"]["baseline_n"] == 30


def test_brief_input_endpoint_returns_the_contract(session, client, auth):
    seed_history(session)
    response = client.get(f"/api/v1/brief/input/{TODAY.isoformat()}", headers=auth)

    assert response.status_code == 200
    assert response.json()["phase"] == "baseline"


def test_reading_a_brief_that_does_not_exist(session, client, auth):
    response = client.get(
        f"/api/v1/brief/{(TODAY - timedelta(days=400)).isoformat()}", headers=auth
    )
    assert response.status_code == 404


def test_endpoints_require_the_token(client):
    assert client.get(f"/api/v1/metrics/{date(2026, 9, 4).isoformat()}").status_code == 401
