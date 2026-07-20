"""Adapter sortant : persistance du salon et de ses photos (SQLAlchemy, #15).

Implémente le port `SalonRepository` sur une `Session` SQLAlchemy 2.0 et les
modèles ORM `Salon` / `SalonPhoto`. Seul cet adapter connaît SQLAlchemy ; il mappe
les entités de domaine ↔ modèles ORM et retraduit l'absence d'un salon en
**erreur de domaine** `SalonNotFound` (jamais de fuite d'un détail SQLAlchemy).

Comme `SqlUserRepository` / `SqlSalonMemberRepository`, les écritures sont
`flush`ées **sans commit** : le commit (ou rollback) est piloté par la dépendance
de session (`get_session`). Créer un salon donne **mécaniquement** sa portée au
gérant : `SqlSalonScopeRepository` lit `salons.owner_id` — aucun code
supplémentaire (c'est ce qui débloque #13).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.errors import SalonNotFound
from coiflink_api.domain.salon import Salon, SalonPhoto, SalonToCreate, SalonUpdate


class SqlSalonRepository:
    """Dépôt de salons et de photos adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, salon: SalonToCreate) -> Salon:
        """Insère le salon (`status=ACTIVE`, `opening_hours=NULL` par défaut serveur)."""

        row = models.Salon(
            owner_id=salon.owner_id,
            name=salon.name,
            description=salon.description,
            phone=salon.phone,
            address=salon.address,
            city=salon.city,
            commune=salon.commune,
            latitude=salon.latitude,
            longitude=salon.longitude,
        )
        self._session.add(row)
        # `flush` déclenche l'INSERT (et les contraintes) sans committer.
        self._session.flush()
        # Recharge les valeurs générées côté serveur (id, status, timestamps).
        self._session.refresh(row)
        return _to_domain(row)

    def find_by_id(self, salon_id: uuid.UUID) -> Salon | None:
        row = self._session.get(models.Salon, salon_id)
        return _to_domain(row) if row is not None else None

    def list_for_owner(self, owner_id: uuid.UUID) -> tuple[Salon, ...]:
        stmt = (
            select(models.Salon)
            .where(models.Salon.owner_id == owner_id)
            .order_by(models.Salon.created_at.desc())
        )
        return tuple(_to_domain(row) for row in self._session.scalars(stmt).all())

    def update(self, salon_id: uuid.UUID, changes: SalonUpdate) -> Salon:
        row = self._session.get(models.Salon, salon_id)
        if row is None:
            raise SalonNotFound("Salon introuvable.")
        row.name = changes.name
        row.description = changes.description
        row.phone = changes.phone
        row.address = changes.address
        row.city = changes.city
        row.commune = changes.commune
        row.latitude = changes.latitude
        row.longitude = changes.longitude
        # `updated_at` n'a pas d'`onupdate` au niveau ORM (server_default only) : on
        # le rafraîchit explicitement ici pour que la modification soit observable
        # (fraîcheur côté client, #20). `func.now()` est évalué côté serveur au flush.
        row.updated_at = func.now()
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def set_logo(self, salon_id: uuid.UUID, object_key: str | None) -> Salon:
        row = self._session.get(models.Salon, salon_id)
        if row is None:
            raise SalonNotFound("Salon introuvable.")
        row.logo_object_key = object_key
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def set_opening_hours(self, salon_id: uuid.UUID, opening_hours: dict) -> Salon:
        row = self._session.get(models.Salon, salon_id)
        if row is None:
            raise SalonNotFound("Salon introuvable.")
        row.opening_hours = opening_hours
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def add_photo(self, salon_id: uuid.UUID, object_key: str) -> SalonPhoto:
        position = self.count_photos(salon_id)
        row = models.SalonPhoto(
            salon_id=salon_id, object_key=object_key, position=position
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _photo_to_domain(row)

    def list_photos(self, salon_id: uuid.UUID) -> tuple[SalonPhoto, ...]:
        stmt = (
            select(models.SalonPhoto)
            .where(models.SalonPhoto.salon_id == salon_id)
            .order_by(models.SalonPhoto.position.asc(), models.SalonPhoto.created_at.asc())
        )
        return tuple(_photo_to_domain(row) for row in self._session.scalars(stmt).all())

    def count_photos(self, salon_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(models.SalonPhoto.salon_id == salon_id)
        return int(self._session.scalar(stmt) or 0)

    def delete_photo(self, salon_id: uuid.UUID, photo_id: uuid.UUID) -> str | None:
        """Supprime la photo `(salon_id, photo_id)` ; retourne sa clé d'objet.

        Le filtre porte sur `salon_id` **et** `id` : impossible de supprimer la
        photo d'un autre salon (isolation §11.2). `None` si aucune ligne.
        """

        stmt = select(models.SalonPhoto).where(
            models.SalonPhoto.salon_id == salon_id,
            models.SalonPhoto.id == photo_id,
        )
        row = self._session.scalar(stmt)
        if row is None:
            return None
        object_key = row.object_key
        self._session.delete(row)
        self._session.flush()
        return object_key


def _to_domain(row: models.Salon) -> Salon:
    return Salon(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        description=row.description,
        phone=row.phone,
        address=row.address,
        city=row.city,
        commune=row.commune,
        latitude=row.latitude,
        longitude=row.longitude,
        logo_object_key=row.logo_object_key,
        status=row.status,
        opening_hours=row.opening_hours,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _photo_to_domain(row: models.SalonPhoto) -> SalonPhoto:
    return SalonPhoto(
        id=row.id,
        salon_id=row.salon_id,
        object_key=row.object_key,
        position=row.position,
        created_at=row.created_at,
    )


__all__ = ["SqlSalonRepository"]
