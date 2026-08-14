"""Adapter sortant : persistance des **bornes terminal** (SQLAlchemy, US-8.1, #155).

Implémente le port `TerminalDeviceRepository`. **Encapsule** le fait qu'une borne est,
en base, un **compte de service** `users` (rôle `TERMINAL`) + un rattachement
`salon_members` (portée mono-salon) — l'application n'en sait rien (ADR-0041, choix
d'architecture n°1 : réutiliser toute la chaîne `Principal` existante plutôt que de
dupliquer un mécanisme d'authentification parallèle).

Conventions de données du device (invariants documentés ici) :
- `users.id` = identifiant public du device (`device_id`), généré côté application
  pour être **connu avant** l'insert (il alimente la sentinelle `phone`) ;
- `users.phone` = `id.hex` — **valeur sentinelle** inerte (32 caractères hexa, tient
  dans `String(32)`, unique par construction). Innocuité : `normalize_phone` produit
  **toujours** une chaîne commençant par `+` (`domain/phone.py`) et le login/reset ne
  résolvent que des téléphones normalisés ou des e-mails — la sentinelle est donc
  **inatteignable** depuis `/auth/login`, le reset OTP et toute recherche par téléphone ;
- `users.password_hash` = argon2id du secret device (jamais le secret en clair) ;
- `users.full_name` = libellé de borne (pas une PII), `email = NULL`.

Comme les autres dépôts, les écritures sont `flush`ées **sans commit** : le commit
(ou le rollback) est piloté par `get_session`, garantissant l'atomicité des deux
lignes (compte + appartenance).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.terminal_device import (
    TerminalDevice,
    TerminalDeviceCredentials,
    TerminalDeviceToCreate,
)


class SqlTerminalDeviceRepository:
    """Dépôt de bornes terminal adossé à une `Session` SQLAlchemy (compte de service)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, device: TerminalDeviceToCreate) -> TerminalDevice:
        """Insère le compte de service `TERMINAL` + son rattachement `salon_members`.

        `device_id` est généré ici (`uuid4`) pour être connu **avant** l'insert et
        alimenter la sentinelle `phone = id.hex`. Les deux lignes partagent la
        `Session` : `flush()` matérialise les contraintes sans committer (commit
        piloté par `get_session`), rollback atomique si l'une échoue.
        """

        device_id = uuid.uuid4()
        user_row = models.User(
            id=device_id,
            full_name=device.label,
            # Sentinelle inerte (32 hex) : un device n'a pas de téléphone réel, et
            # cette valeur est inatteignable par les flux téléphone (voir docstring).
            phone=device_id.hex,
            email=None,
            password_hash=device.password_hash,
            role=Role.TERMINAL.value,
            status=UserStatus.ACTIVE.value,
        )
        self._session.add(user_row)
        # Flush explicite pour matérialiser la ligne `users` AVANT d'insérer
        # `salon_members.user_id` (FK). SQLAlchemy 2.x détermine l'ordre de
        # flush à partir des `relationship()` ORM ; sans relation déclarée entre
        # `User` et `SalonMember`, il peut inverser l'ordre et provoquer une
        # violation de contrainte (`fk_salon_members_user_id`).
        self._session.flush()
        member_row = models.SalonMember(
            salon_id=device.salon_id,
            user_id=device_id,
            role=Role.TERMINAL.value,
            status=UserStatus.ACTIVE.value,
        )
        self._session.add(member_row)
        self._session.flush()
        self._session.refresh(user_row)
        return TerminalDevice(
            id=user_row.id,
            salon_id=device.salon_id,
            label=user_row.full_name,
            status=user_row.status,
            created_at=user_row.created_at,
        )

    def list_for_salon(self, salon_id: uuid.UUID) -> tuple[TerminalDevice, ...]:
        """Liste les bornes du salon (jointure `salon_members` `TERMINAL` ↔ `users`)."""

        rows = self._session.execute(
            select(models.SalonMember, models.User)
            .join(models.User, models.User.id == models.SalonMember.user_id)
            .where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.role == Role.TERMINAL.value,
            )
            .order_by(models.User.full_name.asc())
        ).all()
        return tuple(
            _to_device(salon_id, user) for _member, user in rows
        )

    def find_by_id(
        self, salon_id: uuid.UUID, device_id: uuid.UUID
    ) -> TerminalDevice | None:
        """Charge la borne `(salon_id, device_id)` (filtre salon **et** device)."""

        row = self._session.execute(
            select(models.User)
            .join(
                models.SalonMember,
                models.SalonMember.user_id == models.User.id,
            )
            .where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.role == Role.TERMINAL.value,
                models.User.id == device_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return _to_device(salon_id, row)

    def find_credentials(
        self, device_id: uuid.UUID
    ) -> TerminalDeviceCredentials | None:
        """Charge le credential d'une borne (scopé `device_id`, rôle `TERMINAL` exigé)."""

        row = self._session.execute(
            select(models.User, models.SalonMember.salon_id)
            .join(
                models.SalonMember,
                models.SalonMember.user_id == models.User.id,
            )
            .where(
                models.User.id == device_id,
                models.User.role == Role.TERMINAL.value,
                models.SalonMember.role == Role.TERMINAL.value,
            )
            .limit(1)
        ).first()
        if row is None:
            return None
        user, salon_id = row
        return TerminalDeviceCredentials(
            id=user.id,
            salon_id=salon_id,
            password_hash=user.password_hash,
            status=user.status,
        )

    def set_password_hash(self, device_id: uuid.UUID, password_hash: str) -> None:
        """Écrase le condensat de la borne (activation #155) — jamais le secret en clair.

        Même patron d'écriture que `revoke()` : charge la ligne `users`, mute,
        `flush()` sans commit (commit piloté par `get_session`).
        """

        user = self._session.get(models.User, device_id)
        if user is None:  # pragma: no cover - device_id already resolved by caller
            return
        user.password_hash = password_hash
        self._session.flush()

    def revoke(
        self, salon_id: uuid.UUID, device_id: uuid.UUID
    ) -> TerminalDevice | None:
        """Révocation logique : `users.status = SUSPENDED` + `salon_members.status = INACTIVE`.

        Défense en profondeur — le premier coupe l'accès à la requête suivante
        (`get_current_principal`), le second vide la portée. `None` si la borne
        n'existe pas dans ce salon (le cas d'usage lève `TerminalDeviceNotFound`).
        """

        member = self._session.execute(
            select(models.SalonMember).where(
                models.SalonMember.salon_id == salon_id,
                models.SalonMember.user_id == device_id,
                models.SalonMember.role == Role.TERMINAL.value,
            )
        ).scalar_one_or_none()
        if member is None:
            return None
        user = self._session.get(models.User, device_id)
        if user is None:  # pragma: no cover - incohérence FK, ne devrait pas arriver
            return None
        user.status = UserStatus.SUSPENDED.value
        member.status = UserStatus.INACTIVE.value
        self._session.flush()
        self._session.refresh(user)
        return _to_device(salon_id, user)


def _to_device(salon_id: uuid.UUID, user: models.User) -> TerminalDevice:
    """Mappe une ligne `users` (compte de service `TERMINAL`) vers `TerminalDevice`.

    Ne recopie **jamais** `password_hash` : `TerminalDevice` est la vue exposée au
    gérant, sans aucun secret.
    """

    return TerminalDevice(
        id=user.id,
        salon_id=salon_id,
        label=user.full_name,
        status=user.status,
        created_at=user.created_at,
    )


__all__ = ["SqlTerminalDeviceRepository"]
