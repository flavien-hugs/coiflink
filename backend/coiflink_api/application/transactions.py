"""Cas d'usage : **historique des transactions filtrable** (US-5.2, #35).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`PaymentRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il matérialise le
critère d'acceptation #35 :

> Filtres fonctionnels ; cohérence avec le journal de caisse.

`ListTransactions` est une **lecture pure** : il liste, du plus récent au plus
ancien, les paiements (transactions) d'un salon sous un `TransactionFilter`
validé (date/client/montant/mode, combinés en **ET**), paginé. Comme
`ListCashJournal` (#34), il **ne journalise aucune action** §11.4 — la
consultation reste bornée par la permission `CASH_JOURNAL_READ`.

La **cohérence avec le journal** est *structurelle* : la liste et le journal
dérivent des **mêmes** paiements (`cash_journal.transaction_id = payments.id`),
mêmes montant/horodatage/auteur. Ce cas d'usage n'a donc rien de spécial à faire
pour la garantir — il lit la même table source.
"""

from __future__ import annotations

import uuid

from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.domain.transaction import Transaction, TransactionFilter


class ListTransactions:
    """Liste paginée et **filtrée** des transactions d'un salon (lecture — pas d'audit).

    Retourne `(page, total)` : la page de transactions (plus récentes d'abord) et
    le total **sous le même filtre** (pagination correcte). Lecture pure : aucune
    écriture, aucun audit.
    """

    def __init__(self, payment_repo: PaymentRepository) -> None:
        self._payment_repo = payment_repo

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        filter: TransactionFilter,
        limit: int,
        offset: int,
    ) -> tuple[tuple[Transaction, ...], int]:
        """Retourne `(page, total)` — transactions filtrées, plus récentes d'abord."""

        page = self._payment_repo.list_for_salon(
            salon_id, filter=filter, limit=limit, offset=offset
        )
        total = self._payment_repo.count_for_salon(salon_id, filter=filter)
        return page, total


__all__ = ["ListTransactions"]
