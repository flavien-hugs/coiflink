"""Adapter sortant : anti-bruteforce de connexion **en mémoire** (ADR-0013).

Implémente le port `LoginRateLimiter` avec une **fenêtre glissante** d'échecs par
clé (identifiant normalisé + IP, construite par le cas d'usage). Au-delà du seuil
sur la fenêtre, la clé est **verrouillée** pour une durée temporisée : `check`
lève alors `TooManyLoginAttempts` (→ `429` + `Retry-After`). Un succès de
connexion appelle `reset` et efface le compteur.

L'horloge est **injectable** (tests déterministes). Le magasin est un simple
`dict` de process : ni partagé entre workers/instances, ni persistant — cohérent
avec l'OTP en mémoire de #8 ; un adapter **Redis** à TTL est **différé** (ADR-0013).
La purge est **paresseuse** (au fil des accès à une clé), suffisante au MVP.
"""

from __future__ import annotations

import datetime
import math
from typing import Callable

from coiflink_api.domain.errors import TooManyLoginAttempts


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


class InMemoryLoginRateLimiter:
    """Limiteur d'échecs de connexion en mémoire (fenêtre glissante + verrou)."""

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window: datetime.timedelta = datetime.timedelta(seconds=300),
        lockout: datetime.timedelta = datetime.timedelta(seconds=900),
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window
        self._lockout = lockout
        self._clock = clock if clock is not None else _utc_now
        # clé -> horodatages des échecs récents (dans la fenêtre).
        self._failures: dict[str, list[datetime.datetime]] = {}
        # clé -> instant de fin de verrou.
        self._locked_until: dict[str, datetime.datetime] = {}

    def check(self, key: str) -> None:
        """Lève `TooManyLoginAttempts` si la clé est verrouillée, sinon ne fait rien."""

        now = self._clock()
        locked_until = self._locked_until.get(key)
        if locked_until is None:
            return
        if now < locked_until:
            retry_after = max(1, math.ceil((locked_until - now).total_seconds()))
            raise TooManyLoginAttempts(
                "Trop de tentatives de connexion. Réessayez plus tard.",
                retry_after=retry_after,
            )
        # Verrou expiré : on repart d'un compteur propre.
        self._locked_until.pop(key, None)
        self._failures.pop(key, None)

    def record_failure(self, key: str) -> None:
        """Enregistre un échec ; verrouille la clé si le seuil est atteint."""

        now = self._clock()
        window_start = now - self._window
        recent = [t for t in self._failures.get(key, []) if t > window_start]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= self._max_attempts:
            self._locked_until[key] = now + self._lockout

    def reset(self, key: str) -> None:
        """Efface compteur et verrou (connexion réussie)."""

        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


__all__ = ["InMemoryLoginRateLimiter"]
