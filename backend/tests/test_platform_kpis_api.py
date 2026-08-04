"""Tests API — `GET /admin/kpis` (US-6.6, #44).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_platform_kpi_repository` → `FakePlatformKpiRepository` ;
- `get_user_repository`         → `FakeAuthUserRepository` ;
- `get_access_policy`           → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 ADMIN : réponse plate (non paginée) avec scalaires globaux + dates + devise ;
- schéma de réponse : tous les champs attendus présents et de bons types ;
- `revenue_total`/`revenue_this_month` sérialisés en chaîne décimale (jamais un
  flottant), négatifs inclus ;
- plateforme vide : compteurs à 0, revenus `"0.00"` (état vide légitime, ≠ erreur) ;
- `reference_date` optionnel : absent → mois courant inféré ; présent → transmis et
  répercuté dans `reference_date`/`month_from`/`month_to` de la réponse ;
- `reference_date` malformé → 422 (validation FastAPI Query) ;
- **non-PII (§11.3)** : aucun champ interdit dans la réponse (`salon_id`,
  `client_id`, `owner_id`, `reference`, `recorded_by`) ;
- **absence de `subscriptions`** : aucun modèle d'abonnement n'existe (ADR-0032) ;
- 401 sans jeton / jeton absent ;
- 403 CLIENT, HAIRDRESSER, MANAGER — rôles sans `STATS_READ_PLATFORM` ;
- message 403 générique (§11.2) ;
- route absente de `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.admin import get_platform_kpi_repository
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
from coiflink_api.domain.platform_kpis import PlatformKpiCounts
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

_ADMIN_TOKEN = make_access_token(_ADMIN_ID, Role.ADMIN.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_URL = "/admin/kpis"


# ---------------------------------------------------------------------------
# Fake PlatformKpiRepository
# ---------------------------------------------------------------------------


class FakePlatformKpiRepository:
    """Fake du port `PlatformKpiRepository` (US-6.6, #44) — aucun I/O."""

    def __init__(self, counts: PlatformKpiCounts | None = None) -> None:
        self._counts = counts or PlatformKpiCounts(
            salons_total=0,
            salons_active=0,
            clients_total=0,
            appointments_total=0,
            appointments_this_month=0,
            revenue_total=decimal.Decimal("0.00"),
            revenue_this_month=decimal.Decimal("0.00"),
        )
        self.calls: list[dict] = []

    def compute_snapshot(
        self,
        *,
        month_from: datetime.date,
        month_to: datetime.date,
        revenue_from_utc: datetime.datetime,
        revenue_to_utc: datetime.datetime,
    ) -> PlatformKpiCounts:
        self.calls.append(
            {
                "month_from": month_from,
                "month_to": month_to,
                "revenue_from_utc": revenue_from_utc,
                "revenue_to_utc": revenue_to_utc,
            }
        )
        return self._counts


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


def _make_counts(**kwargs) -> PlatformKpiCounts:
    defaults = dict(
        salons_total=128,
        salons_active=97,
        clients_total=5421,
        appointments_total=18342,
        appointments_this_month=1204,
        revenue_total=decimal.Decimal("12500000.00"),
        revenue_this_month=decimal.Decimal("980000.00"),
    )
    defaults.update(kwargs)
    return PlatformKpiCounts(**defaults)


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
def kpi_repo() -> FakePlatformKpiRepository:
    return FakePlatformKpiRepository()


@pytest.fixture()
def admin_client(
    kpi_repo: FakePlatformKpiRepository,
) -> Generator[TestClient, None, None]:
    """TestClient avec ADMIN authentifié (STATS_READ_PLATFORM)."""
    creds = _creds(_ADMIN_ID, Role.ADMIN.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(_ADMIN_ID): creds})
    scope_repo = FakeSalonScopeRepository()

    app.dependency_overrides[get_platform_kpi_repository] = lambda: kpi_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_platform_kpi_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# 200 — structure de base
# ---------------------------------------------------------------------------


class TestGetPlatformKpis200:
    def test_returns_200(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.status_code == 200

    def test_response_is_object_not_list(self, admin_client: TestClient) -> None:
        """L'instantané est une réponse plate (non paginée), pas une liste."""
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert isinstance(r.json(), dict)
        assert not isinstance(r.json(), list)

    def test_empty_platform_zero_salons(
        self, admin_client: TestClient
    ) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.json()["salons_total"] == 0
        assert r.json()["salons_active"] == 0

    def test_empty_platform_zero_clients(
        self, admin_client: TestClient
    ) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.json()["clients_total"] == 0

    def test_empty_platform_zero_appointments(
        self, admin_client: TestClient
    ) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.json()["appointments_total"] == 0
        assert r.json()["appointments_this_month"] == 0

    def test_empty_platform_zero_revenue(
        self, admin_client: TestClient
    ) -> None:
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.json()["revenue_total"] == "0.00"
        assert r.json()["revenue_this_month"] == "0.00"

    def test_seeded_counts_reflected(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        kpi_repo._counts = _make_counts()
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        data = r.json()
        assert data["salons_total"] == 128
        assert data["salons_active"] == 97
        assert data["clients_total"] == 5421
        assert data["appointments_total"] == 18342


# ---------------------------------------------------------------------------
# 200 — schéma de réponse complet
# ---------------------------------------------------------------------------


class TestGetPlatformKpisResponseSchema:
    def _get(
        self,
        admin_client: TestClient,
        kpi_repo: FakePlatformKpiRepository,
        counts: PlatformKpiCounts | None = None,
        *,
        params: dict | None = None,
    ) -> dict:
        if counts is not None:
            kpi_repo._counts = counts
        r = admin_client.get(
            _URL,
            params=params or {},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200
        return r.json()

    def test_has_salons_total(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo, _make_counts(salons_total=10))
        assert "salons_total" in data
        assert data["salons_total"] == 10

    def test_has_salons_active(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo, _make_counts(salons_active=7))
        assert "salons_active" in data
        assert data["salons_active"] == 7

    def test_has_clients_total(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo, _make_counts(clients_total=500))
        assert "clients_total" in data
        assert data["clients_total"] == 500

    def test_has_appointments_total(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo, _make_counts(appointments_total=1000))
        assert "appointments_total" in data
        assert data["appointments_total"] == 1000

    def test_has_appointments_this_month(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo, _make_counts(appointments_this_month=42))
        assert "appointments_this_month" in data
        assert data["appointments_this_month"] == 42

    def test_has_revenue_total(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(
            admin_client, kpi_repo, _make_counts(revenue_total=decimal.Decimal("1500000.00"))
        )
        assert "revenue_total" in data
        assert data["revenue_total"] == "1500000.00"

    def test_has_revenue_this_month(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(
            admin_client, kpi_repo, _make_counts(revenue_this_month=decimal.Decimal("125000.00"))
        )
        assert "revenue_this_month" in data
        assert data["revenue_this_month"] == "125000.00"

    def test_has_currency(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "currency" in data
        assert data["currency"] == DEFAULT_CURRENCY
        assert data["currency"] == "XOF"

    def test_has_reference_date(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "reference_date" in data

    def test_has_month_from(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "month_from" in data

    def test_has_month_to(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "month_to" in data

    def test_revenue_total_is_decimal_string(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        """Les montants revenue sont sérialisés en chaîne décimale, jamais en flottant."""
        data = self._get(
            admin_client, kpi_repo, _make_counts(revenue_total=decimal.Decimal("12345.67"))
        )
        assert isinstance(data["revenue_total"], str)

    def test_revenue_this_month_is_decimal_string(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(
            admin_client, kpi_repo, _make_counts(revenue_this_month=decimal.Decimal("1234.56"))
        )
        assert isinstance(data["revenue_this_month"], str)

    def test_revenue_total_negative_serialized(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        """Un montant net négatif (corrections > paiements) est sérialisé correctement."""
        data = self._get(
            admin_client, kpi_repo, _make_counts(revenue_total=decimal.Decimal("-500.00"))
        )
        assert data["revenue_total"] == "-500.00"

    def test_revenue_this_month_negative_serialized(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(
            admin_client,
            kpi_repo,
            _make_counts(revenue_this_month=decimal.Decimal("-100.00")),
        )
        assert data["revenue_this_month"] == "-100.00"

    # ---- Non-PII (§11.3) — champs interdits absents de la réponse HTTP -----

    def test_no_salon_id_in_response(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "salon_id" not in data, "salon_id est une PII interdite (§11.3)"

    def test_no_client_id_in_response(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "client_id" not in data, "client_id est une PII interdite (§11.3)"

    def test_no_owner_id_in_response(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "owner_id" not in data, "owner_id est une PII interdite (§11.3)"

    def test_no_reference_field_in_response(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "reference" not in data, "reference est une PII interdite (§11.3)"

    def test_no_recorded_by_in_response(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        data = self._get(admin_client, kpi_repo)
        assert "recorded_by" not in data, "recorded_by est une PII interdite (§11.3)"

    def test_no_subscriptions_in_response(
        self, admin_client: TestClient, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        """Aucun modèle d'abonnement n'existe — subscriptions absent de la réponse (ADR-0032)."""
        data = self._get(admin_client, kpi_repo)
        assert "subscriptions" not in data


# ---------------------------------------------------------------------------
# `reference_date` — paramètre optionnel
# ---------------------------------------------------------------------------


class TestGetPlatformKpisReferenceDate:
    def test_no_reference_date_returns_200(self, admin_client: TestClient) -> None:
        """Sans `reference_date`, le backend infère aujourd'hui → 200."""
        r = admin_client.get(_URL, headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"})
        assert r.status_code == 200

    def test_explicit_reference_date_reflected(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"reference_date": "2026-07-15"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200
        assert r.json()["reference_date"] == "2026-07-15"

    def test_month_from_derived_from_reference_date(
        self, admin_client: TestClient
    ) -> None:
        """La borne `month_from` est le 1er jour du mois de `reference_date`."""
        r = admin_client.get(
            _URL,
            params={"reference_date": "2026-07-15"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.json()["month_from"] == "2026-07-01"

    def test_month_to_derived_from_reference_date(
        self, admin_client: TestClient
    ) -> None:
        """La borne `month_to` est le dernier jour du mois de `reference_date`."""
        r = admin_client.get(
            _URL,
            params={"reference_date": "2026-07-15"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.json()["month_to"] == "2026-07-31"

    def test_reference_date_first_of_month(
        self, admin_client: TestClient
    ) -> None:
        r = admin_client.get(
            _URL,
            params={"reference_date": "2026-08-01"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.json()["month_from"] == "2026-08-01"
        assert r.json()["reference_date"] == "2026-08-01"

    def test_reference_date_february_month_to(
        self, admin_client: TestClient
    ) -> None:
        """Février 2026 (non bissextile) : month_to = 2026-02-28."""
        r = admin_client.get(
            _URL,
            params={"reference_date": "2026-02-10"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.json()["month_to"] == "2026-02-28"


# ---------------------------------------------------------------------------
# 422 — reference_date malformé
# ---------------------------------------------------------------------------


class TestGetPlatformKpis422:
    def test_malformed_date_returns_422(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"reference_date": "not-a-date"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422

    def test_invalid_date_format_returns_422(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"reference_date": "03-08-2026"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 422

    def test_valid_date_returns_200(self, admin_client: TestClient) -> None:
        r = admin_client.get(
            _URL,
            params={"reference_date": "2026-08-03"},
            headers={"Authorization": f"Bearer {_ADMIN_TOKEN}"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 401 — sans jeton
# ---------------------------------------------------------------------------


class TestGetPlatformKpis401:
    def test_no_token_returns_401(self, admin_client: TestClient) -> None:
        r = admin_client.get(_URL)
        assert r.status_code == 401

    def test_401_includes_www_authenticate_header(
        self, admin_client: TestClient
    ) -> None:
        r = admin_client.get(_URL)
        assert "WWW-Authenticate" in r.headers


# ---------------------------------------------------------------------------
# 403 — rôles sans STATS_READ_PLATFORM
# ---------------------------------------------------------------------------


class TestGetPlatformKpis403:
    def _client_with_role(
        self,
        kpi_repo: FakePlatformKpiRepository,
        user_id: uuid.UUID,
        role: str,
    ) -> TestClient:
        creds = _creds(user_id, role)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(user_id): creds})
        scope_repo = FakeSalonScopeRepository()

        app.dependency_overrides[get_platform_kpi_repository] = lambda: kpi_repo
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        return TestClient(app, raise_server_exceptions=False)

    def test_client_role_returns_403(
        self, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        client = self._client_with_role(kpi_repo, _CLIENT_ID, Role.CLIENT.value)
        try:
            r = client.get(_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_platform_kpi_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_hairdresser_role_returns_403(
        self, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        client = self._client_with_role(
            kpi_repo, _HAIRDRESSER_ID, Role.HAIRDRESSER.value
        )
        try:
            r = client.get(
                _URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_platform_kpi_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_manager_role_returns_403(
        self, kpi_repo: FakePlatformKpiRepository
    ) -> None:
        """Le MANAGER ne porte pas STATS_READ_PLATFORM → 403 générique (§4.1)."""
        client = self._client_with_role(kpi_repo, _MANAGER_ID, Role.MANAGER.value)
        try:
            r = client.get(_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_platform_kpi_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_403_message_is_generic(
        self,
        admin_client: TestClient,
        kpi_repo: FakePlatformKpiRepository,
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
# Sécurité — route jamais publique
# ---------------------------------------------------------------------------


class TestGetPlatformKpisPublicRoutes:
    def test_admin_kpis_not_in_public_route_paths(self) -> None:
        """KPI admin : la route `/admin/kpis` ne doit jamais être publique."""
        for path in PUBLIC_ROUTE_PATHS:
            assert "/admin/kpis" not in path, (
                f"Route KPI admin trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )

    def test_admin_prefix_not_in_public_route_paths(self) -> None:
        """Aucun chemin sous /admin ne doit figurer dans PUBLIC_ROUTE_PATHS."""
        for path in PUBLIC_ROUTE_PATHS:
            assert not path.startswith("/admin"), (
                f"Chemin admin trouvé dans PUBLIC_ROUTE_PATHS : {path}"
            )
