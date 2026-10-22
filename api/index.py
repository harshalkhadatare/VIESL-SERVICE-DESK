"""Vercel entry point (Python serverless function).

Two modes, chosen automatically:

1. Free persistent database (recommended) — set DATABASE_URL (Neon / Vercel Postgres gives this
   automatically when you connect the database to the project). Data is kept permanently.
   On start-up the database schema is migrated and reference data (categories, statuses, SLA…)
   is created. Demo users are NOT created unless DEMO_SEED=true. Create the first administrator
   with BOOTSTRAP_ADMIN_EMAIL + BOOTSTRAP_ADMIN_PASSWORD.

2. No DATABASE_URL — a temporary SQLite database in /tmp, filled with demo data, wiped whenever
   Vercel restarts the function. Only useful as a quick demo.

Attachments are stored inside the database (Vercel's disk is temporary) and limited to 4 MB
(Vercel's request-size limit is 4.5 MB). Email: see docs/DEPLOYMENT.md section H.
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

_persistent = any(os.environ.get(k) for k in ("DATABASE_URL", "POSTGRES_URL", "DATABASE_URL_UNPOOLED"))
if not _persistent:
    os.environ["DATABASE_URL"] = "sqlite:////tmp/servicedesk.db"
os.environ.setdefault("DEMO_SEED", "false" if _persistent else "true")
os.environ.setdefault("ATTACHMENT_STORAGE", "database")
os.environ.setdefault("MAX_UPLOAD_MB", "4")
os.environ.setdefault("UPLOAD_DIR", "/tmp/uploads")
os.environ.setdefault("FRONTEND_DIR", str(ROOT / "frontend"))
os.environ.setdefault("ENABLE_SCHEDULER", "false")    # no always-on process on serverless …
os.environ.setdefault("RUN_JOBS_ON_REQUEST", "true")  # … so jobs run after user actions instead
os.environ.setdefault("COOKIE_SECURE", "true")        # Vercel is always HTTPS
os.environ.setdefault("SERVE_FRONTEND", "true")
if os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") and not os.environ.get("APP_BASE_URL"):
    os.environ["APP_BASE_URL"] = "https://" + os.environ["VERCEL_PROJECT_PRODUCTION_URL"]

log = logging.getLogger("servicedesk.vercel")


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    from app.core.database import engine
    from app.models import Base
    from app.core.config import get_settings
    if get_settings().db_kind == "sqlite" and not _persistent:
        Base.metadata.create_all(engine)  # throwaway demo database
        return
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")


def _bootstrap_admin(db) -> None:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.security import set_user_password
    from app.models import Role, User, UserRole
    s = get_settings()
    email = s.bootstrap_admin_email.strip().lower()
    if not email or not s.bootstrap_admin_password:
        return
    if db.scalar(select(User.id).where(User.email == email)):
        return  # already created; the password variable can now be removed
    if len(s.bootstrap_admin_password) < 6:
        log.error("BOOTSTRAP_ADMIN_PASSWORD must be at least 6 characters — admin not created")
        return
    u = User(employee_code="ADMIN-1", email=email, full_name=s.bootstrap_admin_name, timezone=s.app_timezone)
    set_user_password(u, s.bootstrap_admin_password)
    db.add(u)
    db.flush()
    db.add(UserRole(user_id=u.id, role_id=db.scalar(select(Role.id).where(Role.code == "it_admin"))))
    db.commit()
    log.info("bootstrap administrator created: %s", email)


def _bootstrap() -> None:
    from app.core.database import SessionLocal
    from app.seed import seed_demo, seed_reference
    try:
        _migrate()
    except Exception:  # noqa: BLE001 - another cold start may be migrating at the same moment
        log.exception("migration step failed (will retry on next start)")
    with SessionLocal() as db:
        try:
            seed_reference(db)
            _bootstrap_admin(db)
            if os.environ.get("DEMO_SEED", "false").lower() == "true":
                seed_demo(db)  # skips itself if demo users already exist
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("seeding failed (will retry on next start)")


_bootstrap()

from app.main import app  # noqa: E402,F401  (Vercel serves this ASGI app)
