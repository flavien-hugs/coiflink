"""Entité de domaine interne portant le **condensat** de mot de passe (ADR-0008).

L'entité publique `User` (`domain/user.py`) exclut **volontairement** le
`password_hash` : elle est renvoyée aux clients et ne doit jamais transporter de
secret. La **connexion** (#10) a pourtant besoin du condensat pour appeler
`PasswordHasher.verify`. `UserCredentials` comble ce besoin : c'est une entité
**strictement interne** — jamais sérialisée dans une réponse HTTP.

Elle ne porte que ce qui est nécessaire à l'authentification et au
rafraîchissement : l'identifiant du compte, son `role`, son `status`
(seuls les comptes `ACTIVE` peuvent se connecter) et le `password_hash`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class UserCredentials:
    """Données d'authentification d'un compte — **jamais** renvoyées au client.

    Porte le `password_hash` (nécessaire à `verify`) : à n'utiliser que dans la
    couche application/adapters de connexion, jamais dans un schéma de réponse.
    """

    id: uuid.UUID
    role: str
    status: str
    password_hash: str


__all__ = ["UserCredentials"]
