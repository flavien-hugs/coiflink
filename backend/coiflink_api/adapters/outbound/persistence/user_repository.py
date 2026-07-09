"""Adapter sortant : dépôt d'utilisateurs sur SQLAlchemy (ADR-0008/0009).

Implémente le port `UserRepository` avec une `Session` SQLAlchemy 2.0 sur le
modèle ORM `User` (`models.py`). Seul cet adapter connaît SQLAlchemy ; il mappe
l'entité de domaine `UserToCreate` ↔ le modèle ORM et retraduit les
violations d'unicité base en **erreurs de domaine** (jamais de fuite d'un détail
SQLAlchemy vers l'application).

Le champ métier `phone` est unique en base (`uq_users_phone`) ; l'e-mail
optionnel est unique partiel (`uq_users_email`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.errors import EmailAlreadyInUse, PhoneAlreadyInUse
from coiflink_api.domain.user import User, UserToCreate


class SqlUserRepository:
    """Dépôt d'utilisateurs adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def phone_exists(self, phone: str) -> bool:
        """Vrai si un compte porte déjà ce téléphone (forme canonique)."""

        stmt = select(models.User.id).where(models.User.phone == phone).limit(1)
        return self._session.scalar(stmt) is not None

    def find_by_phone(self, phone: str) -> UserCredentials | None:
        """Charge les identifiants du compte pour ce téléphone (E.164), sinon `None`."""

        stmt = select(models.User).where(models.User.phone == phone).limit(1)
        return _to_credentials(self._session.scalar(stmt))

    def find_by_email(self, email: str) -> UserCredentials | None:
        """Charge les identifiants du compte pour cet e-mail, sinon `None`."""

        stmt = select(models.User).where(models.User.email == email).limit(1)
        return _to_credentials(self._session.scalar(stmt))

    def find_by_id(self, user_id: uuid.UUID | str) -> UserCredentials | None:
        """Charge les identifiants du compte pour cet `id`, sinon `None`.

        Un `id` non convertible en UUID (jeton altéré) donne `None` — jamais
        d'erreur remontée à l'appelant.
        """

        try:
            pk = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            return None
        return _to_credentials(self._session.get(models.User, pk))

    def create(self, user: UserToCreate) -> User:
        """Insère l'utilisateur et retourne l'entité (avec `id`, `created_at`).

        Retraduit la violation de contrainte unique en erreur de domaine :
        `uq_users_phone` → `PhoneAlreadyInUse`, `uq_users_email` →
        `EmailAlreadyInUse`. Toute autre `IntegrityError` est propagée telle quelle.
        """

        row = models.User(
            full_name=user.full_name,
            phone=user.phone,
            email=user.email,
            password_hash=user.password_hash,
            role=user.role,
            status=user.status,
        )
        self._session.add(row)
        try:
            # `flush` déclenche l'INSERT (et donc les contraintes) sans committer :
            # le commit est piloté par la dépendance de session (`get_session`).
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            detail = str(getattr(exc, "orig", exc))
            if "uq_users_phone" in detail:
                raise PhoneAlreadyInUse(
                    "Ce numéro de téléphone est déjà associé à un compte."
                ) from exc
            if "uq_users_email" in detail:
                raise EmailAlreadyInUse(
                    "Cette adresse e-mail est déjà associée à un compte."
                ) from exc
            raise

        # Recharge les valeurs générées côté serveur (id, created_at, status...).
        self._session.refresh(row)
        return User(
            id=row.id,
            full_name=row.full_name,
            phone=row.phone,
            email=row.email,
            role=row.role,
            status=row.status,
            created_at=row.created_at,
        )


def _to_credentials(row: "models.User | None") -> UserCredentials | None:
    """Mappe une ligne ORM `User` vers `UserCredentials` (avec `password_hash`).

    Le `password_hash` reste **interne** : `UserCredentials` n'est jamais
    sérialisé dans une réponse HTTP (cf. `domain/credentials.py`).
    """

    if row is None:
        return None
    return UserCredentials(
        id=row.id,
        role=row.role,
        status=row.status,
        password_hash=row.password_hash,
    )


__all__ = ["SqlUserRepository"]
