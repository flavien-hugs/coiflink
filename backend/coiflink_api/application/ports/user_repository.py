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

    def find_user_by_id(self, user_id: uuid.UUID | str) -> User | None:
        """Retourne l'entité **publique** (sans condensat) du compte, sinon `None`.

        Utilisé par `GET /auth/me` (#12) : contrairement à `find_by_id`, l'entité
        renvoyée est sérialisable (aucun secret). Retourne `None` — jamais une
        exception — si l'`id` est inconnu ou illisible (jeton altéré).
        """
        ...

    def update_password(
        self, user_id: uuid.UUID | str, new_password_hash: str
    ) -> None:
        """Remplace le `password_hash` du compte `user_id` (réinitialisation, #11).

        Invariant de sécurité : **ne reçoit qu'un condensat**, jamais un mot de
        passe en clair (le hachage est fait en amont par `PasswordHasher.hash`).
        En pratique l'`updated_at` du compte est rafraîchi. Idempotent si l'`id`
        n'existe pas (aucune ligne mise à jour) — le cas d'usage a déjà validé
        l'OTP avant d'appeler cette méthode.
        """
        ...


__all__ = ["UserRepository"]
