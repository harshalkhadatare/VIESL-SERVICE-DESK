from tests.conftest import auth, make_ticket

ADMIN = "/api/v1/admin/users"
H = {"X-Requested-With": "fetch"}


def _mk(client, code, email, pw, role="employee"):
    r = client.post(ADMIN, headers=auth("admin"), json={"full_name": f"Shared {code}", "email": email,
                                                         "employee_code": code, "role": role, "password": pw})
    assert r.status_code == 201, r.text
    return r.json()


def test_same_email_allowed_for_several_users(client):
    a = _mk(client, "S1001", "office.team@visioninfraindia.com", "pass-a")
    b = _mk(client, "S1002", "office.team@visioninfraindia.com", "pass-b", role="it_admin")
    assert a["email"] == b["email"]
    # editing another user to the same address also works
    c = _mk(client, "S1003", None, "pass-c")
    assert client.patch(f"{ADMIN}/{c['id']}", headers=auth("admin"),
                        json={"email": "office.team@visioninfraindia.com"}).status_code == 200


def test_login_with_shared_email_picks_the_matching_password(client):
    _mk(client, "S2001", "shared.login@visioninfraindia.com", "alpha")
    _mk(client, "S2002", "shared.login@visioninfraindia.com", "bravo")
    def who(pw):
        r = client.post("/api/v1/auth/login", json={"email": "shared.login@visioninfraindia.com", "password": pw}, headers=H)
        if r.status_code != 200:
            return r.status_code
        return client.get("/api/v1/auth/me", headers={**H, "Authorization": f"Bearer {r.json()['access_token']}"}).json()["employee_code"]
    assert who("alpha") == "S2001" and who("bravo") == "S2002"
    assert who("wrong") == 401
    # same email AND same password: ask for the Employee ID
    _mk(client, "S2003", "shared.login@visioninfraindia.com", "alpha")
    r = client.post("/api/v1/auth/login", json={"email": "shared.login@visioninfraindia.com", "password": "alpha"}, headers=H)
    assert r.status_code == 401 and "Employee ID" in r.json()["error"]["message"]
    assert client.post("/api/v1/auth/login", json={"email": "S2003", "password": "alpha"}, headers=H).status_code == 200


def test_resolution_notes_five_characters(client):
    t = make_ticket(client, subject="Short resolution note")
    n = t["number"]
    v = client.post(f"/api/v1/tickets/{n}/status", headers=auth("admin"),
                    json={"to_status": "IN_PROGRESS", "expected_version": t["version"]}).json()["version"]
    r = client.post(f"/api/v1/tickets/{n}/status", headers=auth("admin"),
                    json={"to_status": "RESOLVED", "resolution_notes": "done", "expected_version": v})
    assert r.status_code == 422 and "5 characters" in r.json()["error"]["message"]
    r = client.post(f"/api/v1/tickets/{n}/status", headers=auth("admin"),
                    json={"to_status": "RESOLVED", "resolution_notes": "Fixed", "expected_version": v})
    assert r.status_code == 200


def test_ticket_page_in_one_request_and_role_change_applies_at_once(client):
    t = make_ticket(client, subject="Full endpoint check")
    client.post(f"/api/v1/tickets/{t['number']}/comments", headers=auth("employee"), json={"body": "hello"})
    full = client.get(f"/api/v1/tickets/{t['number']}/full", headers=auth("employee")).json()
    assert full["ticket"]["number"] == t["number"] and full["comments"] and full["history"] is not None
    # the 60-second permission cache is cleared when an admin changes roles
    u = _mk(client, "S3001", None, "x")
    tok = client.post("/api/v1/auth/login", json={"email": "S3001", "password": "x"}, headers=H).json()["access_token"]
    hh = {**H, "Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/admin/users", headers=hh).status_code == 403
    client.put(f"{ADMIN}/{u['id']}/roles", headers=auth("admin"), json={"roles": ["it_admin"]})
    tok = client.post("/api/v1/auth/login", json={"email": "S3001", "password": "x"}, headers=H).json()["access_token"]
    assert client.get("/api/v1/admin/users", headers={**H, "Authorization": f"Bearer {tok}"}).status_code == 200


def test_health_reports_speed(client):
    d = client.get("/api/v1/health").json()
    assert "db_round_trip_ms" in d and d["speed"]
