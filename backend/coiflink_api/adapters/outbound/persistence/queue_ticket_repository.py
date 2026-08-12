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
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.customer import walk_in_first_name
from coiflink_api.domain.errors import InvalidQueueTicketTransition
from coiflink_api.domain.queue_ticket import (
    QUEUE_TICKET_ACTIVE_STATUSES,
    QUEUE_TICKET_PENDING_STATUSES,
    QueueTicket,
    QueueTicketEntry,
    QueueTicketToCreate,
)


class SqlQueueTicketRepository:
    """Dépôt de tickets de passage adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, ticket: QueueTicketToCreate, *, issued_date: datetime.date
    ) -> QueueTicket:
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
            select(
                func.coalesce(func.max(models.QueueTicket.ticket_number), 0) + 1
            ).where(
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

    def get(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> QueueTicket | None:
        """Charge le ticket `(salon_id, ticket_id)` — filtre d'isolation §11.2."""

        row = self._get_row(salon_id, ticket_id)
        if row is None:
            return None
        return _to_domain(row, self._load_service_ids(ticket_id))

    def count_waiting(
        self, salon_id: uuid.UUID, *, issued_date: datetime.date
    ) -> int:
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
        """Tickets actifs du jour (hors `expired`), noms résolus, triés `ticket_number`.

        Le prénom du client est **dérivé** de `customer_profiles.full_name`
        (`walk_in_first_name`, projection minimale §11.3, miroir #156) ; les noms de
        prestations et de coiffeuse sont résolus par jointure (jamais un
        `customer_profile_id` ni un téléphone à l'écran).
        """

        rows = self._session.execute(
            select(
                models.QueueTicket,
                models.CustomerProfile.full_name,
                models.User.full_name,
            )
            .outerjoin(
                models.CustomerProfile,
                models.CustomerProfile.id == models.QueueTicket.customer_profile_id,
            )
            .outerjoin(
                models.User, models.User.id == models.QueueTicket.hairdresser_id
            )
            .where(
                models.QueueTicket.salon_id == salon_id,
                models.QueueTicket.issued_date == issued_date,
                models.QueueTicket.status.in_(QUEUE_TICKET_ACTIVE_STATUSES),
            )
            .order_by(models.QueueTicket.ticket_number.asc())
        ).all()

        names_by_ticket = self._service_names_by_ticket(
            [row[0].id for row in rows]
        )
        return tuple(
            QueueTicketEntry(
                ticket_id=ticket.id,
                ticket_number=ticket.ticket_number,
                customer_first_name=(
                    walk_in_first_name(customer_name)
                    if customer_name is not None
                    else None
                ),
                service_names=names_by_ticket.get(ticket.id, ()),
                hairdresser_id=ticket.hairdresser_id,
                hairdresser_name=hairdresser_name,
                status=ticket.status,
                estimated_wait_minutes=ticket.estimated_wait_minutes,
                created_at=ticket.created_at,
                started_at=ticket.started_at,
                completed_at=ticket.completed_at,
            )
            for ticket, customer_name, hairdresser_name in rows
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
        double-clic concurrent) lève `InvalidQueueTicketTransition`.
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
        self._session.flush()
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
            raise InvalidQueueTicketTransition(
                "Ce ticket ne peut pas être clôturé dans cet état."
            )
        row.status = "done"
        if row.completed_at is None:
            row.completed_at = now
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, self._load_service_ids(ticket_id))

    # ----------------------------------------------------------------------- #
    # Helpers privés.
    # ----------------------------------------------------------------------- #
    def _get_row(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> models.QueueTicket | None:
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
            select(
                models.QueueTicketService.queue_ticket_id, models.Service.name
            )
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


def _to_domain(
    row: models.QueueTicket, service_ids: tuple[uuid.UUID, ...]
) -> QueueTicket:
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
    )


__all__ = ["SqlQueueTicketRepository"]
