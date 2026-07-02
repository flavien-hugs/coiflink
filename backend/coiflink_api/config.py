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

from coiflink_api.domaine.otp import (
    LONGUEUR_OTP_DEFAUT,
    MAX_ESSAIS_OTP_DEFAUT,
    TTL_OTP_DEFAUT,
)

_VRAI = {"1", "true", "yes", "on"}


def _bool_env(valeur: str | None, defaut: bool) -> bool:
    if valeur is None or valeur.strip() == "":
        return defaut
    return valeur.strip().lower() in _VRAI


def _int_env(valeur: str | None, defaut: int) -> int:
    if valeur is None or valeur.strip() == "":
        return defaut
    try:
        return int(valeur)
    except ValueError:
        return defaut


@dataclass(frozen=True)
class AuthConfig:
    """Réglages d'inscription/OTP (non secrets)."""

    otp_active: bool = False
    otp_longueur: int = LONGUEUR_OTP_DEFAUT
    otp_ttl: datetime.timedelta = TTL_OTP_DEFAUT
    otp_max_essais: int = MAX_ESSAIS_OTP_DEFAUT


def charger_auth_config(env: Mapping[str, str] | None = None) -> AuthConfig:
    """Construit `AuthConfig` depuis l'environnement (défauts sûrs si absent)."""

    source = env if env is not None else os.environ
    return AuthConfig(
        otp_active=_bool_env(source.get("OTP_ENABLED"), False),
        otp_longueur=_int_env(source.get("OTP_CODE_LENGTH"), LONGUEUR_OTP_DEFAUT),
        otp_ttl=datetime.timedelta(
            seconds=_int_env(
                source.get("OTP_TTL_SECONDS"), int(TTL_OTP_DEFAUT.total_seconds())
            )
        ),
        otp_max_essais=_int_env(source.get("OTP_MAX_ATTEMPTS"), MAX_ESSAIS_OTP_DEFAUT),
    )


__all__ = ["AuthConfig", "charger_auth_config"]
