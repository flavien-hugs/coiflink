"""Port de persistance des **rendez-vous** (`Protocol`, US-3.7 #21, US-3.2 #23).

Les cas d'usage `application/appointments.py` déclarent ici leurs besoins de
lecture (créneaux occupés, RDV du client) et d'écriture (création & modification
transactionnelles) ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/appointment_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Garantie anti double-réservation** (§8.1) : `create` **et** `update` **doivent**
lever `SlotAlreadyBooked` quand la contrainte d'exclusion base
`ex_appointments_hairdresser_slot` rejette l'écriture (course concurrente perdue),
en distinguant cette violation de toute autre erreur d'intégrité. La contrainte
d'exclusion PostgreSQL s'applique aussi bien aux `INSERT` qu'aux `UPDATE`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Protocol

from coiflink_api.domain.appointment import (
    Appointment,
    AppointmentToCreate,
    AppointmentUpdate,
)
from coiflink_api.domain.availability import SlotRange


class AppointmentRepository(Protocol):
    """Contrat de persistance des rendez-vous d'un salon."""

    def booked_slots(
        self,
        salon_id: uuid.UUID,
        hairdresser_id: uuid.UUID | None,
        date: datetime.date,
        *,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> tuple[SlotRange, ...]:
        """Créneaux **actifs** (`status IN (PENDING, CONFIRMED)`) du coiffeur pour `date`.

        Alimente le moteur de disponibilité. Le filtre porte sur `salon_id`,
        `hairdresser_id` (ou `IS NULL` si `None`) et la date : un RDV
        `CANCELLED`/`NO_SHOW`/`COMPLETED` n'occupe plus le créneau (hors clause
        `WHERE` de l'exclusion, cohérent avec le schéma).

        `exclude_appointment_id` (optionnel, additif — rétro-compatible #21) exclut
        un RDV du calcul : indispensable à la **modification** (#23), sans quoi le
        propre créneau actuel du RDV apparaîtrait « occupé » et un déplacement
        légitime (ou un simple changement de note) serait faussement rejeté.
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

    def get_owned(
        self, appointment_id: uuid.UUID, client_id: uuid.UUID
    ) -> Appointment | None:
        """Charge le RDV **et** ses `BookedService` si — et seulement si — il
        appartient à `client_id` (isolation §11.2 imposée en SQL).

        Retourne `None` quand le RDV n'existe pas **ou** n'appartient pas au client :
        les deux cas sont **indiscernables** (le cas d'usage lève alors un `404`
        générique, aucun oracle d'existence). Jamais de RDV d'autrui.
        """
        ...

    def update(
        self, appointment_id: uuid.UUID, changes: AppointmentUpdate
    ) -> Appointment:
        """Re-planifie le RDV et **remplace** ses lignes `appointment_services` dans
        **une** transaction (sémantique *replace*, #23).

        L'écriture est conditionnée au statut **actif** (`PENDING`/`CONFIRMED`) :
        si aucune ligne active ne correspond (statut passé terminal entre la lecture
        et l'écriture — garde TOCTOU), lève `domain.errors.AppointmentNotModifiable`.
        Lève `domain.errors.SlotAlreadyBooked` sur violation de l'exclusion base
        (course/collision avec un autre RDV actif du même coiffeur). Toute autre
        erreur d'intégrité est relevée telle quelle.
        """
        ...

    def list_for_client(
        self,
        client_id: uuid.UUID,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        """Liste les RDV **du client** (`client_id`), avec leurs `BookedService`.

        Ne renvoie **que** les données du client demandeur (§11.2/§11.3) — jamais
        l'identité d'un tiers. `statuses` restreint la lecture (p. ex. aux états
        actifs `PENDING`/`CONFIRMED`) ; `None` ne filtre pas sur le statut. Tri
        chronologique (date puis heure de début).
        """
        ...


__all__ = ["AppointmentRepository"]
