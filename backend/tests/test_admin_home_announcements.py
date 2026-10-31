from tests.conftest import auth, make_ticket


def test_admin_home_lists_unassigned_and_team(client):
    t = make_ticket(client, code="SECURITY", impact=1, urgency=1, subject="Phishing email received")
    client.post(f"/api/v1/tickets/{t['number']}/assign", headers=auth("admin"),
                json={"assignee_id": None, "expected_version": t["version"]})
    r = client.get("/api/v1/dashboard/admin-home", headers=auth("admin"))
    assert r.status_code == 200, r.text
    d = r.json()
    hit = [a for a in d["attention"] if a["number"] == t["number"]]
    assert hit and hit[0]["reason"] in ("unassigned", "overdue")
    assert hit[0]["requester_code"]
    assert d["team"] and all({"name", "open", "resolved_week", "employee_code"} <= set(m) for m in d["team"])
    assert client.get("/api/v1/dashboard/admin-home", headers=auth("employee")).status_code == 403


def test_announcements_lifecycle(client):
    r = client.post("/api/v1/admin/announcements", headers=auth("admin"),
                    json={"title": "Email maintenance", "body": "Outlook down 9-10 pm", "severity": "warning", "hours": 4})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["active"]
    seen = client.get("/api/v1/announcements", headers=auth("employee")).json()
    assert any(x["id"] == a["id"] for x in seen)
    assert client.post("/api/v1/admin/announcements", headers=auth("employee"),
                       json={"title": "Nope", "body": "Not allowed", "severity": "info"}).status_code == 403
    assert client.post(f"/api/v1/admin/announcements/{a['id']}/end", headers=auth("admin")).json()["active"] is False
    assert not any(x["id"] == a["id"] for x in client.get("/api/v1/announcements", headers=auth("employee")).json())
    assert client.delete(f"/api/v1/admin/announcements/{a['id']}", headers=auth("admin")).status_code == 204
