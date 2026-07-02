"""Adapter sortant : stockage **en mémoire** des défis OTP (ADR-0008).

Implémentation du port `DepotOtp` suffisante pour les tests et le développement
(#8). Un adapter Redis à TTL (ADR-0004) ou une table dédiée sont **différés**.
Le magasin étant un simple `dict` de process, il n'est ni partagé entre
instances ni persistant — acceptable tant que l'OTP est une capacité non
bloquante (envoi réel en M5).
"""

from __future__ import annotations

from coiflink_api.domaine.otp import DefiOtp


class DepotOtpMemoire:
    """Dépôt d'OTP en mémoire (dict par téléphone)."""

    def __init__(self) -> None:
        self._store: dict[str, DefiOtp] = {}

    def enregistrer(self, telephone: str, defi: DefiOtp) -> None:
        self._store[telephone] = defi

    def recuperer(self, telephone: str) -> DefiOtp | None:
        return self._store.get(telephone)

    def supprimer(self, telephone: str) -> None:
        self._store.pop(telephone, None)


__all__ = ["DepotOtpMemoire"]
