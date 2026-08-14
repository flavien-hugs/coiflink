"""Tests unitaires — cas d'usage Dashboard Manager (application/dashboard.py, #148).

Ports remplacés par des fakes en mémoire : aucun I/O, aucune base. Rebranché sur
`queue_tickets` (pivot walk-in exclusif) : les anciens ports RDV (`AppointmentRepository`,
`NotificationRepository`) ont disparu.

Couvre :
- `SummarizeDashboardKpis` : délégation aux ports (période + période précédente),
  compteur `in_progress` délégué à `count_in_progress` (décompte direct, plus de
  dérivation de créneau), évolution correcte (up/down/flat), lecture pure (aucune
  écriture) ;
- `SummarizeRevenueSeries` : délégation à `net_revenue_series`, buckets vides
  complétés à `0.00`, axe continu ;
- `SummarizeAttendanceSeries` : délégation à `attendance_series`, buckets vides
  complétés à `0`, axe continu ;
- `ListInProgressServices` : délégation à `list_in_progress_details` ;
- `ListRecentActivity` : paiements seulement (les notifications ont disparu avec le
  pivot walk-in), tri décroissant, top-N ;
- `ListDashboardAlerts` : `prolonged_wait` (délégation à `count_waiting_beyond_estimate`),
  `payment_anomaly` (délégation au port), omission des alertes à 0, ordre stable —
  l'ancienne alerte `late` (RDV en retard) n'a pas d'équivalent walk-in et a disparu ;
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
from coiflink_api.domain.dashboard import InProgressService
from coiflink_api.domain.discrepancy import DiscrepancyFilter
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

_TICKET_ID_1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")

_ZERO_MONEY = decimal.Decimal("0.00")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        service_id=None,
        queue_ticket_id=None,
        client_id=_CLIENT_ID,
        reference=None,
        mobile_money_phone=None,
        created_at=created_at or datetime.datetime(2026, 8, 7, 12, 0),
    )
    return Transaction(payment=payment, client_name="Awa Koné")


def _make_in_progress(
    *,
    queue_ticket_id: str = str(_TICKET_ID_1),
    client_name: str | None = "Awa Koné",
    service_names: tuple[str, ...] = ("Coupe femme",),
    hairdresser_name: str | None = "Fatou D.",
    started_at: datetime.datetime = datetime.datetime(2026, 8, 7, 14, 0),
    status: str = "in_progress",
) -> InProgressService:
    return InProgressService(
        queue_ticket_id=queue_ticket_id,
        client_name=client_name,
        service_names=service_names,
        hairdresser_name=hairdresser_name,
        started_at=started_at,
        status=status,
    )


# ---------------------------------------------------------------------------
# Fakes — QueueTicketRepository
# ---------------------------------------------------------------------------


class FakeQueueTicketRepo:
    """Fake du port `QueueTicketRepository` pour les use cases du dashboard (#148).

    `counts_by_status` : résultat de `count_by_status_in_range` (mapping statut→count).
    `distinct_clients` : résultat de `count_distinct_completed_clients`.
    `in_progress_items` : résultat de `list_in_progress_details`.
    `in_progress_count` : résultat de `count_in_progress`.
    `waiting_beyond_estimate` : résultat de `count_waiting_beyond_estimate`.
    `attendance` : résultat de `attendance_series`.
    """

    def __init__(
        self,
        counts_by_status: list[Mapping[str, int]] | None = None,
        distinct_clients: list[int] | None = None,
        in_progress_items: tuple[InProgressService, ...] = (),
        in_progress_count: int = 0,
        waiting_beyond_estimate: int = 0,
        attendance: Mapping[datetime.date, int] | None = None,
        attendance_sequence: list[Mapping[datetime.date, int]] | None = None,
    ) -> None:
        self._counts_by_status = counts_by_status or [{}]
        self._distinct_clients = distinct_clients or [0]
        self._in_progress_items = in_progress_items
        self._in_progress_count = in_progress_count
        self._waiting_beyond_estimate = waiting_beyond_estimate
        self._attendance = attendance or {}
        # `attendance_sequence` : résultats successifs de `attendance_series`, dans
        # l'ordre des appels (utile pour distinguer aujourd'hui/hier, cf.
        # `attendance_today` — sans, `attendance_series` renvoie toujours `_attendance`).
        self._attendance_sequence = attendance_sequence
        self.count_by_status_calls: list[dict] = []
        self.distinct_clients_calls: list[dict] = []
        self.in_progress_calls: list[dict] = []
        self.count_in_progress_calls: list[dict] = []
        self.waiting_beyond_estimate_calls: list[dict] = []
        self.attendance_calls: list[dict] = []
        self._count_idx = 0
        self._clients_idx = 0
        self._attendance_idx = 0

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
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> int:
        self.distinct_clients_calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to}
        )
        result = self._distinct_clients[self._clients_idx % len(self._distinct_clients)]
        self._clients_idx += 1
        return result

    def count_in_progress(self, salon_id: uuid.UUID) -> int:
        self.count_in_progress_calls.append({"salon_id": salon_id})
        return self._in_progress_count

    def count_waiting_beyond_estimate(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> int:
        self.waiting_beyond_estimate_calls.append({"salon_id": salon_id, "now": now})
        return self._waiting_beyond_estimate

    def list_in_progress_details(
        self, salon_id: uuid.UUID
    ) -> tuple[InProgressService, ...]:
        self.in_progress_calls.append({"salon_id": salon_id})
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
        if self._attendance_sequence is not None:
            result = self._attendance_sequence[
                self._attendance_idx % len(self._attendance_sequence)
            ]
            self._attendance_idx += 1
            return result
        return self._attendance

    # Méthodes non utilisées par le dashboard — levée explicite si appelées.
    def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError("no writes in dashboard use cases")

    def demand_by_service(self, *args, **kwargs):  # type: ignore[no-untyped-def]
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


# ===========================================================================
# SummarizeDashboardKpis
# ===========================================================================


class TestSummarizeDashboardKpisPortCalls:
    """Vérifie que les ports sont appelés avec les bons arguments."""

    def _execute(
        self,
        tickets_repo: FakeQueueTicketRepo,
        cash_repo: FakeCashJournalRepo,
    ):  # type: ignore[no-untyped-def]
        return SummarizeDashboardKpis(tickets_repo, cash_repo).execute(
            _SALON_ID,
            date_from=_DATE_FROM,
            date_to=_DATE_TO,
            now=_NOW,
        )

    def test_count_by_status_called_twice(self) -> None:
        """Période courante et période précédente → 2 appels."""
        tickets_repo = FakeQueueTicketRepo()
        self._execute(tickets_repo, FakeCashJournalRepo())
        assert len(tickets_repo.count_by_status_calls) == 2

    def test_count_by_status_uses_waiting_status(self) -> None:
        """Statut « en attente » = `waiting` (imposé serveur)."""
        tickets_repo = FakeQueueTicketRepo()
        self._execute(tickets_repo, FakeCashJournalRepo())
        for call in tickets_repo.count_by_status_calls:
            assert "waiting" in call["statuses"]

    def test_count_by_status_salon_id_forwarded(self) -> None:
        tickets_repo = FakeQueueTicketRepo()
        self._execute(tickets_repo, FakeCashJournalRepo())
        for call in tickets_repo.count_by_status_calls:
            assert call["salon_id"] == _SALON_ID

    def test_net_revenue_called_four_times(self) -> None:
        """Période courante/précédente (2) + semaine courante/précédente fixe (2) → 4 appels."""
        cash_repo = FakeCashJournalRepo()
        self._execute(FakeQueueTicketRepo(), cash_repo)
        assert len(cash_repo.net_revenue_calls) == 4

    def test_net_revenue_salon_id_forwarded(self) -> None:
        cash_repo = FakeCashJournalRepo()
        self._execute(FakeQueueTicketRepo(), cash_repo)
        for call in cash_repo.net_revenue_calls:
            assert call["salon_id"] == _SALON_ID

    def test_distinct_clients_called_twice(self) -> None:
        tickets_repo = FakeQueueTicketRepo()
        self._execute(tickets_repo, FakeCashJournalRepo())
        assert len(tickets_repo.distinct_clients_calls) == 2

    def test_count_in_progress_called_once(self) -> None:
        """« En cours » est un instantané — un seul appel, indépendant de la période."""
        tickets_repo = FakeQueueTicketRepo()
        self._execute(tickets_repo, FakeCashJournalRepo())
        assert len(tickets_repo.count_in_progress_calls) == 1
        assert tickets_repo.count_in_progress_calls[0]["salon_id"] == _SALON_ID

    def test_no_write_triggered(self) -> None:
        """Lecture pure — aucune mutation."""
        tickets_repo = FakeQueueTicketRepo()
        cash_repo = FakeCashJournalRepo()
        self._execute(tickets_repo, cash_repo)  # ne lève pas NotImplementedError


class TestSummarizeDashboardKpisAssembly:
    """Vérifie l'assemblage du `DashboardKpis`."""

    def _execute(
        self,
        *,
        counts: list[Mapping[str, int]] | None = None,
        revenues: list[decimal.Decimal] | None = None,
        clients: list[int] | None = None,
        in_progress_count: int = 0,
        now: datetime.datetime = _NOW,
    ):  # type: ignore[no-untyped-def]
        tickets_repo = FakeQueueTicketRepo(
            counts_by_status=counts or [{}],
            distinct_clients=clients or [0],
            in_progress_count=in_progress_count,
        )
        cash_repo = FakeCashJournalRepo(revenues=revenues or [_ZERO_MONEY])
        return SummarizeDashboardKpis(tickets_repo, cash_repo).execute(
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
        kpis = self._execute(counts=[{"waiting": 5}, {"waiting": 3}])
        assert kpis.waiting_clients.current == 5
        assert kpis.waiting_clients.previous == 3
        assert kpis.waiting_clients.direction == "up"

    def test_waiting_clients_evolution_down(self) -> None:
        kpis = self._execute(counts=[{"waiting": 2}, {"waiting": 7}])
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

    def test_in_progress_zero_by_default(self) -> None:
        kpis = self._execute()
        assert kpis.in_progress == 0

    def test_in_progress_value_passed_through(self) -> None:
        """`in_progress` est le décompte direct du port — aucune arithmétique locale."""
        kpis = self._execute(in_progress_count=4)
        assert kpis.in_progress == 4


class TestSummarizeDashboardKpisFixedWindowFields:
    """`attendance_today`/`revenue_this_week` — bornes **fixes** (jour/semaine
    glissants sur `now`), volontairement indépendantes de `date_from`/`date_to`
    (cartes « À surveiller », réorganisation du tableau de bord).

    `_NOW` = vendredi 2026-08-07 : hier = 2026-08-06 ; semaine civile (lundi→
    dimanche) = 2026-08-03 → 2026-08-09 ; semaine précédente = 2026-07-27 →
    2026-08-02 (mêmes bornes que `domain/revenue.py::week_bounds`, vérifiées
    indépendamment dans `test_domain_revenue.py`).
    """

    _YESTERDAY = datetime.date(2026, 8, 6)
    _WEEK_FROM = datetime.date(2026, 8, 3)
    _WEEK_TO = datetime.date(2026, 8, 9)
    _PREV_WEEK_FROM = datetime.date(2026, 7, 27)
    _PREV_WEEK_TO = datetime.date(2026, 8, 2)

    def _execute(
        self,
        *,
        attendance_sequence: list[Mapping[datetime.date, int]] | None = None,
        revenues: list[decimal.Decimal] | None = None,
        date_from: datetime.date = _DATE_FROM,
        date_to: datetime.date = _DATE_TO,
    ):  # type: ignore[no-untyped-def]
        tickets_repo = FakeQueueTicketRepo(attendance_sequence=attendance_sequence)
        cash_repo = FakeCashJournalRepo(revenues=revenues)
        kpis = SummarizeDashboardKpis(tickets_repo, cash_repo).execute(
            _SALON_ID, date_from=date_from, date_to=date_to, now=_NOW
        )
        return kpis, tickets_repo, cash_repo

    def test_attendance_today_queried_on_today_and_yesterday_regardless_of_filter(
        self,
    ) -> None:
        """Toujours jour/veille de `now` — même si `date_from`/`date_to` diffèrent."""
        _, tickets_repo, _ = self._execute(
            date_from=datetime.date(2020, 1, 1), date_to=datetime.date(2020, 1, 31)
        )
        assert len(tickets_repo.attendance_calls) == 2
        today_call, yesterday_call = tickets_repo.attendance_calls
        assert today_call["date_from"] == today_call["date_to"] == _TODAY
        assert (
            yesterday_call["date_from"]
            == yesterday_call["date_to"]
            == self._YESTERDAY
        )

    def test_attendance_today_evolution_values(self) -> None:
        kpis, _, _ = self._execute(
            attendance_sequence=[{_TODAY: 9}, {self._YESTERDAY: 6}]
        )
        assert kpis.attendance_today.current == 9
        assert kpis.attendance_today.previous == 6
        assert kpis.attendance_today.direction == "up"

    def test_attendance_today_sums_multiple_buckets(self) -> None:
        """Le port peut renvoyer plusieurs jours (interface générique) : on somme."""
        kpis, _, _ = self._execute(
            attendance_sequence=[
                {_TODAY: 3, datetime.date(2026, 8, 5): 2},
                {self._YESTERDAY: 1},
            ]
        )
        assert kpis.attendance_today.current == 5
        assert kpis.attendance_today.previous == 1

    def test_revenue_this_week_queried_on_fixed_week_bounds_regardless_of_filter(
        self,
    ) -> None:
        """Toujours la semaine civile de `now` — jamais `date_from`/`date_to`."""
        _, _, cash_repo = self._execute(
            date_from=datetime.date(2020, 1, 1), date_to=datetime.date(2020, 1, 31)
        )
        assert len(cash_repo.net_revenue_calls) == 4
        # Les 2 derniers appels sont la semaine courante/précédente **fixes**.
        week_current_call, week_previous_call = cash_repo.net_revenue_calls[2:]
        assert week_current_call["from"].date() == self._WEEK_FROM
        assert week_current_call["to"].date() == self._WEEK_TO
        assert week_previous_call["from"].date() == self._PREV_WEEK_FROM
        assert week_previous_call["to"].date() == self._PREV_WEEK_TO

    def test_revenue_this_week_evolution_values(self) -> None:
        kpis, _, _ = self._execute(
            revenues=[
                decimal.Decimal("10.00"),  # période courante (non testée ici)
                decimal.Decimal("10.00"),  # période précédente (non testée ici)
                decimal.Decimal("210000.00"),  # semaine courante
                decimal.Decimal("178000.00"),  # semaine précédente
            ]
        )
        assert kpis.revenue_this_week.current == decimal.Decimal("210000.00")
        assert kpis.revenue_this_week.previous == decimal.Decimal("178000.00")
        assert kpis.revenue_this_week.direction == "up"


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
        tickets_repo = FakeQueueTicketRepo()
        SummarizeAttendanceSeries(tickets_repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert len(tickets_repo.attendance_calls) == 1
        assert tickets_repo.attendance_calls[0]["salon_id"] == _SALON_ID

    def test_empty_attendance_filled_with_zeros(self) -> None:
        tickets_repo = FakeQueueTicketRepo(attendance={})
        result = SummarizeAttendanceSeries(tickets_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 3),
        )
        assert len(result) == 3
        assert all(b.value == 0 for b in result)

    def test_known_day_count_passed_through(self) -> None:
        d = datetime.date(2026, 8, 2)
        tickets_repo = FakeQueueTicketRepo(attendance={d: 7})
        result = SummarizeAttendanceSeries(tickets_repo).execute(
            _SALON_ID,
            date_from=datetime.date(2026, 8, 1),
            date_to=datetime.date(2026, 8, 3),
        )
        bucket = next(b for b in result if b.bucket_start == d)
        assert bucket.value == 7

    def test_missing_day_zero_value(self) -> None:
        d_present = datetime.date(2026, 8, 2)
        tickets_repo = FakeQueueTicketRepo(attendance={d_present: 5})
        result = SummarizeAttendanceSeries(tickets_repo).execute(
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
        item = _make_in_progress()
        tickets_repo = FakeQueueTicketRepo(in_progress_items=(item,))
        result = ListInProgressServices(tickets_repo).execute(_SALON_ID)
        assert result == (item,)
        assert tickets_repo.in_progress_calls[0]["salon_id"] == _SALON_ID

    def test_empty_result_is_empty_tuple(self) -> None:
        tickets_repo = FakeQueueTicketRepo()
        result = ListInProgressServices(tickets_repo).execute(_SALON_ID)
        assert result == ()


# ===========================================================================
# ListRecentActivity
# ===========================================================================


class TestListRecentActivity:
    def test_returns_payment_events(self) -> None:
        txn = _make_payment(created_at=datetime.datetime(2026, 8, 7, 12, 0))
        result = ListRecentActivity(FakePaymentRepo(transactions=(txn,))).execute(
            _SALON_ID, limit=10
        )
        assert len(result) == 1
        assert result[0].kind == "payment"

    def test_sorted_most_recent_first(self) -> None:
        older = _make_payment(created_at=datetime.datetime(2026, 8, 7, 10, 0))
        newer = _make_payment(created_at=datetime.datetime(2026, 8, 7, 12, 0))
        result = ListRecentActivity(
            FakePaymentRepo(transactions=(older, newer))
        ).execute(_SALON_ID, limit=10)
        assert result[0].occurred_at == datetime.datetime(2026, 8, 7, 12, 0)
        assert result[1].occurred_at == datetime.datetime(2026, 8, 7, 10, 0)

    def test_top_n_limit_applied(self) -> None:
        txns = tuple(_make_payment(created_at=datetime.datetime(2026, 8, 7, i, 0)) for i in range(5))
        result = ListRecentActivity(FakePaymentRepo(transactions=txns)).execute(
            _SALON_ID, limit=3
        )
        assert len(result) == 3

    def test_payment_event_has_amount_and_client_name(self) -> None:
        txn = _make_payment(amount=decimal.Decimal("15000.00"))
        result = ListRecentActivity(FakePaymentRepo(transactions=(txn,))).execute(
            _SALON_ID, limit=10
        )
        assert result[0].kind == "payment"
        assert result[0].amount == decimal.Decimal("15000.00")
        assert result[0].client_name == "Awa Koné"

    def test_empty_when_no_source(self) -> None:
        result = ListRecentActivity(FakePaymentRepo()).execute(_SALON_ID, limit=20)
        assert result == ()

    def test_salon_id_forwarded_to_payment_repo(self) -> None:
        payment_repo = FakePaymentRepo()
        ListRecentActivity(payment_repo).execute(_SALON_ID, limit=10)
        assert payment_repo.list_calls[0]["salon_id"] == _SALON_ID


# ===========================================================================
# ListDashboardAlerts
# ===========================================================================


class TestListDashboardAlerts:
    """Alertes dérivées de faits réels — counts-only, aucune PII (#148).

    L'ancienne alerte `late` (RDV en retard) n'a pas d'équivalent walk-in (un ticket
    n'a pas de créneau) et a disparu avec le pivot — seules `payment_anomaly` et
    `prolonged_wait` subsistent.
    """

    def _execute(
        self,
        waiting_beyond_estimate: int = 0,
        anomaly_count: int = 0,
        now: datetime.datetime = _NOW,
    ):  # type: ignore[no-untyped-def]
        tickets_repo = FakeQueueTicketRepo(waiting_beyond_estimate=waiting_beyond_estimate)
        payment_repo = FakePaymentRepo(anomaly_count=anomaly_count)
        return ListDashboardAlerts(tickets_repo, payment_repo).execute(
            _SALON_ID, now=now
        )

    def test_empty_when_no_alerts(self) -> None:
        """Aucune attente prolongée, aucune anomalie → liste vide."""
        result = self._execute()
        assert result == ()

    def test_prolonged_wait_alert_from_port(self) -> None:
        """Alerte `prolonged_wait` déléguée au port, count > 0 → incluse."""
        result = self._execute(waiting_beyond_estimate=2)
        pw_alerts = [a for a in result if a.kind == "prolonged_wait"]
        assert len(pw_alerts) == 1
        assert pw_alerts[0].count == 2
        assert pw_alerts[0].severity == "info"

    def test_prolonged_wait_zero_omitted(self) -> None:
        result = self._execute(waiting_beyond_estimate=0)
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

    def test_stable_order_payment_anomaly_then_prolonged(self) -> None:
        """Ordre d'affichage stable : payment_anomaly → prolonged_wait."""
        result = self._execute(waiting_beyond_estimate=1, anomaly_count=2)
        kinds = [a.kind for a in result]
        assert kinds.index("payment_anomaly") < kinds.index("prolonged_wait")

    def test_alert_count_zero_never_emitted(self) -> None:
        """Une alerte dont l'effectif est 0 n'est jamais incluse."""
        result = self._execute(waiting_beyond_estimate=0, anomaly_count=0)
        for alert in result:
            assert alert.count > 0

    def test_salon_id_forwarded_to_queue_ticket_repo(self) -> None:
        tickets_repo = FakeQueueTicketRepo()
        payment_repo = FakePaymentRepo()
        ListDashboardAlerts(tickets_repo, payment_repo).execute(_SALON_ID, now=_NOW)
        assert tickets_repo.waiting_beyond_estimate_calls[0]["salon_id"] == _SALON_ID

    def test_salon_id_forwarded_to_payment_repo(self) -> None:
        tickets_repo = FakeQueueTicketRepo()
        payment_repo = FakePaymentRepo(anomaly_count=1)
        ListDashboardAlerts(tickets_repo, payment_repo).execute(_SALON_ID, now=_NOW)
        assert payment_repo.anomaly_calls[0]["salon_id"] == _SALON_ID

    def test_now_forwarded_to_waiting_beyond_estimate(self) -> None:
        tickets_repo = FakeQueueTicketRepo()
        payment_repo = FakePaymentRepo()
        ListDashboardAlerts(tickets_repo, payment_repo).execute(_SALON_ID, now=_NOW)
        assert tickets_repo.waiting_beyond_estimate_calls[0]["now"] == _NOW
