"""Email notifications: queued per notification, sent right after the request, retried on failure,
never sent to demo / reserved addresses, and showing the assigned person."""
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models import Notification, Role, Ticket, User, UserRole
from app.services import notifications as notif
from app.services.notifications import EmailProvider, deliver_pending_emails, set_email_provider
from tests.conftest import SessionLocal, auth, category_id


class FakeProvider(EmailProvider):
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, text, html_body=None):
        if self.fail:
            raise ConnectionRefusedError("relay down")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html_body})


@pytest.fixture
def mail(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "email_enabled", True)
    monkeypatch.setattr(s, "smtp_host", "smtp.office365.com")
    monkeypatch.setattr(s, "app_base_url", "https://servicedesk.vision.test")
    p = FakeProvider()
    set_email_provider(p)
    yield p
    set_email_provider(None)


def _real_user(email, name, role_code):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if not u:
            u = User(employee_code=email[:20], email=email, full_name=name, password_hash=hash_password("X"),
                     department_id=None, is_demo=False)
            db.add(u)
            db.flush()
            db.add(UserRole(user_id=u.id, role_id=db.scalar(select(Role.id).where(Role.code == role_code))))
            db.commit()
        return u.id


def _hdr(uid):
    return {"Authorization": "Bearer " + create_access_token(uid)[0]}


def test_emails_sent_with_assignee_name(client, mail):
    emp = _real_user("ravi.employee@visioninfra.co.in", "Ravi Employee", "employee")
    adm = _real_user("kiran.admin@visioninfra.co.in", "Kiran Admin", "it_admin")
    r = client.post("/api/v1/tickets", headers=_hdr(emp), json={
        "subject": "Email flow printer", "description": "Printer not working at all", "category_id": category_id("QUERY")})
    t = r.json()
    assert any(m["to"] == "ravi.employee@visioninfra.co.in" and t["number"] in m["subject"] for m in mail.sent)
    mail.sent.clear()
    r = client.post(f"/api/v1/tickets/{t['number']}/assign", headers=auth("admin"),
                    json={"assignee_id": adm, "expected_version": t["version"]})
    assert r.status_code == 200
    to_admin = [m for m in mail.sent if m["to"] == "kiran.admin@visioninfra.co.in"]
    to_emp = [m for m in mail.sent if m["to"] == "ravi.employee@visioninfra.co.in"]
    assert to_admin and "assigned to you" in to_admin[0]["subject"]
    assert to_emp and "Kiran Admin" in to_emp[0]["subject"]
    assert "Assigned to:  Kiran Admin" in to_emp[0]["text"] and "Kiran Admin" in to_emp[0]["html"]
    assert f"https://servicedesk.vision.test/#/tickets/{t['number']}" in to_emp[0]["text"]
    with SessionLocal() as db:
        tid = db.scalar(select(Ticket.id).where(Ticket.number == t["number"]))
        statuses = {n.email_status for n in db.scalars(select(Notification).where(Notification.ticket_id == tid))
                    if n.user_id in (emp, adm)}
    assert statuses == {"sent"}


def test_demo_addresses_never_emailed(client, mail):
    r = client.post("/api/v1/tickets", headers=auth("employee"), json={
        "subject": "Demo user email skip", "description": "Should not send email", "category_id": category_id("QUERY")})
    assert not [m for m in mail.sent if m["to"].endswith("example.com")]
    with SessionLocal() as db:
        tid = db.scalar(select(Ticket.id).where(Ticket.number == r.json()["number"]))
        assert {n.email_status for n in db.scalars(select(Notification).where(Notification.ticket_id == tid))} == {"skipped"}


def test_failed_email_is_retried_later(client, mail):
    emp = _real_user("retry.employee@visioninfra.co.in", "Retry Employee", "employee")
    set_email_provider(FakeProvider(fail=True))
    client.post("/api/v1/tickets", headers=_hdr(emp), json={
        "subject": "Retry email case", "description": "Relay is down right now", "category_id": category_id("QUERY")})
    with SessionLocal() as db:
        n = db.scalar(select(Notification).where(Notification.user_id == emp).order_by(Notification.id.desc()))
        assert n.email_status == "pending" and n.email_attempts == 1 and "relay down" in n.email_last_error
        set_email_provider(mail)
        assert deliver_pending_emails(db) >= 1
        db.refresh(n)
        assert n.email_status == "sent"


def test_no_email_when_disabled(client):
    assert not notif.email_configured()
    r = client.post("/api/v1/tickets", headers=auth("employee"), json={
        "subject": "Email disabled case", "description": "No email expected here", "category_id": category_id("QUERY")})
    with SessionLocal() as db:
        tid = db.scalar(select(Ticket.id).where(Ticket.number == r.json()["number"]))
        assert {n.email_status for n in db.scalars(select(Notification).where(Notification.ticket_id == tid))} == {"none"}


def test_admin_email_status_and_test_send(client, mail):
    s = client.get("/api/v1/admin/email", headers=auth("admin")).json()
    assert s["enabled"] and s["configured"] and s["smtp_host"] == "smtp.office365.com"
    r = client.post("/api/v1/admin/email/test", headers=auth("admin"), json={"to": "it.head@visioninfra.co.in"})
    assert r.status_code == 200 and mail.sent[-1]["to"] == "it.head@visioninfra.co.in"
    assert client.post("/api/v1/admin/email/test", headers=auth("employee"), json={}).status_code == 403


def test_test_email_reports_smtp_error(client, mail):
    set_email_provider(FakeProvider(fail=True))
    r = client.post("/api/v1/admin/email/test", headers=auth("admin"), json={"to": "it.head@visioninfra.co.in"})
    assert r.status_code == 422 and "relay down" in r.json()["error"]["message"]


def test_test_email_when_not_configured(client):
    r = client.post("/api/v1/admin/email/test", headers=auth("admin"), json={})
    assert r.status_code == 422 and "not configured" in r.json()["error"]["message"]
