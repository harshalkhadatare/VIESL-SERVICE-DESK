"""Role x action matrix, executed against the real API.

Each row: (role, method, path_template, expected_status). `{own}` is a ticket raised by
the employee and routed to the ERP group.
"""
import pytest

from tests.conftest import auth, make_ticket

MATRIX = [
    # --- create tickets: everyone holds ticket.create
    *[(r, "create", 201) for r in ("employee", "erp_engineer", "erp_lead", "admin", "management")],
    # --- view the employee's ERP ticket
    ("employee", "view", 200), ("employee2", "view", 404), ("erp_engineer", "view", 200),
    ("infra_engineer", "view", 404), ("erp_lead", "view", 200), ("infra_lead", "view", 404),
    ("admin", "view", 200), ("management", "view", 200),
    # --- internal notes
    ("employee", "internal_note", 403), ("erp_engineer", "internal_note", 201), ("erp_lead", "internal_note", 201),
    ("admin", "internal_note", 201), ("management", "internal_note", 403),
    # --- ops dashboard
    ("employee", "ops_dashboard", 403), ("erp_engineer", "ops_dashboard", 200), ("erp_lead", "ops_dashboard", 200),
    ("admin", "ops_dashboard", 200), ("management", "ops_dashboard", 200),
    # --- export
    ("employee", "export", 403), ("erp_engineer", "export", 403), ("erp_lead", "export", 200),
    ("admin", "export", 200), ("management", "export", 200),
    # --- user administration
    ("employee", "admin_users", 403), ("erp_engineer", "admin_users", 403), ("erp_lead", "admin_users", 403),
    ("admin", "admin_users", 200), ("management", "admin_users", 403),
    # --- audit log
    ("employee", "audit", 403), ("erp_lead", "audit", 403), ("admin", "audit", 200), ("management", "audit", 200),
    # --- priority change on the ERP ticket
    ("employee", "priority", 403), ("erp_engineer", "priority", 403), ("erp_lead", "priority", 200),
    ("admin", "priority", 200), ("management", "priority", 403),
]


@pytest.mark.parametrize("role,action,expected", MATRIX)
def test_matrix(client, role, action, expected):
    own = make_ticket(client, role="employee", code="ERP_APP")
    n = own["number"]
    h = auth(role)
    if action == "create":
        r = client.post("/api/v1/tickets", headers=h, json={
            "subject": "Matrix create", "description": "Matrix create test", "category_id": own["category"]["id"]})
    elif action == "view":
        r = client.get(f"/api/v1/tickets/{n}", headers=h)
    elif action == "internal_note":
        r = client.post(f"/api/v1/tickets/{n}/comments", headers=h, json={"body": "note", "is_internal": True})
    elif action == "ops_dashboard":
        r = client.get("/api/v1/dashboard/ops", headers=h)
    elif action == "export":
        r = client.get("/api/v1/tickets/export.csv", headers=h)
    elif action == "admin_users":
        r = client.get("/api/v1/admin/users", headers=h)
    elif action == "audit":
        r = client.get("/api/v1/audit-logs", headers=h)
    elif action == "priority":
        r = client.post(f"/api/v1/tickets/{n}/priority", headers=h, json={
            "impact": 1, "urgency": 2, "reason": "Matrix check", "expected_version": own["version"]})
    else:
        raise AssertionError(action)
    assert r.status_code == expected, f"{role} {action}: {r.status_code} {r.text[:200]}"
