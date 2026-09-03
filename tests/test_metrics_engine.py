"""The database assembler that feeds the pure metrics (plan 6, 9.1).

These tests seed a realistic month and assert that what comes out the other
end is right — including, especially, what comes out as null.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.metrics.baselines import STATUS_ESTABLISHING, STATUS_OK
from app.metrics.readiness import STATUS_INSUFFICIENT
from app.models import (
    ActivityDaily,
    BodyMeasurement,
    Checkin,
    DailyMetrics,
    Day,
    HeartMetric,
    NutritionDaily,
    SleepSession,
    Workout,
)
from app.services.ingest import ensure_day
from app.services.metrics_engine import build_brief_input, compute_day, persist

TODAY = date(2026, 9, 4)


def seed_history(session, *, days: int = 30, until: date = TODAY, **overrides) -> None:
    """A month of unremarkable, complete days ending at `until`.

    Deliberately boring: every test then perturbs exactly one thing, so a
    failure points at that thing rather than at the fixture.
    """
    skip_sleep = set(overrides.get("skip_sleep_on", ()))
    duration = overrides.get("sleep_min", 450)
    for offset in range(days):
        day = until - timedelta(days=offset)
        ensure_day(session, day)

        if day not in skip_sleep:
            # Sleep ending at 07:00 local belongs to `day`. Exactly on the
            # 7h30 target, so the baseline day carries no sleep debt.
            end_at = datetime(day.year, day.month, day.day, 6, 0, tzinfo=UTC)
            session.add(
                SleepSession(
                    date=day,
                    start_at=end_at - timedelta(minutes=duration),
                    end_at=end_at,
                    duration_min=duration,
                    efficiency_pct=90.0,
                    deep_min=70,
                    rem_min=95,
                    source="samsung_health",
                    source_record_id=f"sleep-{day}",
                )
            )
        session.add(HeartMetric(date=day, resting_hr=52.0, source="samsung_health"))
        session.add(ActivityDaily(date=day, steps=9000, source="samsung_health"))
        session.add(BodyMeasurement(date=day, weight_kg=84.5, source="withings"))
        session.add(NutritionDaily(date=day, calories_kcal=2400.0, source="myfitnesspal"))
        session.add(
            Checkin(
                date=day,
                submitted_at=datetime(day.year, day.month, day.day, 7, 0, tzinfo=UTC),
                overall_1_10=7,
                energy_1_5=3,
                stress_1_5=2,
                tags=[],
            )
        )
    session.commit()


def test_a_complete_month_produces_a_score(session):
    seed_history(session)
    out = compute_day(session, TODAY)

    assert out.sleep_baseline.status == STATUS_OK
    assert out.sleep_baseline.median == 450.0
    assert out.rhr_baseline.median == 52.0
    assert out.data_completeness_pct == pytest.approx(100.0)
    assert out.readiness.score == pytest.approx(100.0)
    assert out.readiness.confidence == "reduced"  # no HRV on this device


def test_sleeping_under_target_accrues_debt_and_costs_readiness(session):
    """20 minutes short every night for a fortnight is 280 minutes of debt."""
    seed_history(session, sleep_min=430)
    out = compute_day(session, TODAY)

    assert out.sleep_debt_14d_min == pytest.approx(280.0)
    assert out.sleep_debt_nights == 14
    assert out.readiness.score < 100
    assert out.readiness.top_contributors()[0].factor == "sleep_debt_14d"


def test_sleep_is_attributed_to_the_day_it_ends(session):
    """A session running into the morning belongs to that morning."""
    ensure_day(session, TODAY)
    ensure_day(session, TODAY - timedelta(days=1))
    end_at = datetime(2026, 9, 4, 6, 30, tzinfo=UTC)
    session.add(
        SleepSession(
            date=TODAY,
            start_at=end_at - timedelta(minutes=400),  # started the previous evening
            end_at=end_at,
            duration_min=400,
            efficiency_pct=88.0,
            source="samsung_health",
            source_record_id="overnight",
        )
    )
    session.commit()

    out = compute_day(session, TODAY)
    assert out.sleep_duration_min == 400


def test_a_sparse_day_gets_no_score(session):
    """Never explain a day the system cannot see."""
    ensure_day(session, TODAY)
    session.add(HeartMetric(date=TODAY, resting_hr=52.0, source="samsung_health"))
    session.commit()

    out = compute_day(session, TODAY)
    assert out.data_completeness_pct < 60
    assert out.readiness.score is None
    assert out.readiness.status == STATUS_INSUFFICIENT


def test_a_missing_night_is_a_gap_not_a_zero(session):
    seed_history(session, skip_sleep_on={TODAY})
    out = compute_day(session, TODAY)

    assert out.sleep_duration_min is None
    # The baseline still stands on the 29 nights that were measured.
    assert out.sleep_baseline.median == 450.0
    assert out.sleep_baseline.n == 29
    # And the day is marked down for the gap rather than scored as zero sleep.
    assert out.data_completeness_pct < 100


def test_excluded_days_never_enter_a_baseline(session):
    seed_history(session)
    for offset in range(1, 21):
        row = session.get(Day, TODAY - timedelta(days=offset))
        row.is_excluded = True
        row.exclusion_reason = "illness"
    session.commit()

    out = compute_day(session, TODAY)
    assert out.sleep_baseline.n == 10  # 30 days minus 20 excluded
    assert out.sleep_baseline.status == STATUS_ESTABLISHING


def test_protein_stays_null_without_macros(session):
    seed_history(session)
    out = compute_day(session, TODAY)
    assert out.protein_g is None
    assert out.protein_g_per_kg is None  # never a zero, never a guess


def test_rest_days_and_training_load(session):
    seed_history(session)
    for offset in range(4):  # four consecutive training days ending yesterday
        day = TODAY - timedelta(days=1) - timedelta(days=offset)
        session.add(
            Workout(
                date=day,
                start_at=datetime(day.year, day.month, day.day, 18, 0, tzinfo=UTC),
                type="strength",
                duration_min=60.0,
                perceived_exertion_1_10=8.0,
                total_volume_kg=9840.0,
                title="Push A",
                source="hevy",
                source_record_id=f"w-{day}",
            )
        )
    session.commit()

    out = compute_day(session, TODAY)
    assert out.acute_load_7d == pytest.approx(4 * 480.0)
    assert out.days_since_rest == 4
    assert out.last_workout.title == "Push A"
    # Four sessions in an otherwise empty month is not a 4.0 spike; there is
    # no chronic load to compare against yet, so the ratio is withheld.
    assert out.acwr is None


def test_acwr_appears_once_training_is_regular(session):
    seed_history(session)
    for offset in range(1, 25):  # every other day for the last three weeks
        if offset % 2:
            continue
        day = TODAY - timedelta(days=offset)
        session.add(
            Workout(
                date=day,
                start_at=datetime(day.year, day.month, day.day, 18, 0, tzinfo=UTC),
                type="strength",
                duration_min=60.0,
                perceived_exertion_1_10=8.0,
                title="Push A",
                source="hevy",
                source_record_id=f"reg-{day}",
            )
        )
    session.commit()

    out = compute_day(session, TODAY)
    assert out.acwr is not None
    assert out.chronic_load_28d > 0


def test_persist_is_idempotent(session):
    seed_history(session)
    computed = compute_day(session, TODAY)
    persist(session, computed)
    persist(session, compute_day(session, TODAY))

    rows = session.query(DailyMetrics).all()
    assert len(rows) == 1
    assert rows[0].readiness_score == pytest.approx(100.0)
    assert rows[0].readiness_components["top_contributors"] == []


def test_brief_input_matches_the_contract(session):
    seed_history(session)
    payload = build_brief_input(session, compute_day(session, TODAY))

    assert set(payload) == {
        "date",
        "phase",
        "data_completeness_pct",
        "readiness",
        "sleep",
        "cardio",
        "training",
        "nutrition",
        "body",
        "subjective_yesterday",
        "supplements",
        "active_experiments",
        "recent_protocol_changes",
        "known_insights",
    }
    assert payload["phase"] == "baseline"
    assert payload["sleep"]["duration_min"] == 450
    assert payload["cardio"]["baseline_rhr"] == 52
    assert payload["cardio"]["hrv_ms"] is None
    assert payload["nutrition"]["protein_g_per_kg"] is None
    assert payload["subjective_yesterday"]["overall"] == 7


def test_brief_input_carries_no_time_series(session):
    """The model must never receive a series it could do arithmetic on."""
    seed_history(session)
    payload = build_brief_input(session, compute_day(session, TODAY))

    def longest_list(node) -> int:
        if isinstance(node, dict):
            return max((longest_list(v) for v in node.values()), default=0)
        if isinstance(node, list):
            return max([len(node)] + [longest_list(v) for v in node])
        return 0

    # Tags and contributor lists are short by nature; a 30-day series is not.
    assert longest_list(payload) <= 5
