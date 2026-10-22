"""Role x action matrix (Employee vs IT Administrator), executed against the real API.

`own` is an ERP ticket raised by the employee "anjali"; "employee2" is a different employee.
"""
import pytest

from tests.conftest import EMAILS, auth, make_ticket, user_id

MATRIX = [
    ("employee", "create", 201), ("admin", "create", 201),
    ("employee", "view", 200), ("employee2", "view", 404), ("admin", "view", 200), ("infra_admin", "view", 200),
    ("employee", "internal_note", 403), ("admin", "internal_note", 201),
    ("employee", "assign", 403), ("employee2", "assign", 403), ("admin", "assign", 200),
    ("employee", "it_admin_list", 403), ("admin", "it_admin_list", 200),
    ("employee", "priority", 403), ("admin", "priority", 200),
    ("employee", "ops_dashboard", 403), ("admin", "ops_dashboard", 200),
    ("employee", "export", 403), ("admin", "export", 200),
    ("employee", "admin_users", 403), ("admin", "admin_users", 200),
    ("employee", "audit", 403), ("admin", "audit", 200),
    ("employee", "email_settings", 403), ("admin", "email_settings", 200),
]


@pytest.mark.parametrize("role,action,expected", MATRIX)
def test_matrix(client, role, action, expected):
    own = make_ticket(client, role="employee", code="ERP_APP")
    n, h = own["number"], auth(role)
    calls = {
        "create": lambda: client.post("/api/v1/tickets", headers=h, json={
            "subject": "Matrix create", "description": "Matrix create test", "category_id": own["category"]["id"]}),
        "view": lambda: client.get(f"/api/v1/tickets/{n}", headers=h),
        "internal_note": lambda: client.post(f"/api/v1/tickets/{n}/comments", headers=h,
                                             json={"body": "note", "is_internal": True}),
        "assign": lambda: client.post(f"/api/v1/tickets/{n}/assign", headers=h, json={
            "assignee_id": user_id(EMAILS["admin"]), "expected_version": own["version"]}),
        "it_admin_list": lambda: client.get("/api/v1/it-admins", headers=h),
        "priority": lambda: client.post(f"/api/v1/tickets/{n}/priority", headers=h, json={
            "impact": 1, "urgency": 2, "reason": "Matrix check", "expected_version": own["version"]}),
        "ops_dashboard": lambda: client.get("/api/v1/dashboard/ops", headers=h),
        "export": lambda: client.get("/api/v1/tickets/export.csv", headers=h),
        "admin_users": lambda: client.get("/api/v1/admin/users", headers=h),
        "audit": lambda: client.get("/api/v1/audit-logs", headers=h),
        "email_settings": lambda: client.get("/api/v1/admin/email", headers=h),
    }
    r = calls[action]()
    assert r.status_code == expected, f"{role} {action}: {r.status_code} {r.text[:200]}"
