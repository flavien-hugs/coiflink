"""Port de persistance des **fiches clients** (`Protocol`, US-4.1, #28).

Le cas d'usage `application/customers.py` déclare ici ses besoins d'écriture et
de lecture ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/customer_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Isolation §11.2 au niveau du dépôt** : toutes les méthodes portant sur une fiche
existante prennent `salon_id` **en plus** de l'identifiant et filtrent sur le
couple `(salon_id, id)`. Une fiche d'un autre salon est **indiscernable d'une
fiche inexistante** — impossible de la lire même si l'`id` est deviné (miroir de
`ServiceRepository`). C'est la défense en profondeur derrière `require_salon_scope`.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.customer import Customer, CustomerToCreate

# Bornes de pagination de la liste (garde de coût §12.1 — patron catalogue #18).
CUSTOMER_LIMIT_DEFAULT = 50
CUSTOMER_LIMIT_MIN = 1
CUSTOMER_LIMIT_MAX = 200


class CustomerRepository(Protocol):
    """Contrat de persistance des fiches clients d'un salon."""

    def create(self, customer: CustomerToCreate) -> Customer:
        """Persiste et retourne la fiche créée (`user_id` reste `NULL`, walk-in).

        Lève `domain.errors.CustomerAlreadyExists` si l'unicité
        `(salon_id, phone)` est violée — y compris pour le **perdant d'une course
        concurrente** (l'`IntegrityError` base est retraduite, jamais propagée).
        """
        ...

    def find_by_id(
        self, salon_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Customer | None:
        """Retourne la fiche `(salon_id, customer_id)`, sinon `None`.

        Le filtre porte sur `salon_id` **et** `id` (isolation §11.2) : une fiche
        d'un autre salon est indiscernable d'une fiche inexistante.
        """
        ...

    def list_for_salon(
        self, salon_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Customer, ...]:
        """Page de fiches du salon, les plus récentes d'abord (`limit`/`offset` en SQL)."""
        ...

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        """Nombre total de fiches du salon (total de pagination)."""
        ...

    def phone_exists(self, salon_id: uuid.UUID, phone: str) -> bool:
        """Vrai si une fiche du salon porte déjà ce téléphone (forme canonique E.164).

        Pré-contrôle applicatif : il produit un `409` explicite dans le cas
        nominal, mais **ne garantit rien** en concurrence — la garantie est l'index
        unique partiel `uq_customer_profiles_salon_phone`.
        """
        ...


__all__ = [
    "CustomerRepository",
    "CUSTOMER_LIMIT_DEFAULT",
    "CUSTOMER_LIMIT_MIN",
    "CUSTOMER_LIMIT_MAX",
]
