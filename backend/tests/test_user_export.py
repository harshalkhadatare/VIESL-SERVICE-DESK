"""Export users to Excel, edit the file, upload it back: existing people are updated (matched on SYSTEM_ID)."""
import io
import json

from openpyxl import load_workbook
from sqlalchemy import select

from app.models import AuditLog, User
from tests.conftest import SessionLocal, auth
from tests.test_user_import import imp, xlsx

H = {"X-Requested-With": "fetch"}


def _export(client, who="admin"):
    return client.get("/api/v1/admin/users/export.xlsx", headers=auth(who))


def _save(wb):
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _row_of(ws, code):
    head = [c.value for c in ws[1]]
    col = {h.replace(" *", ""): i + 1 for i, h in enumerate(head) if h}
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=col["EMPLOYEE_ID"]).value == code:
            return r, col
    raise AssertionError(code)


def test_export_lists_everyone_with_system_id(client):
    assert _export(client, "employee").status_code == 403
    r = _export(client)
    assert r.status_code == 200 and "Users_" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Users"]
    head = [c.value for c in ws[1]]
    assert head[:8] == ["FULL_NAME *", "EMPLOYEE_ID *", "DEPARTMENT_CATEGORY", "DEPARTMENT", "COMPANY_EMAIL",
                        "JOB_TITLE", "PHONE", "IT_DEPARTMENT"]
    assert head[8:] == ["STATUS", "ROLES (read only)", "LAST_SIGN_IN (read only)", "SYSTEM_ID (do not change)"]
    with SessionLocal() as db:
        total = len(db.scalars(select(User)).all())
    assert sum(1 for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=12).value) == total
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.users_export"))


def test_round_trip_updates_id_email_and_status(client):
    imp(client, xlsx([("USER_ID", "USER_NAME", "EMAIL", "PHONE"), ("70001", "Kiran Joshi", "kiran@old.example.com",
                                                                     "9800000001"), ("70002", "Nisha Rane", None, None)]),
        pw="Start@123")
    wb = load_workbook(io.BytesIO(_export(client).content))
    ws = wb["Users"]
    r1, col = _row_of(ws, "70001")
    ws.cell(row=r1, column=col["EMPLOYEE_ID"], value="70101")               # corrected ERP / Employee ID
    ws.cell(row=r1, column=col["COMPANY_EMAIL"], value="kiran.joshi@visioninfra.co.in")
    ws.cell(row=r1, column=col["PHONE"]).value = None                        # cleared
    r2, _ = _row_of(ws, "70002")
    ws.cell(row=r2, column=col["FULL_NAME"], value="Nisha Rane-Patil")
    ws.cell(row=r2, column=col["STATUS"], value="Inactive")
    content = _save(wb)

    pv = imp(client, content, dry=True).json()
    assert pv["round_trip"] and pv["updated"] == 2 and pv["created"] == 0 and pv["error_count"] == 0
    assert pv["unchanged"] >= 5                                              # everybody else: no change
    changes = {x["employee_id"]: x["changes"] for x in pv["preview"]}
    assert "Employee ID: 70001 → 70101" in changes["70101"]
    assert "Email: kiran@old.example.com → kiran.joshi@visioninfra.co.in" in changes["70101"]
    assert "Phone: 9800000001 → (blank)" in changes["70101"]
    assert "Status: Active → Inactive" in changes["70002"]
    with SessionLocal() as db:
        assert db.scalar(select(User.id).where(User.employee_code == "70101")) is None   # preview saves nothing

    r = imp(client, content).json()
    assert r["updated"] == 2 and r["error_count"] == 0
    with SessionLocal() as db:
        k = db.scalar(select(User).where(User.employee_code == "70101"))
        assert k.email == "kiran.joshi@visioninfra.co.in" and k.phone is None and k.full_name == "Kiran Joshi"
        n = db.scalar(select(User).where(User.employee_code == "70002"))
        assert n.full_name == "Nisha Rane-Patil" and n.is_active is False
        log = db.scalars(select(AuditLog).where(AuditLog.action == "admin.user_update",
                                                AuditLog.entity_id == str(k.id))).all()
        assert log and json.loads(log[-1].detail)["employee_code"] == {"from": "70001", "to": "70101"}
    # signs in with the new ID; the deactivated person can't
    assert client.post("/api/v1/auth/login", json={"email": "70101", "password": "Start@123"}, headers=H).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "70002", "password": "Start@123"}, headers=H).status_code != 200
    # uploading the same file again changes nothing
    assert imp(client, content).json()["updated"] == 0


def test_round_trip_problems_and_new_rows(client):
    imp(client, xlsx([("USER_ID", "USER_NAME"), ("70011", "Ajay Kale"), ("70012", "Ravi Shah"), ("70014", "Om Pai")]))
    wb = load_workbook(io.BytesIO(_export(client).content))
    ws = wb["Users"]
    r1, col = _row_of(ws, "70011")
    r2, _ = _row_of(ws, "70012")
    ws.cell(row=r1, column=col["EMPLOYEE_ID"], value="70012")               # clashes with Ravi
    ws.cell(row=r2, column=col["SYSTEM_ID (do not change)"], value=999999)   # edited by mistake
    new = ws.max_row + 1                                                     # a brand-new person
    ws.cell(row=new, column=col["FULL_NAME"], value="New Joiner")
    ws.cell(row=new, column=col["EMPLOYEE_ID"], value="70013")
    me, _ = _row_of(ws, "D-ADM01")                                           # the signed-in admin
    ws.cell(row=me, column=col["STATUS"], value="Inactive")
    r = imp(client, _save(wb), dry=True).json()
    msgs = " | ".join(e["message"] for e in r["errors"])
    assert "already belongs to Ravi Shah" in msgs and "SYSTEM_ID '999999'" in msgs and "your own account" in msgs
    assert r["created"] == 1 and r["updated"] == 0


def test_mixed_case_names_are_kept(client):
    imp(client, xlsx([("USER_ID", "USER_NAME"), ("70021", "Sunil Kumar")]))
    wb = load_workbook(io.BytesIO(_export(client).content))
    ws = wb["Users"]
    r1, col = _row_of(ws, "70021")
    ws.cell(row=r1, column=col["FULL_NAME"], value="Sunil Kumar (IT)")
    assert imp(client, _save(wb)).json()["updated"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(User.full_name).where(User.employee_code == "70021")) == "Sunil Kumar (IT)"
