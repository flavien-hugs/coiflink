"""Logique OTP **pure et injectable** (domaine, ADR-0008).

Cœur du critère d'acceptation « **l'OTP est testable** » (issue #8) : la
génération et la vérification d'un code à usage unique sont des fonctions pures,
paramétrées par un **RNG injecté** et une **horloge injectée** (aucune I/O,
aucun accès au temps système en dur). Elles ne réalisent **aucun envoi** (le SMS
relève de l'adapter `OtpSender`, différé à M5 — ADR-0006) et ne
**journalisent jamais** le code.

Propriétés couvertes : longueur du code, expiration, **usage unique** et
**limite d'essais**. Le stockage au repos (haché) et l'envoi sont des détails
d'infrastructure, hors de ce module.
"""

from __future__ import annotations

import datetime
import hmac
from dataclasses import dataclass
from enum import Enum
from random import Random

# Paramètres par défaut (surchargés par la configuration — cf. `config.py`).
DEFAULT_OTP_LENGTH = 6
DEFAULT_OTP_TTL = datetime.timedelta(minutes=5)
DEFAULT_OTP_MAX_ATTEMPTS = 3


class OtpStatus(str, Enum):
    """Issue d'une vérification d'OTP."""

    VALID = "VALID"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    ALREADY_CONSUMED = "ALREADY_CONSUMED"


@dataclass
class OtpChallenge:
    """État d'un défi OTP en cours de vie.

    `code` est la valeur attendue *dans le domaine* ; sa mise au repos (hachage)
    est la responsabilité de l'adapter `OtpRepository`. `attempts_left` décroît à
    chaque tentative erronée ; `consumed` matérialise l'usage unique.
    """

    code: str
    expires_at: datetime.datetime
    attempts_left: int
    consumed: bool = False


def generate_otp_challenge(
    rng: Random,
    now: datetime.datetime,
    *,
    length: int = DEFAULT_OTP_LENGTH,
    ttl: datetime.timedelta = DEFAULT_OTP_TTL,
    max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
) -> OtpChallenge:
    """Crée un défi OTP à partir d'un RNG et d'une horloge **injectés**.

    Le code est une suite de `length` chiffres tirés du RNG fourni (en
    production : un `random.SystemRandom` cryptographique ; en test : un
    `random.Random` graine pour un résultat déterministe).
    """

    if length <= 0:
        raise ValueError("La longueur de l'OTP doit être strictement positive.")
    if max_attempts <= 0:
        raise ValueError("Le nombre d'essais doit être strictement positif.")

    code = "".join(str(rng.randrange(10)) for _ in range(length))
    return OtpChallenge(code=code, expires_at=now + ttl, attempts_left=max_attempts)


def verify_otp_challenge(
    challenge: OtpChallenge, submitted_code: str, now: datetime.datetime
) -> OtpStatus:
    """Vérifie `submitted_code` contre `challenge` à l'instant `now`.

    Met à jour `challenge` en place (usage unique / décrément d'essais). La
    comparaison est faite en **temps constant** (`hmac.compare_digest`) pour ne
    pas fuiter d'information par canal temporel. Ne journalise jamais le code.
    """

    if challenge.consumed:
        return OtpStatus.ALREADY_CONSUMED
    if now >= challenge.expires_at:
        return OtpStatus.EXPIRED
    if challenge.attempts_left <= 0:
        return OtpStatus.TOO_MANY_ATTEMPTS

    if hmac.compare_digest(str(submitted_code), challenge.code):
        challenge.consumed = True
        return OtpStatus.VALID

    challenge.attempts_left -= 1
    return OtpStatus.INVALID


__all__ = [
    "OtpStatus",
    "OtpChallenge",
    "generate_otp_challenge",
    "verify_otp_challenge",
    "DEFAULT_OTP_LENGTH",
    "DEFAULT_OTP_TTL",
    "DEFAULT_OTP_MAX_ATTEMPTS",
]
