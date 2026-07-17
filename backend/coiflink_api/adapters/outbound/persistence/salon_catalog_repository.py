"""Adapter sortant : lecture publique du catalogue de salons (SQLAlchemy, #18).

Implémente le port `SalonCatalogRepository` sur une `Session` SQLAlchemy 2.0 et le
modèle ORM `Salon`. Seule responsabilité : **la lecture des salons `ACTIVE`**
(§8.3), avec recherche par nom (`ILIKE` échappé), filtre de zone (ville/commune) et
pagination bornée.

Invariant central (§8.3) : le filtre `status = ACTIVE` est le **premier `where`**,
appliqué **en base** — un salon `INACTIVE`/`SUSPENDED` ne peut pas remonter, ni
dans la liste ni dans `get_active` (→ `None` → `404` côté #19). Aucun
post-filtrage applicatif (faillible). S'appuie sur les index déjà présents
`ix_salons_status` et `ix_salons_city_commune` (aucune migration).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.adapters.outbound.persistence.salon_repository import _to_domain
from coiflink_api.application.ports.salon_catalog_repository import SalonSearchQuery
from coiflink_api.domain.enums import SalonStatus
from coiflink_api.domain.salon import Salon

# Caractère d'échappement des métacaractères `LIKE` (`%`, `_`). Il est déclaré à
# SQLAlchemy via `escape=` afin que la recherche traite un `%` saisi comme un
# littéral, pas comme un joker (`ILIKE` prévisible — §Security du spec).
_LIKE_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Échappe les métacaractères `LIKE` (`\\`, `%`, `_`) d'un terme de recherche.

    N'est **pas** une défense anti-injection (SQLAlchemy paramètre déjà la valeur) :
    c'est une garantie de **prévisibilité** — un `%` ou `_` saisi par le client est
    traité comme un caractère littéral, pas comme un joker `LIKE`. Le backslash est
    échappé en premier pour ne pas neutraliser les échappements suivants.
    """

    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


class SqlSalonCatalogRepository:
    """Dépôt de lecture publique des salons (`ACTIVE`-only) adossé à une `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def search_active(self, query: SalonSearchQuery) -> tuple[Salon, ...]:
        stmt = (
            self._active_filtered(query)
            .order_by(models.Salon.name.asc(), models.Salon.id.asc())
            .limit(query.limit)
            .offset(query.offset)
        )
        return tuple(_to_domain(row) for row in self._session.scalars(stmt).all())

    def count_active(self, query: SalonSearchQuery) -> int:
        stmt = self._active_filtered(query).with_only_columns(
            func.count(models.Salon.id)
        )
        return int(self._session.scalar(stmt) or 0)

    def get_active(self, salon_id: uuid.UUID) -> Salon | None:
        stmt = select(models.Salon).where(
            models.Salon.id == salon_id,
            models.Salon.status == SalonStatus.ACTIVE.value,
        )
        row = self._session.scalar(stmt)
        return _to_domain(row) if row is not None else None

    def _active_filtered(self, query: SalonSearchQuery):
        """`select(Salon)` filtré `ACTIVE` + recherche/zone (sans tri ni pagination).

        Le filtre `status = ACTIVE` est **toujours** le premier `where` : partagé
        entre `search_active` et `count_active`, il ne peut pas diverger.
        """

        stmt = select(models.Salon).where(
            models.Salon.status == SalonStatus.ACTIVE.value
        )
        if query.text:
            pattern = f"%{escape_like(query.text)}%"
            stmt = stmt.where(models.Salon.name.ilike(pattern, escape=_LIKE_ESCAPE))
        if query.city:
            stmt = stmt.where(models.Salon.city.ilike(query.city))
        if query.commune:
            stmt = stmt.where(models.Salon.commune.ilike(query.commune))
        return stmt


__all__ = ["SqlSalonCatalogRepository", "escape_like"]
