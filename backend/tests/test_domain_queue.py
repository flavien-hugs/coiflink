"""Tests unitaires — domaine `queue` (file d'attente, #150).

Domaine **pur** : `derive_queue_status`, `finalize_queue_entry`. Vérifie la
dérivation « en attente / en cours / terminée / payée » sans base ni FastAPI.
"""

from __future__ import annotations

import datetime
import uuid

from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.queue import (
    QUEUE_APPOINTMENT_STATUSES,
    QueueAppointmentRow,
    derive_queue_status,
    finalize_queue_entry,
)

_NOW = datetime.datetime(2026, 8, 9, 10, 0, tzinfo=datetime.timezone.utc)


class TestDeriveQueueStatus:
    def test_confirmed_without_started_at_is_waiting(self) -> None:
        status = derive_queue_status(
            AppointmentStatus.CONFIRMED.value, started_at=None, is_paid=False
        )
        assert status == "waiting"

    def test_confirmed_with_started_at_is_in_progress(self) -> None:
        status = derive_queue_status(
            AppointmentStatus.CONFIRMED.value, started_at=_NOW, is_paid=False
        )
        assert status == "in_progress"

    def test_confirmed_with_started_at_ignores_is_paid(self) -> None:
        """`is_paid` ne s'applique qu'aux RDV `COMPLETED` (payer un RDV en cours n'a pas de sens)."""
        status = derive_queue_status(
            AppointmentStatus.CONFIRMED.value, started_at=_NOW, is_paid=True
        )
        assert status == "in_progress"

    def test_completed_without_payment_is_completed(self) -> None:
        status = derive_queue_status(
            AppointmentStatus.COMPLETED.value, started_at=_NOW, is_paid=False
        )
        assert status == "completed"

    def test_completed_with_payment_is_paid(self) -> None:
        status = derive_queue_status(
            AppointmentStatus.COMPLETED.value, started_at=_NOW, is_paid=True
        )
        assert status == "paid"

    def test_completed_with_payment_and_no_started_at_is_still_paid(self) -> None:
        """Un RDV directement `COMPLETED` sans pointage (workflow legacy) reste dérivable."""
        status = derive_queue_status(
            AppointmentStatus.COMPLETED.value, started_at=None, is_paid=True
        )
        assert status == "paid"


class TestQueueAppointmentStatuses:
    def test_only_confirmed_and_completed(self) -> None:
        assert set(QUEUE_APPOINTMENT_STATUSES) == {
            AppointmentStatus.CONFIRMED.value,
            AppointmentStatus.COMPLETED.value,
        }

    def test_pending_cancelled_no_show_excluded(self) -> None:
        excluded = {
            AppointmentStatus.PENDING.value,
            AppointmentStatus.CANCELLED.value,
            AppointmentStatus.NO_SHOW.value,
        }
        assert not excluded & set(QUEUE_APPOINTMENT_STATUSES)


def _row(**overrides: object) -> QueueAppointmentRow:
    defaults: dict[str, object] = dict(
        appointment_id=uuid.uuid4(),
        client_name="Awa Koné",
        service_names=("Coupe",),
        hairdresser_id=uuid.uuid4(),
        hairdresser_name="Fatou",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(9, 30),
        status=AppointmentStatus.CONFIRMED.value,
        arrived_at=None,
        started_at=None,
    )
    defaults.update(overrides)
    return QueueAppointmentRow(**defaults)  # type: ignore[arg-type]


class TestFinalizeQueueEntry:
    def test_preserves_display_fields(self) -> None:
        row = _row()
        entry = finalize_queue_entry(row, is_paid=False)
        assert entry.appointment_id == row.appointment_id
        assert entry.client_name == row.client_name
        assert entry.service_names == row.service_names
        assert entry.hairdresser_id == row.hairdresser_id
        assert entry.hairdresser_name == row.hairdresser_name

    def test_derives_queue_status_waiting(self) -> None:
        entry = finalize_queue_entry(_row(), is_paid=False)
        assert entry.queue_status == "waiting"

    def test_derives_queue_status_in_progress(self) -> None:
        entry = finalize_queue_entry(_row(started_at=_NOW), is_paid=False)
        assert entry.queue_status == "in_progress"

    def test_derives_queue_status_paid(self) -> None:
        row = _row(status=AppointmentStatus.COMPLETED.value, started_at=_NOW)
        entry = finalize_queue_entry(row, is_paid=True)
        assert entry.queue_status == "paid"
