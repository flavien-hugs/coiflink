"""Tests unitaires pour la logique OTP pure (domaine, #8).

Critère d'acceptation « l'OTP est testable » : le RNG et l'horloge sont injectés,
rendant chaque test déterministe et indépendant de l'I/O ou du temps système.
"""

from __future__ import annotations

import datetime
from random import Random

import pytest

from coiflink_api.domaine.otp import (
    LONGUEUR_OTP_DEFAUT,
    MAX_ESSAIS_OTP_DEFAUT,
    TTL_OTP_DEFAUT,
    DefiOtp,
    StatutOtp,
    generer_defi_otp,
    verifier_defi_otp,
)

_MAINTENANT = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_RNG_GRAINE = Random(42)


def _rng() -> Random:
    """RNG à graine fixe (déterministe) pour les tests."""
    return Random(42)


def _defi_actif(
    code: str = "123456",
    essais: int = MAX_ESSAIS_OTP_DEFAUT,
    consomme: bool = False,
    delta: datetime.timedelta = TTL_OTP_DEFAUT,
) -> DefiOtp:
    return DefiOtp(
        code=code,
        expire_a=_MAINTENANT + delta,
        essais_restants=essais,
        consomme=consomme,
    )


class TestGenererDefiOtp:
    def test_longueur_code_egale_parametre(self) -> None:
        defi = generer_defi_otp(_rng(), _MAINTENANT, longueur=6)
        assert len(defi.code) == 6

    def test_longueur_personnalisee(self) -> None:
        defi = generer_defi_otp(_rng(), _MAINTENANT, longueur=4)
        assert len(defi.code) == 4

    def test_code_uniquement_des_chiffres(self) -> None:
        defi = generer_defi_otp(_rng(), _MAINTENANT)
        assert defi.code.isdigit()

    def test_deterministe_avec_meme_graine(self) -> None:
        code1 = generer_defi_otp(Random(99), _MAINTENANT).code
        code2 = generer_defi_otp(Random(99), _MAINTENANT).code
        assert code1 == code2

    def test_expire_a_est_maintenant_plus_ttl(self) -> None:
        ttl = datetime.timedelta(minutes=10)
        defi = generer_defi_otp(_rng(), _MAINTENANT, ttl=ttl)
        assert defi.expire_a == _MAINTENANT + ttl

    def test_essais_restants_egale_max_essais(self) -> None:
        defi = generer_defi_otp(_rng(), _MAINTENANT, max_essais=5)
        assert defi.essais_restants == 5

    def test_non_consomme_a_la_creation(self) -> None:
        defi = generer_defi_otp(_rng(), _MAINTENANT)
        assert defi.consomme is False

    def test_longueur_zero_leve_value_error(self) -> None:
        with pytest.raises(ValueError):
            generer_defi_otp(_rng(), _MAINTENANT, longueur=0)

    def test_longueur_negative_leve_value_error(self) -> None:
        with pytest.raises(ValueError):
            generer_defi_otp(_rng(), _MAINTENANT, longueur=-1)

    def test_max_essais_zero_leve_value_error(self) -> None:
        with pytest.raises(ValueError):
            generer_defi_otp(_rng(), _MAINTENANT, max_essais=0)

    def test_max_essais_negatif_leve_value_error(self) -> None:
        with pytest.raises(ValueError):
            generer_defi_otp(_rng(), _MAINTENANT, max_essais=-3)

    def test_longueur_defaut_est_6(self) -> None:
        assert LONGUEUR_OTP_DEFAUT == 6

    def test_max_essais_defaut_est_3(self) -> None:
        assert MAX_ESSAIS_OTP_DEFAUT == 3


class TestVerifierDefiOtp:
    def test_valide_si_code_correct_avant_expiration(self) -> None:
        defi = _defi_actif(code="123456")
        statut = verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert statut == StatutOtp.VALIDE

    def test_consomme_apres_verification_valide(self) -> None:
        defi = _defi_actif(code="123456")
        verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert defi.consomme is True

    def test_invalide_si_code_incorrect(self) -> None:
        defi = _defi_actif(code="123456", essais=3)
        statut = verifier_defi_otp(defi, "000000", _MAINTENANT)
        assert statut == StatutOtp.INVALIDE

    def test_essais_decremente_apres_code_incorrect(self) -> None:
        defi = _defi_actif(code="123456", essais=3)
        verifier_defi_otp(defi, "000000", _MAINTENANT)
        assert defi.essais_restants == 2

    def test_expire_si_instant_egal_expiration(self) -> None:
        defi = _defi_actif(code="123456")
        statut = verifier_defi_otp(defi, "123456", defi.expire_a)
        assert statut == StatutOtp.EXPIRE

    def test_expire_si_instant_apres_expiration(self) -> None:
        defi = _defi_actif(code="123456")
        apres = defi.expire_a + datetime.timedelta(seconds=1)
        statut = verifier_defi_otp(defi, "123456", apres)
        assert statut == StatutOtp.EXPIRE

    def test_trop_d_essais_si_essais_epuises(self) -> None:
        defi = _defi_actif(code="123456", essais=0)
        statut = verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert statut == StatutOtp.TROP_D_ESSAIS

    def test_usage_unique_deja_consomme(self) -> None:
        defi = _defi_actif(code="123456", consomme=True)
        statut = verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert statut == StatutOtp.DEJA_CONSOMME

    def test_deja_consomme_prime_sur_expiration(self) -> None:
        """DEJA_CONSOMME est vérifié en premier (avant l'expiration)."""
        defi = _defi_actif(code="123456", consomme=True, delta=-TTL_OTP_DEFAUT)
        statut = verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert statut == StatutOtp.DEJA_CONSOMME

    def test_code_correct_ne_peut_pas_etre_reutilise(self) -> None:
        defi = _defi_actif(code="123456")
        verifier_defi_otp(defi, "123456", _MAINTENANT)
        # Deuxième tentative avec le bon code
        statut = verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert statut == StatutOtp.DEJA_CONSOMME

    def test_essais_epuises_apres_serie_d_echecs(self) -> None:
        defi = _defi_actif(code="123456", essais=3)
        for _ in range(3):
            verifier_defi_otp(defi, "000000", _MAINTENANT)
        statut = verifier_defi_otp(defi, "123456", _MAINTENANT)
        assert statut == StatutOtp.TROP_D_ESSAIS

    def test_essais_restants_ne_descend_pas_en_dessous_de_zero(self) -> None:
        defi = _defi_actif(code="123456", essais=1)
        verifier_defi_otp(defi, "000000", _MAINTENANT)
        verifier_defi_otp(defi, "000000", _MAINTENANT)  # déjà à 0
        assert defi.essais_restants == 0

    def test_statuts_otp_str_enum(self) -> None:
        assert StatutOtp.VALIDE == "VALIDE"
        assert StatutOtp.INVALIDE == "INVALIDE"
        assert StatutOtp.EXPIRE == "EXPIRE"
        assert StatutOtp.TROP_D_ESSAIS == "TROP_D_ESSAIS"
        assert StatutOtp.DEJA_CONSOMME == "DEJA_CONSOMME"
