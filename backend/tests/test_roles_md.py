"""Five roles: Managing Director's private tickets, MD email rule, Manager L1 ticket access."""
from datetime import timedelta

from app.models import utcnow
from tests.conftest import EMAILS, auth, category_id, user_id
from tests.test_email_notifications import _hdr, _real_user, mail  # noqa: F401  (fixture)

T = "/api/v1/tickets"


def _md_ticket(client, md, admin_id, subject="MD laptop needs a new battery"):
    r = client.post(T, headers=_hdr(md), json={"subject": subject, "description": "Battery drains within an hour.",
                                                "category_id": category_id("QUERY"), "assign_to_id": admin_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_md_tickets_are_private_to_md_and_chosen_admin(client, mail):  # noqa: F811
    md = _real_user("md.private@visioninfraindia.com", "Mahesh Director", "top_management")
    admin, other = user_id(EMAILS["admin"]), auth("sd_admin")
    l1 = _real_user("l1.viewer@visioninfraindia.com", "Lata L1", "manager_l1")
    # the MD must choose the IT administrator; nobody else may choose
    r = client.post(T, headers=_hdr(md), json={"subject": "No admin chosen", "description": "Should be refused.",
                                                "category_id": category_id("QUERY")})
    assert r.status_code == 422
    r = client.post(T, headers=auth("employee"), json={"subject": "Employee picks admin", "description": "Not allowed.",
                                                       "category_id": category_id("QUERY"), "assign_to_id": admin})
    assert r.status_code == 422
    t = _md_ticket(client, md, admin)
    n = t["number"]
    assert t["assignee"]["id"] == admin
    # visible to the MD and the chosen admin only
    assert client.get(f"{T}/{n}", headers=_hdr(md)).status_code == 200
    assert client.get(f"{T}/{n}", headers=auth("admin")).status_code == 200
    for h in (other, _hdr(l1), auth("employee")):
        assert client.get(f"{T}/{n}", headers=h).status_code == 404
        items = client.get(T, params={"page_size": 100}, headers=h).json()["items"]
        assert n not in [i["number"] for i in items]
    # nobody else was notified that it exists
    sd = user_id(EMAILS["sd_admin"])
    notes = client.get("/api/v1/notifications", headers=other).json()["items"]
    assert not any(x.get("ticket_number") == n for x in notes), sd
    # it can be handed to another admin, but never left unassigned
    v = client.get(f"{T}/{n}", headers=auth("admin")).json()["version"]
    assert client.post(f"{T}/{n}/assign", headers=auth("admin"),
                       json={"assignee_id": None, "expected_version": v}).status_code == 422
    # the MD is not emailed about replies on their ticket — only when it is resolved
    client.post(f"{T}/{n}/comments", headers=auth("admin"), json={"body": "Ordered a battery", "is_internal": False})
    md_mail = lambda: [m for m in mail.sent if m["to"] == "md.private@visioninfraindia.com" and n in m["subject"]]  # noqa: E731
    assert md_mail() == []
    v = client.get(f"{T}/{n}", headers=auth("admin")).json()["version"]
    r = client.post(f"{T}/{n}/status", headers=auth("admin"), json={"to_status": "IN_PROGRESS", "expected_version": v})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    client.post(f"{T}/{n}/status", headers=auth("admin"), json={"to_status": "RESOLVED", "root_cause": "Old battery",
                                                                "resolution_notes": "Battery replaced", "expected_version": v})
    assert len(md_mail()) == 1


def test_md_email_only_when_their_task_is_done(client, mail):  # noqa: F811
    md = _real_user("md.tasks@visioninfraindia.com", "Meena Director", "top_management")
    l2 = _real_user("l2.doer@visioninfraindia.com", "Dinesh Doer", "manager_l2")
    due = (utcnow() + timedelta(days=3)).isoformat()
    n = client.post("/api/v1/tasks", headers=_hdr(md), json={"title": "Prepare board deck", "assignee_ids": [l2],
                                                              "due_at": due}).json()["number"]
    md_mail = lambda: [m for m in mail.sent if m["to"] == "md.tasks@visioninfraindia.com" and n in m["subject"]]  # noqa: E731
    client.post(f"/api/v1/tasks/{n}/updates", headers=_hdr(l2), json={"body": "Draft ready", "progress": 60})
    client.post(f"/api/v1/tasks/{n}/extension", headers=_hdr(l2),
                json={"due_at": (utcnow() + timedelta(days=6)).isoformat(), "reason": "Waiting for numbers"})
    assert md_mail() == []                                   # no mails while work is going on
    notes = client.get("/api/v1/notifications", params={"area": "tasks"}, headers=_hdr(md)).json()["items"]
    assert notes                                             # … but the MD still sees it all in the app
    client.post(f"/api/v1/tasks/{n}/submit", headers=_hdr(l2), json={"body": "Deck done"})
    assert len(md_mail()) == 1                               # the task is done → one email


def test_manager_l1_sees_and_comments_on_all_tickets(client):
    l1 = _real_user("l1.tickets@visioninfraindia.com", "Lokesh L1", "manager_l1")
    from tests.conftest import make_ticket
    n = make_ticket(client, subject="Shared drive not opening for L1 test")["number"]
    h = _hdr(l1)
    assert client.get(f"{T}/{n}", headers=h).status_code == 200
    assert client.post(f"{T}/{n}/comments", headers=h, json={"body": "Please check today", "is_internal": False}).status_code == 201
    assert client.get("/api/v1/admin/users", headers=h).status_code == 403
    me = client.get("/api/v1/tasks/me", headers=h).json()
    assert me["can_assign"] and sorted(me["assign_to"]) == ["Manager L1", "Manager L2"]
