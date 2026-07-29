"""Détection des **écarts de caisse** (domaine pur, US-5.4, #36).

Ce module porte l'objet-valeur de lecture `CashDiscrepancy` — un **rendez-vous
`COMPLETED` sans paiement rattaché** (prestation réalisée mais non encaissée) — et
son filtre de dates `DiscrepancyFilter` / `validate_discrepancy_filter`.
Conformément à l'hexagonal (ADR-0008), il ne connaît ni FastAPI ni SQLAlchemy :
l'adapter entrant traduit `InvalidDiscrepancyFilter` en `422` et le dépôt convertit
le filtre en clauses `WHERE`.

**Ce qui « compte comme réalisé »** : un RDV est une prestation réalisée
**uniquement** s'il est `COMPLETED` (`COMPLETED_STATUS`). `NO_SHOW`/`CANCELLED`/
`PENDING`/`CONFIRMED` ne sont **jamais** des écarts (rien n'a été réalisé, ou le RDV
est encore actif).

**Ce qui « compte comme payé »** : un RDV est couvert (donc **pas** un écart) dès
qu'un paiement `VALIDATED` **ou** `ADJUSTED` lui est rattaché (`PAID_PAYMENT_STATUSES`).
Un paiement corrigé (`ADJUSTED`) a bien été réalisé — il couvre le RDV ; un paiement
`CANCELLED`/`PENDING` ne couvre **rien** (l'encaissement n'est pas acquis). Le
rapprochement se fait **uniquement** sur `payments.appointment_id` (source de vérité
du lien RDV↔paiement) — un walk-in encaissé sur `service_id` seul n'entre pas dans la
comparaison (pas de RDV `COMPLETED` associé).

**Montant attendu** : la somme des `price_at_booking` des lignes du RDV (prix figés à
la réservation, cf. `payment.expected_amount_for_prices`) — la valeur « qui manque en
caisse », en `Decimal` quantifié au centime (`NUMERIC(12,2)`), jamais un flottant.

**Interprétation temporelle** : `date_from`/`date_to` sont des **jours civils**
`Africa/Abidjan` (UTC+0, convention #21) comparés directement à
`appointments.appointment_date` (colonne `Date` déjà exprimée en jour civil) — d'où,
contrairement à l'historique des transactions (#35 sur `created_at`), **aucune**
conversion de fuseau n'est requise ici.

**Non-fuite PII (§11.3)** : seule `users.full_name` (colonne non sensible) est résolue
pour l'affichage ; jamais de téléphone, email ni autre donnée client. `client_name`
peut être `None`.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import AppointmentStatus, PaymentStatus
from coiflink_api.domain.errors import InvalidDiscrepancyFilter
from coiflink_api.domain.payment import DEFAULT_CURRENCY

# Un RDV n'est un « écart » que s'il est **réalisé** : seul `COMPLETED` compte
# (jamais `NO_SHOW`/`CANCELLED`/`PENDING`/`CONFIRMED`).
COMPLETED_STATUS: str = AppointmentStatus.COMPLETED.value

# Statuts de paiement qui **couvrent** un RDV (le RDV n'est donc pas un écart) : un
# paiement `VALIDATED` (encaissement acquis) ou `ADJUSTED` (encaissement réalisé puis
# corrigé). Un `CANCELLED`/`PENDING` ne couvre rien (cf. Open Question tranchée dans
# l'ADR-0028).
PAID_PAYMENT_STATUSES: tuple[str, ...] = (
    PaymentStatus.VALIDATED.value,
    PaymentStatus.ADJUSTED.value,
)


@dataclass(frozen=True)
class CashDiscrepancy:
    """Écart de caisse : un RDV `COMPLETED` **sans** paiement rattaché (US-5.4, #36).

    Projection de **lecture** immuable, rattachée à un salon (§11.2). `expected_amount`
    est le « montant manquant » (somme des `price_at_booking` du RDV), en `Decimal`
    quantifié au centime ; `client_name` résout `users.full_name` (colonne non sensible
    **uniquement**, §11.3), `None` si non résolu.
    """

    appointment_id: uuid.UUID
    salon_id: uuid.UUID
    appointment_date: datetime.date
    start_time: datetime.time
    client_id: uuid.UUID
    expected_amount: decimal.Decimal
    client_name: str | None = None
    currency: str = DEFAULT_CURRENCY


@dataclass(frozen=True)
class DiscrepancyFilter:
    """Critères **validés** de filtrage des écarts (US-5.4, #36).

    Les deux bornes sont optionnelles (`None` = « pas de contrainte ») et se combinent
    en **ET** ; elles portent sur `appointments.appointment_date` (jour civil
    `Africa/Abidjan`). Cet objet est produit **uniquement** par
    `validate_discrepancy_filter` — un `DiscrepancyFilter` en circulation a donc
    toujours une plage ordonnée (`date_from ≤ date_to`).
    """

    date_from: datetime.date | None = None
    date_to: datetime.date | None = None

    @property
    def is_empty(self) -> bool:
        """`True` si aucune borne n'est posée (tous les écarts du salon)."""

        return self.date_from is None and self.date_to is None


def validate_discrepancy_filter(
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> DiscrepancyFilter:
    """Valide/normalise les bornes de dates → `DiscrepancyFilter` (US-5.4, #36).

    Règles (toutes → `InvalidDiscrepancyFilter`, message métier **neutre**) :

    - chaque borne, si fournie, est une `datetime.date` ;
    - la plage est **ordonnée** : `date_from ≤ date_to`.

    Les bornes comparent directement `appointments.appointment_date` (colonne `Date`,
    jour civil `Africa/Abidjan`) — aucune conversion de fuseau (contrairement à
    l'historique #35 qui compare `created_at`).
    """

    if date_from is not None and not isinstance(date_from, datetime.date):
        raise InvalidDiscrepancyFilter("Filtre des écarts de caisse invalide.")
    if date_to is not None and not isinstance(date_to, datetime.date):
        raise InvalidDiscrepancyFilter("Filtre des écarts de caisse invalide.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidDiscrepancyFilter("Filtre des écarts de caisse invalide.")

    return DiscrepancyFilter(date_from=date_from, date_to=date_to)


__all__ = [
    "COMPLETED_STATUS",
    "PAID_PAYMENT_STATUSES",
    "CashDiscrepancy",
    "DiscrepancyFilter",
    "validate_discrepancy_filter",
]
