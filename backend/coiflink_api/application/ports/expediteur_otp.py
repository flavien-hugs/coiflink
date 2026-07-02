"""Port d'envoi d'OTP (interface `typing.Protocol`, ADR-0008).

L'envoi réel (SMS) dépend de l'infra notifications (ADR-0006) livrée en **M5** :
en #8, l'implémentation est un **stub** no-op. **Contrat de sécurité : une
implémentation ne journalise JAMAIS le code ni le numéro de téléphone.**
"""

from __future__ import annotations

from typing import Protocol


class ExpediteurOtp(Protocol):
    """Contrat d'acheminement d'un code OTP vers un destinataire."""

    def envoyer(self, telephone: str, code: str) -> None:
        """Achemine `code` vers `telephone`. Ne journalise ni l'un ni l'autre."""
        ...


__all__ = ["ExpediteurOtp"]
