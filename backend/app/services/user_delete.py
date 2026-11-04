"""Permanently delete a user (Users & roles → Delete).

What happens
- Tickets the user RAISED are deleted with everything in them (same as deleting each ticket).
- The user's comments, uploaded files, ratings and ticket links on other people's tickets are deleted.
- Knowledge-base articles they wrote are deleted.
- Tickets assigned to them become Unassigned; history and audit entries stay but show "System".
- One audit entry records who deleted whom. Deactivate is the safer choice for people who simply left.
"""
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import BusinessRuleError, NotFound
from app.models import (
    Announcement, ApplicationSetting, AuditLog, AutomationRule, IdempotencyKey, KnowledgeArticle,
    KnowledgeArticleVersion, Notification, NotificationPreference, RefreshToken, Role, SatisfactionRating,
    SupportGroup, SupportGroupMember, Ticket, TicketAssignment, TicketAttachment, TicketAttachmentBlob,
    TicketComment, TicketHistory, TicketRelationship, TicketUserFlag, TicketWatcher, User, UserRole,
)
from app.services.audit import audit_p
from app.services.ticket_delete import purge_tickets, remove_files


def delete_preview(db: Session, u: User) -> dict:
    def n(stmt):
        return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return {
        "tickets_raised": n(select(Ticket.id).where(Ticket.requester_id == u.id)),
        "tickets_assigned": n(select(Ticket.id).where(Ticket.assignee_id == u.id)),
        "comments": n(select(TicketComment.id).where(TicketComment.author_id == u.id)),
        "attachments": n(select(TicketAttachment.id).where(TicketAttachment.uploaded_by == u.id)),
        "kb_articles": n(select(KnowledgeArticle.id).where(KnowledgeArticle.author_id == u.id)),
    }


def _last_admin(db: Session, u: User) -> bool:
    admin_role = db.scalar(select(Role.id).where(Role.code == "it_admin"))
    if not db.scalar(select(UserRole.user_id).where(UserRole.user_id == u.id, UserRole.role_id == admin_role)):
        return False
    others = db.scalar(select(func.count()).select_from(UserRole).join(User, User.id == UserRole.user_id)
                       .where(UserRole.role_id == admin_role, User.id != u.id, User.is_active.is_(True)))
    return not others


def delete_user(db: Session, p: Principal, uid: int) -> dict:
    u = db.get(User, uid)
    if not u:
        raise NotFound("User not found.")
    if u.id == p.id:
        raise BusinessRuleError("You can't delete your own account.")
    if _last_admin(db, u):
        raise BusinessRuleError("This is the last active IT Administrator — make someone else an administrator first.")
    summary = delete_preview(db, u)
    label = u.label
    v = u.id
    db.expunge(u)

    # 1. tickets they raised
    stored = purge_tickets(db, list(db.scalars(select(Ticket.id).where(Ticket.requester_id == v))))

    # 2. their content on other tickets
    own_att = select(TicketAttachment.id).where(TicketAttachment.uploaded_by == v)
    stored += list(db.scalars(select(TicketAttachment.stored_name).where(TicketAttachment.uploaded_by == v)))
    own_comments = select(TicketComment.id).where(TicketComment.author_id == v)
    for stmt in (
        delete(TicketAttachmentBlob).where(TicketAttachmentBlob.attachment_id.in_(own_att)),
        delete(TicketAttachment).where(TicketAttachment.uploaded_by == v),
        update(TicketAttachment).where(TicketAttachment.comment_id.in_(own_comments)).values(comment_id=None),
        delete(TicketComment).where(TicketComment.author_id == v),
        delete(SatisfactionRating).where(SatisfactionRating.rated_by == v),
        delete(TicketRelationship).where(TicketRelationship.created_by == v),
        # 3. knowledge base
        delete(KnowledgeArticleVersion).where(or_(
            KnowledgeArticleVersion.edited_by == v,
            KnowledgeArticleVersion.article_id.in_(select(KnowledgeArticle.id).where(KnowledgeArticle.author_id == v)))),
        delete(KnowledgeArticle).where(KnowledgeArticle.author_id == v),
        # 4. keep history, shown as "System"
        update(AuditLog).where(AuditLog.actor_id == v).values(actor_id=None),
        update(TicketHistory).where(TicketHistory.actor_id == v).values(actor_id=None),
        update(Ticket).where(Ticket.assignee_id == v).values(assignee_id=None),
        update(Ticket).where(Ticket.created_by == v).values(created_by=None),
        update(Ticket).where(Ticket.closed_by == v).values(closed_by=None),
        update(TicketAssignment).where(TicketAssignment.assignee_id == v).values(assignee_id=None),
        update(TicketAssignment).where(TicketAssignment.assigned_by == v).values(assigned_by=None),
        update(SupportGroup).where(SupportGroup.last_assigned_user_id == v).values(last_assigned_user_id=None),
        update(UserRole).where(UserRole.granted_by == v).values(granted_by=None),
        update(Announcement).where(Announcement.created_by == v).values(created_by=None),
        update(ApplicationSetting).where(ApplicationSetting.updated_by == v).values(updated_by=None),
        update(AutomationRule).where(AutomationRule.created_by == v).values(created_by=None),
        update(KnowledgeArticle).where(KnowledgeArticle.reviewer_id == v).values(reviewer_id=None),
        # 5. the user's own rows, then the user
        delete(TicketWatcher).where(TicketWatcher.user_id == v),
        delete(TicketUserFlag).where(TicketUserFlag.user_id == v),
        delete(Notification).where(Notification.user_id == v),
        delete(NotificationPreference).where(NotificationPreference.user_id == v),
        delete(IdempotencyKey).where(IdempotencyKey.user_id == v),
        delete(RefreshToken).where(RefreshToken.user_id == v),
        delete(SupportGroupMember).where(SupportGroupMember.user_id == v),
        delete(UserRole).where(UserRole.user_id == v),
        delete(User).where(User.id == v),
    ):
        db.execute(stmt.execution_options(synchronize_session=False))

    audit_p(db, p, "admin.user_delete", entity_type="user", entity_id=str(v), detail={"user": label, **summary})
    db.commit()
    remove_files(stored)
    return summary
