"""Cas d'usage : **file d'attente du salon** — pointage réel + lecture (#150).

Tranche applicative hexagonale (ADR-0008) : ces cas d'usage ne dépendent que de
**ports** (`AppointmentRepository`, `PaymentRepository`) — aucune dépendance
FastAPI/SQLAlchemy.

- `MarkAppointmentArrived` / `StartAppointmentService` — pointage manuel du
  gérant sur un RDV `CONFIRMED` **existant** du salon (§ décision produit « RDV
  existants uniquement ») : posent respectivement `arrived_at`/`started_at`
  (distincts du `status` — `domain/queue.py`), journalisent
  `APPOINTMENT_ARRIVED`/`APPOINTMENT_STARTED`. Démarrer exige l'arrivée déjà
  pointée **et** une coiffeuse déjà assignée (`AppointmentArrivalRequired`/
  `AppointmentHairdresserRequired`) — préconditions vérifiées **ici** (le
  dépôt ne les revalide pas), puis **ré-affirmées à l'écriture** par le dépôt
  (conditionnel sur `status = CONFIRMED`, garde TOCTOU, miroir
  `AssignHairdresser`).
- `ListSalonQueue` — lecture pure **composant** deux ports : les RDV
  `CONFIRMED`/`COMPLETED` du jour (`AppointmentRepository.list_queue_details`)
  et, pour les `COMPLETED`, le sous-ensemble couvert par un paiement validé
  (`PaymentRepository.list_paid_appointment_ids`, § décision produit « Payée
  dérivée du paiement réel ») — puis dérive `queue_status` via
  `domain.queue.finalize_queue_entry`. Aucune écriture, aucun audit (consulter
  la file n'est pas une action journalisée, cohérent avec le Dashboard #148).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable

from coiflink_api.application.ports.appointment_repository import AppointmentRepository
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.domain.appointment import Appointment
from coiflink_api.domain.audit import ENTITY_TYPE_APPOINTMENT, AuditAction, AuditEntry
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import (
    AppointmentArrivalRequired,
    AppointmentHairdresserRequired,
    AppointmentNotFound,
)
from coiflink_api.domain.queue import QueueEntry, finalize_queue_entry


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware), miroir `registration.py`."""

    return datetime.datetime.now(datetime.timezone.utc)


class MarkAppointmentArrived:
    """Pointe l'arrivée d'une cliente sur un RDV `CONFIRMED` du salon (#150)."""

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        audit_log: AuditLog,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._appointments = appointment_repository
        self._audit_log = audit_log
        self._clock = clock if clock is not None else _utc_now

    def execute(
        self, appointment_id: uuid.UUID, salon_id: uuid.UUID, actor_id: uuid.UUID
    ) -> Appointment:
        current = self._appointments.get_in_salon(appointment_id, salon_id)
        if current is None:
            # RDV inexistant **ou** hors salon : indiscernables (§11.2).
            raise AppointmentNotFound("Rendez-vous introuvable.")

        updated = self._appointments.mark_arrived(
            appointment_id, salon_id, now=self._clock()
        )
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.APPOINTMENT_ARRIVED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_APPOINTMENT,
                entity_id=appointment_id,
                metadata={},
            )
        )
        return updated


class StartAppointmentService:
    """Démarre la prestation d'un RDV `CONFIRMED` du salon (#150).

    Exige l'arrivée déjà pointée (`AppointmentArrivalRequired` sinon) **et**
    une coiffeuse déjà assignée (`AppointmentHairdresserRequired` sinon) —
    une prestation « en cours » sans arrivée ni coiffeuse n'a pas de sens
    métier. Ces préconditions sont vérifiées **ici**, avant l'écriture.
    """

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        audit_log: AuditLog,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._appointments = appointment_repository
        self._audit_log = audit_log
        self._clock = clock if clock is not None else _utc_now

    def execute(
        self, appointment_id: uuid.UUID, salon_id: uuid.UUID, actor_id: uuid.UUID
    ) -> Appointment:
        current = self._appointments.get_in_salon(appointment_id, salon_id)
        if current is None:
            # RDV inexistant **ou** hors salon : indiscernables (§11.2).
            raise AppointmentNotFound("Rendez-vous introuvable.")
        if current.arrived_at is None:
            raise AppointmentArrivalRequired(
                "L'arrivée de la cliente doit être enregistrée avant de démarrer la prestation."
            )
        if current.hairdresser_id is None:
            raise AppointmentHairdresserRequired(
                "Une coiffeuse doit être assignée avant de démarrer la prestation."
            )

        updated = self._appointments.mark_started(
            appointment_id, salon_id, now=self._clock()
        )
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.APPOINTMENT_STARTED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_APPOINTMENT,
                entity_id=appointment_id,
                metadata={},
            )
        )
        return updated


class ListSalonQueue:
    """Liste la file d'attente **du salon** pour un jour donné (lecture pure, #150).

    Compose `AppointmentRepository.list_queue_details` (RDV `CONFIRMED`/
    `COMPLETED` du jour, noms résolus) et, pour les `COMPLETED` seulement,
    `PaymentRepository.list_paid_appointment_ids` (bulk-lookup, pas de N+1) —
    puis dérive `queue_status` via `domain.queue.finalize_queue_entry`. Aucune
    écriture, aucun audit (cohérent avec les lectures Dashboard #148).
    """

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        payment_repository: PaymentRepository,
    ) -> None:
        self._appointments = appointment_repository
        self._payments = payment_repository

    def execute(
        self, salon_id: uuid.UUID, day: datetime.date
    ) -> tuple[QueueEntry, ...]:
        rows = self._appointments.list_queue_details(salon_id, day=day)
        completed_ids = tuple(
            row.appointment_id
            for row in rows
            if row.status == AppointmentStatus.COMPLETED.value
        )
        paid_ids = self._payments.list_paid_appointment_ids(salon_id, completed_ids)
        return tuple(
            finalize_queue_entry(row, is_paid=row.appointment_id in paid_ids)
            for row in rows
        )


__all__ = [
    "MarkAppointmentArrived",
    "StartAppointmentService",
    "ListSalonQueue",
]
