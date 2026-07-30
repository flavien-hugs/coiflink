"""Tests API — `GET /admin/transactions/summary` (US-5.6, #37).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_platform_transaction_repository` → `FakePlatformTransactionRepository` ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 sans filtre : structure de page (`items`/`total`/`limit`/`offset`) ;
- 200 avec item : champs attendus (`salon_id`, `salon_name`, `payment_count`,
  `adjustment_count`, `total_amount`, `currency`) ;
- **non-PII (§11.3)** : aucun champ interdit (`client_id`, `reference`,
  `recorded_by`, `performed_by`, `owner_id`) dans les items de réponse ;
- 422 plage incohérente (`date_from > date_to`) — message neutre (§11.3) ;
- 401 sans jeton / jeton absent ;
- 403 CLIENT, HAIRDRESSER, MANAGER — rôles sans `STATS_READ_PLATFORM` ;
- 200 ADMIN — seul rôle porteur de `STATS_READ_PLATFORM` ;
- pagination `limit`/`offset` reflétés, `total` cohérent avec la cardinalité ;
- route absente de `PUBLIC_ROUTE_PATHS` (supervision financière, jamais publique).
"""

from __future__ import annotations

import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.admin import get_platform_transaction_repository
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.platform_transactions import (
    PlatformSummaryFilter,
    SalonTransactionSummary,
)
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

_ADMIN_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000099")
_CLIENT_ID = uuid.UUID("11111111-0000-0000-0000-000000000011")
_HAIRDRESSER_ID = uuid.UUID("22222222-0000-0000-0000-000000000022")
_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)

_SALON_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SALON_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

_ADMIN_TOKEN = make_access_token(_ADMIN_ID, Role.ADMIN.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_URL = "/admin/transactions/summary"

# Valeur par défaut alignée sur PLATFORM_SUMMARY_LIMIT_DEFAULT du port.
_DEFAULT_LIMIT = 50


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


def _make_summary(
    *,
    salon_id: uuid.UUID = _SALON_A_ID,
    salon_name: str = "Salon Alpha",
    payment_count: int = 5,
    adjustment_count: int = 1,
    total_amount: decimal.Decimal = decimal.Decimal("25000.00"),
) -> SalonTransactionSummary:
    return SalonTransactionSummary(
        salon_id=salon_id,
        salon_name=salon_name,
        payment_count=payment_count,
        adjustment_count=adjustment_count,
        total_amount=total_amount,
    )


# ---------------------------------------------------------------------------
# Fake PlatformTransactionRepository
# ---------------------------------------------------------------------------


class FakePlatformTransactionRepository:
    """Fake du port `PlatformTransactionRepository` — aucun I/O (US-5.6, #37).

    Applique limit/offset en mémoire pour que les tests de pagination soient
    déterministes. `_total` est configurable séparément (cardinalité filtrable).
    """

    def __init__(
        self,
        summaries: list[SalonTransactionSummary] | None = None,
        *,
        total: int | None = None,
    ) -> None:
        self._summaries: list[SalonTransactionSummary] = list(summaries or [])
        self._total: int = total if total is not None else len(self._summaries)

    def summary_by_salon(
        self, *, filter: PlatformSummaryFilter, limit: int, offset: int
    ) -> tuple[SalonTransactionSummary, ...]:
        return tuple(self._summaries[offset : offset + limit])

    def count_salons(self, *, filter: PlatformSummaryFilter) -> int:
        return self._total


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
def platform_repo() -> FakePlatformTransactionRepository:
    return FakePlatformTransactionRepository()


@pytest.fixture()
def admin_client(
    platform_repo: FakePlatformTransactionRepository,
) -> Generator[TestClient, None, None]:
    """TestClient avec ADMIN authentifié (STATS_READ_PLATFORM)."""
    creds = _creds(_ADMIN_ID, Role.ADMIN.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(_ADMIN_ID): creds})
    scope_repo = FakeSalonScopeRepository()

    app.dependency_overrides[get_platform_transaction_repository] = lambda: platform_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_platform_transaction_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# 200 — sans filtre : structure de la page
# ---------------------------------------------------------------------------


class TestSummarySalonTransactions200NoFilter:
    def test_returns_200(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.status_code == 200

    def test_response_has_items_field(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert "items" in r.json()

    def test_response_has_total_field(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert "total" in r.json()

    def test_response_has_limit_field(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert "limit" in r.json()

    def test_response_has_offset_field(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert "offset" in r.json()

    def test_empty_repo_returns_zero_total(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        data = r.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_seeded_summary_returns_one_item(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        platform_repo._summaries.append(_make_summary())
        platform_repo._total = 1
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_multiple_summaries_all_returned(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        platform_repo._summaries.extend(
            [
                _make_summary(salon_id=_SALON_A_ID, salon_name="Alpha"),
                _make_summary(salon_id=_SALON_B_ID, salon_name="Beta"),
            ]
        )
        platform_repo._total = 2
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        data = r.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# 200 — schéma de réponse d'un item
# ---------------------------------------------------------------------------


class TestSummarySalonTransactionsResponseSchema:
    def _get_item(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
        summary: SalonTransactionSummary | None = None,
    ) -> dict:
        platform_repo._summaries.append(summary or _make_summary())
        platform_repo._total = 1
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.status_code == 200
        return r.json()["items"][0]

    def test_item_has_salon_id(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(
            admin_client, platform_repo, _make_summary(salon_id=_SALON_A_ID)
        )
        assert "salon_id" in item
        assert item["salon_id"] == str(_SALON_A_ID)

    def test_item_has_salon_name(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(
            admin_client, platform_repo, _make_summary(salon_name="Salon Belle Coupe")
        )
        assert item["salon_name"] == "Salon Belle Coupe"

    def test_item_has_payment_count(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(
            admin_client, platform_repo, _make_summary(payment_count=7)
        )
        assert item["payment_count"] == 7

    def test_item_has_adjustment_count(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(
            admin_client, platform_repo, _make_summary(adjustment_count=3)
        )
        assert item["adjustment_count"] == 3

    def test_item_has_total_amount(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(
            admin_client,
            platform_repo,
            _make_summary(total_amount=decimal.Decimal("615000.00")),
        )
        assert item["total_amount"] == "615000.00"

    def test_item_has_total_amount_as_decimal_string(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        """Le montant net est sérialisé en chaîne décimale, jamais en flottant."""
        item = self._get_item(
            admin_client,
            platform_repo,
            _make_summary(total_amount=decimal.Decimal("1234.56")),
        )
        assert isinstance(item["total_amount"], str)

    def test_item_total_amount_negative(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        """Un montant net négatif (corrections > paiements) est sérialisé correctement."""
        item = self._get_item(
            admin_client,
            platform_repo,
            _make_summary(total_amount=decimal.Decimal("-500.00")),
        )
        assert item["total_amount"] == "-500.00"

    def test_item_has_currency(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert item["currency"] == DEFAULT_CURRENCY

    def test_item_currency_is_xof(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert item["currency"] == "XOF"

    # ---- Non-PII (§11.3) — champs interdits absents de la réponse HTTP -----

    def test_item_does_not_expose_client_id(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert "client_id" not in item, "client_id est une PII interdite (§11.3)"

    def test_item_does_not_expose_reference(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert "reference" not in item, "reference est une PII interdite (§11.3)"

    def test_item_does_not_expose_recorded_by(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert "recorded_by" not in item, "recorded_by est une PII interdite (§11.3)"

    def test_item_does_not_expose_performed_by(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert "performed_by" not in item, "performed_by est une PII interdite (§11.3)"

    def test_item_does_not_expose_owner_id(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        item = self._get_item(admin_client, platform_repo)
        assert "owner_id" not in item, "owner_id est une PII interdite (§11.3)"


# ---------------------------------------------------------------------------
# 422 — filtre invalide
# ---------------------------------------------------------------------------


class TestSummarySalonTransactions422:
    def test_date_from_gt_date_to_returns_422(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422

    def test_422_message_neutral_no_date_from(self, admin_client: TestClient) -> None:
        """Le message d'erreur ne reprend jamais la valeur soumise (§11.3)."""
        r = admin_client.get(
            _URL,
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "2026-03-31" not in detail

    def test_422_message_neutral_no_date_to(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "2026-03-01" not in detail

    def test_422_message_contains_invalide(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422
        assert "invalide" in r.json()["detail"]

    def test_valid_date_range_returns_200(self, admin_client: TestClient) -> None:
        """Une plage valide (date_from ≤ date_to) ne déclenche pas de 422."""
        r = admin_client.get(
            _URL,
            params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200

    def test_single_day_range_returns_200(self, admin_client: TestClient) -> None:
        """Une plage mono-journée (date_from == date_to) est valide."""
        r = admin_client.get(
            _URL,
            params={"date_from": "2026-03-15", "date_to": "2026-03-15"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------


class TestSummarySalonTransactions401:
    def test_no_token_returns_401(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL)
        assert r.status_code == 401

    def test_401_includes_www_authenticate_header(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL)
        assert "WWW-Authenticate" in r.headers


# ---------------------------------------------------------------------------
# 403 — rôles sans STATS_READ_PLATFORM
# ---------------------------------------------------------------------------


class TestSummarySalonTransactions403:
    def _client_with_role(
        self,
        platform_repo: FakePlatformTransactionRepository,
        user_id: uuid.UUID,
        role: str,
    ) -> TestClient:
        creds = _creds(user_id, role)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(user_id): creds})
        scope_repo = FakeSalonScopeRepository()

        app.dependency_overrides[get_platform_transaction_repository] = (
            lambda: platform_repo
        )
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        return TestClient(app, raise_server_exceptions=False)

    def test_client_role_returns_403(
        self, platform_repo: FakePlatformTransactionRepository
    ) -> None:
        client = self._client_with_role(platform_repo, _CLIENT_ID, Role.CLIENT.value)
        try:
            r = client.get(_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_platform_transaction_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_hairdresser_role_returns_403(
        self, platform_repo: FakePlatformTransactionRepository
    ) -> None:
        client = self._client_with_role(
            platform_repo, _HAIRDRESSER_ID, Role.HAIRDRESSER.value
        )
        try:
            r = client.get(
                _URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_platform_transaction_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_manager_role_returns_403(
        self, platform_repo: FakePlatformTransactionRepository
    ) -> None:
        """Le MANAGER ne porte pas STATS_READ_PLATFORM → 403 générique (§4.1)."""
        client = self._client_with_role(platform_repo, _MANAGER_ID, Role.MANAGER.value)
        try:
            r = client.get(_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_platform_transaction_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_403_message_is_generic(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        """Message 403 générique — ne révèle ni la ressource, ni le motif (§11.2)."""
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(_CLIENT_ID): creds})
        scope_repo = FakeSalonScopeRepository()

        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            r = admin_client.get(
                _URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
            )
            assert r.status_code == 403
            assert r.json()["detail"] == "Accès refusé."
        finally:
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestSummarySalonTransactionsPagination:
    def test_default_limit_reflected(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.json()["limit"] == _DEFAULT_LIMIT

    def test_default_offset_is_zero(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.json()["offset"] == 0

    def test_custom_limit_reflected(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        for i in range(5):
            platform_repo._summaries.append(
                _make_summary(salon_id=uuid.uuid4(), salon_name=f"Salon {i}")
            )
        platform_repo._total = 5
        r = admin_client.get(
            _URL,
            params={"limit": 2},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        data = r.json()
        assert data["limit"] == 2
        assert len(data["items"]) == 2

    def test_offset_param_reflected(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"offset": 10},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.json()["offset"] == 10

    def test_total_can_exceed_page_size(
        self,
        admin_client: TestClient,
        platform_repo: FakePlatformTransactionRepository,
    ) -> None:
        """Le total reflète la cardinalité sous le filtre, pas la taille de la page."""
        platform_repo._summaries.append(_make_summary())
        platform_repo._total = 42
        r = admin_client.get(
            _URL,
            params={"limit": 1},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        data = r.json()
        assert data["total"] == 42
        assert len(data["items"]) == 1

    def test_limit_min_boundary(self, admin_client: TestClient) -> None:
        """limit=1 est la valeur minimale autorisée (PLATFORM_SUMMARY_LIMIT_MIN)."""
        r = admin_client.get(
            _URL,
            params={"limit": 1},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200

    def test_limit_max_boundary(self, admin_client: TestClient) -> None:
        """limit=200 est la valeur maximale autorisée (PLATFORM_SUMMARY_LIMIT_MAX)."""
        r = admin_client.get(
            _URL,
            params={"limit": 200},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200

    def test_limit_below_min_returns_422(self, admin_client: TestClient) -> None:
        """limit=0 est hors bornes → FastAPI renvoie 422 (validation Query param)."""
        r = admin_client.get(
            _URL,
            params={"limit": 0},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422

    def test_limit_above_max_returns_422(self, admin_client: TestClient) -> None:
        """limit=201 est hors bornes → FastAPI renvoie 422 (validation Query param)."""
        r = admin_client.get(
            _URL,
            params={"limit": 201},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422

    def test_negative_offset_returns_422(self, admin_client: TestClient) -> None:
        """offset négatif est hors bornes → FastAPI renvoie 422."""
        r = admin_client.get(
            _URL,
            params={"offset": -1},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Sécurité — route jamais publique
# ---------------------------------------------------------------------------


class TestSummarySalonTransactionsPublicRoutes:
    def test_admin_transactions_summary_not_in_public_route_paths(self) -> None:
        """Supervision financière : la route admin ne doit jamais être publique."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "transactions/summary" not in path, (
                f"Route de supervision admin trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )

    def test_admin_prefix_not_in_public_route_paths(self) -> None:
        """Aucun chemin sous /admin ne doit figurer dans PUBLIC_ROUTE_PATHS."""
        for path in PUBLIC_ROUTE_PATHS:
            assert not path.startswith("/admin"), (
                f"Chemin admin trouvé dans PUBLIC_ROUTE_PATHS : {path}"
            )
