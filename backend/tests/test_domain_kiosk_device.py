"""Tests unitaires — domaine `kiosk_device` (US-8.1, #155).

Couvre :
- `DEVICE_LABEL_MAX_LENGTH` : constante alignée sur `users.full_name` (`String(255)`) ;
- `validate_device_label` : vide, whitespace-only, trop long, non-string, valide,
  longueur exacte max, retour normalisé (strip) ;
- `KioskDevice` : champs attendus, gelé, **sans** champ secret ni condensat (invariant
  de non-fuite §11.3 : la vue exposée au gérant ne porte jamais le secret) ;
- `KioskDeviceCredentials` : porte `password_hash` (interne, jamais sérialisé) ;
- `KioskDeviceToCreate` : construction correcte, gelé, sans champ secret en clair.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import fields

import pytest

from coiflink_api.domain.errors import InvalidKioskDeviceLabel
from coiflink_api.domain.kiosk_device import (
    DEVICE_LABEL_MAX_LENGTH,
    KioskDevice,
    KioskDeviceCredentials,
    KioskDeviceToCreate,
    validate_device_label,
)

# Identifiants synthétiques — aucune PII, aucun secret réel.
_SALON_ID  = uuid.UUID("a0000000-0000-0000-0000-000000000001")
_DEVICE_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# DEVICE_LABEL_MAX_LENGTH
# ---------------------------------------------------------------------------


def test_device_label_max_length_is_255() -> None:
    """Longueur max alignée sur `users.full_name` (`String(255)`)."""
    assert DEVICE_LABEL_MAX_LENGTH == 255


# ---------------------------------------------------------------------------
# validate_device_label
# ---------------------------------------------------------------------------


class TestValidateDeviceLabel:
    def test_valid_label_returned_stripped(self) -> None:
        assert validate_device_label("  Borne entrée  ") == "Borne entrée"

    def test_minimal_single_char_accepted(self) -> None:
        assert validate_device_label("A") == "A"

    def test_exactly_max_length_accepted(self) -> None:
        label = "x" * DEVICE_LABEL_MAX_LENGTH
        result = validate_device_label(label)
        assert result == label

    def test_one_beyond_max_length_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label("x" * (DEVICE_LABEL_MAX_LENGTH + 1))

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label("   ")

    def test_tab_only_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label("\t")

    def test_newline_only_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label("\n")

    def test_none_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label(None)  # type: ignore[arg-type]

    def test_integer_raises(self) -> None:
        with pytest.raises(InvalidKioskDeviceLabel):
            validate_device_label(42)  # type: ignore[arg-type]

    def test_label_stripped_of_leading_trailing_spaces(self) -> None:
        result = validate_device_label("  Borne  ")
        assert result == "Borne"
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_label_stripped_to_max_length_at_boundary(self) -> None:
        """Strip d'espaces avant validation de longueur : longueur finale, pas brute."""
        label = " " + "x" * DEVICE_LABEL_MAX_LENGTH + " "
        result = validate_device_label(label)
        assert len(result) == DEVICE_LABEL_MAX_LENGTH

    def test_error_message_is_neutral_not_empty(self) -> None:
        """Le message ne reprend pas la valeur soumise (anti-divulgation)."""
        with pytest.raises(InvalidKioskDeviceLabel) as exc_info:
            validate_device_label("")
        # Le message est neutre : ni la valeur, ni la longueur brute n'y figurent
        # (vérification minimaliste — on s'assure qu'un message existe).
        assert str(exc_info.value)

    def test_too_long_error_message_neutral(self) -> None:
        """Message de dépassement de longueur neutre (ne reprend pas la valeur soumise)."""
        long_label = "x" * (DEVICE_LABEL_MAX_LENGTH + 1)
        with pytest.raises(InvalidKioskDeviceLabel) as exc_info:
            validate_device_label(long_label)
        # Le message ne doit pas contenir la valeur brute (§11.3).
        assert long_label not in str(exc_info.value)


# ---------------------------------------------------------------------------
# KioskDevice — entité publique (sans secret, invariant §11.3)
# ---------------------------------------------------------------------------


def _make_device(**kwargs) -> KioskDevice:  # type: ignore[no-untyped-def]
    defaults = dict(
        id=_DEVICE_ID,
        salon_id=_SALON_ID,
        label="Borne entrée",
        status="ACTIVE",
        created_at=_CREATED_AT,
    )
    defaults.update(kwargs)
    return KioskDevice(**defaults)


class TestKioskDevice:
    def test_construction_nominal(self) -> None:
        device = _make_device()
        assert device.id == _DEVICE_ID
        assert device.salon_id == _SALON_ID
        assert device.label == "Borne entrée"
        assert device.status == "ACTIVE"
        assert device.created_at == _CREATED_AT

    def test_is_frozen(self) -> None:
        device = _make_device()
        with pytest.raises((AttributeError, TypeError)):
            device.label = "autre"  # type: ignore[misc]

    def test_has_no_password_hash_field(self) -> None:
        """Invariant §11.3 : la vue publique n'expose jamais le condensat argon2id."""
        field_names = {f.name for f in fields(KioskDevice)}
        assert "password_hash" not in field_names

    def test_has_no_secret_field(self) -> None:
        """Invariant §11.3 : la vue publique n'expose jamais le secret en clair."""
        field_names = {f.name for f in fields(KioskDevice)}
        assert "secret" not in field_names

    def test_has_no_hash_field(self) -> None:
        field_names = {f.name for f in fields(KioskDevice)}
        assert "hash" not in field_names

    def test_expected_field_names_present(self) -> None:
        field_names = {f.name for f in fields(KioskDevice)}
        assert {"id", "salon_id", "label", "status", "created_at"} <= field_names


# ---------------------------------------------------------------------------
# KioskDeviceCredentials — interne, jamais sérialisé (§11.3)
# ---------------------------------------------------------------------------


def _make_credentials(**kwargs) -> KioskDeviceCredentials:  # type: ignore[no-untyped-def]
    defaults = dict(
        id=_DEVICE_ID,
        salon_id=_SALON_ID,
        password_hash="hash:some-secret",
        status="ACTIVE",
    )
    defaults.update(kwargs)
    return KioskDeviceCredentials(**defaults)


class TestKioskDeviceCredentials:
    def test_carries_password_hash_field(self) -> None:
        """Interne : porte le condensat nécessaire à `PasswordHasher.verify` (login borne)."""
        field_names = {f.name for f in fields(KioskDeviceCredentials)}
        assert "password_hash" in field_names

    def test_construction_nominal(self) -> None:
        creds = _make_credentials()
        assert creds.id == _DEVICE_ID
        assert creds.salon_id == _SALON_ID
        assert creds.password_hash == "hash:some-secret"
        assert creds.status == "ACTIVE"

    def test_is_frozen(self) -> None:
        creds = _make_credentials()
        with pytest.raises((AttributeError, TypeError)):
            creds.password_hash = "autre"  # type: ignore[misc]

    def test_expected_fields_present(self) -> None:
        field_names = {f.name for f in fields(KioskDeviceCredentials)}
        assert {"id", "salon_id", "password_hash", "status"} <= field_names


# ---------------------------------------------------------------------------
# KioskDeviceToCreate
# ---------------------------------------------------------------------------


class TestKioskDeviceToCreate:
    def test_construction_nominal(self) -> None:
        to_create = KioskDeviceToCreate(
            salon_id=_SALON_ID,
            label="Borne test",
            password_hash="hash:secret",
        )
        assert to_create.salon_id == _SALON_ID
        assert to_create.label == "Borne test"
        assert to_create.password_hash == "hash:secret"

    def test_is_frozen(self) -> None:
        to_create = KioskDeviceToCreate(
            salon_id=_SALON_ID, label="Borne test", password_hash="h"
        )
        with pytest.raises((AttributeError, TypeError)):
            to_create.label = "autre"  # type: ignore[misc]

    def test_has_no_plaintext_secret_field(self) -> None:
        """Invariant : le secret en clair ne doit jamais transiter par `KioskDeviceToCreate`."""
        field_names = {f.name for f in fields(KioskDeviceToCreate)}
        assert "secret" not in field_names
