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
