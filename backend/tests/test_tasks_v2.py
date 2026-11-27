"""Task management v2: several people per task, private messages, emails with the writer's words,
counters / mark all read, advanced search, no-deadline tasks and analytics."""
from datetime import timedelta

from app.models import utcnow
from tests.conftest import EMAILS, auth, user_id
from tests.test_email_notifications import _hdr, _real_user, mail  # noqa: F401  (fixture)

API = "/api/v1/tasks"


def _iso(days=3):
    return (utcnow() + timedelta(days=days)).isoformat()


def _mgr():
    return _real_user("v2.manager@visioninfra.co.in", "Kiran Manager", "top_management")


def test_several_people_on_one_task(client):
    mgr = _mgr()
    a = _real_user("v2.a@visioninfra.co.in", "Asha One", "employee")
    b = _real_user("v2.b@visioninfra.co.in", "Bala Two", "employee")
    r = client.post(API, json={"title": "Stock count at Pune yard", "assignee_ids": [a, b], "due_at": _iso()},
                    headers=_hdr(mgr))
    assert r.status_code == 201, r.text
    t = r.json()
    assert [x["name"] for x in t["assignees"]] == ["Asha One", "Bala Two"]
    n = t["number"]
    # both see it under "assigned to me", both can update; either can submit
    for who in (a, b):
        assert n in [i["number"] for i in client.get(API, params={"view": "to_me"}, headers=_hdr(who)).json()["items"]]
    assert client.post(f"{API}/{n}/updates", json={"progress": 30, "body": "Counted rack A"}, headers=_hdr(a)).status_code == 200
    assert client.post(f"{API}/{n}/updates", json={"progress": 60, "body": "Rack B done"}, headers=_hdr(b)).status_code == 200
    # change the people: remove A, add someone else
    c = user_id(EMAILS["employee3"])
    r = client.patch(f"{API}/{n}", json={"assignee_ids": [b, c]}, headers=_hdr(mgr)).json()
    assert [x["id"] for x in r["assignees"]] == [b, c]
    assert client.get(f"{API}/{n}", headers=_hdr(a)).status_code == 404       # A no longer sees it
    ov = client.get(f"{API}/overview", headers=_hdr(mgr)).json()
    assert {b, c} <= {row["user"]["id"] for row in ov["team"]}


def test_messages_are_private_from_admins_but_md_reads_all(client, mail):  # noqa: F811
    mgr = _mgr()
    md = _real_user("v2.md@visioninfra.co.in", "Top Boss", "top_management")
    emp = _real_user("v2.private@visioninfra.co.in", "Priya Private", "employee")
    t = client.post(API, json={"title": "Confidential salary file", "description": "Use the locked sheet in HR drive",
                               "assignee_ids": [emp], "due_at": _iso()}, headers=_hdr(mgr)).json()
    n = t["number"]
    client.post(f"{API}/{n}/updates", json={"body": "Secret figures look fine", "progress": 50}, headers=_hdr(emp))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    f = client.post(f"{API}/{n}/attachments", headers=_hdr(emp),
                    files={"file": ("sheet.png", png, "image/png")}).json()
    # IT administrators cannot open, find or count the task at all
    admin = auth("admin")
    assert client.get(f"{API}/{n}", headers=admin).status_code == 404
    assert client.post(f"{API}/{n}/updates", json={"body": "hi"}, headers=admin).status_code == 404
    for view in ("all", "mine"):
        found = client.get(API, params={"view": view, "status": "all"}, headers=admin).json()
        assert n not in [i["number"] for i in found["items"]]
    ov = client.get(f"{API}/overview", params={"scope": "all"}, headers=admin).json()
    assert ov["scope"] == "mine" and all(x["task"]["number"] != n for x in ov["feed"])
    assert client.get(f"{API}/analytics", params={"scope": "all"}, headers=admin).json()["scope"] != "all"
    # Top management (MD) sees every task, with its messages and files — but cannot post or change it
    d = client.get(f"{API}/{n}", headers=_hdr(md)).json()
    assert d["description"] == "Use the locked sheet in HR drive" and d["private"] is False and d["viewing_as_md"]
    assert any(e["body"] == "Secret figures look fine" for e in d["events"])
    assert [a["id"] for a in d["attachments"]] == [f["id"]]
    assert client.get(f"{API}/{n}/attachments/{f['id']}", headers=_hdr(md)).status_code == 200
    assert d["can"]["comment"] is True
    assert not any(d["can"][k] for k in ("update", "manage", "edit", "cancel", "approve", "attach"))
    # the MD may write a message (but not report progress); the people on the task are told in-app
    assert client.post(f"{API}/{n}/updates", json={"body": "Please finish by Friday"}, headers=_hdr(md)).status_code == 200
    assert client.post(f"{API}/{n}/updates", json={"progress": 90}, headers=_hdr(md)).status_code == 403
    d = client.get(f"{API}/{n}", headers=_hdr(mgr)).json()
    assert any(e["body"] == "Please finish by Friday" and e["author"]["name"] == "Top Boss" for e in d["events"])
    notes = client.get("/api/v1/notifications", params={"area": "tasks"}, headers=_hdr(emp)).json()["items"]
    assert any("Please finish by Friday" in (x.get("body") or "") for x in notes)
    assert client.patch(f"{API}/{n}", json={"due_at": _iso(9)}, headers=_hdr(md)).status_code == 403
    found = client.get(API, params={"view": "all", "status": "all"}, headers=_hdr(md)).json()
    assert n in [i["number"] for i in found["items"]]
    ov = client.get(f"{API}/overview", params={"scope": "all"}, headers=_hdr(md)).json()
    assert ov["scope"] == "all" and ov["tiles"]["total"] >= 1
    assert client.get(f"{API}/analytics", params={"scope": "all"}, headers=_hdr(md)).json()["scope"] == "all"
    # the MD is not emailed about tasks they are not on
    assert not [x for x in mail.sent if x["to"] == "v2.md@visioninfra.co.in" and n in x["subject"]]
    # participants read everything
    d = client.get(f"{API}/{n}", headers=_hdr(mgr)).json()
    assert d["description"] == "Use the locked sheet in HR drive" and d["private"] is False
    assert any(e["body"] == "Secret figures look fine" for e in d["events"])
    # progress messages are not emailed any more; marking it complete is — with the employee's own words
    assert not [x for x in mail.sent if "Secret figures look fine" in x["text"]]
    client.post(f"{API}/{n}/submit", json={"body": "Final sheet uploaded"}, headers=_hdr(emp))
    m = [x for x in mail.sent if x["to"] == "v2.manager@visioninfra.co.in" and n in x["subject"]][-1]
    assert "Final sheet uploaded" in m["text"] and "Message from Priya Private" in m["text"]
    assert "Message from Priya Private" in m["html"] and "Use the locked sheet in HR drive" in m["html"]


def test_counters_and_mark_all_read(client):
    mgr = _mgr()
    emp = _real_user("v2.counter@visioninfra.co.in", "Chetan Count", "employee")
    t = client.post(API, json={"title": "Counter check", "assignee_ids": [emp], "due_at": _iso()}, headers=_hdr(mgr)).json()
    client.post(f"{API}/{t['number']}/updates", json={"body": "First note"}, headers=_hdr(emp))
    c = client.get(f"{API}/counters", headers=_hdr(mgr)).json()
    assert c["comments"] >= 1
    assert client.get(API, params={"view": "by_me", "unread": True}, headers=_hdr(mgr)).json()["total"] >= 1
    client.post(f"{API}/read-all", headers=_hdr(mgr))
    assert client.get(f"{API}/counters", headers=_hdr(mgr)).json()["comments"] == 0
    # opening the task also marks it read
    client.post(f"{API}/{t['number']}/updates", json={"body": "Second note"}, headers=_hdr(emp))
    client.get(f"{API}/{t['number']}", headers=_hdr(mgr))
    assert client.get(f"{API}/counters", headers=_hdr(mgr)).json()["comments"] == 0


def test_advanced_search_and_no_deadline(client):
    mgr = _mgr()
    emp = user_id(EMAILS["employee2"])
    nd = client.post(API, json={"title": "Think about new canteen vendor", "assignee_ids": [emp], "due_at": None,
                                "priority": "low", "category": "Admin"}, headers=_hdr(mgr)).json()
    assert nd["due_at"] is None
    hi = client.post(API, json={"title": "Fix GST mismatch report", "assignee_ids": [emp], "due_at": _iso(2),
                                "priority": "high", "category": "Finance"}, headers=_hdr(mgr)).json()
    g = lambda **kw: [i["number"] for i in client.get(API, params={"view": "by_me", "status": "all", **kw},  # noqa: E731
                                                      headers=_hdr(mgr)).json()["items"]]
    assert nd["number"] in g(no_deadline=True) and hi["number"] not in g(no_deadline=True)
    assert hi["number"] in g(priority="high") and nd["number"] not in g(priority="high")
    assert hi["number"] in g(category="fin")
    assert hi["number"] in g(due_from=utcnow().isoformat(), due_to=_iso(3))
    assert hi["number"] in g(assignee_id=emp, status="open,not_started")
    assert client.get(API, params={"status": "bogus"}, headers=_hdr(mgr)).status_code == 422
    an = client.get(f"{API}/analytics", params={"scope": "team"}, headers=_hdr(mgr)).json()
    assert an["scope"] == "team" and an["totals"]["tasks"] >= 2 and len(an["weeks"]) == 8
    me = client.get(f"{API}/analytics", headers=auth("employee2")).json()
    assert me["scope"] == "me"


def test_notifications_split_by_area(client):
    mgr = _mgr()
    emp = _real_user("v2.split@visioninfra.co.in", "Sita Split", "employee")
    client.post(API, json={"title": "Area split task", "assignee_ids": [emp], "due_at": _iso()}, headers=_hdr(mgr))
    # a ticket notification for the same person
    client.post("/api/v1/tickets", headers=_hdr(emp), json={"subject": "Printer jam on floor 2",
                "description": "Paper stuck in tray 2 since morning", "desk": "it", "category_id": 1})
    tasks = client.get("/api/v1/notifications", params={"area": "tasks"}, headers=_hdr(emp)).json()["items"]
    desk = client.get("/api/v1/notifications", params={"area": "desk"}, headers=_hdr(emp)).json()["items"]
    assert tasks and all(n["area"] == "tasks" and n["event"].startswith("task_") for n in tasks)
    assert tasks[0]["ticket_number"].startswith("TSK-")
    assert all(n["area"] == "desk" for n in desk)
    t = client.get("/api/v1/notifications/unread-count", params={"area": "tasks"}, headers=_hdr(emp)).json()["count"]
    allc = client.get("/api/v1/notifications/unread-count", headers=_hdr(emp)).json()["count"]
    assert 1 <= t <= allc
    client.post("/api/v1/notifications/read-all", params={"area": "tasks"}, headers=_hdr(emp))
    assert client.get("/api/v1/notifications/unread-count", params={"area": "tasks"}, headers=_hdr(emp)).json()["count"] == 0
