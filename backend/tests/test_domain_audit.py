"""Tests unitaires — domaine `audit` (US-2.3, #17).

Couvre :
- `AuditAction` : domaine fermé, valeurs string, membre check ;
- `AuditEntry` : construction, `metadata` par défaut, `salon_id` par défaut,
  invariant de non-fuite (aucun champ PII/secret) ;
- `ENTITY_TYPE_SERVICE` : constante de type d'entité.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import uuid

from coiflink_api.domain.audit import (
    ENTITY_TYPE_APPOINTMENT,
    ENTITY_TYPE_SALON,
    ENTITY_TYPE_SERVICE,
    AuditAction,
    AuditEntry,
)


# ---------------------------------------------------------------------------
# AuditAction
# ---------------------------------------------------------------------------


class TestAuditAction:
    def test_service_created_value(self) -> None:
        assert AuditAction.SERVICE_CREATED == "SERVICE_CREATED"

    def test_service_updated_value(self) -> None:
        assert AuditAction.SERVICE_UPDATED == "SERVICE_UPDATED"

    def test_service_deactivated_value(self) -> None:
        assert AuditAction.SERVICE_DEACTIVATED == "SERVICE_DEACTIVATED"

    def test_service_reactivated_value(self) -> None:
        assert AuditAction.SERVICE_REACTIVATED == "SERVICE_REACTIVATED"

    def test_salon_updated_value(self) -> None:
        assert AuditAction.SALON_UPDATED == "SALON_UPDATED"

    def test_appointment_updated_value(self) -> None:
        assert AuditAction.APPOINTMENT_UPDATED == "APPOINTMENT_UPDATED"

    def test_appointment_cancelled_value(self) -> None:
        assert AuditAction.APPOINTMENT_CANCELLED == "APPOINTMENT_CANCELLED"

    def test_exactly_seven_actions_defined(self) -> None:
        assert len(list(AuditAction)) == 7

    def test_values_are_strings(self) -> None:
        for action in AuditAction:
            assert isinstance(action.value, str)

    def test_string_comparison_works(self) -> None:
        assert AuditAction.SERVICE_CREATED.value == "SERVICE_CREATED"

    def test_all_expected_actions_present(self) -> None:
        names = {a.name for a in AuditAction}
        assert names == {
            "SERVICE_CREATED",
            "SERVICE_UPDATED",
            "SERVICE_DEACTIVATED",
            "SERVICE_REACTIVATED",
            "SALON_UPDATED",
            "APPOINTMENT_UPDATED",
            "APPOINTMENT_CANCELLED",
        }


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


class TestAuditEntry:
    _ACTOR = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    _SALON = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
    _ENTITY = uuid.UUID("cccccccc-0000-0000-0000-000000000003")

    def _make(self, **kwargs):  # type: ignore[no-untyped-def]
        defaults = dict(
            action=AuditAction.SERVICE_CREATED.value,
            actor_user_id=self._ACTOR,
            entity_type=ENTITY_TYPE_SERVICE,
            entity_id=self._ENTITY,
        )
        defaults.update(kwargs)
        return AuditEntry(**defaults)

    def test_construction_minimal(self) -> None:
        entry = self._make()
        assert entry.action == "SERVICE_CREATED"
        assert entry.actor_user_id == self._ACTOR
        assert entry.entity_type == ENTITY_TYPE_SERVICE
        assert entry.entity_id == self._ENTITY

    def test_salon_id_defaults_to_none(self) -> None:
        entry = self._make()
        assert entry.salon_id is None

    def test_metadata_defaults_to_empty_dict(self) -> None:
        entry = self._make()
        assert entry.metadata == {}

    def test_salon_id_can_be_set(self) -> None:
        entry = self._make(salon_id=self._SALON)
        assert entry.salon_id == self._SALON

    def test_metadata_can_carry_changed_fields(self) -> None:
        entry = self._make(metadata={"changed": ["price", "name"]})
        assert entry.metadata["changed"] == ["price", "name"]

    def test_entry_is_frozen(self) -> None:
        entry = self._make()
        import pytest
        with pytest.raises((AttributeError, TypeError)):
            entry.action = "OTHER"  # type: ignore[misc]

    def test_no_pii_field_names(self) -> None:
        entry = self._make()
        field_names = {f.name for f in entry.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        forbidden = {"phone", "email", "password", "address", "name", "token"}
        assert not field_names & forbidden, (
            f"AuditEntry contient des champs PII potentiels : {field_names & forbidden}"
        )

    def test_actor_user_id_is_opaque_uuid(self) -> None:
        entry = self._make()
        assert isinstance(entry.actor_user_id, uuid.UUID)

    def test_metadata_is_dict(self) -> None:
        entry = self._make(metadata={"changed": ["duration_minutes"]})
        assert isinstance(entry.metadata, dict)

    def test_metadata_does_not_contain_secret_keys(self) -> None:
        entry = self._make(metadata={"changed": ["price"]})
        forbidden_keys = {"token", "password", "secret", "hash"}
        actual_keys = set(entry.metadata.keys())
        assert not actual_keys & forbidden_keys


# ---------------------------------------------------------------------------
# ENTITY_TYPE_SERVICE
# ---------------------------------------------------------------------------


class TestEntityTypeService:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_SERVICE, str)

    def test_value_is_service(self) -> None:
        assert ENTITY_TYPE_SERVICE == "service"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_SALON
# ---------------------------------------------------------------------------


class TestEntityTypeSalon:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_SALON, str)

    def test_value_is_salon(self) -> None:
        assert ENTITY_TYPE_SALON == "salon"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_APPOINTMENT (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestEntityTypeAppointment:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_APPOINTMENT, str)

    def test_value_is_appointment(self) -> None:
        assert ENTITY_TYPE_APPOINTMENT == "appointment"
