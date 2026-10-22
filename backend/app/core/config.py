"""Application configuration loaded from environment variables.

Secrets are never hard-coded. In production the app refuses to start with a
missing or weak SECRET_KEY.
"""
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    database_url: str = Field(default="sqlite:///./servicedesk_dev.db",
                              validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL", "DATABASE_URL_UNPOOLED"))
    db_echo: bool = False

    # Files: "disk" stores attachments in UPLOAD_DIR; "database" stores them inside the database
    # (needed on Vercel, whose disk is wiped on every restart).
    attachment_storage: Literal["disk", "database"] = "disk"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10

    # Operations
    app_timezone: str = "Asia/Kolkata"
    enable_scheduler: bool = True
    scheduler_interval_seconds: int = 60
    # Serverless hosts (Vercel) have no always-on scheduler: run the SLA / auto-close / email-retry
    # jobs opportunistically after user actions, at most every N minutes.
    run_jobs_on_request: bool = False
    jobs_min_interval_minutes: int = 10
    cron_secret: str = ""            # Vercel Cron sends "Authorization: Bearer <CRON_SECRET>"
    # Creates the first IT Administrator on an empty production database (then remove the password)
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_name: str = "IT Administrator"
    serve_frontend: bool = True
    frontend_dir: str = "../frontend"

    # Email notifications (sent only when EMAIL_ENABLED=true and SMTP is configured)
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "it-servicedesk@example.invalid"
    smtp_from_name: str = "Vision Infra IT Service Desk"
    smtp_starttls: bool = True        # port 587 (Office 365, Gmail)
    smtp_ssl: bool = False            # port 465 (implicit TLS)
    smtp_timeout_seconds: int = 10
    # Public address of the portal, used for links inside emails
    app_base_url: str = "http://localhost:8000"
    company_name: str = "Vision Infra Equipment Solutions Ltd."

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        """Neon / Vercel / Heroku give postgres:// URLs; SQLAlchemy needs an explicit driver."""
        v = v.strip()
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def db_kind(self) -> str:
        return self.database_url.split(":", 1)[0].split("+", 1)[0]  # sqlite | postgresql | mssql

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
                raise ValueError("SQLite is for development only; configure SQL Server or PostgreSQL in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
