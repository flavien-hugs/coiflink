"""Adapter entrant (driving) : router HTTP **file d'attente walk-in** (US-8.3, #157).

Expose les opérations du ticket de passage sous
`/salons/{salon_id}/queue/tickets[...]`, imbriquées sous le salon pour hériter de
`require_salon_scope` (le `salon_id` est dans le chemin, isolation §11.2) :

- `GET /salons/{salon_id}/queue/tickets` — **lister la file** (gérant / coiffeuse,
  permission dédiée `QUEUE_TICKET_READ_SALON`, #148) : tickets **actifs** du jour
  (`waiting`/`called`/`in_progress`/`done`/`expired`), noms résolus, triés
  `ticket_number` — miroir direct de `ListSalonQueueTickets` (#150/#157). Un
  ticket `expired` (annulation manuelle, no-show) **reste visible** pour le
  reste de la journée, motif inclus (`cancellation_reason`) — jamais retiré de
  la liste. Route combinée « file d'attente » **simplifiée** au pivot walk-in
  exclusif : elle ne renvoyait plus qu'un seul bras (`walk_in_tickets`) depuis
  la suppression du bras `appointments` (ADR-0042 révoquée, #148) — désormais
  fusionnée ici plutôt que dupliquée dans un routeur RDV appelé à disparaître ;
- `POST /salons/{salon_id}/queue/tickets` — **rejoindre la file** (borne `TERMINAL`,
  permission `QUEUE_TICKET_CREATE` livrée par #155) : crée un ticket `waiting`,
  renvoie `ticket_number`, `estimated_wait_minutes`, `people_ahead_count` (tickets
  `waiting` encore devant celui-ci) et l'heure d'émission (la borne imprime
  immédiatement, préalable de #160) ;
- `POST /salons/{salon_id}/queue/tickets/{ticket_id}/start` — **prise en charge**
  (coiffeuse / gérant, permission dédiée `QUEUE_TICKET_UPDATE_STATUS`, #148) :
  assigne une coiffeuse et passe `in_progress` — refuse une coiffeuse déjà
  occupée sur un autre ticket `in_progress` (`409`, portée globale, #173) ;
- `POST /salons/{salon_id}/queue/tickets/{ticket_id}/complete` — **clôture** (idem) :
  passe `in_progress → done`.
- `POST /salons/{salon_id}/queue/tickets/{ticket_id}/cancel` — **annulation
  manuelle** (coiffeuse / gérant, no-show client, permission dédiée
  `QUEUE_TICKET_UPDATE_STATUS`) : passe `waiting`/`called → expired` avec un
  **motif obligatoire** (`reason`, revalidé côté domaine). Un ticket
  `in_progress` n'est **plus jamais** annulable ainsi (déjà garanti par la
  machine à états du domaine). Le ticket annulé reste **visible** dans la file
  du jour (« Annulée » + motif) — jamais retiré de la liste.
- `PUT /salons/{salon_id}/queue/tickets/{ticket_id}/services` — **édition des
  prestations** (coiffeuse / gérant, permission `QUEUE_TICKET_UPDATE_STATUS`,
  #161) : remplace intégralement les prestations d'un ticket `waiting`/
  `in_progress` (erreur de saisie à la borne, ajout en cours d'attente).
- `GET /salons/{salon_id}/queue/tickets/{ticket_id}/customer` — **nom complet
  de la cliente** d'un ticket `in_progress` **pris en charge par le coiffeur
  appelant lui-même** (zone coiffeur « Mes tickets », permission dédiée
  `QUEUE_TICKET_UPDATE_STATUS`) : exposition étroite, jamais le téléphone ni
  les notes, jamais la cliente d'un collègue ni d'un ticket encore en attente
  (celle-ci reste au prénom seul, #156/§11.3).

Sécurité (RBAC #12, ADR-0015/0041 ; anti-oracle ADR-0026) : chaque route déclare
`require_salon_scope` **et** la permission dédiée ; un `salon_id` hors périmètre
device/gérant → `403` générique (jamais un `404` qui confirmerait le salon).
**Aucun** chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : « réservé au rôle TERMINAL »
signifie *atteignable par un device provisionné*, jamais *public* (deny-by-default
inchangé). Le ticket est **indépendant d'`Appointment`** (ADR-0042) : aucune ligne
`appointments` n'est jamais écrite.

Traductions d'erreurs de domaine → HTTP : `InvalidQueueTicketServices` /
`InvalidQueueTicketCancellationReason` → **422** ; `QueueTicketNotFound` /
`HairdresserNotInSalon` (après portée) → **404** ; `InvalidQueueTicketTransition`
/ `QueueTicketHairdresserRequired` → **409**.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    CancelQueueTicket,
    CompleteQueueTicket,
    GetAssignedTicketCustomer,
    JoinQueue,
    JoinQueueCommand,
    ListSalonQueueTickets,
    StartQueueTicket,
    UpdateQueueTicketServices,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import (
    HairdresserAlreadyBusy,
    HairdresserNotInSalon,
    InvalidQueueTicketCancellationReason,
    InvalidQueueTicketServices,
    InvalidQueueTicketTransition,
    QueueTicketHairdresserRequired,
    QueueTicketNotFound,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.queue_ticket import (
    CANCELLATION_REASON_MAX_LENGTH,
    QueueTicket,
    QueueTicketEntry,
)
from coiflink_api.domain.time_window import SALON_TIMEZONE

router = APIRouter(prefix="/salons", tags=["queue-tickets"])

# Borne de robustesse du nombre de prestations d'un ticket (budget §12.1) — un
# ticket walk-in porte quelques prestations, jamais un corps non borné.
_MAX_SERVICES_PER_TICKET = 20


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `terminal_customers.py`).
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
    service_ids: list[uuid.UUID] = Field(min_length=1, max_length=_MAX_SERVICES_PER_TICKET)


class StartQueueTicketRequest(BaseModel):
    """Corps de `POST .../start` — prise en charge : la coiffeuse est **requise**.

    `hairdresser_id` doit être un membre `ACTIVE` du salon (validé serveur) : un
    ticket « en cours » sans coiffeuse n'a pas de sens métier.
    """

    model_config = ConfigDict(extra="ignore")

    hairdresser_id: uuid.UUID


class CancelQueueTicketRequest(BaseModel):
    """Corps de `POST .../cancel` — annulation manuelle : le motif est **requis**.

    `reason` est **obligatoire** (`min_length=1`, client absent/no-show) et borné
    (`CANCELLATION_REASON_MAX_LENGTH`) côté Pydantic — **revalidé également côté
    domaine** (`validate_cancellation_reason`, défense en profondeur, miroir
    `UpdateQueueTicketServicesRequest`) : un motif blanc (espaces uniquement)
    passe la validation Pydantic mais est rejeté par le domaine (`422`).
    """

    model_config = ConfigDict(extra="ignore")

    reason: str = Field(min_length=1, max_length=CANCELLATION_REASON_MAX_LENGTH)


class UpdateQueueTicketServicesRequest(BaseModel):
    """Corps de `PUT .../services` — édition des prestations d'un ticket émis.

    `service_ids` remplace **intégralement** la liste courante (au moins une
    prestation active du salon, miroir `JoinQueueRequest`) — pas de fusion, pas
    de suppression partielle.
    """

    model_config = ConfigDict(extra="ignore")

    service_ids: list[uuid.UUID] = Field(min_length=1, max_length=_MAX_SERVICES_PER_TICKET)


class QueueTicketResponse(BaseModel):
    """Réponse `201` de l'émission d'un ticket (la borne imprime immédiatement).

    `ticket_number` est un **entier brut** (le zéro-padding « N° 014 » relève du
    formatter thermique #160). `estimated_wait_minutes` est **figé à l'émission**.
    `people_ahead_count` est **toujours un entier réel** sur la réponse de création
    de ticket (`join_queue`) ; `None`/inutilisé sur la réponse d'édition des
    prestations (`update_queue_ticket_services` ne recalcule pas cette valeur).
    """

    id: uuid.UUID
    ticket_number: int
    issued_date: datetime.date
    status: str
    estimated_wait_minutes: int
    people_ahead_count: int | None = None
    created_at: datetime.datetime
    service_ids: list[uuid.UUID]


class QueueTicketActionResponse(BaseModel):
    """Réponse `200` d'une prise en charge / clôture / annulation (start/complete/cancel).

    `cancellation_reason` est `null` pour `start`/`complete` (aucun des deux ne le
    pose) ; c'est **toujours** le motif stocké pour `cancel` (troisième
    consommateur de cette réponse partagée).
    """

    id: uuid.UUID
    ticket_number: int
    status: str
    hairdresser_id: uuid.UUID | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    cancellation_reason: str | None = None


class WalkInTicketResponse(BaseModel):
    """Une ligne **ticket walk-in** de la file gérant (US-8.3, #157) — noms résolus + ids opaques.

    Aligné sur la projection minimale de #156 pour l'**affichage** : seul le
    **prénom** (`customer_first_name`, dérivé de `customer_profiles.full_name`) est
    résolu en clair — jamais le nom complet ni le téléphone **dans cette ligne**.
    `customer_profile_id`/`service_ids` (UUID **opaques**, non-PII) sont portés en
    plus, pour permettre au gérant d'ouvrir le **détail** du ticket (fiche complète
    via `GET /customers/{customer_profile_id}`, prix/durée des prestations depuis le
    catalogue) — l'exposition reste bornée à cette route gérant/coiffeur
    authentifiée (`QUEUE_TICKET_READ_SALON`), jamais à un écran public. `ticket_id`/
    `hairdresser_id` restent aussi des UUID opaques, utiles au gérant pour agir.
    Indépendant d'`Appointment` (ADR-0042) : aucun `appointment_id`/créneau.
    `payment_id` est l'id du paiement `VALIDATED`/`ADJUSTED` rattaché au ticket
    (même notion « payé » que `PAID_PAYMENT_STATUSES`), ou `null` si non encaissé.
    `cancellation_reason` est le motif d'annulation manuelle (`status = "expired"`
    issu d'un `cancel`), `null` sinon — permet à la file gérant d'afficher
    « Annulée » + le motif sans que le ticket disparaisse de la liste.
    """

    ticket_id: uuid.UUID
    ticket_number: int
    customer_profile_id: uuid.UUID | None
    customer_first_name: str | None
    service_ids: list[uuid.UUID]
    service_names: list[str]
    hairdresser_id: uuid.UUID | None
    hairdresser_name: str | None
    status: str
    estimated_wait_minutes: int
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    payment_id: uuid.UUID | None
    cancellation_reason: str | None


class QueueTicketListResponse(BaseModel):
    """Réponse de `GET /salons/{salon_id}/queue/tickets` (US-8.3, #157, pivot #148).

    `day` échoie le jour civil résolu (paramètre `day` ou aujourd'hui par défaut,
    `Africa/Abidjan`). `items` = tickets **actifs** du jour (`waiting`/`called`/
    `in_progress`/`done`/`expired`), triés `ticket_number` croissant. Liste
    **vide** si aucun ticket actif (état légitime, ≠ erreur).
    """

    day: datetime.date
    items: list[WalkInTicketResponse]


class AssignedTicketCustomerResponse(BaseModel):
    """Réponse de `GET .../queue/tickets/{ticket_id}/customer` (zone coiffeur).

    Exposition **minimale et à part** de `WalkInTicketResponse`/`GET
    /customers/{id}` : seul `full_name`, jamais le téléphone ni les notes —
    réservée au coiffeur qui a **lui-même** pris en charge ce ticket
    `in_progress` (voir `GetAssignedTicketCustomer`).
    """

    full_name: str


def _walk_in_ticket_response(entry: QueueTicketEntry) -> WalkInTicketResponse:
    return WalkInTicketResponse(
        ticket_id=entry.ticket_id,
        ticket_number=entry.ticket_number,
        customer_profile_id=entry.customer_profile_id,
        customer_first_name=entry.customer_first_name,
        service_ids=list(entry.service_ids),
        service_names=list(entry.service_names),
        hairdresser_id=entry.hairdresser_id,
        hairdresser_name=entry.hairdresser_name,
        status=entry.status,
        estimated_wait_minutes=entry.estimated_wait_minutes,
        created_at=entry.created_at,
        started_at=entry.started_at,
        completed_at=entry.completed_at,
        payment_id=entry.payment_id,
        cancellation_reason=entry.cancellation_reason,
    )


def _today() -> datetime.date:
    """Jour civil courant dans le fuseau du salon (Africa/Abidjan, convention #21)."""

    return datetime.datetime.now(SALON_TIMEZONE).date()


def _ticket_response(
    ticket: QueueTicket, *, people_ahead_count: int | None = None
) -> QueueTicketResponse:
    return QueueTicketResponse(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        issued_date=ticket.issued_date,
        status=ticket.status,
        estimated_wait_minutes=ticket.estimated_wait_minutes,
        people_ahead_count=people_ahead_count,
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
        cancellation_reason=ticket.cancellation_reason,
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


def get_list_salon_queue_tickets(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
) -> ListSalonQueueTickets:
    """Assemble le cas d'usage de **lecture** de la file (dépôt seul, pas d'audit)."""

    return ListSalonQueueTickets(tickets)


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


def get_cancel_queue_ticket(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> CancelQueueTicket:
    """Assemble le cas d'usage d'**annulation manuelle** (dépôt + audit)."""

    return CancelQueueTicket(tickets, audit_log)


def get_update_queue_ticket_services(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
    catalog: Annotated[SalonCatalogRepository, Depends(get_catalog_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> UpdateQueueTicketServices:
    """Assemble le cas d'usage d'**édition des prestations** (dépôt + catalogue + audit)."""

    return UpdateQueueTicketServices(tickets, catalog, audit_log)


def get_assigned_ticket_customer(
    tickets: Annotated[QueueTicketRepository, Depends(get_queue_ticket_repository)],
    customers: Annotated[CustomerRepository, Depends(get_customer_repository)],
) -> GetAssignedTicketCustomer:
    """Assemble le cas d'usage de **résolution du nom de la cliente prise en charge**."""

    return GetAssignedTicketCustomer(tickets, customers)


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    "/{salon_id}/queue/tickets",
    response_model=QueueTicketListResponse,
    summary="Lister la file d'attente walk-in du salon pour un jour donné (gérant/coiffeuse, #148/#157)",
    responses={
        200: {"description": ("Tickets actifs du jour (waiting/called/in_progress/done/expired)")},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def list_salon_queue_tickets(
    salon_id: uuid.UUID,
    usecase: Annotated[ListSalonQueueTickets, Depends(get_list_salon_queue_tickets)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_READ_SALON))
    ],
    day: Annotated[
        datetime.date | None,
        Query(description="Jour ciblé (AAAA-MM-JJ) ; défaut aujourd'hui"),
    ] = None,
) -> QueueTicketListResponse:
    """File du salon pour `day` (défaut aujourd'hui) : tickets walk-in actifs.

    Route combinée « file d'attente » **simplifiée** au pivot walk-in exclusif
    (#148) : ne renvoie plus que les tickets (`waiting`/`called`/`in_progress`/
    `done`/`expired`), noms résolus, triés `ticket_number` — un ticket `expired`
    (annulation manuelle) reste visible pour le reste de la journée, motif
    inclus. L'ancien bras `appointments` a disparu avec le module RDV. Lecture
    pure, aucun audit
    (cohérent avec le Dashboard #148).
    """

    target_day = day if day is not None else _today()
    entries = usecase.execute(salon_id, target_day)
    return QueueTicketListResponse(
        day=target_day,
        items=[_walk_in_ticket_response(entry) for entry in entries],
    )


@router.post(
    "/{salon_id}/queue/tickets",
    response_model=QueueTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Borne — rejoindre la file walk-in (numéro de passage + estimation d'attente)",
    responses={
        201: {
            "description": (
                "Ticket créé (waiting) — numéro, estimation, nombre de personnes "
                "devant (people_ahead_count), heure d'émission"
            )
        },
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
    # Gardes RBAC (#12) : portée salon §11.2 **et** permission TERMINAL dédiée (#155).
    # `salon_id` est lu du chemin par `require_salon_scope` ; les deux dépendances
    # résolvent le même `Principal` (pas de double lecture de compte).
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[Principal, Depends(require_permission(Permission.QUEUE_TICKET_CREATE))],
) -> QueueTicketResponse:
    """Délivre un ticket `waiting` pour le salon de la portée (borne `TERMINAL`).

    Le `salon_id` vient du chemin (portée), jamais du corps. Prestation(s)
    invalide(s) → `422` ; `customer_profile_id` d'un autre salon → `404` neutre
    (indiscernable, §11.2). Aucune écriture dans `appointments` (ADR-0042), aucun
    audit (émettre un ticket n'est pas une action de gestion §11.4). La réponse
    porte aussi `people_ahead_count` (nombre de tickets `waiting` encore devant
    celui-ci, recompté juste après l'émission).
    """

    try:
        result = usecase.execute(
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _ticket_response(result.ticket, people_ahead_count=result.people_ahead_count)


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
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_UPDATE_STATUS))
    ],
) -> QueueTicketActionResponse:
    """Assigne une coiffeuse `ACTIVE` du salon et passe le ticket `in_progress`.

    Un ticket hors salon/inexistant est un `404` indiscernable ; une coiffeuse hors
    salon également (`HairdresserNotInSalon` → `404`, aucun oracle). Une transition
    depuis un statut non-`waiting`, ou une coiffeuse déjà occupée sur un autre
    ticket `in_progress` (`HairdresserAlreadyBusy`, portée globale, #173) → `409`.
    Journalisé `QUEUE_TICKET_STARTED`.
    """

    try:
        ticket = usecase.execute(salon_id, ticket_id, payload.hairdresser_id, principal.id)
    except (
        InvalidQueueTicketTransition,
        QueueTicketHairdresserRequired,
        HairdresserAlreadyBusy,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (QueueTicketNotFound, HairdresserNotInSalon) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_UPDATE_STATUS))
    ],
) -> QueueTicketActionResponse:
    """Passe le ticket `in_progress → done`. Transition invalide → `409`. Journalisé."""

    try:
        ticket = usecase.execute(salon_id, ticket_id, principal.id)
    except InvalidQueueTicketTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except QueueTicketNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _action_response(ticket)


@router.post(
    "/{salon_id}/queue/tickets/{ticket_id}/cancel",
    response_model=QueueTicketActionResponse,
    summary="Annuler un ticket walk-in — client absent (coiffeuse / gérant, §11.4, motif obligatoire)",
    responses={
        200: {"description": "Ticket annulé (expired), motif enregistré"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Ticket hors salon ou inexistant (après portée)"},
        409: {"description": "Transition invalide (ticket déjà pris en charge / terminé)"},
        422: {"description": "Motif d'annulation absent, blanc ou hors bornes"},
    },
)
def cancel_queue_ticket(
    salon_id: uuid.UUID,
    ticket_id: uuid.UUID,
    payload: CancelQueueTicketRequest,
    usecase: Annotated[CancelQueueTicket, Depends(get_cancel_queue_ticket)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_UPDATE_STATUS))
    ],
) -> QueueTicketActionResponse:
    """Passe le ticket `waiting`/`called → expired` — client absent, motif obligatoire.

    Un ticket déjà `in_progress` (pris en charge) — ou `done`/`expired` — n'est
    **plus jamais** annulable ainsi → `409` (règle métier centrale, déjà garantie
    par la machine à états du domaine). Motif absent, blanc ou hors bornes →
    `422`. Journalisé `QUEUE_TICKET_CANCELLED` (`metadata={}` — le motif, libre
    et potentiellement identifiant, n'entre jamais au journal §11.3/§11.4). Le
    ticket annulé reste visible dans `GET .../queue/tickets` du jour.
    """

    try:
        ticket = usecase.execute(salon_id, ticket_id, payload.reason, principal.id)
    except InvalidQueueTicketCancellationReason as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except InvalidQueueTicketTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except QueueTicketNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _action_response(ticket)


@router.put(
    "/{salon_id}/queue/tickets/{ticket_id}/services",
    response_model=QueueTicketResponse,
    summary="Modifier les prestations d'un ticket walk-in émis (coiffeuse / gérant, §11.4, #161)",
    responses={
        200: {"description": "Prestations remplacées"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Ticket hors salon ou inexistant (après portée)"},
        409: {"description": "Ticket dans un état qui ne peut plus être modifié"},
        422: {"description": "Prestation(s) invalide(s) — vide, inactive ou hors salon"},
    },
)
def update_queue_ticket_services(
    salon_id: uuid.UUID,
    ticket_id: uuid.UUID,
    payload: UpdateQueueTicketServicesRequest,
    usecase: Annotated[UpdateQueueTicketServices, Depends(get_update_queue_ticket_services)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_UPDATE_STATUS))
    ],
) -> QueueTicketResponse:
    """Remplace les prestations d'un ticket `waiting`/`in_progress` (erreur de saisie, ajout).

    `service_ids` remplace **intégralement** la liste courante — jamais une fusion.
    Un ticket hors salon/inexistant est un `404` indiscernable ; une prestation
    inactive/hors salon ou une liste vide → `422` ; un ticket `called`/`done`/
    `expired` (plus éditable) → `409`. Journalisé `QUEUE_TICKET_SERVICES_UPDATED`.
    """

    try:
        ticket = usecase.execute(salon_id, ticket_id, tuple(payload.service_ids), principal.id)
    except InvalidQueueTicketServices as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except InvalidQueueTicketTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except QueueTicketNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _ticket_response(ticket)


@router.get(
    "/{salon_id}/queue/tickets/{ticket_id}/customer",
    response_model=AssignedTicketCustomerResponse,
    summary="Nom complet de la cliente d'un ticket pris en charge par le coiffeur appelant",
    responses={
        200: {"description": "Nom complet de la cliente"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {
            "description": (
                "Ticket introuvable, hors salon, pas assigné à ce coiffeur, pas "
                "encore pris en charge, ou ticket anonyme (indiscernable)"
            )
        },
    },
)
def get_ticket_customer(
    salon_id: uuid.UUID,
    ticket_id: uuid.UUID,
    usecase: Annotated[GetAssignedTicketCustomer, Depends(get_assigned_ticket_customer)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.QUEUE_TICKET_UPDATE_STATUS))
    ],
) -> AssignedTicketCustomerResponse:
    """Nom complet de la cliente d'un ticket `in_progress` pris en charge par
    le `principal` appelant (zone coiffeur « Mes tickets »).

    Exposition étroite (voir `GetAssignedTicketCustomer`) : un gérant appelant
    cette route obtient toujours `404` (son id ne correspond jamais au
    `hairdresser_id` d'un ticket) — il dispose de sa propre voie d'accès
    (`GET /customers/{id}`, `CUSTOMER_MANAGE`).
    """

    try:
        full_name = usecase.execute(salon_id, ticket_id, principal.id)
    except QueueTicketNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AssignedTicketCustomerResponse(full_name=full_name)


__all__ = [
    "router",
    "JoinQueueRequest",
    "StartQueueTicketRequest",
    "CancelQueueTicketRequest",
    "UpdateQueueTicketServicesRequest",
    "QueueTicketResponse",
    "QueueTicketActionResponse",
    "WalkInTicketResponse",
    "QueueTicketListResponse",
    "AssignedTicketCustomerResponse",
    "get_queue_ticket_repository",
    "get_catalog_repository",
    "get_audit_log",
]
