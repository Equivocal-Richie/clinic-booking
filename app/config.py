"""Application configuration, loaded from environment variables (12-factor)."""
from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Clinic Booking API"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/clinic"

    # Working hours and "today" are reasoned about in this timezone.
    # Storage is always UTC; this only governs interpretation of local wall-clock time.
    clinic_timezone: str = "Africa/Nairobi"

    slot_duration_minutes: int = 30

    # Bonus rule: reject bookings starting within this many minutes of "now".
    # 0 disables the rule.
    min_lead_minutes: int = 60

    # --- Auth (JWT) ---
    # MUST be overridden in production via the SECRET_KEY env var.
    secret_key: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    # Short-lived access token; long-lived refresh token (DB-backed, revocable).
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # --- Rate limiting ---
    # Default global limit per client, plus a tighter limit on booking writes.
    rate_limit_default: str = "120/minute"
    rate_limit_booking: str = "15/minute"
    rate_limit_enabled: bool = True
    # Optional shared store for limits across workers/instances, e.g.
    # redis://host:6379. In-memory (per-worker) when unset.
    rate_limit_storage_uri: str = "memory://"

    # --- Pagination ---
    default_page_size: int = 20
    max_page_size: int = 100

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.clinic_timezone)

    @property
    def sqlalchemy_url(self) -> str:
        """Normalise the DB URL to the psycopg (v3) driver.

        Managed providers (Render, Heroku, etc.) hand out URLs like
        'postgres://...' or 'postgresql://...', which SQLAlchemy would try to
        open with psycopg2. We force the psycopg3 driver so the same env var
        works locally and in the cloud with no edits.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
