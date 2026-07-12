"""Adapter sortant : **stub** d'envoi d'OTP (ADR-0006, envoi réel différé M5).

Implémente le port `OtpSender` sans réaliser d'envoi : l'infra notifications
(FCM + SMS via file Redis, e-mail transactionnel) est livrée en M5. **Aucune
journalisation** du code, du destinataire ni du canal — invariant de sécurité
(spec §Security, PRD §11.1/§11.3).

Le stub est **multi-canal** (#11) : il ignore le `channel` (SMS ou e-mail) et ne
fait rien dans tous les cas. Seul le **contrat de canal** est posé ici ;
l'acheminement réel (SMS agrégateur, e-mail transactionnel) arrive en M5.
"""

from __future__ import annotations

from coiflink_api.domain.enums import NotificationChannel


class StubOtpSender:
    """Envoi d'OTP no-op (différé). Ne journalise ni le code, ni le destinataire, ni le canal."""

    def send(
        self,
        recipient: str,
        code: str,
        channel: str = NotificationChannel.SMS.value,
    ) -> None:
        # Volontairement sans effet : ni I/O, ni log. Les adapters concrets
        # (SMS / e-mail) arriveront en M5 (ADR-0006). Les paramètres — dont le
        # code et le destinataire — ne sont jamais journalisés.
        return None


__all__ = ["StubOtpSender"]
