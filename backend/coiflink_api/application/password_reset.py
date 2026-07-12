"""Cas d'usage : **réinitialisation du mot de passe par OTP** (application, ADR-0008).

Implémente US-1.3 (issue #11) : un parcours de reset **en deux étapes**, adossé
uniquement à des **ports** (dépôt utilisateur, dépôt OTP dédié, expéditeur OTP,
hacheur, limiteur anti-abus) — jamais de FastAPI, SQLAlchemy, argon2 ni PyJWT.
Comme l'inscription (#8), RNG (`SystemRandom` par défaut) et horloge sont
**injectables** pour des tests déterministes.

1. **Demande** (`RequestPasswordReset`) : à partir d'un identifiant (téléphone
   **ou** e-mail), émet un OTP à usage unique et expirant, stocké dans un dépôt
   **dédié au reset** et acheminé via le canal correspondant (SMS/e-mail, stub).
2. **Confirmation** (`ConfirmPasswordReset`) : vérifie l'OTP puis **remplace** le
   condensat du compte — l'ancien mot de passe ne s'authentifie **plus jamais**.

Garde-fous de sécurité (PRD §11.1/§11.3, ADR-0012/0013, spec §Security) :
- **Anti-énumération** : ni la demande ni la confirmation ne révèlent l'existence
  d'un compte. La demande retourne **normalement** même pour un identifiant
  inconnu/non `ACTIVE` (la route répond un 202 uniforme) ; tout échec d'OTP et un
  identifiant sans défi produisent la **même** `InvalidOtp` (400 générique).
- **Atténuation d'oracle temporel** : un défi est **toujours** généré (même pour
  un compte inexistant), analogue au condensat *dummy* de #10.
- **OTP à usage unique et expirant** : garanti par `verify_otp_challenge`
  (consommation + `expires_at` + `attempts_left`, comparaison temps constant)
  **et** par la suppression du défi après succès ; une nouvelle demande écrase le
  défi précédent (invalidation implicite).
- **Anti-abus** : la demande est rate-limitée (identifiant + IP) ; la confirmation
  est bornée par `attempts_left`.
- **Aucun secret** (mot de passe en clair, condensat, code OTP, numéro, e-mail)
  n'est journalisé ni renvoyé. Le clair ne vit que le temps de
  `validate_password` / `hash`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from random import Random, SystemRandom
from typing import Callable

from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.application.ports.otp_repository import OtpRepository
from coiflink_api.application.ports.otp_sender import OtpSender
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import NotificationChannel, UserStatus
from coiflink_api.domain.errors import InvalidOtp, InvalidPhone
from coiflink_api.domain.identifier import EMAIL, LoginIdentifier, classify_identifier
from coiflink_api.domain.otp import (
    DEFAULT_OTP_LENGTH,
    DEFAULT_OTP_MAX_ATTEMPTS,
    DEFAULT_OTP_TTL,
    OtpStatus,
    generate_otp_challenge,
    verify_otp_challenge,
)
from coiflink_api.domain.password import validate_password

# Message unique renvoyé pour **tout** échec d'OTP (anti-énumération) : code
# invalide, expiré, trop d'essais, déjà consommé, ou aucun défi. Ne divulgue
# jamais la cause exacte ni l'existence d'un compte.
_INVALID_OTP_MESSAGE = "Code de réinitialisation invalide ou expiré."


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


@dataclass(frozen=True)
class PasswordResetRequestCommand:
    """Entrée de la **demande** de reset (aucun secret).

    `identifier` est un **téléphone ou un e-mail** ; `client_ip` (optionnelle)
    entre dans la clé d'anti-abus pour ne pas rate-limiter un tiers sur le seul
    identifiant.
    """

    identifier: str
    client_ip: str | None = None


@dataclass(frozen=True)
class PasswordResetConfirmCommand:
    """Entrée de la **confirmation** (nouveau mot de passe en clair, éphémère)."""

    identifier: str
    code: str
    new_password: str


def _classify(raw: str) -> LoginIdentifier | None:
    """Classe l'identifiant ; `None` si vide ou téléphone inexploitable.

    Un identifiant inclassable ne divulgue rien : le parcours continue et aboutit
    au même comportement générique (202 à la demande, 400 à la confirmation).
    """

    cleaned = raw.strip() if isinstance(raw, str) else ""
    if not cleaned:
        return None
    try:
        return classify_identifier(cleaned)
    except InvalidPhone:
        return None


def _channel_for(identifier: LoginIdentifier) -> str:
    """Canal de remise dérivé du type d'identifiant : e-mail ⇒ EMAIL, sinon SMS."""

    if identifier.kind == EMAIL:
        return NotificationChannel.EMAIL.value
    return NotificationChannel.SMS.value


class RequestPasswordReset:
    """Cas d'usage : **demande** d'un code de réinitialisation (idempotent côté réponse)."""

    def __init__(
        self,
        repository: UserRepository,
        otp_repository: OtpRepository,
        otp_sender: OtpSender,
        *,
        rate_limiter: LoginRateLimiter | None = None,
        rng: Random | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        otp_length: int = DEFAULT_OTP_LENGTH,
        otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL,
        otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._otp_repository = otp_repository
        self._otp_sender = otp_sender
        self._rate_limiter = rate_limiter
        # RNG cryptographique par défaut (les tests injectent un Random graine).
        self._rng: Random = rng if rng is not None else SystemRandom()
        self._clock = clock if clock is not None else _utc_now
        self._otp_length = otp_length
        self._otp_ttl = otp_ttl
        self._otp_max_attempts = otp_max_attempts

    def execute(self, command: PasswordResetRequestCommand) -> None:
        """Émet un OTP si le compte existe et est `ACTIVE` ; retourne sinon (silencieux).

        Ne renvoie **aucune** donnée : la route répond un 202 uniforme quel que
        soit le résultat (anti-énumération). Lève `TooManyLoginAttempts` (⇒ 429)
        si la clé identifiant+IP est verrouillée.
        """

        identifier = _classify(command.identifier)
        # Clé d'anti-abus : identifiant normalisé (ou brut si inclassable) + IP.
        raw = command.identifier.strip() if isinstance(command.identifier, str) else ""
        key_id = identifier.value if identifier is not None else raw
        limiter_key = f"{key_id}|{command.client_ip or '-'}"

        # Verrou anti-flood AVANT tout accès base (lève TooManyLoginAttempts).
        if self._rate_limiter is not None:
            self._rate_limiter.check(limiter_key)

        creds = self._find(identifier)
        # Toujours générer un défi (même sans compte) pour atténuer l'oracle
        # temporel : le coût RNG est payé dans tous les cas.
        challenge = generate_otp_challenge(
            self._rng,
            self._clock(),
            length=self._otp_length,
            ttl=self._otp_ttl,
            max_attempts=self._otp_max_attempts,
        )
        if (
            identifier is not None
            and creds is not None
            and creds.status == UserStatus.ACTIVE.value
        ):
            # `save` **remplace** un éventuel défi antérieur non consommé.
            self._otp_repository.save(identifier.value, challenge)
            self._otp_sender.send(
                identifier.value,
                challenge.code,
                channel=_channel_for(identifier),
            )

        # Chaque demande compte pour l'anti-flood (succès comme échec).
        if self._rate_limiter is not None:
            self._rate_limiter.record_failure(limiter_key)

    def _find(self, identifier: LoginIdentifier | None) -> UserCredentials | None:
        if identifier is None:
            return None
        if identifier.kind == EMAIL:
            return self._repository.find_by_email(identifier.value)
        return self._repository.find_by_phone(identifier.value)


class ConfirmPasswordReset:
    """Cas d'usage : **confirmation** du reset — vérifie l'OTP puis remplace le condensat."""

    def __init__(
        self,
        repository: UserRepository,
        otp_repository: OtpRepository,
        hasher: PasswordHasher,
        *,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._otp_repository = otp_repository
        self._hasher = hasher
        self._clock = clock if clock is not None else _utc_now

    def execute(self, command: PasswordResetConfirmCommand) -> None:
        """Confirme le reset ; lève `InvalidPassword` (⇒ 422) ou `InvalidOtp` (⇒ 400).

        Effet net en cas de succès : `password_hash` remplacé ⇒ **l'ancien mot de
        passe ne s'authentifie plus** (critère #11). Le défi est supprimé (usage
        unique garanti).
        """

        # 1. Politique de mot de passe (porte sur la politique, pas sur le compte :
        #    ne divulgue pas l'existence). Lève `InvalidPassword` ⇒ 422.
        validate_password(command.new_password)

        # 2. Classer l'identifiant (échec de classification ⇒ « pas de défi »).
        identifier = _classify(command.identifier)
        key = identifier.value if identifier is not None else None

        # 3. Récupérer le défi. Absent ⇒ 400 générique (même chemin qu'un code faux).
        challenge = self._otp_repository.get(key) if key is not None else None
        if challenge is None:
            raise InvalidOtp(_INVALID_OTP_MESSAGE)

        # 4. Vérifier (temps constant, mutation en place).
        status = verify_otp_challenge(challenge, command.code, self._clock())
        if status is not OtpStatus.VALID:
            # Persister l'état muté (matérialise la décrémente d'essais sur INVALID)
            # puis lever un 400 **unique** — aucune divulgation de la cause exacte.
            self._otp_repository.save(key, challenge)
            raise InvalidOtp(_INVALID_OTP_MESSAGE)

        # 5. Retrouver le compte (course rare : compte disparu/non ACTIVE ⇒ 400).
        creds = self._find(identifier)
        if creds is None or creds.status != UserStatus.ACTIVE.value:
            self._otp_repository.delete(key)
            raise InvalidOtp(_INVALID_OTP_MESSAGE)

        # 6-7. Hacher le nouveau mot de passe et remplacer le condensat.
        new_hash = self._hasher.hash(command.new_password)
        self._repository.update_password(creds.id, new_hash)

        # 8. Supprimer le défi (usage unique **garanti** après succès).
        self._otp_repository.delete(key)

    def _find(self, identifier: LoginIdentifier | None) -> UserCredentials | None:
        if identifier is None:
            return None
        if identifier.kind == EMAIL:
            return self._repository.find_by_email(identifier.value)
        return self._repository.find_by_phone(identifier.value)


__all__ = [
    "PasswordResetRequestCommand",
    "PasswordResetConfirmCommand",
    "RequestPasswordReset",
    "ConfirmPasswordReset",
]
