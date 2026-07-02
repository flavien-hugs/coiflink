"""Tests unitaires pour `normalize_phone` (domaine, #8).

Couvre : normalisation E.164, idempotence, séparateurs tolérés,
préfixe 00→+, rejet des invalides. Ces tests sont purs (stdlib seule).
"""

from __future__ import annotations

import pytest

from coiflink_api.domain.errors import InvalidPhone
from coiflink_api.domain.phone import DEFAULT_COUNTRY_CODE, normalize_phone


class TestE164Normalization:
    def test_local_number_prefixed_with_default_country_code(self) -> None:
        result = normalize_phone("0700000000")
        assert result == "+2250700000000"

    def test_number_with_plus_unchanged(self) -> None:
        assert normalize_phone("+2250700000000") == "+2250700000000"

    def test_00_prefix_converted_to_plus(self) -> None:
        assert normalize_phone("002250700000000") == "+2250700000000"

    def test_international_number_other_country(self) -> None:
        result = normalize_phone("+33612345678")
        assert result == "+33612345678"

    def test_default_country_code_is_cote_d_ivoire(self) -> None:
        assert DEFAULT_COUNTRY_CODE == "225"

    def test_custom_country_code(self) -> None:
        result = normalize_phone("612345678", country_code="33")
        assert result == "+33612345678"


class TestIdempotence:
    def test_idempotence_local_number(self) -> None:
        first = normalize_phone("0700000000")
        second = normalize_phone(first)
        assert first == second

    def test_idempotence_international_number(self) -> None:
        first = normalize_phone("+2250700000000")
        assert normalize_phone(first) == first

    def test_local_zero_and_e164_same_canonical_form(self) -> None:
        """0700000000 et +2250700000000 → même forme → doublon détectable."""
        form1 = normalize_phone("0700000000")
        form2 = normalize_phone("+2250700000000")
        assert form1 == form2

    def test_00_and_plus_same_canonical_form(self) -> None:
        form1 = normalize_phone("002250700000000")
        form2 = normalize_phone("+2250700000000")
        assert form1 == form2


class TestToleratedSeparators:
    def test_spaces_removed(self) -> None:
        assert normalize_phone("07 00 00 00 00") == "+2250700000000"

    def test_dashes_removed(self) -> None:
        assert normalize_phone("07-00-00-00-00") == "+2250700000000"

    def test_dots_removed(self) -> None:
        assert normalize_phone("07.00.00.00.00") == "+2250700000000"

    def test_parentheses_removed(self) -> None:
        assert normalize_phone("(07)00000000") == "+225(07)00000000".replace("(", "").replace(")", "")

    def test_mixed_separators(self) -> None:
        assert normalize_phone("+225 07 00 00 00 00") == "+2250700000000"

    def test_leading_trailing_spaces(self) -> None:
        assert normalize_phone("  0700000000  ") == "+2250700000000"


class TestInvalidRejections:
    def test_empty_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            normalize_phone("")

    def test_spaces_only_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            normalize_phone("   ")

    def test_letters_in_number_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            normalize_phone("07abc00000")

    def test_too_short_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            normalize_phone("123")

    def test_too_long_raises_invalid_phone(self) -> None:
        # 16 chiffres (sans indicatif) → dépasse la borne E.164 de 15
        with pytest.raises(InvalidPhone):
            normalize_phone("+1234567890123456")

    def test_non_string_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            normalize_phone(700000000)  # type: ignore[arg-type]

    def test_error_message_does_not_contain_number(self) -> None:
        secret_number = "abc123"
        try:
            normalize_phone(secret_number)
        except InvalidPhone as exc:
            assert secret_number not in str(exc)

    def test_output_starts_with_plus(self) -> None:
        assert normalize_phone("0700000000").startswith("+")

    def test_output_only_digits_after_plus(self) -> None:
        result = normalize_phone("0700000000")
        assert result[1:].isdigit()
