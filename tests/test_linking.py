# ruff: noqa: F811
from app.helpers import today
from tests.test_api import PROFILE, _register, client  # noqa: F401

WISHLIST = "/api/v1/wishlist"
GOALS = "/api/v1/goals"
EXPENSES = "/api/v1/expenses"


def _user(client, email):
    auth = _register(client, email)
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    return auth


def _wish(client, auth, **over):
    body = {"name": "Monitor", "price": 1500, "cooldown_days": 0, **over}
    return client.post(WISHLIST, json=body, headers=auth)[1].json["id"]


def _ledger(client, auth):
    return client.get(EXPENSES, headers=auth)[1].json


def test_buying_a_wish_adds_expense_and_undo_removes_it(client):
    auth = _user(client, "link1@b.pl")
    wid = _wish(client, auth, category="GOALS")

    _, res = client.post(f"{WISHLIST}/{wid}/decision", json={"decision": "BOUGHT"}, headers=auth)
    assert res.status == 200 and res.json["status"] == "BOUGHT"
    expense = res.json["expense"]
    assert (expense["category"], expense["amount"], expense["note"]) == ("GOALS", 1500, "Monitor")
    assert (expense["source_type"], expense["source_id"], expense["spent_on"]) == ("WISH", wid, today().isoformat())
    assert _ledger(client, auth)["totals"]["GOALS"] == 1500  # zakup od razu obciąża budżet kategorii

    _, res = client.delete(f"{WISHLIST}/{wid}/decision", headers=auth)
    assert res.status == 200 and res.json["status"] == "WAITING" and res.json["decided_at"] is None
    assert _ledger(client, auth)["items"] == []
    assert client.delete(f"{WISHLIST}/{wid}/decision", headers=auth)[1].status == 409  # nie ma już czego cofać
    # po cofnięciu decyzję można podjąć ponownie
    assert client.post(f"{WISHLIST}/{wid}/decision", json={"decision": "DROPPED"}, headers=auth)[1].status == 200


def test_wish_expense_category_and_opt_out(client):
    auth = _user(client, "link2@b.pl")
    plain, moved, skipped, dropped = (_wish(client, auth, name=n) for n in ("A", "B", "C", "D"))

    def decide(wish_id, **body):
        return client.post(f"{WISHLIST}/{wish_id}/decision", json=body, headers=auth)[1].json["expense"]

    assert decide(plain, decision="BOUGHT")["category"] == "FUN"  # pozycja bez kategorii
    assert decide(moved, decision="BOUGHT", category="NEEDS")["category"] == "NEEDS"
    assert decide(skipped, decision="BOUGHT", add_expense=False) is None
    assert decide(dropped, decision="DROPPED") is None

    assert sorted(e["note"] for e in _ledger(client, auth)["items"]) == ["A", "B"]
    # usunięcie kupionej pozycji z listy nie rusza wydatku: zakup się odbył
    client.delete(f"{WISHLIST}/{plain}", headers=auth)
    assert len(_ledger(client, auth)["items"]) == 2


def test_goal_deposit_adds_expense_in_goal_category_or_future(client):
    auth = _user(client, "link3@b.pl")
    plain = client.post(GOALS, json={"name": "Poduszka", "target_amount": 5000}, headers=auth)[1].json["id"]
    trip = client.post(GOALS, json={"name": "Wakacje", "target_amount": 5000, "category": "GOALS"}, headers=auth)[1]

    client.post(f"{GOALS}/{plain}/deposit", json={"amount": 300}, headers=auth)
    client.post(f"{GOALS}/{trip.json['id']}/deposit", json={"amount": 200}, headers=auth)
    client.post(f"{GOALS}/{plain}/deposit", json={"amount": 50, "add_expense": False}, headers=auth)
    client.post(f"{GOALS}/{plain}/deposit", json={"amount": -100}, headers=auth)  # wypłata nie tworzy wydatku

    ledger = _ledger(client, auth)
    entries = sorted((e["category"], e["amount"], e["note"], e["source_type"]) for e in ledger["items"])
    assert entries == [("FUTURE", 300, "Cel: Poduszka", "GOAL"), ("GOALS", 200, "Cel: Wakacje", "GOAL")]

    history = client.get(f"{GOALS}/{plain}/deposits", headers=auth)[1].json["items"]
    assert sorted((d["amount"], d["in_ledger"]) for d in history) == [(-100, False), (50, False), (300, True)]


def test_undoing_a_deposit_restores_goal_and_removes_expense(client):
    auth = _user(client, "link4@b.pl")
    gid = client.post(GOALS, json={"name": "Poduszka", "target_amount": 5000}, headers=auth)[1].json["id"]
    client.post(f"{GOALS}/{gid}/deposit", json={"amount": 300}, headers=auth)
    client.post(f"{GOALS}/{gid}/deposit", json={"amount": 100}, headers=auth)
    deposits = client.get(f"{GOALS}/{gid}/deposits", headers=auth)[1].json["items"]
    big = next(d["id"] for d in deposits if d["amount"] == 300)

    _, res = client.delete(f"{GOALS}/{gid}/deposits/{big}", headers=auth)
    assert res.status == 200 and res.json["saved_amount"] == 100
    assert [e["amount"] for e in _ledger(client, auth)["items"]] == [100]
    assert client.get(f"{GOALS}/{gid}/deposits", headers=auth)[1].json["total"] == 100
    assert client.delete(f"{GOALS}/{gid}/deposits/{big}", headers=auth)[1].status == 404  # już cofnięta


def test_deposit_cannot_be_undone_after_money_was_withdrawn(client):
    auth = _user(client, "link5@b.pl")
    gid = client.post(GOALS, json={"name": "Poduszka", "target_amount": 5000}, headers=auth)[1].json["id"]
    client.post(f"{GOALS}/{gid}/deposit", json={"amount": 300}, headers=auth)
    client.post(f"{GOALS}/{gid}/deposit", json={"amount": -200}, headers=auth)
    deposit = next(
        d["id"] for d in client.get(f"{GOALS}/{gid}/deposits", headers=auth)[1].json["items"] if d["amount"] == 300
    )

    assert client.delete(f"{GOALS}/{gid}/deposits/{deposit}", headers=auth)[1].status == 409
    other = _user(client, "link6@b.pl")
    assert client.delete(f"{GOALS}/{gid}/deposits/{deposit}", headers=other)[1].status == 404
    assert len(_ledger(client, auth)["items"]) == 1  # nieudane cofnięcia niczego nie usunęły
