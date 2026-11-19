from app.core.request_ctx import describe_user_agent
from tests.conftest import EMAILS, auth

CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.1 Mobile/15E148 Safari/604.1")
EDGE = CHROME_WIN + " Edg/130.0.2849.68"


def test_user_agent_is_readable():
    assert describe_user_agent(CHROME_WIN) == "Chrome 130 · Windows 10/11"
    assert describe_user_agent(IPHONE) == "Safari 18 · iPhone"
    assert describe_user_agent(EDGE) == "Edge 130 · Windows 10/11"
    assert describe_user_agent(None) is None


def _login(client, headers):
    return client.post("/api/v1/auth/login", json={"email": EMAILS["employee2"], "password": "Vision@Demo2026"},
                       headers={"X-Requested-With": "fetch", **headers})


def test_login_records_device_but_no_device_id(client):
    r = _login(client, {"X-Device-Id": "ABCD1234EFGH5678", "User-Agent": CHROME_WIN})
    assert r.status_code == 200
    row = client.get("/api/v1/audit-logs", params={"action": "auth.login"}, headers=auth("admin")).json()["items"][0]
    assert row["action"] == "auth.login" and row["device"] == "Chrome 130 · Windows 10/11"
    assert "Manoj Gupta (" in row["actor_label"]          # name + employee ID instead of email
    assert "device_id" not in row                            # device IDs are no longer collected or shown


def test_real_ip_from_vercel_header(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    r = _login(client, {"x-vercel-forwarded-for": "49.36.12.7", "User-Agent": IPHONE})
    assert r.status_code == 200
    rows = client.get("/api/v1/audit-logs", params={"ip": "49.36.12.7"}, headers=auth("admin")).json()["items"]
    assert rows and rows[0]["device"] == "Safari 18 · iPhone"
