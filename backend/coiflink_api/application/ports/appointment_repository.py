"""Port de persistance des **rendez-vous** (`Protocol`, US-3.7, #21).

Les cas d'usage `application/appointments.py` déclarent ici leurs besoins de
lecture (créneaux occupés) et d'écriture (création transactionnelle) ;
l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/appointment_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Garantie anti double-réservation** (§8.1) : `create` **doit** lever
`SlotAlreadyBooked` quand la contrainte d'exclusion base
`ex_appointments_hairdresser_slot` rejette l'insertion (course concurrente perdue),
en distinguant cette violation de toute autre erreur d'intégrité.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Protocol

from coiflink_api.domain.appointment import Appointment, AppointmentToCreate
from coiflink_api.domain.availability import SlotRange


class AppointmentRepository(Protocol):
    """Contrat de persistance des rendez-vous d'un salon."""

    def booked_slots(
        self,
        salon_id: uuid.UUID,
        hairdresser_id: uuid.UUID | None,
        date: datetime.date,
    ) -> tuple[SlotRange, ...]:
        """Créneaux **actifs** (`status IN (PENDING, CONFIRMED)`) du coiffeur pour `date`.

        Alimente le moteur de disponibilité. Le filtre porte sur `salon_id`,
        `hairdresser_id` (ou `IS NULL` si `None`) et la date : un RDV
        `CANCELLED`/`NO_SHOW`/`COMPLETED` n'occupe plus le créneau (hors clause
        `WHERE` de l'exclusion, cohérent avec le schéma).
        """
        ...

    def create(self, appointment: AppointmentToCreate) -> Appointment:
        """Insère le RDV **et** ses lignes `appointment_services` dans **une** transaction.

        Lève `domain.errors.SlotAlreadyBooked` si la contrainte d'exclusion base est
        violée (course concurrente) — la seconde insertion perd et **rien** n'est
        persisté (rollback de l'unité de travail). Toute autre erreur d'intégrité est
        relevée telle quelle (jamais masquée).
        """
        ...


__all__ = ["AppointmentRepository"]
