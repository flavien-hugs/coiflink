"""Configuration d'authentification lue **depuis l'environnement** (ADR-0011).

Le composition root (`main.py`) charge cette configuration et la dépose sur
`app.state` ; l'adapter entrant `auth` la relit pour assembler le cas d'usage.
Aucun secret ici : seulement des drapeaux/paramètres non sensibles (l'OTP est
**désactivé par défaut** en #8, l'envoi SMS réel étant différé à M5).

Note : `JWT_SECRET` n'est **pas** lu par #8 — l'inscription n'émet aucun JWT
(l'émission de jetons est traitée par la connexion, issue #10).
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from typing import Mapping

from coiflink_api.domain.otp import (
    DEFAULT_OTP_LENGTH,
    DEFAULT_OTP_MAX_ATTEMPTS,
    DEFAULT_OTP_TTL,
)

_TRUTHY = {"1", "true", "yes", "on"}


def _bool_env(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in _TRUTHY


def _int_env(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class AuthConfig:
    """Réglages d'inscription/OTP (non secrets)."""

    otp_enabled: bool = False
    otp_length: int = DEFAULT_OTP_LENGTH
    otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL
    otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS


def load_auth_config(env: Mapping[str, str] | None = None) -> AuthConfig:
    """Construit `AuthConfig` depuis l'environnement (défauts sûrs si absent)."""

    source = env if env is not None else os.environ
    return AuthConfig(
        otp_enabled=_bool_env(source.get("OTP_ENABLED"), False),
        otp_length=_int_env(source.get("OTP_CODE_LENGTH"), DEFAULT_OTP_LENGTH),
        otp_ttl=datetime.timedelta(
            seconds=_int_env(
                source.get("OTP_TTL_SECONDS"), int(DEFAULT_OTP_TTL.total_seconds())
            )
        ),
        otp_max_attempts=_int_env(
            source.get("OTP_MAX_ATTEMPTS"), DEFAULT_OTP_MAX_ATTEMPTS
        ),
    )


__all__ = ["AuthConfig", "load_auth_config"]
