"""Adapter sortant : persistance des **prestations** (SQLAlchemy, US-2.3, #17).

Implémente le port `ServiceRepository` sur une `Session` SQLAlchemy 2.0 et le
modèle ORM `models.Service` (déjà au schéma, migration `0001`). Seul cet adapter
connaît SQLAlchemy ; il mappe les entités de domaine ↔ modèles ORM et retraduit
l'absence d'une prestation en **erreur de domaine** `ServiceNotFound` (jamais de
fuite d'un détail SQLAlchemy).

Comme `SqlSalonRepository`, les écritures sont `flush`ées **sans commit** : le
commit (ou rollback) est piloté par la dépendance de session (`get_session`), ce
qui permet à l'entrée d'audit (`SqlAuditLog`) d'être committée dans la **même**
unité de travail que la mutation métier (atomicité §11.4).

**Isolation §11.2 au niveau du dépôt** : toute lecture/écriture d'une prestation
existante filtre sur le couple `(salon_id, id)` — impossible de lire, modifier ou
désactiver la prestation d'un autre salon même si l'`id` est deviné (miroir de
`delete_photo(salon_id, photo_id)` de #15).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.errors import ServiceNotFound
from coiflink_api.domain.service import Service, ServiceToCreate, ServiceUpdate


class SqlServiceRepository:
    """Dépôt de prestations adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, service: ServiceToCreate) -> Service:
        """Insère la prestation (`is_active=true` par défaut serveur)."""

        row = models.Service(
            salon_id=service.salon_id,
            name=service.name,
            description=service.description,
            price=service.price,
            duration_minutes=service.duration_minutes,
            category=service.category,
        )
        self._session.add(row)
        # `flush` déclenche l'INSERT (et les contraintes) sans committer.
        self._session.flush()
        # Recharge les valeurs générées côté serveur (id, is_active, timestamps).
        self._session.refresh(row)
        return _to_domain(row)

    def find_by_id(
        self, salon_id: uuid.UUID, service_id: uuid.UUID
    ) -> Service | None:
        row = self._get_row(salon_id, service_id)
        return _to_domain(row) if row is not None else None

    def list_for_salon(
        self, salon_id: uuid.UUID, *, include_inactive: bool = True
    ) -> tuple[Service, ...]:
        stmt = select(models.Service).where(models.Service.salon_id == salon_id)
        if not include_inactive:
            stmt = stmt.where(models.Service.is_active.is_(True))
        stmt = stmt.order_by(models.Service.created_at.desc())
        return tuple(_to_domain(row) for row in self._session.scalars(stmt).all())

    def update(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, changes: ServiceUpdate
    ) -> Service:
        row = self._get_row(salon_id, service_id)
        if row is None:
            raise ServiceNotFound("Prestation introuvable.")
        row.name = changes.name
        row.description = changes.description
        row.price = changes.price
        row.duration_minutes = changes.duration_minutes
        row.category = changes.category
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def set_active(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, active: bool
    ) -> Service:
        row = self._get_row(salon_id, service_id)
        if row is None:
            raise ServiceNotFound("Prestation introuvable.")
        row.is_active = active
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def _get_row(
        self, salon_id: uuid.UUID, service_id: uuid.UUID
    ) -> models.Service | None:
        """Charge la prestation `(salon_id, service_id)` — filtre d'isolation §11.2."""

        stmt = select(models.Service).where(
            models.Service.salon_id == salon_id,
            models.Service.id == service_id,
        )
        return self._session.scalar(stmt)


def _to_domain(row: models.Service) -> Service:
    return Service(
        id=row.id,
        salon_id=row.salon_id,
        name=row.name,
        description=row.description,
        price=row.price,
        duration_minutes=row.duration_minutes,
        category=row.category,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["SqlServiceRepository"]
