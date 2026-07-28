"""Tests unitaires — domaine `cash_journal` (US-5.3, #34).

Couvre :
- `validate_adjustment_amount` : None/bool/non-Decimal refusés ; zéro refusé ;
  négatif autorisé (delta signé) ; entier converti ; hors borne refusé ; borne
  exacte acceptée ; plus de deux décimales refusé ; non-fini refusé ;
  message d'erreur neutre (pas de valeur).
- `normalize_description` : None → None ; chaîne vide/espaces → None ; trim ;
  non-chaîne → None ; troncature à `DESCRIPTION_MAX_LENGTH`.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import decimal

import pytest

from coiflink_api.domain.cash_journal import (
    ADJUSTMENT_ABS_MAX,
    DESCRIPTION_MAX_LENGTH,
    normalize_description,
    validate_adjustment_amount,
)
from coiflink_api.domain.errors import InvalidAdjustment


# ---------------------------------------------------------------------------
# validate_adjustment_amount
# ---------------------------------------------------------------------------


class TestValidateAdjustmentAmount:
    def test_none_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(None)

    def test_bool_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(True)

    def test_zero_decimal_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(decimal.Decimal("0"))

    def test_zero_int_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(0)

    def test_positive_decimal_valid(self) -> None:
        result = validate_adjustment_amount(decimal.Decimal("500.00"))
        assert result == decimal.Decimal("500.00")

    def test_negative_decimal_valid(self) -> None:
        """Le delta d'un ajustement peut être négatif (correction à la baisse)."""
        result = validate_adjustment_amount(decimal.Decimal("-500.00"))
        assert result == decimal.Decimal("-500.00")

    def test_integer_coerced_to_decimal(self) -> None:
        result = validate_adjustment_amount(100)
        assert isinstance(result, decimal.Decimal)
        assert result == decimal.Decimal("100")

    def test_above_max_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(ADJUSTMENT_ABS_MAX + decimal.Decimal("0.01"))

    def test_below_negative_max_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(-(ADJUSTMENT_ABS_MAX + decimal.Decimal("0.01")))

    def test_exactly_max_is_valid(self) -> None:
        result = validate_adjustment_amount(ADJUSTMENT_ABS_MAX)
        assert result == ADJUSTMENT_ABS_MAX

    def test_exactly_negative_max_is_valid(self) -> None:
        result = validate_adjustment_amount(-ADJUSTMENT_ABS_MAX)
        assert result == -ADJUSTMENT_ABS_MAX

    def test_three_decimals_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(decimal.Decimal("1.001"))

    def test_two_decimals_valid(self) -> None:
        result = validate_adjustment_amount(decimal.Decimal("1.01"))
        assert result == decimal.Decimal("1.01")

    def test_one_decimal_valid(self) -> None:
        result = validate_adjustment_amount(decimal.Decimal("1.5"))
        assert result == decimal.Decimal("1.5")

    def test_infinity_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(decimal.Decimal("Infinity"))

    def test_nan_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(decimal.Decimal("NaN"))

    def test_string_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount("100")  # type: ignore[arg-type]

    def test_float_raises(self) -> None:
        with pytest.raises(InvalidAdjustment):
            validate_adjustment_amount(1.5)  # type: ignore[arg-type]

    def test_error_message_does_not_contain_value(self) -> None:
        """Le message d'erreur ne reprend jamais la valeur soumise (§11.3)."""
        try:
            validate_adjustment_amount(decimal.Decimal("1.001"))
        except InvalidAdjustment as exc:
            assert "1.001" not in str(exc)

    def test_returns_decimal(self) -> None:
        result = validate_adjustment_amount(decimal.Decimal("200.00"))
        assert isinstance(result, decimal.Decimal)


# ---------------------------------------------------------------------------
# normalize_description
# ---------------------------------------------------------------------------


class TestNormalizeDescription:
    def test_none_returns_none(self) -> None:
        assert normalize_description(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_description("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_description("   ") is None

    def test_strips_leading_and_trailing_whitespace(self) -> None:
        assert normalize_description("  correction  ") == "correction"

    def test_non_string_int_returns_none(self) -> None:
        assert normalize_description(123) is None  # type: ignore[arg-type]

    def test_non_string_list_returns_none(self) -> None:
        assert normalize_description([])  is None  # type: ignore[arg-type]

    def test_long_string_truncated_to_max_length(self) -> None:
        long = "a" * (DESCRIPTION_MAX_LENGTH + 50)
        result = normalize_description(long)
        assert result is not None
        assert len(result) == DESCRIPTION_MAX_LENGTH

    def test_string_at_exact_max_length_not_truncated(self) -> None:
        s = "x" * DESCRIPTION_MAX_LENGTH
        result = normalize_description(s)
        assert result == s

    def test_normal_description_preserved(self) -> None:
        msg = "Erreur de saisie du montant"
        assert normalize_description(msg) == msg

    def test_description_max_length_is_positive(self) -> None:
        assert DESCRIPTION_MAX_LENGTH > 0
