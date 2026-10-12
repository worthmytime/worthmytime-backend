"""Jev (TypeSafe AI): podpowiedzi kategorii i rozpoznawanie kolumn importu.

Klucz API zna tylko backend (`TYPESAFE_API_KEY`), frontend rozmawia wyłącznie z naszym API. Jev odpowiada na pytania
wyboru (`choice`) o przekazany stan; budowanie pytań i odczyt odpowiedzi to czyste funkcje, łatwe do testów.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

from .config import settings
from .errors import ApiError
from .schemas import CATEGORIES

log = logging.getLogger("worthmytime")

CATEGORY_CRITERIA = {
    "NEEDS": "Potrzeby: czynsz, wynajem, jedzenie, supermarket, biedronka, lidl, media, paliwo, konieczny transport, "
    "leczenie, apteka, ubezpieczenie, zobowiązania kredytowe, rachunki.",
    "FUTURE": "Przyszłość: oszczędności, lokata, inwestycje, emerytura, poduszka finansowa, rezerwa awaryjna.",
    "GOALS": "Cele: wakacje, podróże, samochód, elektronika, meble, remont, większy jednorazowy zakup, "
    "na który się odkłada.",
    "FUN": "Przyjemności: restauracje, kawiarnia, fast food, rozrywka, kino, teatr, siłownia, gry, streaming, netflix, "
    "spotify, hobby, spontaniczne zakupy, subskrypcje.",
}

MAPPING_FIELDS = {
    "date": "Która kolumna zawiera datę transakcji (datę operacji albo księgowania)?",
    "amount": "Która kolumna zawiera kwotę transakcji, czyli ile wydano? "
    "Nie chodzi o saldo po operacji ani o numer rachunku. "
    "Jeśli obciążenia i wpływy są w osobnych kolumnach, wybierz kolumnę obciążeń (wydatków).",
    "description": "Która kolumna najlepiej mówi, na co był wydatek: nazwa sprzedawcy, odbiorca albo tytuł/opis "
    "transakcji? Nie chodzi o typ operacji (np. przelew, płatność kartą) ani o numer rachunku.",
    "currency": "Która kolumna zawiera kod waluty transakcji (np. PLN, EUR)? "
    "Jeśli waluta jest tylko doklejona do kwoty, wybierz none.",
}


def choice(instructions: str, criteria: dict[str, str]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def categorize_request(descriptions: list[str]) -> tuple[dict, dict]:
    """Stan i pytania: jedno pytanie na wydatek (q0, q1, ...), każde wprost wskazuje, którego wydatku dotyczy."""
    state = {"wydatki": [{"nr": i + 1, "opis": d} for i, d in enumerate(descriptions)]}
    questions = {
        f"q{i}": choice(f'Do której kategorii budżetu należy wydatek nr {i + 1}: "{d}"?', CATEGORY_CRITERIA)
        for i, d in enumerate(descriptions)
    }
    return state, questions


def categories_from(answers: dict, keys: list[str]) -> dict[str, str]:
    """Kategoria dla każdego klucza; odpowiedź spoza listy kategorii jest pomijana."""
    allowed = {c.value for c in CATEGORIES}
    out = {}
    for i, key in enumerate(keys):
        picked = (answers.get(f"q{i}") or {}).get("choice")
        if picked in allowed:
            out[key] = picked
    return out


def mapping_request(columns: list[dict]) -> tuple[dict, dict]:
    """Każda kolumna pliku to jedna odpowiedź do wyboru (c0, c1, ...), opisana nagłówkiem i przykładami."""
    criteria = {"none": "żadna kolumna nie pasuje"}
    for c in columns:
        samples = " | ".join(c["samples"]) or "(puste)"
        criteria[f"c{c['index']}"] = f"Nagłówek: {c['header']}. Przykłady: {samples}"
    state = {
        "dokument": "Nagłówki i przykładowe wiersze pliku z historią transakcji bankowych",
        "kolumny": [{"kolumna": f"c{c['index']}", "naglowek": c["header"], "przyklady": c["samples"]} for c in columns],
    }
    return state, {field: choice(question, criteria) for field, question in MAPPING_FIELDS.items()}


def mapping_from(answers: dict, columns: list[dict]) -> dict[str, int | None]:
    """Numer kolumny dla każdego pola albo None (brak kolumny lub odpowiedź, której nie było do wyboru)."""
    known = {f"c{c['index']}": c["index"] for c in columns}
    return {field: known.get((answers.get(field) or {}).get("choice")) for field in MAPPING_FIELDS}


def _post(payload: dict) -> dict:
    request = urllib.request.Request(
        f"{settings.typesafe_base_url.rstrip('/')}/v1/systemone",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.typesafe_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "worthmytime-backend",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.typesafe_timeout_seconds) as response:
        return json.loads(response.read())


async def system_one(state: dict, questions: dict) -> dict:
    """Odpowiedzi Jev na pytania o stan; 503 bez klucza na serwerze, 502 gdy Jev nie odpowie."""
    if not settings.typesafe_api_key:
        raise ApiError("Podpowiedzi Jev nie są skonfigurowane na serwerze", 503)
    payload = {"state": state, "questions": questions, "model": settings.typesafe_model}
    try:
        data = await asyncio.to_thread(_post, payload)  # urllib blokuje, więc poza pętlą zdarzeń
    except (OSError, ValueError) as e:  # błąd sieci, limit czasu, odpowiedź HTTP z błędem albo niepoprawny JSON
        # w logu sam rodzaj błędu: treść zapytania to dane użytkownika, a nagłówek zawiera klucz
        log.warning("Jev nie odpowiedział: %s", type(e).__name__)
        raise ApiError("Jev nie odpowiedział, spróbuj ponownie za chwilę", 502) from None
    answers = data.get("answers") if isinstance(data, dict) else None
    return answers if isinstance(answers, dict) else {}
