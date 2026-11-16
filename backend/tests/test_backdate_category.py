from tests.conftest import auth


def test_erp_back_date_lock_open_category(client):
    cats = client.get("/api/v1/meta/catalog", headers=auth("employee")).json()["categories"]
    c = next(x for x in cats if x["code"] == "ERP_BACKDATE")
    assert c["name"] == "ERP Back Date Lock Open" and c["desk"] == "erp"
    assert [s["name"] for s in c["subcategories"]] == ["Pending work"]
    erp = [x["code"] for x in cats if x["desk"] == "erp"]
    assert erp.index("ERP_BACKDATE") == erp.index("ERP_REPORT") + 1
    app = next(x for x in cats if x["code"] == "ERP_APP")
    assert "Pending Work" not in [s["name"] for s in app["subcategories"]]
