"""Adapter entrant (driving) : router HTTP **file d'attente walk-in** (US-8.3, #157).

Expose les trois opérations du ticket de passage sous
`/salons/{salon_id}/queue/tickets[...]`, imbriquées sous le salon pour hériter de
`require_salon_scope` (le `salon_id` est dans le chemin, isolation §11.2) :

- `POST /salons/{salon_id}/queue/tickets` — **rejoindre la file** (borne `KIOSK`,
  permission `QUEUE_TICKET_CREATE` livrée par #155) : crée un ticket `waiting`,
  renvoie `ticket_number`, `estimated_wait_minutes` et l'heure d'émission (la borne
  imprime immédiatement, préalable de #160) ;
- `POST /salons/{salon_id}/queue/tickets/{ticket_id}/start` — **prise en charge**
  (coiffeuse / gérant, permission `APPOINTMENT_UPDATE_STATUS` réutilisée : mêmes
  acteurs que le démarrage d'un RDV) : assigne une coiffeuse et passe `in_progress` ;
- `POST /salons/{salon_id}/queue/tickets/{ticket_id}/complete` — **clôture** (idem) :
  passe `in_progress → done`.

Sécurité (RBAC #12, ADR-0015/0041 ; anti-oracle ADR-0026) : chaque route déclare
`require_salon_scope` **et** la permission dédiée ; un `salon_id` hors périmètre
device/gérant → `403` générique (jamais un `404` qui confirmerait le salon).
**Aucun** chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : « réservé au rôle KIOSK »
signifie *atteignable par un device provisionné*, jamais *public* (deny-by-default
inchangé). Le ticket est **indépendant d'`Appointment`** (ADR-0042) : aucune ligne
`appointments` n'est jamais écrite.

Traductions d'erreurs de domaine → HTTP : `InvalidQueueTicketServices` → **422** ;
`QueueTicketNotFound` / `HairdresserNotInSalon` (après portée) → **404** ;
`InvalidQueueTicketTransition` / `QueueTicketHairdresserRequired` → **409**.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.customers import get_customer_repository
from coiflink_api.adapters.inbound.security import (
    get_salon_scope_repository,
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.queue_ticket_repository import (
    SqlQueueTicketRepository,
)
from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    SqlSalonCatalogRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.application.ports.queue_ticket_repository import (
    QueueTicketRepository,
)
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
)
from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.application.queue_ticket import (
    CompleteQueueTicket,
    JoinQueue,
    JoinQueueCommand,
    StartQueueTicket,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import (
    HairdresserNotInSalon,
    InvalidQueueTicketServices,
    InvalidQueueTicketTransition,
    QueueTicketHairdresserRequired,
    QueueTicketNotFound,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.queue_ticket import QueueTicket

router = APIRouter(prefix="/salons", tags=["queue-tickets"])

# Borne de robustesse du nombre de prestations d'un ticket (budget §12.1) — un
# ticket walk-in porte quelques prestations, jamais un corps non borné.
_MAX_SERVICES_PER_TICKET = 20


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `kiosk_customers.py`).
# --------------------------------------------------------------------------- #
class JoinQueueRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/queue/tickets` — rejoindre la file.

    **Aucun** champ privilégié : le `salon_id` vient de la portée validée (chemin),
    tout `salon_id`/`ticket_number`/`status` présent au corps est **ignoré**
    (`extra="ignore"`). `customer_profile_id` est **optionnel** (`null` = ticket
    anonyme) ; `service_ids` porte **au moins une** prestation active du salon.
    """

    model_config = ConfigDict(extra="ignore")

    customer_profile_id: uuid.UUID | None = None
    service_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=_MAX_SERVICES_PER_TICKET
    )


class StartQueueTicketRequest(BaseModel):
    """Corps de `POST .../start` — prise en charge : la coiffeuse est **requise**.

    `hairdresser_id` doit être un membre `ACTIVE` du salon (validé serveur) : un
    ticket « en cours » sans coiffeuse n'a pas de sens métier.
    """

    model_config = ConfigDict(extra="ignore")

    hairdresser_id: uuid.UUID


class QueueTicketResponse(BaseModel):
    """Réponse `201` de l'émission d'un ticket (la borne imprime immédiatement).

    `ticket_number` est un **entier brut** (le zéro-padding « N° 014 » relève du
    formatter thermique #160). `estimated_wait_minutes` est **figé à l'émission**.
    """

    id: uuid.UUID
    ticket_number: int
    issued_date: datetime.date
    status: str
    estimated_wait_minutes: int
    created_at: datetime.datetime
    service_ids: list[uuid.UUID]


class QueueTicketActionResponse(BaseModel):
    """Réponse `200` d'une prise en charge / clôture (start & complete)."""

    id: uuid.UUID
    ticket_number: int
    status: str
    hairdresser_id: uuid.UUID | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None


def _ticket_response(ticket: QueueTicket) -> QueueTicketResponse:
    return QueueTicketResponse(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        issued_date=ticket.issued_date,
        status=ticket.status,
        estimated_wait_minutes=ticket.estimated_wait_minutes,
        created_at=ticket.created_at,
        service_ids=list(ticket.service_ids),
    )


def _action_response(ticket: QueueTicket) -> QueueTicketActionResponse:
    return QueueTicketActionResponse(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        status=ticket.status,
        hairdresser_id=ticket.hairdresser_id,
        started_at=ticket.started_at,
        completed_at=ticket.completed_at,
    )


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_queue_ticket_repository(
    session: Annotated[Session, Depends(get_session)],
) -> QueueTicketRepository:
    """Dépôt de tickets de passage adossé à la session de la requête."""

    return SqlQueueTicketRepository(session)


def get_catalog_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SalonCatalogRepository:
    """Dépôt de lecture du catalogue (prestations actives + coiffeuses actives)."""

    return SqlSalonCatalogRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité, patron #20)."""

    return SqlAuditLog(session)


def get_join_queue(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
    catalog: Annotated[SalonCatalogRepository, Depends(get_catalog_repository)],
    customers: Annotated[CustomerRepository, Depends(get_customer_repository)],
) -> JoinQueue:
    """Assemble le cas d'usage « rejoindre la file » (aucune règle métier ici)."""

    return JoinQueue(tickets, catalog, customers)


def get_start_queue_ticket(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
    scope: Annotated[SalonScopeRepository, Depends(get_salon_scope_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> StartQueueTicket:
    """Assemble le cas d'usage de **prise en charge** (dépôt + portée + audit)."""

    return StartQueueTicket(tickets, scope, audit_log)


def get_complete_queue_ticket(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> CompleteQueueTicket:
    """Assemble le cas d'usage de **clôture** (dépôt + audit)."""

    return CompleteQueueTicket(tickets, audit_log)


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/queue/tickets",
    response_model=QueueTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Borne — rejoindre la file walk-in (numéro de passage + estimation d'attente)",
    responses={
        201: {"description": "Ticket créé (waiting) — numéro, estimation, heure d'émission"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Fiche client hors salon / inexistante (après portée)"},
        422: {"description": "Prestation(s) invalide(s) — vide, inactive ou hors salon"},
    },
)
def join_queue(
    salon_id: uuid.UUID,
    payload: JoinQueueRequest,
    usecase: Annotated[JoinQueue, Depends(get_join_queue)],
    # Gardes RBAC (#12) : portée salon §11.2 **et** permission KIOSK dédiée (#155).
    # `salon_id` est lu du chemin par `require_salon_scope` ; les deux dépendances
    # résolvent le même `Principal` (pas de double lecture de compte).
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_CREATE))
    ],
) -> QueueTicketResponse:
    """Délivre un ticket `waiting` pour le salon de la portée (borne `KIOSK`).

    Le `salon_id` vient du chemin (portée), jamais du corps. Prestation(s)
    invalide(s) → `422` ; `customer_profile_id` d'un autre salon → `404` neutre
    (indiscernable, §11.2). Aucune écriture dans `appointments` (ADR-0042), aucun
    audit (émettre un ticket n'est pas une action de gestion §11.4).
    """

    try:
        ticket = usecase.execute(
            salon_id,
            JoinQueueCommand(
                customer_profile_id=payload.customer_profile_id,
                service_ids=tuple(payload.service_ids),
            ),
        )
    except InvalidQueueTicketServices as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except QueueTicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _ticket_response(ticket)


@router.post(
    "/{salon_id}/queue/tickets/{ticket_id}/start",
    response_model=QueueTicketActionResponse,
    summary="Prendre en charge un ticket walk-in (coiffeuse / gérant, §11.4, #157)",
    responses={
        200: {"description": "Ticket pris en charge (in_progress), coiffeuse assignée"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Ticket / coiffeuse hors salon ou inexistant (après portée)"},
        409: {"description": "Transition invalide (ticket déjà pris en charge / terminé)"},
    },
)
def start_queue_ticket(
    salon_id: uuid.UUID,
    ticket_id: uuid.UUID,
    payload: StartQueueTicketRequest,
    usecase: Annotated[StartQueueTicket, Depends(get_start_queue_ticket)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_UPDATE_STATUS))
    ],
) -> QueueTicketActionResponse:
    """Assigne une coiffeuse `ACTIVE` du salon et passe le ticket `in_progress`.

    Un ticket hors salon/inexistant est un `404` indiscernable ; une coiffeuse hors
    salon également (`HairdresserNotInSalon` → `404`, aucun oracle). Une transition
    depuis un statut non-`waiting` → `409`. Journalisé `QUEUE_TICKET_STARTED`.
    """

    try:
        ticket = usecase.execute(
            salon_id, ticket_id, payload.hairdresser_id, principal.id
        )
    except (InvalidQueueTicketTransition, QueueTicketHairdresserRequired) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (QueueTicketNotFound, HairdresserNotInSalon) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _action_response(ticket)


@router.post(
    "/{salon_id}/queue/tickets/{ticket_id}/complete",
    response_model=QueueTicketActionResponse,
    summary="Clôturer un ticket walk-in servi (coiffeuse / gérant, §11.4, #157)",
    responses={
        200: {"description": "Ticket clôturé (done)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Ticket hors salon ou inexistant (après portée)"},
        409: {"description": "Transition invalide (ticket pas encore démarré / déjà clôturé)"},
    },
)
def complete_queue_ticket(
    salon_id: uuid.UUID,
    ticket_id: uuid.UUID,
    usecase: Annotated[CompleteQueueTicket, Depends(get_complete_queue_ticket)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_UPDATE_STATUS))
    ],
) -> QueueTicketActionResponse:
    """Passe le ticket `in_progress → done`. Transition invalide → `409`. Journalisé."""

    try:
        ticket = usecase.execute(salon_id, ticket_id, principal.id)
    except InvalidQueueTicketTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except QueueTicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _action_response(ticket)


__all__ = [
    "router",
    "JoinQueueRequest",
    "StartQueueTicketRequest",
    "QueueTicketResponse",
    "QueueTicketActionResponse",
    "get_queue_ticket_repository",
    "get_catalog_repository",
    "get_audit_log",
]
