"""Adapter sortant : **supervision agrégée** des transactions (SQLAlchemy, US-5.6, #37).

Implémente le port `PlatformTransactionRepository` sur une `Session` SQLAlchemy 2.0
et les modèles ORM `models.CashJournal` / `models.Salon`. Seul cet adapter connaît
SQLAlchemy ; il agrège les lignes du **journal de caisse** (#34) **par salon** et
les projette en `SalonTransactionSummary` (domaine pur, sans PII de paiement).

**Source de vérité : le journal de caisse (#34).** Le montant net dérive de la
**somme signée** des `cash_journal.amount` (`PAYMENT` positif, `ADJUSTMENT` signé) :
un paiement corrigé fait **baisser** `total_amount` et **incrémente**
`adjustment_count`. Les compteurs proviennent des mêmes lignes (`COUNT(*) FILTER`),
garantissant la cohérence avec la caisse.

**Vue plateforme (inter-salons), pas exploitation d'un salon.** Contrairement aux
dépôts salon-scopés (`PaymentRepository`/`CashJournalRepository`, isolation §11.2),
l'agrégation **groupe sur tous les salons** ayant de l'activité — d'où un port
dédié. La garde `STATS_READ_PLATFORM` (ADMIN seul) protège l'appelant.

**Lecture pure.** Aucune écriture, aucun `flush`, aucun commit. L'agrégation, le
filtre de dates, le tri et les bornes `limit`/`offset` sont **en SQL** (jamais en
mémoire — garde de coût §12.1). L'index `ix_cash_journal_salon_id (salon_id,
created_at)` couvre le groupement/filtre ; aucun nouvel index requis.

**Non-PII (§11.3).** La projection ne sélectionne **que** l'identité métier du
salon (`salons.id`, `salons.name`) et des agrégats. **Aucun** `client_id`,
`reference`, `recorded_by`/`performed_by`, ni ligne de paiement individuelle.
"""

from __future__ import annotations

import decimal
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import CashOperationType
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.platform_transactions import (
    PlatformSummaryFilter,
    SalonTransactionSummary,
)

# Précision de quantification des montants agrégés : le centime (miroir de
# `NUMERIC(12,2)`), pour rester en `Decimal` (jamais un flottant).
_AMOUNT_QUANTUM = decimal.Decimal("0.01")

# Valeurs textuelles des types d'opération (miroir des `CHECK` de `cash_journal`).
_PAYMENT = CashOperationType.PAYMENT.value
_ADJUSTMENT = CashOperationType.ADJUSTMENT.value


class SqlPlatformTransactionRepository:
    """Dépôt d'agrégation des transactions par salon adossé à une `Session`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def summary_by_salon(
        self, *, filter: PlatformSummaryFilter, limit: int, offset: int
    ) -> tuple[SalonTransactionSummary, ...]:
        """Page d'agrégats **par salon** (US-5.6, #37) — lecture seule.

        Agrège `cash_journal` `GROUP BY salon_id` (jointure `salons` pour le nom),
        avec `payment_count`/`adjustment_count` (`COUNT(*) FILTER`) et
        `total_amount = SUM(amount)` (net signé). Seuls les salons **avec activité**
        (au moins une ligne sous le filtre) apparaissent. Tri déterministe
        `salon_name ASC, salon_id ASC`, bornes en SQL.
        """

        payment_count = func.count().filter(
            models.CashJournal.operation_type == _PAYMENT
        )
        adjustment_count = func.count().filter(
            models.CashJournal.operation_type == _ADJUSTMENT
        )
        total_amount = func.coalesce(func.sum(models.CashJournal.amount), 0)
        stmt = (
            select(
                models.Salon.id,
                models.Salon.name,
                payment_count,
                adjustment_count,
                total_amount,
            )
            .join(models.Salon, models.Salon.id == models.CashJournal.salon_id)
            .where(*self._clauses(filter))
            .group_by(models.Salon.id, models.Salon.name)
            .order_by(models.Salon.name.asc(), models.Salon.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return tuple(
            SalonTransactionSummary(
                salon_id=salon_id,
                salon_name=salon_name,
                payment_count=int(payments),
                adjustment_count=int(adjustments),
                total_amount=decimal.Decimal(amount).quantize(_AMOUNT_QUANTUM),
                currency=DEFAULT_CURRENCY,
            )
            for (
                salon_id,
                salon_name,
                payments,
                adjustments,
                amount,
            ) in self._session.execute(stmt).all()
        )

    def count_salons(self, *, filter: PlatformSummaryFilter) -> int:
        """Nombre de salons **distincts** apparaissant sous le même filtre (pagination).

        Applique **exactement** les mêmes clauses que `summary_by_salon` (bornes de
        dates conditionnelles) pour un `total` cohérent avec la page.
        """

        stmt = (
            select(func.count(func.distinct(models.CashJournal.salon_id)))
            .select_from(models.CashJournal)
            .where(*self._clauses(filter))
        )
        return int(self._session.scalar(stmt) or 0)

    @staticmethod
    def _clauses(filter: PlatformSummaryFilter) -> Sequence[ColumnElement[bool]]:
        """Clauses `WHERE` : bornes de dates **conditionnelles** sur `created_at`.

        Partagées **à l'identique** par `summary_by_salon` et `count_salons` pour
        que le `total` corresponde exactement à la page. Vide (« pas de contrainte »)
        quand aucune borne n'est posée.
        """

        clauses: list[ColumnElement[bool]] = []
        if filter.created_at_from is not None:
            clauses.append(models.CashJournal.created_at >= filter.created_at_from)
        if filter.created_at_to is not None:
            clauses.append(models.CashJournal.created_at <= filter.created_at_to)
        return clauses


__all__ = ["SqlPlatformTransactionRepository"]
