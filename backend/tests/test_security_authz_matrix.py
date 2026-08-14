"""Matrice de tests négatifs d'autorisation **rôle × route réelle** (#51, §11.2/§4.1).

But (spec `specs/tests-securite-authz-jwt-donnees-perso.md` §1) : prouver, sur
l'application **réelle** (`coiflink_api.main.app`) telle qu'exposée, qu'un rôle
**non habilité** est **refusé** (`403` générique) sur un échantillon représentatif
de routes protégées — **une par famille de permission** — et qu'une route protégée
**sans jeton** répond `401` + `WWW-Authenticate: Bearer`.

Deux invariants de sécurité rendent ce fichier **DB-free** (il tourne dans le gate
ADW sans PostgreSQL) :

- un rôle non habilité est refusé **par une garde** (`require_permission` /
  `require_salon_scope`) qui lève **avant** que le handler n'atteigne la base ;
- l'identité est **relue en base**, mais la base est ici un *fake* injecté par
  `app.dependency_overrides` (patron `test_security_guards.py`).

On surcharge donc `get_user_repository` (rôle incarné), `get_access_policy`
(portée vide) et `get_session` (session neutre : les dépôts SQL des handlers sont
*construits* mais **jamais interrogés**, le refus survenant en amont), et on dépose
un `FakeTokenService` sur `app.state`.

La table `_MATRIX` est **dérivée de `ROLE_PERMISSIONS`** (source de vérité §4.1)
pour résister à la dérive : les rôles autorisés d'une route sont exactement ceux
qui détiennent sa permission ; les rôles refusés sont **tous les autres**. On
n'**exerce** que les rôles refusés (attendus en `403`) : les cas positifs
touchent la base et relèvent des suites e2e (`test_security_isolation_e2e.py`,
`test_critical_journeys_e2e.py`).

L'exhaustivité mécanique « aucune route orpheline » est déjà couverte par
`unprotected_routes(app) == []` (`test_security_guards.py`) : on ne la duplique pas.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.security import (
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.permissions import ROLE_PERMISSIONS, Permission
from coiflink_api.main import app as main_app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    FakeAuthUserRepository,
    FakeSalonScopeRepository,
    FakeTokenService,
)

# Identité incarnée (le `sub` du jeton *fake* d'accès de `conftest`).
_USER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)

# Cibles syntaxiques (UUID valides) — jamais résolues en base : le refus tombe en amont.
_SALON_ID = uuid.UUID("50000000-0000-0000-0000-0000000000a1")
_PAYMENT_ID = uuid.UUID("50000000-0000-0000-0000-0000000000b2")
_DEVICE_ID = uuid.UUID("50000000-0000-0000-0000-0000000000c3")
_TICKET_ID = uuid.UUID("50000000-0000-0000-0000-0000000000d4")

# `Role.TERMINAL` (borne terminal, US-8.1 #155) est inclus ici : la dérivation
# `denied = _ALL_ROLES - allowed` (plus bas) l'exerce alors **automatiquement** en
# `403` sur chaque route échantillonnée — dont la création de fiche
# (`CUSTOMER_MANAGE`). C'est le « test RBAC négatif ajouté à la matrice existante »
# du critère d'acceptation de l'issue.
_ALL_ROLES: tuple[Role, ...] = (
    Role.CLIENT,
    Role.HAIRDRESSER,
    Role.MANAGER,
    Role.ADMIN,
    Role.TERMINAL,
)

_FORBIDDEN_DETAIL = "Accès refusé."


# --------------------------------------------------------------------------- #
# Table déclarative : une route **par famille de permission** (spec §1).
# `allowed_roles` est **dérivé** de `ROLE_PERMISSIONS` (jamais figé à la main).
# --------------------------------------------------------------------------- #
def _roles_with(permission: Permission) -> frozenset[Role]:
    """Rôles détenant `permission` d'après la matrice §4.1 (source de vérité)."""

    return frozenset(
        role for role, perms in ROLE_PERMISSIONS.items() if permission in perms
    )


class _Route:
    """Une entrée de la matrice : (méthode, chemin, permission gouvernante)."""

    __slots__ = ("method", "path", "permission")

    def __init__(self, method: str, path: str, permission: Permission) -> None:
        self.method = method
        self.path = path
        self.permission = permission

    @property
    def allowed_roles(self) -> frozenset[Role]:
        return _roles_with(self.permission)

    def __repr__(self) -> str:  # id lisible dans le rapport pytest
        return f"{self.method} {self.path}"


_MATRIX: tuple[_Route, ...] = (
    _Route("POST", "/salons", Permission.SALON_CREATE),
    _Route("POST", f"/salons/{_SALON_ID}/services", Permission.SERVICE_MANAGE),
    _Route("POST", f"/salons/{_SALON_ID}/customers", Permission.CUSTOMER_MANAGE),
    _Route("POST", f"/salons/{_SALON_ID}/payments", Permission.PAYMENT_RECORD),
    _Route("GET", f"/salons/{_SALON_ID}/payments", Permission.CASH_JOURNAL_READ),
    _Route("GET", f"/salons/{_SALON_ID}/revenue/summary", Permission.STATS_READ_SALON),
    _Route("GET", "/admin/kpis", Permission.STATS_READ_PLATFORM),
    _Route("GET", "/me/receipts", Permission.PAYMENT_READ_OWN),
    # File d'attente walk-in (US-8.3, #157, pivot walk-in exclusif #148) : `MANAGER`
    # et `HAIRDRESSER` détiennent `QUEUE_TICKET_UPDATE_STATUS` (démarrer un ticket).
    _Route(
        "POST",
        f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/start",
        Permission.QUEUE_TICKET_UPDATE_STATUS,
    ),
    # Borne terminal (US-8.1, #155) : seul `MANAGER` détient `TERMINAL_PROVISION`.
    # CLIENT, HAIRDRESSER, ADMIN **et TERMINAL lui-même** sont donc dans le jeu de
    # rôles refusés — c'est le « test RBAC négatif ajouté à la matrice » du critère
    # d'acceptation de l'issue.
    _Route("POST", f"/salons/{_SALON_ID}/terminal-devices", Permission.TERMINAL_PROVISION),
    _Route("GET",  f"/salons/{_SALON_ID}/terminal-devices", Permission.TERMINAL_PROVISION),
    _Route("DELETE", f"/salons/{_SALON_ID}/terminal-devices/{_DEVICE_ID}", Permission.TERMINAL_PROVISION),
    # Journal d'audit (page gérante « Journal d'audit ») : seul `MANAGER` détient
    # `AUDIT_LOG_READ` — nouvelle famille de permission de la réorganisation du
    # tableau de bord.
    _Route("GET", f"/salons/{_SALON_ID}/audit-logs", Permission.AUDIT_LOG_READ),
)


# --------------------------------------------------------------------------- #
# Incarnation d'un rôle sur l'application **réelle** (sans base).
# --------------------------------------------------------------------------- #
def _creds(role: Role) -> UserCredentials:
    return UserCredentials(
        id=_USER_ID,
        role=role.value,
        status=UserStatus.ACTIVE.value,
        password_hash="x",  # jamais un secret réel
    )


@pytest.fixture(autouse=True)
def _neutral_state() -> Generator[None, None, None]:
    """Dépose un `TokenService` *fake* et neutralise la session ; nettoie ensuite.

    `get_session` est surchargé pour renvoyer une session **neutre** (`None`) : les
    dépôts SQL des handlers sont construits sans I/O et ne sont jamais interrogés,
    puisque toute requête de cette suite s'arrête sur un refus (`401`/`403`) avant
    d'atteindre le handler.
    """

    orig_token_service = getattr(main_app.state, "token_service", None)
    main_app.state.token_service = FakeTokenService()
    main_app.dependency_overrides[get_session] = lambda: None
    try:
        yield
    finally:
        main_app.dependency_overrides.pop(get_session, None)
        main_app.dependency_overrides.pop(get_user_repository, None)
        main_app.dependency_overrides.pop(get_access_policy, None)
        main_app.state.token_service = orig_token_service


def _incarnate(role: Role) -> None:
    """Fait porter le rôle `role` à l'utilisateur courant (identité relue en *fake*)."""

    creds = _creds(role)
    main_app.dependency_overrides[get_user_repository] = lambda: FakeAuthUserRepository(
        credentials_by_id={str(creds.id): creds}
    )
    # Portée **vide** : un rôle refusé l'est par permission *ou* par portée — jamais
    # un accès par défaut (deny-by-default jusque dans la portée §11.2).
    main_app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
        FakeSalonScopeRepository()
    )


def _request(client: TestClient, route: _Route, *, token: bool) -> object:
    headers = {"Authorization": "Bearer fake-access-token"} if token else {}
    method = route.method.lower()
    if method in ("post", "put", "patch"):
        return client.request(route.method, route.path, json={}, headers=headers)
    return client.request(route.method, route.path, headers=headers)


# --------------------------------------------------------------------------- #
# Cohérence de la table : allowed = dérivé de §4.1, non vide, denied = complément.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", _MATRIX, ids=repr)
def test_matrix_allowed_roles_are_derived_and_non_empty(route: _Route) -> None:
    """Chaque route a au moins un rôle habilité (sinon la route serait morte)."""

    assert route.allowed_roles, f"Aucun rôle n'a {route.permission} — matrice §4.1 ?"


@pytest.mark.parametrize("route", _MATRIX, ids=repr)
def test_matrix_denied_roles_are_complement_of_allowed(route: _Route) -> None:
    """Les rôles refusés = **tous** les rôles − rôles habilités (anti-dérive)."""

    denied = set(_ALL_ROLES) - route.allowed_roles
    assert denied, f"{route} n'a aucun rôle refusé — cible peu discriminante."
    assert denied | route.allowed_roles == set(_ALL_ROLES)


# --------------------------------------------------------------------------- #
# Cœur du critère : rôle non habilité → 403 générique (sur `main.app`).
# --------------------------------------------------------------------------- #
def _denied_cases() -> list[tuple[_Route, Role]]:
    return [
        (route, role)
        for route in _MATRIX
        for role in _ALL_ROLES
        if role not in route.allowed_roles
    ]


@pytest.mark.parametrize(
    ("route", "role"),
    _denied_cases(),
    ids=lambda v: v.value if isinstance(v, Role) else repr(v),
)
def test_unauthorized_role_gets_403_generic(route: _Route, role: Role) -> None:
    """Un rôle sans la permission (ni la portée) reçoit **`403` « Accès refusé. »**."""

    _incarnate(role)
    with TestClient(main_app, raise_server_exceptions=False) as client:
        resp = _request(client, route, token=True)

    assert resp.status_code == 403, (
        f"{role.value} sur {route} attendait 403, reçu {resp.status_code}"
    )
    assert resp.json().get("detail") == _FORBIDDEN_DETAIL


# --------------------------------------------------------------------------- #
# Sans jeton → 401 générique + WWW-Authenticate (deny-by-default, ADR-0015).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", _MATRIX, ids=repr)
def test_missing_token_gets_401_with_www_authenticate(route: _Route) -> None:
    """Toute route de la matrice **sans jeton** → `401` + en-tête `WWW-Authenticate`."""

    # Aucune incarnation : la garde globale refuse avant toute résolution d'identité.
    with TestClient(main_app, raise_server_exceptions=False) as client:
        resp = _request(client, route, token=False)

    assert resp.status_code == 401, f"{route} sans jeton attendait 401."
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


# --------------------------------------------------------------------------- #
# Élévation de privilège via inscription : le champ `role` du corps est **ignoré**.
# --------------------------------------------------------------------------- #
def test_register_request_schema_has_no_role_field() -> None:
    """`RegisterRequest` ne **déclare** aucun champ `role` : le rôle est fixé serveur."""

    from coiflink_api.adapters.inbound.auth import RegisterRequest

    assert "role" not in RegisterRequest.model_fields


def test_register_request_ignores_injected_role() -> None:
    """Un `role` injecté au corps d'inscription est **ignoré** (pas d'attribut `role`).

    Preuve DB-free de l'anti-élévation : même en glissant `role=ADMIN` dans le
    corps, le modèle Pydantic n'en fait rien — la route attribue le rôle
    (`CLIENT`/`MANAGER`) côté serveur (`get_register_client`/`get_register_manager`).
    """

    from coiflink_api.adapters.inbound.auth import RegisterRequest

    parsed = RegisterRequest(
        full_name="Attaquant",
        phone="0700000000",
        password="motdepasse-solide-1234",
        role="ADMIN",  # type: ignore[call-arg]
    )
    assert not hasattr(parsed, "role")
    assert "role" not in parsed.model_dump()
