"""Dashboard: lifetime ticket count, 'High' tile, and the SLA compliance report (IT only)."""
from tests.conftest import auth, make_ticket

API = "/api/v1/dashboard"


def test_lifetime_total_and_high_only(client):
    make_ticket(client, impact=2, urgency=1, subject="High one for dashboard")
    d = client.get(f"{API}/ops", params={"desk": "all"}, headers=auth("admin")).json()
    assert d["historical"]["total_all_time"] >= d["historical"]["created"] >= 1
    assert "high" in d["live"] and "critical_high" not in d["live"]


def test_sla_report_lists_ticket_details_for_admins_only(client):
    t = make_ticket(client, subject="SLA report ticket", impact=2, urgency=2)
    assert client.get(f"{API}/sla", headers=auth("employee")).status_code == 403
    r = client.get(f"{API}/sla", params={"desk": "all"}, headers=auth("admin"))
    assert r.status_code == 200
    body = r.json()
    row = next(i for i in body["items"] if i["number"] == t["number"])
    for k in ("response_due_at", "resolution_due_at", "response_target_minutes", "resolution_target_minutes",
              "business_minutes_used", "percent_used", "paused_minutes", "state", "response_state", "escalation_level"):
        assert k in row
    assert row["priority"]["name"] == "Medium" and row["state"] in ("on_track", "at_risk")
    assert body["summary"]["total"] >= 1
    only = client.get(f"{API}/sla", params={"desk": "all", "state": "breached"}, headers=auth("admin")).json()
    assert all(i["state"] == "breached" for i in only["items"])
    found = client.get(f"{API}/sla", params={"desk": "all", "q": t["number"]}, headers=auth("admin")).json()["items"]
    assert [i["number"] for i in found] == [t["number"]]
