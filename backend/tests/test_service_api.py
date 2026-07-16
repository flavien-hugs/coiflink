"""Tests API — router `/salons/{id}/services` (adapter entrant, US-2.3, #17).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_service_repository` → `FakeServiceRepository` (aucune base) ;
- `get_audit_log` → `FakeAuditLog` (aucune base) ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- matrice RBAC : MANAGER→201/200/204, HAIRDRESSER (avec portée)→200 en lecture / 403 en mutation,
  CLIENT→403, ADMIN→403, non authentifié→401 ;
- isolation : MANAGER ciblant le salon d'un autre → 403 générique (pas 404) ;
- validation : corps sans `price` ou `duration_minutes` → 422 ; prix négatif → 422 ;
- 404 pour prestation inconnue (portée validée) ;
- réponse : champs attendus (`is_active`, `salon_id`, etc.), aucun secret ;
- journalisation : après `PUT`, une entrée `SERVICE_UPDATED` est enregistrée ;
- `unprotected_routes(app)` reste vide (deny-by-default).
"""

from __future__ import annotations

import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.inbound.services import get_audit_log, get_service_repository
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
    FakeServiceRepository,
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
    "name": "Coupe homme",
    "price": "5000.00",
    "duration_minutes": 30,
    "description": "Coupe aux ciseaux.",
    "category": "Coupe",
}


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


def _services_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/services"


def _service_url(salon_id: uuid.UUID, service_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/services/{service_id}"


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
def service_repo() -> FakeServiceRepository:
    return FakeServiceRepository()


@pytest.fixture()
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture()
def manager_client(
    service_repo: FakeServiceRepository,
    audit_log: FakeAuditLog,
) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié et salon dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_service_repository] = lambda: service_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_service_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def manager_client_with_service(
    service_repo: FakeServiceRepository,
    audit_log: FakeAuditLog,
) -> Generator[tuple[TestClient, uuid.UUID], None, None]:
    """MANAGER dont le repo contient déjà une prestation pré-créée dans _SALON_ID."""
    from coiflink_api.application.services import CreateService, ServiceCommand

    service = CreateService(service_repo, audit_log).execute(
        _SALON_ID,
        ServiceCommand(
            name="Coupe homme",
            price=decimal.Decimal("5000.00"),
            duration_minutes=30,
        ),
        actor_user_id=_MANAGER_ID,
    )
    audit_log.recorded.clear()

    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_service_repository] = lambda: service_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app), service.id
    finally:
        app.dependency_overrides.pop(get_service_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/services — RBAC
# ---------------------------------------------------------------------------


class TestCreateServiceRbac:
    def test_manager_with_scope_gets_201(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(_services_url(_SALON_ID), json=_VALID_BODY)
        assert r.status_code == 401

    def test_client_role_returns_403(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _services_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_hairdresser_role_returns_403_on_create(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(
            scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})}
        )
        token = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _services_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_admin_role_returns_403(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_ADMIN_ID, Role.ADMIN.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_ADMIN_ID, Role.ADMIN.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _services_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_403_detail_is_generic(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _services_url(_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/services — RBAC
# ---------------------------------------------------------------------------


class TestListServicesRbac:
    def test_manager_gets_200(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _services_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_services_url(_SALON_ID))
        assert r.status_code == 401

    def test_hairdresser_with_scope_gets_200(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(
            scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})}
        )
        token = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _services_url(_SALON_ID),
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 200

    def test_client_returns_403(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository()
        token = make_access_token(_CLIENT_ID, Role.CLIENT.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _services_url(_SALON_ID),
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Isolation (portée salon)
# ---------------------------------------------------------------------------


class TestServiceSalonIsolation:
    def test_manager_accessing_other_salon_gets_403_not_404(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """MANAGER ciblant le salon d'un autre → 403 générique, pas 404."""
        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        # Manager has scope for _SALON_ID but NOT _OTHER_SALON_ID
        scope_repo = FakeSalonScopeRepository(
            scopes={_MANAGER_ID: frozenset({_SALON_ID})}
        )

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _services_url(_OTHER_SALON_ID),
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403

    def test_get_service_from_other_salon_returns_404(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Service_id d'un autre salon (portée validée) → 404 opaque."""
        from coiflink_api.application.services import CreateService, ServiceCommand

        # Create a service in _OTHER_SALON_ID (not in manager's scope during creation)
        other_service = CreateService(service_repo, audit_log).execute(
            _OTHER_SALON_ID,
            ServiceCommand(name="Soin", price=decimal.Decimal("2000"), duration_minutes=20),
            actor_user_id=_OTHER_MANAGER_ID,
        )
        audit_log.recorded.clear()

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        # Manager has scope for _SALON_ID
        scope_repo = FakeSalonScopeRepository(
            scopes={_MANAGER_ID: frozenset({_SALON_ID})}
        )

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                # Use _SALON_ID as path (scope valid) but service belongs to _OTHER_SALON_ID
                r = c.get(
                    _service_url(_SALON_ID, other_service.id),
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/services — validation
# ---------------------------------------------------------------------------


class TestCreateServiceValidation:
    def test_missing_price_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "price"}
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_missing_duration_returns_422(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_BODY.items() if k != "duration_minutes"}
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_negative_price_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json={**_VALID_BODY, "price": "-1"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_zero_duration_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json={**_VALID_BODY, "duration_minutes": 0},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_empty_name_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json={**_VALID_BODY, "name": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_optional_fields_absent_accepted(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json={"name": "Coupe", "price": "5000.00", "duration_minutes": 30},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/services — réponse
# ---------------------------------------------------------------------------


class TestCreateServiceResponse:
    def test_response_contains_id(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "id" in r.json()

    def test_response_is_active_true(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["is_active"] is True

    def test_response_salon_id_matches_path(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_response_does_not_contain_raw_token(
        self, manager_client: TestClient
    ) -> None:
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert _MANAGER_TOKEN not in r.text

    def test_body_salon_id_ignored(self, manager_client: TestClient) -> None:
        """Champ `salon_id` dans le corps est ignoré (extra='ignore')."""
        body = {**_VALID_BODY, "salon_id": str(_OTHER_SALON_ID)}
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_body_is_active_ignored(self, manager_client: TestClient) -> None:
        """Champ `is_active=false` dans le corps est ignoré — la création force `true`."""
        body = {**_VALID_BODY, "is_active": False}
        r = manager_client.post(
            _services_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["is_active"] is True

    def test_audit_entry_recorded_after_create(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
        manager_client: TestClient,
    ) -> None:
        manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert len(audit_log.recorded) == 1
        assert audit_log.recorded[0].action == "SERVICE_CREATED"


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/services — liste
# ---------------------------------------------------------------------------


class TestListServices:
    def test_empty_list_returned_for_empty_salon(
        self, manager_client: TestClient
    ) -> None:
        r = manager_client.get(
            _services_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_list_contains_created_service(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
        manager_client: TestClient,
    ) -> None:
        manager_client.post(
            _services_url(_SALON_ID),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        r = manager_client.get(
            _services_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/services/{service_id} — consultation
# ---------------------------------------------------------------------------


class TestGetService:
    def test_unknown_service_id_returns_404(
        self, manager_client: TestClient
    ) -> None:
        r = manager_client.get(
            _service_url(_SALON_ID, uuid.uuid4()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_known_service_returns_200(
        self,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        r = client.get(
            _service_url(_SALON_ID, service_id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json()["id"] == str(service_id)


# ---------------------------------------------------------------------------
# PUT /salons/{salon_id}/services/{service_id} — modification journalisée
# ---------------------------------------------------------------------------


class TestUpdateService:
    def test_manager_gets_200(
        self,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        r = client.put(
            _service_url(_SALON_ID, service_id),
            json={**_VALID_BODY, "name": "Coupe femme", "price": "6000.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_no_token_returns_401(
        self,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        r = client.put(
            _service_url(_SALON_ID, service_id),
            json=_VALID_BODY,
        )
        assert r.status_code == 401

    def test_unknown_service_returns_404(self, manager_client: TestClient) -> None:
        r = manager_client.put(
            _service_url(_SALON_ID, uuid.uuid4()),
            json=_VALID_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_invalid_price_returns_422(
        self,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        r = client.put(
            _service_url(_SALON_ID, service_id),
            json={**_VALID_BODY, "price": "-10"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_audit_entry_recorded_with_changed_fields(
        self,
        audit_log: FakeAuditLog,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        client.put(
            _service_url(_SALON_ID, service_id),
            json={**_VALID_BODY, "name": "Coupe femme", "price": "6000.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert len(audit_log.recorded) == 1
        entry = audit_log.recorded[0]
        assert entry.action == "SERVICE_UPDATED"
        assert "name" in entry.metadata["changed"]
        assert "price" in entry.metadata["changed"]


# ---------------------------------------------------------------------------
# DELETE /salons/{salon_id}/services/{service_id} — désactivation
# ---------------------------------------------------------------------------


class TestDeleteService:
    def test_manager_gets_204(
        self,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        r = client.delete(
            _service_url(_SALON_ID, service_id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 204

    def test_no_token_returns_401(
        self,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        r = client.delete(_service_url(_SALON_ID, service_id))
        assert r.status_code == 401

    def test_unknown_service_returns_404(self, manager_client: TestClient) -> None:
        r = manager_client.delete(
            _service_url(_SALON_ID, uuid.uuid4()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_service_deactivated_after_delete(
        self,
        service_repo: FakeServiceRepository,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        client.delete(
            _service_url(_SALON_ID, service_id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        service = service_repo.find_by_id(_SALON_ID, service_id)
        assert service is not None
        assert service.is_active is False

    def test_audit_entry_recorded_on_deactivation(
        self,
        audit_log: FakeAuditLog,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, service_id = manager_client_with_service
        client.delete(
            _service_url(_SALON_ID, service_id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert len(audit_log.recorded) == 1
        assert audit_log.recorded[0].action == "SERVICE_DEACTIVATED"

    def test_hairdresser_returns_403(
        self,
        service_repo: FakeServiceRepository,
        audit_log: FakeAuditLog,
        manager_client_with_service: tuple[TestClient, uuid.UUID],
    ) -> None:
        _, service_id = manager_client_with_service

        creds = _creds(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(
            scopes={_HAIRDRESSER_ID: frozenset({_SALON_ID})}
        )
        token = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

        app.dependency_overrides[get_service_repository] = lambda: service_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.delete(
                    _service_url(_SALON_ID, service_id),
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Deny-by-default (invariant RBAC)
# ---------------------------------------------------------------------------


class TestDenyByDefault:
    def test_service_routes_not_in_public_paths(self) -> None:
        """Aucune route de prestations n'est publique (deny-by-default, ADR-0015)."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "services" not in path
