"""Tests unitaires — domaine `platform_transactions.py` (US-5.6, #37).

Couvre :
- `SalonTransactionSummary` : immutabilité (frozen), devise par défaut, égalité par
  valeur, absence de champs PII (§11.3) ;
- `PlatformSummaryFilter` : immutabilité, `is_empty`, bornes UTC déjà converties ;
- `validate_platform_summary_filter` : filtre vide, bornes valides (date seule, plage
  ordonnée, single-day), plage inversée → `InvalidPlatformSummaryFilter` ;
- types non-date → `InvalidPlatformSummaryFilter` ;
- message d'erreur neutre (§11.3 — ne reprend jamais la valeur soumise) ;
- conversion `Africa/Abidjan → UTC` : Africa/Abidjan = UTC+0, borne basse 00:00:00,
  borne haute 23:59:59.999999 UTC-aware.

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.domain.errors import InvalidPlatformSummaryFilter
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.platform_transactions import (
    PlatformSummaryFilter,
    SalonTransactionSummary,
    validate_platform_summary_filter,
)

# ---------------------------------------------------------------------------
# Dates réutilisées
# ---------------------------------------------------------------------------

_DATE_A = datetime.date(2026, 3, 1)
_DATE_B = datetime.date(2026, 3, 31)
_DATE_C = datetime.date(2026, 4, 15)

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# SalonTransactionSummary — valeur de domaine
# ---------------------------------------------------------------------------


class TestSalonTransactionSummary:
    def _make(self, **kwargs) -> SalonTransactionSummary:  # type: ignore[no-untyped-def]
        defaults = dict(
            salon_id=_SALON_ID,
            salon_name="Salon Belle Coupe",
            payment_count=10,
            adjustment_count=2,
            total_amount=decimal.Decimal("50000.00"),
        )
        defaults.update(kwargs)
        return SalonTransactionSummary(**defaults)

    def test_default_currency_is_xof(self) -> None:
        s = self._make()
        assert s.currency == DEFAULT_CURRENCY

    def test_currency_is_xof_string(self) -> None:
        s = self._make()
        assert s.currency == "XOF"

    def test_total_amount_is_decimal(self) -> None:
        s = self._make(total_amount=decimal.Decimal("12500.50"))
        assert isinstance(s.total_amount, decimal.Decimal)
        assert s.total_amount == decimal.Decimal("12500.50")

    def test_equality_by_value(self) -> None:
        s1 = self._make()
        s2 = self._make()
        assert s1 == s2

    def test_frozen_cannot_mutate_payment_count(self) -> None:
        s = self._make()
        with pytest.raises((AttributeError, TypeError)):
            s.payment_count = 99  # type: ignore[misc]

    def test_frozen_cannot_mutate_total_amount(self) -> None:
        s = self._make()
        with pytest.raises((AttributeError, TypeError)):
            s.total_amount = decimal.Decimal("0.00")  # type: ignore[misc]

    def test_negative_total_amount_allowed(self) -> None:
        """Un montant net peut être négatif (corrections dépassant les paiements)."""
        s = self._make(total_amount=decimal.Decimal("-500.00"))
        assert s.total_amount == decimal.Decimal("-500.00")

    def test_zero_total_amount_allowed(self) -> None:
        s = self._make(total_amount=decimal.Decimal("0.00"))
        assert s.total_amount == decimal.Decimal("0.00")

    # ---- Non-PII (§11.3) — champs interdits absents du VO ----------------

    def test_no_client_id_field(self) -> None:
        s = self._make()
        assert not hasattr(s, "client_id"), "client_id est une PII interdite (§11.3)"

    def test_no_reference_field(self) -> None:
        s = self._make()
        assert not hasattr(s, "reference"), "reference est une PII interdite (§11.3)"

    def test_no_recorded_by_field(self) -> None:
        s = self._make()
        assert not hasattr(s, "recorded_by"), "recorded_by est une PII interdite (§11.3)"

    def test_no_performed_by_field(self) -> None:
        s = self._make()
        assert not hasattr(s, "performed_by"), "performed_by est une PII interdite (§11.3)"

    def test_no_owner_id_field(self) -> None:
        s = self._make()
        assert not hasattr(s, "owner_id"), "owner_id est une PII interdite (§11.3)"

    def test_expected_fields_present(self) -> None:
        """Seuls les champs agrégés + identité métier du salon sont présents."""
        s = self._make()
        assert hasattr(s, "salon_id")
        assert hasattr(s, "salon_name")
        assert hasattr(s, "payment_count")
        assert hasattr(s, "adjustment_count")
        assert hasattr(s, "total_amount")
        assert hasattr(s, "currency")


# ---------------------------------------------------------------------------
# PlatformSummaryFilter — propriété is_empty
# ---------------------------------------------------------------------------


class TestPlatformSummaryFilter:
    def test_all_none_is_empty(self) -> None:
        f = PlatformSummaryFilter()
        assert f.is_empty is True

    def test_date_from_set_not_empty(self) -> None:
        f = PlatformSummaryFilter(date_from=_DATE_A)
        assert f.is_empty is False

    def test_date_to_set_not_empty(self) -> None:
        f = PlatformSummaryFilter(date_to=_DATE_B)
        assert f.is_empty is False

    def test_both_set_not_empty(self) -> None:
        f = PlatformSummaryFilter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.is_empty is False

    def test_frozen_cannot_set_date_from(self) -> None:
        f = PlatformSummaryFilter(date_from=_DATE_A)
        with pytest.raises((AttributeError, TypeError)):
            f.date_from = _DATE_B  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        f1 = PlatformSummaryFilter(date_from=_DATE_A, date_to=_DATE_B)
        f2 = PlatformSummaryFilter(date_from=_DATE_A, date_to=_DATE_B)
        assert f1 == f2

    def test_is_empty_only_checks_date_fields(self) -> None:
        """`is_empty` est True même si created_at bornes sont posées sans dates."""
        f = PlatformSummaryFilter(
            created_at_from=datetime.datetime(
                2026, 3, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
            )
        )
        assert f.is_empty is True


# ---------------------------------------------------------------------------
# validate_platform_summary_filter — filtre vide
# ---------------------------------------------------------------------------


class TestEmptyFilter:
    def test_no_args_is_empty(self) -> None:
        f = validate_platform_summary_filter()
        assert f.is_empty is True

    def test_no_args_no_exception(self) -> None:
        validate_platform_summary_filter()

    def test_no_args_date_from_none(self) -> None:
        f = validate_platform_summary_filter()
        assert f.date_from is None

    def test_no_args_date_to_none(self) -> None:
        f = validate_platform_summary_filter()
        assert f.date_to is None

    def test_no_args_created_at_from_none(self) -> None:
        f = validate_platform_summary_filter()
        assert f.created_at_from is None

    def test_no_args_created_at_to_none(self) -> None:
        f = validate_platform_summary_filter()
        assert f.created_at_to is None

    def test_returns_platform_summary_filter_instance(self) -> None:
        f = validate_platform_summary_filter()
        assert isinstance(f, PlatformSummaryFilter)


# ---------------------------------------------------------------------------
# validate_platform_summary_filter — plages de dates valides
# ---------------------------------------------------------------------------


class TestDateRangeValid:
    def test_date_from_only(self) -> None:
        f = validate_platform_summary_filter(date_from=_DATE_A)
        assert f.date_from == _DATE_A
        assert f.date_to is None
        assert f.is_empty is False

    def test_date_to_only(self) -> None:
        f = validate_platform_summary_filter(date_to=_DATE_B)
        assert f.date_to == _DATE_B
        assert f.date_from is None
        assert f.is_empty is False

    def test_date_from_lt_date_to(self) -> None:
        f = validate_platform_summary_filter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_B

    def test_date_from_eq_date_to_single_day(self) -> None:
        f = validate_platform_summary_filter(date_from=_DATE_A, date_to=_DATE_A)
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_A

    def test_returns_filter_with_utc_bounds(self) -> None:
        f = validate_platform_summary_filter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.created_at_from is not None
        assert f.created_at_to is not None


# ---------------------------------------------------------------------------
# validate_platform_summary_filter — plages de dates invalides
# ---------------------------------------------------------------------------


class TestDateRangeInvalid:
    def test_date_from_gt_date_to_raises(self) -> None:
        with pytest.raises(InvalidPlatformSummaryFilter):
            validate_platform_summary_filter(date_from=_DATE_B, date_to=_DATE_A)

    def test_error_message_neutral(self) -> None:
        """Message neutre : contient « invalide » sans reprendre la valeur (§11.3)."""
        with pytest.raises(InvalidPlatformSummaryFilter, match="invalide"):
            validate_platform_summary_filter(date_from=_DATE_B, date_to=_DATE_A)

    def test_error_message_does_not_contain_date_from_value(self) -> None:
        try:
            validate_platform_summary_filter(date_from=_DATE_B, date_to=_DATE_A)
        except InvalidPlatformSummaryFilter as exc:
            assert str(_DATE_B) not in str(exc)

    def test_error_message_does_not_contain_date_to_value(self) -> None:
        try:
            validate_platform_summary_filter(date_from=_DATE_B, date_to=_DATE_A)
        except InvalidPlatformSummaryFilter as exc:
            assert str(_DATE_A) not in str(exc)


# ---------------------------------------------------------------------------
# Types non-date — rejetés
# ---------------------------------------------------------------------------


class TestTypeErrors:
    def test_string_date_from_raises(self) -> None:
        with pytest.raises(InvalidPlatformSummaryFilter):
            validate_platform_summary_filter(date_from="2026-03-01")  # type: ignore[arg-type]

    def test_string_date_to_raises(self) -> None:
        with pytest.raises(InvalidPlatformSummaryFilter):
            validate_platform_summary_filter(date_to="2026-03-31")  # type: ignore[arg-type]

    def test_integer_date_from_raises(self) -> None:
        with pytest.raises(InvalidPlatformSummaryFilter):
            validate_platform_summary_filter(date_from=20260301)  # type: ignore[arg-type]

    def test_integer_date_to_raises(self) -> None:
        with pytest.raises(InvalidPlatformSummaryFilter):
            validate_platform_summary_filter(date_to=20260331)  # type: ignore[arg-type]

    def test_type_error_message_neutral(self) -> None:
        with pytest.raises(InvalidPlatformSummaryFilter, match="invalide"):
            validate_platform_summary_filter(date_from="not-a-date")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Conversion UTC (Africa/Abidjan = UTC+0)
# ---------------------------------------------------------------------------


class TestUtcConversion:
    def test_created_at_from_is_utc_aware(self) -> None:
        f = validate_platform_summary_filter(date_from=_DATE_A)
        assert f.created_at_from is not None
        assert f.created_at_from.tzinfo is not None

    def test_created_at_to_is_utc_aware(self) -> None:
        f = validate_platform_summary_filter(date_to=_DATE_B)
        assert f.created_at_to is not None
        assert f.created_at_to.tzinfo is not None

    def test_day_start_utc_is_midnight(self) -> None:
        """Africa/Abidjan = UTC+0 : borne basse = 00:00:00.000000 UTC."""
        f = validate_platform_summary_filter(date_from=_DATE_A)
        expected = datetime.datetime(2026, 3, 1, 0, 0, 0, 0, tzinfo=datetime.timezone.utc)
        assert f.created_at_from == expected

    def test_day_end_utc_is_last_microsecond(self) -> None:
        """Africa/Abidjan = UTC+0 : borne haute = 23:59:59.999999 UTC."""
        f = validate_platform_summary_filter(date_to=_DATE_B)
        expected = datetime.datetime(
            2026, 3, 31, 23, 59, 59, 999999, tzinfo=datetime.timezone.utc
        )
        assert f.created_at_to == expected

    def test_single_day_bounds_span_full_day(self) -> None:
        """Une plage mono-journée couvre 00:00:00 → 23:59:59.999999."""
        f = validate_platform_summary_filter(date_from=_DATE_A, date_to=_DATE_A)
        assert f.created_at_from is not None
        assert f.created_at_to is not None
        assert f.created_at_from.hour == 0
        assert f.created_at_from.minute == 0
        assert f.created_at_to.hour == 23
        assert f.created_at_to.minute == 59
        assert f.created_at_to.microsecond == 999999

    def test_date_from_only_has_no_created_at_to(self) -> None:
        f = validate_platform_summary_filter(date_from=_DATE_A)
        assert f.created_at_to is None

    def test_date_to_only_has_no_created_at_from(self) -> None:
        f = validate_platform_summary_filter(date_to=_DATE_B)
        assert f.created_at_from is None

    def test_different_days_produce_different_bounds(self) -> None:
        fa = validate_platform_summary_filter(date_from=_DATE_A, date_to=_DATE_A)
        fb = validate_platform_summary_filter(date_from=_DATE_C, date_to=_DATE_C)
        assert fa.created_at_from != fb.created_at_from
        assert fa.created_at_to != fb.created_at_to
