"""The metrics engine (plan 6).

Pure functions over plain values, unit-tested against fixtures. The LLM never
does arithmetic; every number in a brief is computed here first.
"""

from app.metrics.baselines import (
    BASELINE_WINDOW_DAYS,
    MIN_OBSERVATIONS,
    Baseline,
    deviation,
    relative_deviation,
    rolling_baseline,
    sleep_baseline,
    wear_nights_ok,
    z_score,
)
from app.metrics.derived import (
    EXPECTED_DAILY_FIELDS,
    HRV_FIELD,
    acute_load,
    acwr,
    acwr_penalty,
    chronic_load,
    daily_load,
    data_completeness_pct,
    protein_g_per_kg,
    session_load,
    sleep_debt,
    sleep_midpoint_variance,
    volume_progression_slope,
    weight_ewma_series,
    weight_trend_kg_per_week,
)
from app.metrics.readiness import (
    MIN_COMPLETENESS_PCT,
    Component,
    Readiness,
    ReadinessInput,
    ReadinessWeights,
    compute_readiness,
)

__all__ = [
    "BASELINE_WINDOW_DAYS",
    "EXPECTED_DAILY_FIELDS",
    "HRV_FIELD",
    "MIN_COMPLETENESS_PCT",
    "MIN_OBSERVATIONS",
    "Baseline",
    "Component",
    "Readiness",
    "ReadinessInput",
    "ReadinessWeights",
    "acute_load",
    "acwr",
    "acwr_penalty",
    "chronic_load",
    "compute_readiness",
    "daily_load",
    "data_completeness_pct",
    "deviation",
    "protein_g_per_kg",
    "relative_deviation",
    "rolling_baseline",
    "session_load",
    "sleep_baseline",
    "sleep_debt",
    "sleep_midpoint_variance",
    "volume_progression_slope",
    "wear_nights_ok",
    "weight_ewma_series",
    "weight_trend_kg_per_week",
    "z_score",
]
