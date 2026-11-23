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
    return _real_user("v2.manager@visioninfra.co.in", "Kiran Manager", "task_manager")


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


def test_messages_are_private_even_from_admins_and_md(client, mail):  # noqa: F811
    mgr = _mgr()
    md = _real_user("v2.md@visioninfra.co.in", "Top Boss", "top_management")
    emp = _real_user("v2.private@visioninfra.co.in", "Priya Private", "employee")
    t = client.post(API, json={"title": "Confidential salary file", "description": "Use the locked sheet in HR drive",
                               "assignee_ids": [emp], "due_at": _iso()}, headers=_hdr(mgr)).json()
    n = t["number"]
    client.post(f"{API}/{n}/updates", json={"body": "Secret figures look fine", "progress": 50}, headers=_hdr(emp))
    for outsider in (auth("admin"), _hdr(md)):
        d = client.get(f"{API}/{n}", headers=outsider).json()
        assert d["title"] == "Confidential salary file" and d["private"] is True      # sees the task exists …
        assert d["description"] is None                                               # … but not what was written
        assert all(e["body"] is None for e in d["events"])
        assert any(e["private"] for e in d["events"])
        assert client.post(f"{API}/{n}/updates", json={"body": "hi"}, headers=outsider).status_code == 403
        # searching the description finds nothing for outsiders
        found = client.get(API, params={"view": "all", "status": "all", "q": "locked sheet"}, headers=outsider).json()
        assert n not in [i["number"] for i in found["items"]]
        ov = client.get(f"{API}/overview", params={"scope": "all"}, headers=outsider).json()
        assert all(f["body"] is None for f in ov["feed"] if f["task"]["number"] == n)
    # participants read everything
    d = client.get(f"{API}/{n}", headers=_hdr(mgr)).json()
    assert d["description"] == "Use the locked sheet in HR drive" and d["private"] is False
    assert any(e["body"] == "Secret figures look fine" for e in d["events"])
    # the email to the manager carries the employee's own words, labelled with their name
    m = [x for x in mail.sent if x["to"] == "v2.manager@visioninfra.co.in" and n in x["subject"]][-1]
    assert "Secret figures look fine" in m["text"] and "Message from Priya Private" in m["text"]
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
