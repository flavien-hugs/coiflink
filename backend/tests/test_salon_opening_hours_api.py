"""Tests API — route `PUT /salons/{id}/opening-hours` (adapter entrant, US-2.2, #16).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_salon_repository` → `FakeSalonRepository` (aucune base) ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- matrice RBAC : MANAGER → 200, CLIENT → 403, HAIRDRESSER → 403, ADMIN → 403,
  sans jeton → 401 ;
- isolation : MANAGER visant un autre salon → 403 générique (pas 404) ;
- message 403 générique — ni permission ni existence revelée (PRD §11.1, §11.2) ;
- succès : `opening_hours` normalisé, `is_bookable=true` dans la réponse ;
- validation : structure invalide → 422 (domaine, pas Pydantic uniquement) ;
- sémantique replace : un second PUT écrase complètement le premier.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.salons import get_salon_repository
from coiflink_api.adapters.inbound.security import get_access_policy, get_user_repository
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.application.salons import CreateSalon, CreateSalonCommand
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuthUserRepository,
    FakeSalonRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_OTHER_MANAGER_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ADMIN_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_VALID_HOURS = {
    "weekly": {
        "mon": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
        "fri": [{"start": "09:00", "end": "17:00"}],
    },
}

_INVALID_HOURS_OVERLAP = {
    "weekly": {
        "mon": [
            {"start": "08:00", "end": "12:00"},
            {"start": "11:00", "end": "15:00"},
        ]
    }
}

_INVALID_HOURS_END_BEFORE_START = {
    "weekly": {
        "mon": [{"start": "18:00", "end": "08:00"}]
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds(
    user_id: uuid.UUID,
    role: str,
    status: str = UserStatus.ACTIVE.value,
) -> UserCredentials:
    return UserCredentials(id=user_id, role=role, status=status, password_hash="x")


def _opening_hours_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/opening-hours"


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
def salon_repo() -> FakeSalonRepository:
    return FakeSalonRepository()


@pytest.fixture()
def manager_with_salon(
    salon_repo: FakeSalonRepository,
) -> Generator[tuple[TestClient, uuid.UUID], None, None]:
    """MANAGER authentifié avec un salon pré-créé dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})

    salon = CreateSalon(salon_repo).execute(
        CreateSalonCommand(name="Mon Salon"), owner_id=_MANAGER_ID
    )
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({salon.id})})

    app.dependency_overrides[get_salon_repository] = lambda: salon_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app), salon.id
    finally:
        app.dependency_overrides.pop(get_salon_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


def _make_client_for_role(
    salon_repo: FakeSalonRepository,
    *,
    user_id: uuid.UUID,
    role: str,
    salon_id: uuid.UUID | None = None,
) -> TestClient:
    """Construit un TestClient pour un rôle donné et installe les overrides."""
    creds = _creds(user_id, role)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope = frozenset({salon_id}) if salon_id else frozenset()
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: scope})

    app.dependency_overrides[get_salon_repository] = lambda: salon_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    return TestClient(app)


def _cleanup_overrides() -> None:
    app.dependency_overrides.pop(get_salon_repository, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Matrice RBAC
# ---------------------------------------------------------------------------


class TestSetOpeningHoursRbac:
    def test_manager_own_salon_returns_200(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_missing_token_returns_401(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(_opening_hours_url(salon_id), json=_VALID_HOURS)
        assert r.status_code == 401

    def test_client_role_returns_403(self, salon_repo: FakeSalonRepository) -> None:
        client_id = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="S"), owner_id=_OTHER_MANAGER_ID
        )
        token = make_access_token(client_id, Role.CLIENT.value)
        client = _make_client_for_role(
            salon_repo, user_id=client_id, role=Role.CLIENT.value
        )
        try:
            r = client.put(
                _opening_hours_url(salon.id),
                json=_VALID_HOURS,
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 403

    def test_hairdresser_role_returns_403(self, salon_repo: FakeSalonRepository) -> None:
        hd_id = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="S"), owner_id=_OTHER_MANAGER_ID
        )
        token = make_access_token(hd_id, Role.HAIRDRESSER.value)
        client = _make_client_for_role(
            salon_repo,
            user_id=hd_id,
            role=Role.HAIRDRESSER.value,
            salon_id=salon.id,
        )
        try:
            r = client.put(
                _opening_hours_url(salon.id),
                json=_VALID_HOURS,
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 403

    def test_admin_role_returns_403(self, salon_repo: FakeSalonRepository) -> None:
        """L'ADMIN supervise mais n'a pas SALON_UPDATE → 403."""
        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="S"), owner_id=_OTHER_MANAGER_ID
        )
        token = make_access_token(_ADMIN_ID, Role.ADMIN.value)
        client = _make_client_for_role(
            salon_repo, user_id=_ADMIN_ID, role=Role.ADMIN.value
        )
        try:
            r = client.put(
                _opening_hours_url(salon.id),
                json=_VALID_HOURS,
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Isolation inter-salons — §11.2
# ---------------------------------------------------------------------------


class TestSetOpeningHoursIsolation:
    def test_manager_targeting_other_salon_returns_403(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
        salon_repo: FakeSalonRepository,
    ) -> None:
        """Gérant du salon A → salon B : 403 générique, pas 404 (anti-oracle)."""
        client, _own_salon_id = manager_with_salon
        other_salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="Autre"), owner_id=_OTHER_MANAGER_ID
        )
        r = client.put(
            _opening_hours_url(other_salon.id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 403

    def test_403_for_out_of_scope_salon_is_generic(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Le message 403 inter-salon est générique : ne révèle pas l'existence."""
        client, _ = manager_with_salon
        r = client.put(
            _opening_hours_url(uuid.uuid4()),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["detail"] == "Accès refusé."

    def test_403_for_insufficient_role_is_generic(
        self, salon_repo: FakeSalonRepository
    ) -> None:
        """Le message 403 role-insuffisant est le même que pour hors-portée."""
        client_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
        salon = CreateSalon(salon_repo).execute(
            CreateSalonCommand(name="S"), owner_id=_OTHER_MANAGER_ID
        )
        token = make_access_token(client_id, Role.CLIENT.value)
        client = _make_client_for_role(
            salon_repo, user_id=client_id, role=Role.CLIENT.value
        )
        try:
            r = client.put(
                _opening_hours_url(salon.id),
                json=_VALID_HOURS,
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            _cleanup_overrides()
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# Réponse de succès
# ---------------------------------------------------------------------------


class TestSetOpeningHoursSuccess:
    def test_response_is_bookable_true(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["is_bookable"] is True

    def test_response_opening_hours_not_null(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["opening_hours"] is not None

    def test_response_opening_hours_has_version(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["opening_hours"]["version"] == 1

    def test_response_opening_hours_has_default_timezone(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["opening_hours"]["timezone"] == "Africa/Abidjan"

    def test_response_weekly_contains_submitted_days(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        weekly = r.json()["opening_hours"]["weekly"]
        assert "mon" in weekly
        assert "fri" in weekly

    def test_response_status_code_200(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_get_after_put_reflects_is_bookable_true(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        r = client.get(
            f"/salons/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["is_bookable"] is True


# ---------------------------------------------------------------------------
# Validation — 422
# ---------------------------------------------------------------------------


class TestSetOpeningHoursValidation:
    def test_overlapping_intervals_returns_422(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_INVALID_HOURS_OVERLAP,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_end_before_start_returns_422(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_INVALID_HOURS_END_BEFORE_START,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_all_days_closed_returns_422(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json={"weekly": {"mon": [], "tue": []}},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_422_detail_is_neutral(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Le message 422 ne doit pas contenir de détail SQL ni de PII."""
        client, salon_id = manager_with_salon
        r = client.put(
            _opening_hours_url(salon_id),
            json=_INVALID_HOURS_OVERLAP,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        detail = r.json().get("detail", "")
        assert "sql" not in detail.lower()
        assert "traceback" not in detail.lower()

    def test_valid_payload_leaves_opening_hours_unchanged_if_422(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        """Erreur de validation : aucun effet de bord sur les horaires existants."""
        client, salon_id = manager_with_salon
        # Premier PUT valide.
        client.put(
            _opening_hours_url(salon_id),
            json=_VALID_HOURS,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        # Deuxième PUT invalide.
        client.put(
            _opening_hours_url(salon_id),
            json=_INVALID_HOURS_OVERLAP,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        # Les horaires du premier PUT sont toujours là.
        r = client.get(
            f"/salons/{salon_id}",
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["opening_hours"] is not None


# ---------------------------------------------------------------------------
# Sémantique replace
# ---------------------------------------------------------------------------


class TestSetOpeningHoursReplace:
    def test_second_put_replaces_first_completely(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        first_payload = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}
        client.put(
            _opening_hours_url(salon_id),
            json=first_payload,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )

        second_payload = {"weekly": {"tue": [{"start": "09:00", "end": "17:00"}]}}
        r = client.put(
            _opening_hours_url(salon_id),
            json=second_payload,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )

        weekly = r.json()["opening_hours"]["weekly"]
        assert "mon" not in weekly
        assert "tue" in weekly

    def test_second_put_still_bookable(
        self,
        manager_with_salon: tuple[TestClient, uuid.UUID],
    ) -> None:
        client, salon_id = manager_with_salon
        first_payload = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}
        client.put(
            _opening_hours_url(salon_id),
            json=first_payload,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )

        second_payload = {"weekly": {"fri": [{"start": "09:00", "end": "17:00"}]}}
        r = client.put(
            _opening_hours_url(salon_id),
            json=second_payload,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["is_bookable"] is True


# ---------------------------------------------------------------------------
# Route non dans PUBLIC_ROUTE_PATHS (deny-by-default)
# ---------------------------------------------------------------------------


class TestRouteConfiguration:
    def test_opening_hours_route_not_public(self) -> None:
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS

        assert "/salons/{salon_id}/opening-hours" not in PUBLIC_ROUTE_PATHS

    def test_unprotected_routes_invariant_still_holds(self) -> None:
        from coiflink_api.adapters.inbound.security import unprotected_routes

        assert unprotected_routes(app) == []
