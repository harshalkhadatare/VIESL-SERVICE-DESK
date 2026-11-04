import io

from openpyxl import load_workbook

from tests.conftest import auth, category_id, make_ticket

API = "/api/v1/tickets"


def test_categories_have_a_team_and_ticket_takes_it(client):
    cats = {c["code"]: c for c in client.get("/api/v1/meta/catalog", headers=auth("employee")).json()["categories"]}
    assert cats["ERP_APP"]["desk"] == "erp" and cats["PRINTER"]["desk"] == "it"
    t = make_ticket(client, code="PRINTER", subject="Printer jam on 2nd floor", desk="it")
    assert t["desk"] == "it"
    t2 = make_ticket(client, code="ERP_APP", subject="ERP PO screen error", desk="both")
    assert t2["desk"] == "both"
    t3 = make_ticket(client, code="ERP_REPORT", subject="Report mismatch default team")   # no team sent
    assert t3["desk"] == "erp"


def test_category_must_match_chosen_team(client):
    r = client.post(API, headers=auth("employee"), json={"subject": "Wrong team pick", "description": "printer broken again",
                                                          "category_id": category_id("PRINTER"), "desk": "erp"})
    assert r.status_code == 422 and "IT" in r.json()["error"]["message"]


def test_subcategory_and_type_are_optional(client):
    r = client.post(API, headers=auth("employee"), json={"subject": "Mouse not working", "description": "Left button dead",
                                                          "category_id": category_id("HARDWARE"), "desk": "it"})
    assert r.status_code == 201 and r.json()["subcategory"] is None


def test_desk_filter_list_and_dashboard(client):
    it_t = make_ticket(client, code="NETWORK", subject="Wifi drops desk filter", desk="it")
    erp_t = make_ticket(client, code="ERP_DATA", subject="GRN duplicate desk filter", desk="erp")
    both_t = make_ticket(client, code="ERP_APP", subject="Both teams desk filter", desk="both")

    def nums(desk):
        return {i["number"] for i in client.get(API, params={"desk": desk, "q": "desk filter", "page_size": 100},
                                                headers=auth("admin")).json()["items"]}
    assert nums("it") == {it_t["number"], both_t["number"]}
    assert nums("erp") == {erp_t["number"], both_t["number"]}
    assert nums("all") == {it_t["number"], erp_t["number"], both_t["number"]}
    d_it = client.get("/api/v1/dashboard/ops", params={"desk": "it"}, headers=auth("admin")).json()["live"]["open"]
    d_all = client.get("/api/v1/dashboard/ops", headers=auth("admin")).json()["live"]["open"]
    assert 0 < d_it <= d_all


def test_admin_team_set_and_shown(client):
    r = client.post("/api/v1/admin/users", headers=auth("admin"), json={
        "full_name": "Erp Admin", "employee_code": "88001", "role": "it_admin", "password": "1", "desk": "erp"})
    assert r.status_code == 201 and r.json()["desk"] == "erp"
    uid = r.json()["id"]
    assert client.patch(f"/api/v1/admin/users/{uid}", headers=auth("admin"), json={"desk": "it"}).json()["desk"] == "it"
    assert client.get("/api/v1/auth/me", headers=auth("erp_admin")).json()["desk"] == "erp"


def test_excel_export_is_formatted(client):
    make_ticket(client, code="PRINTER", subject="=HYPERLINK(evil) printer", desk="it")
    r = client.get(f"{API}/export.xlsx", params={"desk": "all"}, headers=auth("admin"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Tickets"]
    assert ws["A4"].value == "Ticket No." and ws["A4"].fill.fgColor.rgb.endswith("1D5FC4") and ws["A4"].font.bold
    assert ws.freeze_panes == "B5" and ws.tables and ws.column_dimensions["F"].width >= 40
    assert ws["A5"].border.left.style == "thin"
    assert all(not str(c.value).startswith("=") for row in ws.iter_rows(min_row=5) for c in row if c.value)
    assert "Summary" in wb.sheetnames
    assert client.get(f"{API}/export.xlsx", headers=auth("employee")).status_code == 403


def test_employees_never_see_other_employees_tickets(client):
    mine = make_ticket(client, role="employee", subject="Private ticket of employee one")
    other = make_ticket(client, role="employee2", subject="Private ticket of employee two")
    for scope in ("all", "mine", "queue"):
        got = {i["number"] for i in client.get(API, params={"scope": scope, "page_size": 100},
                                               headers=auth("employee")).json()["items"]}
        assert other["number"] not in got and mine["number"] in got | {mine["number"]}
    assert client.get(f"{API}/{other['number']}", headers=auth("employee")).status_code == 404
    assert client.get(f"{API}/{other['number']}/comments", headers=auth("employee")).status_code == 404
    s = client.get("/api/v1/dashboard/search", params={"q": "Private ticket"}, headers=auth("employee")).json()
    assert other["number"] not in {t["number"] for t in s["tickets"]} and not s["people"]
