"""Task management v3: attachments on tasks, Excel export, fewer emails."""
import io
from datetime import timedelta

from openpyxl import load_workbook
from sqlalchemy import update

from app.core.database import SessionLocal
from app.models import utcnow
from app.models.task import Task
from app.services.tasks import run_task_reminders
from tests.conftest import auth
from tests.test_email_notifications import _hdr, _real_user, mail  # noqa: F401  (fixture)


import pytest  # noqa: E402

from tests.conftest import EMAILS, grant_role  # noqa: E402


@pytest.fixture(autouse=True)
def _task_roles():
    """The demo employees who receive tasks in these tests are Manager L2 (employees have no Task management)."""
    for k in ("employee", "employee2", "employee3"):
        grant_role(EMAILS[k], "manager_l2")

API = "/api/v1/tasks"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
XLSX = b"PK\x03\x04" + b"\x00" * 64


def _iso(days=3):
    return (utcnow() + timedelta(days=days)).isoformat()


def _up(client, hdr, n, name, data):
    return client.post(f"{API}/{n}/attachments", headers=hdr,
                       files={"file": (name, io.BytesIO(data), "application/octet-stream")})


def _setup(client, suffix):
    mgr = _real_user(f"v3.mgr.{suffix}@visioninfra.co.in", "Meera Manager", "manager_l1")
    emp = _real_user(f"v3.emp.{suffix}@visioninfra.co.in", "Eshan Worker", "manager_l2")
    t = client.post(API, json={"title": f"Quarterly stock report {suffix}", "description": "Use the new format",
                               "assignee_ids": [emp], "due_at": _iso()}, headers=_hdr(mgr)).json()
    return mgr, emp, t["number"]


def test_task_attachments_private_and_removable(client):
    mgr, emp, n = _setup(client, "att")
    r = _up(client, _hdr(emp), n, "photo.png", PNG)
    assert r.status_code == 201, r.text
    png = r.json()
    r = _up(client, _hdr(mgr), n, "stock.xlsx", XLSX)
    assert r.status_code == 201, r.text
    xl = r.json()
    assert _up(client, _hdr(emp), n, "macro.xlsm", XLSX).status_code == 422          # macro files refused
    assert _up(client, _hdr(emp), n, "fake.xlsx", PNG).status_code == 422             # content must match
    d = client.get(f"{API}/{n}", headers=_hdr(mgr)).json()
    assert [a["original_name"] for a in d["attachments"]] == ["photo.png", "stock.xlsx"]
    assert d["can"]["attach"] is True
    assert any(e["kind"] == "file" and e["new_value"] == "photo.png" for e in d["events"])
    v = client.get(f"{API}/{n}/attachments/{png['id']}", params={"mode": "view"}, headers=_hdr(mgr))
    assert v.status_code == 200 and v.content == PNG and v.headers["content-disposition"].startswith("inline")
    # outsiders — even the IT admin — can't list, open or add files
    assert client.get(f"{API}/{n}/attachments/{png['id']}", headers=auth("admin")).status_code == 404
    assert client.get(f"{API}/{n}/attachments", headers=auth("admin")).status_code == 404
    assert _up(client, auth("admin"), n, "x.png", PNG).status_code == 404
    # the employee can't remove the manager's file; the manager (assigner) can remove anything
    assert client.delete(f"{API}/{n}/attachments/{xl['id']}", headers=_hdr(emp)).status_code == 403
    assert client.delete(f"{API}/{n}/attachments/{png['id']}", headers=_hdr(mgr)).status_code == 204
    left = client.get(f"{API}/{n}/attachments", headers=_hdr(emp)).json()
    assert [a["id"] for a in left] == [xl["id"]]


def test_export_to_excel(client):
    mgr, emp, n = _setup(client, "xls")
    client.post(f"{API}/{n}/updates", json={"progress": 40, "body": "Counted the Pune yard"}, headers=_hdr(emp))
    f = _up(client, _hdr(emp), n, "count-sheet.png", PNG).json()
    r = client.get(f"{API}/export.xlsx", params={"view": "by_me", "status": "all"}, headers=_hdr(mgr))
    assert r.status_code == 200 and r.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Tasks", "Updates", "Attachments"]
    tasks = wb["Tasks"]
    head = [c.value for c in tasks[4]]
    row = next(r for r in tasks.iter_rows(min_row=5) if r[0].value == n)
    val = dict(zip(head, (c.value for c in row)))
    assert val["Description"] == "Use the new format" and "Counted the Pune yard" in val["Latest update"]
    assert val["Assigned to"].startswith("Eshan Worker") and val["Attachments"] == 1
    assert row[head.index("Open task")].hyperlink.target.endswith(f"/#/tasks/{n}")
    upd = [[c.value for c in r] for r in wb["Updates"].iter_rows(min_row=5) if r[0].value == n]
    assert any(r[6] == "Counted the Pune yard" for r in upd)
    att = [r for r in wb["Attachments"].iter_rows(min_row=5) if r[0].value == n]
    assert att[0][2].value == "count-sheet.png" and att[0][7].hyperlink.target.endswith(f"/#/tasks/{n}?file={f['id']}")
    # someone not on the task gets nothing of it
    r = client.get(f"{API}/export.xlsx", params={"view": "all", "status": "all"}, headers=auth("admin"))
    assert all(r2[0].value != n for r2 in load_workbook(io.BytesIO(r.content))["Tasks"].iter_rows(min_row=5))


def test_emails_only_for_assigned_completed_and_deadline(client, mail):  # noqa: F811
    mgr, emp, n = _setup(client, "mail")
    to_emp = lambda: [m for m in mail.sent if m["to"] == "v3.emp.mail@visioninfra.co.in" and n in m["subject"]]  # noqa: E731
    to_mgr = lambda: [m for m in mail.sent if m["to"] == "v3.mgr.mail@visioninfra.co.in" and n in m["subject"]]  # noqa: E731
    assert len(to_emp()) == 1                                                   # new task → email
    client.post(f"{API}/{n}/updates", json={"progress": 30, "body": "Started counting"}, headers=_hdr(emp))
    client.post(f"{API}/{n}/updates", json={"body": "Please hurry"}, headers=_hdr(mgr))
    _up(client, _hdr(emp), n, "a.png", PNG)
    assert len(to_emp()) == 1 and len(to_mgr()) == 0                            # messages/progress/files: no email
    # ...but they are still in the app
    notes = client.get("/api/v1/notifications", params={"area": "tasks"}, headers=_hdr(mgr)).json()
    assert any("Started counting" in (x.get("body") or "") for x in notes["items"])
    client.patch(f"{API}/{n}", json={"due_at": _iso(6)}, headers=_hdr(mgr))      # deadline moved → email
    assert len(to_emp()) == 2
    client.post(f"{API}/{n}/extension", json={"due_at": _iso(9), "reason": "Auditor visit"}, headers=_hdr(emp))
    assert len(to_mgr()) == 1                                                   # more time asked → email
    client.post(f"{API}/{n}/extension/decision", json={"approve": True}, headers=_hdr(mgr))
    assert len(to_emp()) == 3                                                   # more time approved → email
    with SessionLocal() as db:                                                  # reminders: in-app only
        db.execute(update(Task).where(Task.number == n).values(due_at=utcnow() - timedelta(hours=1)))
        db.commit()
        run_task_reminders(db)
    assert len(to_emp()) == 3 and len(to_mgr()) == 1
    client.post(f"{API}/{n}/submit", json={"body": "Report done"}, headers=_hdr(emp))
    assert len(to_mgr()) == 2                                                   # completed → email
    client.post(f"{API}/{n}/approve", json={"rating": 4}, headers=_hdr(mgr))
    assert len(to_emp()) == 4                                                   # approved / completed → email


def test_old_management_role_is_merged_into_top_management(client):
    """Anyone who had the retired 'Management' (task_manager) role becomes Top management (MD) and keeps assigning."""
    from sqlalchemy import select

    from app.models import Role, User, UserRole
    from app.seed import seed_reference
    uid = _real_user("v3.oldmgr@visioninfra.co.in", "Old Manager", "employee")
    with SessionLocal() as db:
        old = Role(code="task_manager", name="Management", description="retired")
        db.add(old)
        db.flush()
        db.add(UserRole(user_id=uid, role_id=old.id))
        db.commit()
        seed_reference(db)
        db.commit()
        assert db.scalar(select(Role).where(Role.code == "task_manager")) is None
        assert "top_management" in db.get(User, uid).role_codes
    roles = [r["code"] for r in client.get("/api/v1/admin/roles", headers=auth("admin")).json()]
    assert sorted(roles) == ["employee", "it_admin", "manager_l1", "manager_l2", "top_management"]
    me = client.get(f"{API}/me", headers=_hdr(uid)).json()
    assert me["can_assign"] is True and me["is_management"] is True
    emp = _real_user("v3.worker2@visioninfra.co.in", "Worker Two", "manager_l2")
    r = client.post(API, json={"title": "Check the merged role", "assignee_ids": [emp], "due_at": _iso()},
                    headers=_hdr(uid))
    assert r.status_code == 201, r.text


def test_top_management_sees_all_tickets_read_only(client):
    """The MD sees every ticket, the IT dashboard, SLA report and exports — but cannot change anything."""
    from tests.conftest import make_ticket
    md = _real_user("v3.md.tickets@visioninfra.co.in", "Managing Director", "top_management")
    t = make_ticket(client, subject="Laptop screen flickering for MD view test")
    n = t["number"]
    h = _hdr(md)
    assert n in [i["number"] for i in client.get("/api/v1/tickets", params={"page_size": 100}, headers=h).json()["items"]]
    assert client.get(f"/api/v1/tickets/{n}", headers=h).status_code == 200
    assert client.get(f"/api/v1/tickets/{n}/full", headers=h).status_code == 200
    for path in ("/api/v1/dashboard/admin-home", "/api/v1/dashboard/ops", "/api/v1/dashboard/sla"):
        assert client.get(path, headers=h).status_code == 200, path
    assert client.get("/api/v1/tickets/export.xlsx", headers=h).status_code == 200
    # the MD may comment — a reply (requester + IT are told) or an internal note (IT only) — and see every file
    r = client.post(f"/api/v1/tickets/{n}/comments", json={"body": "Please prioritise this", "is_internal": False},
                    headers=h)
    assert r.status_code == 201, r.text
    assert client.post(f"/api/v1/tickets/{n}/comments", json={"body": "Check vendor warranty", "is_internal": True},
                       headers=h).status_code == 201
    bodies = [c["body"] for c in client.get(f"/api/v1/tickets/{n}/comments", headers=auth("admin")).json()]
    assert "Please prioritise this" in bodies and "Check vendor warranty" in bodies
    mine = [c["body"] for c in client.get(f"/api/v1/tickets/{n}/comments", headers=auth("employee")).json()]
    assert "Please prioritise this" in mine and "Check vendor warranty" not in mine     # notes stay internal
    assert client.get(f"/api/v1/tickets/{n}", headers=h).json()["can_comment_internal"] is True
    assert client.get(f"/api/v1/tickets/{n}/attachments", headers=h).status_code == 200
    # but nothing else: no status changes, assignment or admin pages
    r = client.post(f"/api/v1/tickets/{n}/status", json={"to_status": "IN_PROGRESS", "expected_version": t["version"]},
                    headers=h)
    assert r.status_code in (403, 422)                       # refused (no IT transitions for a viewer)
    assert client.get(f"/api/v1/tickets/{n}", headers=h).json()["status"] == t["status"]
    assert client.post(f"/api/v1/tickets/{n}/assign", json={"assignee_id": md}, headers=h).status_code == 403
    assert client.get("/api/v1/admin/users", headers=h).status_code == 403
    assert client.get("/api/v1/admin/audit", headers=h).status_code in (403, 404)
