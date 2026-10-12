# ruff: noqa: F811
from app.helpers import today
from tests.test_api import PROFILE, _register, client  # noqa: F401

URL = "/api/v1/goals"


def _goal(client, auth, **over):
    body = {"name": "Wakacje", "target_amount": 5000, **over}
    return client.post(URL, json=body, headers=auth)[1].json["id"]


def _deposits(client, auth, goal_id):
    return client.get(f"{URL}/{goal_id}/deposits", headers=auth)[1].json


def test_deposits_and_withdrawals_are_recorded(client):
    auth = _register(client, "dep1@b.pl")
    gid = _goal(client, auth)
    assert _deposits(client, auth, gid) == {"items": [], "total": 0}

    client.post(f"{URL}/{gid}/deposit", json={"amount": 300}, headers=auth)
    client.post(f"{URL}/{gid}/deposit", json={"amount": -100}, headers=auth)

    history = _deposits(client, auth, gid)
    assert sorted(d["amount"] for d in history["items"]) == [-100, 300]
    assert {d["deposited_on"] for d in history["items"]} == {today().isoformat()}
    assert history["total"] == 200  # suma historii równa się odłożonej kwocie
    assert client.get(URL, headers=auth)[1].json["items"][0]["saved_amount"] == 200


def test_initial_amount_and_manual_correction_are_in_history(client):
    auth = _register(client, "dep2@b.pl")
    gid = _goal(client, auth, saved_amount=500)
    assert [d["amount"] for d in _deposits(client, auth, gid)["items"]] == [500]

    # edycja celu ze zmianą odłożonej kwoty zapisuje różnicę; edycja bez zmiany kwoty nic nie dopisuje
    client.put(f"{URL}/{gid}", json={"name": "Wakacje", "target_amount": 5000, "saved_amount": 350}, headers=auth)
    client.put(f"{URL}/{gid}", json={"name": "Urlop", "target_amount": 6000, "saved_amount": 350}, headers=auth)
    history = _deposits(client, auth, gid)
    assert sorted(d["amount"] for d in history["items"]) == [-150, 500] and history["total"] == 350


def test_rejected_withdrawal_leaves_no_trace(client):
    auth = _register(client, "dep3@b.pl")
    gid = _goal(client, auth, saved_amount=100)
    assert client.post(f"{URL}/{gid}/deposit", json={"amount": -500}, headers=auth)[1].status == 422
    assert _deposits(client, auth, gid)["total"] == 100


def test_history_is_private_and_removed_with_goal(client):
    auth = _register(client, "dep4@b.pl")
    gid = _goal(client, auth, saved_amount=100)
    other = _register(client, "dep5@b.pl")
    assert client.get(f"{URL}/{gid}/deposits", headers=other)[1].status == 404
    assert client.get(f"{URL}/{gid}/deposits")[1].status == 401

    client.delete(f"{URL}/{gid}", headers=auth)
    assert client.get(f"{URL}/{gid}/deposits", headers=auth)[1].status == 404
    assert client.get("/api/v1/export", headers=auth)[1].json["goal_deposits"] == []


def test_month_report_and_export_include_deposits(client):
    auth = _register(client, "dep6@b.pl")
    client.put("/api/v1/profile", json=PROFILE, headers=auth)
    gid = _goal(client, auth, saved_amount=200)
    client.post(f"{URL}/{gid}/deposit", json={"amount": 300}, headers=auth)
    client.post(f"{URL}/{gid}/deposit", json={"amount": -50}, headers=auth)

    _, res = client.get("/api/v1/reports/month", headers=auth)
    assert res.json["saved"]["goals"] == 450  # wpłaty minus wypłaty w bieżącym miesiącu
    assert client.get("/api/v1/reports/month?month=2020-01", headers=auth)[1].json["saved"]["goals"] == 0

    _, res = client.get("/api/v1/export", headers=auth)
    assert sorted(d["amount"] for d in res.json["goal_deposits"]) == [-50, 200, 300]
    assert {d["goal_name"] for d in res.json["goal_deposits"]} == {"Wakacje"}
    _, res = client.get("/api/v1/export?format=csv", headers=auth)
    assert res.text.count("goal_deposit,") == 3
    # zakres dat dotyczy daty wpłaty
    assert client.get("/api/v1/export?to=2020-01-01", headers=auth)[1].json["goal_deposits"] == []
