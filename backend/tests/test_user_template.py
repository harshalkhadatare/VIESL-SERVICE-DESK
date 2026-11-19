"""The bulk-upload template is built from live departments, and its new columns import correctly."""
from io import BytesIO

from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.models import User
from tests.conftest import SessionLocal, auth


def test_template_has_dropdowns_departments_and_sheets(client):
    assert client.get("/api/v1/admin/users/template.xlsx", headers=auth("employee")).status_code == 403
    r = client.get("/api/v1/admin/users/template.xlsx", headers=auth("admin"))
    assert r.status_code == 200
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["Users", "Departments", "Example", "Instructions"]
    head = [c.value for c in wb["Users"][1]]
    assert head == ["FULL_NAME *", "EMPLOYEE_ID *", "DEPARTMENT_CATEGORY", "DEPARTMENT", "COMPANY_EMAIL", "JOB_TITLE",
                    "PHONE", "IT_DEPARTMENT"]
    deps = {(row[1], row[2]) for row in wb["Departments"].iter_rows(min_row=2, values_only=True)}
    assert ("ACCOUNTS", "BILLING") in deps and ("TRADING", "REFURBISHMENT") in deps
    lists = [dv.formula1 for dv in wb["Users"].data_validations.dataValidation if dv.type == "list"]
    assert any("Departments!" in f for f in lists) and '"IT,ERP-IT"' in lists


def test_import_reads_category_and_it_department(client):
    wb = Workbook()
    ws = wb.active
    ws.append(["FULL_NAME *", "EMPLOYEE_ID *", "DEPARTMENT_CATEGORY", "DEPARTMENT", "COMPANY_EMAIL", "JOB_TITLE",
               "PHONE", "IT_DEPARTMENT"])
    ws.append(["Template Admin", "T-901", "ACCOUNTS", "BILLING", None, "ERP lead", None, "ERP-IT"])   # → IT Administrator
    ws.append(["Template Emp", "T-902", "TRADING", "NEW PLANT", None, None, None, None])
    ws.append(["Bad Desk", "T-903", None, None, None, None, None, "HR"])
    buf = BytesIO()
    wb.save(buf)
    r = client.post("/api/v1/admin/users/import", headers=auth("admin"),
                    files={"file": ("users.xlsx", buf.getvalue(), "application/octet-stream")},
                    data={"default_password": "Start@1", "dry_run": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2 and body["error_count"] == 1 and "IT department" in body["errors"][0]["message"]
    with SessionLocal() as db:
        a = db.scalar(select(User).where(User.employee_code == "T-901"))
        e = db.scalar(select(User).where(User.employee_code == "T-902"))
        assert a.desk == "erp" and "it_admin" in a.role_codes and a.department.name == "BILLING"
        assert e.desk is None and e.department.name == "NEW PLANT" and e.department.category == "TRADING"
