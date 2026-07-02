"""Tests unitaires pour `validate_password` (domaine, #8).

Vérifie la politique (longueur min/max), le rejet des entrées vides ou invalides,
et l'invariant de sécurité : le message d'erreur ne contient jamais la valeur du
mot de passe en clair.
"""

from __future__ import annotations

import pytest

from coiflink_api.domain.errors import InvalidPassword
from coiflink_api.domain.password import MAX_LENGTH, MIN_LENGTH, validate_password


class TestLengthPolicy:
    def test_accepts_valid_password(self) -> None:
        validate_password("motdepasse1")  # pas d'exception

    def test_accepts_exactly_min_length(self) -> None:
        validate_password("a" * MIN_LENGTH)

    def test_accepts_exactly_max_length(self) -> None:
        validate_password("a" * MAX_LENGTH)

    def test_accepts_length_between_min_and_max(self) -> None:
        validate_password("securise!")

    def test_rejects_too_short(self) -> None:
        with pytest.raises(InvalidPassword):
            validate_password("a" * (MIN_LENGTH - 1))

    def test_rejects_too_long(self) -> None:
        with pytest.raises(InvalidPassword):
            validate_password("a" * (MAX_LENGTH + 1))

    def test_min_length_is_8(self) -> None:
        assert MIN_LENGTH == 8

    def test_max_length_is_128(self) -> None:
        assert MAX_LENGTH == 128


class TestBasicRejections:
    def test_rejects_empty(self) -> None:
        with pytest.raises(InvalidPassword):
            validate_password("")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(InvalidPassword):
            validate_password(None)  # type: ignore[arg-type]

    def test_rejects_single_character(self) -> None:
        with pytest.raises(InvalidPassword):
            validate_password("x")

    def test_rejects_seven_characters(self) -> None:
        with pytest.raises(InvalidPassword):
            validate_password("abcdefg")


class TestMessageSecurity:
    def test_error_message_does_not_contain_password(self) -> None:
        secret_password = "court1"
        try:
            validate_password(secret_password)
        except InvalidPassword as exc:
            assert secret_password not in str(exc)

    def test_too_long_error_message_does_not_contain_password(self) -> None:
        secret_password = "x" * (MAX_LENGTH + 1)
        try:
            validate_password(secret_password)
        except InvalidPassword as exc:
            assert secret_password not in str(exc)

    def test_returns_none_when_valid(self) -> None:
        result = validate_password("motdepasse-ok")
        assert result is None
