"""Tests unitaires — domaine `discrepancy.py` (US-5.4, #36).

Couvre :
- constantes `COMPLETED_STATUS` / `PAID_PAYMENT_STATUSES` (critères métier) ;
- `validate_discrepancy_filter` : filtre vide, bornes valides (date seule, plage
  ordonnée, single-day), inversée → `InvalidDiscrepancyFilter` ;
- types non-date pour chaque borne → `InvalidDiscrepancyFilter` ;
- message d'erreur neutre (§11.3 — ne reprend jamais la valeur soumise) ;
- `DiscrepancyFilter.is_empty` ;
- `CashDiscrepancy` : immutabilité (frozen), devise par défaut, champ optionnel
  `client_name`.

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.domain.discrepancy import (
    COMPLETED_STATUS,
    PAID_PAYMENT_STATUSES,
    CashDiscrepancy,
    DiscrepancyFilter,
    validate_discrepancy_filter,
)
from coiflink_api.domain.errors import InvalidDiscrepancyFilter
from coiflink_api.domain.payment import DEFAULT_CURRENCY

# ---------------------------------------------------------------------------
# Dates réutilisées
# ---------------------------------------------------------------------------

_DATE_A = datetime.date(2026, 3, 1)
_DATE_B = datetime.date(2026, 3, 31)


# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------


class TestConstants:
    def test_completed_status_value(self) -> None:
        """Seul `COMPLETED` est une prestation réalisée (jamais NO_SHOW/CANCELLED/…)."""
        assert COMPLETED_STATUS == "COMPLETED"

    def test_paid_statuses_contains_validated(self) -> None:
        assert "VALIDATED" in PAID_PAYMENT_STATUSES

    def test_paid_statuses_contains_adjusted(self) -> None:
        """Un paiement corrigé (`ADJUSTED`) couvre toujours le RDV (ADR-0028)."""
        assert "ADJUSTED" in PAID_PAYMENT_STATUSES

    def test_paid_statuses_excludes_pending(self) -> None:
        """Un paiement `PENDING` n'est pas acquis : le RDV reste un écart."""
        assert "PENDING" not in PAID_PAYMENT_STATUSES

    def test_paid_statuses_excludes_cancelled(self) -> None:
        """Un paiement `CANCELLED` ne couvre rien : le RDV reste un écart."""
        assert "CANCELLED" not in PAID_PAYMENT_STATUSES

    def test_paid_statuses_is_tuple(self) -> None:
        assert isinstance(PAID_PAYMENT_STATUSES, tuple)


# ---------------------------------------------------------------------------
# Filtre vide
# ---------------------------------------------------------------------------


class TestEmptyFilter:
    def test_no_args_is_empty(self) -> None:
        f = validate_discrepancy_filter()
        assert f.is_empty is True

    def test_no_args_no_exception(self) -> None:
        validate_discrepancy_filter()  # ne lève rien

    def test_no_args_both_bounds_none(self) -> None:
        f = validate_discrepancy_filter()
        assert f.date_from is None
        assert f.date_to is None

    def test_is_empty_false_when_date_from_present(self) -> None:
        f = validate_discrepancy_filter(date_from=_DATE_A)
        assert f.is_empty is False

    def test_is_empty_false_when_date_to_present(self) -> None:
        f = validate_discrepancy_filter(date_to=_DATE_B)
        assert f.is_empty is False

    def test_is_empty_false_when_both_bounds_present(self) -> None:
        f = validate_discrepancy_filter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.is_empty is False


# ---------------------------------------------------------------------------
# Plage de dates — cas valides
# ---------------------------------------------------------------------------


class TestDateRangeValid:
    def test_date_from_only(self) -> None:
        f = validate_discrepancy_filter(date_from=_DATE_A)
        assert f.date_from == _DATE_A
        assert f.date_to is None

    def test_date_to_only(self) -> None:
        f = validate_discrepancy_filter(date_to=_DATE_B)
        assert f.date_to == _DATE_B
        assert f.date_from is None

    def test_date_from_lt_date_to(self) -> None:
        f = validate_discrepancy_filter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_B

    def test_date_from_eq_date_to_single_day(self) -> None:
        """Une plage mono-journée est valide."""
        f = validate_discrepancy_filter(date_from=_DATE_A, date_to=_DATE_A)
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_A

    def test_returns_discrepancy_filter_instance(self) -> None:
        f = validate_discrepancy_filter(date_from=_DATE_A)
        assert isinstance(f, DiscrepancyFilter)


# ---------------------------------------------------------------------------
# Plage de dates — cas invalides
# ---------------------------------------------------------------------------


class TestDateRangeInvalid:
    def test_date_from_gt_date_to_raises(self) -> None:
        with pytest.raises(InvalidDiscrepancyFilter):
            validate_discrepancy_filter(date_from=_DATE_B, date_to=_DATE_A)

    def test_error_message_neutral_date_range(self) -> None:
        """Message neutre : contient « invalide » sans reprendre la valeur (§11.3)."""
        with pytest.raises(InvalidDiscrepancyFilter, match="invalide"):
            validate_discrepancy_filter(date_from=_DATE_B, date_to=_DATE_A)

    def test_error_message_does_not_contain_date_value(self) -> None:
        """Le message ne doit jamais répéter la valeur soumise (§11.3)."""
        try:
            validate_discrepancy_filter(date_from=_DATE_B, date_to=_DATE_A)
        except InvalidDiscrepancyFilter as exc:
            assert str(_DATE_B) not in str(exc)
            assert str(_DATE_A) not in str(exc)


# ---------------------------------------------------------------------------
# Types non-date — rejetés
# ---------------------------------------------------------------------------


class TestTypeErrors:
    def test_string_date_from_raises(self) -> None:
        with pytest.raises(InvalidDiscrepancyFilter):
            validate_discrepancy_filter(date_from="2026-03-01")  # type: ignore[arg-type]

    def test_string_date_to_raises(self) -> None:
        with pytest.raises(InvalidDiscrepancyFilter):
            validate_discrepancy_filter(date_to="2026-03-31")  # type: ignore[arg-type]

    def test_integer_date_from_raises(self) -> None:
        with pytest.raises(InvalidDiscrepancyFilter):
            validate_discrepancy_filter(date_from=20260301)  # type: ignore[arg-type]

    def test_integer_date_to_raises(self) -> None:
        with pytest.raises(InvalidDiscrepancyFilter):
            validate_discrepancy_filter(date_to=20260331)  # type: ignore[arg-type]

    def test_type_error_message_neutral(self) -> None:
        with pytest.raises(InvalidDiscrepancyFilter, match="invalide"):
            validate_discrepancy_filter(date_from="not-a-date")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DiscrepancyFilter — propriété is_empty
# ---------------------------------------------------------------------------


class TestDiscrepancyFilter:
    def test_both_none_is_empty(self) -> None:
        f = DiscrepancyFilter()
        assert f.is_empty is True

    def test_date_from_set_not_empty(self) -> None:
        f = DiscrepancyFilter(date_from=_DATE_A)
        assert f.is_empty is False

    def test_date_to_set_not_empty(self) -> None:
        f = DiscrepancyFilter(date_to=_DATE_B)
        assert f.is_empty is False

    def test_both_set_not_empty(self) -> None:
        f = DiscrepancyFilter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.is_empty is False

    def test_frozen_cannot_set_date_from(self) -> None:
        """`DiscrepancyFilter` est un objet-valeur immuable (frozen dataclass)."""
        f = DiscrepancyFilter(date_from=_DATE_A)
        with pytest.raises((AttributeError, TypeError)):
            f.date_from = _DATE_B  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        f1 = DiscrepancyFilter(date_from=_DATE_A, date_to=_DATE_B)
        f2 = DiscrepancyFilter(date_from=_DATE_A, date_to=_DATE_B)
        assert f1 == f2


# ---------------------------------------------------------------------------
# CashDiscrepancy — valeur de domaine
# ---------------------------------------------------------------------------


class TestCashDiscrepancy:
    def _make(self, **kwargs) -> CashDiscrepancy:  # type: ignore[no-untyped-def]
        defaults = dict(
            appointment_id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            salon_id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001"),
            appointment_date=datetime.date(2026, 3, 15),
            start_time=datetime.time(10, 0),
            client_id=uuid.UUID("cccccccc-0000-0000-0000-000000000001"),
            expected_amount=decimal.Decimal("5000.00"),
        )
        defaults.update(kwargs)
        return CashDiscrepancy(**defaults)

    def test_default_currency_is_xof(self) -> None:
        d = self._make()
        assert d.currency == DEFAULT_CURRENCY

    def test_client_name_defaults_to_none(self) -> None:
        d = self._make()
        assert d.client_name is None

    def test_client_name_preserved_when_set(self) -> None:
        d = self._make(client_name="Awa Koné")
        assert d.client_name == "Awa Koné"

    def test_frozen_cannot_mutate_expected_amount(self) -> None:
        """`CashDiscrepancy` est une projection de lecture immuable (frozen dataclass)."""
        d = self._make()
        with pytest.raises((AttributeError, TypeError)):
            d.expected_amount = decimal.Decimal("0.00")  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        appt_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        d1 = self._make(appointment_id=appt_id)
        d2 = self._make(appointment_id=appt_id)
        assert d1 == d2

    def test_expected_amount_is_decimal(self) -> None:
        d = self._make(expected_amount=decimal.Decimal("2500.50"))
        assert isinstance(d.expected_amount, decimal.Decimal)
        assert d.expected_amount == decimal.Decimal("2500.50")
