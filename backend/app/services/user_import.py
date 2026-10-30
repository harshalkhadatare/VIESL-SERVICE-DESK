"""Bulk employee import from Excel (.xlsx) or CSV.

Recognised columns (header names are matched case-insensitively, spaces/underscores ignored):
  required: employee ID  (USER_ID, EMPLOYEE_ID, EMP_ID, EMPLOYEE_CODE, ID, CODE …)
            name         (USER_NAME, NAME, EMPLOYEE_NAME, FULL_NAME …)
  optional: EMAIL, DEPARTMENT, DESIGNATION / JOB_TITLE, PHONE / MOBILE, ROLE (Employee / IT Administrator), PASSWORD

Rows whose employee ID already exists are skipped (or updated when update_existing=True).
Employees without an email get a placeholder address (<ID>@no-email.invalid) that never receives mail;
they sign in with their employee ID. Real emails can be added later with "Edit".
"""
import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessRuleError
from app.core.security import hash_password
from app.models import Department, Role, User, UserRole, utcnow

PLACEHOLDER_DOMAIN = "no-email.invalid"
MAX_ROWS = 5000

ALIASES = {
    "code": {"userid", "employeeid", "empid", "employeecode", "empcode", "employeeno", "empno", "id", "code",
             "staffid", "erpid", "erpuserid"},
    "name": {"username", "name", "employeename", "empname", "fullname", "employee", "staffname"},
    "email": {"email", "emailid", "mail", "emailaddress", "officialemail"},
    "department": {"department", "dept", "departmentname"},
    "job_title": {"designation", "jobtitle", "title", "position", "role_title"},
    "phone": {"phone", "mobile", "mobileno", "phoneno", "contact", "contactno"},
    "role": {"role", "portalrole", "access"},
    "password": {"password", "pwd", "initialpassword"},
}


def _key(h) -> str:
    return re.sub(r"[^a-z]", "", str(h or "").lower())


def clean_name(v) -> str:
    s = " ".join(str(v or "").replace("\xa0", " ").split())
    # Title-case each word, keeping parts like O'BRIEN / D'SOUZA / JEAN-LUC tidy
    return " ".join("-".join("'".join(x[:1].upper() + x[1:].lower() for x in part.split("'"))
                             for part in word.split("-")) for word in s.split(" "))


def clean_code(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def placeholder_email(code: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9._-]', '', code).lower() or 'user'}@{PLACEHOLDER_DOMAIN}"


def read_rows(filename: str, content: bytes) -> list[list]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise BusinessRuleError(f"Could not read the Excel file: {exc}")
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    raise BusinessRuleError("Upload an Excel (.xlsx) or CSV file.")


@dataclass
class ImportResult:
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped_existing: int = 0
    errors: list[dict] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)
    columns: dict = field(default_factory=dict)


def import_users(db: Session, filename: str, content: bytes, default_password: str, default_role: str,
                 update_existing: bool, dry_run: bool, actor_id: int | None) -> ImportResult:
    rows = [r for r in read_rows(filename, content) if any(c not in (None, "") for c in r)]
    if not rows:
        raise BusinessRuleError("The file is empty.")
    # Find the header row (first row that contains an ID and a name column within the first 10 rows)
    header_idx, colmap = None, {}
    for i, row in enumerate(rows[:10]):
        found = {}
        for j, h in enumerate(row):
            k = _key(h)
            for target, names in ALIASES.items():
                if k in names and target not in found:
                    found[target] = j
        if "code" in found and "name" in found:
            header_idx, colmap = i, found
            break
    if header_idx is None:
        raise BusinessRuleError("Could not find the columns. The first row must contain an employee ID column "
                                "(e.g. USER_ID) and a name column (e.g. USER_NAME).")
    data = rows[header_idx + 1:]
    if len(data) > MAX_ROWS:
        raise BusinessRuleError(f"Too many rows ({len(data)}). Import at most {MAX_ROWS} at a time.")

    res = ImportResult(total_rows=len(data), columns={k: str(rows[header_idx][v]) for k, v in colmap.items()})
    roles = {r.code: r for r in db.scalars(select(Role))}
    depts = {d.name.lower(): d for d in db.scalars(select(Department))}
    existing_codes = {c.upper(): uid for uid, c in db.execute(select(User.id, User.employee_code)).all()}
    existing_emails = {e.lower(): uid for uid, e in db.execute(select(User.id, User.email)).all()}
    seen_codes: set[str] = set()
    hash_cache: dict[str, str] = {}
    tz = get_settings().app_timezone

    def cell(row, key):
        j = colmap.get(key)
        return row[j] if j is not None and j < len(row) else None

    for n, row in enumerate(data, start=header_idx + 2):  # spreadsheet row numbers
        code = clean_code(cell(row, "code"))
        name = clean_name(cell(row, "name"))
        if not code and not name:
            continue
        if not code or not name:
            res.errors.append({"row": n, "employee_id": code, "message": "Employee ID and name are both required."})
            continue
        if len(code) > 30 or len(name) > 150:
            res.errors.append({"row": n, "employee_id": code, "message": "Employee ID or name is too long."})
            continue
        if code.upper() in seen_codes:
            res.errors.append({"row": n, "employee_id": code, "message": "Duplicate employee ID in the file."})
            continue
        seen_codes.add(code.upper())

        email_raw = str(cell(row, "email") or "").strip().lower()
        if email_raw and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email_raw):
            res.errors.append({"row": n, "employee_id": code, "message": f"Invalid email '{email_raw}'."})
            continue
        role_raw = _key(cell(row, "role"))
        role_code = ("it_admin" if role_raw in {"itadmin", "itadministrator", "admin", "administrator", "it"}
                     else "employee" if role_raw in {"employee", "user", "staff", ""} else None)
        if role_code is None:
            res.errors.append({"row": n, "employee_id": code, "message": "Role must be Employee or IT Administrator."})
            continue
        if not role_raw:
            role_code = default_role
        password = str(cell(row, "password") or "").strip() or default_password
        dept_name = " ".join(str(cell(row, "department") or "").split())
        job = " ".join(str(cell(row, "job_title") or "").split())[:120] or None
        phone = " ".join(str(cell(row, "phone") or "").split())[:30] or None

        uid = existing_codes.get(code.upper())
        if uid is not None and not update_existing:
            res.skipped_existing += 1
            if len(res.preview) < 15:
                res.preview.append({"row": n, "employee_id": code, "name": name, "action": "skip (already exists)"})
            continue
        email = email_raw or (db.get(User, uid).email if uid else placeholder_email(code))
        other = existing_emails.get(email)
        if other is not None and other != uid:
            res.errors.append({"row": n, "employee_id": code, "message": f"Email {email} belongs to another user."})
            continue

        action = "update" if uid else "create"
        if len(res.preview) < 15:
            res.preview.append({"row": n, "employee_id": code, "name": name, "action": action,
                                "email": None if email.endswith(PLACEHOLDER_DOMAIN) else email})
        if dry_run:
            res.created += action == "create"
            res.updated += action == "update"
            continue

        dept = None
        if dept_name:
            dept = depts.get(dept_name.lower())
            if dept is None:
                code_base = re.sub(r"[^A-Z0-9]", "", dept_name.upper())[:12] or "DEPT"
                dcode, k = code_base, 1
                while db.scalar(select(Department.id).where(Department.code == dcode)):
                    k += 1
                    dcode = f"{code_base[:10]}{k}"
                dept = Department(code=dcode, name=dept_name[:120])
                db.add(dept)
                db.flush()
                depts[dept_name.lower()] = dept
        if uid:
            u = db.get(User, uid)
            u.full_name = name
            if email_raw:
                u.email = email_raw
            if dept:
                u.department_id = dept.id
            if job:
                u.job_title = job
            if phone:
                u.phone = phone
            res.updated += 1
        else:
            if password not in hash_cache:
                hash_cache[password] = hash_password(password)
            u = User(employee_code=code, email=email, full_name=name, department_id=dept.id if dept else None,
                     job_title=job, phone=phone, password_plain=password, password_hash=hash_cache[password],
                     timezone=tz)
            db.add(u)
            db.flush()
            db.add(UserRole(user_id=u.id, role_id=roles[role_code].id, granted_by=actor_id, granted_at=utcnow()))
            existing_codes[code.upper()] = u.id
            existing_emails[email] = u.id
            res.created += 1
    return res


def is_placeholder(email: str | None) -> bool:
    return bool(email) and email.endswith("@" + PLACEHOLDER_DOMAIN)


def count_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0
