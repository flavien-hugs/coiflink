"""Adapter sortant : persistance des **tickets de passage walk-in** (US-8.3, #157).

Implémente le port `QueueTicketRepository` sur une `Session` SQLAlchemy 2.0 et les
modèles ORM `models.QueueTicket`/`models.QueueTicketService` (tables du schéma
`0014`). Seul cet adapter connaît SQLAlchemy ; il mappe les entités de domaine ↔
modèles ORM.

**Numérotation séquentielle sûre en concurrence (patron ADR-0040).** `create`
sérialise les créations concurrentes du **même salon et du même jour** par un
verrou consultatif **transactionnel** (`pg_advisory_xact_lock(hashtext(...))`,
relâché au commit/rollback piloté par `get_session`) avant de lire
`MAX(ticket_number)+1` — pas de nouvelle table de compteur, pas de nouvelle
frontière de transaction. La contrainte `uq_queue_tickets_salon_day_number` est le
filet ultime (une course improbable devient `IntegrityError`, jamais une
corruption silencieuse).

**Isolation §11.2 au niveau du dépôt** : toutes les méthodes filtrent `salon_id` en
SQL — impossible de lire/muter le ticket d'un autre salon même si l'`id` est deviné
(miroir `SqlPaymentRepository`/`SqlCustomerRepository`). Les écritures sont
`flush`ées **sans commit** (atomicité pilotée par `get_session`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Mapping

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.customer import walk_in_first_name
from coiflink_api.domain.dashboard import InProgressService
from coiflink_api.domain.discrepancy import PAID_PAYMENT_STATUSES
from coiflink_api.domain.errors import HairdresserAlreadyBusy, InvalidQueueTicketTransition
from coiflink_api.domain.hairdresser_performance import HairdresserActivityCounts
from coiflink_api.domain.queue_ticket import (
    QUEUE_TICKET_ACTIVE_STATUSES,
    QUEUE_TICKET_PENDING_STATUSES,
    QueueTicket,
    QueueTicketEntry,
    QueueTicketToCreate,
)
from coiflink_api.domain.service_demand import ServiceDemand

_AMOUNT_QUANTUM = decimal.Decimal("0.01")

# Nom + SQLSTATE de l'index unique partiel global qui garantit qu'une coiffeuse
# ne sert qu'un seul ticket `in_progress` à la fois (#173, migration `0021`).
_HAIRDRESSER_IN_PROGRESS_UNIQUE_INDEX = "uq_queue_tickets_hairdresser_in_progress"
_UNIQUE_SQLSTATE = "23505"


class SqlQueueTicketRepository:
    """Dépôt de tickets de passage adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, ticket: QueueTicketToCreate, *, issued_date: datetime.date) -> QueueTicket:
        """Insère le ticket (`status = waiting`) + sa jonction — `flush` sans `commit`.

        Alloue un `ticket_number` séquentiel par salon **et** jour civil sous verrou
        consultatif transactionnel (ADR-0040, clé `salon_id:issued_date`) puis
        `MAX+1` dans la **même** transaction. `estimated_wait_minutes` est celui déjà
        **calculé** par le cas d'usage (figé à l'émission).
        """

        lock_key = f"{ticket.salon_id}:{issued_date.isoformat()}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )
        next_number = self._session.execute(
            select(func.coalesce(func.max(models.QueueTicket.ticket_number), 0) + 1).where(
                models.QueueTicket.salon_id == ticket.salon_id,
                models.QueueTicket.issued_date == issued_date,
            )
        ).scalar_one()

        row = models.QueueTicket(
            salon_id=ticket.salon_id,
            ticket_number=next_number,
            issued_date=issued_date,
            customer_profile_id=ticket.customer_profile_id,
            estimated_wait_minutes=ticket.estimated_wait_minutes,
            status="waiting",
        )
        self._session.add(row)
        # Flush pour matérialiser l'`id` du ticket (référencé par la jonction).
        self._session.flush()
        for service_id in ticket.service_ids:
            self._session.add(
                models.QueueTicketService(
                    queue_ticket_id=row.id,
                    service_id=service_id,
                    salon_id=ticket.salon_id,
                )
            )
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, ticket.service_ids)

    def get(self, salon_id: uuid.UUID, ticket_id: uuid.UUID) -> QueueTicket | None:
        """Charge le ticket `(salon_id, ticket_id)` — filtre d'isolation §11.2."""

        row = self._get_row(salon_id, ticket_id)
        if row is None:
            return None
        return _to_domain(row, self._load_service_ids(ticket_id))

    def count_waiting(self, salon_id: uuid.UUID, *, issued_date: datetime.date) -> int:
        """Nombre de tickets `waiting` du salon pour `issued_date` (position file)."""

        stmt = (
            select(func.count())
            .select_from(models.QueueTicket)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.issued_date == issued_date,
                models.QueueTicket.status == "waiting",
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def count_waiting_ahead(
        self, salon_id: uuid.UUID, ticket_number: int, *, issued_date: datetime.date
    ) -> int:
        """Tickets `waiting` du salon/jour dont `ticket_number` < `ticket_number` donné."""

        stmt = (
            select(func.count())
            .select_from(models.QueueTicket)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.issued_date == issued_date,
                models.QueueTicket.status == "waiting",
                models.QueueTicket.ticket_number < ticket_number,
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def average_requested_duration_minutes(
        self, salon_id: uuid.UUID, *, issued_date: datetime.date
    ) -> float | None:
        """`AVG(duration_minutes)` des prestations des tickets actifs (une requête)."""

        stmt = (
            select(func.avg(models.Service.duration_minutes))
            .select_from(models.QueueTicket)
            .join(
                models.QueueTicketService,
                models.QueueTicketService.queue_ticket_id == models.QueueTicket.id,
            )
            .join(
                models.Service,
                models.Service.id == models.QueueTicketService.service_id,
            )
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.issued_date == issued_date,
                models.QueueTicket.status.in_(QUEUE_TICKET_PENDING_STATUSES),
            )
        )
        result = self._session.scalar(stmt)
        return float(result) if result is not None else None

    def list_active_for_salon(
        self, salon_id: uuid.UUID, *, issued_date: datetime.date
    ) -> tuple[QueueTicketEntry, ...]:
        """Tickets actifs du jour (**y compris** `expired`), noms résolus, triés
        `ticket_number`.

        Le prénom du client est **dérivé** de `customer_profiles.full_name`
        (`walk_in_first_name`, projection minimale §11.3, miroir #156) ; les noms de
        prestations et de coiffeuse sont résolus par jointure. `customer_profile_id`/
        `service_ids` (UUID **opaques**) sont portés en plus des noms résolus —
        consommés par le **détail** du ticket côté gérant (jamais un nom complet ni
        un téléphone dans cette ligne elle-même). `payment_id` est résolu par une
        sous-requête **scalaire** (jamais un join, qui multiplierait les lignes du
        ticket si plusieurs paiements matchaient) — le paiement `VALIDATED`/
        `ADJUSTED` le plus récent du ticket, ou `None` (même notion « payé » que
        `PAID_PAYMENT_STATUSES` de `domain/discrepancy.py`). `cancellation_reason`
        (non `None` uniquement pour un `expired` issu d'une annulation manuelle)
        permet à la file gérant d'afficher « Annulée » + le motif sans disparaître.
        """

        payment_id_subquery = (
            select(models.Payment.id)
            .where(
                models.Payment.salon_id == models.QueueTicket.salon_id,
                models.Payment.queue_ticket_id == models.QueueTicket.id,
                models.Payment.status.in_(PAID_PAYMENT_STATUSES),
            )
            .order_by(models.Payment.created_at.desc())
            .limit(1)
            .correlate(models.QueueTicket)
            .scalar_subquery()
        )
        rows = self._session.execute(
            select(
                models.QueueTicket,
                models.CustomerProfile.full_name,
                models.User.full_name,
                payment_id_subquery.label("payment_id"),
            )
            .outerjoin(
                models.CustomerProfile,
                models.CustomerProfile.id == models.QueueTicket.customer_profile_id,
            )
            .outerjoin(models.User, models.User.id == models.QueueTicket.hairdresser_id)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.issued_date == issued_date,
                models.QueueTicket.status.in_(QUEUE_TICKET_ACTIVE_STATUSES),
            )
            .order_by(models.QueueTicket.ticket_number.asc())
        ).all()

        ticket_ids = [row[0].id for row in rows]
        names_by_ticket = self._service_names_by_ticket(ticket_ids)
        ids_by_ticket = self._service_ids_by_ticket(ticket_ids)
        return tuple(
            QueueTicketEntry(
                ticket_id=ticket.id,
                ticket_number=ticket.ticket_number,
                customer_profile_id=ticket.customer_profile_id,
                customer_first_name=(
                    walk_in_first_name(customer_name) if customer_name is not None else None
                ),
                service_ids=ids_by_ticket.get(ticket.id, ()),
                service_names=names_by_ticket.get(ticket.id, ()),
                hairdresser_id=ticket.hairdresser_id,
                hairdresser_name=hairdresser_name,
                status=ticket.status,
                estimated_wait_minutes=ticket.estimated_wait_minutes,
                created_at=ticket.created_at,
                started_at=ticket.started_at,
                completed_at=ticket.completed_at,
                payment_id=payment_id,
                cancellation_reason=ticket.cancellation_reason,
            )
            for ticket, customer_name, hairdresser_name, payment_id in rows
        )

    def is_hairdresser_busy(self, hairdresser_id: uuid.UUID) -> bool:
        """Vrai si la coiffeuse a déjà un ticket `in_progress` — portée **globale** (#173)."""

        return bool(
            self._session.scalar(
                select(models.QueueTicket.id).where(
                    models.QueueTicket.hairdresser_id == hairdresser_id,
                    models.QueueTicket.status == "in_progress",
                )
            )
        )

    def start(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        hairdresser_id: uuid.UUID,
        *,
        now: datetime.datetime,
    ) -> QueueTicket:
        """Passe `waiting → in_progress` (assigne la coiffeuse, pose `started_at`).

        Chargement **conditionnel** `status = 'waiting'` (garde TOCTOU, miroir
        `mark_started`) : un ticket qui n'est plus `waiting` (déjà pris en charge,
        double-clic concurrent) lève `InvalidQueueTicketTransition`. La violation de
        l'index unique partiel global `uq_queue_tickets_hairdresser_in_progress`
        (course concurrente perdue sur la même coiffeuse) est retraduite en
        `HairdresserAlreadyBusy` (#173) — toute autre `IntegrityError` (FK/CHECK
        inattendu) est relevée telle quelle.
        """

        row = self._session.scalar(
            select(models.QueueTicket).where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.id == ticket_id,
                models.QueueTicket.status == "waiting",
            )
        )
        if row is None:
            raise InvalidQueueTicketTransition(
                "Ce ticket ne peut pas être pris en charge dans cet état."
            )
        row.status = "in_progress"
        row.hairdresser_id = hairdresser_id
        if row.started_at is None:
            row.started_at = now
        try:
            self._session.flush()
        except IntegrityError as exc:
            if _is_hairdresser_busy_conflict(exc):
                self._session.rollback()
                raise HairdresserAlreadyBusy(
                    "Cette coiffeuse est déjà occupée sur un autre ticket."
                ) from exc
            raise
        self._session.refresh(row)
        return _to_domain(row, self._load_service_ids(ticket_id))

    def complete(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID, *, now: datetime.datetime
    ) -> QueueTicket:
        """Passe `in_progress → done` (pose `completed_at`) — garde TOCTOU conditionnelle."""

        row = self._session.scalar(
            select(models.QueueTicket).where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.id == ticket_id,
                models.QueueTicket.status == "in_progress",
            )
        )
        if row is None:
            raise InvalidQueueTicketTransition("Ce ticket ne peut pas être clôturé dans cet état.")
        row.status = "done"
        if row.completed_at is None:
            row.completed_at = now
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, self._load_service_ids(ticket_id))

    def cancel(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        reason: str,
        *,
        now: datetime.datetime,
    ) -> QueueTicket:
        """Passe `waiting`/`called` → `expired` (annulation manuelle, no-show).

        Chargement **conditionnel** `status IN ('waiting', 'called')` (garde
        TOCTOU, miroir `start`/`complete`) : un ticket déjà `in_progress` — ou
        `done`/`expired` — lève `InvalidQueueTicketTransition`, ce qui
        ré-affirme au niveau du dépôt la règle métier centrale « impossible
        d'annuler un ticket déjà pris en charge ». `now` n'est pas persisté
        (aucun horodatage dédié à l'annulation, `updated_at` en tient lieu si un
        jour introduit) — paramètre gardé pour la symétrie de signature avec
        `start`/`complete`.
        """

        row = self._session.scalar(
            select(models.QueueTicket).where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.id == ticket_id,
                models.QueueTicket.status.in_(("waiting", "called")),
            )
        )
        if row is None:
            raise InvalidQueueTicketTransition("Ce ticket ne peut pas être annulé dans cet état.")
        row.status = "expired"
        row.cancellation_reason = reason
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, self._load_service_ids(ticket_id))

    def update_services(
        self,
        salon_id: uuid.UUID,
        ticket_id: uuid.UUID,
        service_ids: tuple[uuid.UUID, ...],
    ) -> QueueTicket:
        """Remplace les prestations d'un ticket `waiting`/`in_progress` (#161).

        Chargement **conditionnel** `status IN ('waiting', 'in_progress')` (garde
        TOCTOU, miroir `start`/`complete`) : un ticket qui n'est plus dans un état
        éditable (déjà servi, expiré) lève `InvalidQueueTicketTransition`. La
        jonction `queue_ticket_services` est intégralement remplacée (delete puis
        insert, même patron que `create`).
        """

        row = self._session.scalar(
            select(models.QueueTicket).where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.id == ticket_id,
                models.QueueTicket.status.in_(QUEUE_TICKET_PENDING_STATUSES),
            )
        )
        if row is None:
            raise InvalidQueueTicketTransition("Ce ticket ne peut plus être modifié dans cet état.")
        self._session.execute(
            delete(models.QueueTicketService).where(
                models.QueueTicketService.queue_ticket_id == ticket_id
            )
        )
        for service_id in service_ids:
            self._session.add(
                models.QueueTicketService(
                    queue_ticket_id=ticket_id,
                    service_id=service_id,
                    salon_id=salon_id,
                )
            )
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, tuple(service_ids))

    def count_by_status_in_range(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[str, int]:
        """`GROUP BY status` des tickets du salon sur `[date_from, date_to]` (#148)."""

        stmt = (
            select(models.QueueTicket.status, func.count())
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.status.in_(statuses),
                models.QueueTicket.issued_date >= date_from,
                models.QueueTicket.issued_date <= date_to,
            )
            .group_by(models.QueueTicket.status)
        )
        return {status: int(count) for status, count in self._session.execute(stmt).all()}

    def count_distinct_completed_clients(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> int:
        """`COUNT(DISTINCT customer_profile_id)` des tickets `done` sur la période (#148).

        Un ticket anonyme (`customer_profile_id IS NULL`) n'est jamais compté.
        """

        stmt = select(func.count(func.distinct(models.QueueTicket.customer_profile_id))).where(
            models.QueueTicket.salon_id == salon_id,
            models.QueueTicket.status == "done",
            models.QueueTicket.customer_profile_id.is_not(None),
            models.QueueTicket.issued_date >= date_from,
            models.QueueTicket.issued_date <= date_to,
        )
        return int(self._session.scalar(stmt) or 0)

    def attendance_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, int]:
        """Fréquentation (tous statuts) **par jour civil** (`GROUP BY issued_date`, #148)."""

        stmt = (
            select(models.QueueTicket.issued_date, func.count())
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.issued_date >= date_from,
                models.QueueTicket.issued_date <= date_to,
            )
            .group_by(models.QueueTicket.issued_date)
        )
        return {day: int(count) for day, count in self._session.execute(stmt).all()}

    def count_in_progress(self, salon_id: uuid.UUID) -> int:
        """Nombre de tickets `in_progress` **maintenant** — décompte direct (#148)."""

        stmt = (
            select(func.count())
            .select_from(models.QueueTicket)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.status == "in_progress",
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def count_waiting_beyond_estimate(self, salon_id: uuid.UUID, *, now: datetime.datetime) -> int:
        """Tickets `waiting` dont l'attente réelle dépasse `estimated_wait_minutes` (#148)."""

        now_ts = now
        elapsed_minutes = func.extract("epoch", now_ts - models.QueueTicket.created_at) / 60
        stmt = (
            select(func.count())
            .select_from(models.QueueTicket)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.status == "waiting",
                elapsed_minutes > models.QueueTicket.estimated_wait_minutes,
            )
        )
        return int(self._session.scalar(stmt) or 0)

    def list_in_progress_details(self, salon_id: uuid.UUID) -> tuple[InProgressService, ...]:
        """Tickets `in_progress`, enrichis des noms d'affichage (#148).

        Décompte **direct** sur `status = 'in_progress'` (contrairement à l'ancien
        RDV, aucune arithmétique de créneau n'est nécessaire — le statut du ticket
        encode déjà « en cours »).
        """

        customer = aliased(models.CustomerProfile)
        hairdresser = aliased(models.User)
        rows = self._session.execute(
            select(
                models.QueueTicket.id,
                customer.full_name.label("client_name"),
                hairdresser.full_name.label("hairdresser_name"),
                models.QueueTicket.started_at,
                models.QueueTicket.status,
            )
            .outerjoin(customer, customer.id == models.QueueTicket.customer_profile_id)
            .outerjoin(hairdresser, hairdresser.id == models.QueueTicket.hairdresser_id)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.status == "in_progress",
            )
            .order_by(
                models.QueueTicket.started_at.asc(),
                models.QueueTicket.id.asc(),
            )
        ).all()
        if not rows:
            return ()

        names_by_ticket = self._service_names_by_ticket([row.id for row in rows])
        return tuple(
            InProgressService(
                queue_ticket_id=str(row.id),
                client_name=row.client_name,
                service_names=names_by_ticket.get(row.id, ()),
                hairdresser_name=row.hairdresser_name,
                started_at=row.started_at,
                status=row.status,
            )
            for row in rows
        )

    def demand_by_service(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> tuple[ServiceDemand, ...]:
        stmt = (
            select(
                models.QueueTicketService.service_id,
                models.Service.name,
                func.count().label("volume"),
                func.coalesce(func.sum(models.Service.price), 0).label("revenue"),
            )
            .join(
                models.QueueTicket,
                models.QueueTicket.id == models.QueueTicketService.queue_ticket_id,
            )
            .join(
                models.Service,
                (models.Service.id == models.QueueTicketService.service_id)
                & (models.Service.salon_id == models.QueueTicketService.salon_id),
            )
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.status.in_(statuses),
            )
            .group_by(models.QueueTicketService.service_id, models.Service.name)
        )
        if date_from is not None:
            stmt = stmt.where(models.QueueTicket.issued_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(models.QueueTicket.issued_date <= date_to)

        rows = self._session.execute(stmt).all()
        return tuple(
            ServiceDemand(
                service_id=row.service_id,
                name=row.name,
                volume=int(row.volume),
                revenue=decimal.Decimal(row.revenue or 0).quantize(_AMOUNT_QUANTUM),
            )
            for row in rows
        )

    def performance_by_hairdresser(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
        completed_statuses: tuple[str, ...],
        cancelled_statuses: tuple[str, ...],
    ) -> tuple[HairdresserActivityCounts, ...]:
        cancelled = func.sum(
            case(
                (models.QueueTicket.status.in_(cancelled_statuses), 1),
                else_=0,
            )
        )
        counts_stmt = (
            select(
                models.QueueTicket.hairdresser_id,
                models.User.full_name,
                func.count().label("total_count"),
                func.coalesce(cancelled, 0).label("cancelled_count"),
            )
            .join(models.User, models.User.id == models.QueueTicket.hairdresser_id)
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.hairdresser_id.is_not(None),
                models.QueueTicket.issued_date.between(date_from, date_to),
            )
            .group_by(models.QueueTicket.hairdresser_id, models.User.full_name)
        )

        # `services_completed` = occurrences de prestations réalisées (lignes
        # `queue_ticket_services` des tickets `done`) — comptées **séparément** pour ne
        # pas gonfler les comptes de tickets via le join un-à-plusieurs.
        services_stmt = (
            select(
                models.QueueTicket.hairdresser_id,
                func.count().label("services_completed"),
            )
            .join(
                models.QueueTicketService,
                models.QueueTicketService.queue_ticket_id == models.QueueTicket.id,
            )
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.hairdresser_id.is_not(None),
                models.QueueTicket.status.in_(completed_statuses),
                models.QueueTicket.issued_date.between(date_from, date_to),
            )
            .group_by(models.QueueTicket.hairdresser_id)
        )
        services_by_hairdresser = {
            row.hairdresser_id: int(row.services_completed)
            for row in self._session.execute(services_stmt).all()
        }

        return tuple(
            HairdresserActivityCounts(
                hairdresser_id=row.hairdresser_id,
                name=row.full_name,
                services_completed=services_by_hairdresser.get(row.hairdresser_id, 0),
                cancelled_count=int(row.cancelled_count),
                total_count=int(row.total_count),
            )
            for row in self._session.execute(counts_stmt).all()
        )

    # ----------------------------------------------------------------------- #
    # Helpers privés.
    # ----------------------------------------------------------------------- #
    def _get_row(self, salon_id: uuid.UUID, ticket_id: uuid.UUID) -> models.QueueTicket | None:
        return self._session.scalar(
            select(models.QueueTicket).where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.id == ticket_id,
            )
        )

    def _load_service_ids(self, ticket_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        rows = self._session.execute(
            select(models.QueueTicketService.service_id).where(
                models.QueueTicketService.queue_ticket_id == ticket_id
            )
        ).all()
        return tuple(row[0] for row in rows)

    def _service_names_by_ticket(
        self, ticket_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[str, ...]]:
        """Noms de prestations groupés par ticket (bulk, pas de N+1), triés par nom."""

        if not ticket_ids:
            return {}
        rows = self._session.execute(
            select(models.QueueTicketService.queue_ticket_id, models.Service.name)
            .join(
                models.Service,
                models.Service.id == models.QueueTicketService.service_id,
            )
            .where(models.QueueTicketService.queue_ticket_id.in_(ticket_ids))
            .order_by(models.Service.name.asc())
        ).all()
        grouped: dict[uuid.UUID, list[str]] = {}
        for ticket_id, name in rows:
            grouped.setdefault(ticket_id, []).append(name)
        return {ticket_id: tuple(names) for ticket_id, names in grouped.items()}

    def _service_ids_by_ticket(
        self, ticket_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        """Ids de prestations groupés par ticket (bulk, pas de N+1) — miroir des noms.

        UUID **opaques** (non-PII) : consommés par le détail du ticket côté gérant
        pour résoudre prix/durée depuis le catalogue déjà chargé, sans dupliquer ces
        champs ici.
        """

        if not ticket_ids:
            return {}
        rows = self._session.execute(
            select(
                models.QueueTicketService.queue_ticket_id,
                models.QueueTicketService.service_id,
            ).where(models.QueueTicketService.queue_ticket_id.in_(ticket_ids))
        ).all()
        grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
        for ticket_id, service_id in rows:
            grouped.setdefault(ticket_id, []).append(service_id)
        return {ticket_id: tuple(ids) for ticket_id, ids in grouped.items()}


def _is_hairdresser_busy_conflict(exc: IntegrityError) -> bool:
    """Vrai si l'`IntegrityError` provient de l'index unique partiel global
    `uq_queue_tickets_hairdresser_in_progress` (miroir `_is_phone_duplicate`,
    `customer_repository.py`).

    Inspecte le driver psycopg (`orig`) : SQLSTATE `23505` (*unique_violation*)
    **et** nom de contrainte. On ne masque **que** cette violation — une FK ou un
    `CHECK` inattendu doivent remonter.
    """

    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    diag = getattr(orig, "diag", None)
    if (
        diag is not None
        and getattr(diag, "constraint_name", None) == _HAIRDRESSER_IN_PROGRESS_UNIQUE_INDEX
    ):
        return True
    if getattr(orig, "sqlstate", None) != _UNIQUE_SQLSTATE:
        return False
    return _HAIRDRESSER_IN_PROGRESS_UNIQUE_INDEX in str(orig)


def _to_domain(row: models.QueueTicket, service_ids: tuple[uuid.UUID, ...]) -> QueueTicket:
    return QueueTicket(
        id=row.id,
        salon_id=row.salon_id,
        ticket_number=row.ticket_number,
        issued_date=row.issued_date,
        customer_profile_id=row.customer_profile_id,
        service_ids=tuple(service_ids),
        status=row.status,
        hairdresser_id=row.hairdresser_id,
        estimated_wait_minutes=row.estimated_wait_minutes,
        created_at=row.created_at,
        called_at=row.called_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        cancellation_reason=row.cancellation_reason,
    )


__all__ = ["SqlQueueTicketRepository"]
