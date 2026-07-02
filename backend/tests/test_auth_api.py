"""Tests API pour `POST /auth/register` (adapter entrant, #8).

Utilise FastAPI `TestClient` avec override de `get_register_client` pour
injecter un `RegisterClient` à ports fakes — aucune base de données réelle.
Vérifie : 201 succès, non-fuite du mot de passe, 409 doublon, 422 validation.
"""

from __future__ import annotations

import datetime
from collections.abc import Generator
from random import Random

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.auth import get_register_client
from coiflink_api.application.registration import RegisterClient
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FakeHasher,
    FakeOtpRepository,
    FakeOtpSender,
    FakeUserRepository,
)

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

_VALID_BODY = {
    "full_name": "Awa Koné",
    "phone": "0700000000",
    "password": "motdepasse-solide",
}


def _build_usecase(
    existing_phones: set[str] | None = None,
    otp_enabled: bool = False,
) -> RegisterClient:
    return RegisterClient(
        repository=FakeUserRepository(existing_phones=existing_phones),
        hasher=FakeHasher(),
        otp_enabled=otp_enabled,
        otp_sender=FakeOtpSender(),
        otp_repository=FakeOtpRepository(),
        rng=Random(42),
        clock=lambda: _NOW,
    )


@pytest.fixture()
def client_without_db() -> Generator[TestClient, None, None]:
    """TestClient dont `get_register_client` est remplacé par un fake."""

    def _fake_register_client() -> RegisterClient:
        return _build_usecase()

    app.dependency_overrides[get_register_client] = _fake_register_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_register_client, None)


@pytest.fixture()
def client_with_duplicate() -> Generator[TestClient, None, None]:
    """TestClient dont le dépôt contient déjà le téléphone normalisé."""

    def _fake_register_client() -> RegisterClient:
        return _build_usecase(existing_phones={"+2250700000000"})

    app.dependency_overrides[get_register_client] = _fake_register_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_register_client, None)


class TestRegistrationSuccess:
    def test_status_201(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert r.status_code == 201

    def test_body_contains_id(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert "id" in r.json()

    def test_body_contains_full_name(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert r.json()["full_name"] == "Awa Koné"

    def test_body_contains_phone(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert "phone" in r.json()

    def test_body_contains_role_client(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert r.json()["role"] == Role.CLIENT.value

    def test_body_contains_status_active(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert r.json()["status"] == UserStatus.ACTIVE.value

    def test_body_contains_created_at(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert "created_at" in r.json()

    def test_optional_email_absent_returns_null(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert r.json()["email"] is None

    def test_with_optional_email(self, client_without_db: TestClient) -> None:
        body = {**_VALID_BODY, "email": "awa@example.com"}
        r = client_without_db.post("/auth/register", json=body)
        assert r.status_code == 201


class TestNoSecretLeak:
    def test_password_absent_from_response(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        body = r.json()
        assert "password" not in body

    def test_password_hash_absent_from_response(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        body = r.json()
        assert "password_hash" not in body

    def test_password_value_absent_from_json_body(self, client_without_db: TestClient) -> None:
        password = "motdepasse-solide"
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "password": password})
        assert password not in r.text

    def test_hash_absent_from_json_body(self, client_without_db: TestClient) -> None:
        """Le condensat fake 'hash:motdepasse-solide' ne doit pas apparaître dans la réponse."""
        password = "motdepasse-solide"
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "password": password})
        assert f"hash:{password}" not in r.text


class TestDuplicatePhone:
    def test_duplicate_returns_409(self, client_with_duplicate: TestClient) -> None:
        r = client_with_duplicate.post("/auth/register", json=_VALID_BODY)
        assert r.status_code == 409

    def test_duplicate_local_format_returns_409(self, client_with_duplicate: TestClient) -> None:
        """0700000000 (local) est normalisé → reconnu comme doublon."""
        r = client_with_duplicate.post("/auth/register", json={**_VALID_BODY, "phone": "0700000000"})
        assert r.status_code == 409

    def test_duplicate_e164_format_returns_409(self, client_with_duplicate: TestClient) -> None:
        r = client_with_duplicate.post("/auth/register", json={**_VALID_BODY, "phone": "+2250700000000"})
        assert r.status_code == 409


class TestPydanticValidation:
    def test_missing_full_name_field_returns_422(self, client_without_db: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "full_name"}
        r = client_without_db.post("/auth/register", json=body)
        assert r.status_code == 422

    def test_missing_phone_field_returns_422(self, client_without_db: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "phone"}
        r = client_without_db.post("/auth/register", json=body)
        assert r.status_code == 422

    def test_missing_password_field_returns_422(self, client_without_db: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "password"}
        r = client_without_db.post("/auth/register", json=body)
        assert r.status_code == 422

    def test_invalid_email_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "email": "pas-un-email"})
        assert r.status_code == 422

    def test_empty_full_name_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "full_name": ""})
        assert r.status_code == 422

    def test_password_too_short_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "password": "court"})
        assert r.status_code == 422

    def test_empty_json_body_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={})
        assert r.status_code == 422


class TestDomainValidation:
    def test_invalid_phone_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "phone": "abcdefg"})
        assert r.status_code == 422

    def test_phone_too_short_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "phone": "123"})
        assert r.status_code == 422


class TestContentType:
    def test_content_type_json(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json=_VALID_BODY)
        assert "application/json" in r.headers.get("content-type", "")


class TestFieldLimits:
    def test_full_name_256_chars_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "full_name": "a" * 256})
        assert r.status_code == 422

    def test_phone_33_chars_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "phone": "0" * 33})
        assert r.status_code == 422

    def test_password_129_chars_returns_422(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "password": "a" * 129})
        assert r.status_code == 422

    def test_full_name_255_chars_accepted(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "full_name": "a" * 255})
        assert r.status_code == 201

    def test_password_128_chars_accepted(self, client_without_db: TestClient) -> None:
        r = client_without_db.post(
            "/auth/register", json={**_VALID_BODY, "password": "a" * 128}
        )
        assert r.status_code == 201


class TestResponseNormalization:
    def test_local_phone_returns_e164_in_response(self, client_without_db: TestClient) -> None:
        r = client_without_db.post("/auth/register", json={**_VALID_BODY, "phone": "0700000000"})
        assert r.status_code == 201
        assert r.json()["phone"] == "+2250700000000"

    def test_duplicate_response_contains_non_empty_detail(
        self, client_with_duplicate: TestClient
    ) -> None:
        r = client_with_duplicate.post("/auth/register", json=_VALID_BODY)
        assert r.status_code == 409
        body = r.json()
        assert "detail" in body
        assert body["detail"]

    def test_duplicate_response_detail_does_not_contain_phone(
        self, client_with_duplicate: TestClient
    ) -> None:
        """Le message d'erreur 409 ne doit pas exposer le numéro de téléphone."""
        r = client_with_duplicate.post("/auth/register", json=_VALID_BODY)
        assert r.status_code == 409
        assert "0700000000" not in r.text
        assert "+2250700000000" not in r.text


class TestHttpMethod:
    def test_get_register_returns_405(self, client_without_db: TestClient) -> None:
        r = client_without_db.get("/auth/register")
        assert r.status_code == 405
