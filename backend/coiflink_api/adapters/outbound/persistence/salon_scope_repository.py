"""Adapter sortant : lecture SQL de la **portée salon** d'un compte (§11.2, #12).

Implémente le port `SalonScopeRepository` sur une `Session` SQLAlchemy. C'est la
**seule** source d'autorité de l'isolation multi-salons : la portée est lue en
base, jamais déduite d'un paramètre de requête.

Rattachements exploités (schéma existant) :

- `MANAGER` → `salons.owner_id` : rattachement **réel** du gérant à ses salons ;
- `HAIRDRESSER` → `salon_members.salon_id WHERE user_id = … AND status = 'ACTIVE'`.
  Depuis #13 (ADR-0016), la portée d'un coiffeur est lue depuis la table
  d'**appartenance** employé↔salon (`salon_members`), et non plus dérivée des
  rendez-vous qui lui sont assignés : un coiffeur fraîchement créé « voit » son
  salon dès sa création, sans dépendre d'un RDV. L'assignation d'un RDV reste
  gérée séparément par `can_access_appointment` (inchangé). Un membre `INACTIVE`
  perd sa portée (le filtre exige `ACTIVE`). Le port et les gardes restent
  identiques (ADR-0015 : « seule la requête change »).
- `CLIENT` / rôle inconnu → portée vide (deny-by-default).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import Role, UserStatus


class SqlSalonScopeRepository:
    """Portée salon d'un compte, lue via SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def salon_ids_for(self, principal_id: uuid.UUID, role: str) -> frozenset[uuid.UUID]:
        """Salons du périmètre de ce compte ; `frozenset()` si aucun (ou rôle sans portée)."""

        if role == Role.MANAGER.value:
            stmt = select(models.Salon.id).where(models.Salon.owner_id == principal_id)
        elif role == Role.HAIRDRESSER.value:
            stmt = select(models.SalonMember.salon_id).where(
                models.SalonMember.user_id == principal_id,
                models.SalonMember.status == UserStatus.ACTIVE.value,
            )
        else:
            # CLIENT, ADMIN (portée plateforme, court-circuitée par AccessPolicy)
            # et tout rôle inconnu : aucune portée salon.
            return frozenset()

        return frozenset(self._session.scalars(stmt).all())


__all__ = ["SqlSalonScopeRepository"]
