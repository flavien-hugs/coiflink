"""Port d'anti-bruteforce sur les connexions (interface `typing.Protocol`, ADR-0008).

Le cas d'usage `AuthenticateUser` (#10) déclare via ce port son besoin de
**limiter les échecs** de connexion (§11.1). L'implémentation concrète — d'abord
**en mémoire** (`adapters/outbound/security/login_rate_limiter_memory.py`), un
adapter Redis étant différé (ADR-0013) — reste inconnue de l'application.

`key` est une clé opaque construite par le cas d'usage (identifiant normalisé +
IP client, cf. ADR-0013) : le port ne connaît ni le format de la clé ni l'IP.
"""

from __future__ import annotations

from typing import Protocol


class LoginRateLimiter(Protocol):
    """Contrat de limitation des tentatives de connexion en échec."""

    def check(self, key: str) -> None:
        """Ne fait rien si la clé n'est pas verrouillée ; lève sinon.

        Lève `domain.errors.TooManyLoginAttempts` (avec un `retry_after` indicatif)
        quand le seuil d'échecs a été atteint et que le verrou temporisé court.
        """
        ...

    def record_failure(self, key: str) -> None:
        """Enregistre un échec de connexion pour cette clé (fenêtre glissante)."""
        ...

    def reset(self, key: str) -> None:
        """Réinitialise le compteur pour cette clé (appelé sur connexion réussie)."""
        ...


__all__ = ["LoginRateLimiter"]
