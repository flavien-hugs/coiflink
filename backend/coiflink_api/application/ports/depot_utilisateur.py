"""Port de dépôt d'utilisateurs (interface `typing.Protocol`, ADR-0008).

Le cas d'usage `InscrireClient` déclare **ses besoins** de persistance via ce
port ; l'implémentation concrète (SQLAlchemy) vit dans `adapters/sortant/`. La
dépendance va vers l'intérieur : l'application ne connaît ni la Session ni le
modèle ORM.
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domaine.utilisateur import Utilisateur, UtilisateurACreer


class DepotUtilisateur(Protocol):
    """Contrat de persistance des comptes utilisateur."""

    def telephone_existe(self, telephone: str) -> bool:
        """Vrai si un compte porte déjà ce téléphone (forme canonique)."""
        ...

    def creer(self, utilisateur: UtilisateurACreer) -> Utilisateur:
        """Persiste et retourne l'entité créée (avec `id`, `created_at`).

        Doit lever `domaine.erreurs.TelephoneDejaUtilise` (resp.
        `EmailDejaUtilise`) si la contrainte d'unicité base est violée — garde-fou
        d'ultime recours contre une course concurrente.
        """
        ...


__all__ = ["DepotUtilisateur"]
