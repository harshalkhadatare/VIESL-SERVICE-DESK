"""Readable passwords (owner's choice): stored in users.password_plain, editable in the DB console."""
from sqlalchemy import select

from app.core.security import hash_password
from app.models import AuditLog, User
from tests.conftest import SessionLocal, auth, user_id

H = {"X-Requested-With": "fetch"}


def _login(client, email, pw):
    return client.post("/api/v1/auth/login", json={"email": email, "password": pw}, headers=H)


def test_created_user_password_is_readable(client):
    r = client.post("/api/v1/admin/users", headers=auth("admin"), json={
        "full_name": "Plain Text", "email": "plain.text@visioninfra.co.in", "employee_code": "PT01",
        "role": "employee", "password": "Readable@2026"})
    assert r.status_code == 201
    with SessionLocal() as db:
        assert db.scalar(select(User.password_plain).where(User.email == "plain.text@visioninfra.co.in")) == "Readable@2026"
    assert _login(client, "plain.text@visioninfra.co.in", "Readable@2026").status_code == 200


def test_editing_password_in_console_changes_login(client):
    email = "anjali.sharma@demo.example.com"
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        u.password_plain = "Edited123"      # what the owner would do in the Neon table editor
        db.commit()
    assert _login(client, email, "Edited123").status_code == 200
    assert _login(client, email, "Vision@Demo2026").status_code == 401
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        u.password_plain = "Vision@Demo2026"
        u.failed_logins, u.locked_until = 0, None
        db.commit()


def test_old_hash_only_accounts_become_readable_after_login(client):
    with SessionLocal() as db:
        u = User(employee_code="OLD1", email="old.account@visioninfra.co.in", full_name="Old Account",
                 password_hash=hash_password("OldSecret99"))
        db.add(u)
        db.commit()
    assert _login(client, "old.account@visioninfra.co.in", "OldSecret99").status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(User.password_plain).where(User.email == "old.account@visioninfra.co.in")) == "OldSecret99"


def test_admin_reset_password_unlocks_and_is_not_logged(client):
    uid = user_id("manoj.gupta@demo.example.com")
    with SessionLocal() as db:
        u = db.get(User, uid)
        u.failed_logins = 4
        db.commit()
    assert client.post(f"/api/v1/admin/users/{uid}/password", json={"password": "Temp1234"},
                       headers=auth("employee")).status_code == 403
    r = client.post(f"/api/v1/admin/users/{uid}/password", json={"password": "Temp1234"}, headers=auth("admin"))
    assert r.status_code == 200
    assert _login(client, "manoj.gupta@demo.example.com", "Temp1234").status_code == 200
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "admin.password_reset")).all()
        assert logs and all("Temp1234" not in (a.detail or "") for a in logs)
        u = db.get(User, uid)
        u.password_plain = "Vision@Demo2026"
        db.commit()


def test_change_own_password_updates_plain(client):
    _login(client, "meera.pillai@demo.example.com", "Vision@Demo2026")
    r = client.post("/api/v1/auth/change-password", headers=auth("employee3"),
                    json={"current_password": "Vision@Demo2026", "new_password": "NewMeera2026x"})
    assert r.status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(User.password_plain).where(User.email == "meera.pillai@demo.example.com")) == "NewMeera2026x"
