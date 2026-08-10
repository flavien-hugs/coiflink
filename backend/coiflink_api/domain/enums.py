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

    `KIOSK` est un **compte de service** — jamais un humain : c'est l'identité
    d'une **borne kiosque** en libre-service (jalon M7). Une borne s'authentifie
    avec un credential de device longue durée (`POST /auth/kiosk/login`), obtient
    une paire JWT courte au rôle `KIOSK` et ne détient que trois permissions
    dédiées et minimales (`CUSTOMER_LOOKUP_KIOSK`, `CUSTOMER_CREATE_WALKIN`,
    `QUEUE_TICKET_CREATE`) — jamais `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK`
    (moindre privilège strict, cf. `domain/permissions.py` et ADR-0041).
    """

    CLIENT = "CLIENT"
    HAIRDRESSER = "HAIRDRESSER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"
    # Compte de service d'une borne kiosque (jalon M7, US-8.1) : jamais un humain.
    KIOSK = "KIOSK"


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
class AppointmentStatus(_StrEnum):
    """Statuts d'un rendez-vous (PRD §9.4)."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


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
class NotificationType(_StrEnum):
    """Type métier d'une notification (PRD §8.4).

    `NEW_BOOKING` (US-7.3, #47) désigne la notification destinée au **salon** (au
    gérant) à chaque nouvelle réservation — distincte de la `CONFIRMATION` du
    **client** (#45). L'ajouter suppose de **régénérer** le `CHECK` `type`
    (migration `0007`, dérivé de cette énumération via `models.py::enum_check`).

    `APPOINTMENT_UPDATE` (US-7.4, #48) couvre les **autres** changements de statut
    d'un RDV côté client (confirmation/clôture/absence par le gérant) **et** la
    **modification** notifiée au salon — sémantique qu'aucune valeur existante ne
    porte (`CONFIRMATION`/`REMINDER` visent une réservation client, `NEW_BOOKING`
    le salon, `CANCELLATION` une annulation). L'ajouter suppose de **régénérer** le
    `CHECK` `type` (migration `0008`, même patron que `0007`). L'**annulation**
    réutilise `CANCELLATION` — elle n'exige **aucune** migration.
    """

    CONFIRMATION = "CONFIRMATION"
    REMINDER = "REMINDER"
    CANCELLATION = "CANCELLATION"
    NEW_BOOKING = "NEW_BOOKING"
    APPOINTMENT_UPDATE = "APPOINTMENT_UPDATE"


@unique
class NotificationChannel(_StrEnum):
    """Canaux de notification (PRD §9.8)."""

    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    IN_APP = "IN_APP"


@unique
class NotificationStatus(_StrEnum):
    """Statut d'acheminement d'une notification.

    `CANCELLED` (US-7.2, #46) marque un rappel qui ne partira jamais parce que le
    RDV auquel il se rattache a été annulé — la ligne est **conservée** (trace
    §8.4/§11.4) plutôt que supprimée.
    """

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"
    CANCELLED = "CANCELLED"


@unique
class CampaignType(_StrEnum):
    """Type métier d'une campagne/message aux clients (PRD §8.4, US-7.5, #49).

    Les trois exemples « campagnes simples » du backlog (Épic 7) : un **rappel**
    générique, une **promotion** et une **fermeture exceptionnelle**. Contrairement
    aux notifications de RDV (#45–#48, à libellés fixes), le **titre** et le **corps**
    d'une campagne sont **composés par le gérant** (texte libre validé). La colonne
    `type` (`campaigns`, migration `0009`) en dérive son `CHECK` via
    `models.py::enum_check`.
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
    `FAILED`. Enum **dédié** (cycle de vie propre à la campagne), distinct de
    `NotificationStatus` (notifications de RDV).
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
    "AppointmentStatus",
    "Gender",
    "PaymentMethod",
    "PaymentStatus",
    "CashOperationType",
    "NotificationType",
    "NotificationChannel",
    "NotificationStatus",
    "CampaignType",
    "CampaignSegment",
    "CampaignStatus",
    "values",
]
