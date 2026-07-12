"""Configuration d'authentification lue **depuis l'environnement** (ADR-0011).

Le composition root (`main.py`) charge cette configuration et la dépose sur
`app.state` ; les adapters entrants (`auth`) la relisent pour assembler les cas
d'usage. Elle regroupe :

- l'**inscription/OTP** (#8, non secret ; OTP désactivé par défaut) ;
- la **connexion/JWT** (#10) : `jwt_secret` (**secret**, ADR-0011), algorithme,
  TTL des jetons d'accès/refresh, et les paramètres d'**anti-bruteforce**.

Le `jwt_secret` **n'a pas de défaut sûr** : ici il vaut `""` quand `JWT_SECRET`
est absent. La **validation fail-fast** n'a **pas** lieu au chargement (pour ne
pas casser `GET /health` en env mal configuré) mais à l'**assemblage du
`TokenService`** (`JwtTokenService.__init__` lève si le secret est vide) — donc
uniquement sur les routes `/auth/*` qui émettent des jetons.
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

# Défauts de connexion/JWT (non secrets). Le secret lui-même n'a jamais de défaut.
DEFAULT_JWT_ALGORITHM = "HS256"
DEFAULT_ACCESS_TTL = datetime.timedelta(minutes=15)
DEFAULT_REFRESH_TTL = datetime.timedelta(days=30)
DEFAULT_LOGIN_MAX_ATTEMPTS = 5
DEFAULT_LOGIN_WINDOW = datetime.timedelta(seconds=300)
DEFAULT_LOGIN_LOCKOUT = datetime.timedelta(seconds=900)


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
    """Réglages d'inscription/OTP (non secrets) et de connexion/JWT (#10).

    `jwt_secret` est le seul champ **secret** ; il vaut `""` par défaut (validation
    fail-fast déportée à l'assemblage du `TokenService`).
    """

    otp_enabled: bool = False
    otp_length: int = DEFAULT_OTP_LENGTH
    otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL
    otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS
    jwt_secret: str = ""
    jwt_algorithm: str = DEFAULT_JWT_ALGORITHM
    access_ttl: datetime.timedelta = DEFAULT_ACCESS_TTL
    refresh_ttl: datetime.timedelta = DEFAULT_REFRESH_TTL
    login_max_attempts: int = DEFAULT_LOGIN_MAX_ATTEMPTS
    login_window: datetime.timedelta = DEFAULT_LOGIN_WINDOW
    login_lockout: datetime.timedelta = DEFAULT_LOGIN_LOCKOUT
    # Réinitialisation du mot de passe par OTP (#11). L'OTP de reset est **toujours
    # actif** (indépendant d'`OTP_ENABLED`) ; sa longueur réutilise `otp_length`.
    # TTL / essais / anti-abus ont des variables dédiées optionnelles, dont le
    # défaut retombe sur les valeurs OTP (#8) et login (#10).
    password_reset_otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL
    password_reset_otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS
    password_reset_max_attempts: int = DEFAULT_LOGIN_MAX_ATTEMPTS
    password_reset_window: datetime.timedelta = DEFAULT_LOGIN_WINDOW
    password_reset_lockout: datetime.timedelta = DEFAULT_LOGIN_LOCKOUT


def load_auth_config(env: Mapping[str, str] | None = None) -> AuthConfig:
    """Construit `AuthConfig` depuis l'environnement (défauts sûrs si absent)."""

    source = env if env is not None else os.environ

    # Valeurs OTP (#8) et login (#10) lues d'abord : elles servent de **défaut**
    # aux réglages de reset (#11) quand les `PASSWORD_RESET_*` sont absents.
    otp_ttl_seconds = _int_env(
        source.get("OTP_TTL_SECONDS"), int(DEFAULT_OTP_TTL.total_seconds())
    )
    otp_max_attempts = _int_env(source.get("OTP_MAX_ATTEMPTS"), DEFAULT_OTP_MAX_ATTEMPTS)
    login_max_attempts = _int_env(
        source.get("LOGIN_MAX_ATTEMPTS"), DEFAULT_LOGIN_MAX_ATTEMPTS
    )
    login_window_seconds = _int_env(
        source.get("LOGIN_WINDOW_SECONDS"), int(DEFAULT_LOGIN_WINDOW.total_seconds())
    )
    login_lockout_seconds = _int_env(
        source.get("LOGIN_LOCKOUT_SECONDS"), int(DEFAULT_LOGIN_LOCKOUT.total_seconds())
    )

    return AuthConfig(
        otp_enabled=_bool_env(source.get("OTP_ENABLED"), False),
        otp_length=_int_env(source.get("OTP_CODE_LENGTH"), DEFAULT_OTP_LENGTH),
        otp_ttl=datetime.timedelta(seconds=otp_ttl_seconds),
        otp_max_attempts=otp_max_attempts,
        # Connexion / JWT (#10). Le secret n'a pas de défaut : "" quand absent.
        jwt_secret=(source.get("JWT_SECRET") or "").strip(),
        jwt_algorithm=(source.get("JWT_ALGORITHM") or DEFAULT_JWT_ALGORITHM).strip(),
        access_ttl=datetime.timedelta(
            seconds=_int_env(
                source.get("JWT_ACCESS_TTL_SECONDS"),
                int(DEFAULT_ACCESS_TTL.total_seconds()),
            )
        ),
        refresh_ttl=datetime.timedelta(
            seconds=_int_env(
                source.get("JWT_REFRESH_TTL_SECONDS"),
                int(DEFAULT_REFRESH_TTL.total_seconds()),
            )
        ),
        login_max_attempts=login_max_attempts,
        login_window=datetime.timedelta(seconds=login_window_seconds),
        login_lockout=datetime.timedelta(seconds=login_lockout_seconds),
        # Réinitialisation (#11) : variables dédiées, défaut = valeurs OTP/login.
        password_reset_otp_ttl=datetime.timedelta(
            seconds=_int_env(
                source.get("PASSWORD_RESET_OTP_TTL_SECONDS"), otp_ttl_seconds
            )
        ),
        password_reset_otp_max_attempts=_int_env(
            source.get("PASSWORD_RESET_OTP_MAX_ATTEMPTS"), otp_max_attempts
        ),
        password_reset_max_attempts=_int_env(
            source.get("PASSWORD_RESET_MAX_ATTEMPTS"), login_max_attempts
        ),
        password_reset_window=datetime.timedelta(
            seconds=_int_env(
                source.get("PASSWORD_RESET_WINDOW_SECONDS"), login_window_seconds
            )
        ),
        password_reset_lockout=datetime.timedelta(
            seconds=_int_env(
                source.get("PASSWORD_RESET_LOCKOUT_SECONDS"), login_lockout_seconds
            )
        ),
    )


__all__ = ["AuthConfig", "load_auth_config"]
