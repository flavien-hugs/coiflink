"""Entités de domaine « utilisateur » et validation du nom (domaine pur).

Ces `dataclass` découplent l'application du modèle ORM SQLAlchemy
(`adapters/sortant/persistance/modeles.py`) : conformément à l'hexagonal
(ADR-0008), ni `domaine/` ni `application/` n'importent SQLAlchemy. Le champ
métier `telephone` correspond à la colonne `phone` (mappage assuré par l'adapter
de persistance).

`UtilisateurACreer` porte **le condensat** (`password_hash`), jamais le mot de
passe en clair. `Utilisateur` représente une entité déjà persistée (avec `id`)
et n'expose **aucun** secret.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domaine.enums import Role, UserStatus
from coiflink_api.domaine.erreurs import NomInvalide

LONGUEUR_MAX_NOM = 255


def valider_nom(nom: str) -> str:
    """Valide et normalise (trim) le nom complet ; lève `NomInvalide` sinon."""

    if not isinstance(nom, str):
        raise NomInvalide("Le nom est requis.")
    nettoye = nom.strip()
    if not nettoye:
        raise NomInvalide("Le nom est requis.")
    if len(nettoye) > LONGUEUR_MAX_NOM:
        raise NomInvalide(
            f"Le nom ne doit pas dépasser {LONGUEUR_MAX_NOM} caractères."
        )
    return nettoye


@dataclass(frozen=True)
class UtilisateurACreer:
    """Utilisateur prêt à être persisté (téléphone canonique, mot de passe haché)."""

    full_name: str
    telephone: str
    password_hash: str
    email: str | None = None
    role: str = Role.CLIENT.value
    status: str = UserStatus.ACTIVE.value


@dataclass(frozen=True)
class Utilisateur:
    """Utilisateur persisté, sans secret (ni mot de passe ni condensat)."""

    id: uuid.UUID
    full_name: str
    telephone: str
    email: str | None
    role: str
    status: str
    created_at: datetime.datetime


__all__ = ["valider_nom", "UtilisateurACreer", "Utilisateur", "LONGUEUR_MAX_NOM"]
