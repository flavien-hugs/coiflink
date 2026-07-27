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

import datetime
import decimal
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
    GetCustomerServiceStats,
    GetCustomerVisitHistory,
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
from coiflink_api.domain.visit import (
    CustomerServiceStats,
    CustomerVisit,
    VisitHistory,
)

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


class VisitServiceResponse(BaseModel):
    """Prestation d'une visite : libellé + prix figé (US-4.2, #29).

    `price_at_booking` est le prix **figé à la réservation** (`NUMERIC(12,2)`
    sérialisé en chaîne décimale, jamais de flottant), jamais le tarif courant.
    """

    service_id: uuid.UUID
    name: str
    price_at_booking: decimal.Decimal


class CustomerVisitResponse(BaseModel):
    """Une visite terminée : date, créneau, prestations nommées et montant total.

    **`client_id`/`user_id` ne sont pas exposés** (anti-oracle ADR-0026) : seule
    l'identité du RDV (`appointment_id`) et ses données de visite sont renvoyées.
    """

    appointment_id: uuid.UUID
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    status: str
    services: list[VisitServiceResponse]
    total_amount: decimal.Decimal


class CustomerVisitHistoryResponse(BaseModel):
    """Historique des visites d'une fiche + résumé **dérivé en lecture** (US-4.2, #29).

    `total_visits`/`last_visit_at`/`total_amount` sont calculés à la volée depuis
    les visites `COMPLETED` (jamais lus des colonnes dénormalisées de
    `customer_profiles`). Fiche walk-in ou sans visite → `items: []`,
    `total_visits: 0`, `last_visit_at: null`, `total_amount: "0"` (comportement
    normal, pas une erreur). Devise **XOF** (§9.6).
    """

    customer_id: uuid.UUID
    items: list[CustomerVisitResponse]
    total_visits: int
    last_visit_at: datetime.datetime | None
    total_amount: decimal.Decimal
    currency: str


class ServiceFrequencyResponse(BaseModel):
    """Une prestation dans le classement des préférences d'un client (US-4.3, #31).

    `count` = nombre d'occurrences **réalisées** (`COMPLETED`) ; `total_amount` =
    somme des `price_at_booking` de cette prestation (prix **figés**, `NUMERIC(12,2)`
    sérialisé en chaîne décimale, jamais de flottant). `name` est le libellé
    **courant** (résoluble même si la prestation est soft-deletée).
    """

    service_id: uuid.UUID
    name: str
    count: int
    total_amount: decimal.Decimal


class CustomerServiceStatsResponse(BaseModel):
    """Prestations préférées d'une fiche : classement **dérivé en lecture** (US-4.3, #31).

    Les prestations sont classées de la **plus fréquente à la moins fréquente**.
    `total_visits`/`total_services` sont dérivés à la volée des visites `COMPLETED`
    (jamais persistés). Fiche walk-in ou sans visite → `services: []`,
    `total_visits: 0`, `total_services: 0` (comportement **normal**, pas une
    erreur). **`user_id`/`client_id` ne sont jamais exposés** (anti-oracle
    ADR-0026). Devise **XOF** (§9.6).
    """

    customer_id: uuid.UUID
    services: list[ServiceFrequencyResponse]
    total_visits: int
    total_services: int
    currency: str


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


def _visit_response(visit: CustomerVisit) -> CustomerVisitResponse:
    return CustomerVisitResponse(
        appointment_id=visit.appointment_id,
        date=visit.date,
        start_time=visit.start_time,
        end_time=visit.end_time,
        status=visit.status,
        services=[
            VisitServiceResponse(
                service_id=service.service_id,
                name=service.name,
                price_at_booking=service.price_at_booking,
            )
            for service in visit.services
        ],
        total_amount=visit.total_amount,
    )


def _history_response(
    customer_id: uuid.UUID, history: VisitHistory
) -> CustomerVisitHistoryResponse:
    return CustomerVisitHistoryResponse(
        customer_id=customer_id,
        items=[_visit_response(visit) for visit in history.visits],
        total_visits=history.total_visits,
        last_visit_at=history.last_visit_at,
        total_amount=history.total_amount,
        currency=history.currency,
    )


def _stats_response(
    customer_id: uuid.UUID, stats: CustomerServiceStats
) -> CustomerServiceStatsResponse:
    return CustomerServiceStatsResponse(
        customer_id=customer_id,
        services=[
            ServiceFrequencyResponse(
                service_id=service.service_id,
                name=service.name,
                count=service.count,
                total_amount=service.total_amount,
            )
            for service in stats.services
        ],
        total_visits=stats.total_visits,
        total_services=stats.total_services,
        currency=stats.currency,
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


@router.get(
    "/{salon_id}/customers/{customer_id}/appointments",
    response_model=CustomerVisitHistoryResponse,
    summary="Historique des visites terminées d'un client (prestations + montants)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Fiche introuvable (portée déjà validée)"},
    },
)
def get_customer_history(
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
) -> CustomerVisitHistoryResponse:
    """Historique des visites `COMPLETED` de la fiche `(salon_id, customer_id)` (US-4.2, #29).

    Lecture **fiche-scopée** : la fiche est résolue dans le salon (`404` **après**
    portée si hors salon/inconnue, sans oracle) puis ses RDV terminés liés sont
    lus (lien `user_id` encapsulé côté dépôt, `salon_id` refiltré en SQL). Le
    résumé (`total_visits`, `last_visit_at`, `total_amount`) est **dérivé en
    lecture**. Une fiche walk-in ou sans visite réalisée → `items: []` (comportement
    normal). Aucune écriture, aucun audit — ni `user_id`/`client_id` exposés.
    """

    try:
        history = GetCustomerVisitHistory(repository).execute(salon_id, customer_id)
    except CustomerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _history_response(customer_id, history)


@router.get(
    "/{salon_id}/customers/{customer_id}/stats",
    response_model=CustomerServiceStatsResponse,
    summary="Prestations préférées d'un client (les plus fréquentes)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Fiche introuvable (portée déjà validée)"},
    },
)
def get_customer_stats(
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
) -> CustomerServiceStatsResponse:
    """Prestations préférées de la fiche `(salon_id, customer_id)` (US-4.3, #31).

    Lecture **fiche-scopée** dérivée des visites `COMPLETED` (réutilise la brique
    #29, **aucun nouvel accès base**) : la fiche est résolue dans le salon (`404`
    **après** portée si hors salon/inconnue, sans oracle) puis ses visites
    terminées liées sont agrégées **par `service_id`** et classées de la plus
    fréquente à la moins fréquente. Une fiche walk-in ou sans visite réalisée →
    `services: []` (comportement normal). Montants **figés** (`price_at_booking`,
    XOF). Aucune écriture, aucun audit — ni `user_id`/`client_id` exposés.
    """

    try:
        stats = GetCustomerServiceStats(repository).execute(salon_id, customer_id)
    except CustomerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _stats_response(customer_id, stats)


__all__ = ["router"]
