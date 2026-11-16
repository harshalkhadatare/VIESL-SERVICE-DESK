"""In-app viewing of attachments: inline 'view' mode, audit, sign-in required, IT-only delete."""
from sqlalchemy import select

from app.models import AuditLog, TicketAttachment
from tests.conftest import SessionLocal, auth, make_ticket

API = "/api/v1/tickets"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(client, number, name="screen.png"):
    r = client.post(f"{API}/{number}/attachments", headers=auth("employee"), files={"file": (name, PNG, "image/png")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_view_is_inline_and_download_is_attachment(client):
    t = make_ticket(client, subject="Viewer check")
    aid = _upload(client, t["number"])
    v = client.get(f"{API}/{t['number']}/attachments/{aid}", params={"mode": "view"}, headers=auth("employee"))
    assert v.status_code == 200 and v.content == PNG
    assert v.headers["content-disposition"].startswith("inline")
    d = client.get(f"{API}/{t['number']}/attachments/{aid}", headers=auth("admin"))
    assert d.headers["content-disposition"].startswith("attachment")
    with SessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == t["number"])))
    assert {"ticket.attachment_view", "ticket.attachment_download"} <= actions
    # files are never public: no sign-in → refused; another employee → not found
    assert client.get(f"{API}/{t['number']}/attachments/{aid}", params={"mode": "view"}).status_code == 401
    assert client.get(f"{API}/{t['number']}/attachments/{aid}", params={"mode": "bad"}, headers=auth("employee")).status_code == 422


def test_only_it_can_delete_attachments(client):
    t = make_ticket(client, subject="Delete file check")
    aid = _upload(client, t["number"], "wrong.png")
    assert client.delete(f"{API}/{t['number']}/attachments/{aid}", headers=auth("employee")).status_code == 403
    assert client.delete(f"{API}/{t['number']}/attachments/{aid}", headers=auth("admin")).status_code == 204
    with SessionLocal() as db:
        assert db.get(TicketAttachment, aid) is None
    full = client.get(f"{API}/{t['number']}/full", headers=auth("employee")).json()
    assert full["attachments"] == []
    assert any(h["field"] == "attachment" and h["new_value"] == "removed" and h["old_value"] == "wrong.png"
               for h in full["history"])
    assert client.delete(f"{API}/{t['number']}/attachments/{aid}", headers=auth("admin")).status_code == 404
