"""Tests unitaires pour `Argon2Hasher` (adapter sortant, #8).

Vérifie : condensat ≠ clair, sel aléatoire, vérification valide/invalide,
non-fuite du clair dans le condensat, format argon2id.
Les paramètres de coût sont réduits pour la rapidité des tests.
"""

from __future__ import annotations

import argon2
import pytest

from coiflink_api.adapters.outbound.security.argon2_hasher import Argon2Hasher

# `argon2.PasswordHasher` allégé : adéquat pour les tests (rapidité >> sécurité ici).
# Import explicite via le module pour éviter la collision avec le port
# `coiflink_api.application.ports.password_hasher.PasswordHasher`.
_TEST_PH = argon2.PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1)


@pytest.fixture()
def hasher() -> Argon2Hasher:
    return Argon2Hasher(hasher=_TEST_PH)


class TestHash:
    def test_hash_differs_from_plain(self, hasher: Argon2Hasher) -> None:
        plain = "motdepasse-test-123"
        assert hasher.hash(plain) != plain

    def test_two_hashes_of_same_plain_differ(self, hasher: Argon2Hasher) -> None:
        plain = "motdepasse-test-123"
        h1 = hasher.hash(plain)
        h2 = hasher.hash(plain)
        assert h1 != h2  # sel aléatoire garantit l'unicité

    def test_plain_absent_from_hash(self, hasher: Argon2Hasher) -> None:
        plain = "motdepasse-test-123"
        hashed = hasher.hash(plain)
        assert plain not in hashed

    def test_hash_starts_with_argon2id(self, hasher: Argon2Hasher) -> None:
        hashed = hasher.hash("motdepasse-ok")
        assert hashed.startswith("$argon2id$")

    def test_hash_is_a_string(self, hasher: Argon2Hasher) -> None:
        assert isinstance(hasher.hash("motdepasse-ok"), str)

    def test_hash_not_empty(self, hasher: Argon2Hasher) -> None:
        assert hasher.hash("motdepasse-ok") != ""


class TestVerify:
    def test_verify_correct_plain_returns_true(self, hasher: Argon2Hasher) -> None:
        plain = "motdepasse-test-123"
        hashed = hasher.hash(plain)
        assert hasher.verify(plain, hashed) is True

    def test_verify_incorrect_plain_returns_false(self, hasher: Argon2Hasher) -> None:
        hashed = hasher.hash("motdepasse-test-123")
        assert hasher.verify("mauvais-mot-de-passe", hashed) is False

    def test_verify_invalid_hash_returns_false(self, hasher: Argon2Hasher) -> None:
        assert hasher.verify("motdepasse", "pas-un-condensat-argon2") is False

    def test_verify_does_not_raise(self, hasher: Argon2Hasher) -> None:
        hashed = hasher.hash("motdepasse-ok")
        # Ne doit pas lever même avec un mauvais clair
        result = hasher.verify("mauvais", hashed)
        assert isinstance(result, bool)

    def test_verify_empty_hash_returns_false(self, hasher: Argon2Hasher) -> None:
        assert hasher.verify("motdepasse", "") is False

    def test_hash_of_another_password_fails(self, hasher: Argon2Hasher) -> None:
        h1 = hasher.hash("mdp-a")
        assert hasher.verify("mdp-b", h1) is False
