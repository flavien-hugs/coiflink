"""Cas d'usage : **supervision agrégée** des transactions par salon (US-5.6, #37).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`PlatformTransactionRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il
matérialise le critère d'acceptation #37 :

> L'admin voit des agrégats par salon **sans PII de paiement superflue** (§11.2/§11.3).

`SummarizeSalonTransactions` est une **lecture pure** (calquée sur
`ListCashDiscrepancies` #36) : il agrège les transactions **par salon** sur toute la
plateforme, paginées, sous un `PlatformSummaryFilter` validé (bornes de dates
optionnelles). Comme le journal #34, l'historique #35 et les écarts #36, il **ne
journalise aucune action** §11.4 — la consultation reste bornée par la permission
`STATS_READ_PLATFORM` (l'`ADMIN` seul).
"""

from __future__ import annotations

from coiflink_api.application.ports.platform_transaction_repository import (
    PlatformTransactionRepository,
)
from coiflink_api.domain.platform_transactions import (
    PlatformSummaryFilter,
    SalonTransactionSummary,
)


class SummarizeSalonTransactions:
    """Agrégat paginé des transactions par salon (lecture — pas d'audit).

    Retourne `(page, total)` : la page d'agrégats (un par salon actif, tri
    déterministe) et le total des salons **sous le même filtre** (pagination
    correcte). Lecture pure : aucune écriture, aucun audit.
    """

    def __init__(self, repo: PlatformTransactionRepository) -> None:
        self._repo = repo

    def execute(
        self,
        *,
        filter: PlatformSummaryFilter,
        limit: int,
        offset: int,
    ) -> tuple[tuple[SalonTransactionSummary, ...], int]:
        """Retourne `(page, total)` — agrégats par salon + total sous le même filtre."""

        page = self._repo.summary_by_salon(filter=filter, limit=limit, offset=offset)
        total = self._repo.count_salons(filter=filter)
        return page, total


__all__ = ["SummarizeSalonTransactions"]
