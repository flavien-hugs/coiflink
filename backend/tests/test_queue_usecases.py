"""Tests unitaires pour les cas d'usage de la file d'attente (#150).

Couvre `MarkAppointmentArrived`, `StartAppointmentService`, `ListSalonQueue` —
tous les ports sont des fakes (conftest.py) : pas de base de données. Vérifie :
- l'idempotence du pointage (double appel sans second horodatage) ;
- les préconditions du démarrage (arrivée pointée + coiffeuse assignée) ;
- l'isolation §11.2 (RDV hors salon/inexistant → 404 indiscernable) ;
- la journalisation §11.4 (action, salon_id, métadonnées neutres) ;
- la composition RDV + paiement de `ListSalonQueue` (dérivation `queue_status`).
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.application.queue import (
    ListSalonQueue,
    MarkAppointmentArrived,
    StartAppointmentService,
)
from coiflink_api.domain.appointment import Appointment
from coiflink_api.domain.audit import AuditAction, ENTITY_TYPE_APPOINTMENT
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import (
    AppointmentArrivalRequired,
    AppointmentHairdresserRequired,
    AppointmentNotFound,
    InvalidAppointmentTransition,
)
from coiflink_api.domain.queue import QueueAppointmentRow

from .conftest import FakeAppointmentRepository, FakeAuditLog, FakePaymentRepository

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_APPOINTMENT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
_CLIENT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
_HAIRDRESSER_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
_ACTOR_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000009")
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_NOW = datetime.datetime(2026, 8, 9, 10, 0, tzinfo=datetime.timezone.utc)
_DAY = datetime.date(2026, 8, 9)


def _appointment(**overrides: object) -> Appointment:
    defaults: dict[str, object] = dict(
        id=_APPOINTMENT_ID,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=_HAIRDRESSER_ID,
        date=_DAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(9, 30),
        status=AppointmentStatus.CONFIRMED.value,
        client_note=None,
        created_at=_CREATED_AT,
        arrived_at=None,
        started_at=None,
    )
    defaults.update(overrides)
    return Appointment(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# MarkAppointmentArrived
# ---------------------------------------------------------------------------


class TestMarkAppointmentArrived:
    def test_sets_arrived_at(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment()])
        uc = MarkAppointmentArrived(repo, FakeAuditLog(), clock=lambda: _NOW)
        updated = uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        assert updated.arrived_at == _NOW

    def test_idempotent_second_call_keeps_first_timestamp(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment()])
        clocks = iter([_NOW, _NOW + datetime.timedelta(minutes=5)])
        uc = MarkAppointmentArrived(repo, FakeAuditLog(), clock=lambda: next(clocks))
        uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        second = uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        assert second.arrived_at == _NOW

    def test_unknown_appointment_raises_not_found(self) -> None:
        repo = FakeAppointmentRepository()
        uc = MarkAppointmentArrived(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentNotFound):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_appointment_of_other_salon_raises_not_found(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment()])
        uc = MarkAppointmentArrived(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentNotFound):
            uc.execute(_APPOINTMENT_ID, _OTHER_SALON_ID, _ACTOR_ID)

    def test_non_confirmed_status_raises_invalid_transition(self) -> None:
        repo = FakeAppointmentRepository(
            appointments=[_appointment(status=AppointmentStatus.PENDING.value)]
        )
        uc = MarkAppointmentArrived(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(InvalidAppointmentTransition):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_completed_status_raises_invalid_transition(self) -> None:
        repo = FakeAppointmentRepository(
            appointments=[_appointment(status=AppointmentStatus.COMPLETED.value)]
        )
        uc = MarkAppointmentArrived(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(InvalidAppointmentTransition):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_records_neutral_audit_entry(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment()])
        audit_log = FakeAuditLog()
        uc = MarkAppointmentArrived(repo, audit_log, clock=lambda: _NOW)
        uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

        assert len(audit_log.recorded) == 1
        entry = audit_log.recorded[0]
        assert entry.action == AuditAction.APPOINTMENT_ARRIVED.value
        assert entry.actor_user_id == _ACTOR_ID
        assert entry.salon_id == _SALON_ID
        assert entry.entity_type == ENTITY_TYPE_APPOINTMENT
        assert entry.entity_id == _APPOINTMENT_ID
        assert entry.metadata == {}

    def test_no_audit_entry_on_not_found(self) -> None:
        repo = FakeAppointmentRepository()
        audit_log = FakeAuditLog()
        uc = MarkAppointmentArrived(repo, audit_log, clock=lambda: _NOW)
        with pytest.raises(AppointmentNotFound):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        assert audit_log.recorded == []


# ---------------------------------------------------------------------------
# StartAppointmentService
# ---------------------------------------------------------------------------


class TestStartAppointmentService:
    def test_sets_started_at_when_preconditions_met(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment(arrived_at=_NOW)])
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: _NOW)
        updated = uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        assert updated.started_at == _NOW

    def test_missing_arrival_raises_arrival_required(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment(arrived_at=None)])
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentArrivalRequired):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_missing_hairdresser_raises_hairdresser_required(self) -> None:
        repo = FakeAppointmentRepository(
            appointments=[_appointment(arrived_at=_NOW, hairdresser_id=None)]
        )
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentHairdresserRequired):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_arrival_checked_before_hairdresser(self) -> None:
        """Les deux préconditions manquent : l'arrivée est le message renvoyé (ordre stable)."""
        repo = FakeAppointmentRepository(
            appointments=[_appointment(arrived_at=None, hairdresser_id=None)]
        )
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentArrivalRequired):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_unknown_appointment_raises_not_found(self) -> None:
        repo = FakeAppointmentRepository()
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentNotFound):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

    def test_appointment_of_other_salon_raises_not_found(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment(arrived_at=_NOW)])
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: _NOW)
        with pytest.raises(AppointmentNotFound):
            uc.execute(_APPOINTMENT_ID, _OTHER_SALON_ID, _ACTOR_ID)

    def test_idempotent_second_call_keeps_first_timestamp(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment(arrived_at=_NOW)])
        clocks = iter([_NOW, _NOW + datetime.timedelta(minutes=5)])
        uc = StartAppointmentService(repo, FakeAuditLog(), clock=lambda: next(clocks))
        uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        second = uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        assert second.started_at == _NOW

    def test_records_neutral_audit_entry(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment(arrived_at=_NOW)])
        audit_log = FakeAuditLog()
        uc = StartAppointmentService(repo, audit_log, clock=lambda: _NOW)
        uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)

        entry = audit_log.recorded[0]
        assert entry.action == AuditAction.APPOINTMENT_STARTED.value
        assert entry.metadata == {}

    def test_no_audit_entry_on_missing_precondition(self) -> None:
        repo = FakeAppointmentRepository(appointments=[_appointment(arrived_at=None)])
        audit_log = FakeAuditLog()
        uc = StartAppointmentService(repo, audit_log, clock=lambda: _NOW)
        with pytest.raises(AppointmentArrivalRequired):
            uc.execute(_APPOINTMENT_ID, _SALON_ID, _ACTOR_ID)
        assert audit_log.recorded == []


# ---------------------------------------------------------------------------
# ListSalonQueue
# ---------------------------------------------------------------------------


def _queue_row(**overrides: object) -> QueueAppointmentRow:
    defaults: dict[str, object] = dict(
        appointment_id=_APPOINTMENT_ID,
        client_name="Awa Koné",
        service_names=("Coupe",),
        hairdresser_id=_HAIRDRESSER_ID,
        hairdresser_name="Fatou",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(9, 30),
        status=AppointmentStatus.CONFIRMED.value,
        arrived_at=None,
        started_at=None,
    )
    defaults.update(overrides)
    return QueueAppointmentRow(**defaults)  # type: ignore[arg-type]


class TestListSalonQueue:
    def test_empty_queue_returns_empty_tuple(self) -> None:
        appointments = FakeAppointmentRepository()
        payments = FakePaymentRepository()
        uc = ListSalonQueue(appointments, payments)
        assert uc.execute(_SALON_ID, _DAY) == ()

    def test_confirmed_waiting_entry(self) -> None:
        appointments = FakeAppointmentRepository()
        appointments.queue_details = (_queue_row(),)
        payments = FakePaymentRepository()
        uc = ListSalonQueue(appointments, payments)
        entries = uc.execute(_SALON_ID, _DAY)
        assert len(entries) == 1
        assert entries[0].queue_status == "waiting"

    def test_confirmed_in_progress_entry(self) -> None:
        appointments = FakeAppointmentRepository()
        appointments.queue_details = (_queue_row(started_at=_NOW),)
        payments = FakePaymentRepository()
        uc = ListSalonQueue(appointments, payments)
        entries = uc.execute(_SALON_ID, _DAY)
        assert entries[0].queue_status == "in_progress"

    def test_completed_without_payment_is_completed(self) -> None:
        appointments = FakeAppointmentRepository()
        appointments.queue_details = (
            _queue_row(status=AppointmentStatus.COMPLETED.value, started_at=_NOW),
        )
        payments = FakePaymentRepository()
        uc = ListSalonQueue(appointments, payments)
        entries = uc.execute(_SALON_ID, _DAY)
        assert entries[0].queue_status == "completed"

    def test_completed_with_validated_payment_is_paid(self) -> None:
        from coiflink_api.domain.payment import PaymentToCreate

        appointments = FakeAppointmentRepository()
        appointments.queue_details = (
            _queue_row(status=AppointmentStatus.COMPLETED.value, started_at=_NOW),
        )
        payments = FakePaymentRepository()
        payments.create(
            PaymentToCreate(
                salon_id=_SALON_ID,
                amount=5000,
                currency="XOF",
                payment_method="CASH",
                recorded_by=_ACTOR_ID,
                appointment_id=_APPOINTMENT_ID,
                service_id=None,
                client_id=_CLIENT_ID,
            )
        )
        uc = ListSalonQueue(appointments, payments)
        entries = uc.execute(_SALON_ID, _DAY)
        assert entries[0].queue_status == "paid"

    def test_completed_with_cancelled_payment_is_not_paid(self) -> None:
        """Un paiement `CANCELLED` ne couvre pas le RDV (miroir #36)."""
        import dataclasses as _dc

        from coiflink_api.domain.payment import PaymentToCreate

        appointments = FakeAppointmentRepository()
        appointments.queue_details = (
            _queue_row(status=AppointmentStatus.COMPLETED.value, started_at=_NOW),
        )
        payments = FakePaymentRepository()
        created = payments.create(
            PaymentToCreate(
                salon_id=_SALON_ID,
                amount=5000,
                currency="XOF",
                payment_method="CASH",
                recorded_by=_ACTOR_ID,
                appointment_id=_APPOINTMENT_ID,
                service_id=None,
                client_id=_CLIENT_ID,
                status="CANCELLED",
            )
        )
        payments._payments[created.id] = _dc.replace(created, status="CANCELLED")

        uc = ListSalonQueue(appointments, payments)
        entries = uc.execute(_SALON_ID, _DAY)
        assert entries[0].queue_status == "completed"

    def test_does_not_check_payment_for_confirmed_entries(self) -> None:
        """Optimisation : seuls les `appointment_id` `COMPLETED` sont passés au bulk-lookup."""
        appointments = FakeAppointmentRepository()
        appointments.queue_details = (_queue_row(),)  # CONFIRMED
        payments = FakePaymentRepository()
        calls: list = []
        original = payments.list_paid_appointment_ids

        def _tracking(salon_id, appointment_ids):
            calls.append(appointment_ids)
            return original(salon_id, appointment_ids)

        payments.list_paid_appointment_ids = _tracking  # type: ignore[method-assign]
        uc = ListSalonQueue(appointments, payments)
        uc.execute(_SALON_ID, _DAY)
        assert calls == [()]

    def test_passes_day_to_repository(self) -> None:
        appointments = FakeAppointmentRepository()
        payments = FakePaymentRepository()
        uc = ListSalonQueue(appointments, payments)
        uc.execute(_SALON_ID, _DAY)
        assert appointments.list_queue_details_calls[-1]["day"] == _DAY
        assert appointments.list_queue_details_calls[-1]["salon_id"] == _SALON_ID
