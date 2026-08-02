"""Cas d'usage : **chiffre d'affaires** jour / semaine / mois d'un salon (US-6.2, #40).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`CashJournalRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il matérialise le
critère d'acceptation #40 :

> Le gérant voit son **CA journalier, hebdomadaire, mensuel** ; les RDV annulés ne
> comptent pas ; le CA est **calculé à partir des paiements** (§6 US-6.2, §8.1).

`SummarizeRevenue` est une **lecture pure** (calquée sur `SummarizeDailyAppointments`
#39 et `SummarizeSalonTransactions` #37) : pour une **date de référence** (jour civil
`Africa/Abidjan`), il dérive les bornes des trois périodes (`domain/revenue.py`),
les convertit en bornes UTC (`domain/time_window.py`, miroir #35/#37) et somme le
**journal de caisse** une fois par période. Comme les autres lectures financières
(#34/#35/#36/#37/#39), il **ne journalise aucune action** §11.4 — la consultation
d'un KPI reste bornée par la permission `STATS_READ_SALON` (le `MANAGER` seul).

**« Annulés exclus » par construction (§8.1, spec §Open Questions 2).** Un RDV
`CANCELLED` ne génère aucun paiement, donc aucune ligne de journal, donc aucune
contribution au CA — l'exclusion est vraie **à la source** (le journal de caisse),
sans jointure ni filtre supplémentaire.
"""

from __future__ import annotations

import datetime
import uuid

from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.revenue import (
    RevenuePeriodTotal,
    RevenueSummary,
    day_bounds,
    month_bounds,
    week_bounds,
)
from coiflink_api.domain.time_window import day_end_utc, day_start_utc


class SummarizeRevenue:
    """CA d'un salon sur trois périodes pour une date de référence (lecture — pas d'audit).

    `execute(salon_id, reference_date)` calcule les bornes civiles du **jour**, de la
    **semaine** (lundi→dimanche) et du **mois** contenant `reference_date`, puis somme
    le journal de caisse (`net_revenue_between`) **une fois par période** (trois
    requêtes indexées, bornées — ni plage arbitraire, ni pagination). Les périodes se
    chevauchant, les sommes ne sont **pas** combinées : trois `SUM` indépendants et
    lisibles. Lecture pure : aucune écriture, aucun audit (§11.4).
    """

    def __init__(self, cash_journal_repository: CashJournalRepository) -> None:
        self._cash_journal = cash_journal_repository

    def execute(
        self, salon_id: uuid.UUID, reference_date: datetime.date
    ) -> RevenueSummary:
        return RevenueSummary(
            reference_date=reference_date,
            day=self._period_total(salon_id, day_bounds(reference_date)),
            week=self._period_total(salon_id, week_bounds(reference_date)),
            month=self._period_total(salon_id, month_bounds(reference_date)),
            currency=DEFAULT_CURRENCY,
        )

    def _period_total(
        self,
        salon_id: uuid.UUID,
        bounds: tuple[datetime.date, datetime.date],
    ) -> RevenuePeriodTotal:
        """Somme le journal sur une période (bornes civiles → bornes UTC → `SUM`)."""

        date_from, date_to = bounds
        total = self._cash_journal.net_revenue_between(
            salon_id,
            created_at_from=day_start_utc(date_from),
            created_at_to=day_end_utc(date_to),
        )
        return RevenuePeriodTotal(
            date_from=date_from,
            date_to=date_to,
            total=total,
            currency=DEFAULT_CURRENCY,
        )


__all__ = ["SummarizeRevenue"]
