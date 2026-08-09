"""Port de persistance des **prestations** (`Protocol`, US-2.3, #17).

Le cas d'usage `application/services.py` déclare ici ses besoins d'écriture et de
lecture ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/service_repository.py`. Conformément à l'hexagonal
(ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Isolation §11.2 au niveau du dépôt** : toutes les méthodes de lecture/écriture
portant sur une prestation existante prennent `salon_id` **en plus** de
`service_id` et filtrent sur le couple `(salon_id, id)`. Impossible de lire, de
modifier ou de désactiver la prestation d'un autre salon même si l'`id` est deviné
— miroir de `delete_photo(salon_id, photo_id)` de #15.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.service import (
    Service,
    ServiceFilter,
    ServiceToCreate,
    ServiceUpdate,
)


class ServiceRepository(Protocol):
    """Contrat de persistance des prestations d'un salon."""

    def create(self, service: ServiceToCreate) -> Service:
        """Persiste et retourne la prestation créée (`is_active=True` par défaut)."""
        ...

    def find_by_id(
        self, salon_id: uuid.UUID, service_id: uuid.UUID
    ) -> Service | None:
        """Retourne la prestation `(salon_id, service_id)`, sinon `None`.

        Le filtre porte sur `salon_id` **et** `id` (isolation §11.2) : une
        prestation d'un autre salon est indiscernable d'une prestation inexistante.
        """
        ...

    def list_for_salon(
        self, salon_id: uuid.UUID, *, filter: ServiceFilter, include_inactive: bool = True
    ) -> tuple[Service, ...]:
        """Prestations **filtrées** du salon, les plus récentes d'abord.

        `include_inactive=True` (défaut) renvoie actives **et** désactivées (vue
        gérant). Le futur catalogue client (#18) filtrera les actives seulement.
        `filter` porte les critères optionnels (nom, catégorie, plage de dates de
        création), combinés en **ET** avec `salon_id` et `include_inactive` —
        aucune pagination ici (portée volontairement hors périmètre, la réponse
        reste une liste complète, cf. `CustomerFilter` pour le pendant paginé).
        """
        ...

    def update(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, changes: ServiceUpdate
    ) -> Service:
        """Remplace les champs modifiables de la prestation ; retourne l'entité relue.

        Lève `domain.errors.ServiceNotFound` si `(salon_id, service_id)` est absent.
        """
        ...

    def set_active(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, active: bool
    ) -> Service:
        """Bascule `is_active` de la prestation ; retourne l'entité relue.

        Support de la « suppression » canonique (désactivation, `active=False`) et
        d'une éventuelle réactivation (`active=True`). Lève
        `domain.errors.ServiceNotFound` si `(salon_id, service_id)` est absent.
        """
        ...

    def set_image(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, image_object_key: str | None
    ) -> Service:
        """Remplace la clé d'objet image de la prestation ; retourne l'entité relue.

        `None` efface l'illustration (aucune image). Action **dédiée**, découplée
        de `update()` (miroir `set_active`/`AttachSalonLogo` — le binaire est
        téléversé séparément, la clé est revalidée par le cas d'usage avant
        d'atteindre le dépôt). Lève `domain.errors.ServiceNotFound` si
        `(salon_id, service_id)` est absent.
        """
        ...


__all__ = ["ServiceRepository"]
