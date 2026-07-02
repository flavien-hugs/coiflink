"""Politique de mot de passe (domaine pur, ADR-0008).

Ce module ne fait **pas** le hachage : le hachage est un détail d'infrastructure
derrière le port `HacheurMotDePasse` (cf. `application/ports/`). Il porte
uniquement la **règle métier** de validité du mot de passe en clair, avant tout
hachage (PRD §11.1). Le mot de passe en clair n'est **jamais** journalisé ni
inclus dans un message d'erreur.
"""

from __future__ import annotations

from coiflink_api.domaine.erreurs import MotDePasseInvalide

# Longueur minimale (recommandation OWASP ≥ 8). La borne haute protège la couche
# de hachage argon2 contre un abus de ressources (déni de service par mot de
# passe démesuré) tout en restant très permissive pour les usagers légitimes.
LONGUEUR_MIN = 8
LONGUEUR_MAX = 128


def valider_mot_de_passe(clair: str) -> None:
    """Valide le mot de passe en clair selon la politique ; lève sinon.

    Ne retourne rien (validation par effet). Le message d'erreur ne contient
    **jamais** la valeur du mot de passe.
    """

    if not isinstance(clair, str) or clair == "":
        raise MotDePasseInvalide("Le mot de passe est requis.")
    if len(clair) < LONGUEUR_MIN:
        raise MotDePasseInvalide(
            f"Le mot de passe doit contenir au moins {LONGUEUR_MIN} caractères."
        )
    if len(clair) > LONGUEUR_MAX:
        raise MotDePasseInvalide(
            f"Le mot de passe ne doit pas dépasser {LONGUEUR_MAX} caractères."
        )


__all__ = ["valider_mot_de_passe", "LONGUEUR_MIN", "LONGUEUR_MAX"]
