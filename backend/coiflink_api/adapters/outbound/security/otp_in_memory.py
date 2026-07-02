"""Adapter sortant : stockage **en mémoire** des défis OTP (ADR-0008).

Implémentation du port `OtpRepository` suffisante pour les tests et le
développement (#8). Un adapter Redis à TTL (ADR-0004) ou une table dédiée sont
**différés**. Le magasin étant un simple `dict` de process, il n'est ni partagé
entre instances ni persistant — acceptable tant que l'OTP est une capacité non
bloquante (envoi réel en M5).
"""

from __future__ import annotations

from coiflink_api.domain.otp import OtpChallenge


class InMemoryOtpRepository:
    """Dépôt d'OTP en mémoire (dict par téléphone)."""

    def __init__(self) -> None:
        self._store: dict[str, OtpChallenge] = {}

    def save(self, phone: str, challenge: OtpChallenge) -> None:
        self._store[phone] = challenge

    def get(self, phone: str) -> OtpChallenge | None:
        return self._store.get(phone)

    def delete(self, phone: str) -> None:
        self._store.pop(phone, None)


__all__ = ["InMemoryOtpRepository"]
