from datetime import timedelta

from sqlalchemy import select

from app.models import SLATracking, Ticket, TicketHistory, utcnow
from tests.conftest import SessionLocal, auth, category_id, make_ticket, user_id

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
    assert t["requester"]["id"] == user_id("anjali.sharma@demo.example.com")
    assert t["department"]["name"] == "Finance & Accounts"   # from profile, not client
    assert t["priority"]["code"] == "P2"                       # impact 1 + urgency 2
    assert t["support_group"]["name"] == "ERP Application Support"
    assert t["assignee"] is not None and t["status"]["code"] == "ASSIGNED"  # round robin
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
    r = client.get(f"{API}/{t['number']}", headers=auth("employee2"))
    assert r.status_code == 404


def test_engineer_outside_group_cannot_see(client):
    t = make_ticket(client, code="ERP_APP")
    assert client.get(f"{API}/{t['number']}", headers=auth("infra_engineer")).status_code == 404
    assert client.get(f"{API}/{t['number']}", headers=auth("erp_engineer")).status_code == 200


def test_list_is_scoped(client):
    make_ticket(client, role="employee2", code="QUERY", subject="Belongs to Manoj only")
    items = client.get(API, params={"q": "Belongs to Manoj", "page_size": 100}, headers=auth("employee")).json()
    assert items["total"] == 0
    items = client.get(API, params={"q": "Belongs to Manoj"}, headers=auth("management")).json()
    assert items["total"] >= 1


def test_department_viewer_sees_department_tickets_only_when_granted(client):
    t = make_ticket(client, role="dept_viewer", code="QUERY")  # Meera (HR) has dept_viewer
    assert client.get(f"{API}/{t['number']}", headers=auth("dept_viewer")).status_code == 200
    assert client.get(f"{API}/{t['number']}", headers=auth("employee")).status_code == 404


# ---------------------------------------------------------------- lifecycle
def _erp_ticket_assigned_to_engineer(client):
    t = make_ticket(client, code="ERP_APP")
    eng = "erp_engineer" if t["assignee"]["id"] == user_id("amit.deshmukh@demo.example.com") else "erp_engineer2"
    return t, eng


def test_full_lifecycle_employee_to_closure(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    n = t["number"]
    r = act(client, eng, n, "status", to_status="IN_PROGRESS", expected_version=t["version"])
    assert r.status_code == 200 and r.json()["first_response_at"]
    v = r.json()["version"]
    r = act(client, eng, n, "status", to_status="PENDING_EMPLOYEE", reason="Need screenshot", expected_version=v)
    assert r.json()["sla"]["is_paused"]
    # Employee replies => automatically back to In Progress, SLA resumes
    assert act(client, "employee", n, "comments", body="Screenshot attached").status_code == 201
    d = current(client, eng, n)
    assert d["status"]["code"] == "IN_PROGRESS" and not d["sla"]["is_paused"]
    r = act(client, eng, n, "status", to_status="RESOLVED", resolution_notes="Cleared cached workflow.",
            root_cause="Stale workflow cache", expected_version=d["version"])
    assert r.status_code == 200 and r.json()["resolved_at"]
    d = current(client, "employee", n)
    assert d["root_cause"] is None  # internal field hidden from employee
    assert {"CLOSED", "REOPENED"} <= {s["code"] for s in d["allowed_transitions"]}
    r = act(client, "employee", n, "status", to_status="CLOSED", expected_version=d["version"])
    assert r.status_code == 200 and r.json()["closure_reason"] == "confirmed"
    assert act(client, "employee", n, "rating", rating=5, comment="Quick fix").status_code == 201
    assert act(client, "employee", n, "rating", rating=4).status_code == 409  # only once
    hist = client.get(f"{API}/{n}/history", headers=auth(eng)).json()
    fields = [(h["field"], h["new_value"]) for h in hist]
    assert ("status", "CLOSED") in fields and ("status", "RESOLVED") in fields
    assert all(h["created_at"] for h in hist)


def test_invalid_transition_rejected(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    r = act(client, eng, t["number"], "status", to_status="CLOSED", expected_version=t["version"])
    assert r.status_code == 422


def test_employee_cannot_resolve_own_ticket(client):
    t = make_ticket(client)
    r = act(client, "employee", t["number"], "status", to_status="RESOLVED", resolution_notes="I fixed it myself",
            expected_version=t["version"])
    assert r.status_code == 422


def test_resolve_requires_notes(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    r = act(client, eng, t["number"], "status", to_status="RESOLVED", expected_version=t["version"])
    assert r.status_code == 422


def test_reason_required_for_pending_employee(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    r = act(client, eng, t["number"], "status", to_status="PENDING_EMPLOYEE", expected_version=t["version"])
    assert r.status_code == 422


def test_stale_version_conflict(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    assert act(client, eng, t["number"], "status", to_status="IN_PROGRESS",
               expected_version=t["version"]).status_code == 200
    r = act(client, "erp_lead", t["number"], "status", to_status="PENDING_VENDOR", reason="Vendor",
            expected_version=t["version"])
    assert r.status_code == 409


def test_requester_cannot_reopen_after_window(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    act(client, eng, t["number"], "status", to_status="RESOLVED", resolution_notes="Fixed the configuration.",
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
    t, eng = _erp_ticket_assigned_to_engineer(client)
    d = act(client, eng, t["number"], "status", to_status="RESOLVED", resolution_notes="Fixed the configuration.",
            expected_version=t["version"]).json()
    d = act(client, "employee", t["number"], "status", to_status="REOPENED", reason="Error is back",
            expected_version=d["version"]).json()
    assert d["status"]["code"] == "REOPENED" and d["reopen_count"] == 1 and d["resolved_at"] is None


def test_requester_can_cancel_queued_ticket(client):
    t = make_ticket(client, code="QUERY")  # Service Desk = manual => stays SUBMITTED
    assert t["status"]["code"] == "SUBMITTED"
    r = act(client, "employee", t["number"], "status", to_status="CANCELLED", reason="Not needed anymore",
            expected_version=t["version"])
    assert r.status_code == 200 and r.json()["closed_at"]


# ---------------------------------------------------------------- comments & internal notes
def test_internal_notes_hidden_from_employee(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    assert act(client, eng, t["number"], "comments", body="Internal analysis", is_internal=True).status_code == 201
    assert act(client, eng, t["number"], "comments", body="Public reply").status_code == 201
    emp = client.get(f"{API}/{t['number']}/comments", headers=auth("employee")).json()
    staff = client.get(f"{API}/{t['number']}/comments", headers=auth(eng)).json()
    assert [c["body"] for c in emp] == ["Public reply"]
    assert len(staff) == 2


def test_employee_cannot_write_internal_note(client):
    t = make_ticket(client)
    r = act(client, "employee", t["number"], "comments", body="sneaky", is_internal=True)
    assert r.status_code == 403


def test_management_reads_internal_but_cannot_work(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    act(client, eng, t["number"], "comments", body="Internal analysis", is_internal=True)
    assert len(client.get(f"{API}/{t['number']}/comments", headers=auth("management")).json()) == 1
    r = act(client, "management", t["number"], "status", to_status="IN_PROGRESS", expected_version=t["version"])
    assert r.status_code == 422
    assert act(client, "management", t["number"], "comments", body="hello").status_code == 403


# ---------------------------------------------------------------- assignment & priority
def test_engineer_cannot_assign_but_can_escalate(client, db):
    from app.models import SupportGroup
    infra = db.scalar(select(SupportGroup.id).where(SupportGroup.code == "INFRA"))
    erp = db.scalar(select(SupportGroup.id).where(SupportGroup.code == "ERP"))
    t, eng = _erp_ticket_assigned_to_engineer(client)
    other = "erp_engineer2" if eng == "erp_engineer" else "erp_engineer"
    r = act(client, eng, t["number"], "assign", support_group_id=erp, assignee_id=user_id(
        "priya.nair@demo.example.com" if other == "erp_engineer2" else "amit.deshmukh@demo.example.com"),
        expected_version=t["version"])
    assert r.status_code == 403
    r = act(client, eng, t["number"], "assign", support_group_id=infra, reason="Looks like a network problem",
            expected_version=t["version"])
    assert r.status_code == 200 and r.json()["support_group"]["name"] == "Infrastructure & Network"


def test_lead_assigns_within_group_only_to_members(client, db):
    from app.models import SupportGroup
    erp = db.scalar(select(SupportGroup.id).where(SupportGroup.code == "ERP"))
    t = make_ticket(client)
    r = act(client, "erp_lead", t["number"], "assign", support_group_id=erp,
            assignee_id=user_id("rahul.kulkarni@demo.example.com"), expected_version=t["version"])
    assert r.status_code == 422  # not a member of ERP
    r = act(client, "erp_lead", t["number"], "assign", support_group_id=erp,
            assignee_id=user_id("priya.nair@demo.example.com"), reason="Workload", expected_version=t["version"])
    assert r.status_code == 200 and r.json()["assignee"]["full_name"] == "Priya Nair"


def test_lead_of_other_group_cannot_assign(client, db):
    from app.models import SupportGroup
    erp = db.scalar(select(SupportGroup.id).where(SupportGroup.code == "ERP"))
    t = make_ticket(client)
    r = act(client, "infra_lead", t["number"], "assign", support_group_id=erp, assignee_id=None,
            expected_version=t["version"])
    assert r.status_code == 404  # not even visible


def test_priority_change_keeps_sla_start(client):
    t = make_ticket(client, impact=3, urgency=3)
    assert t["priority"]["code"] == "P4"
    with SessionLocal() as db:
        tid = db.scalar(select(Ticket.id).where(Ticket.number == t["number"]))
        started = db.get(SLATracking, tid).started_at
    r = act(client, "erp_lead", t["number"], "priority", impact=1, urgency=1, reason="Whole team blocked",
            expected_version=t["version"])
    assert r.status_code == 200 and r.json()["priority"]["code"] == "P1"
    with SessionLocal() as db:
        s = db.get(SLATracking, tid)
        assert s.started_at == started and s.resolution_target_minutes == 240
        h = db.scalars(select(TicketHistory).where(TicketHistory.ticket_id == tid,
                                                   TicketHistory.field == "priority")).all()
        assert h and h[-1].reason == "Whole team blocked"


def test_engineer_cannot_change_priority(client):
    t, eng = _erp_ticket_assigned_to_engineer(client)
    r = act(client, eng, t["number"], "priority", impact=1, urgency=1, reason="Want it faster",
            expected_version=t["version"])
    assert r.status_code == 403


def test_accept_queued_ticket(client):
    t = make_ticket(client, code="QUERY")
    r = act(client, "erp_lead", t["number"], "accept", expected_version=t["version"])  # lead of Service Desk
    assert r.status_code == 200 and r.json()["status"]["code"] == "IN_PROGRESS"


def test_link_tickets_does_not_leak(client):
    a, eng = _erp_ticket_assigned_to_engineer(client)
    b = make_ticket(client, role="employee2", code="ERP_APP")
    r = client.post(f"{API}/{a['number']}/links", json={"target_number": b["number"], "relation_type": "related"},
                    headers=auth("erp_lead"))
    assert r.status_code == 204
    # Requester of A must not learn about B (owned by someone else)
    assert current(client, "employee", a["number"])["relations"] == []
    assert len(current(client, "erp_lead", a["number"])["relations"]) == 1
