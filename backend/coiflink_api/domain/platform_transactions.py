"""Supervision **agrégée** des transactions par salon (domaine pur, US-5.6, #37).

Ce module porte l'objet-valeur de lecture `SalonTransactionSummary` — l'**agrégat
d'un salon** (compteurs + montant net) — et son filtre de dates optionnel
`PlatformSummaryFilter` / `validate_platform_summary_filter`. Conformément à
l'hexagonal (ADR-0008), il ne connaît ni FastAPI ni SQLAlchemy : l'adapter entrant
traduit `InvalidPlatformSummaryFilter` en `422` et le dépôt convertit le filtre en
clauses `WHERE`.

**Vue plateforme, pas exploitation d'un salon.** À la différence des lectures caisse
salon-scopées (#34/#35/#36, gardées par `CASH_JOURNAL_READ` du seul `MANAGER`), il
s'agit d'une supervision **inter-salons** réservée à l'`ADMIN`
(`STATS_READ_PLATFORM`). L'agrégat groupe **tous** les salons ayant de l'activité.

**Source de vérité : le journal de caisse (#34).** Le **montant net** dérive de la
**somme signée** des lignes `cash_journal.amount` (`PAYMENT` positif, `ADJUSTMENT`
signé) : un paiement corrigé fait donc **baisser** `total_amount` et **incrémente**
`adjustment_count`. `payment_count`/`adjustment_count` proviennent des mêmes lignes,
garantissant la cohérence avec la caisse.

**Non-PII (§11.3), cœur du critère d'acceptation.** L'agrégat ne porte **que** des
compteurs, une somme, une devise et l'**identité métier du salon** (id + nom — pas
une PII de paiement ; l'admin a déjà `SALON_READ_ANY`). **Jamais** de `client_id`,
nom de client, `reference`, `recorded_by`, ni ligne de paiement individuelle.

**Interprétation temporelle.** `date_from`/`date_to` sont des **jours civils**
`Africa/Abidjan` (UTC+0, convention #21) convertis en bornes UTC inclusives —
`[date_from 00:00:00, date_to 23:59:59.999999]` — pour comparer à
`cash_journal.created_at` (`timezone-aware`). La logique de fuseau est **réutilisée**
depuis `domain/time_window.py` (aucune duplication, miroir de #35).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.errors import InvalidPlatformSummaryFilter
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.time_window import day_end_utc, day_start_utc


@dataclass(frozen=True)
class SalonTransactionSummary:
    """Agrégat des transactions **d'un** salon (projection de lecture, US-5.6, #37).

    Immuable et **sans PII de paiement** : seulement des compteurs, un montant net et
    l'identité métier du salon. `total_amount` est la **somme signée** des lignes
    `cash_journal` (net des corrections), en `Decimal` quantifié au centime
    (`NUMERIC(12,2)`), jamais un flottant.
    """

    salon_id: uuid.UUID
    salon_name: str
    payment_count: int
    adjustment_count: int
    total_amount: decimal.Decimal
    currency: str = DEFAULT_CURRENCY


@dataclass(frozen=True)
class PlatformSummaryFilter:
    """Filtre **validé** de plage de dates de la supervision agrégée (US-5.6, #37).

    Les deux bornes sont optionnelles (`None` = « pas de contrainte ») et se combinent
    en **ET** ; elles portent sur `cash_journal.created_at`. Cet objet est produit
    **uniquement** par `validate_platform_summary_filter` — un `PlatformSummaryFilter`
    en circulation a donc toujours une plage ordonnée (`date_from ≤ date_to`).

    Les bornes de date sont exposées **déjà converties** en `datetime` UTC
    (`created_at_from`/`created_at_to`) pour comparer directement à `created_at` sans
    que le dépôt ne connaisse le fuseau.
    """

    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    created_at_from: datetime.datetime | None = None
    created_at_to: datetime.datetime | None = None

    @property
    def is_empty(self) -> bool:
        """`True` si aucune borne n'est posée (toute l'activité de la plateforme)."""

        return self.date_from is None and self.date_to is None


def validate_platform_summary_filter(
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> PlatformSummaryFilter:
    """Valide/normalise les bornes de dates → `PlatformSummaryFilter` (US-5.6, #37).

    Règles (toutes → `InvalidPlatformSummaryFilter`, message métier **neutre**) :

    - chaque borne, si fournie, est une `datetime.date` ;
    - la plage est **ordonnée** : `date_from ≤ date_to`.

    Les bornes sont converties du jour civil `Africa/Abidjan` (UTC+0) vers des
    `datetime` UTC inclusifs, exposés par `created_at_from`/`created_at_to` (miroir de
    `validate_transaction_filter`, #35).
    """

    if date_from is not None and not isinstance(date_from, datetime.date):
        raise InvalidPlatformSummaryFilter("Filtre de supervision invalide.")
    if date_to is not None and not isinstance(date_to, datetime.date):
        raise InvalidPlatformSummaryFilter("Filtre de supervision invalide.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidPlatformSummaryFilter("Filtre de supervision invalide.")

    return PlatformSummaryFilter(
        date_from=date_from,
        date_to=date_to,
        created_at_from=day_start_utc(date_from) if date_from is not None else None,
        created_at_to=day_end_utc(date_to) if date_to is not None else None,
    )


__all__ = [
    "SalonTransactionSummary",
    "PlatformSummaryFilter",
    "validate_platform_summary_filter",
]
