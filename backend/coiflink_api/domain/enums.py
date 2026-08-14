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

from enum import Enum, unique


@unique
class _StrEnum(str, Enum):
    """Base : énumération dont la valeur est la chaîne stockée en base."""

    def __str__(self) -> str:  # pragma: no cover - confort d'affichage
        return self.value


@unique
class Role(_StrEnum):
    """Rôles utilisateur (PRD §9.1) + identité de terminal (US-8.1, #155).

    `TERMINAL` est un **compte de service** — jamais un humain : c'est l'identité
    d'une **borne terminal** en libre-service (jalon M7). Une borne s'authentifie
    avec un credential de device longue durée (`POST /auth/terminal/login`), obtient
    une paire JWT courte au rôle `TERMINAL` et ne détient que trois permissions
    dédiées et minimales (`CUSTOMER_LOOKUP_TERMINAL`, `CUSTOMER_CREATE_WALKIN`,
    `QUEUE_TICKET_CREATE`) — jamais `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK`
    (moindre privilège strict, cf. `domain/permissions.py` et ADR-0041).
    """

    CLIENT = "CLIENT"
    HAIRDRESSER = "HAIRDRESSER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"
    # Compte de service d'une borne terminal (jalon M7, US-8.1) : jamais un humain.
    TERMINAL = "TERMINAL"


@unique
class UserStatus(_StrEnum):
    """Statut de compte (désactivation logique — PRD §11.3)."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


@unique
class SalonStatus(_StrEnum):
    """Statut d'un salon (un salon inactif n'est plus visible — PRD §8.3)."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


@unique
class Gender(_StrEnum):
    """Genre d'une fiche client (US-4.1, #28) — **optionnel** : `NULL` = non renseigné.

    Le PRD ne fixe aucune liste : trois valeurs neutres suffisent au besoin
    (« genre optionnel »). Aucune valeur `UNSPECIFIED` — l'absence est portée par
    `NULL` en base, pour n'avoir **qu'une** représentation du « non renseigné ».
    """

    FEMALE = "FEMALE"
    MALE = "MALE"
    OTHER = "OTHER"


@unique
class PaymentMethod(_StrEnum):
    """Modes de paiement MVP (PRD §9.6)."""

    CASH = "CASH"
    MOBILE_MONEY_MANUAL = "MOBILE_MONEY_MANUAL"
    CARD_MANUAL = "CARD_MANUAL"
    OTHER = "OTHER"


@unique
class PaymentStatus(_StrEnum):
    """Statuts d'un paiement (PRD §9.6)."""

    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    CANCELLED = "CANCELLED"
    ADJUSTED = "ADJUSTED"


@unique
class CashOperationType(_StrEnum):
    """Types d'opération du journal de caisse (PRD §9.7)."""

    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    CASH_OPENING = "CASH_OPENING"
    CASH_CLOSING = "CASH_CLOSING"


@unique
class NotificationChannel(_StrEnum):
    """Canaux de notification (PRD §9.8)."""

    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    IN_APP = "IN_APP"


@unique
class CampaignType(_StrEnum):
    """Type métier d'une campagne/message aux clients (PRD §8.4, US-7.5, #49).

    Les trois exemples « campagnes simples » du backlog (Épic 7) : un **rappel**
    générique, une **promotion** et une **fermeture exceptionnelle**. Le **titre**
    et le **corps** d'une campagne sont **composés par le gérant** (texte libre
    validé). La colonne `type` (`campaigns`, migration `0009`) en dérive son
    `CHECK` via `models.py::enum_check`.
    """

    REMINDER = "REMINDER"
    PROMOTION = "PROMOTION"
    EXCEPTIONAL_CLOSURE = "EXCEPTIONAL_CLOSURE"


@unique
class CampaignSegment(_StrEnum):
    """Segment ciblé d'une campagne — prédicat **salon-scopé** sur les fiches (#28).

    Le segment est un prédicat **structuré et fermé** sur `customer_profiles` du
    salon (isolation §11.2). Au MVP : **tout le fichier** (`ALL`) ou un segment
    **par genre** (`FEMALE`/`MALE`/`OTHER`) — réutilisant le `CustomerFilter`
    existant (#28/#35) et sa brique `count_for_salon` (aucun nouveau chemin
    d'agrégat). Les valeurs de genre reprennent celles de `Gender` (fiche client)
    afin que `campaigns.segment` se traduise directement en `CustomerFilter`.
    """

    ALL = "ALL"
    FEMALE = "FEMALE"
    MALE = "MALE"
    OTHER = "OTHER"


@unique
class CampaignStatus(_StrEnum):
    """Statut d'émission/remise d'une campagne (US-7.5, #49).

    Au MVP, une campagne est **émise/tracée** (`PENDING`) mais jamais remise : le
    worker de remise (M5+, ADR-0006) passera `SENT` (fan-out SMS effectué) ou
    `FAILED`. Enum **dédié** (cycle de vie propre à la campagne).
    """

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


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
    "Gender",
    "PaymentMethod",
    "PaymentStatus",
    "CashOperationType",
    "NotificationChannel",
    "CampaignType",
    "CampaignSegment",
    "CampaignStatus",
    "values",
]
