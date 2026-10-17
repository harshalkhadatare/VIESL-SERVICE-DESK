"""In-app notifications with an email outbox.

Each notification has a unique dedupe_key so retries and repeated SLA checks never
produce duplicates. Email is queued (email_status='pending') only when the user's
preference allows it AND EMAIL_ENABLED is true; a background job delivers it with retries.
"""
import logging
import smtplib
import uuid
from abc import ABC, abstractmethod
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Notification, NotificationPreference, Ticket, User

log = logging.getLogger("servicedesk.notify")

EVENTS = {
    "ticket_created": "Ticket created", "ticket_assigned": "Ticket assigned", "status_changed": "Status changed",
    "comment_added": "New comment", "info_requested": "Information requested", "sla_warning": "SLA warning",
    "sla_breached": "SLA breached", "ticket_resolved": "Ticket resolved", "ticket_reopened": "Ticket reopened",
    "ticket_closed": "Ticket closed",
}
DEFAULT_EMAIL_EVENTS = {"info_requested", "ticket_resolved", "sla_breached", "ticket_assigned"}
MAX_EMAIL_ATTEMPTS = 5


def notify(db: Session, user_id: int | None, event: str, title: str, body: str | None = None,
           ticket: Ticket | None = None, dedupe_key: str | None = None) -> Notification | None:
    if not user_id:
        return None
    pref = db.get(NotificationPreference, (user_id, event))
    if pref is not None and not pref.in_app and not pref.email:
        return None
    key = dedupe_key or f"{event}:{ticket.id if ticket else 0}:{user_id}:{uuid.uuid4().hex}"
    if db.scalar(select(Notification.id).where(Notification.dedupe_key == key)):
        return None
    wants_email = pref.email if pref is not None else event in DEFAULT_EMAIL_EVENTS
    n = Notification(
        user_id=user_id, ticket_id=ticket.id if ticket else None, event=event, title=title[:200],
        body=(body or "")[:1000] or None, link=f"#/tickets/{ticket.number}" if ticket else None,
        dedupe_key=key[:120], email_status="pending" if (wants_email and get_settings().email_enabled) else "none",
    )
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:  # concurrent duplicate
        return None
    return n


# ---------------------------------------------------------------- email providers
class EmailProvider(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None: ...


class LogEmailProvider(EmailProvider):
    """Development provider: logs instead of sending."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info("[email:dev] to=%s subject=%s", to, subject)


class SmtpEmailProvider(EmailProvider):
    """SMTP relay provider. Not verified against a real relay in this release — test before enabling."""

    def __init__(self) -> None:
        self.s = get_settings()

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_username:
                smtp.login(self.s.smtp_username, self.s.smtp_password)
            smtp.send_message(msg)


def get_email_provider() -> EmailProvider:
    s = get_settings()
    return SmtpEmailProvider() if (s.email_enabled and s.smtp_host) else LogEmailProvider()


def deliver_pending_emails(db: Session, provider: EmailProvider | None = None, batch: int = 50) -> int:
    provider = provider or get_email_provider()
    rows = db.scalars(select(Notification).where(Notification.email_status == "pending")
                      .order_by(Notification.id).limit(batch)).all()
    sent = 0
    for n in rows:
        user = db.get(User, n.user_id)
        try:
            provider.send(user.email, f"[IT Service Desk] {n.title}", (n.body or n.title))
            n.email_status, sent = "sent", sent + 1
        except Exception as exc:  # noqa: BLE001 - provider errors are recorded, retried later
            n.email_attempts += 1
            n.email_last_error = str(exc)[:500]
            if n.email_attempts >= MAX_EMAIL_ATTEMPTS:
                n.email_status = "failed"
            log.warning("email delivery failed id=%s attempt=%s", n.id, n.email_attempts)
    db.commit()
    return sent
