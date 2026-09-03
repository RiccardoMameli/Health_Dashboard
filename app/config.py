"""Application settings. Everything secret comes from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def hevy_enabled(self) -> bool:
        return bool(self.hevy_api_key)

    @property
    def withings_enabled(self) -> bool:
        return bool(self.withings_client_id and self.withings_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
