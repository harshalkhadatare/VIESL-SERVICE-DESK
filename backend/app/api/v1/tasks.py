"""Task management API (management assigns, assignees report progress)."""
from datetime import datetime

from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.database import get_db
from app.core.errors import BusinessRuleError, Forbidden, NotFound
from app.models import User, utcnow
from app.models.task import OPEN_TASK_STATUSES, TASK_STATUSES, Task, TaskAttachment, TaskAttachmentBlob
from app.models.identity import UserRole, Role
from app.services import tasks as svc

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(None, max_length=8000)
    assignee_ids: list[int] = Field(default_factory=list, max_length=25)   # one or more people
    assignee_id: int | None = None                                       # (older clients: one person)
    due_at: datetime | None = None                                       # None = no deadline
    priority: str = Field("medium", pattern="^(high|medium|low)$")
    category: str | None = Field(None, max_length=60)
    requires_approval: bool = True


class TaskEdit(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=8000)
    assignee_ids: list[int] | None = Field(None, max_length=25)
    due_at: datetime | None = None
    priority: str | None = Field(None, pattern="^(high|medium|low)$")
    category: str | None = Field(None, max_length=60)
    requires_approval: bool | None = None
    reason: str | None = Field(None, max_length=500)


class UpdateIn(BaseModel):
    body: str | None = Field(None, max_length=4000)
    progress: int | None = Field(None, ge=0, le=100)


class StartIn(BaseModel):
    body: str | None = Field(None, max_length=4000)


class NoteIn(BaseModel):
    body: str | None = Field(None, max_length=4000)


class ApproveIn(BaseModel):
    body: str | None = Field(None, max_length=4000)
    rating: int | None = Field(None, ge=1, le=5)


class ExtensionIn(BaseModel):
    due_at: datetime
    reason: str = Field(min_length=3, max_length=500)


class DecisionIn(BaseModel):
    approve: bool
    body: str | None = Field(None, max_length=1000)


@router.get("/me")
def my_task_access(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """What the Tasks area should show for this person (used for menus and the start page)."""
    open_mine = db.scalar(select(func.count()).select_from(Task).where(
        svc.member_clause(p.id), Task.is_deleted.is_(False), Task.status.in_(OPEN_TASK_STATUSES))) or 0
    any_mine = db.scalar(select(func.count()).select_from(Task).where(
        svc.member_clause(p.id), Task.is_deleted.is_(False))) or 0
    return {"can_assign": svc.can_assign(p), "sees_all": svc.sees_all(p),
            # management by ROLE (IT administrators hold every permission but start on the IT desk)
            "is_management": "top_management" in p.roles,
            "is_top_management": "top_management" in p.roles,
            "has_tasks": any_mine > 0, "open_assigned_to_me": open_mine}


@router.get("/overview")
def overview(scope: str = Query("mine", pattern="^(mine|all)$"), p: Principal = Depends(get_principal),
             db: Session = Depends(get_db)):
    if not svc.can_assign(p):
        raise Forbidden("The task overview is for management.")
    return svc.overview(db, p, scope)


@router.get("/people")
def people(q: str | None = Query(None, max_length=60), p: Principal = Depends(get_principal),
           db: Session = Depends(get_db)):
    """Anyone active can be given a task."""
    if not svc.can_assign(p):
        raise Forbidden("Only management can assign tasks.")
    stmt = select(User).where(User.is_active.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.employee_code.ilike(like), User.email.ilike(like)))
    users = db.scalars(stmt.order_by(User.full_name).limit(30)).all()
    mgmt = set(db.scalars(select(UserRole.user_id).join(Role, Role.id == UserRole.role_id)
                          .where(Role.code == "top_management",
                                 UserRole.user_id.in_([u.id for u in users]))))
    return [{"id": u.id, "name": u.full_name, "employee_code": u.employee_code, "job_title": u.job_title,
             "department": u.department.name if u.department else None, "is_management": u.id in mgmt}
            for u in users]


@router.get("/counters")
def counters(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Overdue / due soon / unread comments on tasks you are part of."""
    return svc.counters(db, p)


@router.post("/read-all")
def read_all(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return {"marked": svc.mark_all_read(db, p)}


@router.get("/analytics")
def analytics(scope: str = Query("me", pattern="^(me|team|all)$"), days: int = Query(90, ge=7, le=730),
              p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.analytics(db, p, scope, days)


def _csv(v: str | None, allowed: set[str]) -> list[str] | None:
    if not v:
        return None
    vals = [x for x in v.split(",") if x]
    bad = [x for x in vals if x not in allowed]
    if bad:
        raise BusinessRuleError(f"Unknown filter value: {', '.join(bad)}")
    return vals


def _filters(view: str = Query("auto", pattern="^(auto|to_me|by_me|mine|all)$"),
             status: str | None = Query("open", max_length=120), q: str | None = Query(None, max_length=80),
             assignee_id: int | None = None, assigner_id: int | None = None,
             priority: str | None = Query(None, max_length=40), category: str | None = Query(None, max_length=60),
             due_from: datetime | None = None, due_to: datetime | None = None,
             created_from: datetime | None = None, created_to: datetime | None = None,
             overdue: bool = False, no_deadline: bool = False, has_request: bool = False, unread: bool = False,
             sort: str = Query("due", pattern="^(due|updated|created|priority)$"),
             p: Principal = Depends(get_principal)) -> dict:
    if view == "auto":
        view = "by_me" if svc.can_assign(p) else "to_me"
    if status == "overdue":
        status, overdue = "open", True
    statuses = None if (not status or status == "all") else _csv(status, {"open", *TASK_STATUSES})
    return dict(view=view, statuses=statuses, q=q, assignee_id=assignee_id, assigner_id=assigner_id,
                priorities=_csv(priority, {"high", "medium", "low"}), category=category,
                due_from=due_from, due_to=due_to, created_from=created_from, created_to=created_to,
                overdue=overdue, no_deadline=no_deadline, has_request=has_request, unread=unread, sort=sort)


@router.get("")
def list_tasks(f: dict = Depends(_filters), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
               p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Advanced search. status: comma list of open|not_started|in_progress|waiting_approval|completed|cancelled|all;
    'overdue' is accepted as a status too (older links)."""
    return svc.search(db, p, **f, page=page, page_size=page_size)


_VIEW_TITLE = {"to_me": "Tasks assigned to me", "by_me": "Tasks assigned by me", "mine": "My tasks", "all": "My tasks"}


@router.get("/export.xlsx")
def export_xlsx(f: dict = Depends(_filters), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Excel workbook of the tasks in the current list (only tasks you are on): details, every update, and
    every attachment with a link that opens it in the portal."""
    from zoneinfo import ZoneInfo

    from fastapi import Response

    from app.core.config import get_settings
    from app.services.audit import audit_p
    from app.services.task_export import build_task_workbook
    rows = svc.search(db, p, **f, page=1, page_size=1, rows_only=True)
    files = svc.attachments_of(db, [t.id for t in rows])
    shown = []
    if f["statuses"]:
        shown.append("Status: " + ", ".join(svc.STATUS_NAME.get(x, "Open") for x in f["statuses"]))
    for k, label in (("q", "Search"), ("category", "Category")):
        if f.get(k):
            shown.append(f"{label}: {f[k]}")
    if f["priorities"]:
        shown.append("Priority: " + ", ".join(x.title() for x in f["priorities"]))
    if f["overdue"]:
        shown.append("Overdue only")
    title = _VIEW_TITLE.get(f["view"], "Tasks")
    s = get_settings()
    data = build_task_workbook(rows, files=files, tz=p.user.timezone, company=s.company_name, title=title,
                               filters_text=", ".join(shown), base_url=s.app_base_url)
    audit_p(db, p, "task.export", entity_type="task", detail={"rows": len(rows), "view": f["view"]})
    db.commit()
    fname = f"{title.replace(' ', '_')}_{datetime.now(ZoneInfo(p.user.timezone)):%Y%m%d_%H%M}.xlsx"
    return Response(content=data, headers={"Content-Disposition": f'attachment; filename="{fname}"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("", status_code=201)
def create(data: TaskIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    body = data.model_dump()
    ids = body.pop("assignee_ids") or []
    one = body.pop("assignee_id")
    if one and one not in ids:
        ids.insert(0, one)
    t = svc.create_task(db, p, assignee_ids=ids, **body)
    return svc.task_detail(db, p, t)


@router.get("/{number}")
def detail(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(db, p, svc.get_task(db, p, number))


@router.patch("/{number}")
def edit(number: str, data: TaskEdit, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.edit_task(db, p, t, data.model_dump(exclude_unset=True)))


@router.post("/{number}/updates")
def post_update(number: str, data: UpdateIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.post_update(db, p, t, body=data.body, progress=data.progress))


@router.post("/{number}/start")
def start(number: str, data: StartIn | None = None, p: Principal = Depends(get_principal),
          db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.start_task(db, p, t, body=data.body if data else None))


@router.post("/{number}/submit")
def submit(number: str, data: NoteIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(db, p, svc.submit_task(db, p, svc.get_task(db, p, number, lock=True), body=data.body))


@router.post("/{number}/approve")
def approve(number: str, data: ApproveIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.approve_task(db, p, t, body=data.body, rating=data.rating))


@router.post("/{number}/send-back")
def send_back(number: str, data: NoteIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.send_back(db, p, t, body=data.body or ""))


@router.post("/{number}/cancel")
def cancel(number: str, data: NoteIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(db, p, svc.cancel_task(db, p, svc.get_task(db, p, number, lock=True), body=data.body))


@router.post("/{number}/extension")
def extension(number: str, data: ExtensionIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.request_extension(db, p, t, due_at=data.due_at, reason=data.reason))


@router.post("/{number}/extension/decision")
def extension_decision(number: str, data: DecisionIn, p: Principal = Depends(get_principal),
                       db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(db, p, svc.decide_extension(db, p, t, approve=data.approve, body=data.body))


# ------------------------------------------------------------------ attachments (people on the task only)
@router.get("/{number}/attachments")
def list_attachments(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number)
    return [svc.attachment_out(a) for a in svc.attachments_of(db, [t.id]).get(t.id, [])]


@router.post("/{number}/attachments", status_code=201)
async def upload_attachment(number: str, file: UploadFile = File(...), p: Principal = Depends(get_principal),
                            db: Session = Depends(get_db)):
    from app.services.attachments import MAX_FILES_PER_TASK, TASK_ALLOWED, store_upload
    from app.services.audit import audit_p
    t = svc.get_task(db, p, number)
    if not svc.can_attach(p, t):
        raise Forbidden("Files can't be added to this task.")
    n = db.scalar(select(func.count()).select_from(TaskAttachment).where(TaskAttachment.task_id == t.id))
    if n >= MAX_FILES_PER_TASK:
        raise BusinessRuleError(f"A task can have at most {MAX_FILES_PER_TASK} files.")
    meta = await store_upload(file, TASK_ALLOWED)
    data = meta.pop("data", None)
    a = svc.add_attachment(db, p, t, meta, data)
    audit_p(db, p, "task.attachment_upload", entity_type="task", entity_id=t.number,
            detail={"name": meta["original_name"], "size": meta["size_bytes"], "sha256": meta["sha256"]})
    db.commit()
    db.refresh(a)
    return svc.attachment_out(a)


@router.get("/{number}/attachments/{attachment_id}")
def download_attachment(number: str, attachment_id: int, mode: Literal["view", "download"] = Query("download"),
                        p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from urllib.parse import quote

    from fastapi import Response
    from fastapi.responses import FileResponse

    from app.services.attachments import path_for
    from app.services.audit import audit_p
    t = svc.get_task(db, p, number)          # not on the task → "Task not found"
    a = db.scalar(select(TaskAttachment).where(TaskAttachment.id == attachment_id, TaskAttachment.task_id == t.id))
    if not a:
        raise NotFound("File not found.")
    path = path_for(a.stored_name)
    blob = None
    if not path.exists():
        blob = db.get(TaskAttachmentBlob, a.id)
        if blob is None:
            raise NotFound("The file is missing from storage.")
    audit_p(db, p, "task.attachment_view" if mode == "view" else "task.attachment_download",
            entity_type="task", entity_id=t.number, detail={"attachment_id": a.id, "file": a.original_name})
    db.commit()
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    disposition = "inline" if mode == "view" else "attachment"
    if blob is not None:
        headers["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{quote(a.original_name)}"
        return Response(content=blob.data, media_type=a.content_type, headers=headers)
    return FileResponse(path, media_type=a.content_type, filename=a.original_name,
                        content_disposition_type=disposition, headers=headers)


@router.delete("/{number}/attachments/{attachment_id}", status_code=204)
def delete_attachment(number: str, attachment_id: int, p: Principal = Depends(get_principal),
                      db: Session = Depends(get_db)):
    from fastapi import Response

    from app.services.audit import audit_p
    from app.services.ticket_delete import remove_files
    t = svc.get_task(db, p, number)
    a = db.scalar(select(TaskAttachment).where(TaskAttachment.id == attachment_id, TaskAttachment.task_id == t.id))
    if not a:
        raise NotFound("File not found.")
    name = a.original_name
    stored = svc.remove_attachment(db, p, t, a)
    audit_p(db, p, "task.attachment_delete", entity_type="task", entity_id=t.number,
            detail={"attachment_id": attachment_id, "file": name})
    db.commit()
    remove_files([stored])
    return Response(status_code=204)
