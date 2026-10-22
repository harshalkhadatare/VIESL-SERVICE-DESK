"""Serverless (Vercel) support: attachments stored in the database, job runner, cron endpoint, DB URLs."""
import io

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models import ApplicationSetting, TicketAttachment, TicketAttachmentBlob
from app.services.scheduler import JOBS_KEY, maybe_run_jobs
from tests.conftest import SessionLocal, auth, make_ticket

PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 64


def test_neon_and_vercel_urls_get_a_driver(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@ep-cool-1-pooler.neon.tech/neondb?sslmode=require")
    assert Settings().database_url.startswith("postgresql+psycopg://u:p@ep-cool-1-pooler")
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://a:b@host/db")
    assert Settings().database_url == "postgresql+psycopg://a:b@host/db"


def test_attachments_can_live_in_the_database(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachment_storage", "database")
    t = make_ticket(client)
    r = client.post(f"/api/v1/tickets/{t['number']}/attachments", headers=auth("employee"),
                    files={"file": ("screen.png", io.BytesIO(PNG), "image/png")})
    assert r.status_code == 201
    aid = r.json()["id"]
    with SessionLocal() as db:
        assert db.get(TicketAttachmentBlob, aid).data == PNG
        assert db.get(TicketAttachment, aid).size_bytes == len(PNG)
    d = client.get(f"/api/v1/tickets/{t['number']}/attachments/{aid}", headers=auth("employee"))
    assert d.status_code == 200 and d.content == PNG and "attachment" in d.headers["content-disposition"]
    assert client.get(f"/api/v1/tickets/{t['number']}/attachments/{aid}", headers=auth("employee2")).status_code == 404


def test_jobs_run_at_most_once_per_interval():
    with SessionLocal() as db:
        row = db.get(ApplicationSetting, JOBS_KEY)
        if row:
            row.value = "1970-01-01T00:00:00+00:00"
            db.commit()
        assert maybe_run_jobs(db) is not None      # due -> runs
        assert maybe_run_jobs(db) is None          # ran just now -> skipped
        assert maybe_run_jobs(db, force=True) is not None


def test_cron_endpoint_requires_secret(client, monkeypatch):
    assert client.get("/api/v1/internal/jobs").status_code == 401          # no secret configured
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret-value")
    assert client.get("/api/v1/internal/jobs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/api/v1/internal/jobs", headers={"Authorization": "Bearer s3cret-value"})
    assert r.status_code == 200 and "sla" in r.json()["ran"]
