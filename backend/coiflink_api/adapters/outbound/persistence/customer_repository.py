"""Adapter sortant : persistance des **fiches clients** (SQLAlchemy, US-4.1, #28).

Implémente le port `CustomerRepository` sur une `Session` SQLAlchemy 2.0 et le
modèle ORM `models.CustomerProfile` (table `customer_profiles` du schéma `0001`,
colonne `gender` ajoutée par `0005`). Seul cet adapter connaît SQLAlchemy ; il
mappe les entités de domaine ↔ modèles ORM et retraduit les violations de
contrainte en **erreurs de domaine** (jamais de fuite d'un détail SQLAlchemy).

Comme `SqlServiceRepository`, les écritures sont `flush`ées **sans commit** : le
commit (ou rollback) est piloté par la dépendance de session (`get_session`), ce
qui permet à l'entrée d'audit (`SqlAuditLog`) d'être committée dans la **même**
unité de travail que la mutation métier (atomicité §11.4).

**Isolation §11.2 au niveau du dépôt** : toute lecture d'une fiche existante
filtre sur le couple `(salon_id, id)` — impossible de lire la fiche d'un autre
salon même si l'`id` est deviné (miroir de `SqlServiceRepository`). C'est la
défense en profondeur derrière `require_salon_scope`.

**Refus de doublon garanti en base** : la violation de l'index unique partiel
`uq_customer_profiles_salon_phone` (course concurrente perdue) est traduite en
`CustomerAlreadyExists` (message neutre, sans rappeler le numéro). Toute autre
`IntegrityError` (FK/CHECK inattendu) est **relevée telle quelle** — jamais masquée.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    escape_like,
)
from coiflink_api.domain.customer import Customer, CustomerFilter, CustomerToCreate
from coiflink_api.domain.errors import CustomerAlreadyExists, CustomerNotFound
from coiflink_api.domain.visit import CustomerVisit, VisitService, visit_total

# Index unique partiel garantissant l'unicité du téléphone **dans un salon** (0005).
_PHONE_UNIQUE_INDEX = "uq_customer_profiles_salon_phone"

# SQLSTATE `23505` — *unique_violation* (PostgreSQL).
_UNIQUE_SQLSTATE = "23505"


class SqlCustomerRepository:
    """Dépôt de fiches clients adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, customer: CustomerToCreate) -> Customer:
        """Insère la fiche (`user_id` laissé `NULL` — client walk-in, #28)."""

        row = models.CustomerProfile(
            salon_id=customer.salon_id,
            full_name=customer.full_name,
            phone=customer.phone,
            gender=customer.gender,
            notes=customer.notes,
        )
        self._session.add(row)
        try:
            # `flush` déclenche l'INSERT (et les contraintes) sans committer.
            self._session.flush()
        except IntegrityError as exc:
            if _is_phone_duplicate(exc):
                # Course concurrente perdue : rollback puis erreur de domaine
                # neutre (l'`IntegrityError` brute n'est jamais journalisée, elle
                # peut porter le numéro soumis).
                self._session.rollback()
                raise CustomerAlreadyExists(
                    "Une fiche existe déjà pour ce numéro dans ce salon."
                ) from exc
            raise

        # Recharge les valeurs générées côté serveur (id, total_visits, timestamps).
        self._session.refresh(row)
        return _to_domain(row)

    def find_by_id(
        self, salon_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Customer | None:
        """Charge la fiche `(salon_id, customer_id)` — filtre d'isolation §11.2."""

        stmt = select(models.CustomerProfile).where(
            models.CustomerProfile.salon_id == salon_id,
            models.CustomerProfile.id == customer_id,
        )
        row = self._session.scalar(stmt)
        return _to_domain(row) if row is not None else None

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        filter: CustomerFilter,
        limit: int,
        offset: int,
    ) -> tuple[Customer, ...]:
        """Page **filtrée** de fiches du salon, les plus récentes d'abord (SQL)."""

        stmt = (
            select(models.CustomerProfile)
            .where(*self._filter_clauses(salon_id, filter))
            .order_by(
                models.CustomerProfile.created_at.desc(),
                models.CustomerProfile.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(_to_domain(row) for row in self._session.scalars(stmt).all())

    def count_for_salon(self, salon_id: uuid.UUID, *, filter: CustomerFilter) -> int:
        """Nombre total de fiches du salon **sous le même filtre** (pagination)."""

        stmt = (
            select(func.count())
            .select_from(models.CustomerProfile)
            .where(*self._filter_clauses(salon_id, filter))
        )
        return int(self._session.scalar(stmt) or 0)

    @staticmethod
    def _filter_clauses(
        salon_id: uuid.UUID, filter: CustomerFilter
    ) -> Sequence[ColumnElement[bool]]:
        """Clauses `WHERE` : `salon_id` inconditionnel + critères présents (ET).

        Partagées **à l'identique** par `list_for_salon` et `count_for_salon` pour
        que le `total` corresponde exactement à la page (miroir `SqlPaymentRepository`).
        """

        clauses: list[ColumnElement[bool]] = [models.CustomerProfile.salon_id == salon_id]
        if filter.created_at_from is not None:
            clauses.append(models.CustomerProfile.created_at >= filter.created_at_from)
        if filter.created_at_to is not None:
            clauses.append(models.CustomerProfile.created_at <= filter.created_at_to)
        if filter.gender is not None:
            clauses.append(models.CustomerProfile.gender == filter.gender)
        # Joignabilité SMS (US-7.5, #49) : n'inclut que les fiches ayant un
        # téléphone — une fiche walk-in sans numéro ne peut recevoir de campagne.
        if filter.has_phone:
            clauses.append(models.CustomerProfile.phone.is_not(None))
        if filter.q is not None:
            clauses.append(
                models.CustomerProfile.full_name.ilike(
                    f"%{escape_like(filter.q)}%", escape="\\"
                )
            )
        return clauses

    def phone_exists(self, salon_id: uuid.UUID, phone: str) -> bool:
        """Pré-contrôle d'unicité `(salon_id, phone)` — la garantie reste l'index base."""

        stmt = select(models.CustomerProfile.id).where(
            models.CustomerProfile.salon_id == salon_id,
            models.CustomerProfile.phone == phone,
        )
        return self._session.scalar(stmt) is not None

    def update_notes(
        self, salon_id: uuid.UUID, customer_id: uuid.UUID, notes: str | None
    ) -> Customer:
        """Remplace la note privée de la fiche `(salon_id, customer_id)` (US-4.5, #32).

        Filtre d'isolation §11.2 `(salon_id, id)` : une fiche d'un autre salon est
        indiscernable d'une fiche inexistante → `CustomerNotFound` (mappé `404`
        **après** portée par l'adapter entrant), jamais un oracle. `notes = None`
        efface la note (`notes = NULL`). Seule la colonne `notes` est écrite.
        `flush` sans `commit` : le commit est piloté par `get_session`, ce qui
        rend la mutation atomique avec l'entrée d'audit (patron `SqlServiceRepository`).
        """

        stmt = select(models.CustomerProfile).where(
            models.CustomerProfile.salon_id == salon_id,
            models.CustomerProfile.id == customer_id,
        )
        row = self._session.scalar(stmt)
        if row is None:
            raise CustomerNotFound("Fiche client introuvable.")
        row.notes = notes
        # `flush` déclenche l'UPDATE sans committer (atomicité avec l'audit).
        self._session.flush()
        # Recharge `updated_at` régénéré côté serveur (`onupdate`).
        self._session.refresh(row)
        return _to_domain(row)

    def update(
        self,
        salon_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        full_name: str,
        phone: str | None,
        gender: str | None,
    ) -> Customer:
        """Remplace l'identité de la fiche `(salon_id, customer_id)` (US-4.6, #144).

        Fusion des patrons `update_notes` (résolution `(salon_id, id)` → isolation
        §11.2, `CustomerNotFound` avant l'audit, `flush` sans `commit`) et `create`
        (retraduction de l'`IntegrityError` du doublon de téléphone en
        `CustomerAlreadyExists` — filet de la course concurrente). `phone`/`gender`
        `None` **effacent** le champ ; conserver son propre numéro ne viole pas
        l'index (même ligne). **Seules** les colonnes d'identité sont écrites.
        """

        stmt = select(models.CustomerProfile).where(
            models.CustomerProfile.salon_id == salon_id,
            models.CustomerProfile.id == customer_id,
        )
        row = self._session.scalar(stmt)
        if row is None:
            raise CustomerNotFound("Fiche client introuvable.")
        row.full_name = full_name
        row.phone = phone
        row.gender = gender
        try:
            # `flush` déclenche l'UPDATE (et les contraintes) sans committer.
            self._session.flush()
        except IntegrityError as exc:
            if _is_phone_duplicate(exc):
                # Course concurrente perdue : rollback puis erreur de domaine
                # neutre (l'`IntegrityError` brute n'est jamais journalisée, elle
                # peut porter le numéro soumis).
                self._session.rollback()
                raise CustomerAlreadyExists(
                    "Une fiche existe déjà pour ce numéro dans ce salon."
                ) from exc
            raise
        # Recharge `updated_at` régénéré côté serveur (`onupdate`).
        self._session.refresh(row)
        return _to_domain(row)

    def list_visits(
        self,
        salon_id: uuid.UUID,
        customer_id: uuid.UUID,
        statuses: tuple[str, ...],
    ) -> tuple[CustomerVisit, ...]:
        """RDV `statuses` du compte lié à la fiche `(salon_id, customer_id)`, triés récent d'abord.

        Le lien `customer_profiles.user_id == appointments.client_id` est calculé
        **entièrement en SQL** et **jamais** exposé (anti-oracle ADR-0026). Étapes :

        1. Projette l'`user_id` de la fiche filtrée `(id, salon_id)` (isolation
           §11.2). Fiche introuvable dans le salon **ou** walk-in
           (`user_id IS NULL`) → tuple vide (aucun RDV reliable, pas une erreur).
        2. Charge les RDV `(salon_id, client_id = user_id, status IN statuses)` —
           le `salon_id` est **refiltré** (cloisonnement strict : jamais un RDV du
           même compte dans un autre salon) — joints à leurs prestations
           (`appointment_services`) et libellés (`services.name`), triés `date
           DESC, start_time DESC`. Les lignes plates (une par prestation) sont
           regroupées par RDV, l'ordre des prestations stabilisé par `created_at`
           de la jonction puis `service_id`. **Lecture seule** : aucun flush.
        """

        user_id = self._session.scalar(
            select(models.CustomerProfile.user_id).where(
                models.CustomerProfile.id == customer_id,
                models.CustomerProfile.salon_id == salon_id,
            )
        )
        if user_id is None:
            # Fiche hors salon/inexistante, ou fiche walk-in : aucun RDV reliable.
            # L'`user_id` n'est jamais renvoyé — indiscernable d'une fiche liée
            # sans visite terminée (aucun oracle sur l'existence d'un compte).
            return ()

        stmt = (
            select(
                models.Appointment.id,
                models.Appointment.appointment_date,
                models.Appointment.start_time,
                models.Appointment.end_time,
                models.Appointment.status,
                models.AppointmentService.service_id,
                models.AppointmentService.price_at_booking,
                models.AppointmentService.created_at,
                models.Service.name,
            )
            .join(
                models.AppointmentService,
                models.AppointmentService.appointment_id == models.Appointment.id,
            )
            .join(
                models.Service,
                models.Service.id == models.AppointmentService.service_id,
            )
            .where(
                models.Appointment.salon_id == salon_id,
                models.Appointment.client_id == user_id,
                models.Appointment.status.in_(statuses),
            )
            .order_by(
                models.Appointment.appointment_date.desc(),
                models.Appointment.start_time.desc(),
                models.Appointment.id.desc(),
                models.AppointmentService.created_at.asc(),
                models.AppointmentService.service_id.asc(),
            )
        )

        visits: list[CustomerVisit] = []
        current_id: uuid.UUID | None = None
        current_row: object | None = None
        current_services: list[VisitService] = []

        def _flush() -> None:
            if current_row is None:
                return
            services = tuple(current_services)
            visits.append(
                CustomerVisit(
                    appointment_id=current_row.id,
                    date=current_row.appointment_date,
                    start_time=current_row.start_time,
                    end_time=current_row.end_time,
                    status=current_row.status,
                    services=services,
                    total_amount=visit_total(services),
                )
            )

        for row in self._session.execute(stmt):
            if row.id != current_id:
                _flush()
                current_id = row.id
                current_row = row
                current_services = []
            current_services.append(
                VisitService(
                    service_id=row.service_id,
                    name=row.name,
                    price_at_booking=row.price_at_booking,
                )
            )
        _flush()

        return tuple(visits)


def _is_phone_duplicate(exc: IntegrityError) -> bool:
    """Vrai si l'`IntegrityError` provient de l'index unique `(salon_id, phone)`.

    Inspecte le driver psycopg (`orig`) : SQLSTATE `23505` (*unique_violation*)
    **et** nom de contrainte `uq_customer_profiles_salon_phone`. On ne masque
    **que** cette violation : l'unicité `(salon_id, user_id)`, une FK ou un `CHECK`
    inattendu doivent remonter.
    """

    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    diag = getattr(orig, "diag", None)
    if diag is not None and getattr(diag, "constraint_name", None) == _PHONE_UNIQUE_INDEX:
        return True
    if getattr(orig, "sqlstate", None) != _UNIQUE_SQLSTATE:
        return False
    return _PHONE_UNIQUE_INDEX in str(orig)


def _to_domain(row: models.CustomerProfile) -> Customer:
    return Customer(
        id=row.id,
        salon_id=row.salon_id,
        full_name=row.full_name,
        phone=row.phone,
        gender=row.gender,
        notes=row.notes,
        last_visit_at=row.last_visit_at,
        total_visits=row.total_visits,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["SqlCustomerRepository"]
