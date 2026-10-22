import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require
from app.core.database import get_db
from app.core.errors import BusinessRuleError, Forbidden, NotFound
from app.models import (
    Priority, SatisfactionRating, SLATracking, Ticket, TicketAttachment, TicketComment, TicketHistory,
    TicketStatus,
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

router = APIRouter(prefix="/tickets", tags=["Tickets"])

SORTS = {
    "created_desc": Ticket.created_at.desc(), "created_asc": Ticket.created_at.asc(),
    "updated_desc": Ticket.updated_at.desc(), "priority": Priority.rank.asc(),
    "due": SLATracking.resolution_due_at.asc(),
}


# ------------------------------------------------------------------ serialisers
def _list_item(t: Ticket, now: datetime) -> TicketListItem:
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
        number=t.number, version=t.version, assignee_id=t.assignee_id, subject=t.subject, ticket_type=t.ticket_type,
        status=CodeRef(code=t.status.code, name=t.status.name),
        priority=CodeRef(code=t.priority.code, name=t.priority.name), category=t.category.name,
        requester=t.requester.full_name, department=t.department.name if t.department else None,
        assignee=t.assignee.full_name if t.assignee else None,
        support_group=t.support_group.name if t.support_group else None,
        created_at=t.created_at, updated_at=t.updated_at, sla_state=sla_state,
        resolution_due_at=t.sla.resolution_due_at if t.sla else None,
    )


def _detail(db: Session, p: Principal, t: Ticket) -> TicketDetail:
    rating = db.scalar(select(SatisfactionRating).where(SatisfactionRating.ticket_id == t.id))
    staff = can_work_ticket(p, t)
    snap = sla_snapshot(db, t)
    return TicketDetail(
        number=t.number, version=t.version, subject=t.subject, description=t.description,
        ticket_type=t.ticket_type, status=CodeRef(code=t.status.code, name=t.status.name),
        priority=CodeRef(code=t.priority.code, name=t.priority.name), impact=t.impact, urgency=t.urgency,
        category=Ref(id=t.category.id, name=t.category.name),
        subcategory=Ref(id=t.subcategory.id, name=t.subcategory.name) if t.subcategory else None,
        requester=UserRef(id=t.requester.id, full_name=t.requester.full_name, email=t.requester.email),
        requester_phone=t.requester.phone if (staff or is_requester(p, t)) else None,
        department=Ref(id=t.department.id, name=t.department.name) if t.department else None,
        location=Ref(id=t.location.id, name=t.location.name) if t.location else None,
        support_group=Ref(id=t.support_group.id, name=t.support_group.name) if t.support_group else None,
        assignee=UserRef(id=t.assignee.id, full_name=t.assignee.full_name, email=t.assignee.email)
        if t.assignee else None,
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
        allowed_transitions=[CodeRef(code=s.code, name=s.name) for s in svc.allowed_transitions(db, p, t)],
    )


# ------------------------------------------------------------------ list / search
def _filtered(db: Session, p: Principal, *, q, status, priority, category_id, group_id, assignee, scope,
              sla, date_from, date_to, tz):
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
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(Ticket.number.ilike(like), Ticket.subject.ilike(like)))
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
) -> ListFilters:
    return dict(q=q, status=status, priority=priority, category_id=category_id, group_id=group_id,
                assignee=assignee, scope=scope, sla=sla, date_from=date_from, date_to=date_to)


@router.get("", response_model=Page[TicketListItem])
def list_tickets(f: ListFilters = Depends(list_filters), page: int = Query(1, ge=1, le=10000),
                 page_size: int = Query(25, ge=1, le=100), sort: str = "updated_desc",
                 p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    stmt = _filtered(db, p, tz=p.user.timezone, **f)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = SORTS.get(sort, SORTS["updated_desc"])
    rows = db.scalars(stmt.order_by(order, Ticket.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    now = datetime.now(timezone.utc)
    return Page(items=[_list_item(t, now) for t in rows], total=total, page=page, page_size=page_size)


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
    w.writerow(["Ticket", "Subject", "Type", "Status", "Priority", "Category", "Requester", "Department",
                "Support group", "Assignee", f"Created ({p.user.timezone})", "Resolved", "SLA breached"])
    count = 0
    for t in db.scalars(stmt).all():
        count += 1
        w.writerow([_csv_safe(x) for x in [
            t.number, t.subject, t.ticket_type, t.status.name, t.priority.code, t.category.name,
            t.requester.full_name, t.department.name if t.department else "",
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
    return _detail(db, p, get_visible_ticket(db, p, number))


def _sees_internal(p: Principal, t: Ticket) -> bool:
    return can_work_ticket(p, t) or p.can("ticket.view_internal")


@router.get("/{number}/comments", response_model=list[CommentOut])
def list_comments(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = get_visible_ticket(db, p, number)
    stmt = select(TicketComment).where(TicketComment.ticket_id == t.id)
    if not _sees_internal(p, t):
        stmt = stmt.where(TicketComment.is_internal.is_(False))
    return db.scalars(stmt.order_by(TicketComment.created_at)).all()


@router.get("/{number}/history", response_model=list[HistoryOut])
def list_history(number: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    t = get_visible_ticket(db, p, number)
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
    t = get_visible_ticket(db, p, number)
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
    a = TicketAttachment(ticket_id=t.id, uploaded_by=p.id, is_internal=is_internal, **meta)
    db.add(a)
    svc.add_history(db, t, "attachment", None, meta["original_name"], p.id, internal=is_internal)
    audit_p(db, p, "ticket.attachment_upload", entity_type="ticket", entity_id=t.number,
            detail={"name": meta["original_name"], "size": meta["size_bytes"], "sha256": meta["sha256"]})
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
    path = path_for(a.stored_name)
    if not path.exists():
        raise NotFound("Attachment file is missing from storage.")
    audit_p(db, p, "ticket.attachment_download", entity_type="ticket", entity_id=t.number,
            detail={"attachment_id": a.id})
    db.commit()
    return FileResponse(path, media_type=a.content_type, filename=a.original_name,
                        content_disposition_type="attachment",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
