from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require
from app.core.database import get_db
from app.core.errors import BusinessRuleError
from app.models import Ticket
from app.services import dashboard as dash
from app.services.access import ticket_visibility_clause

router = APIRouter(prefix="/dashboard", tags=["Dashboards"])


@router.get("/employee")
def employee(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    recent = db.scalars(select(Ticket).where(Ticket.requester_id == p.id)
                        .order_by(Ticket.updated_at.desc()).limit(6)).all()
    return {
        "summary": dash.employee_summary(db, p),
        "recent": [{"number": t.number, "subject": t.subject, "status": {"code": t.status.code, "name": t.status.name},
                    "priority": t.priority.code, "updated_at": t.updated_at,
                    "assignee": t.assignee.full_name if t.assignee else None} for t in recent],
    }


@router.get("/admin-home")
def admin_home(p: Principal = Depends(require("dashboard.ops")), db: Session = Depends(get_db)):
    """Simple admin dashboard: tickets needing attention, my open work, team this week."""
    return dash.admin_home(db, p, p.user.timezone)


@router.get("/ops")
def ops(start: date | None = None, end: date | None = None, category_id: int | None = None,
        department_id: int | None = None, group_id: int | None = None, assignee_id: int | None = None,
        desk: str | None = Query(None, pattern="^(it|erp|all)$"),
        p: Principal = Depends(require("dashboard.ops")), db: Session = Depends(get_db)):
    tz = p.user.timezone
    today = datetime.now(ZoneInfo(tz)).date()
    end = end or today
    start = start or end - timedelta(days=13)
    if start > end:
        raise BusinessRuleError("Start date must be before end date.")
    if (end - start).days > 366:
        raise BusinessRuleError("Date range cannot exceed one year.")
    return dash.ops_summary(db, p, start=start, end=end, tz=tz, category_id=category_id,
                            department_id=department_id, group_id=group_id, assignee_id=assignee_id, desk=desk)


@router.get("/search")
def global_search(q: str = Query(min_length=2, max_length=100), p: Principal = Depends(get_principal),
                  db: Session = Depends(get_db)):
    """Global search over tickets the user may see and published knowledge articles."""
    from app.models import KnowledgeArticle
    like = f"%{q.strip()}%"
    from sqlalchemy import func, or_

    from app.models import User
    people_q = select(User.id).where(or_(User.full_name.ilike(like), User.employee_code.ilike(like),
                                         User.email.ilike(like)))
    tickets = db.scalars(select(Ticket).where(ticket_visibility_clause(p), or_(
        Ticket.number.ilike(like), Ticket.subject.ilike(like), Ticket.requester_id.in_(people_q)))
                         .order_by(Ticket.updated_at.desc()).limit(6)).all()
    people = []
    if p.can("ticket.work") or p.can("ticket.view_all"):
        counts = db.execute(select(User.full_name, User.employee_code, func.count(Ticket.id))
                            .join(Ticket, Ticket.requester_id == User.id)
                            .where(User.id.in_(people_q), ticket_visibility_clause(p))
                            .group_by(User.id, User.full_name, User.employee_code)
                            .order_by(func.count(Ticket.id).desc()).limit(5)).all()
        people = [{"name": n, "employee_code": c, "tickets": k} for n, c, k in counts]
    arts = db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.status == "published",
                                                     (KnowledgeArticle.title.ilike(like)) |
                                                     (KnowledgeArticle.keywords.ilike(like))).limit(5)).all()
    return {
        "tickets": [{"number": t.number, "subject": t.subject, "status": t.status.name,
                     "requester": t.requester.full_name, "requester_code": t.requester.employee_code}
                    for t in tickets],
        "people": people,
        "articles": [{"id": a.id, "title": a.title} for a in arts],
    }
