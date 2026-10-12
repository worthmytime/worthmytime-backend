"""Podsumowanie miesiąca (GET /reports/month) i eksport danych użytkownika (GET /export)."""

from datetime import UTC, date, datetime, time, timedelta

from sanic import Blueprint, Request
from sanic.response import text
from sqlalchemy import select

from .errors import ApiError
from .helpers import (
    NOT_LOAN_PAYMENT,
    load_loans,
    load_rollover,
    login_required,
    materialize_recurring,
    ok,
    plan_from_row,
    rate_from_user,
    today,
)
from .models import Budget, Calculation, Expense, SavingsGoal, WishlistItem
from .planning import add_months, month_bounds, parse_period, period_of, totals_by_category
from .reports import export_csv, month_report

bp = Blueprint("reports", url_prefix="/api/v1")


def _month_expenses(user_id: str, period: str):
    start, end = month_bounds(period)
    return (
        select(Expense)
        .where(Expense.user_id == user_id, Expense.spent_on >= start, Expense.spent_on < end, NOT_LOAN_PAYMENT)
        .order_by(Expense.amount.desc(), Expense.spent_on.desc(), Expense.id)
    )


@bp.get("/reports/month")
@login_required
async def month_summary(request: Request):
    """Podsumowanie miesiąca: wydatki kontra budżet, odłożone, godziny pracy i porównanie z poprzednim miesiącem."""
    user, db = request.ctx.user, request.ctx.db
    current = period_of(today())
    period = request.args.get("month") or current
    try:
        parse_period(period)
    except ValueError:
        raise ApiError("Parametr month ma format YYYY-MM", 422)
    rate = rate_from_user(user)
    await materialize_recurring(request, user)

    previous = period_of(add_months(month_bounds(period)[0], -1))
    rows = list(await db.scalars(_month_expenses(user.id, period)))
    previous_rows = list(await db.scalars(_month_expenses(user.id, previous)))

    row = await db.get(Budget, user.id)
    loans = await load_loans(request, user)
    # środki przeniesione znamy tylko dla bieżącego miesiąca; minione liczymy z samego podziału dochodu
    rollover = await load_rollover(request, user, row, rate.monthly_income, loans) if period == current else None
    plan = plan_from_row(
        row, rate.monthly_income, loans, totals_by_category((e.category, e.amount) for e in rows), period, rollover
    )
    largest = None
    if rows:  # zapytanie sortuje malejąco po kwocie
        top = rows[0]
        largest = {
            "id": top.id,
            "category": top.category,
            "amount": top.amount,
            "note": top.note,
            "spent_on": top.spent_on.isoformat(),
        }
    report = month_report(
        plan,
        totals_by_category((e.category, e.amount) for e in previous_rows),
        largest,
        len(rows),
        rate.hourly_rate,
    )
    return ok({"month": period, "previous_month": previous, "currency": user.currency, **report})


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _date_arg(request: Request, name: str) -> date | None:
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError(f"Parametr {name} ma format YYYY-MM-DD", 422)


def _created_between(model, start: date | None, end: date | None) -> list:
    """Warunki na datę utworzenia (zakres domknięty, dni liczone w UTC)."""
    conditions = []
    if start:
        conditions.append(model.created_at >= datetime.combine(start, time.min, tzinfo=UTC))
    if end:
        conditions.append(model.created_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC))
    return conditions


async def _export_data(request: Request, start: date | None = None, end: date | None = None) -> dict:
    """Dane do eksportu; zakres dat dotyczy daty wydatku, a dla celów, życzeń i obliczeń daty utworzenia."""
    user, db = request.ctx.user, request.ctx.db
    await materialize_recurring(request, user)
    spent = ([Expense.spent_on >= start] if start else []) + ([Expense.spent_on <= end] if end else [])
    expenses = await db.scalars(
        select(Expense)
        .where(Expense.user_id == user.id, *spent)
        .order_by(Expense.spent_on, Expense.created_at, Expense.id)
    )
    goals = await db.scalars(
        select(SavingsGoal)
        .where(SavingsGoal.user_id == user.id, *_created_between(SavingsGoal, start, end))
        .order_by(SavingsGoal.created_at)
    )
    wishes = await db.scalars(
        select(WishlistItem)
        .where(WishlistItem.user_id == user.id, *_created_between(WishlistItem, start, end))
        .order_by(WishlistItem.created_at)
    )
    calculations = await db.scalars(
        select(Calculation)
        .where(Calculation.user_id == user.id, *_created_between(Calculation, start, end))
        .order_by(Calculation.created_at)
    )
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "range": {"from": _iso(start), "to": _iso(end)},
        "currency": user.currency,
        "expenses": [
            {
                "id": e.id,
                "spent_on": e.spent_on.isoformat(),
                "category": e.category,
                "amount": e.amount,
                "note": e.note,
                "source_type": e.source_type,
            }
            for e in expenses
        ],
        "goals": [
            {
                "id": g.id,
                "name": g.name,
                "category": g.category,
                "target_amount": g.target_amount,
                "saved_amount": g.saved_amount,
                "monthly_contribution": g.monthly_contribution,
                "target_date": _iso(g.target_date),
                "created_at": g.created_at.isoformat(),
                "completed_at": _iso(g.completed_at),
            }
            for g in goals
        ],
        "wishlist": [
            {
                "id": w.id,
                "name": w.name,
                "category": w.category,
                "price": w.price,
                "cooldown_days": w.cooldown_days,
                "status": w.status,
                "created_at": w.created_at.isoformat(),
                "decided_at": _iso(w.decided_at),
            }
            for w in wishes
        ],
        "calculations": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "category": c.category,
                "purchase_price": c.purchase_price,
                "ownership_years": c.ownership_years,
                "resale_value": c.resale_value,
                "costs": [{"name": x.name, "amount": x.amount, "frequency": x.frequency} for x in c.costs],
                "created_at": c.created_at.isoformat(),
            }
            for c in calculations
        ],
    }


@bp.get("/export")
@login_required
async def export_data(request: Request):
    """Eksport danych użytkownika: wydatki, cele, lista życzeń i zapisane obliczenia (JSON albo CSV)."""
    fmt = (request.args.get("format") or "json").lower()
    if fmt not in ("json", "csv"):
        raise ApiError("Parametr format ma wartość json albo csv", 422)
    start, end = _date_arg(request, "from"), _date_arg(request, "to")
    if start and end and start > end:
        raise ApiError("Parametr from nie może być późniejszy niż to", 422)
    data = await _export_data(request, start, end)
    # nazwa pliku mówi, czego dotyczy: zakres dat albo (dla całości) dzień eksportu
    label = f"{_iso(start) or 'start'}_{_iso(end) or today().isoformat()}" if start or end else today().isoformat()
    name = f"worthmytime-{label}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if fmt == "csv":
        return text(export_csv(data), content_type="text/csv; charset=utf-8", headers=headers)
    return ok(data, headers=headers)
