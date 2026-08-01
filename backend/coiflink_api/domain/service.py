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
    InvalidServiceFilter,
    InvalidServiceName,
    InvalidServicePrice,
)
from coiflink_api.domain.time_window import (
    day_end_utc as _day_end_utc,
    day_start_utc as _day_start_utc,
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


@dataclass(frozen=True)
class ServiceFilter:
    """Critères **validés** de filtrage du catalogue de prestations.

    Chaque champ est optionnel : `None` = « pas de contrainte ». Les critères se
    combinent en **ET**. Cet objet est produit **uniquement** par
    `validate_service_filter` — un `ServiceFilter` en circulation est donc
    toujours cohérent (plage de dates ordonnée). Miroir de `CustomerFilter`, avec
    une différence : `category` est un texte **libre** (pas d'énumération fermée,
    cf. `normalize_category`) comparé en **égalité exacte**, pas devinée.

    `created_from`/`created_to` sont les jours civils saisis ; `created_at_from`/
    `created_at_to` sont les bornes déjà converties en `datetime` UTC (miroir de
    `CustomerFilter`/`TransactionFilter`), pour comparer directement à
    `services.created_at` sans que le dépôt ne connaisse le fuseau.
    """

    q: str | None = None
    category: str | None = None
    created_from: datetime.date | None = None
    created_to: datetime.date | None = None
    created_at_from: datetime.datetime | None = None
    created_at_to: datetime.datetime | None = None

    @property
    def is_empty(self) -> bool:
        """`True` si aucun critère n'est posé (catalogue complet du salon)."""

        return (
            self.q is None
            and self.category is None
            and self.created_from is None
            and self.created_to is None
        )


def _validate_filter_q(q: str | None) -> str | None:
    """Valide la **recherche texte optionnelle** (nom) : trim, `""` → `None`."""

    if q is None:
        return None
    if not isinstance(q, str):
        raise InvalidServiceFilter("Filtre de prestations invalide.")
    cleaned = q.strip()
    return cleaned or None


def _validate_filter_category(category: str | None) -> str | None:
    """Valide la **catégorie optionnelle du filtre** : texte libre, trim, `""` → `None`.

    Contrairement au genre des fiches clients, la catégorie n'est **pas** une
    énumération fermée (cf. `normalize_category`) : aucune valeur n'est refusée
    ici, seulement normalisée pour une comparaison d'égalité exacte cohérente.
    """

    if category is None:
        return None
    if not isinstance(category, str):
        raise InvalidServiceFilter("Filtre de prestations invalide.")
    cleaned = category.strip()
    return cleaned or None


def validate_service_filter(
    *,
    q: str | None = None,
    category: str | None = None,
    created_from: datetime.date | None = None,
    created_to: datetime.date | None = None,
) -> ServiceFilter:
    """Valide/normalise les critères de filtre → `ServiceFilter`.

    Règles (toutes → `InvalidServiceFilter`, message métier **neutre**) :

    - **plage ordonnée** : `created_from ≤ created_to` ;
    - `None` (ou chaîne vide de texte/catégorie) = **pas de contrainte**.

    Les bornes de date sont converties du jour civil `Africa/Abidjan` (UTC+0) vers
    des `datetime` UTC inclusifs, exposés par `created_at_from`/`created_at_to`.
    """

    if created_from is not None and not isinstance(created_from, datetime.date):
        raise InvalidServiceFilter("Filtre de prestations invalide.")
    if created_to is not None and not isinstance(created_to, datetime.date):
        raise InvalidServiceFilter("Filtre de prestations invalide.")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise InvalidServiceFilter("Filtre de prestations invalide.")

    return ServiceFilter(
        q=_validate_filter_q(q),
        category=_validate_filter_category(category),
        created_from=created_from,
        created_to=created_to,
        created_at_from=_day_start_utc(created_from) if created_from is not None else None,
        created_at_to=_day_end_utc(created_to) if created_to is not None else None,
    )


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
    "ServiceFilter",
    "validate_service_filter",
]
