"""Tests API — `GET /salons/{salon_id}/service-demand` (US-6.3, #41).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_appointment_repository` → `FakeServiceDemandRepo` ;
- `get_user_repository` → `FakeAuthUserRepository` (toutes les clés de rôle) ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 : structure attendue (`currency`, `date_from`, `date_to`, `by_volume`,
  `by_revenue`) ; `revenue` en chaîne décimale ; classements vides si aucun RDV
  réalisé ; les deux classements présents ;
- **non-PII (§11.3)** : seules les clés autorisées sont présentes (`client_id`,
  `appointment_id` interdits à tous les niveaux) ;
- **filtre de statut** : `REVENUE_STATUSES` (`COMPLETED`) passé au port ;
- **bornes de période** : `date_from`/`date_to` transmis ; `date_to < date_from` →
  422 ; date mal formée → 422 ; sans bornes → `None` transmis au port ;
- route absente de `PUBLIC_ROUTE_PATHS` (donnée d'exploitation salon) ;
- **non-collision de routage** : `service-demand` n'est pas parsé comme un UUID ;
- 401 : jeton absent ou invalide ;
- 403 : CLIENT, HAIRDRESSER, ADMIN, gérant hors portée ;
- **isolation** : `salon_id` de l'URL transmis au dépôt (§11.2).
"""

from __future__ import annotations

import datetime
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
from coiflink_api.adapters.inbound.stats import get_appointment_repository
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.appointment import REVENUE_STATUSES
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.service_demand import ServiceDemand
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

_URL = f"/salons/{_SALON_ID}/service-demand"

_SVC_A = ServiceDemand(
    service_id=uuid.UUID("a1a1a1a1-0000-0000-0000-000000000001"),
    name="Coupe homme",
    volume=42,
    revenue=decimal.Decimal("210000.00"),
)
_SVC_B = ServiceDemand(
    service_id=uuid.UUID("b2b2b2b2-0000-0000-0000-000000000002"),
    name="Barbe",
    volume=30,
    revenue=decimal.Decimal("60000.00"),
)


# ---------------------------------------------------------------------------
# Fake AppointmentRepository (service-demand only)
# ---------------------------------------------------------------------------


class FakeServiceDemandRepo:
    """Fake du port `AppointmentRepository` pour la route service-demand (#41) — aucun I/O.

    `results` contrôle ce que `demand_by_service` renvoie ; `calls` enregistre les
    arguments reçus. Les méthodes de mutation lèvent `NotImplementedError`.
    """

    def __init__(self, results: tuple[ServiceDemand, ...] = ()) -> None:
        self._results = results
        self.calls: list[dict] = []

    def demand_by_service(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from=None, date_to=None
    ):
        self.calls.append(
            {
                "salon_id": salon_id,
                "statuses": statuses,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return self._results

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


def _demand_client(
    repo: FakeServiceDemandRepo | None = None,
    manager_scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient MANAGER avec `_SALON_ID` dans sa portée (US-6.3, #41)."""
    r = repo if repo is not None else FakeServiceDemandRepo()
    scope = (
        manager_scope
        if manager_scope is not None
        else FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_appointment_repository] = lambda: r
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
    app.dependency_overrides.pop(get_appointment_repository, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# 200 — structure de la réponse
# ---------------------------------------------------------------------------


class TestServiceDemand200:
    def test_returns_200(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_response_has_currency_xof(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["currency"] == "XOF"

    def test_response_has_by_volume_key(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "by_volume" in r.json()

    def test_response_has_by_revenue_key(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "by_revenue" in r.json()

    def test_date_from_null_when_no_params(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["date_from"] is None

    def test_date_to_null_when_no_params(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["date_to"] is None

    def test_revenue_is_string_in_by_volume(self) -> None:
        """Pydantic sérialise `Decimal` en chaîne — jamais un flottant (§11.3)."""
        repo = FakeServiceDemandRepo(results=(_SVC_A,))
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        items = r.json()["by_volume"]
        assert len(items) == 1
        assert isinstance(items[0]["revenue"], str)

    def test_revenue_value_in_by_volume(self) -> None:
        repo = FakeServiceDemandRepo(results=(_SVC_A,))
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["by_volume"][0]["revenue"] == "210000.00"

    def test_by_volume_item_has_expected_fields(self) -> None:
        repo = FakeServiceDemandRepo(results=(_SVC_A,))
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        item = r.json()["by_volume"][0]
        for field in ("service_id", "name", "volume", "revenue"):
            assert field in item, f"champ manquant dans by_volume[0] : {field}"

    def test_volume_is_int_in_by_volume(self) -> None:
        repo = FakeServiceDemandRepo(results=(_SVC_A,))
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        assert isinstance(r.json()["by_volume"][0]["volume"], int)

    def test_empty_lists_when_no_completed_appointments(self) -> None:
        """Aucun RDV réalisé → classements vides (état légitime, ≠ erreur)."""
        repo = FakeServiceDemandRepo(results=())
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        assert r.json()["by_volume"] == []
        assert r.json()["by_revenue"] == []

    def test_both_classements_present_with_data(self) -> None:
        repo = FakeServiceDemandRepo(results=(_SVC_A, _SVC_B))
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        assert len(r.json()["by_volume"]) == 2
        assert len(r.json()["by_revenue"]) == 2


# ---------------------------------------------------------------------------
# Non-PII (§11.3)
# ---------------------------------------------------------------------------


class TestServiceDemandNonPII:
    def _data(self) -> dict:
        repo = FakeServiceDemandRepo(results=(_SVC_A,))
        r = _demand_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        return r.json()

    def test_only_expected_top_level_keys(self) -> None:
        """Seuls `currency`, `date_from`, `date_to`, `by_volume`, `by_revenue` autorisés."""
        allowed = {"currency", "date_from", "date_to", "by_volume", "by_revenue"}
        extra = set(self._data().keys()) - allowed
        assert extra == set(), f"Champs inattendus dans la réponse : {extra}"

    def test_no_client_id_in_root(self) -> None:
        assert "client_id" not in self._data()

    def test_no_appointment_id_in_root(self) -> None:
        assert "appointment_id" not in self._data()

    def test_by_volume_items_have_only_allowed_keys(self) -> None:
        allowed = {"service_id", "name", "volume", "revenue"}
        for item in self._data()["by_volume"]:
            extra = set(item.keys()) - allowed
            assert extra == set(), f"Champs inattendus dans by_volume[] : {extra}"

    def test_by_revenue_items_have_only_allowed_keys(self) -> None:
        allowed = {"service_id", "name", "volume", "revenue"}
        for item in self._data()["by_revenue"]:
            extra = set(item.keys()) - allowed
            assert extra == set(), f"Champs inattendus dans by_revenue[] : {extra}"

    def test_no_client_id_in_by_volume_items(self) -> None:
        for item in self._data()["by_volume"]:
            assert "client_id" not in item

    def test_no_appointment_id_in_by_volume_items(self) -> None:
        for item in self._data()["by_volume"]:
            assert "appointment_id" not in item


# ---------------------------------------------------------------------------
# Route absente de PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestServiceDemandRouteProtection:
    def test_service_demand_not_in_public_route_paths(self) -> None:
        """Les données d'exploitation du salon ne sont jamais publiques."""
        for public_path in PUBLIC_ROUTE_PATHS:
            assert "service-demand" not in public_path, (
                f"service-demand trouvé dans PUBLIC_ROUTE_PATHS : {public_path}"
            )


# ---------------------------------------------------------------------------
# Non-collision de routage
# ---------------------------------------------------------------------------


class TestServiceDemandRouteNoCollision:
    def test_service_demand_not_parsed_as_uuid(self) -> None:
        """Le segment 'service-demand' n'est pas parsé comme un {service_id} UUID.

        Un 401 ou 403 (garde auth) prouve que le routeur a résolu la route
        correctement. Un 422 indiquerait une collision avec `/{salon_id}/services/{id}`.
        """
        r = _demand_client().get(_URL)  # sans jeton → 401
        assert r.status_code in (401, 403), (
            f"Attendu 401/403 (route résolue), obtenu {r.status_code} "
            "(possible collision de routage)"
        )
        assert r.status_code != 422, (
            "422 indique un possible parsing UUID du segment 'service-demand'"
        )


# ---------------------------------------------------------------------------
# 422 — paramètres mal formés ou incohérents
# ---------------------------------------------------------------------------


class TestServiceDemand422:
    def test_date_to_before_date_from_returns_422(self) -> None:
        r = _demand_client().get(
            _URL + "?date_from=2026-08-31&date_to=2026-08-01",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_malformed_date_from_returns_422(self) -> None:
        r = _demand_client().get(
            _URL + "?date_from=pas-une-date",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_malformed_date_to_returns_422(self) -> None:
        r = _demand_client().get(
            _URL + "?date_to=2026-13-01",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_same_date_from_and_to_is_valid(self) -> None:
        """date_from == date_to est valide (plage d'un jour)."""
        r = _demand_client().get(
            _URL + "?date_from=2026-08-02&date_to=2026-08-02",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 401 — jeton absent ou invalide
# ---------------------------------------------------------------------------


class TestServiceDemand401:
    def test_no_token_returns_401(self) -> None:
        r = _demand_client().get(_URL)
        assert r.status_code == 401

    def test_invalid_token_returns_401(self) -> None:
        r = _demand_client().get(
            _URL,
            headers={"Authorization": "Bearer malformed.token.value"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — rôles sans STATS_READ_SALON ou gérant hors portée
# ---------------------------------------------------------------------------


class TestServiceDemand403:
    def test_client_role_returns_403(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("CLIENT"))
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        r = _demand_client().get(_URL, headers=_auth_header("HAIRDRESSER"))
        assert r.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        """ADMIN dispose de STATS_READ_PLATFORM mais pas de STATS_READ_SALON (#41)."""
        r = _demand_client().get(_URL, headers=_auth_header("ADMIN"))
        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        """Gérant hors portée → 403 indiscernable (aucun oracle d'existence)."""
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        scope = FakeSalonScopeRepository({_OTHER_MANAGER_ID: frozenset()})
        r = _demand_client(manager_scope=scope).get(
            _URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_manager_with_other_salon_returns_403(self) -> None:
        """Gérant ayant accès à un autre salon mais pas `_SALON_ID` → 403."""
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        scope = FakeSalonScopeRepository({_OTHER_MANAGER_ID: frozenset({_OTHER_SALON_ID})})
        r = _demand_client(manager_scope=scope).get(
            _URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Isolation — salon_id transmis au dépôt (§11.2)
# ---------------------------------------------------------------------------


class _TrackingSalonRepo(FakeServiceDemandRepo):
    def __init__(self) -> None:
        super().__init__()
        self.salon_ids_received: list[uuid.UUID] = []

    def demand_by_service(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from=None, date_to=None
    ):
        self.salon_ids_received.append(salon_id)
        return ()


class TestServiceDemandIsolation:
    def test_salon_id_forwarded_to_repository(self) -> None:
        """demand_by_service reçoit le salon_id de l'URL — défense en profondeur §11.2."""
        tracking = _TrackingSalonRepo()
        r = _demand_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        assert len(tracking.salon_ids_received) == 1
        assert tracking.salon_ids_received[0] == _SALON_ID

    def test_salon_id_is_not_other_salon(self) -> None:
        tracking = _TrackingSalonRepo()
        _demand_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        for sid in tracking.salon_ids_received:
            assert sid != _OTHER_SALON_ID


# ---------------------------------------------------------------------------
# Filtre de statut — REVENUE_STATUSES imposé
# ---------------------------------------------------------------------------


class _TrackingStatusRepo(FakeServiceDemandRepo):
    def __init__(self) -> None:
        super().__init__()
        self.statuses_received: list = []

    def demand_by_service(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from=None, date_to=None
    ):
        self.statuses_received.append(statuses)
        return ()


class TestServiceDemandStatusFilter:
    def test_revenue_statuses_forwarded(self) -> None:
        """Le port reçoit REVENUE_STATUSES (COMPLETED), jamais soumis par l'appelant."""
        tracking = _TrackingStatusRepo()
        _demand_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert len(tracking.statuses_received) == 1
        assert tracking.statuses_received[0] == REVENUE_STATUSES

    def test_completed_in_statuses(self) -> None:
        tracking = _TrackingStatusRepo()
        _demand_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert "COMPLETED" in tracking.statuses_received[0]


# ---------------------------------------------------------------------------
# Bornes de période — transmises au port
# ---------------------------------------------------------------------------


class _TrackingDatesRepo(FakeServiceDemandRepo):
    def __init__(self) -> None:
        super().__init__()
        self.date_from_received: list = []
        self.date_to_received: list = []

    def demand_by_service(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from=None, date_to=None
    ):
        self.date_from_received.append(date_from)
        self.date_to_received.append(date_to)
        return ()


class TestServiceDemandDateBounds:
    def test_date_from_forwarded_to_port(self) -> None:
        tracking = _TrackingDatesRepo()
        _demand_client(tracking).get(
            _URL + "?date_from=2026-08-01",
            headers=_auth_header("MANAGER"),
        )
        assert tracking.date_from_received[0] == datetime.date(2026, 8, 1)

    def test_date_to_forwarded_to_port(self) -> None:
        tracking = _TrackingDatesRepo()
        _demand_client(tracking).get(
            _URL + "?date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert tracking.date_to_received[0] == datetime.date(2026, 8, 31)

    def test_without_dates_none_forwarded(self) -> None:
        tracking = _TrackingDatesRepo()
        _demand_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert tracking.date_from_received[0] is None
        assert tracking.date_to_received[0] is None

    def test_date_from_echoed_in_response(self) -> None:
        """La borne `date_from` transmise est répercutée dans la réponse."""
        r = _demand_client().get(
            _URL + "?date_from=2026-08-01",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["date_from"] == "2026-08-01"

    def test_date_to_echoed_in_response(self) -> None:
        r = _demand_client().get(
            _URL + "?date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["date_to"] == "2026-08-31"
