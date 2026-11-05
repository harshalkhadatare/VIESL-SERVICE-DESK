import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require
from app.core.database import get_db
from app.core.errors import BusinessRuleError, Forbidden, NotFound
from app.models import (
    Priority, SatisfactionRating, SLATracking, Ticket, TicketAttachment, TicketAttachmentBlob, TicketComment,
    Department, TicketHistory, TicketStatus, TicketUserFlag, User,
)
from app.schemas.common import CodeRef, Page, Ref, UserRef
from app.schemas.tickets import (
    AssignIn, AttachmentOut, CommentIn, CommentOut, DuplicateCandidate, DuplicateCheckIn, HistoryOut, LinkIn,
    PriorityChangeIn, RatingIn, RatingOut, StatusChangeIn, TicketCreate, TicketDetail, TicketListItem, VersionIn,
)
from app.services import tickets as svc
from app.services.access import (
    can_assign_ticket, can_work_ticket, get_visible_ticket, is_requester, ticket_visibility_clause,
)
from app.services.attachments import MAX_FILES_PER_TICKET, path_for, store_upload
from app.services.audit import audit_p
from app.services.sla import sla_snapshot
from app.services.ticket_delete import can_delete_ticket, delete_ticket
from app.services.ticket_flags import flags_for, is_new, mark_viewed, set_star

router = APIRouter(prefix="/tickets", tags=["Tickets"])

SORTS = {
    "created_desc": Ticket.created_at.desc(), "created_asc": Ticket.created_at.asc(),
    "updated_desc": Ticket.updated_at.desc(), "priority": Priority.rank.asc(),
    "due": SLATracking.resolution_due_at.asc(),
}


# ------------------------------------------------------------------ serialisers
def _list_item(t: Ticket, now: datetime, flag=None, p: Principal | None = None) -> TicketListItem:
    sla_state = None
    if t.sla:
        if t.status_code in ("RESOLVED", "CLOSED", "CANCELLED"):
            sla_state = "breached" if t.sla.resolution_breached else "met"
        elif t.sla.paused_at:
            sla_state = "paused"
        elif t.sla.resolution_breached or t.sla.resolution_due_at < now:
            sla_state = "breached"
        else:
            sla_state = "on_track"
    return TicketListItem(
        number=t.number, version=t.version, assignee_id=t.assignee_id, desk=t.desk, subject=t.subject, ticket_type=t.ticket_type,
        status=CodeRef(code=t.status.code, name=t.status.name),
        priority=CodeRef(code=t.priority.code, name=t.priority.name), category=t.category.name,
        requester=t.requester.full_name, requester_code=t.requester.employee_code, requester_id=t.requester_id,
        starred=bool(flag and flag.starred), is_new=bool(p and is_new(p, t, flag, now)), department=t.department.name if t.department else None,
        assignee=t.assignee.full_name if t.assignee else None,
        assignee_code=t.assignee.employee_code if t.assignee else None,
        support_group=t.support_group.name if t.support_group else None,
        created_at=t.created_at, updated_at=t.updated_at, sla_state=sla_state,
        resolution_due_at=t.sla.resolution_due_at if t.sla else None,
    )


def _detail(db: Session, p: Principal, t: Ticket) -> TicketDetail:
    rating = db.scalar(select(SatisfactionRating).where(SatisfactionRating.ticket_id == t.id))
    staff = can_work_ticket(p, t)
    snap = sla_snapshot(db, t)
    return TicketDetail(
        number=t.number, version=t.version, desk=t.desk, subject=t.subject, description=t.description,
        ticket_type=t.ticket_type, status=CodeRef(code=t.status.code, name=t.status.name),
        priority=CodeRef(code=t.priority.code, name=t.priority.name), impact=t.impact, urgency=t.urgency,
        category=Ref(id=t.category.id, name=t.category.name),
        subcategory=Ref(id=t.subcategory.id, name=t.subcategory.name) if t.subcategory else None,
        requester=UserRef.model_validate(t.requester),
        requester_phone=t.requester.phone if (staff or is_requester(p, t)) else None,
        department=Ref(id=t.department.id, name=t.department.name) if t.department else None,
        location=Ref(id=t.location.id, name=t.location.name) if t.location else None,
        support_group=Ref(id=t.support_group.id, name=t.support_group.name) if t.support_group else None,
        assignee=UserRef.model_validate(t.assignee) if t.assignee else None,
        contact_method=t.contact_method,
        root_cause=t.root_cause if (staff or p.can("ticket.view_all")) else None,  # internal field
        resolution_notes=t.resolution_notes, created_at=t.created_at, updated_at=t.updated_at,
        first_response_at=t.first_response_at, assigned_at=t.assigned_at, resolved_at=t.resolved_at,
        closed_at=t.closed_at, closure_reason=t.closure_reason, reopen_count=t.reopen_count, is_demo=t.is_demo,
        erp=t.erp, sla=snap, rating=RatingOut.model_validate(rating) if rating else None,
        relations=svc.get_relations(db, p, t),
        can_work=staff, can_assign=can_assign_ticket(p, t),
        can_set_priority=p.can("ticket.set_priority") and (can_assign_ticket(p, t) or p.can("ticket.manage_all")),
        can_comment_internal=p.can("ticket.comment_internal") and (staff or p.can("ticket.manage_all")),
        can_rate=is_requester(p, t) and t.status_code in ("RESOLVED", "CLOSED") and rating is None,
        can_delete=can_delete_ticket(p, t),
        allowed_transitions=[CodeRef(code=s.code, name=s.name) for s in svc.allowed_transitions(db, p, t)],
    )


# ------------------------------------------------------------------ list / search
def _filtered(db: Session, p: Principal, *, q, status, priority, category_id, group_id, assignee, scope,
              sla, date_from, date_to, tz, requester=None, starred=False, department_id=None, desk=None):
    stmt = (select(Ticket).join(Priority, Priority.id == Ticket.priority_id)
            .outerjoin(SLATracking, SLATracking.ticket_id == Ticket.id)
            .where(ticket_visibility_clause(p)))
    if scope == "mine":
        stmt = stmt.where(Ticket.requester_id == p.id)
    elif scope == "assigned":
        stmt = stmt.where(Ticket.assignee_id == p.id)
    elif scope == "queue":
        stmt = stmt.where(Ticket.support_group_id.in_(p.group_ids or {-1}))
    if q:
        # one box finds tickets by number, subject, or the employee who raised it (ID, name, email),
        # the IT administrator it is assigned to, or the department
        term = q.strip()[:100]
        like = f"%{term}%"
        people = select(User.id).where(or_(User.full_name.ilike(like), User.employee_code.ilike(like),
                                           User.email.ilike(like)))
        depts = select(Department.id).where(Department.name.ilike(like))
        stmt = stmt.where(or_(Ticket.number.ilike(like), Ticket.subject.ilike(like),
                              Ticket.requester_id.in_(people), Ticket.assignee_id.in_(people),
                              Ticket.department_id.in_(depts)))
    if requester:
        r = requester.strip()
        # employee ID (code) first; "id:<n>" selects by internal user id
        if r.lower().startswith("id:") and r[3:].isdigit():
            rid = int(r[3:])
        else:
            rid = db.scalar(select(User.id).where(func.upper(User.employee_code) == r.upper())) or -1
        stmt = stmt.where(Ticket.requester_id == rid)
    if department_id:
        stmt = stmt.where(Ticket.department_id == department_id)
    if desk in ("it", "erp"):   # "Both" tickets belong to both departments
        stmt = stmt.where(Ticket.desk.in_([desk, "both"]))
    if starred:
        stmt = stmt.where(Ticket.id.in_(select(TicketUserFlag.ticket_id).where(
            TicketUserFlag.user_id == p.id, TicketUserFlag.starred.is_(True))))
    if status == "open":
        stmt = stmt.where(Ticket.status_code.in_(select(TicketStatus.code).where(TicketStatus.is_open.is_(True))))
    elif status:
        stmt = stmt.where(Ticket.status_code.in_([s.strip().upper() for s in status.split(",")][:15]))
    if priority:
        stmt = stmt.where(Priority.code.in_([s.strip().upper() for s in priority.split(",")][:4]))
    if category_id:
        stmt = stmt.where(Ticket.category_id == category_id)
    if group_id:
        stmt = stmt.where(Ticket.support_group_id == group_id)
    if assignee == "me":
        stmt = stmt.where(Ticket.assignee_id == p.id)
    elif assignee == "unassigned":
        stmt = stmt.where(Ticket.assignee_id.is_(None))
    elif assignee and assignee.isdigit():
        stmt = stmt.where(Ticket.assignee_id == int(assignee))
    now = datetime.now(timezone.utc)
    if sla == "breached":
        stmt = stmt.where(or_(SLATracking.resolution_breached.is_(True),
                              (SLATracking.resolution_due_at < now) & SLATracking.paused_at.is_(None)
                              & Ticket.status_code.notin_(["RESOLVED", "CLOSED", "CANCELLED"])))
    elif sla == "at_risk":
        stmt = stmt.where(SLATracking.resolution_breached.is_(False), SLATracking.paused_at.is_(None),
                          SLATracking.resolution_due_at >= now,
                          SLATracking.resolution_due_at < now + timedelta(hours=4),
                          Ticket.status_code.notin_(["RESOLVED", "CLOSED", "CANCELLED"]))
    z = ZoneInfo(tz)
    if date_from:
        stmt = stmt.where(Ticket.created_at >= datetime.combine(date_from, time(0), z).astimezone(timezone.utc))
    if date_to:
        stmt = stmt.where(Ticket.created_at < datetime.combine(date_to + timedelta(days=1), time(0), z)
                          .astimezone(timezone.utc))
    return stmt


ListFilters = dict


def list_filters(
    q: str | None = Query(None, max_length=100), status: str | None = Query(None, max_length=200),
    priority: str | None = Query(None, max_length=20), category_id: int | None = None,
    group_id: int | None = None, assignee: str | None = Query(None, max_length=20),
    scope: Literal["all", "mine", "assigned", "queue"] = "all",
    sla: Literal["breached", "at_risk"] | None = None,
    date_from: date | None = None, date_to: date | None = None,
    requester: str | None = Query(None, max_length=40, description="Employee ID (code) or user id of the requester"),
    starred: bool = False, department_id: int | None = None,
    desk: Literal["it", "erp", "all"] | None = None,
) -> ListFilters:
    return dict(q=q, status=status, priority=priority, category_id=category_id, group_id=group_id,
                assignee=assignee, scope=scope, sla=sla, date_from=date_from, date_to=date_to,
                requester=requester, starred=starred, department_id=department_id, desk=desk)


@router.get("", response_model=Page[TicketListItem])
def list_tickets(f: ListFilters = Depends(list_filters), page: int = Query(1, ge=1, le=10000),
                 page_size: int = Query(25, ge=1, le=100), sort: str = "updated_desc",
                 p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    stmt = _filtered(db, p, tz=p.user.timezone, **f)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = SORTS.get(sort, SORTS["updated_desc"])
    rows = db.scalars(stmt.order_by(order, Ticket.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    now = datetime.now(timezone.utc)
    flags = flags_for(db, p.id, [t.id for t in rows])
    return Page(items=[_list_item(t, now, flags.get(t.id), p) for t in rows], total=total, page=page,
                page_size=page_size)


def _csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection in user-controlled text."""
    s = "" if v is None else str(v)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@router.get("/export.csv")
def export_csv(f: ListFilters = Depends(list_filters), p: Principal = Depends(require("report.export")),
               db: Session = Depends(get_db)):
    stmt = _filtered(db, p, tz=p.user.timezone, **f).order_by(Ticket.created_at.desc()).limit(10000)
    z = ZoneInfo(p.user.timezone)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Ticket", "IT team", "Subject", "Type", "Status", "Priority", "Category", "Requester", "Employee ID", "Department",
                "Support group", "Assignee", f"Created ({p.user.timezone})", "Resolved", "SLA breached"])
    count = 0
    for t in db.scalars(stmt).all():
        count += 1
        w.writerow([_csv_safe(x) for x in [
            t.number, {"it": "IT", "erp": "ERP-IT", "both": "IT + ERP-IT"}.get(t.desk, t.desk), t.subject, t.ticket_type, t.status.name, t.priority.code, t.category.name,
            t.requester.full_name, t.requester.employee_code or "", t.department.name if t.department else "",
            t.support_group.name if t.support_group else "", t.assignee.full_name if t.assignee else "",
            t.created_at.astimezone(z).strftime("%Y-%m-%d %H:%M"),
            t.resolved_at.astimezone(z).strftime("%Y-%m-%d %H:%M") if t.resolved_at else "",
            "Yes" if (t.sla and t.sla.resolution_breached) else "No"]])
    audit_p(db, p, "report.export", entity_type="ticket", detail={"rows": count, "filters": {
        k: v for k, v in f.items() if v}})
    db.commit()
    data = "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 correctly
    fname = f"tickets_{datetime.now(z):%Y%m%d_%H%M}.csv"
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


_FILTER_LABELS = {"desk": "IT team", "q": "Search", "status": "Status", "priority": "Priority", "assignee": "Assignee",
                  "requester": "Employee ID", "sla": "SLA", "date_from": "From", "date_to": "To"}


@router.get("/export.xlsx")
def export_xlsx(f: ListFilters = Depends(list_filters), sort: str = "created_desc",
                p: Principal = Depends(require("report.export")), db: Session = Depends(get_db)):
    """Formatted Excel workbook of the tickets matching the current list filters (max 10 000 rows)."""
    from app.core.config import get_settings
    from app.services.excel_export import DESK_NAME, build_ticket_workbook
    order = SORTS.get(sort, SORTS["created_desc"])
    rows = db.scalars(_filtered(db, p, tz=p.user.timezone, **f).order_by(order, Ticket.id.desc()).limit(10000)).all()
    desk = f.get("desk")
    title = {"it": "IT tickets", "erp": "ERP-IT tickets"}.get(desk, "All tickets")
    shown = []
    for k, label in _FILTER_LABELS.items():
        v = f.get(k)
        if v and not (k == "desk" and v == "all"):
            shown.append(f"{label}: {DESK_NAME.get(v, v) if k == 'desk' else ('open' if v == 'open' else v)}")
    files: dict[int, list[str]] = {}
    ids = [t.id for t in rows]
    for i in range(0, len(ids), 900):    # one query per 900 tickets, not one per ticket
        for tid, name in db.execute(select(TicketAttachment.ticket_id, TicketAttachment.original_name)
                                    .where(TicketAttachment.ticket_id.in_(ids[i:i + 900]))
                                    .order_by(TicketAttachment.created_at)):
            files.setdefault(tid, []).append(name)
    data = build_ticket_workbook(rows, tz=p.user.timezone, company=get_settings().company_name, title=title,
                                 filters_text=", ".join(shown), files=files, base_url=get_settings().app_base_url)
    audit_p(db, p, "report.export", entity_type="ticket", detail={"rows": len(rows), "format": "xlsx", "filters": {
        k: v for k, v in f.items() if v}})
    db.commit()
    z = ZoneInfo(p.user.timezone)
    fname = f"{title.replace(' ', '_')}_{datetime.now(z):%Y%m%d_%H%M}.xlsx"
    return Response(content=data, headers={"Content-Disposition": f'attachment; filename="{fname}"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------------------------------------------------------------------ create
@router.post("/duplicate-check", response_model=list[DuplicateCandidate])
def duplicate_check(data: DuplicateCheckIn, p: Principal = Depends(require("ticket.create")),
                    db: Session = Depends(get_db)):
    return svc.find_duplicates(db, p, data.subject, data.category_id)


@router.post("", response_model=TicketDetail, status_code=201)
def create_ticket(data: TicketCreate, p: Principal = Depends(require("ticket.create")),
                  idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=80),
                  db: Session = Depends(get_db)):
    t = svc.create_ticket(db, p, data, idempotency_key)
    db.commit()
    db.refresh(t)
    return _detail(db, p, t)


# ------------------------------------------------------------------ detail + timeline
@router.get("/{number}", response_model=TicketDetail)
def get_ticket(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = get_visible_ticket(db, p, number)
    flag = mark_viewed(db, p.id, t.id)       # opening a ticket clears its green "New" mark for you
    d = _detail(db, p, t)
    d.starred = flag.starred
    return d


class TicketFull(BaseModel):
    ticket: TicketDetail
    comments: list[CommentOut]
    history: list[HistoryOut]
    attachments: list[AttachmentOut]


@router.get("/{number}/full", response_model=TicketFull)
def get_ticket_full(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Everything the ticket page needs in ONE request (instead of four)."""
    t = get_visible_ticket(db, p, number)
    flag = mark_viewed(db, p.id, t.id)
    d = _detail(db, p, t)
    d.starred = flag.starred
    return TicketFull(ticket=d, comments=_comments(db, p, t), history=_history(db, p, t),
                      attachments=_attachments(db, p, t))


class StarIn(BaseModel):
    starred: bool


@router.put("/{number}/star", tags=["Tickets"])
def star_ticket(number: str, data: StarIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """★ Star / un-star a ticket for yourself (shown in the list and the Starred tab)."""
    t = get_visible_ticket(db, p, number)
    return {"number": t.number, "starred": set_star(db, p.id, t.id, data.starred).starred}


@router.delete("/{number}", status_code=204)
def remove_ticket(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Permanently delete a ticket: the requester (until resolved) or an IT administrator."""
    delete_ticket(db, p, get_visible_ticket(db, p, number, for_update=True))
    return Response(status_code=204)


def _sees_internal(p: Principal, t: Ticket) -> bool:
    return can_work_ticket(p, t) or p.can("ticket.view_internal")


@router.get("/{number}/comments", response_model=list[CommentOut])
def list_comments(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _comments(db, p, get_visible_ticket(db, p, number))


def _comments(db: Session, p: Principal, t: Ticket):
    stmt = select(TicketComment).where(TicketComment.ticket_id == t.id)
    if not _sees_internal(p, t):
        stmt = stmt.where(TicketComment.is_internal.is_(False))
    return db.scalars(stmt.order_by(TicketComment.created_at)).all()


@router.get("/{number}/history", response_model=list[HistoryOut])
def list_history(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _history(db, p, get_visible_ticket(db, p, number))


def _history(db: Session, p: Principal, t: Ticket):
    stmt = select(TicketHistory).where(TicketHistory.ticket_id == t.id)
    if not _sees_internal(p, t):
        stmt = stmt.where(TicketHistory.is_internal.is_(False))
    return db.scalars(stmt.order_by(TicketHistory.created_at, TicketHistory.id)).all()


@router.post("/{number}/comments", response_model=CommentOut, status_code=201)
def add_comment(number: str, data: CommentIn, p: Principal = Depends(get_principal),
                db: Session = Depends(get_db)):
    c = svc.add_comment(db, p, number, data)
    db.commit()
    return c


# ------------------------------------------------------------------ actions
@router.post("/{number}/status", response_model=TicketDetail)
def change_status(number: str, data: StatusChangeIn, p: Principal = Depends(get_principal),
                  db: Session = Depends(get_db)):
    t = svc.change_status(db, p, number, data)
    db.commit()
    return _detail(db, p, t)


@router.post("/{number}/assign", response_model=TicketDetail)
def assign(number: str, data: AssignIn, p: Principal = Depends(require("ticket.assign")),
           db: Session = Depends(get_db)):
    t = svc.assign(db, p, number, data)
    db.commit()
    return _detail(db, p, t)


@router.post("/{number}/accept", response_model=TicketDetail)
def accept(number: str, data: VersionIn, p: Principal = Depends(require("ticket.accept")),
           db: Session = Depends(get_db)):
    t = svc.accept(db, p, number, data.expected_version)
    db.commit()
    return _detail(db, p, t)


@router.post("/{number}/priority", response_model=TicketDetail)
def change_priority(number: str, data: PriorityChangeIn, p: Principal = Depends(require("ticket.set_priority")),
                    db: Session = Depends(get_db)):
    t = svc.change_priority(db, p, number, data)
    db.commit()
    return _detail(db, p, t)


@router.post("/{number}/rating", response_model=RatingOut, status_code=201)
def rate(number: str, data: RatingIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    r = svc.rate(db, p, number, data.rating, data.comment)
    db.commit()
    return r


@router.post("/{number}/links", status_code=204)
def link(number: str, data: LinkIn, p: Principal = Depends(require("ticket.link")), db: Session = Depends(get_db)):
    svc.link(db, p, number, data.target_number, data.relation_type)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ attachments
@router.get("/{number}/attachments", response_model=list[AttachmentOut])
def list_attachments(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _attachments(db, p, get_visible_ticket(db, p, number))


def _attachments(db: Session, p: Principal, t: Ticket):
    stmt = select(TicketAttachment).where(TicketAttachment.ticket_id == t.id)
    if not _sees_internal(p, t):
        stmt = stmt.where(TicketAttachment.is_internal.is_(False))
    return db.scalars(stmt.order_by(TicketAttachment.created_at)).all()


@router.post("/{number}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(number: str, file: UploadFile = File(...), is_internal: bool = Form(False),
                            p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = get_visible_ticket(db, p, number)
    staff = can_work_ticket(p, t)
    if not (staff or is_requester(p, t)):
        raise Forbidden("You cannot add attachments to this ticket.")
    if is_internal and not staff:
        raise Forbidden("Internal attachments are restricted to IT staff.")
    if t.status_code in ("CLOSED", "CANCELLED"):
        raise BusinessRuleError("Attachments cannot be added to closed tickets.")
    n = db.scalar(select(func.count()).select_from(TicketAttachment).where(TicketAttachment.ticket_id == t.id))
    if n >= MAX_FILES_PER_TICKET:
        raise BusinessRuleError(f"A ticket can have at most {MAX_FILES_PER_TICKET} attachments.")
    meta = await store_upload(file)
    data = meta.pop("data", None)
    a = TicketAttachment(ticket_id=t.id, uploaded_by=p.id, is_internal=is_internal, **meta)
    db.add(a)
    if data is not None:
        db.flush()
        db.add(TicketAttachmentBlob(attachment_id=a.id, data=data))
    svc.add_history(db, t, "attachment", None, meta["original_name"], p.id, internal=is_internal)
    audit_p(db, p, "ticket.attachment_upload", entity_type="ticket", entity_id=t.number,
            detail={"name": meta["original_name"], "size": meta["size_bytes"], "sha256": meta["sha256"]})
    if staff and not is_internal and t.requester_id != p.id:   # IT shared a file with the employee
        from app.services.notifications import notify
        notify(db, t.requester_id, "comment_added", f"{p.user.full_name} added a file to {t.number}",
               f"File: {meta['original_name']}", t)
    db.commit()
    db.refresh(a)
    return a


@router.get("/{number}/attachments/{attachment_id}")
def download_attachment(number: str, attachment_id: int, p: Principal = Depends(get_principal),
                        db: Session = Depends(get_db)):
    t = get_visible_ticket(db, p, number)
    a = db.scalar(select(TicketAttachment).where(TicketAttachment.id == attachment_id,
                                                 TicketAttachment.ticket_id == t.id))
    if not a or (a.is_internal and not _sees_internal(p, t)):
        raise NotFound("Attachment not found.")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    path = path_for(a.stored_name)
    blob = None
    if not path.exists():  # stored in the database (serverless hosting)
        blob = db.get(TicketAttachmentBlob, a.id)
        if blob is None:
            raise NotFound("Attachment file is missing from storage.")
    audit_p(db, p, "ticket.attachment_download", entity_type="ticket", entity_id=t.number,
            detail={"attachment_id": a.id})
    db.commit()
    if blob is not None:
        from urllib.parse import quote
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(a.original_name)}"
        return Response(content=blob.data, media_type=a.content_type, headers=headers)
    return FileResponse(path, media_type=a.content_type, filename=a.original_name,
                        content_disposition_type="attachment", headers=headers)
