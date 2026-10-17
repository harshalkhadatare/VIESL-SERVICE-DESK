"""Reference data used by forms (categories, priorities, statuses, groups) and announcements."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require, require_any
from app.core.database import get_db
from app.models import (
    Announcement, Category, Department, Priority, PriorityMatrix, SupportGroup, SupportGroupMember, TicketStatus,
    utcnow,
)
from app.services.routing import priority_for

router = APIRouter(tags=["Reference data"])

ERP_MODULES = ["Finance & Accounts", "Procurement", "Inventory / Stores", "Sales & Billing", "Equipment Rental",
               "Projects", "Plant & Maintenance", "HR & Payroll", "Fixed Assets", "Reports / MIS"]
IMPACT = {1: "High — many users or a critical process", 2: "Medium — a team or department",
          3: "Low — only me / minor"}
URGENCY = {1: "High — work has stopped", 2: "Medium — work is slowed", 3: "Low — can wait"}


class SubOut(BaseModel):
    id: int
    name: str


class CategoryOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    default_ticket_type: str
    uses_erp_fields: bool
    requires_approval: bool
    subcategories: list[SubOut]


class PriorityOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None


class StatusOut(BaseModel):
    code: str
    name: str
    is_open: bool
    pauses_sla: bool


class CatalogOut(BaseModel):
    categories: list[CategoryOut]
    priorities: list[PriorityOut]
    statuses: list[StatusOut]
    impact: dict[int, str]
    urgency: dict[int, str]
    erp_modules: list[str]
    matrix: list[dict]


@router.get("/meta/catalog", response_model=CatalogOut)
def catalog(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    cats = db.scalars(select(Category).where(Category.is_active.is_(True))
                      .order_by(Category.sort_order, Category.name)).all()
    prios = db.scalars(select(Priority).order_by(Priority.rank)).all()
    stats = db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order)).all()
    matrix = db.scalars(select(PriorityMatrix)).all()
    pmap = {x.id: x.code for x in prios}
    return CatalogOut(
        categories=[CategoryOut(id=c.id, code=c.code, name=c.name, description=c.description,
                                default_ticket_type=c.default_ticket_type, uses_erp_fields=c.uses_erp_fields,
                                requires_approval=c.requires_approval,
                                subcategories=[SubOut(id=s.id, name=s.name) for s in c.subcategories if s.is_active])
                    for c in cats],
        priorities=[PriorityOut(id=x.id, code=x.code, name=x.name, description=x.description) for x in prios],
        statuses=[StatusOut(code=s.code, name=s.name, is_open=s.is_open, pauses_sla=s.pauses_sla) for s in stats],
        impact=IMPACT, urgency=URGENCY, erp_modules=ERP_MODULES,
        matrix=[{"impact": m.impact, "urgency": m.urgency, "priority": pmap[m.priority_id]} for m in matrix],
    )


@router.get("/meta/priority-preview", response_model=PriorityOut)
def priority_preview(impact: int = Query(ge=1, le=3), urgency: int = Query(ge=1, le=3),
                     p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    x = priority_for(db, impact, urgency)
    return PriorityOut(id=x.id, code=x.code, name=x.name, description=x.description)


class GroupOut(BaseModel):
    id: int
    code: str
    name: str
    assignment_strategy: str


class MemberOut(BaseModel):
    user_id: int
    full_name: str
    is_lead: bool
    is_available: bool
    skills: str | None


@router.get("/support-groups", response_model=list[GroupOut])
def support_groups(p: Principal = Depends(require_any("ticket.work", "dashboard.ops")),
                   db: Session = Depends(get_db)):
    return [GroupOut(id=g.id, code=g.code, name=g.name, assignment_strategy=g.assignment_strategy)
            for g in db.scalars(select(SupportGroup).where(SupportGroup.is_active.is_(True))
                                .order_by(SupportGroup.name))]


@router.get("/support-groups/{group_id}/members", response_model=list[MemberOut])
def group_members(group_id: int, p: Principal = Depends(require("ticket.work")), db: Session = Depends(get_db)):
    rows = db.scalars(select(SupportGroupMember).where(SupportGroupMember.group_id == group_id)).all()
    return [MemberOut(user_id=m.user_id, full_name=m.user.full_name, is_lead=m.is_lead,
                      is_available=m.is_available, skills=m.skills)
            for m in sorted(rows, key=lambda m: m.user.full_name) if m.user.is_active]


@router.get("/departments", response_model=list[dict])
def departments(p: Principal = Depends(require_any("dashboard.ops", "user.manage")), db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name} for d in db.scalars(select(Department).order_by(Department.name))]


class AnnouncementOut(BaseModel):
    id: int
    title: str
    body: str
    severity: str
    starts_at: datetime


@router.get("/announcements", response_model=list[AnnouncementOut])
def announcements(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    now = utcnow()
    rows = db.scalars(select(Announcement).where(Announcement.starts_at <= now,
                                                 or_(Announcement.ends_at.is_(None), Announcement.ends_at > now))
                      .order_by(Announcement.starts_at.desc()).limit(5)).all()
    return [AnnouncementOut(id=a.id, title=a.title, body=a.body, severity=a.severity, starts_at=a.starts_at)
            for a in rows]
