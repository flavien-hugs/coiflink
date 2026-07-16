"""Port de persistance du **salon** et de ses **photos** (`Protocol`, #15).

Le cas d'usage `application/salons.py` déclare ici ses besoins d'écriture et de
lecture ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/salon_repository.py`. Conformément à l'hexagonal
(ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

La **lecture de portée** (« sur quels salons ce compte a-t-il une portée ? »)
reste la responsabilité du port `SalonScopeRepository`, pas de ce port : créer un
salon suffit à donner mécaniquement sa portée au gérant (`salons.owner_id`).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.salon import Salon, SalonPhoto, SalonToCreate, SalonUpdate


class SalonRepository(Protocol):
    """Contrat de persistance des salons et de leurs photos."""

    def create(self, salon: SalonToCreate) -> Salon:
        """Persiste et retourne le salon créé (`status=ACTIVE`, `opening_hours=NULL`)."""
        ...

    def find_by_id(self, salon_id: uuid.UUID) -> Salon | None:
        """Retourne le salon pour cet `id`, sinon `None`."""
        ...

    def update(self, salon_id: uuid.UUID, changes: SalonUpdate) -> Salon:
        """Remplace les champs modifiables du salon (sémantique *replace*) ; retourne le salon relu.

        Lève `domain.errors.SalonNotFound` si le salon n'existe pas.
        """
        ...

    def list_for_owner(self, owner_id: uuid.UUID) -> tuple[Salon, ...]:
        """Salons rattachés à ce gérant (`owner_id`), les plus récents d'abord."""
        ...

    def set_logo(self, salon_id: uuid.UUID, object_key: str | None) -> Salon:
        """Écrit (ou efface) la **clé d'objet** du logo ; retourne le salon relu.

        Lève `domain.errors.SalonNotFound` si le salon n'existe pas.
        """
        ...

    def set_opening_hours(self, salon_id: uuid.UUID, opening_hours: dict) -> Salon:
        """Écrit la structure d'horaires (déjà validée) ; retourne le salon relu.

        `opening_hours` est le JSONB **normalisé** produit par le domaine
        (`domain/opening_hours.to_jsonb`). Écrire un dict non vide fait basculer
        `is_bookable` à `True` (§8.3). Lève `domain.errors.SalonNotFound` si le
        salon n'existe pas.
        """
        ...

    def add_photo(self, salon_id: uuid.UUID, object_key: str) -> SalonPhoto:
        """Ajoute une photo (position = fin de liste) ; retourne l'entité créée."""
        ...

    def list_photos(self, salon_id: uuid.UUID) -> tuple[SalonPhoto, ...]:
        """Photos du salon, ordonnées par `position` croissante."""
        ...

    def count_photos(self, salon_id: uuid.UUID) -> int:
        """Nombre de photos du salon (borne `MEDIA_MAX_PHOTOS`)."""
        ...

    def delete_photo(self, salon_id: uuid.UUID, photo_id: uuid.UUID) -> str | None:
        """Supprime la photo `(salon_id, photo_id)` ; retourne sa clé d'objet.

        Retourne `None` si la photo n'existe pas pour ce salon (l'adapter entrant
        traduit alors en `404`). La clé retournée permet au cas d'usage de
        supprimer l'objet correspondant du bucket.
        """
        ...


__all__ = ["SalonRepository"]
