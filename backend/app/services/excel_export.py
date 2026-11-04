"""Professional Excel (.xlsx) export of the ticket list: title block, coloured header, borders, zebra rows,
fitted column widths, filters on every column, frozen header, and colour-coded status / priority / SLA."""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

DESK_NAME = {"it": "IT", "erp": "ERP-IT", "both": "IT + ERP-IT"}

NAVY = "0B2545"
BLUE = "1D5FC4"
LIGHT = "E4EEFB"
ZEBRA = "F6F9FD"
GRID = "C9D6E6"
PRIO_FILL = {"P1": ("FDECEB", "B42318"), "P2": ("FDF1DC", "A15C07"), "P3": ("E4EEFB", "1D5FC4"), "P4": ("EDF1F6", "55657A")}
STATUS_FONT = {"RESOLVED": "157A52", "CLOSED": "55657A", "CANCELLED": "55657A", "PENDING_EMPLOYEE": "A15C07",
               "PENDING_VENDOR": "A15C07", "PENDING_APPROVAL": "A15C07", "PENDING_CHANGE": "A15C07",
               "REOPENED": "A15C07"}

# (header, width, getter) — width in Excel character units
COLUMNS = [
    ("Ticket No.", 17), ("Raised on", 17), ("IT team", 12), ("Category", 28), ("Subcategory", 22),
    ("Subject", 46), ("Status", 17), ("Priority", 12), ("Raised by", 22), ("Employee ID", 13),
    ("Department", 20), ("Assigned to", 22), ("Assignee ID", 13), ("Resolved on", 17), ("SLA", 11),
]


def _sla(t) -> str:
    if not t.sla:
        return ""
    if t.status_code in ("RESOLVED", "CLOSED", "CANCELLED"):
        return "Breached" if t.sla.resolution_breached else "Met"
    if t.sla.paused_at:
        return "Paused"
    return "Breached" if t.sla.resolution_breached else "On track"


def build_ticket_workbook(tickets, *, tz: str, company: str, title: str, filters_text: str) -> bytes:
    z = ZoneInfo(tz)
    wb = Workbook()
    ws = wb.active
    ws.title = "Tickets"
    thin = Side(style="thin", color=GRID)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ncol = len(COLUMNS)
    last = get_column_letter(ncol)

    # ---- title block (rows 1–3)
    ws.merge_cells(f"A1:{last}1")
    ws["A1"] = f"{company} — {title}"
    ws["A1"].font = Font(name="Calibri", size=15, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 30
    ws.merge_cells(f"A2:{last}2")
    ws["A2"] = (f"Generated {datetime.now(z).strftime('%d %b %Y, %H:%M')} ({tz})  ·  {len(tickets)} tickets"
                + (f"  ·  Filters: {filters_text}" if filters_text else ""))
    ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="4A5C74")
    ws["A2"].fill = PatternFill("solid", fgColor=LIGHT)
    ws["A2"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[2].height = 20

    # ---- header (row 4)
    hdr = 4
    for i, (name, width) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=hdr, column=i, value=name)
        c.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[hdr].height = 24

    # ---- data
    for r, t in enumerate(tickets, start=hdr + 1):
        values = [
            t.number,
            t.created_at.astimezone(z).replace(tzinfo=None),
            DESK_NAME.get(t.desk, t.desk),
            t.category.name if t.category else "",
            t.subcategory.name if t.subcategory else "",
            t.subject,
            t.status.name,
            f"{t.priority.code} · {t.priority.name}",
            t.requester.full_name if t.requester else "",
            t.requester.employee_code if t.requester else "",
            t.department.name if t.department else "",
            t.assignee.full_name if t.assignee else "Unassigned",
            t.assignee.employee_code if t.assignee else "",
            t.resolved_at.astimezone(z).replace(tzinfo=None) if t.resolved_at else None,
            _sla(t),
        ]
        zebra = PatternFill("solid", fgColor=ZEBRA) if (r - hdr) % 2 == 0 else None
        for i, v in enumerate(values, start=1):
            if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
                v = "'" + v   # never let user text become a formula
            c = ws.cell(row=r, column=i, value=v)
            c.border = border
            c.font = Font(name="Calibri", size=10.5)
            c.alignment = Alignment(vertical="center", wrap_text=(i == 6))
            if zebra:
                c.fill = zebra
        ws.cell(row=r, column=1).font = Font(name="Consolas", size=10.5, bold=True, color=BLUE)
        for col in (2, 14):
            ws.cell(row=r, column=col).number_format = "dd-mmm-yyyy hh:mm"
            ws.cell(row=r, column=col).alignment = Alignment(horizontal="center", vertical="center")
        for col in (3, 10, 13, 15):
            ws.cell(row=r, column=col).alignment = Alignment(horizontal="center", vertical="center")
        st = ws.cell(row=r, column=7)
        st.font = Font(name="Calibri", size=10.5, bold=True, color=STATUS_FONT.get(t.status_code, BLUE))
        fill, color = PRIO_FILL.get(t.priority.code, PRIO_FILL["P4"])
        pc = ws.cell(row=r, column=8)
        pc.fill = PatternFill("solid", fgColor=fill)
        pc.font = Font(name="Calibri", size=10.5, bold=True, color=color)
        pc.alignment = Alignment(horizontal="center", vertical="center")
        sla = ws.cell(row=r, column=15)
        sla.font = Font(name="Calibri", size=10.5, bold=True,
                        color={"Breached": "B42318", "Met": "157A52", "On track": "157A52"}.get(sla.value, "55657A"))
        if not t.assignee:
            ws.cell(row=r, column=12).font = Font(name="Calibri", size=10.5, italic=True, color="74859B")

    end_row = max(hdr + 1, hdr + len(tickets))
    # Excel table = filter buttons on every header + keeps working when rows are sorted/filtered
    if tickets:
        table = Table(displayName="Tickets", ref=f"A{hdr}:{last}{end_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
        ws.add_table(table)
    else:
        ws.auto_filter.ref = f"A{hdr}:{last}{hdr}"
        ws.cell(row=hdr + 1, column=1, value="No tickets match these filters.").font = Font(italic=True, color="74859B")
    ws.freeze_panes = f"B{hdr + 1}"          # header row and ticket number stay visible while scrolling
    ws.sheet_view.zoomScale = 100
    ws.sheet_view.showGridLines = False
    ws.print_title_rows = f"{hdr}:{hdr}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # ---- summary sheet
    s = wb.create_sheet("Summary")
    s["A1"] = f"{company} — summary"
    s["A1"].font = Font(size=14, bold=True, color=NAVY)
    rows = [("Total tickets", len(tickets))]
    for label, key in (("By IT team", lambda t: DESK_NAME.get(t.desk, t.desk)),
                       ("By status", lambda t: t.status.name), ("By priority", lambda t: t.priority.code)):
        counts: dict[str, int] = {}
        for t in tickets:
            counts[key(t)] = counts.get(key(t), 0) + 1
        rows.append((label, None))
        rows += [(f"   {k}", v) for k, v in sorted(counts.items())]
    for i, (k, v) in enumerate(rows, start=3):
        a, b = s.cell(row=i, column=1, value=k), s.cell(row=i, column=2, value=v)
        a.border = b.border = border
        if v is None:
            a.font = Font(bold=True, color="FFFFFF")
            a.fill = b.fill = PatternFill("solid", fgColor=BLUE)
        b.alignment = Alignment(horizontal="center")
    s.column_dimensions["A"].width = 28
    s.column_dimensions["B"].width = 12
    s.sheet_view.showGridLines = False

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
