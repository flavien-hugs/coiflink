"""Tests unitaires pour `load_auth_config` (#8) et `load_media_config`.

Vérifie : valeurs par défaut, parsing des drapeaux booléens OTP, parsing
des paramètres entiers, et robustesse face à des valeurs malformées.
"""

from __future__ import annotations

import datetime

import pytest

from coiflink_api.config import AuthConfig, MediaConfig, load_auth_config, load_media_config
from coiflink_api.domain.otp import (
    DEFAULT_OTP_LENGTH,
    DEFAULT_OTP_MAX_ATTEMPTS,
    DEFAULT_OTP_TTL,
)


class TestDefaults:
    def test_otp_disabled_by_default(self) -> None:
        config = load_auth_config({})
        assert config.otp_enabled is False

    def test_default_otp_length(self) -> None:
        config = load_auth_config({})
        assert config.otp_length == DEFAULT_OTP_LENGTH

    def test_default_otp_ttl(self) -> None:
        config = load_auth_config({})
        assert config.otp_ttl == DEFAULT_OTP_TTL

    def test_default_max_attempts(self) -> None:
        config = load_auth_config({})
        assert config.otp_max_attempts == DEFAULT_OTP_MAX_ATTEMPTS

    def test_auth_config_is_frozen(self) -> None:
        config = AuthConfig()
        with pytest.raises((AttributeError, TypeError)):
            config.otp_enabled = True  # type: ignore[misc]


class TestOtpEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "on"])
    def test_truthy_value(self, value: str) -> None:
        config = load_auth_config({"OTP_ENABLED": value})
        assert config.otp_enabled is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off"])
    def test_falsy_value(self, value: str) -> None:
        config = load_auth_config({"OTP_ENABLED": value})
        assert config.otp_enabled is False

    def test_empty_value_uses_default(self) -> None:
        config = load_auth_config({"OTP_ENABLED": ""})
        assert config.otp_enabled is False

    def test_spaces_value_uses_default(self) -> None:
        config = load_auth_config({"OTP_ENABLED": "   "})
        assert config.otp_enabled is False

    def test_missing_key_uses_default(self) -> None:
        config = load_auth_config({})
        assert config.otp_enabled is False


class TestOtpParameters:
    def test_custom_otp_length(self) -> None:
        config = load_auth_config({"OTP_CODE_LENGTH": "8"})
        assert config.otp_length == 8

    def test_invalid_otp_length_uses_default(self) -> None:
        config = load_auth_config({"OTP_CODE_LENGTH": "pas-un-entier"})
        assert config.otp_length == DEFAULT_OTP_LENGTH

    def test_empty_otp_length_uses_default(self) -> None:
        config = load_auth_config({"OTP_CODE_LENGTH": ""})
        assert config.otp_length == DEFAULT_OTP_LENGTH

    def test_custom_otp_ttl(self) -> None:
        config = load_auth_config({"OTP_TTL_SECONDS": "120"})
        assert config.otp_ttl == datetime.timedelta(seconds=120)

    def test_invalid_otp_ttl_uses_default(self) -> None:
        config = load_auth_config({"OTP_TTL_SECONDS": "abc"})
        assert config.otp_ttl == DEFAULT_OTP_TTL

    def test_custom_max_attempts_(self) -> None:
        config = load_auth_config({"OTP_MAX_ATTEMPTS": "5"})
        assert config.otp_max_attempts == 5

    def test_invalid_max_attempts_uses_default(self) -> None:
        config = load_auth_config({"OTP_MAX_ATTEMPTS": "nope"})
        assert config.otp_max_attempts == DEFAULT_OTP_MAX_ATTEMPTS

    def test_all_parameters_together(self) -> None:
        env = {
            "OTP_ENABLED": "1",
            "OTP_CODE_LENGTH": "4",
            "OTP_TTL_SECONDS": "300",
            "OTP_MAX_ATTEMPTS": "5",
        }
        config = load_auth_config(env)
        assert config.otp_enabled is True
        assert config.otp_length == 4
        assert config.otp_ttl == datetime.timedelta(seconds=300)
        assert config.otp_max_attempts == 5


class TestMediaConfigPresignEndpoint:
    """`presign_endpoint_url` : hôte des URLs pré-signées, distinct de l'hôte des
    appels réseau internes du backend (`endpoint_url`) — cf. docstring
    `MediaConfig`. Le repli sur `endpoint_url` préserve le comportement d'avant
    l'introduction de `S3_PUBLIC_ENDPOINT_URL` pour tout déploiement qui ne la
    définit pas."""

    def test_falls_back_to_endpoint_url_when_public_endpoint_unset(self) -> None:
        config = MediaConfig(endpoint_url="http://minio:9000")
        assert config.presign_endpoint_url == "http://minio:9000"

    def test_uses_public_endpoint_url_when_set(self) -> None:
        config = MediaConfig(
            endpoint_url="http://minio:9000",
            public_endpoint_url="http://192.168.1.128:9000",
        )
        assert config.presign_endpoint_url == "http://192.168.1.128:9000"

    def test_both_empty_yields_empty(self) -> None:
        config = MediaConfig()
        assert config.presign_endpoint_url == ""


class TestLoadMediaConfig:
    def test_public_endpoint_url_defaults_to_empty(self) -> None:
        config = load_media_config({})
        assert config.public_endpoint_url == ""

    def test_public_endpoint_url_read_from_environment(self) -> None:
        config = load_media_config({"S3_PUBLIC_ENDPOINT_URL": "http://192.168.1.128:9000"})
        assert config.public_endpoint_url == "http://192.168.1.128:9000"

    def test_public_endpoint_url_is_stripped(self) -> None:
        config = load_media_config({"S3_PUBLIC_ENDPOINT_URL": "  http://192.168.1.128:9000  "})
        assert config.public_endpoint_url == "http://192.168.1.128:9000"

    def test_endpoint_url_and_public_endpoint_url_are_independent(self) -> None:
        config = load_media_config(
            {
                "S3_ENDPOINT_URL": "http://minio:9000",
                "S3_PUBLIC_ENDPOINT_URL": "http://192.168.1.128:9000",
            }
        )
        assert config.endpoint_url == "http://minio:9000"
        assert config.public_endpoint_url == "http://192.168.1.128:9000"
        assert config.presign_endpoint_url == "http://192.168.1.128:9000"
