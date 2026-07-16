"""Tests unitaires — cas d'usage de gestion des prestations (US-2.3, #17).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.
Couvre :
- `CreateService` : `salon_id` imposé par l'argument ; validation avant écriture ;
  audit `SERVICE_CREATED` avec le bon acteur ; aucun audit si la validation échoue ;
- `ListSalonServices` : liste vide, liste filtrée par salon ;
- `GetService` : `ServiceNotFound` si absent ; retourne la bonne prestation ;
- `UpdateService` : `ServiceNotFound` si absent ; validation avant écriture ;
  `metadata.changed` correct ; audit `SERVICE_UPDATED` ; aucun audit si validation échoue ;
- `DeactivateService` : `ServiceNotFound` si absent ; `is_active=False` ;
  audit `SERVICE_DEACTIVATED` ;
- atomicité (ordre) : si le dépôt échoue avant l'audit, aucune entrée n'est laissée.
"""

from __future__ import annotations

import decimal
import uuid

import pytest

from coiflink_api.application.services import (
    CreateService,
    DeactivateService,
    GetService,
    ListSalonServices,
    ServiceCommand,
    UpdateService,
)
from coiflink_api.domain.audit import AuditAction, AuditEntry
from coiflink_api.domain.errors import (
    InvalidServiceDuration,
    InvalidServiceName,
    InvalidServicePrice,
    ServiceNotFound,
)

from .conftest import FakeAuditLog, FakeServiceRepository

# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ACTOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

_VALID_COMMAND = ServiceCommand(
    name="Coupe homme",
    price=decimal.Decimal("5000.00"),
    duration_minutes=30,
    description="Coupe aux ciseaux.",
    category="Coupe",
)


# ---------------------------------------------------------------------------
# CreateService
# ---------------------------------------------------------------------------


class TestCreateService:
    def test_service_created_with_correct_salon_id(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert service.salon_id == _SALON_ID

    def test_service_created_active_by_default(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert service.is_active is True

    def test_command_has_no_salon_id_field(self) -> None:
        """Invariant anti-élévation : la commande ne déclare pas de champ salon_id."""
        assert not hasattr(_VALID_COMMAND, "salon_id")

    def test_audit_entry_recorded_on_success(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert len(audit.recorded) == 1

    def test_audit_entry_has_correct_action(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.action == AuditAction.SERVICE_CREATED.value

    def test_audit_entry_has_correct_actor(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.actor_user_id == _ACTOR_ID

    def test_audit_entry_has_correct_salon_id(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.salon_id == _SALON_ID

    def test_audit_entry_entity_id_matches_service(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.entity_id == service.id

    def test_no_audit_if_name_invalid(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        cmd = ServiceCommand(name="", price=decimal.Decimal("100"), duration_minutes=30)
        with pytest.raises(InvalidServiceName):
            CreateService(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert audit.recorded == []

    def test_no_repository_call_if_price_invalid(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        cmd = ServiceCommand(
            name="Coupe", price=decimal.Decimal("-1"), duration_minutes=30
        )
        with pytest.raises(InvalidServicePrice):
            CreateService(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert repo.created == []
        assert audit.recorded == []

    def test_no_audit_if_duration_invalid(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        cmd = ServiceCommand(
            name="Coupe", price=decimal.Decimal("100"), duration_minutes=0
        )
        with pytest.raises(InvalidServiceDuration):
            CreateService(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert audit.recorded == []

    def test_service_name_trimmed(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        cmd = ServiceCommand(
            name="  Coupe homme  ",
            price=decimal.Decimal("5000.00"),
            duration_minutes=30,
        )
        service = CreateService(repo, audit).execute(
            _SALON_ID, cmd, actor_user_id=_ACTOR_ID
        )
        assert service.name == "Coupe homme"

    def test_empty_description_stored_as_none(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        cmd = ServiceCommand(
            name="Coupe",
            price=decimal.Decimal("100"),
            duration_minutes=30,
            description="",
        )
        service = CreateService(repo, audit).execute(
            _SALON_ID, cmd, actor_user_id=_ACTOR_ID
        )
        assert service.description is None

    def test_atomicity_no_audit_if_repository_raises(self) -> None:
        class _FailingRepo:
            def create(self, _service):  # type: ignore[no-untyped-def]
                raise RuntimeError("DB failure")

        audit = FakeAuditLog()
        with pytest.raises(RuntimeError):
            CreateService(_FailingRepo(), audit).execute(  # type: ignore[arg-type]
                _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
            )
        assert audit.recorded == []


# ---------------------------------------------------------------------------
# ListSalonServices
# ---------------------------------------------------------------------------


class TestListSalonServices:
    def test_empty_repository_returns_empty_tuple(self) -> None:
        repo = FakeServiceRepository()
        result = ListSalonServices(repo).execute(_SALON_ID)
        assert result == ()

    def test_returns_services_for_correct_salon(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        result = ListSalonServices(repo).execute(_SALON_ID)
        assert len(result) == 1
        assert result[0].salon_id == _SALON_ID

    def test_does_not_return_other_salon_services(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        result = ListSalonServices(repo).execute(_OTHER_SALON_ID)
        assert result == ()

    def test_returns_multiple_services(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        cmd2 = ServiceCommand(
            name="Barbe",
            price=decimal.Decimal("2000.00"),
            duration_minutes=15,
        )
        CreateService(repo, audit).execute(_SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID)
        CreateService(repo, audit).execute(_SALON_ID, cmd2, actor_user_id=_ACTOR_ID)
        result = ListSalonServices(repo).execute(_SALON_ID)
        assert len(result) == 2

    def test_inactive_services_included_by_default(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        DeactivateService(repo, audit).execute(
            _SALON_ID, service.id, actor_user_id=_ACTOR_ID
        )
        result = ListSalonServices(repo).execute(_SALON_ID, include_inactive=True)
        assert len(result) == 1
        assert result[0].is_active is False

    def test_inactive_services_excluded_when_requested(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        DeactivateService(repo, audit).execute(
            _SALON_ID, service.id, actor_user_id=_ACTOR_ID
        )
        result = ListSalonServices(repo).execute(_SALON_ID, include_inactive=False)
        assert result == ()


# ---------------------------------------------------------------------------
# GetService
# ---------------------------------------------------------------------------


class TestGetService:
    def test_raises_service_not_found_for_unknown_id(self) -> None:
        repo = FakeServiceRepository()
        with pytest.raises(ServiceNotFound):
            GetService(repo).execute(_SALON_ID, uuid.uuid4())

    def test_returns_service_when_found(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        result = GetService(repo).execute(_SALON_ID, service.id)
        assert result.id == service.id

    def test_raises_when_service_belongs_to_other_salon(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _OTHER_SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        with pytest.raises(ServiceNotFound):
            GetService(repo).execute(_SALON_ID, service.id)


# ---------------------------------------------------------------------------
# UpdateService
# ---------------------------------------------------------------------------


class TestUpdateService:
    def test_raises_when_service_not_found(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        with pytest.raises(ServiceNotFound):
            UpdateService(repo, audit).execute(
                _SALON_ID, uuid.uuid4(), _VALID_COMMAND, actor_user_id=_ACTOR_ID
            )

    def test_updated_service_returned(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        new_cmd = ServiceCommand(
            name="Coupe femme",
            price=decimal.Decimal("6000.00"),
            duration_minutes=45,
        )
        updated = UpdateService(repo, audit).execute(
            _SALON_ID, service.id, new_cmd, actor_user_id=_ACTOR_ID
        )
        assert updated.name == "Coupe femme"
        assert updated.price == decimal.Decimal("6000.00")
        assert updated.duration_minutes == 45

    def test_audit_entry_recorded_on_update(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        new_cmd = ServiceCommand(
            name="Coupe femme",
            price=decimal.Decimal("6000.00"),
            duration_minutes=45,
        )
        UpdateService(repo, audit).execute(
            _SALON_ID, service.id, new_cmd, actor_user_id=_ACTOR_ID
        )
        assert len(audit.recorded) == 1
        entry: AuditEntry = audit.recorded[0]
        assert entry.action == AuditAction.SERVICE_UPDATED.value

    def test_changed_fields_in_metadata(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        # Change only name and price
        new_cmd = ServiceCommand(
            name="Coupe femme",
            price=decimal.Decimal("6000.00"),
            duration_minutes=_VALID_COMMAND.duration_minutes,
            description=_VALID_COMMAND.description,
            category=_VALID_COMMAND.category,
        )
        UpdateService(repo, audit).execute(
            _SALON_ID, service.id, new_cmd, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        changed = entry.metadata["changed"]
        assert "name" in changed
        assert "price" in changed
        assert "duration_minutes" not in changed

    def test_no_changed_fields_when_identical(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        # Same values
        same_cmd = ServiceCommand(
            name=service.name,
            price=service.price,
            duration_minutes=service.duration_minutes,
            description=service.description,
            category=service.category,
        )
        UpdateService(repo, audit).execute(
            _SALON_ID, service.id, same_cmd, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.metadata["changed"] == []

    def test_no_audit_if_validation_fails(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        bad_cmd = ServiceCommand(
            name="", price=decimal.Decimal("100"), duration_minutes=30
        )
        with pytest.raises(InvalidServiceName):
            UpdateService(repo, audit).execute(
                _SALON_ID, service.id, bad_cmd, actor_user_id=_ACTOR_ID
            )
        assert audit.recorded == []

    def test_no_write_if_validation_fails(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        original_name = service.name
        bad_cmd = ServiceCommand(
            name="", price=decimal.Decimal("100"), duration_minutes=30
        )
        with pytest.raises(InvalidServiceName):
            UpdateService(repo, audit).execute(
                _SALON_ID, service.id, bad_cmd, actor_user_id=_ACTOR_ID
            )
        # Service unchanged
        unchanged = repo.find_by_id(_SALON_ID, service.id)
        assert unchanged is not None
        assert unchanged.name == original_name

    def test_audit_actor_user_id_correct(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        other_actor = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
        new_cmd = ServiceCommand(
            name="Coupe femme",
            price=decimal.Decimal("6000.00"),
            duration_minutes=45,
        )
        UpdateService(repo, audit).execute(
            _SALON_ID, service.id, new_cmd, actor_user_id=other_actor
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.actor_user_id == other_actor

    def test_service_from_other_salon_not_found(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _OTHER_SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        with pytest.raises(ServiceNotFound):
            UpdateService(repo, audit).execute(
                _SALON_ID, service.id, _VALID_COMMAND, actor_user_id=_ACTOR_ID
            )


# ---------------------------------------------------------------------------
# DeactivateService
# ---------------------------------------------------------------------------


class TestDeactivateService:
    def test_raises_when_service_not_found(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        with pytest.raises(ServiceNotFound):
            DeactivateService(repo, audit).execute(
                _SALON_ID, uuid.uuid4(), actor_user_id=_ACTOR_ID
            )

    def test_deactivated_service_has_is_active_false(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        result = DeactivateService(repo, audit).execute(
            _SALON_ID, service.id, actor_user_id=_ACTOR_ID
        )
        assert result.is_active is False

    def test_audit_entry_recorded_on_deactivation(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        DeactivateService(repo, audit).execute(
            _SALON_ID, service.id, actor_user_id=_ACTOR_ID
        )
        assert len(audit.recorded) == 1

    def test_audit_action_is_service_deactivated(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        DeactivateService(repo, audit).execute(
            _SALON_ID, service.id, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.action == AuditAction.SERVICE_DEACTIVATED.value

    def test_audit_actor_correct(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        DeactivateService(repo, audit).execute(
            _SALON_ID, service.id, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.actor_user_id == _ACTOR_ID

    def test_service_from_other_salon_raises(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        service = CreateService(repo, audit).execute(
            _OTHER_SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        with pytest.raises(ServiceNotFound):
            DeactivateService(repo, audit).execute(
                _SALON_ID, service.id, actor_user_id=_ACTOR_ID
            )

    def test_no_audit_if_repository_find_returns_none(self) -> None:
        repo = FakeServiceRepository()
        audit = FakeAuditLog()
        with pytest.raises(ServiceNotFound):
            DeactivateService(repo, audit).execute(
                _SALON_ID, uuid.uuid4(), actor_user_id=_ACTOR_ID
            )
        assert audit.recorded == []
