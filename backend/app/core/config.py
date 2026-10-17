"""Application configuration loaded from environment variables.

Secrets are never hard-coded. In production the app refuses to start with a
missing or weak SECRET_KEY.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Vision Infra IT Service Desk"
    app_env: Literal["development", "testing", "production"] = "development"
    debug: bool = False

    # Security
    secret_key: str = Field(default="dev-only-insecure-key-change-me-0123456789abcdef")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:8000"
    login_rate_limit_per_minute: int = 10
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Database. Local default is SQLite; production uses SQL Server, e.g.
    # mssql+pyodbc://user:pass@host:1433/ServiceDesk?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes
    database_url: str = "sqlite:///./servicedesk_dev.db"
    db_echo: bool = False

    # Files
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10

    # Operations
    app_timezone: str = "Asia/Kolkata"
    enable_scheduler: bool = True
    scheduler_interval_seconds: int = 60
    serve_frontend: bool = True
    frontend_dir: str = "../frontend"

    # Email (disabled until configured and tested against the company relay)
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "it-servicedesk@example.invalid"
    smtp_starttls: bool = True

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.is_production:
            if len(self.secret_key) < 32 or self.secret_key.startswith("dev-only"):
                raise ValueError("SECRET_KEY must be set to a strong random value (>=32 chars) in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production (serve over HTTPS)")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is for development only; configure SQL Server in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
