"""Tests unitaires — domaine `payment` (US-5.1/5.3, #33/#34).

Couvre :
- `validate_amount` : None/bool refusés ; zéro accepté ; positif accepté ;
  négatif refusé ; hors borne refusé ; borne exacte acceptée ; plus de deux
  décimales refusé ; non-fini refusé ; entier converti ; message neutre.
- `validate_payment_method` : None/vide/inconnu refusés ; sensible à la casse ;
  toutes les valeurs valides de l'enum acceptées.
- `validate_currency` : None/vide → `DEFAULT_CURRENCY` ; devise conforme acceptée ;
  devise différente ou non-string refusée (MVP mono-devise).
- `normalize_reference` : None → None ; vide/espaces → None ; trim ; troncature.
- `require_reference_present` : prestation et ticket absents → erreur ; l'un ou
  l'autre présent → OK ; les deux présents → OK.
- `validate_mobile_money_phone` : autre mode → toujours `None` (même si fourni) ;
  Mobile Money sans téléphone → erreur ; Mobile Money avec téléphone → normalisé
  E.164 ; format invalide → `InvalidPhone`.
- `require_mobile_money_reference` : Mobile Money sans référence → erreur ; avec
  référence → OK ; autre mode sans référence → OK.
- `validate_amount_matches` : égalité stricte au centime ; message neutre (§11.3).
- `expected_amount_for_prices` : somme vide → 0.00 ; somme simple ; somme multiple ;
  résultat quantifié ; retour `Decimal`.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import decimal
import uuid

import pytest

from coiflink_api.domain.errors import (
    InvalidPaymentAmount,
    InvalidPaymentCurrency,
    InvalidPaymentMethod,
    InvalidPhone,
    MobileMoneyPhoneRequired,
    MobileMoneyReferenceRequired,
    PaymentAmountMismatch,
    PaymentReferenceRequired,
)
from coiflink_api.domain.payment import (
    AMOUNT_MAX,
    AMOUNT_MIN,
    DEFAULT_CURRENCY,
    PAYMENT_METHOD_VALUES,
    REFERENCE_MAX_LENGTH,
    expected_amount_for_prices,
    normalize_reference,
    require_mobile_money_reference,
    require_reference_present,
    validate_amount,
    validate_amount_matches,
    validate_currency,
    validate_mobile_money_phone,
    validate_payment_method,
)


# ---------------------------------------------------------------------------
# validate_amount
# ---------------------------------------------------------------------------


class TestValidateAmount:
    def test_none_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(None)

    def test_bool_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(True)

    def test_zero_valid(self) -> None:
        result = validate_amount(decimal.Decimal("0.00"))
        assert result == decimal.Decimal("0")

    def test_positive_valid(self) -> None:
        result = validate_amount(decimal.Decimal("5000.00"))
        assert result == decimal.Decimal("5000.00")

    def test_negative_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(decimal.Decimal("-0.01"))

    def test_above_max_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(AMOUNT_MAX + decimal.Decimal("0.01"))

    def test_exactly_max_valid(self) -> None:
        result = validate_amount(AMOUNT_MAX)
        assert result == AMOUNT_MAX

    def test_exactly_min_valid(self) -> None:
        result = validate_amount(AMOUNT_MIN)
        assert result == AMOUNT_MIN

    def test_three_decimals_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(decimal.Decimal("1.001"))

    def test_two_decimals_valid(self) -> None:
        result = validate_amount(decimal.Decimal("1.01"))
        assert result == decimal.Decimal("1.01")

    def test_integer_coerced_to_decimal(self) -> None:
        result = validate_amount(1000)
        assert isinstance(result, decimal.Decimal)
        assert result == decimal.Decimal("1000")

    def test_infinity_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(decimal.Decimal("Infinity"))

    def test_nan_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(decimal.Decimal("NaN"))

    def test_string_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount("100")  # type: ignore[arg-type]

    def test_float_raises(self) -> None:
        with pytest.raises(InvalidPaymentAmount):
            validate_amount(1.5)  # type: ignore[arg-type]

    def test_error_message_does_not_contain_value(self) -> None:
        """Le message d'erreur ne reprend jamais le montant soumis (§11.3)."""
        try:
            validate_amount(decimal.Decimal("-9999.00"))
        except InvalidPaymentAmount as exc:
            assert "9999" not in str(exc)

    def test_returns_decimal(self) -> None:
        result = validate_amount(decimal.Decimal("100.00"))
        assert isinstance(result, decimal.Decimal)


# ---------------------------------------------------------------------------
# validate_payment_method
# ---------------------------------------------------------------------------


class TestValidatePaymentMethod:
    def test_none_raises(self) -> None:
        with pytest.raises(InvalidPaymentMethod):
            validate_payment_method(None)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidPaymentMethod):
            validate_payment_method("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidPaymentMethod):
            validate_payment_method("   ")

    def test_unknown_method_raises(self) -> None:
        with pytest.raises(InvalidPaymentMethod):
            validate_payment_method("CRYPTO")

    def test_all_valid_methods_accepted(self) -> None:
        for method in PAYMENT_METHOD_VALUES:
            result = validate_payment_method(method)
            assert result == method

    def test_case_sensitive_lowercase_raises(self) -> None:
        """La comparaison porte sur la valeur exacte — pas de correction de casse."""
        with pytest.raises(InvalidPaymentMethod):
            validate_payment_method("cash")

    def test_at_least_one_valid_method_exists(self) -> None:
        assert len(PAYMENT_METHOD_VALUES) > 0

    def test_returns_string(self) -> None:
        result = validate_payment_method(PAYMENT_METHOD_VALUES[0])
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# validate_currency
# ---------------------------------------------------------------------------


class TestValidateCurrency:
    def test_none_defaults_to_default_currency(self) -> None:
        assert validate_currency(None) == DEFAULT_CURRENCY

    def test_empty_string_defaults_to_default_currency(self) -> None:
        assert validate_currency("") == DEFAULT_CURRENCY

    def test_whitespace_only_defaults_to_default_currency(self) -> None:
        assert validate_currency("   ") == DEFAULT_CURRENCY

    def test_default_currency_accepted(self) -> None:
        assert validate_currency(DEFAULT_CURRENCY) == DEFAULT_CURRENCY

    def test_different_currency_raises(self) -> None:
        with pytest.raises(InvalidPaymentCurrency):
            validate_currency("USD")

    def test_lowercase_variant_raises(self) -> None:
        """La comparaison porte sur la valeur exacte — pas de correction de casse."""
        with pytest.raises(InvalidPaymentCurrency):
            validate_currency("xof")

    def test_oversized_value_raises(self) -> None:
        """Refusé en amont plutôt que de violer la colonne `String(3)` (500)."""
        with pytest.raises(InvalidPaymentCurrency):
            validate_currency("EURO")

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidPaymentCurrency):
            validate_currency(123)  # type: ignore[arg-type]

    def test_returns_string(self) -> None:
        result = validate_currency(DEFAULT_CURRENCY)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# normalize_reference
# ---------------------------------------------------------------------------


class TestNormalizeReference:
    def test_none_returns_none(self) -> None:
        assert normalize_reference(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_reference("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_reference("   ") is None

    def test_strips_whitespace(self) -> None:
        assert normalize_reference("  REC-001  ") == "REC-001"

    def test_long_string_truncated(self) -> None:
        long = "x" * (REFERENCE_MAX_LENGTH + 10)
        result = normalize_reference(long)
        assert result is not None
        assert len(result) == REFERENCE_MAX_LENGTH

    def test_string_at_exact_max_not_truncated(self) -> None:
        s = "x" * REFERENCE_MAX_LENGTH
        assert normalize_reference(s) == s

    def test_normal_reference_preserved(self) -> None:
        assert normalize_reference("REC-2026-0001") == "REC-2026-0001"

    def test_non_string_returns_none(self) -> None:
        assert normalize_reference(42) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# require_reference_present
# ---------------------------------------------------------------------------


class TestRequireReferencePresent:
    def test_both_none_raises(self) -> None:
        with pytest.raises(PaymentReferenceRequired):
            require_reference_present(None, None)

    def test_service_id_present_passes(self) -> None:
        require_reference_present(uuid.uuid4(), None)

    def test_queue_ticket_id_present_passes(self) -> None:
        require_reference_present(None, uuid.uuid4())

    def test_both_present_passes(self) -> None:
        require_reference_present(uuid.uuid4(), uuid.uuid4())

    def test_error_is_payment_reference_required(self) -> None:
        with pytest.raises(PaymentReferenceRequired):
            require_reference_present(None, None)


# ---------------------------------------------------------------------------
# validate_mobile_money_phone
# ---------------------------------------------------------------------------


class TestValidateMobileMoneyPhone:
    def test_other_method_returns_none_even_if_phone_provided(self) -> None:
        assert validate_mobile_money_phone("CASH", "0700000000") is None

    def test_other_method_with_no_phone_returns_none(self) -> None:
        assert validate_mobile_money_phone("CARD_MANUAL", None) is None

    def test_mobile_money_without_phone_raises(self) -> None:
        with pytest.raises(MobileMoneyPhoneRequired):
            validate_mobile_money_phone("MOBILE_MONEY_MANUAL", None)

    def test_mobile_money_with_blank_phone_raises(self) -> None:
        with pytest.raises(MobileMoneyPhoneRequired):
            validate_mobile_money_phone("MOBILE_MONEY_MANUAL", "   ")

    def test_mobile_money_with_valid_phone_normalizes_to_e164(self) -> None:
        assert (
            validate_mobile_money_phone("MOBILE_MONEY_MANUAL", "0700000000")
            == "+2250700000000"
        )

    def test_mobile_money_with_already_international_phone_is_idempotent(self) -> None:
        assert (
            validate_mobile_money_phone("MOBILE_MONEY_MANUAL", "+2250700000000")
            == "+2250700000000"
        )

    def test_mobile_money_with_malformed_phone_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            validate_mobile_money_phone("MOBILE_MONEY_MANUAL", "not-a-phone")


# ---------------------------------------------------------------------------
# require_mobile_money_reference
# ---------------------------------------------------------------------------


class TestRequireMobileMoneyReference:
    def test_mobile_money_without_reference_raises(self) -> None:
        with pytest.raises(MobileMoneyReferenceRequired):
            require_mobile_money_reference("MOBILE_MONEY_MANUAL", None)

    def test_mobile_money_with_reference_passes(self) -> None:
        require_mobile_money_reference("MOBILE_MONEY_MANUAL", "MM-TX-0001")

    def test_other_method_without_reference_passes(self) -> None:
        require_mobile_money_reference("CASH", None)

    def test_other_method_with_reference_passes(self) -> None:
        require_mobile_money_reference("CARD_MANUAL", "REC-0001")


# ---------------------------------------------------------------------------
# validate_amount_matches
# ---------------------------------------------------------------------------


class TestValidateAmountMatches:
    def test_equal_amounts_passes(self) -> None:
        validate_amount_matches(decimal.Decimal("5000.00"), decimal.Decimal("5000.00"))

    def test_different_quantization_equal_value_passes(self) -> None:
        """5000 et 5000.00 sont identiques au centime près."""
        validate_amount_matches(decimal.Decimal("5000"), decimal.Decimal("5000.00"))

    def test_different_amounts_raises(self) -> None:
        with pytest.raises(PaymentAmountMismatch):
            validate_amount_matches(decimal.Decimal("5001.00"), decimal.Decimal("5000.00"))

    def test_one_cent_off_raises(self) -> None:
        """L'égalité est stricte au centime — 0.01 d'écart est refusé."""
        with pytest.raises(PaymentAmountMismatch):
            validate_amount_matches(decimal.Decimal("5000.01"), decimal.Decimal("5000.00"))

    def test_error_type_is_payment_amount_mismatch(self) -> None:
        with pytest.raises(PaymentAmountMismatch):
            validate_amount_matches(decimal.Decimal("1000.00"), decimal.Decimal("2000.00"))

    def test_error_message_does_not_contain_amounts(self) -> None:
        """Le message d'erreur ne reprend jamais les montants (§11.3)."""
        try:
            validate_amount_matches(decimal.Decimal("1234.00"), decimal.Decimal("5678.00"))
        except PaymentAmountMismatch as exc:
            assert "1234" not in str(exc)
            assert "5678" not in str(exc)

    def test_zero_vs_zero_passes(self) -> None:
        validate_amount_matches(decimal.Decimal("0.00"), decimal.Decimal("0.00"))

    def test_returns_none(self) -> None:
        result = validate_amount_matches(decimal.Decimal("100.00"), decimal.Decimal("100.00"))
        assert result is None


# ---------------------------------------------------------------------------
# expected_amount_for_prices
# ---------------------------------------------------------------------------


class TestExpectedAmountForPrices:
    def test_empty_iterable_returns_zero(self) -> None:
        result = expected_amount_for_prices([])
        assert result == decimal.Decimal("0.00")

    def test_single_price_returned(self) -> None:
        result = expected_amount_for_prices([decimal.Decimal("5000.00")])
        assert result == decimal.Decimal("5000.00")

    def test_multiple_prices_summed(self) -> None:
        result = expected_amount_for_prices([
            decimal.Decimal("2000.00"),
            decimal.Decimal("3000.00"),
        ])
        assert result == decimal.Decimal("5000.00")

    def test_result_quantized_to_cent(self) -> None:
        """Un prix entier est quantifié à deux décimales (NUMERIC(12,2))."""
        result = expected_amount_for_prices([decimal.Decimal("1000")])
        assert result == decimal.Decimal("1000.00")
        assert result.as_tuple().exponent == -2

    def test_returns_decimal(self) -> None:
        result = expected_amount_for_prices([decimal.Decimal("1000.00")])
        assert isinstance(result, decimal.Decimal)

    def test_tuple_iterable_accepted(self) -> None:
        result = expected_amount_for_prices((decimal.Decimal("1500.00"), decimal.Decimal("500.00")))
        assert result == decimal.Decimal("2000.00")
