"""Tests unitaires pour `domain/identifier.py` — classification des identifiants
de connexion (issue #10, US-1.2).

Vérifie que `classify_identifier` distingue e-mail / téléphone, normalise
le numéro en E.164 (cohérence avec l'inscription) et lève `InvalidPhone` sur
un numéro inexploitable.
"""

from __future__ import annotations

import pytest

from coiflink_api.domain.errors import InvalidPhone
from coiflink_api.domain.identifier import EMAIL, PHONE, LoginIdentifier, classify_identifier


class TestEmailClassification:
    def test_simple_email_classified_as_email(self) -> None:
        result = classify_identifier("user@example.com")
        assert result.kind == EMAIL

    def test_email_value_is_stripped(self) -> None:
        result = classify_identifier("  user@example.com  ")
        assert result.value == "user@example.com"

    def test_email_case_preserved(self) -> None:
        """La casse de l'e-mail n'est pas modifiée (cohérence avec l'inscription, ADR-0013)."""
        result = classify_identifier("User@Example.COM")
        assert result.value == "User@Example.COM"

    def test_email_returns_login_identifier_instance(self) -> None:
        result = classify_identifier("a@b.com")
        assert isinstance(result, LoginIdentifier)

    def test_email_with_subaddress_is_email(self) -> None:
        result = classify_identifier("user+tag@example.com")
        assert result.kind == EMAIL

    def test_email_with_subdomain_is_email(self) -> None:
        result = classify_identifier("user@mail.example.com")
        assert result.kind == EMAIL


class TestPhoneClassification:
    def test_local_phone_classified_as_phone(self) -> None:
        result = classify_identifier("0700000000")
        assert result.kind == PHONE

    def test_local_phone_normalized_to_e164(self) -> None:
        result = classify_identifier("0700000000")
        assert result.value == "+2250700000000"

    def test_e164_phone_classified_as_phone(self) -> None:
        result = classify_identifier("+2250700000000")
        assert result.kind == PHONE

    def test_e164_phone_value_is_canonical(self) -> None:
        result = classify_identifier("+2250700000000")
        assert result.value == "+2250700000000"

    def test_local_and_e164_normalize_to_same_value(self) -> None:
        """0700000000 et +2250700000000 doivent pointer le même compte (anti-mismatch)."""
        local = classify_identifier("0700000000")
        e164 = classify_identifier("+2250700000000")
        assert local.value == e164.value

    def test_invalid_phone_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            classify_identifier("notaphone")

    def test_short_digits_raise_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            classify_identifier("000")

    def test_alphabetic_string_without_at_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            classify_identifier("abcdefghij")


class TestLoginIdentifierDataclass:
    def test_login_identifier_is_frozen(self) -> None:
        ident = LoginIdentifier(kind=EMAIL, value="a@b.com")
        with pytest.raises(AttributeError):
            ident.kind = PHONE  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        a = LoginIdentifier(kind=PHONE, value="+2250700000000")
        b = LoginIdentifier(kind=PHONE, value="+2250700000000")
        assert a == b

    def test_different_kind_not_equal(self) -> None:
        a = LoginIdentifier(kind=EMAIL, value="x@x.com")
        b = LoginIdentifier(kind=PHONE, value="x@x.com")
        assert a != b
