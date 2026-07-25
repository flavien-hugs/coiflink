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

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.customer import Customer, CustomerToCreate
from coiflink_api.domain.errors import CustomerAlreadyExists

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
        self, salon_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Customer, ...]:
        """Page de fiches du salon, les plus récentes d'abord (bornes appliquées en SQL)."""

        stmt = (
            select(models.CustomerProfile)
            .where(models.CustomerProfile.salon_id == salon_id)
            .order_by(
                models.CustomerProfile.created_at.desc(),
                models.CustomerProfile.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(_to_domain(row) for row in self._session.scalars(stmt).all())

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(models.CustomerProfile).where(
            models.CustomerProfile.salon_id == salon_id
        )
        return int(self._session.scalar(stmt) or 0)

    def phone_exists(self, salon_id: uuid.UUID, phone: str) -> bool:
        """Pré-contrôle d'unicité `(salon_id, phone)` — la garantie reste l'index base."""

        stmt = select(models.CustomerProfile.id).where(
            models.CustomerProfile.salon_id == salon_id,
            models.CustomerProfile.phone == phone,
        )
        return self._session.scalar(stmt) is not None


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
