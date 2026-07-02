"""Tests unitaires pour `normaliser_telephone` (domaine, #8).

Couvre : normalisation E.164, idempotence, séparateurs tolérés,
préfixe 00→+, rejet des invalides. Ces tests sont purs (stdlib seule).
"""

from __future__ import annotations

import pytest

from coiflink_api.domaine.erreurs import TelephoneInvalide
from coiflink_api.domaine.telephone import INDICATIF_DEFAUT, normaliser_telephone


class TestNormalisationE164:
    def test_numero_local_prefixe_indicatif_defaut(self) -> None:
        resultat = normaliser_telephone("0700000000")
        assert resultat == "+2250700000000"

    def test_numero_avec_plus_inchange(self) -> None:
        assert normaliser_telephone("+2250700000000") == "+2250700000000"

    def test_prefixe_00_converti_en_plus(self) -> None:
        assert normaliser_telephone("002250700000000") == "+2250700000000"

    def test_numero_international_autre_pays(self) -> None:
        resultat = normaliser_telephone("+33612345678")
        assert resultat == "+33612345678"

    def test_indicatif_defaut_est_cote_d_ivoire(self) -> None:
        assert INDICATIF_DEFAUT == "225"

    def test_indicatif_custom(self) -> None:
        resultat = normaliser_telephone("612345678", indicatif_defaut="33")
        assert resultat == "+33612345678"


class TestIdempotence:
    def test_idempotence_numero_local(self) -> None:
        premier = normaliser_telephone("0700000000")
        second = normaliser_telephone(premier)
        assert premier == second

    def test_idempotence_numero_international(self) -> None:
        premier = normaliser_telephone("+2250700000000")
        assert normaliser_telephone(premier) == premier

    def test_zero_local_et_e164_meme_forme_canonique(self) -> None:
        """0700000000 et +2250700000000 → même forme → doublon détectable."""
        forme1 = normaliser_telephone("0700000000")
        forme2 = normaliser_telephone("+2250700000000")
        assert forme1 == forme2

    def test_00_et_plus_meme_forme_canonique(self) -> None:
        forme1 = normaliser_telephone("002250700000000")
        forme2 = normaliser_telephone("+2250700000000")
        assert forme1 == forme2


class TestSeparateursToleres:
    def test_espaces_retires(self) -> None:
        assert normaliser_telephone("07 00 00 00 00") == "+2250700000000"

    def test_tirets_retires(self) -> None:
        assert normaliser_telephone("07-00-00-00-00") == "+2250700000000"

    def test_points_retires(self) -> None:
        assert normaliser_telephone("07.00.00.00.00") == "+2250700000000"

    def test_parentheses_retirees(self) -> None:
        assert normaliser_telephone("(07)00000000") == "+225(07)00000000".replace("(", "").replace(")", "")

    def test_mixte_separateurs(self) -> None:
        assert normaliser_telephone("+225 07 00 00 00 00") == "+2250700000000"

    def test_espaces_en_tete_fin(self) -> None:
        assert normaliser_telephone("  0700000000  ") == "+2250700000000"


class TestRejetsInvalides:
    def test_vide_leve_telephone_invalide(self) -> None:
        with pytest.raises(TelephoneInvalide):
            normaliser_telephone("")

    def test_espaces_seuls_leve_telephone_invalide(self) -> None:
        with pytest.raises(TelephoneInvalide):
            normaliser_telephone("   ")

    def test_lettres_dans_numero_leve_telephone_invalide(self) -> None:
        with pytest.raises(TelephoneInvalide):
            normaliser_telephone("07abc00000")

    def test_trop_court_leve_telephone_invalide(self) -> None:
        with pytest.raises(TelephoneInvalide):
            normaliser_telephone("123")

    def test_trop_long_leve_telephone_invalide(self) -> None:
        # 16 chiffres (sans indicatif) → dépasse la borne E.164 de 15
        with pytest.raises(TelephoneInvalide):
            normaliser_telephone("+1234567890123456")

    def test_non_string_leve_telephone_invalide(self) -> None:
        with pytest.raises(TelephoneInvalide):
            normaliser_telephone(700000000)  # type: ignore[arg-type]

    def test_message_erreur_ne_contient_pas_numero(self) -> None:
        numero_secret = "abc123"
        try:
            normaliser_telephone(numero_secret)
        except TelephoneInvalide as exc:
            assert numero_secret not in str(exc)

    def test_sortie_commence_par_plus(self) -> None:
        assert normaliser_telephone("0700000000").startswith("+")

    def test_sortie_uniquement_chiffres_apres_plus(self) -> None:
        resultat = normaliser_telephone("0700000000")
        assert resultat[1:].isdigit()
