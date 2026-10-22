from datetime import timedelta

from sqlalchemy import select

from app.models import Category, Notification, SLATracking, Ticket, TicketHistory, utcnow
from app.services.business_time import add_business_minutes
from app.services.scheduler import run_auto_close, run_sla_checks
from app.services.sla import spec_for
from tests.conftest import SessionLocal, auth, make_ticket, user_id

API = "/api/v1/tickets"


def _age(number: str, business_minutes: int):
    """Move a ticket's SLA start back so `business_minutes` have elapsed."""
    with SessionLocal() as db:
        t = db.scalar(select(Ticket).where(Ticket.number == number))
        s = t.sla
        spec = spec_for(db, s.calendar_id)
        start = utcnow() - timedelta(days=40)
        # find a start that leaves exactly business_minutes until now (search backwards in steps)
        lo, hi = start, utcnow()
        for _ in range(60):
            mid = lo + (hi - lo) / 2
            if add_business_minutes(mid, business_minutes, spec) > utcnow():
                hi = mid
            else:
                lo = mid
        s.started_at = lo
        from app.services.sla import recompute_due
        recompute_due(db, s)
        db.commit()


def test_breach_marks_escalates_and_notifies_once(client):
    t = make_ticket(client, code="ERP_APP", impact=1, urgency=1)  # P1: 240 business minutes
    _age(t["number"], 300)
    with SessionLocal() as db:
        stats = run_sla_checks(db)
        assert stats["breached"] >= 1
        tid = db.scalar(select(Ticket.id).where(Ticket.number == t["number"]))
        s = db.get(SLATracking, tid)
        assert s.resolution_breached and s.escalation_level == 1 and s.response_breached
        lead = t["assignee"]["id"]
        n1 = db.scalars(select(Notification).where(Notification.ticket_id == tid,
                                                   Notification.event == "sla_breached",
                                                   Notification.user_id == lead)).all()
        run_sla_checks(db)  # idempotent
        n2 = db.scalars(select(Notification).where(Notification.ticket_id == tid,
                                                   Notification.event == "sla_breached",
                                                   Notification.user_id == lead)).all()
        assert len(n1) == len(n2) == 1
    d = client.get(f"{API}/{t['number']}", headers=auth("admin")).json()
    assert d["sla"]["state"] == "breached"


def test_warning_before_breach(client):
    t = make_ticket(client, code="ERP_APP", impact=1, urgency=1)
    _age(t["number"], 200)  # 83% of 240
    with SessionLocal() as db:
        run_sla_checks(db)
        tid = db.scalar(select(Ticket.id).where(Ticket.number == t["number"]))
        s = db.get(SLATracking, tid)
        assert s.warning_sent and not s.resolution_breached


def test_pause_excludes_time_and_status_change_does_not_reset(client):
    t = make_ticket(client, code="ERP_APP", impact=2, urgency=2)
    eng = "admin"
    d = client.post(f"{API}/{t['number']}/status", headers=auth(eng), json={
        "to_status": "PENDING_EMPLOYEE", "reason": "Need details", "expected_version": t["version"]}).json()
    with SessionLocal() as db:
        tid = db.scalar(select(Ticket.id).where(Ticket.number == t["number"]))
        s = db.get(SLATracking, tid)
        started, due = s.started_at, s.resolution_due_at
        # Pretend the pause began 2 business hours ago
        s.paused_at = add_business_minutes(s.paused_at - timedelta(days=3), 0, spec_for(db, s.calendar_id))
        db.commit()
    client.post(f"{API}/{t['number']}/status", headers=auth(eng), json={
        "to_status": "IN_PROGRESS", "expected_version": d["version"]})
    with SessionLocal() as db:
        s = db.get(SLATracking, tid)
        assert s.started_at == started          # never reset
        assert s.paused_minutes > 0
        assert s.resolution_due_at > due        # pushed out by the paused time


def test_auto_close_skips_protected_categories(client):
    normal = make_ticket(client, code="PRINTER")
    secure = make_ticket(client, code="SECURITY", impact=2, urgency=2)
    with SessionLocal() as db:
        for num in (normal["number"], secure["number"]):
            t = db.scalar(select(Ticket).where(Ticket.number == num))
            t.status_code = "RESOLVED"
            t.resolved_at = utcnow() - timedelta(days=10)
            t.resolution_notes = "done"
        db.commit()
        assert db.scalar(select(Category.is_protected).where(Category.code == "SECURITY"))
        run_auto_close(db)
        a = db.scalar(select(Ticket).where(Ticket.number == normal["number"]))
        b = db.scalar(select(Ticket).where(Ticket.number == secure["number"]))
        assert a.status_code == "CLOSED" and a.closure_reason == "auto"
        assert b.status_code == "RESOLVED"
        assert db.scalar(select(TicketHistory).where(TicketHistory.ticket_id == a.id,
                                                     TicketHistory.new_value == "CLOSED"))


def test_security_category_uses_specific_policy(client):
    t = make_ticket(client, code="SECURITY", impact=1, urgency=1)
    assert t["sla"]["response_target_minutes"] == 15
