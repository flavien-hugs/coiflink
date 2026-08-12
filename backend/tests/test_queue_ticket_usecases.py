"""Tests applicatifs — cas d'usage walk-in (US-8.3, #157).

Utilise les fakes de `conftest.py` (aucune I/O, aucun réseau) : miroir
`test_queue_usecases.py` pour la file de RDV (#150).

Couvre :
- `JoinQueue` : numérotation séquentielle par salon+jour, anonymat, fiche hors
  salon, prestation vide/hors salon, formule ETA (file vide, file non vide, 0
  coiffeuses actives, repli sur durées propres).
- `StartQueueTicket` : ticket hors salon/inexistant, ticket non-`waiting`, coiffeuse
  hors salon, succès, audit `QUEUE_TICKET_STARTED` exactement une fois avec
  `metadata={}`.
- `CompleteQueueTicket` : ticket non-`in_progress`, ticket hors salon, succès, audit
  `QUEUE_TICKET_COMPLETED`.
- `ListSalonQueueTickets` : retourne uniquement les tickets actifs du salon/jour,
  triés `ticket_number` ; exclut `expired` et les tickets d'autres salons/jours.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.application.queue_ticket import (
    CompleteQueueTicket,
    JoinQueue,
    JoinQueueCommand,
    ListSalonQueueTickets,
    StartQueueTicket,
)
from coiflink_api.domain.audit import AuditAction, ENTITY_TYPE_QUEUE_TICKET
from coiflink_api.domain.errors import (
    HairdresserNotInSalon,
    InvalidQueueTicketServices,
    InvalidQueueTicketTransition,
    QueueTicketNotFound,
)
from coiflink_api.domain.queue_ticket import DEFAULT_WAIT_MINUTES_NO_STAFF, QueueTicket

from .conftest import (
    FakeAuditLog,
    FakeCustomerRepository,
    FakeQueueTicketRepository,
    FakeSalonCatalogRepository,
    FakeSalonScopeRepository,
    _CREATED_AT,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_A = uuid.UUID("aa000000-0000-0000-0000-000000000001")
_SALON_B = uuid.UUID("bb000000-0000-0000-0000-000000000002")
_ACTOR_ID = uuid.UUID("ac000000-0000-0000-0000-000000000001")
_HAIRDRESSER_ID = uuid.UUID("aa000000-0000-0000-0000-000000000003")
_TICKET_ID = uuid.UUID("cc000000-0000-0000-0000-000000000001")
_DAY = datetime.date(2026, 8, 11)
_OTHER_DAY = datetime.date(2026, 8, 12)

_FIXED_CLOCK = datetime.datetime(2026, 8, 11, 9, 0, 0, tzinfo=datetime.timezone.utc)


def _fixed_clock() -> datetime.datetime:
    return _FIXED_CLOCK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service(**overrides):  # type: ignore[no-untyped-def]
    """Construit un objet Service minimal (duck-typing, pas d'import du domain)."""

    data = dict(id=uuid.uuid4(), salon_id=_SALON_A, duration_minutes=30, is_active=True)
    data.update(overrides)

    class _Svc:
        def __init__(self) -> None:  # type: ignore[no-untyped-def]
            self.id = data["id"]
            self.salon_id = data["salon_id"]
            self.duration_minutes = data["duration_minutes"]
            self.is_active = data["is_active"]
            self.name = "Prestation Test"

    return _Svc()


def _catalog_with_service(service, hairdressers=None):  # type: ignore[no-untyped-def]
    """Catalogue avec une seule prestation active et des coiffeuses configurables."""

    class _Hairdresser:
        def __init__(self, id_):  # type: ignore[no-untyped-def]
            self.id = id_
            self.status = "ACTIVE"
            self.full_name = "Coiffeuse Test"

    hds = hairdressers or [_Hairdresser(_HAIRDRESSER_ID)]
    return FakeSalonCatalogRepository(
        services={service.salon_id: [service]},
        hairdressers={service.salon_id: hds},
    )


def _make_ticket(
    *,
    salon_id: uuid.UUID = _SALON_A,
    status: str = "waiting",
    hairdresser_id: uuid.UUID | None = None,
    issued_date: datetime.date = _DAY,
) -> QueueTicket:
    """Construit un `QueueTicket` en mémoire directement dans le fake."""

    sid = uuid.uuid4()
    return QueueTicket(
        id=sid,
        salon_id=salon_id,
        ticket_number=1,
        issued_date=issued_date,
        customer_profile_id=None,
        service_ids=(uuid.uuid4(),),
        status=status,
        hairdresser_id=hairdresser_id,
        estimated_wait_minutes=10,
        created_at=_CREATED_AT,
        called_at=None,
        started_at=_CREATED_AT if status in ("in_progress", "done") else None,
        completed_at=_CREATED_AT if status == "done" else None,
    )


# ---------------------------------------------------------------------------
# JoinQueue
# ---------------------------------------------------------------------------


class TestJoinQueue:
    def _usecase(
        self,
        tickets: FakeQueueTicketRepository | None = None,
        catalog: FakeSalonCatalogRepository | None = None,
        customers: FakeCustomerRepository | None = None,
    ) -> JoinQueue:
        svc = _service(salon_id=_SALON_A, duration_minutes=30)
        return JoinQueue(
            queue_ticket_repository=tickets or FakeQueueTicketRepository(),
            catalog_repository=catalog or _catalog_with_service(svc),
            customer_repository=customers or FakeCustomerRepository(),
            clock=_fixed_clock,
        )

    def test_first_ticket_gets_number_one(self) -> None:
        tickets = FakeQueueTicketRepository()
        svc = _service(salon_id=_SALON_A)
        uc = JoinQueue(tickets, _catalog_with_service(svc), FakeCustomerRepository(), clock=_fixed_clock)
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.ticket_number == 1

    def test_second_ticket_same_salon_same_day_increments(self) -> None:
        tickets = FakeQueueTicketRepository()
        svc = _service(salon_id=_SALON_A)
        uc = JoinQueue(tickets, _catalog_with_service(svc), FakeCustomerRepository(), clock=_fixed_clock)
        cmd = JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,))
        first = uc.execute(_SALON_A, cmd)
        second = uc.execute(_SALON_A, cmd)
        assert second.ticket_number == first.ticket_number + 1

    def test_two_salons_have_independent_counters(self) -> None:
        tickets = FakeQueueTicketRepository()
        svc_a = _service(salon_id=_SALON_A)
        svc_b = _service(salon_id=_SALON_B)
        catalog_a = _catalog_with_service(svc_a)
        catalog_b = _catalog_with_service(svc_b)
        uc_a = JoinQueue(tickets, catalog_a, FakeCustomerRepository(), clock=_fixed_clock)
        uc_b = JoinQueue(tickets, catalog_b, FakeCustomerRepository(), clock=_fixed_clock)
        t_a = uc_a.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc_a.id,)))
        t_b = uc_b.execute(_SALON_B, JoinQueueCommand(customer_profile_id=None, service_ids=(svc_b.id,)))
        # Chaque salon démarre à 1 indépendamment.
        assert t_a.ticket_number == 1
        assert t_b.ticket_number == 1

    def test_anonymous_ticket_is_accepted(self) -> None:
        svc = _service(salon_id=_SALON_A)
        uc = self._usecase(catalog=_catalog_with_service(svc))
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.customer_profile_id is None
        assert result.status == "waiting"

    def test_customer_profile_from_other_salon_raises_not_found(self) -> None:
        customers = FakeCustomerRepository()
        # Fiche créée pour le salon B ; `JoinQueue` sur salon A ne peut pas la trouver.
        customer = customers.create(type("C", (), {
            "salon_id": _SALON_B,
            "full_name": "Awa",
            "phone": None,
            "gender": None,
            "notes": None,
        })())
        svc = _service(salon_id=_SALON_A)
        uc = self._usecase(catalog=_catalog_with_service(svc), customers=customers)
        with pytest.raises(QueueTicketNotFound):
            uc.execute(
                _SALON_A,
                JoinQueueCommand(customer_profile_id=customer.id, service_ids=(svc.id,)),
            )

    def test_customer_from_other_salon_creates_no_ticket(self) -> None:
        tickets = FakeQueueTicketRepository()
        customers = FakeCustomerRepository()
        customer = customers.create(type("C", (), {
            "salon_id": _SALON_B,
            "full_name": "Awa",
            "phone": None,
            "gender": None,
            "notes": None,
        })())
        svc = _service(salon_id=_SALON_A)
        uc = JoinQueue(tickets, _catalog_with_service(svc), customers, clock=_fixed_clock)
        with pytest.raises(QueueTicketNotFound):
            uc.execute(
                _SALON_A,
                JoinQueueCommand(customer_profile_id=customer.id, service_ids=(svc.id,)),
            )
        assert tickets.created == []

    def test_empty_service_ids_raises_invalid_services(self) -> None:
        uc = self._usecase()
        with pytest.raises(InvalidQueueTicketServices):
            uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=()))

    def test_service_from_other_salon_raises_invalid_services(self) -> None:
        svc_other = _service(salon_id=_SALON_B)
        catalog = FakeSalonCatalogRepository(services={_SALON_B: [svc_other]})
        uc = JoinQueue(
            FakeQueueTicketRepository(),
            catalog,
            FakeCustomerRepository(),
            clock=_fixed_clock,
        )
        with pytest.raises(InvalidQueueTicketServices):
            uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc_other.id,)))

    def test_eta_is_zero_when_queue_is_empty_and_one_hairdresser(self) -> None:
        # File vide → position=0 → ETA=0, quelle que soit la durée ou le nb coiffeuses.
        svc = _service(salon_id=_SALON_A, duration_minutes=45)
        catalog = _catalog_with_service(svc)
        uc = JoinQueue(FakeQueueTicketRepository(), catalog, FakeCustomerRepository(), clock=_fixed_clock)
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.estimated_wait_minutes == 0

    def test_eta_uses_fallback_constant_when_no_active_hairdresser(self) -> None:
        svc = _service(salon_id=_SALON_A, duration_minutes=30)
        # Aucune coiffeuse active → repli `DEFAULT_WAIT_MINUTES_NO_STAFF`.
        catalog = FakeSalonCatalogRepository(
            services={_SALON_A: [svc]},
            hairdressers={_SALON_A: []},  # aucune coiffeuse
        )
        tickets = FakeQueueTicketRepository()
        # Placer un ticket `waiting` pour que position > 0.
        existing = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(existing)
        uc = JoinQueue(tickets, catalog, FakeCustomerRepository(), clock=_fixed_clock)
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.estimated_wait_minutes == DEFAULT_WAIT_MINUTES_NO_STAFF

    def test_eta_uses_own_duration_when_queue_is_empty_and_hairdresser_exists(self) -> None:
        # Aucun ticket actif → `average_requested_duration_minutes` retourne `None` →
        # repli sur la moyenne des durées du ticket lui-même.
        svc = _service(salon_id=_SALON_A, duration_minutes=30)
        catalog = _catalog_with_service(svc)
        tickets = FakeQueueTicketRepository(average_duration=None)
        uc = JoinQueue(tickets, catalog, FakeCustomerRepository(), clock=_fixed_clock)
        # File vide : position=0 → ETA=0 même avec durée=30.
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.estimated_wait_minutes == 0

    def test_eta_computed_from_waiting_position_and_average(self) -> None:
        # Position=2, durée moyenne=30, 2 coiffeuses → 30 min.
        svc = _service(salon_id=_SALON_A, duration_minutes=30)
        tickets = FakeQueueTicketRepository(average_duration=30.0)
        # Pré-charger 2 tickets `waiting` pour que position=2.
        for _ in range(2):
            t = _make_ticket(salon_id=_SALON_A, status="waiting")
            tickets.seed(t)

        class _Two:
            def __init__(self):  # type: ignore[no-untyped-def]
                self.id = _HAIRDRESSER_ID
                self.status = "ACTIVE"
                self.full_name = "H"

        catalog = FakeSalonCatalogRepository(
            services={_SALON_A: [svc]},
            hairdressers={_SALON_A: [_Two(), _Two()]},
        )
        uc = JoinQueue(tickets, catalog, FakeCustomerRepository(), clock=_fixed_clock)
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        # 2 × 30 / 2 = 30
        assert result.estimated_wait_minutes == 30

    def test_ticket_status_is_waiting_on_creation(self) -> None:
        svc = _service(salon_id=_SALON_A)
        uc = self._usecase(catalog=_catalog_with_service(svc))
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.status == "waiting"

    def test_ticket_salon_matches_requested_salon(self) -> None:
        svc = _service(salon_id=_SALON_A)
        uc = self._usecase(catalog=_catalog_with_service(svc))
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert result.salon_id == _SALON_A

    def test_service_ids_stored_in_ticket(self) -> None:
        svc = _service(salon_id=_SALON_A)
        uc = self._usecase(catalog=_catalog_with_service(svc))
        result = uc.execute(_SALON_A, JoinQueueCommand(customer_profile_id=None, service_ids=(svc.id,)))
        assert svc.id in result.service_ids


# ---------------------------------------------------------------------------
# StartQueueTicket
# ---------------------------------------------------------------------------


class TestStartQueueTicket:
    def _usecase(
        self,
        tickets: FakeQueueTicketRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
        audit: FakeAuditLog | None = None,
    ) -> tuple[StartQueueTicket, FakeAuditLog]:
        log = audit or FakeAuditLog()
        hairdresser_scope = scope or FakeSalonScopeRepository(
            {_HAIRDRESSER_ID: frozenset({_SALON_A})}
        )
        uc = StartQueueTicket(
            queue_ticket_repository=tickets or FakeQueueTicketRepository(),
            scope_repository=hairdresser_scope,
            audit_log=log,
            clock=_fixed_clock,
        )
        return uc, log

    def test_unknown_ticket_raises_not_found(self) -> None:
        uc, _ = self._usecase()
        with pytest.raises(QueueTicketNotFound):
            uc.execute(_SALON_A, uuid.uuid4(), _HAIRDRESSER_ID, _ACTOR_ID)

    def test_ticket_from_other_salon_raises_not_found(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_B, status="waiting")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(QueueTicketNotFound):
            uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)

    def test_in_progress_ticket_raises_invalid_transition(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)

    def test_done_ticket_raises_invalid_transition(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="done")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)

    def test_expired_ticket_raises_invalid_transition(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="expired")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)

    def test_hairdresser_not_in_salon_raises_error(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        # Coiffeuse connue du salon B uniquement.
        scope = FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({_SALON_B})})
        uc, _ = self._usecase(tickets=tickets, scope=scope)
        with pytest.raises(HairdresserNotInSalon):
            uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)

    def test_success_returns_in_progress_ticket(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        result = uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        assert result.status == "in_progress"

    def test_success_sets_hairdresser_id(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        result = uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        assert result.hairdresser_id == _HAIRDRESSER_ID

    def test_success_sets_started_at(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        result = uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        assert result.started_at is not None

    def test_audit_recorded_exactly_once(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        assert len(log.recorded) == 1

    def test_audit_action_is_queue_ticket_started(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        entry = log.recorded[0]
        assert entry.action == AuditAction.QUEUE_TICKET_STARTED.value

    def test_audit_entity_type_is_queue_ticket(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        entry = log.recorded[0]
        assert entry.entity_type == ENTITY_TYPE_QUEUE_TICKET

    def test_audit_metadata_is_empty(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        entry = log.recorded[0]
        assert entry.metadata == {}

    def test_audit_actor_is_actor_id(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        entry = log.recorded[0]
        assert entry.actor_user_id == _ACTOR_ID

    def test_audit_salon_id_matches(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        entry = log.recorded[0]
        assert entry.salon_id == _SALON_A

    def test_no_audit_on_error(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="done")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _HAIRDRESSER_ID, _ACTOR_ID)
        assert log.recorded == []


# ---------------------------------------------------------------------------
# CompleteQueueTicket
# ---------------------------------------------------------------------------


class TestCompleteQueueTicket:
    def _usecase(
        self,
        tickets: FakeQueueTicketRepository | None = None,
        audit: FakeAuditLog | None = None,
    ) -> tuple[CompleteQueueTicket, FakeAuditLog]:
        log = audit or FakeAuditLog()
        uc = CompleteQueueTicket(
            queue_ticket_repository=tickets or FakeQueueTicketRepository(),
            audit_log=log,
            clock=_fixed_clock,
        )
        return uc, log

    def test_unknown_ticket_raises_not_found(self) -> None:
        uc, _ = self._usecase()
        with pytest.raises(QueueTicketNotFound):
            uc.execute(_SALON_A, uuid.uuid4(), _ACTOR_ID)

    def test_ticket_from_other_salon_raises_not_found(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_B, status="in_progress")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(QueueTicketNotFound):
            uc.execute(_SALON_A, ticket.id, _ACTOR_ID)

    def test_waiting_ticket_raises_invalid_transition(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _ACTOR_ID)

    def test_done_ticket_raises_invalid_transition(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="done")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _ACTOR_ID)

    def test_success_returns_done_ticket(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        result = uc.execute(_SALON_A, ticket.id, _ACTOR_ID)
        assert result.status == "done"

    def test_success_sets_completed_at(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(ticket)
        uc, _ = self._usecase(tickets=tickets)
        result = uc.execute(_SALON_A, ticket.id, _ACTOR_ID)
        assert result.completed_at is not None

    def test_audit_recorded_exactly_once(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _ACTOR_ID)
        assert len(log.recorded) == 1

    def test_audit_action_is_queue_ticket_completed(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _ACTOR_ID)
        assert log.recorded[0].action == AuditAction.QUEUE_TICKET_COMPLETED.value

    def test_audit_metadata_is_empty(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        uc.execute(_SALON_A, ticket.id, _ACTOR_ID)
        assert log.recorded[0].metadata == {}

    def test_no_audit_on_error(self) -> None:
        tickets = FakeQueueTicketRepository()
        ticket = _make_ticket(salon_id=_SALON_A, status="waiting")
        tickets.seed(ticket)
        uc, log = self._usecase(tickets=tickets)
        with pytest.raises(InvalidQueueTicketTransition):
            uc.execute(_SALON_A, ticket.id, _ACTOR_ID)
        assert log.recorded == []


# ---------------------------------------------------------------------------
# ListSalonQueueTickets
# ---------------------------------------------------------------------------


class TestListSalonQueueTickets:
    def _usecase(self, tickets: FakeQueueTicketRepository) -> ListSalonQueueTickets:
        return ListSalonQueueTickets(queue_ticket_repository=tickets)

    def test_empty_salon_returns_empty_tuple(self) -> None:
        tickets = FakeQueueTicketRepository()
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        assert result == ()

    def test_returns_only_tickets_for_requested_salon(self) -> None:
        tickets = FakeQueueTicketRepository()
        t_a = _make_ticket(salon_id=_SALON_A, status="waiting")
        t_b = _make_ticket(salon_id=_SALON_B, status="waiting")
        tickets.seed(t_a)
        tickets.seed(t_b)
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        ticket_ids = {e.ticket_id for e in result}
        assert t_a.id in ticket_ids
        assert t_b.id not in ticket_ids

    def test_excludes_expired_tickets(self) -> None:
        tickets = FakeQueueTicketRepository()
        t_waiting = _make_ticket(salon_id=_SALON_A, status="waiting")
        t_expired = _make_ticket(salon_id=_SALON_A, status="expired")
        tickets.seed(t_waiting)
        tickets.seed(t_expired)
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        ticket_ids = {e.ticket_id for e in result}
        assert t_waiting.id in ticket_ids
        assert t_expired.id not in ticket_ids

    def test_includes_done_tickets(self) -> None:
        tickets = FakeQueueTicketRepository()
        t_done = _make_ticket(salon_id=_SALON_A, status="done")
        tickets.seed(t_done)
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        assert len(result) == 1
        assert result[0].ticket_id == t_done.id

    def test_returns_only_tickets_for_requested_day(self) -> None:
        tickets = FakeQueueTicketRepository()
        t_today = _make_ticket(salon_id=_SALON_A, status="waiting", issued_date=_DAY)
        t_other = _make_ticket(salon_id=_SALON_A, status="waiting", issued_date=_OTHER_DAY)
        tickets.seed(t_today)
        tickets.seed(t_other)
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        assert len(result) == 1
        assert result[0].ticket_id == t_today.id

    def test_results_sorted_by_ticket_number(self) -> None:
        import dataclasses as _dc

        tickets = FakeQueueTicketRepository()
        # Créer trois tickets avec des numéros hors ordre.
        for number in (3, 1, 2):
            base = _make_ticket(salon_id=_SALON_A, status="waiting")
            ordered = _dc.replace(base, ticket_number=number)
            tickets._tickets[ordered.id] = ordered
            tickets._display[ordered.id] = {}
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        numbers = [e.ticket_number for e in result]
        assert numbers == sorted(numbers)

    def test_result_entries_have_correct_status(self) -> None:
        tickets = FakeQueueTicketRepository()
        t = _make_ticket(salon_id=_SALON_A, status="in_progress")
        tickets.seed(t)
        uc = self._usecase(tickets)
        result = uc.execute(_SALON_A, _DAY)
        assert result[0].status == "in_progress"
