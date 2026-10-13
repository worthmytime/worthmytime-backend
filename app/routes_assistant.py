"""Asystent AI: czat o budżecie bieżącego miesiąca (POST /assistant/chat) i podgląd danych, które dostaje model."""

from sanic import Blueprint, Request
from sqlalchemy import select

from . import assistant, life
from .errors import ApiError
from .forecast import forecast
from .helpers import (
    NOT_LOAN_PAYMENT,
    client_ip,
    load_loans,
    load_plan,
    login_required,
    ok,
    parse,
    rate_from_user,
    today,
)
from .models import Expense, RecurringExpense, SavingsGoal, User
from .planning import add_months, month_bounds, period_of, remaining_installments
from .schemas import AssistantChatIn

bp = Blueprint("assistant", url_prefix="/api/v1")

TOP_EXPENSES = 10


async def _context(request: Request, user: User) -> list[str]:
    """Dane bieżącego miesiąca dla modelu; te same zdania zwraca GET /assistant/context."""
    db, now = request.ctx.db, today()
    plan = await load_plan(request, user, rate_from_user(user).monthly_income)
    start, end = month_bounds(period_of(now))
    in_month = (Expense.user_id == user.id, Expense.spent_on >= start, Expense.spent_on < end)

    top = await db.scalars(
        select(Expense)
        .where(*in_month, NOT_LOAN_PAYMENT)
        .order_by(Expense.amount.desc(), Expense.id)
        .limit(TOP_EXPENSES)
    )
    paid = set(await db.scalars(select(Expense.source_id).where(*in_month, Expense.source_type == "LOAN")))
    month_start = now.replace(day=1)
    loans = [
        {
            "name": loan.name,
            "amount": loan.installment_amount,
            "due": add_months(month_start, 0, loan.payment_day).isoformat() if loan.payment_day else None,
            "paid": loan.id in paid,
        }
        for loan in await load_loans(request, user)
        # ta sama reguła co w budżecie: rata wymagalna w tym miesiącu liczy się przez cały miesiąc
        if remaining_installments(month_start, loan.installments_left, loan.end_date, loan.payment_day) > 0
    ]
    recurring = await db.scalars(
        select(RecurringExpense)
        .where(RecurringExpense.user_id == user.id, RecurringExpense.active.is_(True))
        .order_by(RecurringExpense.day_of_month)
    )
    goals = await db.scalars(
        select(SavingsGoal).where(SavingsGoal.user_id == user.id, SavingsGoal.completed_at.is_(None)).limit(10)
    )
    return assistant.build_context(
        today=now,
        currency=user.currency,
        plan=plan,
        forecast=forecast(plan, now),
        top_expenses=[
            {"date": e.spent_on.isoformat(), "note": e.note, "category": e.category, "amount": e.amount} for e in top
        ],
        recurring=[{"name": r.name, "amount": r.amount, "day": r.day_of_month} for r in recurring],
        loans=loans,
        goals=[{"name": g.name, "remaining": max(g.target_amount - g.saved_amount, 0)} for g in goals],
        life=life.summary(user.life_context),
    )


@bp.get("/assistant/context")
@login_required
async def assistant_context(request: Request):
    """Podsumowanie miesiąca, które dostaje model: użytkownik widzi dokładnie, co o nim wysyłamy."""
    lines = await _context(request, request.ctx.user)
    return ok({"context": lines, "configured": assistant.configured()})


@bp.post("/assistant/chat")
@login_required
async def assistant_chat(request: Request):
    """Odpowiedź asystenta na rozmowę; kontekst miesiąca dokłada serwer przy każdym żądaniu (jest zawsze aktualny)."""
    data = parse(AssistantChatIn, request)
    if not assistant.configured():
        raise ApiError("Asystent AI nie jest skonfigurowany na serwerze", 503)
    wait = request.app.ctx.limiter.check_ai(client_ip(request))
    if wait:
        raise ApiError("Zbyt wiele wiadomości, spróbuj ponownie za chwilę", 429, headers={"Retry-After": str(wait)})
    context = await _context(request, request.ctx.user)
    reply = await assistant.chat(context, [m.model_dump() for m in data.messages])
    return ok({"reply": reply})
