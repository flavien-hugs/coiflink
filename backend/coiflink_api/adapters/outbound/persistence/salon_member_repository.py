"""Adapter sortant : écriture de l'appartenance employé↔salon (SQLAlchemy, #13).

Implémente le port `SalonMemberRepository` sur une `Session` SQLAlchemy 2.0 et
le modèle ORM `SalonMember` (`salon_members`). Seul cet adapter connaît
SQLAlchemy ; il retraduit la violation d'unicité `(salon_id, user_id)` en
**erreur de domaine** `EmployeeAlreadyInSalon` (jamais de fuite d'un détail
SQLAlchemy vers l'application).

Comme `SqlUserRepository`, l'écriture est `flush`ée **sans commit** : le commit
(ou le rollback) est piloté par la dépendance de session (`get_session`), ce qui
garantit l'atomicité de la création utilisateur + appartenance (#13).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.errors import EmployeeAlreadyInSalon
from coiflink_api.domain.membership import SalonMembershipToCreate


class SqlSalonMemberRepository:
    """Dépôt d'appartenances employé↔salon adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_member(self, membership: SalonMembershipToCreate) -> None:
        """Insère l'appartenance ; `EmployeeAlreadyInSalon` si `(salon, user)` existe.

        Retraduit `uq_salon_members_salon_user` → `EmployeeAlreadyInSalon`. Toute
        autre `IntegrityError` (FK salon/user manquant, valeur hors `CHECK`) est
        propagée telle quelle : elle signale une incohérence de programmation, pas
        un doublon métier.
        """

        row = models.SalonMember(
            salon_id=membership.salon_id,
            user_id=membership.user_id,
            role=membership.role,
            status=membership.status,
        )
        self._session.add(row)
        try:
            # `flush` déclenche l'INSERT (et les contraintes) sans committer.
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            detail = str(getattr(exc, "orig", exc))
            if "uq_salon_members_salon_user" in detail:
                raise EmployeeAlreadyInSalon(
                    "Cet employé est déjà rattaché à ce salon."
                ) from exc
            raise


__all__ = ["SqlSalonMemberRepository"]
