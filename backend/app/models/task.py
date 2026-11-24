"""Task management: management assigns tasks, the assignee reports progress, the assigner approves."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, LargeBinary, CheckConstraint, ForeignKey, Index, Integer, Unicode, false, true
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LongText, TimestampMixin, UTCDateTime, utcnow
from app.models.identity import User

TASK_STATUSES = ("not_started", "in_progress", "waiting_approval", "completed", "cancelled")
TASK_PRIORITIES = ("high", "medium", "low")
OPEN_TASK_STATUSES = ("not_started", "in_progress", "waiting_approval")


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('not_started','in_progress','waiting_approval','completed','cancelled')",
                        name="task_status"),
        CheckConstraint("priority IN ('high','medium','low')", name="task_priority"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="task_progress"),
        Index("ix_tasks_assignee_status", "assignee_id", "status"),
        Index("ix_tasks_assigner_status", "assigner_id", "status"),
        Index("ix_tasks_due", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(Unicode(20), unique=True, nullable=False)        # TSK-26-000001
    title: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    description: Mapped[str | None] = mapped_column(LongText)
    category: Mapped[str | None] = mapped_column(Unicode(60))                               # free text, e.g. "MIS"
    priority: Mapped[str] = mapped_column(Unicode(10), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(Unicode(20), nullable=False, default="not_started", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)       # owner (management)
    # first / responsible person; everyone on the task (including this person) is in `members`
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)                            # None = no deadline
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # deadline extension asked by the assignee, waiting for the assigner's decision
    requested_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    request_reason: Mapped[str | None] = mapped_column(Unicode(500))
    rating: Mapped[int | None] = mapped_column(Integer)                                    # 1–5 on approval
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    assigner: Mapped[User] = relationship(foreign_keys=[assigner_id], lazy="joined")
    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id], lazy="joined")
    events: Mapped[list["TaskEvent"]] = relationship(back_populates="task", order_by="TaskEvent.id",
                                                     cascade="all, delete-orphan")
    members: Mapped[list["TaskAssignee"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                         order_by="TaskAssignee.position")

    @property
    def member_ids(self) -> list[int]:
        return [m.user_id for m in self.members] or [self.assignee_id]

    @property
    def assignees(self) -> list[User]:
        return [m.user for m in self.members] or [self.assignee]

    @property
    def participant_ids(self) -> set[int]:
        """The only people who may read the description and messages."""
        return {self.assigner_id, *self.member_ids}

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_TASK_STATUSES

    def is_overdue(self, now: datetime | None = None) -> bool:
        return self.status in ("not_started", "in_progress") and self.due_at is not None and self.due_at < (now or utcnow())


class TaskAssignee(Base):
    """Everyone a task is assigned to (one or more people)."""
    __tablename__ = "task_assignees"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user: Mapped[User] = relationship(lazy="joined")


class TaskRead(Base):
    """What each participant has already seen (drives the Comments counter)."""
    __tablename__ = "task_reads"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TaskEvent(Base):
    """Timeline entry: created, progress update, comment, status change, approval, feedback, deadline change…"""
    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task", "task_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(Unicode(24), nullable=False)
    body: Mapped[str | None] = mapped_column(LongText)
    progress: Mapped[int | None] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(Unicode(120))
    new_value: Mapped[str | None] = mapped_column(Unicode(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="events")
    author: Mapped[User | None] = relationship(lazy="joined")


class TaskAttachment(Base):
    """A file on a task (image, PDF or Office file). Only the people on the task can see or download it."""
    __tablename__ = "task_attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("task_events.id", ondelete="SET NULL"))
    original_name: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(Unicode(64), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Unicode(64), nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    uploader: Mapped[User] = relationship(lazy="joined")


class TaskAttachmentBlob(Base):
    """File bytes when ATTACHMENT_STORAGE=database (Vercel has no persistent disk)."""
    __tablename__ = "task_attachment_blobs"
    attachment_id: Mapped[int] = mapped_column(ForeignKey("task_attachments.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary().with_variant(mssql.VARBINARY("max"), "mssql"), nullable=False)
