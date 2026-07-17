"""Cas d'usage : **recherche/liste publique du catalogue de salons** (US-2.3, #18).

Tranche applicative hexagonale (ADR-0008) : ce cas d'usage ne dépend que de
**ports** (`SalonCatalogRepository`, `MediaStorage`) — aucune dépendance
FastAPI/SQLAlchemy/boto3. Il orchestre la lecture publique (`ACTIVE`-only, §8.3)
et laisse l'adapter entrant traduire les bornes de pagination en `422`.

Invariants portés ici (spec §A.4) :

- **projection publique minimale** : `PublicSalonView` n'expose que des champs de
  vitrine (nom, description, localisation, `logo_url` signé, `is_bookable`) — jamais
  l'`owner_id`, le `status`, les `opening_hours` bruts, le `phone` ni les
  timestamps. Un champ de gestion qui n'existe pas dans la vue ne peut pas fuir ;
- **filtre `ACTIVE` délégué au port** : le cas d'usage ne re-filtre pas en Python —
  le port `SalonCatalogRepository` garantit `status = ACTIVE` au niveau SQL (§8.3) ;
- **logo → URL signée** (ADR-0005) : `logo_url` est toujours une URL signée à durée
  limitée ou `None` (stockage non configuré), jamais une clé d'objet brute.
"""

from __future__ import annotations

from dataclasses import dataclass

from coiflink_api.application.ports.media_storage import MediaStorage
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
    SalonSearchQuery,
)
from coiflink_api.domain.salon import Salon


@dataclass(frozen=True)
class PublicSalonView:
    """Projection **publique** d'un salon (vitrine) — sans donnée de gestion.

    Volontairement dissociée de `SalonView` (`application/salons.py`) : celle-ci
    porte `owner_id`, `status`, `opening_hours` et le `phone`, jamais exposés au
    client. `logo_url` est une **URL signée** (ou `None`), jamais une clé d'objet.
    """

    id: object
    name: str
    description: str | None
    address: str | None
    city: str | None
    commune: str | None
    latitude: object | None
    longitude: object | None
    logo_url: str | None
    is_bookable: bool


@dataclass(frozen=True)
class PublicSalonPage:
    """Page de résultats du catalogue : items + total (hors pagination) + bornes."""

    items: tuple[PublicSalonView, ...]
    total: int
    limit: int
    offset: int


class SearchSalons:
    """Recherche/liste les salons `ACTIVE` et les projette en vue publique (§8.3).

    Le filtre de visibilité §8.3 est **entièrement** porté par le dépôt
    (`search_active`/`count_active` : `status = ACTIVE` en SQL) : ce cas d'usage ne
    fait qu'assembler la page et résoudre le logo en URL signée. Aucun
    post-filtrage applicatif (faillible) n'est ajouté ici.
    """

    def __init__(
        self,
        repository: SalonCatalogRepository,
        media_storage: MediaStorage | None = None,
    ) -> None:
        self._repository = repository
        self._media_storage = media_storage

    def execute(self, query: SalonSearchQuery) -> PublicSalonPage:
        salons = self._repository.search_active(query)
        total = self._repository.count_active(query)
        items = tuple(self._to_view(salon) for salon in salons)
        return PublicSalonPage(
            items=items,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    def _to_view(self, salon: Salon) -> PublicSalonView:
        return PublicSalonView(
            id=salon.id,
            name=salon.name,
            description=salon.description,
            address=salon.address,
            city=salon.city,
            commune=salon.commune,
            latitude=salon.latitude,
            longitude=salon.longitude,
            logo_url=self._sign(salon.logo_object_key),
            is_bookable=salon.is_bookable,
        )

    def _sign(self, object_key: str | None) -> str | None:
        """URL signée de lecture, ou `None` si pas de clé / stockage non configuré."""

        if object_key is None or self._media_storage is None:
            return None
        return self._media_storage.presign_download(object_key)


__all__ = ["PublicSalonView", "PublicSalonPage", "SearchSalons"]
