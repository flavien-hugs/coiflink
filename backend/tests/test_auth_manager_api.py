"""Tests API pour `POST /auth/register/manager` (adapter entrant, #9).

Utilise FastAPI `TestClient` avec override de `get_register_manager` pour
injecter un `RegisterUser(role=MANAGER)` à ports fakes — aucune base de données
réelle. Vérifie : 201 succès, rôle MANAGER imposé côté serveur, non-fuite du mot
de passe, 409 doublon, 422 validation, anti-injection de rôle (test de sécurité).
"""

from __future__ import annotations

import datetime
from collections.abc import Generator
from random import Random

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.auth import get_register_manager
from coiflink_api.application.registration import RegisterUser
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
    "full_name": "Koné Moussa",
    "phone": "0700000001",
    "password": "motdepasse-solide",
}


def _build_manager_usecase(
    existing_phones: set[str] | None = None,
    otp_enabled: bool = False,
) -> RegisterUser:
    return RegisterUser(
        repository=FakeUserRepository(existing_phones=existing_phones),
        hasher=FakeHasher(),
        role=Role.MANAGER,
        otp_enabled=otp_enabled,
        otp_sender=FakeOtpSender(),
        otp_repository=FakeOtpRepository(),
        rng=Random(42),
        clock=lambda: _NOW,
    )


@pytest.fixture()
def manager_client() -> Generator[TestClient, None, None]:
    """TestClient dont `get_register_manager` est remplacé par un fake."""

    def _fake() -> RegisterUser:
        return _build_manager_usecase()

    app.dependency_overrides[get_register_manager] = _fake
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_register_manager, None)


@pytest.fixture()
def manager_client_with_duplicate() -> Generator[TestClient, None, None]:
    """TestClient dont le dépôt contient déjà le téléphone normalisé (`+2250700000001`)."""

    def _fake() -> RegisterUser:
        return _build_manager_usecase(existing_phones={"+2250700000001"})

    app.dependency_overrides[get_register_manager] = _fake
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_register_manager, None)


class TestManagerRegistrationSuccess:
    def test_status_201(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert r.status_code == 201

    def test_role_is_manager(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert r.json()["role"] == Role.MANAGER.value

    def test_status_is_active(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert r.json()["status"] == UserStatus.ACTIVE.value

    def test_body_contains_id(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert "id" in r.json()

    def test_body_contains_full_name(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert r.json()["full_name"] == "Koné Moussa"

    def test_body_contains_phone(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert "phone" in r.json()

    def test_body_contains_created_at(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert "created_at" in r.json()

    def test_optional_email_absent_returns_null(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert r.json()["email"] is None

    def test_with_optional_email(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "email": "moussa@example.com"}
        r = manager_client.post("/auth/register/manager", json=body)
        assert r.status_code == 201


class TestManagerNoSecretLeak:
    def test_password_absent_from_response(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert "password" not in r.json()

    def test_password_hash_absent_from_response(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert "password_hash" not in r.json()

    def test_password_value_absent_from_response_text(self, manager_client: TestClient) -> None:
        password = "motdepasse-solide"
        r = manager_client.post("/auth/register/manager", json={**_VALID_BODY, "password": password})
        assert password not in r.text

    def test_hash_absent_from_response_text(self, manager_client: TestClient) -> None:
        """Le condensat fake `hash:motdepasse-solide` ne doit pas apparaître dans la réponse."""
        password = "motdepasse-solide"
        r = manager_client.post("/auth/register/manager", json={**_VALID_BODY, "password": password})
        assert f"hash:{password}" not in r.text


class TestManagerDuplicatePhone:
    def test_duplicate_returns_409(self, manager_client_with_duplicate: TestClient) -> None:
        r = manager_client_with_duplicate.post("/auth/register/manager", json=_VALID_BODY)
        assert r.status_code == 409

    def test_duplicate_local_format_returns_409(
        self, manager_client_with_duplicate: TestClient
    ) -> None:
        """0700000001 (local) est normalisé → reconnu comme doublon."""
        body = {**_VALID_BODY, "phone": "0700000001"}
        r = manager_client_with_duplicate.post("/auth/register/manager", json=body)
        assert r.status_code == 409

    def test_duplicate_e164_format_returns_409(
        self, manager_client_with_duplicate: TestClient
    ) -> None:
        """+2250700000001 (E.164) → reconnu comme doublon."""
        body = {**_VALID_BODY, "phone": "+2250700000001"}
        r = manager_client_with_duplicate.post("/auth/register/manager", json=body)
        assert r.status_code == 409


class TestManagerPydanticValidation:
    def test_missing_full_name_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "full_name"}
        r = manager_client.post("/auth/register/manager", json=body)
        assert r.status_code == 422

    def test_missing_phone_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "phone"}
        r = manager_client.post("/auth/register/manager", json=body)
        assert r.status_code == 422

    def test_missing_password_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "password"}
        r = manager_client.post("/auth/register/manager", json=body)
        assert r.status_code == 422

    def test_invalid_email_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "email": "pas-un-email"}
        )
        assert r.status_code == 422

    def test_empty_full_name_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json={**_VALID_BODY, "full_name": ""})
        assert r.status_code == 422

    def test_password_too_short_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json={**_VALID_BODY, "password": "court"})
        assert r.status_code == 422

    def test_empty_json_body_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json={})
        assert r.status_code == 422


class TestManagerDomainValidation:
    def test_invalid_phone_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json={**_VALID_BODY, "phone": "abcdefg"})
        assert r.status_code == 422

    def test_phone_too_short_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json={**_VALID_BODY, "phone": "123"})
        assert r.status_code == 422


class TestManagerRoleInjectionRefused:
    """Tests de sécurité : le rôle ne doit JAMAIS provenir de la requête.

    `RegisterRequest.extra="forbid"` garantit qu'un champ `role` injecté par
    l'appelant provoque un `422` plutôt qu'être silencieusement ignoré — défense
    en profondeur contre l'élévation de privilège (PRD §11, label `security`).
    """

    def test_role_admin_in_body_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "role": "ADMIN"}
        )
        assert r.status_code == 422

    def test_role_manager_in_body_returns_422(self, manager_client: TestClient) -> None:
        """Même `role=MANAGER` explicite est rejeté : le rôle est imposé par le chemin."""
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "role": "MANAGER"}
        )
        assert r.status_code == 422

    def test_role_client_in_body_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "role": "CLIENT"}
        )
        assert r.status_code == 422

    def test_role_hairdresser_in_body_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "role": "HAIRDRESSER"}
        )
        assert r.status_code == 422

    def test_without_role_field_response_role_is_manager(
        self, manager_client: TestClient
    ) -> None:
        """Sans champ `role` : le rôle attribué est bien MANAGER (imposé côté serveur)."""
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert r.status_code == 201
        assert r.json()["role"] == Role.MANAGER.value


class TestManagerFieldLimits:
    def test_full_name_256_chars_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "full_name": "a" * 256}
        )
        assert r.status_code == 422

    def test_phone_33_chars_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "phone": "0" * 33}
        )
        assert r.status_code == 422

    def test_password_129_chars_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "password": "a" * 129}
        )
        assert r.status_code == 422

    def test_full_name_255_chars_accepted(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "full_name": "a" * 255}
        )
        assert r.status_code == 201

    def test_password_128_chars_accepted(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "password": "a" * 128}
        )
        assert r.status_code == 201


class TestManagerResponseNormalization:
    def test_local_phone_returns_e164_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            "/auth/register/manager", json={**_VALID_BODY, "phone": "0700000001"}
        )
        assert r.status_code == 201
        assert r.json()["phone"] == "+2250700000001"

    def test_duplicate_detail_does_not_contain_phone(
        self, manager_client_with_duplicate: TestClient
    ) -> None:
        """Le message d'erreur 409 ne doit pas exposer le numéro de téléphone (PRD §11.3)."""
        r = manager_client_with_duplicate.post("/auth/register/manager", json=_VALID_BODY)
        assert r.status_code == 409
        assert "0700000001" not in r.text
        assert "+2250700000001" not in r.text

    def test_duplicate_response_contains_non_empty_detail(
        self, manager_client_with_duplicate: TestClient
    ) -> None:
        r = manager_client_with_duplicate.post("/auth/register/manager", json=_VALID_BODY)
        assert r.status_code == 409
        body = r.json()
        assert "detail" in body
        assert body["detail"]


class TestManagerContentType:
    def test_content_type_json(self, manager_client: TestClient) -> None:
        r = manager_client.post("/auth/register/manager", json=_VALID_BODY)
        assert "application/json" in r.headers.get("content-type", "")


class TestManagerHttpMethod:
    def test_get_register_manager_returns_405(self, manager_client: TestClient) -> None:
        r = manager_client.get("/auth/register/manager")
        assert r.status_code == 405
