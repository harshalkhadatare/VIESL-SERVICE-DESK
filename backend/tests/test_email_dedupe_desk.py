"""No duplicate emails (shared inbox, two senders at once) and 'Both' tickets follow the assignee's team."""
from sqlalchemy import select, update

from app.models import Notification, Ticket, User
from app.services.notifications import deliver_pending_emails, notify
from tests.conftest import SessionLocal, auth, category_id
from tests.test_email_notifications import _hdr, _real_user, mail  # noqa: F401  (fixture)


def test_shared_inbox_gets_one_copy(client, mail):  # noqa: F811
    a = _real_user("shared.a@visioninfra.co.in", "Shared A", "it_admin")
    b = _real_user("shared.b@visioninfra.co.in", "Shared B", "it_admin")
    with SessionLocal() as db:   # two admins on one mailbox
        db.execute(update(User).where(User.id.in_([a, b])).values(email="it.team@visioninfra.co.in", desk="it"))
        db.commit()
    emp = _real_user("raj.emp@visioninfra.co.in", "Raj Emp", "employee")
    mail.sent.clear()
    t = client.post("/api/v1/tickets", headers=_hdr(emp), json={
        "subject": "Shared inbox check", "description": "Mouse not working since morning", "desk": "it",
        "category_id": category_id("HARDWARE")}).json()
    copies = [m for m in mail.sent if m["to"] == "it.team@visioninfra.co.in" and t["number"] in m["subject"]]
    assert len(copies) == 1
    with SessionLocal() as db:
        st = set(db.scalars(select(Notification.email_status).join(Ticket, Ticket.id == Notification.ticket_id)
                            .where(Ticket.number == t["number"], Notification.user_id.in_([a, b]))))
        assert st == {"sent", "merged"}
        db.execute(update(User).where(User.id.in_([a, b])).values(is_active=False))   # keep other tests unaffected
        db.commit()


def test_claimed_email_is_never_sent_twice(client, mail):  # noqa: F811
    emp = _real_user("claim.emp@visioninfra.co.in", "Claim Emp", "employee")
    with SessionLocal() as db:
        n = notify(db, emp, "status_changed", "Claim test", "body", None, dedupe_key="claim-test-1")
        db.commit()
        nid = n.id
    mail.sent.clear()
    with SessionLocal() as db1, SessionLocal() as db2:   # two requests finishing at the same moment
        deliver_pending_emails(db1, first_attempt_only=True)
        deliver_pending_emails(db2, first_attempt_only=True)
    assert [m["subject"] for m in mail.sent].count(next(m["subject"] for m in mail.sent)) == 1
    with SessionLocal() as db:
        assert db.get(Notification, nid).email_status == "sent"


def test_both_ticket_moves_to_assignee_team(client):
    t = client.post("/api/v1/tickets", headers=auth("employee"), json={
        "subject": "Both desks issue", "description": "ERP and laptop both failing", "desk": "both",
        "category_id": category_id("QUERY")}).json()
    assert t["desk"] == "both"
    with SessionLocal() as db:
        erp_admin = db.scalar(select(User).where(User.full_name == "Amit Deshmukh"))
        old = erp_admin.desk
        erp_admin.desk = "erp"
        db.commit()
        aid = erp_admin.id
    r = client.post(f"/api/v1/tickets/{t['number']}/assign", headers=auth("admin"),
                    json={"assignee_id": aid, "expected_version": t["version"]})
    assert r.status_code == 200, r.text
    d = client.get(f"/api/v1/tickets/{t['number']}/full", headers=auth("admin")).json()
    assert d["ticket"]["desk"] == "erp"
    assert any(h["field"] == "desk" and h["new_value"] == "ERP-IT" for h in d["history"])
    with SessionLocal() as db:
        db.get(User, aid).desk = old
        db.commit()
