"""Filtre de l'**historique des transactions** (domaine pur, US-5.2, #35).

Ce module porte l'objet-valeur `TransactionFilter` et sa validation pure
`validate_transaction_filter` : les critères de recherche de la liste filtrable
des paiements d'un salon (date, client, montant, mode de paiement). Conformément
à l'hexagonal (ADR-0008), il ne connaît ni FastAPI ni SQLAlchemy ; l'adapter
entrant traduit `InvalidTransactionFilter` en `422` et le dépôt convertit le
filtre en clauses `WHERE`.

La **source de vérité** de la liste est la table `payments` (les transactions) —
seule table portant à la fois `client_id` **et** `payment_method` — ce qui rend
la liste *cohérente avec le journal de caisse* (#34) puisque les deux vues
dérivent des **mêmes** paiements.

Points de sécurité/qualité de donnée (PRD §11.3) :

- les bornes de montant sont des `Decimal` (jamais un flottant), `>= 0`, bornées
  et à au plus deux décimales (précision `NUMERIC(12,2)`) ;
- le mode de paiement, s'il est fourni, appartient à l'énumération **fermée**
  `PaymentMethod` — aucune valeur n'est devinée ni corrigée ;
- une plage incohérente (`date_from > date_to`, `amount_min > amount_max`) est
  refusée ;
- les messages d'erreur restent **neutres** : ils ne reprennent jamais la valeur
  saisie.

**Interprétation temporelle.** `date_from`/`date_to` sont des **jours civils**
interprétés dans le fuseau `Africa/Abidjan` (UTC+0, convention #21). La
conversion vers des bornes UTC inclusives — `[date_from 00:00:00,
date_to 23:59:59.999999]` — est centralisée ici (l'adapter/le dépôt ne
réinventent aucun fuseau) pour comparer à `payments.created_at`
(`timezone-aware`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import PaymentMethod, values
from coiflink_api.domain.errors import InvalidTransactionFilter
from coiflink_api.domain.payment import AMOUNT_MAX, AMOUNT_MIN, Payment
from coiflink_api.domain.time_window import (
    SALON_TIMEZONE,
    day_end_utc as _day_end_utc,
    day_start_utc as _day_start_utc,
)

# Précision de comparaison des montants : le centime (miroir de `NUMERIC(12,2)`).
_AMOUNT_QUANTUM = decimal.Decimal("0.01")

# Modes de paiement autorisés (source de vérité partagée avec le schéma).
PAYMENT_METHOD_VALUES: tuple[str, ...] = values(PaymentMethod)


@dataclass(frozen=True)
class Transaction:
    """Ligne de l'historique des transactions : un `Payment` + le nom du client.

    Projection de **lecture** de la liste filtrable (#35). Le paiement est la
    transaction telle qu'enregistrée (montant brut + statut : un paiement corrigé
    porte `ADJUSTED`, cohérent avec le journal #34). `client_name` résout, en
    lecture, **soit** `payments.client_id → users.full_name` (compte client
    enregistré), **soit** — pour un paiement lié à un ticket walk-in
    (`queue_ticket_id`) sans compte client — `queue_tickets.customer_profile_id
    → customer_profiles.full_name` (le client de la fiche qui a pris le ticket) ;
    `None` si ni l'un ni l'autre n'est résoluble (paiement comptoir anonyme).
    `ticket_number` accompagne ce nom pour le ticket lié (`None` pour un paiement
    lié à une prestation seule).
    """

    payment: Payment
    client_name: str | None = None
    ticket_number: int | None = None


@dataclass(frozen=True)
class TransactionFilter:
    """Critères **validés** de filtrage de l'historique des transactions (§35).

    Chaque champ est optionnel : `None` = « pas de contrainte ». Les critères se
    combinent en **ET**. Cet objet est produit **uniquement** par
    `validate_transaction_filter` — un `TransactionFilter` en circulation est donc
    toujours cohérent (plages ordonnées, mode dans l'enum, montants bornés).

    Les bornes de date sont exposées **déjà converties** en `datetime` UTC
    (`created_at_from`/`created_at_to`) pour comparer directement à
    `payments.created_at` sans que le dépôt ne connaisse le fuseau.
    """

    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    client_id: uuid.UUID | None = None
    amount_min: decimal.Decimal | None = None
    amount_max: decimal.Decimal | None = None
    payment_method: str | None = None
    q: str | None = None
    created_at_from: datetime.datetime | None = None
    created_at_to: datetime.datetime | None = None

    @property
    def is_empty(self) -> bool:
        """`True` si aucun critère n'est posé (liste complète du salon)."""

        return (
            self.date_from is None
            and self.date_to is None
            and self.client_id is None
            and self.amount_min is None
            and self.amount_max is None
            and self.payment_method is None
            and self.q is None
        )


def _validate_bound(amount: decimal.Decimal | int | None) -> decimal.Decimal | None:
    """Valide une **borne de montant optionnelle** (`>= 0`, ≤ `AMOUNT_MAX`, ≤ 2 déc.).

    `None` = pas de contrainte. Accepte un `Decimal` ou un entier (jamais un
    flottant, ni un booléen). Lève `InvalidTransactionFilter` (message neutre)
    sinon.
    """

    if amount is None:
        return None
    if isinstance(amount, bool):
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    if isinstance(amount, int):
        amount = decimal.Decimal(amount)
    if not isinstance(amount, decimal.Decimal):
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    if not amount.is_finite():
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    if amount < AMOUNT_MIN or amount > AMOUNT_MAX:
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    return amount


def _validate_method(method: str | None) -> str | None:
    """Valide le **mode de paiement optionnel** : dans l'enum fermé, sinon erreur."""

    if method is None:
        return None
    if not isinstance(method, str):
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    cleaned = method.strip()
    if not cleaned:
        return None
    if cleaned not in PAYMENT_METHOD_VALUES:
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    return cleaned


def _validate_q(q: str | None) -> str | None:
    """Valide la **recherche texte optionnelle** (nom client) : trim, `""` → `None`."""

    if q is None:
        return None
    if not isinstance(q, str):
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    cleaned = q.strip()
    return cleaned or None


def validate_transaction_filter(
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    client_id: uuid.UUID | None = None,
    amount_min: decimal.Decimal | int | None = None,
    amount_max: decimal.Decimal | int | None = None,
    payment_method: str | None = None,
    q: str | None = None,
) -> TransactionFilter:
    """Valide/normalise les critères de filtre → `TransactionFilter` (US-5.2, #35).

    Règles (toutes → `InvalidTransactionFilter`, message métier **neutre**) :

    - **plages ordonnées** : `date_from ≤ date_to`, `amount_min ≤ amount_max` ;
    - **montants** bornés `[0, AMOUNT_MAX]`, ≤ 2 décimales, en `Decimal` (jamais
      un flottant) ;
    - **mode de paiement** dans l'énumération fermée `PaymentMethod` ;
    - **recherche texte** (`q`) : sous-chaîne du **nom client** — compte client
      enregistré (`users.full_name`) **ou** client d'un ticket walk-in lié
      (`customer_profiles.full_name`) — même paire de colonnes que `client_name`
      (`ILIKE`, §11.3 aucune autre colonne PII n'est recherchée) ;
    - `None` (ou chaîne vide de mode/texte) = **pas de contrainte**.

    Les bornes de date sont converties du jour civil `Africa/Abidjan` (UTC+0) vers
    des `datetime` UTC inclusifs, exposés par `created_at_from`/`created_at_to`.
    """

    if date_from is not None and not isinstance(date_from, datetime.date):
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    if date_to is not None and not isinstance(date_to, datetime.date):
        raise InvalidTransactionFilter("Filtre de transactions invalide.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidTransactionFilter("Filtre de transactions invalide.")

    min_amount = _validate_bound(amount_min)
    max_amount = _validate_bound(amount_max)
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise InvalidTransactionFilter("Filtre de transactions invalide.")

    method = _validate_method(payment_method)
    cleaned_q = _validate_q(q)

    return TransactionFilter(
        date_from=date_from,
        date_to=date_to,
        client_id=client_id,
        amount_min=min_amount,
        amount_max=max_amount,
        payment_method=method,
        q=cleaned_q,
        created_at_from=_day_start_utc(date_from) if date_from is not None else None,
        created_at_to=_day_end_utc(date_to) if date_to is not None else None,
    )


__all__ = [
    "SALON_TIMEZONE",
    "PAYMENT_METHOD_VALUES",
    "Transaction",
    "TransactionFilter",
    "validate_transaction_filter",
]
