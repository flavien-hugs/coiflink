"""Tests API — `GET /salons/{salon_id}/active-clients` (US-6.4, #42).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_appointment_repository` → `FakeActiveClientsRepo` ;
- `get_user_repository` → `FakeAuthUserRepository` (toutes les clés de rôle) ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- 200 : structure attendue (`date_from`, `date_to`, `new`, `recurring`,
  `inactive`, `active`) ; compteurs entiers ≥ 0 ; `active == new + recurring` ;
  salon sans RDV `COMPLETED` → tous les compteurs à 0 (état vide légitime) ;
- **défaut de période** : sans `date_from`/`date_to` → backend applique le
  mois civil courant (bornes non nulles dans la réponse) ; une seule borne
  fournie → retombe aussi sur le mois courant ;
- **bornes explicites** : transmises et répercutées dans la réponse ;
- **non-PII (§11.3)** : seules les clés autorisées sont présentes
  (`client_id`, `appointment_id`, noms interdits) ;
- **filtre de statut** : `HISTORY_STATUSES` (`COMPLETED`) passé au port ;
- route absente de `PUBLIC_ROUTE_PATHS` (donnée d'exploitation salon) ;
- **non-collision de routage** : `active-clients` n'est pas parsé comme un UUID ;
- 422 : `date_to < date_from`, date mal formée ;
- 401 : jeton absent ou invalide ;
- 403 : CLIENT, HAIRDRESSER, ADMIN (rôles sans `STATS_READ_SALON`) ;
        gérant hors portée → 403 générique (aucun oracle) ;
- **isolation** : `salon_id` de l'URL transmis au dépôt (§11.2, défense en
  profondeur SQL).
"""

from __future__ import annotations

import datetime
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
from coiflink_api.domain.client_segments import ClientVisitProfile
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.visit import HISTORY_STATUSES
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

_URL = f"/salons/{_SALON_ID}/active-clients"

# Profils représentatifs — sans `client_id` (anti-oracle §11.1/§11.3)
_PROFILE_NEW = ClientVisitProfile(
    first_visit=datetime.date(2026, 8, 15),
    visits_in_period=1,
    visits_before=0,
)
_PROFILE_RECURRING = ClientVisitProfile(
    first_visit=datetime.date(2026, 7, 1),
    visits_in_period=2,
    visits_before=3,
)
_PROFILE_INACTIVE = ClientVisitProfile(
    first_visit=datetime.date(2026, 6, 1),
    visits_in_period=0,
    visits_before=1,
)


# ---------------------------------------------------------------------------
# Fake AppointmentRepository (active-clients only)
# ---------------------------------------------------------------------------


class FakeActiveClientsRepo:
    """Fake du port `AppointmentRepository` pour la route active-clients (#42) — aucun I/O.

    `profiles` contrôle ce que `segment_active_clients` renvoie ; `calls`
    enregistre les arguments reçus. Les méthodes non utilisées lèvent
    `NotImplementedError`.
    """

    def __init__(
        self, profiles: tuple[ClientVisitProfile, ...] = ()
    ) -> None:
        self._profiles = profiles
        self.calls: list[dict] = []

    def segment_active_clients(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from, date_to
    ):
        self.calls.append(
            {
                "salon_id": salon_id,
                "statuses": statuses,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return self._profiles

    def demand_by_service(self, *a, **kw):  # type: ignore[no-untyped-def]
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


def _active_clients_client(
    repo: FakeActiveClientsRepo | None = None,
    manager_scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient MANAGER avec `_SALON_ID` dans sa portée (US-6.4, #42)."""
    r = repo if repo is not None else FakeActiveClientsRepo()
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


class TestActiveClients200:
    def test_returns_200(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_response_has_date_from(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "date_from" in r.json()

    def test_response_has_date_to(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "date_to" in r.json()

    def test_response_has_new_key(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "new" in r.json()

    def test_response_has_recurring_key(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "recurring" in r.json()

    def test_response_has_inactive_key(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "inactive" in r.json()

    def test_response_has_active_key(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert "active" in r.json()

    def test_counters_are_integers(self) -> None:
        repo = FakeActiveClientsRepo(
            profiles=(_PROFILE_NEW, _PROFILE_RECURRING, _PROFILE_INACTIVE)
        )
        r = _active_clients_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        data = r.json()
        for key in ("new", "recurring", "inactive", "active"):
            assert isinstance(data[key], int), f"{key} devrait être un entier"

    def test_active_equals_new_plus_recurring(self) -> None:
        repo = FakeActiveClientsRepo(
            profiles=(_PROFILE_NEW, _PROFILE_RECURRING, _PROFILE_INACTIVE)
        )
        r = _active_clients_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        data = r.json()
        assert data["active"] == data["new"] + data["recurring"]

    def test_correct_new_count(self) -> None:
        repo = FakeActiveClientsRepo(
            profiles=(_PROFILE_NEW, _PROFILE_NEW, _PROFILE_RECURRING)
        )
        r = _active_clients_client(repo).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["new"] == 2

    def test_correct_recurring_count(self) -> None:
        repo = FakeActiveClientsRepo(profiles=(_PROFILE_NEW, _PROFILE_RECURRING))
        r = _active_clients_client(repo).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["recurring"] == 1

    def test_correct_inactive_count(self) -> None:
        repo = FakeActiveClientsRepo(
            profiles=(_PROFILE_INACTIVE, _PROFILE_INACTIVE)
        )
        r = _active_clients_client(repo).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["inactive"] == 2

    def test_empty_salon_all_zeros(self) -> None:
        """Aucun RDV `COMPLETED` → compteurs à 0 (état vide légitime, ≠ erreur)."""
        r = _active_clients_client(FakeActiveClientsRepo(profiles=())).get(
            _URL, headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        data = r.json()
        assert data["new"] == 0
        assert data["recurring"] == 0
        assert data["inactive"] == 0
        assert data["active"] == 0

    def test_counters_are_non_negative(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        data = r.json()
        for key in ("new", "recurring", "inactive", "active"):
            assert data[key] >= 0


# ---------------------------------------------------------------------------
# Défaut de période — mois civil courant
# ---------------------------------------------------------------------------


class TestActiveClientsDefaultPeriod:
    def test_without_params_returns_200(self) -> None:
        """Sans date_from/date_to → backend applique le mois civil courant."""
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200

    def test_without_params_date_from_not_null(self) -> None:
        """Sans params → le backend résout date_from (non null)."""
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["date_from"] is not None

    def test_without_params_date_to_not_null(self) -> None:
        """Sans params → le backend résout date_to (non null)."""
        r = _active_clients_client().get(_URL, headers=_auth_header("MANAGER"))
        assert r.json()["date_to"] is not None

    def test_only_date_from_falls_back_to_current_month(self) -> None:
        """Une seule borne fournie → retombe sur le mois courant (les deux bornes)."""
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-01", headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        assert r.json()["date_from"] is not None
        assert r.json()["date_to"] is not None

    def test_only_date_to_falls_back_to_current_month(self) -> None:
        """Une seule borne fournie → retombe sur le mois courant."""
        r = _active_clients_client().get(
            _URL + "?date_to=2026-08-31", headers=_auth_header("MANAGER")
        )
        assert r.status_code == 200
        assert r.json()["date_from"] is not None
        assert r.json()["date_to"] is not None

    def test_with_explicit_dates_echoed(self) -> None:
        """Bornes explicites transmises → répercutées dans la réponse."""
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        data = r.json()
        assert data["date_from"] == "2026-08-01"
        assert data["date_to"] == "2026-08-31"


# ---------------------------------------------------------------------------
# Non-PII (§11.3) — schéma figé, champs interdits absents
# ---------------------------------------------------------------------------


class TestActiveClientsNonPII:
    def _data(self) -> dict:
        repo = FakeActiveClientsRepo(
            profiles=(_PROFILE_NEW, _PROFILE_RECURRING, _PROFILE_INACTIVE)
        )
        r = _active_clients_client(repo).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        return r.json()

    def test_only_expected_top_level_keys(self) -> None:
        """Seuls `date_from`, `date_to`, `new`, `recurring`, `inactive`, `active` autorisés."""
        allowed = {"date_from", "date_to", "new", "recurring", "inactive", "active"}
        extra = set(self._data().keys()) - allowed
        assert extra == set(), f"Champs inattendus dans la réponse : {extra}"

    def test_no_client_id_in_response(self) -> None:
        assert "client_id" not in self._data()

    def test_no_appointment_id_in_response(self) -> None:
        assert "appointment_id" not in self._data()

    def test_no_user_id_in_response(self) -> None:
        assert "user_id" not in self._data()

    def test_no_name_in_response(self) -> None:
        assert "name" not in self._data()

    def test_no_phone_in_response(self) -> None:
        assert "phone" not in self._data()


# ---------------------------------------------------------------------------
# Route absente de PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestActiveClientsRouteProtection:
    def test_active_clients_not_in_public_route_paths(self) -> None:
        """Une donnée d'exploitation salon n'est jamais publique."""
        for public_path in PUBLIC_ROUTE_PATHS:
            assert "active-clients" not in public_path, (
                f"active-clients trouvé dans PUBLIC_ROUTE_PATHS : {public_path}"
            )


# ---------------------------------------------------------------------------
# Non-collision de routage
# ---------------------------------------------------------------------------


class TestActiveClientsRouteNoCollision:
    def test_active_clients_not_parsed_as_uuid(self) -> None:
        """Le segment 'active-clients' n'est pas parsé comme un {customer_id} UUID.

        Un 401 ou 403 prouve que le routeur a résolu la route stats correctement.
        Un 422 indiquerait une collision avec /{salon_id}/customers/{id}.
        """
        r = _active_clients_client().get(_URL)  # sans jeton → 401
        assert r.status_code in (401, 403), (
            f"Attendu 401/403 (route résolue), obtenu {r.status_code} "
            "(possible collision de routage)"
        )
        assert r.status_code != 422, (
            "422 indique un possible parsing UUID du segment 'active-clients'"
        )


# ---------------------------------------------------------------------------
# 422 — paramètres mal formés ou incohérents
# ---------------------------------------------------------------------------


class TestActiveClients422:
    def test_date_to_before_date_from_returns_422(self) -> None:
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-31&date_to=2026-08-01",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_malformed_date_from_returns_422(self) -> None:
        r = _active_clients_client().get(
            _URL + "?date_from=pas-une-date&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_malformed_date_to_returns_422(self) -> None:
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-01&date_to=2026-13-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 422

    def test_same_date_from_and_to_is_valid(self) -> None:
        """date_from == date_to (plage d'un seul jour) est valide."""
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-15&date_to=2026-08-15",
            headers=_auth_header("MANAGER"),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 401 — jeton absent ou invalide
# ---------------------------------------------------------------------------


class TestActiveClients401:
    def test_no_token_returns_401(self) -> None:
        r = _active_clients_client().get(_URL)
        assert r.status_code == 401

    def test_invalid_token_returns_401(self) -> None:
        r = _active_clients_client().get(
            _URL,
            headers={"Authorization": "Bearer malformed.token.value"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 — rôles sans STATS_READ_SALON ou gérant hors portée
# ---------------------------------------------------------------------------


class TestActiveClients403:
    def test_client_role_returns_403(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("CLIENT"))
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        r = _active_clients_client().get(_URL, headers=_auth_header("HAIRDRESSER"))
        assert r.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        """ADMIN dispose de STATS_READ_PLATFORM mais pas de STATS_READ_SALON (#42)."""
        r = _active_clients_client().get(_URL, headers=_auth_header("ADMIN"))
        assert r.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        """Gérant hors portée → 403 générique, aucun oracle d'existence."""
        token = make_access_token(_OTHER_MANAGER_ID, Role.MANAGER.value)
        scope = FakeSalonScopeRepository({_OTHER_MANAGER_ID: frozenset()})
        r = _active_clients_client(manager_scope=scope).get(
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
        r = _active_clients_client(manager_scope=scope).get(
            _URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Isolation — salon_id transmis au dépôt (§11.2)
# ---------------------------------------------------------------------------


class _TrackingSalonRepo(FakeActiveClientsRepo):
    def __init__(self) -> None:
        super().__init__()
        self.salon_ids_received: list[uuid.UUID] = []

    def segment_active_clients(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from, date_to
    ):
        self.salon_ids_received.append(salon_id)
        return ()


class TestActiveClientsIsolation:
    def test_salon_id_forwarded_to_repository(self) -> None:
        """segment_active_clients reçoit le salon_id de l'URL — défense en profondeur §11.2."""
        tracking = _TrackingSalonRepo()
        r = _active_clients_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert r.status_code == 200
        assert len(tracking.salon_ids_received) == 1
        assert tracking.salon_ids_received[0] == _SALON_ID

    def test_salon_id_is_not_other_salon(self) -> None:
        tracking = _TrackingSalonRepo()
        _active_clients_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        for sid in tracking.salon_ids_received:
            assert sid != _OTHER_SALON_ID


# ---------------------------------------------------------------------------
# Filtre de statut — HISTORY_STATUSES imposé
# ---------------------------------------------------------------------------


class _TrackingStatusRepo(FakeActiveClientsRepo):
    def __init__(self) -> None:
        super().__init__()
        self.statuses_received: list = []

    def segment_active_clients(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from, date_to
    ):
        self.statuses_received.append(statuses)
        return ()


class TestActiveClientsStatusFilter:
    def test_history_statuses_forwarded(self) -> None:
        """Le port reçoit HISTORY_STATUSES (COMPLETED), jamais soumis par l'appelant."""
        tracking = _TrackingStatusRepo()
        _active_clients_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert len(tracking.statuses_received) == 1
        assert tracking.statuses_received[0] == HISTORY_STATUSES

    def test_completed_in_statuses(self) -> None:
        tracking = _TrackingStatusRepo()
        _active_clients_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert "COMPLETED" in tracking.statuses_received[0]


# ---------------------------------------------------------------------------
# Bornes de période — transmises au port
# ---------------------------------------------------------------------------


class _TrackingDatesRepo(FakeActiveClientsRepo):
    def __init__(self) -> None:
        super().__init__()
        self.date_from_received: list = []
        self.date_to_received: list = []

    def segment_active_clients(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from, date_to
    ):
        self.date_from_received.append(date_from)
        self.date_to_received.append(date_to)
        return ()


class TestActiveClientsDateBounds:
    def test_date_from_forwarded_to_port(self) -> None:
        tracking = _TrackingDatesRepo()
        _active_clients_client(tracking).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert tracking.date_from_received[0] == datetime.date(2026, 8, 1)

    def test_date_to_forwarded_to_port(self) -> None:
        tracking = _TrackingDatesRepo()
        _active_clients_client(tracking).get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert tracking.date_to_received[0] == datetime.date(2026, 8, 31)

    def test_without_dates_port_receives_current_month_bounds(self) -> None:
        """Sans paramètres → le port reçoit les bornes du mois courant (non nulles)."""
        tracking = _TrackingDatesRepo()
        _active_clients_client(tracking).get(_URL, headers=_auth_header("MANAGER"))
        assert tracking.date_from_received[0] is not None
        assert tracking.date_to_received[0] is not None

    def test_date_from_echoed_in_response(self) -> None:
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["date_from"] == "2026-08-01"

    def test_date_to_echoed_in_response(self) -> None:
        r = _active_clients_client().get(
            _URL + "?date_from=2026-08-01&date_to=2026-08-31",
            headers=_auth_header("MANAGER"),
        )
        assert r.json()["date_to"] == "2026-08-31"
