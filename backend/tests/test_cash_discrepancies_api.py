"""Tests API — `GET /salons/{id}/cash-discrepancies` (US-5.4, #36).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_payment_repository` → `FakePaymentRepository` (avec `discrepancies` pré-chargés) ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 sans filtre : structure de page (`items`/`total`/`limit`/`offset`) ;
- 200 avec filtre `date_from` et `date_to` : sous-ensemble correct ;
- 200 filtre combined (`date_from` + `date_to`) ;
- réponse contient `appointment_id`, `appointment_date`, `start_time`, `client_id`,
  `client_name`, `expected_amount`, `currency` — et **pas** `salon_id` (non exposé) ;
- 422 plage incohérente (`date_from > date_to`) — message neutre (§11.3) ;
- 401 sans jeton / token absent ;
- 403 CLIENT, HAIRDRESSER, MANAGER hors portée — message générique ;
- pagination `limit`/`offset` respectés, `total` cohérent ;
- route absente de `PUBLIC_ROUTE_PATHS` (données financières, jamais publiques).
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
from coiflink_api.domain.discrepancy import CashDiscrepancy
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.payment import DEFAULT_CURRENCY
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

_APPT_CLIENT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

_DATE_OLD = datetime.date(2026, 3, 1)
_DATE_MID = datetime.date(2026, 3, 15)
_DATE_NEW = datetime.date(2026, 3, 31)

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/cash-discrepancies"


def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _make_discrepancy(
    *,
    salon_id: uuid.UUID = _SALON_ID,
    appointment_date: datetime.date = _DATE_MID,
    start_time: datetime.time = datetime.time(10, 0),
    client_name: str | None = None,
    expected_amount: decimal.Decimal = decimal.Decimal("5000.00"),
) -> CashDiscrepancy:
    return CashDiscrepancy(
        appointment_id=uuid.uuid4(),
        salon_id=salon_id,
        appointment_date=appointment_date,
        start_time=start_time,
        client_id=_APPT_CLIENT_ID,
        expected_amount=expected_amount,
        client_name=client_name,
        currency=DEFAULT_CURRENCY,
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


class TestListCashDiscrepancies200NoFilter:
    def test_returns_200(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert r.status_code == 200

    def test_response_has_items_field(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "items" in r.json()

    def test_response_has_total_field(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "total" in r.json()

    def test_response_has_limit_field(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "limit" in r.json()

    def test_response_has_offset_field(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert "offset" in r.json()

    def test_empty_repo_returns_zero_total(
        self, manager_client: TestClient
    ) -> None:
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_seeded_discrepancy_returns_one_item(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy())
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1


# ---------------------------------------------------------------------------
# 200 — schéma de réponse d'un item
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesResponseSchema:
    def test_item_has_appointment_id(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy())
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert "appointment_id" in item

    def test_item_has_appointment_date(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_MID))
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert item["appointment_date"] == "2026-03-15"

    def test_item_has_start_time(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(
            _make_discrepancy(start_time=datetime.time(9, 30))
        )
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert "start_time" in item

    def test_item_has_client_id(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy())
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert "client_id" in item

    def test_item_has_client_name_field(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(client_name="Awa Koné"))
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert "client_name" in item
        assert item["client_name"] == "Awa Koné"

    def test_item_client_name_nullable(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(client_name=None))
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert item["client_name"] is None

    def test_item_has_expected_amount(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(
            _make_discrepancy(expected_amount=decimal.Decimal("7500.00"))
        )
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert item["expected_amount"] == "7500.00"

    def test_item_has_currency(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy())
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert item["currency"] == DEFAULT_CURRENCY

    def test_item_does_not_expose_salon_id(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        """Le `salon_id` n'est pas inclus dans l'item — il est implicite du path."""
        payment_repo._discrepancies.append(_make_discrepancy())
        r = manager_client.get(
            _url(_SALON_ID), headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        item = r.json()["items"][0]
        assert "salon_id" not in item


# ---------------------------------------------------------------------------
# 200 — filtres de dates
# ---------------------------------------------------------------------------


class TestListCashDiscrepancies200WithFilters:
    def test_date_from_excludes_older(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_OLD))
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_NEW))
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_from": "2026-03-20"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1

    def test_date_to_excludes_newer(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_OLD))
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_NEW))
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_to": "2026-03-10"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 1

    def test_date_range_combined(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_OLD))
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_MID))
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_NEW))
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_from": "2026-03-01", "date_to": "2026-03-15"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 2

    def test_no_match_returns_empty(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        payment_repo._discrepancies.append(_make_discrepancy(appointment_date=_DATE_OLD))
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_from": "2026-04-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []


# ---------------------------------------------------------------------------
# 422 — filtre invalide
# ---------------------------------------------------------------------------


class TestListCashDiscrepancies422:
    def test_date_from_gt_date_to_returns_422(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_422_message_neutral(self, manager_client: TestClient) -> None:
        """Message d'erreur neutre : ne reprend jamais la valeur soumise (§11.3)."""
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "2026-03-31" not in detail
        assert "2026-03-01" not in detail

    def test_422_message_contains_invalide(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID),
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422
        assert "invalide" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------


class TestListCashDiscrepancies401:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_url(_SALON_ID))
        assert r.status_code == 401

    def test_401_includes_www_authenticate_header(self, manager_client: TestClient) -> None:
        r = manager_client.get(_url(_SALON_ID))
        assert "WWW-Authenticate" in r.headers


# ---------------------------------------------------------------------------
# 403 — rôle insuffisant / hors portée
# ---------------------------------------------------------------------------


class TestListCashDiscrepancies403:
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
                _url(_SALON_ID),
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
                _url(_SALON_ID),
                headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_manager_out_of_scope_returns_403(self, payment_repo: FakePaymentRepository) -> None:
        """Gérant hors portée du salon → 403 générique (§11.2 — aucun oracle)."""
        client = self._client_with_role_and_scope(
            payment_repo, _MANAGER_ID, Role.MANAGER.value, _OTHER_SALON_ID
        )
        try:
            r = client.get(
                _url(_SALON_ID),
                headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_403_message_is_generic(self, manager_client: TestClient) -> None:
        """Message 403 générique — ne révèle ni la ressource, ni le motif (§11.2)."""
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_CLIENT_ID): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_CLIENT_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            r = manager_client.get(
                _url(_SALON_ID),
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


class TestListCashDiscrepanciesPagination:
    def test_limit_param_respected(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        for i in range(10):
            payment_repo._discrepancies.append(
                _make_discrepancy(appointment_date=datetime.date(2026, 1, i + 1))
            )
        r = manager_client.get(
            _url(_SALON_ID),
            params={"limit": 3},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["limit"] == 3
        assert len(data["items"]) == 3

    def test_offset_param_reflected(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _url(_SALON_ID),
            params={"offset": 5},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["offset"] == 5

    def test_total_reflects_all_under_filter(
        self, manager_client: TestClient, payment_repo: FakePaymentRepository
    ) -> None:
        for i in range(7):
            payment_repo._discrepancies.append(
                _make_discrepancy(appointment_date=datetime.date(2026, 1, i + 1))
            )
        r = manager_client.get(
            _url(_SALON_ID),
            params={"limit": 3, "offset": 0},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 7
        assert len(data["items"]) == 3


# ---------------------------------------------------------------------------
# Sécurité — route jamais publique
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesPublicRoutes:
    def test_cash_discrepancies_not_in_public_route_paths(self) -> None:
        """Données financières : `cash-discrepancies` ne doit jamais être public."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "cash-discrepancies" not in path, (
                f"Route d'écarts de caisse trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )
