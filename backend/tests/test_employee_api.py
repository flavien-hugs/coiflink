"""Tests API pour `POST /salons/{salon_id}/employees` (adapter entrant, #13).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_create_employee` → `CreateEmployee` avec ports fakes (aucune base) ;
- `get_user_repository` → `FakeAuthUserRepository` avec un MANAGER en base ;
- `get_access_policy` → `AccessPolicy` avec le salon dans le périmètre.

Vérifie :
- 201 + role=HAIRDRESSER, non-fuite du secret ;
- 409 sur doublon téléphone, email, appartenance déjà existante ;
- 422 sur validation pydantic et domaine ;
- 401 sans jeton ;
- 403 pour un rôle non autorisé (HAIRDRESSER, CLIENT) — `EMPLOYEE_MANAGE` absent ;
- 403 inter-salon (portée §11.2) ;
- anti-élévation : aucun champ `role` dans le corps de la requête ;
- route absente de `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.employees import get_create_employee
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.application.employees import CreateEmployee
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import EmailAlreadyInUse
from coiflink_api.main import app

from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakeHasher,
    FakeSalonMemberRepository,
    FakeSalonScopeRepository,
    FakeUserRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_EMPLOYEES_URL = f"/salons/{_SALON_ID}/employees"

_VALID_BODY = {
    "full_name": "Awa Koné",
    "phone": "0700000000",
    "password": "motdepasse-solide",
}

# Jeton d'accès MANAGER (valide, signé avec le secret de test).
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manager_creds() -> UserCredentials:
    return UserCredentials(
        id=_MANAGER_ID,
        role=Role.MANAGER.value,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _build_create_employee_usecase(
    existing_phones: set[str] | None = None,
    members: FakeSalonMemberRepository | None = None,
) -> CreateEmployee:
    return CreateEmployee(
        repository=FakeUserRepository(existing_phones=existing_phones),
        hasher=FakeHasher(),
        members=members or FakeSalonMemberRepository(),
        role=Role.HAIRDRESSER.value,
    )


def _build_create_employee_raising(exc: Exception) -> CreateEmployee:
    """Use case dont `execute` lève l'exception fournie."""

    class _RaisingMemberRepo:
        def add_member(self, _membership):  # type: ignore[override]
            raise exc

    return CreateEmployee(
        repository=FakeUserRepository(),
        hasher=FakeHasher(),
        members=_RaisingMemberRepo(),  # type: ignore[arg-type]
        role=Role.HAIRDRESSER.value,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_test_token_service() -> Generator[None, None, None]:
    """Monte un JwtTokenService signé avec TEST_JWT_SECRET sur app.state.

    Tous les tests de ce module exigent un token service valide.
    On restaure la valeur d'origine après chaque test.
    """
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture()
def manager_client() -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié sur _SALON_ID."""
    creds = _manager_creds()
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_ID})})

    app.dependency_overrides[get_create_employee] = lambda: _build_create_employee_usecase()
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_create_employee, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def manager_client_with_duplicate_phone() -> Generator[TestClient, None, None]:
    """TestClient dont le dépôt contient déjà le téléphone normalisé."""
    creds = _manager_creds()
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_ID})})

    app.dependency_overrides[get_create_employee] = (
        lambda: _build_create_employee_usecase(existing_phones={"+2250700000000"})
    )
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_create_employee, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def manager_client_email_duplicate() -> Generator[TestClient, None, None]:
    """TestClient dont le use case lève `EmailAlreadyInUse`."""
    creds = _manager_creds()
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_ID})})

    app.dependency_overrides[get_create_employee] = (
        lambda: _build_create_employee_raising(EmailAlreadyInUse("email déjà utilisé."))
    )
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_create_employee, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def manager_client_membership_duplicate() -> Generator[TestClient, None, None]:
    """TestClient dont le dépôt d'appartenances lève `EmployeeAlreadyInSalon`."""
    creds = _manager_creds()
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_ID})})

    duplicate_members = FakeSalonMemberRepository(raise_duplicate=True)
    app.dependency_overrides[get_create_employee] = (
        lambda: _build_create_employee_usecase(members=duplicate_members)
    )
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_create_employee, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Succès (201)
# ---------------------------------------------------------------------------


class TestCreateEmployeeSuccess:
    def test_status_201(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201

    def test_role_is_hairdresser(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["role"] == Role.HAIRDRESSER.value

    def test_role_is_not_manager(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["role"] != Role.MANAGER.value

    def test_status_is_active(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["status"] == UserStatus.ACTIVE.value

    def test_body_contains_id(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "id" in r.json()

    def test_body_contains_full_name(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["full_name"] == "Awa Koné"

    def test_phone_normalized_to_e164(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "phone": "0700000000"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["phone"] == "+2250700000000"

    def test_optional_email_absent_returns_null(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.json()["email"] is None

    def test_with_optional_email(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "email": "awa@example.com"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201

    def test_content_type_json(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "application/json" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Non-fuite des secrets
# ---------------------------------------------------------------------------


class TestNoSecretLeak:
    def test_password_key_absent_from_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "password" not in r.json()

    def test_password_hash_key_absent_from_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json=_VALID_BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "password_hash" not in r.json()

    def test_password_value_absent_from_json_text(self, manager_client: TestClient) -> None:
        password = "motdepasse-solide"
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "password": password},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert password not in r.text

    def test_hash_value_absent_from_json_text(self, manager_client: TestClient) -> None:
        password = "motdepasse-solide"
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "password": password},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert f"hash:{password}" not in r.text


# ---------------------------------------------------------------------------
# RBAC et contrôle d'accès
# ---------------------------------------------------------------------------


class TestRbacAndAccessControl:
    def test_missing_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(_EMPLOYEES_URL, json=_VALID_BODY)
        assert r.status_code == 401

    def test_hairdresser_role_returns_403(self) -> None:
        """Un HAIRDRESSER n'a pas EMPLOYEE_MANAGE → 403."""
        hairdresser_id = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        creds = UserCredentials(
            id=hairdresser_id,
            role=Role.HAIRDRESSER.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        )
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_ID})})
        token = make_access_token(hairdresser_id, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_create_employee] = lambda: _build_create_employee_usecase()
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _EMPLOYEES_URL,
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_create_employee, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403

    def test_client_role_returns_403(self) -> None:
        """Un CLIENT n'a pas EMPLOYEE_MANAGE → 403."""
        client_id = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
        creds = UserCredentials(
            id=client_id,
            role=Role.CLIENT.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        )
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(client_id, Role.CLIENT.value)

        app.dependency_overrides[get_create_employee] = lambda: _build_create_employee_usecase()
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _EMPLOYEES_URL,
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_create_employee, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        """Gérant hors périmètre du salon ciblé → 403 (isolation §11.2)."""
        creds = _manager_creds()
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        # Portée du gérant : uniquement _OTHER_SALON_ID, pas _SALON_ID
        scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_OTHER_SALON_ID})})

        app.dependency_overrides[get_create_employee] = lambda: _build_create_employee_usecase()
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _EMPLOYEES_URL,
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_create_employee, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403

    def test_forbidden_detail_is_generic(self) -> None:
        """Le message 403 ne révèle ni l'identité ni la ressource (PRD §11.1)."""
        client_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
        creds = UserCredentials(
            id=client_id,
            role=Role.CLIENT.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        )
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(client_id, Role.CLIENT.value)

        app.dependency_overrides[get_create_employee] = lambda: _build_create_employee_usecase()
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _EMPLOYEES_URL,
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_create_employee, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403
        detail = r.json().get("detail", "")
        assert "Accès refusé." == detail


# ---------------------------------------------------------------------------
# Conflits (409)
# ---------------------------------------------------------------------------


class TestDuplicateConflicts:
    def test_duplicate_phone_returns_409(
        self, manager_client_with_duplicate_phone: TestClient
    ) -> None:
        r = manager_client_with_duplicate_phone.post(
            _EMPLOYEES_URL,
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 409

    def test_duplicate_phone_detail_does_not_contain_phone(
        self, manager_client_with_duplicate_phone: TestClient
    ) -> None:
        r = manager_client_with_duplicate_phone.post(
            _EMPLOYEES_URL,
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 409
        assert "0700000000" not in r.text
        assert "+2250700000000" not in r.text

    def test_duplicate_email_returns_409(
        self, manager_client_email_duplicate: TestClient
    ) -> None:
        body = {**_VALID_BODY, "email": "awa@example.com"}
        r = manager_client_email_duplicate.post(
            _EMPLOYEES_URL,
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 409

    def test_employee_already_in_salon_returns_409(
        self, manager_client_membership_duplicate: TestClient
    ) -> None:
        r = manager_client_membership_duplicate.post(
            _EMPLOYEES_URL,
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 409

    def test_conflict_response_contains_non_empty_detail(
        self, manager_client_with_duplicate_phone: TestClient
    ) -> None:
        r = manager_client_with_duplicate_phone.post(
            _EMPLOYEES_URL,
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        body = r.json()
        assert "detail" in body
        assert body["detail"]


# ---------------------------------------------------------------------------
# Validation Pydantic (422)
# ---------------------------------------------------------------------------


class TestPydanticValidation:
    def test_missing_full_name_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "full_name"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 422

    def test_missing_phone_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "phone"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 422

    def test_missing_password_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "password"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 422

    def test_empty_json_body_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL, json={}, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 422

    def test_invalid_email_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "email": "pas-un-email"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_full_name_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "full_name": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_password_too_short_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "password": "court"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_full_name_256_chars_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "full_name": "a" * 256},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_password_129_chars_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "password": "a" * 129},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_full_name_255_chars_accepted(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "full_name": "a" * 255},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_password_128_chars_accepted(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "password": "a" * 128},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Validation domaine (422)
# ---------------------------------------------------------------------------


class TestDomainValidation:
    def test_invalid_phone_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "phone": "abcdefg"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_phone_too_short_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _EMPLOYEES_URL,
            json={**_VALID_BODY, "phone": "123"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Anti-élévation de privilège — pas de champ `role` dans la requête
# ---------------------------------------------------------------------------


class TestAntiPrivilegeEscalation:
    def test_request_schema_has_no_role_field(self) -> None:
        """Vérification statique : `CreateEmployeeRequest` ne déclare pas de champ `role`."""
        from coiflink_api.adapters.inbound.employees import CreateEmployeeRequest

        assert "role" not in CreateEmployeeRequest.model_fields

    def test_role_admin_in_body_ignored_returns_hairdresser(
        self, manager_client: TestClient
    ) -> None:
        body = {**_VALID_BODY, "role": "ADMIN"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201
        assert r.json()["role"] == Role.HAIRDRESSER.value

    def test_role_manager_in_body_ignored_returns_hairdresser(
        self, manager_client: TestClient
    ) -> None:
        body = {**_VALID_BODY, "role": "MANAGER"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201
        assert r.json()["role"] == Role.HAIRDRESSER.value

    def test_role_client_in_body_ignored_returns_hairdresser(
        self, manager_client: TestClient
    ) -> None:
        body = {**_VALID_BODY, "role": "CLIENT"}
        r = manager_client.post(
            _EMPLOYEES_URL, json=body, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 201
        assert r.json()["role"] == Role.HAIRDRESSER.value


# ---------------------------------------------------------------------------
# Route hors liste publique et méthodes HTTP
# ---------------------------------------------------------------------------


class TestRouteConfiguration:
    def test_employees_path_not_in_public_route_paths(self) -> None:
        """La route employees n'est pas listée comme publique (deny-by-default)."""
        pattern = f"/salons/{_SALON_ID}/employees"
        assert pattern not in PUBLIC_ROUTE_PATHS
        # Le préfixe patron aussi
        assert "/salons/{salon_id}/employees" not in PUBLIC_ROUTE_PATHS

    def test_get_method_returns_405(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _EMPLOYEES_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 405
