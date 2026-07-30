"""Tests unitaires — cas d'usage `SummarizeSalonTransactions` (US-5.6, #37).

Tous les ports sont remplacés par un fake : pas de base, pas de réseau.

Couvre :
- page vide quand aucun agrégat ;
- un seul agrégat retourné ;
- plusieurs agrégats ;
- filtre/limit/offset transmis tels quels au port ;
- `total` cohérent (différent de la taille de la page) ;
- `SummarizeSalonTransactions` ne déclenche aucune écriture ni audit ;
- les deux méthodes du port (`summary_by_salon` + `count_salons`) sont appelées.
"""

from __future__ import annotations

import decimal
import uuid

from coiflink_api.application.platform_transactions import SummarizeSalonTransactions
from coiflink_api.domain.platform_transactions import (
    PlatformSummaryFilter,
    SalonTransactionSummary,
    validate_platform_summary_filter,
)

# ---------------------------------------------------------------------------
# Fake PlatformTransactionRepository
# ---------------------------------------------------------------------------

_NO_FILTER = validate_platform_summary_filter()

_SALON_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SALON_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _make_summary(
    *,
    salon_id: uuid.UUID = _SALON_A,
    salon_name: str = "Salon A",
    payment_count: int = 5,
    adjustment_count: int = 1,
    total_amount: decimal.Decimal = decimal.Decimal("25000.00"),
) -> SalonTransactionSummary:
    return SalonTransactionSummary(
        salon_id=salon_id,
        salon_name=salon_name,
        payment_count=payment_count,
        adjustment_count=adjustment_count,
        total_amount=total_amount,
    )


class FakePlatformTransactionRepository:
    """Fake du port `PlatformTransactionRepository` (US-5.6, #37) — aucun I/O.

    Enregistre chaque appel à `summary_by_salon` / `count_salons` pour vérifier
    que le use case transmet correctement `filter`, `limit`, `offset`. La liste
    `summaries` est utilisée directement, sans filtrage en mémoire (le filtrage
    est la responsabilité du dépôt réel — on ne le ré-implémente pas ici).
    """

    def __init__(
        self,
        summaries: list[SalonTransactionSummary] | None = None,
        *,
        total: int | None = None,
    ) -> None:
        self._summaries: list[SalonTransactionSummary] = list(summaries or [])
        self._total = total if total is not None else len(self._summaries)
        self.summary_calls: list[dict] = []
        self.count_calls: list[dict] = []

    def summary_by_salon(
        self, *, filter: PlatformSummaryFilter, limit: int, offset: int
    ) -> tuple[SalonTransactionSummary, ...]:
        self.summary_calls.append({"filter": filter, "limit": limit, "offset": offset})
        return tuple(self._summaries)

    def count_salons(self, *, filter: PlatformSummaryFilter) -> int:
        self.count_calls.append({"filter": filter})
        return self._total


# ---------------------------------------------------------------------------
# Page vide / résultat minimal
# ---------------------------------------------------------------------------


class TestSummarizeSalonTransactionsEmpty:
    def test_no_summaries_returns_empty_page(self) -> None:
        repo = FakePlatformTransactionRepository()
        page, total = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=50, offset=0
        )
        assert page == ()
        assert total == 0

    def test_single_summary_returned(self) -> None:
        s = _make_summary()
        repo = FakePlatformTransactionRepository(summaries=[s])
        page, total = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 1
        assert len(page) == 1
        assert page[0].salon_id == s.salon_id

    def test_multiple_summaries_returned(self) -> None:
        summaries = [
            _make_summary(salon_id=_SALON_A, salon_name="Alpha"),
            _make_summary(salon_id=_SALON_B, salon_name="Beta"),
        ]
        repo = FakePlatformTransactionRepository(summaries=summaries)
        page, total = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 2
        assert len(page) == 2


# ---------------------------------------------------------------------------
# Transmission exacte de filter / limit / offset au port
# ---------------------------------------------------------------------------


class TestSummarizeSalonTransactionsArgForwarding:
    def test_filter_forwarded_to_summary_by_salon(self) -> None:
        import datetime

        f = validate_platform_summary_filter(date_from=datetime.date(2026, 3, 1))
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=f, limit=50, offset=0)
        assert repo.summary_calls[0]["filter"] is f

    def test_limit_forwarded_to_summary_by_salon(self) -> None:
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=_NO_FILTER, limit=17, offset=0)
        assert repo.summary_calls[0]["limit"] == 17

    def test_offset_forwarded_to_summary_by_salon(self) -> None:
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=_NO_FILTER, limit=50, offset=25)
        assert repo.summary_calls[0]["offset"] == 25

    def test_filter_forwarded_to_count_salons(self) -> None:
        import datetime

        f = validate_platform_summary_filter(date_from=datetime.date(2026, 3, 1))
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=f, limit=50, offset=0)
        assert repo.count_calls[0]["filter"] is f


# ---------------------------------------------------------------------------
# Cohérence (page, total)
# ---------------------------------------------------------------------------


class TestSummarizeSalonTransactionsTotalVsPage:
    def test_total_can_differ_from_page_size(self) -> None:
        """Le total reflète la cardinalité du filtre, pas la taille de la page."""
        summaries = [_make_summary(salon_id=_SALON_A)]
        repo = FakePlatformTransactionRepository(summaries=summaries, total=42)
        page, total = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=1, offset=0
        )
        assert total == 42
        assert len(page) == 1

    def test_returns_tuple_of_two_elements(self) -> None:
        repo = FakePlatformTransactionRepository()
        result = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=50, offset=0
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_tuple_of_summaries(self) -> None:
        repo = FakePlatformTransactionRepository()
        page, _ = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=50, offset=0
        )
        assert isinstance(page, tuple)

    def test_second_element_is_int(self) -> None:
        repo = FakePlatformTransactionRepository()
        _, total = SummarizeSalonTransactions(repo).execute(
            filter=_NO_FILTER, limit=50, offset=0
        )
        assert isinstance(total, int)


# ---------------------------------------------------------------------------
# Lecture pure — aucune écriture / aucun audit
# ---------------------------------------------------------------------------


class TestSummarizeSalonTransactionsPurity:
    def test_calls_summary_by_salon_once(self) -> None:
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=_NO_FILTER, limit=50, offset=0)
        assert len(repo.summary_calls) == 1

    def test_calls_count_salons_once(self) -> None:
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=_NO_FILTER, limit=50, offset=0)
        assert len(repo.count_calls) == 1

    def test_no_extra_calls(self) -> None:
        """Le use case n'appelle pas d'autres méthodes — lecture pure, zéro audit."""
        repo = FakePlatformTransactionRepository()
        SummarizeSalonTransactions(repo).execute(filter=_NO_FILTER, limit=50, offset=0)
        assert len(repo.summary_calls) == 1
        assert len(repo.count_calls) == 1
