# ruff: noqa: F811
import urllib.error

import pytest

from app import jev
from app.config import Settings, settings
from app.ratelimit import Limits, RateLimiter
from tests.test_api import client  # noqa: F401

CATEGORIZE = "/api/v1/ai/categorize"
MAP = "/api/v1/ai/map-columns"

COLUMNS = [
    {"index": 0, "header": "Data operacji", "samples": ["05.10.2026", "06.10.2026"]},
    {"index": 1, "header": "Opis operacji", "samples": ["LIDL 123", "ORLEN 4411"]},
    {"index": 3, "header": "Kwota", "samples": ["-45,20", "-210,00"]},
]


def _picked(**choices):
    """Odpowiedzi Jev w kształcie API: nazwa pytania -> wybrana etykieta."""
    return {name: {"choice": label} for name, label in choices.items()}


def test_categorize_request_asks_one_question_per_expense():
    state, questions = jev.categorize_request(["LIDL 123", "NETFLIX.COM"])
    assert state == {"wydatki": [{"nr": 1, "opis": "LIDL 123"}, {"nr": 2, "opis": "NETFLIX.COM"}]}
    assert list(questions) == ["q0", "q1"]
    assert questions["q1"]["type"] == "choice" and "NETFLIX.COM" in questions["q1"]["instructions"]
    assert set(questions["q0"]["criteria"]) == {"NEEDS", "FUTURE", "GOALS", "FUN"}


def test_categories_from_skips_missing_and_unknown_answers():
    answers = {"q0": {"choice": "NEEDS"}, "q1": {"choice": "INNE"}, "q3": {"choice": "FUN"}}
    assert jev.categories_from(answers, ["a", "b", "c", "d"]) == {"a": "NEEDS", "d": "FUN"}


def test_mapping_request_offers_every_column_and_none():
    state, questions = jev.mapping_request(COLUMNS)
    assert list(questions) == ["date", "amount", "description", "currency"]
    criteria = questions["amount"]["criteria"]
    assert list(criteria) == ["none", "c0", "c1", "c3"]
    assert criteria["c3"] == "Nagłówek: Kwota. Przykłady: -45,20 | -210,00"
    samples = ["LIDL 123", "ORLEN 4411"]
    assert state["kolumny"][1] == {"kolumna": "c1", "naglowek": "Opis operacji", "przyklady": samples}


def test_mapping_from_returns_indexes_and_none_for_unknown_labels():
    answers = _picked(date="c0", amount="c3", description="c9", currency="none")
    assert jev.mapping_from(answers, COLUMNS) == {"date": 0, "amount": 3, "description": None, "currency": None}


@pytest.fixture
def fake_jev(monkeypatch):
    """Podmienia wywołanie Jev: zapamiętuje pytania i zwraca przygotowane odpowiedzi."""
    calls = []

    def install(answers):
        async def system_one(state, questions):
            calls.append((state, questions))
            return answers

        monkeypatch.setattr(jev, "system_one", system_one)
        return calls

    return install


def test_categorize_endpoint_works_without_login(client, fake_jev):
    calls = fake_jev({"q0": {"choice": "NEEDS"}, "q1": {"choice": "FUN"}})
    items = [{"key": "LIDL", "description": "LIDL 123"}, {"key": "NETFLIX.COM", "description": "NETFLIX.COM"}]

    _, res = client.post(CATEGORIZE, json={"items": items})
    assert res.status == 200 and res.json == {"suggestions": {"LIDL": "NEEDS", "NETFLIX.COM": "FUN"}}
    assert [w["opis"] for w in calls[0][0]["wydatki"]] == ["LIDL 123", "NETFLIX.COM"]  # do Jev idą opisy, nie klucze


def test_map_columns_endpoint(client, fake_jev):
    fake_jev(_picked(date="c0", amount="c3", description="c1", currency="none"))
    _, res = client.post(MAP, json={"columns": COLUMNS})
    assert res.status == 200
    assert res.json == {"mapping": {"date": 0, "amount": 3, "description": 1, "currency": None}}


def test_input_is_validated(client, fake_jev):
    calls = fake_jev({})
    item = {"key": "k", "description": "opis"}
    assert client.post(CATEGORIZE, json={"items": []})[1].status == 422
    assert client.post(CATEGORIZE, json={"items": [item] * 61})[1].status == 422
    assert client.post(CATEGORIZE, json={"items": [{"key": "k", "description": "x" * 201}]})[1].status == 422
    assert client.post(MAP, json={"columns": []})[1].status == 422
    assert client.post(MAP, json={"columns": [COLUMNS[0], COLUMNS[0]]})[1].status == 422  # ten sam numer kolumny
    assert client.post(MAP, json={"columns": [{**COLUMNS[0], "samples": ["x" * 61]}]})[1].status == 422
    assert calls == []  # błędne żądania nie docierają do Jev


def test_without_key_endpoints_answer_503(client, monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    _, res = client.post(CATEGORIZE, json={"items": [{"key": "k", "description": "opis"}]})
    assert res.status == 503 and "Jev" in res.json["error"]
    assert client.post(MAP, json={"columns": COLUMNS})[1].status == 503


def test_jev_call_sends_key_and_model_and_maps_failures(client, monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "sekret")
    sent = []

    def post(payload):
        sent.append(payload)
        return {"answers": {"q0": {"choice": "GOALS"}}, "model": "jev-latest"}

    monkeypatch.setattr(jev, "_post", post)
    _, res = client.post(CATEGORIZE, json={"items": [{"key": "k", "description": "wakacje"}]})
    assert res.json == {"suggestions": {"k": "GOALS"}}
    assert sent[0]["model"] == settings.typesafe_model and set(sent[0]) == {"state", "questions", "model"}

    def broken(payload):
        raise urllib.error.URLError("brak sieci")

    monkeypatch.setattr(jev, "_post", broken)
    _, res = client.post(CATEGORIZE, json={"items": [{"key": "k", "description": "wakacje"}]})
    assert res.status == 502 and "sekret" not in res.text


def test_ai_requests_have_their_own_rate_limit():
    limiter = RateLimiter(Limits(ai_per_minute=2))
    assert [limiter.check_ai("1.1.1.1") for _ in range(2)] == [0, 0]
    assert limiter.check_ai("1.1.1.1") > 0
    assert limiter.check_ai("2.2.2.2") == 0 and limiter.check_api("1.1.1.1") == 0  # inne IP i zwykłe żądania bez zmian


def test_base_url_must_be_http():
    strong = "x" * 40
    assert Settings(jwt_secret=strong).production_problems() == []
    assert Settings(jwt_secret=strong, typesafe_base_url="file:///etc/passwd").production_problems()
