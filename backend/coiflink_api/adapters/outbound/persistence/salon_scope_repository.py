"""Adapter sortant : lecture SQL de la **portée salon** d'un compte (§11.2, #12).

Implémente le port `SalonScopeRepository` sur une `Session` SQLAlchemy. C'est la
**seule** source d'autorité de l'isolation multi-salons : la portée est lue en
base, jamais déduite d'un paramètre de requête.

Rattachements exploités (schéma existant — #12 n'ajoute **aucune** migration) :

- `MANAGER` → `salons.owner_id` : rattachement **réel** du gérant à ses salons ;
- `HAIRDRESSER` → `DISTINCT appointments.salon_id WHERE hairdresser_id = …`.
  Le schéma n'a **pas encore** de table d'appartenance employé↔salon (elle arrive
  avec #13) : la portée du coiffeur est donc dérivée des rendez-vous qui lui sont
  **assignés**, ce qui est la lecture littérale du PRD §11.2 (« son planning ou les
  rendez-vous qui lui sont assignés »). **Limite assumée et documentée**
  (ADR-0015) : un coiffeur sans aucun RDV assigné a une portée **vide** — il ne
  voit rien (sûr, mais insuffisant à terme). Quand #13 livrera la table, seule
  cette requête change ; le port et les gardes restent identiques.
- `CLIENT` / rôle inconnu → portée vide (deny-by-default).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import Role


class SqlSalonScopeRepository:
    """Portée salon d'un compte, lue via SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def salon_ids_for(self, principal_id: uuid.UUID, role: str) -> frozenset[uuid.UUID]:
        """Salons du périmètre de ce compte ; `frozenset()` si aucun (ou rôle sans portée)."""

        if role == Role.MANAGER.value:
            stmt = select(models.Salon.id).where(models.Salon.owner_id == principal_id)
        elif role == Role.HAIRDRESSER.value:
            stmt = (
                select(models.Appointment.salon_id)
                .where(models.Appointment.hairdresser_id == principal_id)
                .distinct()
            )
        else:
            # CLIENT, ADMIN (portée plateforme, court-circuitée par AccessPolicy)
            # et tout rôle inconnu : aucune portée salon.
            return frozenset()

        return frozenset(self._session.scalars(stmt).all())


__all__ = ["SqlSalonScopeRepository"]
