"""Centralized configuration. Every service imports `settings` from here.

No secrets are hardcoded — everything comes from environment variables (see
`.env.example` at the repo root). This module is the single source of truth
for how services find Postgres/Redis/Binance, so a fresh clone on another
server only needs a `.env` file, never code changes.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "change-me-to-a-long-random-string"
    timezone: str = "UTC"

    admin_username: str = "admin"
    admin_password: str = "change-me-strong-password"

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_environment: Literal["testnet", "production"] = "testnet"

    postgres_db: str = "binmarket"
    postgres_user: str = "binmarket"
    postgres_password: str = "binmarket"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    redis_url: str = "redis://redis:6379/0"

    cors_origins: str = "http://localhost:5173"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    alert_email_to: str = ""

    engine_loop_interval_seconds: int = 15

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def binance_masked_key(self) -> str:
        if not self.binance_api_key:
            return ""
        return "*" * max(len(self.binance_api_key) - 4, 0) + self.binance_api_key[-4:]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
