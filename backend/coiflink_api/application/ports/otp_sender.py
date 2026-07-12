"""Port d'envoi d'OTP (interface `typing.Protocol`, ADR-0008).

L'envoi réel dépend de l'infra notifications (ADR-0006) livrée en **M5** : en
#8/#11, l'implémentation est un **stub** no-op. **Contrat de sécurité : une
implémentation ne journalise JAMAIS le code ni le destinataire (numéro, e-mail).**

La remise est **multi-canal** (#11) : le même contrat achemine un code par SMS
(inscription #8, téléphone) ou par e-mail (réinitialisation #11). Le `channel`
appartient à `domain.enums.NotificationChannel` (`SMS` / `EMAIL`) ; il vaut `SMS`
par défaut pour rester compatible avec l'appelant historique (#8).
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.enums import NotificationChannel


class OtpSender(Protocol):
    """Contrat d'acheminement d'un code OTP vers un destinataire (multi-canal)."""

    def send(
        self,
        recipient: str,
        code: str,
        channel: str = NotificationChannel.SMS.value,
    ) -> None:
        """Achemine `code` vers `recipient` via `channel`. Ne journalise rien."""
        ...


__all__ = ["OtpSender"]
