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


def render_email(n: Notification, user: User, ticket: Ticket | None) -> tuple[str, str, str]:
    """Returns (subject, plain_text, html)."""
    s = get_settings()
    base = s.app_base_url.rstrip("/")
    url = f"{base}/{n.link}" if n.link else base
    subject = f"[{ticket.number}] {n.title}" if ticket and ticket.number not in n.title else n.title
    assigned = ticket.assignee.full_name if ticket and ticket.assignee else "Not yet assigned"
    body = n.body
    if body and ticket:  # the details table already shows the assignee
        body = "\n".join(l for l in body.split("\n") if not l.startswith("Assigned to:")).strip() or None

    lines = [f"Hello {user.full_name},", "", n.title]
    if body:
        lines += ["", body]
    if ticket:
        lines += ["", f"Ticket:       {ticket.number}", f"Subject:      {ticket.subject}",
                  f"Status:       {ticket.status.name}", f"Priority:     {ticket.priority.code} {ticket.priority.name}",
                  f"Assigned to:  {assigned}", f"Raised by:    {ticket.requester.full_name}"]
    lines += ["", f"Open the ticket: {url}", "", f"— {s.smtp_from_name}",
              "This is an automated message. Reply in the portal, not to this email."]
    text = "\n".join(lines)

    details = ""
    if ticket:
        details = ('<table role="presentation" style="width:100%;border-collapse:collapse;font-size:14px;'
                   'margin:18px 0 6px">'
                   + _row("Ticket", html.escape(ticket.number))
                   + _row("Subject", html.escape(ticket.subject))
                   + _row("Status", html.escape(ticket.status.name))
                   + _row("Priority", html.escape(f"{ticket.priority.code} · {ticket.priority.name}"))
                   + _row("Assigned to", html.escape(assigned))
                   + _row("Raised by", html.escape(ticket.requester.full_name))
                   + "</table>")
    body_html = (f'<p style="margin:12px 0 0;color:#4a5c74;white-space:pre-wrap">{html.escape(body)}</p>'
                 if body else "")
    page = f"""<!doctype html><html><body style="margin:0;background:#f4f7fb;font-family:Segoe UI,Arial,sans-serif">
<table role="presentation" width="100%" style="background:#f4f7fb;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="600" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #dfe7f1;border-radius:10px;overflow:hidden">
<tr><td style="background:#0b2545;padding:18px 24px;color:#ffffff">
  <div style="font-size:17px;font-weight:700">{html.escape(s.company_name)}</div>
  <div style="font-size:12px;color:#8ec5ff;margin-top:2px">IT Service Desk</div></td></tr>
<tr><td style="padding:24px">
  <p style="margin:0;color:#4a5c74;font-size:14px">Hello {html.escape(user.full_name)},</p>
  <h1 style="margin:10px 0 0;font-size:19px;color:#13233a">{html.escape(n.title)}</h1>
  {body_html}{details}
  <p style="margin:22px 0 4px"><a href="{html.escape(url)}" style="display:inline-block;background:#1d5fc4;color:#ffffff;
     text-decoration:none;padding:10px 18px;border-radius:7px;font-weight:600;font-size:14px">Open ticket</a></p>
</td></tr>
<tr><td style="padding:14px 24px;border-top:1px solid #dfe7f1;font-size:12px;color:#74859b">
  Automated message from the IT Service Desk. Please reply in the portal, not to this email.</td></tr>
</table></td></tr></table></body></html>"""
    return subject[:200], text, page


# ---------------------------------------------------------------- providers
class EmailProvider(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, text: str, html_body: str | None = None) -> None: ...


class LogEmailProvider(EmailProvider):
    """Used when email is not configured: logs instead of sending."""

    def send(self, to: str, subject: str, text: str, html_body: str | None = None) -> None:
        log.info("[email:not-configured] to=%s subject=%s", to, subject)


class SmtpEmailProvider(EmailProvider):
    """SMTP relay (Office 365: smtp.office365.com:587 STARTTLS; Gmail: smtp.gmail.com:587 with an app password)."""

    def __init__(self) -> None:
        self.s = get_settings()

    def send(self, to: str, subject: str, text: str, html_body: str | None = None) -> None:
        s = self.s
        msg = EmailMessage()
        msg["From"] = formataddr((s.smtp_from_name, s.smtp_from))
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        ctx = ssl.create_default_context()
        if s.smtp_ssl:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=ctx) as smtp:
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
                if s.smtp_starttls:
                    smtp.starttls(context=ctx)
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)


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
    for n in rows:
        user = db.get(User, n.user_id)
        ticket = db.get(Ticket, n.ticket_id) if n.ticket_id else None
        try:
            subject, text, page = render_email(n, user, ticket)
            provider.send(user.email, subject, text, page)
            n.email_status, sent = "sent", sent + 1
        except Exception as exc:  # noqa: BLE001 - provider errors are recorded, retried later
            n.email_attempts += 1
            n.email_last_error = str(exc)[:500]
            if n.email_attempts >= MAX_EMAIL_ATTEMPTS:
                n.email_status = "failed"
            log.warning("email delivery failed id=%s attempt=%s error=%s", n.id, n.email_attempts, exc)
            if first_attempt_only:  # don't make the user wait on a broken relay
                break
    db.commit()
    return sent


def send_test_email(to: str, name: str) -> None:
    s = get_settings()
    text = (f"Hello {name},\n\nThis is a test email from the {s.company_name} IT Service Desk.\n"
            f"If you received it, email notifications are working.\n\nPortal: {s.app_base_url}")
    page = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#13233a">'
            f'<div style="background:#0b2545;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;font-weight:700">'
            f'{html.escape(s.company_name)} · IT Service Desk</div>'
            f'<div style="border:1px solid #dfe7f1;border-top:0;padding:20px;border-radius:0 0 8px 8px">'
            f'<p>Hello {html.escape(name)},</p><p>This is a test email. If you received it, '
            f'<b>email notifications are working</b>.</p></div></div>')
    get_email_provider().send(to, "IT Service Desk — test email", text, page)
