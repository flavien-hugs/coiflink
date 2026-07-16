"""Entités et règles de domaine « prestation » (domaine pur, US-2.3, #17).

Ces `dataclass` et fonctions découplent l'application du modèle ORM SQLAlchemy
(`adapters/outbound/persistence/models.py::Service`) : conformément à l'hexagonal
(ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni SQLAlchemy.

Ce module porte deux responsabilités **pures** :

- les entités de lecture/écriture (`ServiceToCreate`, `ServiceUpdate`, `Service`),
  toutes rattachées à un salon (`salon_id`) — miroir de l'isolation §11.2 ;
- la **validation** propre à la prestation (`validate_service_name`,
  `validate_price`, `validate_duration`, `normalize_category`), qui matérialise
  les critères d'acceptation « durée et prix obligatoires » (US-2.3). Cette
  validation précède **toute** écriture ; les contraintes `CHECK` de la table
  (`price >= 0`, `duration_minutes > 0`) ne sont qu'un filet de sécurité base.

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit les erreurs de
domaine en `422` (cf. `adapters/inbound/services.py`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.errors import (
    InvalidServiceCategory,
    InvalidServiceDuration,
    InvalidServiceName,
    InvalidServicePrice,
)

# Bornes du nom et de la catégorie (cohérentes avec `models.Service`).
SERVICE_NAME_MAX_LENGTH = 255
CATEGORY_MAX_LENGTH = 128

# Bornes de valeur. Le prix est aligné sur la colonne `NUMERIC(12,2)` : au plus
# 2 décimales et au plus `99999999.99`. La durée est bornée à une journée
# (robustesse — une prestation ne dure pas plus de 24 h, budget PRD §12).
_PRICE_MIN = decimal.Decimal("0")
_PRICE_MAX = decimal.Decimal("99999999.99")
_DURATION_MAX_MINUTES = 24 * 60


def validate_service_name(name: str) -> str:
    """Valide et normalise (trim) le nom de la prestation ; lève `InvalidServiceName`.

    Règles : chaîne non vide après `strip()`, longueur ≤ `SERVICE_NAME_MAX_LENGTH`.
    Volontairement **séparée** de `validate_salon_name` : l'erreur est distincte et
    mappée distinctement par l'adapter entrant.
    """

    if not isinstance(name, str):
        raise InvalidServiceName("Le nom de la prestation est requis.")
    cleaned = name.strip()
    if not cleaned:
        raise InvalidServiceName("Le nom de la prestation est requis.")
    if len(cleaned) > SERVICE_NAME_MAX_LENGTH:
        raise InvalidServiceName(
            f"Le nom de la prestation ne doit pas dépasser "
            f"{SERVICE_NAME_MAX_LENGTH} caractères."
        )
    return cleaned


def validate_price(price: decimal.Decimal | int | None) -> decimal.Decimal:
    """Valide le **prix obligatoire** : requis, numérique, `>= 0`, ≤ `_PRICE_MAX`.

    Critère d'acceptation US-2.3 (« prix obligatoire »). Accepte un `Decimal` ou un
    entier (jamais un flottant, ni un booléen), refuse `None`, les valeurs non
    finies, négatives, hors borne, ou comportant plus de 2 décimales (au-delà de la
    précision `NUMERIC(12,2)`). Lève `InvalidServicePrice` sinon.
    """

    if isinstance(price, bool) or price is None:
        raise InvalidServicePrice("Le prix de la prestation est requis.")
    if isinstance(price, int):
        price = decimal.Decimal(price)
    if not isinstance(price, decimal.Decimal):
        raise InvalidServicePrice("Le prix de la prestation est requis.")
    if not price.is_finite():
        raise InvalidServicePrice("Le prix de la prestation est invalide.")
    if price < _PRICE_MIN:
        raise InvalidServicePrice("Le prix de la prestation doit être positif ou nul.")
    if price > _PRICE_MAX:
        raise InvalidServicePrice("Le prix de la prestation est hors des bornes autorisées.")
    exponent = price.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise InvalidServicePrice(
            "Le prix ne doit pas comporter plus de deux décimales."
        )
    return price


def validate_duration(minutes: int | None) -> int:
    """Valide la **durée obligatoire** : requise, entière, `> 0`, ≤ 24 h.

    Critère d'acceptation US-2.3 (« durée obligatoire »). Refuse `None`, les
    booléens, les non-entiers, `0`, les négatifs et les valeurs au-delà d'une
    journée. Lève `InvalidServiceDuration` sinon.
    """

    if isinstance(minutes, bool) or minutes is None or not isinstance(minutes, int):
        raise InvalidServiceDuration("La durée de la prestation est requise.")
    if minutes <= 0:
        raise InvalidServiceDuration(
            "La durée de la prestation doit être strictement positive."
        )
    if minutes > _DURATION_MAX_MINUTES:
        raise InvalidServiceDuration(
            "La durée de la prestation dépasse la borne autorisée (24 h)."
        )
    return minutes


def normalize_category(category: str | None) -> str | None:
    """Normalise la catégorie **libre** : `strip()`, `None` si vide, ≤ 128 caractères.

    La catégorie n'est pas énumérée au MVP (le PRD ne fixe pas de liste) : texte
    libre borné. Une catégorie absente ou vide est normalisée en `None` ; une
    catégorie trop longue lève `InvalidServiceCategory`.
    """

    if category is None:
        return None
    if not isinstance(category, str):
        raise InvalidServiceCategory("La catégorie de la prestation est invalide.")
    cleaned = category.strip()
    if not cleaned:
        return None
    if len(cleaned) > CATEGORY_MAX_LENGTH:
        raise InvalidServiceCategory(
            f"La catégorie ne doit pas dépasser {CATEGORY_MAX_LENGTH} caractères."
        )
    return cleaned


def normalize_description(description: str | None) -> str | None:
    """Normalise la description optionnelle : `None` si vide (aucune borne dure).

    La colonne est `TEXT` (non bornée) : on se contente de replier une chaîne vide
    ou blanche sur `None` pour ne pas persister de description « fantôme ».
    """

    if description is None:
        return None
    cleaned = description.strip()
    return cleaned or None


@dataclass(frozen=True)
class ServiceToCreate:
    """Intention de création d'une prestation (le `salon_id` est **imposé par la portée**).

    `salon_id` provient toujours de la portée validée (`require_salon_scope`),
    jamais du corps de requête : garde-fou anti-élévation de privilège (miroir du
    `owner_id` absent de `CreateSalonRequest`). `is_active` n'est pas ici : la
    création force `is_active=True`.
    """

    salon_id: uuid.UUID
    name: str
    price: decimal.Decimal
    duration_minutes: int
    description: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class ServiceUpdate:
    """Champs modifiables d'une prestation (sémantique *replace* du `PUT`).

    Prix et durée restent **obligatoires** à la modification (mêmes règles qu'à la
    création). `is_active` n'est **pas** modifiable ici : la (dés)activation passe
    par une action dédiée (cf. `DeactivateService`).
    """

    name: str
    price: decimal.Decimal
    duration_minutes: int
    description: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class Service:
    """Prestation persistée, rattachée à un salon (PRD §9.3)."""

    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    description: str | None
    price: decimal.Decimal
    duration_minutes: int
    category: str | None
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


__all__ = [
    "SERVICE_NAME_MAX_LENGTH",
    "CATEGORY_MAX_LENGTH",
    "validate_service_name",
    "validate_price",
    "validate_duration",
    "normalize_category",
    "normalize_description",
    "ServiceToCreate",
    "ServiceUpdate",
    "Service",
]
