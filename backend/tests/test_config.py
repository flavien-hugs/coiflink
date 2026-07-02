"""Tests unitaires pour `charger_auth_config` (#8).

Vérifie : valeurs par défaut, parsing des drapeaux booléens OTP, parsing
des paramètres entiers, et robustesse face à des valeurs malformées.
"""

from __future__ import annotations

import datetime

import pytest

from coiflink_api.config import AuthConfig, charger_auth_config
from coiflink_api.domaine.otp import (
    LONGUEUR_OTP_DEFAUT,
    MAX_ESSAIS_OTP_DEFAUT,
    TTL_OTP_DEFAUT,
)


class TestDefauts:
    def test_otp_desactive_par_defaut(self) -> None:
        config = charger_auth_config({})
        assert config.otp_active is False

    def test_longueur_otp_defaut(self) -> None:
        config = charger_auth_config({})
        assert config.otp_longueur == LONGUEUR_OTP_DEFAUT

    def test_ttl_otp_defaut(self) -> None:
        config = charger_auth_config({})
        assert config.otp_ttl == TTL_OTP_DEFAUT

    def test_max_essais_defaut(self) -> None:
        config = charger_auth_config({})
        assert config.otp_max_essais == MAX_ESSAIS_OTP_DEFAUT

    def test_auth_config_est_frozen(self) -> None:
        config = AuthConfig()
        with pytest.raises((AttributeError, TypeError)):
            config.otp_active = True  # type: ignore[misc]


class TestOtpEnabled:
    @pytest.mark.parametrize("valeur", ["1", "true", "True", "TRUE", "yes", "on"])
    def test_valeur_truthy(self, valeur: str) -> None:
        config = charger_auth_config({"OTP_ENABLED": valeur})
        assert config.otp_active is True

    @pytest.mark.parametrize("valeur", ["0", "false", "False", "no", "off"])
    def test_valeur_falsy(self, valeur: str) -> None:
        config = charger_auth_config({"OTP_ENABLED": valeur})
        assert config.otp_active is False

    def test_valeur_vide_utilise_defaut(self) -> None:
        config = charger_auth_config({"OTP_ENABLED": ""})
        assert config.otp_active is False

    def test_valeur_espaces_utilise_defaut(self) -> None:
        config = charger_auth_config({"OTP_ENABLED": "   "})
        assert config.otp_active is False

    def test_cle_absente_utilise_defaut(self) -> None:
        config = charger_auth_config({})
        assert config.otp_active is False


class TestParametresOtp:
    def test_longueur_otp_personnalisee(self) -> None:
        config = charger_auth_config({"OTP_CODE_LENGTH": "8"})
        assert config.otp_longueur == 8

    def test_longueur_otp_invalide_utilise_defaut(self) -> None:
        config = charger_auth_config({"OTP_CODE_LENGTH": "pas-un-entier"})
        assert config.otp_longueur == LONGUEUR_OTP_DEFAUT

    def test_longueur_otp_vide_utilise_defaut(self) -> None:
        config = charger_auth_config({"OTP_CODE_LENGTH": ""})
        assert config.otp_longueur == LONGUEUR_OTP_DEFAUT

    def test_ttl_otp_personnalise(self) -> None:
        config = charger_auth_config({"OTP_TTL_SECONDS": "120"})
        assert config.otp_ttl == datetime.timedelta(seconds=120)

    def test_ttl_otp_invalide_utilise_defaut(self) -> None:
        config = charger_auth_config({"OTP_TTL_SECONDS": "abc"})
        assert config.otp_ttl == TTL_OTP_DEFAUT

    def test_max_essais_personnalise(self) -> None:
        config = charger_auth_config({"OTP_MAX_ATTEMPTS": "5"})
        assert config.otp_max_essais == 5

    def test_max_essais_invalide_utilise_defaut(self) -> None:
        config = charger_auth_config({"OTP_MAX_ATTEMPTS": "nope"})
        assert config.otp_max_essais == MAX_ESSAIS_OTP_DEFAUT

    def test_tous_les_parametres_ensemble(self) -> None:
        env = {
            "OTP_ENABLED": "1",
            "OTP_CODE_LENGTH": "4",
            "OTP_TTL_SECONDS": "300",
            "OTP_MAX_ATTEMPTS": "5",
        }
        config = charger_auth_config(env)
        assert config.otp_active is True
        assert config.otp_longueur == 4
        assert config.otp_ttl == datetime.timedelta(seconds=300)
        assert config.otp_max_essais == 5
