"""Standalone settings for MarketPulse - a separate application from
BinMarket (same repo, same server, independent Docker stack). Deliberately
has zero imports from BinMarket's `shared` package: this app must be
buildable, runnable, and portable (`docker pull`-able to another machine) on
its own, sharing nothing but the git repository and the host it happens to
run on.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARKETPULSE_", env_file=".env", extra="ignore")

    app_env: str = "production"
    secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me-too"

    postgres_host: str = "marketpulse-db"
    postgres_port: int = 5432
    postgres_db: str = "marketpulse"
    postgres_user: str = "marketpulse"
    postgres_password: str = "marketpulse"

    # How often the background scheduler re-fetches feeds and recomputes the
    # outlook. News doesn't move that fast and free feeds/APIs should never
    # be hammered - every 30 minutes is plenty for a 24-48h-horizon call.
    ingest_interval_minutes: int = 30

    # The symbol this instance tracks for its primary outlook. ^IXIC (NASDAQ
    # Composite) via Yahoo's free chart endpoint - see app/prices.py.
    primary_symbol: str = "^IXIC"
    primary_symbol_label: str = "NASDAQ Composite"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
