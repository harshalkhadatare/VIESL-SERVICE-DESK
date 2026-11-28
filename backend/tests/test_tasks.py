"""Task management: who can do what, the full flow, reminders and the management overview."""
from datetime import timedelta

from sqlalchemy import select, update

from app.models import Notification, User, utcnow
from app.models.task import Task
from app.services.tasks import run_task_reminders
from tests.conftest import EMAILS, SessionLocal, auth, user_id
from tests.test_email_notifications import _hdr, _real_user, mail  # noqa: F401  (fixture)


import pytest  # noqa: E402

from tests.conftest import grant_role  # noqa: E402


@pytest.fixture(autouse=True)
def _task_roles():
    """The demo employees who receive tasks in these tests are Manager L2 (employees have no Task management)."""
    for k in ("employee", "employee2", "employee3"):
        grant_role(EMAILS[k], "manager_l2")

API = "/api/v1/tasks"


def _iso(days=3, hours=0):
    return (utcnow() + timedelta(days=days, hours=hours)).isoformat()


def _people():
    md = _real_user("md.top@visioninfra.co.in", "Sandeep MD", "top_management")
    mgr = _real_user("head.ops@visioninfra.co.in", "Operations Head", "manager_l1")
    mgr2 = _real_user("head.fin@visioninfra.co.in", "Finance Head", "manager_l1")
    return md, mgr, mgr2


def _new(client, who, assignee, **kw):
    body = {"title": kw.pop("title", "Prepare monthly MIS report"), "description": "Sales + collections, as PDF",
            "assignee_id": assignee, "due_at": kw.pop("due_at", _iso()), "priority": kw.pop("priority", "high"), **kw}
    r = client.post(API, json=body, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


def test_roles_and_visibility(client):
    md, mgr, mgr2 = _people()                      # Managing Director, two Managers L1
    emp, emp2 = user_id(EMAILS["employee"]), user_id(EMAILS["employee2"])      # Managers L2 (see fixture)
    l2 = auth("employee")
    # Manager L2 receives tasks but cannot assign or see the overview
    assert client.post(API, json={"title": "x task", "assignee_id": emp2, "due_at": _iso()}, headers=l2).status_code == 403
    assert client.get(f"{API}/overview", headers=l2).status_code == 403
    t = _new(client, _hdr(mgr), emp, title="Visibility check task")
    assert t["number"].startswith("TSK-") and t["status"] == "not_started"
    # assignee and assigner see it; another Manager L1/L2 and IT administrators do not
    assert client.get(f"{API}/{t['number']}", headers=l2).status_code == 200
    assert client.get(f"{API}/{t['number']}", headers=auth("employee2")).status_code == 404
    assert client.get(f"{API}/{t['number']}", headers=_hdr(mgr2)).status_code == 404
    assert client.get(f"{API}/{t['number']}", headers=auth("admin")).status_code == 404
    # the Managing Director sees every task in the company
    assert client.get(f"{API}/{t['number']}", headers=_hdr(md)).status_code == 200
    # the MD can assign to Managers and IT administrators …
    t2 = _new(client, _hdr(md), mgr, title="Budget review for Q4")
    assert t2["assignee"]["name"] == "Operations Head"
    assert _new(client, _hdr(md), user_id(EMAILS["admin"]), title="Renew the firewall licence")["number"]
    # … but nobody may give a task to the MD — not a Manager L1, not an IT administrator
    for who in (_hdr(mgr), auth("admin")):
        r = client.post(API, json={"title": "Task for the MD", "assignee_ids": [md], "due_at": _iso()}, headers=who)
        assert r.status_code == 422 and "can't give a task" in r.json()["error"]["message"]
    # Manager L1 assigns to L1 and L2 only; IT administrators to L1, L2 and other admins
    assert client.post(API, json={"title": "L1 to admin task", "assignee_ids": [user_id(EMAILS["sd_admin"])],
                                  "due_at": _iso()}, headers=_hdr(mgr)).status_code == 422
    assert _new(client, _hdr(mgr), mgr2, title="L1 to L1 task")["number"]
    assert _new(client, auth("admin"), user_id(EMAILS["sd_admin"]), title="Admin to admin task")["number"]
    people = {u["id"] for u in client.get(f"{API}/people", headers=_hdr(mgr)).json()}
    assert emp in people and md not in people and user_id(EMAILS["admin"]) not in people
    me = client.get(f"{API}/me", headers=l2).json()
    assert me["has_access"] and me["has_tasks"] and not me["can_assign"]


def test_employees_have_no_task_management(client):
    """A plain Employee works only in the IT Service Desk."""
    emp = _real_user("plain.employee@visioninfra.co.in", "Plain Employee", "employee")
    me = client.get(f"{API}/me", headers=_hdr(emp)).json()
    assert me["has_access"] is False and me["can_assign"] is False
    for path in ("", "/counters", "/analytics"):
        assert client.get(f"{API}{path}", headers=_hdr(emp)).status_code == 403
    _, mgr, _ = _people()
    r = client.post(API, json={"title": "Task for an employee", "assignee_ids": [emp], "due_at": _iso()},
                    headers=_hdr(mgr))
    assert r.status_code == 422


def test_full_flow_with_feedback_and_approval(client, mail):  # noqa: F811
    _, mgr, _ = _people()
    emp = _real_user("worker.one@visioninfra.co.in", "Worker One", "manager_l2")
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
    emp = _real_user("tasked.person@visioninfra.co.in", "Tasked Person", "manager_l2")
    _new(client, _hdr(mgr), emp, title="Keep my history")
    r = client.delete(f"/api/v1/admin/users/{emp}", headers=auth("admin"))
    assert r.status_code == 422 and "Deactivate" in r.json()["error"]["message"]
    with SessionLocal() as db:
        assert db.get(User, emp) is not None
