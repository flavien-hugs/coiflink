"""Tests unitaires — domaine `service` (US-2.3, #17).

Couvre les règles de validation pures :
- `validate_service_name` : trim, vide, trop long, non-chaîne ;
- `validate_price` : requis, None/bool/float refusés, négatif, hors borne, > 2 décimales ;
- `validate_duration` : requis, None/bool/float refusés, 0, négatif, > 24 h ;
- `normalize_category` : None/vide → None, trop longue, trim, non-chaîne ;
- `normalize_description` : None/vide → None, trim ;
- `validate_service_filter`/`ServiceFilter` : trim `q`, catégorie texte libre exacte,
  plage de dates incohérente, message neutre, `is_empty`.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import datetime
import decimal

import pytest

from coiflink_api.domain.errors import (
    InvalidServiceCategory,
    InvalidServiceDuration,
    InvalidServiceFilter,
    InvalidServiceName,
    InvalidServicePrice,
)
from coiflink_api.domain.service import (
    CATEGORY_MAX_LENGTH,
    SERVICE_NAME_MAX_LENGTH,
    ServiceFilter,
    _DURATION_MAX_MINUTES,
    _PRICE_MAX,
    normalize_category,
    normalize_description,
    validate_duration,
    validate_price,
    validate_service_filter,
    validate_service_name,
)


# ---------------------------------------------------------------------------
# validate_service_name
# ---------------------------------------------------------------------------


class TestValidateServiceName:
    def test_valid_name_returned(self) -> None:
        assert validate_service_name("Coupe homme") == "Coupe homme"

    def test_leading_trailing_whitespace_trimmed(self) -> None:
        assert validate_service_name("  Coupe homme  ") == "Coupe homme"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidServiceName):
            validate_service_name("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidServiceName):
            validate_service_name("   ")

    def test_non_string_int_raises(self) -> None:
        with pytest.raises(InvalidServiceName):
            validate_service_name(42)  # type: ignore[arg-type]

    def test_non_string_none_raises(self) -> None:
        with pytest.raises(InvalidServiceName):
            validate_service_name(None)  # type: ignore[arg-type]

    def test_name_at_max_length_accepted(self) -> None:
        name = "A" * SERVICE_NAME_MAX_LENGTH
        assert validate_service_name(name) == name

    def test_name_over_max_length_raises(self) -> None:
        name = "A" * (SERVICE_NAME_MAX_LENGTH + 1)
        with pytest.raises(InvalidServiceName):
            validate_service_name(name)

    def test_name_trimmed_then_length_checked(self) -> None:
        padded = " " + "A" * SERVICE_NAME_MAX_LENGTH + " "
        assert validate_service_name(padded) == "A" * SERVICE_NAME_MAX_LENGTH

    def test_single_character_name_accepted(self) -> None:
        assert validate_service_name("X") == "X"


# ---------------------------------------------------------------------------
# validate_price
# ---------------------------------------------------------------------------


class TestValidatePrice:
    def test_none_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(None)  # type: ignore[arg-type]

    def test_true_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(True)  # type: ignore[arg-type]

    def test_false_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(False)  # type: ignore[arg-type]

    def test_float_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(5.0)  # type: ignore[arg-type]

    def test_string_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price("5000.00")  # type: ignore[arg-type]

    def test_negative_decimal_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(decimal.Decimal("-0.01"))

    def test_zero_accepted(self) -> None:
        result = validate_price(decimal.Decimal("0"))
        assert result == decimal.Decimal("0")

    def test_zero_decimal_form_accepted(self) -> None:
        result = validate_price(decimal.Decimal("0.00"))
        assert result == decimal.Decimal("0.00")

    def test_valid_price_returned(self) -> None:
        result = validate_price(decimal.Decimal("5000.00"))
        assert result == decimal.Decimal("5000.00")

    def test_price_at_max_accepted(self) -> None:
        result = validate_price(_PRICE_MAX)
        assert result == _PRICE_MAX

    def test_price_over_max_raises(self) -> None:
        over = _PRICE_MAX + decimal.Decimal("0.01")
        with pytest.raises(InvalidServicePrice):
            validate_price(over)

    def test_more_than_two_decimals_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(decimal.Decimal("5.123"))

    def test_exactly_two_decimals_accepted(self) -> None:
        result = validate_price(decimal.Decimal("5.12"))
        assert result == decimal.Decimal("5.12")

    def test_one_decimal_accepted(self) -> None:
        result = validate_price(decimal.Decimal("5.1"))
        assert result == decimal.Decimal("5.1")

    def test_infinity_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(decimal.Decimal("Infinity"))

    def test_nan_raises(self) -> None:
        with pytest.raises(InvalidServicePrice):
            validate_price(decimal.Decimal("NaN"))

    def test_integer_input_accepted_and_converted(self) -> None:
        result = validate_price(100)
        assert result == decimal.Decimal(100)

    def test_integer_zero_accepted(self) -> None:
        result = validate_price(0)
        assert result == decimal.Decimal(0)

    def test_returned_type_is_decimal(self) -> None:
        result = validate_price(decimal.Decimal("50"))
        assert isinstance(result, decimal.Decimal)


# ---------------------------------------------------------------------------
# validate_duration
# ---------------------------------------------------------------------------


class TestValidateDuration:
    def test_none_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(None)  # type: ignore[arg-type]

    def test_true_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(True)  # type: ignore[arg-type]

    def test_false_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(False)  # type: ignore[arg-type]

    def test_float_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(30.0)  # type: ignore[arg-type]

    def test_string_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration("30")  # type: ignore[arg-type]

    def test_zero_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(0)

    def test_negative_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(-1)

    def test_valid_duration_returned(self) -> None:
        assert validate_duration(30) == 30

    def test_one_minute_accepted(self) -> None:
        assert validate_duration(1) == 1

    def test_max_duration_accepted(self) -> None:
        assert validate_duration(_DURATION_MAX_MINUTES) == _DURATION_MAX_MINUTES

    def test_over_max_raises(self) -> None:
        with pytest.raises(InvalidServiceDuration):
            validate_duration(_DURATION_MAX_MINUTES + 1)

    def test_returned_type_is_int(self) -> None:
        result = validate_duration(60)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# normalize_category
# ---------------------------------------------------------------------------


class TestNormalizeCategory:
    def test_none_returns_none(self) -> None:
        assert normalize_category(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_category("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_category("   ") is None

    def test_valid_category_returned(self) -> None:
        assert normalize_category("Coupe") == "Coupe"

    def test_whitespace_trimmed(self) -> None:
        assert normalize_category("  Coupe  ") == "Coupe"

    def test_non_string_int_raises(self) -> None:
        with pytest.raises(InvalidServiceCategory):
            normalize_category(42)  # type: ignore[arg-type]

    def test_category_at_max_length_accepted(self) -> None:
        cat = "A" * CATEGORY_MAX_LENGTH
        assert normalize_category(cat) == cat

    def test_category_over_max_length_raises(self) -> None:
        cat = "A" * (CATEGORY_MAX_LENGTH + 1)
        with pytest.raises(InvalidServiceCategory):
            normalize_category(cat)

    def test_trimmed_category_length_checked(self) -> None:
        padded = " " + "A" * CATEGORY_MAX_LENGTH + " "
        assert normalize_category(padded) == "A" * CATEGORY_MAX_LENGTH


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

    def test_valid_description_returned(self) -> None:
        assert normalize_description("Coupe aux ciseaux.") == "Coupe aux ciseaux."

    def test_whitespace_trimmed(self) -> None:
        assert normalize_description("  Coupe.  ") == "Coupe."


# ---------------------------------------------------------------------------
# ServiceFilter.is_empty
# ---------------------------------------------------------------------------


class TestServiceFilterIsEmpty:
    def test_default_filter_is_empty(self) -> None:
        assert ServiceFilter().is_empty is True

    def test_filter_with_q_is_not_empty(self) -> None:
        assert ServiceFilter(q="coupe").is_empty is False

    def test_filter_with_category_is_not_empty(self) -> None:
        assert ServiceFilter(category="Coupe").is_empty is False

    def test_filter_with_created_from_is_not_empty(self) -> None:
        assert ServiceFilter(created_from=datetime.date(2026, 1, 1)).is_empty is False

    def test_filter_with_created_to_is_not_empty(self) -> None:
        assert ServiceFilter(created_to=datetime.date(2026, 1, 1)).is_empty is False


# ---------------------------------------------------------------------------
# validate_service_filter — q
# ---------------------------------------------------------------------------


class TestQFilter:
    def test_none_returns_none(self) -> None:
        assert validate_service_filter(q=None).q is None

    def test_empty_string_returns_none(self) -> None:
        assert validate_service_filter(q="").q is None

    def test_whitespace_only_returns_none(self) -> None:
        assert validate_service_filter(q="   ").q is None

    def test_value_is_trimmed(self) -> None:
        assert validate_service_filter(q="  coupe  ").q == "coupe"

    def test_valid_value_returned_as_is(self) -> None:
        assert validate_service_filter(q="coupe").q == "coupe"


# ---------------------------------------------------------------------------
# validate_service_filter — category (texte libre, égalité exacte)
# ---------------------------------------------------------------------------


class TestCategoryFilter:
    def test_none_returns_none(self) -> None:
        assert validate_service_filter(category=None).category is None

    def test_empty_string_returns_none(self) -> None:
        assert validate_service_filter(category="").category is None

    def test_whitespace_only_returns_none(self) -> None:
        assert validate_service_filter(category="   ").category is None

    def test_value_is_trimmed(self) -> None:
        assert validate_service_filter(category="  Coupe  ").category == "Coupe"

    def test_any_free_text_value_accepted(self) -> None:
        """Contrairement au genre des fiches clients, aucune énumération fermée."""
        assert validate_service_filter(category="Nimporte quoi").category == "Nimporte quoi"

    def test_case_is_preserved_not_normalized(self) -> None:
        assert validate_service_filter(category="coupe").category == "coupe"


# ---------------------------------------------------------------------------
# validate_service_filter — plage de dates de création
# ---------------------------------------------------------------------------


class TestCreatedRangeFilter:
    def test_no_bounds_returns_none_bounds(self) -> None:
        result = validate_service_filter()
        assert result.created_from is None
        assert result.created_to is None
        assert result.created_at_from is None
        assert result.created_at_to is None

    def test_created_from_alone_accepted(self) -> None:
        result = validate_service_filter(created_from=datetime.date(2026, 1, 1))
        assert result.created_from == datetime.date(2026, 1, 1)
        assert result.created_at_from is not None
        assert result.created_at_to is None

    def test_created_to_alone_accepted(self) -> None:
        result = validate_service_filter(created_to=datetime.date(2026, 1, 31))
        assert result.created_to == datetime.date(2026, 1, 31)
        assert result.created_at_to is not None

    def test_equal_bounds_accepted(self) -> None:
        day = datetime.date(2026, 3, 15)
        result = validate_service_filter(created_from=day, created_to=day)
        assert result.created_from == day
        assert result.created_to == day

    def test_ordered_range_accepted(self) -> None:
        result = validate_service_filter(
            created_from=datetime.date(2026, 3, 1), created_to=datetime.date(2026, 3, 31)
        )
        assert result.created_from == datetime.date(2026, 3, 1)
        assert result.created_to == datetime.date(2026, 3, 31)

    def test_created_from_after_created_to_raises(self) -> None:
        with pytest.raises(InvalidServiceFilter):
            validate_service_filter(
                created_from=datetime.date(2026, 3, 31), created_to=datetime.date(2026, 3, 1)
            )

    def test_bounds_converted_to_utc_datetimes(self) -> None:
        result = validate_service_filter(
            created_from=datetime.date(2026, 3, 1), created_to=datetime.date(2026, 3, 1)
        )
        assert isinstance(result.created_at_from, datetime.datetime)
        assert isinstance(result.created_at_to, datetime.datetime)
        assert result.created_at_from < result.created_at_to


# ---------------------------------------------------------------------------
# validate_service_filter — message neutre (§11.3)
# ---------------------------------------------------------------------------


class TestServiceFilterNeutralMessage:
    def test_invalid_range_message_does_not_repeat_dates(self) -> None:
        try:
            validate_service_filter(
                created_from=datetime.date(2026, 3, 31), created_to=datetime.date(2026, 3, 1)
            )
        except InvalidServiceFilter as exc:
            assert "2026-03-31" not in str(exc)
            assert "2026-03-01" not in str(exc)
        else:
            pytest.fail("InvalidServiceFilter attendue")
