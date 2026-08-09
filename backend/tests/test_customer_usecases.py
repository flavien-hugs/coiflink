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
    GetCustomerPaymentHistory,
    GetCustomerServiceStats,
    GetCustomerVisitHistory,
    ListSalonCustomers,
    UpdateCustomer,
    UpdateCustomerNote,
)
from coiflink_api.domain.audit import AuditAction, AuditEntry, ENTITY_TYPE_CUSTOMER
from coiflink_api.domain.customer import CustomerFilter
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import (
    CustomerAlreadyExists,
    CustomerNotFound,
    InvalidCustomerGender,
    InvalidCustomerName,
    InvalidCustomerNotes,
    InvalidPhone,
)
from coiflink_api.domain.visit import (
    HISTORY_STATUSES,
    CustomerPayment,
    CustomerVisit,
    VisitService,
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

# Filtre vide (pas de contrainte) — mirroir de `_NO_FILTER` des tests de transactions.
_NO_FILTER = CustomerFilter()


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
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=50, offset=0)
        assert page == ()
        assert total == 0

    def test_returns_customers_for_correct_salon(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        CreateCustomer(repo, audit).execute(
            _SALON_ID, _MIN_COMMAND, actor_user_id=_ACTOR_ID
        )
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=50, offset=0)
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
            _OTHER_SALON_ID, filter=_NO_FILTER, limit=50, offset=0
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
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=2, offset=0)
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
        page, total = ListSalonCustomers(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=50, offset=2)
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
        _, total_a = ListSalonCustomers(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=50, offset=0)
        _, total_b = ListSalonCustomers(repo).execute(_OTHER_SALON_ID, filter=_NO_FILTER, limit=50, offset=0)
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

_PAYMENT_ID_1 = uuid.UUID("55555555-5555-0000-0000-000000000005")
_PAYMENT_ID_2 = uuid.UUID("66666666-6666-0000-0000-000000000006")
_PAYMENT_CREATED_AT = datetime.datetime(2026, 7, 20, 9, 30, tzinfo=datetime.timezone.utc)


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


# ---------------------------------------------------------------------------
# GetCustomerPaymentHistory (fiche client)
# ---------------------------------------------------------------------------


def _make_payment(
    payment_id: uuid.UUID,
    *,
    created_at: datetime.datetime = _PAYMENT_CREATED_AT,
    amount: str = "5000.00",
    status: str = "VALIDATED",
) -> CustomerPayment:
    return CustomerPayment(
        payment_id=payment_id,
        created_at=created_at,
        amount=decimal.Decimal(amount),
        currency="XOF",
        status=status,
    )


class TestGetCustomerPaymentHistory:
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
            GetCustomerPaymentHistory(repo).execute(_SALON_ID, uuid.uuid4())

    def test_raises_not_found_for_customer_in_other_salon(self) -> None:
        """Isolation §11.2 : fiche d'un autre salon indiscernable d'une inexistante."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _OTHER_SALON_ID)
        with pytest.raises(CustomerNotFound):
            GetCustomerPaymentHistory(repo).execute(_SALON_ID, customer.id)

    def test_walk_in_customer_returns_empty_payments(self) -> None:
        """Fiche walk-in (aucun paiement amorcé) → liste vide (comportement normal)."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        payments = GetCustomerPaymentHistory(repo).execute(_SALON_ID, customer.id)
        assert payments == ()

    def test_returns_payments_set_on_repository(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        payment = _make_payment(_PAYMENT_ID_1)
        repo.set_payments(customer.id, (payment,))
        payments = GetCustomerPaymentHistory(repo).execute(_SALON_ID, customer.id)
        assert payments == (payment,)

    def test_all_statuses_returned_unfiltered(self) -> None:
        """Contrairement aux visites, le use case ne filtre aucun statut de paiement."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        validated = _make_payment(_PAYMENT_ID_1, status="VALIDATED")
        pending = _make_payment(_PAYMENT_ID_2, status="PENDING")
        repo.set_payments(customer.id, (validated, pending))
        payments = GetCustomerPaymentHistory(repo).execute(_SALON_ID, customer.id)
        statuses = {p.status for p in payments}
        assert statuses == {"VALIDATED", "PENDING"}

    def test_not_found_raised_before_payments_query(self) -> None:
        """`CustomerNotFound` levée avant tout appel `list_payments` (économie de requête)."""
        repo = FakeCustomerRepository()
        with pytest.raises(CustomerNotFound):
            GetCustomerPaymentHistory(repo).execute(_SALON_ID, uuid.uuid4())


# ---------------------------------------------------------------------------
# GetCustomerServiceStats (US-4.3, #31)
# ---------------------------------------------------------------------------


_SERVICE_ID_C = uuid.UUID("cccccccc-cccc-0000-0000-000000000003")
_APT_ID_3 = uuid.UUID("33333333-3333-0000-0000-000000000003")
_APT_ID_4 = uuid.UUID("44444444-4444-0000-0000-000000000004")


def _make_completed_visit_with_services(
    appointment_id: uuid.UUID,
    services_data: list[tuple[uuid.UUID, str, str]],
    date: datetime.date = _DATE_RECENT,
) -> CustomerVisit:
    """Crée une visite COMPLETED avec les prestations (service_id, nom, prix)."""
    services = tuple(
        VisitService(
            service_id=sid,
            name=name,
            price_at_booking=decimal.Decimal(price),
        )
        for sid, name, price in services_data
    )
    total = sum((decimal.Decimal(p) for _, _, p in services_data), decimal.Decimal("0"))
    return CustomerVisit(
        appointment_id=appointment_id,
        date=date,
        start_time=_TIME_09,
        end_time=_TIME_10,
        status=AppointmentStatus.COMPLETED.value,
        services=services,
        total_amount=total,
    )


class TestGetCustomerServiceStats:
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
            GetCustomerServiceStats(repo).execute(_SALON_ID, uuid.uuid4())

    def test_raises_not_found_for_customer_in_other_salon(self) -> None:
        """Isolation §11.2 : fiche d'un autre salon indiscernable d'une inexistante."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _OTHER_SALON_ID)
        with pytest.raises(CustomerNotFound):
            GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)

    def test_walk_in_returns_empty_services(self) -> None:
        """Fiche walk-in (aucune visite COMPLETED) → classement vide (comportement normal)."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.services == ()

    def test_walk_in_total_visits_is_zero(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.total_visits == 0

    def test_walk_in_total_services_is_zero(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.total_services == 0

    def test_walk_in_currency_is_xof(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.currency == "XOF"

    def test_statuses_passed_to_repository_is_history_statuses(self) -> None:
        """Le cas d'usage passe exactement `HISTORY_STATUSES` au dépôt (filtre COMPLETED)."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert repo.last_visits_call is not None
        _, _, statuses = repo.last_visits_call
        assert statuses == HISTORY_STATUSES

    def test_repository_call_uses_correct_salon_and_customer_ids(self) -> None:
        """Défense en profondeur §11.2 : `salon_id` et `customer_id` sont transmis au dépôt."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert repo.last_visits_call is not None
        salon_arg, customer_arg, _ = repo.last_visits_call
        assert salon_arg == _SALON_ID
        assert customer_arg == customer.id

    def test_not_found_raised_before_visits_query(self) -> None:
        """CustomerNotFound est levée avant tout appel `list_visits`."""
        repo = FakeCustomerRepository()
        with pytest.raises(CustomerNotFound):
            GetCustomerServiceStats(repo).execute(_SALON_ID, uuid.uuid4())
        assert repo.last_visits_call is None

    def test_only_completed_visits_counted(self) -> None:
        """Seules les visites `COMPLETED` sont comptabilisées — PENDING/CANCELLED exclus."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        completed = _make_completed_visit_with_services(
            _APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")]
        )
        pending = _make_visit_with_status(AppointmentStatus.PENDING.value, _APT_ID_2)
        cancelled = _make_visit_with_status(AppointmentStatus.CANCELLED.value, _APT_ID_3)
        repo.set_visits(customer.id, (completed, pending, cancelled))
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        # Seul le COMPLETED compte : un service, count=1.
        assert len(stats.services) == 1
        assert stats.services[0].count == 1
        assert stats.total_visits == 1
        assert stats.total_services == 1

    def test_no_show_visit_excluded(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        no_show = _make_visit_with_status(AppointmentStatus.NO_SHOW.value, _APT_ID_2)
        repo.set_visits(customer.id, (no_show,))
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.services == ()
        assert stats.total_visits == 0

    def test_multiple_visits_aggregated(self) -> None:
        """Plusieurs visites COMPLETED → services agrégés par fréquence."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        v1 = _make_completed_visit_with_services(
            _APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")]
        )
        v2 = _make_completed_visit_with_services(
            _APT_ID_2,
            [(_SERVICE_ID_A, "Coupe homme", "5000.00"), (_SERVICE_ID_B, "Barbe", "2000.00")],
            date=_DATE_OLDER,
        )
        repo.set_visits(customer.id, (v1, v2))
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.total_visits == 2
        assert stats.total_services == 3
        # Coupe homme (count=2) avant Barbe (count=1).
        assert stats.services[0].service_id == _SERVICE_ID_A
        assert stats.services[0].count == 2
        assert stats.services[1].service_id == _SERVICE_ID_B
        assert stats.services[1].count == 1

    def test_total_amount_is_sum_of_price_at_booking(self) -> None:
        """Montants = somme des `price_at_booking` figés, pas le tarif courant."""
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        v1 = _make_completed_visit_with_services(
            _APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")]
        )
        v2 = _make_completed_visit_with_services(
            _APT_ID_2, [(_SERVICE_ID_A, "Coupe homme", "6000.00")]
        )
        repo.set_visits(customer.id, (v1, v2))
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert stats.services[0].total_amount == decimal.Decimal("11000.00")

    def test_total_amount_is_decimal_not_float(self) -> None:
        repo = FakeCustomerRepository()
        customer = self._create_customer(repo, _SALON_ID)
        visit = _make_completed_visit_with_services(
            _APT_ID_1, [(_SERVICE_ID_A, "Coupe", "5000.00")]
        )
        repo.set_visits(customer.id, (visit,))
        stats = GetCustomerServiceStats(repo).execute(_SALON_ID, customer.id)
        assert isinstance(stats.services[0].total_amount, decimal.Decimal)


# ---------------------------------------------------------------------------
# UpdateCustomerNote (US-4.5, #32)
# ---------------------------------------------------------------------------


class TestUpdateCustomerNote:
    def _create_customer(
        self, repo: FakeCustomerRepository, salon_id: uuid.UUID = _SALON_ID
    ) -> object:
        audit = FakeAuditLog()
        return CreateCustomer(repo, audit).execute(
            salon_id, CustomerCommand(full_name="Awa Koné"), actor_user_id=_ACTOR_ID
        )

    def test_update_returns_customer_with_new_note(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "Allergie réactif X.", actor_user_id=_ACTOR_ID
        )
        assert result.notes == "Allergie réactif X."

    def test_audit_action_is_customer_note_updated(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
        )
        # Seule l'entrée de l'édition de note est enregistrée (la création a son propre log).
        note_entries = [
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        ]
        assert len(note_entries) == 1

    def test_audit_actor_user_id_correct(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
        )
        entry = next(
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        )
        assert entry.actor_user_id == _ACTOR_ID

    def test_audit_salon_id_correct(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
        )
        entry = next(
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        )
        assert entry.salon_id == _SALON_ID

    def test_audit_entity_type_is_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
        )
        entry = next(
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        )
        assert entry.entity_type == ENTITY_TYPE_CUSTOMER

    def test_audit_entity_id_matches_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
        )
        entry = next(
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        )
        assert entry.entity_id == customer.id

    def test_audit_metadata_is_empty_dict(self) -> None:
        """Invariant §11.3 : ni contenu, ni ancienne valeur dans le journal."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "Allergie réactif X.", actor_user_id=_ACTOR_ID
        )
        entry = next(
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        )
        assert entry.metadata == {}

    def test_audit_metadata_contains_no_pii(self) -> None:
        """Ni le contenu de la note ni l'ancienne valeur n'entrent au journal (§11.3)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "Allergie réactif X.", actor_user_id=_ACTOR_ID
        )
        entry = next(
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        )
        forbidden_keys = {"notes", "note", "content", "value", "old", "new", "previous"}
        assert not forbidden_keys & set(entry.metadata.keys())

    def test_whitespace_note_erases(self) -> None:
        """Note blanche normalisée en `None` : efface la note (§ effacement)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "   ", actor_user_id=_ACTOR_ID
        )
        assert result.notes is None

    def test_empty_string_note_erases(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "", actor_user_id=_ACTOR_ID
        )
        assert result.notes is None

    def test_null_note_erases(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, None, actor_user_id=_ACTOR_ID
        )
        assert result.notes is None

    def test_note_trimmed(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "  note avec espaces  ", actor_user_id=_ACTOR_ID
        )
        assert result.notes == "note avec espaces"

    def test_note_too_long_raises_invalid(self) -> None:
        """Note > 2000 → `InvalidCustomerNotes`, aucune écriture, aucun audit."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        with pytest.raises(InvalidCustomerNotes):
            UpdateCustomerNote(repo, audit).execute(
                _SALON_ID, customer.id, "A" * 2001, actor_user_id=_ACTOR_ID
            )

    def test_note_too_long_no_audit(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        with pytest.raises(InvalidCustomerNotes):
            UpdateCustomerNote(repo, audit).execute(
                _SALON_ID, customer.id, "A" * 2001, actor_user_id=_ACTOR_ID
            )
        note_entries = [
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        ]
        assert note_entries == []

    def test_unknown_customer_raises_not_found(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        with pytest.raises(CustomerNotFound):
            UpdateCustomerNote(repo, audit).execute(
                _SALON_ID, uuid.uuid4(), "note", actor_user_id=_ACTOR_ID
            )

    def test_other_salon_customer_raises_not_found(self) -> None:
        """Isolation §11.2 : fiche d'un autre salon indiscernable d'une inexistante."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, _OTHER_SALON_ID)
        with pytest.raises(CustomerNotFound):
            UpdateCustomerNote(repo, audit).execute(
                _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
            )

    def test_not_found_no_audit(self) -> None:
        """Aucune trace d'audit si la fiche est hors salon/inconnue (§11.3)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        audit.recorded.clear()
        with pytest.raises(CustomerNotFound):
            UpdateCustomerNote(repo, audit).execute(
                _SALON_ID, uuid.uuid4(), "note", actor_user_id=_ACTOR_ID
            )
        note_entries = [
            e for e in audit.recorded
            if e.action == AuditAction.CUSTOMER_NOTE_UPDATED.value
        ]
        assert note_entries == []

    def test_salon_id_comes_from_scope_argument(self) -> None:
        """Invariant anti-élévation : `salon_id` vient de l'argument, jamais d'un corps."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomerNote(repo, audit).execute(
            _SALON_ID, customer.id, "note", actor_user_id=_ACTOR_ID
        )
        assert result.salon_id == _SALON_ID


# ---------------------------------------------------------------------------
# UpdateCustomer (US-4.6, #144)
# ---------------------------------------------------------------------------


class TestUpdateCustomer:
    """Cas d'usage US-4.6 — édition de l'identité d'une fiche client.

    Garanties testées :
    - `salon_id` du paramètre de portée est utilisé (anti-élévation).
    - Seuls `full_name`, `phone`, `gender` sont édités ; `notes` est préservée.
    - L'audit enregistre `CUSTOMER_UPDATED` une fois, avec acteur/salon/entité corrects.
    - `metadata["changed"]` ne contient que les **noms** des champs modifiés,
      jamais leurs valeurs (§11.3/§11.4 — PII-neutral).
    - Numéro inchangé : pas de faux 409 contre soi-même.
    - Numéro changé, slot libre : succès ; pris par une autre fiche → 409, pas d'audit.
    - Effacement : `phone=""` / `None` → `None` ; `gender=""` / `None` → `None`.
    - Validation avant écriture : erreurs ne produisent aucune écriture ni audit.
    - Fiche inconnue ou d'un autre salon → `CustomerNotFound`, pas d'audit (§11.2).
    """

    def _create_customer(
        self,
        repo: FakeCustomerRepository,
        audit: FakeAuditLog | None = None,
        salon_id: uuid.UUID = _SALON_ID,
        *,
        full_name: str = "Awa Koné",
        phone: str | None = "0700000000",
        gender: str | None = "FEMALE",
        notes: str | None = "Note privée.",
    ) -> object:
        if audit is None:
            audit = FakeAuditLog()
        return CreateCustomer(repo, audit).execute(
            salon_id,
            CustomerCommand(full_name=full_name, phone=phone, gender=gender, notes=notes),
            actor_user_id=_ACTOR_ID,
        )

    # -- Cas nominal --------------------------------------------------------

    def test_nominal_returns_updated_fields(self) -> None:
        """Mise à jour complète : les trois champs d'identité sont reflétés."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo", phone="0700111111", gender="MALE"),
            actor_user_id=_ACTOR_ID,
        )
        assert result.full_name == "Aminata Diallo"
        assert result.phone == "+2250700111111"
        assert result.gender == "MALE"

    def test_salon_id_preserved_from_scope(self) -> None:
        """Invariant anti-élévation : `salon_id` du résultat = argument de portée."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        assert result.salon_id == _SALON_ID

    def test_full_name_trimmed(self) -> None:
        """Le nom est normalisé (espaces en bordure supprimés)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="  Aminata Diallo  "),
            actor_user_id=_ACTOR_ID,
        )
        assert result.full_name == "Aminata Diallo"

    # -- Notes préservées ---------------------------------------------------

    def test_notes_unchanged_after_identity_edit(self) -> None:
        """Invariant #144 : la note privée n'est jamais touchée par l'édition d'identité."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, notes="Note privée.")
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo", phone=None, gender=None),
            actor_user_id=_ACTOR_ID,
        )
        assert result.notes == "Note privée."

    # -- Audit CUSTOMER_UPDATED (§11.3/§11.4) ------------------------------

    def test_audit_recorded_once(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        updated_entries = [
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        ]
        assert len(updated_entries) == 1

    def test_audit_action_is_customer_updated(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert entry.action == AuditAction.CUSTOMER_UPDATED.value

    def test_audit_actor_user_id(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert entry.actor_user_id == _ACTOR_ID

    def test_audit_salon_id(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert entry.salon_id == _SALON_ID

    def test_audit_entity_type_is_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert entry.entity_type == ENTITY_TYPE_CUSTOMER

    def test_audit_entity_id_matches_customer(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert str(entry.entity_id) == str(customer.id)

    # -- Métadonnées PII-neutrales ------------------------------------------

    def test_audit_metadata_has_changed_key(self) -> None:
        """Diff neutre : `metadata` contient uniquement la clé `changed`."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert "changed" in entry.metadata

    def test_audit_metadata_changed_are_field_names_only(self) -> None:
        """§11.3/§11.4 : seuls les noms de champs admis (`full_name|phone|gender`)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, phone="0700111000", gender="FEMALE")
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo", phone="0700222000", gender="MALE"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        allowed = {"full_name", "phone", "gender"}
        for item in entry.metadata["changed"]:
            assert item in allowed, f"Valeur inattendue dans metadata['changed']: {item!r}"

    def test_audit_metadata_contains_no_pii_values(self) -> None:
        """§11.3/§11.4 : aucune valeur d'identité dans metadata (nom, numéro, genre)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, phone="0700111000", gender="FEMALE")
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo", phone="0700222999", gender="MALE"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        serialized = str(entry.metadata)
        assert "Aminata" not in serialized
        assert "Diallo" not in serialized
        assert "0700222999" not in serialized
        assert "+225" not in serialized
        assert "MALE" not in serialized

    def test_changed_includes_full_name_when_modified(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, full_name="Awa Koné")
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo", phone="0700000000", gender="FEMALE"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert "full_name" in entry.metadata["changed"]

    def test_changed_omits_unchanged_phone_and_gender(self) -> None:
        """Téléphone et genre inchangés → absents de `changed`."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(
            repo, full_name="Awa Koné", phone="0700000000", gender="FEMALE"
        )
        audit.recorded.clear()
        # Seul le nom change ; phone/genre identiques après normalisation.
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Aminata Diallo", phone="0700000000", gender="FEMALE"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert "phone" not in entry.metadata["changed"]
        assert "gender" not in entry.metadata["changed"]

    def test_changed_is_empty_when_nothing_changes(self) -> None:
        """Aucun champ modifié → `changed == []` ; l'audit est quand même enregistré."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(
            repo, full_name="Awa Koné", phone="0700000000", gender="FEMALE"
        )
        audit.recorded.clear()
        UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné", phone="0700000000", gender="FEMALE"),
            actor_user_id=_ACTOR_ID,
        )
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert entry.metadata["changed"] == []

    # -- Unicité du numéro --------------------------------------------------

    def test_unchanged_phone_no_false_409(self) -> None:
        """Numéro inchangé : pas de faux 409 contre soi-même (invariant d'identité)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, phone="0700000000")
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné Bis", phone="0700000000"),
            actor_user_id=_ACTOR_ID,
        )
        assert result.phone == "+2250700000000"

    def test_changed_phone_free_slot_succeeds(self) -> None:
        """Nouveau numéro libre → succès ; `phone` dans `changed`."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, phone="0700000001")
        audit.recorded.clear()
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné", phone="0700999999"),
            actor_user_id=_ACTOR_ID,
        )
        assert result.phone == "+2250700999999"
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert "phone" in entry.metadata["changed"]

    def test_changed_phone_conflict_raises(self) -> None:
        """Numéro déjà fiché par une **autre** fiche du salon → `CustomerAlreadyExists`."""
        repo = FakeCustomerRepository()
        customer_a = self._create_customer(repo, phone="0700000001")
        self._create_customer(repo, phone="0700000002")
        audit = FakeAuditLog()
        with pytest.raises(CustomerAlreadyExists):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer_a.id,
                CustomerCommand(full_name="Awa Koné", phone="0700000002"),
                actor_user_id=_ACTOR_ID,
            )

    def test_changed_phone_conflict_no_audit(self) -> None:
        """Conflit de numéro → aucune trace `CUSTOMER_UPDATED` dans l'audit."""
        repo = FakeCustomerRepository()
        customer_a = self._create_customer(repo, phone="0700000001")
        self._create_customer(repo, phone="0700000002")
        audit = FakeAuditLog()
        with pytest.raises(CustomerAlreadyExists):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer_a.id,
                CustomerCommand(full_name="Awa Koné", phone="0700000002"),
                actor_user_id=_ACTOR_ID,
            )
        assert not any(
            e.action == AuditAction.CUSTOMER_UPDATED.value for e in audit.recorded
        )

    def test_same_phone_other_salon_no_conflict(self) -> None:
        """Cloisonnement §11.2 : numéro pris dans un **autre** salon → aucun conflit ici."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer_a = self._create_customer(repo, salon_id=_SALON_ID, phone="0700000001")
        # Fiche B dans l'autre salon avec le numéro qu'on veut attribuer à A.
        self._create_customer(repo, salon_id=_OTHER_SALON_ID, phone="0700000002")
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer_a.id,
            CustomerCommand(full_name="Awa Koné", phone="0700000002"),
            actor_user_id=_ACTOR_ID,
        )
        assert result.phone == "+2250700000002"

    # -- Effacement (erasure) -----------------------------------------------

    def test_erase_phone_with_none(self) -> None:
        """`phone=None` → NULL en base ; `phone` apparaît dans `changed`."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, phone="0700000000")
        audit.recorded.clear()
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné", phone=None, gender="FEMALE"),
            actor_user_id=_ACTOR_ID,
        )
        assert result.phone is None
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert "phone" in entry.metadata["changed"]

    def test_erase_phone_with_empty_string(self) -> None:
        """`phone=""` normalisé en `None` → effacement du champ."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, phone="0700000000")
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné", phone=""),
            actor_user_id=_ACTOR_ID,
        )
        assert result.phone is None

    def test_erase_gender_with_none(self) -> None:
        """`gender=None` → NULL en base ; `gender` apparaît dans `changed`."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, gender="FEMALE")
        audit.recorded.clear()
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné", gender=None),
            actor_user_id=_ACTOR_ID,
        )
        assert result.gender is None
        entry = next(
            e for e in audit.recorded if e.action == AuditAction.CUSTOMER_UPDATED.value
        )
        assert "gender" in entry.metadata["changed"]

    def test_erase_gender_with_empty_string(self) -> None:
        """`gender=""` normalisé en `None` → effacement du champ."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, gender="FEMALE")
        result = UpdateCustomer(repo, audit).execute(
            _SALON_ID,
            customer.id,
            CustomerCommand(full_name="Awa Koné", gender=""),
            actor_user_id=_ACTOR_ID,
        )
        assert result.gender is None

    # -- Validation (avant toute écriture) ----------------------------------

    def test_invalid_name_empty_raises(self) -> None:
        """Nom vide → `InvalidCustomerName` sans écriture."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        with pytest.raises(InvalidCustomerName):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer.id,
                CustomerCommand(full_name=""),
                actor_user_id=_ACTOR_ID,
            )

    def test_invalid_name_no_audit(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        audit.recorded.clear()
        with pytest.raises(InvalidCustomerName):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer.id,
                CustomerCommand(full_name=""),
                actor_user_id=_ACTOR_ID,
            )
        assert not any(
            e.action == AuditAction.CUSTOMER_UPDATED.value for e in audit.recorded
        )

    def test_invalid_phone_raises(self) -> None:
        """Téléphone malformé → `InvalidPhone` sans écriture."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        with pytest.raises(InvalidPhone):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer.id,
                CustomerCommand(full_name="Awa Koné", phone="not-a-phone"),
                actor_user_id=_ACTOR_ID,
            )

    def test_invalid_gender_raises(self) -> None:
        """Genre hors énumération → `InvalidCustomerGender` sans écriture."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo)
        with pytest.raises(InvalidCustomerGender):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer.id,
                CustomerCommand(full_name="Awa Koné", gender="INVALID"),
                actor_user_id=_ACTOR_ID,
            )

    # -- Isolation §11.2 ----------------------------------------------------

    def test_unknown_customer_raises_not_found(self) -> None:
        """Fiche inconnue → `CustomerNotFound`."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        with pytest.raises(CustomerNotFound):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                uuid.uuid4(),
                CustomerCommand(full_name="Awa Koné"),
                actor_user_id=_ACTOR_ID,
            )

    def test_customer_from_other_salon_raises_not_found(self) -> None:
        """Isolation §11.2 : fiche d'un autre salon indiscernable d'une inexistante."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        customer = self._create_customer(repo, salon_id=_OTHER_SALON_ID)
        with pytest.raises(CustomerNotFound):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                customer.id,
                CustomerCommand(full_name="Awa Koné"),
                actor_user_id=_ACTOR_ID,
            )

    def test_not_found_no_audit(self) -> None:
        """Aucune trace d'audit si la fiche est hors salon/inconnue (§11.3)."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        with pytest.raises(CustomerNotFound):
            UpdateCustomer(repo, audit).execute(
                _SALON_ID,
                uuid.uuid4(),
                CustomerCommand(full_name="Awa Koné"),
                actor_user_id=_ACTOR_ID,
            )
        assert not any(
            e.action == AuditAction.CUSTOMER_UPDATED.value for e in audit.recorded
        )
