"""Application settings. Everything secret comes from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.metrics.readiness import ReadinessWeights


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    database_url: str = "sqlite+pysqlite:///./health.db"
    timezone: str = "Europe/London"
    environment: str = "development"
    api_token: str = "dev-token"

    # Hevy (plan 3.1)
    hevy_api_key: str | None = None
    hevy_base_url: str = "https://api.hevyapp.com"

    # Withings (plan 3.2)
    withings_client_id: str | None = None
    withings_client_secret: str | None = None
    withings_redirect_uri: str = "http://localhost:8000/api/v1/withings/callback"
    withings_base_url: str = "https://wbsapi.withings.net"
    withings_auth_url: str = "https://account.withings.com/oauth2_user/authorize2"

    # AI layer (Phase 2)
    anthropic_api_key: str | None = None

    # Ops
    healthchecks_ping_url: str | None = None

    # Metrics config (plan 6.2 / O3: default sleep target 7h30)
    sleep_target_min: int = 450

    # Until HRV is verified on a real device (plan 3.3) it is neither scored
    # nor counted against completeness — a known gap reported once is not a
    # gap the day should be marked down for.
    hrv_available: bool = False

    # Readiness weights (plan 6.3: "weights live in config, not code").
    # Unset means "use the documented default"; the dataclass is the single
    # source of truth for what that default is.
    readiness_w_sleep_duration: float | None = None
    readiness_w_sleep_efficiency: float | None = None
    readiness_w_rhr_deviation: float | None = None
    readiness_w_hrv_deviation: float | None = None
    readiness_w_sleep_debt: float | None = None
    readiness_w_acwr: float | None = None
    readiness_w_subjective: float | None = None

    @property
    def readiness_weights(self) -> "ReadinessWeights":
        """Plan 6.3 w1-w7, with any environment override applied."""
        overrides = {
            "sleep_duration": self.readiness_w_sleep_duration,
            "sleep_efficiency": self.readiness_w_sleep_efficiency,
            "rhr_deviation": self.readiness_w_rhr_deviation,
            "hrv_deviation": self.readiness_w_hrv_deviation,
            "sleep_debt": self.readiness_w_sleep_debt,
            "acwr": self.readiness_w_acwr,
            "subjective": self.readiness_w_subjective,
        }
        return ReadinessWeights(**{k: v for k, v in overrides.items() if v is not None})

    @property
    def hevy_enabled(self) -> bool:
        return bool(self.hevy_api_key)

    @property
    def withings_enabled(self) -> bool:
        return bool(self.withings_client_id and self.withings_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
