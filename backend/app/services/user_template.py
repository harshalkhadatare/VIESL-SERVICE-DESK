"""The 'Users & roles' Excel upload template, built from the live department list so dropdowns are always current."""
import io

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department

NAVY, BLUE, LIGHT, GREY, REQ = "0B2545", "1F5FD1", "EAF1FD", "F2F4F7", "B42318"
ROWS = 1000   # rows prepared with dropdowns

# The same fields as "Edit user" in Users & roles, in the same order.
# header, width, required, help shown when the cell is selected
COLUMNS = [
    ("FULL_NAME", 28, True, "Full name, e.g. Ramesh Patil."),
    ("EMPLOYEE_ID", 15, True, "Employee ID — used to sign in. Must be unique."),
    ("DEPARTMENT_CATEGORY", 22, False, "Filled automatically when you pick a DEPARTMENT — no need to type."),
    ("DEPARTMENT", 30, False, "Pick from the list. The category fills in by itself."),
    ("COMPANY_EMAIL", 32, False, "Optional. Ticket updates are emailed here. Several people may share one."),
    ("JOB_TITLE", 24, False, "Optional, e.g. Site Engineer."),
    ("PHONE", 16, False, "Optional. Mobile or desk number."),
    ("IT_DEPARTMENT", 16, False, "Only for IT Administrators: IT or ERP-IT. Filling it makes the person an IT "
                                 "Administrator of that department. Leave blank for employees."),
]
C = {name: get_column_letter(i) for i, (name, *_r) in enumerate(COLUMNS, start=1)}   # header → column letter


def _header(ws, row, cols, fill=BLUE):
    thin = Side(style="thin", color="C9D4E3")
    for i, (name, width, required, _help) in enumerate(cols, start=1):
        c = ws.cell(row=row, column=i, value=name + (" *" if required else ""))
        c.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY if required else fill)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[row].height = 30


# Extra columns in "Export users" (after the template columns). STATUS can be edited; the others are for checking.
EXPORT_EXTRA = [
    ("STATUS", 12, False, "Active or Inactive. Inactive people cannot sign in."),
    ("ROLES (read only)", 34, False, "Shown for checking only. Change roles with the Roles button in Users & roles."),
    ("LAST_SIGN_IN (read only)", 20, False, "Shown for checking only."),
    ("SYSTEM_ID (do not change)", 14, False, "Links this row to the person, so even the Employee ID can be changed. "
                                             "Leave it as it is. New people: leave it blank."),
]
ROLE_NAMES = {"top_management": "Managing Director", "it_admin": "IT Administrator", "manager_l1": "Manager L1",
              "manager_l2": "Manager L2", "employee": "Employee"}


def build_user_template(db: Session, company: str = "", users=None) -> bytes:
    """The blank upload template, or with `users` the filled-in export that can be edited and uploaded back."""
    from app.seed import ROLE_ORDER
    from app.services.user_import import is_placeholder
    depts = db.scalars(select(Department).where(Department.is_active.is_(True))
                       .order_by(Department.category, Department.name)).all()
    export = users is not None
    cols = COLUMNS + (EXPORT_EXTRA if export else [])
    rows_ready = max(ROWS, len(users) + 300) if export else ROWS
    wb = Workbook()

    # ---- 1. Users (the only sheet that is imported — keep it first)
    ws = wb.active
    ws.title = "Users"
    _header(ws, 1, cols)
    ws.freeze_panes = "C2"
    ws.sheet_view.zoomScale = 100
    n = max(1, len(depts))
    last = n + 1
    # Department dropdown + automatic category (from the Departments sheet)
    dv_dept = DataValidation(type="list", formula1=f"=Departments!$C$2:$C${last}", allow_blank=True,
                             showErrorMessage=True, errorStyle="warning", errorTitle="Department not in the list",
                             error="Pick a department from the list. A new name will create a new department.")
    dv_desk = DataValidation(type="list", formula1='"IT,ERP-IT"', allow_blank=True,
                             showErrorMessage=True, errorTitle="IT department", error="Choose IT or ERP-IT.")
    lists = {C["DEPARTMENT"]: dv_dept, C["IT_DEPARTMENT"]: dv_desk}
    if export:
        lists[get_column_letter(len(COLUMNS) + 1)] = DataValidation(
            type="list", formula1='"Active,Inactive"', allow_blank=True, showErrorMessage=True,
            errorTitle="Status", error="Choose Active or Inactive.")
    for i, (name, _w, _req, help_text) in enumerate(cols, start=1):
        col = get_column_letter(i)
        dv = lists.get(col) or DataValidation(type="custom", formula1="TRUE", allow_blank=True)
        dv.showInputMessage, dv.promptTitle, dv.prompt = True, name, help_text[:250]
        dv.add(f"{col}2:{col}{rows_ready + 1}")
        ws.add_data_validation(dv)
    grey = PatternFill("solid", fgColor=GREY)
    dep, cat = C["DEPARTMENT"], C["DEPARTMENT_CATEGORY"]
    for r in range(2, rows_ready + 2):
        c = ws[f"{cat}{r}"]
        c.value = (f'=IF({dep}{r}="","",IFERROR(INDEX(Departments!$B$2:$B${last},'
                   f'MATCH({dep}{r},Departments!$C$2:$C${last},0)),""))')
        c.fill = grey
        c.font = Font(color="4A5C74", italic=True)
        for col in (C["EMPLOYEE_ID"], C["PHONE"]):   # IDs and phones stay as text (no lost leading zeros)
            ws[f"{col}{r}"].number_format = "@"
    ws["A1"].comment = Comment("Required. Fill one employee per row from row 2.", "IT Service Desk")
    if export:
        rank = {c: i for i, c in enumerate(ROLE_ORDER)}
        ro = PatternFill("solid", fgColor=GREY)
        for r, u in enumerate(users, start=2):
            codes = sorted(u.role_codes, key=lambda c: rank.get(c, 99))
            vals = {"FULL_NAME": u.full_name, "EMPLOYEE_ID": u.employee_code,
                    "DEPARTMENT": u.department.name if u.department else None,
                    "COMPANY_EMAIL": None if is_placeholder(u.email) else u.email, "JOB_TITLE": u.job_title,
                    "PHONE": u.phone,
                    "IT_DEPARTMENT": ("ERP-IT" if u.desk == "erp" else "IT") if "it_admin" in codes else None}
            for name, v in vals.items():
                ws[f"{C[name]}{r}"] = v
            extra = ["Active" if u.is_active else "Inactive", ", ".join(ROLE_NAMES.get(c, c) for c in codes),
                     u.last_login_at.strftime("%d-%b-%Y %H:%M") if u.last_login_at else "Never", u.id]
            for k, v in enumerate(extra):
                c = ws.cell(row=r, column=len(COLUMNS) + 1 + k, value=v)
                if k:
                    c.fill = ro
                    c.font = Font(color="4A5C74")
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(users) + 1}"
        for k in range(1, 4):   # read-only headers in grey
            ws.cell(row=1, column=len(COLUMNS) + 1 + k).fill = PatternFill("solid", fgColor="5B6B82")

    # ---- 2. Departments (reference + source of the dropdown)
    d = wb.create_sheet("Departments")
    _header(d, 1, [("SR_NO", 8, False, ""), ("DEPARTMENT_CATEGORY", 26, False, ""), ("DEPARTMENT", 34, False, "")])
    zebra = PatternFill("solid", fgColor=LIGHT)
    for i, dep in enumerate(depts, start=2):
        for j, v in enumerate((i - 1, dep.category or "OTHER", dep.name), start=1):
            c = d.cell(row=i, column=j, value=v)
            if i % 2 == 0:
                c.fill = zebra
        d.cell(row=i, column=1).alignment = Alignment(horizontal="center")
    d.freeze_panes = "A2"

    # ---- 3. Example (not imported)
    ex = wb.create_sheet("Example")
    _header(ex, 1, COLUMNS)
    pick = lambda k: depts[min(k, len(depts) - 1)] if depts else None  # noqa: E731
    samples = [   # full name, employee ID, department, email, job title, phone, IT department
        ("Ramesh Patil (sample)", "90001", pick(0), "ramesh.patil@example.com", "Accountant", "9876543210", None),
        ("Sunita Jadhav (sample)", "90002", pick(10), None, "Site Engineer", None, None),
        ("Vikas More (sample)", "90003", pick(6), "it.team@example.com", "ERP Executive", None, "ERP-IT"),
        ("Pooja Shinde (sample)", "90004", pick(6), "it.team@example.com", "System Administrator", None, "IT"),
    ]
    for r, (name, uid, dep, email, job, phone, desk) in enumerate(samples, start=2):
        for j, v in enumerate((name, uid, dep.category if dep else None, dep.name if dep else None, email, job, phone,
                               desk), start=1):
            ex.cell(row=r, column=j, value=v)
    note = ex.cell(row=len(samples) + 3, column=1,
                   value="Example only — this sheet is NOT imported. Fill the 'Users' sheet (the first sheet).")
    note.font = Font(bold=True, color=REQ)

    # ---- 4. Instructions
    ins = wb.create_sheet("Instructions")
    ins.column_dimensions["A"].width = 110
    lines = [
        ("How to update existing users from this file" + (f" — {company}" if company else ""), "title"),
        ("", None),
        ("1. This file lists everyone in the portal. Change any cell in the 'Users' sheet: name, Employee ID, "
         "department, email, job title, phone, IT department or STATUS (Active / Inactive).", None),
        ("2. Do NOT change the SYSTEM_ID column — it tells the portal which person each row is, so the Employee ID itself "
         "can be corrected.", None),
        ("3. Emptying a cell clears that value (an empty email means the person gets no emails).", None),
        ("4. Grey columns (ROLES, LAST_SIGN_IN) are only for checking. Change roles with the Roles button.", None),
        ("5. To add new people, fill a new row and leave SYSTEM_ID empty. They get the starting password from the import screen.", None),
        ("6. Deleting a row does NOT delete the person — use Deactivate or Delete in the portal.", None),
        ("7. Save as .xlsx. In the portal: Users & roles → Import from Excel → choose this file → Preview.", None),
        ("8. The preview lists every change (old → new) and every problem before anything is saved. Then press Import.", None),
        ("", None),
        ("Every change is recorded in the audit log. Keep this file private — it has everyone's contact details.", "warn"),
    ] if export else [
        ("How to add employees to the IT Service Desk" + (f" — {company}" if company else ""), "title"),
        ("", None),
        ("1. Fill the first sheet, 'Users' — one employee per row, starting on row 2. Do not change the header row.", None),
        ("2. FULL_NAME and EMPLOYEE_ID are required (dark headers marked *). Every other column is optional.", None),
        ("3. DEPARTMENT: pick from the dropdown. DEPARTMENT_CATEGORY fills in by itself (see the 'Departments' sheet).", None),
        ("4. IT_DEPARTMENT: only for IT Administrators (IT or ERP-IT). Leave it blank for employees.", None),
        ("5. Everyone gets the starting password you type on the import screen; they can change it after signing in.", None),
        ("6. COMPANY_EMAIL is optional. Without it the person can still sign in and use the portal, but gets no emails.", None),
        ("7. Save as .xlsx. In the portal: Users & roles → Import from Excel → choose the file → Preview → Import.", None),
        ("8. The preview shows every problem row before anything is saved. Fix them and preview again.", None),
        ("9. Tick 'Update people who already exist' to change names, emails or departments of existing users.", None),
        ("", None),
        ("The columns are the same as 'Edit user' in Users & roles. Employees sign in with their EMPLOYEE_ID.", "note"),
        ("Keep this file private — it can contain passwords.", "warn"),
    ]
    for i, (text, kind) in enumerate(lines, start=1):
        c = ins.cell(row=i, column=1, value=text)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        if kind == "title":
            c.font = Font(size=15, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=NAVY)
            ins.row_dimensions[i].height = 28
        elif kind == "note":
            c.font = Font(italic=True, color="4A5C74")
        elif kind == "warn":
            c.font = Font(bold=True, color=REQ)
    for sheet in (ws, d, ex, ins):
        sheet.sheet_view.showGridLines = sheet is not ins

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
