"""Per-person ticket marks: ★ starred, and 'New' (not opened yet by this IT administrator)."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.models import Ticket, TicketUserFlag, utcnow

NEW_WINDOW = timedelta(days=3)               # a ticket counts as "New" for 3 days unless you open it
NEW_STATUSES = ("NEW", "SUBMITTED", "TRIAGED", "ASSIGNED")


def flags_for(db: Session, user_id: int, ticket_ids: list[int]) -> dict[int, TicketUserFlag]:
    if not ticket_ids:
        return {}
    rows = db.scalars(select(TicketUserFlag).where(TicketUserFlag.user_id == user_id,
                                                   TicketUserFlag.ticket_id.in_(ticket_ids))).all()
    return {f.ticket_id: f for f in rows}


def is_new(p: Principal, t: Ticket, flag: TicketUserFlag | None, now: datetime | None = None) -> bool:
    """Green 'New' row for IT staff: recently raised, still waiting to be picked up, and not opened by me yet."""
    if not p.can("ticket.work") or t.requester_id == p.id:
        return False
    if flag is not None and flag.viewed_at is not None:
        return False
    return t.status_code in NEW_STATUSES and t.created_at >= (now or utcnow()) - NEW_WINDOW


def _get_or_create(db: Session, user_id: int, ticket_id: int) -> TicketUserFlag:
    f = db.get(TicketUserFlag, (ticket_id, user_id))
    if f is None:
        f = TicketUserFlag(ticket_id=ticket_id, user_id=user_id, starred=False)
        try:
            with db.begin_nested():
                db.add(f)
                db.flush()
        except IntegrityError:  # opened in two tabs at the same moment
            f = db.get(TicketUserFlag, (ticket_id, user_id))
    return f


def mark_viewed(db: Session, user_id: int, ticket_id: int) -> TicketUserFlag:
    f = _get_or_create(db, user_id, ticket_id)
    f.viewed_at = utcnow()
    db.commit()
    return f


def set_star(db: Session, user_id: int, ticket_id: int, starred: bool) -> TicketUserFlag:
    f = _get_or_create(db, user_id, ticket_id)
    f.starred = starred
    f.starred_at = utcnow() if starred else None
    db.commit()
    return f
