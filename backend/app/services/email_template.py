"""Notification email design.

Built for real email clients: table layout, inline styles, a 600 px card that shrinks on phones, and an animated GIF
per kind of update (embedded in the email, so it shows without "load images"). CSS animations in <style> are a
bonus for Apple Mail / iOS; every other client simply shows the static design.
"""
import html
from functools import lru_cache
from pathlib import Path

ART_DIR = Path(__file__).resolve().parents[1] / "assets" / "email"
DESK_NAME = {"it": "IT", "erp": "ERP-IT", "both": "IT + ERP-IT"}
STEPS = ["Submitted", "Assigned", "In progress", "Resolved", "Closed"]
STEP_OF = {"NEW": 0, "SUBMITTED": 0, "TRIAGED": 0, "ASSIGNED": 1, "IN_PROGRESS": 2, "PENDING_EMPLOYEE": 2,
           "PENDING_APPROVAL": 2, "PENDING_VENDOR": 2, "PENDING_CHANGE": 2, "REOPENED": 2, "RESOLVED": 3, "CLOSED": 4}
STATUS_COLORS = {"RESOLVED": ("#157a52", "#e3f4ec"), "CLOSED": ("#55657a", "#edf1f6"), "CANCELLED": ("#55657a", "#edf1f6"),
                 "PENDING_EMPLOYEE": ("#a15c07", "#fdf1dc"), "PENDING_VENDOR": ("#a15c07", "#fdf1dc"),
                 "PENDING_APPROVAL": ("#a15c07", "#fdf1dc"), "PENDING_CHANGE": ("#a15c07", "#fdf1dc"),
                 "REOPENED": ("#c2410c", "#fdecde")}
PRIO_COLORS = {"P1": ("#b42318", "#fdeceb"), "P2": ("#a15c07", "#fdf1dc"), "P3": ("#1d5fc4", "#e4eefb"),
               "P4": ("#55657a", "#edf1f6")}
ACCENT = {"received": "#1d5fc4", "bell": "#c4780a", "assigned": "#5a48d6", "working": "#1d5fc4", "question": "#c4780a",
          "reply": "#1d5fc4", "resolved": "#157a52", "reopened": "#d66216", "closed": "#4b5b72", "priority": "#b42318",
          "alert": "#b42318", "info": "#1d5fc4"}


@lru_cache(maxsize=32)
def art(name: str) -> bytes | None:
    p = ART_DIR / f"{name}.gif"
    return p.read_bytes() if p.exists() else None


def pick_art(event: str, title: str, ticket, is_staff_recipient: bool) -> str:
    t = (title or "").lower()
    if event == "ticket_created":
        return "bell" if is_staff_recipient else "received"
    if event == "ticket_assigned":
        return "assigned"
    if event == "info_requested":
        return "question"
    if event == "comment_added":
        return "reply"
    if event == "ticket_resolved":
        return "resolved"
    if event == "ticket_reopened":
        return "reopened"
    if event == "ticket_closed":
        return "closed"
    if event in ("sla_warning", "sla_breached"):
        return "alert"
    if "priority" in t:
        return "priority"
    if ticket is not None and ticket.status_code in ("CLOSED", "CANCELLED"):
        return "closed"
    if ticket is not None and ticket.status_code == "RESOLVED":
        return "resolved"
    return "working"


def headline(kind: str, ticket, is_staff_recipient: bool, title: str) -> tuple[str, str, str | None]:
    """(big headline, one friendly sentence, 'what happens next' tip) in plain language."""
    who = ticket.assignee.full_name if ticket is not None and ticket.assignee else None
    if "we did not receive a response" in (title or "").lower():
        if is_staff_recipient:
            return ("Ticket closed — no reply", "The employee did not reply within 3 days of the last message, "
                    "so the ticket was closed automatically.", None)
        return ("We're closing your ticket",
                "We have not received a response from you since our last message, so we are closing this ticket.",
                "If you still need help, please raise a new ticket and mention this ticket number. We'll be happy to help.")
    desk = DESK_NAME.get(getattr(ticket, "desk", None) or "", "IT")
    if is_staff_recipient:
        return {
            "bell": (f"New {desk} ticket", "A new ticket has been raised for your team.",
                     "Open it to accept it, or assign it to a colleague."),
            "assigned": ("Ticket assigned to you", "You are now the owner of this ticket.",
                         "Click “Accept & start” when you begin working on it."),
            "reply": ("New reply from the employee", "The employee has added a message to the ticket.", None),
            "reopened": ("Ticket reopened", "The employee says the problem is not solved yet.",
                         "Please take another look."),
            "alert": ("Attention needed", "This ticket needs action to stay within its target time.", None),
        }.get(kind, (title, "There is an update on this ticket.", None))
    return {
        "received": ("We've received your ticket", f"Your request is with the {desk} team. We'll email you at every step.",
                     "You don't need to do anything right now."),
        "assigned": ("Your ticket has an owner", f"{who} will take care of it." if who else "It is back in the IT queue.",
                     "They will contact you if they need anything."),
        "working": ("There's an update on your ticket", "IT has changed the status of your ticket.", None),
        "question": ("IT needs a little more information", "Please reply on the ticket so we can continue.",
                     "Work resumes automatically as soon as you answer."),
        "reply": ("New reply from IT", "Someone from IT has written to you.", "You can reply directly on the ticket."),
        "resolved": ("Good news — it's fixed!", "IT has marked your ticket as resolved.",
                     "Please click “Confirm it's fixed”, or “Still not working” within 7 days."),
        "closed": ("Your ticket is closed", "This ticket is now complete.",
                   "If the problem comes back, simply raise a new ticket."),
        "priority": ("Priority updated", "The priority of your ticket has changed.", None),
        "reopened": ("Your ticket was reopened", "It is back with the IT team.", None),
        "alert": ("Update on your ticket", title, None),
    }.get(kind, (title, "There is an update on your ticket.", None))


def _pill(text: str, fg: str, bg: str) -> str:
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;background:{bg};color:{fg};'
            f'font-size:12px;font-weight:700;letter-spacing:.2px;white-space:nowrap">{html.escape(text)}</span>')


def _row(label: str, value_html: str) -> str:
    return (f'<tr><td style="padding:9px 0;color:#74859b;font-size:13px;width:38%;vertical-align:top;'
            f'border-bottom:1px solid #eef2f7">{html.escape(label)}</td>'
            f'<td style="padding:9px 0;color:#13233a;font-size:14px;font-weight:600;border-bottom:1px solid #eef2f7">'
            f'{value_html}</td></tr>')


def _progress(ticket) -> str:
    if ticket is None or ticket.status_code == "CANCELLED":
        return ""
    cur = STEP_OF.get(ticket.status_code, 0)
    cells, labels = [], []
    for i, name in enumerate(STEPS):
        done, now = i < cur or (i == cur == 4), i == cur and cur != 4
        if done:
            dot = ('<div style="width:28px;height:28px;line-height:28px;border-radius:50%;background:#157a52;color:#fff;'
                   'font-size:15px;font-weight:700;margin:0 auto">&#10003;</div>')
        elif now:
            dot = ('<div class="sd-pulse" style="width:24px;height:24px;line-height:24px;border-radius:50%;background:#e4eefb;'
                   f'color:#1d5fc4;border:2px solid #1d5fc4;font-size:12px;font-weight:700;margin:0 auto">{i + 1}</div>')
        else:
            dot = ('<div style="width:24px;height:24px;line-height:24px;border-radius:50%;background:#ffffff;color:#9aa8ba;'
                   f'border:2px solid #d5deea;font-size:12px;font-weight:700;margin:0 auto">{i + 1}</div>')
        bar_l = "" if i == 0 else ("#157a52" if i <= cur else "#d5deea")
        bar_r = "" if i == 4 else ("#157a52" if i < cur else "#d5deea")
        cells.append(
            '<td width="20%" align="center" style="padding:0">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="50%" style="padding:0"><div style="height:3px;background:{bar_l or "transparent"}"></div></td>'
            f'<td style="padding:0">{dot}</td>'
            f'<td width="50%" style="padding:0"><div style="height:3px;background:{bar_r or "transparent"}"></div></td>'
            '</tr></table></td>')
        color = "#13233a" if i <= cur else "#9aa8ba"
        weight = "700" if i == cur else "600"
        labels.append(f'<td align="center" style="padding:6px 2px 0;font-size:11.5px;color:{color};font-weight:{weight}">'
                      f'{name}</td>')
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="margin:22px 0 4px;background:#f7f9fc;border:1px solid #e6edf6;border-radius:12px">'
            '<tr><td style="padding:16px 10px 12px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            f'<tr>{"".join(cells)}</tr><tr>{"".join(labels)}</tr></table></td></tr></table>')


def build(*, company: str, base_url: str, url: str, recipient_name: str, event: str, title: str, body: str | None,
          ticket, is_staff_recipient: bool) -> tuple[str, dict[str, bytes]]:
    """Returns (html, inline images {content-id: gif bytes})."""
    kind = pick_art(event, title, ticket, is_staff_recipient)
    accent = ACCENT.get(kind, "#1d5fc4")
    big, sentence, tip = headline(kind, ticket, is_staff_recipient, title)
    images: dict[str, bytes] = {}
    gif = art(kind)
    hero = ""
    if gif:
        images[f"sd-{kind}"] = gif
        hero = (f'<img class="sd-pop" src="cid:sd-{kind}" width="66" height="66" alt="" '
                'style="display:block;margin:0 auto 14px;width:66px;height:66px;border:0">')
    first = html.escape(recipient_name.split(" ")[0] if recipient_name else "there")
    e = html.escape

    details = progress = status_pill = ""
    if ticket is not None:
        sfg, sbg = STATUS_COLORS.get(ticket.status_code, ("#1d5fc4", "#e4eefb"))
        pfg, pbg = PRIO_COLORS.get(ticket.priority.code, PRIO_COLORS["P4"])
        status_pill = _pill(ticket.status.name, sfg, sbg)
        assigned = (f'{e(ticket.assignee.full_name)} <span style="color:#74859b;font-weight:500">'
                    f'({e(ticket.assignee.employee_code)})</span>' if ticket.assignee else
                    '<span style="color:#a15c07">Not assigned yet</span>')
        details = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 0">'
            + _row("Ticket number", f'<span style="font-family:Consolas,monospace;color:#1d5fc4">{e(ticket.number)}</span>')
            + _row("Subject", e(ticket.subject))
            + _row("IT department", _pill(DESK_NAME.get(ticket.desk, ticket.desk), "#1550ad", "#e4eefb"))
            + _row("Category", e(ticket.category.name) if ticket.category else "—")
            + _row("Status", status_pill)
            + _row("Priority", _pill(f"{ticket.priority.code} · {ticket.priority.name}", pfg, pbg))
            + _row("Assigned to", assigned)
            + _row("Raised by", f'{e(ticket.requester.full_name)} <span style="color:#74859b;font-weight:500">'
                                f'({e(ticket.requester.employee_code)})</span>')
            + '</table>')
        progress = _progress(ticket)

    body_box = ""
    if body:
        body_box = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 0">'
                    f'<tr><td style="background:#f7f9fc;border-left:4px solid {accent};border-radius:0 10px 10px 0;'
                    f'padding:14px 16px;color:#34465e;font-size:14px;line-height:1.6;white-space:pre-wrap">'
                    f'{e(body)}</td></tr></table>')
    tip_box = (f'<p style="margin:16px 0 0;font-size:13px;color:#4a5c74;line-height:1.5">'
               f'<span style="color:{accent};font-weight:700">What happens next?</span> {e(tip)}</p>') if tip else ""
    btn_label = "Open ticket" if is_staff_recipient else "View your ticket"
    button = (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px auto 4px"><tr>'
        f'<td align="center" bgcolor="{accent}" style="border-radius:10px">'
        f'<a href="{e(url)}" class="sd-btn" style="display:inline-block;padding:13px 30px;font-size:15px;font-weight:700;'
        f'color:#ffffff;text-decoration:none;border-radius:10px;background:{accent}">{btn_label} &rarr;</a>'
        '</td></tr></table>')
    preheader = e(f"{big} — {ticket.number + ': ' + ticket.subject if ticket is not None else title}")[:180]
    desk_line = (f' &middot; {e(DESK_NAME.get(ticket.desk, ""))}' if ticket is not None else "")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{e(title)}</title>
<style>
  @keyframes sdPop {{ 0% {{ transform: scale(.6); opacity: 0 }} 70% {{ transform: scale(1.08); opacity: 1 }} 100% {{ transform: scale(1) }} }}
  @keyframes sdPulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(29,95,196,.45) }} 70% {{ box-shadow: 0 0 0 8px rgba(29,95,196,0) }} 100% {{ box-shadow: 0 0 0 0 rgba(29,95,196,0) }} }}
  @keyframes sdRise {{ from {{ transform: translateY(8px); opacity: 0 }} to {{ transform: none; opacity: 1 }} }}
  .sd-pop {{ animation: sdPop .7s ease-out both; }}
  .sd-pulse {{ animation: sdPulse 1.8s ease-out infinite; }}
  .sd-card {{ animation: sdRise .6s ease-out both; }}
  .sd-btn:hover {{ filter: brightness(1.08); }}
  @media (max-width: 620px) {{ .sd-pad {{ padding-left: 18px !important; padding-right: 18px !important; }}
    .sd-h1 {{ font-size: 22px !important; }} }}
  @media (prefers-reduced-motion: reduce) {{ .sd-pop, .sd-pulse, .sd-card {{ animation: none !important; }} }}
</style></head>
<body style="margin:0;padding:0;background:#eef3f9;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#eef3f9">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef3f9">
<tr><td align="center" style="padding:28px 12px">
  <table role="presentation" class="sd-card" width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;
                border:1px solid #dfe7f1;box-shadow:0 6px 24px rgba(11,37,69,.08);
                font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
    <tr><td style="background:#0b2545;background-image:linear-gradient(120deg,#0b2545,#1d5fc4);padding:18px 28px" class="sd-pad">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td style="color:#ffffff;font-size:16px;font-weight:700">{e(company)}</td>
        <td align="right" style="color:#bcd7ff;font-size:12px;white-space:nowrap">IT Service Desk{desk_line}</td>
      </tr></table></td></tr>
    <tr><td style="height:4px;background:{accent};font-size:0;line-height:0">&nbsp;</td></tr>
    <tr><td class="sd-pad" style="padding:30px 36px 8px;text-align:center">
      {hero}
      <div style="font-size:14px;color:#74859b">Hi {first},</div>
      <h1 class="sd-h1" style="margin:6px 0 8px;font-size:25px;line-height:1.25;color:#0b2545;font-weight:800">{e(big)}</h1>
      <div style="font-size:15px;color:#4a5c74;line-height:1.5">{e(sentence)}</div>
      {f'<div style="margin-top:12px">{status_pill}</div>' if status_pill else ''}
    </td></tr>
    <tr><td class="sd-pad" style="padding:6px 36px 30px">
      {progress}
      {body_box}
      {details}
      {tip_box}
      {button}
    </td></tr>
    <tr><td class="sd-pad" style="background:#f7f9fc;border-top:1px solid #e6edf6;padding:16px 36px;font-size:12px;color:#74859b;line-height:1.6;text-align:center">
      This is an automatic message from the {e(company)} IT Service Desk.<br>
      Please reply on the ticket in the portal — replies to this email are not read.<br>
      <a href="{e(base_url)}" style="color:#1d5fc4;text-decoration:none">{e(base_url.replace('https://', ''))}</a>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""
    return page, images
