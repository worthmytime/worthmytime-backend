# ruff: noqa: F811
from datetime import date

from tests.test_api import PROFILE, _register, client  # noqa: F401

URL = "/api/v1/budget"
PERCENTAGES = {"NEEDS": 50, "FUTURE": 25, "GOALS": 15, "FUN": 10}  # przy dochodzie 7000: Potrzeby = 3500


def _today(monkeypatch, value):
    monkeypatch.setattr("app.helpers.today", lambda: value)


def test_last_installment_counts_for_the_whole_month_it_was_due(client, monkeypatch):
    _today(monkeypatch, date(2026, 10, 5))
    auth = _register(client, "loanm1@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    loans = [
        # ostatnia rata 11 października
        {"name": "Pożyczka", "installment_amount": 540.18, "end_date": "2026-10-11", "payment_day": 11},
        {"name": "Kredyt", "installment_amount": 800, "installments_left": 24, "payment_day": 20},
    ]
    res = client.put(URL, json={"percentages": PERCENTAGES, "loans": loans}, headers=auth)[1]
    assert res.status == 200 and res.json["monthly_loans"] == 1340.18

    # po dniu ostatniej raty pożyczka jest spłacona, ale rata z tego miesiąca nadal obciąża budżet miesiąca
    _today(monkeypatch, date(2026, 10, 20))
    body = client.get(URL, headers=auth)[1].json
    finished = next(x for x in body["loans"] if x["name"] == "Pożyczka")
    assert finished["finished"] is True and finished["installments_left"] == 0
    assert body["monthly_loans"] == 1340.18 and body["available"]["NEEDS"] == 2159.82

    # od następnego miesiąca spłacona pożyczka nie wchodzi już do budżetu
    _today(monkeypatch, date(2026, 11, 2))
    body = client.get(URL, headers=auth)[1].json
    assert body["monthly_loans"] == 800 and body["available"]["NEEDS"] == 2700


def _loan(**over):
    return {"name": "Kredyt auto", "installment_amount": 800, "installments_left": 24, "payment_day": 12, **over}


def test_saving_budget_keeps_loan_ids_and_paid_installments_stay_linked(client):
    auth = _register(client, "loanm2@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    saved = client.put(URL, json={"percentages": PERCENTAGES, "loans": [_loan()]}, headers=auth)[1].json["loans"]
    loan_id = saved[0]["id"]
    paid = client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={}, headers=auth)[1]
    assert paid.status == 201 and paid.json["source_id"] == loan_id

    # ponowny zapis z tym samym id zmienia kredyt w miejscu
    body = {"percentages": PERCENTAGES, "loans": [_loan(id=loan_id, name="Kredyt na auto", installment_amount=850)]}
    (after,) = client.put(URL, json=body, headers=auth)[1].json["loans"]
    assert (after["id"], after["name"], after["installment_amount"]) == (loan_id, "Kredyt na auto", 850)
    # rata z tego miesiąca jest nadal rozpoznawana jako opłacona
    assert client.post(f"/api/v1/budget/loans/{loan_id}/pay", json={}, headers=auth)[1].status == 409


def test_budget_saved_without_loans_field_leaves_loans_untouched(client):
    auth = _register(client, "loanm3@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    (loan,) = client.put(URL, json={"percentages": PERCENTAGES, "loans": [_loan()]}, headers=auth)[1].json["loans"]

    # zapis samych procentów (strona Budżet): kredyty i ich identyfikatory zostają
    res = client.put(URL, json={"percentages": {"NEEDS": 60, "FUTURE": 20, "GOALS": 10, "FUN": 10}}, headers=auth)[1]
    assert res.status == 200 and res.json["percentages"]["NEEDS"] == 60
    assert [x["id"] for x in res.json["loans"]] == [loan["id"]] and res.json["monthly_loans"] == 800

    # pusta lista nadal usuwa wszystkie kredyty
    res = client.put(URL, json={"percentages": PERCENTAGES, "loans": []}, headers=auth)[1]
    assert res.json["loans"] == [] and res.json["monthly_loans"] == 0


def test_loans_are_added_updated_and_removed_by_id(client):
    auth = _register(client, "loanm4@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    first, second = client.put(
        URL, json={"percentages": PERCENTAGES, "loans": [_loan(name="A"), _loan(name="B")]}, headers=auth
    )[1].json["loans"]

    # B zostaje (z id), A znika, C jest nowy; nieznany id oznacza po prostu nowy kredyt
    body = {"percentages": PERCENTAGES, "loans": [_loan(id=second["id"], name="B"), _loan(id="nie-ma", name="C")]}
    loans = client.put(URL, json=body, headers=auth)[1].json["loans"]
    assert [x["name"] for x in loans] == ["B", "C"]
    assert loans[0]["id"] == second["id"] and loans[1]["id"] not in (first["id"], second["id"], "nie-ma")

    # cudzy identyfikator nie daje dostępu do cudzego kredytu
    other = _register(client, "loanm5@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=other)
    mine = client.put(URL, json={"percentages": PERCENTAGES, "loans": [_loan(id=second["id"], name="X")]}, headers=other)
    assert mine[1].json["loans"][0]["id"] != second["id"]
    assert [x["name"] for x in client.get(URL, headers=auth)[1].json["loans"]] == ["B", "C"]
