from sqlalchemy import select

from app.models import AuditLog, Ticket, TicketComment, User
from tests.conftest import SessionLocal, auth, make_ticket

ADMIN = "/api/v1/admin/users"


def _create(client, code, email=None, role="employee"):
    r = client.post(ADMIN, headers=auth("admin"), json={
        "full_name": f"Person {code}", "email": email, "employee_code": code, "role": role, "password": "Viesl@2026x"})
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, code):
    r = client.post("/api/v1/auth/login", json={"email": code, "password": "Viesl@2026x"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Requested-With": "fetch"}


def test_add_user_without_email(client):
    u = _create(client, "77001")
    assert u["has_email"] is False and u["email"].endswith("@no-email.invalid")
    _login(client, "77001")   # signs in with the employee ID
    # blank email field is also accepted from the form
    r = client.post(ADMIN, headers=auth("admin"), json={"full_name": "Blank Email", "email": None,
                                                         "employee_code": "77002", "role": "employee",
                                                         "password": "Viesl@2026x"})
    assert r.status_code == 201


def test_delete_user_with_tickets_and_comments(client):
    u = _create(client, "77010")
    h = _login(client, "77010")
    r = client.post("/api/v1/tickets", headers=h, json={"subject": "Mouse broken", "description": "Left click dead",
                                                         "category_id": make_ticket.__globals__["category_id"]("QUERY")})
    assert r.status_code == 201, r.text
    n = r.json()["number"]
    other = make_ticket(client, subject="Someone else's ticket")
    client.post(f"/api/v1/tickets/{other['number']}/comments", headers=auth("admin"), json={"body": "admin note"})
    pv = client.get(f"{ADMIN}/{u['id']}/delete-preview", headers=auth("admin")).json()
    assert pv["tickets_raised"] == 1
    r = client.delete(f"{ADMIN}/{u['id']}", headers=auth("admin"))
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(User, u["id"]) is None
        assert db.scalar(select(Ticket).where(Ticket.number == n)) is None
        assert db.scalar(select(Ticket).where(Ticket.number == other["number"]))   # others untouched
        assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.user_delete"))
    assert client.post("/api/v1/auth/login", json={"email": "77010", "password": "Viesl@2026x"}, headers={"X-Requested-With": "fetch"}).status_code == 401


def test_delete_assignee_unassigns_and_keeps_comments_of_others(client):
    adm = _create(client, "77020", role="it_admin")
    t = make_ticket(client, subject="Assigned to temp admin")
    r = client.post(f"/api/v1/tickets/{t['number']}/assign", headers=auth("admin"),
                    json={"assignee_id": adm["id"], "expected_version": t["version"]})
    assert r.status_code == 200, r.text
    ha = _login(client, "77020")
    client.post(f"/api/v1/tickets/{t['number']}/comments", headers=ha, json={"body": "looking"})
    client.post(f"/api/v1/tickets/{t['number']}/comments", headers=auth("employee"), json={"body": "thanks"})
    assert client.delete(f"{ADMIN}/{adm['id']}", headers=auth("admin")).status_code == 200
    d = client.get(f"/api/v1/tickets/{t['number']}", headers=auth("admin")).json()
    assert d["assignee"] is None
    with SessionLocal() as db:
        bodies = [c.body for c in db.scalars(select(TicketComment).join(Ticket).where(Ticket.number == t["number"]))]
    assert "thanks" in bodies and "looking" not in bodies


def test_cannot_delete_self_and_employee_cannot_delete(client):
    me = client.get("/api/v1/auth/me", headers=auth("admin")).json()
    r = client.delete(f"{ADMIN}/{me['id']}", headers=auth("admin"))
    assert r.status_code in (400, 422) and "own account" in r.text
    victim = _create(client, "77030")
    assert client.delete(f"{ADMIN}/{victim['id']}", headers=auth("employee")).status_code == 403
