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
from collections.abc import Mapping
from typing import Protocol

from coiflink_api.domain.dashboard import InProgressService
from coiflink_api.domain.hairdresser_performance import HairdresserActivityCounts
from coiflink_api.domain.queue_ticket import (
    QueueTicket,
    QueueTicketEntry,
    QueueTicketToCreate,
)
from coiflink_api.domain.service_demand import ServiceDemand


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

    def count_waiting_ahead(
        self, salon_id: uuid.UUID, ticket_number: int, *, issued_date: datetime.date
    ) -> int:
        """Tickets `waiting` du salon/jour dont `ticket_number` est **strictement
        inférieur** à `ticket_number` — nombre de personnes encore devant ce ticket
        dans la file.

        Reste correct **même bien après** l'émission du ticket, contrairement à
        `count_waiting` (décompte total des `waiting`, qui dérive dès qu'un autre
        ticket change de statut) : la numérotation par salon/jour est **strictement
        croissante** (ADR-0040), donc `ticket_number < X` signifie toujours « émis
        avant X », quoi qu'il soit arrivé depuis aux tickets émis après X.
        """
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
        """Tickets **actifs** du jour (`waiting`/`called`/`in_progress`/`done`/
        `expired`), noms résolus, triés `ticket_number` croissant (file gérant
        #157). `expired` (annulation manuelle, motif obligatoire) reste visible
        pour le reste de la journée — élargissement délibéré, cf.
        `QUEUE_TICKET_ACTIVE_STATUSES`."""
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

    def cancel(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        reason: str,
        *,
        now: datetime.datetime,
    ) -> QueueTicket:
        """Passe le ticket `waiting`/`called` → `expired` (annulation manuelle, no-show).

        `UPDATE ... WHERE status IN ('waiting', 'called')` **conditionnel**
        (garde TOCTOU, miroir `start`/`complete`) : lève
        `domain.errors.InvalidQueueTicketTransition` si le ticket n'est plus
        `waiting`/`called` — couvre notamment `in_progress` (règle métier
        centrale : un ticket déjà pris en charge n'est plus annulable ainsi),
        ainsi que `done`/`expired`. Le `reason` est déjà **validé** par le cas
        d'usage (`validate_cancellation_reason`) ; ce dépôt se contente de
        l'écrire tel quel sur `cancellation_reason`. `flush` sans `commit`.
        """
        ...

    def update_services(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        service_ids: tuple[uuid.UUID, ...],
    ) -> QueueTicket:
        """Remplace les prestations d'un ticket `waiting`/`in_progress` (#161).

        `UPDATE ... WHERE status IN ('waiting', 'in_progress')` **conditionnel**
        (garde TOCTOU, même patron que `start`/`complete`) : lève
        `domain.errors.InvalidQueueTicketTransition` si le ticket n'est plus dans
        un état éditable (déjà servi, expiré). La jonction `queue_ticket_services`
        est intégralement remplacée (delete + insert, miroir `create`). `flush`
        sans `commit`.
        """
        ...

    def count_by_status_in_range(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[str, int]:
        """Décompte `GROUP BY status` des tickets du salon sur `[date_from, date_to]` (#148).

        Le filtre `status IN statuses` est **décidé serveur**. Isolation §11.2
        ré-affirmée **en SQL**. Agrégat en base, aucune ligne ni PII rapatriée.
        """
        ...

    def count_distinct_completed_clients(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> int:
        """`COUNT(DISTINCT customer_profile_id)` des tickets `done` sur la période (#148).

        Un ticket anonyme (`customer_profile_id IS NULL`) n'est **jamais** compté (pas
        de client identifiable). Le `customer_profile_id` est **compté mais jamais
        sélectionné** (anti-oracle §11.1/§11.3). Isolation §11.2 ré-affirmée en SQL.
        """
        ...

    def attendance_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, int]:
        """Fréquentation du salon **par jour civil** (`GROUP BY issued_date`, #148).

        Compte les tickets du salon (tous statuts) par jour dans `[date_from,
        date_to]` **inclus**. Un jour sans ticket est **absent** de la map (le
        domaine `build_series` le complète à `0`). Isolation §11.2 ré-affirmée en
        SQL. Lecture pure.
        """
        ...

    def count_in_progress(self, salon_id: uuid.UUID) -> int:
        """Nombre de tickets `in_progress` **maintenant** (#148).

        Contrairement à l'ancien RDV (« en cours » dérivé d'un créneau `slot @>
        now`), un ticket walk-in porte directement le statut `in_progress` —
        décompte direct, aucune arithmétique de créneau. Isolation §11.2 ré-affirmée
        en SQL.
        """
        ...

    def count_waiting_beyond_estimate(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> int:
        """Tickets `waiting` dont l'attente **réelle** dépasse l'estimation figée (#148).

        `now - created_at > estimated_wait_minutes` — alerte « attente prolongée »,
        équivalent walk-in de l'ancien `prolonged_wait` (RDV `PENDING` dont le
        créneau était dépassé). Isolation §11.2 ré-affirmée en SQL.
        """
        ...

    def list_in_progress_details(
        self, salon_id: uuid.UUID
    ) -> tuple[InProgressService, ...]:
        """Tickets `in_progress`, enrichis des noms d'affichage (#148).

        Émet **uniquement** des noms d'affichage (`customer_profiles.full_name`,
        `services.name`, `users.full_name`, patron #43/#36) — **jamais**
        `customer_profile_id`/`hairdresser_id` ni contact. Isolation §11.2
        ré-affirmée en SQL. Trié `started_at` croissant. Lecture pure.
        """
        ...

    def demand_by_service(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> tuple[ServiceDemand, ...]:
        """Agrège volume + revenu **par prestation** du salon (US-6.3 #41).

        `GROUP BY service_id` en base : `COUNT(*)` = volume (occurrences dans
        `queue_ticket_services` des tickets dont le statut ∈ `statuses`),
        `COALESCE(SUM(services.price), 0)` = revenu — **prix courant** (résolution en
        direct, décision actée #148 : `queue_ticket_services` ne fige aucun prix,
        contrairement à l'ancien `appointment_services.price_at_booking`). Isolation
        §11.2 ré-affirmée en SQL. Ordre **non garanti** (le domaine ordonne). Lecture
        pure, aucune PII rapatriée.
        """
        ...

    def performance_by_hairdresser(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
        completed_statuses: tuple[str, ...],
        cancelled_statuses: tuple[str, ...],
    ) -> tuple[HairdresserActivityCounts, ...]:
        """Agrège les compteurs de file d'attente **par coiffeur** du salon (US-6.5 #43).

        Deux agrégats **séparés** `GROUP BY hairdresser_id` pour ne **pas sur-compter**
        (miroir de l'ancien `performance_by_hairdresser` planning) :

        1. sur `queue_tickets` (join `users` pour le nom) : `COUNT(*)` = `total_count`
           (tous statuts assignés), `SUM(CASE …)` = `cancelled_count` (tickets dont
           `status ∈ cancelled_statuses` — équivalent walk-in de l'ancien « annulé »,
           un ticket `expired`) ;
        2. sur `queue_ticket_services` (join `queue_tickets`, filtré `status ∈
           completed_statuses`) : `COUNT` = `services_completed` (occurrences
           **réalisées**), mappé par `hairdresser_id` (défaut `0`).

        L'isolation §11.2 est ré-affirmée **en SQL** (`WHERE queue_tickets.salon_id`)
        et `hairdresser_id IS NOT NULL` exclut les tickets non assignés. La lecture ne
        rapatrie **aucune** ligne ni PII **client** — seulement les tuples agrégés + le
        nom d'affichage de l'employé (`users.full_name`, jamais téléphone/e-mail).
        Ordre **non garanti** (le domaine ordonne). Lecture pure (aucun `flush`).
        """
        ...


__all__ = ["QueueTicketRepository"]
