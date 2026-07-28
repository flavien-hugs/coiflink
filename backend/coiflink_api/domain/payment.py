"""Entités et règles de domaine « paiement » (domaine pur, US-5.1/5.3, #33/#34).

Ces `dataclass` et fonctions découplent l'application du modèle ORM SQLAlchemy
(`adapters/outbound/persistence/models.py::Payment`) : conformément à l'hexagonal
(ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni SQLAlchemy.

Ce module porte deux responsabilités **pures** :

- les entités d'écriture/lecture (`PaymentToCreate`, `Payment`), toutes rattachées
  à un salon (`salon_id`) — miroir de l'isolation §11.2 ;
- la **validation** propre au paiement (montant, mode, référence prestation/RDV,
  devise), qui matérialise la spécification §8.2 « montant + mode + utilisateur
  responsable ; paiement lié à une prestation OU un RDV ». Cette validation précède
  **toute** écriture.

Points de sécurité/qualité de donnée (PRD §8.2/§11.3) :

- le **montant** est un `Decimal` (jamais un flottant), `>= 0`, borné et à au plus
  deux décimales (précision `NUMERIC(12,2)`) ;
- l'**auteur** (`recorded_by`) est **imposé par le principal** authentifié, jamais
  lu du corps de requête (non-répudiation §8.2) ;
- les messages d'erreur restent **neutres** : ils ne reprennent jamais le montant.

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit les erreurs de
domaine en `422` (cf. `adapters/inbound/payments.py`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from collections.abc import Iterable

from coiflink_api.domain.enums import PaymentMethod, PaymentStatus, values
from coiflink_api.domain.errors import (
    InvalidPaymentAmount,
    InvalidPaymentCurrency,
    InvalidPaymentMethod,
    PaymentAmountMismatch,
    PaymentReferenceRequired,
)

# Précision de comparaison des montants : le centime (miroir de `NUMERIC(12,2)`).
# Toute comparaison de cohérence quantifie à ce pas, en `Decimal` (jamais un
# flottant), pour ne jamais dépendre d'un artefact de représentation binaire.
_AMOUNT_QUANTUM = decimal.Decimal("0.01")

# Bornes de montant, alignées sur la colonne `NUMERIC(12,2)` de `payments.amount`
# (contrainte base `CHECK amount >= 0`). Un paiement ne peut pas être négatif.
AMOUNT_MIN = decimal.Decimal("0")
AMOUNT_MAX = decimal.Decimal("9999999999.99")

# Devise unique du MVP (mono-devise XOF/FCFA — PRD §9.6, défaut base `'XOF'`).
DEFAULT_CURRENCY = "XOF"

# Borne de la référence libre (numéro de reçu, id de transaction Mobile Money…),
# alignée sur `payments.reference` (`String(255)`).
REFERENCE_MAX_LENGTH = 255

# Modes de paiement autorisés, dérivés de l'énumération du domaine (source de
# vérité partagée avec la contrainte `CHECK` du schéma).
PAYMENT_METHOD_VALUES: tuple[str, ...] = values(PaymentMethod)


def validate_amount(amount: decimal.Decimal | int | None) -> decimal.Decimal:
    """Valide le **montant obligatoire** d'un paiement : requis, `>= 0`, ≤ `AMOUNT_MAX`.

    Accepte un `Decimal` ou un entier (jamais un flottant, ni un booléen), refuse
    `None`, les valeurs non finies, négatives, hors borne, ou comportant plus de
    deux décimales (au-delà de la précision `NUMERIC(12,2)`). Lève
    `InvalidPaymentAmount` sinon. Le message ne reprend jamais la valeur (§11.3).
    """

    if isinstance(amount, bool) or amount is None:
        raise InvalidPaymentAmount("Le montant du paiement est requis.")
    if isinstance(amount, int):
        amount = decimal.Decimal(amount)
    if not isinstance(amount, decimal.Decimal):
        raise InvalidPaymentAmount("Le montant du paiement est requis.")
    if not amount.is_finite():
        raise InvalidPaymentAmount("Le montant du paiement est invalide.")
    if amount < AMOUNT_MIN:
        raise InvalidPaymentAmount("Le montant du paiement doit être positif ou nul.")
    if amount > AMOUNT_MAX:
        raise InvalidPaymentAmount("Le montant du paiement est hors des bornes autorisées.")
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise InvalidPaymentAmount(
            "Le montant ne doit pas comporter plus de deux décimales."
        )
    return amount


def expected_amount_for_prices(prices: Iterable[decimal.Decimal]) -> decimal.Decimal:
    """Somme (pure) des prix figés d'un RDV → « montant attendu » (§5.3/§8.2, US-5.1).

    Alimente la vérification de cohérence pour un paiement lié à un rendez-vous : le
    montant attendu est la **somme des `price_at_booking`** de ses lignes (prix figés
    à la réservation, source de vérité déjà utilisée par #29/#30/#31 — un changement
    de tarif ultérieur ne réécrit pas l'historique). Le résultat est quantifié au
    centime (`NUMERIC(12,2)`), en `Decimal`. Une somme vide vaut `0.00`.
    """

    total = sum(prices, decimal.Decimal("0"))
    return total.quantize(_AMOUNT_QUANTUM)


def validate_amount_matches(amount: decimal.Decimal, expected: decimal.Decimal) -> None:
    """Vérifie que le montant saisi **correspond** au prix attendu (§5.3/§8.2, US-5.1).

    Cœur de #33 : le PRD impose « le système vérifie que le montant correspond à la
    prestation ». Règle MVP = **égalité stricte au centime** (`amount == expected`),
    la comparaison étant faite en `Decimal` quantifié à `0.01` (jamais un flottant).
    Lève `PaymentAmountMismatch` sinon. Le message reste **neutre** : il ne reprend
    **jamais** ni le montant saisi ni le prix attendu (§11.3).
    """

    if amount.quantize(_AMOUNT_QUANTUM) != expected.quantize(_AMOUNT_QUANTUM):
        raise PaymentAmountMismatch("Le montant ne correspond pas à la prestation.")


def validate_payment_method(method: str | None) -> str:
    """Valide le **mode de paiement obligatoire** ; lève `InvalidPaymentMethod`.

    La comparaison porte sur la **valeur exacte** de l'énumération `PaymentMethod` :
    rien n'est deviné ni corrigé (ni casse, ni synonyme). Message neutre.
    """

    if not isinstance(method, str):
        raise InvalidPaymentMethod("Le mode de paiement est requis.")
    cleaned = method.strip()
    if not cleaned:
        raise InvalidPaymentMethod("Le mode de paiement est requis.")
    if cleaned not in PAYMENT_METHOD_VALUES:
        raise InvalidPaymentMethod("Le mode de paiement est invalide.")
    return cleaned


def validate_currency(currency: str | None) -> str:
    """Valide la devise **optionnelle** ; lève `InvalidPaymentCurrency` sinon.

    Le MVP est mono-devise (§9.6) : seule `DEFAULT_CURRENCY` (XOF) est acceptée.
    `None` retombe sur `DEFAULT_CURRENCY`. Miroir de la colonne `payments.currency`
    (`String(3)`) — refuse toute valeur non conforme **avant** l'écriture plutôt que
    de la laisser produire un `500` de violation de colonne ou un stockage silencieux
    incohérent avec l'affichage (codé en dur sur `DEFAULT_CURRENCY`).
    """

    if currency is None:
        return DEFAULT_CURRENCY
    if not isinstance(currency, str):
        raise InvalidPaymentCurrency("La devise du paiement est invalide.")
    cleaned = currency.strip()
    if not cleaned:
        return DEFAULT_CURRENCY
    if cleaned != DEFAULT_CURRENCY:
        raise InvalidPaymentCurrency("La devise du paiement est invalide.")
    return cleaned


def normalize_reference(reference: str | None) -> str | None:
    """Normalise la référence **optionnelle** : trim, `None` si vide, ≤ borne.

    La référence (numéro de reçu, identifiant de transaction Mobile Money…) est un
    texte libre borné ; sa longueur est déjà contrôlée en amont (Pydantic
    `max_length`). Cette fonction se contente de normaliser : `strip()`, `None` si
    vide, et une troncature défensive à `REFERENCE_MAX_LENGTH` (jamais d'erreur).
    """

    if not isinstance(reference, str):
        return None
    cleaned = reference.strip()
    if not cleaned:
        return None
    return cleaned[:REFERENCE_MAX_LENGTH]


def require_reference_present(
    appointment_id: uuid.UUID | None, service_id: uuid.UUID | None
) -> None:
    """Impose qu'un paiement référence une prestation **ou** un RDV (§8.2).

    Miroir du `CHECK (appointment_id IS NOT NULL OR service_id IS NOT NULL)` de la
    table `payments`. Lève `PaymentReferenceRequired` (→ `422`) si les deux sont
    absents. Le contrôle applicatif produit un message métier clair **avant** que la
    contrainte base ne rejette l'`INSERT`.
    """

    if appointment_id is None and service_id is None:
        raise PaymentReferenceRequired(
            "Un paiement doit être lié à une prestation ou à un rendez-vous."
        )


@dataclass(frozen=True)
class PaymentToCreate:
    """Intention d'enregistrement d'un paiement (le `salon_id`/`recorded_by` imposés).

    `salon_id` provient toujours de la portée validée (`require_salon_scope`) et
    `recorded_by` du `Principal` authentifié (§8.2 « utilisateur responsable ») —
    **jamais** lus du corps de requête (garde-fou anti-répudiation). Pas d'`id`
    (généré côté serveur), pas de `created_at` (horodatage serveur), pas de `status`
    (imposé `VALIDATED` par le cas d'usage).
    """

    salon_id: uuid.UUID
    amount: decimal.Decimal
    payment_method: str
    recorded_by: uuid.UUID
    appointment_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    currency: str = DEFAULT_CURRENCY
    reference: str | None = None
    status: str = PaymentStatus.VALIDATED.value


@dataclass(frozen=True)
class Payment:
    """Paiement persisté, rattaché à un salon (PRD §9.6).

    Entité de lecture **immuable** : un paiement validé n'est jamais supprimé (§8.2)
    ; une correction crée une **ligne d'ajustement** dans `cash_journal` et fait
    passer ce paiement à `status = ADJUSTED` (mutation de statut, jamais un delete).
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    amount: decimal.Decimal
    currency: str
    payment_method: str
    status: str
    recorded_by: uuid.UUID
    appointment_id: uuid.UUID | None
    service_id: uuid.UUID | None
    client_id: uuid.UUID | None
    reference: str | None
    created_at: datetime.datetime


__all__ = [
    "AMOUNT_MIN",
    "AMOUNT_MAX",
    "DEFAULT_CURRENCY",
    "REFERENCE_MAX_LENGTH",
    "PAYMENT_METHOD_VALUES",
    "validate_amount",
    "expected_amount_for_prices",
    "validate_amount_matches",
    "validate_payment_method",
    "validate_currency",
    "normalize_reference",
    "require_reference_present",
    "PaymentToCreate",
    "Payment",
]
