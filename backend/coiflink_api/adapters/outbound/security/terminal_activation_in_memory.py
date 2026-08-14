"""Adapter sortant : stockage **en mémoire** des défis d'activation de borne (US-8.1, #155).

Implémentation du port `TerminalActivationRepository` suffisante pour les tests et le
développement, calquée sur `otp_in_memory.py`. Un adapter Redis à TTL (ADR-0004) ou
une table dédiée sont **différés**. Le magasin étant un simple `dict` de process, il
n'est ni partagé entre instances ni persistant : un redémarrage invalide les codes
d'activation en cours (la borne est alors re-provisionnée — geste physique, sans
conséquence sur les bornes déjà activées, dont le secret vit en base).

Une **instance dédiée** est câblée sur `app.state.terminal_activation_repository`,
physiquement distincte des dépôts OTP d'inscription et de reset : un code
d'activation de borne ne peut jamais servir de code de reset (ou l'inverse).
"""

from __future__ import annotations

import uuid

from coiflink_api.domain.otp import OtpChallenge


class InMemoryTerminalActivationRepository:
    """Dépôt de défis d'activation en mémoire (dict par `device_id`)."""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, OtpChallenge] = {}

    def save(self, device_id: uuid.UUID, challenge: OtpChallenge) -> None:
        self._store[device_id] = challenge

    def find_by_code(self, code: str) -> tuple[uuid.UUID, OtpChallenge] | None:
        # Balayage linéaire : la borne ne connaît que le code, jamais son
        # `device_id`. Le parc de bornes d'un salon se compte en unités et
        # l'activation est un geste **physique** rare — ce n'est pas un chemin chaud.
        for device_id, challenge in self._store.items():
            if challenge.code == code:
                return device_id, challenge
        return None

    def delete(self, device_id: uuid.UUID) -> None:
        self._store.pop(device_id, None)


__all__ = ["InMemoryTerminalActivationRepository"]
