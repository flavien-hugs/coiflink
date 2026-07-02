"""Tests unitaires pour `validate_name` (domaine, #8).

Couvre : normalisation (trim), longueur maximale, rejet des entrées
invalides, invariant de sécurité (message d'erreur sans la valeur saisie).
"""

from __future__ import annotations

import pytest

from coiflink_api.domain.errors import InvalidName
from coiflink_api.domain.user import NAME_MAX_LENGTH, validate_name


class TestValidName:
    def test_simple_name_returned_unchanged(self) -> None:
        assert validate_name("Alice") == "Alice"

    def test_name_with_leading_and_trailing_spaces_trimmed(self) -> None:
        assert validate_name("  Awa Koné  ") == "Awa Koné"

    def test_name_with_accents_accepted(self) -> None:
        assert validate_name("Élodie Müller") == "Élodie Müller"

    def test_single_character_name_accepted(self) -> None:
        assert validate_name("X") == "X"

    def test_name_exactly_max_length_accepted(self) -> None:
        validate_name("a" * NAME_MAX_LENGTH)

    def test_max_length_is_255(self) -> None:
        assert NAME_MAX_LENGTH == 255

    def test_returns_normalized_name_not_original(self) -> None:
        original = "  Kofi  "
        result = validate_name(original)
        assert result == "Kofi"
        assert result != original


class TestInvalidName:
    def test_empty_name_raises_invalid_name(self) -> None:
        with pytest.raises(InvalidName):
            validate_name("")

    def test_whitespace_only_name_raises_invalid_name(self) -> None:
        with pytest.raises(InvalidName):
            validate_name("   ")

    def test_non_string_name_raises_invalid_name(self) -> None:
        with pytest.raises(InvalidName):
            validate_name(None)  # type: ignore[arg-type]

    def test_integer_name_raises_invalid_name(self) -> None:
        with pytest.raises(InvalidName):
            validate_name(42)  # type: ignore[arg-type]

    def test_too_long_name_raises_invalid_name(self) -> None:
        with pytest.raises(InvalidName):
            validate_name("a" * (NAME_MAX_LENGTH + 1))

    def test_length_checked_after_trim(self) -> None:
        """Espaces en tête/queue retirés avant la vérification de longueur."""
        name_short_after_trim = "  " + "a" * NAME_MAX_LENGTH + "  "
        validate_name(name_short_after_trim)  # ne doit pas lever


class TestMessageSecurity:
    def test_too_long_error_message_does_not_contain_name(self) -> None:
        name = "a" * (NAME_MAX_LENGTH + 1)
        try:
            validate_name(name)
        except InvalidName as exc:
            assert name not in str(exc)

    def test_invalid_name_is_subclass_of_domain_error(self) -> None:
        from coiflink_api.domain.errors import DomainError

        with pytest.raises(DomainError):
            validate_name("")
