"""Tests unitaires — cas d'usage `SetOpeningHours` (US-2.2, #16).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base,
pas de réseau. Couvre :
- validation avant écriture (aucun appel au dépôt si la structure est invalide) ;
- `SalonNotFound` si le salon est introuvable ;
- JSONB normalisé (version, timezone, intervalles triés) transmis au dépôt ;
- salon renvoyé avec `opening_hours` non null → `is_bookable=True` (§8.3) ;
- sémantique replace : un second appel remplace intégralement le premier.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.salons import SetOpeningHours
from coiflink_api.domain.errors import InvalidOpeningHours, SalonNotFound
from coiflink_api.domain.opening_hours import DEFAULT_TIMEZONE, OPENING_HOURS_SCHEMA_VERSION
from coiflink_api.domain.salon import SalonToCreate

from .conftest import FakeSalonRepository

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_OWNER_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")

_VALID_PAYLOAD: dict = {
    "weekly": {
        "mon": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
        "fri": [{"start": "09:00", "end": "17:00"}],
    },
}

_INVALID_PAYLOAD: dict = {
    # end <= start → invalide
    "weekly": {"mon": [{"start": "18:00", "end": "08:00"}]},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_salon(repo: FakeSalonRepository) -> uuid.UUID:
    """Crée un salon de test dans le dépôt et retourne son id."""
    salon = repo.create(SalonToCreate(owner_id=_OWNER_ID, name="Salon Test"))
    return salon.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSetOpeningHoursUseCase:
    def test_valid_payload_updates_opening_hours(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        result = SetOpeningHours(repo).execute(salon_id, _VALID_PAYLOAD)

        assert result.opening_hours is not None

    def test_valid_payload_makes_salon_bookable(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        result = SetOpeningHours(repo).execute(salon_id, _VALID_PAYLOAD)

        assert result.is_bookable is True

    def test_opening_hours_before_call_is_none(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        assert repo.find_by_id(salon_id).opening_hours is None

    def test_invalid_payload_raises_before_any_write(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        with pytest.raises(InvalidOpeningHours):
            SetOpeningHours(repo).execute(salon_id, _INVALID_PAYLOAD)

        # Aucune écriture ne doit avoir eu lieu.
        assert repo.find_by_id(salon_id).opening_hours is None

    def test_nonexistent_salon_raises_salon_not_found(self) -> None:
        repo = FakeSalonRepository()

        with pytest.raises(SalonNotFound):
            SetOpeningHours(repo).execute(uuid.uuid4(), _VALID_PAYLOAD)

    def test_jsonb_contains_schema_version(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        result = SetOpeningHours(repo).execute(salon_id, _VALID_PAYLOAD)

        assert result.opening_hours["version"] == OPENING_HOURS_SCHEMA_VERSION

    def test_jsonb_contains_default_timezone(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        result = SetOpeningHours(repo).execute(salon_id, _VALID_PAYLOAD)

        assert result.opening_hours["timezone"] == DEFAULT_TIMEZONE

    def test_jsonb_intervals_are_sorted(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        result = SetOpeningHours(repo).execute(salon_id, _VALID_PAYLOAD)

        mon_intervals = result.opening_hours["weekly"]["mon"]
        assert mon_intervals[0]["start"] == "08:00"
        assert mon_intervals[1]["start"] == "14:00"

    def test_replace_semantics(self) -> None:
        """Un second appel remplace intégralement le premier (pas de fusion)."""
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        first_payload = {"weekly": {"mon": [{"start": "08:00", "end": "18:00"}]}}
        SetOpeningHours(repo).execute(salon_id, first_payload)

        second_payload = {"weekly": {"tue": [{"start": "09:00", "end": "17:00"}]}}
        result = SetOpeningHours(repo).execute(salon_id, second_payload)

        weekly = result.opening_hours["weekly"]
        assert "mon" not in weekly
        assert "tue" in weekly

    def test_validation_precedes_existence_check(self) -> None:
        """Domaine valide en premier : SalonNotFound est masquée si payload invalide."""
        repo = FakeSalonRepository()
        # Aucun salon créé.

        with pytest.raises(InvalidOpeningHours):
            SetOpeningHours(repo).execute(uuid.uuid4(), _INVALID_PAYLOAD)

    def test_empty_exceptions_list_accepted(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        payload = {**_VALID_PAYLOAD, "exceptions": []}
        result = SetOpeningHours(repo).execute(salon_id, payload)
        assert result.opening_hours["exceptions"] == []

    def test_with_open_exception_makes_salon_bookable(self) -> None:
        repo = FakeSalonRepository()
        salon_id = _make_salon(repo)

        # Un salon sans horaire hebdo mais avec une exception ouverte.
        payload = {
            "exceptions": [
                {
                    "date": "2026-08-07",
                    "closed": False,
                    "intervals": [{"start": "09:00", "end": "17:00"}],
                }
            ]
        }
        result = SetOpeningHours(repo).execute(salon_id, payload)
        assert result.is_bookable is True
