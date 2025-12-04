from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars like POSTGRES_USER etc.
    )

    # Application
    app_name: str = "LeadMachine"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://leadmachine:password@localhost:5432/leadmachine"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""

    # SMTP
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@lm.allardvolker.nl"

    # IMAP
    imap_host: str = "localhost"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""

    # JWT Authentication
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Tracking
    tracking_base_url: str = "https://lm.allardvolker.nl"

    # Rate Limiting
    email_daily_limit: int = 50
    email_min_delay_seconds: int = 120
    email_max_delay_seconds: int = 300

    # Scoring thresholds
    score_hot_threshold: int = 75
    score_warm_threshold: int = 60
    score_cool_threshold: int = 45


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
