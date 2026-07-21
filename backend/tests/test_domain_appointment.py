"""Tests unitaires — règles de domaine « rendez-vous » (US-3.7, #21).

Couvre `domain/appointment.py` sans I/O ni base de données.

Cas traités :
- `require_services` : tuple vide → `AppointmentServiceRequired`, non-vide → OK ;
- `validate_booking_window` : `end <= start` → `SlotUnavailable`, `end > start` → OK ;
- `compute_end_time` : calcul normal, somme multi-prestations, franchissement minuit →
  `SlotUnavailable` ;
- Invariants des dataclasses (`BookedService`, `AppointmentToCreate`, `Appointment`) :
  champs préservés, valeurs par défaut, immutabilité.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.domain.appointment import (
    Appointment,
    AppointmentToCreate,
    BookedService,
    compute_end_time,
    require_services,
    validate_booking_window,
)
from coiflink_api.domain.errors import AppointmentServiceRequired, SlotUnavailable

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_SERVICE_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_PRICE = decimal.Decimal("5000.00")
_DATE = datetime.date(2026, 8, 3)
_START = datetime.time(9, 0)
_END = datetime.time(10, 0)


# ---------------------------------------------------------------------------
# require_services
# ---------------------------------------------------------------------------


class TestRequireServices:
    def test_empty_tuple_raises(self) -> None:
        with pytest.raises(AppointmentServiceRequired):
            require_services(())

    def test_single_service_accepted(self) -> None:
        service = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        require_services((service,))  # ne doit pas lever

    def test_multiple_services_accepted(self) -> None:
        s1 = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        s2 = BookedService(service_id=uuid.uuid4(), price_at_booking=_PRICE)
        require_services((s1, s2))  # ne doit pas lever

    def test_error_message_is_neutral(self) -> None:
        with pytest.raises(AppointmentServiceRequired) as exc_info:
            require_services(())
        assert exc_info.value.args[0]  # message non vide
        assert "prestation" in exc_info.value.args[0].lower()


# ---------------------------------------------------------------------------
# validate_booking_window
# ---------------------------------------------------------------------------


class TestValidateBookingWindow:
    def test_end_after_start_accepted(self) -> None:
        validate_booking_window(_START, _END)  # ne doit pas lever

    def test_end_equal_start_raises(self) -> None:
        with pytest.raises(SlotUnavailable):
            validate_booking_window(_START, _START)

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(SlotUnavailable):
            validate_booking_window(_END, _START)

    def test_one_minute_window_accepted(self) -> None:
        validate_booking_window(datetime.time(9, 0), datetime.time(9, 1))  # ne doit pas lever


# ---------------------------------------------------------------------------
# compute_end_time
# ---------------------------------------------------------------------------


class TestComputeEndTime:
    def test_single_service_60_minutes(self) -> None:
        end = compute_end_time(datetime.time(9, 0), 60)
        assert end == datetime.time(10, 0)

    def test_multi_service_sum_of_durations(self) -> None:
        # 30 + 45 = 75 minutes
        end = compute_end_time(datetime.time(9, 0), 75)
        assert end == datetime.time(10, 15)

    def test_midnight_overflow_raises_slot_unavailable(self) -> None:
        # 23:30 + 60 min = 00:30 (lendemain) → non modélisable
        with pytest.raises(SlotUnavailable):
            compute_end_time(datetime.time(23, 30), 60)

    def test_exactly_at_1440_raises(self) -> None:
        with pytest.raises(SlotUnavailable):
            compute_end_time(datetime.time(0, 0), 24 * 60)

    def test_result_just_before_midnight(self) -> None:
        end = compute_end_time(datetime.time(23, 0), 59)
        assert end == datetime.time(23, 59)

    def test_zero_duration_same_as_start(self) -> None:
        # 0 minutes = heure identique (cas dégénéré admis par compute_end_time)
        end = compute_end_time(datetime.time(10, 0), 0)
        assert end == datetime.time(10, 0)


# ---------------------------------------------------------------------------
# BookedService — invariants dataclass
# ---------------------------------------------------------------------------


class TestBookedService:
    def test_fields_preserved(self) -> None:
        service = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        assert service.service_id == _SERVICE_ID
        assert service.price_at_booking == _PRICE

    def test_immutable(self) -> None:
        service = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        with pytest.raises((AttributeError, TypeError)):
            service.price_at_booking = decimal.Decimal("0.00")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AppointmentToCreate — invariants dataclass
# ---------------------------------------------------------------------------


class TestAppointmentToCreate:
    def _make(self) -> AppointmentToCreate:
        return AppointmentToCreate(
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=_HAIRDRESSER_ID,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            services=(BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE),),
        )

    def test_fields_preserved(self) -> None:
        appt = self._make()
        assert appt.salon_id == _SALON_ID
        assert appt.client_id == _CLIENT_ID
        assert appt.hairdresser_id == _HAIRDRESSER_ID

    def test_default_status_is_pending(self) -> None:
        appt = self._make()
        assert appt.status == "PENDING"

    def test_default_client_note_is_none(self) -> None:
        appt = self._make()
        assert appt.client_note is None

    def test_hairdresser_id_optional(self) -> None:
        appt = AppointmentToCreate(
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=None,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            services=(BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE),),
        )
        assert appt.hairdresser_id is None


# ---------------------------------------------------------------------------
# Appointment — invariants dataclass (entité de lecture)
# ---------------------------------------------------------------------------


class TestAppointment:
    def _make(self, *, hairdresser_id: uuid.UUID | None = _HAIRDRESSER_ID) -> Appointment:
        return Appointment(
            id=_SALON_ID,  # uuid quelconque pour l'id
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=hairdresser_id,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            status="PENDING",
            client_note=None,
            created_at=datetime.datetime(2026, 1, 1),
        )

    def test_fields_preserved(self) -> None:
        appt = self._make()
        assert appt.salon_id == _SALON_ID
        assert appt.client_id == _CLIENT_ID
        assert appt.hairdresser_id == _HAIRDRESSER_ID
        assert appt.date == _DATE
        assert appt.start_time == _START
        assert appt.end_time == _END
        assert appt.status == "PENDING"
        assert appt.client_note is None

    def test_services_default_empty_tuple(self) -> None:
        appt = self._make()
        assert appt.services == ()
        assert isinstance(appt.services, tuple)

    def test_hairdresser_id_optional(self) -> None:
        appt = self._make(hairdresser_id=None)
        assert appt.hairdresser_id is None

    def test_immutable(self) -> None:
        appt = self._make()
        with pytest.raises((AttributeError, TypeError)):
            appt.status = "CONFIRMED"  # type: ignore[misc]

    def test_services_stored_as_tuple(self) -> None:
        svc = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        appt = Appointment(
            id=_SALON_ID,
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=None,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            status="PENDING",
            client_note="Note.",
            created_at=datetime.datetime(2026, 1, 1),
            services=(svc,),
        )
        assert len(appt.services) == 1
        assert appt.services[0].service_id == _SERVICE_ID
        assert appt.client_note == "Note."
