"""Tests API — `GET /salons/{id}/payments` (US-5.2, #35).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_payment_repository` → `FakePaymentRepository` ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 sans filtre : page `items`/`total`/`limit`/`offset` ;
- 200 avec chaque filtre : `payment_method`, `amount_min`/`amount_max`, `client_id`,
  `date_from`/`date_to` — sous-ensemble correct ;
- 200 avec combinaison de filtres ;
- 422 mode hors enum / plage incohérente (`date_from > date_to`, `amount_min >
  amount_max`) / montant négatif — message neutre sans reprise de la valeur (§11.3) ;
- 401 sans jeton ; 403 CLIENT, HAIRDRESSER, hors portée — message générique ;
- pagination `limit`/`offset` respectés, `total` cohérent ;
- `client_name` présent dans `TransactionResponse` ;
- aucune route de type `GET /salons/{id}/payments` dans `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.payments import get_payment_repository
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import PaymentStatus, Role, UserStatus
from coiflink_api.domain.payment import Payment
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakePaymentRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_CLIENT_ID = uuid.UUID("11111111-0000-0000-0000-000000000011")
_HAIRDRESSER_ID = uuid.UUID("22222222-0000-0000-0000-000000000022")

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_SERVICE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_LINKED_CLIENT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

_CREATED_AT = datetime.datetime(2026, 3, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payments_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/payments"


def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _make_payment(
    *,
    payment_id: uuid.UUID | None = None,
    salon_id: uuid.UUID = _SALON_ID,
    amount: decimal.Decimal = decimal.Decimal("5000.00"),
    payment_method: str = "CASH",
    client_id: uuid.UUID | None = None,
    status: str = PaymentStatus.VALIDATED.value,
    created_at: datetime.datetime = _CREATED_AT,
) -> Payment:
    return Payment(
        id=payment_id or uuid.uuid4(),
        salon_id=salon_id,
        amount=amount,
        currency="XOF",
        payment_method=payment_method,
        status=status,
        recorded_by=_MANAGER_ID,
        service_id=_SERVICE_ID,
        queue_ticket_id=None,
        client_id=client_id,
        reference=None,
        mobile_money_phone=None,
        created_at=created_at,
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
def payment_repo() -> FakePaymentRepository:
    return FakePaymentRepository()


@pytest.fixture()
def manager_client(payment_repo: FakePaymentRepository) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié et salon dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_payment_repository] = lambda: payment_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_payment_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# 200 — sans filtre
# ---------------------------------------------------------------------------


class TestListTransactions200NoFilter:
    def test_returns_200(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_response_has_items_field(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "items" in data

    def test_response_has_total_field(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "total" in data

    def test_response_has_limit_field(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "limit" in data

    def test_response_has_offset_field(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert "offset" in data

    def test_empty_repo_total_is_zero(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total"] == 0
        assert r.json()["items"] == []

    def test_seeded_payment_returns_one_item(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        payment_repo._payments[uuid.uuid4()] = _make_payment()
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_item_has_client_name_field(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        p = _make_payment()
        payment_repo._payments[p.id] = p
        r = manager_client.get(
            _payments_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        item = r.json()["items"][0]
        assert "client_name" in item


# ---------------------------------------------------------------------------
# 200 — filtres individuels
# ---------------------------------------------------------------------------


class TestListTransactions200WithFilters:
    def test_filter_payment_method_cash(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        cash = _make_payment(payment_method="CASH")
        mobile = _make_payment(payment_method="MOBILE_MONEY_MANUAL")
        payment_repo._payments[cash.id] = cash
        payment_repo._payments[mobile.id] = mobile

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"payment_method": "CASH"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["payment_method"] == "CASH"

    def test_filter_amount_min(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        low = _make_payment(amount=decimal.Decimal("1000.00"))
        high = _make_payment(amount=decimal.Decimal("10000.00"))
        payment_repo._payments[low.id] = low
        payment_repo._payments[high.id] = high

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"amount_min": "5000.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["amount"] == "10000.00"

    def test_filter_amount_max(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        low = _make_payment(amount=decimal.Decimal("1000.00"))
        high = _make_payment(amount=decimal.Decimal("10000.00"))
        payment_repo._payments[low.id] = low
        payment_repo._payments[high.id] = high

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"amount_max": "5000.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["amount"] == "1000.00"

    def test_filter_client_id(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        pa = _make_payment(client_id=_LINKED_CLIENT_ID)
        pb = _make_payment(client_id=None)
        payment_repo._payments[pa.id] = pa
        payment_repo._payments[pb.id] = pb

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"client_id": str(_LINKED_CLIENT_ID)},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["client_id"] == str(_LINKED_CLIENT_ID)

    def test_filter_date_from(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        old = _make_payment(
            created_at=datetime.datetime(2026, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)
        )
        recent = _make_payment(
            created_at=datetime.datetime(2026, 3, 20, 8, 0, 0, tzinfo=datetime.timezone.utc)
        )
        payment_repo._payments[old.id] = old
        payment_repo._payments[recent.id] = recent

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"date_from": "2026-03-10"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1

    def test_filter_date_to(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        old = _make_payment(
            created_at=datetime.datetime(2026, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)
        )
        recent = _make_payment(
            created_at=datetime.datetime(2026, 3, 20, 8, 0, 0, tzinfo=datetime.timezone.utc)
        )
        payment_repo._payments[old.id] = old
        payment_repo._payments[recent.id] = recent

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"date_to": "2026-03-10"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1

    def test_filter_q_matches_client_name(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        pa = _make_payment(client_id=_LINKED_CLIENT_ID)
        pb = _make_payment(client_id=None)
        payment_repo._payments[pa.id] = pa
        payment_repo._payments[pb.id] = pb
        payment_repo._client_names[_LINKED_CLIENT_ID] = "Awa Koné"

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"q": "koné"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["client_id"] == str(_LINKED_CLIENT_ID)

    def test_filter_q_no_match_returns_empty(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        p = _make_payment(client_id=_LINKED_CLIENT_ID)
        payment_repo._payments[p.id] = p
        payment_repo._client_names[_LINKED_CLIENT_ID] = "Awa Koné"

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"q": "Ibrahim"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# 200 — combinaison de filtres
# ---------------------------------------------------------------------------


class TestListTransactions200CombinedFilters:
    def test_method_and_amount_combined(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        cash_low = _make_payment(payment_method="CASH", amount=decimal.Decimal("1000.00"))
        mobile_high = _make_payment(payment_method="MOBILE_MONEY_MANUAL", amount=decimal.Decimal("5000.00"))
        payment_repo._payments[cash_low.id] = cash_low
        payment_repo._payments[mobile_high.id] = mobile_high

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"payment_method": "MOBILE_MONEY_MANUAL", "amount_min": "2000.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["payment_method"] == "MOBILE_MONEY_MANUAL"


# ---------------------------------------------------------------------------
# 422 — filtres invalides
# ---------------------------------------------------------------------------


class TestListTransactions422:
    def test_unknown_payment_method(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"payment_method": "WIRE_TRANSFER"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_date_from_gt_date_to(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_amount_min_gt_amount_max(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"amount_min": "5000.00", "amount_max": "1000.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_negative_amount_min(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"amount_min": "-100.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_422_message_does_not_repeat_invalid_value(self, manager_client: TestClient) -> None:
        """Message d'erreur neutre : ne reprend jamais la valeur soumise (§11.3)."""
        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"payment_method": "INVALID_SECRET_METHOD"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "INVALID_SECRET_METHOD" not in detail


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------


class TestListTransactions401:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_payments_url(_SALON_ID))
        assert r.status_code == 401

    def test_401_includes_www_authenticate_header(self, manager_client: TestClient) -> None:
        r = manager_client.get(_payments_url(_SALON_ID))
        assert "WWW-Authenticate" in r.headers


# ---------------------------------------------------------------------------
# 403 — rôle insuffisant / hors portée
# ---------------------------------------------------------------------------


class TestListTransactions403:
    def _client_with_role_and_scope(
        self,
        payment_repo: FakePaymentRepository,
        user_id: uuid.UUID,
        role: str,
        scope_salon_id: uuid.UUID | None,
    ) -> TestClient:
        creds = _creds(user_id, role)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(user_id): creds})
        scopes = {user_id: frozenset({scope_salon_id})} if scope_salon_id else {}
        scope_repo = FakeSalonScopeRepository(scopes=scopes)

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        return TestClient(app, raise_server_exceptions=False)

    def test_client_role_returns_403(self, payment_repo: FakePaymentRepository) -> None:
        client = self._client_with_role_and_scope(
            payment_repo, _CLIENT_ID, Role.CLIENT.value, _SALON_ID
        )
        try:
            r = client.get(
                _payments_url(_SALON_ID),
                headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_hairdresser_role_returns_403(self, payment_repo: FakePaymentRepository) -> None:
        client = self._client_with_role_and_scope(
            payment_repo, _HAIRDRESSER_ID, Role.HAIRDRESSER.value, _SALON_ID
        )
        try:
            r = client.get(
                _payments_url(_SALON_ID),
                headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_manager_out_of_scope_returns_403(self, payment_repo: FakePaymentRepository) -> None:
        """Gérant hors portée du salon → 403 générique (§11.2)."""
        client = self._client_with_role_and_scope(
            payment_repo, _MANAGER_ID, Role.MANAGER.value, _OTHER_SALON_ID
        )
        try:
            r = client.get(
                _payments_url(_SALON_ID),
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_403_message_is_generic(self, manager_client: TestClient) -> None:
        """Message d'erreur 403 générique — ne révèle pas la ressource ni le motif."""
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_CLIENT_ID): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_CLIENT_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            r = manager_client.get(
                _payments_url(_SALON_ID),
                headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
            )
            assert r.status_code == 403
            assert r.json()["detail"] == "Accès refusé."
        finally:
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestListTransactionsPagination:
    def test_limit_param_respected(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        for _ in range(10):
            p = _make_payment()
            payment_repo._payments[p.id] = p

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"limit": 3},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["limit"] == 3
        assert len(data["items"]) == 3

    def test_offset_param_reflected(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"offset": 5},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["offset"] == 5

    def test_total_reflects_all_under_filter(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        for _ in range(7):
            p = _make_payment()
            payment_repo._payments[p.id] = p

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"limit": 3, "offset": 0},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 7
        assert len(data["items"]) == 3

    def test_limit_exceeds_items_returns_all(self, manager_client: TestClient, payment_repo: FakePaymentRepository) -> None:
        p = _make_payment()
        payment_repo._payments[p.id] = p

        r = manager_client.get(
            _payments_url(_SALON_ID),
            params={"limit": 50},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1


# ---------------------------------------------------------------------------
# Sécurité — PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestListTransactionsPublicRoutes:
    def test_payments_get_not_in_public_route_paths(self) -> None:
        """GET /salons/{id}/payments : données financières, jamais publiques."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "/payments" not in path, (
                f"Route paiement trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )
