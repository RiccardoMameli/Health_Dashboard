"""Assemble the metrics engine's inputs from the database (plan 6, 9.1).

This is the only place that knows both SQL and the metrics. `app.metrics`
stays pure and testable; this module does the fetching, the windowing and the
persistence, then hands plain values across.

**Which day is which.** A brief written at 06:30 on day D describes the
morning of D, and it draws on two different days:

- *Overnight* metrics belong to D — last night's sleep (a session belongs to
  the day it ends on) and this morning's resting HR.
- *Daytime* metrics belong to D-1 — yesterday's training, food, steps and
  check-in, because at 06:30 today's have not happened yet.

Mixing those up would compare last night against a day that is six hours old,
and the resulting numbers would look plausible while being wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.metrics.baselines import (
    BASELINE_WINDOW_DAYS,
    STATUS_POTENTIALLY_BIASED,
    Baseline,
    deviation,
    relative_deviation,
    rolling_baseline,
    sleep_baseline,
    z_score,
)
from app.metrics.derived import (
    EXPECTED_DAILY_FIELDS,
    HRV_FIELD,
    acute_load,
    acwr,
    chronic_load,
    daily_load,
    data_completeness_pct,
    protein_g_per_kg,
    session_load,
    sleep_debt,
    sleep_midpoint_variance,
    weight_ewma_series,
    weight_trend_kg_per_week,
)
from app.metrics.readiness import Readiness, ReadinessInput, compute_readiness
from app.models import (
    ActivityDaily,
    BodyMeasurement,
    Checkin,
    DailyMetrics,
    Day,
    HeartMetric,
    NutritionDaily,
    ProtocolChange,
    SleepSession,
    Workout,
)
from app.services.supplements import adherence_7d, missed_on
from app.services.timeutil import sleep_midpoint_minutes, utcnow

#: Minimum spread per metric, in that metric's own units. Without these a
#: quiet fortnight produces a near-zero SD and every trivial difference reads
#: as a three-sigma event. Each is a plausible *minimum* night-to-night
#: variation, not a typical one: real sleep varies by the best part of an
#: hour, so a floor much below that turns an ordinary short night into a
#: three-sigma outlier and saturates the readiness score.
SD_FLOORS = {
    "sleep_duration_min": 30.0,
    "sleep_efficiency_pct": 3.0,
    "resting_hr": 2.0,
    "hrv_ms": 5.0,
    "subjective_overall": 0.8,
}

DEBT_WINDOW_DAYS = 14
MIDPOINT_WINDOW_DAYS = 14
LOAD_WINDOW_DAYS = 28
WEIGHT_WINDOW_DAYS = 120

#: A weigh-in this recent still counts as today's weight for completeness.
WEIGHT_FRESHNESS_DAYS = 1


def _dates(start: Date, end: Date) -> list[Date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _excluded_dates(session: Session, start: Date, end: Date) -> set[Date]:
    """Days marked excluded never enter a baseline (plan 6.1)."""
    return set(
        session.execute(
            select(Day.date).where(Day.date >= start, Day.date <= end, Day.is_excluded.is_(True))
        ).scalars()
    )


def _nights(session: Session, start: Date, end: Date) -> dict[Date, SleepSession]:
    """The main sleep session per date — the longest one.

    Summing every session would let an afternoon nap inflate last night.
    """
    rows = session.execute(
        select(SleepSession).where(SleepSession.date >= start, SleepSession.date <= end)
    ).scalars()
    best: dict[Date, SleepSession] = {}
    for row in rows:
        current = best.get(row.date)
        if current is None or (row.duration_min or 0) > (current.duration_min or 0):
            best[row.date] = row
    return best


def _by_date(session: Session, model, start: Date, end: Date) -> dict:
    return {
        row.date: row
        for row in session.execute(
            select(model).where(model.date >= start, model.date <= end)
        ).scalars()
    }


def _daily_loads(session: Session, start: Date, end: Date) -> list[float]:
    """Training load per calendar day. A rest day is a real zero."""
    workouts = list(
        session.execute(select(Workout).where(Workout.date >= start, Workout.date <= end)).scalars()
    )
    per_day: dict[Date, list[float | None]] = {}
    for w in workouts:
        per_day.setdefault(w.date, []).append(
            session_load(
                duration_min=w.duration_min,
                rpe=w.perceived_exertion_1_10,
                volume_kg=w.total_volume_kg,
            )
        )
    return [daily_load(per_day.get(d, [])) for d in _dates(start, end)]


def _days_since_rest(session: Session, day: Date, *, lookback: int = 30) -> int | None:
    """Consecutive training days ending at `day`. None with no history."""
    start = day - timedelta(days=lookback)
    trained = set(
        session.execute(
            select(Workout.date).where(Workout.date >= start, Workout.date <= day)
        ).scalars()
    )
    if not trained:
        return 0
    count = 0
    cursor = day
    while cursor in trained and count <= lookback:
        count += 1
        cursor -= timedelta(days=1)
    return count


@dataclass
class ComputedDay:
    """Everything the metrics engine knows about one morning.

    Every field may be None. None means "not measured" and travels all the
    way to the brief as an explicit gap.
    """

    date: Date
    overnight_date: Date
    daytime_date: Date

    sleep_duration_min: float | None = None
    sleep_efficiency_pct: float | None = None
    sleep_deep_min: float | None = None
    sleep_rem_min: float | None = None
    sleep_baseline: Baseline | None = None
    sleep_efficiency_baseline: Baseline | None = None
    sleep_debt_14d_min: float | None = None
    sleep_debt_nights: int = 0
    sleep_midpoint_variance_min: float | None = None

    resting_hr: float | None = None
    rhr_baseline: Baseline | None = None
    rhr_deviation_bpm: float | None = None
    hrv_ms: float | None = None
    hrv_baseline: Baseline | None = None
    hrv_deviation_pct: float | None = None

    acute_load_7d: float | None = None
    chronic_load_28d: float | None = None
    acwr: float | None = None
    days_since_rest: int | None = None
    last_workout: Workout | None = None

    steps: int | None = None
    calories_kcal: float | None = None
    protein_g: float | None = None
    protein_g_per_kg: float | None = None
    nutrition_completeness_pct: float | None = None

    weight_ewma_kg: float | None = None
    weight_trend_kg_per_week: float | None = None

    checkin: Checkin | None = None
    subjective_z: float | None = None

    present: dict[str, bool] = field(default_factory=dict)
    data_completeness_pct: float = 0.0
    readiness: Readiness | None = None

    @property
    def hrv_available(self) -> bool:
        return self.hrv_ms is not None

    @property
    def sleep_baseline_biased(self) -> bool:
        return bool(self.sleep_baseline and self.sleep_baseline.status == STATUS_POTENTIALLY_BIASED)


def compute_day(session: Session, day: Date, settings: Settings | None = None) -> ComputedDay:
    """Compute every metric for one morning. Pure functions do the arithmetic."""
    settings = settings or get_settings()
    overnight = day
    daytime = day - timedelta(days=1)

    window_start = day - timedelta(days=BASELINE_WINDOW_DAYS - 1)
    excluded = _excluded_dates(session, window_start, day)

    nights = _nights(session, window_start, day)
    hearts = _by_date(session, HeartMetric, window_start, day)
    checkins = _by_date(session, Checkin, window_start, day)

    def series(source: dict, attr: str, days: int) -> list[float | None]:
        """Window of one attribute, oldest first, excluded days dropped."""
        start = day - timedelta(days=days - 1)
        out: list[float | None] = []
        for d in _dates(start, day):
            if d in excluded:
                continue
            row = source.get(d)
            out.append(None if row is None else getattr(row, attr))
        return out

    out = ComputedDay(date=day, overnight_date=overnight, daytime_date=daytime)

    # ── sleep ────────────────────────────────────────────────────────────
    tonight = nights.get(overnight)
    if tonight is not None:
        out.sleep_duration_min = tonight.duration_min
        out.sleep_efficiency_pct = tonight.efficiency_pct
        out.sleep_deep_min = tonight.deep_min
        out.sleep_rem_min = tonight.rem_min

    durations = series(nights, "duration_min", BASELINE_WINDOW_DAYS)
    out.sleep_baseline = sleep_baseline(durations)
    out.sleep_efficiency_baseline = rolling_baseline(
        series(nights, "efficiency_pct", BASELINE_WINDOW_DAYS)
    )

    debt_window = series(nights, "duration_min", DEBT_WINDOW_DAYS)
    out.sleep_debt_14d_min, out.sleep_debt_nights = sleep_debt(
        debt_window, target_min=float(settings.sleep_target_min)
    )

    midpoints = [
        sleep_midpoint_minutes(n.start_at, n.end_at)
        for d, n in sorted(nights.items())
        if d not in excluded and d > day - timedelta(days=MIDPOINT_WINDOW_DAYS)
    ]
    out.sleep_midpoint_variance_min = sleep_midpoint_variance(midpoints)

    # ── cardiovascular ───────────────────────────────────────────────────
    heart_today = hearts.get(overnight)
    out.resting_hr = heart_today.resting_hr if heart_today else None
    out.hrv_ms = heart_today.hrv_rmssd_ms if heart_today else None

    out.rhr_baseline = rolling_baseline(series(hearts, "resting_hr", BASELINE_WINDOW_DAYS))
    out.hrv_baseline = rolling_baseline(series(hearts, "hrv_rmssd_ms", BASELINE_WINDOW_DAYS))
    out.rhr_deviation_bpm = deviation(out.resting_hr, out.rhr_baseline)
    out.hrv_deviation_pct = relative_deviation(out.hrv_ms, out.hrv_baseline)

    # ── training ─────────────────────────────────────────────────────────
    loads = _daily_loads(session, day - timedelta(days=LOAD_WINDOW_DAYS - 1), day)
    out.acute_load_7d = acute_load(loads)
    out.chronic_load_28d = chronic_load(loads)
    out.acwr = acwr(loads)
    out.days_since_rest = _days_since_rest(session, daytime)
    out.last_workout = session.execute(
        select(Workout).where(Workout.date <= day).order_by(Workout.start_at.desc()).limit(1)
    ).scalar_one_or_none()

    # ── nutrition and body ───────────────────────────────────────────────
    activity = session.get(ActivityDaily, daytime)
    out.steps = activity.steps if activity else None

    nutrition = session.get(NutritionDaily, daytime)
    if nutrition is not None:
        out.calories_kcal = nutrition.calories_kcal
        out.protein_g = nutrition.protein_g
        out.nutrition_completeness_pct = nutrition.completeness_pct

    weights = [
        (row.date, row.weight_kg)
        for row in session.execute(
            select(BodyMeasurement)
            .where(
                BodyMeasurement.date >= day - timedelta(days=WEIGHT_WINDOW_DAYS),
                BodyMeasurement.date <= day,
                BodyMeasurement.weight_kg.is_not(None),
            )
            .order_by(BodyMeasurement.date)
        ).scalars()
    ]
    ewma = weight_ewma_series(weights)
    if ewma:
        out.weight_ewma_kg = ewma[-1][1]
        out.weight_trend_kg_per_week = weight_trend_kg_per_week(ewma)
    out.protein_g_per_kg = protein_g_per_kg(out.protein_g, out.weight_ewma_kg)

    # ── subjective ───────────────────────────────────────────────────────
    out.checkin = checkins.get(daytime)
    overall_baseline = rolling_baseline(series(checkins, "overall_1_10", BASELINE_WINDOW_DAYS))
    out.subjective_z = z_score(
        out.checkin.overall_1_10 if out.checkin else None,
        overall_baseline,
        sd_floor=SD_FLOORS["subjective_overall"],
    )

    # ── completeness and readiness ───────────────────────────────────────
    fresh_weight = any((day - d).days <= WEIGHT_FRESHNESS_DAYS for d, _ in weights)
    out.present = {
        "sleep_duration_min": out.sleep_duration_min is not None,
        "sleep_efficiency_pct": out.sleep_efficiency_pct is not None,
        "resting_hr": out.resting_hr is not None,
        "steps": out.steps is not None,
        "weight_kg": fresh_weight,
        "calories_kcal": out.calories_kcal is not None,
        "checkin_overall": out.checkin is not None,
        HRV_FIELD: out.hrv_ms is not None,
    }
    expected = list(EXPECTED_DAILY_FIELDS)
    if settings.hrv_available:
        expected.append(HRV_FIELD)
    out.data_completeness_pct = data_completeness_pct(out.present, expected=expected)

    out.readiness = compute_readiness(
        ReadinessInput(
            data_completeness_pct=out.data_completeness_pct,
            sleep_duration_z=z_score(
                out.sleep_duration_min,
                out.sleep_baseline,
                sd_floor=SD_FLOORS["sleep_duration_min"],
            ),
            sleep_efficiency_z=z_score(
                out.sleep_efficiency_pct,
                out.sleep_efficiency_baseline,
                sd_floor=SD_FLOORS["sleep_efficiency_pct"],
            ),
            rhr_deviation_z=z_score(
                out.resting_hr, out.rhr_baseline, sd_floor=SD_FLOORS["resting_hr"]
            ),
            hrv_deviation_z=z_score(out.hrv_ms, out.hrv_baseline, sd_floor=SD_FLOORS["hrv_ms"]),
            sleep_debt_14d_min=out.sleep_debt_14d_min,
            acwr=out.acwr,
            subjective_z=out.subjective_z,
        ),
        settings.readiness_weights,
    )
    return out


def persist(session: Session, computed: ComputedDay) -> DailyMetrics:
    """Upsert one `daily_metrics` row. Recomputing a day is always safe."""
    row = session.get(DailyMetrics, computed.date)
    if row is None:
        row = DailyMetrics(date=computed.date)
        session.add(row)

    readiness = computed.readiness
    row.computed_at = utcnow()
    row.readiness_score = readiness.score if readiness else None
    row.readiness_components = readiness.as_dict() if readiness else None
    row.readiness_confidence = readiness.confidence if readiness else None
    row.sleep_debt_14d_min = computed.sleep_debt_14d_min
    row.sleep_midpoint_variance_min = computed.sleep_midpoint_variance_min
    row.rhr_deviation_bpm = computed.rhr_deviation_bpm
    row.hrv_deviation_pct = computed.hrv_deviation_pct
    row.acute_load_7d = computed.acute_load_7d
    row.chronic_load_28d = computed.chronic_load_28d
    row.acwr = computed.acwr
    row.weight_ewma_kg = computed.weight_ewma_kg
    row.weight_trend_kg_per_week = computed.weight_trend_kg_per_week
    row.protein_g_per_kg = computed.protein_g_per_kg
    row.data_completeness_pct = computed.data_completeness_pct
    session.commit()
    return row


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def build_brief_input(session: Session, computed: ComputedDay, *, phase: str = "baseline") -> dict:
    """The §9.1 input contract: compact JSON, no raw time-series.

    Every number here was computed by the metrics engine. The model receives
    this and nothing else — it never sees a series it could try to do
    arithmetic on.
    """
    readiness = computed.readiness
    day = computed.date
    workout = computed.last_workout
    checkin = computed.checkin

    recent_changes = list(
        session.execute(
            select(ProtocolChange)
            .where(ProtocolChange.changed_at >= utcnow() - timedelta(days=28))
            .order_by(ProtocolChange.changed_at.desc())
            .limit(5)
        ).scalars()
    )

    return {
        "date": day.isoformat(),
        "phase": phase,
        "data_completeness_pct": round(computed.data_completeness_pct),
        "readiness": {
            "score": _round(readiness.score) if readiness else None,
            "status": readiness.status if readiness else None,
            "confidence": readiness.confidence if readiness else None,
            "top_contributors": [
                {"factor": c.factor, "impact": _round(c.impact)}
                for c in (readiness.top_contributors() if readiness else [])
            ],
        },
        "sleep": {
            "duration_min": _round(computed.sleep_duration_min),
            "baseline_min": _round(
                computed.sleep_baseline.median if computed.sleep_baseline else None
            ),
            "baseline_status": computed.sleep_baseline.status if computed.sleep_baseline else None,
            "efficiency_pct": _round(computed.sleep_efficiency_pct),
            "deep_min": _round(computed.sleep_deep_min),
            "rem_min": _round(computed.sleep_rem_min),
            "debt_14d_min": _round(computed.sleep_debt_14d_min),
            "debt_nights_observed": computed.sleep_debt_nights,
            "midpoint_variance_min": _round(computed.sleep_midpoint_variance_min),
            "baseline_bias_flag": computed.sleep_baseline_biased,
        },
        "cardio": {
            "resting_hr": _round(computed.resting_hr),
            "baseline_rhr": _round(computed.rhr_baseline.median if computed.rhr_baseline else None),
            "rhr_deviation_bpm": _round(computed.rhr_deviation_bpm),
            "hrv_ms": _round(computed.hrv_ms),
            "hrv_deviation_pct": _round(computed.hrv_deviation_pct, 3),
        },
        "training": {
            "yesterday": (
                {
                    "date": workout.date.isoformat(),
                    "type": workout.type,
                    "title": workout.title,
                    "volume_kg": _round(workout.total_volume_kg),
                    "duration_min": _round(workout.duration_min),
                    "rpe": _round(workout.perceived_exertion_1_10),
                }
                if workout is not None and workout.date == computed.daytime_date
                else None
            ),
            "acute_load_7d": _round(computed.acute_load_7d),
            "chronic_load_28d": _round(computed.chronic_load_28d),
            "acwr": _round(computed.acwr, 2),
            "days_since_rest": computed.days_since_rest,
        },
        "nutrition": {
            "calories": _round(computed.calories_kcal),
            "protein_g": _round(computed.protein_g),
            "protein_g_per_kg": _round(computed.protein_g_per_kg, 2),
            "completeness_pct": _round(computed.nutrition_completeness_pct),
        },
        "body": {
            "weight_ewma_kg": _round(computed.weight_ewma_kg, 2),
            "trend_kg_per_week": _round(computed.weight_trend_kg_per_week, 2),
        },
        "subjective_yesterday": (
            {
                "overall": checkin.overall_1_10,
                "energy": checkin.energy_1_5,
                "mood": checkin.mood_1_5,
                "stress": checkin.stress_1_5,
                "soreness": checkin.soreness_1_5,
                "tags": list(checkin.tags or []),
            }
            if checkin is not None
            else None
        ),
        "supplements": {
            "adherence_7d_pct": adherence_7d(session, computed.daytime_date),
            "missed_yesterday": missed_on(session, computed.daytime_date),
        },
        "active_experiments": [],
        "recent_protocol_changes": [
            {
                "date": c.changed_at.date().isoformat(),
                "entity_type": c.entity_type,
                "change_type": c.change_type,
                "new_value": c.new_value,
            }
            for c in recent_changes
        ],
        "known_insights": [],
    }
