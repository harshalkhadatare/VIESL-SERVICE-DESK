"""Task management API (management assigns, assignees report progress)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.database import get_db
from app.core.errors import Forbidden
from app.models import User, utcnow
from app.models.task import OPEN_TASK_STATUSES, Task
from app.models.identity import UserRole, Role
from app.services import tasks as svc

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(None, max_length=8000)
    assignee_id: int
    due_at: datetime
    priority: str = Field("medium", pattern="^(high|medium|low)$")
    category: str | None = Field(None, max_length=60)
    requires_approval: bool = True


class TaskEdit(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=8000)
    assignee_id: int | None = None
    due_at: datetime | None = None
    priority: str | None = Field(None, pattern="^(high|medium|low)$")
    category: str | None = Field(None, max_length=60)
    requires_approval: bool | None = None
    reason: str | None = Field(None, max_length=500)


class UpdateIn(BaseModel):
    body: str | None = Field(None, max_length=4000)
    progress: int | None = Field(None, ge=0, le=100)


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
        Task.assignee_id == p.id, Task.is_deleted.is_(False), Task.status.in_(OPEN_TASK_STATUSES))) or 0
    any_mine = db.scalar(select(func.count()).select_from(Task).where(
        Task.assignee_id == p.id, Task.is_deleted.is_(False))) or 0
    return {"can_assign": svc.can_assign(p), "sees_all": svc.sees_all(p),
            # management by ROLE (IT administrators hold every permission but start on the IT desk)
            "is_management": bool({"task_manager", "top_management"} & set(p.roles)),
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
                          .where(Role.code.in_(["task_manager", "top_management"]),
                                 UserRole.user_id.in_([u.id for u in users]))))
    return [{"id": u.id, "name": u.full_name, "employee_code": u.employee_code, "job_title": u.job_title,
             "department": u.department.name if u.department else None, "is_management": u.id in mgmt}
            for u in users]


@router.get("")
def list_tasks(view: str = Query("auto", pattern="^(auto|to_me|by_me|all)$"),
               status: str = Query("open", pattern="^(open|all|not_started|in_progress|waiting_approval|completed|cancelled|overdue)$"),
               q: str | None = Query(None, max_length=80), assignee_id: int | None = None,
               priority: str | None = Query(None, pattern="^(high|medium|low)$"),
               sort: str = Query("due", pattern="^(due|updated|created|priority)$"),
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    now = utcnow()
    if view == "auto":
        view = "by_me" if svc.can_assign(p) else "to_me"
    w = [Task.is_deleted.is_(False), svc.scope_clause(p)]
    if view == "to_me":
        w.append(Task.assignee_id == p.id)
    elif view == "by_me":
        w.append(Task.assigner_id == p.id)
    elif not svc.sees_all(p):
        w.append(or_(Task.assignee_id == p.id, Task.assigner_id == p.id))
    if status == "open":
        w.append(Task.status.in_(OPEN_TASK_STATUSES))
    elif status == "overdue":
        w += [Task.status.in_(["not_started", "in_progress"]), Task.due_at < now]
    elif status != "all":
        w.append(Task.status == status)
    if q:
        like = f"%{q.strip()}%"
        w.append(or_(Task.title.ilike(like), Task.number.ilike(like), Task.category.ilike(like),
                     Task.assignee.has(or_(User.full_name.ilike(like), User.employee_code.ilike(like)))))
    if assignee_id:
        w.append(Task.assignee_id == assignee_id)
    if priority:
        w.append(Task.priority == priority)
    order = {"due": [Task.due_at], "updated": [Task.last_activity_at.desc()], "created": [Task.id.desc()],
             "priority": [func.lower(Task.priority) == "low", func.lower(Task.priority) == "medium", Task.due_at]}[sort]
    total = db.scalar(select(func.count()).select_from(Task).where(*w)) or 0
    rows = db.scalars(select(Task).where(*w).order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    return {"view": view, "total": total, "page": page, "page_size": page_size,
            "items": [svc.task_brief(t, now) for t in rows]}


@router.post("", status_code=201)
def create(data: TaskIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.create_task(db, p, **data.model_dump())
    return svc.task_detail(p, t)


@router.get("/{number}")
def detail(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(p, svc.get_task(db, p, number))


@router.patch("/{number}")
def edit(number: str, data: TaskEdit, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(p, svc.edit_task(db, p, t, data.model_dump(exclude_unset=True)))


@router.post("/{number}/updates")
def post_update(number: str, data: UpdateIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(p, svc.post_update(db, p, t, body=data.body, progress=data.progress))


@router.post("/{number}/start")
def start(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(p, svc.start_task(db, p, svc.get_task(db, p, number, lock=True)))


@router.post("/{number}/submit")
def submit(number: str, data: NoteIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(p, svc.submit_task(db, p, svc.get_task(db, p, number, lock=True), body=data.body))


@router.post("/{number}/approve")
def approve(number: str, data: ApproveIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(p, svc.approve_task(db, p, t, body=data.body, rating=data.rating))


@router.post("/{number}/send-back")
def send_back(number: str, data: NoteIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(p, svc.send_back(db, p, t, body=data.body or ""))


@router.post("/{number}/cancel")
def cancel(number: str, data: NoteIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return svc.task_detail(p, svc.cancel_task(db, p, svc.get_task(db, p, number, lock=True), body=data.body))


@router.post("/{number}/extension")
def extension(number: str, data: ExtensionIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(p, svc.request_extension(db, p, t, due_at=data.due_at, reason=data.reason))


@router.post("/{number}/extension/decision")
def extension_decision(number: str, data: DecisionIn, p: Principal = Depends(get_principal),
                       db: Session = Depends(get_db)):
    t = svc.get_task(db, p, number, lock=True)
    return svc.task_detail(p, svc.decide_extension(db, p, t, approve=data.approve, body=data.body))
