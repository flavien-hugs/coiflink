"""Tests du squelette backend : endpoint de santé et invariants du scaffold.

Sert de point d'ancrage vert au test gate `pytest` (cf. ADR-0003 / #6).
"""

from fastapi.testclient import TestClient

from coiflink_api.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_content_type_is_json() -> None:
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]


def test_unknown_route_returns_404() -> None:
    response = client.get("/nonexistent")
    assert response.status_code == 404


def test_app_name_from_env(monkeypatch: object) -> None:
    import importlib

    import coiflink_api.main as m

    monkeypatch.setenv("APP_NAME", "TestApp")
    importlib.reload(m)
    assert m.APP_NAME == "TestApp"
    # Remettre à l'état initial pour les autres tests.
    monkeypatch.delenv("APP_NAME", raising=False)
    importlib.reload(m)


def test_app_env_from_env(monkeypatch: object) -> None:
    import importlib

    import coiflink_api.main as m

    monkeypatch.setenv("APP_ENV", "staging")
    importlib.reload(m)
    assert m.APP_ENV == "staging"
    monkeypatch.delenv("APP_ENV", raising=False)
    importlib.reload(m)


def test_app_env_defaults_to_development(monkeypatch: object) -> None:
    import importlib

    import coiflink_api.main as m

    monkeypatch.delenv("APP_ENV", raising=False)
    importlib.reload(m)
    assert m.APP_ENV == "development"
    importlib.reload(m)
