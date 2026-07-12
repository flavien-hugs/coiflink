"""Tests des gardes HTTP d'autorisation (adapters/inbound/security.py, issue #12).

Couvre :
- invariant deny-by-default : `unprotected_routes(app)` est vide ;
- `is_public_path` : chemins publics vs protégés ;
- `require_authenticated` : 401 sans jeton sur une route protégée ;
- `require_authenticated` : route publique accessible sans jeton ;
- `get_current_principal` : 401 si compte introuvable, 403 si inactif ;
- `require_roles(...)` : 403 si mauvais rôle, passe avec le bon rôle ;
- `require_permission(...)` : 403 si permission absente, passe si accordée ;
- `require_salon_scope` : 403 hors portée, 200 dans la portée ;
- refresh token refusé sur route protégée → 401 ;
- messages d'erreur génériques (aucune fuite de motif).
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_current_principal,
    get_user_repository,
    is_public_path,
    require_authenticated,
    require_permission,
    require_roles,
    require_salon_scope,
    unprotected_routes,
)
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import InvalidToken
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.main import app as main_app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    FakeAuthUserRepository,
    FakeSalonScopeRepository,
    FakeTokenService,
)

_USER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_SALON_A  = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_SALON_B  = uuid.UUID("bbbbbb00-0000-0000-0000-000000000002")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_creds(
    uid: uuid.UUID = _USER_ID,
    role: str = Role.CLIENT.value,
    status: str = UserStatus.ACTIVE.value,
) -> UserCredentials:
    return UserCredentials(id=uid, role=role, status=status, password_hash="x")



@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    """Retire les overrides après chaque test pour éviter les fuites de contexte."""
    yield
    main_app.dependency_overrides.pop(get_user_repository, None)
    main_app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# Invariant deny-by-default
# ---------------------------------------------------------------------------

def test_no_unprotected_routes() -> None:
    """Toutes les routes non publiques portent une garde de Principal."""
    bad = unprotected_routes(main_app)
    assert bad == [], f"Routes non protégées détectées : {bad}"


# ---------------------------------------------------------------------------
# is_public_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(PUBLIC_ROUTE_PATHS))
def test_is_public_path_true_for_listed_paths(path: str) -> None:
    assert is_public_path(path) is True


@pytest.mark.parametrize("path", [
    "/health/internal",
    "/salons",
    "/salons/some-id/appointments",
    "/auth/me",
    "/",
    "",
])
def test_is_public_path_false_for_protected_paths(path: str) -> None:
    assert is_public_path(path) is False


# ---------------------------------------------------------------------------
# require_authenticated — route publique accessible sans jeton
# ---------------------------------------------------------------------------

def test_public_route_no_token_required() -> None:
    with TestClient(main_app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# require_authenticated — route protégée sans jeton → 401
# ---------------------------------------------------------------------------


def test_missing_token_on_protected_route_returns_401_with_generic_message() -> None:
    """Pas de jeton → 401 générique sans révélation du motif."""
    mini = FastAPI(dependencies=[Depends(require_authenticated)])

    @mini.get("/protected")
    def _handler() -> dict:
        return {"ok": True}

    mini.state.token_service = FakeTokenService()

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/protected")

    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
    data = resp.json()
    assert "motdepasse" not in data.get("detail", "").lower()
    assert "token" not in data.get("detail", "").lower()


def test_invalid_token_returns_401_generic() -> None:
    mini = FastAPI(dependencies=[Depends(require_authenticated)])

    @mini.get("/protected")
    def _handler() -> dict:
        return {"ok": True}

    mini.state.token_service = FakeTokenService(
        verify_access_result=InvalidToken("bad token")
    )

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/protected", headers={"Authorization": "Bearer bogus.jwt.token"})

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# get_current_principal — compte introuvable → 401, inactif → 403
# ---------------------------------------------------------------------------


def test_current_principal_deleted_account_returns_401() -> None:
    mini = FastAPI()
    mini.state.token_service = FakeTokenService()
    empty_repo = FakeAuthUserRepository()

    @mini.get("/me")
    def _handler(
        p: Annotated[Principal, Depends(get_current_principal)],
        _users: Annotated[UserRepository, Depends(get_user_repository)],
    ) -> dict:
        return {"id": str(p.id)}

    mini.dependency_overrides[get_user_repository] = lambda: empty_repo

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 401


def test_current_principal_inactive_account_returns_403_with_generic_message() -> None:
    inactive_creds = _active_creds(status=UserStatus.INACTIVE.value)
    user_repo = FakeAuthUserRepository(
        credentials_by_id={str(inactive_creds.id): inactive_creds}
    )
    mini = FastAPI()
    mini.state.token_service = FakeTokenService()

    @mini.get("/me")
    def _handler(
        p: Annotated[Principal, Depends(get_current_principal)],
        _users: Annotated[UserRepository, Depends(get_user_repository)],
    ) -> dict:
        return {"id": str(p.id)}

    mini.dependency_overrides[get_user_repository] = lambda: user_repo

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert resp.status_code == 403
    detail = resp.json().get("detail", "")
    # Doit être générique — ne doit pas révéler de PII
    assert "téléphone" not in detail.lower()
    assert "mot de passe" not in detail.lower()


# ---------------------------------------------------------------------------
# require_roles guard
# ---------------------------------------------------------------------------

def _mini_app_with_role_guard(*roles: Role) -> FastAPI:
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    creds = _active_creds(role=roles[0].value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository()

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    guard = require_roles(*roles)

    @mini.get("/restricted")
    def _handler(p: Principal = Depends(guard)) -> dict:  # noqa: B008
        return {"role": p.role}

    return mini


def test_require_roles_correct_role_passes() -> None:
    mini = _mini_app_with_role_guard(Role.MANAGER)
    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get(
            "/restricted",
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp.status_code == 200
    assert resp.json()["role"] == Role.MANAGER.value


def test_require_roles_wrong_role_returns_403() -> None:
    """CLIENT tente une route réservée MANAGER → 403."""
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    # Compte CLIENT dans le dépôt
    creds = _active_creds(role=Role.CLIENT.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository()

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    guard = require_roles(Role.MANAGER)

    @mini.get("/managers-only")
    def _handler(p: Principal = Depends(guard)) -> dict:  # noqa: B008
        return {"role": p.role}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get(
            "/managers-only",
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# require_permission guard
# ---------------------------------------------------------------------------

def test_require_permission_granted_passes() -> None:
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    creds = _active_creds(role=Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository()

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    guard = require_permission(Permission.SALON_CREATE)

    @mini.get("/salon-create")
    def _handler(p: Principal = Depends(guard)) -> dict:  # noqa: B008
        return {"ok": True}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/salon-create", headers={"Authorization": "Bearer fake-token"})
    assert resp.status_code == 200


def test_require_permission_denied_returns_403() -> None:
    """CLIENT n'a pas SALON_CREATE → 403."""
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    creds = _active_creds(role=Role.CLIENT.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository()

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    guard = require_permission(Permission.SALON_CREATE)

    @mini.get("/salon-create")
    def _handler(p: Principal = Depends(guard)) -> dict:  # noqa: B008
        return {"ok": True}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/salon-create", headers={"Authorization": "Bearer fake-token"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# require_salon_scope guard
# ---------------------------------------------------------------------------

def test_require_salon_scope_in_scope_passes() -> None:
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    creds = _active_creds(role=Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_A})})

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    @mini.get("/salons/{salon_id}/data")
    def _handler(
        scope: Annotated[SalonScope, Depends(require_salon_scope)],
    ) -> dict:
        return {"platform_wide": scope.platform_wide}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get(
            f"/salons/{_SALON_A}/data",
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp.status_code == 200


def test_require_salon_scope_cross_salon_returns_403() -> None:
    """Gérant du salon A tente d'accéder au salon B → 403."""
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    creds = _active_creds(role=Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    # Portée : uniquement salon A
    scope_repo = FakeSalonScopeRepository(scopes={creds.id: frozenset({_SALON_A})})

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    @mini.get("/salons/{salon_id}/data")
    def _handler(
        scope: Annotated[SalonScope, Depends(require_salon_scope)],
    ) -> dict:
        return {"ok": True}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get(
            f"/salons/{_SALON_B}/data",
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Accès refusé."


def test_require_salon_scope_client_always_forbidden() -> None:
    """CLIENT n'a jamais de portée salon → 403."""
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService()

    creds = _active_creds(role=Role.CLIENT.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository()

    mini.dependency_overrides[get_user_repository] = lambda: user_repo
    mini.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)

    @mini.get("/salons/{salon_id}/data")
    def _handler(
        scope: Annotated[SalonScope, Depends(require_salon_scope)],
    ) -> dict:
        return {"ok": True}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get(
            f"/salons/{_SALON_A}/data",
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Refresh token refusé sur une route protégée (mauvais type)
# ---------------------------------------------------------------------------

def test_refresh_token_rejected_on_protected_route() -> None:
    """Un refresh token présenté comme access token est refusé (→ 401)."""
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = FakeTokenService(
        verify_access_result=InvalidToken("refresh présenté comme access")
    )

    @mini.get("/protected")
    def _handler() -> dict:
        return {"ok": True}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/protected", headers={"Authorization": "Bearer fake-refresh-token"})

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 503 quand JWT_SECRET n'est pas configuré
# ---------------------------------------------------------------------------

def test_jwt_unavailable_returns_503() -> None:
    mini = FastAPI(dependencies=[Depends(require_authenticated)])
    mini.state.token_service = None  # JWT_SECRET absent

    @mini.get("/protected")
    def _handler() -> dict:
        return {"ok": True}

    with TestClient(mini, raise_server_exceptions=False) as c:
        resp = c.get("/protected", headers={"Authorization": "Bearer any-token"})

    assert resp.status_code == 503
