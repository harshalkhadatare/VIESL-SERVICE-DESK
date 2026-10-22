from datetime import timedelta

from sqlalchemy import select

from app.models import SLATracking, Ticket, TicketHistory, utcnow
from tests.conftest import EMAILS, SessionLocal, auth, category_id, make_ticket, user_id

API = "/api/v1/tickets"


def act(client, role, number, path, **body):
    return client.post(f"{API}/{number}/{path}", json=body, headers=auth(role))


def current(client, role, number):
    return client.get(f"{API}/{number}", headers=auth(role)).json()


# ---------------------------------------------------------------- creation
def test_create_sets_identity_number_priority_and_routing(client):
    t = make_ticket(client, code="ERP_APP", impact=1, urgency=2,
                    erp={"erp_module": "Procurement", "reference_no": "PO/77"})
    assert t["number"].startswith("IT-") and len(t["number"]) == 14
    assert t["requester"]["id"] == user_id(EMAILS["employee"])
    assert t["department"]["name"] == "Finance & Accounts"   # from profile, not client
    assert t["priority"]["code"] == "P2"                       # impact 1 + urgency 2
    assert t["support_group"]["name"] == "ERP Application Support"
    assert t["assignee"]["full_name"] in ("Amit Deshmukh", "Priya Nair")  # round robin within ERP team
    assert t["status"]["code"] == "ASSIGNED"
    assert t["erp"]["reference_no"] == "PO/77"
    assert t["sla"]["state"] == "on_track"


def test_cannot_spoof_requester_or_protected_fields(client):
    body = {"subject": "Spoof attempt", "description": "Trying to set protected fields",
            "category_id": category_id("QUERY"), "requester_id": 1, "status_code": "CLOSED"}
    r = client.post(API, json=body, headers=auth("employee"))
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"requester_id", "status_code"} <= fields


def test_validation_on_backend(client):
    r = client.post(API, json={"subject": "x", "description": "short", "category_id": 1, "impact": 9},
                    headers=auth("employee"))
    assert r.status_code == 422


def test_erp_fields_rejected_for_non_erp_category(client):
    r = client.post(API, headers=auth("employee"), json={
        "subject": "Laptop broken", "description": "Screen flickers constantly", "category_id": category_id("HARDWARE"),
        "erp": {"erp_module": "Finance & Accounts"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "business_rule"


def test_subcategory_must_match_category(client, db):
    from app.models import Subcategory
    wrong = db.scalar(select(Subcategory.id).where(Subcategory.category_id == category_id("PRINTER")))
    r = client.post(API, headers=auth("employee"), json={
        "subject": "Mismatch test", "description": "Subcategory from another category",
        "category_id": category_id("HARDWARE"), "subcategory_id": wrong})
    assert r.status_code == 422


def test_idempotency_key_prevents_duplicates(client):
    body = {"subject": "Idempotent create", "description": "Retry should not duplicate",
            "category_id": category_id("QUERY")}
    h = {**auth("employee"), "Idempotency-Key": "retry-abc-1"}
    a = client.post(API, json=body, headers=h).json()["number"]
    b = client.post(API, json=body, headers=h).json()["number"]
    assert a == b


def test_duplicate_detection(client):
    make_ticket(client, code="PRINTER", subject="Finance floor printer jammed again")
    r = client.post(f"{API}/duplicate-check", headers=auth("employee"),
                    json={"subject": "Finance printer jammed", "category_id": category_id("PRINTER")})
    assert r.status_code == 200 and len(r.json()) >= 1


def test_sequential_numbers_unique(client):
    nums = {make_ticket(client, code="QUERY")["number"] for _ in range(5)}
    assert len(nums) == 5


# ---------------------------------------------------------------- visibility
def test_other_employee_gets_404_not_403(client):
    t = make_ticket(client)
    assert client.get(f"{API}/{t['number']}", headers=auth("employee2")).status_code == 404


def test_every_it_admin_can_see_every_ticket(client):
    t = make_ticket(client, code="ERP_APP")
    for role in ("admin", "erp_admin", "infra_admin", "sd_admin"):
        assert client.get(f"{API}/{t['number']}", headers=auth(role)).status_code == 200


def test_list_is_scoped_for_employees(client):
    make_ticket(client, role="employee2", code="QUERY", subject="Belongs to Manoj only")
    assert client.get(API, params={"q": "Belongs to Manoj"}, headers=auth("employee")).json()["total"] == 0
    assert client.get(API, params={"q": "Belongs to Manoj"}, headers=auth("admin")).json()["total"] >= 1


def test_list_items_include_version_and_assignee(client):
    t = make_ticket(client, code="ERP_APP")
    item = client.get(API, params={"q": t["number"]}, headers=auth("admin")).json()["items"][0]
    assert item["version"] == t["version"] and item["assignee_id"] == t["assignee"]["id"]


# ---------------------------------------------------------------- lifecycle
def _erp(client):
    t = make_ticket(client, code="ERP_APP")
    return t, ("erp_admin" if t["assignee"]["full_name"] == "Amit Deshmukh" else "erp_admin2")


def test_full_lifecycle_employee_to_closure(client):
    t, adm = _erp(client)
    n = t["number"]
    r = act(client, adm, n, "status", to_status="IN_PROGRESS", expected_version=t["version"])
    assert r.status_code == 200 and r.json()["first_response_at"]
    v = r.json()["version"]
    r = act(client, adm, n, "status", to_status="PENDING_EMPLOYEE", reason="Need screenshot", expected_version=v)
    assert r.json()["sla"]["is_paused"]
    assert act(client, "employee", n, "comments", body="Screenshot attached").status_code == 201
    d = current(client, adm, n)
    assert d["status"]["code"] == "IN_PROGRESS" and not d["sla"]["is_paused"]
    r = act(client, adm, n, "status", to_status="RESOLVED", resolution_notes="Cleared cached workflow.",
            root_cause="Stale workflow cache", expected_version=d["version"])
    assert r.status_code == 200 and r.json()["resolved_at"]
    d = current(client, "employee", n)
    assert d["root_cause"] is None  # internal field hidden from employee
    assert {"CLOSED", "REOPENED"} <= {s["code"] for s in d["allowed_transitions"]}
    r = act(client, "employee", n, "status", to_status="CLOSED", expected_version=d["version"])
    assert r.status_code == 200 and r.json()["closure_reason"] == "confirmed"
    assert act(client, "employee", n, "rating", rating=5, comment="Quick fix").status_code == 201
    assert act(client, "employee", n, "rating", rating=4).status_code == 409
    hist = client.get(f"{API}/{n}/history", headers=auth(adm)).json()
    fields = [(h["field"], h["new_value"]) for h in hist]
    assert ("status", "CLOSED") in fields and ("status", "RESOLVED") in fields


def test_invalid_transition_rejected(client):
    t, adm = _erp(client)
    assert act(client, adm, t["number"], "status", to_status="CLOSED", expected_version=t["version"]).status_code == 422


def test_employee_cannot_resolve_own_ticket(client):
    t = make_ticket(client)
    r = act(client, "employee", t["number"], "status", to_status="RESOLVED", resolution_notes="I fixed it myself",
            expected_version=t["version"])
    assert r.status_code == 422


def test_resolve_requires_notes(client):
    t, adm = _erp(client)
    assert act(client, adm, t["number"], "status", to_status="RESOLVED",
               expected_version=t["version"]).status_code == 422


def test_reason_required_for_pending_employee(client):
    t, adm = _erp(client)
    assert act(client, adm, t["number"], "status", to_status="PENDING_EMPLOYEE",
               expected_version=t["version"]).status_code == 422


def test_stale_version_conflict(client):
    t, adm = _erp(client)
    assert act(client, adm, t["number"], "status", to_status="IN_PROGRESS",
               expected_version=t["version"]).status_code == 200
    r = act(client, "admin", t["number"], "status", to_status="PENDING_VENDOR", reason="Vendor",
            expected_version=t["version"])
    assert r.status_code == 409


def test_requester_cannot_reopen_after_window(client):
    t, adm = _erp(client)
    act(client, adm, t["number"], "status", to_status="RESOLVED", resolution_notes="Fixed the configuration.",
        expected_version=t["version"])
    with SessionLocal() as db:
        row = db.scalar(select(Ticket).where(Ticket.number == t["number"]))
        row.resolved_at = utcnow() - timedelta(days=30)
        db.commit()
    d = current(client, "employee", t["number"])
    assert "REOPENED" not in {s["code"] for s in d["allowed_transitions"]}
    r = act(client, "employee", t["number"], "status", to_status="REOPENED", reason="Still broken",
            expected_version=d["version"])
    assert r.status_code == 422


def test_reopen_within_window_counts(client):
    t, adm = _erp(client)
    d = act(client, adm, t["number"], "status", to_status="RESOLVED", resolution_notes="Fixed the configuration.",
            expected_version=t["version"]).json()
    d = act(client, "employee", t["number"], "status", to_status="REOPENED", reason="Error is back",
            expected_version=d["version"]).json()
    assert d["status"]["code"] == "REOPENED" and d["reopen_count"] == 1 and d["resolved_at"] is None


def test_requester_can_cancel_queued_ticket(client):
    t = make_ticket(client, code="QUERY")  # Service Desk team is manual => stays SUBMITTED
    assert t["status"]["code"] == "SUBMITTED"
    r = act(client, "employee", t["number"], "status", to_status="CANCELLED", reason="Not needed anymore",
            expected_version=t["version"])
    assert r.status_code == 200 and r.json()["closed_at"]


# ---------------------------------------------------------------- comments & internal notes
def test_internal_notes_hidden_from_employee(client):
    t, adm = _erp(client)
    assert act(client, adm, t["number"], "comments", body="Internal analysis", is_internal=True).status_code == 201
    assert act(client, adm, t["number"], "comments", body="Public reply").status_code == 201
    emp = client.get(f"{API}/{t['number']}/comments", headers=auth("employee")).json()
    staff = client.get(f"{API}/{t['number']}/comments", headers=auth(adm)).json()
    assert [c["body"] for c in emp] == ["Public reply"]
    assert len(staff) == 2


def test_employee_cannot_write_internal_note(client):
    t = make_ticket(client)
    assert act(client, "employee", t["number"], "comments", body="sneaky", is_internal=True).status_code == 403


# ---------------------------------------------------------------- assignment (⋮ menu) & priority
def test_admin_can_assign_to_any_it_admin(client):
    t = make_ticket(client, code="ERP_APP")
    target = user_id(EMAILS["infra_admin"])  # not in the ERP team — allowed
    r = act(client, "admin", t["number"], "assign", assignee_id=target, expected_version=t["version"])
    assert r.status_code == 200, r.text
    assert r.json()["assignee"]["full_name"] == "Rahul Kulkarni"
    assert r.json()["support_group"]["name"] == "ERP Application Support"  # team unchanged


def test_assignment_only_to_it_admins(client):
    t = make_ticket(client, code="QUERY")
    r = act(client, "admin", t["number"], "assign", assignee_id=user_id(EMAILS["employee2"]),
            expected_version=t["version"])
    assert r.status_code == 422


def test_employee_cannot_assign(client):
    t = make_ticket(client, code="QUERY")
    r = act(client, "employee", t["number"], "assign", assignee_id=user_id(EMAILS["admin"]),
            expected_version=t["version"])
    assert r.status_code == 403


def test_assign_moves_queued_ticket_to_assigned_and_can_unassign(client):
    t = make_ticket(client, code="QUERY")
    d = act(client, "sd_admin", t["number"], "assign", assignee_id=user_id(EMAILS["sd_admin"]),
            expected_version=t["version"]).json()
    assert d["status"]["code"] == "ASSIGNED"
    d = act(client, "sd_admin", t["number"], "assign", assignee_id=None, expected_version=d["version"]).json()
    assert d["assignee"] is None


def test_assign_can_move_team(client, db):
    from app.models import SupportGroup
    infra = db.scalar(select(SupportGroup.id).where(SupportGroup.code == "INFRA"))
    t = make_ticket(client, code="QUERY")
    d = act(client, "admin", t["number"], "assign", support_group_id=infra, assignee_id=None,
            reason="Network issue", expected_version=t["version"]).json()
    assert d["support_group"]["name"] == "Infrastructure & Network"


def test_it_admin_list(client):
    r = client.get("/api/v1/it-admins", headers=auth("admin"))
    names = [x["full_name"] for x in r.json()]
    assert r.status_code == 200 and "Rohan Mehta" in names and "Anjali Sharma" not in names
    assert client.get("/api/v1/it-admins", headers=auth("employee")).status_code == 403


def test_priority_change_keeps_sla_start(client):
    t = make_ticket(client, impact=3, urgency=3)
    assert t["priority"]["code"] == "P4"
    with SessionLocal() as db:
        tid = db.scalar(select(Ticket.id).where(Ticket.number == t["number"]))
        started = db.get(SLATracking, tid).started_at
    r = act(client, "admin", t["number"], "priority", impact=1, urgency=1, reason="Whole team blocked",
            expected_version=t["version"])
    assert r.status_code == 200 and r.json()["priority"]["code"] == "P1"
    with SessionLocal() as db:
        s = db.get(SLATracking, tid)
        assert s.started_at == started and s.resolution_target_minutes == 240
        h = db.scalars(select(TicketHistory).where(TicketHistory.ticket_id == tid,
                                                   TicketHistory.field == "priority")).all()
        assert h and h[-1].reason == "Whole team blocked"


def test_employee_cannot_change_priority(client):
    t = make_ticket(client)
    r = act(client, "employee", t["number"], "priority", impact=1, urgency=1, reason="Want it faster",
            expected_version=t["version"])
    assert r.status_code == 403


def test_accept_queued_ticket(client):
    t = make_ticket(client, code="QUERY")
    r = act(client, "sd_admin", t["number"], "accept", expected_version=t["version"])
    assert r.status_code == 200 and r.json()["status"]["code"] == "IN_PROGRESS"


def test_link_tickets_does_not_leak(client):
    a, _ = _erp(client)
    b = make_ticket(client, role="employee2", code="ERP_APP")
    r = client.post(f"{API}/{a['number']}/links", json={"target_number": b["number"], "relation_type": "related"},
                    headers=auth("admin"))
    assert r.status_code == 204
    assert current(client, "employee", a["number"])["relations"] == []
    assert len(current(client, "admin", a["number"])["relations"]) == 1


# ---------------------------------------------------------------- notifications show the assignee
def test_notifications_show_assigned_person(client):
    t = make_ticket(client, code="QUERY", subject="Notification assignee check")
    act(client, "admin", t["number"], "assign", assignee_id=user_id(EMAILS["sd_admin"]),
        expected_version=t["version"])
    items = client.get("/api/v1/notifications", headers=auth("employee")).json()["items"]
    mine = [n for n in items if n["ticket_number"] == t["number"]]
    assert mine and all(n["assignee_name"] == "Sneha Iyer" for n in mine)
    assert any("Sneha Iyer" in n["title"] for n in mine)            # "IT-… assigned to Sneha Iyer"
    staff = client.get("/api/v1/notifications", headers=auth("sd_admin")).json()["items"]
    assert any(n["ticket_number"] == t["number"] and "assigned to you" in n["title"] for n in staff)
