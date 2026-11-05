"""Permanent ticket deletion.

Rules
- Only IT administrators (``ticket.manage_all``) may delete a ticket.
- Employees cannot delete; they cancel instead, so the ticket stays in their history and in Excel exports.
- The ticket and everything attached to it is removed; one audit-log entry keeps the number, subject and who
  deleted it. The ticket number is never reused.
"""
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.errors import Forbidden
from app.models import (
    AutomationExecutionLog, IdempotencyKey, KnowledgeArticle, Notification, SatisfactionRating, SLATracking, Ticket,
    TicketAssignment, TicketAttachment, TicketAttachmentBlob, TicketComment, TicketErpDetail, TicketHistory,
    TicketRelationship, TicketUserFlag, TicketWatcher,
)
from app.services.audit import audit_p
from app.services.notifications import notify

LOCKED_FOR_REQUESTER = ("RESOLVED", "CLOSED")


def can_delete_ticket(p: Principal, t: Ticket) -> bool:
    """Only IT administrators delete. Employees cancel instead, so the ticket stays in their history and in exports."""
    return p.can("ticket.manage_all")


def delete_ticket(db: Session, p: Principal, t: Ticket) -> None:
    if not can_delete_ticket(p, t):
        raise Forbidden("Tickets can't be deleted from here — use “Cancel ticket” instead. It stays in your history.")

    tid, number, subject = t.id, t.number, t.subject
    assignee_id, requester_id = t.assignee_id, t.requester_id
    by_owner = requester_id == p.id

    db.expunge(t)
    stored = purge_tickets(db, [tid])

    audit_p(db, p, "ticket.delete", entity_type="ticket", entity_id=number,
            detail={"subject": subject[:200], "by_requester": by_owner})
    # let the assigned engineer (or the requester, if IT deleted it) know
    who = p.user.label
    if assignee_id and assignee_id != p.id:
        notify(db, assignee_id, "status_changed", f"{number} was deleted by {who}", subject, email=False)
    if not by_owner:
        notify(db, requester_id, "status_changed", f"Your ticket {number} was deleted by IT", subject, email=False)
    db.commit()

    remove_files(stored)


def purge_tickets(db: Session, ids: list[int]) -> list[str]:
    """Delete tickets and every row that belongs to them. Returns stored file names to remove from disk."""
    if not ids:
        return []
    stored = list(db.scalars(select(TicketAttachment.stored_name).where(TicketAttachment.ticket_id.in_(ids))).all())
    att_ids = select(TicketAttachment.id).where(TicketAttachment.ticket_id.in_(ids))
    for stmt in (
        delete(TicketAttachmentBlob).where(TicketAttachmentBlob.attachment_id.in_(att_ids)),
        delete(TicketAttachment).where(TicketAttachment.ticket_id.in_(ids)),
        delete(TicketComment).where(TicketComment.ticket_id.in_(ids)),
        delete(TicketHistory).where(TicketHistory.ticket_id.in_(ids)),
        delete(TicketAssignment).where(TicketAssignment.ticket_id.in_(ids)),
        delete(TicketWatcher).where(TicketWatcher.ticket_id.in_(ids)),
        delete(TicketUserFlag).where(TicketUserFlag.ticket_id.in_(ids)),
        delete(TicketRelationship).where(or_(TicketRelationship.source_ticket_id.in_(ids),
                                             TicketRelationship.target_ticket_id.in_(ids))),
        delete(TicketErpDetail).where(TicketErpDetail.ticket_id.in_(ids)),
        delete(SLATracking).where(SLATracking.ticket_id.in_(ids)),
        delete(SatisfactionRating).where(SatisfactionRating.ticket_id.in_(ids)),
        delete(IdempotencyKey).where(IdempotencyKey.ticket_id.in_(ids)),
        delete(Notification).where(Notification.ticket_id.in_(ids)),
        update(AutomationExecutionLog).where(AutomationExecutionLog.ticket_id.in_(ids)).values(ticket_id=None),
        update(KnowledgeArticle).where(KnowledgeArticle.source_ticket_id.in_(ids)).values(source_ticket_id=None),
        delete(Ticket).where(Ticket.id.in_(ids)),
    ):
        db.execute(stmt.execution_options(synchronize_session=False))
    return stored


def remove_files(stored: list[str]) -> None:
    if get_settings().attachment_storage == "database":
        return
    from app.services.attachments import path_for
    for name in stored:
        try:
            path_for(name).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 — file cleanup must never fail the request
            pass
