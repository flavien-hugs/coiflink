"""Entités et règles de domaine « fiche client » (domaine pur, US-4.1, #28).

Ces `dataclass` et fonctions découplent l'application du modèle ORM SQLAlchemy
(`adapters/outbound/persistence/models.py::CustomerProfile`) : conformément à
l'hexagonal (ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni
SQLAlchemy.

Ce module porte deux responsabilités **pures** :

- les entités d'écriture/lecture (`CustomerToCreate`, `Customer`), toutes
  rattachées à un salon (`salon_id`) — miroir de l'isolation §11.2 ;
- la **validation** propre à la fiche client (nom, téléphone, genre, notes), qui
  matérialise la spécification US-4.1 « nom, téléphone, genre optionnel, notes
  internes ». Cette validation précède **toute** écriture.

Deux points de sécurité/qualité de donnée :

- le téléphone est normalisé en **E.164** (`domain/phone.py`) : sans forme
  canonique, `0700000000` et `+2250700000000` créeraient deux fiches et
  contourneraient l'unicité `(salon_id, phone)` ;
- les messages d'erreur restent **neutres** : ils ne reprennent jamais le nom, le
  numéro ni les notes (PII, PRD §11.3).

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit les erreurs de
domaine en `422` (cf. `adapters/inbound/customers.py`).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import Gender, values
from coiflink_api.domain.errors import (
    InvalidCustomerFilter,
    InvalidCustomerGender,
    InvalidCustomerName,
    InvalidCustomerNotes,
)
from coiflink_api.domain.phone import normalize_phone
from coiflink_api.domain.time_window import (
    day_end_utc as _day_end_utc,
    day_start_utc as _day_start_utc,
)

# Borne du nom, alignée sur la colonne `String(255)` de `customer_profiles`.
CUSTOMER_NAME_MAX_LENGTH = 255

# Borne des notes internes. La colonne est `TEXT` (non bornée) : cette borne est
# **applicative**, pour ne pas accepter un corps de requête non borné (§12.1).
NOTES_MAX_LENGTH = 2000

# Valeurs de genre autorisées, dérivées de l'énumération du domaine (source de
# vérité partagée avec la contrainte `CHECK` du schéma).
GENDER_VALUES: tuple[str, ...] = values(Gender)


def validate_customer_name(name: str) -> str:
    """Valide et normalise (trim) le nom du client ; lève `InvalidCustomerName`.

    Règles : chaîne non vide après `strip()`, longueur ≤ `CUSTOMER_NAME_MAX_LENGTH`.
    Volontairement **séparée** de `validate_name` (compte utilisateur) et de
    `validate_service_name` : l'erreur est distincte et mappée distinctement par
    l'adapter entrant. Le message ne reprend jamais le nom soumis (PII, §11.3).
    """

    if not isinstance(name, str):
        raise InvalidCustomerName("Le nom du client est requis.")
    cleaned = name.strip()
    if not cleaned:
        raise InvalidCustomerName("Le nom du client est requis.")
    if len(cleaned) > CUSTOMER_NAME_MAX_LENGTH:
        raise InvalidCustomerName(
            f"Le nom du client ne doit pas dépasser "
            f"{CUSTOMER_NAME_MAX_LENGTH} caractères."
        )
    return cleaned


def normalize_customer_phone(phone: str | None) -> str | None:
    """Normalise le téléphone **optionnel** en E.164 ; `None` si absent ou vide.

    Le téléphone d'une fiche est optionnel (la colonne est nullable et le modèle
    documente explicitement les clients **walk-in** : exiger un numéro empêcherait
    de ficher un client de passage). Fourni, il est normalisé par
    `domain/phone.py::normalize_phone` (indicatif par défaut `+225`, idempotent),
    qui lève `InvalidPhone` si le numéro est malformé.

    Cette forme canonique est ce qui rend l'unicité `(salon_id, phone)` **effective**.
    """

    if phone is None:
        return None
    if isinstance(phone, str) and not phone.strip():
        return None
    # Type non-`str` compris : `normalize_phone` lève `InvalidPhone`.
    return normalize_phone(phone)


def normalize_gender(value: str | None) -> str | None:
    """Normalise le genre **optionnel** : `None`/vide → `None`, sinon valeur fermée.

    La comparaison porte sur la **valeur exacte** de l'énumération `Gender` : rien
    n'est deviné ni corrigé (ni casse, ni synonyme) — une valeur inconnue lève
    `InvalidCustomerGender`. Le genre n'est **jamais** déduit du prénom ni d'une
    autre donnée (collecte minimale, §11.3).
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidCustomerGender("Le genre du client est invalide.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned not in GENDER_VALUES:
        raise InvalidCustomerGender("Le genre du client est invalide.")
    return cleaned


def normalize_notes(notes: str | None) -> str | None:
    """Normalise les notes internes : trim, `None` si vide, ≤ `NOTES_MAX_LENGTH`.

    Les notes sont **internes au salon** et potentiellement sensibles (le PRD
    US-4.5 cite les allergies) : le message d'erreur ne reprend jamais leur
    contenu. Trop longues → `InvalidCustomerNotes`.
    """

    if notes is None:
        return None
    if not isinstance(notes, str):
        raise InvalidCustomerNotes("Les notes internes sont invalides.")
    cleaned = notes.strip()
    if not cleaned:
        return None
    if len(cleaned) > NOTES_MAX_LENGTH:
        raise InvalidCustomerNotes(
            f"Les notes internes ne doivent pas dépasser "
            f"{NOTES_MAX_LENGTH} caractères."
        )
    return cleaned


@dataclass(frozen=True)
class CustomerToCreate:
    """Intention de création d'une fiche (le `salon_id` est **imposé par la portée**).

    `salon_id` provient toujours de la portée validée (`require_salon_scope`),
    jamais du corps de requête : garde-fou anti-élévation de privilège (miroir de
    `ServiceToCreate`). Pas de `user_id` (#28 crée des fiches **walk-in**,
    `user_id = NULL`), pas de `total_visits` ni `last_visit_at` (défauts base,
    alimentés par #29), pas d'`id` (généré côté serveur).
    """

    salon_id: uuid.UUID
    full_name: str
    phone: str | None = None
    gender: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Customer:
    """Fiche client persistée, rattachée à un salon (PRD §9.5).

    `user_id` n'est **pas** porté par l'entité : il vaut toujours `NULL` dans ce
    périmètre et son exposition renseignerait sur l'existence d'un compte
    (anti-oracle §11.1/§11.3, cf. ADR-0026).
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    full_name: str
    phone: str | None
    gender: str | None
    notes: str | None
    last_visit_at: datetime.datetime | None
    total_visits: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class CustomerFilter:
    """Critères **validés** de filtrage de la liste des fiches clients.

    Chaque champ est optionnel : `None` = « pas de contrainte ». Les critères se
    combinent en **ET**. Cet objet est produit **uniquement** par
    `validate_customer_filter` — un `CustomerFilter` en circulation est donc
    toujours cohérent (genre dans l'énumération, plage de dates ordonnée).

    `created_from`/`created_to` sont les jours civils saisis ; `created_at_from`/
    `created_at_to` sont les bornes déjà converties en `datetime` UTC (miroir de
    `TransactionFilter`), pour comparer directement à
    `customer_profiles.created_at` sans que le dépôt ne connaisse le fuseau.
    """

    q: str | None = None
    gender: str | None = None
    created_from: datetime.date | None = None
    created_to: datetime.date | None = None
    created_at_from: datetime.datetime | None = None
    created_at_to: datetime.datetime | None = None

    @property
    def is_empty(self) -> bool:
        """`True` si aucun critère n'est posé (liste complète du salon)."""

        return (
            self.q is None
            and self.gender is None
            and self.created_from is None
            and self.created_to is None
        )


def _validate_filter_q(q: str | None) -> str | None:
    """Valide la **recherche texte optionnelle** (nom) : trim, `""` → `None`."""

    if q is None:
        return None
    if not isinstance(q, str):
        raise InvalidCustomerFilter("Filtre de fiches clients invalide.")
    cleaned = q.strip()
    return cleaned or None


def _validate_filter_gender(gender: str | None) -> str | None:
    """Valide le **genre optionnel du filtre** : dans l'enum fermé, sinon erreur."""

    if gender is None:
        return None
    if not isinstance(gender, str):
        raise InvalidCustomerFilter("Filtre de fiches clients invalide.")
    cleaned = gender.strip()
    if not cleaned:
        return None
    if cleaned not in GENDER_VALUES:
        raise InvalidCustomerFilter("Filtre de fiches clients invalide.")
    return cleaned


def validate_customer_filter(
    *,
    q: str | None = None,
    gender: str | None = None,
    created_from: datetime.date | None = None,
    created_to: datetime.date | None = None,
) -> CustomerFilter:
    """Valide/normalise les critères de filtre → `CustomerFilter`.

    Règles (toutes → `InvalidCustomerFilter`, message métier **neutre**) :

    - **plage ordonnée** : `created_from ≤ created_to` ;
    - **genre** dans l'énumération fermée `GENDER_VALUES` ;
    - `None` (ou chaîne vide de genre/texte) = **pas de contrainte**.

    Les bornes de date sont converties du jour civil `Africa/Abidjan` (UTC+0) vers
    des `datetime` UTC inclusifs, exposés par `created_at_from`/`created_at_to`.
    """

    if created_from is not None and not isinstance(created_from, datetime.date):
        raise InvalidCustomerFilter("Filtre de fiches clients invalide.")
    if created_to is not None and not isinstance(created_to, datetime.date):
        raise InvalidCustomerFilter("Filtre de fiches clients invalide.")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise InvalidCustomerFilter("Filtre de fiches clients invalide.")

    return CustomerFilter(
        q=_validate_filter_q(q),
        gender=_validate_filter_gender(gender),
        created_from=created_from,
        created_to=created_to,
        created_at_from=_day_start_utc(created_from) if created_from is not None else None,
        created_at_to=_day_end_utc(created_to) if created_to is not None else None,
    )


__all__ = [
    "CUSTOMER_NAME_MAX_LENGTH",
    "NOTES_MAX_LENGTH",
    "GENDER_VALUES",
    "validate_customer_name",
    "normalize_customer_phone",
    "normalize_gender",
    "normalize_notes",
    "CustomerToCreate",
    "Customer",
    "CustomerFilter",
    "validate_customer_filter",
]
