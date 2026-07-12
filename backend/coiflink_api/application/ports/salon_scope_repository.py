"""Port de lecture de la **portée salon** d'un compte (`Protocol`, ADR-0008, #12).

C'est le port de l'**isolation multi-salons** (PRD §11.2) : il répond à la seule
question dont la politique d'autorisation a besoin — « sur quels salons ce compte
a-t-il une portée ? ». La réponse vient **toujours de la base**, jamais d'un
paramètre client : le `salon_id` d'une requête n'est qu'une **cible à valider**
contre cette portée.

L'application ne connaît que ce contrat ; l'implémentation SQL vit dans
`adapters/outbound/persistence/salon_scope_repository.py`.
"""

from __future__ import annotations

import uuid
from typing import Protocol


class SalonScopeRepository(Protocol):
    """Contrat de lecture de la portée salon d'un compte."""

    def salon_ids_for(self, principal_id: uuid.UUID, role: str) -> frozenset[uuid.UUID]:
        """Salons sur lesquels ce compte a une portée (PRD §11.2).

        - `MANAGER` : les salons dont il est **propriétaire** (`salons.owner_id`) ;
        - `HAIRDRESSER` : les salons de son **périmètre** (RDV assignés, cf.
          ADR-0015 — l'implémentation changera avec la table d'appartenance de #13,
          **sans** changer ce port) ;
        - `CLIENT` : ensemble **vide** — un client n'a pas de portée *salon* ; il
          accède à *ses* rendez-vous, pas aux données d'un salon ;
        - rôle inconnu : ensemble **vide** (deny-by-default).

        L'`ADMIN` n'appelle pas ce port : sa portée est la plateforme entière
        (`SalonScope.platform()`), ce qui évite une requête inutile.
        """
        ...


__all__ = ["SalonScopeRepository"]
