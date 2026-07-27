"""Tests unitaires — cas d'usage de gestion des fiches clients (US-4.1, #28).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.
Couvre :
- `CreateCustomer` :
  - `salon_id` imposé par l'argument de portée, jamais par la commande ;
  - audit `CUSTOMER_CREATED` enregistré une fois, bon acteur/salon/entity_id ;
  - `metadata` **vide** (aucune PII au journal) ;
  - validation invalide → aucune écriture, aucun audit ;
  - `phone_exists` → `CustomerAlreadyExists`, aucune écriture, aucun audit ;
  - même téléphone dans un autre salon → accepté (cloisonnement §11.2) ;
  - race condition (create lève directement `CustomerAlreadyExists`) ;
- `GetCustomer` : trouvée, `CustomerNotFound` si inconnue ou dans un autre salon ;
- `ListSalonCustomers` : ne renvoie que les fiches du salon, total, limit/offset.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.customers import (
    CreateCustomer,
    CustomerCommand,
    GetCustomer,
    ListSalonCustomers,
)
from coiflink_api.domain.audit import AuditAction, AuditEntry, ENTITY_TYPE_CUSTOMER
from coiflink_api.domain.errors import (
    CustomerAlreadyExists,
    CustomerNotFound,
    InvalidCustomerGender,
    InvalidCustomerName,
    InvalidPhone,
)

from .conftest import FakeAuditLog, FakeCustomerRepository

# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ACTOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

_VALID_COMMAND = CustomerCommand(
    full_name="Awa Koné",
    phone="0700000000",
    gender="FEMALE",
    notes="Préfère le samedi.",
)

_MIN_COMMAND = CustomerCommand(full_name="Awa Koné")


# ---------------------------------------------------------------------------
# CreateCustomer
# ---------------------------------------------------------------------------


class TestCreateCustomer:
    def test_customer_created_with_correct_salon_id(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert customer.salon_id == _SALON_ID

    def test_salon_id_from_scope_not_from_command(self) -> None:
        """Invariant anti-élévation : la commande ne déclare pas de champ salon_id."""
        assert not hasattr(_VALID_COMMAND, "salon_id")

    def test_audit_entry_recorded_once(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert len(audit.recorded) == 1

    def test_audit_action_is_customer_created(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.action == AuditAction.CUSTOMER_CREATED.value

    def test_audit_actor_user_id_correct(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.actor_user_id == _ACTOR_ID

    def test_audit_salon_id_correct(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.salon_id == _SALON_ID

    def test_audit_entity_type_is_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.entity_type == ENTITY_TYPE_CUSTOMER

    def test_audit_entity_id_matches_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.entity_id == customer.id

    def test_audit_metadata_is_empty_dict(self) -> None:
        """Invariant §11.3 : aucune PII dans le journal d'audit."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        assert entry.metadata == {}

    def test_audit_metadata_contains_no_pii_keys(self) -> None:
        """Nom, téléphone, genre et notes n'entrent jamais dans le journal."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        entry: AuditEntry = audit.recorded[0]
        forbidden = {"name", "phone", "gender", "notes", "full_name"}
        assert not forbidden & set(entry.metadata.keys())

    def test_phone_normalized_in_persisted_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert customer.phone == "+2250700000000"

    def test_name_trimmed_in_persisted_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        cmd = CustomerCommand(full_name="  Awa Koné  ")
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, cmd, actor_user_id=_ACTOR_ID
        )
        assert customer.full_name == "Awa Koné"

    def test_total_visits_defaults_to_zero(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert customer.total_visits == 0

    def test_last_visit_at_defaults_to_none(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert customer.last_visit_at is None

    def test_no_audit_if_name_invalid(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        cmd = CustomerCommand(full_name="")
        with pytest.raises(InvalidCustomerName):
            CreateCustomer(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert audit.recorded == []

    def test_no_write_if_name_invalid(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        cmd = CustomerCommand(full_name="")
        with pytest.raises(InvalidCustomerName):
            CreateCustomer(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert repo.created == []

    def test_no_audit_if_phone_invalid(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        cmd = CustomerCommand(full_name="Awa", phone="not-a-phone")
        with pytest.raises(InvalidPhone):
            CreateCustomer(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert audit.recorded == []

    def test_no_audit_if_gender_invalid(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        cmd = CustomerCommand(full_name="Awa", gender="invalid")
        with pytest.raises(InvalidCustomerGender):
            CreateCustomer(repo, audit).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        assert audit.recorded == []

    def test_duplicate_phone_same_salon_raises(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        with pytest.raises(CustomerAlreadyExists):
            CreateCustomer(repo, audit).execute(
                _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
            )

    def test_duplicate_phone_no_audit(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        audit.recorded.clear()
        with pytest.raises(CustomerAlreadyExists):
            CreateCustomer(repo, audit).execute(
                _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
            )
        assert audit.recorded == []

    def test_duplicate_phone_no_extra_write(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        first_count = len(repo.created)
        with pytest.raises(CustomerAlreadyExists):
            CreateCustomer(repo, audit).execute(
                _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
            )
        assert len(repo.created) == first_count

    def test_same_phone_different_salon_accepted(self) -> None:
        """Cloisonnement §11.2 : le même numéro peut exister dans un autre salon."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        # Doit réussir dans un salon différent.
        customer_b = CreateCustomer(repo, audit).execute(
            _OTHER_SALON_ID, _VALID_COMMAND, actor_user_id=_ACTOR_ID
        )
        assert customer_b.salon_id == _OTHER_SALON_ID

    def test_race_condition_create_raises_conflict(self) -> None:
        """Filet concurrent : `create` lève directement `CustomerAlreadyExists`."""
        repo = FakeCustomerRepository(raise_conflict=True)
        audit = FakeAuditLog()
        with pytest.raises(CustomerAlreadyExists):
            CreateCustomer(repo, audit).execute(
                _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
            )
        assert audit.recorded == []

    def test_atomicity_no_audit_if_repository_raises(self) -> None:
        class _FailingRepo:
            def phone_exists(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
                return False

            def create(self, _customer):  # type: ignore[no-untyped-def]
                raise RuntimeError("DB failure")

        audit = FakeAuditLog()
        with pytest.raises(RuntimeError):
            CreateCustomer(_FailingRepo(), audit).execute(  # type: ignore[arg-type]
                _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
            )
        assert audit.recorded == []


# ---------------------------------------------------------------------------
# GetCustomer
# ---------------------------------------------------------------------------


class TestGetCustomer:
    def test_raises_customer_not_found_for_unknown_id(self) -> None:
        repo = FakeCustomerRepository()
        with pytest.raises(CustomerNotFound):
            GetCustomer(repo).execute(_SALON_ID, uuid.uuid4())

    def test_returns_customer_when_found(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        result = GetCustomer(repo).execute(_SALON_ID, customer.id)
        assert result.id == customer.id

    def test_raises_when_customer_belongs_to_other_salon(self) -> None:
        """Isolation §11.2 : fiche d'un autre salon indiscernable d'une fiche inexistante."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = CreateCustomer(repo, audit).execute(
            _OTHER_SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        with pytest.raises(CustomerNotFound):
            GetCustomer(repo).execute(_SALON_ID, customer.id)


# ---------------------------------------------------------------------------
# ListSalonCustomers
# ---------------------------------------------------------------------------


class TestListSalonCustomers:
    def test_empty_repository_returns_empty_page(self) -> None:
        repo = FakeCustomerRepository()
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, limit=50, offset=0)
        assert page == ()
        assert total == 0

    def test_returns_customers_for_correct_salon(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, limit=50, offset=0)
        assert len(page) == 1
        assert total == 1
        assert page[0].salon_id == _SALON_ID

    def test_does_not_return_other_salon_customers(self) -> None:
        """Isolation §11.2 : le gérant ne voit que les fiches de son salon."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        page, total = ListSalonCustomers(repo).execute(
            _OTHER_SALON_ID, limit=50, offset=0
        )
        assert page == ()
        assert total == 0

    def test_total_is_independent_of_limit(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        for i in range(5):
            cmd = CustomerCommand(full_name=f"Client {i}")
            CreateCustomer(repo, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, limit=2, offset=0)
        assert len(page) == 2
        assert total == 5

    def test_offset_respected(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        for i in range(3):
            cmd = CustomerCommand(full_name=f"Client {i}")
            CreateCustomer(repo, audit).execute(
                _SALON_ID, cmd, actor_user_id=_ACTOR_ID
            )
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, limit=50, offset=2)
        assert len(page) == 1
        assert total == 3

    def test_multiple_salons_independent_totals(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, CustomerCommand(full_name="A"), actor_user_id=_ACTOR_ID
        )
        CreateCustomer(repo, audit).execute(
            _SALON_ID, CustomerCommand(full_name="B"), actor_user_id=_ACTOR_ID
        )
        CreateCustomer(repo, audit).execute(
            _OTHER_SALON_ID, CustomerCommand(full_name="C"), actor_user_id=_ACTOR_ID
        )
        _, total_a = ListSalonCustomers(repo).execute(_SALON_ID, limit=50, offset=0)
        _, total_b = ListSalonCustomers(repo).execute(_OTHER_SALON_ID, limit=50, offset=0)
        assert total_a == 2
        assert total_b == 1
