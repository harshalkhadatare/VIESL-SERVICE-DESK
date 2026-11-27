"""Task management: who can do what, the full flow, reminders and the management overview."""
from datetime import timedelta

from sqlalchemy import select, update

from app.models import Notification, User, utcnow
from app.models.task import Task
from app.services.tasks import run_task_reminders
from tests.conftest import EMAILS, SessionLocal, auth, user_id
from tests.test_email_notifications import _hdr, _real_user, mail  # noqa: F401  (fixture)

API = "/api/v1/tasks"


def _iso(days=3, hours=0):
    return (utcnow() + timedelta(days=days, hours=hours)).isoformat()


def _people():
    md = _real_user("md.top@visioninfra.co.in", "Sandeep MD", "top_management")
    mgr = _real_user("head.ops@visioninfra.co.in", "Operations Head", "top_management")
    mgr2 = _real_user("head.fin@visioninfra.co.in", "Finance Head", "top_management")
    return md, mgr, mgr2


def _new(client, who, assignee, **kw):
    body = {"title": kw.pop("title", "Prepare monthly MIS report"), "description": "Sales + collections, as PDF",
            "assignee_id": assignee, "due_at": kw.pop("due_at", _iso()), "priority": kw.pop("priority", "high"), **kw}
    r = client.post(API, json=body, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


def test_roles_and_visibility(client):
    md, mgr, mgr2 = _people()
    emp, emp2 = user_id(EMAILS["employee"]), user_id(EMAILS["employee2"])
    # employees cannot assign or see the overview
    assert client.post(API, json={"title": "x task", "assignee_id": emp2, "due_at": _iso()},
                       headers=auth("employee")).status_code == 403
    assert client.get(f"{API}/overview", headers=auth("employee")).status_code == 403
    t = _new(client, _hdr(mgr), emp, title="Visibility check task")
    assert t["number"].startswith("TSK-") and t["status"] == "not_started"
    # assignee and assigner see it; another manager and another employee do not
    assert client.get(f"{API}/{t['number']}", headers=auth("employee")).status_code == 200
    assert client.get(f"{API}/{t['number']}", headers=_hdr(mgr2)).status_code == 404
    assert client.get(f"{API}/{t['number']}", headers=auth("employee2")).status_code == 404
    # nobody else sees it — not even top management (MD) or IT administrators
    assert client.get(f"{API}/{t['number']}", headers=_hdr(md)).status_code == 404
    assert client.get(f"{API}/{t['number']}", headers=auth("admin")).status_code == 404
    # the MD can assign to anyone, including other managers
    t2 = _new(client, _hdr(md), mgr, title="Budget review for Q4")
    assert t2["assignee"]["name"] == "Operations Head"
    me = client.get(f"{API}/me", headers=auth("employee")).json()
    assert me["has_tasks"] and not me["can_assign"]


def test_full_flow_with_feedback_and_approval(client, mail):  # noqa: F811
    _, mgr, _ = _people()
    emp = _real_user("worker.one@visioninfra.co.in", "Worker One", "employee")
    t = _new(client, _hdr(mgr), emp, title="Collect vendor quotations")
    n = t["number"]
    assert any(m["to"] == "worker.one@visioninfra.co.in" and n in m["subject"] for m in mail.sent)
    # the manager can't report progress; the employee can't approve
    assert client.post(f"{API}/{n}/updates", json={"progress": 50}, headers=_hdr(mgr)).status_code == 403
    assert client.post(f"{API}/{n}/approve", json={}, headers=_hdr(emp)).status_code == 403
    r = client.post(f"{API}/{n}/updates", json={"progress": 40, "body": "2 of 5 vendors replied"}, headers=_hdr(emp))
    assert r.status_code == 200 and r.json()["status"] == "in_progress" and r.json()["progress"] == 40
    r = client.post(f"{API}/{n}/submit", json={"body": "All 5 quotations attached in mail"}, headers=_hdr(emp)).json()
    assert r["status"] == "waiting_approval" and r["progress"] == 100
    # send back with feedback → in progress again
    assert client.post(f"{API}/{n}/send-back", json={"body": ""}, headers=_hdr(mgr)).status_code == 422
    r = client.post(f"{API}/{n}/send-back", json={"body": "Add a comparison table"}, headers=_hdr(mgr)).json()
    assert r["status"] == "in_progress" and r["progress"] == 90
    client.post(f"{API}/{n}/submit", json={"body": "Comparison added"}, headers=_hdr(emp))
    r = client.post(f"{API}/{n}/approve", json={"rating": 5, "body": "Great work"}, headers=_hdr(mgr)).json()
    assert r["status"] == "completed" and r["rating"] == 5
    kinds = [e["kind"] for e in r["events"]]
    assert kinds[0] == "created" and "returned" in kinds and kinds[-1] == "approved"
    with SessionLocal() as db:
        events = set(db.scalars(select(Notification.event).join(Task, Task.id == Notification.task_id)
                                .where(Task.number == n)))
    assert {"task_assigned", "task_update", "task_submitted", "task_returned", "task_completed"} <= events


def test_extension_request_and_decision(client):
    _, mgr, _ = _people()
    emp = user_id(EMAILS["employee3"])
    t = _new(client, _hdr(mgr), emp, title="Site audit checklist")
    n, due = t["number"], t["due_at"]
    later = _iso(days=10)
    assert client.post(f"{API}/{n}/extension", json={"due_at": _iso(days=1), "reason": "need time"},
                       headers=auth("employee3")).status_code == 422          # earlier than the deadline
    r = client.post(f"{API}/{n}/extension", json={"due_at": later, "reason": "Vendor visit next week"},
                    headers=auth("employee3")).json()
    assert r["requested_due_at"] and r["can"]["request_extension"] is False
    ov = client.get(f"{API}/overview", headers=_hdr(mgr)).json()
    assert any(a["kind"] == "extension" and a["task"]["number"] == n for a in ov["attention"])
    r = client.post(f"{API}/{n}/extension/decision", json={"approve": True}, headers=_hdr(mgr)).json()
    assert r["due_at"] != due and r["requested_due_at"] is None


def test_reminders_and_overdue_once(client):
    _, mgr, _ = _people()
    emp = user_id(EMAILS["employee2"])
    t = _new(client, _hdr(mgr), emp, title="Reminder check task", due_at=_iso(days=0, hours=5))
    with SessionLocal() as db:
        assert run_task_reminders(db)["due_soon"] >= 1
        assert run_task_reminders(db)["due_soon"] == 0                 # only once
        db.execute(update(Task).where(Task.number == t["number"]).values(due_at=utcnow() - timedelta(hours=1)))
        db.commit()
        assert run_task_reminders(db)["overdue"] >= 1
        assert run_task_reminders(db)["overdue"] == 0
    ov = client.get(f"{API}/overview", headers=_hdr(mgr)).json()
    assert ov["tiles"]["overdue"] >= 1
    assert any(r["user"]["id"] == emp and r["overdue"] >= 1 for r in ov["team"])
    lst = client.get(API, params={"status": "overdue"}, headers=_hdr(mgr)).json()
    assert t["number"] in [i["number"] for i in lst["items"]]


def test_cannot_delete_user_with_tasks(client):
    _, mgr, _ = _people()
    emp = _real_user("tasked.person@visioninfra.co.in", "Tasked Person", "employee")
    _new(client, _hdr(mgr), emp, title="Keep my history")
    r = client.delete(f"/api/v1/admin/users/{emp}", headers=auth("admin"))
    assert r.status_code == 422 and "Deactivate" in r.json()["error"]["message"]
    with SessionLocal() as db:
        assert db.get(User, emp) is not None
