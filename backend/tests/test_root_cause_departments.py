"""Root cause is required to resolve and appears in the Excel report; company departments with categories."""
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select

from app.models import Department, User
from app.seed import COMPANY_DEPARTMENTS
from tests.conftest import EMAILS, SessionLocal, auth, make_ticket, user_id

API = "/api/v1/tickets"


def _start(client, t):
    return client.post(f"{API}/{t['number']}/status", headers=auth("admin"),
                       json={"to_status": "IN_PROGRESS", "expected_version": t["version"]}).json()["version"]


def test_root_cause_required_and_in_excel(client):
    t = make_ticket(client, subject="Root cause check")
    n, v = t["number"], _start(client, t)
    r = client.post(f"{API}/{n}/status", headers=auth("admin"),
                    json={"to_status": "RESOLVED", "resolution_notes": "Replaced toner", "expected_version": v})
    assert r.status_code == 422 and "Root cause" in r.json()["error"]["message"]
    r = client.post(f"{API}/{n}/status", headers=auth("admin"),
                    json={"to_status": "RESOLVED", "resolution_notes": "Replaced toner", "root_cause": "Toner empty",
                          "expected_version": v})
    assert r.status_code == 200
    ws = load_workbook(BytesIO(client.get(f"{API}/export.xlsx", params={"desk": "all"}, headers=auth("admin")).content))["Tickets"]
    head = [c.value for c in ws[4]]
    for col in ("Dept. category", "Department", "Resolution notes", "Root cause"):
        assert col in head
    row = next(r for r in ws.iter_rows(min_row=5) if r[0].value == n)
    assert row[head.index("Root cause")].value == "Toner empty"
    assert row[head.index("Resolution notes")].value == "Replaced toner"
    csv = client.get(f"{API}/export.csv", headers=auth("admin")).text
    assert "Root cause" in csv.splitlines()[0] and "Toner empty" in csv


def test_company_departments_and_category_in_users_and_excel(client):
    deps = client.get("/api/v1/departments", headers=auth("admin")).json()
    active = {(d["category"], d["name"]) for d in deps if d["is_active"]}
    assert set(COMPANY_DEPARTMENTS) <= active
    billing = next(d for d in deps if d["name"] == "BILLING")
    emp = user_id(EMAILS["employee"])
    with SessionLocal() as db:
        old_dept = db.get(User, emp).department_id
    assert client.patch(f"/api/v1/admin/users/{emp}", headers=auth("admin"),
                        json={"department_id": billing["id"]}).status_code == 200
    u = next(x for x in client.get("/api/v1/admin/users", headers=auth("admin"), params={"q": EMAILS["employee"], "page_size": 100}).json()["items"]
             if x["id"] == emp)
    assert u["department"] == "BILLING" and u["department_category"] == "ACCOUNTS"
    t = make_ticket(client, subject="Dept in excel")
    ws = load_workbook(BytesIO(client.get(f"{API}/export.xlsx", params={"desk": "all"}, headers=auth("admin")).content))["Tickets"]
    head = [c.value for c in ws[4]]
    row = next(r for r in ws.iter_rows(min_row=5) if r[0].value == t["number"])
    assert row[head.index("Dept. category")].value == "ACCOUNTS" and row[head.index("Department")].value == "BILLING"
    # employees cannot change departments
    assert client.patch(f"/api/v1/admin/users/{emp}", headers=auth("employee"), json={"department_id": billing["id"]}).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(Department.category).where(Department.name == "PILLING RIG")) == "EQUIPMENT CATEGORY"
        db.get(User, emp).department_id = old_dept      # leave the shared test employee as it was
        db.commit()


def test_notifications_filter_by_kind(client):
    t = make_ticket(client, subject="Notification kinds")
    client.post(f"{API}/{t['number']}/comments", headers=auth("admin"), json={"body": "Please share a screenshot."})
    msgs = client.get("/api/v1/notifications", headers=auth("employee"), params={"kind": "messages"}).json()["items"]
    assert msgs and all(n["event"] in ("comment_added", "info_requested") for n in msgs)
    ups = client.get("/api/v1/notifications", headers=auth("employee"), params={"kind": "updates"}).json()["items"]
    assert all(n["event"] not in ("comment_added", "info_requested") for n in ups)
    assert client.get("/api/v1/notifications", headers=auth("employee"), params={"kind": "bad"}).status_code == 422
