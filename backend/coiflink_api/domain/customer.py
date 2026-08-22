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
            f"Le nom du client ne doit pas dépasser {CUSTOMER_NAME_MAX_LENGTH} caractères."
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
            f"Les notes internes ne doivent pas dépasser {NOTES_MAX_LENGTH} caractères."
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


# --------------------------------------------------------------------------- #
# Borne terminal — identité walk-in minimale (US-8.2, #156).
# --------------------------------------------------------------------------- #
def walk_in_first_name(full_name: str) -> str:
    """Retourne le **prénom** (premier token) d'un `full_name` déjà validé.

    Projection d'affichage **borne** exigée par le critère d'acceptation US-8.2
    (« n'affiche que le prénom du client »). Le modèle ne stocke qu'un `full_name`
    (`CustomerProfile.full_name`) : plutôt qu'une migration (colonne `first_name`),
    le prénom est **dérivé**. Pour les fiches créées par la borne (composition
    contrôlée « Prénom Nom », cf. `validate_walk_in_customer`) la dérivation est
    exacte ; pour les fiches historiques du gérant elle est heuristique (premier
    token). `full_name` est déjà **trim + non vide** (`validate_customer_name`),
    donc `split()` renvoie au moins un token.
    """

    parts = full_name.split()
    return parts[0] if parts else full_name


@dataclass(frozen=True)
class WalkInIdentity:
    """Projection **minimale** d'une fiche franchissant la frontière HTTP terminal.

    La **seule** donnée exposée à la borne : `customer_id` + `first_name`. Ni
    téléphone (même celui qui vient d'être saisi), ni nom complet, ni genre, ni
    notes, ni compteurs de visites — l'entité `Customer` complète ne sort **jamais**
    vers un terminal public (exposition minimale de PII, §11.3).
    """

    customer_id: uuid.UUID
    first_name: str


@dataclass(frozen=True)
class WalkInCustomerCommand:
    """Champs saisis à la borne pour créer une fiche walk-in (US-8.2, #156).

    Prénom/nom/téléphone sont **requis** au terminal (contrairement au flux gérant
    #28 où le téléphone est optionnel : à la borne, le téléphone est la **clé
    d'identification** — une fiche sans numéro serait introuvable à la visite
    suivante). `gender` est **optionnel** (#172 — deux choix à l'écran borne,
    Homme/Femme ; `normalize_gender` accepte aussi `OTHER` si jamais transmis).
    `notes` et mot de passe restent hors de portée de la borne : collecte minimale
    (§11.3), la fiche reste walk-in (`user_id = NULL`).
    """

    first_name: str
    last_name: str
    phone: str
    gender: str | None = None


def validate_walk_in_customer(command: WalkInCustomerCommand) -> tuple[str, str, str | None]:
    """Valide/compose la commande borne → `(full_name, phone canonique, genre)` (US-8.2, #156).

    Règles (toutes en amont de **tout** accès base) :

    1. `first_name` / `last_name` : trim + non vides (mécanique
       `validate_customer_name`, erreur `InvalidCustomerName`, message neutre) ;
    2. composition **ordonnée** `full_name = "Prénom Nom"` puis
       `validate_customer_name` sur le résultat (borne ≤ 255 sur le composé) —
       l'ordre garantit `walk_in_first_name(full_name) == first_name` saisi ;
    3. `phone` : **requis** — normalisé E.164 par `normalize_phone` **directement**
       (sémantique « requis » : vide/malformé → `InvalidPhone`), jamais par le
       wrapper optionnel `normalize_customer_phone` ;
    4. `gender` : **optionnel** — `normalize_gender` (même règle que le flux gérant
       #28, `InvalidCustomerGender` si valeur hors énumération).
    """

    first_name = validate_customer_name(command.first_name)
    last_name = validate_customer_name(command.last_name)
    full_name = validate_customer_name(f"{first_name} {last_name}")
    phone = normalize_phone(command.phone)
    gender = normalize_gender(command.gender)
    return full_name, phone, gender


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
    # Contrainte de **joignabilité** (US-7.5, #49) : `True` restreint aux fiches
    # portant un téléphone (`phone IS NOT NULL`). `None` = pas de contrainte (la
    # liste des fiches #28 ne la pose jamais). Une campagne SMS l'active pour que
    # l'effectif ciblé ne compte que les fiches réellement joignables (Risks §4).
    has_phone: bool | None = None

    @property
    def is_empty(self) -> bool:
        """`True` si aucun critère n'est posé (liste complète du salon)."""

        return (
            self.q is None
            and self.gender is None
            and self.created_from is None
            and self.created_to is None
            and self.has_phone is None
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
    has_phone: bool | None = None,
) -> CustomerFilter:
    """Valide/normalise les critères de filtre → `CustomerFilter`.

    Règles (toutes → `InvalidCustomerFilter`, message métier **neutre**) :

    - **plage ordonnée** : `created_from ≤ created_to` ;
    - **genre** dans l'énumération fermée `GENDER_VALUES` ;
    - `None` (ou chaîne vide de genre/texte) = **pas de contrainte**.

    Les bornes de date sont converties du jour civil `Africa/Abidjan` (UTC+0) vers
    des `datetime` UTC inclusifs, exposés par `created_at_from`/`created_at_to`.

    `has_phone` (US-7.5, #49) restreint, quand il vaut `True`, aux fiches
    **joignables** par téléphone (`phone IS NOT NULL`) — utilisé pour l'effectif
    d'une campagne SMS ; `None` (défaut) = pas de contrainte de joignabilité.
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
        has_phone=has_phone if has_phone else None,
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
    "walk_in_first_name",
    "WalkInIdentity",
    "WalkInCustomerCommand",
    "validate_walk_in_customer",
    "CustomerFilter",
    "validate_customer_filter",
]
