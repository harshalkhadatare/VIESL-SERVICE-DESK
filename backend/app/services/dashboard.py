"""Dashboard metrics computed from live database queries, scoped by ticket visibility."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.models import (
    Category, Department, Priority, SatisfactionRating, SLATracking, Ticket, TicketStatus, User, utcnow,
)
from app.services import sla as sla_svc
from app.services.access import ticket_visibility_clause
from app.services.business_time import business_minutes_between


def _local_day_bounds(tz: str, d: date) -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    s = datetime.combine(d, time(0), z).astimezone(timezone.utc)
    return s, s + timedelta(days=1)


def employee_summary(db: Session, p: Principal) -> dict:
    base = select(func.count()).select_from(Ticket).where(Ticket.requester_id == p.id)
    open_codes = select(TicketStatus.code).where(TicketStatus.is_open.is_(True))
    return {
        "open": db.scalar(base.where(Ticket.status_code.in_(open_codes))),
        "awaiting_me": db.scalar(base.where(Ticket.status_code == "PENDING_EMPLOYEE")),
        "in_progress": db.scalar(base.where(Ticket.status_code.in_(["ASSIGNED", "IN_PROGRESS", "REOPENED"]))),
        "resolved": db.scalar(base.where(Ticket.status_code == "RESOLVED")),
        "closed": db.scalar(base.where(Ticket.status_code == "CLOSED")),
    }


def ops_summary(db: Session, p: Principal, *, start: date, end: date, tz: str,
                category_id: int | None = None, department_id: int | None = None,
                group_id: int | None = None, assignee_id: int | None = None, desk: str | None = None) -> dict:
    now = utcnow()
    vis = ticket_visibility_clause(p)
    filters = [vis]
    if category_id:
        filters.append(Ticket.category_id == category_id)
    if department_id:
        filters.append(Ticket.department_id == department_id)
    if group_id:
        filters.append(Ticket.support_group_id == group_id)
    if assignee_id:
        filters.append(Ticket.assignee_id == assignee_id)
    if desk in ("it", "erp"):   # IT or ERP-IT dashboard; "Both" tickets count in both
        filters.append(Ticket.desk.in_([desk, "both"]))
    scope = and_(*filters)

    range_start, _ = _local_day_bounds(tz, start)
    _, range_end = _local_day_bounds(tz, end)
    today_start, today_end = _local_day_bounds(tz, datetime.now(ZoneInfo(tz)).date())
    open_codes = [c for c in db.scalars(select(TicketStatus.code).where(TicketStatus.is_open.is_(True)))]

    def count(*w):
        return db.scalar(select(func.count()).select_from(Ticket).where(scope, *w)) or 0

    # ---- live operational metrics (current state, not range-bound) — all in ONE query
    open_q = Ticket.status_code.in_(open_codes)
    live_sla = and_(open_q, SLATracking.paused_at.is_(None))

    def n(cond):
        return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)
    row = db.execute(
        select(n(open_q), n(and_(Ticket.created_at >= today_start, Ticket.created_at < today_end)),
               n(and_(open_q, Ticket.assignee_id.is_(None))), n(and_(open_q, Priority.code.in_(["P1", "P2"]))),
               n(and_(live_sla, SLATracking.resolution_breached.is_(False), SLATracking.resolution_due_at >= now,
                      SLATracking.resolution_due_at < now + timedelta(hours=4))),
               n(and_(live_sla, Ticket.status_code != "RESOLVED",
                      (SLATracking.resolution_breached.is_(True)) | (SLATracking.resolution_due_at < now))),
               n(Ticket.status_code == "PENDING_EMPLOYEE"), n(Ticket.status_code == "PENDING_APPROVAL"),
               n(and_(Ticket.resolved_at >= today_start, Ticket.resolved_at < today_end)))
        .select_from(Ticket).join(Priority, Priority.id == Ticket.priority_id)
        .outerjoin(SLATracking, SLATracking.ticket_id == Ticket.id).where(scope)).one()
    live = dict(zip(["open", "new_today", "unassigned", "critical_high", "approaching_sla", "overdue",
                     "pending_employee", "pending_approval", "resolved_today"], (int(x or 0) for x in row)))

    # ---- historical metrics for the selected range (by creation date)
    in_range = and_(scope, Ticket.created_at >= range_start, Ticket.created_at < range_end)
    rng = db.scalars(select(Ticket).where(in_range)).all()
    total = len(rng)
    specs: dict = {}
    fr = [b for b in (_bm(db, t, t.first_response_at, specs) for t in rng) if b is not None]
    rs = [b for b in (_bm(db, t, t.resolved_at, specs) for t in rng) if b is not None]
    resolved_rows = [t for t in rng if t.resolved_at and t.sla]
    met = sum(1 for t in resolved_rows if not t.sla.resolution_breached)
    reopened = sum(1 for t in rng if t.reopen_count > 0)
    csat = db.execute(select(func.avg(SatisfactionRating.rating * 1.0), func.count())
                      .join(Ticket, Ticket.id == SatisfactionRating.ticket_id).where(in_range)).one()

    by_cat = db.execute(select(Category.name, func.count()).join(Ticket, Ticket.category_id == Category.id)
                        .where(in_range).group_by(Category.name).order_by(func.count().desc())).all()
    by_dept = db.execute(select(func.coalesce(Department.name, "Unassigned"), func.count())
                         .select_from(Ticket).outerjoin(Department, Department.id == Ticket.department_id)
                         .where(in_range).group_by(Department.name).order_by(func.count().desc())).all()
    by_prio = db.execute(select(Priority.code, func.count()).join(Ticket, Ticket.priority_id == Priority.id)
                         .where(in_range).group_by(Priority.code).order_by(Priority.code)).all()

    workload_rows = db.execute(
        select(User.id, User.full_name,
               func.count(Ticket.id),
               func.sum(case((Ticket.priority.has(Priority.code.in_(["P1", "P2"])), 1), else_=0)))
        .join(Ticket, Ticket.assignee_id == User.id)
        .where(scope, open_q).group_by(User.id, User.full_name).order_by(func.count(Ticket.id).desc())
    ).all()

    # Daily trend (created vs resolved), local dates
    days = (end - start).days + 1
    z = ZoneInfo(tz)
    created_by_day = {start + timedelta(days=i): 0 for i in range(days)}
    resolved_by_day = dict.fromkeys(created_by_day, 0)
    for t in rng:
        d = t.created_at.astimezone(z).date()
        if d in created_by_day:
            created_by_day[d] += 1
    for (ra,) in db.execute(select(Ticket.resolved_at).where(
            scope, Ticket.resolved_at >= range_start, Ticket.resolved_at < range_end)).all():
        d = ra.astimezone(z).date()
        if d in resolved_by_day:
            resolved_by_day[d] += 1

    return {
        "generated_at": now,
        "range": {"start": start, "end": end, "timezone": tz},
        "live": live,
        "historical": {
            "created": total,
            "avg_first_response_minutes": round(sum(fr) / len(fr)) if fr else None,
            "avg_resolution_minutes": round(sum(rs) / len(rs)) if rs else None,
            "sla_compliance_percent": round(met * 100 / len(resolved_rows), 1) if resolved_rows else None,
            "sla_measured": len(resolved_rows),
            "reopen_rate_percent": round(reopened * 100 / total, 1) if total else None,
            "csat_average": round(float(csat[0]), 2) if csat[0] is not None else None,
            "csat_responses": csat[1],
        },
        "by_category": [{"label": n, "value": c} for n, c in by_cat],
        "by_department": [{"label": n, "value": c} for n, c in by_dept],
        "by_priority": [{"label": n, "value": c} for n, c in by_prio],
        "workload": [{"user_id": i, "name": n, "open": c, "high": int(h or 0)} for i, n, c, h in workload_rows],
        "trend": [{"date": d, "created": created_by_day[d], "resolved": resolved_by_day[d]}
                  for d in created_by_day],
    }


def _bm(db: Session, t: Ticket, end: datetime | None, specs: dict) -> int | None:
    """Business minutes from creation to `end`; resolution time is net of SLA pauses."""
    if not end or not t.sla:
        return None
    if t.sla.calendar_id not in specs:
        specs[t.sla.calendar_id] = sla_svc.spec_for(db, t.sla.calendar_id)
    raw = business_minutes_between(t.created_at, end, specs[t.sla.calendar_id])
    return max(0, raw - (t.sla.paused_minutes if end == t.resolved_at else 0))


# ---------------------------------------------------------------- admin home (simple dashboard)
def admin_home(db: Session, p: Principal, tz: str) -> dict:
    """What needs attention now, my open work, and how the team is doing this week."""
    from app.services.staff import it_staff
    now = utcnow()
    vis = ticket_visibility_clause(p)
    open_codes = list(db.scalars(select(TicketStatus.code).where(TicketStatus.is_open.is_(True))))
    active = Ticket.status_code.in_([c for c in open_codes if c not in ("RESOLVED", "PENDING_EMPLOYEE")])

    rows = db.scalars(select(Ticket).outerjoin(SLATracking, SLATracking.ticket_id == Ticket.id)
                      .join(Priority, Priority.id == Ticket.priority_id)
                      .where(vis, active, (Ticket.assignee_id.is_(None)) | (SLATracking.resolution_breached.is_(True))
                             | (SLATracking.resolution_due_at < now + timedelta(hours=4))
                             | (Priority.code.in_(["P1", "P2"])))
                      .order_by(Priority.rank.asc(), SLATracking.resolution_due_at.asc()).limit(60)).all()

    def reason(t: Ticket) -> tuple[int, str, str]:
        s = t.sla
        paused = s is not None and s.paused_at is not None
        if s and not paused and (s.resolution_breached or s.resolution_due_at < now):
            return 0, "overdue", "Overdue"
        if t.assignee_id is None:
            return 1, "unassigned", "Needs an owner"
        if s and not paused and s.resolution_due_at < now + timedelta(hours=4):
            mins = max(1, int((s.resolution_due_at - now).total_seconds() // 60))
            return 2, "due", f"Due in {mins // 60}h {mins % 60}m" if mins >= 60 else f"Due in {mins}m"
        return 3, "high", "High priority"

    ranked = sorted(((reason(t), t) for t in rows), key=lambda x: (x[0][0], x[1].priority.rank, x[1].created_at))
    attention = [{
        "number": t.number, "subject": t.subject, "version": t.version, "priority": t.priority.code,
        "status": {"code": t.status.code, "name": t.status.name},
        "requester": t.requester.full_name, "requester_code": t.requester.employee_code,
        "assignee": t.assignee.full_name if t.assignee else None, "assignee_id": t.assignee_id,
        "created_at": t.created_at, "reason": r[1], "reason_label": r[2],
    } for r, t in ranked[:8]]

    my_open = db.scalar(select(func.count()).select_from(Ticket).where(
        vis, Ticket.assignee_id == p.id, Ticket.status_code.in_(open_codes), Ticket.status_code != "RESOLVED")) or 0

    week_start = now - timedelta(days=7)
    staff = it_staff(db)
    ids = [u.id for u in staff] or [-1]
    open_by = dict(db.execute(select(Ticket.assignee_id, func.count()).where(
        Ticket.assignee_id.in_(ids), Ticket.status_code.in_(open_codes), Ticket.status_code != "RESOLVED")
        .group_by(Ticket.assignee_id)).all())
    resolved_by = dict(db.execute(select(Ticket.assignee_id, func.count()).where(
        Ticket.assignee_id.in_(ids), Ticket.resolved_at >= week_start).group_by(Ticket.assignee_id)).all())
    rating_by = {a: (round(float(avg), 1), n) for a, avg, n in db.execute(
        select(Ticket.assignee_id, func.avg(SatisfactionRating.rating * 1.0), func.count())
        .join(Ticket, Ticket.id == SatisfactionRating.ticket_id)
        .where(Ticket.assignee_id.in_(ids), SatisfactionRating.created_at >= now - timedelta(days=30))
        .group_by(Ticket.assignee_id)).all()}
    team = sorted(({
        "user_id": u.id, "name": u.full_name, "employee_code": u.employee_code,
        "open": open_by.get(u.id, 0), "resolved_week": resolved_by.get(u.id, 0),
        "rating": rating_by.get(u.id, (None, 0))[0], "ratings": rating_by.get(u.id, (None, 0))[1],
        "is_me": u.id == p.id,
    } for u in staff), key=lambda x: (-x["resolved_week"], x["open"], x["name"]))
    return {"my_open": my_open, "attention": attention, "team": team,
            "attention_total": len(rows)}
