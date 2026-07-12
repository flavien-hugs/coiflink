"""Port de stockage des défis OTP (interface `typing.Protocol`, ADR-0008).

Permet de conserver un défi OTP hors du schéma relationnel (aucune migration en
#8). L'implémentation de #8 est **en mémoire** (tests/dev) ; un adapter Redis à
TTL ou une table dédiée sont **différés**. Une implémentation stocke le code
**haché** au repos (jamais en clair) — cf. spec §Security.

La clé (`key`) est un identifiant opaque de destinataire : un **téléphone E.164**
à l'inscription (#8) ou un **e-mail** à la réinitialisation (#11, keyée par
e-mail comme par téléphone). Le contrat est agnostique du canal. La
réinitialisation (#11) utilise une **instance dédiée**, distincte de celle de
l'inscription : un OTP d'inscription ne peut jamais servir à un reset (ou
l'inverse).
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.otp import OtpChallenge


class OtpRepository(Protocol):
    """Contrat de conservation d'un défi OTP par destinataire."""

    def save(self, key: str, challenge: OtpChallenge) -> None:
        """Associe (ou remplace) le défi OTP courant pour cette clé."""
        ...

    def get(self, key: str) -> OtpChallenge | None:
        """Retourne le défi OTP en cours pour cette clé, ou `None`."""
        ...

    def delete(self, key: str) -> None:
        """Supprime tout défi OTP associé à cette clé (idempotent)."""
        ...


__all__ = ["OtpRepository"]
