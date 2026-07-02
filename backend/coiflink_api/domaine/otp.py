"""Logique OTP **pure et injectable** (domaine, ADR-0008).

Cœur du critère d'acceptation « **l'OTP est testable** » (issue #8) : la
génération et la vérification d'un code à usage unique sont des fonctions pures,
paramétrées par un **RNG injecté** et une **horloge injectée** (aucune I/O,
aucun accès au temps système en dur). Elles ne réalisent **aucun envoi** (le SMS
relève de l'adapter `ExpediteurOtp`, différé à M5 — ADR-0006) et ne
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
LONGUEUR_OTP_DEFAUT = 6
TTL_OTP_DEFAUT = datetime.timedelta(minutes=5)
MAX_ESSAIS_OTP_DEFAUT = 3


class StatutOtp(str, Enum):
    """Issue d'une vérification d'OTP."""

    VALIDE = "VALIDE"
    INVALIDE = "INVALIDE"
    EXPIRE = "EXPIRE"
    TROP_D_ESSAIS = "TROP_D_ESSAIS"
    DEJA_CONSOMME = "DEJA_CONSOMME"


@dataclass
class DefiOtp:
    """État d'un défi OTP en cours de vie.

    `code` est la valeur attendue *dans le domaine* ; sa mise au repos (hachage)
    est la responsabilité de l'adapter `DepotOtp`. `essais_restants` décroît à
    chaque tentative erronée ; `consomme` matérialise l'usage unique.
    """

    code: str
    expire_a: datetime.datetime
    essais_restants: int
    consomme: bool = False


def generer_defi_otp(
    rng: Random,
    maintenant: datetime.datetime,
    *,
    longueur: int = LONGUEUR_OTP_DEFAUT,
    ttl: datetime.timedelta = TTL_OTP_DEFAUT,
    max_essais: int = MAX_ESSAIS_OTP_DEFAUT,
) -> DefiOtp:
    """Crée un défi OTP à partir d'un RNG et d'une horloge **injectés**.

    Le code est une suite de `longueur` chiffres tirés du RNG fourni (en
    production : un `random.SystemRandom` cryptographique ; en test : un
    `random.Random` graine pour un résultat déterministe).
    """

    if longueur <= 0:
        raise ValueError("La longueur de l'OTP doit être strictement positive.")
    if max_essais <= 0:
        raise ValueError("Le nombre d'essais doit être strictement positif.")

    code = "".join(str(rng.randrange(10)) for _ in range(longueur))
    return DefiOtp(code=code, expire_a=maintenant + ttl, essais_restants=max_essais)


def verifier_defi_otp(
    defi: DefiOtp, code_saisi: str, maintenant: datetime.datetime
) -> StatutOtp:
    """Vérifie `code_saisi` contre `defi` à l'instant `maintenant`.

    Met à jour `defi` en place (usage unique / décrément d'essais). La
    comparaison est faite en **temps constant** (`hmac.compare_digest`) pour ne
    pas fuiter d'information par canal temporel. Ne journalise jamais le code.
    """

    if defi.consomme:
        return StatutOtp.DEJA_CONSOMME
    if maintenant >= defi.expire_a:
        return StatutOtp.EXPIRE
    if defi.essais_restants <= 0:
        return StatutOtp.TROP_D_ESSAIS

    if hmac.compare_digest(str(code_saisi), defi.code):
        defi.consomme = True
        return StatutOtp.VALIDE

    defi.essais_restants -= 1
    return StatutOtp.INVALIDE


__all__ = [
    "StatutOtp",
    "DefiOtp",
    "generer_defi_otp",
    "verifier_defi_otp",
    "LONGUEUR_OTP_DEFAUT",
    "TTL_OTP_DEFAUT",
    "MAX_ESSAIS_OTP_DEFAUT",
]
