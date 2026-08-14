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
    ServicePhoto,
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

    def add_photo(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, object_key: str
    ) -> ServicePhoto:
        """Ajoute une photo en fin de galerie (`position` = nombre de photos actuel).

        Miroir `SalonRepository.add_photo`. La limite (`MEDIA_MAX_PHOTOS`) et la
        revalidation du préfixe de clé sont du ressort du cas d'usage
        (`AddServicePhoto`), pas du dépôt.
        """
        ...

    def list_photos(
        self, salon_id: uuid.UUID, service_id: uuid.UUID
    ) -> tuple[ServicePhoto, ...]:
        """Photos de la prestation, ordonnées par `position` croissante.

        La photo de `position = 0` sert de couverture catalogue.
        """
        ...

    def count_photos(self, salon_id: uuid.UUID, service_id: uuid.UUID) -> int:
        """Nombre de photos actuel de la prestation (vérification de la limite)."""
        ...

    def delete_photo(
        self, salon_id: uuid.UUID, service_id: uuid.UUID, photo_id: uuid.UUID
    ) -> str | None:
        """Supprime la photo `(salon_id, service_id, photo_id)` ; retourne sa clé d'objet.

        Le filtre porte sur `salon_id`, `service_id` **et** `id` (isolation
        §11.2) : impossible de supprimer la photo d'une autre prestation ou d'un
        autre salon. `None` si aucune ligne (photo ou prestation introuvable).
        """
        ...


__all__ = ["ServiceRepository"]
