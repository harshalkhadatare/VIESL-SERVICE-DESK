"""Priority matrix lookup and rule-based routing / auto-assignment."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AutomationExecutionLog, AutomationRule, Priority, PriorityMatrix, SupportGroup, SupportGroupMember, Ticket,
)

OPEN_WORK_STATUSES = ("ASSIGNED", "IN_PROGRESS", "REOPENED", "PENDING_VENDOR", "PENDING_CHANGE", "TRIAGED")


def priority_for(db: Session, impact: int, urgency: int) -> Priority:
    row = db.scalar(select(PriorityMatrix).where(PriorityMatrix.impact == impact, PriorityMatrix.urgency == urgency))
    if row:
        return db.get(Priority, row.priority_id)
    # Fallback when matrix incomplete: P(min(impact+urgency-1, 4))
    code = f"P{min(4, max(1, impact + urgency - 1))}"
    return db.scalar(select(Priority).where(Priority.code == code))


def _rule_matches(rule: AutomationRule, t: Ticket, erp_module: str | None) -> bool:
    checks = [
        (rule.match_category_id, t.category_id), (rule.match_subcategory_id, t.subcategory_id),
        (rule.match_department_id, t.department_id), (rule.match_location_id, t.location_id),
        (rule.match_priority_id, t.priority_id),
    ]
    if any(want is not None and want != have for want, have in checks):
        return False
    if rule.match_erp_module and (erp_module or "").lower() != rule.match_erp_module.lower():
        return False
    return True


def _eligible_members(db: Session, group_id: int) -> list[SupportGroupMember]:
    return list(db.scalars(
        select(SupportGroupMember).where(SupportGroupMember.group_id == group_id,
                                         SupportGroupMember.is_available.is_(True))
        .order_by(SupportGroupMember.user_id)
    ).all())


def pick_engineer(db: Session, group: SupportGroup, strategy: str) -> int | None:
    members = [m for m in _eligible_members(db, group.id) if m.user.is_active]
    # Leads coordinate the queue; auto-assign to them only if nobody else is available
    members = [m for m in members if not m.is_lead] or members
    if not members:
        return None
    if strategy == "least_loaded":
        ids = [m.user_id for m in members]
        loads = dict(db.execute(
            select(Ticket.assignee_id, func.count()).where(Ticket.assignee_id.in_(ids),
                                                            Ticket.status_code.in_(OPEN_WORK_STATUSES))
            .group_by(Ticket.assignee_id)).all())
        return min(ids, key=lambda uid: (loads.get(uid, 0), uid))
    if strategy == "round_robin":
        ids = [m.user_id for m in members]
        last = group.last_assigned_user_id
        nxt = next((i for i in ids if last is None or i > last), ids[0])
        group.last_assigned_user_id = nxt
        return nxt
    return None


def route_ticket(db: Session, t: Ticket, erp_module: str | None = None) -> tuple[int | None, int | None, str]:
    """Returns (group_id, assignee_id, method). Logs every decision."""
    rules = db.scalars(select(AutomationRule).where(AutomationRule.is_active.is_(True))
                       .order_by(AutomationRule.sort_order, AutomationRule.id)).all()
    group_id, strategy, rule_id = None, "group_default", None
    for r in rules:
        if _rule_matches(r, t, erp_module):
            group_id, strategy, rule_id = r.target_group_id, r.assignment_strategy, r.id
            break
    if group_id is None and t.category and t.category.default_group_id:
        group_id = t.category.default_group_id
        db.add(AutomationExecutionLog(ticket_id=t.id, action="route", outcome="applied",
                                      detail=f"No rule matched; category default group {group_id}"))
    elif rule_id:
        db.add(AutomationExecutionLog(rule_id=rule_id, ticket_id=t.id, action="route", outcome="applied",
                                      detail=f"Routed to group {group_id}"))
    if group_id is None:
        db.add(AutomationExecutionLog(ticket_id=t.id, action="route", outcome="skipped",
                                      detail="No routing rule or default group; left for triage"))
        return None, None, "none"

    group = db.get(SupportGroup, group_id)
    eff = group.assignment_strategy if strategy == "group_default" else strategy
    assignee = pick_engineer(db, group, eff) if eff in ("round_robin", "least_loaded") else None
    if assignee:
        db.add(AutomationExecutionLog(rule_id=rule_id, ticket_id=t.id, action="auto_assign", outcome="applied",
                                      detail=f"{eff} -> user {assignee}"))
    return group_id, assignee, eff
