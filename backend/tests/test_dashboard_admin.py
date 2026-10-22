from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import SessionLocal, auth, make_ticket, user_id


def test_ops_dashboard_admin_only(client):
    assert client.get("/api/v1/dashboard/ops", headers=auth("employee")).status_code == 403
    assert client.get("/api/v1/dashboard/ops", headers=auth("admin")).status_code == 200


def test_dashboard_counts_come_from_database(client):
    before = client.get("/api/v1/dashboard/ops", headers=auth("admin")).json()["live"]["open"]
    make_ticket(client, code="QUERY")
    after = client.get("/api/v1/dashboard/ops", headers=auth("admin")).json()["live"]["open"]
    assert after == before + 1


def test_employee_dashboard(client):
    make_ticket(client)
    d = client.get("/api/v1/dashboard/employee", headers=auth("employee")).json()
    assert d["summary"]["open"] >= 1 and d["recent"]


def test_invalid_date_range(client):
    r = client.get("/api/v1/dashboard/ops", params={"start": "2026-10-10", "end": "2026-10-01"},
                   headers=auth("admin"))
    assert r.status_code == 422


def test_only_two_roles_exist(client):
    roles = client.get("/api/v1/admin/roles", headers=auth("admin")).json()
    assert [r["code"] for r in roles] == ["employee", "it_admin"]


def test_role_change_admin_only_and_audited(client):
    target = user_id("deepak.verma@demo.example.com")
    assert client.put(f"/api/v1/admin/users/{target}/roles", json={"roles": ["it_admin"]},
                      headers=auth("employee")).status_code == 403
    r = client.put(f"/api/v1/admin/users/{target}/roles", json={"roles": ["it_admin"]}, headers=auth("admin"))
    assert r.status_code == 200 and r.json()["roles"] == ["it_admin"]
    names = [x["full_name"] for x in client.get("/api/v1/it-admins", headers=auth("admin")).json()]
    assert "Deepak Verma" in names          # promoted users appear in the assignment menu
    with SessionLocal() as db:
        a = db.scalar(select(AuditLog).where(AuditLog.action == "admin.roles_change",
                                             AuditLog.entity_id == str(target)))
        assert a and "it_admin" in a.detail
    client.put(f"/api/v1/admin/users/{target}/roles", json={"roles": ["employee"]}, headers=auth("admin"))


def test_admin_cannot_remove_own_admin_role(client):
    me = user_id("rohan.mehta@demo.example.com")
    r = client.put(f"/api/v1/admin/users/{me}/roles", json={"roles": ["employee"]}, headers=auth("admin"))
    assert r.status_code == 422


def test_unknown_role_rejected(client):
    target = user_id("deepak.verma@demo.example.com")
    for bad in (["superuser"], ["it_lead"], ["management"]):
        r = client.put(f"/api/v1/admin/users/{target}/roles", json={"roles": bad}, headers=auth("admin"))
        assert r.status_code == 422


def test_deactivated_user_loses_access(client):
    target = user_id("pooja.kadam@demo.example.com")
    from app.core.security import create_access_token
    tok = {"Authorization": "Bearer " + create_access_token(target)[0]}
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 200
    client.patch(f"/api/v1/admin/users/{target}/active", json={"is_active": False}, headers=auth("admin"))
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 401
    client.patch(f"/api/v1/admin/users/{target}/active", json={"is_active": True}, headers=auth("admin"))


def test_audit_log_access(client):
    assert client.get("/api/v1/audit-logs", headers=auth("employee")).status_code == 403
    r = client.get("/api/v1/audit-logs", headers=auth("admin"))
    assert r.status_code == 200 and r.json()["total"] > 0


def test_ticket_actions_are_audited(client):
    t = make_ticket(client)
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "ticket.create",
                                                AuditLog.entity_id == t["number"]))


def test_notifications_are_private(client):
    make_ticket(client)
    mine = client.get("/api/v1/notifications", headers=auth("employee")).json()
    assert mine["total"] >= 1
    nid = mine["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{nid}/read", headers=auth("employee2")).status_code == 404
    assert client.post(f"/api/v1/notifications/{nid}/read", headers=auth("employee")).status_code == 204


def test_kb_search_only_published_for_employees(client):
    r = client.get("/api/v1/kb/articles", params={"q": "vpn disconnect"}, headers=auth("employee"))
    assert r.status_code == 200 and r.json() and "VPN" in r.json()[0]["title"]


def test_global_search_respects_visibility(client):
    make_ticket(client, role="employee2", code="QUERY", subject="Unique search phrase qq42")
    assert client.get("/api/v1/dashboard/search", params={"q": "qq42"},
                      headers=auth("employee")).json()["tickets"] == []
    assert client.get("/api/v1/dashboard/search", params={"q": "qq42"},
                      headers=auth("employee2")).json()["tickets"]


def test_admin_creates_real_user(client):
    body = {"full_name": "Suresh Patil", "email": "Suresh.Patil@VisionInfra.co.in", "employee_code": "E1042",
            "role": "employee", "password": "Welcome@2026x"}
    assert client.post("/api/v1/admin/users", json=body, headers=auth("employee")).status_code == 403
    r = client.post("/api/v1/admin/users", json=body, headers=auth("admin"))
    assert r.status_code == 201 and r.json()["email"] == "suresh.patil@visioninfra.co.in" and not r.json()["is_demo"]
    assert client.post("/api/v1/admin/users", json=body, headers=auth("admin")).status_code == 422  # duplicate
    weak = {**body, "email": "x@visioninfra.co.in", "employee_code": "E1043", "password": "weakpassword"}
    assert client.post("/api/v1/admin/users", json=weak, headers=auth("admin")).status_code == 422
    bad_role = {**body, "email": "y@visioninfra.co.in", "employee_code": "E1044", "role": "it_lead"}
    assert client.post("/api/v1/admin/users", json=bad_role, headers=auth("admin")).status_code == 422
    login = client.post("/api/v1/auth/login", json={"email": "suresh.patil@visioninfra.co.in", "password": "Welcome@2026x"},
                        headers={"X-Requested-With": "fetch"})
    assert login.status_code == 200
