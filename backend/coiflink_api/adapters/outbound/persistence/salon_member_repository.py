"""Adapter sortant : persistance de l'appartenance employé↔salon (SQLAlchemy, #13/#150).

Implémente le port `SalonMemberRepository` sur une `Session` SQLAlchemy 2.0 et
les modèles ORM `SalonMember`/`User`. Seul cet adapter connaît SQLAlchemy ; il
retraduit la violation d'unicité `(salon_id, user_id)` en **erreur de domaine**
`EmployeeAlreadyInSalon` (jamais de fuite d'un détail SQLAlchemy vers
l'application).

Comme `SqlUserRepository`, l'écriture est `flush`ée **sans commit** : le commit
(ou le rollback) est piloté par la dépendance de session (`get_session`), ce qui
garantit l'atomicité de la création utilisateur + appartenance (#13) et de la
modification identité + champs pro (#150).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.employee import Employee
from coiflink_api.domain.enums import Role
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

    def list_for_salon(self, salon_id: uuid.UUID) -> tuple[Employee, ...]:
        """Liste les coiffeuses du salon, jointes à `users`, triées par nom."""

        rows = self._session.execute(
            select(models.SalonMember, models.User)
            .join(models.User, models.User.id == models.SalonMember.user_id)
            .where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.role == Role.HAIRDRESSER.value,
            )
            .order_by(models.User.full_name.asc())
        ).all()
        return tuple(_to_employee(member, user) for member, user in rows)

    def find_by_id(
        self, salon_id: uuid.UUID, user_id: uuid.UUID
    ) -> Employee | None:
        """Charge la coiffeuse `(salon_id, user_id)`, jointe à `users`, ou `None`."""

        row = self._session.execute(
            select(models.SalonMember, models.User)
            .join(models.User, models.User.id == models.SalonMember.user_id)
            .where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.user_id == user_id,
            )
            .limit(1)
        ).first()
        if row is None:
            return None
        member, user = row
        return _to_employee(member, user)

    def update_professional_fields(
        self,
        salon_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        specialties: str | None,
        hired_at: datetime.date | None,
    ) -> Employee | None:
        """Remplace `specialties`/`hired_at` de la coiffeuse ; `None` si hors salon."""

        member = self._session.scalar(
            select(models.SalonMember).where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.user_id == user_id,
            )
        )
        if member is None:
            return None
        member.specialties = specialties
        member.hired_at = hired_at
        self._session.flush()
        self._session.refresh(member)
        return _to_employee(member, self._session.get(models.User, user_id))

    def set_status(
        self, salon_id: uuid.UUID, user_id: uuid.UUID, status: str
    ) -> Employee | None:
        """Pose `salon_members.status` ; `None` si hors salon (jamais `users.status`)."""

        member = self._session.scalar(
            select(models.SalonMember).where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.user_id == user_id,
            )
        )
        if member is None:
            return None
        member.status = status
        self._session.flush()
        self._session.refresh(member)
        return _to_employee(member, self._session.get(models.User, user_id))


def _to_employee(member: models.SalonMember, user: models.User) -> Employee:
    return Employee(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        role=member.role,
        status=member.status,
        specialties=member.specialties,
        hired_at=member.hired_at,
        created_at=member.created_at,
    )


__all__ = ["SqlSalonMemberRepository"]
