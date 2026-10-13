# ruff: noqa: F811
from datetime import date

import openai

from app import assistant
from app.budget import BudgetPlan
from app.config import Settings, settings
from app.forecast import forecast
from app.helpers import today
from app.schemas import Category
from tests.test_api import PROFILE, _register, client  # noqa: F401

CHAT = "/api/v1/assistant/chat"
CONTEXT = "/api/v1/assistant/context"
QUESTION = {"messages": [{"role": "user", "content": "Co zrobić, żeby starczyło do końca miesiąca?"}]}


def _context(**over):
    spent = {Category.NEEDS: 1200.0, Category.FUTURE: 0.0, Category.GOALS: 0.0, Category.FUN: 650.0}
    plan = BudgetPlan(monthly_income=7000, spent=spent, monthly_loans=800, loans_count=1)
    now = date(2026, 10, 20)
    args = {
        "today": now,
        "currency": "PLN",
        "plan": plan,
        "forecast": forecast(plan, now),
        "top_expenses": [{"date": "2026-10-02", "note": "czynsz", "category": "NEEDS", "amount": 1200}],
        "recurring": [{"name": "Internet", "amount": 60, "day": 15}],
        "loans": [{"name": "Kredyt auto", "amount": 800, "due": "2026-10-12", "paid": False}],
        "goals": [{"name": "Wakacje", "remaining": 3500}],
        "life": ["Mieszka z rodzicami: nie płaci czynszu najmu ani raty za mieszkanie."],
    }
    return assistant.build_context(**{**args, **over})


def test_context_describes_the_month_in_plain_sentences():
    text = "\n".join(_context())
    assert "Dziś jest 2026-10-20; do końca miesiąca zostało 12 dni" in text
    assert "Miesięczny dochód netto: 7000.00 PLN." in text
    assert "Wydane w tym miesiącu łącznie (z ratami): 2650.00 PLN; zostało z dochodu: 4350.00 PLN." in text
    # Potrzeby zawierają ratę: 1200 z rejestru + 800 raty z budżetu 3500
    assert "Potrzeby: budżet 3500.00 PLN, wydane 2000.00 PLN, zostało 1500.00 PLN" in text
    assert "Przyjemności: budżet 700.00 PLN, wydane 650.00 PLN, zostało 50.00 PLN" in text
    assert "Kredyt auto 800.00 PLN, termin 2026-10-12 (nieopłacona w tym miesiącu)" in text
    assert "Stałe wydatki co miesiąc: Internet 60.00 PLN (15. dnia miesiąca)." in text
    assert "Największe wydatki w tym miesiącu: 2026-10-02 czynsz 1200.00 PLN (Potrzeby)." in text
    assert "Cele oszczędnościowe w toku: Wakacje: brakuje 3500.00 PLN." in text
    assert "Sytuacja życiowa użytkownika: Mieszka z rodzicami" in text


def test_context_says_when_there_is_nothing():
    text = "\n".join(_context(top_expenses=[], recurring=[], loans=[], goals=[], life=[]))
    assert "W rejestrze nie ma jeszcze wydatków z tego miesiąca." in text
    assert "Brak rat kredytów i pożyczek w tym miesiącu." in text
    assert "Stałe wydatki" not in text and "Cele oszczędnościowe" not in text and "Sytuacja życiowa" not in text


def test_instructions_carry_user_data_and_rules():
    text = assistant.instructions(["Dochód: 7000.00 PLN."])
    assert "Dane użytkownika:\n- Dochód: 7000.00 PLN." in text
    assert "nie porada finansowa" in text and "wyłącznie na danych" in text


def _configure(monkeypatch, reply="Wydawaj najwyżej 4 zł dziennie na przyjemności."):
    """Asystent skonfigurowany, a wywołanie modelu podmienione: zapamiętuje żądanie i zwraca gotową odpowiedź."""
    sent = []
    monkeypatch.setattr(settings, "assistant_api_key", "sekret")
    monkeypatch.setattr(settings, "assistant_model", "gpt-test")

    async def ask(system, history):
        sent.append({"instructions": system, "input": history})
        return f"  {reply}  "

    monkeypatch.setattr(assistant, "_ask", ask)
    return sent


def test_chat_sends_month_data_and_conversation_to_the_model(client, monkeypatch):
    sent = _configure(monkeypatch)
    auth = _register(client, "asst1@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    day = today().isoformat()
    expense = {"category": "FUN", "amount": 650, "note": "koncert", "spent_on": day}
    client.post("/api/v1/expenses", json=expense, headers=auth)
    client.put("/api/v1/profile/context", json={"housing": "WITH_PARENTS"}, headers=auth)

    _, res = client.post(CHAT, json=QUESTION, headers=auth)
    assert res.status == 200 and res.json == {"reply": "Wydawaj najwyżej 4 zł dziennie na przyjemności."}

    (call,) = sent
    assert call["input"] == QUESTION["messages"]  # rozmowa idzie bez zmian, dane miesiąca są w instrukcji
    system = call["instructions"]
    assert "Przyjemności: budżet 700.00 PLN, wydane 650.00 PLN, zostało 50.00 PLN" in system
    assert "koncert 650.00 PLN (Przyjemności)" in system
    assert "Mieszka z rodzicami" in system
    assert "asst1@b.pl" not in system  # adres e-mail nie trafia do modelu


def test_context_endpoint_shows_what_the_model_gets(client, monkeypatch):
    auth = _register(client, "asst2@b.pl")
    assert client.get(CONTEXT, headers=auth)[1].status == 409  # bez profilu nie ma dochodu
    client.put("/api/v1/profile", json=PROFILE, headers=auth)

    _, res = client.get(CONTEXT, headers=auth)
    assert res.status == 200 and res.json["configured"] is False
    assert any(line.startswith("Miesięczny dochód netto: 7000.00 PLN") for line in res.json["context"])
    _configure(monkeypatch)
    assert client.get(CONTEXT, headers=auth)[1].json["configured"] is True
    assert client.get(CONTEXT)[1].status == 401


def test_chat_requires_login_configuration_and_valid_conversation(client, monkeypatch):
    monkeypatch.setattr(settings, "assistant_api_key", "")
    auth = _register(client, "asst3@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    assert client.post(CHAT, json=QUESTION)[1].status == 401
    assert client.post(CHAT, json=QUESTION, headers=auth)[1].status == 503  # brak klucza i modelu na serwerze

    sent = _configure(monkeypatch)
    user = {"role": "user", "content": "x"}
    assert client.post(CHAT, json={"messages": []}, headers=auth)[1].status == 422
    assert client.post(CHAT, json={"messages": [user] * 31}, headers=auth)[1].status == 422
    too_long = {"messages": [{"role": "user", "content": "x" * 2001}]}
    assert client.post(CHAT, json=too_long, headers=auth)[1].status == 422
    assert client.post(CHAT, json={"messages": [{"role": "system", "content": "x"}]}, headers=auth)[1].status == 422
    ends_with_reply = {"messages": [user, {"role": "assistant", "content": "y"}]}
    assert client.post(CHAT, json=ends_with_reply, headers=auth)[1].status == 422
    assert sent == []  # błędne żądania nie docierają do modelu


def test_model_failures_become_502_without_leaking_the_key(client, monkeypatch):
    _configure(monkeypatch)
    auth = _register(client, "asst4@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)

    async def broken(system, history):
        raise openai.OpenAIError("brak sieci, klucz sekret")

    monkeypatch.setattr(assistant, "_ask", broken)
    _, res = client.post(CHAT, json=QUESTION, headers=auth)
    assert res.status == 502 and "sekret" not in res.text  # komunikat biblioteki nie trafia do odpowiedzi

    async def empty(system, history):
        return "   "

    monkeypatch.setattr(assistant, "_ask", empty)
    assert client.post(CHAT, json=QUESTION, headers=auth)[1].status == 502


def test_api_key_can_use_the_standard_openai_name(monkeypatch):
    monkeypatch.delenv("ASSISTANT_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-standard")
    assert Settings(_env_file=None).assistant_api_key == "sk-standard"
    monkeypatch.setenv("ASSISTANT_API_KEY", "sk-wlasny")
    assert Settings(_env_file=None).assistant_api_key == "sk-wlasny"  # własna nazwa ma pierwszeństwo
