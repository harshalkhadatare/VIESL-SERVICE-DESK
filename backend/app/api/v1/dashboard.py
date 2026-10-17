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


@router.get("/ops")
def ops(start: date | None = None, end: date | None = None, category_id: int | None = None,
        department_id: int | None = None, group_id: int | None = None, assignee_id: int | None = None,
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
                            department_id=department_id, group_id=group_id, assignee_id=assignee_id)


@router.get("/search")
def global_search(q: str = Query(min_length=2, max_length=100), p: Principal = Depends(get_principal),
                  db: Session = Depends(get_db)):
    """Global search over tickets the user may see and published knowledge articles."""
    from app.models import KnowledgeArticle
    like = f"%{q.strip()}%"
    tickets = db.scalars(select(Ticket).where(ticket_visibility_clause(p),
                                              (Ticket.number.ilike(like)) | (Ticket.subject.ilike(like)))
                         .order_by(Ticket.updated_at.desc()).limit(6)).all()
    arts = db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.status == "published",
                                                     (KnowledgeArticle.title.ilike(like)) |
                                                     (KnowledgeArticle.keywords.ilike(like))).limit(5)).all()
    return {
        "tickets": [{"number": t.number, "subject": t.subject, "status": t.status.name} for t in tickets],
        "articles": [{"id": a.id, "title": a.title} for a in arts],
    }
