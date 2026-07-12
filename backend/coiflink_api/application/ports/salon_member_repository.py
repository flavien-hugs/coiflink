"""Port de persistance de l'**appartenance employé↔salon** (`Protocol`, #13).

Le cas d'usage `CreateEmployee` déclare ici son besoin d'écriture de
l'appartenance (`salon_members`) ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/salon_member_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle
ORM.

La **lecture de portée** (« sur quels salons ce membre a-t-il une portée ? »)
reste la responsabilité du port `SalonScopeRepository` (branche `HAIRDRESSER`),
pas de ce port : ici on ne fait qu'**écrire** le rattachement.
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.membership import SalonMembershipToCreate


class SalonMemberRepository(Protocol):
    """Contrat d'écriture de l'appartenance d'un compte à un salon."""

    def add_member(self, membership: SalonMembershipToCreate) -> None:
        """Insère l'appartenance `(salon_id, user_id)` (statut fourni).

        Doit lever `domain.errors.EmployeeAlreadyInSalon` si l'unicité
        `(salon_id, user_id)` est violée (le compte est déjà employé de ce
        salon). L'écriture partage la `Session` de la requête : le commit est
        piloté par `get_session` (atomicité user + appartenance).
        """
        ...


__all__ = ["SalonMemberRepository"]
