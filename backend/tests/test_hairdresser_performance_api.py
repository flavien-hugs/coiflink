"""Tests API — `GET /salons/{salon_id}/hairdresser-performance` (US-6.5, #43).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_appointment_repository`  → `FakeHairdresserPerformanceAppointmentRepo` ;
- `get_cash_journal_repository` → `FakeHairdresserPerformanceCashRepo` ;
- `get_user_repository`         → `FakeAuthUserRepository` (toutes les clés de rôle) ;
- `get_access_policy`           → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 : structure attendue (`currency`, `date_from`, `date_to`, `hairdressers`) ;
  liste vide si aucun coiffeur assigné (état vide légitime) ;
  `revenue` et `cancellation_rate` en chaîne décimale (jamais un flottant) ;
- **défaut de période** : sans `date_from`/`date_to` → backend applique le mois
  civil courant (bornes non nulles) ; une seule borne fournie → mois courant ;
- **bornes explicites** : transmises et répercutées dans la réponse ;
- **non-PII (§11.3)** : réponse sans `client_id`, `phone`, `email`, `role`
  d'employé ; seul `hairdresser_id` + `hairdresser_name` autorisés comme identité
  (endpoint nominatif) ;
- schéma top-level et par item : clés autorisées uniquement ;
- route absente de `PUBLIC_ROUTE_PATHS` ;
- **non-collision de routage** : `hairdresser-performance` n'est pas un UUID ;
- **isolation** : `salon_id` de l'URL transmis aux deux dépôts (§11.2) ;
- **statuts serveur** : `REVENUE_STATUSES` et `CANCELLED_STATUSES` imposés
  (jamais soumis par l'appelant) ;
- 422 : `date_to < date_from`, dates malformées ;
- 401 : jeton absent ou invalide ;
- 403 : CLIENT, HAIRDRESSER, ADMIN ; gérant hors portée → 403 générique.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator, Mapping

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.inbound.stats import (
    get_appointment_repository,
    get_cash_journal_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.appointment import CANCELLED_STATUSES, REVENUE_STATUSES
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.hairdresser_performance import HairdresserActivityCounts
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
_HAIRDRESSER_USER_ID = uuid.UUID("cc111111-0000-0000-0000-000000000022")
_OTHER_MANAGER_ID = uuid.UUID("dd111111-0000-0000-0000-000000000033")

_SALON_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000002")

_H_ID_1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
_H_ID_2 = uuid.UUID("22222222-0000-0000-0000-000000000002")

_ROLE_USER_IDS: dict[str, uuid.UUID] = {
    "CLIENT": _CLIENT_ID,
    "MANAGER": _MANAGER_ID,
    "ADMIN": _ADMIN_ID,
    "HAIRDRESSER": _HAIRDRESSER_USER_ID,
}

_URL = f"/salons/{_SALON_ID}/hairdresser-performance"


# ---------------------------------------------------------------------------
# Fake AppointmentRepository (hairdresser-performance)
# ---------------------------------------------------------------------------


class FakeHairdresserPerformanceAppointmentRepo:
    """Fake du port `AppointmentRepository` pour la route hairdresser-performance (#43).

    `counts` contrôle ce que `performance_by_hairdresser` renvoie.
    `calls` enregistre les arguments reçus.
    """

    def __init__(
        self,
        counts: tuple[HairdresserActivityCounts, ...] = (),
    ) -> None:
        self._counts = counts
        self.calls: list[dict] = []

    def performance_by_hairdresser(  # type: ignore[no-untyped-def]
        self,
        salon_id,
        *,
        date_from,
        date_to,
        completed_statuses,
        cancelled_statuses,
    ):
        self.calls.append(
            {
                "salon_id": salon_id,
                "date_from": date_from,
                "date_to": date_to,
                "completed_statuses": completed_statuses,
                "cancelled_statuses": cancelled_statuses,
            }
        )
        return self._counts

    def demand_by_service(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def segment_active_clients(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_by_status_for_day(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def booked_slots(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def create(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_owned(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def update(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def cancel(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_in_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def set_status(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def assign_hairdresser(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_client(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_hairdresser(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fake CashJournalRepository (hairdresser-performance)
# ---------------------------------------------------------------------------


class FakeHairdresserPerformanceCashRepo:
    """Fake du port `CashJournalRepository` pour la route hairdresser-performance (#43).

    `revenue_map` contrôle ce que `net_revenue_by_hairdresser` renvoie.
    `calls` enregistre les arguments reçus.
    """

    def __init__(
        self,
        revenue_map: Mapping[uuid.UUID, decimal.Decimal] | None = None,
    ) -> None:
        self._revenue_map: Mapping[uuid.UUID, decimal.Decimal] = revenue_map or {}
        self.calls: list[dict] = []

    def net_revenue_by_hairdresser(  # type: ignore[no-untyped-def]
        self, salon_id, *, date_from, date_to
    ):
        self.calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to}
        )
        return self._revenue_map

    def append(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def net_revenue_between(self, *a, **kw):  # type: ignore[no-untyped-def]
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
    creds = {str(uid): _creds(uid, role) for role, uid in _ROLE_USER_IDS.items()}
    creds[str(_OTHER_MANAGER_ID)] = _creds(_OTHER_MANAGER_ID, Role.MANAGER.value)
    return FakeAuthUserRepository(credentials_by_id=creds)


def _auth_header(role: str) -> dict[str, str]:
    user_id = _ROLE_USER_IDS.get(role, uuid.uuid4())
    token = make_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


def _perf_client(
    appt_repo: FakeHairdresserPerformanceAppointmentRepo | None = None,
    cash_repo: FakeHairdresserPerformanceCashRepo | None = None,
    manager_scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient MANAGER avec `_SALON_ID` dans sa portée (US-6.5, #43)."""
    ar = appt_repo or FakeHairdresserPerformanceAppointmentRepo()
    cr = cash_repo or FakeHairdresserPerformanceCashRepo()
    scope = (
        manager_scope
        if manager_scope is not None
        else FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_appointment_repository] = lambda: ar
    app.dependency_overrides[get_cash_journal_repository] = lambda: cr
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope)
    return TestClient(app)


def _counts(
    hairdresser_id: uuid.UUID = _H_ID_1,
    name: str = "Awa Koné",
    services_completed: int = 10,
    cancelled_count: int = 2,
    total_count: int = 20,
) -> HairdresserActivityCounts:
    return HairdresserActivityCounts(
        hairdresser_id=hairdresser_id,
        name=name,
        services_completed=services_completed,
        cancelled_count=cancelled_count,
        total_count=total_count,
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


@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.pop(get_appointment_repository, None)
    app.dependency_overrides.pop(get_cash_journal_repository, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# 200 — structure de la réponse
# ---------------------------------------------------------------------------


class TestHairdresserPerformance200:
    def test_returns_200(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_response_has_currency(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "currency" in r.json()

    def test_response_currency_is_xof(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["currency"] == "XOF"

    def test_response_has_date_from(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "date_from" in r.json()

    def test_response_has_date_to(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "date_to" in r.json()

    def test_response_has_hairdressers_key(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "hairdressers" in r.json()

    def test_hairdressers_is_list(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert isinstance(r.json()["hairdressers"], list)

    def test_empty_hairdressers_list_is_legitimate(self) -> None:
        """Aucun coiffeur assigné → liste vide (état vide légitime, ≠ erreur)."""
        r = _perf_client(FakeHairdresserPerformanceAppointmentRepo(counts=())).get(
            _URL, headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        assert r.json()["hairdressers"] == []

    def test_one_hairdresser_in_list(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert len(r.json()["hairdressers"]) == 1

    def test_hairdresser_item_has_hairdresser_id(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert "hairdresser_id" in r.json()["hairdressers"][0]

    def test_hairdresser_item_has_hairdresser_name(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert "hairdresser_name" in r.json()["hairdressers"][0]

    def test_hairdresser_name_value_correct(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(name="Mariame"),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["hairdressers"][0]["hairdresser_name"] == "Mariame"

    def test_revenue_is_decimal_string(self) -> None:
        """Le CA est sérialisé en chaîne décimale, jamais en flottant JS."""
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(),))
        cr = FakeHairdresserPerformanceCashRepo(
            revenue_map={_H_ID_1: decimal.Decimal("75000.00")}
        )
        r = _perf_client(ar, cr).get(_URL, headers=_auth_header("MANAGER"))
        assert isinstance(r.json()["hairdressers"][0]["revenue"], str)

    def test_cancellation_rate_is_decimal_string(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert isinstance(r.json()["hairdressers"][0]["cancellation_rate"], str)

    def test_services_completed_is_integer(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(services_completed=42),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert isinstance(r.json()["hairdressers"][0]["services_completed"], int)

    def test_services_completed_value_correct(self) -> None:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(services_completed=42),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["hairdressers"][0]["services_completed"] == 42


# ---------------------------------------------------------------------------
# Défaut de période — mois civil courant
# ---------------------------------------------------------------------------


class TestHairdresserPerformanceDefaultPeriod:
    def test_without_params_returns_200(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_without_params_date_from_not_null(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["date_from"] is not None

    def test_without_params_date_to_not_null(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["date_to"] is not None

    def test_only_date_from_falls_back_to_current_month(self) -> None:
        r = _perf_client().get(
            _URL + "?date_from=2026-08-01", headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        assert r.json()["date_from"] is not None
        assert r.json()["date_to"] is not None

    def test_only_date_to_falls_back_to_current_month(self) -> None:
        r = _perf_client().get(
            _URL + "?date_to=2026-08-31", headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        assert r.json()["date_from"] is not None
        assert r.json()["date_to"] is not None

    def test_explicit_dates_echoed_in_response(self) -> None:
        r = _perf_client().get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        data = r.json()
        assert data["date_from"] == "2026-08-01"
        assert data["date_to"] == "2026-08-31"


# ---------------------------------------------------------------------------
# Non-PII (§11.3) — schéma figé, champs interdits absents
# ---------------------------------------------------------------------------


class TestHairdresserPerformanceNonPII:
    def _data_with_one_entry(self) -> dict:
        ar = FakeHairdresserPerformanceAppointmentRepo(counts=(_counts(),))
        r = _perf_client(ar).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        return r.json()

    def test_only_expected_top_level_keys(self) -> None:
        allowed = {"currency", "date_from", "date_to", "hairdressers"}
        extra = set(self._data_with_one_entry().keys()) - allowed
        assert extra == set(), f"Champs inattendus en racine : {extra}"

    def test_hairdresser_item_only_expected_keys(self) -> None:
        allowed = {
            "hairdresser_id", "hairdresser_name", "services_completed",
            "revenue", "cancelled_count", "total_count", "cancellation_rate",
        }
        item = self._data_with_one_entry()["hairdressers"][0]
        extra = set(item.keys()) - allowed
        assert extra == set(), f"Champs inattendus dans l'item coiffeur : {extra}"

    def test_no_client_id_in_response(self) -> None:
        assert "client_id" not in self._data_with_one_entry()

    def test_no_phone_in_hairdresser_item(self) -> None:
        item = self._data_with_one_entry()["hairdressers"][0]
        assert "phone" not in item

    def test_no_email_in_hairdresser_item(self) -> None:
        item = self._data_with_one_entry()["hairdressers"][0]
        assert "email" not in item

    def test_no_role_in_hairdresser_item(self) -> None:
        item = self._data_with_one_entry()["hairdressers"][0]
        assert "role" not in item

    def test_no_appointment_id_in_response(self) -> None:
        assert "appointment_id" not in self._data_with_one_entry()

    def test_no_recorded_by_in_response(self) -> None:
        assert "recorded_by" not in self._data_with_one_entry()

    def test_no_reference_in_response(self) -> None:
        assert "reference" not in self._data_with_one_entry()


# ---------------------------------------------------------------------------
# Route absente de PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestHairdresserPerformanceRouteProtection:
    def test_hairdresser_performance_not_in_public_route_paths(self) -> None:
        for public_path in PUBLIC_ROUTE_PATHS:
            assert "hairdresser-performance" not in public_path, (
                f"hairdresser-performance trouvé dans PUBLIC_ROUTE_PATHS : {public_path}"
            )


# ---------------------------------------------------------------------------
# Non-collision de routage
# ---------------------------------------------------------------------------


class TestHairdresserPerformanceRouteNoCollision:
    def test_segment_not_parsed_as_uuid(self) -> None:
        """Le segment 'hairdresser-performance' n'est pas un UUID : 401 ou 403 attendu."""
        r = _perf_client().get(_URL)  # sans jeton → 401
        assert r.status_code in (401, 403), (
            f"Attendu 401/403 (route résolue), obtenu {r.status_code} "
            "(possible collision de routage)"
        )
        assert r.status_code != 422


# ---------------------------------------------------------------------------
# 422 — paramètres mal formés ou incohérents
# ---------------------------------------------------------------------------


class TestHairdresserPerformance422:
    def test_date_to_before_date_from_returns_422(self) -> None:
        r = _perf_client().get(
            _URL + "?date_from=2026-08-31&date_to=2026-08-01",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_malformed_date_from_returns_422(self) -> None:
        r = _perf_client().get(
            _URL + "?date_from=pas-une-date&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_malformed_date_to_returns_422(self) -> None:
        r = _perf_client().get(
            _URL + "?date_from=2026-08-01&date_to=2026-13-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_same_date_from_and_to_is_valid(self) -> None:
        r = _perf_client().get(
            _URL + "?date_from=2026-08-15&date_to=2026-08-15",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 401 — jeton absent ou invalide
# ---------------------------------------------------------------------------


class TestHairdresserPerformance401:
    def test_no_token_returns_401(self) -> None:
        r = _perf_client().get(_URL)
        assert r.status_code == 401

    def test_invalid_token_returns_401(self) -> None:
        r = _perf_client().get(
            _URL,
            headers={"Authorization": "Bearer malformed.token.value"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — rôles sans STATS_READ_SALON ou gérant hors portée
# ---------------------------------------------------------------------------


class TestHairdresserPerformance403:
    def test_client_role_returns_403(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("CLIENT"))
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        r = _perf_client().get(_URL, headers=_auth_header("HAIRDRESSER"))
        assert r.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        """ADMIN dispose de STATS_READ_PLATFORM mais pas de STATS_READ_SALON (#43)."""
        r = _perf_client().get(_URL, headers=_auth_header("ADMIN"))
        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        """Gérant hors portée → 403 générique, indiscernable d'une ressource inexistante."""
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        scope = FakeSalonScopeRepository({_OTHER_MANAGER_ID: frozenset()})
        r = _perf_client(manager_scope=scope).get(
            _URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_manager_with_other_salon_returns_403(self) -> None:
        """Gérant ayant accès à un autre salon mais pas `_SALON_ID` → 403."""
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        scope = FakeSalonScopeRepository(
            {_OTHER_MANAGER_ID: frozenset({_OTHER_SALON_ID})}
        )
        r = _perf_client(manager_scope=scope).get(
            _URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Isolation — salon_id transmis aux deux dépôts (§11.2)
# ---------------------------------------------------------------------------


class _TrackingAppointmentRepo(FakeHairdresserPerformanceAppointmentRepo):
    def __init__(self) -> None:
        super().__init__()
        self.salon_ids_received: list[uuid.UUID] = []

    def performance_by_hairdresser(  # type: ignore[no-untyped-def]
        self, salon_id, *, date_from, date_to, completed_statuses, cancelled_statuses
    ):
        self.salon_ids_received.append(salon_id)
        return ()


class _TrackingCashRepo(FakeHairdresserPerformanceCashRepo):
    def __init__(self) -> None:
        super().__init__()
        self.salon_ids_received: list[uuid.UUID] = []

    def net_revenue_by_hairdresser(  # type: ignore[no-untyped-def]
        self, salon_id, *, date_from, date_to
    ):
        self.salon_ids_received.append(salon_id)
        return {}


class TestHairdresserPerformanceIsolation:
    def test_salon_id_forwarded_to_appointment_repo(self) -> None:
        tracking = _TrackingAppointmentRepo()
        r = _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        assert len(tracking.salon_ids_received) == 1
        assert tracking.salon_ids_received[0] == _SALON_ID

    def test_salon_id_forwarded_to_cash_repo(self) -> None:
        tracking_cash = _TrackingCashRepo()
        r = _perf_client(cash_repo=tracking_cash).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        assert len(tracking_cash.salon_ids_received) == 1
        assert tracking_cash.salon_ids_received[0] == _SALON_ID

    def test_appointment_repo_does_not_receive_other_salon_id(self) -> None:
        tracking = _TrackingAppointmentRepo()
        _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        for sid in tracking.salon_ids_received:
            assert sid != _OTHER_SALON_ID

    def test_cash_repo_does_not_receive_other_salon_id(self) -> None:
        tracking_cash = _TrackingCashRepo()
        _perf_client(cash_repo=tracking_cash).get(_URL, headers=_auth_header("MANAGER"))
        for sid in tracking_cash.salon_ids_received:
            assert sid != _OTHER_SALON_ID


# ---------------------------------------------------------------------------
# Statuts imposés serveur
# ---------------------------------------------------------------------------


class _TrackingStatusesRepo(FakeHairdresserPerformanceAppointmentRepo):
    def __init__(self) -> None:
        super().__init__()
        self.completed_statuses_received: list = []
        self.cancelled_statuses_received: list = []

    def performance_by_hairdresser(  # type: ignore[no-untyped-def]
        self, salon_id, *, date_from, date_to, completed_statuses, cancelled_statuses
    ):
        self.completed_statuses_received.append(completed_statuses)
        self.cancelled_statuses_received.append(cancelled_statuses)
        return ()


class TestHairdresserPerformanceStatusFilter:
    def test_revenue_statuses_forwarded(self) -> None:
        """REVENUE_STATUSES (COMPLETED) transmis au port — jamais soumis par l'appelant."""
        tracking = _TrackingStatusesRepo()
        _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert len(tracking.completed_statuses_received) == 1
        assert tracking.completed_statuses_received[0] == REVENUE_STATUSES

    def test_completed_in_revenue_statuses(self) -> None:
        tracking = _TrackingStatusesRepo()
        _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert "COMPLETED" in tracking.completed_statuses_received[0]

    def test_cancelled_statuses_forwarded(self) -> None:
        tracking = _TrackingStatusesRepo()
        _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert len(tracking.cancelled_statuses_received) == 1
        assert tracking.cancelled_statuses_received[0] == CANCELLED_STATUSES

    def test_cancelled_in_cancelled_statuses(self) -> None:
        tracking = _TrackingStatusesRepo()
        _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert "CANCELLED" in tracking.cancelled_statuses_received[0]


# ---------------------------------------------------------------------------
# Bornes de période transmises aux deux dépôts
# ---------------------------------------------------------------------------


class _TrackingDatesAppointmentRepo(FakeHairdresserPerformanceAppointmentRepo):
    def __init__(self) -> None:
        super().__init__()
        self.date_from_received: list = []
        self.date_to_received: list = []

    def performance_by_hairdresser(  # type: ignore[no-untyped-def]
        self, salon_id, *, date_from, date_to, completed_statuses, cancelled_statuses
    ):
        self.date_from_received.append(date_from)
        self.date_to_received.append(date_to)
        return ()


class TestHairdresserPerformanceDateBounds:
    def test_date_from_forwarded_to_appointment_port(self) -> None:
        tracking = _TrackingDatesAppointmentRepo()
        _perf_client(tracking).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert tracking.date_from_received[0] == datetime.date(2026, 8, 1)

    def test_date_to_forwarded_to_appointment_port(self) -> None:
        tracking = _TrackingDatesAppointmentRepo()
        _perf_client(tracking).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert tracking.date_to_received[0] == datetime.date(2026, 8, 31)

    def test_without_dates_port_receives_non_null_bounds(self) -> None:
        """Sans paramètres → les deux bornes du mois courant sont transmises."""
        tracking = _TrackingDatesAppointmentRepo()
        _perf_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert tracking.date_from_received[0] is not None
        assert tracking.date_to_received[0] is not None
