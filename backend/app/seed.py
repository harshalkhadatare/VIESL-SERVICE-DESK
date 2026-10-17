"""Seed reference data (all environments) and optional DEMO data (development only).

Usage:
    python -m app.seed                 # reference data only (idempotent)
    python -m app.seed --demo          # + fictional demo users/tickets (refused in production)

Demo users are fictional, use the reserved domain demo.example.com and are flagged is_demo=1.
Their password comes from DEMO_PASSWORD (default shown in README; change it).
"""
import argparse
import os
import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import (
    Announcement, ApplicationSetting, AutomationRule, BusinessCalendar, Category, Department, Holiday,
    KnowledgeArticle, Location, Notification, Permission, Priority, PriorityMatrix, Role, RolePermission,
    SatisfactionRating, SLAPolicy, StatusTransition, Subcategory, SupportGroup, SupportGroupMember, Ticket,
    TicketComment, TicketHistory, TicketStatus, User, UserRole, utcnow,
)
from app.schemas.tickets import ErpDetailIn, TicketCreate
from app.services import sla as sla_svc
from app.services.business_time import add_business_minutes
from app.services.settings_service import DEFAULTS

PERMISSIONS = {
    "ticket.create": "Raise tickets", "ticket.view_own": "View own tickets",
    "ticket.view_department": "View tickets of own department (explicit grant)",
    "ticket.view_group": "View tickets of own support groups / assigned", "ticket.view_all": "View all tickets",
    "ticket.view_internal": "Read internal notes (auditors)", "ticket.work": "Work on tickets",
    "ticket.accept": "Self-assign queued tickets", "ticket.assign": "Assign / reassign within led groups",
    "ticket.escalate": "Escalate to another group", "ticket.set_priority": "Change priority",
    "ticket.comment_internal": "Write internal notes", "ticket.link": "Link related/duplicate tickets",
    "ticket.manage_all": "Act on any ticket (admin)", "dashboard.ops": "IT operations dashboard",
    "report.export": "Export reports", "kb.view": "Read knowledge base", "kb.manage": "Author/review articles",
    "user.manage": "Manage users and roles", "audit.view": "View audit log", "settings.manage": "Manage settings",
}
_EMP = ["ticket.create", "ticket.view_own", "kb.view"]
_ENG = _EMP + ["ticket.view_group", "ticket.work", "ticket.accept", "ticket.escalate", "ticket.comment_internal",
               "ticket.link", "dashboard.ops"]
_LEAD = _ENG + ["ticket.assign", "ticket.set_priority", "report.export", "kb.manage"]
ROLES = {
    "employee": ("Employee", "Raise and track own tickets", _EMP),
    "dept_viewer": ("Department Viewer", "Explicit read access to own department's tickets",
                    _EMP + ["ticket.view_department"]),
    "it_engineer": ("IT Support Engineer", "Work tickets in assigned support groups", _ENG),
    "it_lead": ("IT Team Lead", "Assign, prioritise and oversee team tickets", _LEAD),
    "it_admin": ("IT Administrator", "Full configuration and user administration", list(PERMISSIONS)),
    "management": ("Management / Auditor", "Read-only dashboards, reports and audit",
                   _EMP + ["ticket.view_all", "ticket.view_internal", "dashboard.ops", "report.export",
                           "audit.view"]),
}
STATUSES = [  # code, name, is_open, pauses_sla
    ("NEW", "New", True, False), ("SUBMITTED", "Submitted", True, False), ("TRIAGED", "Triaged", True, False),
    ("ASSIGNED", "Assigned", True, False), ("IN_PROGRESS", "In Progress", True, False),
    ("PENDING_EMPLOYEE", "Pending Employee", True, True), ("PENDING_APPROVAL", "Pending Approval", True, True),
    ("PENDING_VENDOR", "Pending Vendor", True, False), ("PENDING_CHANGE", "Pending Change", True, False),
    ("RESOLVED", "Resolved", False, True), ("REOPENED", "Reopened", True, False),
    ("CLOSED", "Closed", False, True), ("CANCELLED", "Cancelled", False, True),
]
S, R, A = "staff", "requester", "any"
TRANSITIONS = [  # from, to, actor, requires_reason
    ("NEW", "SUBMITTED", S, False), ("NEW", "CANCELLED", A, True),
    ("SUBMITTED", "TRIAGED", S, False), ("SUBMITTED", "IN_PROGRESS", S, False),
    ("SUBMITTED", "PENDING_EMPLOYEE", S, True), ("SUBMITTED", "PENDING_APPROVAL", S, False),
    ("SUBMITTED", "CANCELLED", A, True),
    ("TRIAGED", "IN_PROGRESS", S, False), ("TRIAGED", "PENDING_EMPLOYEE", S, True),
    ("TRIAGED", "PENDING_APPROVAL", S, False), ("TRIAGED", "CANCELLED", A, True),
    ("ASSIGNED", "IN_PROGRESS", S, False), ("ASSIGNED", "PENDING_EMPLOYEE", S, True),
    ("ASSIGNED", "RESOLVED", S, False), ("ASSIGNED", "CANCELLED", S, True),
    ("IN_PROGRESS", "PENDING_EMPLOYEE", S, True), ("IN_PROGRESS", "PENDING_VENDOR", S, True),
    ("IN_PROGRESS", "PENDING_CHANGE", S, True), ("IN_PROGRESS", "PENDING_APPROVAL", S, True),
    ("IN_PROGRESS", "RESOLVED", S, False),
    ("PENDING_EMPLOYEE", "IN_PROGRESS", S, False), ("PENDING_EMPLOYEE", "RESOLVED", S, False),
    ("PENDING_EMPLOYEE", "CANCELLED", S, True),
    ("PENDING_APPROVAL", "IN_PROGRESS", S, False), ("PENDING_APPROVAL", "CANCELLED", S, True),
    ("PENDING_VENDOR", "IN_PROGRESS", S, False), ("PENDING_VENDOR", "RESOLVED", S, False),
    ("PENDING_CHANGE", "IN_PROGRESS", S, False), ("PENDING_CHANGE", "RESOLVED", S, False),
    ("RESOLVED", "CLOSED", A, False), ("RESOLVED", "REOPENED", A, True),
    ("REOPENED", "IN_PROGRESS", S, False), ("REOPENED", "RESOLVED", S, False),
]
PRIORITIES = [("P1", "Critical", 1, "Major outage or critical service down for many users"),
              ("P2", "High", 2, "Significant impact on a department or key business process"),
              ("P3", "Medium", 3, "Normal issue with a workaround or limited impact"),
              ("P4", "Low", 4, "Low-impact query, suggestion or routine request")]
SLA_TARGETS = {"P1": (30, 240), "P2": (60, 540), "P3": (240, 1620), "P4": (480, 2700)}  # business minutes
GROUPS = [("SD", "Service Desk", "manual"), ("ERP", "ERP Application Support", "round_robin"),
          ("INFRA", "Infrastructure & Network", "least_loaded"), ("EUC", "End-User Computing", "least_loaded"),
          ("SEC", "Information Security", "manual")]
# code, name, type, group, erp, approval, protected, subcategories
CATEGORIES = [
    ("ERP_APP", "ERP Application Issue", "incident", "ERP", True, False, False,
     ["Screen error", "Login / session", "Performance", "Workflow stuck"]),
    ("ERP_DATA", "ERP Data / Transaction Issue", "incident", "ERP", True, False, False,
     ["Posting failure", "Wrong values", "Duplicate entry", "Missing record"]),
    ("ERP_REPORT", "ERP Report / Excel Discrepancy", "incident", "ERP", True, False, False,
     ["Totals mismatch", "Export to Excel", "Missing columns", "Scheduled report"]),
    ("ACCESS", "User Account and Access Request", "service_request", "SD", False, True, False,
     ["New ERP role", "Shared folder access", "Application access", "Remove access"]),
    ("PASSWORD", "Password Reset / Account Unlock", "service_request", "SD", False, False, False,
     ["Windows / domain", "ERP", "Email"]),
    ("HARDWARE", "Hardware / Desktop / Laptop", "incident", "EUC", False, False, False,
     ["Laptop", "Desktop", "Monitor", "Keyboard / mouse", "Battery / charger"]),
    ("PRINTER", "Printer / Scanner", "incident", "EUC", False, False, False,
     ["Not printing", "Paper jam", "Scanner", "Toner / cartridge"]),
    ("NETWORK", "Network / Internet / VPN", "incident", "INFRA", False, False, False,
     ["No internet", "Slow network", "VPN", "Wi-Fi", "Site connectivity"]),
    ("EMAIL", "Email / Microsoft 365", "incident", "INFRA", False, False, False,
     ["Outlook", "Teams", "OneDrive / SharePoint", "Mailbox full", "Distribution list"]),
    ("SOFTWARE", "Software Installation", "service_request", "EUC", False, True, False,
     ["Licensed software", "Free / approved tool", "Update / upgrade"]),
    ("DB_INTEG", "Database / Integration", "incident", "ERP", False, False, False,
     ["Interface failure", "Data sync", "Backup / restore request"]),
    ("SECURITY", "Security Incident", "incident", "SEC", False, False, True,
     ["Phishing email", "Malware / virus", "Lost / stolen device", "Suspicious activity"]),
    ("ONBOARD", "New Employee IT Setup", "service_request", "SD", False, True, False,
     ["Laptop + accounts", "Accounts only"]),
    ("OFFBOARD", "Employee Exit / Access Revocation", "service_request", "SD", False, True, True,
     ["Planned exit", "Immediate revocation"]),
    ("ASSET_REQ", "IT Asset Request", "service_request", "EUC", False, True, False,
     ["Laptop", "Monitor", "Accessories", "Mobile / data card"]),
    ("CHANGE", "Change Request", "service_request", "INFRA", False, True, False,
     ["Configuration change", "Production change"]),
    ("ENHANCE", "New Feature / Enhancement", "service_request", "ERP", False, False, False,
     ["ERP enhancement", "New report", "Automation"]),
    ("SUGGEST", "Employee Suggestion", "service_request", "SD", False, False, False, ["IT improvement idea"]),
    ("QUERY", "General Query", "service_request", "SD", False, False, False, ["How-to", "Policy question"]),
    ("OTHER", "Other", "incident", "SD", False, False, False, []),
]


def _get_or_create(db: Session, model, lookup: dict, **values):
    obj = db.scalar(select(model).filter_by(**lookup))
    if obj:
        return obj, False
    obj = model(**lookup, **values)
    db.add(obj)
    db.flush()
    return obj, True


def seed_reference(db: Session) -> None:
    perms = {}
    for code, desc in PERMISSIONS.items():
        perms[code], _ = _get_or_create(db, Permission, {"code": code}, description=desc)
    for code, (name, desc, plist) in ROLES.items():
        role, _ = _get_or_create(db, Role, {"code": code}, name=name, description=desc)
        have = {rp.permission_id for rp in db.scalars(select(RolePermission).where(RolePermission.role_id == role.id))}
        for pc in plist:
            if perms[pc].id not in have:
                db.add(RolePermission(role_id=role.id, permission_id=perms[pc].id))
    for i, (code, name, is_open, pauses) in enumerate(STATUSES):
        _get_or_create(db, TicketStatus, {"code": code}, name=name, is_open=is_open, pauses_sla=pauses,
                       sort_order=i * 10)
    db.flush()
    for f, t, actor, reason in TRANSITIONS:
        _get_or_create(db, StatusTransition, {"from_code": f, "to_code": t, "actor": actor}, requires_reason=reason)
    prio = {}
    for code, name, rank, desc in PRIORITIES:
        prio[code], _ = _get_or_create(db, Priority, {"code": code}, name=name, rank=rank, description=desc)
    for i in (1, 2, 3):
        for u in (1, 2, 3):
            s = i + u
            code = "P1" if s == 2 else "P2" if s == 3 else "P3" if s == 4 else "P4"
            _get_or_create(db, PriorityMatrix, {"impact": i, "urgency": u}, priority_id=prio[code].id)
    cal, created = _get_or_create(db, BusinessCalendar, {"name": "Head Office (IST)"}, timezone="Asia/Kolkata",
                                  work_start=time(9, 30), work_end=time(18, 30), working_days="1111110",
                                  is_default=True)
    if created:  # national holidays only — add company/state holidays in admin configuration
        for d, n in [(date(2026, 1, 26), "Republic Day"), (date(2026, 8, 15), "Independence Day"),
                     (date(2026, 10, 2), "Gandhi Jayanti"), (date(2027, 1, 26), "Republic Day")]:
            db.add(Holiday(calendar_id=cal.id, holiday_date=d, name=n))
    for code, (resp, res) in SLA_TARGETS.items():
        _get_or_create(db, SLAPolicy, {"priority_id": prio[code].id, "category_id": None},
                       name=f"Standard {code}", calendar_id=cal.id, response_minutes=resp, resolution_minutes=res,
                       warning_percent=75)
    groups = {}
    for code, name, strat in GROUPS:
        groups[code], _ = _get_or_create(db, SupportGroup, {"code": code}, name=name, assignment_strategy=strat)
    for i, (code, name, ttype, g, erp, appr, prot, subs) in enumerate(CATEGORIES):
        cat, _ = _get_or_create(db, Category, {"code": code}, name=name, default_ticket_type=ttype,
                                default_group_id=groups[g].id, uses_erp_fields=erp, requires_approval=appr,
                                is_protected=prot, sort_order=i * 10)
        for s in subs:
            _get_or_create(db, Subcategory, {"category_id": cat.id, "name": s})
    sec = db.scalar(select(Category).where(Category.code == "SECURITY"))
    _get_or_create(db, SLAPolicy, {"priority_id": prio["P1"].id, "category_id": sec.id},
                   name="Security P1", calendar_id=cal.id, response_minutes=15, resolution_minutes=180,
                   warning_percent=60)
    if not db.scalar(select(AutomationRule.id)):
        net = db.scalar(select(Category).where(Category.code == "NETWORK"))
        db.add_all([
            AutomationRule(name="Critical network incidents to Infrastructure (least loaded)", sort_order=10,
                           match_category_id=net.id, match_priority_id=prio["P1"].id,
                           target_group_id=groups["INFRA"].id, assignment_strategy="least_loaded"),
            AutomationRule(name="Payroll ERP module to ERP support (round robin)", sort_order=20,
                           match_erp_module="HR & Payroll", target_group_id=groups["ERP"].id,
                           assignment_strategy="round_robin"),
            AutomationRule(name="Security incidents stay with InfoSec lead (manual)", sort_order=5,
                           match_category_id=sec.id, target_group_id=groups["SEC"].id, assignment_strategy="manual"),
        ])
    for k, (v, d) in DEFAULTS.items():
        _get_or_create(db, ApplicationSetting, {"key": k}, value=v, description=d)
    db.commit()


# ---------------------------------------------------------------------------- demo data
DEPTS = [("FIN", "Finance & Accounts"), ("PROC", "Procurement"), ("PROJ", "Projects"), ("SALES", "Sales & Rental"),
         ("STORE", "Stores & Logistics"), ("HR", "HR & Admin"), ("IT", "Information Technology"),
         ("MGMT", "Management")]
LOCS = [("PUN", "Pune — Head Office"), ("MUM", "Mumbai Branch"), ("BLR", "Bengaluru Branch"),
        ("NAG", "Nagpur Site Office")]
DEMO_USERS = [  # code, name, dept, loc, title, roles, groups [(code, lead)]
    ("D-ADM01", "Rohan Mehta", "IT", "PUN", "IT Administrator", ["it_admin"], []),
    ("D-MGT01", "Kavita Rao", "MGMT", "PUN", "Head — Finance & IT", ["management"], []),
    ("D-LED01", "Sanjay Patil", "IT", "PUN", "IT Lead — Applications", ["it_lead"],
     [("ERP", True), ("SD", True)]),
    ("D-LED02", "Neha Joshi", "IT", "PUN", "IT Lead — Infrastructure", ["it_lead"],
     [("INFRA", True), ("EUC", True), ("SEC", True)]),
    ("D-ENG01", "Amit Deshmukh", "IT", "PUN", "ERP Support Engineer", ["it_engineer"], [("ERP", False)]),
    ("D-ENG02", "Priya Nair", "IT", "MUM", "ERP Support Engineer", ["it_engineer"], [("ERP", False)]),
    ("D-ENG03", "Rahul Kulkarni", "IT", "PUN", "Network Engineer", ["it_engineer"],
     [("INFRA", False), ("EUC", False)]),
    ("D-ENG04", "Sneha Iyer", "IT", "BLR", "Service Desk Engineer", ["it_engineer"], [("SD", False), ("EUC", False)]),
    ("D-ENG05", "Vikram Singh", "IT", "PUN", "Systems & Security Engineer", ["it_engineer"],
     [("INFRA", False), ("SEC", False)]),
    ("D-EMP01", "Anjali Sharma", "FIN", "PUN", "Accounts Executive", ["employee"], []),
    ("D-EMP02", "Manoj Gupta", "PROC", "MUM", "Purchase Officer", ["employee"], []),
    ("D-EMP03", "Farhan Shaikh", "PROJ", "NAG", "Site Engineer", ["employee"], []),
    ("D-EMP04", "Pooja Kadam", "SALES", "PUN", "Rental Coordinator", ["employee"], []),
    ("D-EMP05", "Deepak Verma", "STORE", "BLR", "Stores Supervisor", ["employee"], []),
    ("D-EMP06", "Meera Pillai", "HR", "PUN", "HR Executive", ["employee", "dept_viewer"], []),
]
SAMPLES = {
    "ERP_APP": ["Purchase order approval screen shows error", "ERP logs out every few minutes",
                "Rental contract screen very slow", "Goods receipt workflow stuck at approval"],
    "ERP_DATA": ["Vendor invoice posting fails with ledger error", "Duplicate GRN created for same delivery",
                 "Equipment hire charges posted with wrong rate"],
    "ERP_REPORT": ["Stock ageing report totals do not match Excel", "Monthly rental billing report missing columns",
                   "Export to Excel truncates project codes"],
    "ACCESS": ["Need access to Procurement shared folder", "Add ERP role for site billing"],
    "PASSWORD": ["Domain account locked", "ERP password reset required"],
    "HARDWARE": ["Laptop battery drains within an hour", "Second monitor not detected", "Keyboard keys not working"],
    "PRINTER": ["Finance printer not printing", "Scanner not sending to email"],
    "NETWORK": ["VPN disconnects frequently from site", "Internet very slow at Nagpur site", "Wi-Fi not available in conference room"],
    "EMAIL": ["Outlook not syncing new emails", "Teams meetings audio drops", "Mailbox full warning"],
    "SOFTWARE": ["Install AutoCAD viewer", "Request for PDF editor licence"],
    "SECURITY": ["Received suspicious email asking for bank details"],
    "QUERY": ["How to configure email signature", "Policy for using personal USB drives"],
    "ENHANCE": ["Add equipment serial number to rental invoice print"],
}
KB = [
    ("ERP", "ERP_APP", "ERP session logs out frequently", "erp logout session timeout idle",
     "Users are signed out of the ERP after a few minutes, losing unsaved work.",
     "1. Close all ERP browser tabs except one.\n2. Clear the browser cache (Ctrl+Shift+Delete → Cached files).\n"
     "3. Make sure the system clock is correct (Settings → Time → Sync now).\n4. Sign in again.\n"
     "If it still happens, raise an ERP Application Issue and mention the time it occurred."),
    ("ERP", "ERP_REPORT", "Report totals differ from Excel export", "report excel mismatch totals rounding filter",
     "The on-screen ERP report total does not match the total after exporting to Excel.",
     "1. Check the same filters (date range, branch, project) are applied in both.\n"
     "2. In Excel, make sure no rows are hidden by an AutoFilter.\n3. Totals can differ by rounding; "
     "compare with 2 decimal places.\n4. Cancelled documents are excluded on screen but may appear in raw exports.\n"
     "Attach both files to a ticket if the difference remains."),
    ("NET", "NETWORK", "VPN keeps disconnecting", "vpn disconnect forticlient remote site",
     "VPN connection drops repeatedly when working remotely or from site offices.",
     "1. Switch to a stable network (avoid mobile hotspot with weak signal).\n2. Disconnect and reconnect the VPN client.\n"
     "3. Restart the laptop to clear stale network adapters.\n4. If on site, check whether colleagues have the same issue — "
     "if yes, raise a Network incident with Impact = Medium or High."),
    ("PRN", "PRINTER", "Printer shows offline", "printer offline not printing queue",
     "Documents stay in the print queue and the printer is shown as offline.",
     "1. Check the printer is powered on and shows no error on its panel.\n2. Open Settings → Printers, select the printer, "
     "Open queue → cancel stuck jobs.\n3. Remove and re-add the printer from \\\\printserver if it remains offline.\n"
     "4. Raise a Printer / Scanner ticket with the printer's asset tag if unresolved."),
    ("PWD", "PASSWORD", "Reset your domain password", "password reset locked account unlock",
     "You have forgotten your Windows password or your account is locked.",
     "1. Wait 15 minutes — accounts unlock automatically after the lockout period.\n2. Use the self-service password "
     "portal if enabled for your account.\n3. Otherwise raise a Password Reset ticket; the Service Desk will verify your "
     "identity by phone before resetting. IT will never ask for your password."),
    ("EML", "EMAIL", "Outlook not receiving new emails", "outlook sync email not receiving offline",
     "Outlook shows old emails only or displays 'Disconnected'.",
     "1. Check the status bar — click 'Work Offline' to toggle it off if enabled.\n2. Check webmail: if emails appear there, "
     "restart Outlook.\n3. If the mailbox is full, archive or delete large items.\n4. Raise an Email ticket if webmail is also affected."),
    ("SEC", "SECURITY", "How to report a phishing email", "phishing suspicious email security report",
     "You received an unexpected email asking for credentials, payments or bank details.",
     "1. Do not click links, open attachments or reply.\n2. Raise a Security Incident ticket immediately with a screenshot.\n"
     "3. If you already clicked or entered credentials, call the IT Service Desk at once and change your password.\n"
     "4. Delete the email after IT confirms."),
    ("ACC", "ACCESS", "Requesting access to a shared folder", "shared folder access permission request approval",
     "You need read or write access to a departmental shared folder.",
     "1. Raise a 'User Account and Access Request' ticket.\n2. Give the exact folder path and whether you need read or write.\n"
     "3. Your department head approves the request.\n4. Access is granted after approval; sign out and back in to apply it."),
]


def _principal(db: Session, u: User) -> Principal:
    m = db.scalars(select(SupportGroupMember).where(SupportGroupMember.user_id == u.id)).all()
    return Principal(user=u, permissions=u.permission_codes, roles=u.role_codes,
                     group_ids={x.group_id for x in m}, lead_group_ids={x.group_id for x in m if x.is_lead})


def _biz_time(d: datetime, rnd: random.Random) -> datetime:
    z = timezone(timedelta(hours=5, minutes=30))
    local = d.astimezone(z)
    while local.weekday() == 6:
        local -= timedelta(days=1)
    return local.replace(hour=rnd.randint(10, 17), minute=rnd.randint(0, 59), second=0,
                         microsecond=0).astimezone(timezone.utc)


def seed_demo(db: Session, n_tickets: int = 70) -> None:
    if get_settings().is_production:
        raise SystemExit("Refusing to load demo data in production.")
    if db.scalar(select(User.id).where(User.is_demo.is_(True))):
        print("Demo data already present — skipping.")
        return
    pw = hash_password(os.environ.get("DEMO_PASSWORD", "Vision@Demo2026"))
    depts = {c: _get_or_create(db, Department, {"code": c}, name=n)[0] for c, n in DEPTS}
    locs = {c: _get_or_create(db, Location, {"code": c}, name=n)[0] for c, n in LOCS}
    roles = {r.code: r for r in db.scalars(select(Role))}
    groups = {g.code: g for g in db.scalars(select(SupportGroup))}
    users: dict[str, User] = {}
    for code, name, d, l, title, rl, gl in DEMO_USERS:
        first, last = name.lower().split()
        u = User(employee_code=code, email=f"{first}.{last}@demo.example.com", full_name=name, job_title=title,
                 department_id=depts[d].id, location_id=locs[l].id, password_hash=pw, is_demo=True,
                 phone=f"+91 20 5555 {random.Random(code).randint(1000, 9999)}")
        db.add(u)
        db.flush()
        for r in rl:
            db.add(UserRole(user_id=u.id, role_id=roles[r].id))
        for g, lead in gl:
            db.add(SupportGroupMember(group_id=groups[g].id, user_id=u.id, is_lead=lead,
                                      skills="ERP" if g == "ERP" else None))
        users[code] = u
    db.flush()
    for u in users.values():
        db.refresh(u)

    admin = users["D-ADM01"]
    cats = {c.code: c for c in db.scalars(select(Category))}
    for _, cat, title, kw, prob, sol in KB:
        db.add(KnowledgeArticle(title=title, category_id=cats[cat].id, keywords=kw, problem=prob, solution=sol,
                                status="published", author_id=users["D-LED01"].id, reviewer_id=admin.id,
                                published_at=utcnow(), view_count=random.Random(title).randint(5, 120)))
    db.add(Announcement(title="Planned ERP maintenance (demo)",
                        body="ERP will be unavailable on Sunday 06:00–09:00 IST for patching. Save your work.",
                        severity="warning", created_by=admin.id, ends_at=utcnow() + timedelta(days=10)))
    db.add(Announcement(title="Beware of invoice-themed phishing (demo)",
                        body="Report suspicious emails using the Security Incident category. IT never asks for passwords.",
                        severity="info", created_by=admin.id, ends_at=utcnow() + timedelta(days=20)))
    db.commit()

    from app.services import tickets as tsvc
    rnd = random.Random(2026)
    employees = [users[c] for c in ("D-EMP01", "D-EMP02", "D-EMP03", "D-EMP04", "D-EMP05", "D-EMP06")]
    now = utcnow()
    created_times = sorted(_biz_time(now - timedelta(days=rnd.uniform(0.05, 27)), rnd) for _ in range(n_tickets))
    created_times = [c if c < now else now - timedelta(minutes=30) for c in created_times]
    cal = sla_svc._calendar(db)
    spec = sla_svc.CalendarSpec.from_model(cal)
    erp_mods = ["Finance & Accounts", "Procurement", "Inventory / Stores", "Equipment Rental", "Projects",
                "HR & Payroll"]

    for created in created_times:
        cat_code = rnd.choice(list(SAMPLES))
        cat = cats[cat_code]
        req = rnd.choice(employees)
        impact = rnd.choices([1, 2, 3], [1, 3, 6])[0]
        urgency = rnd.choices([1, 2, 3], [1, 4, 5])[0]
        subj = rnd.choice(SAMPLES[cat_code])
        erp = None
        if cat.uses_erp_fields:
            erp = ErpDetailIn(erp_module=rnd.choice(erp_mods), transaction_type="Document",
                              reference_no=f"DOC/{rnd.randint(10000, 99999)}",
                              error_message="Demo error text", workaround_available=rnd.random() < 0.4)
        data = TicketCreate(subject=subj, description=f"{subj}. (Demo data — fictional.) Started this morning; "
                            "please check.", category_id=cat.id,
                            subcategory_id=cat.subcategories[0].id if cat.subcategories else None,
                            impact=impact, urgency=urgency, erp=erp)
        t = tsvc.create_ticket(db, _principal(db, req), data)
        t.is_demo = True
        # Backdate creation and SLA start, then rebuild due dates
        t.created_at = t.updated_at = created
        t.sla.started_at = created
        sla_svc.recompute_due(db, t.sla)
        for h in db.scalars(select(TicketHistory).where(TicketHistory.ticket_id == t.id)):
            h.created_at = created
        if t.assigned_at:
            t.assigned_at = created
        db.flush()

        age_days = (now - created).total_seconds() / 86400
        if age_days < 1.5:
            weights = {"open_new": 30, "progress": 40, "pending": 15, "resolved": 15, "closed": 0}
        elif age_days < 5:
            weights = {"open_new": 3, "progress": 25, "pending": 15, "resolved": 32, "closed": 25}
        else:
            weights = {"open_new": 0, "progress": 4, "pending": 2, "resolved": 6, "closed": 88}
        outcome = rnd.choices(list(weights), list(weights.values()))[0]
        if outcome == "open_new":
            continue
        group_members = [m.user for m in db.scalars(select(SupportGroupMember).where(
            SupportGroupMember.group_id == t.support_group_id))] or [users["D-ENG04"]]
        eng = t.assignee or rnd.choice(group_members)
        t.assignee_id = eng.id
        t.assigned_at = t.assigned_at or created + timedelta(minutes=rnd.randint(5, 90))
        fr = add_business_minutes(created, rnd.randint(5, int(t.sla.response_target_minutes * 1.4)), spec)
        if fr > now:
            fr = now - timedelta(minutes=5)
        t.first_response_at = fr
        t.sla.response_breached = fr > t.sla.response_due_at
        db.add(TicketHistory(ticket_id=t.id, field="status", old_value=t.status_code, new_value="IN_PROGRESS",
                             actor_id=eng.id, created_at=fr))
        db.add(TicketComment(ticket_id=t.id, author_id=eng.id, created_at=fr,
                             body="Thanks for reporting. I am looking into this now."))
        if rnd.random() < 0.5:
            db.add(TicketComment(ticket_id=t.id, author_id=eng.id, is_internal=True, created_at=fr + timedelta(minutes=7),
                                 body="Internal: checked logs, likely related to last week's patch."))
        t.status_code = "IN_PROGRESS"
        if outcome == "progress":
            t.updated_at = fr
            continue
        if outcome == "pending":
            t.status_code = "PENDING_EMPLOYEE"
            t.sla.paused_at = fr + timedelta(minutes=10)
            db.add(TicketHistory(ticket_id=t.id, field="status", old_value="IN_PROGRESS",
                                 new_value="PENDING_EMPLOYEE", actor_id=eng.id, created_at=t.sla.paused_at,
                                 reason="Please share a screenshot of the error."))
            t.updated_at = t.sla.paused_at
            continue
        res_minutes = rnd.randint(30, int(t.sla.resolution_target_minutes * 1.3))
        resolved = add_business_minutes(created, res_minutes, spec)
        if resolved > now:
            resolved = now - timedelta(minutes=rnd.randint(5, 60))
        if resolved <= fr:
            resolved = fr + timedelta(minutes=20)
        t.resolved_at = resolved
        t.resolution_notes = "Issue identified and corrected. Verified with the user. (Demo)"
        t.root_cause = rnd.choice(["Configuration drift", "User profile corruption", "Data entry error",
                                   "Vendor-side outage", "Expired certificate"])
        t.sla.paused_at = resolved
        t.sla.resolution_breached = res_minutes > t.sla.resolution_target_minutes
        db.add(TicketHistory(ticket_id=t.id, field="status", old_value="IN_PROGRESS", new_value="RESOLVED",
                             actor_id=eng.id, created_at=resolved))
        t.status_code, t.updated_at = "RESOLVED", resolved
        if outcome == "closed":
            closed = min(now, resolved + timedelta(hours=rnd.randint(2, 40)))
            t.status_code, t.closed_at, t.closed_by, t.closure_reason = "CLOSED", closed, req.id, "confirmed"
            t.updated_at = closed
            db.add(TicketHistory(ticket_id=t.id, field="status", old_value="RESOLVED", new_value="CLOSED",
                                 actor_id=req.id, created_at=closed, reason="Confirmed fixed"))
            if rnd.random() < 0.7:
                db.add(SatisfactionRating(ticket_id=t.id, rating=rnd.choices([5, 4, 3, 2], [5, 4, 1, 0.5])[0],
                                          rated_by=req.id, created_at=closed))
            if rnd.random() < 0.08:
                t.reopen_count = 1
        db.flush()
    # Seed notifications are noise: mark all read except the latest few per user
    for n in db.scalars(select(Notification)):
        n.is_read = True
    db.commit()
    print(f"Demo data loaded: {len(users)} users, {n_tickets} tickets. All demo records are flagged is_demo.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="also load fictional demo data (development only)")
    args = ap.parse_args()
    with SessionLocal() as db:
        seed_reference(db)
        print("Reference data OK.")
        if args.demo:
            seed_demo(db)


if __name__ == "__main__":
    main()
