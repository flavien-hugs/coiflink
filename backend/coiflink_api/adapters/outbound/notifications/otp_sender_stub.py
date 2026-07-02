"""Adapter sortant : **stub** d'envoi d'OTP (ADR-0006, envoi réel différé M5).

Implémente le port `OtpSender` sans réaliser d'envoi : l'infra notifications
(FCM + SMS via file Redis) est livrée en M5. **Aucune journalisation** du code ni
du numéro — invariant de sécurité (spec §Security, PRD §11.1/§11.3).
"""

from __future__ import annotations


class StubOtpSender:
    """Envoi d'OTP no-op (différé). Ne journalise ni le code ni le téléphone."""

    def send(self, phone: str, code: str) -> None:
        # Volontairement sans effet : ni I/O, ni log. L'adapter SMS concret
        # arrivera en M5 (ADR-0006). Les paramètres ne sont jamais journalisés.
        return None


__all__ = ["StubOtpSender"]
