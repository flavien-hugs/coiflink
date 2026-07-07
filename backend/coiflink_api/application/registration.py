"""Cas d'usage : **inscription d'un utilisateur** (application, ADR-0008).

Orchestre le parcours d'inscription commun aux différents rôles — client
(US-1.1, issue #8) et gérant/propriétaire de salon (issue #9) — en s'appuyant
uniquement sur des **ports** (interfaces) : aucune dépendance à FastAPI,
SQLAlchemy, argon2 ou au SMS. Le câblage des adapters concrets est fait par le
composition root (`main.py`).

Le **rôle cible** est un **paramètre de configuration du cas d'usage** (injecté
au câblage), **jamais** lu depuis la commande ni depuis la requête HTTP : un
appelant ne peut donc pas s'auto-attribuer un rôle (garde-fou anti-élévation de
privilège, PRD §11.1). Seul ce rôle diffère entre l'inscription client et
gérant ; tout le reste du parcours est identique.

Séquence : valider les entrées → **normaliser le téléphone** (forme canonique) →
**pré-vérifier le doublon** → **hacher** le mot de passe → **persister** (`role`
injecté, `status=ACTIVE`) → si activé, émettre un OTP (capacité testable, envoi
différé M5) → retourner l'entité créée **sans** secret.

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
from coiflink_api.domain.enums import Role, UserStatus, values
from coiflink_api.domain.errors import PhoneAlreadyInUse
from coiflink_api.domain.otp import (
    DEFAULT_OTP_LENGTH,
    DEFAULT_OTP_MAX_ATTEMPTS,
    DEFAULT_OTP_TTL,
    generate_otp_challenge,
)
from coiflink_api.domain.password import validate_password
from coiflink_api.domain.phone import normalize_phone
from coiflink_api.domain.user import User, UserToCreate, validate_name


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


# Valeurs de rôle autorisées, dérivées du domaine (source de vérité `Role`).
# Sert de garde-fou au câblage : un rôle inconnu échoue à la construction du
# cas d'usage, jamais silencieusement.
_ROLE_VALUES: frozenset[str] = frozenset(values(Role))


@dataclass(frozen=True)
class RegisterCommand:
    """Données d'entrée du cas d'usage (mot de passe en clair, éphémère)."""

    full_name: str
    phone: str
    password: str
    email: str | None = None


class RegisterUser:
    """Cas d'usage d'inscription **générique**, paramétré par le rôle cible.

    Le rôle est fixé au **câblage** (composition root / injection de dépendances),
    jamais lu depuis la commande ni la requête : un appelant ne peut pas choisir
    son rôle (anti-élévation de privilège, PRD §11.1). Le reste du parcours
    d'inscription est identique quel que soit le rôle.
    """

    def __init__(
        self,
        repository: UserRepository,
        hasher: PasswordHasher,
        *,
        role: str = Role.CLIENT.value,
        otp_enabled: bool = False,
        otp_sender: OtpSender | None = None,
        otp_repository: OtpRepository | None = None,
        rng: Random | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        otp_length: int = DEFAULT_OTP_LENGTH,
        otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL,
        otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
    ) -> None:
        if role not in _ROLE_VALUES:
            raise ValueError(f"Rôle d'inscription inconnu : {role!r}")
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
        """Crée le compte (rôle injecté) et retourne l'entité (sans secret)."""

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
            role=self._role,
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


class RegisterClient(RegisterUser):
    """Spécialisation : inscription d'un **client** (rôle `CLIENT` figé, #8).

    Conserve la surface d'appel de #8 tout en réutilisant `RegisterUser` : le
    rôle est verrouillé à `CLIENT` et ne peut pas être surchargé par l'appelant.
    """

    def __init__(
        self,
        repository: UserRepository,
        hasher: PasswordHasher,
        *,
        otp_enabled: bool = False,
        otp_sender: OtpSender | None = None,
        otp_repository: OtpRepository | None = None,
        rng: Random | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        otp_length: int = DEFAULT_OTP_LENGTH,
        otp_ttl: datetime.timedelta = DEFAULT_OTP_TTL,
        otp_max_attempts: int = DEFAULT_OTP_MAX_ATTEMPTS,
    ) -> None:
        super().__init__(
            repository,
            hasher,
            role=Role.CLIENT.value,
            otp_enabled=otp_enabled,
            otp_sender=otp_sender,
            otp_repository=otp_repository,
            rng=rng,
            clock=clock,
            otp_length=otp_length,
            otp_ttl=otp_ttl,
            otp_max_attempts=otp_max_attempts,
        )


__all__ = ["RegisterCommand", "RegisterUser", "RegisterClient"]
