"""Port de dépôt d'utilisateurs (interface `typing.Protocol`, ADR-0008).

Le cas d'usage `RegisterClient` déclare **ses besoins** de persistance via ce
port ; l'implémentation concrète (SQLAlchemy) vit dans `adapters/outbound/`. La
dépendance va vers l'intérieur : l'application ne connaît ni la Session ni le
modèle ORM.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.user import User, UserToCreate


class UserRepository(Protocol):
    """Contrat de persistance des comptes utilisateur."""

    def phone_exists(self, phone: str) -> bool:
        """Vrai si un compte porte déjà ce téléphone (forme canonique)."""
        ...

    def create(self, user: UserToCreate) -> User:
        """Persiste et retourne l'entité créée (avec `id`, `created_at`).

        Doit lever `domain.errors.PhoneAlreadyInUse` (resp.
        `EmailAlreadyInUse`) si la contrainte d'unicité base est violée — garde-fou
        d'ultime recours contre une course concurrente.
        """
        ...

    def find_by_phone(self, phone: str) -> UserCredentials | None:
        """Retourne les identifiants du compte pour ce téléphone (E.164), sinon `None`.

        Utilisé par la **connexion** (#10) : l'entité renvoyée porte le
        `password_hash` (nécessaire à `verify`) — elle n'est jamais sérialisée.
        """
        ...

    def find_by_email(self, email: str) -> UserCredentials | None:
        """Retourne les identifiants du compte pour cet e-mail, sinon `None`."""
        ...

    def find_by_id(self, user_id: uuid.UUID | str) -> UserCredentials | None:
        """Retourne les identifiants du compte pour cet `id`, sinon `None`.

        Utilisé au **rafraîchissement** (#10) pour relire `role`/`status` courants
        et refuser un compte devenu non `ACTIVE`.
        """
        ...


__all__ = ["UserRepository"]
