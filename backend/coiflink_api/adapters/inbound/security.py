"""Adapter entrant : gardes d'autorisation HTTP (RBAC, ADR-0015, issue #12).

C'est le « middleware » d'autorisation de CoifLink — implémenté en **dépendances
FastAPI** plutôt qu'en middleware ASGI (ADR-0015) : testable, surchargeable
(`app.dependency_overrides`) et visible dans OpenAPI.

Ce module ne contient **aucune règle métier** : il traduit HTTP → domaine
(en-tête `Authorization` → `Principal`) et refus → statut (`401`/`403`/`503`). Les
décisions appartiennent au domaine (`domain/permissions.py`, `domain/access.py`)
et leur orchestration à l'application (`application/authorization.py`).

Chaîne d'exécution d'une route protégée :

    requête ─▶ require_authenticated   (globale) → 401 / 503   deny-by-default, sans I/O
           ─▶ get_current_principal    (route)   → 401 / 403   rôle + statut **relus en base**
           ─▶ require_roles / require_permission → 403         matrice PRD §4.1
           ─▶ require_salon_scope                → 403         isolation PRD §11.2
           ─▶ handler

**Deny-by-default** : `require_authenticated` est enregistrée comme dépendance
**globale** de l'application (`main.py`). Toute route est donc fermée, *sauf* si
son chemin figure dans `PUBLIC_ROUTE_PATHS`. Une route ajoutée demain sans rien
déclarer est **protégée**, pas ouverte. L'invariant est vérifié par un test qui
énumère `app.routes` (helpers `is_public_path` / `route_requires_principal`).

Sécurité (PRD §11.1/§11.2/§11.4) :
- messages `401`/`403` **constants et génériques** — jamais `str(exc)`, jamais
  l'identifiant visé : un refus ne renseigne pas sur ce qui existe chez autrui ;
- **aucun secret ni PII** n'est journalisé (le jeton, même tronqué, n'apparaît
  nulle part) ;
- le claim `role` du JWT **n'autorise rien** : seul le rôle relu en base fait foi.

Comment protéger une nouvelle route (mode d'emploi des issues M2–M5) :

    @router.get("/salons/{salon_id}/appointments")
    def list_appointments(
        salon_id: uuid.UUID,
        scope: Annotated[SalonScope, Depends(require_salon_scope)],
        principal: Annotated[
            Principal, Depends(require_permission(Permission.APPOINTMENT_READ_SALON))
        ],
    ): ...

**Ne jamais** ajouter un chemin à `PUBLIC_ROUTE_PATHS` sans revue de sécurité.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence.salon_scope_repository import (
    SqlSalonScopeRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.application.ports.token_service import TokenService
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import (
    ExpiredToken,
    InvalidToken,
    NotAuthenticated,
    PermissionDenied,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.tokens import TokenClaims

# Schéma déclaré pour OpenAPI (bouton « Authorize » de /docs, ADR-0003).
# `auto_error=False` : on maîtrise nous-mêmes le message et l'en-tête
# `WWW-Authenticate`, au lieu du 403 par défaut de FastAPI sur en-tête absent.
bearer_scheme = HTTPBearer(auto_error=False, description="Jeton d'accès (JWT)")

# --------------------------------------------------------------------------- #
# Messages **constants** (aucune fuite : ni motif exact, ni identifiant visé).
# --------------------------------------------------------------------------- #
_UNAUTHENTICATED_DETAIL = "Authentification requise."
_FORBIDDEN_DETAIL = "Accès refusé."
_INACTIVE_ACCOUNT_DETAIL = "Compte désactivé."
_JWT_UNAVAILABLE_DETAIL = (
    "Service d'authentification indisponible (JWT_SECRET non configuré)."
)

# --------------------------------------------------------------------------- #
# Liste d'exemption publique — **unique et explicite** (deny-by-default).
#
# Tout chemin absent de cette liste est protégé. Les routes de documentation
# (`/docs`, `/redoc`, `/openapi.json`) sont montées par FastAPI **hors** du
# système de dépendances : elles ne sont pas concernées et leur exposition reste
# inchangée.
#
# ⚠ Ajouter un chemin ici, c'est ouvrir une route à Internet : revue obligatoire.
# --------------------------------------------------------------------------- #
PUBLIC_ROUTE_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/auth/register",
        "/auth/register/manager",
        "/auth/login",
        "/auth/refresh",
        "/auth/password/reset/request",
        "/auth/password/reset/confirm",
    }
)

# Marqueur posé sur les dépendances qui résolvent (et exigent) un `Principal`.
# Il rend l'invariant deny-by-default **mécaniquement vérifiable** : un test peut
# énumérer `app.routes` et exiger que chaque route soit publique-listée ou porte
# l'une de ces dépendances dans son arbre.
_PRINCIPAL_GUARD_ATTR = "__coiflink_principal_guard__"


def _mark_principal_guard(func: Callable[..., Any]) -> Callable[..., Any]:
    """Marque une dépendance comme exigeant un `Principal` authentifié."""

    setattr(func, _PRINCIPAL_GUARD_ATTR, True)
    return func


def is_principal_guard(call: Any) -> bool:
    """Vrai si cet appelable est une garde qui exige un `Principal`."""

    return getattr(call, _PRINCIPAL_GUARD_ATTR, False) is True


def is_public_path(path: str) -> bool:
    """Vrai si ce chemin de route figure dans la liste d'exemption publique."""

    return path in PUBLIC_ROUTE_PATHS


def route_requires_principal(route: Any) -> bool:
    """Vrai si la route déclare (directement ou non) une garde de `Principal`.

    Parcourt récursivement l'arbre de dépendances résolu par FastAPI
    (`route.dependant`) : `get_current_principal`, `require_roles(...)`,
    `require_permission(...)` et `require_salon_scope` y sont détectées, où
    qu'elles se trouvent dans l'arbre.
    """

    dependant = getattr(route, "dependant", None)
    return _dependant_requires_principal(dependant)


def _dependant_requires_principal(dependant: Any) -> bool:
    if dependant is None:
        return False
    if is_principal_guard(getattr(dependant, "call", None)):
        return True
    return any(
        _dependant_requires_principal(sub)
        for sub in getattr(dependant, "dependencies", ())
    )


# Routes montées par FastAPI **hors** du système de dépendances (la garde globale
# ne s'y applique pas) : documentation OpenAPI, exposition inchangée par #12.
DOC_ROUTE_PATHS: frozenset[str] = frozenset(
    {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)


def _child_routes(container: Any) -> tuple[Any, ...]:
    """Routes filles d'un conteneur, quelle que soit sa forme.

    Couvre l'application et les routeurs (`routes`), l'**enveloppe** posée par
    `include_router` depuis FastAPI 0.13x (`original_router`) et les `Mount` /
    sous-applications ASGI (`app`).
    """

    routes = getattr(container, "routes", None)
    if routes is not None:
        return tuple(routes)
    nested = getattr(container, "original_router", None) or getattr(
        container, "app", None
    )
    if nested is not None and nested is not container:
        return _child_routes(nested)
    return ()


def iter_api_routes(container: Any) -> Iterator[APIRoute]:
    """Énumère **récursivement** les `APIRoute` d'une application FastAPI.

    Indispensable à l'invariant deny-by-default : depuis FastAPI 0.13x,
    `include_router` n'aplatit plus les routes dans `app.routes` — il y dépose une
    enveloppe (`original_router`). Une énumération naïve de `app.routes` ne verrait
    donc **aucune** `APIRoute` et validerait l'invariant *à vide* (faux vert). On
    descend ici dans les enveloppes, les `Mount` et les sous-applications.
    """

    for route in _child_routes(container):
        if isinstance(route, APIRoute):
            yield route
        else:
            yield from iter_api_routes(route)


def foreign_routes(app: Any) -> list[str]:
    """Routes qui **échappent** au système de dépendances (donc à la garde globale).

    Seules les routes de documentation (`DOC_ROUTE_PATHS`) sont attendues ici : une
    route ajoutée via `app.add_route` ou une sous-application ASGI montée
    contournerait `require_authenticated` (risque connu, ADR-0015). Ce
    contournement doit **échouer** le test d'invariant, pas passer inaperçu.
    """

    return [
        str(getattr(route, "path", route))
        for route in getattr(app, "routes", ())
        if not isinstance(route, APIRoute)
        and getattr(route, "path", None) not in DOC_ROUTE_PATHS
        and next(iter_api_routes(route), None) is None
    ]


def unprotected_routes(app: Any) -> list[str]:
    """Routes **ni** publiques-listées **ni** protégées — doit toujours être vide.

    C'est l'invariant deny-by-default rendu exécutable : toute route de
    l'application est soit dans `PUBLIC_ROUTE_PATHS` (choix conscient et revu),
    soit porteuse d'une garde de `Principal`.
    """

    return [
        f"{sorted(route.methods or [])} {route.path}"
        for route in iter_api_routes(app)
        if not is_public_path(route.path) and not route_requires_principal(route)
    ]


# --------------------------------------------------------------------------- #
# Traduction des refus en HTTP (jamais `str(exc)`).
# --------------------------------------------------------------------------- #
def _unauthenticated() -> HTTPException:
    """`401` générique + `WWW-Authenticate: Bearer` (motif jamais divulgué)."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_UNAUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str = _FORBIDDEN_DETAIL) -> HTTPException:
    """`403` générique — identique pour un rôle insuffisant et un accès inter-salons."""

    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _token_service(request: Request) -> TokenService:
    """`TokenService` déposé sur `app.state` ; `503` si `JWT_SECRET` n'est pas configuré.

    Cohérent avec `/auth/login` (#10) : sans secret, le service d'authentification
    est **indisponible** (503) — jamais « ouvert ».
    """

    service = getattr(request.app.state, "token_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_JWT_UNAVAILABLE_DETAIL,
        )
    return service


def _verify_access(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> TokenClaims:
    """Vérifie l'en-tête `Authorization: Bearer <access_token>` (contrôle *stateless*).

    Signature + `exp` + `type == "access"` uniquement : **aucune lecture de base**
    (une requête protégée ne paie pas une session pour être rejetée). La fraîcheur
    du rôle et du statut est vérifiée juste après par `get_current_principal`.
    """

    if credentials is None or not credentials.credentials:
        # En-tête absent, vide, ou schéma non-`Bearer` (HTTPBearer renvoie alors
        # `None` puisque `auto_error=False`).
        raise _unauthenticated()

    service = _token_service(request)
    try:
        return service.verify_access(credentials.credentials)
    except (InvalidToken, ExpiredToken, NotAuthenticated) as exc:
        # Jeton illisible, signature invalide, `alg` inattendu, expiré, **ou
        # refresh présenté comme jeton d'accès** : même 401, même message.
        raise _unauthenticated() from exc


# --------------------------------------------------------------------------- #
# Dépendance **globale** : deny-by-default.
# --------------------------------------------------------------------------- #
def require_authenticated(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> None:
    """Ferme **toutes** les routes, sauf celles de `PUBLIC_ROUTE_PATHS`.

    Enregistrée sur l'application (`FastAPI(dependencies=[...])`), elle s'applique
    à tous les routers. Les claims validés sont déposés sur
    `request.state.token_claims` pour éviter un second décodage en aval.

    Une route publique **ne déclenche aucune I/O** (ni décodage, ni session de
    base) : `/health` reste une sonde sans coût.
    """

    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    if is_public_path(path):
        return

    request.state.token_claims = _verify_access(request, credentials)


# --------------------------------------------------------------------------- #
# Assemblage des ports (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_user_repository(
    session: Annotated[Session, Depends(get_session)],
) -> UserRepository:
    """Dépôt d'utilisateurs adossé à la session de la requête."""

    return SqlUserRepository(session)


def get_salon_scope_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SalonScopeRepository:
    """Dépôt de portée salon adossé à la session de la requête (isolation §11.2)."""

    return SqlSalonScopeRepository(session)


def get_access_policy(
    scope_repository: Annotated[
        SalonScopeRepository, Depends(get_salon_scope_repository)
    ],
) -> AccessPolicy:
    """Politique d'autorisation (permissions §4.1 + portée §11.2)."""

    return AccessPolicy(scope_repository)


# --------------------------------------------------------------------------- #
# Dépendance de route : identité **relue en base**.
# --------------------------------------------------------------------------- #
def get_current_principal(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> Principal:
    """Résout l'utilisateur courant : claims → compte **relu en base** → `Principal`.

    Le rôle et le statut proviennent **de la base**, jamais du claim `role` : une
    rétrogradation ou une suspension prend effet immédiatement, sans attendre
    l'expiration du jeton d'accès (ADR-0015).

    - compte introuvable (jeton d'un compte supprimé) → `401` générique ;
    - compte non `ACTIVE` → `403` « Compte désactivé. » (le porteur d'un jeton
      signé **est** le titulaire du compte : le lui dire n'est pas une fuite) ;
    - sinon → `Principal` (sans PII).
    """

    claims: TokenClaims | None = getattr(request.state, "token_claims", None)
    if claims is None:
        # Repli : la garde globale n'a pas tourné (route montée hors du système de
        # dépendances, test isolé). On revérifie plutôt que de faire confiance.
        claims = _verify_access(request, credentials)

    account = users.find_by_id(claims.sub)
    if account is None:
        raise _unauthenticated()
    if account.status != UserStatus.ACTIVE.value:
        raise _forbidden(_INACTIVE_ACCOUNT_DETAIL)

    return Principal(id=account.id, role=account.role, status=account.status)


_mark_principal_guard(get_current_principal)


# --------------------------------------------------------------------------- #
# Fabriques de gardes — composables, réutilisées par toutes les issues suivantes.
# --------------------------------------------------------------------------- #
def require_roles(*roles: Role) -> Callable[..., Principal]:
    """Garde de **rôle** : `403` si le compte ne porte aucun des rôles listés."""

    def guard(
        principal: Annotated[Principal, Depends(get_current_principal)],
        policy: Annotated[AccessPolicy, Depends(get_access_policy)],
    ) -> Principal:
        try:
            policy.require_roles(principal, *roles)
        except PermissionDenied as exc:
            raise _forbidden() from exc
        return principal

    return _mark_principal_guard(guard)


def require_permission(permission: Permission) -> Callable[..., Principal]:
    """Garde de **permission** (matrice PRD §4.1) : `403` si le rôle ne l'a pas."""

    def guard(
        principal: Annotated[Principal, Depends(get_current_principal)],
        policy: Annotated[AccessPolicy, Depends(get_access_policy)],
    ) -> Principal:
        try:
            policy.require_permission(principal, permission)
        except PermissionDenied as exc:
            raise _forbidden() from exc
        return principal

    return _mark_principal_guard(guard)


def require_any_permission(*permissions: Permission) -> Callable[..., Principal]:
    """Garde de **permission composable** : `403` si le rôle n'en détient **aucune**.

    Élargissement lisible et testé (issue #15) : `GET /salons/{salon_id}` doit
    laisser passer le `MANAGER`/`HAIRDRESSER` (`SALON_READ_OWN`) **et** l'`ADMIN`
    (`SALON_READ_ANY`, matrice §4.1) — `require_permission` seule exclurait l'un
    d'eux. La portée (`require_salon_scope`) reste appliquée **en plus** : ce n'est
    pas un contournement, seulement un « OU » de permissions. Ne jamais l'employer
    pour élargir un droit sans revue (cf. Risques du spec).
    """

    def guard(
        principal: Annotated[Principal, Depends(get_current_principal)],
        policy: Annotated[AccessPolicy, Depends(get_access_policy)],
    ) -> Principal:
        for permission in permissions:
            try:
                policy.require_permission(principal, permission)
            except PermissionDenied:
                continue
            return principal
        raise _forbidden()

    return _mark_principal_guard(guard)


def require_salon_scope(
    salon_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    policy: Annotated[AccessPolicy, Depends(get_access_policy)],
) -> SalonScope:
    """Garde de **portée salon** (isolation PRD §11.2) : `403` hors périmètre.

    Convention : les ressources à portée salon sont montées sous
    `/salons/{salon_id}/…` — `salon_id` est lu du chemin. La portée est **chargée
    en base** (propriété du gérant, RDV assignés du coiffeur) ; le `salon_id` de la
    requête n'est qu'une **cible à valider**. Un accès inter-salons est refusé par
    un `403` **identique** à celui d'un rôle insuffisant (aucun oracle d'existence).

    Retourne la portée chargée, que le handler peut réutiliser sans seconde requête.
    """

    try:
        return policy.require_salon(principal, salon_id)
    except PermissionDenied as exc:
        raise _forbidden() from exc


_mark_principal_guard(require_salon_scope)


__all__ = [
    "bearer_scheme",
    "PUBLIC_ROUTE_PATHS",
    "require_authenticated",
    "get_current_principal",
    "get_user_repository",
    "get_salon_scope_repository",
    "get_access_policy",
    "require_roles",
    "require_permission",
    "require_any_permission",
    "require_salon_scope",
    "is_public_path",
    "is_principal_guard",
    "route_requires_principal",
    "iter_api_routes",
    "unprotected_routes",
    "foreign_routes",
    "DOC_ROUTE_PATHS",
]
