"""In-app notifications + email notifications.

Every notification is stored in the `notifications` table (the in-app bell). When email is
enabled (EMAIL_ENABLED=true and SMTP configured) the same row is queued for email
(`email_status='pending'`) and delivered:
  * immediately after the request that created it (see main.py), and
  * by the background scheduler, which retries failures (up to 5 attempts).

Each notification has a unique dedupe_key so retries and repeated SLA checks never
produce duplicates. Emails show the ticket's current status and the assigned person.
"""
import html
import logging
import smtplib
import ssl
import uuid
from abc import ABC, abstractmethod
from email.message import EmailMessage
from email.utils import formataddr

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
# Events that are emailed unless the user switched them off in notification_preferences
DEFAULT_EMAIL_EVENTS = set(EVENTS)
MAX_EMAIL_ATTEMPTS = 5
# Reserved / non-deliverable domains (demo data) are never emailed
_UNDELIVERABLE_SUFFIXES = (".example.com", ".example", ".invalid", ".test", ".localhost", "example.com")


def email_configured() -> bool:
    s = get_settings()
    return bool(s.email_enabled and s.smtp_host)


def _deliverable(user: User) -> bool:
    email = (user.email or "").lower()
    return bool(email) and not user.is_demo and not email.endswith(_UNDELIVERABLE_SUFFIXES)


def notify(db: Session, user_id: int | None, event: str, title: str, body: str | None = None,
           ticket: Ticket | None = None, dedupe_key: str | None = None, email: bool = True) -> Notification | None:
    """In-app notification, also emailed unless email=False (e.g. ticket deleted) or the user opted out."""
    if not user_id:
        return None
    pref = db.get(NotificationPreference, (user_id, event))
    if pref is not None and not pref.in_app and not pref.email:
        return None
    key = dedupe_key or f"{event}:{ticket.id if ticket else 0}:{user_id}:{uuid.uuid4().hex}"
    if db.scalar(select(Notification.id).where(Notification.dedupe_key == key)):
        return None
    wants_email = email and (pref.email if pref is not None else event in DEFAULT_EMAIL_EVENTS)
    status = "none"
    if wants_email and email_configured():
        user = db.get(User, user_id)
        status = "pending" if user and _deliverable(user) else "skipped"
    n = Notification(
        user_id=user_id, ticket_id=ticket.id if ticket else None, event=event, title=title[:200],
        body=(body or "")[:1000] or None, link=f"#/tickets/{ticket.number}" if ticket else None,
        dedupe_key=key[:120], email_status=status,
    )
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:  # concurrent duplicate
        return None
    return n


# ---------------------------------------------------------------- email content
def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:6px 0;color:#74859b;width:130px;vertical-align:top">{html.escape(label)}</td>'
            f'<td style="padding:6px 0;color:#13233a;font-weight:600">{value}</td></tr>')


def render_email(n: Notification, user: User, ticket: Ticket | None) -> tuple[str, str, str, dict[str, bytes]]:
    """Returns (subject, plain_text, html, inline_images)."""
    from app.services.email_template import DESK_NAME, build
    s = get_settings()
    base = s.app_base_url.rstrip("/")
    url = f"{base}/{n.link}" if n.link else base
    subject = f"[{ticket.number}] {n.title}" if ticket and ticket.number not in n.title else n.title
    assigned = ticket.assignee.label if ticket and ticket.assignee else "Not yet assigned"
    body = n.body
    if body and ticket:  # the details table already shows the assignee
        body = "\n".join(l for l in body.split("\n") if not l.startswith("Assigned to:")).strip() or None

    lines = [f"Hello {user.full_name},", "", n.title]
    if body:
        lines += ["", body]
    if ticket:
        lines += ["", f"Ticket:         {ticket.number}", f"Subject:        {ticket.subject}",
                  f"IT department:  {DESK_NAME.get(ticket.desk, ticket.desk)}",
                  f"Status:         {ticket.status.name}", f"Priority:       {ticket.priority.code} {ticket.priority.name}",
                  f"Assigned to:    {assigned}", f"Raised by:      {ticket.requester.label}"]
    lines += ["", f"Open the ticket: {url}", "", f"— {s.smtp_from_name}",
              "This is an automated message. Reply in the portal, not to this email."]
    text = "\n".join(lines)
    is_staff_recipient = bool(ticket) and user.id != ticket.requester_id
    page, images = build(company=s.company_name, base_url=base, url=url, recipient_name=user.full_name,
                         event=n.event, title=n.title, body=body, ticket=ticket, is_staff_recipient=is_staff_recipient)
    return subject[:200], text, page, images


# ---------------------------------------------------------------- providers
class EmailProvider(ABC):
    from contextlib import contextmanager as _cm

    @_cm
    def batch(self):
        """Send several emails over one connection (providers that support it override this)."""
        yield self

    @abstractmethod
    def send(self, to: str, subject: str, text: str, html_body: str | None = None,
             images: dict[str, bytes] | None = None) -> None: ...


class LogEmailProvider(EmailProvider):
    """Used when email is not configured: logs instead of sending."""

    def send(self, to: str, subject: str, text: str, html_body: str | None = None,
             images: dict[str, bytes] | None = None) -> None:
        log.info("[email:not-configured] to=%s subject=%s", to, subject)


class SmtpEmailProvider(EmailProvider):
    """SMTP relay (Office 365: smtp.office365.com:587 STARTTLS; Gmail: smtp.gmail.com:587 with an app password)."""

    def __init__(self) -> None:
        self.s = get_settings()
        self._conn = None

    def _connect(self):
        s = self.s
        ctx = ssl.create_default_context()
        if s.smtp_ssl:
            conn = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=ctx)
        else:
            conn = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
            if s.smtp_starttls:
                conn.starttls(context=ctx)
        if s.smtp_username:
            conn.login(s.smtp_username, s.smtp_password)
        return conn

    from contextlib import contextmanager as _cm2

    @_cm2
    def batch(self):
        """One sign-in to the mail server for the whole batch (Gmail sign-in takes ~1 s each time)."""
        self._conn = None
        try:
            yield self
        finally:
            if self._conn is not None:
                try:
                    self._conn.quit()
                except Exception:  # noqa: BLE001
                    pass
            self._conn = None

    def send(self, to: str, subject: str, text: str, html_body: str | None = None,
             images: dict[str, bytes] | None = None) -> None:
        msg = build_message(to, subject, text, html_body, images)
        if self._conn is None:        # inside batch(): reuse; otherwise one connection for this email
            conn = self._connect()
            try:
                conn.send_message(msg)
            finally:
                try:
                    conn.quit()
                except Exception:  # noqa: BLE001
                    pass
            return
        try:
            self._conn.send_message(msg)
        except (smtplib.SMTPServerDisconnected, OSError):
            self._conn = self._connect()          # server dropped the idle connection: reconnect once
            self._conn.send_message(msg)


def build_message(to: str, subject: str, text: str, html_body: str | None = None,
                  images: dict[str, bytes] | None = None) -> EmailMessage:
    """multipart/alternative (plain text + HTML); the animated GIFs ride along as inline parts (cid:)."""
    from email.utils import make_msgid
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((s.smtp_from_name, s.smtp_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(s.smtp_from.split("@")[-1] or None) if s.smtp_from else None)
    msg["Auto-Submitted"] = "auto-generated"          # tells mail servers not to send out-of-office replies
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
        if images:
            html_part = msg.get_payload()[1]
            for cid, data in images.items():
                html_part.add_related(data, maintype="image", subtype="gif", cid=f"<{cid}>",
                                      filename=f"{cid}.gif", disposition="inline")
    return msg


_provider_override: EmailProvider | None = None


def set_email_provider(p: EmailProvider | None) -> None:
    """Testing hook."""
    global _provider_override
    _provider_override = p


def get_email_provider() -> EmailProvider:
    if _provider_override:
        return _provider_override
    return SmtpEmailProvider() if email_configured() else LogEmailProvider()


def deliver_pending_emails(db: Session, provider: EmailProvider | None = None, batch: int = 50,
                           first_attempt_only: bool = False) -> int:
    """Send queued emails. first_attempt_only=True is used right after a request (fast path);
    the scheduler calls it without the flag to retry failures."""
    if not email_configured():
        return 0
    provider = provider or get_email_provider()
    stmt = select(Notification).where(Notification.email_status == "pending")
    if first_attempt_only:
        stmt = stmt.where(Notification.email_attempts == 0)
    rows = db.scalars(stmt.order_by(Notification.id).limit(batch)).all()
    sent = 0
    if not rows:
        return 0
    with provider.batch():
        for n in rows:
            user = db.get(User, n.user_id)
            ticket = db.get(Ticket, n.ticket_id) if n.ticket_id else None
            try:
                subject, text, page, images = render_email(n, user, ticket)
                provider.send(user.email, subject, text, page, images=images)
                n.email_status, sent = "sent", sent + 1
            except Exception as exc:  # noqa: BLE001 - provider errors are recorded, retried later
                n.email_attempts += 1
                n.email_last_error = str(exc)[:500]
                if n.email_attempts >= MAX_EMAIL_ATTEMPTS:
                    n.email_status = "failed"
                log.warning("email delivery failed id=%s attempt=%s error=%s", n.id, n.email_attempts, exc)
                if first_attempt_only:  # don't keep trying a broken relay; the scheduler retries later
                    break
    db.commit()
    return sent


def send_test_email(to: str, name: str) -> None:
    from app.services.email_template import build
    s = get_settings()
    base = s.app_base_url.rstrip("/")
    text = (f"Hello {name},\n\nThis is a test email from the {s.company_name} IT Service Desk.\n"
            f"If you received it, email notifications are working.\n\nPortal: {base}")
    page, images = build(company=s.company_name, base_url=base, url=base, recipient_name=name, event="ticket_resolved",
                         title="Email is working", body="This is a test email. If you can read it, ticket updates will "
                         "arrive in this mailbox.", ticket=None, is_staff_recipient=False)
    get_email_provider().send(to, "IT Service Desk — test email", text, page, images=images)
