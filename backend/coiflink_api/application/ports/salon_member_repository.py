"""Port de persistance de l'**appartenance employé↔salon** (`Protocol`, #13/#150).

Le cas d'usage `CreateEmployee` déclare ici son besoin d'écriture de
l'appartenance (`salon_members`) ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/salon_member_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle
ORM.

**Gestion des coiffeuses** (#150) : `list_for_salon`/`find_by_id` résolvent la
vue de lecture `Employee` (identité `users` + appartenance `salon_members`,
jointes) ; `update_professional_fields`/`set_status` écrivent respectivement
les champs pro et la **disponibilité aux affectations** (`salon_members.
status`, distinct de `users.status`).

La **lecture de portée** (« sur quels salons ce membre a-t-il une portée ? »)
reste la responsabilité du port `SalonScopeRepository` (branche `HAIRDRESSER`),
pas de ce port.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Protocol

from coiflink_api.domain.employee import Employee
from coiflink_api.domain.membership import SalonMembershipToCreate


class SalonMemberRepository(Protocol):
    """Contrat de persistance de l'appartenance d'un compte à un salon."""

    def add_member(self, membership: SalonMembershipToCreate) -> None:
        """Insère l'appartenance `(salon_id, user_id)` (statut fourni).

        Doit lever `domain.errors.EmployeeAlreadyInSalon` si l'unicité
        `(salon_id, user_id)` est violée (le compte est déjà employé de ce
        salon). L'écriture partage la `Session` de la requête : le commit est
        piloté par `get_session` (atomicité user + appartenance).
        """
        ...

    def list_for_salon(self, salon_id: uuid.UUID) -> tuple[Employee, ...]:
        """Liste les coiffeuses (`role=HAIRDRESSER`) membres de `salon_id`.

        Jointure interne avec `users` pour résoudre identité + champs pro,
        triée par nom d'affichage. L'isolation §11.2 est imposée **en SQL**
        (`WHERE salon_members.salon_id`), en défense en profondeur de la garde
        HTTP `require_salon_scope` : ne renvoie jamais une coiffeuse d'un
        autre salon. Lecture pure.
        """
        ...

    def find_by_id(
        self, salon_id: uuid.UUID, user_id: uuid.UUID
    ) -> Employee | None:
        """Charge la coiffeuse `(salon_id, user_id)`, ou `None`.

        Le filtre porte sur `salon_id` **et** `user_id` : une coiffeuse d'un
        autre salon est indiscernable d'un identifiant inexistant (aucun
        oracle, §11.2). Le cas d'usage lève alors `EmployeeNotFound` (`404`
        **après** la portée).
        """
        ...

    def update_professional_fields(
        self,
        salon_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        specialties: str | None,
        hired_at: datetime.date | None,
    ) -> Employee | None:
        """Remplace les champs pro (`specialties`/`hired_at`) ; `None` si hors salon.

        Reçoit des valeurs **déjà normalisées** (`domain.employee.
        normalize_specialties`) — ce port ne revalide rien. `None` (jamais une
        exception) si `(salon_id, user_id)` ne correspond à aucune ligne —
        garde-fou cohérent avec `find_by_id`.
        """
        ...

    def set_status(
        self, salon_id: uuid.UUID, user_id: uuid.UUID, status: str
    ) -> Employee | None:
        """Pose `salon_members.status` (disponibilité aux affectations, #150).

        Pilote l'**éligibilité aux nouvelles affectations** de ce salon
        (`_require_salon_hairdresser` filtre `status = 'ACTIVE'`) — ne touche
        **jamais** `users.status` (compte global, hors périmètre). `None`
        (jamais une exception) si `(salon_id, user_id)` ne correspond à aucune
        ligne.
        """
        ...


__all__ = ["SalonMemberRepository"]
