"""Tests unitaires — domaine `salon` : validation et règle §8.3 (US-2.1, #15).

Aucune I/O (pas de base, pas de réseau). Couvre :
- `validate_salon_name` : vide / espaces / > 255 chars → `InvalidSalonName` ;
  `strip()` appliqué ; valeur à la limite (255) acceptée ;
- `validate_coordinates` : une seule coordonnée → `InvalidLocation` ; hors bornes
  WGS-84 → `InvalidLocation` ; (None, None) → accepté ; paire valide → acceptée ;
- `validate_content_type` : MIME valides → extension canonique ; MIME invalide /
  non-chaîne → `InvalidMediaType` ;
- `is_bookable` (§8.3) — table de vérité complète (cœur du critère d'acceptation) ;
- `Salon.is_bookable` (propriété) — délègue à la même règle.
"""

from __future__ import annotations

import decimal
import datetime
import uuid

import pytest

from coiflink_api.domain.errors import InvalidLocation, InvalidMediaType, InvalidSalonName
from coiflink_api.domain.salon import (
    SALON_NAME_MAX_LENGTH,
    Salon,
    validate_coordinates,
    validate_content_type,
    validate_salon_name,
    is_bookable,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_UUID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _make_salon(*, status: str = "ACTIVE", opening_hours: object = None) -> Salon:
    return Salon(
        id=_UUID,
        owner_id=_UUID,
        name="Salon Test",
        description=None,
        phone=None,
        address=None,
        city=None,
        commune=None,
        latitude=None,
        longitude=None,
        logo_object_key=None,
        status=status,
        opening_hours=opening_hours,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# validate_salon_name
# ---------------------------------------------------------------------------


class TestValidateSalonName:
    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidSalonName):
            validate_salon_name("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidSalonName):
            validate_salon_name("   ")

    def test_exceeding_max_length_raises(self) -> None:
        with pytest.raises(InvalidSalonName):
            validate_salon_name("a" * (SALON_NAME_MAX_LENGTH + 1))

    def test_exactly_max_length_accepted(self) -> None:
        name = "a" * SALON_NAME_MAX_LENGTH
        result = validate_salon_name(name)
        assert result == name

    def test_strips_leading_trailing_whitespace(self) -> None:
        result = validate_salon_name("  Salon Élégance  ")
        assert result == "Salon Élégance"

    def test_valid_name_returned(self) -> None:
        result = validate_salon_name("Mon Salon")
        assert result == "Mon Salon"

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidSalonName):
            validate_salon_name(None)  # type: ignore[arg-type]

    def test_strip_then_check_length(self) -> None:
        # La vérification de longueur porte sur la valeur après strip :
        # une chaîne de MAX+1 « a » entourée d'espaces → dépasse la limite
        # après strip → InvalidSalonName.
        padded = " " + "a" * (SALON_NAME_MAX_LENGTH + 1) + " "
        with pytest.raises(InvalidSalonName):
            validate_salon_name(padded)

    def test_non_string_integer_raises(self) -> None:
        with pytest.raises(InvalidSalonName):
            validate_salon_name(0)  # type: ignore[arg-type]

    def test_strip_within_max_accepted(self) -> None:
        # Padding sans dépasser la limite après strip → accepté.
        padded = " " + "a" * SALON_NAME_MAX_LENGTH + " "
        result = validate_salon_name(padded)
        assert result == "a" * SALON_NAME_MAX_LENGTH

    def test_single_character_accepted(self) -> None:
        result = validate_salon_name("X")
        assert result == "X"


# ---------------------------------------------------------------------------
# validate_coordinates
# ---------------------------------------------------------------------------


class TestValidateCoordinates:
    def test_both_none_accepted(self) -> None:
        lat, lon = validate_coordinates(None, None)
        assert lat is None
        assert lon is None

    def test_only_latitude_raises(self) -> None:
        with pytest.raises(InvalidLocation):
            validate_coordinates(decimal.Decimal("5.36"), None)

    def test_only_longitude_raises(self) -> None:
        with pytest.raises(InvalidLocation):
            validate_coordinates(None, decimal.Decimal("-3.99"))

    def test_valid_pair_returned(self) -> None:
        lat_in = decimal.Decimal("5.359952")
        lon_in = decimal.Decimal("-3.996643")
        lat, lon = validate_coordinates(lat_in, lon_in)
        assert lat == lat_in
        assert lon == lon_in

    def test_latitude_above_90_raises(self) -> None:
        with pytest.raises(InvalidLocation):
            validate_coordinates(decimal.Decimal("91"), decimal.Decimal("0"))

    def test_latitude_below_minus_90_raises(self) -> None:
        with pytest.raises(InvalidLocation):
            validate_coordinates(decimal.Decimal("-91"), decimal.Decimal("0"))

    def test_longitude_above_180_raises(self) -> None:
        with pytest.raises(InvalidLocation):
            validate_coordinates(decimal.Decimal("0"), decimal.Decimal("181"))

    def test_longitude_below_minus_180_raises(self) -> None:
        with pytest.raises(InvalidLocation):
            validate_coordinates(decimal.Decimal("0"), decimal.Decimal("-181"))

    def test_boundary_lat_90_accepted(self) -> None:
        lat, lon = validate_coordinates(decimal.Decimal("90"), decimal.Decimal("0"))
        assert lat == decimal.Decimal("90")

    def test_boundary_lat_minus_90_accepted(self) -> None:
        lat, _ = validate_coordinates(decimal.Decimal("-90"), decimal.Decimal("0"))
        assert lat == decimal.Decimal("-90")

    def test_boundary_lon_180_accepted(self) -> None:
        _, lon = validate_coordinates(decimal.Decimal("0"), decimal.Decimal("180"))
        assert lon == decimal.Decimal("180")

    def test_boundary_lon_minus_180_accepted(self) -> None:
        _, lon = validate_coordinates(decimal.Decimal("0"), decimal.Decimal("-180"))
        assert lon == decimal.Decimal("-180")


# ---------------------------------------------------------------------------
# validate_content_type
# ---------------------------------------------------------------------------


class TestValidateContentType:
    def test_image_jpeg_returns_jpg(self) -> None:
        assert validate_content_type("image/jpeg") == "jpg"

    def test_image_png_returns_png(self) -> None:
        assert validate_content_type("image/png") == "png"

    def test_image_webp_returns_webp(self) -> None:
        assert validate_content_type("image/webp") == "webp"

    def test_unknown_mime_raises(self) -> None:
        with pytest.raises(InvalidMediaType):
            validate_content_type("image/gif")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidMediaType):
            validate_content_type("")

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidMediaType):
            validate_content_type(None)  # type: ignore[arg-type]

    def test_mime_with_leading_spaces_normalised(self) -> None:
        # content_type.strip().lower() est appliqué
        assert validate_content_type("  image/png  ") == "png"

    def test_application_pdf_raises(self) -> None:
        with pytest.raises(InvalidMediaType):
            validate_content_type("application/pdf")


# ---------------------------------------------------------------------------
# is_bookable (fonction libre — table de vérité §8.3)
# ---------------------------------------------------------------------------


class TestIsBookable:
    """Table de vérité de la règle §8.3 — cœur du critère d'acceptation de #15."""

    def test_active_no_hours_is_not_bookable(self) -> None:
        assert is_bookable("ACTIVE", None) is False

    def test_active_empty_dict_is_not_bookable(self) -> None:
        # `bool({})` → False : un JSONB vide ne rend pas un salon réservable.
        assert is_bookable("ACTIVE", {}) is False

    def test_active_with_hours_is_bookable(self) -> None:
        assert is_bookable("ACTIVE", {"mon": ["09:00-18:00"]}) is True

    def test_inactive_with_hours_is_not_bookable(self) -> None:
        assert is_bookable("INACTIVE", {"mon": ["09:00-18:00"]}) is False

    def test_inactive_no_hours_is_not_bookable(self) -> None:
        assert is_bookable("INACTIVE", None) is False

    def test_unknown_status_is_not_bookable(self) -> None:
        assert is_bookable("SUSPENDED", {"mon": ["09:00-18:00"]}) is False


# ---------------------------------------------------------------------------
# Salon.is_bookable (propriété — délègue à is_bookable)
# ---------------------------------------------------------------------------


class TestSalonIsBookableProperty:
    def test_active_no_hours_returns_false(self) -> None:
        salon = _make_salon(status="ACTIVE", opening_hours=None)
        assert salon.is_bookable is False

    def test_active_empty_dict_returns_false(self) -> None:
        salon = _make_salon(status="ACTIVE", opening_hours={})
        assert salon.is_bookable is False

    def test_active_with_hours_returns_true(self) -> None:
        salon = _make_salon(status="ACTIVE", opening_hours={"tue": ["10:00-19:00"]})
        assert salon.is_bookable is True

    def test_inactive_with_hours_returns_false(self) -> None:
        salon = _make_salon(status="INACTIVE", opening_hours={"tue": ["10:00-19:00"]})
        assert salon.is_bookable is False
