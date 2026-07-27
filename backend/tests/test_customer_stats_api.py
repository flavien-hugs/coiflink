"""Tests API — `GET /salons/{id}/customers/{id}/stats` (US-4.3, #31).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_customer_repository` → `FakeCustomerRepository` pré-chargé ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 fiche walk-in → `services: []`, `total_visits: 0`, `total_services: 0` ;
- 200 avec visites : corps complet (services, count, total_amount, totaux, currency) ;
- `user_id`/`client_id` absents de la réponse (anti-oracle ADR-0026) ;
- `currency` == "XOF" (devise §9.6) ;
- 401 sans jeton ; 403 CLIENT/HAIRDRESSER/ADMIN/hors-portée (message générique) ;
- 404 fiche inconnue dans le salon (message **neutre**) ;
- La route ne figure pas dans `PUBLIC_ROUTE_PATHS` (deny-by-default ADR-0015).
"""

from __future__ import annotations

import decimal
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
from coiflink_api.application.customers import CreateCustomer, CustomerCommand
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import AppointmentStatus, Role, UserStatus
from coiflink_api.domain.visit import CustomerVisit, VisitService
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
_HAIRDRESSER_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_CLIENT_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")
_ADMIN_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_SERVICE_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_APT_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")


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


def _stats_url(salon_id: uuid.UUID, customer_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/customers/{customer_id}/stats"


def _make_completed_visit() -> CustomerVisit:
    import datetime

    svc = VisitService(
        service_id=_SERVICE_ID,
        name="Coupe homme",
        price_at_booking=decimal.Decimal("5000.00"),
    )
    return CustomerVisit(
        appointment_id=_APT_ID,
        date=datetime.date(2026, 7, 20),
        start_time=datetime.time(9, 0, 0),
        end_time=datetime.time(10, 0, 0),
        status=AppointmentStatus.COMPLETED.value,
        services=(svc,),
        total_amount=decimal.Decimal("5000.00"),
    )


def _create_customer(
    repo: FakeCustomerRepository,
    salon_id: uuid.UUID = _SALON_ID,
    name: str = "Awa Koné",
) -> object:
    audit = FakeAuditLog()
    return CreateCustomer(repo, audit).execute(
        salon_id, CustomerCommand(full_name=name), actor_user_id=_MANAGER_ID
    )


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
    """TestClient MANAGER authentifié, salon dans sa portée."""
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
# 200 — fiche walk-in (sans visite COMPLETED)
# ---------------------------------------------------------------------------


class TestStatsWalkIn:
    def test_walk_in_returns_200(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_walk_in_services_is_empty_list(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["services"] == []

    def test_walk_in_total_visits_is_zero(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total_visits"] == 0

    def test_walk_in_total_services_is_zero(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total_services"] == 0

    def test_walk_in_currency_is_xof(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["currency"] == "XOF"

    def test_walk_in_customer_id_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["customer_id"] == str(customer.id)


# ---------------------------------------------------------------------------
# 200 — avec visites COMPLETED
# ---------------------------------------------------------------------------


class TestStatsWithVisits:
    def test_returns_200_with_visit(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_services_list_contains_entry(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert len(r.json()["services"]) == 1

    def test_service_id_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["services"][0]["service_id"] == str(_SERVICE_ID)

    def test_service_name_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["services"][0]["name"] == "Coupe homme"

    def test_service_count_is_one(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["services"][0]["count"] == 1

    def test_service_total_amount_correct(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        total_amount = r.json()["services"][0]["total_amount"]
        assert decimal.Decimal(total_amount) == decimal.Decimal("5000.00")

    def test_total_visits_is_one(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total_visits"] == 1

    def test_total_services_is_one(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total_services"] == 1

    def test_customer_id_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["customer_id"] == str(customer.id)

    def test_total_amount_is_decimal_string(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """Montant sérialisé en chaîne décimale, jamais en flottant."""
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        total_amount_raw = r.json()["services"][0]["total_amount"]
        assert isinstance(total_amount_raw, str)


# ---------------------------------------------------------------------------
# Anti-oracle : user_id / client_id absents de la réponse
# ---------------------------------------------------------------------------


class TestStatsAntiOracle:
    def test_user_id_not_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """ADR-0026 : `user_id` ne quitte jamais la couche de persistance."""
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        body = r.json()
        assert "user_id" not in body
        for item in body.get("services", []):
            assert "user_id" not in item
            assert "client_id" not in item

    def test_client_id_not_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_visits(customer.id, (_make_completed_visit(),))
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "client_id" not in r.json()

    def test_user_id_not_in_walk_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _stats_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "user_id" not in r.json()
        assert "client_id" not in r.json()


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------


class TestStatsUnauthorized:
    def test_no_token_returns_401(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(_stats_url(_SALON_ID, customer.id))
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — RBAC
# ---------------------------------------------------------------------------


class TestStatsForbidden:
    def _setup_overrides(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
        user_id: uuid.UUID,
        role: str,
        scope_ids: frozenset[uuid.UUID] | None = None,
    ) -> tuple[TestClient, str]:
        creds = _creds(user_id, role)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(
            scopes={user_id: scope_ids} if scope_ids else {}
        )
        token = make_access_token(user_id, role)

        app.dependency_overrides[get_customer_repository] = lambda: customer_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        return TestClient(app), token

    def _teardown(self) -> None:
        app.dependency_overrides.pop(get_customer_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)

    def test_client_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _create_customer(customer_repo)
        c, token = self._setup_overrides(customer_repo, audit_log, _CLIENT_ID, Role.CLIENT.value)
        try:
            r = c.get(
                _stats_url(_SALON_ID, customer.id),
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            self._teardown()
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _create_customer(customer_repo)
        c, token = self._setup_overrides(
            customer_repo, audit_log, _HAIRDRESSER_ID, Role.HAIRDRESSER.value,
            frozenset({_SALON_ID}),
        )
        try:
            r = c.get(
                _stats_url(_SALON_ID, customer.id),
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            self._teardown()
        assert r.status_code == 403

    def test_admin_role_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        customer = _create_customer(customer_repo)
        c, token = self._setup_overrides(customer_repo, audit_log, _ADMIN_ID, Role.ADMIN.value)
        try:
            r = c.get(
                _stats_url(_SALON_ID, customer.id),
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            self._teardown()
        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Isolation §11.2 : gérant ciblant un salon hors de sa portée → 403."""
        customer = _create_customer(customer_repo)
        c, token = self._setup_overrides(
            customer_repo, audit_log, _OTHER_MANAGER_ID, Role.MANAGER.value,
            frozenset({_OTHER_SALON_ID}),
        )
        try:
            r = c.get(
                _stats_url(_SALON_ID, customer.id),
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            self._teardown()
        assert r.status_code == 403

    def test_403_detail_is_generic(
        self,
        customer_repo: FakeCustomerRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Le message 403 est constant et ne révèle pas le motif (ADR-0015)."""
        customer = _create_customer(customer_repo)
        c, token = self._setup_overrides(customer_repo, audit_log, _CLIENT_ID, Role.CLIENT.value)
        try:
            r = c.get(
                _stats_url(_SALON_ID, customer.id),
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            self._teardown()
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# 404 — fiche inconnue dans le salon
# ---------------------------------------------------------------------------


class TestStatsNotFound:
    def test_unknown_customer_returns_404(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _stats_url(_SALON_ID, uuid.uuid4()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_404_message_does_not_contain_customer_id(
        self, manager_client: TestClient
    ) -> None:
        """Message neutre (§11.3) : aucun identifiant dans l'erreur."""
        mystery_id = uuid.uuid4()
        r = manager_client.get(
            _stats_url(_SALON_ID, mystery_id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        detail = r.json().get("detail", "")
        assert str(mystery_id) not in detail


# ---------------------------------------------------------------------------
# Deny-by-default : la route stats ne figure pas dans PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestStatsRouteNotPublic:
    def test_stats_path_not_in_public_routes(self) -> None:
        """Invariant deny-by-default (ADR-0015) : les stats client sont toujours protégées."""
        for path in PUBLIC_ROUTE_PATHS:
            assert not (
                "customers" in path.lower() and "stats" in path.lower()
            ), f"Route stats trouvée dans PUBLIC_ROUTE_PATHS : {path}"

    def test_no_stats_suffix_in_public_routes(self) -> None:
        combined = " ".join(PUBLIC_ROUTE_PATHS).lower()
        assert "stats" not in combined or "customers" not in combined
