"""Bulk employee import from Excel (.xlsx) or CSV.

Recognised columns (header names are matched case-insensitively, spaces/underscores ignored):
  required: employee ID  (USER_ID, EMPLOYEE_ID, EMP_ID, EMPLOYEE_CODE, ID, CODE …)
            name         (USER_NAME, NAME, EMPLOYEE_NAME, FULL_NAME …)
  optional: EMAIL, DEPARTMENT, DESIGNATION / JOB_TITLE, PHONE / MOBILE, ROLE (Employee / IT Administrator), PASSWORD

Rows whose employee ID already exists are skipped (or updated when update_existing=True).

Round trip: "Export users" writes every user with a SYSTEM_ID column. A file that has SYSTEM_ID is treated as an
edit of existing users: each row is matched on SYSTEM_ID, so even the Employee ID can be changed; a blank optional
cell clears that value (blank email = no emails); STATUS (Active / Inactive) can be changed. Rows without a
SYSTEM_ID are matched on Employee ID, or created. Roles are never changed from a file.
Employees without an email get a placeholder address (<ID>@no-email.invalid) that never receives mail;
they sign in with their employee ID. Real emails can be added later with "Edit".
"""
import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessRuleError
from app.core.security import hash_password
from app.models import Department, RefreshToken, Role, User, UserRole, utcnow

PLACEHOLDER_DOMAIN = "no-email.invalid"
MAX_ROWS = 5000
PREVIEW_ROWS = 500
LABELS = {"full_name": "Name", "employee_code": "Employee ID", "email": "Email", "department": "Department",
          "job_title": "Job title", "phone": "Phone", "desk": "IT department", "is_active": "Status"}


def describe(key: str, pair) -> str:
    def show(v):
        if key == "is_active":
            return "Active" if v else "Inactive"
        if key == "desk":
            return "ERP-IT" if v == "erp" else "IT"
        return "(blank)" if v in (None, "") else str(v)
    return f"{LABELS.get(key, key)}: {show(pair[0])} \u2192 {show(pair[1])}"

ALIASES = {
    "code": {"userid", "employeeid", "empid", "employeecode", "empcode", "employeeno", "empno", "id", "code",
             "staffid", "erpid", "erpuserid"},
    "name": {"username", "name", "employeename", "empname", "fullname", "employee", "staffname"},
    "email": {"email", "emailid", "mail", "emailaddress", "officialemail", "companyemail"},
    "department": {"department", "dept", "departmentname", "subdepartment"},
    "department_category": {"departmentcategory", "deptcategory", "category", "departmentgroup"},
    "desk": {"itdepartment", "itteam", "desk", "itdesk"},
    "job_title": {"designation", "jobtitle", "title", "position", "role_title"},
    "phone": {"phone", "mobile", "mobileno", "phoneno", "contact", "contactno"},
    "role": {"role", "portalrole", "access"},
    "password": {"password", "pwd", "initialpassword"},
    "sysid": {"systemid", "systemiddonotchange", "sysid", "internalid"},
    "status": {"status", "accountstatus", "active"},
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
    unchanged: int = 0
    round_trip: bool = False
    errors: list[dict] = field(default_factory=list)
    changes: list[tuple] = field(default_factory=list)   # (user id, {field: [old, new]}) for the audit log
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
    seen_ids: set[int] = set()
    hash_cache: dict[str, str] = {}
    tz = get_settings().app_timezone
    round_trip = res.round_trip = "sysid" in colmap
    if round_trip:
        update_existing = True   # an exported file is an edit of the people in it
    from sqlalchemy.orm import selectinload
    users = {u.id: u for u in db.scalars(select(User).options(selectinload(User.roles)))} if round_trip else {}

    def _dept(dept_name: str, cat_name: str):
        dept = depts.get(dept_name.lower())
        if dept is None:
            code_base = re.sub(r"[^A-Z0-9]", "", dept_name.upper())[:12] or "DEPT"
            dcode, k = code_base, 1
            while db.scalar(select(Department.id).where(Department.code == dcode)):
                k += 1
                dcode = f"{code_base[:10]}{k}"
            dept = Department(code=dcode, name=dept_name[:120], category=cat_name or None)
            db.add(dept)
            db.flush()
            depts[dept_name.lower()] = dept
        elif cat_name and not dept.category:
            dept.category = cat_name
        return dept

    def cell(row, key):
        j = colmap.get(key)
        return row[j] if j is not None and j < len(row) else None

    for n, row in enumerate(data, start=header_idx + 2):  # spreadsheet row numbers
        code = clean_code(cell(row, "code"))
        raw_name = " ".join(str(cell(row, "name") or "").replace("\xa0", " ").split())
        name = clean_name(raw_name)
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
        cat_name = " ".join(str(cell(row, "department_category") or "").split()).upper()[:60]
        if cat_name.startswith("="):
            cat_name = ""   # an unsaved formula cell
        desk_raw = _key(cell(row, "desk"))
        desk = "erp" if desk_raw in {"erpit", "erp"} else "it" if desk_raw == "it" else None
        if desk_raw and desk is None:
            res.errors.append({"row": n, "employee_id": code, "message": "IT department must be IT or ERP-IT."})
            continue
        if desk and not role_raw:
            role_code = "it_admin"   # IT department filled (template has no Role column) → IT Administrator
        job = " ".join(str(cell(row, "job_title") or "").split())[:120] or None
        phone = clean_code(cell(row, "phone"))[:30] or None

        if round_trip:
            sid_raw = clean_code(cell(row, "sysid"))
            uid = None
            if sid_raw:
                try:
                    uid = int(sid_raw)
                except ValueError:
                    uid = -1
                if uid not in users:
                    res.errors.append({"row": n, "employee_id": code,
                                       "message": f"SYSTEM_ID '{sid_raw}' is not a user here — don't edit that column."})
                    seen_codes.discard(code.upper())
                    continue
                if uid in seen_ids:
                    res.errors.append({"row": n, "employee_id": code, "message": "The same user appears twice in the file."})
                    seen_codes.discard(code.upper())
                    continue
                seen_ids.add(uid)
                other = existing_codes.get(code.upper())
                if other is not None and other != uid:
                    res.errors.append({"row": n, "employee_id": code,
                                       "message": f"Employee ID {code} already belongs to {users[other].full_name}."})
                    seen_codes.discard(code.upper())
                    continue
            else:
                uid = existing_codes.get(code.upper())
        else:
            uid = existing_codes.get(code.upper())
        if uid is not None and not update_existing:
            res.skipped_existing += 1
            if len(res.preview) < 15:
                res.preview.append({"row": n, "employee_id": code, "name": name, "action": "skip (already exists)"})
            continue

        status_raw = _key(cell(row, "status"))
        active = (True if status_raw in {"active", "yes", "y", "enabled", "true", "1"} else
                  False if status_raw in {"inactive", "no", "n", "disabled", "false", "0", "deactivated"} else None)
        if status_raw and active is None:
            res.errors.append({"row": n, "employee_id": code, "message": "STATUS must be Active or Inactive."})
            continue

        if uid is not None:
            u = users.get(uid) or db.get(User, uid)
            if active is False and uid == actor_id and u.is_active:
                res.errors.append({"row": n, "employee_id": code, "message": "You cannot deactivate your own account."})
                continue
            ch = {}
            # names typed all in capitals / small letters are tidied; mixed case (e.g. "IT Team") is kept as typed
            one_case = raw_name.isupper() or raw_name.islower()
            new_name = name if one_case else raw_name
            if new_name != u.full_name and not (one_case and new_name.lower() == u.full_name.lower()):
                ch["full_name"] = [u.full_name, new_name]
            if code != u.employee_code:
                ch["employee_code"] = [u.employee_code, code]
            blank_clears = round_trip
            if "email" in colmap:
                cur_ph = is_placeholder(u.email)
                if email_raw:
                    if email_raw != u.email.lower():
                        ch["email"] = [None if cur_ph else u.email, email_raw]
                elif blank_clears and not cur_ph:
                    ch["email"] = [u.email, None]
            if "department" in colmap:
                cur = u.department.name if u.department else None
                if dept_name:
                    if not cur or dept_name.lower() != cur.lower():
                        ch["department"] = [cur, depts[dept_name.lower()].name if dept_name.lower() in depts
                                            else dept_name + " (new)"]
                elif blank_clears and cur:
                    ch["department"] = [cur, None]
            for key, val in (("job_title", job), ("phone", phone)):
                if key in colmap:
                    cur = getattr(u, key)
                    if val and val != cur:
                        ch[key] = [cur, val]
                    elif not val and blank_clears and cur:
                        ch[key] = [cur, None]
            if desk and "it_admin" in u.role_codes and desk != (u.desk or "it"):
                ch["desk"] = [u.desk or "it", desk]
            if active is not None and active != u.is_active:
                ch["is_active"] = [u.is_active, active]
            if not ch:
                res.unchanged += 1
                continue
            if len(res.preview) < PREVIEW_ROWS:
                res.preview.append({"row": n, "employee_id": code, "name": new_name, "action": "update",
                                    "changes": [describe(k, v) for k, v in ch.items()]})
            if code != u.employee_code:   # keep the in-file view of IDs current, so later rows can reuse an old ID
                existing_codes.pop(u.employee_code.upper(), None)
                existing_codes[code.upper()] = uid
            res.updated += 1
            if dry_run:
                continue
            if "department" in ch:
                u.department_id = _dept(dept_name, cat_name).id if dept_name else None
            if "full_name" in ch:
                u.full_name = new_name
            if "employee_code" in ch:
                u.employee_code = code
            if "email" in ch:
                u.email = email_raw or placeholder_email(code)
            for key in ("job_title", "phone", "desk"):
                if key in ch:
                    setattr(u, key, ch[key][1])
            if "is_active" in ch:
                u.is_active = active
                if active:
                    u.locked_until, u.failed_logins = None, 0
                else:
                    db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id,
                                                          RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
            db.flush()
            res.changes.append((uid, ch))
            continue

        email = email_raw or placeholder_email(code)
        if active is False:
            res.errors.append({"row": n, "employee_id": code, "message": "A new user can't be created as Inactive."})
            continue
        if len(res.preview) < PREVIEW_ROWS:
            res.preview.append({"row": n, "employee_id": code, "name": name, "action": "create",
                                "email": None if email.endswith(PLACEHOLDER_DOMAIN) else email})
        res.created += 1
        if dry_run:
            existing_codes[code.upper()] = -n
            continue
        dept = _dept(dept_name, cat_name) if dept_name else None
        if password not in hash_cache:
            hash_cache[password] = hash_password(password)
        u = User(employee_code=code, email=email, full_name=name, department_id=dept.id if dept else None,
                 job_title=job, phone=phone, password_plain=password, password_hash=hash_cache[password],
                 timezone=tz, desk=(desk or "it") if role_code == "it_admin" else None)
        db.add(u)
        db.flush()
        db.add(UserRole(user_id=u.id, role_id=roles[role_code].id, granted_by=actor_id, granted_at=utcnow()))
        existing_codes[code.upper()] = u.id
    return res


def is_placeholder(email: str | None) -> bool:
    return bool(email) and email.endswith("@" + PLACEHOLDER_DOMAIN)


def count_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0
