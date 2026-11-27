"""Task management rules.

Who can do what
* Management (task.assign) creates tasks for one or more people and manages the tasks they assigned.
* Nobody — not IT administrators, not top management — can see a task they are not on. There is no
  "whole company" view: a task exists only for the person who assigned it and the people it is assigned to.
* PRIVACY: the description and every message are visible only to the participants — the person who assigned the
  task and the people it is assigned to. This is enforced here, on the server, not just on screen.
* Assignees (any user, employees included) start the task, post progress, ask for more time and submit it.

Flow:  not_started → in_progress → waiting_approval → completed      (cancelled from any open state)
       waiting_approval / completed → in_progress  when the assigner sends it back with feedback.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, exists, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import BusinessRuleError, Conflict, Forbidden, NotFound
from app.models import TicketSequence, User, utcnow
from app.models.task import (OPEN_TASK_STATUSES, TASK_PRIORITIES, Task, TaskAssignee, TaskAttachment,
                             TaskAttachmentBlob, TaskEvent, TaskRead)
from app.services.audit import audit_p
from app.services.notifications import notify

STATUS_NAME = {"not_started": "Not started", "in_progress": "In progress", "waiting_approval": "Waiting for approval",
               "completed": "Completed", "cancelled": "Cancelled"}
PRIORITY_NAME = {"high": "High", "medium": "Medium", "low": "Low"}
QUIET_DAYS = 5          # "no update for N days" shows in Needs your attention
MAX_ASSIGNEES = 25
PRIVATE = "Private — only the people on this task can read it."


# ---------------------------------------------------------------- access
def can_assign(p: Principal) -> bool:
    return p.can("task.assign") or p.can("task.admin")


def sees_all(p: Principal) -> bool:
    """Top management (MD) sees every task in the company, including its messages and files.
    Everyone else — IT administrators included — sees only the tasks they are on."""
    return p.can("task.view_all")


def can_read(p: Principal, t: Task) -> bool:
    """May read the description, messages and files of this task."""
    return is_participant(p, t) or sees_all(p)


def member_clause(uid: int):
    return exists().where(TaskAssignee.task_id == Task.id, TaskAssignee.user_id == uid)


def participant_clause(uid: int):
    return or_(Task.assigner_id == uid, member_clause(uid))


def scope_clause(p: Principal):
    """Tasks this person may see in lists (content may still be private — see is_participant)."""
    return true() if sees_all(p) else participant_clause(p.id)


def is_participant(p: Principal, t: Task) -> bool:
    return p.id in t.participant_ids


def is_member(p: Principal, t: Task) -> bool:
    return p.id in t.member_ids


def can_manage(p: Principal, t: Task) -> bool:
    """Fix the task: deadline, people, priority, cancel — only the person who assigned it."""
    return t.assigner_id == p.id


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
        raise Forbidden("Only the person who assigned this task can do this.")


def _need_owner(p: Principal, t: Task) -> None:
    """Approving / sending back involves reading the work — only the assigner."""
    if t.assigner_id != p.id:
        raise Forbidden("Only the person who assigned this task can review it.")


def _need_member(p: Principal, t: Task) -> None:
    if not is_member(p, t):
        raise Forbidden("Only the people this task is assigned to can do this.")


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
    db.flush()
    if actor_id:   # your own action counts as read
        mark_read(db, actor_id, t.id, ev.id)
    return ev


# Email only for what matters: a new task, a task completed, and the deadline moving (changed, more time asked
# for, more time approved or refused). Everything else (messages, progress, reminders…) is in-app only.
EMAIL_EVENTS = {"task_assigned", "task_submitted", "task_completed", "task_extension"}


def _tell(db: Session, user_ids, actor_id: int, event: str, title: str, body: str | None, t: Task,
          key: str | None = None, email: bool | None = None) -> None:
    """Notify people on the task — never yourself. Emails only for EMAIL_EVENTS (or email=True)."""
    send = (event in EMAIL_EVENTS) if email is None else email
    for uid in ([user_ids] if isinstance(user_ids, int) else user_ids):
        if uid and uid != actor_id:
            notify(db, uid, event, title, body, task=t, dedupe_key=f"{key}:{uid}" if key else None, email=send)


def _members_except(t: Task, uid: int) -> list[int]:
    return [m for m in t.member_ids if m != uid]


def fmt_due(dt: datetime | None, tz: str) -> str:
    if dt is None:
        return "No deadline"
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(tz)).strftime("%d %b %Y, %I:%M %p")


def _people(db: Session, ids: list[int]) -> list[User]:
    ids = list(dict.fromkeys(i for i in ids if i))           # keep order, no duplicates
    if not ids:
        raise BusinessRuleError("Choose at least one person.", details=[{"field": "assignee_ids"}])
    if len(ids) > MAX_ASSIGNEES:
        raise BusinessRuleError(f"A task can have at most {MAX_ASSIGNEES} people.", details=[{"field": "assignee_ids"}])
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)))}
    if len(users) != len(ids):
        raise BusinessRuleError("Choose active people only.", details=[{"field": "assignee_ids"}])
    return [users[i] for i in ids]


def _set_members(db: Session, t: Task, people: list[User]) -> None:
    db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == t.id))
    for i, u in enumerate(people):
        db.add(TaskAssignee(task_id=t.id, user_id=u.id, position=i))
    t.assignee_id = people[0].id
    db.flush()
    db.expire(t, ["members", "assignee"])


def _check_due(due: datetime | None) -> datetime | None:
    if due is None:
        return None
    if due.tzinfo is None:
        raise BusinessRuleError("Deadline must include a time zone.", details=[{"field": "due_at"}])
    if due < utcnow() - timedelta(minutes=5):
        raise BusinessRuleError("The deadline is in the past.", details=[{"field": "due_at"}])
    return due


def _clean(s: str | None) -> str | None:
    s = (s or "").strip()
    return s or None


def _names(people: list[User]) -> str:
    return ", ".join(u.full_name for u in people)


# ---------------------------------------------------------------- read tracking (Comments counter)
def mark_read(db: Session, uid: int, task_id: int, event_id: int | None = None) -> None:
    if event_id is None:
        event_id = db.scalar(select(func.max(TaskEvent.id)).where(TaskEvent.task_id == task_id)) or 0
    r = db.get(TaskRead, (task_id, uid))
    if r is None:
        db.add(TaskRead(task_id=task_id, user_id=uid, last_event_id=event_id))
    elif event_id > r.last_event_id:
        r.last_event_id = event_id
    db.flush()


def unread_counts(db: Session, uid: int, task_ids: list[int] | None = None) -> dict[int, int]:
    """task_id → number of events by other people since this person last looked (participants only)."""
    q = (select(TaskEvent.task_id, func.count())
         .join(Task, Task.id == TaskEvent.task_id)
         .outerjoin(TaskRead, and_(TaskRead.task_id == TaskEvent.task_id, TaskRead.user_id == uid))
         .where(Task.is_deleted.is_(False), participant_clause(uid),
                or_(TaskEvent.author_id.is_(None), TaskEvent.author_id != uid),
                TaskEvent.id > func.coalesce(TaskRead.last_event_id, 0))
         .group_by(TaskEvent.task_id))
    if task_ids is not None:
        if not task_ids:
            return {}
        q = q.where(TaskEvent.task_id.in_(task_ids))
    return dict(db.execute(q).all())


def counters(db: Session, p: Principal) -> dict:
    now = utcnow()
    mine = and_(Task.is_deleted.is_(False), participant_clause(p.id))
    overdue = db.scalar(select(func.count()).select_from(Task).where(
        mine, Task.status.in_(["not_started", "in_progress"]), Task.due_at.isnot(None), Task.due_at < now)) or 0
    today_end = now + timedelta(hours=24)
    due_today = db.scalar(select(func.count()).select_from(Task).where(
        mine, Task.status.in_(["not_started", "in_progress"]), Task.due_at >= now, Task.due_at < today_end)) or 0
    unread = unread_counts(db, p.id)
    return {"overdue": overdue, "due_soon": due_today, "comments": sum(unread.values()), "tasks_with_comments": len(unread)}


def mark_all_read(db: Session, p: Principal) -> int:
    ids = list(unread_counts(db, p.id).keys())
    for tid in ids:
        mark_read(db, p.id, tid)
    db.commit()
    return len(ids)


# ---------------------------------------------------------------- actions
def create_task(db: Session, p: Principal, *, title: str, description: str | None, assignee_ids: list[int],
                due_at: datetime | None, priority: str = "medium", category: str | None = None,
                requires_approval: bool = True) -> Task:
    if not can_assign(p):
        raise Forbidden("Only management can assign tasks.")
    if priority not in TASK_PRIORITIES:
        raise BusinessRuleError("Choose High, Medium or Low priority.", details=[{"field": "priority"}])
    people = _people(db, assignee_ids)
    now = utcnow()
    t = Task(number=next_task_number(db, now.year), title=title.strip(), description=_clean(description),
             category=_clean(category), priority=priority, status="not_started", progress=0, assigner_id=p.id,
             assignee_id=people[0].id, due_at=_check_due(due_at), requires_approval=requires_approval,
             last_activity_at=now, created_at=now, updated_at=now)
    db.add(t)
    db.flush()
    _set_members(db, t, people)
    _event(db, t, "created", p.id, new=_names(people)[:120])
    for u in people:
        _tell(db, u.id, p.id, "task_assigned", f"New task from {p.user.full_name}: {t.title}",
              f"Deadline: {fmt_due(t.due_at, u.timezone)}\nPriority: {PRIORITY_NAME[t.priority]}"
              + (f"\nAlso on this task: {_names([x for x in people if x.id != u.id])}" if len(people) > 1 else ""), t)
    audit_p(db, p, "task.create", entity_type="task", entity_id=t.number,     # no description: it's private
            detail={"assignees": [u.label for u in people], "due_at": t.due_at.isoformat() if t.due_at else None,
                    "priority": priority})
    db.commit()
    return t


def edit_task(db: Session, p: Principal, t: Task, changes: dict) -> Task:
    _need_manage(p, t)
    _need_open(t)
    part = is_participant(p, t)
    if ("description" in changes or "title" in changes) and not part:
        raise Forbidden("Only the person who assigned the task can change its title or details.")
    if "title" in changes and changes["title"] and changes["title"].strip() != t.title:
        _event(db, t, "title", p.id, old=t.title, new=changes["title"].strip())
        t.title = changes["title"].strip()
    if "description" in changes and _clean(changes["description"]) != t.description:
        t.description = _clean(changes["description"])
        _event(db, t, "description", p.id, body=t.description)
        _tell(db, t.member_ids, p.id, "task_update", f"{p.user.full_name} changed the details of “{t.title}”",
              t.description or "(details removed)", t)
    if "category" in changes:
        t.category = _clean(changes["category"])
    if "requires_approval" in changes and changes["requires_approval"] is not None:
        t.requires_approval = bool(changes["requires_approval"])
    if changes.get("priority") and changes["priority"] != t.priority:
        if changes["priority"] not in TASK_PRIORITIES:
            raise BusinessRuleError("Choose High, Medium or Low priority.", details=[{"field": "priority"}])
        _event(db, t, "priority", p.id, old=PRIORITY_NAME[t.priority], new=PRIORITY_NAME[changes["priority"]])
        t.priority = changes["priority"]
    if "due_at" in changes and changes["due_at"] != t.due_at:
        new_due = _check_due(changes["due_at"])
        _event(db, t, "deadline", p.id, body=_clean(changes.get("reason")) if part else None,
               old=t.due_at.isoformat() if t.due_at else "none", new=new_due.isoformat() if new_due else "none")
        t.due_at = new_due
        t.requested_due_at = t.request_reason = None
        for u in t.assignees:
            _tell(db, u.id, p.id, "task_update", f"Deadline changed: {t.title}", f"New deadline: {fmt_due(new_due, u.timezone)}", t,
                  email=True)
    if changes.get("assignee_ids"):
        people = _people(db, changes["assignee_ids"])
        old_ids, new_ids = t.member_ids, [u.id for u in people]
        if old_ids != new_ids:
            added = [u for u in people if u.id not in old_ids]
            removed = [i for i in old_ids if i not in new_ids]
            removed_users = [db.get(User, i) for i in removed]
            _set_members(db, t, people)
            _event(db, t, "reassigned", p.id, body=_clean(changes.get("reason")) if part else None,
                   old=_names(removed_users)[:120] or None, new=_names(added)[:120] or None)
            for u in added:
                _tell(db, u.id, p.id, "task_assigned", f"New task from {t.assigner.full_name}: {t.title}",
                      f"Deadline: {fmt_due(t.due_at, u.timezone)}", t)
            _tell(db, removed, p.id, "task_update", f"You were taken off “{t.title}”",
                  "You no longer need to work on this task.", t)
    t.updated_at = utcnow()
    audit_p(db, p, "task.edit", entity_type="task", entity_id=t.number,
            detail={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in changes.items()
                    if k not in ("description", "reason", "title")})
    db.commit()
    return t


def post_update(db: Session, p: Principal, t: Task, *, body: str | None, progress: int | None) -> Task:
    """Assignees report progress (with or without a note); every participant may write a message."""
    body = _clean(body)
    if not is_participant(p, t):
        raise Forbidden("Only the people on this task can write on it.")
    member = is_member(p, t)
    if progress is not None and not member:
        raise Forbidden("Only the people the task is assigned to report progress.")
    if not body and progress is None:
        raise BusinessRuleError("Write an update or set the progress.")
    _need_open(t)
    others = [i for i in t.participant_ids if i != p.id]
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
        _tell(db, others, p.id, "task_update", f"{p.user.full_name} updated “{t.title}” to {progress}%", body, t)
    else:
        _event(db, t, "comment", p.id, body=body)
        _tell(db, others, p.id, "task_update", f"New message on “{t.title}” from {p.user.full_name}", body, t)
    t.updated_at = utcnow()
    db.commit()
    return t


def start_task(db: Session, p: Principal, t: Task, body: str | None = None) -> Task:
    _need_member(p, t)
    if t.status != "not_started":
        raise BusinessRuleError("This task has already started.")
    t.status, t.started_at = "in_progress", utcnow()
    _event(db, t, "status", p.id, body=_clean(body), old="not_started", new="in_progress")
    _tell(db, [i for i in t.participant_ids if i != p.id], p.id, "task_update",
          f"{p.user.full_name} started working on “{t.title}”", _clean(body), t)
    db.commit()
    return t


def submit_task(db: Session, p: Principal, t: Task, *, body: str | None) -> Task:
    _need_member(p, t)
    if t.status not in ("not_started", "in_progress"):
        raise BusinessRuleError("This task can't be submitted now.")
    now = utcnow()
    t.progress, t.submitted_at = 100, now
    t.started_at = t.started_at or now
    t.requested_due_at = t.request_reason = None
    others = [i for i in t.participant_ids if i != p.id]
    if t.requires_approval:
        old, t.status = t.status, "waiting_approval"
        _event(db, t, "submitted", p.id, body=_clean(body), old=old, new="waiting_approval")
        _tell(db, t.assigner_id, p.id, "task_submitted", f"Please review: {p.user.full_name} completed “{t.title}”",
              _clean(body), t)
        _tell(db, [i for i in others if i != t.assigner_id], p.id, "task_update",
              f"{p.user.full_name} sent “{t.title}” for approval", _clean(body), t)
    else:
        old, t.status, t.completed_at = t.status, "completed", now
        _event(db, t, "completed", p.id, body=_clean(body), old=old, new="completed")
        _tell(db, others, p.id, "task_completed", f"{p.user.full_name} completed “{t.title}”", _clean(body), t)
    db.commit()
    return t


def approve_task(db: Session, p: Principal, t: Task, *, body: str | None, rating: int | None) -> Task:
    _need_owner(p, t)
    if t.status != "waiting_approval":
        raise BusinessRuleError("Only tasks waiting for approval can be approved.")
    if rating is not None and not 1 <= rating <= 5:
        raise BusinessRuleError("Rating must be 1 to 5 stars.")
    t.status, t.completed_at, t.rating = "completed", utcnow(), rating
    _event(db, t, "approved", p.id, body=_clean(body), new=f"{rating}★" if rating else None)
    _tell(db, t.member_ids, p.id, "task_completed", f"Approved: “{t.title}”",
          (f"Rating: {'★' * rating}\n" if rating else "") + (_clean(body) or "Well done — the task is complete."), t)
    audit_p(db, p, "task.approve", entity_type="task", entity_id=t.number, detail={"rating": rating})
    db.commit()
    return t


def send_back(db: Session, p: Principal, t: Task, *, body: str) -> Task:
    """Not good enough yet (or reopen a completed task): back to In progress with the assigner's feedback."""
    _need_owner(p, t)
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
    _tell(db, t.member_ids, p.id, "task_returned", f"Changes needed on “{t.title}”", body, t)
    db.commit()
    return t


def cancel_task(db: Session, p: Principal, t: Task, *, body: str | None) -> Task:
    _need_manage(p, t)
    _need_open(t)
    old = t.status
    t.status, t.cancelled_at = "cancelled", utcnow()
    reason = _clean(body) if is_participant(p, t) else None
    _event(db, t, "cancelled", p.id, body=reason, old=old, new="cancelled")
    _tell(db, [i for i in t.participant_ids if i != p.id], p.id, "task_update", f"Task cancelled: “{t.title}”",
          reason or "You no longer need to work on this task.", t)
    audit_p(db, p, "task.cancel", entity_type="task", entity_id=t.number)
    db.commit()
    return t


def request_extension(db: Session, p: Principal, t: Task, *, due_at: datetime, reason: str) -> Task:
    _need_member(p, t)
    _need_open(t)
    reason = _clean(reason)
    if not reason or len(reason) < 3:
        raise BusinessRuleError("Give a short reason for the extra time.", details=[{"field": "reason"}])
    if t.due_at is None:
        raise BusinessRuleError("This task has no deadline.")
    if due_at <= t.due_at:
        raise BusinessRuleError("Pick a date after the current deadline.", details=[{"field": "due_at"}])
    t.requested_due_at, t.request_reason = due_at, reason[:500]
    _event(db, t, "extension_requested", p.id, body=reason, old=t.due_at.isoformat(), new=due_at.isoformat())
    _tell(db, t.assigner_id, p.id, "task_extension", f"{p.user.full_name} asks for more time on “{t.title}”",
          f"Requested deadline: {fmt_due(due_at, t.assigner.timezone)}\nReason: {reason}", t)
    db.commit()
    return t


def decide_extension(db: Session, p: Principal, t: Task, *, approve: bool, body: str | None) -> Task:
    _need_manage(p, t)
    if not t.requested_due_at:
        raise BusinessRuleError("There is no pending request for more time.")
    old, new = t.due_at, t.requested_due_at
    if approve:
        t.due_at = new
    note = _clean(body) if is_participant(p, t) else None
    _event(db, t, "extension_approved" if approve else "extension_declined", p.id, body=note,
           old=old.isoformat() if old else None, new=new.isoformat())
    t.requested_due_at = t.request_reason = None
    for u in t.assignees:
        _tell(db, u.id, p.id, "task_extension",
              (f"More time approved: “{t.title}”" if approve else f"More time not approved: “{t.title}”"),
              (f"New deadline: {fmt_due(new, u.timezone)}" if approve else f"The deadline stays {fmt_due(old, u.timezone)}.")
              + (f"\n{note}" if note else ""), t)
    db.commit()
    return t


# ---------------------------------------------------------------- reminders (scheduler)
def run_task_reminders(db: Session, now: datetime | None = None) -> dict:
    """Due within 24 h → remind the assignees once. Past the deadline → tell assignees and assigner once."""
    now = now or utcnow()
    stats = {"due_soon": 0, "overdue": 0}
    live = [Task.status.in_(["not_started", "in_progress"]), Task.is_deleted.is_(False), Task.due_at.isnot(None)]
    for t in db.scalars(select(Task).where(*live, Task.due_at > now, Task.due_at <= now + timedelta(hours=24))).all():
        for u in t.assignees:
            if notify(db, u.id, "task_due_soon", f"Due soon: “{t.title}”",
                      f"Deadline: {fmt_due(t.due_at, u.timezone)} — {t.progress}% done so far.", task=t, email=False,
                      dedupe_key=f"task-due:{t.id}:{t.due_at.isoformat()}:{u.id}"):
                stats["due_soon"] += 1
    for t in db.scalars(select(Task).where(*live, Task.due_at <= now)).all():
        key = f"task-late:{t.id}:{t.due_at.isoformat()}"
        for u in t.assignees:
            if notify(db, u.id, "task_overdue", f"Overdue: “{t.title}”",
                      f"The deadline was {fmt_due(t.due_at, u.timezone)}. Please update your progress or ask "
                      "for more time.", task=t, email=False, dedupe_key=f"{key}:{u.id}"):
                stats["overdue"] += 1
        notify(db, t.assigner_id, "task_overdue", f"Overdue: “{t.title}” ({_names(t.assignees)})",
               f"Deadline was {fmt_due(t.due_at, t.assigner.timezone)} · {t.progress}% done.", task=t,
               email=False, dedupe_key=key + ":owner")
    db.commit()
    return stats


# ---------------------------------------------------------------- list / search
def search(db: Session, p: Principal, *, view: str, statuses: list[str] | None, q: str | None,
           assignee_id: int | None, assigner_id: int | None, priorities: list[str] | None, category: str | None,
           due_from: datetime | None, due_to: datetime | None, created_from: datetime | None,
           created_to: datetime | None, overdue: bool, no_deadline: bool, has_request: bool, unread: bool,
           sort: str, page: int, page_size: int, rows_only: bool = False):
    now = utcnow()
    w = [Task.is_deleted.is_(False), scope_clause(p)]
    if view == "to_me":
        w.append(member_clause(p.id))
    elif view == "by_me":
        w.append(Task.assigner_id == p.id)
    elif view == "mine":
        w.append(participant_clause(p.id))
    elif not sees_all(p):
        w.append(participant_clause(p.id))
    if statuses:
        st = set(statuses)
        if "open" in st:
            st |= set(OPEN_TASK_STATUSES)
        w.append(Task.status.in_(st - {"open"}))
    if overdue:
        w += [Task.status.in_(["not_started", "in_progress"]), Task.due_at.isnot(None), Task.due_at < now]
    if no_deadline:
        w.append(Task.due_at.is_(None))
    if has_request:
        w.append(Task.requested_due_at.isnot(None))
    if q:
        like = f"%{q.strip()}%"
        # the description is searched only on tasks you are part of (it's private)
        w.append(or_(Task.title.ilike(like), Task.number.ilike(like), Task.category.ilike(like),
                     and_(scope_clause(p), Task.description.ilike(like)),
                     exists().where(TaskAssignee.task_id == Task.id, TaskAssignee.user_id == User.id,
                                    or_(User.full_name.ilike(like), User.employee_code.ilike(like)))))
    if assignee_id:
        w.append(member_clause(assignee_id))
    if assigner_id:
        w.append(Task.assigner_id == assigner_id)
    if priorities:
        w.append(Task.priority.in_(priorities))
    if category:
        w.append(Task.category.ilike(f"%{category.strip()}%"))
    if due_from:
        w.append(Task.due_at >= due_from)
    if due_to:
        w.append(Task.due_at < due_to)
    if created_from:
        w.append(Task.created_at >= created_from)
    if created_to:
        w.append(Task.created_at < created_to)
    if unread:
        ids = list(unread_counts(db, p.id).keys())
        w.append(Task.id.in_(ids or [-1]))
    nulls_last = Task.due_at.is_(None)
    order = {"due": [nulls_last, Task.due_at, Task.id], "updated": [Task.last_activity_at.desc()],
             "created": [Task.id.desc()],
             "priority": [Task.priority == "low", Task.priority == "medium", nulls_last, Task.due_at]}[sort]
    if rows_only:   # Excel export: every matching task (max 5 000)
        from sqlalchemy.orm import selectinload
        return db.scalars(select(Task).where(*w).order_by(*order).limit(5000)
                          .options(selectinload(Task.events))).unique().all()
    total = db.scalar(select(func.count()).select_from(Task).where(*w)) or 0
    rows = db.scalars(select(Task).where(*w).order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    unread_map = unread_counts(db, p.id, [t.id for t in rows])
    return {"view": view, "total": total, "page": page, "page_size": page_size,
            "items": [{**task_brief(t, now), "unread": unread_map.get(t.id, 0), "private": not can_read(p, t)}
                      for t in rows]}


# ---------------------------------------------------------------- overview (management home)
def overview(db: Session, p: Principal, scope: str = "mine") -> dict:
    """scope 'mine': every task I am on (assigned by me or to me). 'all': the whole company (Top management)."""
    now = utcnow()
    company = scope == "all" and sees_all(p)
    base = [Task.is_deleted.is_(False), true() if company else participant_clause(p.id)]
    open_q = and_(*base, Task.status.in_(OPEN_TASK_STATUSES))

    def n(*w):
        return db.scalar(select(func.count()).select_from(Task).where(*base, *w)) or 0

    tiles = {
        "total": n(Task.status != "cancelled"),
        "open": n(Task.status.in_(OPEN_TASK_STATUSES)),
        "pending": n(Task.status == "not_started"),
        "in_progress": n(Task.status == "in_progress"),
        "overdue": n(Task.status.in_(["not_started", "in_progress"]), Task.due_at.isnot(None), Task.due_at < now),
        "completed": n(Task.status == "completed"),
        "due_this_week": n(Task.status.in_(["not_started", "in_progress"]), Task.due_at >= now,
                           Task.due_at < now + timedelta(days=7)),
    }
    open_tasks = db.scalars(select(Task).where(open_q).order_by(Task.due_at.is_(None), Task.due_at)).all()
    attention = []
    for t in open_tasks:
        if t.status == "waiting_approval" and t.assigner_id == p.id:
            attention.append(("approval", t, "Marked complete — please review"))
        elif t.requested_due_at and t.assigner_id == p.id:
            attention.append(("extension", t, "Asks for more time"))
        elif t.is_overdue(now):
            attention.append(("overdue", t, "Overdue"))
        elif t.last_activity_at < now - timedelta(days=QUIET_DAYS):
            attention.append(("quiet", t, f"No update for {(now - t.last_activity_at).days} days"))
    order = {"approval": 0, "extension": 1, "overdue": 2, "quiet": 3}
    far = datetime.max.replace(tzinfo=now.tzinfo)
    attention.sort(key=lambda x: (order[x[0]], x[1].due_at or far))

    team: dict[int, dict] = {}
    for t in open_tasks:
        if t.assigner_id != p.id:          # team = people I gave work to
            continue
        for u in t.assignees:
            r = team.setdefault(u.id, {"user": person(u), "open": 0, "overdue": 0, "progress_sum": 0})
            r["open"] += 1
            r["progress_sum"] += t.progress
            r["overdue"] += int(t.is_overdue(now))
    for r in team.values():
        r["avg_progress"] = round(r.pop("progress_sum") / r["open"]) if r["open"] else 0
    team_rows = sorted(team.values(), key=lambda r: (-r["overdue"], -r["open"], r["user"]["name"]))

    scoped_ids = select(Task.id).where(*base)
    events = db.scalars(select(TaskEvent).where(TaskEvent.task_id.in_(scoped_ids), TaskEvent.author_id != p.id)
                        .order_by(TaskEvent.id.desc()).limit(15)).all()
    upcoming = [t for t in open_tasks if t.status != "waiting_approval" and t.due_at and now <= t.due_at < now + timedelta(days=7)]
    return {
        "scope": "all" if company else "mine", "can_see_all": sees_all(p), "tiles": tiles,
        "attention": [{"kind": k, "label": lbl, "task": task_brief(t, now)} for k, t, lbl in attention[:12]],
        "team": team_rows,
        "feed": [{"task": task_brief(e.task, now), **event_out(e, can_read(p, e.task))} for e in events],
        "upcoming": [task_brief(t, now) for t in upcoming[:10]],
    }


# ---------------------------------------------------------------- performance & analytics
def analytics(db: Session, p: Principal, scope: str = "me", days: int = 90) -> dict:
    """scope 'me' = my own performance; 'team' = tasks I assigned; 'all' = whole company (top management)."""
    now = utcnow()
    since = now - timedelta(days=days)
    base = [Task.is_deleted.is_(False), Task.created_at >= since]
    if scope == "all" and sees_all(p):
        pass
    elif scope == "team" and can_assign(p):
        base.append(Task.assigner_id == p.id)
    else:
        scope = "me"
        base.append(member_clause(p.id))
    tasks = db.scalars(select(Task).where(*base)).all()
    people: dict[int, dict] = {}
    for t in tasks:
        for u in t.assignees:
            if scope == "me" and u.id != p.id:
                continue
            r = people.setdefault(u.id, {"user": person(u), "assigned": 0, "completed": 0, "on_time": 0, "overdue": 0,
                                         "open": 0, "ratings": [], "days": []})
            r["assigned"] += 1
            if t.status == "completed":
                r["completed"] += 1
                r["on_time"] += int(t.due_at is None or t.completed_at <= t.due_at)
                r["days"].append((t.completed_at - t.created_at).total_seconds() / 86400)
                if t.rating:
                    r["ratings"].append(t.rating)
            elif t.is_open:
                r["open"] += 1
                r["overdue"] += int(t.is_overdue(now))
    rows = []
    for r in people.values():
        ratings, d = r.pop("ratings"), r.pop("days")
        finished = r["completed"] + r["overdue"]
        r["efficiency"] = round(r["on_time"] * 100 / finished) if finished else None   # like Bitrix "Performance"
        r["avg_rating"] = round(sum(ratings) / len(ratings), 1) if ratings else None
        r["avg_days"] = round(sum(d) / len(d), 1) if d else None
        rows.append(r)
    rows.sort(key=lambda r: (-(r["efficiency"] or -1), r["user"]["name"]))

    def bucket(key):
        out: dict = {}
        for t in tasks:
            k = key(t)
            out[k] = out.get(k, 0) + 1
        return out
    weeks = []
    for i in range(7, -1, -1):
        start = (now - timedelta(days=now.weekday() + 7 * i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        weeks.append({"week": start.date().isoformat(),
                      "created": sum(1 for t in tasks if start <= t.created_at < end),
                      "completed": sum(1 for t in tasks if t.completed_at and start <= t.completed_at < end)})
    total_done = sum(r["completed"] for r in rows)
    total_late = sum(r["overdue"] for r in rows)
    total_on_time = sum(r["on_time"] for r in rows)
    return {"scope": scope, "days": days, "can_team": can_assign(p), "can_all": sees_all(p),
            "efficiency": round(total_on_time * 100 / (total_done + total_late)) if (total_done + total_late) else None,
            "totals": {"tasks": len(tasks), "completed": sum(1 for t in tasks if t.status == "completed"),
                       "open": sum(1 for t in tasks if t.is_open), "overdue": sum(1 for t in tasks if t.is_overdue(now)),
                       "cancelled": sum(1 for t in tasks if t.status == "cancelled")},
            "by_status": bucket(lambda t: t.status), "by_priority": bucket(lambda t: t.priority),
            "by_category": dict(sorted(bucket(lambda t: t.category or "Uncategorised").items(), key=lambda x: -x[1])[:10]),
            "weeks": weeks, "people": rows}


# ---------------------------------------------------------------- attachments
def attachments_of(db: Session, task_ids: list[int]) -> dict[int, list[TaskAttachment]]:
    out: dict[int, list[TaskAttachment]] = {}
    for i in range(0, len(task_ids), 900):
        for a in db.scalars(select(TaskAttachment).where(TaskAttachment.task_id.in_(task_ids[i:i + 900]))
                            .order_by(TaskAttachment.created_at, TaskAttachment.id)):
            out.setdefault(a.task_id, []).append(a)
    return out


def can_attach(p: Principal, t: Task) -> bool:
    return is_participant(p, t) and t.status != "cancelled"


def add_attachment(db: Session, p: Principal, t: Task, meta: dict, data: bytes | None) -> TaskAttachment:
    """Store the file, put a 'file' entry in the conversation, tell the others in-app (no email)."""
    if not can_attach(p, t):
        raise Forbidden("Only the people on this task can add files." if t.status != "cancelled"
                        else "Files can't be added to a cancelled task.")
    ev = _event(db, t, "file", p.id, new=meta["original_name"])
    a = TaskAttachment(task_id=t.id, event_id=ev.id, uploaded_by=p.id, **meta)
    db.add(a)
    db.flush()
    if data is not None:
        db.add(TaskAttachmentBlob(attachment_id=a.id, data=data))
    _tell(db, [i for i in t.participant_ids if i != p.id], p.id, "task_update",
          f"{p.user.full_name} added a file to “{t.title}”", f"File: {meta['original_name']}", t)
    return a


def remove_attachment(db: Session, p: Principal, t: Task, a: TaskAttachment) -> str:
    """The person who added the file, or the person who assigned the task, can remove it."""
    if not is_participant(p, t) or (a.uploaded_by != p.id and t.assigner_id != p.id):
        raise Forbidden("Only the person who added this file (or who assigned the task) can remove it.")
    stored, name = a.stored_name, a.original_name
    blob = db.get(TaskAttachmentBlob, a.id)
    if blob is not None:
        db.delete(blob)
    db.delete(a)
    _event(db, t, "file_removed", p.id, new=name)
    return stored


def attachment_out(a: TaskAttachment) -> dict:
    u = a.uploader
    return {"id": a.id, "event_id": a.event_id, "original_name": a.original_name, "content_type": a.content_type,
            "size_bytes": a.size_bytes, "created_at": a.created_at, "is_internal": False,
            "uploader": {"id": u.id, "full_name": u.full_name, "employee_code": u.employee_code} if u else None}


# ---------------------------------------------------------------- output
def person(u: User | None) -> dict | None:
    if u is None:
        return None
    return {"id": u.id, "name": u.full_name, "employee_code": u.employee_code,
            "department": u.department.name if u.department else None}


def task_brief(t: Task, now: datetime | None = None) -> dict:
    now = now or utcnow()
    people = t.assignees
    return {"number": t.number, "title": t.title, "status": t.status, "status_name": STATUS_NAME[t.status],
            "priority": t.priority, "progress": t.progress, "due_at": t.due_at, "category": t.category,
            "overdue": t.is_overdue(now), "assignee": person(people[0]), "assignees": [person(u) for u in people],
            "assigner": person(t.assigner), "created_at": t.created_at, "started_at": t.started_at,
            "completed_at": t.completed_at, "updated_at": t.updated_at,
            "last_activity_at": t.last_activity_at, "has_extension_request": t.requested_due_at is not None}


def event_out(e: TaskEvent, can_read: bool = True) -> dict:
    private = not can_read and e.body is not None
    return {"id": e.id, "kind": e.kind, "body": e.body if can_read else None, "private": private,
            "progress": e.progress, "old_value": e.old_value if can_read or e.kind != "title" else None,
            "new_value": e.new_value if can_read or e.kind != "title" else None,
            "created_at": e.created_at, "author": person(e.author)}


def task_detail(db: Session, p: Principal, t: Task) -> dict:
    now = utcnow()
    member = is_member(p, t)
    part = is_participant(p, t)
    read = can_read(p, t)          # participants, or Top management (read-only)
    manage = can_manage(p, t)
    owner = t.assigner_id == p.id
    if part:
        mark_read(db, p.id, t.id)
        db.commit()
    return {
        **task_brief(t, now), "description": t.description if read else None,
        "private": not read, "private_note": None if read else PRIVATE, "viewing_as_md": read and not part,
        "requires_approval": t.requires_approval, "submitted_at": t.submitted_at, "cancelled_at": t.cancelled_at,
        "rating": t.rating, "requested_due_at": t.requested_due_at,
        "request_reason": t.request_reason if read else None,
        "events": [event_out(e, read) for e in t.events],
        "attachments": [attachment_out(a) for a in attachments_of(db, [t.id]).get(t.id, [])] if read else [],
        "can": {
            "manage": manage, "is_assignee": member, "is_participant": part, "is_owner": owner,
            "start": member and t.status == "not_started",
            "update": member and t.status in ("not_started", "in_progress"),
            "submit": member and t.status in ("not_started", "in_progress"),
            "request_extension": member and t.is_open and not t.requested_due_at and t.due_at is not None,
            "comment": part and t.is_open,
            "attach": can_attach(p, t),
            "edit": manage and t.is_open, "edit_text": part and manage and t.is_open,
            "approve": owner and t.status == "waiting_approval",
            "send_back": owner and t.status in ("waiting_approval", "completed"),
            "cancel": manage and t.is_open,
            "decide_extension": manage and bool(t.requested_due_at),
        },
    }
