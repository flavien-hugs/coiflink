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

    def cancel(
        self, appointment_id: uuid.UUID, *, reason: str | None
    ) -> Appointment:
        """Annule le RDV (transition vers `CANCELLED`) et pose son motif (#24).

        Écriture **conditionnée au statut actif** (`PENDING`/`CONFIRMED`) via un
        UPDATE conditionnel : si aucune ligne active ne correspond (RDV inexistant
        ou statut passé terminal entre la lecture et l'écriture — garde TOCTOU), lève
        `domain.errors.AppointmentNotCancellable`. Pose `status = 'CANCELLED'` et
        `cancellation_reason = reason` (`reason` déjà normalisé, `None` = pas de
        motif) ; `updated_at` se rafraîchit automatiquement. Les jonctions
        `appointment_services` (prestations + prix figé) sont **conservées** (utiles
        à l'historique/CA futur). L'annulation **libère** le créneau (le RDV quitte
        l'ensemble actif de l'exclusion base et de `booked_slots`) : elle ne peut pas
        violer la contrainte d'exclusion. Retourne l'entité relue.
        """
        ...

    def get_in_salon(
        self, appointment_id: uuid.UUID, salon_id: uuid.UUID
    ) -> Appointment | None:
        """Charge le RDV **et** ses `BookedService` ssi il appartient à `salon_id`
        (isolation §11.2 imposée en SQL, US-3.4 #25 — analogue salon-scopé de
        `get_owned`).

        Le filtre porte sur `id` **et** `salon_id` : un RDV d'un autre salon est
        indiscernable d'un identifiant inexistant. Retourne `None` dans les deux
        cas — le cas d'usage lève alors un `404` générique **après** la portée
        (aucun oracle d'existence). Jamais un RDV hors salon.
        """
        ...

    def set_status(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        expected_current: str,
        target: str,
        reason: str | None = None,
    ) -> Appointment:
        """Fait passer le RDV vers `target` (transition de statut gérant, US-3.4 #25).

        Écriture **conditionnée** au salon **et** au statut courant attendu
        (`WHERE id = :id AND salon_id = :salon_id AND status = :expected_current`) :
        si aucune ligne ne correspond (RDV disparu, hors salon, ou statut changé
        entre la lecture et l'écriture — garde TOCTOU), lève
        `domain.errors.InvalidAppointmentTransition`. Pose `status = :target` et,
        **uniquement** si `target = 'CANCELLED'`, `cancellation_reason = :reason`
        (déjà normalisé, `None` = pas de motif). `updated_at` (`onupdate`) se
        rafraîchit automatiquement. Une transition de statut **ne peut pas** violer
        l'exclusion base : elle retire le RDV de l'ensemble actif (→ terminal) ou le
        maintient sur le **même** créneau/coiffeur (`PENDING → CONFIRMED`). Retourne
        l'entité relue (avec ses `BookedService`, conservés).
        """
        ...

    def assign_hairdresser(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        hairdresser_id: uuid.UUID | None,
    ) -> Appointment:
        """(Dés)assigne un coiffeur à un RDV **actif** du salon (US-3.4 #25).

        Écriture **conditionnée** au salon **et** au statut **actif**
        (`WHERE id = :id AND salon_id = :salon_id AND status IN (PENDING, CONFIRMED)`) :
        si aucune ligne active ne correspond (RDV disparu, hors salon, ou terminal —
        créneau libéré, assignation non pertinente), lève
        `domain.errors.InvalidAppointmentTransition`. Pose `hairdresser_id`
        (`None` = désassignation). Lève `domain.errors.SlotAlreadyBooked` si la
        contrainte d'exclusion base rejette l'assignation (le coiffeur est déjà pris
        sur ce créneau) — une désassignation ne peut jamais la violer. Retourne
        l'entité relue.
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
