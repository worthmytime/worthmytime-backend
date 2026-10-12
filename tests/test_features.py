# ruff: noqa: F811
from app.config import Settings, parse_feature_flags, settings
from tests.test_api import client  # noqa: F401


def test_parse_names_and_values():
    flags, invalid = parse_feature_flags(" reports, tags=false ,Rollover=ON,beta_2=0,")
    assert flags == {"reports": True, "tags": False, "rollover": True, "beta_2": False}
    assert invalid == []


def test_parse_reports_invalid_entries_and_keeps_the_rest():
    flags, invalid = parse_feature_flags("reports,tags=maybe,z spacją,=true")
    assert flags == {"reports": True}
    assert invalid == ["tags=maybe", "z spacją", "=true"]


def test_empty_config_means_no_flags():
    assert parse_feature_flags("") == ({}, [])
    assert Settings(feature_flags="").feature_flag_map == {}


def test_invalid_flags_block_production_start():
    strong = "x" * 40
    assert Settings(jwt_secret=strong, feature_flags="reports,tags=false").production_problems() == []
    problems = Settings(jwt_secret=strong, feature_flags="tags=maybe").production_problems()
    assert len(problems) == 1 and "FEATURE_FLAGS" in problems[0]


def test_features_endpoint_is_public_and_reflects_config(client, monkeypatch):
    _, res = client.get("/api/v1/features")
    assert res.status == 200 and res.json == {"features": settings.feature_flag_map}

    monkeypatch.setattr(settings, "feature_flags", "reports,tags=false")
    _, res = client.get("/api/v1/features")
    assert res.json == {"features": {"reports": True, "tags": False}}
