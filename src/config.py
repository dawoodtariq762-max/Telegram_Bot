"""Application configuration (environment / .env driven).

Per-user panel credentials are NO LONGER stored in config — each dashboard
user keeps their own encrypted panel username/password in the database.
Only the panel *base URL* and global limits live here.
"""
from __future__ import annotations

import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_web_port() -> int:
    # Railway injects the listening port as PORT; fall back to WEB_PORT/8000.
    return int(os.environ.get("PORT", os.environ.get("WEB_PORT", 8000)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Telegram ----
    bot_token: str = Field(..., description="Bot token from @BotFather")
    admin_ids: list[int] = Field(default_factory=list)

    # ---- Database ----
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # ---- Secrets ----
    encryption_key: str = Field(..., description="Fernet key for panel credentials")
    web_secret_key: str = Field(
        default="change-me-in-production", description="Signs web sessions"
    )

    # ---- Web dashboard ----
    web_host: str = "0.0.0.0"
    web_port: int = Field(default_factory=_default_web_port)

    # Initial admin account (created on first launch if it doesn't exist).
    # CHANGE THESE in production!
    admin_username: str = "admin"
    admin_password: str = "admin"

    # ---- Panel (global, read-only connection info) ----
    panel_base_url: str = "http://168.119.13.175/ints"
    panel_login_path: str = "/login"
    panel_mode: str = "mock"  # "mock" (test) | "live" (real panel)

    # ---- Daily per-client allocation limit (UK time) ----
    daily_client_limit: int = 300
    daily_limit_timezone: str = "Europe/London"

    # ---- Browser / scaling ----
    max_concurrent_browsers: int = 8
    browser_timeout_ms: int = 30_000
    request_timeout_ms: int = 60_000
    headless: bool = True

    # ---- Logging ----
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    @field_validator("panel_mode")
    @classmethod
    def _validate_panel_mode(cls, v: str) -> str:
        if v not in {"mock", "live"}:
            raise ValueError("panel_mode must be 'mock' or 'live'")
        return v
