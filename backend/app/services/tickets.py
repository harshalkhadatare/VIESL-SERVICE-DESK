"""Ticket domain service. All business rules for the lifecycle live here, not in routers or UI."""
import re
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import BusinessRuleError, Conflict, Forbidden, NotFound
from app.models import (
    Category, IdempotencyKey, SatisfactionRating, StatusTransition, Subcategory, SupportGroup, SupportGroupMember,
    Ticket, TicketAssignment, TicketComment, TicketErpDetail, TicketHistory, TicketRelationship, TicketSequence,
    TicketStatus, TicketWatcher, User, utcnow,
)
from app.schemas.tickets import AssignIn, CommentIn, PriorityChangeIn, StatusChangeIn, TicketCreate
from app.services import sla as sla_svc
from app.services.access import can_assign_ticket, can_work_ticket, get_visible_ticket, is_requester
from app.services.audit import audit_p
from app.services.notifications import notify
from app.services.routing import priority_for, route_ticket
from app.services.settings_service import get_int

INITIAL_STATUS = "SUBMITTED"
FINAL_STATUSES = {"CLOSED", "CANCELLED"}
# Staff moving a ticket into these counts as the first response
RESPONSE_STATUSES = {"IN_PROGRESS", "PENDING_EMPLOYEE", "RESOLVED", "PENDING_VENDOR", "PENDING_CHANGE"}


# ------------------------------------------------------------------ helpers
def check_version(t: Ticket, expected: int) -> None:
    if t.version != expected:
        raise Conflict("This ticket was updated by someone else. Reload to see the latest changes.",
                       details=[{"current_version": t.version}])


def add_history(db: Session, t: Ticket, field: str, old, new, actor_id: int | None,
                reason: str | None = None, internal: bool = False) -> None:
    db.add(TicketHistory(ticket_id=t.id, field=field, old_value=None if old is None else str(old)[:500],
                         new_value=None if new is None else str(new)[:500], reason=reason,
                         actor_id=actor_id, is_internal=internal))


def next_ticket_number(db: Session, year: int) -> str:
    for _ in range(3):
        seq = db.scalar(select(TicketSequence).where(TicketSequence.year == year).with_for_update())
        if seq is None:
            try:
                with db.begin_nested():
                    seq = TicketSequence(year=year, last_value=0)
                    db.add(seq)
                    db.flush()
            except IntegrityError:
                continue
        seq.last_value += 1
        db.flush()
        return f"IT-{year}-{seq.last_value:06d}"
    raise Conflict("Could not allocate a ticket number, please retry.")


def _tokens(s: str) -> set[str]:
    stop = {"the", "a", "an", "is", "not", "in", "on", "of", "to", "and", "for", "my", "i", "with", "unable", "issue"}
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in stop}


def find_duplicates(db: Session, p: Principal, subject: str, category_id: int | None, limit: int = 5):
    since = utcnow() - timedelta(days=get_int(db, "duplicate_lookback_days"))
    stmt = select(Ticket).where(Ticket.created_at >= since, Ticket.status_code.notin_(list(FINAL_STATUSES)))
    if not p.can("ticket.view_all") and not p.can("ticket.view_group"):
        stmt = stmt.where(Ticket.requester_id == p.id)  # employees only see their own possible duplicates
    if category_id:
        stmt = stmt.where(Ticket.category_id == category_id)
    want = _tokens(subject)
    if not want:
        return []
    out = []
    for t in db.scalars(stmt.order_by(Ticket.created_at.desc()).limit(300)).all():
        have = _tokens(t.subject)
        if not have:
            continue
        score = len(want & have) / len(want | have)
        if score >= 0.4:
            out.append({"number": t.number, "subject": t.subject, "status": t.status.name,
                        "created_at": t.created_at, "score": round(score, 2)})
    return sorted(out, key=lambda x: -x["score"])[:limit]


def _group_leads(db: Session, group_id: int | None) -> list[int]:
    if not group_id:
        return []
    return list(db.scalars(select(SupportGroupMember.user_id).where(
        SupportGroupMember.group_id == group_id, SupportGroupMember.is_lead.is_(True))).all())


# ------------------------------------------------------------------ create
def create_ticket(db: Session, p: Principal, data: TicketCreate, idempotency_key: str | None = None) -> Ticket:
    if idempotency_key:
        existing = db.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == p.id,
                                                          IdempotencyKey.key == idempotency_key))
        if existing:
            return db.get(Ticket, existing.ticket_id)

    cat = db.get(Category, data.category_id)
    if not cat or not cat.is_active:
        raise BusinessRuleError("Select a valid category.", details=[{"field": "category_id"}])
    if data.subcategory_id:
        sub = db.get(Subcategory, data.subcategory_id)
        if not sub or sub.category_id != cat.id or not sub.is_active:
            raise BusinessRuleError("Subcategory does not belong to the selected category.",
                                    details=[{"field": "subcategory_id"}])
    if data.erp and not cat.uses_erp_fields:
        raise BusinessRuleError("ERP details are only accepted for ERP categories.", details=[{"field": "erp"}])

    now = utcnow()
    prio = priority_for(db, data.impact, data.urgency)
    user = p.user
    t = Ticket(
        number=next_ticket_number(db, now.year), ticket_type=data.ticket_type or cat.default_ticket_type,
        subject=data.subject, description=data.description,
        requester_id=user.id, department_id=user.department_id, location_id=user.location_id,  # never from client
        category_id=cat.id, subcategory_id=data.subcategory_id, impact=data.impact, urgency=data.urgency,
        priority_id=prio.id, status_code=INITIAL_STATUS, contact_method=data.contact_method,
        created_by=user.id, created_at=now, updated_at=now,
    )
    db.add(t)
    db.flush()
    t.category, t.priority = cat, prio

    if data.erp:
        db.add(TicketErpDetail(ticket_id=t.id, **data.erp.model_dump()))
    db.add(TicketWatcher(ticket_id=t.id, user_id=user.id))
    add_history(db, t, "created", None, t.number, user.id)
    sla_svc.start_sla(db, t, now)

    # Routing
    group_id, assignee_id, method = route_ticket(db, t, data.erp.erp_module if data.erp else None)
    if group_id:
        t.support_group_id = group_id
        add_history(db, t, "support_group", None, db.get(SupportGroup, group_id).name, None, "Automatic routing")
    if assignee_id:
        t.assignee_id, t.assigned_at = assignee_id, now
        old = t.status_code
        t.status_code = "ASSIGNED"
        add_history(db, t, "status", old, "ASSIGNED", None, f"Auto-assigned ({method})")
        add_history(db, t, "assignee", None, db.get(User, assignee_id).full_name, None)
    db.add(TicketAssignment(ticket_id=t.id, support_group_id=group_id, assignee_id=assignee_id,
                            assigned_by=None, method=method if group_id else "none", reason="Initial routing"))

    if data.related_ticket_number:
        rel = db.scalar(select(Ticket).where(Ticket.number == data.related_ticket_number,
                                             Ticket.requester_id == user.id))
        if rel:
            db.add(TicketRelationship(source_ticket_id=t.id, target_ticket_id=rel.id, relation_type="related",
                                      created_by=user.id))

    if idempotency_key:
        db.add(IdempotencyKey(user_id=user.id, key=idempotency_key[:80], ticket_id=t.id))

    notify(db, user.id, "ticket_created", f"{t.number} received",
           f"We received your request '{t.subject}'.", t, dedupe_key=f"created:{t.id}")
    for lead in _group_leads(db, group_id):
        notify(db, lead, "ticket_created", f"New {prio.code} ticket {t.number}", t.subject, t,
               dedupe_key=f"created-lead:{t.id}:{lead}")
    if assignee_id:
        notify(db, assignee_id, "ticket_assigned", f"{t.number} assigned to you", t.subject, t,
               dedupe_key=f"assigned:{t.id}:{assignee_id}:{now.timestamp()}")
    _check_recurring(db, t)
    audit_p(db, p, "ticket.create", entity_type="ticket", entity_id=t.number,
            detail={"category": cat.code, "priority": prio.code})
    return t


def _check_recurring(db: Session, t: Ticket) -> None:
    threshold = get_int(db, "recurring_issue_threshold")
    if threshold <= 0:
        return
    since = utcnow() - timedelta(hours=24)
    stmt = select(func.count()).select_from(Ticket).where(Ticket.category_id == t.category_id,
                                                          Ticket.created_at >= since)
    if t.subcategory_id:
        stmt = stmt.where(Ticket.subcategory_id == t.subcategory_id)
    n = db.scalar(stmt)
    if n >= threshold:
        bucket = utcnow().strftime("%Y%m%d")
        for lead in _group_leads(db, t.support_group_id):
            notify(db, lead, "sla_warning", f"Recurring issue: {n} '{t.category.name}' tickets in 24h",
                   "Consider raising a problem record or a known-error article.", t,
                   dedupe_key=f"recurring:{t.category_id}:{t.subcategory_id}:{bucket}:{lead}")


# ------------------------------------------------------------------ lifecycle
def allowed_transitions(db: Session, p: Principal, t: Ticket) -> list[TicketStatus]:
    rows = db.scalars(select(StatusTransition).where(StatusTransition.from_code == t.status_code)).all()
    staff = can_work_ticket(p, t)
    req = is_requester(p, t)
    codes = []
    for r in rows:
        if (r.actor in ("staff", "any") and staff) or (r.actor in ("requester", "any") and req):
            if r.to_code == "REOPENED" and not staff and not _within_reopen_window(db, t):
                continue
            codes.append(r.to_code)
    if not codes:
        return []
    statuses = db.scalars(select(TicketStatus).where(TicketStatus.code.in_(set(codes)))
                          .order_by(TicketStatus.sort_order)).all()
    return list(statuses)


def _within_reopen_window(db: Session, t: Ticket) -> bool:
    if not t.resolved_at:
        return False
    return utcnow() - t.resolved_at <= timedelta(days=get_int(db, "reopen_window_days"))


def change_status(db: Session, p: Principal, number: str, data: StatusChangeIn) -> Ticket:
    t = get_visible_ticket(db, p, number, for_update=True)
    check_version(t, data.expected_version)
    target = data.to_status.upper()
    allowed = {s.code for s in allowed_transitions(db, p, t)}
    if target not in allowed:
        raise BusinessRuleError(f"Cannot move ticket from {t.status.name} to {target}.")
    rule = db.scalar(select(StatusTransition).where(StatusTransition.from_code == t.status_code,
                                                    StatusTransition.to_code == target))
    if rule and rule.requires_reason and not (data.reason and data.reason.strip()):
        raise BusinessRuleError("A reason is required for this change.", details=[{"field": "reason"}])

    now = utcnow()
    old = t.status_code
    staff = can_work_ticket(p, t)

    if target == "RESOLVED":
        notes = (data.resolution_notes or "").strip()
        if len(notes) < 10:
            raise BusinessRuleError("Resolution notes (min 10 characters) are required to resolve.",
                                    details=[{"field": "resolution_notes"}])
        if t.resolution_notes != notes:
            add_history(db, t, "resolution_notes", None, "updated", p.id)
        t.resolution_notes = notes
        if data.root_cause:
            t.root_cause = data.root_cause.strip()
            add_history(db, t, "root_cause", None, "recorded", p.id, internal=True)
        t.resolved_at = now
    if target in ("IN_PROGRESS", "ASSIGNED") and t.assignee_id is None and staff:
        t.assignee_id, t.assigned_at = p.id, now
        db.add(TicketAssignment(ticket_id=t.id, support_group_id=t.support_group_id, assignee_id=p.id,
                                assigned_by=p.id, method="self", reason="Picked up while changing status"))
        add_history(db, t, "assignee", None, p.user.full_name, p.id)
    if target == "CLOSED":
        t.closed_at, t.closed_by = now, p.id
        t.closure_reason = "confirmed" if is_requester(p, t) and not staff else "staff"
    if target == "CANCELLED":
        t.closed_at, t.closed_by, t.closure_reason = now, p.id, "cancelled"
    if target == "REOPENED":
        t.reopen_count += 1
        t.resolved_at = None
        t.closed_at = None

    t.status_code = target
    sla_svc.on_status_change(db, t, old, target, now)
    if staff and target in RESPONSE_STATUSES:
        sla_svc.record_first_response(t, now)
    add_history(db, t, "status", old, target, p.id, data.reason)
    t.updated_at = now
    db.flush()
    db.refresh(t)

    # Notifications: requester hears about meaningful public changes; staff about reopen
    if target == "PENDING_EMPLOYEE":
        notify(db, t.requester_id, "info_requested", f"{t.number}: more information needed",
               data.reason or "The support engineer needs more information.", t)
    elif target == "RESOLVED":
        notify(db, t.requester_id, "ticket_resolved", f"{t.number} resolved",
               "Please confirm the fix or reopen if the issue persists.", t)
    elif target == "REOPENED":
        notify(db, t.assignee_id, "ticket_reopened", f"{t.number} reopened", data.reason, t)
    elif target in ("IN_PROGRESS", "CLOSED", "CANCELLED") and not is_requester(p, t):
        notify(db, t.requester_id, "status_changed", f"{t.number} is now {t.status.name}", None, t)

    audit_p(db, p, "ticket.status", entity_type="ticket", entity_id=t.number, detail={"from": old, "to": target})
    return t


def assign(db: Session, p: Principal, number: str, data: AssignIn) -> Ticket:
    t = get_visible_ticket(db, p, number, for_update=True)
    check_version(t, data.expected_version)
    if t.status_code in FINAL_STATUSES:
        raise BusinessRuleError("Closed or cancelled tickets cannot be reassigned.")
    group = db.get(SupportGroup, data.support_group_id)
    if not group or not group.is_active:
        raise BusinessRuleError("Select a valid support group.")

    moving_group = data.support_group_id != t.support_group_id
    # Leads assign within their groups; engineers may only escalate (move group, no assignee)
    if not can_assign_ticket(p, t):
        if not (can_work_ticket(p, t) and p.can("ticket.escalate") and moving_group and data.assignee_id is None):
            raise Forbidden("You do not have permission to assign this ticket.")
        if not (data.reason and len(data.reason.strip()) >= 5):
            raise BusinessRuleError("An escalation reason is required.", details=[{"field": "reason"}])
    if data.assignee_id is not None:
        member = db.scalar(select(SupportGroupMember).where(SupportGroupMember.group_id == group.id,
                                                            SupportGroupMember.user_id == data.assignee_id))
        if not member or not member.user.is_active:
            raise BusinessRuleError("The engineer is not an active member of that support group.")

    now = utcnow()
    old_group = t.support_group.name if t.support_group else None
    old_assignee = t.assignee.full_name if t.assignee else None
    t.support_group_id = group.id
    t.assignee_id = data.assignee_id
    if data.assignee_id:
        t.assigned_at = now
    db.add(TicketAssignment(ticket_id=t.id, support_group_id=group.id, assignee_id=data.assignee_id,
                            assigned_by=p.id, method="escalation" if not can_assign_ticket(p, t) else "manual",
                            reason=data.reason))
    if moving_group:
        add_history(db, t, "support_group", old_group, group.name, p.id, data.reason)
    new_assignee = db.get(User, data.assignee_id).full_name if data.assignee_id else None
    if new_assignee != old_assignee:
        add_history(db, t, "assignee", old_assignee, new_assignee, p.id, data.reason)
    if data.assignee_id and t.status_code in ("SUBMITTED", "TRIAGED", "REOPENED", "NEW"):
        old = t.status_code
        t.status_code = "ASSIGNED"
        sla_svc.on_status_change(db, t, old, "ASSIGNED", now)
        add_history(db, t, "status", old, "ASSIGNED", p.id)
    t.updated_at = now
    db.flush()
    db.refresh(t)
    if data.assignee_id and data.assignee_id != p.id:
        notify(db, data.assignee_id, "ticket_assigned", f"{t.number} assigned to you", t.subject, t)
    if moving_group and not data.assignee_id:
        for lead in _group_leads(db, group.id):
            notify(db, lead, "ticket_assigned", f"{t.number} escalated to {group.name}", data.reason, t)
    audit_p(db, p, "ticket.assign", entity_type="ticket", entity_id=t.number,
            detail={"group": group.code, "assignee_id": data.assignee_id})
    return t


def accept(db: Session, p: Principal, number: str, expected_version: int) -> Ticket:
    t = get_visible_ticket(db, p, number, for_update=True)
    check_version(t, expected_version)
    if not p.can("ticket.accept") or not can_work_ticket(p, t):
        raise Forbidden("You cannot accept this ticket.")
    if t.assignee_id not in (None, p.id):
        raise BusinessRuleError("Ticket is already assigned to another engineer. Ask your lead to reassign.")
    if t.status_code not in ("SUBMITTED", "TRIAGED", "ASSIGNED", "REOPENED"):
        raise BusinessRuleError("Only queued tickets can be accepted.")
    now = utcnow()
    if t.assignee_id is None:
        t.assignee_id, t.assigned_at = p.id, now
        db.add(TicketAssignment(ticket_id=t.id, support_group_id=t.support_group_id, assignee_id=p.id,
                                assigned_by=p.id, method="self", reason="Accepted"))
        add_history(db, t, "assignee", None, p.user.full_name, p.id)
    old = t.status_code
    t.status_code = "IN_PROGRESS"
    sla_svc.on_status_change(db, t, old, "IN_PROGRESS", now)
    sla_svc.record_first_response(t, now)
    add_history(db, t, "status", old, "IN_PROGRESS", p.id, "Accepted by engineer")
    t.updated_at = now
    db.flush()
    db.refresh(t)
    notify(db, t.requester_id, "status_changed", f"{t.number} is being worked on",
           f"{p.user.full_name} has picked up your ticket.", t)
    audit_p(db, p, "ticket.accept", entity_type="ticket", entity_id=t.number)
    return t


def change_priority(db: Session, p: Principal, number: str, data: PriorityChangeIn) -> Ticket:
    t = get_visible_ticket(db, p, number, for_update=True)
    check_version(t, data.expected_version)
    if not p.can("ticket.set_priority") or not (can_assign_ticket(p, t) or p.can("ticket.manage_all")):
        raise Forbidden("Only team leads or administrators can change priority.")
    if t.status_code in FINAL_STATUSES:
        raise BusinessRuleError("Closed tickets cannot be re-prioritised.")
    new_p = priority_for(db, data.impact, data.urgency)
    old_code = t.priority.code
    t.impact, t.urgency, t.priority_id = data.impact, data.urgency, new_p.id
    t.priority = new_p
    sla_svc.on_priority_change(db, t)  # re-targets from the ORIGINAL start time — never resets the clock
    add_history(db, t, "priority", old_code, new_p.code, p.id, data.reason)
    t.updated_at = utcnow()
    db.flush()
    db.refresh(t)
    audit_p(db, p, "ticket.priority", entity_type="ticket", entity_id=t.number,
            detail={"from": old_code, "to": new_p.code})
    return t


def add_comment(db: Session, p: Principal, number: str, data: CommentIn) -> TicketComment:
    t = get_visible_ticket(db, p, number, for_update=True)
    staff = can_work_ticket(p, t)
    if data.is_internal and not (p.can("ticket.comment_internal") and (staff or p.can("ticket.manage_all"))):
        raise Forbidden("Internal notes are restricted to IT staff.")
    if not data.is_internal and not (staff or is_requester(p, t) or p.can("ticket.manage_all")):
        raise Forbidden("You cannot comment on this ticket.")
    if t.status_code in FINAL_STATUSES and not data.is_internal:
        raise BusinessRuleError("This ticket is closed. Raise a new ticket or ask IT to reopen it.")
    now = utcnow()
    c = TicketComment(ticket_id=t.id, author_id=p.id, body=data.body, is_internal=data.is_internal, created_at=now)
    db.add(c)
    if staff and not data.is_internal:
        sla_svc.record_first_response(t, now)
        notify(db, t.requester_id, "comment_added", f"New reply on {t.number}", data.body[:300], t)
    elif is_requester(p, t) and not staff:
        if t.status_code == "PENDING_EMPLOYEE":  # requester answered — resume work and SLA
            old = t.status_code
            t.status_code = "IN_PROGRESS"
            sla_svc.on_status_change(db, t, old, "IN_PROGRESS", now)
            add_history(db, t, "status", old, "IN_PROGRESS", None, "Requester responded")
        notify(db, t.assignee_id, "comment_added", f"Requester replied on {t.number}", data.body[:300], t)
    db.flush()
    # Touch updated_at without bumping the optimistic-lock version: a comment must not
    # invalidate a colleague's pending status change.
    db.execute(update(Ticket).where(Ticket.id == t.id).values(updated_at=now)
               .execution_options(synchronize_session=False))
    db.refresh(c)
    audit_p(db, p, "ticket.comment", entity_type="ticket", entity_id=t.number,
            detail={"internal": data.is_internal})
    return c


def rate(db: Session, p: Principal, number: str, rating: int, comment: str | None) -> SatisfactionRating:
    t = get_visible_ticket(db, p, number)
    if not is_requester(p, t):
        raise Forbidden("Only the requester can rate this ticket.")
    if t.status_code not in ("RESOLVED", "CLOSED"):
        raise BusinessRuleError("You can rate a ticket once it is resolved.")
    if db.scalar(select(SatisfactionRating).where(SatisfactionRating.ticket_id == t.id)):
        raise Conflict("You have already rated this ticket.")
    r = SatisfactionRating(ticket_id=t.id, rating=rating, comment=comment, rated_by=p.id)
    db.add(r)
    add_history(db, t, "rating", None, str(rating), p.id)
    db.flush()
    return r


def link(db: Session, p: Principal, number: str, target_number: str, relation_type: str) -> None:
    t = get_visible_ticket(db, p, number)
    if not (p.can("ticket.link") and can_work_ticket(p, t)):
        raise Forbidden("You cannot link this ticket.")
    target = get_visible_ticket(db, p, target_number)
    if target.id == t.id:
        raise BusinessRuleError("A ticket cannot be linked to itself.")
    exists = db.scalar(select(TicketRelationship).where(
        TicketRelationship.source_ticket_id == t.id, TicketRelationship.target_ticket_id == target.id,
        TicketRelationship.relation_type == relation_type))
    if exists:
        raise Conflict("These tickets are already linked.")
    db.add(TicketRelationship(source_ticket_id=t.id, target_ticket_id=target.id, relation_type=relation_type,
                              created_by=p.id))
    add_history(db, t, "link", None, f"{relation_type} {target.number}", p.id)
    audit_p(db, p, "ticket.link", entity_type="ticket", entity_id=t.number,
            detail={"target": target.number, "type": relation_type})


def get_relations(db: Session, p: Principal, t: Ticket) -> list[dict]:
    from app.services.access import ticket_visibility_clause
    out = []
    rows = db.scalars(select(TicketRelationship).where(
        (TicketRelationship.source_ticket_id == t.id) | (TicketRelationship.target_ticket_id == t.id))).all()
    vis = ticket_visibility_clause(p)
    for r in rows:
        other_id = r.target_ticket_id if r.source_ticket_id == t.id else r.source_ticket_id
        other = db.scalar(select(Ticket).where(Ticket.id == other_id, vis))
        if other:  # never leak tickets the user cannot see
            out.append({"number": other.number, "subject": other.subject, "status": other.status.name,
                        "relation_type": r.relation_type,
                        "direction": "outgoing" if r.source_ticket_id == t.id else "incoming"})
    return out


def requester_label(t: Ticket) -> str:
    return t.requester.full_name if t.requester else "-"
