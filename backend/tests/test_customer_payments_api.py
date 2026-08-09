"""Tests API — `GET /salons/{id}/customers/{id}/payments` (fiche client).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_customer_repository` → `FakeCustomerRepository` pré-chargé ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 fiche walk-in → `items: []` ;
- 200 avec paiements : corps complet (montant, devise, statut) ;
- tous les statuts (`PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED`) sont renvoyés ;
- `user_id`/`client_id`/`recorded_by`/`reference` absents de la réponse (anti-oracle ADR-0026) ;
- 401 sans jeton ; 403 CLIENT/HAIRDRESSER/ADMIN/hors-portée (message générique) ;
- 404 fiche inconnue dans le salon (message **neutre**) ;
- La route ne figure pas dans `PUBLIC_ROUTE_PATHS` (deny-by-default ADR-0015).
"""

from __future__ import annotations

import datetime
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
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.visit import CustomerPayment
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

_PAYMENT_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
_PAYMENT_CREATED_AT = datetime.datetime(2026, 7, 20, 9, 30, tzinfo=datetime.timezone.utc)


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


def _payments_url(salon_id: uuid.UUID, customer_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/customers/{customer_id}/payments"


def _make_payment(
    *, status: str = "VALIDATED", amount: str = "5000.00"
) -> CustomerPayment:
    return CustomerPayment(
        payment_id=_PAYMENT_ID,
        created_at=_PAYMENT_CREATED_AT,
        amount=decimal.Decimal(amount),
        currency="XOF",
        status=status,
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
# 200 — fiche walk-in (sans paiement)
# ---------------------------------------------------------------------------


class TestPaymentsWalkIn:
    def test_walk_in_returns_200(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_walk_in_items_is_empty_list(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["items"] == []


# ---------------------------------------------------------------------------
# 200 — avec paiements
# ---------------------------------------------------------------------------


class TestPaymentsWithPayments:
    def test_returns_200_with_payment(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_items_contains_payment(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert len(r.json()["items"]) == 1

    def test_payment_amount_correct(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(amount="7500.00"),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        amount = r.json()["items"][0]["amount"]
        assert decimal.Decimal(amount) == decimal.Decimal("7500.00")

    def test_payment_currency_is_xof(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["items"][0]["currency"] == "XOF"

    @pytest.mark.parametrize("status", ["PENDING", "VALIDATED", "CANCELLED", "ADJUSTED"])
    def test_payment_status_reflected(
        self,
        manager_client: TestClient,
        customer_repo: FakeCustomerRepository,
        status: str,
    ) -> None:
        """Tous les statuts sont renvoyés — c'est justement l'objet de la colonne."""
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(status=status),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["items"][0]["status"] == status

    def test_customer_id_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["customer_id"] == str(customer.id)


# ---------------------------------------------------------------------------
# Anti-oracle : user_id / client_id / recorded_by / reference absents
# ---------------------------------------------------------------------------


class TestPaymentsAntiOracle:
    def test_user_id_not_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """ADR-0026 : `user_id` ne quitte jamais la couche de persistance."""
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        body = r.json()
        assert "user_id" not in body
        for item in body.get("items", []):
            assert "user_id" not in item
            assert "client_id" not in item
            assert "recorded_by" not in item
            assert "reference" not in item

    def test_client_id_not_in_response(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        customer_repo.set_payments(customer.id, (_make_payment(),))
        r = manager_client.get(
            _payments_url(_SALON_ID, customer.id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "client_id" not in r.json()


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------


class TestPaymentsUnauthorized:
    def test_no_token_returns_401(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        customer = _create_customer(customer_repo)
        r = manager_client.get(_payments_url(_SALON_ID, customer.id))
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — RBAC
# ---------------------------------------------------------------------------


class TestPaymentsForbidden:
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
                _payments_url(_SALON_ID, customer.id),
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
                _payments_url(_SALON_ID, customer.id),
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
                _payments_url(_SALON_ID, customer.id),
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
                _payments_url(_SALON_ID, customer.id),
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
                _payments_url(_SALON_ID, customer.id),
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            self._teardown()
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# 404 — fiche inconnue dans le salon
# ---------------------------------------------------------------------------


class TestPaymentsNotFound:
    def test_unknown_customer_returns_404(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID, uuid.uuid4()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_404_message_does_not_contain_customer_id(
        self, manager_client: TestClient, customer_repo: FakeCustomerRepository
    ) -> None:
        """Message neutre (§11.3) : aucun identifiant dans l'erreur."""
        mystery_id = uuid.uuid4()
        r = manager_client.get(
            _payments_url(_SALON_ID, mystery_id),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        detail = r.json().get("detail", "")
        assert str(mystery_id) not in detail


# ---------------------------------------------------------------------------
# Deny-by-default : la route paiements ne figure pas dans PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestPaymentsRouteNotPublic:
    def test_no_customer_payments_path_in_public_routes(self) -> None:
        """Invariant deny-by-default (ADR-0015) : l'historique de paiements est toujours protégé."""
        combined = " ".join(PUBLIC_ROUTE_PATHS).lower()
        assert "customers" not in combined or "payments" not in combined
