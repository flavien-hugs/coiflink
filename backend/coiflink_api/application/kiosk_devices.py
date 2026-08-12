"""Cas d'usage : **provisioning des bornes kiosque** par un gérant (US-8.1, #155).

Orchestre la création, la lecture et la révocation d'une **borne kiosque** —
compte de service durable, scopé à un salon, sur lequel #156/#157 poseront les
gardes du parcours walk-in **sans jamais** accorder `CUSTOMER_MANAGE` ni
`APPOINTMENT_BOOK` (ADR-0041).

Comme `CreateEmployee` (#13/#150), ces cas d'usage ne dépendent que de **ports**
(aucune dépendance FastAPI/SQLAlchemy). Le geste de provisioning est le **même**
qu'une création d'employé — compte de service au lieu d'un compte personnel,
secret **généré** au lieu d'un mot de passe choisi :

**Provisioning** — valider le libellé → **générer** un secret **jetable** aussitôt
oublié, uniquement pour produire un condensat *placeholder* inutilisable → **hacher**
(port `PasswordHasher`, argon2id) → **créer** les deux lignes (compte `users`
`KIOSK` + rattachement `salon_members`, atomiques) → **émettre un code d'activation
à 6 chiffres** (défi `OtpChallenge`, TTL 24 h, 5 essais) → **journaliser**
`KIOSK_DEVICE_PROVISIONED` (`metadata = {}`, ni code ni condensat ni libellé) →
retourner l'entité **et le code d'activation, une seule fois**.

Le secret **réel** de la borne n'est plus généré ici : il l'est à l'**activation**
(`application/kiosk_device_activation.py::ActivateKioskDevice`), quand la borne
échange les 6 chiffres saisis à l'écran contre son credential longue durée. Motif
(#155, provisioning silencieux) : recopier ~43 caractères sur une tablette tactile
est impraticable. Conséquence de sécurité **inchangée** : aucun secret n'est
**jamais** persisté en clair, **jamais** journalisé, **jamais** relisible — et une
borne non activée ne peut pas s'authentifier (son condensat placeholder ne
correspond à aucun secret connu, `/auth/kiosk/login` échoue déterministiquement).

**Révocation** — suspension logique (jamais une suppression, traçabilité §11.4) :
audit `KIOSK_DEVICE_REVOKED`, effet immédiat (relecture du statut par requête).
"""

from __future__ import annotations

import datetime
import secrets
import uuid
from dataclasses import dataclass
from random import Random, SystemRandom
from typing import Callable

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.kiosk_activation_repository import (
    KioskActivationRepository,
)
from coiflink_api.application.ports.kiosk_device_repository import KioskDeviceRepository
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.domain.audit import (
    ENTITY_TYPE_KIOSK_DEVICE,
    AuditAction,
    AuditEntry,
)
from coiflink_api.domain.errors import KioskDeviceNotFound
from coiflink_api.domain.kiosk_device import (
    KioskDevice,
    KioskDeviceToCreate,
    validate_device_label,
)
from coiflink_api.domain.otp import DEFAULT_OTP_LENGTH, generate_otp_challenge

# Longueur (en octets) du secret **jetable** haché au provisioning : 32 octets →
# ~43 caractères URL-safe, 256 bits d'entropie. Même mécanisme que le secret réel
# émis à l'activation — ici, sa seule fonction est de rendre le condensat
# placeholder **imprédictible et inutilisable** (aucun secret ne le vérifie).
_SECRET_NBYTES = 32

# Paramètres du défi d'activation — volontairement **plus larges** que les défauts
# OTP (5 min / 3 essais, `domain/otp.py`) : l'activation d'une borne est une
# **installation matérielle** (déballer la tablette, la brancher, la poser au
# comptoir), pas une authentification en direct. Une fenêtre d'une journée ouvrée et
# 5 essais absorbent une faute de frappe sur un pavé tactile sans forcer un
# re-provisioning. La surface reste faible : code à usage unique, borne inutilisable
# tant qu'elle n'est pas activée, et endpoint rate-limité par IP.
_ACTIVATION_TTL = datetime.timedelta(hours=24)
_ACTIVATION_MAX_ATTEMPTS = 5


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


@dataclass(frozen=True)
class ProvisionKioskDeviceCommand:
    """Données d'entrée du provisioning (aucun secret : il est **généré** serveur).

    `label` est le libellé de borne composé par le gérant (ex. « Borne entrée »).
    Aucun champ `salon_id` (il est la **cible** de portée, passée séparément) ni
    `role`/`status` (fixés côté serveur).
    """

    label: str


class ProvisionKioskDevice:
    """Provisionne une borne et retourne l'entité **+ le code d'activation (une fois)**."""

    def __init__(
        self,
        repository: KioskDeviceRepository,
        hasher: PasswordHasher,
        audit_log: AuditLog,
        activation_repository: KioskActivationRepository,
        *,
        rng: Random | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._audit_log = audit_log
        self._activation_repository = activation_repository
        # RNG cryptographique par défaut (les tests injectent un Random graine).
        self._rng: Random = rng if rng is not None else SystemRandom()
        self._clock = clock if clock is not None else _utc_now

    def execute(
        self,
        salon_id: uuid.UUID,
        command: ProvisionKioskDeviceCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> tuple[KioskDevice, str]:
        """Crée la borne du `salon_id` ; retourne `(device, code_activation)`.

        `salon_id` provient de la **portée** (jamais de la commande) : la borne est
        rattachée à ce salon, figé une fois. Le code à 6 chiffres retourné n'est
        renvoyé qu'**ici**, une seule fois : la borne l'échange ensuite contre son
        secret longue durée via `ActivateKioskDevice` (`POST /auth/kiosk/activate`),
        seul endroit où un secret est généré. Le condensat écrit à la création est un
        **placeholder** (secret jetable, immédiatement oublié) : il ne correspond à
        aucun secret connu, donc la borne ne peut pas s'authentifier avant activation.
        """

        label = validate_device_label(command.label)
        # Secret **jetable** : jamais retourné, jamais stocké, jamais journalisé — il
        # ne sert qu'à produire un condensat placeholder imprédictible (aucun besoin
        # de cas particulier côté login : la vérification échoue, tout simplement).
        throwaway_secret = secrets.token_urlsafe(_SECRET_NBYTES)
        password_hash = self._hasher.hash(throwaway_secret)

        device = self._repository.create(
            KioskDeviceToCreate(
                salon_id=salon_id,
                label=label,
                password_hash=password_hash,
            )
        )

        # Défi d'activation à 6 chiffres — usage unique, expirant, borné en essais
        # (mêmes propriétés que l'OTP de reset #11, paramètres adaptés au geste
        # d'installation physique, cf. `_ACTIVATION_TTL`/`_ACTIVATION_MAX_ATTEMPTS`).
        challenge = generate_otp_challenge(
            self._rng,
            self._clock(),
            length=DEFAULT_OTP_LENGTH,
            ttl=_ACTIVATION_TTL,
            max_attempts=_ACTIVATION_MAX_ATTEMPTS,
        )
        self._activation_repository.save(device.id, challenge)

        # Audit §11.4 dans la **même** unité de travail que la création (patron #13/#20) :
        # entrée **neutre** — ni code d'activation, ni condensat, ni libellé au journal.
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.KIOSK_DEVICE_PROVISIONED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_KIOSK_DEVICE,
                entity_id=device.id,
                metadata={},
            )
        )

        return device, challenge.code


class ListKioskDevices:
    """Liste les bornes **du salon** (lecture gérant — aucune écriture, aucun audit)."""

    def __init__(self, repository: KioskDeviceRepository) -> None:
        self._repository = repository

    def execute(self, salon_id: uuid.UUID) -> tuple[KioskDevice, ...]:
        return self._repository.list_for_salon(salon_id)


class RevokeKioskDevice:
    """Révoque une borne **du salon** (suspension logique) et journalise (§11.4)."""

    def __init__(
        self, repository: KioskDeviceRepository, audit_log: AuditLog
    ) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        device_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> KioskDevice:
        """Suspend la borne (effet immédiat) ; `KioskDeviceNotFound` si hors salon."""

        device = self._repository.revoke(salon_id, device_id)
        if device is None:
            # Borne inexistante **ou** hors salon : indiscernables (§11.2).
            raise KioskDeviceNotFound("Borne introuvable.")
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.KIOSK_DEVICE_REVOKED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_KIOSK_DEVICE,
                entity_id=device.id,
                metadata={},
            )
        )
        return device


__all__ = [
    "ProvisionKioskDeviceCommand",
    "ProvisionKioskDevice",
    "ListKioskDevices",
    "RevokeKioskDevice",
]
