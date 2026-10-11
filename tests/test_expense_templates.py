# ruff: noqa: F811
from app.helpers import today
from tests.test_api import PROFILE, _register, client  # noqa: F401

URL = "/api/v1/expense-templates"


def _body(**over):
    return {"name": "Kawa", "category": "FUN", "amount": 14.5, **over}


def test_templates_are_listed_in_creation_order(client):
    auth = _register(client, "tpl1@b.pl")
    _, res = client.post(URL, json=_body(), headers=auth)
    assert res.status == 201
    assert (res.json["name"], res.json["category"], res.json["amount"]) == ("Kawa", "FUN", 14.5)
    client.post(URL, json=_body(name="Obiad", category="NEEDS", amount=32), headers=auth)

    _, listed = client.get(URL, headers=auth)
    assert [t["name"] for t in listed.json["items"]] == ["Kawa", "Obiad"]


def test_use_adds_manual_entry_and_counts_towards_category(client):
    auth = _register(client, "tpl2@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    tid = client.post(URL, json=_body(), headers=auth)[1].json["id"]

    _, res = client.post(f"{URL}/{tid}/use", json={}, headers=auth)
    assert res.status == 201
    assert (res.json["category"], res.json["amount"], res.json["note"]) == ("FUN", 14.5, "Kawa")
    assert res.json["spent_on"] == today().isoformat() and res.json["source_type"] is None

    # ten sam szablon drugi raz tego samego dnia to drugi wpis (dwie kawy)
    assert client.post(f"{URL}/{tid}/use", json={}, headers=auth)[1].status == 201
    _, listed = client.get("/api/v1/expenses", headers=auth)
    assert len(listed.json["items"]) == 2 and listed.json["totals"]["FUN"] == 29


def test_use_accepts_date(client):
    auth = _register(client, "tpl3@b.pl")
    tid = client.post(URL, json=_body(), headers=auth)[1].json["id"]
    first = today().replace(day=1).isoformat()

    _, res = client.post(f"{URL}/{tid}/use", json={"spent_on": first}, headers=auth)
    assert res.status == 201 and res.json["spent_on"] == first
    assert client.post(f"{URL}/{tid}/use", json={"spent_on": "wczoraj"}, headers=auth)[1].status == 422


def test_delete_keeps_ledger_entries(client):
    auth = _register(client, "tpl4@b.pl")
    tid = client.post(URL, json=_body(), headers=auth)[1].json["id"]
    client.post(f"{URL}/{tid}/use", json={}, headers=auth)

    _, res = client.delete(f"{URL}/{tid}", headers=auth)
    assert res.status == 200 and res.json == {"deleted": True}
    assert client.get(URL, headers=auth)[1].json["items"] == []
    assert len(client.get("/api/v1/expenses", headers=auth)[1].json["items"]) == 1
    assert client.post(f"{URL}/{tid}/use", json={}, headers=auth)[1].status == 404


def test_validation_and_limit(client):
    auth = _register(client, "tpl5@b.pl")
    assert client.post(URL, json=_body(amount=0), headers=auth)[1].status == 422
    assert client.post(URL, json=_body(name=""), headers=auth)[1].status == 422
    assert client.post(URL, json=_body(category="INNE"), headers=auth)[1].status == 422

    for i in range(20):
        assert client.post(URL, json=_body(name=f"Szablon {i}"), headers=auth)[1].status == 201
    assert client.post(URL, json=_body(name="Ponad limit"), headers=auth)[1].status == 409
    assert len(client.get(URL, headers=auth)[1].json["items"]) == 20


def test_templates_are_private_and_require_login(client):
    auth = _register(client, "tpl6@b.pl")
    tid = client.post(URL, json=_body(), headers=auth)[1].json["id"]
    other = _register(client, "tpl7@b.pl")

    assert client.get(URL, headers=other)[1].json["items"] == []
    assert client.post(f"{URL}/{tid}/use", json={}, headers=other)[1].status == 404
    assert client.delete(f"{URL}/{tid}", headers=other)[1].status == 404
    assert client.get(URL)[1].status == 401
    assert client.post(URL, json=_body())[1].status == 401
