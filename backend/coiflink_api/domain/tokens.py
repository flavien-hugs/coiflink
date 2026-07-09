"""Types de domaine décrivant les jetons émis à la connexion (ADR-0008).

Valeurs **pures** : ni la lib JWT ni la signature ne vivent ici (c'est un adapter
sortant, `adapters/outbound/security/jwt_token_service.py`). Le domaine reste
agnostique de PyJWT/HS256 — il ne connaît que la **forme** d'une paire de jetons
et des claims attendus.

Le format des claims (`sub`, `role`, `type`, `iat`, `exp`, `jti`) est un
**contrat inter-issue** partagé avec le RBAC (#12), qui consommera ces claims
pour identifier l'utilisateur courant. Aucun claim ne porte de PII (ni téléphone,
ni e-mail, ni nom) — cf. ADR-0013 / Security de la spec.
"""

from __future__ import annotations

from dataclasses import dataclass

# Valeurs du claim `type` : distingue un jeton d'accès (court) d'un refresh (long).
ACCESS = "access"
REFRESH = "refresh"


@dataclass(frozen=True)
class TokenClaims:
    """Claims décodés d'un JWT CoifLink (sans aucune PII).

    `sub` est l'identifiant du compte (UUID sérialisé en chaîne) ; `iat`/`exp`
    sont des timestamps UNIX (secondes). `type` vaut `access` ou `refresh`.
    """

    sub: str
    role: str
    type: str
    jti: str
    iat: int
    exp: int


@dataclass(frozen=True)
class TokenPair:
    """Paire de jetons renvoyée à une connexion (ou un rafraîchissement) valide.

    `expires_in` est la durée de vie **du jeton d'accès** en secondes (le refresh
    vit plus longtemps). `token_type` suit le schéma **Bearer** (`Authorization:
    Bearer <access_token>`).
    """

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


__all__ = ["TokenClaims", "TokenPair", "ACCESS", "REFRESH"]
