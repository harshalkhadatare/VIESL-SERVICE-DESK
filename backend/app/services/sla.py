"""SLA engine: start, pause/resume, priority changes and breach evaluation.

Rules
- Targets are business minutes from the configured SLAPolicy (category-specific beats generic).
- Due dates are always derived from the ORIGINAL start time plus paused time, so changing
  status or priority never silently resets the clock.
- Time spent in statuses with pauses_sla=True is excluded (e.g. Pending Employee, Resolved).
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessCalendar, SLAPolicy, SLATracking, Ticket, TicketStatus, utcnow
from app.services.business_time import CalendarSpec, add_business_minutes, business_minutes_between

FALLBACK_TARGETS = {"P1": (30, 240), "P2": (60, 480), "P3": (240, 1440), "P4": (480, 2880)}


def _calendar(db: Session, calendar_id: int | None = None) -> BusinessCalendar:
    if calendar_id:
        cal = db.get(BusinessCalendar, calendar_id)
        if cal:
            return cal
    cal = db.scalar(select(BusinessCalendar).where(BusinessCalendar.is_default.is_(True)))
    if not cal:
        raise RuntimeError("No default business calendar configured")
    return cal


def resolve_policy(db: Session, priority_id: int, category_id: int) -> SLAPolicy | None:
    rows = db.scalars(
        select(SLAPolicy).where(SLAPolicy.priority_id == priority_id, SLAPolicy.is_active.is_(True),
                                (SLAPolicy.category_id == category_id) | (SLAPolicy.category_id.is_(None)))
    ).all()
    specific = [p for p in rows if p.category_id == category_id]
    return (specific or rows or [None])[0]


def spec_for(db: Session, calendar_id: int) -> CalendarSpec:
    return CalendarSpec.from_model(_calendar(db, calendar_id))


def _apply_targets(db: Session, sla: SLATracking, ticket: Ticket) -> None:
    policy = resolve_policy(db, ticket.priority_id, ticket.category_id)
    if policy:
        sla.policy_id = policy.id
        sla.calendar_id = policy.calendar_id
        sla.response_target_minutes = policy.response_minutes
        sla.resolution_target_minutes = policy.resolution_minutes
        sla.warning_percent = policy.warning_percent
    else:
        r, s = FALLBACK_TARGETS.get(ticket.priority.code if ticket.priority else "P3", (240, 1440))
        sla.policy_id = None
        sla.calendar_id = sla.calendar_id or _calendar(db).id
        sla.response_target_minutes, sla.resolution_target_minutes = r, s
    recompute_due(db, sla)


def recompute_due(db: Session, sla: SLATracking) -> None:
    spec = spec_for(db, sla.calendar_id)
    sla.response_due_at = add_business_minutes(sla.started_at, sla.response_target_minutes, spec)
    sla.resolution_due_at = add_business_minutes(
        sla.started_at, sla.resolution_target_minutes + sla.paused_minutes, spec)


def start_sla(db: Session, ticket: Ticket, now: datetime | None = None) -> SLATracking:
    now = now or utcnow()
    sla = SLATracking(ticket_id=ticket.id, started_at=now, calendar_id=_calendar(db).id,
                      response_target_minutes=1, resolution_target_minutes=1,
                      response_due_at=now, resolution_due_at=now, paused_minutes=0)
    _apply_targets(db, sla, ticket)
    db.add(sla)
    ticket.sla = sla
    return sla


def on_priority_change(db: Session, ticket: Ticket) -> None:
    """Re-target from the original start; elapsed time is preserved."""
    if ticket.sla:
        _apply_targets(db, ticket.sla, ticket)


def on_status_change(db: Session, ticket: Ticket, old_code: str, new_code: str, now: datetime | None = None) -> None:
    sla = ticket.sla
    if not sla:
        return
    now = now or utcnow()
    statuses = {s.code: s for s in db.scalars(select(TicketStatus)).all()}
    was_paused = statuses[old_code].pauses_sla if old_code in statuses else False
    now_paused = statuses[new_code].pauses_sla if new_code in statuses else False

    if not was_paused and now_paused and sla.paused_at is None:
        sla.paused_at = now
    elif was_paused and not now_paused and sla.paused_at is not None:
        spec = spec_for(db, sla.calendar_id)
        sla.paused_minutes += business_minutes_between(sla.paused_at, now, spec)
        sla.paused_at = None
        recompute_due(db, sla)

    if new_code == "RESOLVED" and elapsed_business_minutes(db, sla, now) > sla.resolution_target_minutes:
        sla.resolution_breached = True


def elapsed_business_minutes(db: Session, sla: SLATracking, now: datetime | None = None) -> int:
    """Business minutes counted against the resolution target (pauses excluded)."""
    now = now or utcnow()
    spec = spec_for(db, sla.calendar_id)
    ref = sla.paused_at or now
    return max(0, business_minutes_between(sla.started_at, ref, spec) - sla.paused_minutes)


def record_first_response(ticket: Ticket, now: datetime | None = None) -> None:
    now = now or utcnow()
    if ticket.first_response_at is None:
        ticket.first_response_at = now
        if ticket.sla and now > ticket.sla.response_due_at:
            ticket.sla.response_breached = True


def sla_snapshot(db: Session, ticket: Ticket, now: datetime | None = None) -> dict | None:
    """Computed view for the UI: remaining business minutes and state."""
    sla = ticket.sla
    if not sla:
        return None
    now = now or utcnow()
    spec = spec_for(db, sla.calendar_id)
    ref = sla.paused_at or now
    elapsed = max(0, business_minutes_between(sla.started_at, ref, spec) - sla.paused_minutes)
    target = sla.resolution_target_minutes
    stopped = ticket.status_code in ("RESOLVED", "CLOSED", "CANCELLED")
    if ticket.resolved_at and stopped:
        elapsed = max(0, business_minutes_between(sla.started_at, ticket.resolved_at, spec) - sla.paused_minutes)
    remaining = target - elapsed
    breached = sla.resolution_breached or (not stopped and now > sla.resolution_due_at and sla.paused_at is None)
    pct = min(100, round(elapsed * 100 / target)) if target else 0
    if stopped:
        state = "met" if not sla.resolution_breached else "breached"
    elif sla.paused_at:
        state = "paused"
    elif breached:
        state = "breached"
    elif pct >= sla.warning_percent:
        state = "at_risk"
    else:
        state = "on_track"
    return {
        "state": state, "percent_used": pct, "remaining_business_minutes": remaining,
        "response_due_at": sla.response_due_at, "resolution_due_at": sla.resolution_due_at,
        "response_target_minutes": sla.response_target_minutes,
        "resolution_target_minutes": target, "paused_minutes": sla.paused_minutes,
        "is_paused": sla.paused_at is not None, "response_breached": sla.response_breached,
        "resolution_breached": breached, "escalation_level": sla.escalation_level,
    }
