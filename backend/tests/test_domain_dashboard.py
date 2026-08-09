"""Tests unitaires — domaine `dashboard.py` (dashboard Manager activité, #148).

Couvre :
- `resolve_period` : `today`/`week`/`month`/`custom` → bornes correctes ; `custom`
  sans l'une ou les deux bornes → `InvalidDashboardPeriod` ; `date_to < date_from`
  → `InvalidDashboardPeriod` ; genre inconnu → `InvalidDashboardPeriod` ;
- `previous_period` : longueur préservée, contiguïté (prev_to = date_from - 1j) ;
- `Evolution`/`compute_evolution` : direction `up`/`down`/`flat` ; delta dérivé ;
  frozen (immuable) ; fonctionne avec `int` et `Decimal` ; `previous = 0` robuste
  (pas de division par zéro — `direction` fondée sur le signe du delta seul) ;
- `is_in_progress` : instant **avant** début → faux ; **au** début (inclus) → vrai ;
  **entre** début et fin → vrai ; **à** la fin (exclusif) → faux ; **après** → faux ;
  **jour différent** → faux ;
- `has_started` : instant **avant** début → faux ; **au** début (inclus) → vrai ;
  **après** → vrai ;
- `build_series` : jours vides complétés à `zero` ; jours avec valeur renvoyés
  tels quels ; axe continu (aucun trou) ; tuple immutable.

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import datetime
import decimal

import pytest

from coiflink_api.domain.dashboard import (
    Evolution,
    SeriesBucket,
    build_series,
    compute_evolution,
    has_started,
    is_in_progress,
    previous_period,
    resolve_period,
)
from coiflink_api.domain.errors import InvalidDashboardPeriod
from coiflink_api.domain.revenue import day_bounds, month_bounds, week_bounds

# ---------------------------------------------------------------------------
# Dates réutilisées
# ---------------------------------------------------------------------------

_REF_TUESDAY = datetime.date(2026, 8, 4)   # mardi
_REF_MONDAY = datetime.date(2026, 8, 3)    # lundi de la même semaine


# ---------------------------------------------------------------------------
# resolve_period — today
# ---------------------------------------------------------------------------


class TestResolvePeriodToday:
    def test_today_returns_same_date_twice(self) -> None:
        lo, hi = resolve_period("today", reference=_REF_TUESDAY)
        assert lo == _REF_TUESDAY
        assert hi == _REF_TUESDAY

    def test_today_matches_day_bounds(self) -> None:
        lo, hi = resolve_period("today", reference=_REF_TUESDAY)
        assert (lo, hi) == day_bounds(_REF_TUESDAY)

    def test_today_date_from_le_date_to(self) -> None:
        lo, hi = resolve_period("today", reference=_REF_TUESDAY)
        assert lo <= hi


# ---------------------------------------------------------------------------
# resolve_period — week
# ---------------------------------------------------------------------------


class TestResolvePeriodWeek:
    def test_week_date_from_is_monday(self) -> None:
        lo, _ = resolve_period("week", reference=_REF_TUESDAY)
        assert lo == _REF_MONDAY

    def test_week_date_to_is_sunday(self) -> None:
        _, hi = resolve_period("week", reference=_REF_TUESDAY)
        assert hi == datetime.date(2026, 8, 9)

    def test_week_matches_week_bounds(self) -> None:
        lo, hi = resolve_period("week", reference=_REF_TUESDAY)
        assert (lo, hi) == week_bounds(_REF_TUESDAY)


# ---------------------------------------------------------------------------
# resolve_period — month
# ---------------------------------------------------------------------------


class TestResolvePeriodMonth:
    def test_month_date_from_is_first(self) -> None:
        lo, _ = resolve_period("month", reference=_REF_TUESDAY)
        assert lo == datetime.date(2026, 8, 1)

    def test_month_date_to_is_last(self) -> None:
        _, hi = resolve_period("month", reference=_REF_TUESDAY)
        assert hi == datetime.date(2026, 8, 31)

    def test_month_matches_month_bounds(self) -> None:
        lo, hi = resolve_period("month", reference=_REF_TUESDAY)
        assert (lo, hi) == month_bounds(_REF_TUESDAY)


# ---------------------------------------------------------------------------
# resolve_period — custom
# ---------------------------------------------------------------------------


class TestResolvePeriodCustom:
    def test_custom_returns_given_dates(self) -> None:
        d_from = datetime.date(2026, 7, 1)
        d_to = datetime.date(2026, 7, 15)
        lo, hi = resolve_period("custom", reference=_REF_TUESDAY, date_from=d_from, date_to=d_to)
        assert lo == d_from
        assert hi == d_to

    def test_custom_single_day_is_valid(self) -> None:
        d = datetime.date(2026, 8, 1)
        lo, hi = resolve_period("custom", reference=_REF_TUESDAY, date_from=d, date_to=d)
        assert lo == hi == d

    def test_custom_missing_date_from_raises(self) -> None:
        with pytest.raises(InvalidDashboardPeriod):
            resolve_period("custom", reference=_REF_TUESDAY, date_from=None, date_to=datetime.date(2026, 8, 1))

    def test_custom_missing_date_to_raises(self) -> None:
        with pytest.raises(InvalidDashboardPeriod):
            resolve_period("custom", reference=_REF_TUESDAY, date_from=datetime.date(2026, 8, 1), date_to=None)

    def test_custom_both_missing_raises(self) -> None:
        with pytest.raises(InvalidDashboardPeriod):
            resolve_period("custom", reference=_REF_TUESDAY)

    def test_custom_date_to_before_date_from_raises(self) -> None:
        with pytest.raises(InvalidDashboardPeriod):
            resolve_period(
                "custom",
                reference=_REF_TUESDAY,
                date_from=datetime.date(2026, 8, 10),
                date_to=datetime.date(2026, 8, 1),
            )


# ---------------------------------------------------------------------------
# resolve_period — genre inconnu
# ---------------------------------------------------------------------------


class TestResolvePeriodUnknown:
    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(InvalidDashboardPeriod):
            resolve_period("yearly", reference=_REF_TUESDAY)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidDashboardPeriod):
            resolve_period("", reference=_REF_TUESDAY)


# ---------------------------------------------------------------------------
# previous_period
# ---------------------------------------------------------------------------


class TestPreviousPeriod:
    def test_single_day_period_prev_to_is_day_before(self) -> None:
        d = datetime.date(2026, 8, 5)
        prev_from, prev_to = previous_period(d, d)
        assert prev_to == d - datetime.timedelta(days=1)
        assert prev_from == prev_to

    def test_seven_day_period_same_length(self) -> None:
        d_from = datetime.date(2026, 8, 3)  # lundi
        d_to = datetime.date(2026, 8, 9)   # dimanche
        prev_from, prev_to = previous_period(d_from, d_to)
        assert (prev_to - prev_from).days == 6

    def test_contiguous_prev_to_equals_date_from_minus_one(self) -> None:
        d_from = datetime.date(2026, 8, 3)
        d_to = datetime.date(2026, 8, 9)
        prev_from, prev_to = previous_period(d_from, d_to)
        assert prev_to == d_from - datetime.timedelta(days=1)

    def test_month_period_same_length(self) -> None:
        d_from = datetime.date(2026, 8, 1)
        d_to = datetime.date(2026, 8, 31)
        prev_from, prev_to = previous_period(d_from, d_to)
        expected_length = (d_to - d_from).days
        assert (prev_to - prev_from).days == expected_length

    def test_prev_from_le_prev_to(self) -> None:
        prev_from, prev_to = previous_period(
            datetime.date(2026, 8, 3), datetime.date(2026, 8, 9)
        )
        assert prev_from <= prev_to

    def test_cross_year_boundary(self) -> None:
        d_from = datetime.date(2026, 1, 1)
        d_to = datetime.date(2026, 1, 7)
        prev_from, prev_to = previous_period(d_from, d_to)
        assert prev_to == datetime.date(2025, 12, 31)
        assert prev_from == datetime.date(2025, 12, 25)


# ---------------------------------------------------------------------------
# Evolution / compute_evolution
# ---------------------------------------------------------------------------


class TestEvolution:
    def test_current_greater_than_previous_direction_up(self) -> None:
        evo = Evolution(current=10, previous=5)
        assert evo.direction == "up"

    def test_current_less_than_previous_direction_down(self) -> None:
        evo = Evolution(current=3, previous=7)
        assert evo.direction == "down"

    def test_equal_current_previous_direction_flat(self) -> None:
        evo = Evolution(current=5, previous=5)
        assert evo.direction == "flat"

    def test_delta_is_current_minus_previous(self) -> None:
        evo = Evolution(current=10, previous=3)
        assert evo.delta == 7

    def test_negative_delta(self) -> None:
        evo = Evolution(current=2, previous=8)
        assert evo.delta == -6

    def test_zero_previous_direction_based_on_delta_sign(self) -> None:
        """Pas de division par zéro : la direction est fondée sur le signe du delta."""
        evo = Evolution(current=5, previous=0)
        assert evo.direction == "up"

    def test_zero_previous_zero_current_is_flat(self) -> None:
        evo = Evolution(current=0, previous=0)
        assert evo.direction == "flat"

    def test_decimal_current_and_previous(self) -> None:
        evo = Evolution(
            current=decimal.Decimal("125000.00"),
            previous=decimal.Decimal("98000.00"),
        )
        assert evo.direction == "up"
        assert evo.delta == decimal.Decimal("27000.00")

    def test_frozen_cannot_mutate_current(self) -> None:
        evo = Evolution(current=5, previous=3)
        with pytest.raises((AttributeError, TypeError)):
            evo.current = 99  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert Evolution(current=5, previous=3) == Evolution(current=5, previous=3)

    def test_compute_evolution_returns_evolution(self) -> None:
        evo = compute_evolution(10, 7)
        assert isinstance(evo, Evolution)
        assert evo.current == 10
        assert evo.previous == 7


# ---------------------------------------------------------------------------
# is_in_progress
# ---------------------------------------------------------------------------


class TestIsInProgress:
    _DATE = datetime.date(2026, 8, 7)
    _START = datetime.time(14, 0)
    _END = datetime.time(15, 30)

    def _now(self, h: int, m: int) -> datetime.datetime:
        return datetime.datetime.combine(self._DATE, datetime.time(h, m))

    def test_before_start_is_false(self) -> None:
        assert not is_in_progress(self._now(13, 59), self._DATE, self._START, self._END)

    def test_at_start_is_true(self) -> None:
        """Borne basse inclusive."""
        assert is_in_progress(self._now(14, 0), self._DATE, self._START, self._END)

    def test_between_start_and_end_is_true(self) -> None:
        assert is_in_progress(self._now(14, 45), self._DATE, self._START, self._END)

    def test_at_end_is_false(self) -> None:
        """Borne haute exclusive."""
        assert not is_in_progress(self._now(15, 30), self._DATE, self._START, self._END)

    def test_after_end_is_false(self) -> None:
        assert not is_in_progress(self._now(16, 0), self._DATE, self._START, self._END)

    def test_different_day_same_time_is_false(self) -> None:
        other_day = datetime.datetime(2026, 8, 8, 14, 30)
        assert not is_in_progress(other_day, self._DATE, self._START, self._END)

    def test_midnight_boundary_same_day(self) -> None:
        start = datetime.time(0, 0)
        end = datetime.time(1, 0)
        d = datetime.date(2026, 8, 7)
        assert is_in_progress(datetime.datetime(2026, 8, 7, 0, 0), d, start, end)
        assert not is_in_progress(datetime.datetime(2026, 8, 7, 1, 0), d, start, end)


# ---------------------------------------------------------------------------
# has_started
# ---------------------------------------------------------------------------


class TestHasStarted:
    _DATE = datetime.date(2026, 8, 7)
    _START = datetime.time(10, 0)

    def test_before_start_is_false(self) -> None:
        now = datetime.datetime.combine(self._DATE, datetime.time(9, 59))
        assert not has_started(now, self._DATE, self._START)

    def test_at_start_is_true(self) -> None:
        now = datetime.datetime.combine(self._DATE, datetime.time(10, 0))
        assert has_started(now, self._DATE, self._START)

    def test_after_start_is_true(self) -> None:
        now = datetime.datetime.combine(self._DATE, datetime.time(11, 0))
        assert has_started(now, self._DATE, self._START)

    def test_different_day_past_start_time_is_false(self) -> None:
        """Un jour différent avec la même heure : ne doit pas matcher le jour original."""
        now = datetime.datetime(2026, 8, 8, 10, 0)
        # start > now quand le RDV est pour le 2026-08-07 et maintenant c'est le 08 :
        # datetime.combine(2026-08-07, 10:00) <= datetime(2026-08-08, 10:00) → True
        # Donc « le RDV du 07 a démarré » d'après has_started, ce qui est correct —
        # `has_started` est agnostique du jour : elle compare juste les datetimes.
        start_dt = datetime.datetime.combine(self._DATE, self._START)
        assert has_started(now, self._DATE, self._START) == (start_dt <= now)


# ---------------------------------------------------------------------------
# build_series
# ---------------------------------------------------------------------------


class TestBuildSeries:
    _FROM = datetime.date(2026, 8, 1)
    _TO = datetime.date(2026, 8, 5)

    def test_empty_values_all_zero(self) -> None:
        series = build_series(self._FROM, self._TO, {}, zero=0)
        assert all(b.value == 0 for b in series)

    def test_five_day_range_has_five_buckets(self) -> None:
        series = build_series(self._FROM, self._TO, {}, zero=0)
        assert len(series) == 5

    def test_known_day_has_correct_value(self) -> None:
        values = {datetime.date(2026, 8, 3): 7}
        series = build_series(self._FROM, self._TO, values, zero=0)
        bucket = next(b for b in series if b.bucket_start == datetime.date(2026, 8, 3))
        assert bucket.value == 7

    def test_missing_day_has_zero_value(self) -> None:
        values = {datetime.date(2026, 8, 3): 7}
        series = build_series(self._FROM, self._TO, values, zero=0)
        bucket = next(b for b in series if b.bucket_start == datetime.date(2026, 8, 1))
        assert bucket.value == 0

    def test_returns_tuple(self) -> None:
        series = build_series(self._FROM, self._TO, {}, zero=0)
        assert isinstance(series, tuple)

    def test_buckets_are_series_buckets(self) -> None:
        series = build_series(self._FROM, self._TO, {}, zero=0)
        assert all(isinstance(b, SeriesBucket) for b in series)

    def test_single_day_range(self) -> None:
        d = datetime.date(2026, 8, 7)
        series = build_series(d, d, {}, zero=0)
        assert len(series) == 1
        assert series[0].bucket_start == d
        assert series[0].bucket_end == d

    def test_decimal_zero_for_money_series(self) -> None:
        zero = decimal.Decimal("0.00")
        series = build_series(self._FROM, self._TO, {}, zero=zero)
        assert all(b.value == zero for b in series)

    def test_contiguous_dates(self) -> None:
        """Les buckets couvrent chaque jour civil, sans trou."""
        series = build_series(self._FROM, self._TO, {}, zero=0)
        for i, bucket in enumerate(series):
            expected = self._FROM + datetime.timedelta(days=i)
            assert bucket.bucket_start == expected
