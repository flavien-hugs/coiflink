"""Tests unitaires pour `valider_mot_de_passe` (domaine, #8).

Vérifie la politique (longueur min/max), le rejet des entrées vides ou invalides,
et l'invariant de sécurité : le message d'erreur ne contient jamais la valeur du
mot de passe en clair.
"""

from __future__ import annotations

import pytest

from coiflink_api.domaine.erreurs import MotDePasseInvalide
from coiflink_api.domaine.mot_de_passe import LONGUEUR_MAX, LONGUEUR_MIN, valider_mot_de_passe


class TestPolitiqueLongueur:
    def test_accepte_mot_de_passe_valide(self) -> None:
        valider_mot_de_passe("motdepasse1")  # pas d'exception

    def test_accepte_exactement_longueur_minimale(self) -> None:
        valider_mot_de_passe("a" * LONGUEUR_MIN)

    def test_accepte_exactement_longueur_maximale(self) -> None:
        valider_mot_de_passe("a" * LONGUEUR_MAX)

    def test_accepte_longueur_entre_min_et_max(self) -> None:
        valider_mot_de_passe("securise!")

    def test_rejette_trop_court(self) -> None:
        with pytest.raises(MotDePasseInvalide):
            valider_mot_de_passe("a" * (LONGUEUR_MIN - 1))

    def test_rejette_trop_long(self) -> None:
        with pytest.raises(MotDePasseInvalide):
            valider_mot_de_passe("a" * (LONGUEUR_MAX + 1))

    def test_longueur_min_est_8(self) -> None:
        assert LONGUEUR_MIN == 8

    def test_longueur_max_est_128(self) -> None:
        assert LONGUEUR_MAX == 128


class TestRejetsBase:
    def test_rejette_vide(self) -> None:
        with pytest.raises(MotDePasseInvalide):
            valider_mot_de_passe("")

    def test_rejette_non_string(self) -> None:
        with pytest.raises(MotDePasseInvalide):
            valider_mot_de_passe(None)  # type: ignore[arg-type]

    def test_rejette_un_seul_caractere(self) -> None:
        with pytest.raises(MotDePasseInvalide):
            valider_mot_de_passe("x")

    def test_rejette_sept_caracteres(self) -> None:
        with pytest.raises(MotDePasseInvalide):
            valider_mot_de_passe("abcdefg")


class TestSecuriteMessage:
    def test_message_erreur_ne_contient_pas_le_mot_de_passe(self) -> None:
        mdp_secret = "court1"
        try:
            valider_mot_de_passe(mdp_secret)
        except MotDePasseInvalide as exc:
            assert mdp_secret not in str(exc)

    def test_message_erreur_trop_long_ne_contient_pas_le_mot_de_passe(self) -> None:
        mdp_secret = "x" * (LONGUEUR_MAX + 1)
        try:
            valider_mot_de_passe(mdp_secret)
        except MotDePasseInvalide as exc:
            assert mdp_secret not in str(exc)

    def test_retourne_none_si_valide(self) -> None:
        resultat = valider_mot_de_passe("motdepasse-ok")
        assert resultat is None
