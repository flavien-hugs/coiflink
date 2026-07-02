"""Tests unitaires pour `HacheurArgon2` (adapter sortant, #8).

Vérifie : condensat ≠ clair, sel aléatoire, vérification valide/invalide,
non-fuite du clair dans le condensat, format argon2id.
Les paramètres de coût sont réduits pour la rapidité des tests.
"""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from coiflink_api.adapters.sortant.securite.hacheur import HacheurArgon2

# PasswordHasher allégé : adéquat pour les tests (rapidité >> sécurité ici).
_PH_TEST = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1)


@pytest.fixture()
def hacheur() -> HacheurArgon2:
    return HacheurArgon2(hasher=_PH_TEST)


class TestHacher:
    def test_condensat_different_du_clair(self, hacheur: HacheurArgon2) -> None:
        clair = "motdepasse-test-123"
        assert hacheur.hacher(clair) != clair

    def test_deux_hachages_du_meme_clair_different(self, hacheur: HacheurArgon2) -> None:
        clair = "motdepasse-test-123"
        h1 = hacheur.hacher(clair)
        h2 = hacheur.hacher(clair)
        assert h1 != h2  # sel aléatoire garantit l'unicité

    def test_clair_absent_du_condensat(self, hacheur: HacheurArgon2) -> None:
        clair = "motdepasse-test-123"
        condensat = hacheur.hacher(clair)
        assert clair not in condensat

    def test_condensat_commence_par_argon2id(self, hacheur: HacheurArgon2) -> None:
        condensat = hacheur.hacher("motdepasse-ok")
        assert condensat.startswith("$argon2id$")

    def test_condensat_est_une_chaine(self, hacheur: HacheurArgon2) -> None:
        assert isinstance(hacheur.hacher("motdepasse-ok"), str)

    def test_condensat_non_vide(self, hacheur: HacheurArgon2) -> None:
        assert hacheur.hacher("motdepasse-ok") != ""


class TestVerifier:
    def test_verifier_clair_correct_retourne_vrai(self, hacheur: HacheurArgon2) -> None:
        clair = "motdepasse-test-123"
        condensat = hacheur.hacher(clair)
        assert hacheur.verifier(clair, condensat) is True

    def test_verifier_clair_incorrect_retourne_faux(self, hacheur: HacheurArgon2) -> None:
        condensat = hacheur.hacher("motdepasse-test-123")
        assert hacheur.verifier("mauvais-mot-de-passe", condensat) is False

    def test_verifier_condensat_invalide_retourne_faux(self, hacheur: HacheurArgon2) -> None:
        assert hacheur.verifier("motdepasse", "pas-un-condensat-argon2") is False

    def test_verifier_ne_leve_pas_d_exception(self, hacheur: HacheurArgon2) -> None:
        condensat = hacheur.hacher("motdepasse-ok")
        # Ne doit pas lever même avec un mauvais clair
        resultat = hacheur.verifier("mauvais", condensat)
        assert isinstance(resultat, bool)

    def test_verifier_condensat_vide_retourne_faux(self, hacheur: HacheurArgon2) -> None:
        assert hacheur.verifier("motdepasse", "") is False

    def test_condensat_d_un_autre_hachage_echoue(self, hacheur: HacheurArgon2) -> None:
        h1 = hacheur.hacher("mdp-a")
        assert hacheur.verifier("mdp-b", h1) is False
