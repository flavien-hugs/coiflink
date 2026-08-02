"""Tests API — `GET /salons/{salon_id}/revenue/summary` (US-6.2, #40).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_cash_journal_repository` → `FakeRevenueJournalRepository` ;
- `get_user_repository` → `FakeAuthUserRepository` (toutes les clés de rôle) ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 : structure attendue (`reference_date`, `currency`, `day`/`week`/`month` avec
  `date_from`, `date_to`, `total`) ; `total` en chaîne décimale (`NUMERIC(12,2)`) ;
  CA positif, nul, négatif ; semaine et mois dérivés de la date de référence ;
- **non-PII (§11.3)** : clés uniquement autorisées au niveau racine et par période ;
- route absente de `PUBLIC_ROUTE_PATHS` (donnée financière, jamais publique) ;
- paramètre `date` optionnel : sans → 200 (jour courant Africa/Abidjan) ;
  avec date explicite → 200 et périodes cohérentes ;
- 422 : date mal formée, partielle, mois invalide ;
- 401 : jeton absent ou invalide ;
- 403 : CLIENT, HAIRDRESSER, ADMIN (rôles sans `STATS_READ_SALON`) ;
        gérant hors portée → 403 générique (aucun oracle d'existence).
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
from coiflink_api.adapters.inbound.stats import get_cash_journal_repository
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
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
_ADMIN_ID = uuid.UUID("aa111111-0000-0000-0000-000000000099")
_CLIENT_ID = uuid.UUID("bb111111-0000-0000-0000-000000000011")
_HAIRDRESSER_ID = uuid.UUID("cc111111-0000-0000-0000-000000000022")
_OTHER_MANAGER_ID = uuid.UUID("dd111111-0000-0000-0000-000000000033")

_SALON_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000002")

_ROLE_USER_IDS: dict[str, uuid.UUID] = {
    "CLIENT": _CLIENT_ID,
    "MANAGER": _MANAGER_ID,
    "ADMIN": _ADMIN_ID,
    "HAIRDRESSER": _HAIRDRESSER_ID,
}

_URL = f"/salons/{_SALON_ID}/revenue/summary"


# ---------------------------------------------------------------------------
# Fake CashJournalRepository
# ---------------------------------------------------------------------------


class FakeRevenueJournalRepository:
    """Fake du port pour la route stats (US-6.2, #40) — aucun I/O.

    `amounts` : liste de `Decimal` retournés dans l'ordre des appels à
    `net_revenue_between` (jour, semaine, mois). Le dernier montant est répété si
    la liste est plus courte.
    """

    def __init__(self, amounts: list[decimal.Decimal] | None = None) -> None:
        self._amounts = list(amounts or [decimal.Decimal("0.00")])
        self._call_index = 0

    def net_revenue_between(self, salon_id, *, created_at_from, created_at_to):  # type: ignore[no-untyped-def]
        result = self._amounts[self._call_index % len(self._amounts)]
        self._call_index += 1
        return result

    def append(self, entry):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_salon(self, salon_id, *, limit, offset):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_for_salon(self, salon_id):  # type: ignore[no-untyped-def]
        raise NotImplementedError


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


def _user_repo_for_all_roles() -> FakeAuthUserRepository:
    """Dépôt en mémoire avec un compte ACTIVE pour chaque rôle testé."""
    creds = {
        str(uid): _creds(uid, role)
        for role, uid in _ROLE_USER_IDS.items()
    }
    creds[str(_OTHER_MANAGER_ID)] = _creds(_OTHER_MANAGER_ID, Role.MANAGER.value)
    return FakeAuthUserRepository(credentials_by_id=creds)


def _auth_header(role: str) -> dict[str, str]:
    """Jeton d'accès signé avec le secret de test, `sub` = id du compte du rôle."""
    user_id = _ROLE_USER_IDS.get(role, uuid.uuid4())
    token = make_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


def _stats_client(
    revenue_repo: FakeRevenueJournalRepository | None = None,
    manager_scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient MANAGER avec `_SALON_ID` dans sa portée (US-6.2, #40)."""
    repo = revenue_repo if revenue_repo is not None else FakeRevenueJournalRepository()
    scope = (
        manager_scope
        if manager_scope is not None
        else FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_cash_journal_repository] = lambda: repo
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.pop(get_cash_journal_repository, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)


@pytest.fixture()
def repo() -> FakeRevenueJournalRepository:
    return FakeRevenueJournalRepository()


# ---------------------------------------------------------------------------
# 200 — structure de la réponse
# ---------------------------------------------------------------------------


class TestRevenueSummary200:
    def test_returns_200(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_response_has_reference_date(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["reference_date"] == "2026-08-02"

    def test_response_has_currency_xof(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["currency"] == "XOF"

    def test_response_has_day_week_month_keys(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        data = r.json()
        for key in ("day", "week", "month"):
            assert key in data, f"clé manquante dans la réponse : {key}"

    def test_each_period_has_date_from_date_to_total(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        data = r.json()
        for period_key in ("day", "week", "month"):
            period = data[period_key]
            for field in ("date_from", "date_to", "total"):
                assert field in period, f"{period_key} manque le champ {field}"

    def test_day_date_from_equals_reference(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["day"]["date_from"] == "2026-08-02"

    def test_day_date_to_equals_reference(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["day"]["date_to"] == "2026-08-02"

    def test_week_date_from_is_monday(self) -> None:
        """2026-08-02 (dim) → semaine ISO lundi 27/07 → dim 02/08."""
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["week"]["date_from"] == "2026-07-27"

    def test_week_date_to_is_sunday(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["week"]["date_to"] == "2026-08-02"

    def test_month_date_from_is_first_of_month(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["month"]["date_from"] == "2026-08-01"

    def test_month_date_to_is_last_of_month(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["month"]["date_to"] == "2026-08-31"

    def test_total_is_decimal_string(self) -> None:
        """Le total est sérialisé en chaîne décimale, jamais en flottant JS."""
        repo = FakeRevenueJournalRepository(amounts=[decimal.Decimal("35000.00")])
        r = _stats_client(repo).get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert isinstance(r.json()["day"]["total"], str)

    def test_total_value_correct(self) -> None:
        repo = FakeRevenueJournalRepository(amounts=[decimal.Decimal("35000.00")])
        r = _stats_client(repo).get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["day"]["total"] == "35000.00"

    def test_zero_total_returned_as_string(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["day"]["total"] == "0.00"

    def test_negative_total_serialized_correctly(self) -> None:
        """Total négatif si les corrections excèdent les paiements (valide)."""
        repo = FakeRevenueJournalRepository(amounts=[decimal.Decimal("-500.00")])
        r = _stats_client(repo).get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.json()["day"]["total"] == "-500.00"

    def test_without_date_param_returns_200(self) -> None:
        """Sans paramètre `date`, le backend applique le jour courant (Africa/Abidjan)."""
        r = _stats_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_february_non_leap_month_bounds(self) -> None:
        """date=2026-02-14 → mois = fév. 2026 non bissextile (28 j)."""
        r = _stats_client().get(_URL + "?date=2026-02-14", headers=_auth_header("MANAGER"))
        data = r.json()
        assert data["reference_date"] == "2026-02-14"
        assert data["month"]["date_from"] == "2026-02-01"
        assert data["month"]["date_to"] == "2026-02-28"

    def test_cross_month_week_bounds(self) -> None:
        """2026-07-01 (mer) → semaine lundi 29/06 → dim 05/07 (deux mois)."""
        r = _stats_client().get(_URL + "?date=2026-07-01", headers=_auth_header("MANAGER"))
        data = r.json()
        assert data["week"]["date_from"] == "2026-06-29"
        assert data["week"]["date_to"] == "2026-07-05"


# ---------------------------------------------------------------------------
# Non-PII (§11.3) — schéma figé, champs interdits absents
# ---------------------------------------------------------------------------


class TestRevenueSummaryNonPII:
    def _data(self) -> dict:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        return r.json()

    def test_no_client_id_in_response(self) -> None:
        assert "client_id" not in self._data()

    def test_no_reference_in_response(self) -> None:
        assert "reference" not in self._data()

    def test_no_recorded_by_in_response(self) -> None:
        assert "recorded_by" not in self._data()

    def test_no_performed_by_in_response(self) -> None:
        assert "performed_by" not in self._data()

    def test_no_appointment_id_in_response(self) -> None:
        assert "appointment_id" not in self._data()

    def test_only_expected_top_level_keys(self) -> None:
        """Seuls `reference_date`, `currency`, `day`, `week`, `month` autorisés."""
        data = self._data()
        allowed = {"reference_date", "currency", "day", "week", "month"}
        extra = set(data.keys()) - allowed
        assert extra == set(), f"Champs inattendus dans la réponse : {extra}"

    def test_each_period_has_only_allowed_keys(self) -> None:
        """Chaque période ne porte que `date_from`, `date_to`, `total`."""
        data = self._data()
        allowed = {"date_from", "date_to", "total"}
        for key in ("day", "week", "month"):
            extra = set(data[key].keys()) - allowed
            assert extra == set(), f"{key} a des clés inattendues : {extra}"


# ---------------------------------------------------------------------------
# Route absente de PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestRevenueSummaryRouteProtection:
    def test_revenue_summary_not_in_public_route_paths(self) -> None:
        """La donnée financière ne doit jamais être accessible sans authentification."""
        for public_path in PUBLIC_ROUTE_PATHS:
            assert "revenue/summary" not in public_path, (
                f"revenue/summary trouvé dans PUBLIC_ROUTE_PATHS : {public_path}"
            )


# ---------------------------------------------------------------------------
# 422 — paramètre `date` mal formé
# ---------------------------------------------------------------------------


class TestRevenueSummary422:
    def test_malformed_date_returns_422(self) -> None:
        r = _stats_client().get(_URL + "?date=pas-une-date", headers=_auth_header("MANAGER"))
        assert r.status_code == 422

    def test_partial_date_returns_422(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08", headers=_auth_header("MANAGER"))
        assert r.status_code == 422

    def test_invalid_month_returns_422(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-13-01", headers=_auth_header("MANAGER"))
        assert r.status_code == 422

    def test_invalid_day_returns_422(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-02-30", headers=_auth_header("MANAGER"))
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# 401 — jeton absent ou invalide
# ---------------------------------------------------------------------------


class TestRevenueSummary401:
    def test_no_token_returns_401(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02")
        assert r.status_code == 401

    def test_invalid_token_returns_401(self) -> None:
        r = _stats_client().get(
            _URL + "?date=2026-08-02",
            headers={"Authorization": "Bearer malformed.token.value"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — rôles sans STATS_READ_SALON ou gérant hors portée
# ---------------------------------------------------------------------------


class TestRevenueSummary403:
    def test_client_role_returns_403(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("CLIENT"))
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("HAIRDRESSER"))
        assert r.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        """ADMIN dispose de STATS_READ_PLATFORM mais pas de STATS_READ_SALON (#40)."""
        r = _stats_client().get(_URL + "?date=2026-08-02", headers=_auth_header("ADMIN"))
        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        """Gérant hors portée → 403 générique, indiscernable d'une ressource inexistante."""
        # `_OTHER_MANAGER_ID` n'a aucun salon dans sa portée
        other_token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        scope = FakeSalonScopeRepository({_OTHER_MANAGER_ID: frozenset()})
        r = _stats_client(manager_scope=scope).get(
            _URL + "?date=2026-08-02",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 403

    def test_manager_with_different_salon_scope_returns_403(self) -> None:
        """Gérant ayant accès à un autre salon mais pas `_SALON_ID` → 403."""
        other_token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        # Portée contient `_OTHER_SALON_ID` seulement, pas `_SALON_ID`
        scope = FakeSalonScopeRepository({_OTHER_MANAGER_ID: frozenset({_OTHER_SALON_ID})})
        r = _stats_client(manager_scope=scope).get(
            _URL + "?date=2026-08-02",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Dates limites : semaine à cheval sur deux années, février bissextile
# ---------------------------------------------------------------------------


class TestRevenueSummaryEdgeDates:
    """Bornes de période aux dates limites — vérifiées à l'API sans I/O réelle."""

    def test_cross_year_week_bounds(self) -> None:
        """2025-12-31 (mer) → semaine lundi 29/12/2025 → dim 04/01/2026."""
        r = _stats_client().get(_URL + "?date=2025-12-31", headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        data = r.json()
        assert data["week"]["date_from"] == "2025-12-29"
        assert data["week"]["date_to"] == "2026-01-04"

    def test_leap_year_february_month_bounds(self) -> None:
        """2028-02-29 (29 fév. bissextile) → mois fév. 2028 (01 → 29), pas d'erreur."""
        r = _stats_client().get(_URL + "?date=2028-02-29", headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        data = r.json()
        assert data["month"]["date_from"] == "2028-02-01"
        assert data["month"]["date_to"] == "2028-02-29"

    def test_first_day_of_month_is_its_own_lower_bound(self) -> None:
        """1er août 2026 → day=(01,01), mois commence ce jour et finit le 31."""
        r = _stats_client().get(_URL + "?date=2026-08-01", headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        data = r.json()
        assert data["day"]["date_from"] == "2026-08-01"
        assert data["day"]["date_to"] == "2026-08-01"
        assert data["month"]["date_from"] == "2026-08-01"
        assert data["month"]["date_to"] == "2026-08-31"

    def test_cross_year_month_bounds(self) -> None:
        """2025-12-31 → mois décembre 2025 (01/12 → 31/12)."""
        r = _stats_client().get(_URL + "?date=2025-12-31", headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        data = r.json()
        assert data["month"]["date_from"] == "2025-12-01"
        assert data["month"]["date_to"] == "2025-12-31"

    def test_non_leap_february_returns_28(self) -> None:
        """2026-02-28 → mois fév. 2026 non bissextile (01 → 28)."""
        r = _stats_client().get(_URL + "?date=2026-02-28", headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        data = r.json()
        assert data["month"]["date_to"] == "2026-02-28"


# ---------------------------------------------------------------------------
# Isolation — salon_id du chemin transmis au dépôt (§11.2, défense en profondeur)
# ---------------------------------------------------------------------------


class _TrackingSalonRepo(FakeRevenueJournalRepository):
    """Variant du fake qui enregistre le `salon_id` reçu par `net_revenue_between`."""

    def __init__(self) -> None:
        super().__init__()
        self.salon_ids_received: list[uuid.UUID] = []

    def net_revenue_between(self, salon_id, *, created_at_from, created_at_to):  # type: ignore[no-untyped-def]
        self.salon_ids_received.append(salon_id)
        return decimal.Decimal("0.00")


class TestRevenueSummaryIsolation:
    """Le `salon_id` de l'URL est transmis au dépôt (§11.2, défense en profondeur SQL)."""

    def test_salon_id_forwarded_to_repository_three_times(self) -> None:
        """net_revenue_between reçoit le bon salon_id pour chacune des trois périodes."""
        tracking = _TrackingSalonRepo()
        r = _stats_client(revenue_repo=tracking).get(
            _URL + "?date=2026-08-02", headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        assert len(tracking.salon_ids_received) == 3
        for sid in tracking.salon_ids_received:
            assert sid == _SALON_ID

    def test_salon_id_is_not_other_salon_id(self) -> None:
        """Le salon_id transmis au dépôt est celui de l'URL, jamais `_OTHER_SALON_ID`."""
        tracking = _TrackingSalonRepo()
        _stats_client(revenue_repo=tracking).get(
            _URL + "?date=2026-08-02", headers=_auth_header("MANAGER")
        )
        for sid in tracking.salon_ids_received:
            assert sid != _OTHER_SALON_ID


# ---------------------------------------------------------------------------
# Types d'opération inclus dans le CA (constante du dépôt — spec §Open Questions 3)
# ---------------------------------------------------------------------------


class TestRevenueOperationTypes:
    """La constante `_REVENUE_OPERATION_TYPES` inclut PAYMENT/ADJUSTMENT et exclut
    les types hors-CA (REFUND, CASH_OPENING, CASH_CLOSING — spec §Open Questions 3)."""

    def test_payment_included_in_revenue_types(self) -> None:
        from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
            _REVENUE_OPERATION_TYPES,
        )
        from coiflink_api.domain.enums import CashOperationType

        assert CashOperationType.PAYMENT.value in _REVENUE_OPERATION_TYPES

    def test_adjustment_included_in_revenue_types(self) -> None:
        from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
            _REVENUE_OPERATION_TYPES,
        )
        from coiflink_api.domain.enums import CashOperationType

        assert CashOperationType.ADJUSTMENT.value in _REVENUE_OPERATION_TYPES

    def test_refund_excluded_from_revenue_types(self) -> None:
        from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
            _REVENUE_OPERATION_TYPES,
        )
        from coiflink_api.domain.enums import CashOperationType

        assert CashOperationType.REFUND.value not in _REVENUE_OPERATION_TYPES

    def test_cash_opening_excluded_from_revenue_types(self) -> None:
        from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
            _REVENUE_OPERATION_TYPES,
        )
        from coiflink_api.domain.enums import CashOperationType

        assert CashOperationType.CASH_OPENING.value not in _REVENUE_OPERATION_TYPES

    def test_cash_closing_excluded_from_revenue_types(self) -> None:
        from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
            _REVENUE_OPERATION_TYPES,
        )
        from coiflink_api.domain.enums import CashOperationType

        assert CashOperationType.CASH_CLOSING.value not in _REVENUE_OPERATION_TYPES

    def test_exactly_two_types_in_revenue_types(self) -> None:
        """Seuls PAYMENT et ADJUSTMENT font partie du CA (spec §Open Questions 3)."""
        from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
            _REVENUE_OPERATION_TYPES,
        )

        assert len(_REVENUE_OPERATION_TYPES) == 2
