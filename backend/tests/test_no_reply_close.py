"""Tickets close automatically when the employee does not answer IT within 3 days."""
from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, Ticket, TicketComment, TicketHistory
from app.services.scheduler import run_auto_close
from tests.conftest import EMAILS, SessionLocal, auth, make_ticket, user_id

API = "/api/v1/tickets"


def _age(number, days):
    """Move everything on the ticket `days` into the past, keeping the order of events."""
    shift = timedelta(days=days)
    with SessionLocal() as db:
        t = db.scalar(select(Ticket).where(Ticket.number == number))
        for row in list(db.scalars(select(TicketComment).where(TicketComment.ticket_id == t.id))) + \
                list(db.scalars(select(TicketHistory).where(TicketHistory.ticket_id == t.id))):
            row.created_at = row.created_at - shift
        t.created_at, t.updated_at = t.created_at - shift, t.updated_at - shift
        if t.resolved_at:
            t.resolved_at = t.resolved_at - shift
        db.commit()


def _run():
    with SessionLocal() as db:
        return run_auto_close(db)


def _status(number):
    with SessionLocal() as db:
        return db.scalar(select(Ticket.status_code).where(Ticket.number == number))


def test_closes_three_days_after_it_reply_and_emails_employee(client):
    t = make_ticket(client, subject="No answer after IT reply")
    n = t["number"]
    client.post(f"{API}/{n}/comments", headers=auth("admin"), json={"body": "Please restart and tell me if it works."})
    _age(n, 2)
    _run()
    assert _status(n) != "CLOSED"                       # only 2 days: still open
    _age(n, 1.1)                                        # now 3.1 days
    assert _run()["closed"] >= 1
    assert _status(n) == "CLOSED"
    with SessionLocal() as db:
        tk = db.scalar(select(Ticket).where(Ticket.number == n))
        assert tk.closure_reason == "no_response"
        note = db.scalar(select(Notification).where(Notification.ticket_id == tk.id,
                                                    Notification.user_id == user_id(EMAILS["employee"]),
                                                    Notification.event == "ticket_closed"))
        assert note and "did not receive a response" in note.title and "raise a new ticket" in note.body
    # still visible to the employee in their history
    assert client.get(f"{API}/{n}", headers=auth("employee")).json()["status"]["code"] == "CLOSED"


def test_employee_reply_stops_the_clock_and_it_reply_restarts_it(client):
    t = make_ticket(client, subject="Employee answered")
    n = t["number"]
    client.post(f"{API}/{n}/comments", headers=auth("admin"), json={"body": "Which printer is it?"})
    client.post(f"{API}/{n}/comments", headers=auth("employee"), json={"body": "The one on floor 2."})
    _age(n, 5)
    _run()
    assert _status(n) != "CLOSED"                       # last word was the employee's: IT's turn
    client.post(f"{API}/{n}/comments", headers=auth("admin"), json={"body": "Fixed the driver, please try."})
    _run()
    assert _status(n) != "CLOSED"                       # IT just replied: a fresh 3 days


def test_internal_notes_and_untouched_tickets_never_close(client):
    a = make_ticket(client, subject="Only an internal note")
    client.post(f"{API}/{a['number']}/comments", headers=auth("admin"), json={"body": "checking logs", "is_internal": True})
    b = make_ticket(client, subject="IT never wrote")
    _age(a["number"], 10)
    _age(b["number"], 10)
    _run()
    assert _status(a["number"]) != "CLOSED" and _status(b["number"]) != "CLOSED"


def test_resolved_ticket_closes_after_three_days_without_reply(client):
    t = make_ticket(client, subject="Resolved, no confirmation")
    n = t["number"]
    v = client.post(f"{API}/{n}/status", headers=auth("admin"), json={"to_status": "IN_PROGRESS", "expected_version": t["version"]}).json()["version"]
    client.post(f"{API}/{n}/status", headers=auth("admin"),
                json={"to_status": "RESOLVED", "resolution_notes": "Replaced cable", "expected_version": v})
    _age(n, 3.1)
    _run()
    assert _status(n) == "CLOSED"
