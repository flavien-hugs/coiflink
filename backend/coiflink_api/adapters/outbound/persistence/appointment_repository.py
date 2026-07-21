"""Adapter sortant : persistance des **rendez-vous** (SQLAlchemy, US-3.7, #21).

Implémente le port `AppointmentRepository` sur une `Session` SQLAlchemy 2.0 et les
modèles ORM `Appointment` / `AppointmentService` (déjà au schéma, migration `0001`).
Seul cet adapter connaît SQLAlchemy ; il mappe les entités de domaine ↔ modèles ORM.

**Cœur de la garantie anti double-réservation** (§8.1) : `create` insère le RDV et
ses lignes de jonction puis `flush` — ce qui déclenche l'INSERT et **toutes** les
contraintes sans committer (le commit est piloté par `get_session`, atomicité de
l'unité de travail). Si la contrainte d'exclusion `ex_appointments_hairdresser_slot`
est violée (course concurrente perdue, SQLSTATE `23P01`), l'`IntegrityError` est
traduite en `SlotAlreadyBooked` (message **neutre**, sans journaliser l'erreur brute
qui peut porter des identifiants). Toute autre `IntegrityError` (FK/CHECK inattendu)
est **relevée telle quelle** — jamais masquée.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.appointment import Appointment, AppointmentToCreate, BookedService
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import SlotAlreadyBooked

# Statuts « actifs » au sens de l'exclusion base (un RDV annulé/absent n'occupe
# plus le créneau) — miroir de la clause `WHERE` de `ex_appointments_hairdresser_slot`.
_ACTIVE_STATUSES = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
)

# Nom de la contrainte d'exclusion anti double-réservation (schéma #3) et SQLSTATE
# PostgreSQL `exclusion_violation` — servent à distinguer la course concurrente.
_EXCLUSION_CONSTRAINT = "ex_appointments_hairdresser_slot"
_EXCLUSION_SQLSTATE = "23P01"


class SqlAppointmentRepository:
    """Dépôt de rendez-vous adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def booked_slots(
        self,
        salon_id: uuid.UUID,
        hairdresser_id: uuid.UUID | None,
        date: datetime.date,
    ) -> tuple[SlotRange, ...]:
        """Créneaux actifs (`PENDING`/`CONFIRMED`) du coiffeur pour la date donnée."""

        stmt = select(models.Appointment).where(
            models.Appointment.salon_id == salon_id,
            models.Appointment.appointment_date == date,
            models.Appointment.status.in_(_ACTIVE_STATUSES),
        )
        if hairdresser_id is None:
            stmt = stmt.where(models.Appointment.hairdresser_id.is_(None))
        else:
            stmt = stmt.where(models.Appointment.hairdresser_id == hairdresser_id)
        return tuple(
            SlotRange(date=row.appointment_date, start=row.start_time, end=row.end_time)
            for row in self._session.scalars(stmt).all()
        )

    def create(self, appointment: AppointmentToCreate) -> Appointment:
        """Insère le RDV + ses jonctions ; traduit la violation d'exclusion en conflit."""

        row = models.Appointment(
            salon_id=appointment.salon_id,
            client_id=appointment.client_id,
            hairdresser_id=appointment.hairdresser_id,
            appointment_date=appointment.date,
            start_time=appointment.start_time,
            end_time=appointment.end_time,
            status=appointment.status,
            client_note=appointment.client_note,
        )
        self._session.add(row)
        # `flush` matérialise l'id du RDV (nécessaire aux jonctions) et déclenche la
        # contrainte d'exclusion — sans committer.
        try:
            self._session.flush()
            for service in appointment.services:
                self._session.add(
                    models.AppointmentService(
                        appointment_id=row.id,
                        service_id=service.service_id,
                        salon_id=appointment.salon_id,
                        price_at_booking=service.price_at_booking,
                    )
                )
            self._session.flush()
        except IntegrityError as exc:
            if _is_exclusion_violation(exc):
                # Course concurrente perdue : rollback puis erreur de domaine neutre
                # (l'`IntegrityError` brute n'est jamais journalisée).
                self._session.rollback()
                raise SlotAlreadyBooked(
                    "Ce créneau vient d'être réservé pour ce coiffeur."
                ) from exc
            raise

        self._session.refresh(row)
        return _to_domain(row, appointment.services)


def _is_exclusion_violation(exc: IntegrityError) -> bool:
    """Vrai si l'`IntegrityError` provient de la contrainte d'exclusion anti-doublon.

    Inspecte le driver psycopg (`orig`) : SQLSTATE `23P01` (*exclusion_violation*) ou
    nom de contrainte `ex_appointments_hairdresser_slot`. On ne masque **que** cette
    violation : toute autre erreur d'intégrité doit remonter.
    """

    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    if getattr(orig, "sqlstate", None) == _EXCLUSION_SQLSTATE:
        return True
    diag = getattr(orig, "diag", None)
    if diag is not None and getattr(diag, "constraint_name", None) == _EXCLUSION_CONSTRAINT:
        return True
    return _EXCLUSION_CONSTRAINT in str(orig)


def _to_domain(
    row: models.Appointment, services: tuple[BookedService, ...]
) -> Appointment:
    return Appointment(
        id=row.id,
        salon_id=row.salon_id,
        client_id=row.client_id,
        hairdresser_id=row.hairdresser_id,
        date=row.appointment_date,
        start_time=row.start_time,
        end_time=row.end_time,
        status=row.status,
        client_note=row.client_note,
        created_at=row.created_at,
        services=services,
    )


__all__ = ["SqlAppointmentRepository"]
