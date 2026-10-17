"""Vercel entry point (Python serverless function).

Vercel runs the FastAPI app as a serverless function. Its filesystem is read-only
except /tmp, and /tmp is wiped on cold starts, so this setup is for a DEMO:
an SQLite database is created in /tmp and filled with fictional demo data on start.
For real use, set DATABASE_URL to a hosted SQL Server and DEMO_SEED=false
(see docs/DEPLOYMENT.md, section "Vercel").
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/servicedesk.db")
os.environ.setdefault("UPLOAD_DIR", "/tmp/uploads")
os.environ.setdefault("FRONTEND_DIR", str(ROOT / "frontend"))
os.environ.setdefault("ENABLE_SCHEDULER", "false")   # no background loops on serverless
os.environ.setdefault("COOKIE_SECURE", "true")       # Vercel is always HTTPS
os.environ.setdefault("SERVE_FRONTEND", "true")

from app.core.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402


def _bootstrap() -> None:
    Base.metadata.create_all(engine)
    if os.environ.get("DEMO_SEED", "true").lower() != "true":
        return
    from app.seed import seed_demo, seed_reference
    with SessionLocal() as db:
        seed_reference(db)
        seed_demo(db)  # skips itself if demo users already exist


_bootstrap()

from app.main import app  # noqa: E402,F401  (Vercel serves this ASGI app)
