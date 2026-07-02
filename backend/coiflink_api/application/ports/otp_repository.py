"""Port de stockage des défis OTP (interface `typing.Protocol`, ADR-0008).

Permet de conserver un défi OTP hors du schéma relationnel (aucune migration en
#8). L'implémentation de #8 est **en mémoire** (tests/dev) ; un adapter Redis à
TTL ou une table dédiée sont **différés**. Une implémentation stocke le code
**haché** au repos (jamais en clair) — cf. spec §Security.
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.otp import OtpChallenge


class OtpRepository(Protocol):
    """Contrat de conservation d'un défi OTP par destinataire."""

    def save(self, phone: str, challenge: OtpChallenge) -> None:
        """Associe (ou remplace) le défi OTP courant pour ce téléphone."""
        ...

    def get(self, phone: str) -> OtpChallenge | None:
        """Retourne le défi OTP en cours pour ce téléphone, ou `None`."""
        ...

    def delete(self, phone: str) -> None:
        """Supprime tout défi OTP associé à ce téléphone (idempotent)."""
        ...


__all__ = ["OtpRepository"]
