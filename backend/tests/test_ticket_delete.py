from sqlalchemy import select

from app.models import AuditLog, Notification, Ticket, TicketComment
from tests.conftest import EMAILS, SessionLocal, auth, make_ticket, user_id

API = "/api/v1/tickets"


def test_requester_can_delete_own_open_ticket(client):
    t = make_ticket(client, subject="Delete me please")
    n = t["number"]
    assert t["can_delete"] is True
    client.post(f"{API}/{n}/comments", json={"body": "one more detail"}, headers=auth("employee"))
    up = client.post(f"{API}/{n}/attachments", headers=auth("employee"),
                     files={"file": ("s.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")})
    assert up.status_code == 201, up.text
    r = client.delete(f"{API}/{n}", headers=auth("employee"))
    assert r.status_code == 204, r.text
    assert client.get(f"{API}/{n}", headers=auth("employee")).status_code == 404
    assert client.get(f"{API}/{n}", headers=auth("admin")).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(Ticket).where(Ticket.number == n)) is None
        a = db.scalar(select(AuditLog).where(AuditLog.action == "ticket.delete", AuditLog.entity_id == n))
        assert a is not None and a.actor_id == user_id(EMAILS["employee"])
        # assignee was told; no notification still points at the deleted ticket
        assignee = t["assignee"]["id"]
        assert db.scalar(select(Notification).where(Notification.user_id == assignee,
                                                    Notification.title.like(f"{n} was deleted%")))


def test_other_employee_cannot_delete(client):
    n = make_ticket(client, subject="Not yours")["number"]
    assert client.delete(f"{API}/{n}", headers=auth("employee2")).status_code == 404   # cannot even see it


def test_requester_cannot_delete_resolved_ticket_but_admin_can(client):
    t = make_ticket(client, subject="Resolve then delete")
    n = t["number"]
    r = client.post(f"{API}/{n}/status", headers=auth("admin"), json={
        "to_status": "IN_PROGRESS", "expected_version": t["version"]})
    assert r.status_code == 200, r.text
    r = client.post(f"{API}/{n}/status", headers=auth("admin"), json={
        "to_status": "RESOLVED", "resolution_notes": "Fixed it by reinstalling", "expected_version": r.json()["version"]})
    assert r.status_code == 200, r.text
    assert client.get(f"{API}/{n}", headers=auth("employee")).json()["can_delete"] is False
    r = client.delete(f"{API}/{n}", headers=auth("employee"))
    assert r.status_code == 403
    assert client.delete(f"{API}/{n}", headers=auth("admin")).status_code == 204


def test_delete_keeps_ticket_numbers_unique(client):
    a = make_ticket(client, subject="First")["number"]
    client.delete(f"{API}/{a}", headers=auth("employee"))
    b = make_ticket(client, subject="Second")["number"]
    assert b != a and b > a
