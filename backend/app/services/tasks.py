"""Task management rules.

Who can do what
* Management (task.assign) creates tasks for anyone and manages the tasks they assigned.
* Top management (task.view_all) and Task admins (task.admin — IT administrators) see and manage every task.
* The assignee (any user, employees included) starts the task, posts progress, asks for more time and submits it.
* Everyone else sees nothing.

Flow:  not_started → in_progress → waiting_approval → completed      (cancelled from any open state)
       waiting_approval / completed → in_progress  when the assigner sends it back with feedback.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import BusinessRuleError, Conflict, Forbidden, NotFound
from app.models import TicketSequence, User, utcnow
from app.models.task import OPEN_TASK_STATUSES, TASK_PRIORITIES, Task, TaskEvent
from app.services.audit import audit_p
from app.services.notifications import notify

STATUS_NAME = {"not_started": "Not started", "in_progress": "In progress", "waiting_approval": "Waiting for approval",
               "completed": "Completed", "cancelled": "Cancelled"}
PRIORITY_NAME = {"high": "High", "medium": "Medium", "low": "Low"}
QUIET_DAYS = 5          # "no update for N days" shows in Needs your attention


# ---------------------------------------------------------------- access
def can_assign(p: Principal) -> bool:
    return p.can("task.assign") or p.can("task.admin")


def sees_all(p: Principal) -> bool:
    return p.can("task.view_all") or p.can("task.admin")


def scope_clause(p: Principal):
    """Tasks this person may see."""
    if sees_all(p):
        return true()
    return or_(Task.assignee_id == p.id, Task.assigner_id == p.id)


def can_manage(p: Principal, t: Task) -> bool:
    return t.assigner_id == p.id or sees_all(p)


def get_task(db: Session, p: Principal, number: str, lock: bool = False) -> Task:
    stmt = select(Task).where(Task.number == number, Task.is_deleted.is_(False), scope_clause(p))
    if lock:
        stmt = stmt.with_for_update(of=Task)
    t = db.scalar(stmt)
    if not t:
        raise NotFound("Task not found.")
    return t


def _need_manage(p: Principal, t: Task) -> None:
    if not can_manage(p, t):
        raise Forbidden("Only the person who assigned this task (or top management) can do this.")


def _need_assignee(p: Principal, t: Task) -> None:
    if t.assignee_id != p.id:
        raise Forbidden("Only the person this task is assigned to can do this.")


def _need_open(t: Task) -> None:
    if not t.is_open:
        raise BusinessRuleError(f"This task is {STATUS_NAME[t.status].lower()}.")


# ---------------------------------------------------------------- helpers
def next_task_number(db: Session, year: int) -> str:
    for _ in range(3):
        seq = db.scalar(select(TicketSequence).where(TicketSequence.series == "TSK", TicketSequence.year == year)
                        .with_for_update())
        if seq is None:
            try:
                with db.begin_nested():
                    seq = TicketSequence(series="TSK", year=year, last_value=0)
                    db.add(seq)
                    db.flush()
            except IntegrityError:
                continue
        seq.last_value += 1
        db.flush()
        return f"TSK-{year % 100:02d}-{seq.last_value:06d}"
    raise Conflict("Could not allocate a task number, please retry.")


def _event(db: Session, t: Task, kind: str, actor_id: int | None, body: str | None = None, progress: int | None = None,
           old: str | None = None, new: str | None = None) -> TaskEvent:
    ev = TaskEvent(task_id=t.id, author_id=actor_id, kind=kind, body=(body or None), progress=progress,
                   old_value=(old or None) and str(old)[:120], new_value=(new or None) and str(new)[:120],
                   created_at=utcnow())
    db.add(ev)
    t.last_activity_at = ev.created_at
    return ev


def _tell(db: Session, user_id: int | None, actor_id: int, event: str, title: str, body: str | None, t: Task,
          key: str | None = None) -> None:
    if user_id and user_id != actor_id:   # never notify yourself
        notify(db, user_id, event, title, body, task=t, dedupe_key=key)


def _fmt_due(dt: datetime, tz: str) -> str:
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(tz)).strftime("%d %b %Y, %I:%M %p")


def _active_user(db: Session, uid: int) -> User:
    u = db.get(User, uid)
    if not u or not u.is_active:
        raise BusinessRuleError("Choose an active person to assign the task to.", details=[{"field": "assignee_id"}])
    return u


def _check_due(due: datetime) -> datetime:
    if due.tzinfo is None:
        raise BusinessRuleError("Deadline must include a time zone.", details=[{"field": "due_at"}])
    if due < utcnow() - timedelta(minutes=5):
        raise BusinessRuleError("The deadline is in the past.", details=[{"field": "due_at"}])
    return due


def _clean(s: str | None) -> str | None:
    s = (s or "").strip()
    return s or None


# ---------------------------------------------------------------- actions
def create_task(db: Session, p: Principal, *, title: str, description: str | None, assignee_id: int,
                due_at: datetime, priority: str = "medium", category: str | None = None,
                requires_approval: bool = True) -> Task:
    if not can_assign(p):
        raise Forbidden("Only management can assign tasks.")
    if priority not in TASK_PRIORITIES:
        raise BusinessRuleError("Choose High, Medium or Low priority.", details=[{"field": "priority"}])
    assignee = _active_user(db, assignee_id)
    now = utcnow()
    t = Task(number=next_task_number(db, now.year), title=title.strip(), description=_clean(description),
             category=_clean(category), priority=priority, status="not_started", progress=0, assigner_id=p.id,
             assignee_id=assignee.id, due_at=_check_due(due_at), requires_approval=requires_approval,
             last_activity_at=now, created_at=now, updated_at=now)
    db.add(t)
    db.flush()
    _event(db, t, "created", p.id, new=assignee.label)
    _tell(db, assignee.id, p.id, "task_assigned", f"New task from {p.user.full_name}: {t.title}",
          f"Deadline: {_fmt_due(t.due_at, assignee.timezone)}\nPriority: {PRIORITY_NAME[t.priority]}"
          + (f"\n\n{t.description[:600]}" if t.description else ""), t)
    audit_p(db, p, "task.create", entity_type="task", entity_id=t.number,
            detail={"assignee": assignee.label, "due_at": t.due_at.isoformat(), "priority": priority})
    db.commit()
    return t


def edit_task(db: Session, p: Principal, t: Task, changes: dict) -> Task:
    _need_manage(p, t)
    _need_open(t)
    if "title" in changes and changes["title"]:
        t.title = changes["title"].strip()
    if "description" in changes:
        t.description = _clean(changes["description"])
    if "category" in changes:
        t.category = _clean(changes["category"])
    if "requires_approval" in changes and changes["requires_approval"] is not None:
        t.requires_approval = bool(changes["requires_approval"])
    if changes.get("priority") and changes["priority"] != t.priority:
        if changes["priority"] not in TASK_PRIORITIES:
            raise BusinessRuleError("Choose High, Medium or Low priority.", details=[{"field": "priority"}])
        _event(db, t, "priority", p.id, old=PRIORITY_NAME[t.priority], new=PRIORITY_NAME[changes["priority"]])
        t.priority = changes["priority"]
    if changes.get("due_at") and changes["due_at"] != t.due_at:
        new_due = _check_due(changes["due_at"])
        _event(db, t, "deadline", p.id, body=_clean(changes.get("reason")), old=t.due_at.isoformat(),
               new=new_due.isoformat())
        t.due_at = new_due
        t.requested_due_at = t.request_reason = None
        _tell(db, t.assignee_id, p.id, "task_update", f"Deadline changed: {t.title}",
              f"New deadline: {_fmt_due(new_due, t.assignee.timezone)}", t)
    if changes.get("assignee_id") and changes["assignee_id"] != t.assignee_id:
        new = _active_user(db, changes["assignee_id"])
        old = t.assignee
        _event(db, t, "reassigned", p.id, body=_clean(changes.get("reason")), old=old.label, new=new.label)
        t.assignee_id = new.id
        db.flush()
        db.refresh(t, ["assignee"])
        _tell(db, new.id, p.id, "task_assigned", f"New task from {p.user.full_name}: {t.title}",
              f"Deadline: {_fmt_due(t.due_at, new.timezone)}", t)
        _tell(db, old.id, p.id, "task_update", f"Task moved to {new.full_name}: {t.title}",
              "You no longer need to work on this task.", t)
    t.updated_at = utcnow()
    audit_p(db, p, "task.edit", entity_type="task", entity_id=t.number,
            detail={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in changes.items() if k != "description"})
    db.commit()
    return t


def post_update(db: Session, p: Principal, t: Task, *, body: str | None, progress: int | None) -> Task:
    """Assignee reports progress (with or without a note); either side may add a plain comment."""
    body = _clean(body)
    is_assignee = t.assignee_id == p.id
    if not is_assignee and not can_manage(p, t):
        raise Forbidden("You can't post on this task.")
    if progress is not None and not is_assignee:
        raise Forbidden("Only the assignee reports progress.")
    if not body and progress is None:
        raise BusinessRuleError("Write an update or set the progress.")
    _need_open(t)
    if progress is not None:
        if not 0 <= progress <= 100:
            raise BusinessRuleError("Progress must be between 0 and 100%.")
        if t.status == "waiting_approval":
            raise BusinessRuleError("This task is waiting for approval — wait for the decision.")
        if t.status == "not_started":
            t.status, t.started_at = "in_progress", utcnow()
            _event(db, t, "status", p.id, old="not_started", new="in_progress")
        old = t.progress
        t.progress = progress
        _event(db, t, "progress", p.id, body=body, progress=progress, old=f"{old}%", new=f"{progress}%")
        _tell(db, t.assigner_id, p.id, "task_update", f"{p.user.full_name} updated “{t.title}” to {progress}%",
              body, t)
    else:
        _event(db, t, "comment", p.id, body=body)
        other = t.assigner_id if is_assignee else t.assignee_id
        _tell(db, other, p.id, "task_update", f"New message on “{t.title}” from {p.user.full_name}", body, t)
    t.updated_at = utcnow()
    db.commit()
    return t


def start_task(db: Session, p: Principal, t: Task) -> Task:
    _need_assignee(p, t)
    if t.status != "not_started":
        raise BusinessRuleError("This task has already started.")
    t.status, t.started_at = "in_progress", utcnow()
    _event(db, t, "status", p.id, old="not_started", new="in_progress")
    _tell(db, t.assigner_id, p.id, "task_update", f"{p.user.full_name} started “{t.title}”", None, t)
    db.commit()
    return t


def submit_task(db: Session, p: Principal, t: Task, *, body: str | None) -> Task:
    _need_assignee(p, t)
    if t.status not in ("not_started", "in_progress"):
        raise BusinessRuleError("This task can't be submitted now.")
    now = utcnow()
    t.progress, t.submitted_at = 100, now
    t.started_at = t.started_at or now
    t.requested_due_at = t.request_reason = None
    if t.requires_approval:
        old, t.status = t.status, "waiting_approval"
        _event(db, t, "submitted", p.id, body=_clean(body), old=old, new="waiting_approval")
        _tell(db, t.assigner_id, p.id, "task_submitted", f"Please review: {p.user.full_name} completed “{t.title}”",
              _clean(body), t)
    else:
        old, t.status, t.completed_at = t.status, "completed", now
        _event(db, t, "completed", p.id, body=_clean(body), old=old, new="completed")
        _tell(db, t.assigner_id, p.id, "task_completed", f"{p.user.full_name} completed “{t.title}”", _clean(body), t)
    db.commit()
    return t


def approve_task(db: Session, p: Principal, t: Task, *, body: str | None, rating: int | None) -> Task:
    _need_manage(p, t)
    if t.status != "waiting_approval":
        raise BusinessRuleError("Only tasks waiting for approval can be approved.")
    if rating is not None and not 1 <= rating <= 5:
        raise BusinessRuleError("Rating must be 1 to 5 stars.")
    t.status, t.completed_at, t.rating = "completed", utcnow(), rating
    _event(db, t, "approved", p.id, body=_clean(body), new=f"{rating}★" if rating else None)
    _tell(db, t.assignee_id, p.id, "task_completed", f"Approved: “{t.title}”",
          (f"Rating: {'★' * rating}\n" if rating else "") + (_clean(body) or "Well done — the task is complete."), t)
    audit_p(db, p, "task.approve", entity_type="task", entity_id=t.number, detail={"rating": rating})
    db.commit()
    return t


def send_back(db: Session, p: Principal, t: Task, *, body: str) -> Task:
    """Not good enough yet (or reopen a completed task): back to In progress with the assigner's feedback."""
    _need_manage(p, t)
    if t.status not in ("waiting_approval", "completed"):
        raise BusinessRuleError("Only submitted or completed tasks can be sent back.")
    body = _clean(body)
    if not body or len(body) < 3:
        raise BusinessRuleError("Tell the assignee what needs to change (at least 3 characters).",
                                details=[{"field": "body"}])
    old = t.status
    t.status, t.completed_at, t.submitted_at, t.rating = "in_progress", None, None, None
    t.progress = min(t.progress, 90)
    _event(db, t, "returned", p.id, body=body, old=old, new="in_progress")
    _tell(db, t.assignee_id, p.id, "task_returned", f"Changes needed on “{t.title}”", body, t)
    db.commit()
    return t


def cancel_task(db: Session, p: Principal, t: Task, *, body: str | None) -> Task:
    _need_manage(p, t)
    _need_open(t)
    old = t.status
    t.status, t.cancelled_at = "cancelled", utcnow()
    _event(db, t, "cancelled", p.id, body=_clean(body), old=old, new="cancelled")
    _tell(db, t.assignee_id, p.id, "task_update", f"Task cancelled: “{t.title}”",
          _clean(body) or "You no longer need to work on this task.", t)
    audit_p(db, p, "task.cancel", entity_type="task", entity_id=t.number)
    db.commit()
    return t


def request_extension(db: Session, p: Principal, t: Task, *, due_at: datetime, reason: str) -> Task:
    _need_assignee(p, t)
    _need_open(t)
    reason = _clean(reason)
    if not reason or len(reason) < 3:
        raise BusinessRuleError("Give a short reason for the extra time.", details=[{"field": "reason"}])
    if due_at <= t.due_at:
        raise BusinessRuleError("Pick a date after the current deadline.", details=[{"field": "due_at"}])
    t.requested_due_at, t.request_reason = due_at, reason[:500]
    _event(db, t, "extension_requested", p.id, body=reason, old=t.due_at.isoformat(), new=due_at.isoformat())
    _tell(db, t.assigner_id, p.id, "task_extension",
          f"{p.user.full_name} asks for more time on “{t.title}”",
          f"Requested deadline: {_fmt_due(due_at, t.assigner.timezone)}\nReason: {reason}", t)
    db.commit()
    return t


def decide_extension(db: Session, p: Principal, t: Task, *, approve: bool, body: str | None) -> Task:
    _need_manage(p, t)
    if not t.requested_due_at:
        raise BusinessRuleError("There is no pending request for more time.")
    old, new = t.due_at, t.requested_due_at
    if approve:
        t.due_at = new
    _event(db, t, "extension_approved" if approve else "extension_declined", p.id, body=_clean(body),
           old=old.isoformat(), new=new.isoformat())
    t.requested_due_at = t.request_reason = None
    _tell(db, t.assignee_id, p.id, "task_extension",
          (f"More time approved: “{t.title}”" if approve else f"More time not approved: “{t.title}”"),
          (f"New deadline: {_fmt_due(new, t.assignee.timezone)}" if approve else
           f"The deadline stays {_fmt_due(old, t.assignee.timezone)}.")
          + (f"\n{_clean(body)}" if _clean(body) else ""), t)
    db.commit()
    return t


# ---------------------------------------------------------------- reminders (scheduler)
def run_task_reminders(db: Session, now: datetime | None = None) -> dict:
    """Due within 24 h → remind the assignee once. Past the deadline → tell assignee and assigner once."""
    now = now or utcnow()
    stats = {"due_soon": 0, "overdue": 0}
    soon = db.scalars(select(Task).where(Task.status.in_(["not_started", "in_progress"]), Task.is_deleted.is_(False),
                                         Task.due_at > now, Task.due_at <= now + timedelta(hours=24))).all()
    for t in soon:
        if notify(db, t.assignee_id, "task_due_soon", f"Due soon: “{t.title}”",
                  f"Deadline: {_fmt_due(t.due_at, t.assignee.timezone)} — {t.progress}% done so far.", task=t,
                  dedupe_key=f"task-due:{t.id}:{t.due_at.isoformat()}"):
            stats["due_soon"] += 1
    late = db.scalars(select(Task).where(Task.status.in_(["not_started", "in_progress"]), Task.is_deleted.is_(False),
                                         Task.due_at <= now)).all()
    for t in late:
        key = f"task-late:{t.id}:{t.due_at.isoformat()}"
        if notify(db, t.assignee_id, "task_overdue", f"Overdue: “{t.title}”",
                  f"The deadline was {_fmt_due(t.due_at, t.assignee.timezone)}. Please update your progress or ask "
                  "for more time.", task=t, dedupe_key=key):
            stats["overdue"] += 1
        notify(db, t.assigner_id, "task_overdue", f"Overdue: “{t.title}” ({t.assignee.full_name})",
               f"Deadline was {_fmt_due(t.due_at, t.assigner.timezone)} · {t.progress}% done.", task=t,
               dedupe_key=key + ":owner")
    db.commit()
    return stats


# ---------------------------------------------------------------- overview (management home)
def overview(db: Session, p: Principal, scope: str = "mine") -> dict:
    """scope 'mine' = tasks I assigned; 'all' = every task (top management / task admin)."""
    now = utcnow()
    base = [Task.is_deleted.is_(False)]
    if scope == "all" and sees_all(p):
        pass
    else:
        base.append(Task.assigner_id == p.id)
    open_q = and_(*base, Task.status.in_(OPEN_TASK_STATUSES))

    def n(*w):
        return db.scalar(select(func.count()).select_from(Task).where(*base, *w)) or 0

    month_ago = now - timedelta(days=30)
    done_30 = db.execute(select(Task.completed_at, Task.due_at).where(*base, Task.status == "completed",
                                                                       Task.completed_at >= month_ago)).all()
    on_time = sum(1 for c, d in done_30 if c <= d)
    tiles = {
        "open": n(Task.status.in_(OPEN_TASK_STATUSES)),
        "overdue": n(Task.status.in_(["not_started", "in_progress"]), Task.due_at < now),
        "due_this_week": n(Task.status.in_(["not_started", "in_progress"]), Task.due_at >= now,
                           Task.due_at < now + timedelta(days=7)),
        "waiting_approval": n(Task.status == "waiting_approval"),
        "completed_30": len(done_30),
        "on_time_percent": round(on_time * 100 / len(done_30)) if done_30 else None,
    }
    open_tasks = db.scalars(select(Task).where(open_q).order_by(Task.due_at)).all()
    attention = []
    for t in open_tasks:
        if t.status == "waiting_approval":
            attention.append(("approval", t, "Waiting for your approval"))
        elif t.requested_due_at:
            attention.append(("extension", t, "Asks for more time"))
        elif t.due_at < now:
            attention.append(("overdue", t, "Overdue"))
        elif t.last_activity_at < now - timedelta(days=QUIET_DAYS):
            attention.append(("quiet", t, f"No update for {(now - t.last_activity_at).days} days"))
    order = {"approval": 0, "extension": 1, "overdue": 2, "quiet": 3}
    attention.sort(key=lambda x: (order[x[0]], x[1].due_at))

    team: dict[int, dict] = {}
    for t in open_tasks:
        r = team.setdefault(t.assignee_id, {"user": _person(t.assignee), "open": 0, "overdue": 0, "progress_sum": 0,
                                            "waiting_approval": 0})
        r["open"] += 1
        r["progress_sum"] += t.progress
        r["overdue"] += int(t.status != "waiting_approval" and t.due_at < now)
        r["waiting_approval"] += int(t.status == "waiting_approval")
    for r in team.values():
        r["avg_progress"] = round(r.pop("progress_sum") / r["open"]) if r["open"] else 0
    team_rows = sorted(team.values(), key=lambda r: (-r["overdue"], -r["open"], r["user"]["name"]))

    scoped_ids = select(Task.id).where(*base)
    events = db.scalars(select(TaskEvent).where(TaskEvent.task_id.in_(scoped_ids), TaskEvent.author_id != p.id)
                        .order_by(TaskEvent.id.desc()).limit(15)).all()
    upcoming = [t for t in open_tasks if t.status != "waiting_approval" and now <= t.due_at < now + timedelta(days=7)]
    return {
        "scope": "all" if (scope == "all" and sees_all(p)) else "mine",
        "can_see_all": sees_all(p), "tiles": tiles,
        "attention": [{"kind": k, "label": lbl, "task": task_brief(t, now)} for k, t, lbl in attention[:12]],
        "team": team_rows,
        "feed": [{"task": task_brief(e.task, now), **event_out(e)} for e in events],
        "upcoming": [task_brief(t, now) for t in upcoming[:10]],
    }


# ---------------------------------------------------------------- output
def _person(u: User | None) -> dict | None:
    if u is None:
        return None
    return {"id": u.id, "name": u.full_name, "employee_code": u.employee_code,
            "department": u.department.name if u.department else None}


def task_brief(t: Task, now: datetime | None = None) -> dict:
    now = now or utcnow()
    return {"number": t.number, "title": t.title, "status": t.status, "status_name": STATUS_NAME[t.status],
            "priority": t.priority, "progress": t.progress, "due_at": t.due_at, "category": t.category,
            "overdue": t.status in ("not_started", "in_progress") and t.due_at < now,
            "assignee": _person(t.assignee), "assigner": _person(t.assigner), "updated_at": t.updated_at,
            "last_activity_at": t.last_activity_at, "has_extension_request": t.requested_due_at is not None}


def event_out(e: TaskEvent) -> dict:
    return {"id": e.id, "kind": e.kind, "body": e.body, "progress": e.progress, "old_value": e.old_value,
            "new_value": e.new_value, "created_at": e.created_at, "author": _person(e.author)}


def task_detail(p: Principal, t: Task) -> dict:
    now = utcnow()
    mine = t.assignee_id == p.id
    manage = can_manage(p, t)
    return {
        **task_brief(t, now), "description": t.description, "requires_approval": t.requires_approval,
        "created_at": t.created_at, "started_at": t.started_at, "submitted_at": t.submitted_at,
        "completed_at": t.completed_at, "cancelled_at": t.cancelled_at, "rating": t.rating,
        "requested_due_at": t.requested_due_at, "request_reason": t.request_reason,
        "events": [event_out(e) for e in t.events],
        "can": {
            "manage": manage, "is_assignee": mine,
            "start": mine and t.status == "not_started",
            "update": mine and t.status in ("not_started", "in_progress"),
            "submit": mine and t.status in ("not_started", "in_progress"),
            "request_extension": mine and t.is_open and not t.requested_due_at,
            "comment": (mine or manage) and t.is_open,
            "edit": manage and t.is_open,
            "approve": manage and t.status == "waiting_approval",
            "send_back": manage and t.status in ("waiting_approval", "completed"),
            "cancel": manage and t.is_open,
            "decide_extension": manage and bool(t.requested_due_at),
        },
    }
