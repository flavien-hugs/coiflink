"""Entités de domaine « utilisateur » et validation du nom (domaine pur).

Ces `dataclass` découplent l'application du modèle ORM SQLAlchemy
(`adapters/outbound/persistence/models.py`) : conformément à l'hexagonal
(ADR-0008), ni `domain/` ni `application/` n'importent SQLAlchemy.

`UserToCreate` porte **le condensat** (`password_hash`), jamais le mot de
passe en clair. `User` représente une entité déjà persistée (avec `id`)
et n'expose **aucun** secret.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import InvalidName

NAME_MAX_LENGTH = 255


def validate_name(name: str) -> str:
    """Valide et normalise (trim) le nom complet ; lève `InvalidName` sinon."""

    if not isinstance(name, str):
        raise InvalidName("Le nom est requis.")
    cleaned = name.strip()
    if not cleaned:
        raise InvalidName("Le nom est requis.")
    if len(cleaned) > NAME_MAX_LENGTH:
        raise InvalidName(
            f"Le nom ne doit pas dépasser {NAME_MAX_LENGTH} caractères."
        )
    return cleaned


@dataclass(frozen=True)
class UserToCreate:
    """Utilisateur prêt à être persisté (téléphone canonique, mot de passe haché)."""

    full_name: str
    phone: str
    password_hash: str
    email: str | None = None
    role: str = Role.CLIENT.value
    status: str = UserStatus.ACTIVE.value


@dataclass(frozen=True)
class User:
    """Utilisateur persisté, sans secret (ni mot de passe ni condensat)."""

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    role: str
    status: str
    created_at: datetime.datetime


__all__ = ["validate_name", "UserToCreate", "User", "NAME_MAX_LENGTH"]
