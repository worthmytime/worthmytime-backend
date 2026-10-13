"""Asystent AI: kontekst miesiąca dla modelu językowego i wywołanie OpenAI przez oficjalną bibliotekę `openai`.

Klucz i nazwa modelu są w konfiguracji backendu (`ASSISTANT_API_KEY` albo `OPENAI_API_KEY`, `ASSISTANT_MODEL`);
frontend rozmawia wyłącznie z naszym API. Budowanie kontekstu to czyste funkcje (łatwe do testów);
wywołanie modelu jest w `_ask`, a zamiana błędów na odpowiedzi API w `chat`.
"""

from __future__ import annotations

import logging
from datetime import date

import openai

from .budget import BudgetPlan
from .config import settings
from .errors import ApiError
from .money import rnd
from .schemas import CATEGORIES

log = logging.getLogger("worthmytime")

CATEGORY_LABELS = {"NEEDS": "Potrzeby", "FUTURE": "Przyszłość", "GOALS": "Cele", "FUN": "Przyjemności"}

SYSTEM_PROMPT = """Jesteś asystentem budżetu domowego w aplikacji WorthMyTime. Rozmawiasz po polsku.

Twoje zadanie: pomóc użytkownikowi tak pokierować wydatkami w BIEŻĄCYM miesiącu, żeby pieniądze nie skończyły się \
przed końcem miesiąca i żeby nie powstał dług.

Zasady:
- Opieraj się wyłącznie na danych z sekcji "Dane użytkownika" poniżej. Nie wymyślaj kwot ani wydatków, \
których tam nie ma. Jeśli czegoś brakuje, powiedz, czego, i poproś o uzupełnienie w aplikacji.
- Dawaj konkretne kroki na ten miesiąc, z kwotami w walucie użytkownika: ile można jeszcze wydać dziennie, z której \
kategorii przesunąć, co odłożyć na później, którą ratę opłacić najpierw.
- Zacznij od najważniejszego wniosku w jednym lub dwóch zdaniach, potem wypisz do pięciu kroków.
- Budżet ma cztery kategorie: Potrzeby (konieczne, w tym raty), Przyszłość (oszczędności), Cele, Przyjemności. \
Raty kredytów to wydatek konieczny i są już wliczone w Potrzeby.
- Nie doradzaj w sprawie konkretnych produktów finansowych, inwestycji ani podatków i nie obiecuj zysków. \
Przy poważnych kłopotach z długami zasugeruj kontakt z doradcą lub bezpłatną poradnią.
- Pisz zwykłym tekstem, krótko, bez tabel i bez znaczników formatowania.
- To pomoc w planowaniu, nie porada finansowa."""


def _money(value: float, currency: str) -> str:
    return f"{rnd(value, 2):.2f} {currency}"


def build_context(
    *,
    today: date,
    currency: str,
    plan: BudgetPlan,
    forecast: dict,
    top_expenses: list[dict],
    recurring: list[dict],
    loans: list[dict],
    goals: list[dict],
    life: list[str],
) -> list[str]:
    """Podsumowanie bieżącego miesiąca jako lista zdań: to, i tylko to, dostaje model o użytkowniku."""
    left_total = rnd(plan.monthly_income - plan.total_spent, 2)
    lines = [
        f"Dziś jest {today.isoformat()}; do końca miesiąca zostało {forecast['days_left']} dni (z dzisiejszym).",
        f"Miesięczny dochód netto: {_money(plan.monthly_income, currency)}.",
        f"Wydane w tym miesiącu łącznie (z ratami): {_money(plan.total_spent, currency)}; "
        f"zostało z dochodu: {_money(left_total, currency)}.",
    ]
    rows = {row["category"]: row for row in forecast["categories"]}
    for c in CATEGORIES:
        row = rows[c.value]
        text = (
            f"{CATEGORY_LABELS[c.value]}: budżet {_money(row['budget'], currency)}, "
            f"wydane {_money(row['spent'], currency)}, zostało {_money(row['available'], currency)}, "
            f"dzienny limit do końca miesiąca {_money(row['daily_limit'], currency)}"
        )
        if row.get("runs_out_on"):
            text += f"; przy obecnym tempie budżet tej kategorii skończy się {row['runs_out_on']}"
        elif row.get("status") == "OVER":
            text += "; budżet tej kategorii jest już przekroczony"
        lines.append(text + ".")

    if loans:
        items = "; ".join(
            f"{x['name']} {_money(x['amount'], currency)}"
            + (f", termin {x['due']}" if x.get("due") else "")
            + (" (opłacona w tym miesiącu)" if x.get("paid") else " (nieopłacona w tym miesiącu)")
            for x in loans
        )
        lines.append(f"Raty kredytów i pożyczek w tym miesiącu (wliczone w Potrzeby): {items}.")
    else:
        lines.append("Brak rat kredytów i pożyczek w tym miesiącu.")

    if recurring:
        items = "; ".join(f"{x['name']} {_money(x['amount'], currency)} ({x['day']}. dnia miesiąca)" for x in recurring)
        lines.append(f"Stałe wydatki co miesiąc: {items}.")
    if top_expenses:
        items = "; ".join(
            f"{x['date']} {x['note'] or CATEGORY_LABELS.get(x['category'], x['category'])} "
            f"{_money(x['amount'], currency)} ({CATEGORY_LABELS.get(x['category'], x['category'])})"
            for x in top_expenses
        )
        lines.append(f"Największe wydatki w tym miesiącu: {items}.")
    else:
        lines.append("W rejestrze nie ma jeszcze wydatków z tego miesiąca.")
    if goals:
        items = "; ".join(f"{x['name']}: brakuje {_money(x['remaining'], currency)}" for x in goals)
        lines.append(f"Cele oszczędnościowe w toku: {items}.")
    if life:
        lines.append("Sytuacja życiowa użytkownika: " + " ".join(life))
    return lines


def instructions(context: list[str]) -> str:
    """Instrukcja dla modelu razem z danymi użytkownika z bieżącego miesiąca."""
    return SYSTEM_PROMPT + "\n\nDane użytkownika:\n" + "\n".join(f"- {line}" for line in context)


def configured() -> bool:
    return bool(settings.assistant_api_key and settings.assistant_model)


async def _ask(system: str, history: list[dict]) -> str:
    """Jedno wywołanie Responses API: instrukcja z danymi użytkownika i dotychczasowa rozmowa."""
    async with openai.AsyncOpenAI(
        api_key=settings.assistant_api_key,
        timeout=settings.assistant_timeout_seconds,
        max_retries=1,
    ) as client:
        response = await client.responses.create(
            model=settings.assistant_model,
            instructions=system,
            input=[{"role": m["role"], "content": m["content"]} for m in history],
            store=False,  # dane finansowe użytkownika nie mają zostawać w historii odpowiedzi u dostawcy
        )
    return response.output_text


async def chat(context: list[str], history: list[dict]) -> str:
    """Odpowiedź modelu na rozmowę; 503 bez konfiguracji na serwerze, 502 gdy model nie odpowie."""
    if not configured():
        raise ApiError("Asystent AI nie jest skonfigurowany na serwerze", 503)
    try:
        reply = await _ask(instructions(context), history)
    except openai.OpenAIError as e:
        # w logu rodzaj błędu i kod odpowiedzi: treść rozmowy to dane użytkownika, a żądanie zawiera klucz
        log.warning("Asystent AI nie odpowiedział: %s (status %s)", type(e).__name__, getattr(e, "status_code", "-"))
        raise ApiError("Asystent nie odpowiedział, spróbuj ponownie za chwilę", 502) from None
    if not isinstance(reply, str) or not reply.strip():
        raise ApiError("Asystent zwrócił pustą odpowiedź, spróbuj ponownie", 502)
    return reply.strip()
