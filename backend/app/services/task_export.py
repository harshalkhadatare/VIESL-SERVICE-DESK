"""Excel export of tasks: one workbook with three sheets.

- Tasks        one row per task with all its details, latest update and a link to open it
- Updates      the full conversation / history of every task (who, when, progress, message)
- Attachments  one row per file, with a link that opens that file in the portal (sign-in required)

Only tasks the person is on are ever exported (the caller passes rows from tasks.search, which enforces it).
"""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.services.excel_export import BLUE, GRID, LIGHT, NAVY, ZEBRA
from app.services.tasks import STATUS_NAME

PRIO = {"high": ("High", "FDECEB", "B42318"), "medium": ("Medium", "FDF1DC", "A15C07"), "low": ("Low", "E4EEFB", "1D5FC4")}
STATUS_COLOR = {"completed": "157A52", "cancelled": "55657A", "waiting_approval": "A15C07", "in_progress": "1D5FC4",
                "not_started": "55657A"}
KIND_NAME = {"created": "Assigned", "update": "Update", "comment": "Message", "progress": "Progress",
             "status": "Started", "submitted": "Marked complete", "approved": "Approved", "completed": "Completed",
             "returned": "Changes needed", "cancelled": "Cancelled", "deadline": "Deadline changed",
             "extension_requested": "More time asked", "extension_approved": "More time approved",
             "extension_declined": "More time refused", "description": "Details changed", "title": "Title changed",
             "priority": "Priority changed", "reassigned": "People changed", "file": "File added",
             "file_removed": "File removed"}


def _when(v, z) -> str:
    try:
        return datetime.fromisoformat(v).astimezone(z).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return v or ""


def _what_changed(e, z) -> str:
    """A short line for history entries that have no message of their own."""
    nv, ov = e.new_value, e.old_value
    if e.kind == "created":
        return f"Assigned to {nv}" if nv else ""
    if e.kind == "deadline":
        return "Deadline removed" if nv == "none" else f"New deadline: {_when(nv, z)}" + (
            f" (was {_when(ov, z)})" if ov and ov != "none" else "")
    if e.kind in ("extension_requested", "extension_approved"):
        return f"Until {_when(nv, z)}"
    if e.kind in ("file", "file_removed", "title"):
        return nv or ""
    if e.kind == "priority":
        return f"{ov} → {nv}" if ov else (nv or "")
    if e.kind == "reassigned":
        return "; ".join(x for x in (f"Added {nv}" if nv else "", f"Removed {ov}" if ov else "") if x)
    if e.kind == "progress" and e.progress is not None:
        return f"Progress {e.progress}%"
    return ""


def _safe(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v          # never let user text become a formula
    return v


def _size(b: int) -> str:
    return f"{b / 1048576:.1f} MB" if b >= 1048576 else f"{max(1, round(b / 1024))} KB"


class _Sheet:
    def __init__(self, wb, name, title, subtitle, columns, first=False):
        self.ws = wb.active if first else wb.create_sheet(name)
        self.ws.title = name
        self.cols = columns
        self.col = {h: i for i, (h, _w) in enumerate(columns, start=1)}
        thin = Side(style="thin", color=GRID)
        self.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        last = get_column_letter(len(columns))
        self.last = last
        ws = self.ws
        ws.merge_cells(f"A1:{last}1")
        ws["A1"] = title
        ws["A1"].font = Font(name="Calibri", size=15, bold=True, color="FFFFFF")
        ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
        ws["A1"].alignment = Alignment(vertical="center", indent=1)
        ws.row_dimensions[1].height = 30
        ws.merge_cells(f"A2:{last}2")
        ws["A2"] = subtitle
        ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="4A5C74")
        ws["A2"].fill = PatternFill("solid", fgColor=LIGHT)
        ws["A2"].alignment = Alignment(vertical="center", indent=1)
        ws.row_dimensions[2].height = 20
        self.hdr = 4
        for i, (h, w) in enumerate(columns, start=1):
            c = ws.cell(row=self.hdr, column=i, value=h)
            c.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=BLUE)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = self.border
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.row_dimensions[self.hdr].height = 24
        self.r = self.hdr

    def add(self, values: list, wrap=(), center=(), dates=(), link: tuple[str, str] | None = None):
        self.r += 1
        zebra = PatternFill("solid", fgColor=ZEBRA) if (self.r - self.hdr) % 2 == 0 else None
        for i, v in enumerate(values, start=1):
            c = self.ws.cell(row=self.r, column=i, value=_safe(v))
            c.border = self.border
            c.font = Font(name="Calibri", size=10.5)
            h = self.cols[i - 1][0]
            c.alignment = Alignment(vertical="top", wrap_text=h in wrap,
                                    horizontal="center" if (h in center or h in dates) else None)
            if h in dates:
                c.number_format = "dd-mmm-yyyy hh:mm"
            if zebra:
                c.fill = zebra
        self.ws.cell(row=self.r, column=1).font = Font(name="Consolas", size=10.5, bold=True, color=BLUE)
        if link:
            col, url = link
            c = self.cell(col)
            c.hyperlink = url
            c.font = Font(name="Calibri", size=10.5, color=BLUE, underline="single")
        return self.r

    def cell(self, header):
        return self.ws.cell(row=self.r, column=self.col[header])

    def finish(self, table_name: str, empty_text: str, freeze="B"):
        ws = self.ws
        if self.r > self.hdr:
            t = Table(displayName=table_name, ref=f"A{self.hdr}:{self.last}{self.r}")
            t.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
            ws.add_table(t)
        else:
            ws.cell(row=self.hdr + 1, column=1, value=empty_text).font = Font(italic=True, color="74859B")
        ws.freeze_panes = f"{freeze}{self.hdr + 1}"
        ws.sheet_view.showGridLines = False
        ws.print_title_rows = f"{self.hdr}:{self.hdr}"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_task_workbook(tasks, *, files: dict, tz: str, company: str, title: str, filters_text: str,
                        base_url: str) -> bytes:
    """tasks: Task rows (events and members loaded). files = {task_id: [TaskAttachment]}."""
    z = ZoneInfo(tz)
    base = base_url.rstrip("/")
    loc = lambda d: d.astimezone(z).replace(tzinfo=None) if d else None  # noqa: E731
    now = datetime.now(z)
    gen = f"Generated {now.strftime('%d %b %Y, %H:%M')} ({tz})"
    wb = Workbook()

    # ---- Tasks
    s = _Sheet(wb, "Tasks", f"{company} — {title}",
               f"{gen}  ·  {len(tasks)} tasks" + (f"  ·  Filters: {filters_text}" if filters_text else ""), [
                   ("Task No.", 16), ("Title", 38), ("Category", 16), ("Priority", 11), ("Status", 18),
                   ("Progress", 10), ("Assigned by", 22), ("Assigned to", 30), ("Assigned on", 17), ("Deadline", 17),
                   ("Started on", 17), ("Completed on", 17), ("Overdue", 10), ("Rating", 9), ("Description", 50),
                   ("Latest update", 50), ("Updates", 10), ("Attachments", 12), ("File names", 36), ("Open task", 14)],
               first=True)
    for t in tasks:
        msgs = [e for e in t.events if e.body]
        latest = msgs[-1] if msgs else None
        fl = files.get(t.id, [])
        pr = PRIO.get(t.priority, PRIO["medium"])
        s.add([
            t.number, t.title, t.category or "", pr[0], STATUS_NAME.get(t.status, t.status), t.progress / 100,
            f"{t.assigner.full_name} ({t.assigner.employee_code})" if t.assigner.employee_code else t.assigner.full_name,
            ", ".join(f"{u.full_name}" + (f" ({u.employee_code})" if u.employee_code else "") for u in t.assignees),
            loc(t.created_at), loc(t.due_at) if t.due_at else "No deadline", loc(t.started_at), loc(t.completed_at),
            "Yes" if t.is_overdue() else "No", f"{t.rating} / 5" if t.rating else "",
            t.description or "",
            (f"{latest.author.full_name if latest.author else 'System'} · {loc(latest.created_at):%d %b %Y %H:%M}\n"
             f"{latest.body}") if latest else "",
            len(msgs), len(fl), "\n".join(a.original_name for a in fl), "Open task",
        ], wrap={"Title", "Assigned to", "Description", "Latest update", "File names"},
            center={"Priority", "Progress", "Overdue", "Rating", "Updates", "Attachments", "Open task"},
            dates={"Assigned on", "Started on", "Completed on"} | ({"Deadline"} if t.due_at else set()),
            link=("Open task", f"{base}/#/tasks/{t.number}"))
        s.cell("Progress").number_format = "0%"
        c = s.cell("Priority")
        c.fill = PatternFill("solid", fgColor=pr[1])
        c.font = Font(name="Calibri", size=10.5, bold=True, color=pr[2])
        s.cell("Status").font = Font(name="Calibri", size=10.5, bold=True, color=STATUS_COLOR.get(t.status, BLUE))
        if t.is_overdue():
            s.cell("Overdue").font = Font(name="Calibri", size=10.5, bold=True, color="B42318")
        if not t.due_at:
            s.cell("Deadline").font = Font(name="Calibri", size=10.5, italic=True, color="74859B")
    s.finish("Tasks", "No tasks match these filters.")

    # ---- Updates (conversation + history)
    u = _Sheet(wb, "Updates", f"{company} — Task updates", f"{gen}  ·  every message and change, oldest first", [
        ("Task No.", 16), ("Task title", 34), ("When", 17), ("By", 24), ("What", 20), ("Progress", 10),
        ("Message", 70)])
    for t in tasks:
        for e in t.events:
            what = KIND_NAME.get(e.kind, e.kind.replace("_", " ").capitalize())
            detail = e.body or _what_changed(e, z)
            u.add([t.number, t.title, loc(e.created_at), e.author.full_name if e.author else "System", what,
                   (e.progress / 100) if e.progress is not None else None, detail],
                  wrap={"Task title", "Message"}, center={"Progress"}, dates={"When"})
            if e.progress is not None:
                u.cell("Progress").number_format = "0%"
    u.finish("Updates", "No updates yet.")

    # ---- Attachments
    a = _Sheet(wb, "Attachments", f"{company} — Task attachments",
               f"{gen}  ·  the link opens the file inside the portal (sign-in required; only people on the task)", [
                   ("Task No.", 16), ("Task title", 34), ("File name", 40), ("Type", 10), ("Size", 10),
                   ("Uploaded by", 24), ("Uploaded on", 17), ("Link", 14)])
    for t in tasks:
        for f in files.get(t.id, []):
            ext = f.original_name.rsplit(".", 1)[-1].upper() if "." in f.original_name else ""
            a.add([t.number, t.title, f.original_name, ext, _size(f.size_bytes),
                   f.uploader.full_name if f.uploader else "", loc(f.created_at), "Open file"],
                  wrap={"Task title", "File name"}, center={"Type", "Size", "Link"}, dates={"Uploaded on"},
                  link=("Link", f"{base}/#/tasks/{t.number}?file={f.id}"))
    a.finish("Attachments", "No files attached to these tasks.")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
