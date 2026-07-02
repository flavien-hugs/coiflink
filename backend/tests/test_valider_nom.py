"""Tests unitaires pour `valider_nom` (domaine, #8).

Couvre : normalisation (trim), longueur maximale, rejet des entrées
invalides, invariant de sécurité (message d'erreur sans la valeur saisie).
"""

from __future__ import annotations

import pytest

from coiflink_api.domaine.erreurs import NomInvalide
from coiflink_api.domaine.utilisateur import LONGUEUR_MAX_NOM, valider_nom


class TestNomValide:
    def test_nom_simple_retourne_identique(self) -> None:
        assert valider_nom("Alice") == "Alice"

    def test_nom_avec_espaces_en_tete_et_fin_nettoye(self) -> None:
        assert valider_nom("  Awa Koné  ") == "Awa Koné"

    def test_nom_avec_accents_accepte(self) -> None:
        assert valider_nom("Élodie Müller") == "Élodie Müller"

    def test_nom_un_seul_caractere_accepte(self) -> None:
        assert valider_nom("X") == "X"

    def test_nom_exactement_longueur_max_accepte(self) -> None:
        valider_nom("a" * LONGUEUR_MAX_NOM)

    def test_longueur_max_est_255(self) -> None:
        assert LONGUEUR_MAX_NOM == 255

    def test_retourne_le_nom_normalise_pas_l_original(self) -> None:
        original = "  Kofi  "
        resultat = valider_nom(original)
        assert resultat == "Kofi"
        assert resultat != original


class TestNomInvalide:
    def test_nom_vide_leve_nom_invalide(self) -> None:
        with pytest.raises(NomInvalide):
            valider_nom("")

    def test_nom_espaces_seuls_leve_nom_invalide(self) -> None:
        with pytest.raises(NomInvalide):
            valider_nom("   ")

    def test_nom_non_string_leve_nom_invalide(self) -> None:
        with pytest.raises(NomInvalide):
            valider_nom(None)  # type: ignore[arg-type]

    def test_nom_entier_leve_nom_invalide(self) -> None:
        with pytest.raises(NomInvalide):
            valider_nom(42)  # type: ignore[arg-type]

    def test_nom_trop_long_leve_nom_invalide(self) -> None:
        with pytest.raises(NomInvalide):
            valider_nom("a" * (LONGUEUR_MAX_NOM + 1))

    def test_nom_trop_long_est_bien_verifie_apres_trim(self) -> None:
        """Espaces en tête/queue retirés avant la vérification de longueur."""
        nom_court_apres_trim = "  " + "a" * LONGUEUR_MAX_NOM + "  "
        valider_nom(nom_court_apres_trim)  # ne doit pas lever


class TestSecuriteMessage:
    def test_message_erreur_trop_long_ne_contient_pas_le_nom(self) -> None:
        nom = "a" * (LONGUEUR_MAX_NOM + 1)
        try:
            valider_nom(nom)
        except NomInvalide as exc:
            assert nom not in str(exc)

    def test_nom_invalide_est_sous_classe_erreur_domaine(self) -> None:
        from coiflink_api.domaine.erreurs import ErreurDomaine

        with pytest.raises(ErreurDomaine):
            valider_nom("")
