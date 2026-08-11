"""Adapter entrant (driving) : router HTTP **borne kiosque — identité walk-in** (US-8.2, #156).

Expose au rôle `KIOSK` (compte de service d'une borne, ADR-0041) les deux
opérations d'identité du parcours « client sans rendez-vous » (PRD §17), sous
`/salons/{salon_id}/kiosk/customers[...]`, imbriquées sous le salon pour hériter de
`require_salon_scope` (le `salon_id` est dans le chemin, isolation §11.2) :

- `POST /salons/{salon_id}/kiosk/customers/lookup` — retrouve une fiche par
  **téléphone** (salon de la borne uniquement), réponse **minimale** (prénom seul) ;
- `POST /salons/{salon_id}/kiosk/customers` — crée une fiche walk-in
  (**prénom + nom + téléphone**, sans mot de passe, `user_id = NULL`).

`POST` (jamais `GET`) : le numéro voyage en **corps de requête**, jamais en query
string — pas de PII dans les URL, les logs d'accès, l'historique des proxies ou les
traces.

Le router traduit HTTP → commande applicative, assemble les cas d'usage par
injection de dépendances FastAPI, puis retraduit les erreurs de domaine :

- `InvalidPhone` / `InvalidCustomerName` → **422** ;
- `CustomerAlreadyExists` (téléphone déjà fiché dans ce salon) → **409** ;
- `TooManyLoginAttempts` (anti-énumération du lookup) → **429** + `Retry-After` ;
- fiche introuvable → **404** neutre (sans écho du numéro).

Sécurité (RBAC #12, ADR-0015/0041 ; anti-oracle ADR-0026) :
- chaque route déclare `require_salon_scope` **et** la permission `KIOSK` **dédiée**
  déjà livrée par #155 (`CUSTOMER_LOOKUP_KIOSK` / `CUSTOMER_CREATE_WALKIN`) : la
  matrice `ROLE_PERMISSIONS` n'est **pas** modifiée, `CUSTOMER_MANAGE` reste
  MANAGER-seul. Un JWT `CLIENT`/`MANAGER`/`HAIRDRESSER`/`ADMIN` est refusé (`403`
  générique) sur ces routes ; un credential `KIOSK` reste incapable d'atteindre
  `CUSTOMER_MANAGE` ou `APPOINTMENT_BOOK` (moindre privilège) ;
- **aucun** chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : « réservé au rôle KIOSK »
  signifie *atteignable par un device provisionné*, jamais *public* ;
- la réponse est la projection **minimale** `WalkInIdentity` (`customer_id` +
  `first_name`) — jamais le nom complet, le téléphone, le genre, les notes ni les
  compteurs de visites ; le numéro soumis n'apparaît dans aucun message ou log.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from coiflink_api.adapters.inbound.auth import _client_ip
from coiflink_api.adapters.inbound.customers import (
    get_audit_log,
    get_customer_repository,
)
from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.application.kiosk_customers import (
    CreateWalkInCustomer,
    IdentifyWalkInCustomer,
)
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.config import AuthConfig
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.customer import (
    CUSTOMER_NAME_MAX_LENGTH,
    WalkInCustomerCommand,
    WalkInIdentity,
)
from coiflink_api.domain.errors import (
    CustomerAlreadyExists,
    InvalidCustomerName,
    InvalidPhone,
    TooManyLoginAttempts,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["kiosk"])

# Message **neutre constant** d'un lookup infructueux : il ne rappelle jamais le
# numéro soumis (anti-oracle / non-fuite de PII, §11.3).
_NOT_FOUND_DETAIL = "Aucune fiche pour ce numéro dans ce salon."
# Message **générique** d'anti-énumération (patron `/auth/kiosk/login`, #155).
_RATE_LIMITED_DETAIL = "Trop de tentatives. Réessayez plus tard."

# Bornes du téléphone en entrée, alignées sur `users.phone`/`RegisterRequest` :
# corps borné (budget §12.1), toute normalisation réelle revient à `normalize_phone`.
_PHONE_MIN_LENGTH = 1
_PHONE_MAX_LENGTH = 32


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `customers.py`).
# --------------------------------------------------------------------------- #
class KioskLookupRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/kiosk/customers/lookup`.

    **Aucun** champ privilégié : le `salon_id` vient de la portée validée (chemin),
    jamais du corps. Un champ superflu est **ignoré** (`extra="ignore"`). Le
    téléphone est toléré en **tout format** (séparateurs, national, international) —
    la normalisation E.164 est faite côté serveur (`normalize_phone`).
    """

    model_config = ConfigDict(extra="ignore")

    phone: str = Field(
        min_length=_PHONE_MIN_LENGTH,
        max_length=_PHONE_MAX_LENGTH,
        examples=["07 00 00 00 00"],
    )


class KioskWalkInCreateRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/kiosk/customers` — création walk-in.

    Les **trois** champs sont requis (US-8.2). **Aucun** champ privilégié : tout
    `salon_id`, `user_id`, `gender`, `notes`, `total_visits` présent au corps est
    **ignoré** (`extra="ignore"`) — collecte minimale (§11.3), la fiche reste
    walk-in (`user_id = NULL`, aucun mot de passe).
    """

    model_config = ConfigDict(extra="ignore")

    first_name: str = Field(
        min_length=1, max_length=CUSTOMER_NAME_MAX_LENGTH, examples=["Awa"]
    )
    last_name: str = Field(
        min_length=1, max_length=CUSTOMER_NAME_MAX_LENGTH, examples=["Koné"]
    )
    phone: str = Field(
        min_length=_PHONE_MIN_LENGTH,
        max_length=_PHONE_MAX_LENGTH,
        examples=["0700000000"],
    )


class WalkInIdentityResponse(BaseModel):
    """Projection **minimale** renvoyée à la borne : `customer_id` + `first_name`.

    **Jamais** le nom complet, le téléphone (même celui qui vient d'être saisi), le
    genre, les notes ni les compteurs de visites (exposition minimale de PII sur un
    écran public, §11.3). Le `customer_id` est le `customer_profile_id` que la
    création de ticket #157 consommera.
    """

    customer_id: uuid.UUID
    first_name: str


def _identity_response(identity: WalkInIdentity) -> WalkInIdentityResponse:
    return WalkInIdentityResponse(
        customer_id=identity.customer_id, first_name=identity.first_name
    )


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_kiosk_lookup_rate_limiter(request: Request) -> LoginRateLimiter:
    """Limiteur anti-énumération **dédié au lookup kiosque** (singleton `app.state`).

    Réutilise le port `LoginRateLimiter` et l'adapter `InMemoryLoginRateLimiter`
    exactement comme #155 pour `/auth/kiosk/login` — mais avec un **singleton
    distinct** (`kiosk_lookup_rate_limiter`) et des seuils propres au lookup :
    verrouiller les recherches d'une borne ne doit pas verrouiller son login (et
    inversement). Repli sûr avec les seuils kiosque d'`AuthConfig` si l'état n'est
    pas configuré (tests isolés).
    """

    limiter = getattr(request.app.state, "kiosk_lookup_rate_limiter", None)
    if limiter is None:
        from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
            InMemoryLoginRateLimiter,
        )

        config: AuthConfig = (
            getattr(request.app.state, "auth_config", None) or AuthConfig()
        )
        limiter = InMemoryLoginRateLimiter(
            max_attempts=config.kiosk_lookup_max_attempts,
            window=config.kiosk_lookup_window,
            lockout=config.kiosk_lookup_lockout,
        )
        request.app.state.kiosk_lookup_rate_limiter = limiter
    return limiter


def get_identify_walk_in_customer(
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    rate_limiter: Annotated[
        LoginRateLimiter, Depends(get_kiosk_lookup_rate_limiter)
    ],
) -> IdentifyWalkInCustomer:
    """Assemble le cas d'usage de **recherche** par téléphone (aucune règle métier ici)."""

    return IdentifyWalkInCustomer(repository, rate_limiter)


def get_create_walk_in_customer(
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> CreateWalkInCustomer:
    """Assemble le cas d'usage de **création** walk-in (dépôt clients + audit)."""

    return CreateWalkInCustomer(repository, audit_log)


def _rate_key(principal: Principal, request: Request) -> str:
    """Clé de débit **opaque** : device (compte de service) + IP client, jamais le numéro.

    Le device est une ligne `users` (ADR-0041) : `principal.id` est l'identité du
    terminal. L'IP est extraite par `_client_ip` (patron `/auth/login`, #10). La
    clé ne porte **jamais** le téléphone soumis (§11.3).
    """

    return f"{principal.id}|{_client_ip(request)}"


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/kiosk/customers/lookup",
    response_model=WalkInIdentityResponse,
    status_code=status.HTTP_200_OK,
    summary="Borne — retrouver une fiche client par téléphone (réponse minimale : prénom seul)",
    responses={
        200: {"description": "Fiche trouvée — projection minimale (customer_id + first_name)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Aucune fiche pour ce numéro dans ce salon (neutre, sans écho du numéro)"},
        422: {"description": "Numéro de téléphone invalide"},
        429: {"description": "Trop de tentatives (anti-énumération par device + IP)"},
    },
)
def lookup_walk_in_customer(
    salon_id: uuid.UUID,
    payload: KioskLookupRequest,
    request: Request,
    usecase: Annotated[
        IdentifyWalkInCustomer, Depends(get_identify_walk_in_customer)
    ],
    # Gardes RBAC (#12) : portée salon §11.2 **et** permission KIOSK dédiée (#155).
    # `salon_id` est lu du chemin par `require_salon_scope` ; les deux dépendances
    # résolvent le même `Principal` (pas de double lecture de compte).
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_LOOKUP_KIOSK))
    ],
) -> WalkInIdentityResponse:
    """Retrouve la fiche `(salon_id, phone)` et n'en renvoie que le **prénom**.

    Le `salon_id` vient du chemin (portée), jamais du corps. Un format invalide →
    `422` ; une fiche absente → `404` **neutre** (jamais l'écho du numéro) ; une
    fenêtre de débit verrouillée → `429` + `Retry-After`. Lecture **sans audit**
    (ADR-0026). La traçabilité passe par la limitation de débit (clé opaque
    device + IP).
    """

    try:
        identity = usecase.execute(
            salon_id, payload.phone, rate_key=_rate_key(principal, request)
        )
    except TooManyLoginAttempts as exc:
        headers = (
            {"Retry-After": str(exc.retry_after)}
            if exc.retry_after is not None
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_RATE_LIMITED_DETAIL,
            headers=headers,
        ) from exc
    except InvalidPhone as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if identity is None:
        # `404` **neutre constant** : jamais l'écho du numéro soumis (§11.3).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        )
    return _identity_response(identity)


@router.post(
    "/{salon_id}/kiosk/customers",
    response_model=WalkInIdentityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Borne — créer une fiche client walk-in (prénom + nom + téléphone, sans mot de passe)",
    responses={
        201: {"description": "Fiche créée — projection minimale (customer_id + first_name)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        409: {"description": "Une fiche porte déjà ce téléphone dans ce salon"},
        422: {"description": "Prénom, nom ou téléphone invalide"},
    },
)
def create_walk_in_customer(
    salon_id: uuid.UUID,
    payload: KioskWalkInCreateRequest,
    usecase: Annotated[
        CreateWalkInCustomer, Depends(get_create_walk_in_customer)
    ],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_CREATE_WALKIN))
    ],
) -> WalkInIdentityResponse:
    """Crée une fiche walk-in (`user_id = NULL`, sans mot de passe) pour le salon de la portée.

    Le `salon_id` vient du chemin (portée), jamais du corps ; `gender`/`notes` ne
    sont **jamais** collectés (§11.3). Journalise `CUSTOMER_CREATED` (§11.4) dans la
    même unité de travail, `metadata` **vide** (aucune PII), acteur = `principal.id`
    du compte de service de la borne. Doublon de téléphone → `409` neutre (la borne
    relance alors le lookup, contrat #159) ; champ invalide → `422`.
    """

    try:
        identity = usecase.execute(
            salon_id,
            WalkInCustomerCommand(
                first_name=payload.first_name,
                last_name=payload.last_name,
                phone=payload.phone,
            ),
            actor_user_id=principal.id,
        )
    except (InvalidCustomerName, InvalidPhone) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except CustomerAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _identity_response(identity)


__all__ = [
    "router",
    "KioskLookupRequest",
    "KioskWalkInCreateRequest",
    "WalkInIdentityResponse",
    "get_kiosk_lookup_rate_limiter",
]
