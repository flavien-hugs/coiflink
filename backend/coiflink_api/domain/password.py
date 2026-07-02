"""Politique de mot de passe (domaine pur, ADR-0008).

Ce module ne fait **pas** le hachage : le hachage est un détail d'infrastructure
derrière le port `PasswordHasher` (cf. `application/ports/`). Il porte
uniquement la **règle métier** de validité du mot de passe en clair, avant tout
hachage (PRD §11.1). Le mot de passe en clair n'est **jamais** journalisé ni
inclus dans un message d'erreur.
"""

from __future__ import annotations

from coiflink_api.domain.errors import InvalidPassword

# Longueur minimale (recommandation OWASP ≥ 8). La borne haute protège la couche
# de hachage argon2 contre un abus de ressources (déni de service par mot de
# passe démesuré) tout en restant très permissive pour les usagers légitimes.
MIN_LENGTH = 8
MAX_LENGTH = 128


def validate_password(plain: str) -> None:
    """Valide le mot de passe en clair selon la politique ; lève sinon.

    Ne retourne rien (validation par effet). Le message d'erreur ne contient
    **jamais** la valeur du mot de passe.
    """

    if not isinstance(plain, str) or plain == "":
        raise InvalidPassword("Le mot de passe est requis.")
    if len(plain) < MIN_LENGTH:
        raise InvalidPassword(
            f"Le mot de passe doit contenir au moins {MIN_LENGTH} caractères."
        )
    if len(plain) > MAX_LENGTH:
        raise InvalidPassword(
            f"Le mot de passe ne doit pas dépasser {MAX_LENGTH} caractères."
        )


__all__ = ["validate_password", "MIN_LENGTH", "MAX_LENGTH"]
