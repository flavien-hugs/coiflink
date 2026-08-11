"""Tests unitaires — domaine walk-in kiosque (US-8.2, #156).

Couvre les fonctions et dataclasses ajoutées à `domain/customer.py` pour la borne :
- `walk_in_first_name` : extraction du prénom (premier token de `full_name`) ;
- `WalkInIdentity` : dataclass frozen, champs attendus ;
- `WalkInCustomerCommand` : dataclass frozen, champs requis ;
- `validate_walk_in_customer` : validation/composition complète — prénom, nom,
  composition « Prénom Nom », borne 255, téléphone requis (E.164), formats de
  saisie tactile variés.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.domain.customer import (
    CUSTOMER_NAME_MAX_LENGTH,
    WalkInCustomerCommand,
    WalkInIdentity,
    validate_walk_in_customer,
    walk_in_first_name,
)
from coiflink_api.domain.errors import InvalidCustomerName, InvalidPhone


# ---------------------------------------------------------------------------
# walk_in_first_name
# ---------------------------------------------------------------------------


class TestWalkInFirstName:
    def test_two_token_name_returns_first(self) -> None:
        assert walk_in_first_name("Awa Koné") == "Awa"

    def test_three_token_name_returns_first(self) -> None:
        assert walk_in_first_name("Awa Marie Koné") == "Awa"

    def test_single_token_returns_itself(self) -> None:
        assert walk_in_first_name("Awa") == "Awa"

    def test_extra_spaces_between_tokens_handled(self) -> None:
        # split() consomme les espaces multiples
        assert walk_in_first_name("Awa  Koné") == "Awa"

    def test_leading_trailing_spaces_handled(self) -> None:
        # L'appelant passe une chaîne déjà trim (validate_customer_name), mais on
        # vérifie la robustesse au cas où.
        assert walk_in_first_name("  Awa Koné  ") == "Awa"

    def test_accentuated_first_name(self) -> None:
        assert walk_in_first_name("Élodie Dupont") == "Élodie"

    def test_single_char_name(self) -> None:
        assert walk_in_first_name("A B") == "A"

    def test_full_name_composed_by_kiosk_roundtrips(self) -> None:
        """La composition « Prénom Nom » garantit que walk_in_first_name == first_name."""
        first_name = "Awa"
        last_name = "Koné"
        full_name = f"{first_name} {last_name}"
        assert walk_in_first_name(full_name) == first_name


# ---------------------------------------------------------------------------
# WalkInIdentity
# ---------------------------------------------------------------------------


class TestWalkInIdentity:
    def test_fields_accessible(self) -> None:
        cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        identity = WalkInIdentity(customer_id=cid, first_name="Awa")
        assert identity.customer_id == cid
        assert identity.first_name == "Awa"

    def test_is_frozen(self) -> None:
        cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        identity = WalkInIdentity(customer_id=cid, first_name="Awa")
        with pytest.raises((AttributeError, TypeError)):
            identity.first_name = "Autre"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        a = WalkInIdentity(customer_id=cid, first_name="Awa")
        b = WalkInIdentity(customer_id=cid, first_name="Awa")
        assert a == b


# ---------------------------------------------------------------------------
# WalkInCustomerCommand — dataclass
# ---------------------------------------------------------------------------


class TestWalkInCustomerCommand:
    def test_fields_accessible(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="0700000000")
        assert cmd.first_name == "Awa"
        assert cmd.last_name == "Koné"
        assert cmd.phone == "0700000000"

    def test_is_frozen(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="0700000000")
        with pytest.raises((AttributeError, TypeError)):
            cmd.first_name = "Autre"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# validate_walk_in_customer
# ---------------------------------------------------------------------------


class TestValidateWalkInCustomer:
    # --- Parcours heureux ---

    def test_returns_full_name_and_canonical_phone(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="0700000000")
        full_name, phone = validate_walk_in_customer(cmd)
        assert full_name == "Awa Koné"
        assert phone == "+2250700000000"

    def test_full_name_composition_order_preserves_first_name(self) -> None:
        """L'ordre « Prénom Nom » garantit walk_in_first_name(full_name) == first_name."""
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="0700000000")
        full_name, _ = validate_walk_in_customer(cmd)
        assert walk_in_first_name(full_name) == "Awa"

    def test_trims_first_name_and_last_name(self) -> None:
        cmd = WalkInCustomerCommand(first_name="  Awa  ", last_name="  Koné  ", phone="0700000000")
        full_name, _ = validate_walk_in_customer(cmd)
        assert full_name == "Awa Koné"

    # --- Formats de saisie tactile (normalisation idempotente E.164) ---

    def test_local_10_digit_format(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="0700000000")
        _, phone = validate_walk_in_customer(cmd)
        assert phone == "+2250700000000"

    def test_spaced_local_format(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="07 00 00 00 00")
        _, phone = validate_walk_in_customer(cmd)
        assert phone == "+2250700000000"

    def test_international_prefix_with_separator(self) -> None:
        cmd = WalkInCustomerCommand(
            first_name="Awa", last_name="Koné", phone="+225 07-00-00-00-00"
        )
        _, phone = validate_walk_in_customer(cmd)
        assert phone == "+2250700000000"

    def test_double_zero_international_prefix(self) -> None:
        cmd = WalkInCustomerCommand(
            first_name="Awa", last_name="Koné", phone="002250700000000"
        )
        _, phone = validate_walk_in_customer(cmd)
        assert phone == "+2250700000000"

    def test_already_e164_idempotent(self) -> None:
        cmd = WalkInCustomerCommand(
            first_name="Awa", last_name="Koné", phone="+2250700000000"
        )
        _, phone = validate_walk_in_customer(cmd)
        assert phone == "+2250700000000"

    def test_all_formats_yield_same_canonical(self) -> None:
        """Formats divers produits par un pavé tactile → même forme canonique."""
        formats = ["0700000000", "07 00 00 00 00", "+2250700000000", "002250700000000"]
        results = set()
        for raw in formats:
            cmd = WalkInCustomerCommand(first_name="A", last_name="B", phone=raw)
            _, phone = validate_walk_in_customer(cmd)
            results.add(phone)
        assert len(results) == 1

    # --- Invalide : prénom ---

    def test_empty_first_name_raises_invalid_customer_name(self) -> None:
        cmd = WalkInCustomerCommand(first_name="", last_name="Koné", phone="0700000000")
        with pytest.raises(InvalidCustomerName):
            validate_walk_in_customer(cmd)

    def test_whitespace_first_name_raises_invalid_customer_name(self) -> None:
        cmd = WalkInCustomerCommand(first_name="   ", last_name="Koné", phone="0700000000")
        with pytest.raises(InvalidCustomerName):
            validate_walk_in_customer(cmd)

    # --- Invalide : nom ---

    def test_empty_last_name_raises_invalid_customer_name(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="", phone="0700000000")
        with pytest.raises(InvalidCustomerName):
            validate_walk_in_customer(cmd)

    def test_whitespace_last_name_raises_invalid_customer_name(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="   ", phone="0700000000")
        with pytest.raises(InvalidCustomerName):
            validate_walk_in_customer(cmd)

    # --- Invalide : composé dépasse 255 ---

    def test_composed_full_name_over_max_raises(self) -> None:
        """Prénom + Nom légalement courts mais composé > 255 → InvalidCustomerName."""
        long_first = "A" * (CUSTOMER_NAME_MAX_LENGTH // 2 + 1)
        long_last = "B" * (CUSTOMER_NAME_MAX_LENGTH // 2 + 1)
        cmd = WalkInCustomerCommand(first_name=long_first, last_name=long_last, phone="0700000000")
        with pytest.raises(InvalidCustomerName):
            validate_walk_in_customer(cmd)

    # --- Invalide : téléphone ---

    def test_empty_phone_raises_invalid_phone(self) -> None:
        # La sémantique borne : téléphone requis (différent du flux gérant #28 où
        # `normalize_customer_phone` accepte la chaîne vide → None).
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="")
        with pytest.raises(InvalidPhone):
            validate_walk_in_customer(cmd)

    def test_malformed_phone_raises_invalid_phone(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="not-a-phone")
        with pytest.raises(InvalidPhone):
            validate_walk_in_customer(cmd)

    def test_too_short_phone_raises_invalid_phone(self) -> None:
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="123")
        with pytest.raises(InvalidPhone):
            validate_walk_in_customer(cmd)

    # --- Erreur avant accès base ---

    def test_name_error_raised_before_phone_normalisation(self) -> None:
        """InvalidCustomerName levée avant d'atteindre normalize_phone."""
        cmd = WalkInCustomerCommand(first_name="", last_name="Koné", phone="not-a-phone")
        with pytest.raises(InvalidCustomerName):
            validate_walk_in_customer(cmd)

    # --- Messages neutres (aucune PII) ---

    def test_first_name_error_message_does_not_echo_input(self) -> None:
        cmd = WalkInCustomerCommand(first_name="", last_name="Koné", phone="0700000000")
        try:
            validate_walk_in_customer(cmd)
        except InvalidCustomerName as exc:
            # Le message ne doit pas refléter la valeur soumise (§11.3).
            assert "Koné" not in str(exc)
