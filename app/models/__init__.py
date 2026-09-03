"""All models, imported so Alembic autogenerate sees the full metadata."""

from app.models.analysis import (
    Brief,
    DailyMetrics,
    Device,
    Experiment,
    Insight,
    OAuthToken,
)
from app.models.base import Base
from app.models.core import Day, RawRecord, SyncRun
from app.models.health import (
    ActivityDaily,
    BodyMeasurement,
    HeartMetric,
    NutritionDaily,
    SleepSession,
)
from app.models.subjective import CONFOUNDER_TAGS, Checkin
from app.models.supplements import SCHEDULES, ProtocolChange, Supplement, SupplementLog
from app.models.training import Workout, WorkoutSet

__all__ = [
    "CONFOUNDER_TAGS",
    "SCHEDULES",
    "ActivityDaily",
    "Base",
    "BodyMeasurement",
    "Brief",
    "Checkin",
    "DailyMetrics",
    "Day",
    "Device",
    "Experiment",
    "HeartMetric",
    "Insight",
    "NutritionDaily",
    "OAuthToken",
    "ProtocolChange",
    "RawRecord",
    "SleepSession",
    "Supplement",
    "SupplementLog",
    "SyncRun",
    "Workout",
    "WorkoutSet",
]
