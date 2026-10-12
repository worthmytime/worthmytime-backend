# ruff: noqa: F811
from datetime import datetime

from tests.test_api import _register, client  # noqa: F401

IMPORT = "/api/v1/expenses/import"
HISTORY = "/api/v1/imports"
EXPENSES = "/api/v1/expenses?month=2026-10"


def _item(n, amount=10.0, **over):
    row = {"category": "FUN", "amount": amount, "note": f"pozycja {n}", "spent_on": "2026-10-06"}
    return {**row, "key": f"klucz-{n:04d}", **over}


def _import(client, auth, items, **extra):
    return client.post(IMPORT, json={"items": items, **extra}, headers=auth)[1]


def _history(client, auth):
    return client.get(HISTORY, headers=auth)[1].json["items"]


def test_import_is_recorded_with_file_name_time_and_counts(client):
    auth = _register(client, "hist1@b.pl")
    res = _import(client, auth, [_item(1, 14.5), _item(2, 25), _item(2, 25)], file_name="wyciag-pazdziernik.csv")
    assert res.status == 201 and res.json["batch_id"]

    (batch,) = _history(client, auth)
    assert batch["id"] == res.json["batch_id"] and batch["file_name"] == "wyciag-pazdziernik.csv"
    assert (batch["created"], batch["skipped"], batch["total"], batch["remaining"]) == (2, 1, 39.5, 2)
    assert batch["undone_at"] is None
    assert datetime.fromisoformat(batch["imported_at"]).tzinfo is not None  # data i godzina ze strefą


def test_undo_removes_only_entries_of_that_import(client):
    auth = _register(client, "hist2@b.pl")
    first = _import(client, auth, [_item(1), _item(2)], file_name="pierwszy.xlsx").json["batch_id"]
    second = _import(client, auth, [_item(3)], file_name="drugi.csv").json["batch_id"]
    client.post("/api/v1/expenses", json={"category": "FUN", "amount": 5, "spent_on": "2026-10-06"}, headers=auth)

    _, res = client.delete(f"{HISTORY}/{first}", headers=auth)
    assert res.status == 200 and res.json["deleted"] == 2 and res.json["undone_at"] is not None

    notes = sorted(e["note"] or "ręczny" for e in client.get(EXPENSES, headers=auth)[1].json["items"])
    assert notes == ["pozycja 3", "ręczny"]  # drugi import i wpis ręczny zostają
    by_id = {b["id"]: b for b in _history(client, auth)}
    assert by_id[first]["remaining"] == 0 and by_id[first]["undone_at"] is not None
    assert by_id[first]["created"] == 2  # historia pamięta, ile wpisów dopisał cofnięty import
    assert by_id[second]["remaining"] == 1 and by_id[second]["undone_at"] is None
    assert client.delete(f"{HISTORY}/{first}", headers=auth)[1].status == 409  # już cofnięty


def test_file_can_be_imported_again_after_undo(client):
    auth = _register(client, "hist3@b.pl")
    items = [_item(1), _item(2)]
    batch = _import(client, auth, items, file_name="wyciag.csv").json["batch_id"]
    client.delete(f"{HISTORY}/{batch}", headers=auth)

    again = _import(client, auth, items, file_name="wyciag.csv")
    assert (again.json["created"], again.json["skipped"]) == (2, 0) and again.json["batch_id"] != batch
    assert [b["file_name"] for b in _history(client, auth)] == ["wyciag.csv", "wyciag.csv"]


def test_large_file_is_one_import_across_requests(client):
    auth = _register(client, "hist4@b.pl")
    first = _import(client, auth, [_item(1), _item(2)], file_name="duzy.csv").json["batch_id"]
    res = _import(client, auth, [_item(3)], batch_id=first)
    assert res.json["batch_id"] == first

    (batch,) = _history(client, auth)
    assert (batch["created"], batch["total"], batch["remaining"]) == (3, 30, 3)
    client.delete(f"{HISTORY}/{first}", headers=auth)
    assert _import(client, auth, [_item(4)], batch_id=first).status == 409  # do cofniętego importu nic nie dopiszemy


def test_edited_entry_is_removed_and_deleted_entry_lowers_remaining(client):
    auth = _register(client, "hist5@b.pl")
    batch = _import(client, auth, [_item(1), _item(2)], file_name="wyciag.csv").json["batch_id"]
    one, two = client.get(EXPENSES, headers=auth)[1].json["items"]
    client.put(f"/api/v1/expenses/{one['id']}", json={"category": "NEEDS", "amount": 99}, headers=auth)
    client.delete(f"/api/v1/expenses/{two['id']}", headers=auth)

    assert _history(client, auth)[0]["remaining"] == 1
    assert client.delete(f"{HISTORY}/{batch}", headers=auth)[1].json["deleted"] == 1  # edytowany wpis też znika
    assert client.get(EXPENSES, headers=auth)[1].json["items"] == []


def test_history_is_private_and_requires_login(client):
    auth = _register(client, "hist6@b.pl")
    batch = _import(client, auth, [_item(1)], file_name="moj.csv").json["batch_id"]
    other = _register(client, "hist7@b.pl")

    assert _history(client, other) == []
    assert client.delete(f"{HISTORY}/{batch}", headers=other)[1].status == 404
    assert _import(client, other, [_item(9)], batch_id=batch).status == 404
    assert client.get(HISTORY)[1].status == 401
    assert len(client.get(EXPENSES, headers=auth)[1].json["items"]) == 1


def test_import_without_file_name_is_still_recorded(client):
    auth = _register(client, "hist8@b.pl")
    _import(client, auth, [_item(1)])
    (batch,) = _history(client, auth)
    assert batch["file_name"] is None and batch["created"] == 1
    assert _import(client, auth, [_item(2)], file_name="x" * 256).status == 422
