"""Port de hachage de mot de passe (interface `typing.Protocol`, ADR-0008).

Abstrait l'algorithme de hachage (argon2 en #8, cf. ADR-0012) derrière un
contrat stable, réutilisé par la connexion (#10) et la réinitialisation (#11).
Le mot de passe en clair ne vit que le temps de l'appel `hash()`/`verify()`
et n'est **jamais** journalisé.
"""

from __future__ import annotations

from typing import Protocol


class PasswordHasher(Protocol):
    """Contrat de hachage/vérification de mot de passe."""

    def hash(self, plain: str) -> str:
        """Retourne un condensat salé du mot de passe en clair."""
        ...

    def verify(self, plain: str, hashed: str) -> bool:
        """Vrai si `plain` correspond à `hashed` ; faux sinon (sans lever)."""
        ...


__all__ = ["PasswordHasher"]
