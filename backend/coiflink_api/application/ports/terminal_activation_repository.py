"""Port de stockage des défis d'**activation de borne** (`Protocol`, US-8.1, #155).

Conserve, hors du schéma relationnel (aucune migration — comme les défis OTP de
#8/#11), le **code d'activation à 6 chiffres** émis au provisioning d'une borne et
échangé une seule fois contre son secret réel (`ActivateTerminalDevice`).

Le défi réutilise tel quel `domain/otp.py::OtpChallenge` : mêmes propriétés
(longueur, expiration, usage unique via `consumed`, limite d'essais, comparaison
en temps constant). Seule la **clé** change — un `device_id`, pas un destinataire
(téléphone/e-mail) — d'où un port dédié plutôt qu'une réutilisation d'`OtpRepository` :
un code d'activation de borne ne peut jamais servir de code de reset (ou l'inverse).

L'implémentation de #155 est **en mémoire** (tests/dev) ; un adapter Redis à TTL ou
une table dédiée sont **différés** (ADR-0004/ADR-0008).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.otp import OtpChallenge


class TerminalActivationRepository(Protocol):
    """Contrat de conservation d'un défi d'activation par borne."""

    def save(self, device_id: uuid.UUID, challenge: OtpChallenge) -> None:
        """Associe (ou remplace) le défi d'activation courant pour cette borne."""
        ...

    def find_by_code(self, code: str) -> tuple[uuid.UUID, OtpChallenge] | None:
        """Résout `(device_id, challenge)` dont le défi porte ce code exact.

        Recherche PAR VALEUR (pas par device_id) : la borne ne connaît que le code
        à ce stade, jamais son device_id. Ne filtre PAS sur expiry/consumed — c'est
        le rôle du cas d'usage (via `verify_otp_challenge`), pour un comportement
        uniforme avec le flux OTP de reset mot de passe. `None` si aucun défi ne
        porte ce code.
        """
        ...

    def delete(self, device_id: uuid.UUID) -> None:
        """Supprime le défi d'activation de cette borne (idempotent)."""
        ...


__all__ = ["TerminalActivationRepository"]
