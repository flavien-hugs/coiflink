"""Port d'émission / décodage de jetons JWT (interface `typing.Protocol`, ADR-0008).

Abstrait la bibliothèque JWT (PyJWT en #10, cf. ADR-0013) et l'algorithme de
signature derrière un contrat stable, réutilisé par le RBAC (#12, décodage sur
les routes protégées). Le domaine et l'application ne dépendent que de ce port ;
seul l'adapter sortant connaît PyJWT/HS256 et le `JWT_SECRET`.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.tokens import TokenClaims, TokenPair


class TokenService(Protocol):
    """Contrat d'émission et de vérification des jetons d'accès / de refresh."""

    def issue_pair(self, user_id: uuid.UUID | str, role: str) -> TokenPair:
        """Émet une paire jeton d'accès (court) + refresh (long) pour ce compte."""
        ...

    def decode(self, token: str) -> TokenClaims:
        """Décode et **vérifie** un jeton (signature + `exp` + algorithme attendu).

        Lève `domain.errors.ExpiredToken` si `exp` est dépassé,
        `domain.errors.InvalidToken` pour toute autre invalidité (signature,
        altération, `alg` inattendu) — **sans** fuite du détail de la lib.
        """
        ...

    def verify_refresh(self, token: str) -> TokenClaims:
        """Décode un jeton et exige `type == "refresh"` ; lève `InvalidToken` sinon."""
        ...


__all__ = ["TokenService"]
