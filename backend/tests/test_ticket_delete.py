from sqlalchemy import select

from app.models import AuditLog, Notification, Ticket
from tests.conftest import EMAILS, SessionLocal, auth, make_ticket, user_id

API = "/api/v1/tickets"


def test_employee_cannot_delete_but_can_cancel_and_still_sees_it(client):
    t = make_ticket(client, subject="Cancel instead of delete")
    n = t["number"]
    assert t["can_delete"] is False
    assert client.delete(f"{API}/{n}", headers=auth("employee")).status_code == 403
    # cancel works even after IT has started
    v = client.post(f"{API}/{n}/status", headers=auth("admin"),
                    json={"to_status": "IN_PROGRESS", "expected_version": t["version"]}).json()["version"]
    d = client.get(f"{API}/{n}", headers=auth("employee")).json()
    assert "CANCELLED" in [s["code"] for s in d["allowed_transitions"]]
    r = client.post(f"{API}/{n}/status", headers=auth("employee"),
                    json={"to_status": "CANCELLED", "reason": "Not needed any more", "expected_version": v})
    assert r.status_code == 200 and r.json()["status"]["code"] == "CANCELLED"
    # still in the employee's history and the admin's full export
    mine = client.get(API, params={"scope": "mine", "status": "CANCELLED"}, headers=auth("employee")).json()["items"]
    assert n in [i["number"] for i in mine]
    allx = client.get(f"{API}/export.xlsx", params={"desk": "all"}, headers=auth("admin"))
    from io import BytesIO

    from openpyxl import load_workbook
    ws = load_workbook(BytesIO(allx.content))["Tickets"]
    assert n in [c.value for c in ws["A"]]


def test_admin_can_delete_and_assignee_is_told(client):
    t = make_ticket(client, subject="Admin deletes this")
    n = t["number"]
    client.post(f"{API}/{n}/comments", headers=auth("employee"), json={"body": "one more detail"})
    assert client.get(f"{API}/{n}", headers=auth("admin")).json()["can_delete"] is True
    assert client.delete(f"{API}/{n}", headers=auth("admin")).status_code == 204
    assert client.get(f"{API}/{n}", headers=auth("admin")).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(Ticket).where(Ticket.number == n)) is None
        a = db.scalar(select(AuditLog).where(AuditLog.action == "ticket.delete", AuditLog.entity_id == n))
        assert a is not None and a.actor_id == user_id(EMAILS["admin"])
        assert db.scalar(select(Notification).where(Notification.user_id == user_id(EMAILS["employee"]),
                                                    Notification.title.like(f"Your ticket {n} was deleted%")))


def test_other_employee_cannot_see_or_delete(client):
    n = make_ticket(client, subject="Not yours")["number"]
    assert client.delete(f"{API}/{n}", headers=auth("employee2")).status_code == 404


def test_numbers_per_department(client):
    it = make_ticket(client, code="PRINTER", subject="Printer series", desk="it")["number"]
    erp = make_ticket(client, code="ERP_APP", subject="ERP series", desk="erp")["number"]
    both = make_ticket(client, code="ERP_APP", subject="Both series", desk="both")["number"]
    assert it.startswith("IT-26-") and erp.startswith("ERP-26-") and both.startswith("ITERP-26-")
    it2 = make_ticket(client, code="NETWORK", subject="Printer series 2", desk="it")["number"]
    assert int(it2[-6:]) == int(it[-6:]) + 1          # each department counts on its own
    assert len({it, erp, both, it2}) == 4
    assert client.get(f"{API}/{both}", headers=auth("admin")).status_code == 200


def test_excel_has_attachment_columns(client):
    t = make_ticket(client, subject="Excel attachment check")
    up = client.post(f"{API}/{t['number']}/attachments", headers=auth("employee"),
                     files={"file": ("screen.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")})
    assert up.status_code == 201, up.text
    from io import BytesIO

    from openpyxl import load_workbook
    ws = load_workbook(BytesIO(client.get(f"{API}/export.xlsx", params={"desk": "all"}, headers=auth("admin")).content))["Tickets"]
    head = [c.value for c in ws[4]]
    assert head[-3:] == ["Attachments", "File names", "Attachment link"]
    row = next(r for r in ws.iter_rows(min_row=5) if r[0].value == t["number"])
    assert row[15].value == "Yes (1)" and row[16].value == "screen.png"
    assert row[17].hyperlink is not None and row[17].hyperlink.target.endswith(f"#/tickets/{t['number']}/files")
    other = next(r for r in ws.iter_rows(min_row=5) if r[15].value == "No")
    assert other[17].hyperlink is None
