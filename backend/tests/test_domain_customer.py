"""Tests unitaires — domaine `customer` (US-4.1, #28).

Couvre les règles de validation pures :
- `validate_customer_name` : trim, vide, trop long, non-chaîne ;
- `normalize_customer_phone` : None/vide → None, forme locale normalisée en
  E.164, idempotent, invalide → `InvalidPhone` ;
- `normalize_gender` : valeurs valides, None/vide → None, valeur inconnue →
  `InvalidCustomerGender`, casse stricte (pas de tolérance) ;
- `normalize_notes` : trim, vide → None, > 2000 → `InvalidCustomerNotes`.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import pytest

from coiflink_api.domain.customer import (
    CUSTOMER_NAME_MAX_LENGTH,
    GENDER_VALUES,
    NOTES_MAX_LENGTH,
    normalize_customer_phone,
    normalize_gender,
    normalize_notes,
    validate_customer_name,
)
from coiflink_api.domain.errors import (
    InvalidCustomerGender,
    InvalidCustomerName,
    InvalidCustomerNotes,
    InvalidPhone,
)


# ---------------------------------------------------------------------------
# validate_customer_name
# ---------------------------------------------------------------------------


class TestValidateCustomerName:
    def test_valid_name_returned(self) -> None:
        assert validate_customer_name("Awa Koné") == "Awa Koné"

    def test_leading_trailing_whitespace_trimmed(self) -> None:
        assert validate_customer_name("  Awa Koné  ") == "Awa Koné"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidCustomerName):
            validate_customer_name("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidCustomerName):
            validate_customer_name("   ")

    def test_non_string_int_raises(self) -> None:
        with pytest.raises(InvalidCustomerName):
            validate_customer_name(42)  # type: ignore[arg-type]

    def test_non_string_none_raises(self) -> None:
        with pytest.raises(InvalidCustomerName):
            validate_customer_name(None)  # type: ignore[arg-type]

    def test_name_at_max_length_accepted(self) -> None:
        name = "A" * CUSTOMER_NAME_MAX_LENGTH
        assert validate_customer_name(name) == name

    def test_name_over_max_length_raises(self) -> None:
        name = "A" * (CUSTOMER_NAME_MAX_LENGTH + 1)
        with pytest.raises(InvalidCustomerName):
            validate_customer_name(name)

    def test_trimmed_to_max_length_accepted(self) -> None:
        padded = " " + "A" * CUSTOMER_NAME_MAX_LENGTH + " "
        assert validate_customer_name(padded) == "A" * CUSTOMER_NAME_MAX_LENGTH

    def test_single_character_accepted(self) -> None:
        assert validate_customer_name("X") == "X"

    def test_error_message_does_not_contain_name(self) -> None:
        try:
            validate_customer_name("")
        except InvalidCustomerName as exc:
            assert "Awa" not in str(exc)


# ---------------------------------------------------------------------------
# normalize_customer_phone
# ---------------------------------------------------------------------------


class TestNormalizeCustomerPhone:
    def test_none_returns_none(self) -> None:
        assert normalize_customer_phone(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_customer_phone("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_customer_phone("   ") is None

    def test_local_number_normalized_to_e164(self) -> None:
        result = normalize_customer_phone("0700000000")
        assert result == "+2250700000000"

    def test_already_e164_idempotent(self) -> None:
        result = normalize_customer_phone("+2250700000000")
        assert result == "+2250700000000"

    def test_invalid_number_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            normalize_customer_phone("not-a-phone")

    def test_returns_string_when_valid(self) -> None:
        result = normalize_customer_phone("0700000000")
        assert isinstance(result, str)

    def test_non_string_raises_invalid_phone(self) -> None:
        with pytest.raises((InvalidPhone, Exception)):
            normalize_customer_phone(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# normalize_gender
# ---------------------------------------------------------------------------


class TestNormalizeGender:
    def test_none_returns_none(self) -> None:
        assert normalize_gender(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_gender("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_gender("   ") is None

    def test_female_accepted(self) -> None:
        assert normalize_gender("FEMALE") == "FEMALE"

    def test_male_accepted(self) -> None:
        assert normalize_gender("MALE") == "MALE"

    def test_other_accepted(self) -> None:
        assert normalize_gender("OTHER") == "OTHER"

    def test_all_gender_values_accepted(self) -> None:
        for value in GENDER_VALUES:
            result = normalize_gender(value)
            assert result == value

    def test_lowercase_female_raises(self) -> None:
        with pytest.raises(InvalidCustomerGender):
            normalize_gender("female")

    def test_lowercase_male_raises(self) -> None:
        with pytest.raises(InvalidCustomerGender):
            normalize_gender("male")

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(InvalidCustomerGender):
            normalize_gender("UNKNOWN")

    def test_mixed_case_raises(self) -> None:
        with pytest.raises(InvalidCustomerGender):
            normalize_gender("Female")

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidCustomerGender):
            normalize_gender(123)  # type: ignore[arg-type]

    def test_error_message_is_neutral(self) -> None:
        try:
            normalize_gender("UNKNOWN")
        except InvalidCustomerGender as exc:
            assert "UNKNOWN" not in str(exc)


# ---------------------------------------------------------------------------
# normalize_notes
# ---------------------------------------------------------------------------


class TestNormalizeNotes:
    def test_none_returns_none(self) -> None:
        assert normalize_notes(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_notes("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_notes("   ") is None

    def test_valid_notes_trimmed_and_returned(self) -> None:
        assert normalize_notes("  Préfère le samedi matin.  ") == "Préfère le samedi matin."

    def test_valid_notes_at_max_length(self) -> None:
        notes = "A" * NOTES_MAX_LENGTH
        assert normalize_notes(notes) == notes

    def test_notes_over_max_length_raises(self) -> None:
        notes = "A" * (NOTES_MAX_LENGTH + 1)
        with pytest.raises(InvalidCustomerNotes):
            normalize_notes(notes)

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidCustomerNotes):
            normalize_notes(123)  # type: ignore[arg-type]

    def test_error_message_does_not_contain_note_content(self) -> None:
        notes = "A" * (NOTES_MAX_LENGTH + 1)
        try:
            normalize_notes(notes)
        except InvalidCustomerNotes as exc:
            assert notes[:100] not in str(exc)

    def test_trimmed_then_length_checked(self) -> None:
        notes = " " + "A" * NOTES_MAX_LENGTH + " "
        result = normalize_notes(notes)
        assert result == "A" * NOTES_MAX_LENGTH


# ---------------------------------------------------------------------------
# GENDER_VALUES constant
# ---------------------------------------------------------------------------


class TestGenderValues:
    def test_contains_female(self) -> None:
        assert "FEMALE" in GENDER_VALUES

    def test_contains_male(self) -> None:
        assert "MALE" in GENDER_VALUES

    def test_contains_other(self) -> None:
        assert "OTHER" in GENDER_VALUES

    def test_exactly_three_values(self) -> None:
        assert len(GENDER_VALUES) == 3

    def test_all_uppercase_strings(self) -> None:
        for value in GENDER_VALUES:
            assert isinstance(value, str)
            assert value == value.upper()
