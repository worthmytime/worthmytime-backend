"""Podsumowanie miesiąca i eksport danych: czysta logika bez I/O (endpointy w `routes_reports.py`)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from .budget import LOW_PRIORITY, BudgetPlan
from .money import rnd
from .schemas import CATEGORIES, Category


def _change(current: float, previous: float) -> dict:
    """Porównanie z poprzednim miesiącem; procent tylko wtedy, gdy jest do czego porównać."""
    diff = rnd(current - previous, 2)
    return {
        "previous": rnd(previous, 2),
        "change": diff,
        "change_percent": rnd(diff / previous * 100, 1) if previous > 0 else None,
    }


def month_report(
    plan: BudgetPlan,
    previous_spent: dict[str, float],
    largest: dict | None,
    entries: int,
    hourly_rate: float | None,
) -> dict:
    """Liczby miesiąca: `plan.spent` to wydatki z rejestru w tym miesiącu, `previous_spent` w poprzednim.

    Raty kredytów (`plan.monthly_loans`) doliczamy do Potrzeb w obu miesiącach, tak jak w budżecie.
    """
    categories = []
    for c in CATEGORIES:
        fixed = plan.monthly_loans if c == Category.NEEDS else 0.0
        budget, spent = plan.category_budget(c), plan.effective_spent(c)
        categories.append(
            {
                "category": c.value,
                "budget": budget,
                "spent": spent,
                "available": rnd(budget - spent, 2),
                "usage_percent": rnd(spent / budget * 100, 1) if budget > 0 else None,
                **_change(spent, previous_spent.get(c.value, 0.0) + fixed),
            }
        )
    total = plan.total_spent
    previous_total = sum(previous_spent.get(c.value, 0.0) for c in CATEGORIES) + plan.monthly_loans
    # wydatki uznaniowe: kategorie o najniższym priorytecie (Cele i Przyjemności)
    discretionary = rnd(sum(plan.spent[c] for c in LOW_PRIORITY), 2)
    return {
        "monthly_income": rnd(plan.monthly_income, 2),
        "categories": categories,
        "total_spent": total,
        **_change(total, previous_total),
        "saved": {
            # odłożone = wpisy w kategorii Przyszłość; niewydane = dochód minus wszystkie wydatki (nie mniej niż 0)
            "future": plan.spent[Category.FUTURE],
            "unspent": rnd(max(0.0, plan.monthly_income - total), 2),
        },
        "discretionary": {
            "spent": discretionary,
            "work_hours": rnd(discretionary / hourly_rate, 1) if hourly_rate else None,
        },
        "largest_expense": largest,
        "entries": entries,
    }


EXPORT_COLUMNS = ["type", "id", "date", "name", "category", "amount", "status", "target_amount"]


def _safe_cell(value) -> str:
    """Tekst zaczynający się od znaku formuły dostaje apostrof, żeby arkusz nie wykonał go jako formuły."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def export_rows(data: dict) -> Iterable[dict]:
    """Spłaszcza eksport JSON do jednej tabeli: typ wiersza w kolumnie `type`."""
    for e in data["expenses"]:
        yield {**e, "type": "expense", "date": e["spent_on"], "name": e["note"], "status": e["source_type"]}
    for g in data["goals"]:
        yield {
            **g,
            "type": "goal",
            "date": g["created_at"][:10],
            "amount": g["saved_amount"],
            "status": "completed" if g["completed_at"] else "active",
        }
    for w in data["wishlist"]:
        yield {**w, "type": "wish", "date": w["created_at"][:10], "amount": w["price"]}
    for c in data["calculations"]:
        yield {
            **c,
            "status": c["type"],  # rodzaj obliczenia (SIMPLE, RECURRING, TCO), zanim "type" stanie się typem wiersza
            "type": "calculation",
            "date": c["created_at"][:10],
            "amount": c["purchase_price"],
        }


def export_csv(data: dict) -> str:
    """CSV w UTF-8 z BOM (Excel poprawnie odczytuje polskie znaki)."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in export_rows(data):
        writer.writerow({k: _safe_cell(row.get(k)) for k in EXPORT_COLUMNS})
    return "﻿" + out.getvalue()
