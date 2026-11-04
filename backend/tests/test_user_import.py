"""Bulk employee import (Excel/CSV), sign-in by employee ID, edit user."""
import io

import openpyxl
from sqlalchemy import select

from app.models import AuditLog, User
from tests.conftest import SessionLocal, auth

H = {"X-Requested-With": "fetch"}


def xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def imp(client, content, name="users.xlsx", dry=False, role="employee", update=False, pw="Start@123", who="admin"):
    return client.post("/api/v1/admin/users/import", headers=auth(who), files={"file": (name, content)},
                       data={"default_password": pw, "dry_run": str(dry).lower(), "default_role": role,
                             "update_existing": str(update).lower()})


def test_preview_then_import_erp_sheet(client):
    rows = [("USER_ID", "USER_NAME"), (90001, "ABHISHEK  BANSODE"), (90002, "ANSHUMAN BARIK\xa0"),
            (90003, "MOHAMMAD SHER KHAN")]
    r = imp(client, xlsx(rows), dry=True).json()
    assert r["created"] == 3 and r["error_count"] == 0 and r["columns"] == {"code": "USER_ID", "name": "USER_NAME"}
    with SessionLocal() as db:
        assert db.scalar(select(User.id).where(User.employee_code == "90001")) is None  # preview saves nothing
    r = imp(client, xlsx(rows)).json()
    assert r["created"] == 3
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.employee_code == "90001"))
        assert u.full_name == "Abhishek Bansode" and u.role_codes == {"employee"} and u.password_plain == "Start@123"
        assert u.email == "90001@no-email.invalid"
        assert db.scalar(select(User.full_name).where(User.employee_code == "90002")) == "Anshuman Barik"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.users_import"))
    again = imp(client, xlsx(rows)).json()
    assert again["created"] == 0 and again["skipped_existing"] == 3


def test_sign_in_with_employee_id(client):
    imp(client, xlsx([("USER_ID", "USER_NAME"), (90011, "Login Person")]), pw="Login@123")
    assert client.post("/api/v1/auth/login", json={"email": "90011", "password": "Login@123"}, headers=H).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": " 90011 ", "password": "Login@123"}, headers=H).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "90011", "password": "nope"}, headers=H).status_code == 401
    # placeholder addresses never receive email and are hidden in the admin list
    users = client.get("/api/v1/admin/users", params={"q": "90011"}, headers=auth("admin")).json()["items"]
    assert users[0]["has_email"] is False


def test_csv_optional_columns_errors_and_roles(client):
    csv = ("Employee Code,Full Name,Email,Department,Designation,Role,Password\n"
           "90021,Asha Rao,asha.rao@visioninfra.co.in,Plant Maintenance,Fitter,,\n"
           "90022,Ravi Admin,,IT,Engineer,IT Administrator,Own@Pass1\n"
           "90021,Duplicate Row,,,,,\n"
           ",No Id Person,,,,,\n"
           "90023,Bad Email,not-an-email,,,,\n"
           "90024,Bad Role,,,,Manager,\n").encode()
    r = imp(client, csv, name="people.csv").json()
    assert r["created"] == 2 and r["error_count"] == 4
    msgs = " ".join(e["message"] for e in r["errors"])
    assert "Duplicate" in msgs and "required" in msgs and "Invalid email" in msgs and "Role" in msgs
    with SessionLocal() as db:
        a = db.scalar(select(User).where(User.employee_code == "90021"))
        assert a.email == "asha.rao@visioninfra.co.in" and a.department.name == "Plant Maintenance" and a.job_title == "Fitter"
        b = db.scalar(select(User).where(User.employee_code == "90022"))
        assert b.role_codes == {"it_admin"} and b.password_plain == "Own@Pass1"


def test_update_existing(client):
    imp(client, xlsx([("USER_ID", "USER_NAME"), (90031, "OLD NAME")]))
    r = imp(client, xlsx([("USER_ID", "USER_NAME", "EMAIL"), (90031, "NEW NAME", "new.name@visioninfra.co.in")]),
            update=True).json()
    assert r["updated"] == 1
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.employee_code == "90031"))
        assert u.full_name == "New Name" and u.email == "new.name@visioninfra.co.in"


def test_import_rejects_bad_files_and_non_admins(client):
    assert imp(client, xlsx([("USER_ID", "USER_NAME"), (1, "X Y")]), who="employee").status_code == 403
    assert imp(client, b"hello", name="notes.txt").status_code == 422
    r = imp(client, xlsx([("A", "B"), (1, 2)]))
    assert r.status_code == 422 and "columns" in r.json()["error"]["message"]
    assert imp(client, xlsx([("USER_ID", "USER_NAME"), (1, "X Y")]), pw="1").status_code == 200   # any length
    assert imp(client, xlsx([("USER_ID", "USER_NAME"), (1, "X Y")]), pw="").status_code == 422


def test_edit_user_adds_real_email(client):
    imp(client, xlsx([("USER_ID", "USER_NAME"), (90041, "Edit Me")]))
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.employee_code == "90041"))
    r = client.patch(f"/api/v1/admin/users/{uid}", headers=auth("admin"),
                     json={"email": "edit.me@visioninfra.co.in", "job_title": "Operator"})
    assert r.status_code == 200 and r.json()["has_email"] and r.json()["job_title"] == "Operator"
    dup = client.patch(f"/api/v1/admin/users/{uid}", headers=auth("admin"), json={"email": "anjali.sharma@demo.example.com"})
    assert dup.status_code == 422
    assert client.patch(f"/api/v1/admin/users/{uid}", headers=auth("employee"), json={"job_title": "x"}).status_code == 403
