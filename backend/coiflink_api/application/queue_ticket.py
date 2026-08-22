"""Cas d'usage : **file d'attente walk-in** — ticket de passage & prise en charge (US-8.3, #157).

Tranche applicative hexagonale (ADR-0008) : ces cas d'usage ne dépendent que de
**ports** (`QueueTicketRepository`, `SalonCatalogRepository`, `CustomerRepository`,
`SalonScopeRepository`, `AuditLog`) — aucune dépendance FastAPI/SQLAlchemy. Le
ticket de passage est **indépendant** d'`Appointment` (ADR-0042) : aucune ligne
`appointments` n'est créée, mise à jour ni référencée.

- `JoinQueue` — « rejoindre la file » (borne `TERMINAL`) : valide les prestations
  (actives, du salon), la fiche client optionnelle (appartenance salon), **calcule
  une fois** l'estimation d'attente (formule V1, `estimate_wait_minutes`) à partir
  de l'état de la file **avant** insertion, puis alloue un `ticket_number`
  séquentiel (verrou salon+jour, §dépôt). Retourne un `JoinQueueResult` : le ticket
  créé **et** `people_ahead_count` (nombre de tickets `waiting` encore devant lui,
  recompté **après** insertion via `count_waiting_ahead` — non persisté, simple
  instantané). **Aucun audit** : émettre un ticket n'est pas une action humaine de
  gestion et le ticket ne porte aucune PII propre.
- `StartQueueTicket` — prise en charge (coiffeuse / gérant) : assigne une coiffeuse
  **membre `ACTIVE`** du salon, **pas déjà occupée** sur un autre ticket `in_progress`
  (#173, portée globale) et passe le ticket `in_progress` en un seul geste (un
  walk-in n'a jamais de coiffeuse pré-assignée), pose `started_at`, journalise
  `QUEUE_TICKET_STARTED` (`metadata={}`). Préconditions vérifiées **ici**, puis
  **ré-affirmées à l'écriture** par le dépôt (`UPDATE ... WHERE status = 'waiting'`
  + index unique partiel global anti-double-affectation, garde TOCTOU, miroir
  `StartAppointmentService`).
- `CompleteQueueTicket` — clôture (coiffeuse / gérant) : passe `in_progress → done`,
  pose `completed_at`, journalise `QUEUE_TICKET_COMPLETED`.
- `CancelQueueTicket` — annulation manuelle (coiffeuse / gérant, no-show client) :
  passe `waiting`/`called → expired` avec un **motif obligatoire** (revalidé côté
  domaine), journalise `QUEUE_TICKET_CANCELLED`. Un ticket `in_progress` n'est
  **plus jamais** annulable ainsi — déjà garanti par la machine à états
  (`ALLOWED_QUEUE_TICKET_TRANSITIONS` n'autorise pas `in_progress → expired`),
  ré-affirmé ici par une double garde (pré-contrôle applicatif + TOCTOU dépôt).
- `UpdateQueueTicketServices` — modifie les prestations d'un ticket `waiting`/
  `in_progress` (coiffeuse / gérant, #161) : revalide les prestations (actives,
  du salon) puis remplace la jonction, journalise `QUEUE_TICKET_SERVICES_UPDATED`.
  Un ticket `called`/`done`/`expired` n'est plus éditable.
- `ListSalonQueueTickets` — lecture pure des tickets actifs du jour (file gérant #157
  et écran borne #159), triés `ticket_number`. Aucune écriture, aucun audit.
- `GetAssignedTicketCustomer` — nom complet de la cliente d'un ticket `in_progress`
  pris en charge par le coiffeur appelant (zone coiffeur « Mes tickets »).
  Exposition étroite : jamais le téléphone ni les notes, jamais la cliente d'un
  collègue, jamais tant que le ticket n'est pas pris en charge. Aucune écriture,
  aucun audit (une simple lecture n'est pas une action de gestion).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.application.ports.queue_ticket_repository import (
    QueueTicketRepository,
)
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
)
from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.domain.audit import (
    ENTITY_TYPE_QUEUE_TICKET,
    AuditAction,
    AuditEntry,
)
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    HairdresserAlreadyBusy,
    HairdresserNotInSalon,
    InvalidQueueTicketServices,
    InvalidQueueTicketTransition,
    QueueTicketNotFound,
)
from coiflink_api.domain.queue_ticket import (
    QUEUE_TICKET_PENDING_STATUSES,
    QueueTicket,
    QueueTicketEntry,
    QueueTicketToCreate,
    estimate_wait_minutes,
    validate_cancellation_reason,
    validate_service_ids,
)
from coiflink_api.domain.time_window import SALON_TIMEZONE


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware), miroir `application/queue.py`."""

    return datetime.datetime.now(datetime.timezone.utc)


def _issued_date(now: datetime.datetime) -> datetime.date:
    """Jour civil du salon (Africa/Abidjan) pour un instant donné (scope du compteur)."""

    return now.astimezone(SALON_TIMEZONE).date()


@dataclass(frozen=True)
class JoinQueueCommand:
    """Commande « rejoindre la file » — déjà bornée par l'adapter entrant.

    `customer_profile_id = None` = ticket **anonyme** (le client refuse de laisser
    son identité) ; `service_ids` porte les prestations demandées (≥ 1, validées ici).
    """

    customer_profile_id: uuid.UUID | None
    service_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class JoinQueueResult:
    """Résultat de `JoinQueue.execute` : le ticket créé + sa position dans la file.

    `people_ahead_count` n'est **pas persisté** (aucune colonne nouvelle) : comme
    `estimated_wait_minutes`, c'est un instantané — mais calculé par un appel
    **frais** à `count_waiting_ahead` juste après l'insertion (avec le
    `ticket_number` que le dépôt vient d'allouer), ce qui reste fiable grâce à
    l'invariant de numérotation strictement croissante (ADR-0040) : contrairement à
    `estimated_wait_minutes` (formule figée à l'émission, jamais recalculée),
    `people_ahead_count` reflète l'état réel de la file au moment de l'émission.
    """

    ticket: QueueTicket
    people_ahead_count: int


class JoinQueue:
    """Délivre un ticket de passage walk-in (borne `TERMINAL`, US-8.3, #157)."""

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        catalog_repository: SalonCatalogRepository,
        customer_repository: CustomerRepository,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._catalog = catalog_repository
        self._customers = customer_repository
        self._clock = clock if clock is not None else _utc_now

    def execute(self, salon_id: uuid.UUID, command: JoinQueueCommand) -> JoinQueueResult:
        service_ids = validate_service_ids(command.service_ids)
        own_durations = self._resolve_durations(salon_id, service_ids)

        if command.customer_profile_id is not None:
            # Fiche hors salon / inexistante : indiscernable (§11.2), jamais un oracle.
            customer = self._customers.find_by_id(salon_id, command.customer_profile_id)
            if customer is None:
                raise QueueTicketNotFound("Fiche client introuvable pour ce salon.")

        now = self._clock()
        issued_date = _issued_date(now)
        estimated = self._estimate(salon_id, issued_date, own_durations)

        ticket = self._tickets.create(
            QueueTicketToCreate(
                salon_id=salon_id,
                customer_profile_id=command.customer_profile_id,
                service_ids=service_ids,
                estimated_wait_minutes=estimated,
            ),
            issued_date=issued_date,
        )
        people_ahead = self._tickets.count_waiting_ahead(
            salon_id, ticket.ticket_number, issued_date=issued_date
        )
        return JoinQueueResult(ticket=ticket, people_ahead_count=people_ahead)

    def _resolve_durations(
        self, salon_id: uuid.UUID, service_ids: tuple[uuid.UUID, ...]
    ) -> tuple[int, ...]:
        """Résout les durées des prestations **actives du salon** (ordre `service_ids`).

        Lève `InvalidQueueTicketServices` sur une prestation inactive/hors salon
        (miroir `_resolve_booked_services` du RDV, mais un seul type d'erreur côté
        ticket). Les durées servent au repli d'ETA « moyenne des prestations de ce
        ticket » quand la file est encore vide.
        """

        active = {s.id: s for s in self._catalog.list_active_services(salon_id)}
        durations: list[int] = []
        for service_id in service_ids:
            service = active.get(service_id)
            if service is None:
                raise InvalidQueueTicketServices(
                    "Prestation introuvable ou inactive pour ce salon."
                )
            durations.append(service.duration_minutes)
        return tuple(durations)

    def _estimate(
        self,
        salon_id: uuid.UUID,
        issued_date: datetime.date,
        own_durations: tuple[int, ...],
    ) -> int:
        """Estimation V1, calculée **avant** insertion (état de la file courant).

        `position` = tickets `waiting` déjà présents ; `average_service_minutes` =
        moyenne des durées des tickets actifs, ou — si la file est vide — repli sur
        la moyenne des prestations **de ce ticket**. Filet « aucune coiffeuse
        active » assuré par `estimate_wait_minutes`.
        """

        position = self._tickets.count_waiting(salon_id, issued_date=issued_date)
        average = self._tickets.average_requested_duration_minutes(
            salon_id, issued_date=issued_date
        )
        if average is None:
            average = sum(own_durations) / len(own_durations) if own_durations else 0.0
        active_count = len(self._catalog.list_active_hairdressers(salon_id))
        return estimate_wait_minutes(
            position=position,
            average_service_minutes=average,
            active_hairdresser_count=active_count,
        )


class StartQueueTicket:
    """Prise en charge d'un ticket `waiting` par une coiffeuse du salon (US-8.3, #157).

    Combine en un seul geste métier ce qui serait, côté RDV, deux étapes
    (assignation + démarrage) : un ticket walk-in n'a jamais de coiffeuse
    pré-assignée. Exige `hairdresser_id` **membre `ACTIVE`** du salon (miroir
    `HairdresserNotInSalon`).
    """

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        scope_repository: SalonScopeRepository,
        audit_log: AuditLog,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._scope = scope_repository
        self._audit_log = audit_log
        self._clock = clock if clock is not None else _utc_now

    def execute(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        hairdresser_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> QueueTicket:
        current = self._tickets.get(salon_id, ticket_id)
        if current is None:
            # Ticket inexistant **ou** hors salon : indiscernables (§11.2).
            raise QueueTicketNotFound("Ticket de passage introuvable.")
        if current.status != "waiting":
            raise InvalidQueueTicketTransition(
                "Ce ticket ne peut pas être pris en charge dans cet état."
            )
        _require_salon_hairdresser(self._scope, salon_id, hairdresser_id)
        if self._tickets.is_hairdresser_busy(hairdresser_id):
            # Pré-contrôle (#173) — portée globale, l'index unique partiel reste
            # l'arbitre final contre la course concurrente (voir `start()`).
            raise HairdresserAlreadyBusy("Cette coiffeuse est déjà occupée sur un autre ticket.")

        updated = self._tickets.start(salon_id, ticket_id, hairdresser_id, now=self._clock())
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.QUEUE_TICKET_STARTED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_QUEUE_TICKET,
                entity_id=ticket_id,
                metadata={},
            )
        )
        return updated


class CompleteQueueTicket:
    """Clôture d'un ticket `in_progress` (prestation servie) — US-8.3, #157."""

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        audit_log: AuditLog,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._audit_log = audit_log
        self._clock = clock if clock is not None else _utc_now

    def execute(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID, actor_id: uuid.UUID
    ) -> QueueTicket:
        current = self._tickets.get(salon_id, ticket_id)
        if current is None:
            raise QueueTicketNotFound("Ticket de passage introuvable.")
        if current.status != "in_progress":
            raise InvalidQueueTicketTransition("Ce ticket ne peut pas être clôturé dans cet état.")

        updated = self._tickets.complete(salon_id, ticket_id, now=self._clock())
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.QUEUE_TICKET_COMPLETED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_QUEUE_TICKET,
                entity_id=ticket_id,
                metadata={},
            )
        )
        return updated


class CancelQueueTicket:
    """Annule un ticket `waiting`/`called` — client absent (no-show), motif obligatoire.

    Une fois `in_progress`, un ticket n'est **plus jamais** annulable par ce
    geste (règle métier centrale de cette fonctionnalité) : la machine à états
    `ALLOWED_QUEUE_TICKET_TRANSITIONS` ne porte **aucune** entrée
    `in_progress → expired`, ce qui la rend déjà structurellement impossible ;
    le pré-contrôle ci-dessous (avant tout appel dépôt) et la garde TOCTOU du
    dépôt (`UPDATE ... WHERE status IN ('waiting', 'called')`) la ré-affirment
    à deux niveaux supplémentaires — y compris contre une course concurrente
    (prise en charge en cours pendant la tentative d'annulation). Le motif
    (`reason`) est **validé en premier**, avant toute lecture dépôt (miroir
    `UpdateQueueTicketServices` : validation pure d'abord).
    """

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        audit_log: AuditLog,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._audit_log = audit_log
        self._clock = clock if clock is not None else _utc_now

    def execute(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        reason: str,
        actor_id: uuid.UUID,
    ) -> QueueTicket:
        validated_reason = validate_cancellation_reason(reason)
        current = self._tickets.get(salon_id, ticket_id)
        if current is None:
            raise QueueTicketNotFound("Ticket de passage introuvable.")
        if current.status not in ("waiting", "called"):
            raise InvalidQueueTicketTransition("Ce ticket ne peut pas être annulé dans cet état.")

        updated = self._tickets.cancel(salon_id, ticket_id, validated_reason, now=self._clock())
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.QUEUE_TICKET_CANCELLED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_QUEUE_TICKET,
                entity_id=ticket_id,
                metadata={},
            )
        )
        return updated


class UpdateQueueTicketServices:
    """Modifie les prestations d'un ticket `waiting`/`in_progress` (US-8.3, #161).

    Aucun moyen n'existait jusqu'ici de corriger les prestations d'un ticket déjà
    émis (erreur de saisie à la borne, ajout demandé en cours d'attente). Revalide
    les prestations contre le catalogue **actif du salon** (même garde que
    `JoinQueue._resolve_durations`) puis remplace la jonction. Un ticket `called`/
    `done`/`expired` n'est plus éditable (`QUEUE_TICKET_PENDING_STATUSES`).
    """

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        catalog_repository: SalonCatalogRepository,
        audit_log: AuditLog,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._catalog = catalog_repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        service_ids: tuple[uuid.UUID, ...],
        actor_id: uuid.UUID,
    ) -> QueueTicket:
        service_ids = validate_service_ids(service_ids)
        current = self._tickets.get(salon_id, ticket_id)
        if current is None:
            raise QueueTicketNotFound("Ticket de passage introuvable.")
        if current.status not in QUEUE_TICKET_PENDING_STATUSES:
            raise InvalidQueueTicketTransition("Ce ticket ne peut plus être modifié dans cet état.")

        active = {s.id for s in self._catalog.list_active_services(salon_id)}
        for service_id in service_ids:
            if service_id not in active:
                raise InvalidQueueTicketServices(
                    "Prestation introuvable ou inactive pour ce salon."
                )

        updated = self._tickets.update_services(salon_id, ticket_id, service_ids)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.QUEUE_TICKET_SERVICES_UPDATED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_QUEUE_TICKET,
                entity_id=ticket_id,
                metadata={},
            )
        )
        return updated


class ListSalonQueueTickets:
    """Liste les tickets **actifs** du salon pour un jour donné (lecture pure, #157).

    Tickets `waiting`/`called`/`in_progress`/`done`/`expired` du jour, noms
    résolus, triés `ticket_number` — `expired` (annulation manuelle, motif
    obligatoire) reste visible pour le reste de la journée, à l'image de `done`.
    Aucune écriture, aucun audit — consommé par la file gérant (fusion en
    lecture, §C) et l'écran borne (#159).
    """

    def __init__(self, queue_ticket_repository: QueueTicketRepository) -> None:
        self._tickets = queue_ticket_repository

    def execute(
        self, salon_id: uuid.UUID, issued_date: datetime.date
    ) -> tuple[QueueTicketEntry, ...]:
        return self._tickets.list_active_for_salon(salon_id, issued_date=issued_date)


class GetAssignedTicketCustomer:
    """Nom complet de la cliente d'un ticket `in_progress` pris en charge par le
    coiffeur appelant (zone coiffeur « Mes tickets », US-8.3).

    Exposition **volontairement étroite** — bien plus restreinte que la fiche
    complète du gérant (`GET /customers/{id}`, `CUSTOMER_MANAGE`) : ne révèle
    **jamais** le téléphone ni les notes, seulement le nom complet, et
    **uniquement** si (a) le ticket appartient au salon, (b) `hairdresser_id` du
    ticket est exactement le coiffeur appelant (jamais celui d'un collègue — pas
    d'oracle sur les clientes des autres coiffeuses), (c) le ticket est
    `in_progress` (la file d'attente reste au prénom seul tant que non prise en
    charge, #156/§11.3). Toute condition non remplie (ticket introuvable, hors
    salon, pas le sien, pas encore pris en charge, ticket anonyme, fiche
    introuvable) lève **un seul et même** `QueueTicketNotFound` — indiscernable,
    aucun oracle.
    """

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        customer_repository: CustomerRepository,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._customers = customer_repository

    def execute(self, salon_id: uuid.UUID, ticket_id: uuid.UUID, hairdresser_id: uuid.UUID) -> str:
        ticket = self._tickets.get(salon_id, ticket_id)
        if (
            ticket is None
            or ticket.hairdresser_id != hairdresser_id
            or ticket.status != "in_progress"
            or ticket.customer_profile_id is None
        ):
            raise QueueTicketNotFound("Ticket introuvable ou fiche client non accessible.")

        customer = self._customers.find_by_id(salon_id, ticket.customer_profile_id)
        if customer is None:
            raise QueueTicketNotFound("Ticket introuvable ou fiche client non accessible.")
        return customer.full_name


def _require_salon_hairdresser(
    scope_repository: SalonScopeRepository,
    salon_id: uuid.UUID,
    hairdresser_id: uuid.UUID,
) -> None:
    """Refuse un `hairdresser_id` qui n'est pas membre `ACTIVE` du salon (§11.2).

    Réutilise le **patron** `_require_salon_hairdresser` du RDV (#21) : la portée
    employé (`salon_members WHERE user_id = … AND status = 'ACTIVE'`) est l'autorité.
    Un membre `INACTIVE`, une coiffeuse d'un autre salon, un client ou un UUID
    inconnu donnent tous une portée sans `salon_id` — refus indiscernable
    (`HairdresserNotInSalon` → `404`, aucun oracle).
    """

    scope = scope_repository.salon_ids_for(hairdresser_id, Role.HAIRDRESSER.value)
    if salon_id not in scope:
        raise HairdresserNotInSalon("Coiffeur introuvable pour ce salon.")


__all__ = [
    "JoinQueueCommand",
    "JoinQueue",
    "JoinQueueResult",
    "StartQueueTicket",
    "CompleteQueueTicket",
    "CancelQueueTicket",
    "UpdateQueueTicketServices",
    "ListSalonQueueTickets",
    "GetAssignedTicketCustomer",
]
