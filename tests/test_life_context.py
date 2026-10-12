# ruff: noqa: F811
import pytest

from app import jev, life
from tests.test_api import _register, client  # noqa: F401

URL = "/api/v1/profile/context"
CATEGORIZE = "/api/v1/ai/categorize"

FULL = {
    "housing": "WITH_PARENTS",
    "household_size": 4,
    "children": 0,
    "car": "OWN",
    "car_age_years": 8,
    "commute": "NONE",
    "work_mode": "REMOTE",
    "employment": "EMPLOYEE",
    "phone_age_years": 3,
    "computer_age_years": 1,
    "has_emergency_fund": True,
    "emergency_fund_months": 3,
    "saves_regularly": True,
    "invests": False,
    "has_pets": True,
    "pets_description": "pies i dwa koty",
    "regular_health_costs": False,
    "does_sport": True,
    "pays_for_education": True,
    "custom": [{"name": "Hobby", "description": "fotografia, co kilka miesięcy kupuję sprzęt"}],
    "notes": "odkładam na własne mieszkanie",
}


@pytest.mark.parametrize(
    ("n", "text"),
    [(0, "mniej niż rok"), (1, "1 rok"), (2, "2 lata"), (4, "4 lata"), (5, "5 lat"), (12, "12 lat"), (22, "22 lata")],
)
def test_years_in_words(n, text):
    assert life.years(n) == text


def test_summary_describes_each_answer_in_group_order():
    assert life.summary(FULL) == [
        "Mieszka z rodzicami: nie płaci czynszu najmu ani raty za mieszkanie.",
        "Gospodarstwo domowe liczy 4 os.",
        "Nie ma dzieci na utrzymaniu.",
        "Ma własny samochód (wiek auta: 8 lat).",
        "Nie dojeżdża do pracy.",
        "Pracuje zdalnie, z domu.",
        "Jest zatrudniony na etacie lub umowie.",
        "Jego telefon ma 3 lata.",
        "Jego komputer ma 1 rok.",
        "Ma poduszkę finansową na 3 mies. wydatków.",
        "Regularnie odkłada pieniądze.",
        "Nie inwestuje.",
        "Ma zwierzęta domowe: pies i dwa koty.",
        "Nie ma stałych wydatków na leczenie.",
        "Regularnie uprawia sport lub chodzi na siłownię.",
        "Płaci za naukę, studia lub kursy.",
        "Hobby: fotografia, co kilka miesięcy kupuję sprzęt",
        "Sam o sobie dodaje: odkładam na własne mieszkanie",
    ]


def test_summary_skips_unanswered_questions():
    assert life.summary(None) == [] and life.summary({}) == []
    assert life.summary({"car": "NONE", "household_size": 1}) == ["Mieszka sam.", "Nie ma samochodu."]
    assert life.summary({"car": "FINANCED"}) == ["Ma samochód w leasingu albo na kredyt."]


def test_summary_of_savings_pets_and_custom_categories():
    assert life.summary({"has_emergency_fund": True}) == ["Ma poduszkę finansową."]
    assert life.summary({"has_emergency_fund": False}) == ["Nie ma jeszcze poduszki finansowej."]
    assert life.summary({"emergency_fund_months": 6}) == ["Ma poduszkę finansową na 6 mies. wydatków."]
    assert life.summary({"has_pets": True}) == ["Ma zwierzęta domowe."]
    mixed = {"has_pets": False, "invests": True}
    assert life.summary(mixed) == ["Inwestuje część oszczędności.", "Nie ma zwierząt domowych."]
    custom = [
        {"name": "Rodzina", "description": "pomagam finansowo rodzicom"},
        {"name": " ", "description": "pusta nazwa"},
    ]
    assert life.summary({"custom": custom}) == ["Rodzina: pomagam finansowo rodzicom"]


def test_own_categories_are_validated_and_dependent_answers_cleared(client):
    auth = _register(client, "life6@b.pl")
    item = {"name": "Hobby", "description": "fotografia"}
    assert client.put(URL, json={"custom": [item] * 11}, headers=auth)[1].status == 422  # najwyżej 10
    assert client.put(URL, json={"custom": [{"name": "Hobby"}]}, headers=auth)[1].status == 422  # brak opisu
    assert client.put(URL, json={"custom": [{"name": "  ", "description": "x"}]}, headers=auth)[1].status == 422
    assert client.put(URL, json={"custom": [{**item, "name": "x" * 41}]}, headers=auth)[1].status == 422

    body = {
        "custom": [item],
        "has_pets": False,
        "pets_description": "kot",
        "has_emergency_fund": False,
        "emergency_fund_months": 6,
    }
    _, res = client.put(URL, json=body, headers=auth)
    saved = res.json["context"]
    assert res.status == 200 and saved["custom"] == [item]
    assert saved["pets_description"] is None and saved["emergency_fund_months"] is None
    assert res.json["summary"] == [
        "Nie ma jeszcze poduszki finansowej.",
        "Nie ma zwierząt domowych.",
        "Hobby: fotografia",
    ]

    # sama pusta lista własnych kategorii to nadal pusty wywiad
    assert client.put(URL, json={"custom": []}, headers=auth)[1].json["filled"] is False


def test_categorize_request_carries_user_context():
    state, questions = jev.categorize_request(["Orlen"], ["Nie ma samochodu."])
    assert state["uzytkownik"] == ["Nie ma samochodu."]
    assert "sytuację użytkownika" in questions["q0"]["instructions"]
    state, questions = jev.categorize_request(["Orlen"], [])
    assert "uzytkownik" not in state and "sytuację użytkownika" not in questions["q0"]["instructions"]


def test_context_is_empty_until_saved(client):
    auth = _register(client, "life1@b.pl")
    _, res = client.get(URL, headers=auth)
    assert res.status == 200 and res.json["filled"] is False and res.json["summary"] == []
    assert res.json["context"]["housing"] is None and set(res.json["context"]) == set(FULL)


def test_saving_context_returns_answers_and_summary(client):
    auth = _register(client, "life2@b.pl")
    _, res = client.put(URL, json=FULL, headers=auth)
    assert res.status == 200 and res.json["filled"] is True
    assert res.json["context"] == FULL and len(res.json["summary"]) == 18
    assert client.get(URL, headers=auth)[1].json["context"] == FULL

    # częściowe odpowiedzi też są w porządku; auto, którego nie ma, nie ma wieku
    _, res = client.put(URL, json={"housing": "RENT", "car": "NONE", "car_age_years": 5}, headers=auth)
    assert res.json["context"]["car_age_years"] is None and res.json["context"]["work_mode"] is None
    assert res.json["summary"] == ["Wynajmuje mieszkanie: płaci czynsz najmu i opłaty.", "Nie ma samochodu."]

    # pusty wywiad usuwa odpowiedzi
    _, res = client.put(URL, json={}, headers=auth)
    assert res.json["filled"] is False and res.json["summary"] == []


def test_context_is_validated_private_and_requires_login(client):
    auth = _register(client, "life3@b.pl")
    assert client.put(URL, json={"housing": "PALAC"}, headers=auth)[1].status == 422
    assert client.put(URL, json={"phone_age_years": -1}, headers=auth)[1].status == 422
    assert client.put(URL, json={"notes": "x" * 301}, headers=auth)[1].status == 422
    assert client.put(URL, json={"pesel": "123"}, headers=auth)[1].status == 422  # nieznane pola są odrzucane
    client.put(URL, json=FULL, headers=auth)

    other = _register(client, "life4@b.pl")
    assert client.get(URL, headers=other)[1].json["filled"] is False
    assert client.get(URL)[1].status == 401 and client.put(URL, json=FULL)[1].status == 401


def test_jev_gets_context_only_for_logged_in_user_with_answers(client, monkeypatch):
    states = []

    async def system_one(state, questions):
        states.append(state)
        return {"q0": {"choice": "FUN"}}

    monkeypatch.setattr(jev, "system_one", system_one)
    body = {"items": [{"key": "k", "description": "Orlen"}]}
    auth = _register(client, "life5@b.pl")

    client.post(CATEGORIZE, json=body)  # bez konta
    client.post(CATEGORIZE, json=body, headers=auth)  # konto bez wywiadu
    client.put(URL, json={"car": "NONE", "work_mode": "REMOTE"}, headers=auth)
    _, res = client.post(CATEGORIZE, json=body, headers=auth)

    assert res.json == {"suggestions": {"k": "FUN"}}
    assert "uzytkownik" not in states[0] and "uzytkownik" not in states[1]
    assert states[2]["uzytkownik"] == ["Nie ma samochodu.", "Pracuje zdalnie, z domu."]
