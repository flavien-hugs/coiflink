"""Ticket de passage walk-in & estimation d'attente (domaine pur, US-8.3, #157).

Domaine **pur** (aucune I/O, ni FastAPI ni SQLAlchemy — ADR-0008) du **ticket de
passage** délivré à un client sans rendez-vous à la borne terminal (PRD §17, jalon
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
    InvalidQueueTicketCancellationReason,
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

# Statuts **actifs** repris dans la file gérant (§C) : le jour civil du salon.
# `done` reste visible pour la journée (prestation servie), à l'image d'un RDV
# `COMPLETED` ; `expired` (annulation manuelle, no-show, motif obligatoire) reste
# de même visible pour le reste de la journée, affiché « Annulée » avec son
# motif — un ticket annulé ne doit **jamais** disparaître de la file, seulement
# porter clairement son état terminal (élargissement délibéré, pas un oubli).
QUEUE_TICKET_ACTIVE_STATUSES: tuple[QueueTicketStatus, ...] = (
    "waiting",
    "called",
    "in_progress",
    "done",
    "expired",
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

# Borne applicative du motif d'annulation (colonne `TEXT`, non-bornée en base) —
# même convention que les autres champs libres courts (`SPECIALTIES_MAX_LENGTH`,
# `DEVICE_LABEL_MAX_LENGTH`) : jamais un corps non borné.
CANCELLATION_REASON_MAX_LENGTH = 500


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
    """Exige **au moins une** prestation, **sans doublon** (miroir `require_services` du RDV).

    Ne juge **pas** l'appartenance salon ni l'activité des prestations (résolues
    par le cas d'usage contre le catalogue) : seules la cardinalité « ≥ 1 » et
    l'absence de répétition sont des règles de domaine pures. Un doublon violerait
    silencieusement la contrainte PK composite `(queue_ticket_id, service_id)` de
    `queue_ticket_services` (`IntegrityError` non interceptée, `500`) — rejeté ici
    **avant** toute écriture, avec un message métier clair. Lève
    `InvalidQueueTicketServices` sur un tuple vide ou un doublon.
    """

    if not service_ids:
        raise InvalidQueueTicketServices(
            "Un ticket de passage doit comporter au moins une prestation."
        )
    if len(set(service_ids)) != len(service_ids):
        raise InvalidQueueTicketServices(
            "Une prestation ne peut pas être sélectionnée plusieurs fois."
        )
    return service_ids


def validate_cancellation_reason(reason: str | None) -> str:
    """Exige un motif d'annulation **non vide** et borné (miroir `validate_service_ids`).

    Le motif est **obligatoire** (no-show client, cliente qui ne se présente
    pas) : `None` ou une chaîne vide/blanche après `strip()` lève
    `InvalidQueueTicketCancellationReason`, de même qu'un motif dépassant
    `CANCELLATION_REASON_MAX_LENGTH`. Retourne le motif **trimé**.
    """

    trimmed = reason.strip() if reason is not None else ""
    if not trimmed:
        raise InvalidQueueTicketCancellationReason(
            "Le motif d'annulation est obligatoire."
        )
    if len(trimmed) > CANCELLATION_REASON_MAX_LENGTH:
        raise InvalidQueueTicketCancellationReason(
            "Le motif d'annulation dépasse la longueur autorisée."
        )
    return trimmed


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
    # Motif d'annulation manuelle (no-show), posé **uniquement** quand `status =
    # "expired"` via une annulation explicite (motif obligatoire) ; `None` sinon
    # — y compris pour un `expired` hypothétique d'une autre origine future.
    cancellation_reason: str | None


@dataclass(frozen=True)
class QueueTicketEntry:
    """Ligne **finalisée** d'un ticket dans la file gérant (lecture, §C).

    Miroir de `QueueEntry` (#150) pour les tickets walk-in : n'émet que des noms
    d'affichage (`service_names`/`hairdresser_name` = `services.name`/
    `users.full_name`) et le **prénom** du client (`customer_first_name`,
    projection minimale alignée sur #156, §11.3) — jamais le nom complet ni le
    téléphone **dans cette ligne**. `hairdresser_id`/`customer_profile_id`
    (UUID **opaques**, non-PII) restent exposés : le gérant en a besoin pour agir
    sur la ligne et pour ouvrir le **détail** du ticket (résolution de la fiche
    complète via `GET /customers/{customer_profile_id}`, guardée séparément par
    `CUSTOMER_MANAGE`) — l'exposition reste bornée à la route gérant/coiffeur
    authentifiée, jamais à un écran public. `service_ids` permet de même de
    résoudre le détail (prix/durée courants) d'une prestation depuis le
    catalogue déjà chargé, sans dupliquer ces champs ici.
    """

    ticket_id: uuid.UUID
    ticket_number: int
    customer_profile_id: uuid.UUID | None
    customer_first_name: str | None
    service_ids: tuple[uuid.UUID, ...]
    service_names: tuple[str, ...]
    hairdresser_id: uuid.UUID | None
    hairdresser_name: str | None
    status: QueueTicketStatus
    estimated_wait_minutes: int
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    # Id du paiement `VALIDATED`/`ADJUSTED` rattaché au ticket (même notion de « payé »
    # que `PAID_PAYMENT_STATUSES` de `domain/discrepancy.py`), ou `None` si aucun.
    payment_id: uuid.UUID | None
    # Motif d'annulation manuelle (no-show), affiché « Annulée » + motif dans la
    # file gérant quand `status = "expired"` ; `None` sinon (miroir `QueueTicket`).
    cancellation_reason: str | None


__all__ = [
    "QueueTicketStatus",
    "QUEUE_TICKET_STATUSES",
    "QUEUE_TICKET_ACTIVE_STATUSES",
    "QUEUE_TICKET_PENDING_STATUSES",
    "ALLOWED_QUEUE_TICKET_TRANSITIONS",
    "DEFAULT_WAIT_MINUTES_NO_STAFF",
    "CANCELLATION_REASON_MAX_LENGTH",
    "can_transition",
    "assert_transition",
    "validate_service_ids",
    "validate_cancellation_reason",
    "estimate_wait_minutes",
    "QueueTicketToCreate",
    "QueueTicket",
    "QueueTicketEntry",
]
