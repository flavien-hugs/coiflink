"""Tests API — router `/salons/{id}/customers` (adapter entrant, US-4.1, #28).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_customer_repository` → `FakeCustomerRepository` ;
- `get_audit_log` → `FakeAuditLog` ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- POST 201 : corps complet (téléphone normalisé, `total_visits=0`, `last_visit_at=null`,
  **pas de `user_id`**), champs privilégiés ignorés ;
- POST 422 : nom invalide/vide, téléphone invalide, genre inconnu, notes trop longues ;
- POST 409 : doublon de téléphone dans le salon ;
- GET liste 200 (paginée) ;
- GET fiche 200 ; GET fiche 404 (inconnu après validation de portée) ;
- RBAC : `401` sans jeton sur les 3 routes, `403` CLIENT/HAIRDRESSER/ADMIN/hors-portée,
  message `403` générique et constant ;
- `PUBLIC_ROUTE_PATHS` : aucune route customer ne doit y figurer.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.customers import get_audit_log, get_customer_repository
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeCustomerRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_OTHER_MANAGER_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ADMIN_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_HAIRDRESSER_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_CLIENT_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")
_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_VALID_BODY: dict = {
    "full_name": "Awa Koné",
    "phone": "0700000000",
    "gender": "FEMALE",
    "notes": "Préfère le samedi matin.",
}

_MIN_BODY: dict = {"full_name": "Awa Koné"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _customers_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/customers"


def _customer_url(salon_id: uuid.UUID, customer_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/customers/{customer_id}"


def _notes_url(salon_id: uuid.UUID, customer_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/customers/{customer_id}/notes"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture()
def customer_repo() -> FakeCustomerRepository:
    return FakeCustomerRepository()


@pytest.fixture()
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture()
def manager_client(
    customer_repo: FakeCustomerRepository,
    audit_log: FakeAuditLog,
) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié et salon dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_customer_repository] = lambda: customer_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_customer_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/customers — 201 corps et projection
# ---------------------------------------------------------------------------


class TestCreateCustomer201:
    def test_returns_201_on_success(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_phone_normalized_to_e164(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["phone"] == "+2250700000000"

    def test_total_visits_is_zero(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total_visits"] == 0

    def test_last_visit_at_is_null(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["last_visit_at"] is None

    def test_user_id_not_in_response(self, manager_client: TestClient) -> None:
        """Anti-oracle : `user_id` n'est pas exposé (ADR-0026)."""
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "user_id" not in r.json()

    def test_salon_id_in_response_matches_path(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_gender_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["gender"] == "FEMALE"

    def test_notes_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["notes"] == "Préfère le samedi matin."

    def test_id_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "id" in r.json()

    def test_optional_fields_omitted_returns_201(
        self, manager_client: TestClient
    ) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_MIN_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_optional_fields_null_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=_MIN_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["phone"] is None
        assert data["gender"] is None
        assert data["notes"] is None


# ---------------------------------------------------------------------------
# POST — champs privilégiés ignorés (extra="ignore")
# ---------------------------------------------------------------------------


class TestCreateCustomerIgnoredFields:
    def test_salon_id_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_VALID_BODY, "salon_id": str(_OTHER_SALON_ID)}
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_user_id_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_MIN_BODY, "user_id": str(uuid.uuid4())}
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_total_visits_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_MIN_BODY, "total_visits": 999}
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["total_visits"] == 0

    def test_id_in_body_ignored(self, manager_client: TestClient) -> None:
        body = {**_MIN_BODY, "id": str(uuid.uuid4())}
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# POST — 422 validation
# ---------------------------------------------------------------------------


class TestCreateCustomer422:
    def test_missing_full_name_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json={"phone": "0700000000"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_full_name_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json={**_MIN_BODY, "full_name": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_invalid_phone_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json={**_MIN_BODY, "phone": "not-a-phone"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_unknown_gender_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json={**_MIN_BODY, "gender": "UNKNOWN"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_lowercase_gender_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json={**_MIN_BODY, "gender": "female"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_notes_over_limit_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _customers_url(_SALON_ID),
            json={**_MIN_BODY, "notes": "A" * 2001},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST — 409 doublon
# ---------------------------------------------------------------------------


class TestCreateCustomer409:
    def test_duplicate_phone_returns_409(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                headers = {"Authorization": f"Bearer {_MANAGER_TOKEN}"}
                c.post(_customers_url(_SALON_ID), json=_VALID_BODY, headers=headers)
                r = c.post(_customers_url(_SALON_ID), json=_VALID_BODY, headers=headers)
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 409

    def test_409_message_does_not_contain_phone(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Message neutre (§11.3) : le numéro soumis n'est jamais rappelé."""
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                headers = {"Authorization": f"Bearer {_MANAGER_TOKEN}"}
                c.post(_customers_url(_SALON_ID), json=_VALID_BODY, headers=headers)
                r = c.post(_customers_url(_SALON_ID), json=_VALID_BODY, headers=headers)
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        detail = r.json().get("detail", "")
        assert "0700000000" not in detail
        assert "+2250700000000" not in detail


# ---------------------------------------------------------------------------
# POST — RBAC
# ---------------------------------------------------------------------------


class TestCreateCustomerRbac:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(_customers_url(_SALON_ID), json=_VALID_BODY)
        assert r.status_code == 401

    def test_client_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _customers_url(_SALON_ID),
                    json=_MIN_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(
            scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})}
        )
        token = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _customers_url(_SALON_ID),
                    json=_MIN_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_admin_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_ADMIN_ID, Role.ADMIN.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_ADMIN_ID, Role.ADMIN.value)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _customers_url(_SALON_ID),
                    json=_MIN_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Isolation §11.2 : un gérant ciblant un autre salon reçoit 403 générique."""
        creds = _creds(_OTHER_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(
            scopes={_OTHER_MANAGER_ID: frozenset({_OTHER_SALON_ID})}
        )
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _customers_url(_SALON_ID),
                    json=_MIN_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_403_detail_is_generic(self, manager_client: TestClient) -> None:
        """Le message 403 est constant et ne révèle pas de motif (ADR-0015)."""
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        customer_repo = FakeCustomerRepository()
        audit_log_instance = FakeAuditLog()

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log_instance
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _customers_url(_SALON_ID),
                    json=_MIN_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/customers — liste
# ---------------------------------------------------------------------------


class TestListCustomers:
    def test_manager_gets_200(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_customers_url(_SALON_ID))
        assert r.status_code == 401

    def test_response_contains_items_and_total(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_empty_salon_returns_empty_list(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_client_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _customers_url(_SALON_ID),
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_invalid_limit_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID) + "?limit=0",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_limit_over_max_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID) + "?limit=201",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_negative_offset_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID) + "?offset=-1",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/customers — filtres (q, genre, plage de dates)
# ---------------------------------------------------------------------------


class TestListCustomers200WithFilters:
    def test_filter_q_matches_name_substring(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository, audit_log: FakeAuditLog
    ) -> None:
        from coiflink_api.application.customers import CreateCustomer, CustomerCommand

        CreateCustomer(customer_repo, audit_log).execute(
            _SALON_ID, CustomerCommand(full_name="Awa Koné"), actor_user_id=_MANAGER_ID
        )
        CreateCustomer(customer_repo, audit_log).execute(
            _SALON_ID, CustomerCommand(full_name="Fatou Diabaté"), actor_user_id=_MANAGER_ID
        )

        r = manager_client.get(
            _customers_url(_SALON_ID),
            params={"q": "koné"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["full_name"] == "Awa Koné"

    def test_filter_gender_exact_match(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository, audit_log: FakeAuditLog
    ) -> None:
        from coiflink_api.application.customers import CreateCustomer, CustomerCommand

        CreateCustomer(customer_repo, audit_log).execute(
            _SALON_ID,
            CustomerCommand(full_name="Awa Koné", gender="FEMALE"),
            actor_user_id=_MANAGER_ID,
        )
        CreateCustomer(customer_repo, audit_log).execute(
            _SALON_ID,
            CustomerCommand(full_name="Ibrahim Touré", gender="MALE"),
            actor_user_id=_MANAGER_ID,
        )

        r = manager_client.get(
            _customers_url(_SALON_ID),
            params={"gender": "FEMALE"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["gender"] == "FEMALE"

    def test_unknown_gender_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID),
            params={"gender": "UNKNOWN"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_created_from_gt_created_to_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID),
            params={"created_from": "2026-03-31", "created_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_422_message_does_not_repeat_invalid_value(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customers_url(_SALON_ID),
            params={"gender": "UNKNOWN_GENDER_VALUE"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        detail = r.json().get("detail", "")
        assert "UNKNOWN_GENDER_VALUE" not in detail


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/customers/{customer_id} — fiche individuelle
# ---------------------------------------------------------------------------


class TestGetCustomerDetail:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_customer_url(_SALON_ID, uuid.uuid4()))
        assert r.status_code == 401

    def test_unknown_customer_returns_404(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _customer_url(_SALON_ID, uuid.uuid4()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_known_customer_returns_200(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        from coiflink_api.application.customers import CreateCustomer, CustomerCommand

        customer = CreateCustomer(customer_repo, audit_log).execute(
            _SALON_ID,
            CustomerCommand(full_name="Awa Koné"),
            actor_user_id=_MANAGER_ID,
        )

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _customer_url(_SALON_ID, customer.id),
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 200
        assert r.json()["id"] == str(customer.id)

    def test_customer_from_other_salon_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Isolation §11.2 : 403 (hors portée) avant d'accéder à la fiche."""
        from coiflink_api.application.customers import CreateCustomer, CustomerCommand

        customer = CreateCustomer(customer_repo, audit_log).execute(
            _OTHER_SALON_ID,
            CustomerCommand(full_name="Autre client"),
            actor_user_id=_MANAGER_ID,
        )

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _customer_url(_OTHER_SALON_ID, customer.id),
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_client_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _customer_url(_SALON_ID, uuid.uuid4()),
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_customer_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Deny-by-default : PUBLIC_ROUTE_PATHS n'inclut aucun chemin customers
# ---------------------------------------------------------------------------


class TestCustomerRoutesNotPublic:
    def test_no_customer_path_in_public_routes(self) -> None:
        """Invariant deny-by-default (ADR-0015) : fiches clients jamais publiques."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "customer" not in path.lower()

    def test_no_notes_path_in_public_routes(self) -> None:
        """La route d'édition de note privée n'est jamais publique (US-4.5 #32)."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "notes" not in path.lower()


# ---------------------------------------------------------------------------
# PUT /salons/{salon_id}/customers/{customer_id}/notes — US-4.5 #32
# ---------------------------------------------------------------------------


def _make_customer_in_repo(
    repo: FakeCustomerRepository,
    salon_id: uuid.UUID = _SALON_ID,
) -> object:
    """Crée une fiche dans le dépôt fake et retourne l'entité Customer."""
    from coiflink_api.application.customers import CreateCustomer, CustomerCommand

    audit = FakeAuditLog()
    return CreateCustomer(repo, audit).execute(
        salon_id, CustomerCommand(full_name="Awa Koné"), actor_user_id=_MANAGER_ID
    )


def _make_client_with_overrides(
    customer_repo: FakeCustomerRepository,
    audit_log: FakeAuditLog,
    *,
    user_id: uuid.UUID = _MANAGER_ID,
    role: str,
    scopes: dict | None = None,
) -> TestClient:
    creds = _creds(user_id, role)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(
        scopes=scopes if scopes is not None else {user_id: frozenset({_SALON_ID})}
    )
    app.dependency_overrides[get_customer_repository] = lambda: customer_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    return TestClient(app)


def _cleanup_overrides() -> None:
    app.dependency_overrides.pop(get_customer_repository, None)
    app.dependency_overrides.pop(get_audit_log, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)


class TestUpdateCustomerNoteApi:
    """Tests API pour `PUT /salons/{salon_id}/customers/{customer_id}/notes` (US-4.5, #32)."""

    def test_200_note_updated(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _make_customer_in_repo(customer_repo)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "Allergie réactif X."},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 200
        assert r.json()["notes"] == "Allergie réactif X."

    def test_200_no_user_id_in_response(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Anti-oracle : `user_id` n'est pas exposé (ADR-0026)."""
        customer = _make_customer_in_repo(customer_repo)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert "user_id" not in r.json()

    def test_200_erase_note_with_null(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """`notes: null` efface la note — `notes = NULL` en base."""
        customer = _make_customer_in_repo(customer_repo)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": None},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 200
        assert r.json()["notes"] is None

    def test_200_privileged_fields_in_body_ignored(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Seule `notes` est prise en compte ; `full_name`/`phone`/`gender`/`salon_id`/`user_id` ignorés."""
        customer = _make_customer_in_repo(customer_repo)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={
                    "notes": "note réelle",
                    "full_name": "Autre Nom",
                    "phone": "+0000000000",
                    "gender": "MALE",
                    "salon_id": str(_OTHER_SALON_ID),
                    "user_id": str(uuid.uuid4()),
                },
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 200
        data = r.json()
        # Note mise à jour, mais le reste de la fiche est inchangé.
        assert data["notes"] == "note réelle"
        assert data["full_name"] == "Awa Koné"
        assert data["salon_id"] == str(_SALON_ID)

    def test_422_note_too_long(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _make_customer_in_repo(customer_repo)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "A" * 2001},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 422

    def test_404_unknown_customer(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, uuid.uuid4()),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 404

    def test_404_customer_from_other_salon(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Isolation §11.2 : fiche d'un autre salon → 404 (après validation de portée)."""
        customer = _make_customer_in_repo(customer_repo, _OTHER_SALON_ID)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 404

    def test_401_no_token(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _make_customer_in_repo(customer_repo)
        client = _make_client_with_overrides(
            customer_repo, audit_log, role=Role.MANAGER.value
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 401

    def test_403_client_role(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _make_customer_in_repo(customer_repo)
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)
        client = _make_client_with_overrides(
            customer_repo,
            audit_log,
            user_id=_CLIENT_ID,
            role=Role.CLIENT.value,
            scopes={},
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 403

    def test_403_hairdresser_role(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _make_customer_in_repo(customer_repo)
        token = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        client = _make_client_with_overrides(
            customer_repo,
            audit_log,
            user_id=_HAIRDRESSER_ID,
            role=Role.HAIRDRESSER.value,
            scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})},
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 403

    def test_403_out_of_scope(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Isolation §11.2 : un gérant ciblant un salon hors périmètre → 403 générique."""
        customer = _make_customer_in_repo(customer_repo)
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        client = _make_client_with_overrides(
            customer_repo,
            audit_log,
            user_id=_OTHER_MANAGER_ID,
            role=Role.MANAGER.value,
            scopes={_OTHER_MANAGER_ID: frozenset({_OTHER_SALON_ID})},
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 403

    def test_403_detail_is_generic(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Le message 403 est constant et ne révèle pas le motif (ADR-0015)."""
        customer = _make_customer_in_repo(customer_repo)
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)
        client = _make_client_with_overrides(
            customer_repo,
            audit_log,
            user_id=_CLIENT_ID,
            role=Role.CLIENT.value,
            scopes={},
        )
        try:
            r = client.put(
                _notes_url(_SALON_ID, customer.id),
                json={"notes": "note"},
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.json()["detail"] == "Accès refusé."
