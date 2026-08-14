"""Tests API — Dashboard Manager · activité du salon (stats.py, #148).

Six routes sous `/salons/{salon_id}/dashboard/` :
  - GET dashboard/kpis
  - GET dashboard/revenue-series
  - GET dashboard/attendance-series
  - GET dashboard/in-progress
  - GET dashboard/activity
  - GET dashboard/alerts

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_queue_ticket_repository` → `FakeDashboardQueueTicketRepo` ;
- `get_cash_journal_repository` → `FakeDashboardCashRepo` ;
- `get_payment_repository`      → `FakeDashboardPaymentRepo` ;
- `get_user_repository`         → `FakeAuthUserRepository` (clés de rôle) ;
- `get_access_policy`           → `AccessPolicy(FakeSalonScopeRepository(...))`.

Rebranché sur `queue_tickets` (pivot walk-in exclusif) : les notifications ont
disparu, `dashboard/activity` ne porte plus que des évènements paiement.

Couvre :
- 200 : structure attendue de chaque route (champs requis présents) ;
- **non-PII (§11.3)** : réponses sans `client_id`, `phone`, `email`, `reference`,
  `recorded_by` (vérifié sur chaque format de réponse) ;
- **filtre de période** : today/week/month → 200 ; custom avec bornes → 200 ;
  custom sans bornes → 422 ; genre inconnu → 422 ; date_to < date_from → 422 ;
- **limit** de dashboard/activity : valeur hors [1, 100] → 422 ;
- routes absentes de `PUBLIC_ROUTE_PATHS` ;
- 401 : jeton absent ou invalide ;
- 403 : CLIENT, HAIRDRESSER, ADMIN (sans STATS_READ_SALON) ;
        gérant hors portée → 403 générique (aucun oracle d'existence) ;
- isolation salon_id : les routes renvoient 403 sur un salon hors portée.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator, Mapping

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.queue_tickets import get_queue_ticket_repository
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.inbound.stats import (
    get_cash_journal_repository,
    get_payment_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.dashboard import InProgressService
from coiflink_api.domain.discrepancy import DiscrepancyFilter
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.payment import DEFAULT_CURRENCY, Payment
from coiflink_api.domain.transaction import Transaction, TransactionFilter
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_ADMIN_ID = uuid.UUID("aa222222-0000-0000-0000-000000000099")
_CLIENT_ID = uuid.UUID("bb222222-0000-0000-0000-000000000011")
_HAIRDRESSER_ID = uuid.UUID("cc222222-0000-0000-0000-000000000022")
_OTHER_MANAGER_ID = uuid.UUID("dd222222-0000-0000-0000-000000000033")

_SALON_ID = uuid.UUID("ee148148-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("ff148148-0000-0000-0000-000000000002")

_ROLE_USER_IDS: dict[str, uuid.UUID] = {
    "CLIENT": _CLIENT_ID,
    "MANAGER": _MANAGER_ID,
    "ADMIN": _ADMIN_ID,
    "HAIRDRESSER": _HAIRDRESSER_ID,
}

_KPI_URL = f"/salons/{_SALON_ID}/dashboard/kpis"
_REVENUE_SERIES_URL = f"/salons/{_SALON_ID}/dashboard/revenue-series"
_ATTENDANCE_SERIES_URL = f"/salons/{_SALON_ID}/dashboard/attendance-series"
_IN_PROGRESS_URL = f"/salons/{_SALON_ID}/dashboard/in-progress"
_ACTIVITY_URL = f"/salons/{_SALON_ID}/dashboard/activity"
_ALERTS_URL = f"/salons/{_SALON_ID}/dashboard/alerts"

_ALL_DASHBOARD_URLS = [
    _KPI_URL,
    _REVENUE_SERIES_URL,
    _ATTENDANCE_SERIES_URL,
    _IN_PROGRESS_URL,
    _ACTIVITY_URL,
    _ALERTS_URL,
]


# ---------------------------------------------------------------------------
# Fake repositories
# ---------------------------------------------------------------------------


class FakeDashboardQueueTicketRepo:
    """Fake du port `QueueTicketRepository` pour les routes dashboard (#148)."""

    def __init__(
        self,
        counts_by_status: list[Mapping[str, int]] | None = None,
        distinct_clients: list[int] | None = None,
        in_progress_items: tuple[InProgressService, ...] = (),
        in_progress_count: int = 0,
        waiting_beyond_estimate: int = 0,
        attendance: Mapping[datetime.date, int] | None = None,
    ) -> None:
        self._counts_by_status = counts_by_status or [{}]
        self._distinct_clients = distinct_clients or [0]
        self._in_progress_items = in_progress_items
        self._in_progress_count = in_progress_count
        self._waiting_beyond_estimate = waiting_beyond_estimate
        self._attendance = attendance or {}
        self._count_idx = 0
        self._clients_idx = 0

    def count_by_status_in_range(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[str, int]:
        result = self._counts_by_status[self._count_idx % len(self._counts_by_status)]
        self._count_idx += 1
        return result

    def count_distinct_completed_clients(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> int:
        result = self._distinct_clients[self._clients_idx % len(self._distinct_clients)]
        self._clients_idx += 1
        return result

    def count_in_progress(self, salon_id: uuid.UUID) -> int:
        return self._in_progress_count

    def count_waiting_beyond_estimate(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> int:
        return self._waiting_beyond_estimate

    def list_in_progress_details(
        self, salon_id: uuid.UUID
    ) -> tuple[InProgressService, ...]:
        return self._in_progress_items

    def attendance_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, int]:
        return self._attendance

    def demand_by_service(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class FakeDashboardCashRepo:
    """Fake du port `CashJournalRepository` pour les routes dashboard (#148)."""

    def __init__(
        self,
        revenues: list[decimal.Decimal] | None = None,
        series: Mapping[datetime.date, decimal.Decimal] | None = None,
    ) -> None:
        self._revenues = revenues or [decimal.Decimal("0.00")]
        self._series: Mapping[datetime.date, decimal.Decimal] = series or {}
        self._call_idx = 0

    def net_revenue_between(
        self,
        salon_id: uuid.UUID,
        *,
        created_at_from: datetime.datetime,
        created_at_to: datetime.datetime,
    ) -> decimal.Decimal:
        result = self._revenues[self._call_idx % len(self._revenues)]
        self._call_idx += 1
        return result

    def net_revenue_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, decimal.Decimal]:
        return self._series

    def append(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_salon(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_for_salon(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class FakeDashboardPaymentRepo:
    """Fake du port `PaymentRepository` pour les routes dashboard (#148)."""

    def __init__(
        self,
        transactions: tuple[Transaction, ...] = (),
        anomaly_count: int = 0,
    ) -> None:
        self._transactions = transactions
        self._anomaly_count = anomaly_count

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        filter: TransactionFilter,
        limit: int,
        offset: int,
    ) -> tuple[Transaction, ...]:
        return self._transactions

    def count_completed_without_payment(
        self, salon_id: uuid.UUID, *, filter: DiscrepancyFilter
    ) -> int:
        return self._anomaly_count

    def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def mark_adjusted(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_for_salon(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_completed_without_payment(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_credentials(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _user_repo_with_all_roles() -> FakeAuthUserRepository:
    by_id: dict[str, UserCredentials] = {
        str(uid): _make_credentials(uid, role)
        for role, uid in _ROLE_USER_IDS.items()
    }
    by_id[str(_OTHER_MANAGER_ID)] = _make_credentials(_OTHER_MANAGER_ID, Role.MANAGER.value)
    return FakeAuthUserRepository(credentials_by_id=by_id)


def _scope_repo_for_manager() -> FakeSalonScopeRepository:
    return FakeSalonScopeRepository(
        scopes={_MANAGER_ID: frozenset([_SALON_ID])}
    )


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    tickets_repo = FakeDashboardQueueTicketRepo()
    cash_repo = FakeDashboardCashRepo()
    payment_repo = FakeDashboardPaymentRepo()

    app.dependency_overrides[get_queue_ticket_repository] = lambda: tickets_repo
    app.dependency_overrides[get_cash_journal_repository] = lambda: cash_repo
    app.dependency_overrides[get_payment_repository] = lambda: payment_repo
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_with_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
        _scope_repo_for_manager()
    )

    with TestClient(app) as c:
        yield c


def _manager_token() -> str:
    return make_access_token(_MANAGER_ID, "MANAGER")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _manager_headers() -> dict[str, str]:
    return _auth_header(_manager_token())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FORBIDDEN_KEYS = {"client_id", "phone", "email", "reference", "recorded_by"}


def _assert_no_pii(payload: object) -> None:
    """Vérifie récursivement qu'aucune clé PII interdite ne figure dans la réponse."""
    if isinstance(payload, dict):
        for key in _FORBIDDEN_KEYS:
            assert key not in payload, f"PII key '{key}' found in response"
        for value in payload.values():
            _assert_no_pii(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_pii(item)


def _override_all(
    *,
    tickets_repo: FakeDashboardQueueTicketRepo | None = None,
    cash_repo: FakeDashboardCashRepo | None = None,
    payment_repo: FakeDashboardPaymentRepo | None = None,
) -> None:
    app.dependency_overrides[get_queue_ticket_repository] = lambda: (
        tickets_repo or FakeDashboardQueueTicketRepo()
    )
    app.dependency_overrides[get_cash_journal_repository] = lambda: (
        cash_repo or FakeDashboardCashRepo()
    )
    app.dependency_overrides[get_payment_repository] = lambda: (
        payment_repo or FakeDashboardPaymentRepo()
    )
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_with_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
        _scope_repo_for_manager()
    )


# ===========================================================================
# dashboard/kpis
# ===========================================================================


class TestDashboardKpis200:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        assert r.status_code == 200

    def test_response_has_period(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        data = r.json()
        assert "period" in data
        assert "kind" in data["period"]
        assert "date_from" in data["period"]
        assert "date_to" in data["period"]

    def test_response_has_waiting_clients_evolution(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        data = r.json()
        wc = data["waiting_clients"]
        assert "current" in wc
        assert "previous" in wc
        assert "delta" in wc
        assert "direction" in wc

    def test_response_has_in_progress_count(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        data = r.json()
        assert "in_progress" in data
        assert "current" in data["in_progress"]

    def test_response_has_revenue_evolution(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        data = r.json()
        rev = data["revenue"]
        assert "current" in rev
        assert "previous" in rev
        assert "delta" in rev
        assert "direction" in rev
        assert "currency" in rev

    def test_response_has_clients_count_evolution(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        data = r.json()
        assert "clients_count" in data

    def test_no_pii_in_response(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        _assert_no_pii(r.json())

    def test_period_today_default(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        assert r.json()["period"]["kind"] == "today"

    def test_period_week(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, params={"period": "week"}, headers=_manager_headers())
        assert r.status_code == 200
        assert r.json()["period"]["kind"] == "week"

    def test_period_month(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, params={"period": "month"}, headers=_manager_headers())
        assert r.status_code == 200
        assert r.json()["period"]["kind"] == "month"

    def test_period_custom_with_bounds(self, client: TestClient) -> None:
        r = client.get(
            _KPI_URL,
            params={"period": "custom", "date_from": "2026-08-01", "date_to": "2026-08-07"},
            headers=_manager_headers(),
        )
        assert r.status_code == 200

    def test_revenue_delta_is_decimal_string(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers=_manager_headers())
        delta = r.json()["revenue"]["delta"]
        decimal.Decimal(str(delta))  # must not raise


class TestDashboardKpis422:
    def test_unknown_period_raises_422(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, params={"period": "yearly"}, headers=_manager_headers())
        assert r.status_code == 422

    def test_custom_without_date_from_raises_422(self, client: TestClient) -> None:
        r = client.get(
            _KPI_URL,
            params={"period": "custom", "date_to": "2026-08-07"},
            headers=_manager_headers(),
        )
        assert r.status_code == 422

    def test_custom_without_date_to_raises_422(self, client: TestClient) -> None:
        r = client.get(
            _KPI_URL,
            params={"period": "custom", "date_from": "2026-08-01"},
            headers=_manager_headers(),
        )
        assert r.status_code == 422

    def test_custom_date_to_before_date_from_raises_422(self, client: TestClient) -> None:
        r = client.get(
            _KPI_URL,
            params={"period": "custom", "date_from": "2026-08-10", "date_to": "2026-08-01"},
            headers=_manager_headers(),
        )
        assert r.status_code == 422


class TestDashboardKpisAuth:
    def test_no_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_KPI_URL)
        assert r.status_code == 401

    def test_invalid_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_KPI_URL, headers={"Authorization": "Bearer not-a-valid-jwt"})
        assert r.status_code == 401

    @pytest.mark.parametrize("role", ["CLIENT", "HAIRDRESSER", "ADMIN"])
    def test_non_manager_roles_raise_403(self, client: TestClient, role: str) -> None:
        token = make_access_token(_ROLE_USER_IDS[role], role)
        r = client.get(_KPI_URL, headers=_auth_header(token))
        assert r.status_code == 403

    def test_manager_out_of_scope_raises_403(self, client: TestClient) -> None:
        token = make_access_token(_OTHER_MANAGER_ID, "MANAGER")
        r = client.get(_KPI_URL, headers=_auth_header(token))
        assert r.status_code == 403


# ===========================================================================
# dashboard/revenue-series
# ===========================================================================


class TestDashboardRevenueSeries200:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL, headers=_manager_headers())
        assert r.status_code == 200

    def test_response_has_buckets_list(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL, headers=_manager_headers())
        data = r.json()
        assert "buckets" in data
        assert isinstance(data["buckets"], list)

    def test_response_has_currency(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL, headers=_manager_headers())
        assert r.json()["currency"] == DEFAULT_CURRENCY

    def test_response_has_date_bounds(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL, headers=_manager_headers())
        data = r.json()
        assert "date_from" in data
        assert "date_to" in data

    def test_bucket_has_required_fields(self, client: TestClient) -> None:
        r = client.get(
            _REVENUE_SERIES_URL,
            params={"period": "week", "reference": "2026-08-07"},
            headers=_manager_headers(),
        )
        data = r.json()
        if data["buckets"]:
            bucket = data["buckets"][0]
            assert "bucket_start" in bucket
            assert "bucket_end" in bucket
            assert "total" in bucket

    def test_no_pii_in_response(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL, headers=_manager_headers())
        _assert_no_pii(r.json())


class TestDashboardRevenueSeries422:
    def test_unknown_period_raises_422(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL, params={"period": "bad"}, headers=_manager_headers())
        assert r.status_code == 422

    def test_custom_without_bounds_raises_422(self, client: TestClient) -> None:
        r = client.get(
            _REVENUE_SERIES_URL, params={"period": "custom"}, headers=_manager_headers()
        )
        assert r.status_code == 422


class TestDashboardRevenueSeriesAuth:
    def test_no_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_REVENUE_SERIES_URL)
        assert r.status_code == 401

    @pytest.mark.parametrize("role", ["CLIENT", "HAIRDRESSER"])
    def test_unauthorized_roles_raise_403(self, client: TestClient, role: str) -> None:
        token = make_access_token(_ROLE_USER_IDS[role], role)
        r = client.get(_REVENUE_SERIES_URL, headers=_auth_header(token))
        assert r.status_code == 403


# ===========================================================================
# dashboard/attendance-series
# ===========================================================================


class TestDashboardAttendanceSeries200:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get(_ATTENDANCE_SERIES_URL, headers=_manager_headers())
        assert r.status_code == 200

    def test_response_has_buckets(self, client: TestClient) -> None:
        r = client.get(_ATTENDANCE_SERIES_URL, headers=_manager_headers())
        data = r.json()
        assert "buckets" in data
        assert isinstance(data["buckets"], list)

    def test_no_pii_in_response(self, client: TestClient) -> None:
        r = client.get(_ATTENDANCE_SERIES_URL, headers=_manager_headers())
        _assert_no_pii(r.json())


class TestDashboardAttendanceSeries422:
    def test_unknown_period_raises_422(self, client: TestClient) -> None:
        r = client.get(
            _ATTENDANCE_SERIES_URL, params={"period": "quarterly"}, headers=_manager_headers()
        )
        assert r.status_code == 422


class TestDashboardAttendanceSeriesAuth:
    def test_no_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_ATTENDANCE_SERIES_URL)
        assert r.status_code == 401


# ===========================================================================
# dashboard/in-progress
# ===========================================================================


class TestDashboardInProgress200:
    def test_returns_200_empty_list(self, client: TestClient) -> None:
        r = client.get(_IN_PROGRESS_URL, headers=_manager_headers())
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert data["items"] == []

    def test_response_has_as_of(self, client: TestClient) -> None:
        r = client.get(_IN_PROGRESS_URL, headers=_manager_headers())
        data = r.json()
        assert "as_of" in data

    def test_no_pii_in_response(self, client: TestClient) -> None:
        r = client.get(_IN_PROGRESS_URL, headers=_manager_headers())
        _assert_no_pii(r.json())

    def test_item_shape_with_in_progress_service(self) -> None:
        """Vérifie le schéma d'un item retourné par in-progress."""
        item = InProgressService(
            queue_ticket_id=str(uuid.uuid4()),
            client_name="Awa Koné",
            service_names=("Coupe femme",),
            hairdresser_name="Fatou D.",
            started_at=datetime.datetime(2026, 8, 7, 14, 0),
            status="in_progress",
        )
        tickets_repo = FakeDashboardQueueTicketRepo(in_progress_items=(item,))
        _override_all(tickets_repo=tickets_repo)
        try:
            with TestClient(app) as c:
                r = c.get(_IN_PROGRESS_URL, headers=_manager_headers())
            data = r.json()
            assert len(data["items"]) == 1
            first = data["items"][0]
            assert "queue_ticket_id" in first
            assert "client_name" in first
            assert "service_names" in first
            assert "hairdresser_name" in first
            assert "started_at" in first
            assert "status" in first
            # Non-PII: no customer_profile_id, no contact
            assert "customer_profile_id" not in first
            assert "client_id" not in first
        finally:
            app.dependency_overrides.clear()


class TestDashboardInProgressAuth:
    def test_no_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_IN_PROGRESS_URL)
        assert r.status_code == 401

    @pytest.mark.parametrize("role", ["CLIENT", "HAIRDRESSER"])
    def test_unauthorized_roles_raise_403(self, client: TestClient, role: str) -> None:
        token = make_access_token(_ROLE_USER_IDS[role], role)
        r = client.get(_IN_PROGRESS_URL, headers=_auth_header(token))
        assert r.status_code == 403


# ===========================================================================
# dashboard/activity
# ===========================================================================


class TestDashboardActivity200:
    def test_returns_200_empty(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, headers=_manager_headers())
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_response_has_items(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, headers=_manager_headers())
        data = r.json()
        assert "items" in data

    def test_no_pii_in_response(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, headers=_manager_headers())
        _assert_no_pii(r.json())

    def test_default_limit_accepted(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, headers=_manager_headers())
        assert r.status_code == 200

    def test_explicit_limit_accepted(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, params={"limit": 5}, headers=_manager_headers())
        assert r.status_code == 200

    def test_activity_item_shape_for_payment(self) -> None:
        """Vérifie la forme d'un item paiement (avec montant + client_name)."""
        payment = Payment(
            id=uuid.uuid4(),
            salon_id=_SALON_ID,
            amount=decimal.Decimal("15000.00"),
            currency=DEFAULT_CURRENCY,
            payment_method="CASH",
            status="VALIDATED",
            recorded_by=uuid.uuid4(),
            service_id=None,
            queue_ticket_id=None,
            client_id=uuid.uuid4(),
            reference=None,
            mobile_money_phone=None,
            created_at=datetime.datetime(2026, 8, 7, 12, 0),
        )
        txn = Transaction(payment=payment, client_name="Awa Koné")
        payment_repo = FakeDashboardPaymentRepo(transactions=(txn,))
        _override_all(payment_repo=payment_repo)
        try:
            with TestClient(app) as c:
                r = c.get(_ACTIVITY_URL, headers=_manager_headers())
            data = r.json()
            assert len(data["items"]) == 1
            item = data["items"][0]
            assert item["kind"] == "payment"
            assert "occurred_at" in item
            assert "label" in item
            assert item["amount"] is not None
            assert item["client_name"] == "Awa Koné"
            assert item["currency"] == DEFAULT_CURRENCY
            # Non-PII: no client_id
            assert "client_id" not in item
        finally:
            app.dependency_overrides.clear()


class TestDashboardActivity422:
    def test_limit_below_minimum_raises_422(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, params={"limit": 0}, headers=_manager_headers())
        assert r.status_code == 422

    def test_limit_above_maximum_raises_422(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL, params={"limit": 101}, headers=_manager_headers())
        assert r.status_code == 422


class TestDashboardActivityAuth:
    def test_no_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_ACTIVITY_URL)
        assert r.status_code == 401

    @pytest.mark.parametrize("role", ["CLIENT", "HAIRDRESSER"])
    def test_unauthorized_roles_raise_403(self, client: TestClient, role: str) -> None:
        token = make_access_token(_ROLE_USER_IDS[role], role)
        r = client.get(_ACTIVITY_URL, headers=_auth_header(token))
        assert r.status_code == 403


# ===========================================================================
# dashboard/alerts
# ===========================================================================


class TestDashboardAlerts200:
    def test_returns_200_empty(self, client: TestClient) -> None:
        r = client.get(_ALERTS_URL, headers=_manager_headers())
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_response_has_items(self, client: TestClient) -> None:
        r = client.get(_ALERTS_URL, headers=_manager_headers())
        data = r.json()
        assert "items" in data

    def test_no_pii_in_response(self, client: TestClient) -> None:
        r = client.get(_ALERTS_URL, headers=_manager_headers())
        _assert_no_pii(r.json())

    def test_alert_item_shape(self) -> None:
        """Vérifie la forme d'un item alerte (kind, severity, count)."""
        tickets_repo = FakeDashboardQueueTicketRepo(waiting_beyond_estimate=1)
        payment_repo = FakeDashboardPaymentRepo(anomaly_count=1)
        _override_all(tickets_repo=tickets_repo, payment_repo=payment_repo)
        try:
            with TestClient(app) as c:
                r = c.get(_ALERTS_URL, headers=_manager_headers())
            data = r.json()
            assert len(data["items"]) >= 1
            for item in data["items"]:
                assert "kind" in item
                assert "severity" in item
                assert "count" in item
                assert item["count"] > 0
        finally:
            app.dependency_overrides.clear()


class TestDashboardAlertsAuth:
    def test_no_token_raises_401(self, client: TestClient) -> None:
        r = client.get(_ALERTS_URL)
        assert r.status_code == 401

    @pytest.mark.parametrize("role", ["CLIENT", "HAIRDRESSER"])
    def test_unauthorized_roles_raise_403(self, client: TestClient, role: str) -> None:
        token = make_access_token(_ROLE_USER_IDS[role], role)
        r = client.get(_ALERTS_URL, headers=_auth_header(token))
        assert r.status_code == 403

    def test_manager_out_of_scope_raises_403(self, client: TestClient) -> None:
        token = make_access_token(_OTHER_MANAGER_ID, "MANAGER")
        r = client.get(_ALERTS_URL, headers=_auth_header(token))
        assert r.status_code == 403


# ===========================================================================
# PUBLIC_ROUTE_PATHS — toutes les routes dashboard sont protégées
# ===========================================================================


class TestDashboardRoutesNotPublic:
    @pytest.mark.parametrize("url", _ALL_DASHBOARD_URLS)
    def test_route_not_in_public_paths(self, url: str) -> None:
        """Aucune route dashboard ne doit figurer dans PUBLIC_ROUTE_PATHS (§11.3)."""
        for public_path in PUBLIC_ROUTE_PATHS:
            assert not url.startswith(public_path), (
                f"Route '{url}' should NOT be public (found prefix '{public_path}')"
            )


# ===========================================================================
# Isolation salon_id — périmètre salon (§11.2)
# ===========================================================================


class TestDashboardSalonIsolation:
    """Un gérant dont le salon_id n'est pas dans sa portée reçoit un 403 générique."""

    @pytest.mark.parametrize("url", _ALL_DASHBOARD_URLS)
    def test_other_salon_returns_403(self, url: str) -> None:
        other_salon_url = url.replace(str(_SALON_ID), str(_OTHER_SALON_ID))
        _override_all()
        try:
            with TestClient(app) as c:
                r = c.get(other_salon_url, headers=_manager_headers())
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()
