"""Tests unitaires — domaine `hairdresser_performance` (US-6.5, #43).

Fonction pure sans I/O : aucun fake requis.

Couvre :
- `rank_hairdresser_performance` vide → `entries == ()`, période et devise échouées ;
- entrée unique : champs préservés ;
- taux d'annulation : formule `cancelled / total`, quantification à 4 décimales,
  garde division par zéro (`total_count == 0` → `Decimal("0.0000")`) ;
- revenu quantifié au centime (`Decimal` 2 décimales, jamais de flottant) ;
- ordre déterministe : `-revenue`, `-services_completed`, `name` croissant,
  `str(hairdresser_id)` croissant (départages stables) ;
- cohérence multi-entrées.
"""

from __future__ import annotations

import datetime
import decimal

from coiflink_api.domain.hairdresser_performance import (
    HairdresserActivity,
    HairdresserPerformanceReport,
    rank_hairdresser_performance,
)
from coiflink_api.domain.payment import DEFAULT_CURRENCY

import uuid

_DATE_FROM = datetime.date(2026, 8, 1)
_DATE_TO = datetime.date(2026, 8, 31)

_ID_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_ID_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_ID_C = uuid.UUID("cccccccc-0000-0000-0000-000000000003")


def _activity(
    hairdresser_id: uuid.UUID = _ID_A,
    name: str = "Coiffeur A",
    services_completed: int = 10,
    revenue: str = "50000.00",
    cancelled_count: int = 2,
    total_count: int = 20,
) -> HairdresserActivity:
    return HairdresserActivity(
        hairdresser_id=hairdresser_id,
        name=name,
        services_completed=services_completed,
        revenue=decimal.Decimal(revenue),
        cancelled_count=cancelled_count,
        total_count=total_count,
    )


def _rank(*rows: HairdresserActivity) -> HairdresserPerformanceReport:
    return rank_hairdresser_performance(rows, date_from=_DATE_FROM, date_to=_DATE_TO)


# ---------------------------------------------------------------------------
# Entrée vide
# ---------------------------------------------------------------------------


class TestRankEmpty:
    def test_empty_rows_entries_is_empty_tuple(self) -> None:
        assert _rank().entries == ()

    def test_empty_rows_date_from_echoed(self) -> None:
        assert _rank().date_from == _DATE_FROM

    def test_empty_rows_date_to_echoed(self) -> None:
        assert _rank().date_to == _DATE_TO

    def test_empty_rows_currency_is_default(self) -> None:
        assert _rank().currency == DEFAULT_CURRENCY

    def test_custom_currency_echoed(self) -> None:
        report = rank_hairdresser_performance(
            (), date_from=_DATE_FROM, date_to=_DATE_TO, currency="EUR"
        )
        assert report.currency == "EUR"


# ---------------------------------------------------------------------------
# Entrée unique
# ---------------------------------------------------------------------------


class TestRankSingleEntry:
    def test_single_entry_length_is_one(self) -> None:
        assert len(_rank(_activity()).entries) == 1

    def test_hairdresser_id_preserved(self) -> None:
        assert _rank(_activity(hairdresser_id=_ID_A)).entries[0].hairdresser_id == _ID_A

    def test_name_preserved(self) -> None:
        assert _rank(_activity(name="Awa Koné")).entries[0].name == "Awa Koné"

    def test_services_completed_preserved(self) -> None:
        assert _rank(_activity(services_completed=58)).entries[0].services_completed == 58

    def test_cancelled_count_preserved(self) -> None:
        assert _rank(_activity(cancelled_count=3)).entries[0].cancelled_count == 3

    def test_total_count_preserved(self) -> None:
        assert _rank(_activity(total_count=64)).entries[0].total_count == 64


# ---------------------------------------------------------------------------
# Taux d'annulation
# ---------------------------------------------------------------------------


class TestCancellationRate:
    def test_rate_cancelled_over_total(self) -> None:
        """3 annulés / 64 total = 0.046875 → arrondi à 0.0469."""
        entry = _rank(_activity(cancelled_count=3, total_count=64)).entries[0]
        assert entry.cancellation_rate == decimal.Decimal("0.0469")

    def test_zero_cancelled_gives_zero_rate(self) -> None:
        entry = _rank(_activity(cancelled_count=0, total_count=10)).entries[0]
        assert entry.cancellation_rate == decimal.Decimal("0.0000")

    def test_all_cancelled_gives_full_rate(self) -> None:
        entry = _rank(_activity(cancelled_count=5, total_count=5)).entries[0]
        assert entry.cancellation_rate == decimal.Decimal("1.0000")

    def test_zero_total_gives_zero_rate(self) -> None:
        """Garde division par zéro : total_count == 0 → taux == Decimal('0.0000')."""
        entry = _rank(_activity(cancelled_count=0, total_count=0)).entries[0]
        assert entry.cancellation_rate == decimal.Decimal("0.0000")

    def test_rate_is_decimal_not_float(self) -> None:
        entry = _rank(_activity(cancelled_count=1, total_count=4)).entries[0]
        assert isinstance(entry.cancellation_rate, decimal.Decimal)

    def test_rate_quantized_to_four_decimal_places(self) -> None:
        """1/3 = 0.3333…"""
        entry = _rank(_activity(cancelled_count=1, total_count=3)).entries[0]
        assert entry.cancellation_rate == decimal.Decimal("0.3333")

    def test_rate_in_zero_to_one_range(self) -> None:
        entry = _rank(_activity(cancelled_count=3, total_count=10)).entries[0]
        assert decimal.Decimal("0") <= entry.cancellation_rate <= decimal.Decimal("1")

    def test_high_cancelled_count_not_negative_total(self) -> None:
        """cancelled_count peut théoriquement dépasser total_count (données corrompues) :
        le calcul ne panique pas et produit un Decimal > 1."""
        entry = _rank(_activity(cancelled_count=10, total_count=5)).entries[0]
        assert isinstance(entry.cancellation_rate, decimal.Decimal)


# ---------------------------------------------------------------------------
# Quantification du revenu
# ---------------------------------------------------------------------------


class TestRevenueQuantization:
    def test_revenue_quantized_to_two_decimal_places(self) -> None:
        activity = HairdresserActivity(
            hairdresser_id=_ID_A,
            name="X",
            services_completed=1,
            revenue=decimal.Decimal("35000.123456"),
            cancelled_count=0,
            total_count=1,
        )
        assert _rank(activity).entries[0].revenue == decimal.Decimal("35000.12")

    def test_revenue_is_decimal(self) -> None:
        assert isinstance(_rank(_activity(revenue="50000.00")).entries[0].revenue, decimal.Decimal)

    def test_zero_revenue_preserved(self) -> None:
        assert _rank(_activity(revenue="0.00")).entries[0].revenue == decimal.Decimal("0.00")

    def test_negative_revenue_quantized(self) -> None:
        """Revenu négatif (corrections > paiements) quantifié au centime."""
        activity = HairdresserActivity(
            hairdresser_id=_ID_A,
            name="X",
            services_completed=0,
            revenue=decimal.Decimal("-500.00"),
            cancelled_count=0,
            total_count=1,
        )
        assert _rank(activity).entries[0].revenue == decimal.Decimal("-500.00")


# ---------------------------------------------------------------------------
# Ordre déterministe
# ---------------------------------------------------------------------------


class TestRankOrdering:
    def test_higher_revenue_first(self) -> None:
        a = _activity(hairdresser_id=_ID_A, revenue="30000.00", services_completed=5)
        b = _activity(hairdresser_id=_ID_B, revenue="50000.00", services_completed=3)
        report = _rank(a, b)
        assert report.entries[0].hairdresser_id == _ID_B

    def test_higher_services_completed_when_same_revenue(self) -> None:
        """Ordre secondaire : services_completed décroissant (même revenu)."""
        a = _activity(hairdresser_id=_ID_A, revenue="50000.00", services_completed=3)
        b = _activity(hairdresser_id=_ID_B, revenue="50000.00", services_completed=7)
        report = _rank(a, b)
        assert report.entries[0].hairdresser_id == _ID_B

    def test_name_alphabetical_when_same_revenue_and_services(self) -> None:
        """Ordre tertiaire : nom croissant."""
        a = _activity(hairdresser_id=_ID_A, name="Zoé", revenue="50000.00", services_completed=5)
        b = _activity(hairdresser_id=_ID_B, name="Awa", revenue="50000.00", services_completed=5)
        report = _rank(a, b)
        assert report.entries[0].name == "Awa"

    def test_hairdresser_id_str_as_last_tiebreaker(self) -> None:
        """Ordre quaternaire : str(hairdresser_id) croissant."""
        a = _activity(hairdresser_id=_ID_A, name="Même", revenue="50000.00", services_completed=5)
        b = _activity(hairdresser_id=_ID_B, name="Même", revenue="50000.00", services_completed=5)
        report = _rank(a, b)
        # str(_ID_A) < str(_ID_B) → _ID_A en premier
        assert report.entries[0].hairdresser_id == _ID_A

    def test_three_entries_ordered_by_descending_revenue(self) -> None:
        a = _activity(hairdresser_id=_ID_A, revenue="10000.00")
        b = _activity(hairdresser_id=_ID_B, revenue="50000.00")
        c = _activity(hairdresser_id=_ID_C, revenue="30000.00")
        ids = [e.hairdresser_id for e in _rank(a, b, c).entries]
        assert ids == [_ID_B, _ID_C, _ID_A]

    def test_ordering_is_deterministic_regardless_of_input_order(self) -> None:
        a = _activity(hairdresser_id=_ID_A, name="Même", revenue="50000.00", services_completed=5)
        b = _activity(hairdresser_id=_ID_B, name="Même", revenue="50000.00", services_completed=5)
        ids1 = [e.hairdresser_id for e in _rank(a, b).entries]
        ids2 = [e.hairdresser_id for e in _rank(b, a).entries]
        assert ids1 == ids2

    def test_zero_revenue_sorted_last(self) -> None:
        """Coiffeur sans CA attribué (0.00) arrive après ceux avec du CA."""
        a = _activity(hairdresser_id=_ID_A, revenue="0.00")
        b = _activity(hairdresser_id=_ID_B, revenue="25000.00")
        report = _rank(a, b)
        assert report.entries[0].hairdresser_id == _ID_B

    def test_result_is_tuple_of_performance(self) -> None:
        report = _rank(_activity(), _activity(hairdresser_id=_ID_B))
        assert isinstance(report.entries, tuple)
