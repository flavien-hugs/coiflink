"""Tests unitaires pour les cas d'usage de gestion des coiffeuses (#150).

Couvre `ListSalonEmployees`, `GetSalonEmployee`, `UpdateEmployeeProfile`,
`DeactivateEmployee`, `ReactivateEmployee` — tous les ports sont des fakes
(conftest.py) : pas de base de données. Vérifie :
- la lecture salon-scopée (isolation §11.2, `EmployeeNotFound` indiscernable) ;
- la modification de profil (identité + champs pro, diff neutre journalisé) ;
- l'activation/désactivation (`salon_members.status`, jamais `users.status`) ;
- les invariants de journalisation §11.4 (action, `salon_id`, métadonnées neutres).
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.application.employees import (
    DeactivateEmployee,
    GetSalonEmployee,
    ListSalonEmployees,
    ReactivateEmployee,
    UpdateEmployeeProfile,
    UpdateEmployeeProfileCommand,
)
from coiflink_api.domain.audit import AuditAction, ENTITY_TYPE_SALON_MEMBER
from coiflink_api.domain.employee import Employee
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import (
    EmployeeNotFound,
    EmailAlreadyInUse,
    InvalidEmployeeSpecialties,
    InvalidName,
    InvalidPhone,
    PhoneAlreadyInUse,
)

from .conftest import FakeAuditLog, FakeSalonMemberRepository, FakeUserRepository

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_EMPLOYEE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
_ACTOR_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000009")
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = dict(
        id=_EMPLOYEE_ID,
        full_name="Awa Koné",
        phone="+2250700000000",
        email=None,
        role=Role.HAIRDRESSER.value,
        status=UserStatus.ACTIVE.value,
        specialties=None,
        hired_at=None,
        created_at=_CREATED_AT,
    )
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


def _seeded_members(**overrides: object) -> FakeSalonMemberRepository:
    return FakeSalonMemberRepository(seed={(_SALON_ID, _EMPLOYEE_ID): _employee(**overrides)})


# ---------------------------------------------------------------------------
# ListSalonEmployees
# ---------------------------------------------------------------------------


class TestListSalonEmployees:
    def test_returns_seeded_employees(self) -> None:
        members = _seeded_members()
        uc = ListSalonEmployees(members)
        result = uc.execute(_SALON_ID)
        assert len(result) == 1
        assert result[0].id == _EMPLOYEE_ID

    def test_empty_salon_returns_empty_tuple(self) -> None:
        uc = ListSalonEmployees(FakeSalonMemberRepository())
        assert uc.execute(_SALON_ID) == ()

    def test_other_salon_employee_not_returned(self) -> None:
        members = _seeded_members()
        uc = ListSalonEmployees(members)
        assert uc.execute(_OTHER_SALON_ID) == ()


# ---------------------------------------------------------------------------
# GetSalonEmployee
# ---------------------------------------------------------------------------


class TestGetSalonEmployee:
    def test_returns_employee_of_salon(self) -> None:
        members = _seeded_members()
        uc = GetSalonEmployee(members)
        employee = uc.execute(_SALON_ID, _EMPLOYEE_ID)
        assert employee.id == _EMPLOYEE_ID

    def test_unknown_employee_raises_not_found(self) -> None:
        uc = GetSalonEmployee(FakeSalonMemberRepository())
        with pytest.raises(EmployeeNotFound):
            uc.execute(_SALON_ID, _EMPLOYEE_ID)

    def test_employee_of_other_salon_raises_not_found(self) -> None:
        """Isolation §11.2 : indiscernable d'un identifiant inexistant."""
        members = _seeded_members()
        uc = GetSalonEmployee(members)
        with pytest.raises(EmployeeNotFound):
            uc.execute(_OTHER_SALON_ID, _EMPLOYEE_ID)


# ---------------------------------------------------------------------------
# UpdateEmployeeProfile
# ---------------------------------------------------------------------------


_VALID_UPDATE = UpdateEmployeeProfileCommand(
    full_name="Awa Koné Modifiée",
    phone="0700000001",
    email="awa@example.com",
    specialties="Tresses, colorations",
    hired_at=datetime.date(2026, 1, 15),
)


class TestUpdateEmployeeProfile:
    def test_unknown_employee_raises_not_found(self) -> None:
        uc = UpdateEmployeeProfile(FakeUserRepository(), FakeSalonMemberRepository(), FakeAuditLog())
        with pytest.raises(EmployeeNotFound):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)

    def test_employee_of_other_salon_raises_not_found(self) -> None:
        members = _seeded_members()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        with pytest.raises(EmployeeNotFound):
            uc.execute(_OTHER_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)

    def test_returns_updated_identity_and_professional_fields(self) -> None:
        members = _seeded_members()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        updated = uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)
        assert updated.full_name == "Awa Koné Modifiée"
        assert updated.phone == "+2250700000001"
        assert updated.email == "awa@example.com"
        assert updated.specialties == "Tresses, colorations"
        assert updated.hired_at == datetime.date(2026, 1, 15)

    def test_status_unchanged_by_profile_update(self) -> None:
        members = _seeded_members(status=UserStatus.INACTIVE.value)
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        updated = uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)
        assert updated.status == UserStatus.INACTIVE.value

    def test_calls_update_identity_with_normalized_values(self) -> None:
        members = _seeded_members()
        users = FakeUserRepository()
        uc = UpdateEmployeeProfile(users, members, FakeAuditLog())
        uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)
        assert len(users.updated_identities) == 1
        _, name, phone, email = users.updated_identities[0]
        assert name == "Awa Koné Modifiée"
        assert phone == "+2250700000001"
        assert email == "awa@example.com"

    def test_duplicate_phone_on_update_identity_propagates(self) -> None:
        members = _seeded_members()
        users = FakeUserRepository(
            raise_on_update_identity=PhoneAlreadyInUse("déjà utilisé.")
        )
        uc = UpdateEmployeeProfile(users, members, FakeAuditLog())
        with pytest.raises(PhoneAlreadyInUse):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)

    def test_duplicate_email_on_update_identity_propagates(self) -> None:
        members = _seeded_members()
        users = FakeUserRepository(
            raise_on_update_identity=EmailAlreadyInUse("déjà utilisé.")
        )
        uc = UpdateEmployeeProfile(users, members, FakeAuditLog())
        with pytest.raises(EmailAlreadyInUse):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)

    def test_empty_name_raises_invalid_name(self) -> None:
        members = _seeded_members()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        command = UpdateEmployeeProfileCommand(
            full_name="", phone="0700000000", email=None, specialties=None, hired_at=None
        )
        with pytest.raises(InvalidName):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, command)

    def test_invalid_phone_raises_invalid_phone(self) -> None:
        members = _seeded_members()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        command = UpdateEmployeeProfileCommand(
            full_name="Awa", phone="abc", email=None, specialties=None, hired_at=None
        )
        with pytest.raises(InvalidPhone):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, command)

    def test_specialties_too_long_raises(self) -> None:
        members = _seeded_members()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        command = UpdateEmployeeProfileCommand(
            full_name="Awa",
            phone="0700000000",
            email=None,
            specialties="a" * 1001,
            hired_at=None,
        )
        with pytest.raises(InvalidEmployeeSpecialties):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, command)

    def test_records_audit_entry_with_neutral_diff(self) -> None:
        members = _seeded_members()
        audit_log = FakeAuditLog()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, audit_log)
        uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)

        assert len(audit_log.recorded) == 1
        entry = audit_log.recorded[0]
        assert entry.action == AuditAction.EMPLOYEE_UPDATED.value
        assert entry.actor_user_id == _ACTOR_ID
        assert entry.salon_id == _SALON_ID
        assert entry.entity_type == ENTITY_TYPE_SALON_MEMBER
        assert entry.entity_id == _EMPLOYEE_ID
        assert "changed" in entry.metadata
        assert "Awa Koné Modifiée" not in str(entry.metadata)
        assert "awa@example.com" not in str(entry.metadata)

    def test_unchanged_fields_not_listed_in_diff(self) -> None:
        members = _seeded_members(
            full_name="Awa Koné Modifiée",
            phone="+2250700000001",
            email="awa@example.com",
            specialties="Tresses, colorations",
            hired_at=datetime.date(2026, 1, 15),
        )
        audit_log = FakeAuditLog()
        uc = UpdateEmployeeProfile(FakeUserRepository(), members, audit_log)
        uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID, _VALID_UPDATE)
        assert audit_log.recorded[0].metadata["changed"] == []


# ---------------------------------------------------------------------------
# DeactivateEmployee / ReactivateEmployee
# ---------------------------------------------------------------------------


class TestDeactivateEmployee:
    def test_sets_status_inactive(self) -> None:
        members = _seeded_members()
        uc = DeactivateEmployee(members, FakeAuditLog())
        employee = uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)
        assert employee.status == UserStatus.INACTIVE.value

    def test_unknown_employee_raises_not_found(self) -> None:
        uc = DeactivateEmployee(FakeSalonMemberRepository(), FakeAuditLog())
        with pytest.raises(EmployeeNotFound):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)

    def test_employee_of_other_salon_raises_not_found(self) -> None:
        members = _seeded_members()
        uc = DeactivateEmployee(members, FakeAuditLog())
        with pytest.raises(EmployeeNotFound):
            uc.execute(_OTHER_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)

    def test_idempotent_when_already_inactive(self) -> None:
        members = _seeded_members(status=UserStatus.INACTIVE.value)
        uc = DeactivateEmployee(members, FakeAuditLog())
        employee = uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)
        assert employee.status == UserStatus.INACTIVE.value

    def test_records_neutral_audit_entry(self) -> None:
        members = _seeded_members()
        audit_log = FakeAuditLog()
        uc = DeactivateEmployee(members, audit_log)
        uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)
        entry = audit_log.recorded[0]
        assert entry.action == AuditAction.EMPLOYEE_DEACTIVATED.value
        assert entry.metadata == {}


class TestReactivateEmployee:
    def test_sets_status_active(self) -> None:
        members = _seeded_members(status=UserStatus.INACTIVE.value)
        uc = ReactivateEmployee(members, FakeAuditLog())
        employee = uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)
        assert employee.status == UserStatus.ACTIVE.value

    def test_unknown_employee_raises_not_found(self) -> None:
        uc = ReactivateEmployee(FakeSalonMemberRepository(), FakeAuditLog())
        with pytest.raises(EmployeeNotFound):
            uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)

    def test_records_neutral_audit_entry(self) -> None:
        members = _seeded_members(status=UserStatus.INACTIVE.value)
        audit_log = FakeAuditLog()
        uc = ReactivateEmployee(members, audit_log)
        uc.execute(_SALON_ID, _EMPLOYEE_ID, _ACTOR_ID)
        entry = audit_log.recorded[0]
        assert entry.action == AuditAction.EMPLOYEE_REACTIVATED.value
        assert entry.metadata == {}
