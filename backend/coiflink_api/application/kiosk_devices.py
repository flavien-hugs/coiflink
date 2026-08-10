"""Cas d'usage : **provisioning des bornes kiosque** par un gérant (US-8.1, #155).

Orchestre la création, la lecture et la révocation d'une **borne kiosque** —
compte de service durable, scopé à un salon, sur lequel #156/#157 poseront les
gardes du parcours walk-in **sans jamais** accorder `CUSTOMER_MANAGE` ni
`APPOINTMENT_BOOK` (ADR-0041).

Comme `CreateEmployee` (#13/#150), ces cas d'usage ne dépendent que de **ports**
(aucune dépendance FastAPI/SQLAlchemy). Le geste de provisioning est le **même**
qu'une création d'employé — compte de service au lieu d'un compte personnel,
secret **généré** au lieu d'un mot de passe choisi :

**Provisioning** — valider le libellé → **générer** un secret aléatoire
(`secrets.token_urlsafe(32)`, ~43 caractères, 256 bits d'entropie) → **hacher**
(port `PasswordHasher`, argon2id) → **créer** les deux lignes (compte `users`
`KIOSK` + rattachement `salon_members`, atomiques) → **journaliser**
`KIOSK_DEVICE_PROVISIONED` (`metadata = {}`, ni secret ni condensat ni libellé) →
retourner l'entité **et le secret en clair, une seule fois**. Le secret n'est
**jamais** persisté en clair, **jamais** journalisé, **jamais** relisible.

**Révocation** — suspension logique (jamais une suppression, traçabilité §11.4) :
audit `KIOSK_DEVICE_REVOKED`, effet immédiat (relecture du statut par requête).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
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

# Longueur (en octets) du secret device : 32 octets → ~43 caractères URL-safe,
# 256 bits d'entropie. Ce qui est **long** est le secret révocable (stocké côté
# borne), jamais le jeton porteur (JWT courts, ADR-0041).
_SECRET_NBYTES = 32


@dataclass(frozen=True)
class ProvisionKioskDeviceCommand:
    """Données d'entrée du provisioning (aucun secret : il est **généré** serveur).

    `label` est le libellé de borne composé par le gérant (ex. « Borne entrée »).
    Aucun champ `salon_id` (il est la **cible** de portée, passée séparément) ni
    `role`/`status` (fixés côté serveur).
    """

    label: str


class ProvisionKioskDevice:
    """Provisionne une borne et retourne l'entité **+ le secret en clair (une fois)**."""

    def __init__(
        self,
        repository: KioskDeviceRepository,
        hasher: PasswordHasher,
        audit_log: AuditLog,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        command: ProvisionKioskDeviceCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> tuple[KioskDevice, str]:
        """Crée la borne du `salon_id` ; retourne `(device, secret_en_clair)`.

        `salon_id` provient de la **portée** (jamais de la commande) : la borne est
        rattachée à ce salon, figé une fois. Le secret retourné n'est **jamais**
        persisté en clair ni journalisé — seule son empreinte argon2id est stockée.
        """

        label = validate_device_label(command.label)
        secret = secrets.token_urlsafe(_SECRET_NBYTES)
        password_hash = self._hasher.hash(secret)

        device = self._repository.create(
            KioskDeviceToCreate(
                salon_id=salon_id,
                label=label,
                password_hash=password_hash,
            )
        )

        # Audit §11.4 dans la **même** unité de travail que la création (patron #13/#20) :
        # entrée **neutre** — ni secret, ni condensat, ni libellé au journal.
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

        return device, secret


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
