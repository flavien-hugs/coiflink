"""Cas d'usage : **inscription en libre-service** (application, ADR-0008).

Orchestre l'inscription publique — client (US-1.1, issue #8) **et** gérant
(US-2.1 prérequis, issue #9) — en s'appuyant uniquement sur des **ports**
(interfaces) : aucune dépendance à FastAPI, SQLAlchemy, argon2 ou au SMS. Le
câblage des adapters concrets est fait par le composition root (`main.py`).

Le **rôle est imposé côté serveur** à la construction du cas d'usage (par le
chemin d'inscription / l'assemblage), **jamais** par un champ de la requête, et
validé contre la liste blanche `SELF_REGISTERABLE_ROLES` (garde-fou
anti-élévation de privilège : un appelant ne peut pas se déclarer `ADMIN` ou
`HAIRDRESSER`).

Séquence : valider les entrées → **normaliser le téléphone** (forme canonique) →
**pré-vérifier le doublon** → **hacher** le mot de passe → **persister**
(rôle imposé, `status=ACTIVE`) → si activé, émettre un OTP (capacité testable,
envoi différé M5) → retourner l'entité créée **sans** secret.

Garde-fous : le mot de passe en clair n'est ni journalisé ni conservé au-delà de
l'appel de hachage ; le refus de doublon est garanti par le pré-check **et** par
la contrainte base (l'adapter retraduit l'`IntegrityError` concurrente en
`PhoneAlreadyInUse`).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from random import Random, SystemRandom
from typing import Callable

from coiflink_api.application.ports.otp_repository import OtpRepository
from coiflink_api.application.ports.otp_sender import OtpSender
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import PhoneAlreadyInUse, RoleNotSelfRegisterable
from coiflink_api.domain.otp import (
    DEFAULT_OTP_LENGTH,
    DEFAULT_OTP_MAX_ATTEMPTS,
    DEFAULT_OTP_TTL,
    generate_otp_challenge,
)
from coiflink_api.domain.password import validate_password
from coiflink_api.domain.phone import normalize_phone
from coiflink_api.domain.user import (
    SELF_REGISTERABLE_ROLES,
    User,
    UserToCreate,
    validate_name,
)


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


@dataclass(frozen=True)
class RegisterCommand:
    """Données d'entrée du cas d'usage (mot de passe en clair, éphémère)."""

    full_name: str
    phone: str
    password: str
    email: str | None = None


class RegisterUser:
    """Cas d'usage d'inscription en libre-service (rôle imposé côté serveur).

    Le `role` est fixé **à la construction** (par le chemin d'inscription /
    l'assemblage), jamais par l'appelant HTTP, et validé contre
    `SELF_REGISTERABLE_ROLES` : seuls `CLIENT` et `MANAGER` peuvent s'auto-inscrire.
    Un rôle hors liste blanche lève `RoleNotSelfRegisterable` dès la construction
    (garde-fou anti-élévation de privilège, défense en profondeur).
    """

    def __init__(
        self,
        repository: UserRepository,
        hasher: PasswordHasher,
        *,
        role: Role = Role.CLIENT,
        otp_enabled: bool = False,
        otp_sender: OtpSender | None = None,
        otp_repository: OtpRepository | None = None,
        rng: Random | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        otp_length: int = DEFAULT_OTP_LENGTH,
        otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL,
        otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
    ) -> None:
        if role not in SELF_REGISTERABLE_ROLES:
            # Erreur de programmation/câblage : ne doit jamais provenir d'une
            # requête (aucun endpoint n'expose le choix du rôle).
            raise RoleNotSelfRegisterable(
                "Ce rôle ne peut pas être attribué par auto-inscription."
            )
        self._role = role
        self._repository = repository
        self._hasher = hasher
        self._otp_enabled = otp_enabled
        self._otp_sender = otp_sender
        self._otp_repository = otp_repository
        # RNG cryptographique par défaut (les tests injectent un Random graine).
        self._rng: Random = rng if rng is not None else SystemRandom()
        self._clock = clock if clock is not None else _utc_now
        self._otp_length = otp_length
        self._otp_ttl = otp_ttl
        self._otp_max_attempts = otp_max_attempts

    def execute(self, command: RegisterCommand) -> User:
        """Crée le compte (rôle imposé) et retourne l'entité (sans secret)."""

        name = validate_name(command.full_name)
        validate_password(command.password)
        phone = normalize_phone(command.phone)
        email = command.email or None

        # Pré-vérification applicative du doublon (message clair → 409).
        if self._repository.phone_exists(phone):
            raise PhoneAlreadyInUse(
                "Ce numéro de téléphone est déjà associé à un compte."
            )

        password_hash = self._hasher.hash(command.password)

        to_create = UserToCreate(
            full_name=name,
            phone=phone,
            password_hash=password_hash,
            email=email,
            role=self._role.value,
            status=UserStatus.ACTIVE.value,
        )
        # `create` peut lever PhoneAlreadyInUse (fallback course concurrente via
        # la contrainte base `uq_users_phone`) : on laisse remonter tel quel.
        user = self._repository.create(to_create)

        if self._otp_enabled:
            self._issue_otp(phone)

        return user

    def _issue_otp(self, phone: str) -> None:
        """Génère, stocke et déclenche l'envoi d'un OTP (envoi stub en #8).

        Non bloquant : l'inscription reste valable même sans infra SMS (M5). Le
        code n'est jamais retourné ni journalisé.
        """

        challenge = generate_otp_challenge(
            self._rng,
            self._clock(),
            length=self._otp_length,
            ttl=self._otp_ttl,
            max_attempts=self._otp_max_attempts,
        )
        if self._otp_repository is not None:
            self._otp_repository.save(phone, challenge)
        if self._otp_sender is not None:
            self._otp_sender.send(phone, challenge.code)


# Alias de compatibilité : l'inscription client est simplement `RegisterUser`
# avec le rôle par défaut (`CLIENT`). Conservé pour ne pas casser les imports
# existants (#8) tout en restant DRY (un seul cas d'usage généralisé).
RegisterClient = RegisterUser


__all__ = ["RegisterCommand", "RegisterUser", "RegisterClient"]
