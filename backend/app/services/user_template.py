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

# header, width, required, help shown when the cell is selected
COLUMNS = [
    ("USER_ID", 14, True, "Employee ID / code. Used to sign in. Must be unique."),
    ("USER_NAME", 28, True, "Full name, e.g. Harshal Khadatare."),
    ("EMAIL", 32, False, "Optional. Company email — ticket updates are emailed here. Several people may share one."),
    ("DEPARTMENT", 30, False, "Pick from the list. The category fills in by itself."),
    ("DEPARTMENT_CATEGORY", 22, False, "Filled automatically from DEPARTMENT — no need to type."),
    ("DESIGNATION", 24, False, "Optional. Job title, e.g. Site Engineer."),
    ("PHONE", 16, False, "Optional. Mobile or desk number."),
    ("ROLE", 18, False, "Employee (default) or IT Administrator."),
    ("IT_DEPARTMENT", 16, False, "Only for IT Administrators: IT or ERP-IT. Leave blank for employees."),
    ("PASSWORD", 18, False, "Optional. Starting password. Blank = the password you choose on the import screen."),
]


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
    dv_role = DataValidation(type="list", formula1='"Employee,IT Administrator"', allow_blank=True,
                             showErrorMessage=True, errorTitle="Role", error="Choose Employee or IT Administrator.")
    dv_desk = DataValidation(type="list", formula1='"IT,ERP-IT"', allow_blank=True,
                             showErrorMessage=True, errorTitle="IT department", error="Choose IT or ERP-IT.")
    for dv, col in ((dv_dept, "D"), (dv_role, "H"), (dv_desk, "I")):
        dv.add(f"{col}2:{col}{ROWS + 1}")
        ws.add_data_validation(dv)
    for i, (_name, _w, _req, help_text) in enumerate(COLUMNS, start=1):
        dv = DataValidation(type="custom", formula1="TRUE", allow_blank=True, showInputMessage=True,
                            promptTitle=COLUMNS[i - 1][0], prompt=help_text[:250])
        col = get_column_letter(i)
        if col in ("D", "H", "I"):   # these already have a list; add the prompt to it
            {"D": dv_dept, "H": dv_role, "I": dv_desk}[col].showInputMessage = True
            {"D": dv_dept, "H": dv_role, "I": dv_desk}[col].promptTitle = COLUMNS[i - 1][0]
            {"D": dv_dept, "H": dv_role, "I": dv_desk}[col].prompt = help_text[:250]
            continue
        dv.add(f"{col}2:{col}{ROWS + 1}")
        ws.add_data_validation(dv)
    grey = PatternFill("solid", fgColor=GREY)
    for r in range(2, ROWS + 2):
        c = ws.cell(row=r, column=5, value=f'=IF(D{r}="","",IFERROR(INDEX(Departments!$B$2:$B${last},'
                                           f'MATCH(D{r},Departments!$C$2:$C${last},0)),""))')
        c.fill = grey
        c.font = Font(color="4A5C74", italic=True)
        for col in (1, 7):   # IDs and phones stay as text (no lost leading zeros)
            ws.cell(row=r, column=col).number_format = "@"
    ws.cell(row=1, column=1).comment = Comment("Required. Fill one employee per row from row 2.", "IT Service Desk")

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
    samples = [
        ("90001", "Ramesh Patil (sample)", "ramesh.patil@example.com", pick(0), "Accountant", "9876543210", "Employee", "", ""),
        ("90002", "Sunita Jadhav (sample)", "", pick(10), "Site Engineer", "", "", "", "Welcome@123"),
        ("90003", "Vikas More (sample)", "it.team@example.com", pick(6), "ERP Executive", "", "IT Administrator", "ERP-IT", ""),
        ("90004", "Pooja Shinde (sample)", "it.team@example.com", pick(6), "System Administrator", "", "IT Administrator", "IT", ""),
    ]
    for r, (uid, name, email, dep, job, phone, role, desk, pw) in enumerate(samples, start=2):
        for j, v in enumerate((uid, name, email or None, dep.name if dep else None, (dep.category if dep else None),
                               job, phone or None, role or None, desk or None, pw or None), start=1):
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
        ("2. USER_ID and USER_NAME are required (dark headers marked *). Every other column is optional.", None),
        ("3. DEPARTMENT: pick from the dropdown. DEPARTMENT_CATEGORY fills in by itself (see the 'Departments' sheet).", None),
        ("4. ROLE: Employee (default) or IT Administrator. For IT Administrators also choose IT_DEPARTMENT: IT or ERP-IT.", None),
        ("5. PASSWORD: leave blank to use the starting password you type on the import screen.", None),
        ("6. EMAIL is optional. Without it the person can still sign in and use the portal, but gets no emails.", None),
        ("7. Save as .xlsx. In the portal: Users & roles → Import from Excel → choose the file → Preview → Import.", None),
        ("8. The preview shows every problem row before anything is saved. Fix them and preview again.", None),
        ("9. Tick 'Update people who already exist' to change names, emails or departments of existing users.", None),
        ("", None),
        ("Employees sign in with their USER_ID and password and can change the password after signing in.", "note"),
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
