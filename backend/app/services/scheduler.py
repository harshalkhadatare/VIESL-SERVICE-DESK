"""Background jobs: SLA warnings, breach escalation, auto-closure and email outbox.

Runs in-process via asyncio in a single API instance. For multiple instances, set
ENABLE_SCHEDULER=false on all but one (or run `python -m app.worker`).
All jobs are idempotent (dedupe keys + flags) so overlapping runs are safe.
"""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import SLATracking, Ticket, TicketStatus, utcnow
from app.services import sla as sla_svc
from app.services.business_time import business_minutes_between
from app.services.notifications import deliver_pending_emails, notify
from app.services.settings_service import get_int
from app.services.staff import group_staff_ids
from app.services.tickets import add_history

log = logging.getLogger("servicedesk.scheduler")


def _leads(db: Session, group_id: int | None) -> list[int]:
    return group_staff_ids(db, group_id)


def run_sla_checks(db: Session, now=None) -> dict:
    now = now or utcnow()
    open_codes = [s.code for s in db.scalars(select(TicketStatus).where(TicketStatus.is_open.is_(True),
                                                                        TicketStatus.pauses_sla.is_(False)))]
    rows = db.execute(select(Ticket, SLATracking).join(SLATracking, SLATracking.ticket_id == Ticket.id)
                      .where(Ticket.status_code.in_(open_codes), SLATracking.paused_at.is_(None))).all()
    stats = {"warned": 0, "breached": 0, "response_breached": 0, "escalated_unassigned": 0}
    for t, sla in rows:
        # First-response breach
        if t.first_response_at is None and not sla.response_breached and now > sla.response_due_at:
            sla.response_breached = True
            stats["response_breached"] += 1
            add_history(db, t, "sla", None, "response target missed", None, internal=True)
        elapsed = sla_svc.elapsed_business_minutes(db, sla, now)
        pct = elapsed * 100 / max(1, sla.resolution_target_minutes)
        if pct >= sla.warning_percent and not sla.warning_sent and not sla.resolution_breached:
            sla.warning_sent = True
            stats["warned"] += 1
            target = t.assignee_id or None
            recipients = [target] if target else _leads(db, t.support_group_id)
            for uid in recipients:
                notify(db, uid, "sla_warning", f"{t.number} is approaching its SLA",
                       f"{int(pct)}% of the resolution target used.", t, dedupe_key=f"slawarn:{t.id}:{uid}")
        if elapsed > sla.resolution_target_minutes and not sla.resolution_breached:
            sla.resolution_breached = True
            sla.escalation_level += 1
            stats["breached"] += 1
            add_history(db, t, "sla", None, f"resolution breached; escalation level {sla.escalation_level}",
                        None, internal=True)
            for uid in set(_leads(db, t.support_group_id) + ([t.assignee_id] if t.assignee_id else [])):
                notify(db, uid, "sla_breached", f"SLA breached: {t.number} ({t.priority.code})", t.subject, t,
                       dedupe_key=f"slabreach:{t.id}:{uid}:{sla.escalation_level}")
        # Unassigned critical incidents escalate after 15 business minutes
        if t.assignee_id is None and t.priority.code == "P1" and sla.escalation_level == 0:
            spec = sla_svc.spec_for(db, sla.calendar_id)
            if business_minutes_between(sla.started_at, now, spec) >= 15:
                sla.escalation_level = 1
                stats["escalated_unassigned"] += 1
                add_history(db, t, "sla", None, "unassigned P1 escalated to leads", None, internal=True)
                for uid in _leads(db, t.support_group_id):
                    notify(db, uid, "sla_warning", f"Unassigned P1: {t.number}", t.subject, t,
                           dedupe_key=f"p1unassigned:{t.id}:{uid}")
    db.commit()
    return stats


def run_auto_close(db: Session, now=None) -> dict:
    """Reminder then auto-closure of resolved tickets. Protected categories are never auto-closed."""
    now = now or utcnow()
    close_days = get_int(db, "auto_close_after_days")
    remind_days = get_int(db, "auto_close_reminder_days")
    stats = {"reminded": 0, "closed": 0}
    if close_days <= 0:
        return stats
    rows = db.scalars(select(Ticket).where(Ticket.status_code == "RESOLVED", Ticket.resolved_at.isnot(None))).all()
    for t in rows:
        if t.category.is_protected:
            continue
        age = now - t.resolved_at
        if remind_days and age >= timedelta(days=remind_days) and age < timedelta(days=close_days):
            if notify(db, t.requester_id, "ticket_resolved", f"Please confirm {t.number}",
                      f"This ticket will close automatically after {close_days} days.", t,
                      dedupe_key=f"autoclose-remind:{t.id}:{t.reopen_count}"):
                stats["reminded"] += 1
        if age >= timedelta(days=close_days):
            t.status_code, t.closed_at, t.closure_reason = "CLOSED", now, "auto"
            add_history(db, t, "status", "RESOLVED", "CLOSED", None, f"Auto-closed after {close_days} days")
            notify(db, t.requester_id, "ticket_closed", f"{t.number} closed", "Closed automatically.", t,
                   dedupe_key=f"autoclose:{t.id}:{t.reopen_count}")
            stats["closed"] += 1
    db.commit()
    return stats


def run_all_jobs() -> None:
    with SessionLocal() as db:
        try:
            s1 = run_sla_checks(db)
            s2 = run_auto_close(db)
            sent = deliver_pending_emails(db)
            if any(s1.values()) or any(s2.values()) or sent:
                log.info("jobs sla=%s autoclose=%s emails=%s", s1, s2, sent)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("background job failed")


async def scheduler_loop(stop: asyncio.Event) -> None:
    interval = get_settings().scheduler_interval_seconds
    log.info("scheduler started interval=%ss", interval)
    while not stop.is_set():
        await asyncio.to_thread(run_all_jobs)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


JOBS_KEY = "jobs_last_run"


def run_jobs_once(db: Session) -> dict:
    s1 = run_sla_checks(db)
    s2 = run_auto_close(db)
    sent = deliver_pending_emails(db)
    return {"sla": s1, "auto_close": s2, "emails_sent": sent}


def maybe_run_jobs(db: Session, force: bool = False) -> dict | None:
    """Serverless replacement for the always-on loop: run the jobs if they haven't run for
    JOBS_MIN_INTERVAL_MINUTES. A compare-and-set on application_settings makes sure only one
    concurrent request actually runs them."""
    from sqlalchemy import update

    from app.models import ApplicationSetting
    now = utcnow()
    row = db.get(ApplicationSetting, JOBS_KEY)
    if row is None:
        db.add(ApplicationSetting(key=JOBS_KEY, value="1970-01-01T00:00:00+00:00",
                                  description="Last time background jobs ran (serverless mode)"))
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - created concurrently
            db.rollback()
        row = db.get(ApplicationSetting, JOBS_KEY)
    from datetime import datetime
    last = datetime.fromisoformat(row.value)
    if not force and now - last < timedelta(minutes=get_settings().jobs_min_interval_minutes):
        return None
    claimed = db.execute(update(ApplicationSetting).where(ApplicationSetting.key == JOBS_KEY,
                                                          ApplicationSetting.value == row.value)
                         .values(value=now.isoformat())).rowcount
    db.commit()
    if not claimed:
        return None
    result = run_jobs_once(db)
    log.info("serverless jobs ran: %s", result)
    return result
