"""Entité de domaine « appartenance employé↔salon » (domaine pur, #13).

`SalonMembershipToCreate` décrit le rattachement d'un compte (coiffeur) à un
salon, source d'autorité de sa **portée** (PRD §11.2, ADR-0016). Comme le reste
du domaine (ADR-0008), cette `dataclass` n'importe ni FastAPI ni SQLAlchemy : le
modèle ORM correspondant (`salon_members`) vit dans l'adapter de persistance.

Le rôle d'appartenance est **fixé côté serveur** (jamais lu d'une requête) —
garde-fou anti-élévation de privilège cohérent avec l'inscription (#8/#9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import Role, UserStatus


@dataclass(frozen=True)
class SalonMembershipToCreate:
    """Appartenance prête à être persistée (statut `ACTIVE` par défaut)."""

    salon_id: uuid.UUID
    user_id: uuid.UUID
    role: str = Role.HAIRDRESSER.value
    status: str = UserStatus.ACTIVE.value


__all__ = ["SalonMembershipToCreate"]
