"""Entités de domaine « borne kiosque » et validation (domaine pur, US-8.1, #155).

Ces `dataclass` découplent l'application du modèle ORM SQLAlchemy : conformément à
l'hexagonal (ADR-0008), ni `domain/` ni `application/` n'importent SQLAlchemy. La
borne est, côté persistance, un **compte de service** `users` (rôle `KIOSK`) +
rattachement `salon_members` (portée mono-salon) — mais ce détail est encapsulé
par le port `KioskDeviceRepository` : le domaine ne connaît que la **forme** d'une
borne (identité opaque, libellé, statut) et de son credential.

**Invariant de non-fuite (§11.3)** : `KioskDevice` — la vue exposée au gérant —
ne porte **jamais** le secret ni son condensat. Seul `KioskDeviceCredentials`
(strictement interne, jamais sérialisé) transporte le `password_hash`, utilisé par
l'authentification du device (`POST /auth/kiosk/login`).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.errors import InvalidKioskDeviceLabel

# Aligné sur `users.full_name` (`String(255)`) : le libellé de la borne est stocké
# comme nom d'affichage du compte de service (ce n'est pas une PII).
DEVICE_LABEL_MAX_LENGTH = 255


def validate_device_label(label: str) -> str:
    """Valide et normalise (trim) le libellé d'une borne ; lève `InvalidKioskDeviceLabel`.

    Le libellé est **composé par le gérant** (ex. « Borne entrée ») : vide après
    `strip()` ou trop long → refus **avant** toute écriture (jamais un `500` de
    violation de colonne). Message neutre — il ne reprend jamais la valeur soumise.
    """

    if not isinstance(label, str):
        raise InvalidKioskDeviceLabel("Le libellé de la borne est requis.")
    cleaned = label.strip()
    if not cleaned:
        raise InvalidKioskDeviceLabel("Le libellé de la borne est requis.")
    if len(cleaned) > DEVICE_LABEL_MAX_LENGTH:
        raise InvalidKioskDeviceLabel(
            f"Le libellé ne doit pas dépasser {DEVICE_LABEL_MAX_LENGTH} caractères."
        )
    return cleaned


@dataclass(frozen=True)
class KioskDeviceToCreate:
    """Borne prête à être persistée (libellé normalisé, secret **déjà haché**).

    `salon_id` est la **cible** validée en amont par la garde de portée
    (`require_salon_scope`) : le gérant ne provisionne que **son** salon. Porte le
    condensat argon2id (`password_hash`), jamais le secret en clair.
    """

    salon_id: uuid.UUID
    label: str
    password_hash: str


@dataclass(frozen=True)
class KioskDevice:
    """Borne persistée, telle qu'exposée au gérant — **sans aucun secret**.

    `id` est l'identifiant public du device (à saisir sur la borne au premier
    lancement). `status` reflète l'état du compte de service (`ACTIVE` → révoqué
    `SUSPENDED`). Ne porte **jamais** le secret ni son condensat.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    label: str
    status: str
    created_at: datetime.datetime


@dataclass(frozen=True)
class KioskDeviceCredentials:
    """Credential d'une borne — **strictement interne** (jamais sérialisé).

    Porte le `password_hash` (nécessaire à `PasswordHasher.verify`) : à n'utiliser
    que dans la couche d'authentification du device (`POST /auth/kiosk/login`),
    jamais dans un schéma de réponse. `salon_id` est retourné à la borne dans la
    réponse de login (elle apprend son salon au provisioning, sans configuration
    compilée).
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    password_hash: str
    status: str


__all__ = [
    "DEVICE_LABEL_MAX_LENGTH",
    "validate_device_label",
    "KioskDeviceToCreate",
    "KioskDevice",
    "KioskDeviceCredentials",
]
