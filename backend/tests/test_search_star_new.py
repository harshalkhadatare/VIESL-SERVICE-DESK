from tests.conftest import EMAILS, auth, make_ticket, user_id

API = "/api/v1/tickets"


def _emp_code(client, role="employee"):
    return client.get("/api/v1/auth/me", headers=auth(role)).json()["employee_code"]


def test_admin_finds_tickets_by_employee_id_name_email(client):
    t = make_ticket(client, role="employee2", subject="Scanner not detected xyz")
    code = _emp_code(client, "employee2")
    for q in (code, "Manoj", "manoj.gupta@demo", "Gupta"):
        nums = [i["number"] for i in client.get(API, params={"q": q, "page_size": 100}, headers=auth("admin")).json()["items"]]
        assert t["number"] in nums, q
    # dedicated "raised by" filter by employee ID
    items = client.get(API, params={"requester": code, "page_size": 100}, headers=auth("admin")).json()["items"]
    assert items and all(i["requester_code"] == code for i in items)
    # employees still only see their own tickets, even when searching by someone else's name
    assert not [i for i in client.get(API, params={"q": "Manoj"}, headers=auth("employee")).json()["items"]
                if i["number"] == t["number"]]
    s = client.get("/api/v1/dashboard/search", params={"q": code}, headers=auth("admin")).json()
    assert s["people"] and s["people"][0]["employee_code"] == code


def test_star_and_starred_filter(client):
    t = make_ticket(client, subject="Star me")
    n = t["number"]
    assert client.put(f"{API}/{n}/star", json={"starred": True}, headers=auth("admin")).json()["starred"] is True
    items = client.get(API, params={"starred": True}, headers=auth("admin")).json()["items"]
    assert [i["number"] for i in items] == [n] or n in [i["number"] for i in items]
    assert all(i["starred"] for i in items)
    # stars are personal
    assert n not in [i["number"] for i in client.get(API, params={"starred": True}, headers=auth("sd_admin")).json()["items"]]
    assert client.get(f"{API}/{n}", headers=auth("admin")).json()["starred"] is True
    client.put(f"{API}/{n}/star", json={"starred": False}, headers=auth("admin"))
    assert n not in [i["number"] for i in client.get(API, params={"starred": True}, headers=auth("admin")).json()["items"]]


def test_new_until_opened(client):
    t = make_ticket(client, subject="Brand new ticket for green row")
    n = t["number"]

    def row(role):
        return next(i for i in client.get(API, params={"q": n}, headers=auth(role)).json()["items"] if i["number"] == n)
    assert row("sd_admin")["is_new"] is True
    client.get(f"{API}/{n}", headers=auth("sd_admin"))           # opening it clears "New" for that admin only
    assert row("sd_admin")["is_new"] is False
    assert row("admin")["is_new"] is True
    assert row("employee")["is_new"] is False                      # employees never see the green mark
