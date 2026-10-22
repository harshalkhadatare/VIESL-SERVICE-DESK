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
    assert upload(client, "employee", t["number"], "empty.png", b"").status_code == 422


def test_size_limit(client, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    t = make_ticket(client)
    r = upload(client, "employee", t["number"], "big.png", PNG + b"a" * (1024 * 1024 + 10))
    assert r.status_code == 422


def test_path_traversal_name_is_sanitised(client):
    t = make_ticket(client)
    r = upload(client, "employee", t["number"], "../../etc/passwd.png", PNG)
    assert r.status_code == 201 and "/" not in r.json()["original_name"]


def test_internal_attachment_hidden_from_requester(client):
    t = make_ticket(client)
    assert upload(client, "employee", t["number"], "x.png", PNG, internal=True).status_code == 403
    aid = upload(client, "admin", t["number"], "logs.png", PNG, internal=True).json()["id"]
    names = [a["original_name"] for a in client.get(f"{API}/{t['number']}/attachments",
                                                    headers=auth("employee")).json()]
    assert "logs.png" not in names
    assert client.get(f"{API}/{t['number']}/attachments/{aid}", headers=auth("employee")).status_code == 404


def test_only_images_and_pdf_allowed(client):
    t = make_ticket(client)
    n = t["number"]
    ok = {"photo.jpg": b"\xff\xd8\xff\xe0" + b"0" * 40, "scan.pdf": b"%PDF-1.7\n" + b"0" * 40,
          "anim.gif": b"GIF89a" + b"0" * 40, "pic.webp": b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 40,
          "bitmap.bmp": b"BM" + b"0" * 40, "page.tiff": b"II*\x00" + b"0" * 40,
          "phone.heic": b"\x00\x00\x00\x18ftypheic" + b"0" * 40}
    for name, data in ok.items():
        assert upload(client, "employee", n, name, data).status_code == 201, name
    for name, data in {"notes.txt": b"hello", "sheet.xlsx": b"PK\x03\x04", "doc.docx": b"PK\x03\x04",
                       "logo.svg": b"<svg onload=alert(1)>", "data.csv": b"a,b"}.items():
        r = upload(client, "employee", n, name, data)
        assert r.status_code == 422 and "images" in r.json()["error"]["message"], name


def test_export_requires_admin_and_neutralises_formulas(client):
    make_ticket(client, code="QUERY", subject="=HYPERLINK(\"http://evil\",\"x\") test")
    assert client.get(f"{API}/export.csv", headers=auth("employee")).status_code == 403
    r = client.get(f"{API}/export.csv", headers=auth("admin"))
    assert r.status_code == 200
    assert "'=HYPERLINK" in r.text and ',=HYPERLINK' not in r.text
