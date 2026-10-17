"""Cross-cutting platform tables: notifications, knowledge base, automation, audit, settings."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Unicode, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LongText, TimestampMixin, UTCDateTime, utcnow
from app.models.identity import User


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user", "user_id", "is_read", "created_at"),
        Index("ix_notifications_email", "email_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    event: Mapped[str] = mapped_column(Unicode(40), nullable=False)
    title: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Unicode(1000))
    link: Mapped[str | None] = mapped_column(Unicode(200))
    dedupe_key: Mapped[str] = mapped_column(Unicode(120), nullable=False, unique=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Email outbox state: none | pending | sent | failed
    email_status: Mapped[str] = mapped_column(Unicode(10), default="none", nullable=False)
    email_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    email_last_error: Mapped[str | None] = mapped_column(Unicode(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    event: Mapped[str] = mapped_column(Unicode(40), primary_key=True)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    body: Mapped[str] = mapped_column(Unicode(2000), nullable=False)
    severity: Mapped[str] = mapped_column(Unicode(10), default="info", nullable=False)  # info|warning|outage
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class KnowledgeArticle(Base, TimestampMixin):
    __tablename__ = "knowledge_articles"
    __table_args__ = (
        CheckConstraint("status IN ('draft','in_review','published','retired')", name="status"),
        Index("ix_kb_status", "status", "category_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    keywords: Mapped[str | None] = mapped_column(Unicode(400))
    problem: Mapped[str] = mapped_column(LongText, nullable=False)
    solution: Mapped[str] = mapped_column(LongText, nullable=False)
    status: Mapped[str] = mapped_column(Unicode(12), default="draft", nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="joined")


class KnowledgeArticleVersion(Base):
    __tablename__ = "knowledge_article_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("knowledge_articles.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    problem: Mapped[str] = mapped_column(LongText, nullable=False)
    solution: Mapped[str] = mapped_column(LongText, nullable=False)
    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AutomationRule(Base, TimestampMixin):
    """Routing rule. NULL match columns mean 'any'. Lowest sort_order wins."""
    __tablename__ = "automation_rules"
    __table_args__ = (
        CheckConstraint("assignment_strategy IN ('group_default','manual','round_robin','least_loaded')",
                        name="strategy"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    match_category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    match_subcategory_id: Mapped[int | None] = mapped_column(ForeignKey("subcategories.id"))
    match_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    match_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    match_priority_id: Mapped[int | None] = mapped_column(ForeignKey("priorities.id"))
    match_erp_module: Mapped[str | None] = mapped_column(Unicode(60))
    target_group_id: Mapped[int] = mapped_column(ForeignKey("support_groups.id"), nullable=False)
    assignment_strategy: Mapped[str] = mapped_column(Unicode(20), default="group_default", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class AutomationExecutionLog(Base):
    __tablename__ = "automation_execution_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("automation_rules.id"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    action: Mapped[str] = mapped_column(Unicode(60), nullable=False)
    outcome: Mapped[str] = mapped_column(Unicode(20), nullable=False)  # applied|skipped|error
    detail: Mapped[str | None] = mapped_column(Unicode(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_actor", "actor_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str | None] = mapped_column(Unicode(254))
    action: Mapped[str] = mapped_column(Unicode(60), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(Unicode(40))
    entity_id: Mapped[str | None] = mapped_column(Unicode(40))
    detail: Mapped[str | None] = mapped_column(Unicode(2000))
    ip_address: Mapped[str | None] = mapped_column(Unicode(45))
    request_id: Mapped[str | None] = mapped_column(Unicode(36))
    outcome: Mapped[str] = mapped_column(Unicode(10), default="success", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class ApplicationSetting(Base):
    __tablename__ = "application_settings"
    key: Mapped[str] = mapped_column(Unicode(80), primary_key=True)
    value: Mapped[str] = mapped_column(Unicode(1000), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(255))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
