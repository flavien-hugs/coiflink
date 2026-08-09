"""Tests unitaires — cas d'usage Dashboard Manager (application/dashboard.py, #148).

Ports remplacés par des fakes en mémoire : aucun I/O, aucune base.

Couvre :
- `SummarizeDashboardKpis` : délégation aux ports (période + période précédente),
  compteur in_progress dérivé de `is_in_progress`, évolution correcte (up/down/flat),
  lecture pure (aucune écriture) ;
- `SummarizeRevenueSeries` : délégation à `net_revenue_series`, buckets vides
  complétés à `0.00`, axe continu ;
- `SummarizeAttendanceSeries` : délégation à `attendance_series`, buckets vides
  complétés à `0`, axe continu ;
- `ListRecentActivity` : fusion paiements + notifications, tri décroissant, top-N,
  déduplication des notifications (même type + appointment_id), filtrage des types
  non-activité (CONFIRMATION/REMINDER) ;
- `ListDashboardAlerts` : alerte `late` (CONFIRMED dépassé et hors créneau),
  `prolonged_wait` (PENDING dépassé), `payment_anomaly` (délégation au port),
  omission des alertes à 0, ordre stable ;
- isolation salon_id : tous les appels aux ports propagent le salon_id fourni.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Mapping

from coiflink_api.application.dashboard import (
    ListDashboardAlerts,
    ListInProgressServices,
    ListRecentActivity,
    SummarizeAttendanceSeries,
    SummarizeDashboardKpis,
    SummarizeRevenueSeries,
)
from coiflink_api.domain.appointment import Appointment
from coiflink_api.domain.dashboard import InProgressService
from coiflink_api.domain.discrepancy import DiscrepancyFilter
from coiflink_api.domain.enums import AppointmentStatus, NotificationType
from coiflink_api.domain.notification import SalonNotification
from coiflink_api.domain.payment import DEFAULT_CURRENCY, Payment
from coiflink_api.domain.transaction import Transaction, TransactionFilter

# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000148")
_TODAY = datetime.date(2026, 8, 7)
_DATE_FROM = _TODAY
_DATE_TO = datetime.date(2026, 8, 7)

_NOW = datetime.datetime(2026, 8, 7, 14, 30)  # naïf, 14h30

_APPT_ID_1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
_APPT_ID_2 = uuid.UUID("11111111-0000-0000-0000-000000000002")
_CLIENT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")

_ZERO_MONEY = decimal.Decimal("0.00")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_appointment(
    *,
    appointment_id: uuid.UUID = _APPT_ID_1,
    date: datetime.date = _TODAY,
    start_time: datetime.time = datetime.time(14, 0),
    end_time: datetime.time = datetime.time(15, 30),
    status: str = AppointmentStatus.CONFIRMED.value,
) -> Appointment:
    return Appointment(
        id=appointment_id,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=None,
        date=date,
        start_time=start_time,
        end_time=end_time,
        status=status,
        client_note=None,
        created_at=datetime.datetime(2026, 8, 1, 10, 0),
    )


def _make_payment(
    *,
    amount: decimal.Decimal = decimal.Decimal("15000.00"),
    created_at: datetime.datetime | None = None,
) -> Transaction:
    payment = Payment(
        id=uuid.uuid4(),
        salon_id=_SALON_ID,
        amount=amount,
        currency=DEFAULT_CURRENCY,
        payment_method="CASH",
        status="VALIDATED",
        recorded_by=uuid.uuid4(),
        appointment_id=None,
        service_id=None,
        client_id=_CLIENT_ID,
        reference=None,
        created_at=created_at or datetime.datetime(2026, 8, 7, 12, 0),
    )
    return Transaction(payment=payment, client_name="Awa Koné")


def _make_notification(
    *,
    ntype: str = NotificationType.NEW_BOOKING.value,
    appointment_id: uuid.UUID | None = _APPT_ID_1,
    created_at: datetime.datetime | None = None,
    title: str = "Nouvelle réservation",
) -> SalonNotification:
    return SalonNotification(
        created_at=created_at or datetime.datetime(2026, 8, 7, 11, 0),
        type=ntype,
        title=title,
        message="Un nouveau rendez-vous a été réservé.",
        appointment_id=appointment_id,
    )


# ---------------------------------------------------------------------------
# Fakes — AppointmentRepository
# ---------------------------------------------------------------------------


class FakeAppointmentRepo:
    """Fake du port `AppointmentRepository` pour les use cases du dashboard (#148).

    `counts_by_status` : résultat de `count_by_status_in_range` (mapping statut→count).
    `distinct_clients` : résultat de `count_distinct_completed_clients`.
    `appointments` : liste renvoyée par `list_for_salon` et `list_in_progress_details`.
    `in_progress_items` : résultat de `list_in_progress_details`.
    `attendance` : résultat de `attendance_series`.
    """

    def __init__(
        self,
        counts_by_status: list[Mapping[str, int]] | None = None,
        distinct_clients: list[int] | None = None,
        appointments: tuple[Appointment, ...] = (),
        in_progress_items: tuple[InProgressService, ...] = (),
        attendance: Mapping[datetime.date, int] | None = None,
    ) -> None:
        self._counts_by_status = counts_by_status or [{}]
        self._distinct_clients = distinct_clients or [0]
        self._appointments = appointments
        self._in_progress_items = in_progress_items
        self._attendance = attendance or {}
        self.count_by_status_calls: list[dict] = []
        self.distinct_clients_calls: list[dict] = []
        self.list_for_salon_calls: list[dict] = []
        self.in_progress_calls: list[dict] = []
        self.attendance_calls: list[dict] = []
        self._count_idx = 0
        self._clients_idx = 0

    def count_by_status_in_range(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[str, int]:
        self.count_by_status_calls.append(
            {"salon_id": salon_id, "statuses": statuses, "date_from": date_from, "date_to": date_to}
        )
        result = self._counts_by_status[self._count_idx % len(self._counts_by_status)]
        self._count_idx += 1
        return result

    def count_distinct_completed_clients(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> int:
        self.distinct_clients_calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to}
        )
        result = self._distinct_clients[self._clients_idx % len(self._distinct_clients)]
        self._clients_idx += 1
        return result

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        self.list_for_salon_calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to, "statuses": statuses}
        )
        if statuses is None:
            return self._appointments
        return tuple(appt for appt in self._appointments if appt.status in statuses)

    def list_in_progress_details(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> tuple[InProgressService, ...]:
        self.in_progress_calls.append({"salon_id": salon_id, "now": now})
        return self._in_progress_items

    def attendance_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, int]:
        self.attendance_calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to}
        )
        return self._attendance

    # Méthodes non utilisées par le dashboard — levée explicite si appelées.
    def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError("no writes in dashboard use cases")

    def count_by_status_for_day(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fakes — CashJournalRepository
# ---------------------------------------------------------------------------


class FakeCashJournalRepo:
    """Fake du port `CashJournalRepository` pour le dashboard (#148).

    `revenues` : liste de `Decimal` renvoyés dans l'ordre des appels à
    `net_revenue_between` (période courante puis précédente, 2 appels par KPI).
    `series` : résultat de `net_revenue_series`.
    """

    def __init__(
        self,
        revenues: list[decimal.Decimal] | None = None,
        series: Mapping[datetime.date, decimal.Decimal] | None = None,
    ) -> None:
        self._revenues = revenues or [_ZERO_MONEY]
        self._series: Mapping[datetime.date, decimal.Decimal] = series or {}
        self.net_revenue_calls: list[dict] = []
        self.series_calls: list[dict] = []
        self._call_idx = 0

    def net_revenue_between(
        self,
        salon_id: uuid.UUID,
        *,
        created_at_from: datetime.datetime,
        created_at_to: datetime.datetime,
    ) -> decimal.Decimal:
        self.net_revenue_calls.append(
            {"salon_id": salon_id, "from": created_at_from, "to": created_at_to}
        )
        result = self._revenues[self._call_idx % len(self._revenues)]
        self._call_idx += 1
        return result

    def net_revenue_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, decimal.Decimal]:
        self.series_calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to}
        )
        return self._series

    def append(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError("no writes in dashboard use cases")

    def list_for_salon(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fakes — PaymentRepository
# ---------------------------------------------------------------------------


class FakePaymentRepo:
    """Fake du port `PaymentRepository` pour le dashboard (#148).

    `transactions` : renvoyées par `list_for_salon`.
    `anomaly_count` : valeur de `count_completed_without_payment`.
    """

    def __init__(
        self,
        transactions: tuple[Transaction, ...] = (),
        anomaly_count: int = 0,
    ) -> None:
        self._transactions = transactions
        self._anomaly_count = anomaly_count
        self.list_calls: list[dict] = []
        self.anomaly_calls: list[dict] = []

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        filter: TransactionFilter,
        limit: int,
        offset: int,
    ) -> tuple[Transaction, ...]:
        self.list_calls.append({"salon_id": salon_id, "limit": limit})
        return self._transactions

    def count_completed_without_payment(
        self, salon_id: uuid.UUID, *, filter: DiscrepancyFilter
    ) -> int:
        self.anomaly_calls.append({"salon_id": salon_id})
        return self._anomaly_count

    def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError("no writes in dashboard use cases")


# ---------------------------------------------------------------------------
# Fakes — NotificationRepository
# ---------------------------------------------------------------------------


class FakeNotificationRepo:
    """Fake du port `NotificationRepository` pour le dashboard (#148).

    `notifications` : renvoyées par `list_for_salon`.
    """

    def __init__(self, notifications: tuple[SalonNotification, ...] = ()) -> None:
        self._notifications = notifications
        self.list_calls: list[dict] = []

    def list_for_salon(
        self, salon_id: uuid.UUID, *, limit: int
    ) -> tuple[SalonNotification, ...]:
        self.list_calls.append({"salon_id": salon_id, "limit": limit})
        return self._notifications

    def enqueue(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError("no writes in dashboard use cases")

    def cancel_pending_for_appointment(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ===========================================================================
# SummarizeDashboardKpis
# ===========================================================================


class TestSummarizeDashboardKpisPortCalls:
    """Vérifie que les ports sont appelés avec les bons arguments."""

    def _execute(
        self,
        appt_repo: FakeAppointmentRepo,
        cash_repo: FakeCashJournalRepo,
    ):  # type: ignore[no-untyped-def]
        return SummarizeDashboardKpis(appt_repo, cash_repo).execute(
            _SALON_ID,
            date_from=_DATE_FROM,
            date_to=_DATE_TO,
            now=_NOW,
        )

    def test_count_by_status_called_twice(self) -> None:
        """Période courante et période précédente → 2 appels."""
        appt_repo = FakeAppointmentRepo()
        self._execute(appt_repo, FakeCashJournalRepo())
        assert len(appt_repo.count_by_status_calls) == 2

    def test_count_by_status_uses_pending_statuses(self) -> None:
        """Statut « en attente » = PENDING (imposé serveur)."""
        appt_repo = FakeAppointmentRepo()
        self._execute(appt_repo, FakeCashJournalRepo())
        for call in appt_repo.count_by_status_calls:
            assert AppointmentStatus.PENDING.value in call["statuses"]

    def test_count_by_status_salon_id_forwarded(self) -> None:
        appt_repo = FakeAppointmentRepo()
        self._execute(appt_repo, FakeCashJournalRepo())
        for call in appt_repo.count_by_status_calls:
            assert call["salon_id"] == _SALON_ID

    def test_net_revenue_called_twice(self) -> None:
        """Période courante et période précédente → 2 appels."""
        cash_repo = FakeCashJournalRepo()
        self._execute(FakeAppointmentRepo(), cash_repo)
        assert len(cash_repo.net_revenue_calls) == 2

    def test_net_revenue_salon_id_forwarded(self) -> None:
        cash_repo = FakeCashJournalRepo()
        self._execute(FakeAppointmentRepo(), cash_repo)
        for call in cash_repo.net_revenue_calls:
            assert call["salon_id"] == _SALON_ID

    def test_distinct_clients_called_twice(self) -> None:
        appt_repo = FakeAppointmentRepo()
        self._execute(appt_repo, FakeCashJournalRepo())
        assert len(appt_repo.distinct_clients_calls) == 2

    def test_list_for_salon_called_for_today(self) -> None:
        """L'instantané « en cours » charge les CONFIRMED du jour courant."""
        appt_repo = FakeAppointmentRepo()
        self._execute(appt_repo, FakeCashJournalRepo())
        # list_for_salon is called with today date for CONFIRMED
        confirmed_calls = [
            c for c in appt_repo.list_for_salon_calls
            if c.get("statuses") and AppointmentStatus.CONFIRMED.value in c["statuses"]
        ]
        assert len(confirmed_calls) == 1
        assert confirmed_calls[0]["date_from"] == _NOW.date()
        assert confirmed_calls[0]["date_to"] == _NOW.date()

    def test_no_write_triggered(self) -> None:
        """Lecture pure — aucune mutation."""
        appt_repo = FakeAppointmentRepo()
        cash_repo = FakeCashJournalRepo()
        self._execute(appt_repo, cash_repo)  # ne lève pas NotImplementedError


class TestSummarizeDashboardKpisAssembly:
    """Vérifie l'assemblage du `DashboardKpis`."""

    def _execute(
        self,
        *,
        counts: list[Mapping[str, int]] | None = None,
        revenues: list[decimal.Decimal] | None = None,
        clients: list[int] | None = None,
        appointments: tuple[Appointment, ...] = (),
        now: datetime.datetime = _NOW,
    ):  # type: ignore[no-untyped-def]
        appt_repo = FakeAppointmentRepo(
            counts_by_status=counts or [{}],
            distinct_clients=clients or [0],
            appointments=appointments,
        )
        cash_repo = FakeCashJournalRepo(revenues=revenues or [_ZERO_MONEY])
        return SummarizeDashboardKpis(appt_repo, cash_repo).execute(
            _SALON_ID,
            date_from=_DATE_FROM,
            date_to=_DATE_TO,
            now=now,
        )

    def test_kpis_date_from_to_forwarded(self) -> None:
        kpis = self._execute()
        assert kpis.date_from == _DATE_FROM
        assert kpis.date_to == _DATE_TO

    def test_currency_is_default(self) -> None:
        kpis = self._execute()
        assert kpis.currency == DEFAULT_CURRENCY

    def test_waiting_clients_evolution_up(self) -> None:
        kpis = self._execute(counts=[{AppointmentStatus.PENDING.value: 5}, {AppointmentStatus.PENDING.value: 3}])
        assert kpis.waiting_clients.current == 5
        assert kpis.waiting_clients.previous == 3
        assert kpis.waiting_clients.direction == "up"

    def test_waiting_clients_evolution_down(self) -> None:
        kpis = self._execute(counts=[{AppointmentStatus.PENDING.value: 2}, {AppointmentStatus.PENDING.value: 7}])
        assert kpis.waiting_clients.direction == "down"

    def test_waiting_clients_zero_when_no_pending(self) -> None:
        kpis = self._execute(counts=[{}, {}])
        assert kpis.waiting_clients.current == 0
        assert kpis.waiting_clients.previous == 0
        assert kpis.waiting_clients.direction == "flat"

    def test_revenue_evolution_assembled(self) -> None:
        kpis = self._execute(revenues=[decimal.Decimal("100000.00"), decimal.Decimal("80000.00")])
        assert kpis.revenue.current == decimal.Decimal("100000.00")
        assert kpis.revenue.previous == decimal.Decimal("80000.00")
        assert kpis.revenue.direction == "up"

    def test_clients_count_evolution_assembled(self) -> None:
        kpis = self._execute(clients=[10, 8])
        assert kpis.clients_count.current == 10
        assert kpis.clients_count.previous == 8

    def test_in_progress_zero_when_no_confirmed(self) -> None:
        kpis = self._execute(appointments=())
        assert kpis.in_progress == 0

    def test_in_progress_counts_only_current_slot(self) -> None:
        """Seuls les RDV CONFIRMED dont le créneau contient now sont comptés."""
        inside = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 30),
            status=AppointmentStatus.CONFIRMED.value,
        )
        outside = _make_appointment(
            appointment_id=_APPT_ID_2,
            start_time=datetime.time(10, 0), end_time=datetime.time(11, 0),
            status=AppointmentStatus.CONFIRMED.value,
        )
        kpis = self._execute(
            appointments=(inside, outside),
            now=datetime.datetime(2026, 8, 7, 14, 30),
        )
        assert kpis.in_progress == 1

    def test_in_progress_excludes_pending_appointments(self) -> None:
        """Un RDV PENDING n'est pas « en cours » même si l'heure est dans le créneau."""
        pending = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 30),
            status=AppointmentStatus.PENDING.value,
        )
        # list_for_salon est interrogé avec statuses=(CONFIRMED,) : un PENDING n'est
        # jamais renvoyé, donc jamais compté « en cours ».
        kpis = self._execute(
            appointments=(pending,),
            now=datetime.datetime(2026, 8, 7, 14, 30),
        )
        assert kpis.in_progress == 0

    def test_in_progress_at_exact_start_is_counted(self) -> None:
        """Borne basse inclusive : à l'heure exacte de début, le RDV est en cours."""
        appt = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 0),
            status=AppointmentStatus.CONFIRMED.value,
        )
        kpis = self._execute(
            appointments=(appt,),
            now=datetime.datetime(2026, 8, 7, 14, 0),
        )
        assert kpis.in_progress == 1

    def test_in_progress_at_exact_end_is_not_counted(self) -> None:
        """Borne haute exclusive : à l'heure de fin, le RDV n'est plus en cours."""
        appt = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 0),
            status=AppointmentStatus.CONFIRMED.value,
        )
        kpis = self._execute(
            appointments=(appt,),
            now=datetime.datetime(2026, 8, 7, 15, 0),
        )
        assert kpis.in_progress == 0


# ===========================================================================
# SummarizeRevenueSeries
# ===========================================================================


class TestSummarizeRevenueSeries:
    def test_delegates_to_net_revenue_series(self) -> None:
        cash_repo = FakeCashJournalRepo()
        SummarizeRevenueSeries(cash_repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert len(cash_repo.series_calls) == 1
        assert cash_repo.series_calls[0]["salon_id"] == _SALON_ID
        assert cash_repo.series_calls[0]["date_from"] == _DATE_FROM

    def test_returns_tuple_of_buckets(self) -> None:
        cash_repo = FakeCashJournalRepo()
        result = SummarizeRevenueSeries(cash_repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert isinstance(result, tuple)

    def test_empty_series_filled_with_zeros(self) -> None:
        cash_repo = FakeCashJournalRepo(series={})
        result = SummarizeRevenueSeries(cash_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 3),
        )
        assert len(result) == 3
        assert all(b.value == _ZERO_MONEY for b in result)

    def test_known_day_value_passed_through(self) -> None:
        d = datetime.date(2026, 8, 5)
        amount = decimal.Decimal("35000.00")
        cash_repo = FakeCashJournalRepo(series={d: amount})
        result = SummarizeRevenueSeries(cash_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 4),
            date_to=datetime.date(2026, 8, 6),
        )
        bucket = next(b for b in result if b.bucket_start == d)
        assert bucket.value == amount

    def test_salon_id_isolation(self) -> None:
        other = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
        cash_repo = FakeCashJournalRepo()
        SummarizeRevenueSeries(cash_repo).execute(
            other, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert cash_repo.series_calls[0]["salon_id"] == other


# ===========================================================================
# SummarizeAttendanceSeries
# ===========================================================================


class TestSummarizeAttendanceSeries:
    def test_delegates_to_attendance_series(self) -> None:
        appt_repo = FakeAppointmentRepo()
        SummarizeAttendanceSeries(appt_repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert len(appt_repo.attendance_calls) == 1
        assert appt_repo.attendance_calls[0]["salon_id"] == _SALON_ID

    def test_empty_attendance_filled_with_zeros(self) -> None:
        appt_repo = FakeAppointmentRepo(attendance={})
        result = SummarizeAttendanceSeries(appt_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 3),
        )
        assert len(result) == 3
        assert all(b.value == 0 for b in result)

    def test_known_day_count_passed_through(self) -> None:
        d = datetime.date(2026, 8, 2)
        appt_repo = FakeAppointmentRepo(attendance={d: 7})
        result = SummarizeAttendanceSeries(appt_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 3),
        )
        bucket = next(b for b in result if b.bucket_start == d)
        assert bucket.value == 7

    def test_missing_day_zero_value(self) -> None:
        d_present = datetime.date(2026, 8, 2)
        appt_repo = FakeAppointmentRepo(attendance={d_present: 5})
        result = SummarizeAttendanceSeries(appt_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 3),
        )
        bucket_absent = next(b for b in result if b.bucket_start == datetime.date(2026, 8, 1))
        assert bucket_absent.value == 0


# ===========================================================================
# ListInProgressServices
# ===========================================================================


class TestListInProgressServices:
    def test_delegates_to_list_in_progress_details(self) -> None:
        item = InProgressService(
            appointment_id=str(_APPT_ID_1),
            client_name="Awa Koné",
            service_names=("Coupe femme",),
            hairdresser_name="Fatou D.",
            start_time=datetime.time(14, 0),
            end_time=datetime.time(15, 30),
            status=AppointmentStatus.CONFIRMED.value,
        )
        appt_repo = FakeAppointmentRepo(in_progress_items=(item,))
        result = ListInProgressServices(appt_repo).execute(_SALON_ID, now=_NOW)
        assert result == (item,)
        assert appt_repo.in_progress_calls[0]["salon_id"] == _SALON_ID
        assert appt_repo.in_progress_calls[0]["now"] == _NOW

    def test_empty_result_is_empty_tuple(self) -> None:
        appt_repo = FakeAppointmentRepo()
        result = ListInProgressServices(appt_repo).execute(_SALON_ID, now=_NOW)
        assert result == ()


# ===========================================================================
# ListRecentActivity
# ===========================================================================


class TestListRecentActivity:
    def test_merges_payments_and_notifications(self) -> None:
        txn = _make_payment(created_at=datetime.datetime(2026, 8, 7, 12, 0))
        notif = _make_notification(created_at=datetime.datetime(2026, 8, 7, 11, 0))
        result = ListRecentActivity(
            FakePaymentRepo(transactions=(txn,)),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 2

    def test_sorted_most_recent_first(self) -> None:
        txn = _make_payment(created_at=datetime.datetime(2026, 8, 7, 10, 0))
        notif = _make_notification(created_at=datetime.datetime(2026, 8, 7, 12, 0))
        result = ListRecentActivity(
            FakePaymentRepo(transactions=(txn,)),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert result[0].kind == "new_booking"  # notif plus récente
        assert result[1].kind == "payment"

    def test_top_n_limit_applied(self) -> None:
        txns = tuple(_make_payment(created_at=datetime.datetime(2026, 8, 7, i, 0)) for i in range(5))
        result = ListRecentActivity(
            FakePaymentRepo(transactions=txns),
            FakeNotificationRepo(),
        ).execute(_SALON_ID, limit=3)
        assert len(result) == 3

    def test_deduplicates_notifications_same_key(self) -> None:
        """Deux notifications de même (type, appointment_id) → une seule entrée."""
        notif1 = _make_notification(
            ntype=NotificationType.NEW_BOOKING.value,
            appointment_id=_APPT_ID_1,
            created_at=datetime.datetime(2026, 8, 7, 10, 0),
        )
        notif2 = _make_notification(
            ntype=NotificationType.NEW_BOOKING.value,
            appointment_id=_APPT_ID_1,
            created_at=datetime.datetime(2026, 8, 7, 11, 0),
        )
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif1, notif2)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 1

    def test_different_appointment_ids_not_deduplicated(self) -> None:
        notif1 = _make_notification(appointment_id=_APPT_ID_1)
        notif2 = _make_notification(appointment_id=_APPT_ID_2)
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif1, notif2)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 2

    def test_confirmation_notification_filtered_out(self) -> None:
        """CONFIRMATION et REMINDER ne sont pas de l'activité salon."""
        notif = _make_notification(ntype=NotificationType.CONFIRMATION.value)
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 0

    def test_reminder_notification_filtered_out(self) -> None:
        notif = _make_notification(ntype=NotificationType.REMINDER.value)
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 0

    def test_cancellation_notification_included(self) -> None:
        notif = _make_notification(ntype=NotificationType.CANCELLATION.value)
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 1
        assert result[0].kind == "cancellation"

    def test_appointment_update_notification_included(self) -> None:
        notif = _make_notification(ntype=NotificationType.APPOINTMENT_UPDATE.value)
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert len(result) == 1
        assert result[0].kind == "appointment_update"

    def test_payment_event_has_amount_and_client_name(self) -> None:
        txn = _make_payment(amount=decimal.Decimal("15000.00"))
        result = ListRecentActivity(
            FakePaymentRepo(transactions=(txn,)),
            FakeNotificationRepo(),
        ).execute(_SALON_ID, limit=10)
        assert result[0].kind == "payment"
        assert result[0].amount == decimal.Decimal("15000.00")
        assert result[0].client_name == "Awa Koné"

    def test_notification_event_has_no_amount(self) -> None:
        notif = _make_notification()
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(notifications=(notif,)),
        ).execute(_SALON_ID, limit=10)
        assert result[0].amount is None

    def test_empty_when_no_source(self) -> None:
        result = ListRecentActivity(
            FakePaymentRepo(),
            FakeNotificationRepo(),
        ).execute(_SALON_ID, limit=20)
        assert result == ()

    def test_salon_id_forwarded_to_payment_repo(self) -> None:
        payment_repo = FakePaymentRepo()
        ListRecentActivity(payment_repo, FakeNotificationRepo()).execute(
            _SALON_ID, limit=10
        )
        assert payment_repo.list_calls[0]["salon_id"] == _SALON_ID

    def test_salon_id_forwarded_to_notification_repo(self) -> None:
        notif_repo = FakeNotificationRepo()
        ListRecentActivity(FakePaymentRepo(), notif_repo).execute(
            _SALON_ID, limit=10
        )
        assert notif_repo.list_calls[0]["salon_id"] == _SALON_ID


# ===========================================================================
# ListDashboardAlerts
# ===========================================================================


class TestListDashboardAlerts:
    """Alertes dérivées de faits réels — counts-only, aucune PII (#148)."""

    def _execute(
        self,
        appointments: tuple[Appointment, ...] = (),
        anomaly_count: int = 0,
        now: datetime.datetime = _NOW,
    ):  # type: ignore[no-untyped-def]
        appt_repo = FakeAppointmentRepo(appointments=appointments)
        payment_repo = FakePaymentRepo(anomaly_count=anomaly_count)
        return ListDashboardAlerts(appt_repo, payment_repo).execute(
            _SALON_ID, now=now
        )

    def test_empty_when_no_alerts(self) -> None:
        """Aucun RDV en retard, aucune attente prolongée, aucune anomalie → liste vide."""
        result = self._execute()
        assert result == ()

    def test_late_alert_confirmed_slot_started_not_in_progress(self) -> None:
        """RDV CONFIRMED dont le créneau est passé sans clôture → alerte `late`."""
        now = datetime.datetime(2026, 8, 7, 16, 0)
        # Créneau 14h00–15h30 : commencé (has_started) et terminé (pas en cours).
        late_appt = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 30),
            status=AppointmentStatus.CONFIRMED.value,
        )
        result = self._execute(appointments=(late_appt,), now=now)
        late_alerts = [a for a in result if a.kind == "late"]
        assert len(late_alerts) == 1
        assert late_alerts[0].count == 1
        assert late_alerts[0].severity == "warning"

    def test_late_alert_not_emitted_if_in_progress(self) -> None:
        """Un RDV CONFIRMED en cours (maintenant) n'est pas « en retard »."""
        now = datetime.datetime(2026, 8, 7, 14, 30)
        in_progress = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 30),
            status=AppointmentStatus.CONFIRMED.value,
        )
        result = self._execute(appointments=(in_progress,), now=now)
        late_alerts = [a for a in result if a.kind == "late"]
        assert len(late_alerts) == 0

    def test_late_alert_not_emitted_before_start(self) -> None:
        """Un RDV CONFIRMED dont le début n'est pas encore passé n'est pas en retard."""
        now = datetime.datetime(2026, 8, 7, 13, 0)
        future_appt = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 0),
            status=AppointmentStatus.CONFIRMED.value,
        )
        result = self._execute(appointments=(future_appt,), now=now)
        assert not any(a.kind == "late" for a in result)

    def test_prolonged_wait_alert_pending_start_passed(self) -> None:
        """RDV PENDING dont le début est dépassé → alerte `prolonged_wait`."""
        now = datetime.datetime(2026, 8, 7, 15, 0)
        pending_overdue = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 30),
            status=AppointmentStatus.PENDING.value,
        )
        result = self._execute(appointments=(pending_overdue,), now=now)
        pw_alerts = [a for a in result if a.kind == "prolonged_wait"]
        assert len(pw_alerts) == 1
        assert pw_alerts[0].count == 1
        assert pw_alerts[0].severity == "info"

    def test_prolonged_wait_not_emitted_before_start(self) -> None:
        now = datetime.datetime(2026, 8, 7, 13, 0)
        future_pending = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 0),
            status=AppointmentStatus.PENDING.value,
        )
        result = self._execute(appointments=(future_pending,), now=now)
        assert not any(a.kind == "prolonged_wait" for a in result)

    def test_payment_anomaly_alert_from_port(self) -> None:
        """Alerte `payment_anomaly` déléguée au port, count > 0 → incluse."""
        result = self._execute(anomaly_count=3)
        pa_alerts = [a for a in result if a.kind == "payment_anomaly"]
        assert len(pa_alerts) == 1
        assert pa_alerts[0].count == 3
        assert pa_alerts[0].severity == "warning"

    def test_payment_anomaly_zero_omitted(self) -> None:
        result = self._execute(anomaly_count=0)
        assert not any(a.kind == "payment_anomaly" for a in result)

    def test_stable_order_payment_anomaly_late_prolonged(self) -> None:
        """Ordre d'affichage stable : payment_anomaly → late → prolonged_wait."""
        now = datetime.datetime(2026, 8, 7, 16, 0)
        late_appt = _make_appointment(
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 0),
            status=AppointmentStatus.CONFIRMED.value,
        )
        pending_appt = _make_appointment(
            appointment_id=_APPT_ID_2,
            start_time=datetime.time(14, 0), end_time=datetime.time(15, 0),
            status=AppointmentStatus.PENDING.value,
        )
        result = self._execute(
            appointments=(late_appt, pending_appt),
            anomaly_count=2,
            now=now,
        )
        kinds = [a.kind for a in result]
        assert kinds.index("payment_anomaly") < kinds.index("late")
        assert kinds.index("late") < kinds.index("prolonged_wait")

    def test_alert_count_zero_never_emitted(self) -> None:
        """Une alerte dont l'effectif est 0 n'est jamais incluse."""
        result = self._execute(appointments=(), anomaly_count=0)
        for alert in result:
            assert alert.count > 0

    def test_salon_id_forwarded_to_appointment_repo(self) -> None:
        appt_repo = FakeAppointmentRepo()
        payment_repo = FakePaymentRepo()
        ListDashboardAlerts(appt_repo, payment_repo).execute(_SALON_ID, now=_NOW)
        assert all(c["salon_id"] == _SALON_ID for c in appt_repo.list_for_salon_calls)

    def test_salon_id_forwarded_to_payment_repo(self) -> None:
        appt_repo = FakeAppointmentRepo()
        payment_repo = FakePaymentRepo(anomaly_count=1)
        ListDashboardAlerts(appt_repo, payment_repo).execute(_SALON_ID, now=_NOW)
        assert payment_repo.anomaly_calls[0]["salon_id"] == _SALON_ID

    def test_list_for_salon_called_once_for_today(self) -> None:
        """Un seul appel `list_for_salon(today, today)` — pas deux requêtes distinctes."""
        appt_repo = FakeAppointmentRepo()
        payment_repo = FakePaymentRepo()
        ListDashboardAlerts(appt_repo, payment_repo).execute(_SALON_ID, now=_NOW)
        today_calls = [
            c for c in appt_repo.list_for_salon_calls
            if c["date_from"] == _NOW.date() and c["date_to"] == _NOW.date()
        ]
        assert len(today_calls) == 1
