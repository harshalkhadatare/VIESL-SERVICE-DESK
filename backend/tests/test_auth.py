from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog, User
from tests.conftest import EMAILS, PASSWORD, SessionLocal, auth

H = {"X-Requested-With": "fetch"}


def login(client, email, password=PASSWORD, headers=H):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=headers)


def test_login_success_sets_httponly_refresh_cookie(client):
    r = login(client, EMAILS["employee"])
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie


def test_login_requires_anti_csrf_header(client):
    assert login(client, EMAILS["employee"], headers={}).status_code == 403


def test_wrong_password_and_unknown_user_give_same_error(client):
    a = login(client, EMAILS["employee"], "Wrong-pass-1")
    b = login(client, "nobody@demo.example.com", "Wrong-pass-1")
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_lockout_after_repeated_failures(client):
    email = EMAILS["employee2"]
    for _ in range(get_settings().max_failed_logins):
        login(client, email, "Wrong-pass-1")
    r = login(client, email)  # correct password, but locked
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_locked"
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        u.locked_until = None
        u.failed_logins = 0
        db.commit()


def test_login_rate_limited(client):
    codes = [login(client, "rate@demo.example.com", "x").status_code for _ in range(12)]
    assert 429 in codes


def test_refresh_rotation_and_reuse_detection(client):
    r = login(client, EMAILS["employee"])
    old = client.cookies.get("sd_refresh")
    r2 = client.post("/api/v1/auth/refresh", headers=H)
    assert r2.status_code == 200
    assert client.cookies.get("sd_refresh") != old
    # Replaying the rotated token revokes the whole family
    client.cookies.set("sd_refresh", old, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=H).status_code == 401
    assert r.status_code == 200


def test_logout_revokes_session(client):
    login(client, EMAILS["employee"])
    assert client.post("/api/v1/auth/logout", headers=H).status_code == 204
    assert client.post("/api/v1/auth/refresh", headers=H).status_code == 401


def test_protected_endpoint_requires_token(client):
    assert client.get("/api/v1/tickets").status_code == 401
    assert client.get("/api/v1/tickets", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_and_forged_tokens_rejected(client):
    s = get_settings()
    now = datetime.now(timezone.utc)
    expired = jwt.encode({"sub": "1", "iat": int((now - timedelta(hours=2)).timestamp()),
                          "exp": int((now - timedelta(hours=1)).timestamp()), "typ": "access",
                          "iss": "vision-servicedesk"}, s.secret_key, algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"
    forged = jwt.encode({"sub": "1", "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp()),
                         "typ": "access", "iss": "vision-servicedesk"}, "attacker-key", algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_me_returns_server_side_permissions(client):
    me = client.get("/api/v1/auth/me", headers=auth("employee")).json()
    assert "ticket.work" not in me["permissions"] and "ticket.create" in me["permissions"]


def test_login_events_are_audited(client):
    login(client, EMAILS["management"], "Wrong-pass-1")
    login(client, EMAILS["management"])
    with SessionLocal() as db:
        outcomes = {a.outcome for a in db.scalars(select(AuditLog).where(
            AuditLog.action == "auth.login", AuditLog.actor_label == EMAILS["management"]))}
    assert {"success", "failure"} <= outcomes


def test_security_headers_present(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers.get("x-request-id")


def test_errors_do_not_leak_internals(client):
    r = client.get("/api/v1/tickets/IT-0000-000000", headers=auth("employee"))
    assert r.status_code == 404
    body = r.json()["error"]
    assert set(body) == {"code", "message", "details", "request_id"}
