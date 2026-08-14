"""Cas d'usage : **détection des écarts de caisse** (US-5.4, #36).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`PaymentRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il matérialise le
critère d'acceptation #36 :

> Un ticket walk-in terminé sans paiement est signalé comme écart.

`ListCashDiscrepancies` est une **lecture pure** (calquée sur `ListTransactions`
#35) : il liste les tickets `done` d'un salon **sans paiement rattaché**, paginés,
sous un `DiscrepancyFilter` validé (bornes de dates optionnelles). Comme le journal
#34 et l'historique #35, il **ne journalise aucune action** §11.4 — la consultation
reste bornée par la permission `CASH_JOURNAL_READ`.
"""

from __future__ import annotations

import uuid

from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.domain.discrepancy import CashDiscrepancy, DiscrepancyFilter


class ListCashDiscrepancies:
    """Liste paginée des écarts de caisse d'un salon (lecture — pas d'audit).

    Retourne `(page, total)` : la page d'écarts (tickets `done` non encaissés, plus
    récents d'abord) et le total **sous le même filtre** (pagination correcte).
    Lecture pure : aucune écriture, aucun audit.
    """

    def __init__(self, payment_repo: PaymentRepository) -> None:
        self._payment_repo = payment_repo

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        filter: DiscrepancyFilter,
        limit: int,
        offset: int,
    ) -> tuple[tuple[CashDiscrepancy, ...], int]:
        """Retourne `(page, total)` — écarts filtrés, plus récents d'abord."""

        page = self._payment_repo.list_completed_without_payment(
            salon_id, filter=filter, limit=limit, offset=offset
        )
        total = self._payment_repo.count_completed_without_payment(
            salon_id, filter=filter
        )
        return page, total


__all__ = ["ListCashDiscrepancies"]
