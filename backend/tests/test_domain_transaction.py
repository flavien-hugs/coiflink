"""Tests unitaires — domaine `transaction.py` (US-5.2, #35).

Couvre `validate_transaction_filter` (objet-valeur `TransactionFilter`) :
- filtre vide → `is_empty = True` ; aucun `InvalidTransactionFilter` ;
- plage de dates incohérente (`date_from > date_to`) → `InvalidTransactionFilter` ;
- plage de dates identique (single-day) → valide ;
- plage de montants incohérente (`amount_min > amount_max`) → `InvalidTransactionFilter` ;
- plage de montants égaux → valide ;
- mode de paiement hors enum → `InvalidTransactionFilter` ;
- mode de paiement : chaîne vide/espaces → `None` (pas de contrainte) ;
- bornes de montant : négatif, non fini, > AMOUNT_MAX, > 2 décimales, flottant,
  booléen → `InvalidTransactionFilter` ;
- entier (int) acceptable comme borne de montant ;
- conversion `Africa/Abidjan → UTC` : `created_at_from`/`created_at_to` portés par
  le `TransactionFilter` (UTC+0, donc inchangés) ;
- `None` pour tout champ = pas de contrainte (pas d'erreur).

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import datetime
import decimal

import pytest

from coiflink_api.domain.errors import InvalidTransactionFilter
from coiflink_api.domain.payment import AMOUNT_MAX, AMOUNT_MIN
from coiflink_api.domain.transaction import (
    PAYMENT_METHOD_VALUES,
    SALON_TIMEZONE,
    validate_transaction_filter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_A = datetime.date(2026, 3, 1)
_DATE_B = datetime.date(2026, 3, 31)


def _utc(dt: datetime.datetime) -> datetime.datetime:
    return dt.astimezone(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Filtre vide — aucune contrainte
# ---------------------------------------------------------------------------


class TestEmptyFilter:
    def test_all_none_is_empty(self) -> None:
        f = validate_transaction_filter()
        assert f.is_empty is True

    def test_all_none_no_exception(self) -> None:
        validate_transaction_filter()  # ne lève rien

    def test_empty_filter_created_at_bounds_are_none(self) -> None:
        f = validate_transaction_filter()
        assert f.created_at_from is None
        assert f.created_at_to is None

    def test_is_empty_false_when_date_present(self) -> None:
        f = validate_transaction_filter(date_from=_DATE_A)
        assert f.is_empty is False

    def test_is_empty_false_when_amount_min_present(self) -> None:
        f = validate_transaction_filter(amount_min=decimal.Decimal("100.00"))
        assert f.is_empty is False

    def test_is_empty_false_when_payment_method_present(self) -> None:
        f = validate_transaction_filter(payment_method="CASH")
        assert f.is_empty is False


# ---------------------------------------------------------------------------
# Plage de dates
# ---------------------------------------------------------------------------


class TestDateRange:
    def test_date_from_only_valid(self) -> None:
        f = validate_transaction_filter(date_from=_DATE_A)
        assert f.date_from == _DATE_A
        assert f.date_to is None

    def test_date_to_only_valid(self) -> None:
        f = validate_transaction_filter(date_to=_DATE_B)
        assert f.date_to == _DATE_B
        assert f.date_from is None

    def test_date_from_lt_date_to_valid(self) -> None:
        f = validate_transaction_filter(date_from=_DATE_A, date_to=_DATE_B)
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_B

    def test_date_from_eq_date_to_valid(self) -> None:
        f = validate_transaction_filter(date_from=_DATE_A, date_to=_DATE_A)
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_A

    def test_date_from_gt_date_to_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(date_from=_DATE_B, date_to=_DATE_A)

    def test_date_range_error_message_neutral(self) -> None:
        """Message d'erreur neutre — ne reprend jamais la valeur soumise (§11.3)."""
        with pytest.raises(InvalidTransactionFilter, match="invalide"):
            validate_transaction_filter(date_from=_DATE_B, date_to=_DATE_A)


# ---------------------------------------------------------------------------
# Conversion UTC (Africa/Abidjan = UTC+0)
# ---------------------------------------------------------------------------


class TestUtcConversion:
    def test_created_at_from_is_utc_aware(self) -> None:
        f = validate_transaction_filter(date_from=_DATE_A)
        assert f.created_at_from is not None
        assert f.created_at_from.tzinfo is not None

    def test_created_at_to_is_utc_aware(self) -> None:
        f = validate_transaction_filter(date_to=_DATE_B)
        assert f.created_at_to is not None
        assert f.created_at_to.tzinfo is not None

    def test_created_at_from_is_day_start(self) -> None:
        """Africa/Abidjan = UTC+0 : borne basse = minuit UTC."""
        f = validate_transaction_filter(date_from=_DATE_A)
        expected = datetime.datetime(2026, 3, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        assert f.created_at_from == expected

    def test_created_at_to_is_day_end(self) -> None:
        """Africa/Abidjan = UTC+0 : borne haute = 23:59:59.999999 UTC."""
        f = validate_transaction_filter(date_to=_DATE_B)
        expected = datetime.datetime(
            2026, 3, 31, 23, 59, 59, 999999, tzinfo=datetime.timezone.utc
        )
        assert f.created_at_to == expected

    def test_no_date_no_utc_bounds(self) -> None:
        f = validate_transaction_filter()
        assert f.created_at_from is None
        assert f.created_at_to is None

    def test_salon_timezone_is_abidjan(self) -> None:
        assert str(SALON_TIMEZONE) == "Africa/Abidjan"


# ---------------------------------------------------------------------------
# Bornes de montant
# ---------------------------------------------------------------------------


class TestAmountBounds:
    def test_amount_min_only_valid(self) -> None:
        f = validate_transaction_filter(amount_min=decimal.Decimal("100.00"))
        assert f.amount_min == decimal.Decimal("100.00")

    def test_amount_max_only_valid(self) -> None:
        f = validate_transaction_filter(amount_max=decimal.Decimal("500.00"))
        assert f.amount_max == decimal.Decimal("500.00")

    def test_amount_min_lt_max_valid(self) -> None:
        f = validate_transaction_filter(
            amount_min=decimal.Decimal("100.00"),
            amount_max=decimal.Decimal("500.00"),
        )
        assert f.amount_min == decimal.Decimal("100.00")
        assert f.amount_max == decimal.Decimal("500.00")

    def test_amount_min_eq_max_valid(self) -> None:
        f = validate_transaction_filter(
            amount_min=decimal.Decimal("500.00"),
            amount_max=decimal.Decimal("500.00"),
        )
        assert f.amount_min == f.amount_max

    def test_amount_min_gt_max_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(
                amount_min=decimal.Decimal("500.00"),
                amount_max=decimal.Decimal("100.00"),
            )

    def test_zero_amount_min_valid(self) -> None:
        f = validate_transaction_filter(amount_min=AMOUNT_MIN)
        assert f.amount_min == AMOUNT_MIN

    def test_amount_max_at_bound_valid(self) -> None:
        f = validate_transaction_filter(amount_max=AMOUNT_MAX)
        assert f.amount_max == AMOUNT_MAX

    def test_negative_amount_min_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_min=decimal.Decimal("-0.01"))

    def test_negative_amount_max_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_max=decimal.Decimal("-1.00"))

    def test_amount_above_max_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_min=AMOUNT_MAX + decimal.Decimal("0.01"))

    def test_too_many_decimal_places_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_min=decimal.Decimal("100.001"))

    def test_integer_amount_accepted(self) -> None:
        """Un `int` est converti en `Decimal` (robustesse à la saisie)."""
        f = validate_transaction_filter(amount_min=1000)
        assert isinstance(f.amount_min, decimal.Decimal)
        assert f.amount_min == decimal.Decimal("1000")

    def test_float_amount_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_min=100.0)  # type: ignore[arg-type]

    def test_boolean_amount_raises(self) -> None:
        """Un booléen est sous-classe de `int` — il doit être refusé explicitement."""
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_min=True)  # type: ignore[arg-type]

    def test_non_finite_amount_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(amount_min=decimal.Decimal("Infinity"))

    def test_amount_error_message_neutral(self) -> None:
        """Message d'erreur neutre — ne reprend pas la valeur soumise (§11.3)."""
        with pytest.raises(InvalidTransactionFilter, match="invalide"):
            validate_transaction_filter(amount_min=decimal.Decimal("-1.00"))


# ---------------------------------------------------------------------------
# Mode de paiement
# ---------------------------------------------------------------------------


class TestPaymentMethod:
    @pytest.mark.parametrize("method", list(PAYMENT_METHOD_VALUES))
    def test_valid_method_accepted(self, method: str) -> None:
        f = validate_transaction_filter(payment_method=method)
        assert f.payment_method == method

    def test_unknown_method_raises(self) -> None:
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(payment_method="WIRE_TRANSFER")

    def test_case_sensitive_rejection(self) -> None:
        """Le mode n'est pas normalisé en majuscules — valeur exacte requise."""
        with pytest.raises(InvalidTransactionFilter):
            validate_transaction_filter(payment_method="cash")

    def test_none_method_no_constraint(self) -> None:
        f = validate_transaction_filter(payment_method=None)
        assert f.payment_method is None

    def test_empty_string_method_becomes_none(self) -> None:
        f = validate_transaction_filter(payment_method="")
        assert f.payment_method is None

    def test_whitespace_only_method_becomes_none(self) -> None:
        f = validate_transaction_filter(payment_method="   ")
        assert f.payment_method is None

    def test_method_error_message_neutral(self) -> None:
        """Message d'erreur neutre — ne reprend pas la valeur soumise (§11.3)."""
        with pytest.raises(InvalidTransactionFilter, match="invalide"):
            validate_transaction_filter(payment_method="UNKNOWN_METHOD")


# ---------------------------------------------------------------------------
# Champ client_id
# ---------------------------------------------------------------------------


class TestClientId:
    def test_client_id_uuid_preserved(self) -> None:
        import uuid

        cid = uuid.uuid4()
        f = validate_transaction_filter(client_id=cid)
        assert f.client_id == cid

    def test_none_client_id_no_constraint(self) -> None:
        f = validate_transaction_filter(client_id=None)
        assert f.client_id is None


# ---------------------------------------------------------------------------
# Combinaison de critères
# ---------------------------------------------------------------------------


class TestCombinedFilter:
    def test_all_criteria_combined(self) -> None:
        import uuid

        cid = uuid.uuid4()
        f = validate_transaction_filter(
            date_from=_DATE_A,
            date_to=_DATE_B,
            client_id=cid,
            amount_min=decimal.Decimal("100.00"),
            amount_max=decimal.Decimal("50000.00"),
            payment_method="MOBILE_MONEY_MANUAL",
        )
        assert f.date_from == _DATE_A
        assert f.date_to == _DATE_B
        assert f.client_id == cid
        assert f.amount_min == decimal.Decimal("100.00")
        assert f.amount_max == decimal.Decimal("50000.00")
        assert f.payment_method == "MOBILE_MONEY_MANUAL"
        assert f.is_empty is False

    def test_combined_filter_not_empty(self) -> None:
        f = validate_transaction_filter(
            date_from=_DATE_A,
            payment_method="CASH",
        )
        assert f.is_empty is False
