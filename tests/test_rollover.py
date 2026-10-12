# ruff: noqa: F811
from datetime import date

import pytest

from app.budget import BudgetPlan, rollover_amount
from app.schemas import Category
from tests.test_api import PROFILE, _register, client  # noqa: F401

URL = "/api/v1/budget"
PERCENTAGES = {"NEEDS": 50, "FUTURE": 25, "GOALS": 15, "FUN": 10}  # przy dochodzie 7000: FUN = 700


def test_first_month_has_nothing_to_carry():
    assert rollover_amount(700, []) == 0


def test_unused_budget_accumulates_over_months():
    assert rollover_amount(700, [500]) == 200
    assert rollover_amount(700, [500, 600]) == 300  # 200 + 100 niewykorzystane w drugim miesiącu
    assert rollover_amount(700, [500, 850]) == 50  # przeniesione 200 pokrywa przekroczenie o 150


def test_overspending_does_not_carry_a_debt():
    assert rollover_amount(700, [1000]) == 0
    assert rollover_amount(700, [1000, 600]) == 100  # po przekroczeniu kolejny miesiąc startuje od zera, nie z minusa


def test_carry_is_capped_at_one_monthly_budget():
    assert rollover_amount(700, [0]) == 700
    assert rollover_amount(700, [0, 0, 0]) == 700


def test_plan_budget_includes_carry():
    plan = BudgetPlan(monthly_income=7000, rollover={**{c: 0.0 for c in Category}, Category.FUN: 200.0})
    assert plan.base_budget(Category.FUN) == 700 and plan.category_budget(Category.FUN) == 900
    assert plan.available(Category.FUN) == 900 and plan.category_budget(Category.NEEDS) == 3500


@pytest.fixture
def clock(monkeypatch):
    """Ustawia "dziś" dla liczenia budżetu (rejestr, przeniesienie, miesiąc włączenia opcji)."""

    def set_today(value: date):
        monkeypatch.setattr("app.helpers.today", lambda: value)

    return set_today


def _budget(client, auth, **over):
    return client.put(URL, json={"percentages": PERCENTAGES, **over}, headers=auth)[1]


def _spend(client, auth, amount, day, category="FUN"):
    body = {"category": category, "amount": amount, "spent_on": day}
    assert client.post("/api/v1/expenses", json=body, headers=auth)[1].status == 201


def test_rollover_is_off_by_default_and_zero_in_the_month_it_is_enabled(client, clock):
    clock(date(2026, 1, 15))
    auth = _register(client, "roll1@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)

    res = _budget(client, auth)
    assert res.status == 200 and res.json["rollover"] == {"NEEDS": False, "FUTURE": False, "GOALS": False, "FUN": False}

    res = _budget(client, auth, rollover={"FUN": True})
    assert res.json["rollover"]["FUN"] is True and res.json["rollover"]["GOALS"] is False
    assert res.json["rollover_amounts"]["FUN"] == 0 and res.json["amounts"]["FUN"] == 700


def test_rollover_over_several_months(client, clock):
    clock(date(2026, 1, 15))
    auth = _register(client, "roll2@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _budget(client, auth, rollover={"FUN": True})
    _spend(client, auth, 500, "2026-01-10")
    _spend(client, auth, 300, "2026-01-12", category="GOALS")  # kategoria bez opcji niczego nie przenosi

    clock(date(2026, 2, 15))
    _, res = client.get(URL, headers=auth)
    assert res.json["rollover_amounts"] == {"NEEDS": 0, "FUTURE": 0, "GOALS": 0, "FUN": 200}
    assert res.json["amounts"]["FUN"] == 900 and res.json["available"]["FUN"] == 900
    assert res.json["amounts"]["GOALS"] == 1050

    # luty: przekroczenie powiększonego budżetu nie tworzy długu na marzec
    _spend(client, auth, 1000, "2026-02-05")
    clock(date(2026, 3, 15))
    _, res = client.get(URL, headers=auth)
    assert res.json["rollover_amounts"]["FUN"] == 0 and res.json["amounts"]["FUN"] == 700

    # marzec i kwiecień bez wydatków: przeniesienie zatrzymuje się na jednym miesięcznym budżecie
    clock(date(2026, 5, 15))
    _, res = client.get(URL, headers=auth)
    assert res.json["rollover_amounts"]["FUN"] == 700 and res.json["amounts"]["FUN"] == 1400


def test_saving_budget_without_rollover_field_keeps_setting_and_turning_off_resets(client, clock):
    clock(date(2026, 1, 15))
    auth = _register(client, "roll3@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _budget(client, auth, rollover={"FUN": True})
    _spend(client, auth, 500, "2026-01-10")

    clock(date(2026, 2, 15))
    res = _budget(client, auth)  # zapis planu bez pola rollover (np. starszy klient)
    assert res.json["rollover"]["FUN"] is True and res.json["rollover_amounts"]["FUN"] == 200

    res = _budget(client, auth, rollover={"FUN": False})
    assert res.json["rollover"]["FUN"] is False and res.json["amounts"]["FUN"] == 700

    # ponowne włączenie liczy od nowa: styczeń już się nie liczy
    res = _budget(client, auth, rollover={"FUN": True})
    assert res.json["rollover_amounts"]["FUN"] == 0
    clock(date(2026, 3, 15))
    assert client.get(URL, headers=auth)[1].json["rollover_amounts"]["FUN"] == 700  # luty bez wydatków


def test_carried_amount_feeds_forecast(client, clock):
    clock(date(2026, 1, 15))
    auth = _register(client, "roll4@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _budget(client, auth, rollover={"FUN": True})
    _spend(client, auth, 500, "2026-01-10")

    clock(date(2026, 2, 15))
    _, res = client.get("/api/v1/budget/forecast", headers=auth)
    fun = next(c for c in res.json["categories"] if c["category"] == "FUN")
    assert fun["budget"] == 900
