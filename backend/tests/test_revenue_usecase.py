"""Tests unitaires — cas d'usage `SummarizeRevenue` (US-6.2, #40).

Ports remplacés par un fake : pas de base, pas de réseau.

Couvre :
- `execute` appelle `net_revenue_between` exactement 3 fois (une par période :
  jour, semaine, mois) dans cet ordre ;
- bornes UTC transmises : `day_start_utc(date_from)` / `day_end_utc(date_to)` dérivées
  des bornes civiles `day_bounds`/`week_bounds`/`month_bounds` (Africa/Abidjan = UTC+0) ;
- `RevenueSummary` assemblé : `reference_date`, `day`/`week`/`month` corrects
  (`date_from`, `date_to`, `total` depuis le fake), devise `XOF` ;
- totaux positif, nul, négatif (corrections excédant les paiements) ;
- lecture pure : aucune écriture (les méthodes de mutation ne sont jamais appelées).
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.revenue import SummarizeRevenue
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.revenue import day_bounds, month_bounds, week_bounds
from coiflink_api.domain.time_window import day_end_utc, day_start_utc

# ---------------------------------------------------------------------------
# Fake CashJournalRepository (lecture seule — pas d'écriture dans ce use case)
# ---------------------------------------------------------------------------


class FakeRevenueCashJournalRepository:
    """Fake du port `CashJournalRepository` pour `SummarizeRevenue` — aucun I/O.

    `amounts` est la liste de `Decimal` retournés dans l'ordre des appels à
    `net_revenue_between` (jour en premier, semaine en second, mois en troisième).
    Le même dernier montant est répété si la liste est plus courte que le nombre
    d'appels. Les méthodes de mutation lèvent `NotImplementedError` pour rendre
    toute écriture accidentelle visible immédiatement.
    """

    def __init__(self, amounts: list[decimal.Decimal] | None = None) -> None:
        self._amounts: list[decimal.Decimal] = list(amounts or [decimal.Decimal("0.00")])
        self._call_index = 0
        self.net_revenue_calls: list[dict] = []

    def net_revenue_between(
        self,
        salon_id: uuid.UUID,
        *,
        created_at_from: datetime.datetime,
        created_at_to: datetime.datetime,
    ) -> decimal.Decimal:
        self.net_revenue_calls.append(
            {
                "salon_id": salon_id,
                "created_at_from": created_at_from,
                "created_at_to": created_at_to,
            }
        )
        result = self._amounts[self._call_index % len(self._amounts)]
        self._call_index += 1
        return result

    def append(self, entry):  # type: ignore[no-untyped-def]
        raise NotImplementedError("SummarizeRevenue ne doit pas écrire dans le journal")

    def list_for_salon(self, salon_id, *, limit, offset):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_for_salon(self, salon_id):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
# 2026-08-02 = dimanche (toutes les semaines et bornes de mois sont non-triviales)
_REF_DATE = datetime.date(2026, 8, 2)


# ---------------------------------------------------------------------------
# Appels au port : nombre et bornes UTC
# ---------------------------------------------------------------------------


class TestSummarizeRevenuePortCalls:
    def test_net_revenue_between_called_three_times(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert len(repo.net_revenue_calls) == 3

    def test_salon_id_forwarded_to_all_calls(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        for call in repo.net_revenue_calls:
            assert call["salon_id"] == _SALON_ID

    def test_day_bounds_utc_passed_in_first_call(self) -> None:
        """Premier appel : bornes du jour civil converti en UTC (Africa/Abidjan = UTC+0)."""
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        day_lo, day_hi = day_bounds(_REF_DATE)
        call = repo.net_revenue_calls[0]
        assert call["created_at_from"] == day_start_utc(day_lo)
        assert call["created_at_to"] == day_end_utc(day_hi)

    def test_week_bounds_utc_passed_in_second_call(self) -> None:
        """Second appel : bornes de la semaine civile (lundi→dimanche) en UTC."""
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        week_lo, week_hi = week_bounds(_REF_DATE)
        call = repo.net_revenue_calls[1]
        assert call["created_at_from"] == day_start_utc(week_lo)
        assert call["created_at_to"] == day_end_utc(week_hi)

    def test_month_bounds_utc_passed_in_third_call(self) -> None:
        """Troisième appel : bornes du mois civil (1er → dernier jour) en UTC."""
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        month_lo, month_hi = month_bounds(_REF_DATE)
        call = repo.net_revenue_calls[2]
        assert call["created_at_from"] == day_start_utc(month_lo)
        assert call["created_at_to"] == day_end_utc(month_hi)

    def test_day_utc_from_is_midnight(self) -> None:
        """Africa/Abidjan = UTC+0 → borne basse du jour = 00:00:00.000000 UTC."""
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        call = repo.net_revenue_calls[0]
        assert call["created_at_from"].hour == 0
        assert call["created_at_from"].minute == 0
        assert call["created_at_from"].second == 0

    def test_day_utc_to_is_last_microsecond(self) -> None:
        """Africa/Abidjan = UTC+0 → borne haute du jour = 23:59:59.999999 UTC."""
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        call = repo.net_revenue_calls[0]
        assert call["created_at_to"].hour == 23
        assert call["created_at_to"].minute == 59
        assert call["created_at_to"].second == 59
        assert call["created_at_to"].microsecond == 999999

    def test_no_write_triggered(self) -> None:
        """Lecture pure : `append` ne doit jamais être appelé — sinon NotImplementedError."""
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        # Pas d'exception levée → OK

    def test_no_extra_calls_beyond_three(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert len(repo.net_revenue_calls) == 3


# ---------------------------------------------------------------------------
# Assemblage du RevenueSummary
# ---------------------------------------------------------------------------


class TestSummarizeRevenueAssembly:
    def test_reference_date_in_summary(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.reference_date == _REF_DATE

    def test_summary_currency_is_xof(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.currency == DEFAULT_CURRENCY

    def test_day_total_comes_from_first_call(self) -> None:
        day_total = decimal.Decimal("35000.00")
        repo = FakeRevenueCashJournalRepository(
            amounts=[day_total, decimal.Decimal("0.00"), decimal.Decimal("0.00")]
        )
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.day.total == day_total

    def test_week_total_comes_from_second_call(self) -> None:
        week_total = decimal.Decimal("210000.00")
        repo = FakeRevenueCashJournalRepository(
            amounts=[decimal.Decimal("0.00"), week_total, decimal.Decimal("0.00")]
        )
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.week.total == week_total

    def test_month_total_comes_from_third_call(self) -> None:
        month_total = decimal.Decimal("185000.00")
        repo = FakeRevenueCashJournalRepository(
            amounts=[decimal.Decimal("0.00"), decimal.Decimal("0.00"), month_total]
        )
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.month.total == month_total

    def test_day_date_bounds_match_day_bounds(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        d_lo, d_hi = day_bounds(_REF_DATE)
        assert summary.day.date_from == d_lo
        assert summary.day.date_to == d_hi

    def test_week_date_bounds_match_week_bounds(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        w_lo, w_hi = week_bounds(_REF_DATE)
        assert summary.week.date_from == w_lo
        assert summary.week.date_to == w_hi

    def test_month_date_bounds_match_month_bounds(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        m_lo, m_hi = month_bounds(_REF_DATE)
        assert summary.month.date_from == m_lo
        assert summary.month.date_to == m_hi

    def test_zero_revenue_returns_zero_totals(self) -> None:
        repo = FakeRevenueCashJournalRepository(amounts=[decimal.Decimal("0.00")])
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.day.total == decimal.Decimal("0.00")
        assert summary.week.total == decimal.Decimal("0.00")
        assert summary.month.total == decimal.Decimal("0.00")

    def test_negative_total_passed_through(self) -> None:
        """Un total négatif (corrections > paiements) doit être conservé tel quel."""
        neg = decimal.Decimal("-500.00")
        repo = FakeRevenueCashJournalRepository(amounts=[neg])
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.day.total == neg

    def test_day_period_currency_is_xof(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.day.currency == DEFAULT_CURRENCY

    def test_week_period_currency_is_xof(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.week.currency == DEFAULT_CURRENCY

    def test_month_period_currency_is_xof(self) -> None:
        repo = FakeRevenueCashJournalRepository()
        summary = SummarizeRevenue(repo).execute(_SALON_ID, _REF_DATE)
        assert summary.month.currency == DEFAULT_CURRENCY

    def test_each_call_uses_distinct_salon_id(self) -> None:
        """Tous les appels portent le même salon_id (isolation §11.2)."""
        other_id = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
        repo = FakeRevenueCashJournalRepository()
        SummarizeRevenue(repo).execute(other_id, _REF_DATE)
        for call in repo.net_revenue_calls:
            assert call["salon_id"] == other_id
