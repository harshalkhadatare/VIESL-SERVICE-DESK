"""Row-level ticket visibility. Every ticket query must be filtered through here.

Unauthorized tickets are reported as 404 (not 403) to prevent ticket-number enumeration.
"""
from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.api.deps import Principal
from app.core.errors import NotFound
from app.models import Ticket


def ticket_visibility_clause(p: Principal) -> ColumnElement[bool]:
    if p.can("ticket.view_all"):
        return Ticket.id.isnot(None)
    clauses = []
    if p.can("ticket.view_own"):
        clauses.append(Ticket.requester_id == p.id)
    if p.can("ticket.view_department") and p.user.department_id:
        clauses.append(Ticket.department_id == p.user.department_id)
    if p.can("ticket.view_group"):
        clauses.append(Ticket.assignee_id == p.id)
        if p.group_ids:
            clauses.append(Ticket.support_group_id.in_(p.group_ids))
    return or_(*clauses) if clauses else false()


def get_visible_ticket(db: Session, p: Principal, number: str, for_update: bool = False) -> Ticket:
    stmt = select(Ticket).where(Ticket.number == number, ticket_visibility_clause(p))
    if for_update:
        stmt = stmt.with_for_update()
    t = db.scalar(stmt)
    if not t:
        raise NotFound("Ticket not found.")
    return t


def can_work_ticket(p: Principal, t: Ticket) -> bool:
    """Staff may act on tickets in their groups, assigned to them, or anywhere with ticket.manage_all."""
    if not p.can("ticket.work"):
        return False
    if p.can("ticket.manage_all"):
        return True
    return t.assignee_id == p.id or (t.support_group_id is not None and t.support_group_id in p.group_ids)


def can_assign_ticket(p: Principal, t: Ticket) -> bool:
    if not p.can("ticket.assign"):
        return False
    if p.can("ticket.manage_all"):
        return True
    return t.support_group_id is not None and t.support_group_id in p.lead_group_ids


def is_requester(p: Principal, t: Ticket) -> bool:
    return t.requester_id == p.id
