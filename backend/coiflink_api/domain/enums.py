"""Énumérations métier pures du domaine CoifLink.

Ces énumérations sont des `enum.Enum` Python **sans aucune dépendance**
framework/I/O : conforme à l'ADR-0008, le domaine ne connaît ni FastAPI ni
SQLAlchemy. Elles constituent la **source de vérité** des valeurs autorisées
pour les colonnes à domaine fermé (rôles, statuts, modes de paiement…).

La couche de persistance (`adapters/outbound/persistence/`) **dérive de ces
énumérations** les contraintes `CHECK` du schéma : les valeurs stockées en base
restent ainsi mécaniquement alignées sur le domaine (pas de divergence
Python ↔ SQL). Les valeurs reprennent celles du PRD §9.

Chaque énumération hérite de `str` afin que, par exemple, `Role.CLIENT ==
"CLIENT"` et que la valeur sérialisée soit directement le texte stocké en base.
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """Base : énumération dont la valeur est la chaîne stockée en base."""

    def __str__(self) -> str:  # pragma: no cover - confort d'affichage
        return self.value


class Role(_StrEnum):
    """Rôles utilisateur (PRD §9.1)."""

    CLIENT = "CLIENT"
    HAIRDRESSER = "HAIRDRESSER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class UserStatus(_StrEnum):
    """Statut de compte (désactivation logique — PRD §11.3)."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class SalonStatus(_StrEnum):
    """Statut d'un salon (un salon inactif n'est plus visible — PRD §8.3)."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class AppointmentStatus(_StrEnum):
    """Statuts d'un rendez-vous (PRD §9.4)."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class PaymentMethod(_StrEnum):
    """Modes de paiement MVP (PRD §9.6)."""

    CASH = "CASH"
    MOBILE_MONEY_MANUAL = "MOBILE_MONEY_MANUAL"
    CARD_MANUAL = "CARD_MANUAL"
    OTHER = "OTHER"


class PaymentStatus(_StrEnum):
    """Statuts d'un paiement (PRD §9.6)."""

    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    CANCELLED = "CANCELLED"
    ADJUSTED = "ADJUSTED"


class CashOperationType(_StrEnum):
    """Types d'opération du journal de caisse (PRD §9.7)."""

    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    CASH_OPENING = "CASH_OPENING"
    CASH_CLOSING = "CASH_CLOSING"


class NotificationType(_StrEnum):
    """Type métier d'une notification (PRD §8.4)."""

    CONFIRMATION = "CONFIRMATION"
    REMINDER = "REMINDER"
    CANCELLATION = "CANCELLATION"


class NotificationChannel(_StrEnum):
    """Canaux de notification (PRD §9.8)."""

    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    IN_APP = "IN_APP"


class NotificationStatus(_StrEnum):
    """Statut d'acheminement d'une notification."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"


def values(enum_cls: type[_StrEnum]) -> tuple[str, ...]:
    """Retourne les valeurs textuelles d'une énumération, dans l'ordre déclaré.

    Utilisé par la couche de persistance pour générer les contraintes `CHECK`
    à partir du domaine.
    """

    return tuple(member.value for member in enum_cls)


__all__ = [
    "Role",
    "UserStatus",
    "SalonStatus",
    "AppointmentStatus",
    "PaymentMethod",
    "PaymentStatus",
    "CashOperationType",
    "NotificationType",
    "NotificationChannel",
    "NotificationStatus",
    "values",
]
