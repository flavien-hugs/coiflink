"""Adapter entrant (driving) : router HTTP des **fiches clients** (US-4.1, #28).

Expose la **création d'une fiche client rattachée au salon** (critère
d'acceptation) et les deux lectures minimales qui la rendent observable — liste
paginée du salon et consultation d'une fiche — sous
`/salons/{salon_id}/customers`, imbriqué sous le salon pour hériter de
`require_salon_scope` (le `salon_id` est dans le chemin, isolation §11.2).

Le router traduit HTTP → commande applicative, assemble les cas d'usage par
injection de dépendances FastAPI, puis retraduit les erreurs de domaine :

- `InvalidCustomerName` / `InvalidPhone` / `InvalidCustomerGender` /
  `InvalidCustomerNotes` → **422** ;
- `CustomerAlreadyExists` (téléphone déjà fiché dans ce salon) → **409** ;
- `CustomerNotFound` → **404** *(uniquement après validation de portée)*.

Sécurité (RBAC #12, ADR-0015 ; ADR-0026) :
- **toutes** les routes déclarent `require_permission(CUSTOMER_MANAGE)` **et**
  `require_salon_scope`. #28 est la **première mise en service** de
  `CUSTOMER_MANAGE` (permission §4.1 déjà présente dans la matrice) : la matrice
  `ROLE_PERMISSIONS` n'est **pas** modifiée — seul le `MANAGER` la détient (ni le
  `CLIENT`, ni le `HAIRDRESSER`, ni l'`ADMIN`) ;
- l'**acteur** journalisé est le `Principal` (`principal.id`), jamais lu du corps ;
- **aucun chemin n'est ajouté à `PUBLIC_ROUTE_PATHS`** : une fiche client (PII,
  §11.3) n'est jamais lisible sans jeton.

Journalisation §11.4/§11.3 : la création enregistre une `AuditEntry` **neutre**
(`metadata` vide) dans la **même Session** que l'écriture (atomicité). Ni les
messages d'erreur, ni les logs applicatifs ne portent de nom, téléphone ou note.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.customer_repository import (
    SqlCustomerRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.customers import (
    CreateCustomer,
    CustomerCommand,
    GetCustomer,
    ListSalonCustomers,
)
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.customer_repository import (
    CUSTOMER_LIMIT_DEFAULT,
    CUSTOMER_LIMIT_MAX,
    CUSTOMER_LIMIT_MIN,
    CustomerRepository,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.customer import (
    CUSTOMER_NAME_MAX_LENGTH,
    GENDER_VALUES,
    NOTES_MAX_LENGTH,
    Customer,
)
from coiflink_api.domain.errors import (
    CustomerAlreadyExists,
    CustomerNotFound,
    InvalidCustomerGender,
    InvalidCustomerName,
    InvalidCustomerNotes,
    InvalidPhone,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["customers"])

# Erreurs de validation du domaine → 422 (jamais `str(exc)` sur un refus RBAC).
_VALIDATION_ERRORS = (
    InvalidCustomerName,
    InvalidPhone,
    InvalidCustomerGender,
    InvalidCustomerNotes,
)


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `services.py`).
# --------------------------------------------------------------------------- #
class CreateCustomerRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/customers`.

    **Aucun** champ privilégié dans le corps : le `salon_id` vient de la portée
    validée ; `id`, `user_id`, `total_visits` et `last_visit_at` sont générés ou
    laissés à leur défaut base. Un champ privilégié présent est **ignoré**
    (`extra="ignore"`).

    Seul `full_name` est requis (US-4.1). `phone` est **optionnel** (fiche
    walk-in) et normalisé en E.164 côté domaine ; `gender` est **optionnel** et
    fermé (`FEMALE` | `MALE` | `OTHER`, `null` = non renseigné) ; `notes` est
    **interne au salon** et n'est jamais exposée au client.
    """

    model_config = ConfigDict(extra="ignore")

    full_name: str = Field(
        min_length=1, max_length=CUSTOMER_NAME_MAX_LENGTH, examples=["Awa Koné"]
    )
    phone: str | None = Field(default=None, examples=["0700000000"])
    gender: str | None = Field(default=None, examples=[GENDER_VALUES[0]])
    notes: str | None = Field(
        default=None,
        max_length=NOTES_MAX_LENGTH,
        examples=["Préfère le samedi matin."],
    )


class CustomerResponse(BaseModel):
    """Représentation d'une fiche client renvoyée par l'API.

    **`user_id` n'est pas exposé** : il vaut toujours `NULL` dans ce périmètre et
    son exposition renseignerait sur l'existence d'un compte (anti-oracle
    §11.1/§11.3, ADR-0026). `last_visit_at`/`total_visits` restent à leurs défauts
    tant que #29 (historique des visites) n'est pas livrée.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    full_name: str
    phone: str | None
    gender: str | None
    notes: str | None
    last_visit_at: object
    total_visits: int
    created_at: object
    updated_at: object


class CustomerPageResponse(BaseModel):
    """Réponse paginée de `GET /salons/{salon_id}/customers` : items + total + bornes."""

    items: list[CustomerResponse]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_customer_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CustomerRepository:
    """Dépôt de fiches clients adossé à la session de la requête."""

    return SqlCustomerRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité).

    FastAPI met en cache la dépendance `get_session` par requête : le dépôt de
    fiches et le journal d'audit partagent donc la **même** `Session`, d'où le
    commit/rollback conjoint de la création et de sa trace.
    """

    return SqlAuditLog(session)


def _customer_response(customer: Customer) -> CustomerResponse:
    return CustomerResponse(
        id=customer.id,
        salon_id=customer.salon_id,
        full_name=customer.full_name,
        phone=customer.phone,
        gender=customer.gender,
        notes=customer.notes,
        last_visit_at=customer.last_visit_at,
        total_visits=customer.total_visits,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une fiche client rattachée au salon",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        409: {"description": "Une fiche porte déjà ce téléphone dans ce salon"},
        422: {"description": "Nom, téléphone, genre ou notes invalides"},
    },
)
def create_customer(
    salon_id: uuid.UUID,
    payload: CreateCustomerRequest,
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
) -> CustomerResponse:
    """Crée une fiche client (walk-in, `user_id = NULL`) pour le salon de la portée.

    Le `salon_id` vient du chemin (portée), jamais du corps. Journalise
    `CUSTOMER_CREATED` (§11.4/§11.3) dans la même unité de travail, avec un
    `metadata` **vide** — aucune PII au journal.
    """

    try:
        customer = CreateCustomer(repository, audit_log).execute(
            salon_id,
            CustomerCommand(
                full_name=payload.full_name,
                phone=payload.phone,
                gender=payload.gender,
                notes=payload.notes,
            ),
            actor_user_id=principal.id,
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except CustomerAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _customer_response(customer)


@router.get(
    "/{salon_id}/customers",
    response_model=CustomerPageResponse,
    summary="Lister les fiches clients du salon (paginé, plus récentes d'abord)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def list_customers(
    salon_id: uuid.UUID,
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
    limit: int = Query(
        default=CUSTOMER_LIMIT_DEFAULT, ge=CUSTOMER_LIMIT_MIN, le=CUSTOMER_LIMIT_MAX
    ),
    offset: int = Query(default=0, ge=0),
) -> CustomerPageResponse:
    """Liste **seulement** les fiches du salon de la portée (isolation §11.2)."""

    page, total = ListSalonCustomers(repository).execute(
        salon_id, limit=limit, offset=offset
    )
    return CustomerPageResponse(
        items=[_customer_response(customer) for customer in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{salon_id}/customers/{customer_id}",
    response_model=CustomerResponse,
    summary="Consulter une fiche client du salon",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Fiche introuvable (portée déjà validée)"},
    },
)
def get_customer(
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
) -> CustomerResponse:
    """Consulte la fiche `(salon_id, customer_id)` (isolation §11.2)."""

    try:
        customer = GetCustomer(repository).execute(salon_id, customer_id)
    except CustomerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _customer_response(customer)


__all__ = ["router"]
