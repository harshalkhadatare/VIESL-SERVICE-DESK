from datetime import datetime

from sqlalchemy import (
    LargeBinary, BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, Unicode, UniqueConstraint, false,
)
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedByMixin, LongText, TimestampMixin, UTCDateTime, utcnow
from app.models.catalog import Category, Priority, Subcategory, TicketStatus
from app.models.identity import Department, Location, SupportGroup, User


class TicketSequence(Base):
    """Per-year counter used to generate IT-YYYY-NNNNNN under a row lock."""
    __tablename__ = "ticket_sequences"
    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Ticket(Base, TimestampMixin, CreatedByMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("ticket_type IN ('incident','service_request')", name="ticket_type"),
        CheckConstraint("impact BETWEEN 1 AND 3", name="impact_range"),
        CheckConstraint("urgency BETWEEN 1 AND 3", name="urgency_range"),
        Index("ix_tickets_status_group", "status_code", "support_group_id"),
        Index("ix_tickets_requester", "requester_id", "created_at"),
        Index("ix_tickets_assignee", "assignee_id", "status_code"),
        Index("ix_tickets_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(Unicode(20), unique=True, nullable=False)
    ticket_type: Mapped[str] = mapped_column(Unicode(20), nullable=False, default="incident")
    subject: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    description: Mapped[str] = mapped_column(LongText, nullable=False)

    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    subcategory_id: Mapped[int | None] = mapped_column(ForeignKey("subcategories.id"))

    impact: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    urgency: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    priority_id: Mapped[int] = mapped_column(ForeignKey("priorities.id"), nullable=False)
    status_code: Mapped[str] = mapped_column(ForeignKey("ticket_statuses.code"), nullable=False)

    support_group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    contact_method: Mapped[str | None] = mapped_column(Unicode(20))

    root_cause: Mapped[str | None] = mapped_column(LongText)
    resolution_notes: Mapped[str | None] = mapped_column(LongText)

    first_response_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closure_reason: Mapped[str | None] = mapped_column(Unicode(30))  # confirmed|auto|staff|cancelled
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}

    requester: Mapped[User] = relationship(foreign_keys=[requester_id], lazy="joined")
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    department: Mapped[Department | None] = relationship(lazy="joined")
    location: Mapped[Location | None] = relationship(lazy="joined")
    category: Mapped[Category] = relationship(lazy="joined")
    subcategory: Mapped[Subcategory | None] = relationship(lazy="joined")
    priority: Mapped[Priority] = relationship(lazy="joined")
    status: Mapped[TicketStatus] = relationship(lazy="joined")
    support_group: Mapped[SupportGroup | None] = relationship(lazy="joined")
    erp: Mapped["TicketErpDetail | None"] = relationship(back_populates="ticket", uselist=False, lazy="selectin")
    sla: Mapped["SLATracking | None"] = relationship(back_populates="ticket", uselist=False, lazy="selectin")


class TicketErpDetail(Base):
    __tablename__ = "ticket_erp_details"
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), primary_key=True)
    erp_module: Mapped[str | None] = mapped_column(Unicode(60))
    transaction_type: Mapped[str | None] = mapped_column(Unicode(80))
    reference_no: Mapped[str | None] = mapped_column(Unicode(80), index=True)
    company_branch: Mapped[str | None] = mapped_column(Unicode(120))
    error_message: Mapped[str | None] = mapped_column(LongText)
    expected_result: Mapped[str | None] = mapped_column(LongText)
    actual_result: Mapped[str | None] = mapped_column(LongText)
    steps_to_reproduce: Mapped[str | None] = mapped_column(LongText)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    business_impact: Mapped[str | None] = mapped_column(Unicode(500))
    workaround_available: Mapped[bool | None] = mapped_column(Boolean)
    ticket: Mapped[Ticket] = relationship(back_populates="erp")


class TicketAssignment(Base):
    __tablename__ = "ticket_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    support_group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # NULL = automation
    method: Mapped[str] = mapped_column(Unicode(20), nullable=False, default="manual")
    reason: Mapped[str | None] = mapped_column(Unicode(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    __table_args__ = (Index("ix_ticket_comments_ticket", "ticket_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(LongText, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    author: Mapped[User] = relationship(lazy="joined")


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_comments.id"))
    original_name: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(Unicode(64), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Unicode(64), nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    uploader: Mapped[User] = relationship(lazy="joined")


class TicketAttachmentBlob(Base):
    """File bytes when ATTACHMENT_STORAGE=database (serverless hosts with no persistent disk)."""
    __tablename__ = "ticket_attachment_blobs"
    attachment_id: Mapped[int] = mapped_column(ForeignKey("ticket_attachments.id"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary().with_variant(mssql.VARBINARY("max"), "mssql"), nullable=False)


class TicketHistory(Base):
    __tablename__ = "ticket_history"
    __table_args__ = (Index("ix_ticket_history_ticket", "ticket_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    field: Mapped[str] = mapped_column(Unicode(40), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Unicode(500))
    new_value: Mapped[str | None] = mapped_column(Unicode(500))
    reason: Mapped[str | None] = mapped_column(Unicode(1000))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # NULL = system
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    actor: Mapped[User | None] = relationship(lazy="joined")


class TicketWatcher(Base):
    __tablename__ = "ticket_watchers"
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)


class TicketRelationship(Base):
    __tablename__ = "ticket_relationships"
    __table_args__ = (
        UniqueConstraint("source_ticket_id", "target_ticket_id", "relation_type"),
        CheckConstraint("relation_type IN ('duplicate_of','related')", name="relation_type"),
        CheckConstraint("source_ticket_id <> target_ticket_id", name="no_self"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    target_ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(Unicode(20), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class SLATracking(Base):
    __tablename__ = "sla_tracking"
    __table_args__ = (Index("ix_sla_tracking_due", "resolution_due_at", "resolution_breached"),)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), primary_key=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("sla_policies.id"))
    calendar_id: Mapped[int] = mapped_column(ForeignKey("business_calendars.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    response_target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    response_due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolution_due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    paused_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warning_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
    ticket: Mapped[Ticket] = relationship(back_populates="sla")


class SatisfactionRating(Base):
    __tablename__ = "satisfaction_ratings"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), unique=True, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Unicode(1000))
    rated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(Unicode(80), nullable=False)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
