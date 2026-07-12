"""Adapter sortant : stockage **en mémoire** des défis OTP (ADR-0008).

Implémentation du port `OtpRepository` suffisante pour les tests et le
développement (#8/#11). Un adapter Redis à TTL (ADR-0004) ou une table dédiée
sont **différés**. Le magasin étant un simple `dict` de process, il n'est ni
partagé entre instances ni persistant.

Pour l'inscription (#8) l'OTP est **non bloquant** (limite bénigne). Pour la
**réinitialisation** (#11), l'OTP est **bloquant** : une **instance dédiée** est
câblée (`app.state.password_reset_otp_repository`), physiquement distincte de
celle de l'inscription. La limite mémoire (multi-instances) est documentée
(ADR-0012/0014) ; le passage à Redis est différé M5.
"""

from __future__ import annotations

from coiflink_api.domain.otp import OtpChallenge


class InMemoryOtpRepository:
    """Dépôt d'OTP en mémoire (dict par clé de destinataire)."""

    def __init__(self) -> None:
        self._store: dict[str, OtpChallenge] = {}

    def save(self, key: str, challenge: OtpChallenge) -> None:
        self._store[key] = challenge

    def get(self, key: str) -> OtpChallenge | None:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


__all__ = ["InMemoryOtpRepository"]
