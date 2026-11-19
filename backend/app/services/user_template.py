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


def build_user_template(db: Session, company: str = "") -> bytes:
    depts = db.scalars(select(Department).where(Department.is_active.is_(True))
                       .order_by(Department.category, Department.name)).all()
    wb = Workbook()

    # ---- 1. Users (the only sheet that is imported — keep it first)
    ws = wb.active
    ws.title = "Users"
    _header(ws, 1, COLUMNS)
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
    for i, (name, _w, _req, help_text) in enumerate(COLUMNS, start=1):
        col = get_column_letter(i)
        dv = lists.get(col) or DataValidation(type="custom", formula1="TRUE", allow_blank=True)
        dv.showInputMessage, dv.promptTitle, dv.prompt = True, name, help_text[:250]
        dv.add(f"{col}2:{col}{ROWS + 1}")
        ws.add_data_validation(dv)
    grey = PatternFill("solid", fgColor=GREY)
    dep, cat = C["DEPARTMENT"], C["DEPARTMENT_CATEGORY"]
    for r in range(2, ROWS + 2):
        c = ws[f"{cat}{r}"]
        c.value = (f'=IF({dep}{r}="","",IFERROR(INDEX(Departments!$B$2:$B${last},'
                   f'MATCH({dep}{r},Departments!$C$2:$C${last},0)),""))')
        c.fill = grey
        c.font = Font(color="4A5C74", italic=True)
        for col in (C["EMPLOYEE_ID"], C["PHONE"]):   # IDs and phones stay as text (no lost leading zeros)
            ws[f"{col}{r}"].number_format = "@"
    ws["A1"].comment = Comment("Required. Fill one employee per row from row 2.", "IT Service Desk")

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
