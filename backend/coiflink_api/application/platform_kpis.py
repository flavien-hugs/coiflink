"""Cas d'usage : **KPI globaux** de la plateforme (US-6.6, #44).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`PlatformKpiRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il matérialise le
critère d'acceptation #44 :

> **Dashboard admin avec KPI globaux agrégés** (salons inscrits, tickets walk-in,
> revenus plateforme).

`ComputePlatformKpis` est une **lecture pure** (calquée sur `SummarizeRevenue` #40 et
`SummarizeSalonTransactions` #37) : pour une **date de référence** (jour civil
`Africa/Abidjan`), il dérive les bornes du **mois civil courant** (`month_bounds`,
`domain/revenue.py`), convertit ces bornes en bornes UTC (`domain/time_window.py`,
miroir #37/#40) **pour le revenu** — les tickets du mois se comparant directement
sur `issued_date` (déjà un jour civil) — puis délègue le calcul en base au port.
Il assemble enfin l'instantané public avec la date de référence, les bornes et la
devise. Comme les autres lectures statistiques (#37/#39–#43), il **ne journalise
aucune action** §11.4 — la consultation reste bornée par la permission
`STATS_READ_PLATFORM` (l'`ADMIN` seul).
"""

from __future__ import annotations

import datetime

from coiflink_api.application.ports.platform_kpi_repository import (
    PlatformKpiRepository,
)
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.platform_kpis import PlatformKpiSnapshot
from coiflink_api.domain.revenue import month_bounds
from coiflink_api.domain.time_window import day_end_utc, day_start_utc


class ComputePlatformKpis:
    """Instantané consolidé des KPI globaux plateforme (lecture — pas d'audit).

    `execute(reference_date)` calcule les bornes du **mois civil courant** contenant
    `reference_date`, convertit ces bornes de jour civil `Africa/Abidjan` en bornes
    **UTC inclusives** (via `time_window`) pour le revenu, puis délègue au port le
    calcul **en base** des compteurs et sommes globaux. Il assemble le
    `PlatformKpiSnapshot` public (compteurs + revenus + `reference_date`/bornes/devise).
    Lecture pure : aucune écriture, aucun audit (§11.4).
    """

    def __init__(self, repo: PlatformKpiRepository) -> None:
        self._repo = repo

    def execute(self, *, reference_date: datetime.date) -> PlatformKpiSnapshot:
        month_from, month_to = month_bounds(reference_date)
        counts = self._repo.compute_snapshot(
            month_from=month_from,
            month_to=month_to,
            revenue_from_utc=day_start_utc(month_from),
            revenue_to_utc=day_end_utc(month_to),
        )
        return PlatformKpiSnapshot(
            salons_total=counts.salons_total,
            salons_active=counts.salons_active,
            clients_total=counts.clients_total,
            tickets_total=counts.tickets_total,
            tickets_this_month=counts.tickets_this_month,
            revenue_total=counts.revenue_total,
            revenue_this_month=counts.revenue_this_month,
            reference_date=reference_date,
            month_from=month_from,
            month_to=month_to,
            currency=DEFAULT_CURRENCY,
        )


__all__ = ["ComputePlatformKpis"]
