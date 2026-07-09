"""Tests unitaires pour `InMemoryLoginRateLimiter` (adapter sortant, issue #10).

Vérifie :
- `check` passe quand aucun verrou actif (0 ou N−1 échecs) ;
- `check` lève `TooManyLoginAttempts` au seuil, avec `retry_after` positif et
  proportionnel au temps de verrou restant ;
- le verrou expire → `check` passe à nouveau (compteur nettoyé) ;
- `reset` efface compteur + verrou (simulation d'une connexion réussie) ;
- `reset` sur une clé inconnue est sûr (pas d'exception) ;
- la fenêtre est **glissante** : les échecs anciens (hors fenêtre) ne comptent pas ;
- deux clés différentes sont indépendantes.
"""

from __future__ import annotations

import datetime

import pytest

from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.domain.errors import TooManyLoginAttempts

_NOW = datetime.datetime(2026, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


def _make(
    max_attempts: int = 3,
    window_secs: int = 60,
    lockout_secs: int = 300,
) -> tuple[InMemoryLoginRateLimiter, list[datetime.datetime]]:
    """Retourne `(limiter, [t])` ; modifier `t[0]` avance l'horloge."""
    t: list[datetime.datetime] = [_NOW]
    limiter = InMemoryLoginRateLimiter(
        max_attempts=max_attempts,
        window=datetime.timedelta(seconds=window_secs),
        lockout=datetime.timedelta(seconds=lockout_secs),
        clock=lambda: t[0],
    )
    return limiter, t


class TestCheck:
    def test_no_failures_passes(self) -> None:
        limiter, _ = _make()
        limiter.check("key1")  # ne doit pas lever

    def test_below_threshold_passes(self) -> None:
        limiter, _ = _make(max_attempts=3)
        limiter.record_failure("key1")
        limiter.record_failure("key1")
        limiter.check("key1")  # 2 < 3, ne doit pas lever

    def test_at_threshold_raises(self) -> None:
        limiter, _ = _make(max_attempts=3)
        for _ in range(3):
            limiter.record_failure("key1")
        with pytest.raises(TooManyLoginAttempts):
            limiter.check("key1")

    def test_retry_after_is_positive(self) -> None:
        limiter, _ = _make(max_attempts=1, lockout_secs=300)
        limiter.record_failure("key1")
        with pytest.raises(TooManyLoginAttempts) as exc_info:
            limiter.check("key1")
        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after > 0

    def test_retry_after_matches_remaining_lockout(self) -> None:
        limiter, t = _make(max_attempts=1, lockout_secs=300)
        # Verrou posé à _NOW → fin à _NOW+300.
        limiter.record_failure("key1")
        # 50 secondes plus tard.
        t[0] = _NOW + datetime.timedelta(seconds=50)
        with pytest.raises(TooManyLoginAttempts) as exc_info:
            limiter.check("key1")
        assert exc_info.value.retry_after == 250

    def test_lockout_expired_passes_again(self) -> None:
        limiter, t = _make(max_attempts=1, lockout_secs=300)
        limiter.record_failure("key1")
        # Avance au-delà du verrou.
        t[0] = _NOW + datetime.timedelta(seconds=301)
        limiter.check("key1")  # ne doit pas lever

    def test_different_keys_are_independent(self) -> None:
        limiter, _ = _make(max_attempts=1)
        limiter.record_failure("key1")
        limiter.check("key2")  # key2 n'a aucun échec → passe


class TestRecordFailure:
    def test_below_threshold_does_not_lock(self) -> None:
        limiter, _ = _make(max_attempts=3)
        limiter.record_failure("k")
        limiter.record_failure("k")
        limiter.check("k")  # 2 < 3 → passe

    def test_exactly_at_threshold_locks(self) -> None:
        limiter, _ = _make(max_attempts=3)
        for _ in range(3):
            limiter.record_failure("k")
        with pytest.raises(TooManyLoginAttempts):
            limiter.check("k")

    def test_exceeding_threshold_stays_locked(self) -> None:
        limiter, _ = _make(max_attempts=2)
        for _ in range(5):
            limiter.record_failure("k")
        with pytest.raises(TooManyLoginAttempts):
            limiter.check("k")


class TestReset:
    def test_reset_after_failures_allows_check(self) -> None:
        limiter, _ = _make(max_attempts=1)
        limiter.record_failure("k")
        limiter.reset("k")
        limiter.check("k")  # ne doit pas lever

    def test_reset_clears_failure_count(self) -> None:
        """Après `reset`, les nouvelles tentatives repartent de zéro."""
        limiter, _ = _make(max_attempts=3)
        limiter.record_failure("k")
        limiter.record_failure("k")
        limiter.reset("k")
        # Deux nouveaux échecs — sous le seuil de 3 → ne doit pas lever.
        limiter.record_failure("k")
        limiter.record_failure("k")
        limiter.check("k")

    def test_reset_on_unknown_key_is_safe(self) -> None:
        limiter, _ = _make()
        limiter.reset("nonexistent")  # ne doit pas lever


class TestSlidingWindow:
    def test_old_failures_outside_window_do_not_count(self) -> None:
        """Les échecs antérieurs à la fenêtre sont ignorés."""
        limiter, t = _make(max_attempts=3, window_secs=60)
        # 2 échecs au temps initial.
        limiter.record_failure("k")
        limiter.record_failure("k")
        # Avance au-delà de la fenêtre de 60 s.
        t[0] = _NOW + datetime.timedelta(seconds=61)
        # 1 nouvel échec : les 2 anciens sont hors fenêtre → total dans-fenêtre = 1 < 3.
        limiter.record_failure("k")
        limiter.check("k")  # ne doit pas lever

    def test_failures_accumulate_within_window(self) -> None:
        """Les échecs dans la fenêtre s'accumulent et déclenchent le verrou."""
        limiter, t = _make(max_attempts=3, window_secs=120)
        limiter.record_failure("k")
        t[0] = _NOW + datetime.timedelta(seconds=30)
        limiter.record_failure("k")
        t[0] = _NOW + datetime.timedelta(seconds=60)
        limiter.record_failure("k")  # ← 3e échec dans la fenêtre → verrou
        with pytest.raises(TooManyLoginAttempts):
            limiter.check("k")
