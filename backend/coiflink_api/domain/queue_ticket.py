"""Ticket de passage walk-in & estimation d'attente (domaine pur, US-8.3, #157).

Domaine **pur** (aucune I/O, ni FastAPI ni SQLAlchemy — ADR-0008) du **ticket de
passage** délivré à un client sans rendez-vous à la borne kiosque (PRD §17, jalon
M7). Un `QueueTicket` est **indépendant** d'`Appointment` (ADR-0042) : il ne
détourne aucun créneau planifié, ne suppose aucun compte utilisateur
(`customer_profile_id` nullable) et porte son propre cycle de vie.

Trois responsabilités **pures** vivent ici :

- les entités de commande/lecture (`QueueTicketToCreate`, `QueueTicket`,
  `QueueTicketEntry`) — toutes rattachées à un salon (`salon_id`, isolation §11.2) ;
- la **machine à états** fermée `waiting → called → in_progress → done` (+ `expired`),
  miroir du style `ALLOWED_STATUS_TRANSITIONS` d'`AppointmentStatus` ;
- la **formule V1 d'estimation d'attente** (`estimate_wait_minutes`), heuristique
  assumée perfectible, bornée pour les cas dégénérés (aucune coiffeuse active,
  file vide, aucune donnée de durée).

`QueueTicketEntry` est l'objet-valeur de **lecture** de la file gérant (miroir de
`QueueEntry`/`QueueAppointmentRow` de `domain/queue.py`) : il n'émet que des noms
d'affichage et le **prénom** du client (projection minimale alignée sur #156,
§11.3) — jamais le nom complet, le téléphone ni un `customer_profile_id`.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Literal

from coiflink_api.domain.errors import (
    InvalidQueueTicketServices,
    InvalidQueueTicketTransition,
)

# Statuts fermés du ticket de passage (jamais dérivés d'une autre table, à la
# différence de `QueueStatus` #150). Ordre déclaré = ordre du cycle de vie.
QueueTicketStatus = Literal["waiting", "called", "in_progress", "done", "expired"]

QUEUE_TICKET_STATUSES: tuple[QueueTicketStatus, ...] = (
    "waiting",
    "called",
    "in_progress",
    "done",
    "expired",
)

# Statuts **actifs** repris dans la file gérant (§C) : le jour civil du salon,
# hors `expired` (jamais pris en charge / purgé). `done` reste visible pour la
# journée (prestation servie), à l'image d'un RDV `COMPLETED`.
QUEUE_TICKET_ACTIVE_STATUSES: tuple[QueueTicketStatus, ...] = (
    "waiting",
    "called",
    "in_progress",
    "done",
)

# Statuts pesant sur l'estimation d'attente (file **réellement à écouler**) :
# tickets non encore servis et en cours de service.
QUEUE_TICKET_PENDING_STATUSES: tuple[QueueTicketStatus, ...] = ("waiting", "in_progress")

# Machine à états **fermée** (miroir `ALLOWED_STATUS_TRANSITIONS`) : toute
# transition hors de cette table lève `InvalidQueueTicketTransition`.
#   waiting -> called -> in_progress -> done
#   waiting -> in_progress   (prise en charge directe : un walk-in n'a jamais de
#                             coiffeuse pré-assignée, l'appel est facultatif)
#   waiting/called -> expired  (jamais présenté / purge de fin de journée)
ALLOWED_QUEUE_TICKET_TRANSITIONS: dict[QueueTicketStatus, frozenset[QueueTicketStatus]] = {
    "waiting": frozenset({"called", "in_progress", "expired"}),
    "called": frozenset({"in_progress", "expired"}),
    "in_progress": frozenset({"done"}),
    "done": frozenset(),
    "expired": frozenset(),
}

# Repli documenté de l'ETA quand le salon n'a **aucune** coiffeuse active : on ne
# divise jamais par zéro (filet explicite, pas un `ZeroDivisionError` masqué).
DEFAULT_WAIT_MINUTES_NO_STAFF = 30


def can_transition(current: str, target: str) -> bool:
    """Vrai si `current → target` est autorisé par la machine à états (pure)."""

    allowed = ALLOWED_QUEUE_TICKET_TRANSITIONS.get(current)  # type: ignore[arg-type]
    return allowed is not None and target in allowed


def assert_transition(current: str, target: str) -> None:
    """Lève `InvalidQueueTicketTransition` si `current → target` est interdit (pure).

    Couvre aussi bien une cible incohérente qu'une transition depuis un statut
    terminal (`done`/`expired`) ou une réémission (`X → X`) — miroir de la garde
    de `SetAppointmentStatus`.
    """

    if not can_transition(current, target):
        raise InvalidQueueTicketTransition(
            "Cette transition de ticket n'est pas autorisée."
        )


def validate_service_ids(
    service_ids: tuple[uuid.UUID, ...],
) -> tuple[uuid.UUID, ...]:
    """Exige **au moins une** prestation (miroir `require_services` du RDV).

    Ne juge **pas** l'appartenance salon ni l'activité des prestations (résolues
    par le cas d'usage contre le catalogue) : seule la cardinalité « ≥ 1 » est une
    règle de domaine pure. Lève `InvalidQueueTicketServices` sur un tuple vide.
    """

    if not service_ids:
        raise InvalidQueueTicketServices(
            "Un ticket de passage doit comporter au moins une prestation."
        )
    return service_ids


def estimate_wait_minutes(
    *,
    position: int,
    average_service_minutes: float,
    active_hairdresser_count: int,
) -> int:
    """Estimation d'attente V1 (fonction pure), figée à l'émission du ticket.

    `position × durée moyenne des prestations des tickets actifs ÷ coiffeuses
    actives`, arrondie au plus proche (jamais tronquée — une troncature
    sous-estimerait). Filets pour les cas dégénérés :

    - `active_hairdresser_count <= 0` → constante `DEFAULT_WAIT_MINUTES_NO_STAFF`
      (aucune division par zéro) ;
    - `position <= 0` (aucun ticket devant) → `0` ;
    - `average_service_minutes <= 0` → `0` (aucune donnée de durée exploitable).

    Heuristique **assumée perfectible** (ADR-0042) : elle ignore la progression
    réelle des prestations en cours, ne distingue pas les coiffeuses par
    spécialité et ne s'appuie sur aucune donnée historique.
    """

    if active_hairdresser_count <= 0:
        return DEFAULT_WAIT_MINUTES_NO_STAFF
    if position <= 0 or average_service_minutes <= 0:
        return 0
    raw = (position * average_service_minutes) / active_hairdresser_count
    return max(0, round(raw))


@dataclass(frozen=True)
class QueueTicketToCreate:
    """Commande d'émission d'un ticket, assemblée par le cas d'usage (§D).

    `customer_profile_id = None` désigne un ticket **anonyme** (le client refuse
    de laisser son identité) : le domaine l'autorise ; conséquence documentée —
    aucun historique de visite n'est alimenté (§Sécurité). `service_ids` est déjà
    validé (≥ 1, actives et du salon) et `estimated_wait_minutes` déjà **calculé**
    (une seule fois, stocké tel quel — jamais recalculé en lecture).
    """

    salon_id: uuid.UUID
    customer_profile_id: uuid.UUID | None
    service_ids: tuple[uuid.UUID, ...]
    estimated_wait_minutes: int


@dataclass(frozen=True)
class QueueTicket:
    """Ticket de passage persisté, rattaché à un salon (ADR-0042, PRD §17).

    `ticket_number` est un entier **brut** séquentiel par salon **et** jour civil
    (le formatage « N° 014 » relève de l'impression thermique #160). `issued_date`
    est le jour civil du salon (`SALON_TIMEZONE`), scope du compteur.
    `hairdresser_id` référence un **compte** `users` (identifiant, appartenance
    salon vérifiée applicativement, miroir `Appointment.hairdresser_id`), posé
    uniquement à la prise en charge.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    ticket_number: int
    issued_date: datetime.date
    customer_profile_id: uuid.UUID | None
    service_ids: tuple[uuid.UUID, ...]
    status: QueueTicketStatus
    hairdresser_id: uuid.UUID | None
    estimated_wait_minutes: int
    created_at: datetime.datetime
    called_at: datetime.datetime | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None


@dataclass(frozen=True)
class QueueTicketEntry:
    """Ligne **finalisée** d'un ticket dans la file gérant (lecture, §C).

    Miroir de `QueueEntry` (#150) pour les tickets walk-in : n'émet que des noms
    d'affichage (`service_names`/`hairdresser_name` = `services.name`/
    `users.full_name`) et le **prénom** du client (`customer_first_name`,
    projection minimale alignée sur #156, §11.3) — jamais le nom complet, le
    téléphone ni le `customer_profile_id`. `hairdresser_id` (UUID **opaque**,
    non-PII) reste exposé : le gérant en a besoin pour agir sur la ligne.
    """

    ticket_id: uuid.UUID
    ticket_number: int
    customer_first_name: str | None
    service_names: tuple[str, ...]
    hairdresser_id: uuid.UUID | None
    hairdresser_name: str | None
    status: QueueTicketStatus
    estimated_wait_minutes: int
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None


__all__ = [
    "QueueTicketStatus",
    "QUEUE_TICKET_STATUSES",
    "QUEUE_TICKET_ACTIVE_STATUSES",
    "QUEUE_TICKET_PENDING_STATUSES",
    "ALLOWED_QUEUE_TICKET_TRANSITIONS",
    "DEFAULT_WAIT_MINUTES_NO_STAFF",
    "can_transition",
    "assert_transition",
    "validate_service_ids",
    "estimate_wait_minutes",
    "QueueTicketToCreate",
    "QueueTicket",
    "QueueTicketEntry",
]
