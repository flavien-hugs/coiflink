"""Adapter sortant : hachage de mot de passe **argon2** (ADR-0012).

Implémente le port `HacheurMotDePasse` avec `argon2-cffi`. **argon2id** est
recommandé par l'OWASP et évite la troncature silencieuse à 72 octets de bcrypt.
Les paramètres de coût sont ceux, sûrs par défaut, de `PasswordHasher` (non
secrets) ; ils restent compatibles du budget API < 3 s (PRD §12.1).

Seul cet adapter connaît argon2 : le domaine et l'application n'en dépendent pas
(hexagonal, ADR-0008). Le mot de passe en clair n'est jamais journalisé.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    HashingError,
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)


class HacheurArgon2:
    """Hacheur de mot de passe basé sur argon2id (`argon2-cffi`)."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        # PasswordHasher() utilise argon2id avec des paramètres de coût sûrs.
        self._ph = hasher if hasher is not None else PasswordHasher()

    def hacher(self, clair: str) -> str:
        """Retourne le condensat argon2 (salé) du mot de passe en clair."""

        try:
            return self._ph.hash(clair)
        except HashingError as exc:  # pragma: no cover - défaillance lib/mémoire
            # Ne jamais inclure le clair dans le message d'erreur.
            raise RuntimeError("Échec du hachage du mot de passe.") from exc

    def verifier(self, clair: str, condensat: str) -> bool:
        """Vrai si `clair` correspond à `condensat` ; faux sinon (sans lever)."""

        try:
            return self._ph.verify(condensat, clair)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


__all__ = ["HacheurArgon2"]
