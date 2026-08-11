"""Port de persistance des **tickets de passage walk-in** (`Protocol`, US-8.3, #157).

Le cas d'usage `application/queue_ticket.py` déclare ici ses besoins d'écriture et
de lecture ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/queue_ticket_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Isolation §11.2 au niveau du dépôt** : toutes les méthodes filtrent `salon_id`
en SQL (miroir `CustomerRepository`/`PaymentRepository`) — un ticket d'un autre
salon est **indiscernable** d'un ticket inexistant, impossible à lire ou muter même
si l'`id` est deviné.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Protocol

from coiflink_api.domain.queue_ticket import (
    QueueTicket,
    QueueTicketEntry,
    QueueTicketToCreate,
)


class QueueTicketRepository(Protocol):
    """Contrat de persistance des tickets de passage d'un salon."""

    def create(
        self, ticket: QueueTicketToCreate, *, issued_date: datetime.date
    ) -> QueueTicket:
        """Insère le ticket en allouant un `ticket_number` séquentiel par salon+jour.

        Le numéro est alloué **atomiquement** sous verrou consultatif
        transactionnel (`pg_advisory_xact_lock`, clé `salon_id:issued_date`, patron
        ADR-0040) puis `MAX(ticket_number)+1` dans la même transaction. `flush`
        sans `commit` (atomicité pilotée par `get_session`). La contrainte
        `uq_queue_tickets_salon_day_number` est le filet ultime d'une course
        concurrente. `service_ids` est écrit dans la jonction dans la même unité.
        """
        ...

    def get(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> QueueTicket | None:
        """Retourne le ticket `(salon_id, ticket_id)`, sinon `None` (isolation §11.2)."""
        ...

    def count_waiting(
        self, salon_id: uuid.UUID, *, issued_date: datetime.date
    ) -> int:
        """Nombre de tickets `waiting` du salon pour le jour (position dans la file)."""
        ...

    def average_requested_duration_minutes(
        self, salon_id: uuid.UUID, *, issued_date: datetime.date
    ) -> float | None:
        """Durée moyenne des prestations des tickets **actifs** (`waiting`/`in_progress`).

        `AVG(services.duration_minutes)` en **une** requête agrégée joignant
        `queue_ticket_services → services`, filtrée sur les tickets `waiting`/
        `in_progress` du jour. `None` si aucun ticket actif — le cas d'usage bascule
        alors sur le repli « durée des prestations de ce ticket ».
        """
        ...

    def list_active_for_salon(
        self, salon_id: uuid.UUID, *, issued_date: datetime.date
    ) -> tuple[QueueTicketEntry, ...]:
        """Tickets **actifs** du jour (`waiting`/`called`/`in_progress`/`done`, hors
        `expired`), noms résolus, triés `ticket_number` croissant (file gérant #157)."""
        ...

    def start(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        hairdresser_id: uuid.UUID,
        *,
        now: datetime.datetime,
    ) -> QueueTicket:
        """Passe le ticket `waiting → in_progress` (assigne la coiffeuse, pose `started_at`).

        `UPDATE ... WHERE status = 'waiting'` **conditionnel** (garde TOCTOU, miroir
        `mark_started`) : lève `domain.errors.InvalidQueueTicketTransition` si le
        ticket n'est plus `waiting` (déjà pris en charge, terminé). `flush` sans
        `commit`.
        """
        ...

    def complete(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID, *, now: datetime.datetime
    ) -> QueueTicket:
        """Passe le ticket `in_progress → done` (pose `completed_at`).

        `UPDATE ... WHERE status = 'in_progress'` **conditionnel** (garde TOCTOU) :
        lève `domain.errors.InvalidQueueTicketTransition` si le ticket n'est pas
        `in_progress`. `flush` sans `commit`.
        """
        ...


__all__ = ["QueueTicketRepository"]
