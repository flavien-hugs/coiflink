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

import datetime
import decimal

from coiflink_api.application.customers import (
    CreateCustomer,
    CustomerCommand,
    GetCustomer,
    GetCustomerVisitHistory,
    ListSalonCustomers,
)
from coiflink_api.domain.audit import AuditAction, AuditEntry, ENTITY_TYPE_CUSTOMER
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import (
    CustomerAlreadyExists,
    CustomerNotFound,
    InvalidCustomerGender,
    InvalidCustomerName,
    InvalidPhone,
)
from coiflink_api.domain.visit import HISTORY_STATUSES, CustomerVisit, VisitService

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


# ---------------------------------------------------------------------------
# GetCustomerVisitHistory (US-4.2, #29)
# ---------------------------------------------------------------------------

_SERVICE_ID_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SERVICE_ID_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_APT_ID_1 = uuid.UUID("11111111-1111-0000-0000-000000000001")
_APT_ID_2 = uuid.UUID("22222222-2222-0000-0000-000000000002")

_DATE_RECENT = datetime.date(2026, 7, 20)
_DATE_OLDER = datetime.date(2026, 6, 15)
_TIME_09 = datetime.time(9, 0, 0)
_TIME_10 = datetime.time(10, 0, 0)


def _make_completed_visit(
    appointment_id: uuid.UUID,
    date: datetime.date = _DATE_RECENT,
    price: str = "5000.00",
) -> CustomerVisit:
    svc = VisitService(
        service_id=_SERVICE_ID_A,
        name="Coupe homme",
        price_at_booking=decimal.Decimal(price),
    )
    return CustomerVisit(
        appointment_id=appointment_id,
        date=date,
        start_time=_TIME_09,
        end_time=_TIME_10,
        status=AppointmentStatus.COMPLETED.value,
        services=(svc,),
        total_amount=decimal.Decimal(price),
    )


def _make_visit_with_status(status: str, appointment_id: uuid.UUID) -> CustomerVisit:
    svc = VisitService(
        service_id=_SERVICE_ID_A,
        name="Prestation",
        price_at_booking=decimal.Decimal("1000.00"),
    )
    return CustomerVisit(
        appointment_id=appointment_id,
        date=_DATE_RECENT,
        start_time=_TIME_09,
        end_time=_TIME_10,
        status=status,
        services=(svc,),
        total_amount=decimal.Decimal("1000.00"),
    )


class TestGetCustomerVisitHistory:
    def _create_customer(
        self, repo: FakeCustomerRepository, salon_id: uuid.UUID
    ) -> object:
        audit = FakeAuditLog()
        return CreateCustomer(repo, audit).execute(
            salon_id, CustomerCommand(full_name="Awa Koné"), actor_user_id=_ACTOR_ID
        )

    def test_raises_not_found_for_unknown_customer(self) -> None:
        repo = FakeCustomerRepository()
        with pytest.raises(CustomerNotFound):
            GetCustomerVisitHistory(repo).execute(_SALON_ID, uuid.uuid4())

    def test_raises_not_found_for_customer_in_other_salon(self) -> None:
        """Isolation §11.2 : fiche d'un autre salon indiscernable d'une inexistante."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _OTHER_SALON_ID)
        with pytest.raises(CustomerNotFound):
            GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)

    def test_walk_in_customer_returns_empty_history(self) -> None:
        """Fiche walk-in (aucune visite amorçée) → historique vide (comportement normal)."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert history.visits == ()
        assert history.total_visits == 0
        assert history.last_visit_at is None

    def test_walk_in_total_amount_is_zero(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert history.total_amount == decimal.Decimal("0")

    def test_only_completed_visits_returned(self) -> None:
        """Seules les visites `COMPLETED` apparaissent — pas PENDING/CONFIRMED/CANCELLED/NO_SHOW."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        completed = _make_completed_visit(_APT_ID_1)
        pending = _make_visit_with_status(AppointmentStatus.PENDING.value, _APT_ID_2)
        # Le fake reproduit le filtre du dépôt SQL sur `statuses`.
        repo.set_visits(customer.id, (completed, pending))
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        ids = [v.appointment_id for v in history.visits]
        assert _APT_ID_1 in ids
        assert _APT_ID_2 not in ids

    def test_cancelled_visit_excluded(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        cancelled = _make_visit_with_status(AppointmentStatus.CANCELLED.value, _APT_ID_2)
        repo.set_visits(customer.id, (cancelled,))
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert history.visits == ()

    def test_no_show_visit_excluded(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        no_show = _make_visit_with_status(AppointmentStatus.NO_SHOW.value, _APT_ID_2)
        repo.set_visits(customer.id, (no_show,))
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert history.visits == ()

    def test_statuses_passed_to_repository_is_history_statuses(self) -> None:
        """Le cas d'usage passe exactement `HISTORY_STATUSES` au dépôt."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert repo.last_visits_call is not None
        _, _, statuses = repo.last_visits_call
        assert statuses == HISTORY_STATUSES

    def test_total_visits_matches_number_of_completed(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        visit1 = _make_completed_visit(_APT_ID_1, date=_DATE_RECENT, price="5000.00")
        visit2 = _make_completed_visit(_APT_ID_2, date=_DATE_OLDER, price="2000.00")
        repo.set_visits(customer.id, (visit1, visit2))
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert history.total_visits == 2

    def test_total_amount_is_sum_of_price_at_booking(self) -> None:
        """Le montant est la somme des `price_at_booking` figés, pas le tarif courant."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        visit1 = _make_completed_visit(_APT_ID_1, price="5000.00")
        visit2 = _make_completed_visit(_APT_ID_2, price="2000.00")
        repo.set_visits(customer.id, (visit1, visit2))
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert history.total_amount == decimal.Decimal("7000.00")

    def test_last_visit_at_is_most_recent_visit_datetime(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        visit_recent = _make_completed_visit(_APT_ID_1, date=_DATE_RECENT)
        visit_older = _make_completed_visit(_APT_ID_2, date=_DATE_OLDER)
        # Most-recent-first order (as returned by SQL ORDER BY date DESC).
        repo.set_visits(customer.id, (visit_recent, visit_older))
        history = GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        expected = datetime.datetime.combine(_DATE_RECENT, _TIME_09)
        assert history.last_visit_at == expected

    def test_repository_call_uses_correct_salon_and_customer_ids(self) -> None:
        """Défense en profondeur §11.2 : `salon_id` est transmis au dépôt."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        GetCustomerVisitHistory(repo).execute(_SALON_ID, customer.id)
        assert repo.last_visits_call is not None
        salon_arg, customer_arg, _ = repo.last_visits_call
        assert salon_arg == _SALON_ID
        assert customer_arg == customer.id

    def test_not_found_raised_before_visits_query(self) -> None:
        """CustomerNotFound est levée avant tout appel `list_visits` (économie de requête)."""
        repo = FakeCustomerRepository()
        with pytest.raises(CustomerNotFound):
            GetCustomerVisitHistory(repo).execute(_SALON_ID, uuid.uuid4())
        assert repo.last_visits_call is None
