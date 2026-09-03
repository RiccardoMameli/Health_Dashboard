"""Derived metrics, AI briefs, experiments, insights, devices.

Phase 1 creates these tables but only daily_metrics is written to (partially).
The metrics engine and AI layer land in Phase 2 — the schema exists now so the
migration history does not need rewriting later.
"""

from datetime import date as Date
from datetime import datetime

from sqlalchemy import Date as SADate
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyMetrics(Base):
    """Output of the deterministic metrics engine. Never written by the LLM (plan C2)."""

    __tablename__ = "daily_metrics"

    date: Mapped[Date] = mapped_column(SADate, ForeignKey("days.date"), primary_key=True)
    computed_at: Mapped[datetime]

    readiness_score: Mapped[float | None] = mapped_column(Float)
    readiness_components: Mapped[dict | None]
    readiness_confidence: Mapped[str | None] = mapped_column(String(16))

    sleep_debt_14d_min: Mapped[float | None] = mapped_column(Float)
    sleep_midpoint_variance_min: Mapped[float | None] = mapped_column(Float)
    rhr_deviation_bpm: Mapped[float | None] = mapped_column(Float)
    hrv_deviation_pct: Mapped[float | None] = mapped_column(Float)

    acute_load_7d: Mapped[float | None] = mapped_column(Float)
    chronic_load_28d: Mapped[float | None] = mapped_column(Float)
    acwr: Mapped[float | None] = mapped_column(Float)

    weight_ewma_kg: Mapped[float | None] = mapped_column(Float)
    weight_trend_kg_per_week: Mapped[float | None] = mapped_column(Float)
    protein_g_per_kg: Mapped[float | None] = mapped_column(Float)
    data_completeness_pct: Mapped[float | None] = mapped_column(Float)


class Brief(Base):
    """Every brief keeps its input_snapshot so any past day can be re-run (plan 9.4)."""

    __tablename__ = "briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[Date] = mapped_column(SADate, index=True)
    type: Mapped[str] = mapped_column(String(24))  # daily|weekly|experiment_result
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    phase: Mapped[str | None] = mapped_column(String(16))  # baseline|associative|experimental
    input_snapshot: Mapped[dict | None]
    output: Mapped[dict | None]
    generated_at: Mapped[datetime | None]
    delivered_via: Mapped[str | None] = mapped_column(String(16))
    feedback_rating: Mapped[str | None] = mapped_column(String(16))
    feedback_note: Mapped[str | None] = mapped_column(Text)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(64))
    intervention: Mapped[str] = mapped_column(Text)
    baseline_start: Mapped[Date | None] = mapped_column(SADate)
    baseline_end: Mapped[Date | None] = mapped_column(SADate)
    intervention_start: Mapped[Date | None] = mapped_column(SADate)
    intervention_end: Mapped[Date | None] = mapped_column(SADate)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    result_summary: Mapped[str | None] = mapped_column(Text)
    effect_size: Mapped[float | None] = mapped_column(Float)
    confidence_note: Mapped[str | None] = mapped_column(Text)


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discovered_at: Mapped[datetime]
    statement: Mapped[str] = mapped_column(Text)
    supporting_metric: Mapped[str | None] = mapped_column(String(64))
    sample_size: Mapped[int | None] = mapped_column(Integer)
    strength: Mapped[str | None] = mapped_column(String(16))  # weak|suggestive|strong
    status: Mapped[str] = mapped_column(String(16), default="proposed")


class Device(Base):
    """Phase 3, for expo-notifications."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16))
    push_token: Mapped[str] = mapped_column(String(255), unique=True)
    last_seen_at: Mapped[datetime | None]


class OAuthToken(Base):
    """Withings refresh-token storage.

    Plan R10: Withings rotates the refresh token on every refresh. Persisting
    the new one on each refresh is the only thing standing between you and
    silently losing scale sync in a fortnight.
    """

    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    scope: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime]
