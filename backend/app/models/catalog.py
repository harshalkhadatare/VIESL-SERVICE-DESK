"""Configurable catalog: categories, priorities, SLA policies, calendars, statuses."""
from datetime import date, time

from sqlalchemy import (
    Boolean, CheckConstraint, Date, ForeignKey, Integer, Time, Unicode, UniqueConstraint, false, true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(500))
    default_ticket_type: Mapped[str] = mapped_column(Unicode(20), default="incident", nullable=False)
    default_group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"))
    uses_erp_fields: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    # Protected categories (e.g. security incidents) are never auto-closed
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)

    subcategories: Mapped[list["Subcategory"]] = relationship(back_populates="category", lazy="selectin",
                                                              order_by="Subcategory.name")

    __table_args__ = (CheckConstraint("default_ticket_type IN ('incident','service_request')", name="ticket_type"),)


class Subcategory(Base):
    __tablename__ = "subcategories"
    __table_args__ = (UniqueConstraint("category_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    category: Mapped[Category] = relationship(back_populates="subcategories")


class Priority(Base):
    __tablename__ = "priorities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(5), unique=True, nullable=False)   # P1..P4
    name: Mapped[str] = mapped_column(Unicode(40), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = most urgent
    description: Mapped[str | None] = mapped_column(Unicode(255))


class PriorityMatrix(Base):
    """Impact (1 high..3 low) x Urgency (1 high..3 low) -> Priority."""
    __tablename__ = "priority_matrix"
    __table_args__ = (
        UniqueConstraint("impact", "urgency"),
        CheckConstraint("impact BETWEEN 1 AND 3", name="impact_range"),
        CheckConstraint("urgency BETWEEN 1 AND 3", name="urgency_range"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    urgency: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_id: Mapped[int] = mapped_column(ForeignKey("priorities.id"), nullable=False)


class BusinessCalendar(Base, TimestampMixin):
    __tablename__ = "business_calendars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(80), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(Unicode(60), nullable=False, default="Asia/Kolkata")
    work_start: Mapped[time] = mapped_column(Time, nullable=False)
    work_end: Mapped[time] = mapped_column(Time, nullable=False)
    # 7 chars, Monday..Sunday, '1' = working day. e.g. '1111110' = Mon-Sat
    working_days: Mapped[str] = mapped_column(Unicode(7), nullable=False, default="1111100")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    holidays: Mapped[list["Holiday"]] = relationship(lazy="selectin", order_by="Holiday.holiday_date")


class Holiday(Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("calendar_id", "holiday_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("business_calendars.id"), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)


class SLAPolicy(Base, TimestampMixin):
    """Targets in business minutes. A category-specific row overrides the generic (category NULL) row."""
    __tablename__ = "sla_policies"
    __table_args__ = (
        CheckConstraint("response_minutes > 0 AND resolution_minutes > 0", name="positive_targets"),
        CheckConstraint("warning_percent BETWEEN 1 AND 99", name="warning_pct"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    priority_id: Mapped[int] = mapped_column(ForeignKey("priorities.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    calendar_id: Mapped[int] = mapped_column(ForeignKey("business_calendars.id"), nullable=False)
    response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_percent: Mapped[int] = mapped_column(Integer, default=75, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)


class TicketStatus(Base):
    __tablename__ = "ticket_statuses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(60), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pauses_sla: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StatusTransition(Base):
    """Allowed lifecycle moves. actor: staff (needs ticket.work), requester, any."""
    __tablename__ = "status_transitions"
    __table_args__ = (
        UniqueConstraint("from_code", "to_code", "actor"),
        CheckConstraint("actor IN ('staff','requester','any')", name="actor"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_code: Mapped[str] = mapped_column(ForeignKey("ticket_statuses.code"), nullable=False)
    to_code: Mapped[str] = mapped_column(ForeignKey("ticket_statuses.code"), nullable=False)
    actor: Mapped[str] = mapped_column(Unicode(10), nullable=False, default="staff")
    requires_reason: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
