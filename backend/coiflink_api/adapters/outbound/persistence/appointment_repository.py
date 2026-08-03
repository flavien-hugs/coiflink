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
import decimal
import uuid
from collections.abc import Mapping

from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.appointment import (
    Appointment,
    AppointmentToCreate,
    AppointmentUpdate,
    BookedService,
)
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.client_segments import ClientVisitProfile
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import (
    AppointmentNotCancellable,
    AppointmentNotModifiable,
    InvalidAppointmentTransition,
    SlotAlreadyBooked,
)
from coiflink_api.domain.service_demand import ServiceDemand

# Précision de quantification des montants agrégés : le centime (miroir de la
# colonne `NUMERIC(12,2)`), en `Decimal` — jamais un flottant.
_AMOUNT_QUANTUM = decimal.Decimal("0.01")

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
        *,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> tuple[SlotRange, ...]:
        """Créneaux actifs (`PENDING`/`CONFIRMED`) du coiffeur pour la date donnée.

        `exclude_appointment_id` retire un RDV du calcul (modification #23) : sans
        cette exclusion, le RDV en cours de re-planification verrait son **propre**
        créneau comme occupé et un déplacement légitime serait faussement rejeté.
        """

        stmt = select(models.Appointment).where(
            models.Appointment.salon_id == salon_id,
            models.Appointment.appointment_date == date,
            models.Appointment.status.in_(_ACTIVE_STATUSES),
        )
        if hairdresser_id is None:
            stmt = stmt.where(models.Appointment.hairdresser_id.is_(None))
        else:
            stmt = stmt.where(models.Appointment.hairdresser_id == hairdresser_id)
        if exclude_appointment_id is not None:
            stmt = stmt.where(models.Appointment.id != exclude_appointment_id)
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

    def get_owned(
        self, appointment_id: uuid.UUID, client_id: uuid.UUID
    ) -> Appointment | None:
        """Charge le RDV `(id, client_id)` et ses prestations, ou `None`.

        Le filtre porte sur `id` **et** `client_id` : un RDV d'autrui est
        indiscernable d'un identifiant inexistant (aucun oracle, §11.2).
        """

        row = self._session.scalar(
            select(models.Appointment).where(
                models.Appointment.id == appointment_id,
                models.Appointment.client_id == client_id,
            )
        )
        if row is None:
            return None
        return _to_domain(row, self._load_services(appointment_id))

    def update(
        self, appointment_id: uuid.UUID, changes: AppointmentUpdate
    ) -> Appointment:
        """Re-planifie le RDV (UPDATE conditionnel sur statut) + remplace ses jonctions.

        Le `WHERE ... status IN (actifs)` ré-affirme le verrou d'état **au moment de
        l'écriture** (garde TOCTOU) : si le RDV est passé terminal entre-temps,
        aucune ligne n'est affectée → `AppointmentNotModifiable`. La colonne générée
        `slot` se recalcule et l'exclusion base arbitre toute collision de créneau.
        """

        row = self._session.scalar(
            select(models.Appointment).where(
                models.Appointment.id == appointment_id,
                models.Appointment.status.in_(_ACTIVE_STATUSES),
            )
        )
        if row is None:
            # RDV disparu ou statut passé terminal (course #25) : verrou ré-affirmé.
            raise AppointmentNotModifiable("Ce rendez-vous n'est plus modifiable.")

        try:
            row.appointment_date = changes.date
            row.start_time = changes.start_time
            row.end_time = changes.end_time
            row.hairdresser_id = changes.hairdresser_id
            row.client_note = changes.client_note
            # Remplacement des prestations (durée/prix figé recapturés) : on supprime
            # les jonctions existantes puis on ré-insère celles de la cible, dans la
            # même unité de travail. Le flush déclenche la contrainte d'exclusion.
            self._session.execute(
                delete(models.AppointmentService).where(
                    models.AppointmentService.appointment_id == appointment_id
                )
            )
            for service in changes.services:
                self._session.add(
                    models.AppointmentService(
                        appointment_id=appointment_id,
                        service_id=service.service_id,
                        salon_id=row.salon_id,
                        price_at_booking=service.price_at_booking,
                    )
                )
            self._session.flush()
        except IntegrityError as exc:
            if _is_exclusion_violation(exc):
                # Collision/course perdue : rollback puis erreur de domaine neutre
                # (l'`IntegrityError` brute n'est jamais journalisée).
                self._session.rollback()
                raise SlotAlreadyBooked(
                    "Ce créneau vient d'être réservé pour ce coiffeur."
                ) from exc
            raise

        self._session.refresh(row)
        return _to_domain(row, changes.services)

    def cancel(
        self, appointment_id: uuid.UUID, *, reason: str | None
    ) -> Appointment:
        """Annule le RDV (UPDATE conditionnel sur statut) et pose son motif (#24).

        Le `WHERE ... status IN (actifs)` ré-affirme le verrou d'état **au moment de
        l'écriture** (garde TOCTOU) : si le RDV est inexistant ou passé terminal
        entre-temps, aucune ligne active ne correspond → `AppointmentNotCancellable`.
        Pose `status = 'CANCELLED'` et `cancellation_reason = reason`. Les jonctions
        `appointment_services` sont **conservées** (historique/CA futur). Le RDV quitte
        l'ensemble actif : le créneau **se libère** (exclusion base + `booked_slots`).
        `updated_at` (`onupdate`) se rafraîchit automatiquement.
        """

        row = self._session.scalar(
            select(models.Appointment).where(
                models.Appointment.id == appointment_id,
                models.Appointment.status.in_(_ACTIVE_STATUSES),
            )
        )
        if row is None:
            # RDV disparu ou statut déjà terminal (déjà annulé, terminé, absent, ou
            # course #25) : le verrou est ré-affirmé, aucune annulation possible.
            raise AppointmentNotCancellable(
                "Ce rendez-vous ne peut plus être annulé."
            )

        row.status = AppointmentStatus.CANCELLED.value
        row.cancellation_reason = reason
        # `flush` matérialise l'UPDATE (commit piloté par `get_session`). L'annulation
        # **libère** un créneau : elle ne peut pas violer l'exclusion anti-doublon.
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, self._load_services(appointment_id))

    def get_in_salon(
        self, appointment_id: uuid.UUID, salon_id: uuid.UUID
    ) -> Appointment | None:
        """Charge le RDV `(id, salon_id)` et ses prestations, ou `None` (US-3.4 #25).

        Le filtre porte sur `id` **et** `salon_id` : un RDV d'un autre salon est
        indiscernable d'un identifiant inexistant (aucun oracle, §11.2). Analogue
        salon-scopé de `get_owned` (qui filtre `client_id`).
        """

        row = self._session.scalar(
            select(models.Appointment).where(
                models.Appointment.id == appointment_id,
                models.Appointment.salon_id == salon_id,
            )
        )
        if row is None:
            return None
        return _to_domain(row, self._load_services(appointment_id))

    def set_status(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        expected_current: str,
        target: str,
        reason: str | None = None,
    ) -> Appointment:
        """Transition de statut gérant (UPDATE conditionnel salon + statut, #25).

        Le `WHERE ... salon_id = :salon_id AND status = :expected_current`
        ré-affirme la portée **et** le verrou d'état **au moment de l'écriture**
        (garde TOCTOU) : si le RDV a disparu, sort du salon ou change de statut
        entre la lecture et l'écriture, aucune ligne ne correspond →
        `InvalidAppointmentTransition`. Pose `status = :target` (et
        `cancellation_reason` **uniquement** sur `→ CANCELLED`) ; `updated_at`
        (`onupdate`) se rafraîchit automatiquement. Une transition ne peut pas
        violer l'exclusion base (elle libère le créneau ou conserve le même).
        """

        row = self._session.scalar(
            select(models.Appointment).where(
                models.Appointment.id == appointment_id,
                models.Appointment.salon_id == salon_id,
                models.Appointment.status == expected_current,
            )
        )
        if row is None:
            # RDV disparu, hors salon, ou statut changé (course avec #24) : le verrou
            # et la portée sont ré-affirmés — aucune transition « fantôme ».
            raise InvalidAppointmentTransition(
                "Cette transition de statut n'est pas autorisée."
            )

        row.status = target
        # Le motif n'est posé que sur un refus/annulation gérant (`→ CANCELLED`) :
        # les autres cibles ne touchent pas `cancellation_reason` (patron #24).
        if target == AppointmentStatus.CANCELLED.value:
            row.cancellation_reason = reason
        # `flush` matérialise l'UPDATE (commit piloté par `get_session`).
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row, self._load_services(appointment_id))

    def assign_hairdresser(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        hairdresser_id: uuid.UUID | None,
    ) -> Appointment:
        """(Dés)assigne un coiffeur à un RDV actif du salon (#25).

        UPDATE conditionnel sur le salon **et** le statut **actif**
        (`PENDING`/`CONFIRMED`) : un RDV disparu, hors salon ou terminal n'affecte
        aucune ligne → `InvalidAppointmentTransition` (créneau libéré, assignation
        non pertinente). L'assignation d'un coiffeur déjà pris sur le créneau viole
        l'exclusion base (`23P01`) → `SlotAlreadyBooked` (rollback + message neutre,
        l'`IntegrityError` brute n'est jamais journalisée). Une désassignation
        (`hairdresser_id = None`) retire le RDV de la portée de l'exclusion.
        """

        row = self._session.scalar(
            select(models.Appointment).where(
                models.Appointment.id == appointment_id,
                models.Appointment.salon_id == salon_id,
                models.Appointment.status.in_(_ACTIVE_STATUSES),
            )
        )
        if row is None:
            # RDV disparu, hors salon, ou terminal : l'assignation n'a plus de sens.
            raise InvalidAppointmentTransition(
                "Ce rendez-vous n'accepte plus d'assignation de coiffeur."
            )

        row.hairdresser_id = hairdresser_id
        try:
            self._session.flush()
        except IntegrityError as exc:
            if _is_exclusion_violation(exc):
                # Coiffeur déjà pris sur ce créneau : rollback puis erreur neutre
                # (l'`IntegrityError` brute n'est jamais journalisée).
                self._session.rollback()
                raise SlotAlreadyBooked(
                    "Ce créneau vient d'être réservé pour ce coiffeur."
                ) from exc
            raise

        self._session.refresh(row)
        return _to_domain(row, self._load_services(appointment_id))

    def list_for_client(
        self,
        client_id: uuid.UUID,
        statuses: tuple[str, ...] | None = None,
        *,
        newest_first: bool = False,
    ) -> tuple[Appointment, ...]:
        """RDV du client (avec prestations), filtrés par statut, triés par date/heure.

        `newest_first=True` inverse l'ordre (du plus récent au plus ancien) pour
        l'historique client (#30) ; par défaut, ordre chronologique croissant (RDV à
        venir de `GET /appointments`). L'index `ix_appointments_client_id` couvre le
        filtre `client_id`.
        """

        stmt = select(models.Appointment).where(
            models.Appointment.client_id == client_id
        )
        if statuses is not None:
            stmt = stmt.where(models.Appointment.status.in_(statuses))
        if newest_first:
            stmt = stmt.order_by(
                models.Appointment.appointment_date.desc(),
                models.Appointment.start_time.desc(),
            )
        else:
            stmt = stmt.order_by(
                models.Appointment.appointment_date.asc(),
                models.Appointment.start_time.asc(),
            )
        rows = self._session.scalars(stmt).all()
        return tuple(_to_domain(row, self._load_services(row.id)) for row in rows)

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        """RDV du salon dans `[date_from, date_to]`, filtrés par statut, triés (#26).

        L'isolation §11.2 est ré-affirmée **en SQL** (`salon_id = :salon_id`) : la
        lecture ne peut jamais renvoyer un RDV d'un autre salon, quelle que soit la
        garde HTTP. La plage est **inclusive** aux deux bornes. L'index
        `ix_appointments_salon_id (salon_id, appointment_date)` couvre le filtre.
        """

        stmt = select(models.Appointment).where(
            models.Appointment.salon_id == salon_id,
            models.Appointment.appointment_date >= date_from,
            models.Appointment.appointment_date <= date_to,
        )
        if statuses is not None:
            stmt = stmt.where(models.Appointment.status.in_(statuses))
        stmt = stmt.order_by(
            models.Appointment.appointment_date.asc(),
            models.Appointment.start_time.asc(),
        )
        rows = self._session.scalars(stmt).all()
        return tuple(_to_domain(row, self._load_services(row.id)) for row in rows)

    def list_for_hairdresser(
        self,
        hairdresser_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        """RDV assignés au coiffeur dans `[date_from, date_to]`, filtrés, triés (#27).

        L'isolation « son planning » (§11.2) est imposée **en SQL**
        (`hairdresser_id = :hairdresser_id`) : la lecture ne peut jamais renvoyer un
        RDV d'un autre coiffeur, un RDV **non assigné** (`hairdresser_id IS NULL`, exclu
        par l'égalité) ni un RDV d'un autre salon, quelle que soit la garde HTTP — le
        `hairdresser_id` provenant du `Principal`. La plage est **inclusive** aux deux
        bornes ; la lecture est bornée (≤ 42 j, un seul coiffeur → volume faible au MVP).
        """

        stmt = select(models.Appointment).where(
            models.Appointment.hairdresser_id == hairdresser_id,
            models.Appointment.appointment_date >= date_from,
            models.Appointment.appointment_date <= date_to,
        )
        if statuses is not None:
            stmt = stmt.where(models.Appointment.status.in_(statuses))
        stmt = stmt.order_by(
            models.Appointment.appointment_date.asc(),
            models.Appointment.start_time.asc(),
        )
        rows = self._session.scalars(stmt).all()
        return tuple(_to_domain(row, self._load_services(row.id)) for row in rows)

    def count_by_status_for_day(
        self, salon_id: uuid.UUID, day: datetime.date
    ) -> Mapping[str, int]:
        """Décompte `GROUP BY status` des RDV du salon pour `day` (US-6.1 #39).

        L'isolation §11.2 est ré-affirmée **en SQL** (`salon_id = :salon_id`) : le
        comptage ne peut jamais inclure un RDV d'un autre salon. La lecture **agrège en
        base** (`func.count()` + `group_by`) et ne rapatrie **aucune** ligne de RDV ni
        PII — seulement `(status, count)`. Un statut sans RDV du jour est **absent** de
        la map renvoyée (le domaine le complète à `0`). L'index `ix_appointments_salon_id
        (salon_id, appointment_date)` couvre le filtre.
        """

        rows = self._session.execute(
            select(models.Appointment.status, func.count())
            .where(
                models.Appointment.salon_id == salon_id,
                models.Appointment.appointment_date == day,
            )
            .group_by(models.Appointment.status)
        ).all()
        return {status: count for status, count in rows}

    def demand_by_service(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> tuple[ServiceDemand, ...]:
        """Agrège volume + revenu **par prestation** du salon (US-6.3 #41).

        `GROUP BY service_id` en base : `COUNT(*)` = volume (occurrences réalisées),
        `COALESCE(SUM(price_at_booking), 0)` = revenu (prix figés). Joint
        `appointment_services` → `appointments` (statut/salon/date) puis `services` par
        la **composite** `(salon_id, service_id)` (appartenance salon du libellé,
        résoluble même soft-deleté). L'isolation §11.2 est ré-affirmée **en SQL**
        (`WHERE appointments.salon_id`) ; le filtre `status IN statuses`
        (`REVENUE_STATUSES` côté cas d'usage) exclut « annulés » par construction. La
        lecture ne rapatrie **aucune** ligne ni PII — seulement les tuples agrégés.
        Ordre **non garanti** (le domaine ordonne). Les index `ix_appointments_salon_id`
        et `ix_appointment_services_service_id` couvrent la requête. Lecture pure
        (aucun `flush`).
        """

        stmt = (
            select(
                models.AppointmentService.service_id,
                models.Service.name,
                func.count().label("volume"),
                func.coalesce(
                    func.sum(models.AppointmentService.price_at_booking), 0
                ).label("revenue"),
            )
            .join(
                models.Appointment,
                models.Appointment.id == models.AppointmentService.appointment_id,
            )
            .join(
                models.Service,
                (models.Service.id == models.AppointmentService.service_id)
                & (models.Service.salon_id == models.AppointmentService.salon_id),
            )
            .where(
                models.Appointment.salon_id == salon_id,
                models.Appointment.status.in_(statuses),
            )
            .group_by(models.AppointmentService.service_id, models.Service.name)
        )
        if date_from is not None:
            stmt = stmt.where(models.Appointment.appointment_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(models.Appointment.appointment_date <= date_to)

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

    def segment_active_clients(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> tuple[ClientVisitProfile, ...]:
        """Agrège le profil de visite **par client** du salon (US-6.4 #42).

        `GROUP BY client_id` en base : `MIN(appointment_date)` = première visite au
        salon ; deux `SUM(CASE …)` filtrés = nombre de visites **dans**
        `[date_from, date_to]` et **strictement avant** `date_from`. Le `client_id` est
        **groupé mais jamais sélectionné** (anti-oracle §11.1/§11.3) : ni l'identité, ni
        le nombre exact de visites d'un compte ne quittent la base — seulement des
        profils agrégés **sans PII**. Ne comptent que les RDV dont `status ∈ statuses`
        (le cas d'usage impose `HISTORY_STATUSES` — RDV `COMPLETED`, « annulés exclus »
        §8.1 par construction). L'isolation §11.2 est ré-affirmée **en SQL**
        (`WHERE appointments.salon_id`), en défense en profondeur de la garde HTTP :
        jamais un client d'un autre salon. La lecture ne rapatrie **aucune** ligne de
        RDV ni PII — seulement `(first_visit, visits_in_period, visits_before)` par
        client. Ordre **non garanti** (le domaine classe). L'index
        `ix_appointments_salon_id (salon_id, appointment_date)` couvre la requête.
        Lecture pure (aucun `flush`).
        """

        in_period = func.sum(
            case(
                (
                    models.Appointment.appointment_date.between(date_from, date_to),
                    1,
                ),
                else_=0,
            )
        )
        before = func.sum(
            case(
                (models.Appointment.appointment_date < date_from, 1),
                else_=0,
            )
        )
        stmt = (
            select(
                func.min(models.Appointment.appointment_date).label("first_visit"),
                func.coalesce(in_period, 0).label("visits_in_period"),
                func.coalesce(before, 0).label("visits_before"),
            )
            .where(
                models.Appointment.salon_id == salon_id,
                models.Appointment.status.in_(statuses),
            )
            # `client_id` est groupé (agrégation par compte) mais **jamais** sélectionné
            # (anti-oracle §11.3) : l'identité ne quitte pas la base.
            .group_by(models.Appointment.client_id)
        )

        rows = self._session.execute(stmt).all()
        return tuple(
            ClientVisitProfile(
                first_visit=row.first_visit,
                visits_in_period=int(row.visits_in_period),
                visits_before=int(row.visits_before),
            )
            for row in rows
        )

    def _load_services(
        self, appointment_id: uuid.UUID
    ) -> tuple[BookedService, ...]:
        """Prestations réservées d'un RDV (avec leur prix figé)."""

        stmt = select(models.AppointmentService).where(
            models.AppointmentService.appointment_id == appointment_id
        )
        return tuple(
            BookedService(
                service_id=row.service_id, price_at_booking=row.price_at_booking
            )
            for row in self._session.scalars(stmt).all()
        )


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
