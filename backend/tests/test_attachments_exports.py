import io

from tests.conftest import auth, make_ticket

API = "/api/v1/tickets"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def upload(client, role, number, name, data, internal=False):
    return client.post(f"{API}/{number}/attachments", headers=auth(role),
                       files={"file": (name, io.BytesIO(data), "application/octet-stream")},
                       data={"is_internal": "true" if internal else "false"})


def test_upload_and_download_by_owner(client):
    t = make_ticket(client)
    r = upload(client, "employee", t["number"], "screen.png", PNG)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    d = client.get(f"{API}/{t['number']}/attachments/{aid}", headers=auth("employee"))
    assert d.status_code == 200 and d.content == PNG
    assert "attachment" in d.headers["content-disposition"]
    assert d.headers["x-content-type-options"] == "nosniff"


def test_other_user_cannot_download(client):
    t = make_ticket(client)
    aid = upload(client, "employee", t["number"], "screen.png", PNG).json()["id"]
    assert client.get(f"{API}/{t['number']}/attachments/{aid}", headers=auth("employee2")).status_code == 404


def test_rejects_disguised_and_disallowed_files(client):
    t = make_ticket(client)
    assert upload(client, "employee", t["number"], "invoice.pdf", b"MZ\x90\x00 not a pdf").status_code == 422
    assert upload(client, "employee", t["number"], "tool.exe", b"MZ\x90\x00").status_code == 422
    assert upload(client, "employee", t["number"], "page.html", b"<script>").status_code == 422
    assert upload(client, "employee", t["number"], "empty.txt", b"").status_code == 422


def test_size_limit(client, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    t = make_ticket(client)
    r = upload(client, "employee", t["number"], "big.txt", b"a" * (1024 * 1024 + 10))
    assert r.status_code == 422


def test_path_traversal_name_is_sanitised(client):
    t = make_ticket(client)
    r = upload(client, "employee", t["number"], "../../etc/passwd.txt", b"hello")
    assert r.status_code == 201 and "/" not in r.json()["original_name"]


def test_internal_attachment_hidden_from_requester(client):
    t = make_ticket(client)
    eng = "erp_engineer" if t["assignee"]["full_name"] == "Amit Deshmukh" else "erp_engineer2"
    assert upload(client, "employee", t["number"], "x.png", PNG, internal=True).status_code == 403
    aid = upload(client, eng, t["number"], "logs.txt", b"internal log", internal=True).json()["id"]
    names = [a["original_name"] for a in client.get(f"{API}/{t['number']}/attachments",
                                                    headers=auth("employee")).json()]
    assert "logs.txt" not in names
    assert client.get(f"{API}/{t['number']}/attachments/{aid}", headers=auth("employee")).status_code == 404


def test_export_requires_permission_and_neutralises_formulas(client):
    make_ticket(client, code="QUERY", subject="=HYPERLINK(\"http://evil\",\"x\") test")
    assert client.get(f"{API}/export.csv", headers=auth("employee")).status_code == 403
    assert client.get(f"{API}/export.csv", headers=auth("erp_engineer")).status_code == 403
    r = client.get(f"{API}/export.csv", headers=auth("management"))
    assert r.status_code == 200
    assert "'=HYPERLINK" in r.text and ',=HYPERLINK' not in r.text


def test_export_is_scoped_like_list(client):
    make_ticket(client, code="QUERY", subject="Scoped export marker zz91")
    lead = client.get(f"{API}/export.csv", params={"q": "zz91"}, headers=auth("infra_lead"))
    assert lead.status_code == 200 and "zz91" not in lead.text   # SD ticket, not Neha's group
    sd_lead = client.get(f"{API}/export.csv", params={"q": "zz91"}, headers=auth("erp_lead"))
    assert "zz91" in sd_lead.text
