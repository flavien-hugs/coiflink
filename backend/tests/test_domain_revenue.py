"""Tests unitaires — domaine `revenue.py` (US-6.2, #40).

Couvre :
- `RevenuePeriodTotal` : frozen (immuable), valeurs, devise par défaut, pas de PII ;
- `RevenueSummary` : frozen, structure (reference_date, day/week/month, currency) ;
- `day_bounds` : renvoie `(d, d)` ;
- `week_bounds` : mardi → (lundi, dimanche) ; dimanche → borne haute = ce dimanche ;
  lundi → `date_from == d` ; semaine à cheval sur deux mois ; semaine à cheval sur
  deux années (fin décembre) ;
- `month_bounds` : fév. non bissextile (28 j) ; fév. bissextile 2028 (29 j) ; mois
  de 30 j ; mois de 31 j ; `date_from == 1er`, `date_to == dernier jour` ;
- Invariants : `date_from ≤ date_to` pour toutes les bornes ; `week_bounds ⊇ day_bounds`
  (lundi ≤ d ≤ dimanche) ; `month_bounds ⊇ day_bounds` (1er ≤ d ≤ dernier jour).

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import calendar
import datetime
import decimal

import pytest

from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.revenue import (
    RevenuePeriodTotal,
    RevenueSummary,
    day_bounds,
    month_bounds,
    week_bounds,
)

# ---------------------------------------------------------------------------
# Dates réutilisées
# ---------------------------------------------------------------------------

_TUESDAY = datetime.date(2026, 8, 4)    # mardi
_MONDAY = datetime.date(2026, 8, 3)     # lundi de la même semaine
_SUNDAY = datetime.date(2026, 8, 9)     # dimanche de la même semaine
_MON_REF = datetime.date(2026, 7, 27)   # un lundi exact
_SUN_REF = datetime.date(2026, 8, 2)    # un dimanche exact
# Mercredi 1er juillet 2026 : semaine lundi 29/06 → dimanche 05/07 (deux mois)
_CROSS_MONTH_DAY = datetime.date(2026, 7, 1)
# Mercredi 31 décembre 2025 : semaine lundi 29/12/2025 → dimanche 04/01/2026 (deux années)
_CROSS_YEAR_DAY = datetime.date(2025, 12, 31)


# ---------------------------------------------------------------------------
# RevenuePeriodTotal — objet-valeur
# ---------------------------------------------------------------------------


class TestRevenuePeriodTotal:
    def _make(self, **kw: object) -> RevenuePeriodTotal:
        defaults: dict[str, object] = dict(
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 1),
            total=decimal.Decimal("35000.00"),
        )
        defaults.update(kw)
        return RevenuePeriodTotal(**defaults)  # type: ignore[arg-type]

    def test_default_currency_is_xof(self) -> None:
        assert self._make().currency == DEFAULT_CURRENCY

    def test_currency_string_is_xof(self) -> None:
        assert self._make().currency == "XOF"

    def test_total_is_decimal(self) -> None:
        p = self._make(total=decimal.Decimal("5000.50"))
        assert isinstance(p.total, decimal.Decimal)
        assert p.total == decimal.Decimal("5000.50")

    def test_total_can_be_negative(self) -> None:
        """Total négatif si corrections excèdent les paiements sur la période."""
        p = self._make(total=decimal.Decimal("-1000.00"))
        assert p.total == decimal.Decimal("-1000.00")

    def test_total_can_be_zero(self) -> None:
        p = self._make(total=decimal.Decimal("0.00"))
        assert p.total == decimal.Decimal("0.00")

    def test_frozen_cannot_mutate_total(self) -> None:
        p = self._make()
        with pytest.raises((AttributeError, TypeError)):
            p.total = decimal.Decimal("0.00")  # type: ignore[misc]

    def test_frozen_cannot_mutate_date_from(self) -> None:
        p = self._make()
        with pytest.raises((AttributeError, TypeError)):
            p.date_from = datetime.date(2026, 1, 1)  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert self._make() == self._make()

    def test_no_client_id_field(self) -> None:
        assert not hasattr(self._make(), "client_id"), "client_id est une PII interdite (§11.3)"

    def test_no_reference_field(self) -> None:
        assert not hasattr(self._make(), "reference"), "reference est une PII interdite (§11.3)"

    def test_no_recorded_by_field(self) -> None:
        assert not hasattr(self._make(), "recorded_by"), "recorded_by est une PII interdite (§11.3)"

    def test_no_performed_by_field(self) -> None:
        assert not hasattr(self._make(), "performed_by"), "performed_by est une PII interdite (§11.3)"

    def test_expected_fields_present(self) -> None:
        p = self._make()
        assert hasattr(p, "date_from")
        assert hasattr(p, "date_to")
        assert hasattr(p, "total")
        assert hasattr(p, "currency")


# ---------------------------------------------------------------------------
# RevenueSummary — objet-valeur
# ---------------------------------------------------------------------------


class TestRevenueSummary:
    def _make_period(self, d: datetime.date) -> RevenuePeriodTotal:
        return RevenuePeriodTotal(
            date_from=d,
            date_to=d,
            total=decimal.Decimal("0.00"),
        )

    def _make(self) -> RevenueSummary:
        ref = datetime.date(2026, 8, 2)
        return RevenueSummary(
            reference_date=ref,
            day=self._make_period(ref),
            week=self._make_period(ref),
            month=self._make_period(ref),
        )

    def test_default_currency_is_xof(self) -> None:
        assert self._make().currency == DEFAULT_CURRENCY

    def test_frozen_cannot_mutate_reference_date(self) -> None:
        s = self._make()
        with pytest.raises((AttributeError, TypeError)):
            s.reference_date = datetime.date(2026, 1, 1)  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert self._make() == self._make()

    def test_has_day_week_month_fields(self) -> None:
        s = self._make()
        assert hasattr(s, "day")
        assert hasattr(s, "week")
        assert hasattr(s, "month")

    def test_no_client_id_field(self) -> None:
        assert not hasattr(self._make(), "client_id"), "client_id est une PII interdite (§11.3)"


# ---------------------------------------------------------------------------
# day_bounds
# ---------------------------------------------------------------------------


class TestDayBounds:
    def test_returns_same_date_twice(self) -> None:
        d = datetime.date(2026, 8, 4)
        lo, hi = day_bounds(d)
        assert lo == d
        assert hi == d

    def test_date_from_equals_date_to(self) -> None:
        lo, hi = day_bounds(datetime.date(2026, 1, 15))
        assert lo == hi

    def test_returns_tuple_of_two(self) -> None:
        result = day_bounds(datetime.date(2026, 8, 4))
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_different_dates_produce_different_bounds(self) -> None:
        assert day_bounds(datetime.date(2026, 8, 1)) != day_bounds(datetime.date(2026, 8, 2))

    def test_date_from_le_date_to(self) -> None:
        lo, hi = day_bounds(datetime.date(2026, 8, 4))
        assert lo <= hi


# ---------------------------------------------------------------------------
# week_bounds
# ---------------------------------------------------------------------------


class TestWeekBounds:
    def test_tuesday_date_from_is_monday(self) -> None:
        lo, _ = week_bounds(_TUESDAY)
        assert lo == _MONDAY

    def test_tuesday_date_to_is_sunday(self) -> None:
        _, hi = week_bounds(_TUESDAY)
        assert hi == _SUNDAY

    def test_monday_date_from_equals_self(self) -> None:
        """Un lundi est sa propre borne basse."""
        lo, _ = week_bounds(_MON_REF)
        assert lo == _MON_REF

    def test_monday_date_to_is_six_days_later(self) -> None:
        """Lundi 27/07 → dimanche 02/08."""
        _, hi = week_bounds(_MON_REF)
        assert hi == datetime.date(2026, 8, 2)

    def test_sunday_date_to_equals_self(self) -> None:
        """Un dimanche est sa propre borne haute."""
        _, hi = week_bounds(_SUN_REF)
        assert hi == _SUN_REF

    def test_sunday_date_from_is_six_days_earlier(self) -> None:
        """Dimanche 02/08 → lundi 27/07."""
        lo, _ = week_bounds(_SUN_REF)
        assert lo == datetime.date(2026, 7, 27)

    def test_cross_month_week_bounds(self) -> None:
        """01/07 (mer) → lundi 29/06, dimanche 05/07 (à cheval juin/juillet)."""
        lo, hi = week_bounds(_CROSS_MONTH_DAY)
        assert lo == datetime.date(2026, 6, 29)
        assert hi == datetime.date(2026, 7, 5)

    def test_cross_year_week_bounds(self) -> None:
        """31/12/2025 (mer) → lundi 29/12/2025, dimanche 04/01/2026."""
        lo, hi = week_bounds(_CROSS_YEAR_DAY)
        assert lo == datetime.date(2025, 12, 29)
        assert hi == datetime.date(2026, 1, 4)

    def test_week_spans_exactly_seven_days(self) -> None:
        lo, hi = week_bounds(_TUESDAY)
        assert (hi - lo).days == 6

    def test_date_from_le_date_to_for_all_cases(self) -> None:
        for d in [_TUESDAY, _MON_REF, _SUN_REF, _CROSS_MONTH_DAY, _CROSS_YEAR_DAY]:
            lo, hi = week_bounds(d)
            assert lo <= hi, f"date_from > date_to pour {d}"

    def test_reference_within_week_bounds(self) -> None:
        """La date de référence doit toujours se trouver dans [date_from, date_to]."""
        for d in [_TUESDAY, _MON_REF, _SUN_REF, _CROSS_MONTH_DAY, _CROSS_YEAR_DAY]:
            lo, hi = week_bounds(d)
            assert lo <= d <= hi, f"référence {d} hors de la semaine {lo}–{hi}"

    def test_date_from_is_monday_for_all_cases(self) -> None:
        """date_from doit toujours être un lundi (weekday() == 0)."""
        for d in [_TUESDAY, _MON_REF, _SUN_REF, _CROSS_MONTH_DAY, _CROSS_YEAR_DAY]:
            lo, _ = week_bounds(d)
            assert lo.weekday() == 0, f"date_from {lo} n'est pas un lundi (weekday={lo.weekday()})"

    def test_date_to_is_sunday_for_all_cases(self) -> None:
        """date_to doit toujours être un dimanche (weekday() == 6)."""
        for d in [_TUESDAY, _MON_REF, _SUN_REF, _CROSS_MONTH_DAY, _CROSS_YEAR_DAY]:
            _, hi = week_bounds(d)
            assert hi.weekday() == 6, f"date_to {hi} n'est pas un dimanche (weekday={hi.weekday()})"


# ---------------------------------------------------------------------------
# month_bounds
# ---------------------------------------------------------------------------


class TestMonthBounds:
    def test_january_last_day_is_31(self) -> None:
        lo, hi = month_bounds(datetime.date(2026, 1, 15))
        assert lo == datetime.date(2026, 1, 1)
        assert hi == datetime.date(2026, 1, 31)

    def test_february_non_leap_last_day_is_28(self) -> None:
        lo, hi = month_bounds(datetime.date(2026, 2, 14))
        assert lo == datetime.date(2026, 2, 1)
        assert hi == datetime.date(2026, 2, 28)

    def test_february_leap_2028_last_day_is_29(self) -> None:
        lo, hi = month_bounds(datetime.date(2028, 2, 14))
        assert lo == datetime.date(2028, 2, 1)
        assert hi == datetime.date(2028, 2, 29)

    def test_april_last_day_is_30(self) -> None:
        lo, hi = month_bounds(datetime.date(2026, 4, 10))
        assert lo == datetime.date(2026, 4, 1)
        assert hi == datetime.date(2026, 4, 30)

    def test_august_last_day_is_31(self) -> None:
        lo, hi = month_bounds(datetime.date(2026, 8, 2))
        assert lo == datetime.date(2026, 8, 1)
        assert hi == datetime.date(2026, 8, 31)

    def test_date_from_is_first_of_month_for_all_months(self) -> None:
        for month in range(1, 13):
            lo, _ = month_bounds(datetime.date(2026, month, 15))
            assert lo.day == 1, f"mois {month}: date_from.day={lo.day}, attendu 1"

    def test_date_to_is_last_of_month_for_all_months(self) -> None:
        for month in range(1, 13):
            _, hi = month_bounds(datetime.date(2026, month, 15))
            expected_last = calendar.monthrange(2026, month)[1]
            assert hi.day == expected_last, (
                f"mois {month}: date_to.day={hi.day}, attendu {expected_last}"
            )

    def test_date_from_le_date_to_for_all_months(self) -> None:
        for month in range(1, 13):
            lo, hi = month_bounds(datetime.date(2026, month, 15))
            assert lo <= hi

    def test_reference_within_month_bounds(self) -> None:
        for month in range(1, 13):
            d = datetime.date(2026, month, 15)
            lo, hi = month_bounds(d)
            assert lo <= d <= hi, f"référence {d} hors du mois {lo}–{hi}"

    def test_date_from_day_is_1_for_last_day_of_month(self) -> None:
        lo, _ = month_bounds(datetime.date(2026, 8, 31))
        assert lo.day == 1

    def test_date_to_equals_input_for_last_day_of_month(self) -> None:
        """Le dernier jour du mois est aussi la borne haute."""
        last_day = datetime.date(2026, 8, 31)
        _, hi = month_bounds(last_day)
        assert hi == last_day


# ---------------------------------------------------------------------------
# Invariants croisés : semaine ⊇ jour, mois ⊇ jour
# ---------------------------------------------------------------------------


class TestCrossInvariants:
    _DATES = [
        datetime.date(2026, 8, 2),    # dimanche
        datetime.date(2026, 8, 3),    # lundi
        datetime.date(2026, 7, 1),    # 1er juillet
        datetime.date(2025, 12, 31),  # 31 décembre
        datetime.date(2028, 2, 29),   # 29 février bissextile
    ]

    def test_day_within_week(self) -> None:
        for d in self._DATES:
            d_lo, d_hi = day_bounds(d)
            w_lo, w_hi = week_bounds(d)
            assert w_lo <= d_lo and d_hi <= w_hi, (
                f"jour {d} hors de la semaine {w_lo}–{w_hi}"
            )

    def test_day_within_month(self) -> None:
        for d in self._DATES:
            d_lo, d_hi = day_bounds(d)
            m_lo, m_hi = month_bounds(d)
            assert m_lo <= d_lo and d_hi <= m_hi, (
                f"jour {d} hors du mois {m_lo}–{m_hi}"
            )
