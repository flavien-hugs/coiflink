"""Port de **lecture publique du catalogue de salons** (`Protocol`, #18).

Ce port est **distinct** de `SalonRepository` (gestion, portée gérant) : la
lecture publique n'expose que les salons `ACTIVE` (§8.3) et n'a jamais besoin des
écritures ni de la portée. L'isoler garantit qu'un futur appel de gestion ne
puisse pas contourner le filtre `status = ACTIVE` par mégarde, et que le catalogue
client n'hérite d'aucune capacité d'écriture.

Le cas d'usage `application/catalog.py` déclare ici ses besoins de lecture ;
l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/salon_catalog_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

Invariant **non négociable** (§8.3) : toutes les méthodes de ce port ne renvoient
que des salons `ACTIVE` — le filtre est appliqué **au niveau de la requête SQL**,
jamais en post-filtrage applicatif faillible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from coiflink_api.domain.salon import Salon, SalonPhoto
from coiflink_api.domain.service import Service

# Bornes de pagination (déni de service par page géante → refus côté adapter).
CATALOG_LIMIT_MIN = 1
CATALOG_LIMIT_MAX = 50
CATALOG_LIMIT_DEFAULT = 20


@dataclass(frozen=True)
class SalonSearchQuery:
    """Critères de recherche du catalogue public (tous optionnels sauf pagination).

    - `text` : recherche par **nom** (`ILIKE` sous-chaîne, métacaractères échappés) ;
    - `city` / `commune` : filtre de **zone** (égalité insensible à la casse) ;
    - `limit` / `offset` : pagination **bornée** (`limit` dans
      `[CATALOG_LIMIT_MIN, CATALOG_LIMIT_MAX]`, `offset >= 0`).

    Les bornes de pagination sont validées par l'adapter entrant (→ `422`) ; ce
    `dataclass` transporte des valeurs déjà validées.
    """

    text: str | None = None
    city: str | None = None
    commune: str | None = None
    limit: int = CATALOG_LIMIT_DEFAULT
    offset: int = 0


class SalonCatalogRepository(Protocol):
    """Contrat de lecture **publique** du catalogue de salons (`ACTIVE`-only, §8.3)."""

    def search_active(self, query: SalonSearchQuery) -> tuple[Salon, ...]:
        """Salons `ACTIVE` correspondant à `query`, triés par nom, page bornée.

        Un salon `INACTIVE`/`SUSPENDED` ne peut jamais figurer dans le résultat
        (filtre `status = ACTIVE` appliqué en SQL, en premier `where`).
        """
        ...

    def count_active(self, query: SalonSearchQuery) -> int:
        """Nombre total de salons `ACTIVE` correspondant au filtre (hors pagination).

        Sert à renseigner `total` dans la réponse paginée : les mêmes filtres
        (`text`/`city`/`commune`) s'appliquent, sans `limit`/`offset`.
        """
        ...

    def get_active(self, salon_id: uuid.UUID) -> Salon | None:
        """Un salon `ACTIVE` par identifiant, sinon `None` (fiche client #19).

        Un salon non-`ACTIVE` renvoie `None` (→ `404` côté client) : « absent du
        catalogue » plutôt que « masqué » — pas d'oracle d'existence.
        """
        ...

    def list_active_services(self, salon_id: uuid.UUID) -> tuple[Service, ...]:
        """Prestations **`ACTIVE` seulement** d'un salon, triées par nom (fiche #19).

        Le filtre `is_active = true` est appliqué **en SQL**, jamais en
        post-filtrage applicatif : une prestation soft-deletée (#17) ne peut pas
        fuir côté client. Méthode de **lecture publique dédiée** — le catalogue
        n'hérite d'aucune capacité de gestion du `ServiceRepository` (ADR-0020 §2).
        """
        ...

    def list_photos(self, salon_id: uuid.UUID) -> tuple[SalonPhoto, ...]:
        """Photos du salon, ordonnées par `position` croissante (galerie fiche #19).

        Chaque `SalonPhoto` porte une **clé d'objet** (jamais une URL) : le cas
        d'usage la résout en URL signée à la lecture (ADR-0005).
        """
        ...


__all__ = [
    "CATALOG_LIMIT_MIN",
    "CATALOG_LIMIT_MAX",
    "CATALOG_LIMIT_DEFAULT",
    "SalonSearchQuery",
    "SalonCatalogRepository",
]
