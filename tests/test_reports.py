# ruff: noqa: F811
import csv
import io

import pytest

from app.budget import BudgetPlan
from app.helpers import today
from app.planning import period_of
from app.reports import export_csv, month_report
from app.schemas import Category
from tests.test_api import PROFILE, _register, client  # noqa: F401

REPORT = "/api/v1/reports/month"
EXPORT = "/api/v1/export"


def _plan(**over):
    spent = {Category.NEEDS: 1200.0, Category.FUTURE: 500.0, Category.GOALS: 300.0, Category.FUN: 400.0}
    return BudgetPlan(monthly_income=7000, spent=spent, **over)


def test_report_compares_categories_with_budget_and_previous_month():
    report = month_report(_plan(monthly_loans=800), {"NEEDS": 1000, "FUN": 800}, None, 4, hourly_rate=40)
    by = {c["category"]: c for c in report["categories"]}

    # raty kredytów (800) liczą się do Potrzeb w obu miesiącach
    assert (by["NEEDS"]["budget"], by["NEEDS"]["spent"], by["NEEDS"]["available"]) == (3500, 2000, 1500)
    assert (by["NEEDS"]["previous"], by["NEEDS"]["change"], by["NEEDS"]["change_percent"]) == (1800, 200, 11.1)
    assert (by["FUN"]["usage_percent"], by["FUN"]["change"], by["FUN"]["change_percent"]) == (57.1, -400, -50.0)
    assert by["GOALS"]["previous"] == 0 and by["GOALS"]["change_percent"] is None  # nie ma do czego porównać

    assert (report["total_spent"], report["previous"], report["change"]) == (3200, 2600, 600)
    assert report["saved"] == {"future": 500, "unspent": 3800}
    assert report["discretionary"] == {"spent": 700, "work_hours": 17.5}  # Cele + Przyjemności przy 40 zł/h
    assert report["largest_expense"] is None and report["entries"] == 4


def test_report_without_rate_and_with_overspending():
    plan = BudgetPlan(monthly_income=1000, spent={**{c: 0.0 for c in Category}, Category.FUN: 1500.0})
    report = month_report(plan, {}, None, 1, hourly_rate=None)
    assert report["saved"]["unspent"] == 0  # wydatki ponad dochód nie dają ujemnych oszczędności
    assert report["discretionary"]["work_hours"] is None


def _export(**over):
    data = {"expenses": [], "goals": [], "wishlist": [], "calculations": []}
    return {**data, **over}


def _expense_row(**over):
    row = {"id": "e1", "spent_on": "2026-09-03", "category": "FUN", "amount": 14.5, "note": "Kawa", "source_type": None}
    return {**row, **over}


GOAL_ROW = {
    "id": "g1",
    "name": "Wakacje",
    "category": "GOALS",
    "target_amount": 5000,
    "saved_amount": 1200,
    "monthly_contribution": None,
    "target_date": None,
    "created_at": "2026-08-01T10:00:00+00:00",
    "completed_at": None,
}
CALCULATION_ROW = {
    "id": "c1",
    "name": "Rower",
    "type": "SIMPLE",
    "category": None,
    "purchase_price": 3000,
    "ownership_years": None,
    "resale_value": 0,
    "costs": [],
    "created_at": "2026-07-01T10:00:00+00:00",
}


def test_csv_has_bom_header_and_one_row_per_item():
    text = export_csv(_export(expenses=[_expense_row()], goals=[GOAL_ROW], calculations=[CALCULATION_ROW]))
    assert text.startswith("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    assert [r["type"] for r in rows] == ["expense", "goal", "calculation"]
    assert rows[0] == {
        "type": "expense",
        "id": "e1",
        "date": "2026-09-03",
        "name": "Kawa",
        "category": "FUN",
        "amount": "14.5",
        "status": "",
        "target_amount": "",
    }
    assert (rows[1]["amount"], rows[1]["status"], rows[1]["target_amount"]) == ("1200", "active", "5000")
    assert (rows[2]["date"], rows[2]["status"], rows[2]["amount"]) == ("2026-07-01", "SIMPLE", "3000")


def test_csv_neutralizes_spreadsheet_formulas():
    note = "=HYPERLINK(1)"
    text = export_csv(_export(expenses=[_expense_row(note=note, amount=5)]))
    (row,) = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    assert row["name"] == "'" + note and row["amount"] == "5"


def _spend(client, auth, category, amount, day, note=None):
    body = {"category": category, "amount": amount, "spent_on": day, "note": note}
    assert client.post("/api/v1/expenses", json=body, headers=auth)[1].status == 201


def test_month_report_on_sample_data(client):
    auth = _register(client, "rep1@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _spend(client, auth, "NEEDS", 1200, "2026-09-02", "czynsz")
    _spend(client, auth, "FUN", 400, "2026-09-10", "koncert")
    _spend(client, auth, "FUN", 100, "2026-09-11")
    _spend(client, auth, "FUTURE", 500, "2026-09-15", "lokata")
    _spend(client, auth, "FUN", 250, "2026-08-20")  # poprzedni miesiąc

    _, res = client.get(f"{REPORT}?month=2026-09", headers=auth)
    assert res.status == 200
    body = res.json
    assert (body["month"], body["previous_month"]) == ("2026-09", "2026-08")
    assert (body["currency"], body["entries"]) == ("PLN", 4)
    fun = next(c for c in body["categories"] if c["category"] == "FUN")
    assert (fun["budget"], fun["spent"], fun["previous"]) == (700, 500, 250)
    assert (fun["change"], fun["change_percent"]) == (250, 100.0)
    assert (body["total_spent"], body["previous"], body["change"]) == (2200, 250, 1950)
    assert body["saved"] == {"future": 500, "unspent": 4800}
    assert body["discretionary"]["spent"] == 500
    assert body["discretionary"]["work_hours"] == pytest.approx(500 / (7000 / (8 * 5 * 52 / 12)), abs=0.1)
    assert (body["largest_expense"]["note"], body["largest_expense"]["amount"]) == ("czynsz", 1200)


def test_month_report_defaults_to_current_month_and_validates(client):
    auth = _register(client, "rep2@b.pl")
    assert client.get(REPORT, headers=auth)[1].status == 409  # bez profilu nie ma dochodu ani stawki
    client.put("/api/v1/profile", json=PROFILE, headers=auth)

    _, res = client.get(REPORT, headers=auth)
    assert res.status == 200 and res.json["month"] == period_of(today())
    assert res.json["largest_expense"] is None and res.json["total_spent"] == 0
    assert client.get(f"{REPORT}?month=2026-13", headers=auth)[1].status == 422
    assert client.get(REPORT)[1].status == 401


def test_export_json_and_csv(client):
    auth = _register(client, "rep3@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    _spend(client, auth, "FUN", 14.5, "2026-09-03", "=Kawa")
    client.post("/api/v1/goals", json={"name": "Wakacje", "target_amount": 5000}, headers=auth)
    client.post("/api/v1/wishlist", json={"name": "Monitor", "price": 1500}, headers=auth)
    client.post("/api/v1/calculations", json={"name": "Rower", "purchase_price": 3000}, headers=auth)

    _, res = client.get(EXPORT, headers=auth)
    assert res.status == 200 and "attachment" in res.headers["content-disposition"]
    data = res.json
    assert [e["note"] for e in data["expenses"]] == ["=Kawa"]  # JSON zostaje bez zmian, apostrof dotyczy tylko CSV
    assert [g["name"] for g in data["goals"]] == ["Wakacje"]
    assert [w["name"] for w in data["wishlist"]] == ["Monitor"]
    assert [c["name"] for c in data["calculations"]] == ["Rower"]

    _, res = client.get(f"{EXPORT}?format=csv", headers=auth)
    assert res.status == 200 and res.headers["content-type"].startswith("text/csv")
    assert ".csv" in res.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(res.text.lstrip("\ufeff"))))
    assert [(r["type"], r["name"]) for r in rows] == [
        ("expense", "'=Kawa"),
        ("goal", "Wakacje"),
        ("wish", "Monitor"),
        ("calculation", "Rower"),
    ]


def test_export_is_private_and_validates_format(client):
    auth = _register(client, "rep4@b.pl")
    _spend(client, auth, "FUN", 10, "2026-09-03", "moje")
    other = _register(client, "rep5@b.pl")

    assert client.get(EXPORT, headers=other)[1].json["expenses"] == []
    assert client.get(f"{EXPORT}?format=xml", headers=auth)[1].status == 422
    assert client.get(EXPORT)[1].status == 401


def test_export_date_range(client):
    auth = _register(client, "rep6@b.pl")
    for day in ("2026-08-31", "2026-09-01", "2026-09-30", "2026-10-01"):
        _spend(client, auth, "FUN", 10, day, day)
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    client.post("/api/v1/wishlist", json={"name": "Monitor", "price": 1500}, headers=auth)  # utworzone dziś

    _, res = client.get(f"{EXPORT}?from=2026-09-01&to=2026-09-30", headers=auth)
    assert res.status == 200 and res.json["range"] == {"from": "2026-09-01", "to": "2026-09-30"}
    assert [e["spent_on"] for e in res.json["expenses"]] == ["2026-09-01", "2026-09-30"]  # zakres domknięty
    assert res.json["wishlist"] == []  # życzenie utworzone poza zakresem
    assert "worthmytime-2026-09-01_2026-09-30.json" in res.headers["content-disposition"]

    # sam początek albo sam koniec zakresu
    _, res = client.get(f"{EXPORT}?from=2026-09-30", headers=auth)
    assert [e["spent_on"] for e in res.json["expenses"]] == ["2026-09-30", "2026-10-01"]
    assert [w["name"] for w in res.json["wishlist"]] == ["Monitor"]
    _, res = client.get(f"{EXPORT}?to=2026-08-31&format=csv", headers=auth)
    assert res.text.count("expense") == 1

    # bez zakresu eksport obejmuje całość
    _, res = client.get(EXPORT, headers=auth)
    assert len(res.json["expenses"]) == 4 and res.json["range"] == {"from": None, "to": None}


def test_export_range_validation(client):
    auth = _register(client, "rep7@b.pl")
    assert client.get(f"{EXPORT}?from=wczoraj", headers=auth)[1].status == 422
    assert client.get(f"{EXPORT}?to=2026-02-30", headers=auth)[1].status == 422
    assert client.get(f"{EXPORT}?from=2026-10-02&to=2026-10-01", headers=auth)[1].status == 422
