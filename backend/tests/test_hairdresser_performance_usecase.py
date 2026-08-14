"""Tests unitaires — cas d'usage `SummarizeHairdresserPerformance` (US-6.5, #43).

Ports remplacés par des fakes en mémoire : aucun I/O, aucune base. Rebranché sur
`queue_tickets` (pivot walk-in exclusif, #148) : le port est désormais
`QueueTicketRepository`, et l'équivalent walk-in de l'ancien statut RDV `CANCELLED`
est le ticket `expired`.

Couvre :
- `performance_by_hairdresser` appelé **une** fois avec les tickets `done` (imposé
  serveur §8.1) et `expired` ;
- `net_revenue_by_hairdresser` appelé **une** fois avec le bon `salon_id` et les
  bonnes bornes ;
- `salon_id` et bornes `date_from`/`date_to` transmis tels quels aux deux ports ;
- fusion : revenu `0.00` pour un coiffeur sans entrée dans la map caisse ;
- fusion : revenu attribué correct quand la map caisse a une entrée ;
- coiffeur avec CA en caisse mais absent de la file d'attente → exclu du rapport
  (liste déterminée par la file d'attente) ;
- rapport vide (aucun coiffeur assigné) est un état légitime ;
- lecture pure : aucune méthode de mutation déclenchée (§11.4).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Mapping

from coiflink_api.application.hairdresser_performance import SummarizeHairdresserPerformance
from coiflink_api.domain.hairdresser_performance import HairdresserActivityCounts

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000043")
_DATE_FROM = datetime.date(2026, 8, 1)
_DATE_TO = datetime.date(2026, 8, 31)

_H_ID_1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
_H_ID_2 = uuid.UUID("22222222-0000-0000-0000-000000000002")

_COMPLETED_STATUSES: tuple[str, ...] = ("done",)
_CANCELLED_STATUSES: tuple[str, ...] = ("expired",)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeQueueTicketRepository:
    """Fake du port `QueueTicketRepository` pour `SummarizeHairdresserPerformance` (#43).

    `counts` contrôle ce que `performance_by_hairdresser` renvoie.
    `calls` enregistre les arguments reçus. Les méthodes de mutation lèvent
    `NotImplementedError` (lecture pure, §11.4).
    """

    def __init__(
        self,
        counts: tuple[HairdresserActivityCounts, ...] = (),
    ) -> None:
        self._counts = counts
        self.calls: list[dict] = []

    def performance_by_hairdresser(  # type: ignore[no-untyped-def]
        self,
        salon_id,
        *,
        date_from,
        date_to,
        completed_statuses,
        cancelled_statuses,
    ):
        self.calls.append(
            {
                "salon_id": salon_id,
                "date_from": date_from,
                "date_to": date_to,
                "completed_statuses": completed_statuses,
                "cancelled_statuses": cancelled_statuses,
            }
        )
        return self._counts

    def create(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError("SummarizeHairdresserPerformance ne doit pas écrire")

    def demand_by_service(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class FakeCashJournalRepository:
    """Fake du port `CashJournalRepository` pour `SummarizeHairdresserPerformance` (#43).

    `revenue_map` contrôle ce que `net_revenue_by_hairdresser` renvoie.
    `calls` enregistre les arguments reçus. Les méthodes de mutation lèvent
    `NotImplementedError` (lecture pure, §11.4).
    """

    def __init__(
        self,
        revenue_map: Mapping[uuid.UUID, decimal.Decimal] | None = None,
    ) -> None:
        self._revenue_map: Mapping[uuid.UUID, decimal.Decimal] = revenue_map or {}
        self.calls: list[dict] = []

    def net_revenue_by_hairdresser(  # type: ignore[no-untyped-def]
        self, salon_id, *, date_from, date_to
    ):
        self.calls.append(
            {"salon_id": salon_id, "date_from": date_from, "date_to": date_to}
        )
        return self._revenue_map

    def append(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError("SummarizeHairdresserPerformance ne doit pas écrire")

    def list_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def net_revenue_between(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _counts_fixture(
    hairdresser_id: uuid.UUID = _H_ID_1,
    name: str = "Awa Koné",
    services_completed: int = 10,
    cancelled_count: int = 2,
    total_count: int = 20,
) -> HairdresserActivityCounts:
    return HairdresserActivityCounts(
        hairdresser_id=hairdresser_id,
        name=name,
        services_completed=services_completed,
        cancelled_count=cancelled_count,
        total_count=total_count,
    )


def _execute(
    counts: tuple[HairdresserActivityCounts, ...] = (),
    revenue_map: Mapping[uuid.UUID, decimal.Decimal] | None = None,
):  # type: ignore[no-untyped-def]
    tickets_repo = FakeQueueTicketRepository(counts=counts)
    cash_repo = FakeCashJournalRepository(revenue_map=revenue_map)
    result = SummarizeHairdresserPerformance(tickets_repo, cash_repo).execute(
        _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
    )
    return result, tickets_repo, cash_repo


# ---------------------------------------------------------------------------
# Arguments transmis au port queue_ticket
# ---------------------------------------------------------------------------


class TestPortQueueTicketArgs:
    def test_performance_by_hairdresser_called_once(self) -> None:
        _, tickets, _ = _execute()
        assert len(tickets.calls) == 1

    def test_salon_id_forwarded_to_queue_ticket_port(self) -> None:
        _, tickets, _ = _execute()
        assert tickets.calls[0]["salon_id"] == _SALON_ID

    def test_completed_statuses_imposed(self) -> None:
        """Tickets `done` imposé serveur, jamais soumis par l'appelant (§8.1)."""
        _, tickets, _ = _execute()
        assert tickets.calls[0]["completed_statuses"] == _COMPLETED_STATUSES

    def test_done_in_imposed_completed_statuses(self) -> None:
        _, tickets, _ = _execute()
        assert "done" in tickets.calls[0]["completed_statuses"]

    def test_cancelled_statuses_imposed(self) -> None:
        """Tickets `expired` imposé serveur, jamais soumis par l'appelant."""
        _, tickets, _ = _execute()
        assert tickets.calls[0]["cancelled_statuses"] == _CANCELLED_STATUSES

    def test_expired_in_imposed_cancelled_statuses(self) -> None:
        _, tickets, _ = _execute()
        assert "expired" in tickets.calls[0]["cancelled_statuses"]

    def test_date_from_forwarded_to_queue_ticket_port(self) -> None:
        _, tickets, _ = _execute()
        assert tickets.calls[0]["date_from"] == _DATE_FROM

    def test_date_to_forwarded_to_queue_ticket_port(self) -> None:
        _, tickets, _ = _execute()
        assert tickets.calls[0]["date_to"] == _DATE_TO


# ---------------------------------------------------------------------------
# Arguments transmis au port cash journal
# ---------------------------------------------------------------------------


class TestPortCashJournalArgs:
    def test_net_revenue_by_hairdresser_called_once(self) -> None:
        _, _, cash = _execute()
        assert len(cash.calls) == 1

    def test_salon_id_forwarded_to_cash_port(self) -> None:
        _, _, cash = _execute()
        assert cash.calls[0]["salon_id"] == _SALON_ID

    def test_date_from_forwarded_to_cash_port(self) -> None:
        _, _, cash = _execute()
        assert cash.calls[0]["date_from"] == _DATE_FROM

    def test_date_to_forwarded_to_cash_port(self) -> None:
        _, _, cash = _execute()
        assert cash.calls[0]["date_to"] == _DATE_TO


# ---------------------------------------------------------------------------
# Fusion des sources (file d'attente + caisse)
# ---------------------------------------------------------------------------


class TestRevenueFusion:
    def test_revenue_zero_when_hairdresser_absent_from_cash_map(self) -> None:
        """Coiffeur dans la file d'attente mais absent de la map caisse → CA = 0.00."""
        counts = (_counts_fixture(hairdresser_id=_H_ID_1),)
        result, _, _ = _execute(counts=counts, revenue_map={})
        assert result.entries[0].revenue == decimal.Decimal("0.00")

    def test_revenue_attributed_when_present_in_cash_map(self) -> None:
        counts = (_counts_fixture(hairdresser_id=_H_ID_1),)
        revenue_map = {_H_ID_1: decimal.Decimal("75000.00")}
        result, _, _ = _execute(counts=counts, revenue_map=revenue_map)
        assert result.entries[0].revenue == decimal.Decimal("75000.00")

    def test_hairdresser_with_cash_but_no_queue_entry_excluded(self) -> None:
        """La liste des coiffeurs dérive de la file d'attente : un coiffeur avec du CA
        mais sans ticket assigné dans la fenêtre n'apparaît pas."""
        counts = ()  # aucun coiffeur en file d'attente
        revenue_map = {_H_ID_1: decimal.Decimal("10000.00")}
        result, _, _ = _execute(counts=counts, revenue_map=revenue_map)
        assert result.entries == ()

    def test_two_hairdressers_revenues_merged_correctly(self) -> None:
        counts = (
            _counts_fixture(hairdresser_id=_H_ID_1, name="Awa"),
            _counts_fixture(hairdresser_id=_H_ID_2, name="Bintou"),
        )
        revenue_map = {
            _H_ID_1: decimal.Decimal("60000.00"),
            _H_ID_2: decimal.Decimal("40000.00"),
        }
        result, _, _ = _execute(counts=counts, revenue_map=revenue_map)
        by_id = {e.hairdresser_id: e for e in result.entries}
        assert by_id[_H_ID_1].revenue == decimal.Decimal("60000.00")
        assert by_id[_H_ID_2].revenue == decimal.Decimal("40000.00")

    def test_mixed_with_and_without_revenue(self) -> None:
        """Un coiffeur avec CA, un autre sans → le second a 0.00."""
        counts = (
            _counts_fixture(hairdresser_id=_H_ID_1),
            _counts_fixture(hairdresser_id=_H_ID_2),
        )
        revenue_map = {_H_ID_1: decimal.Decimal("30000.00")}
        result, _, _ = _execute(counts=counts, revenue_map=revenue_map)
        by_id = {e.hairdresser_id: e for e in result.entries}
        assert by_id[_H_ID_2].revenue == decimal.Decimal("0.00")


# ---------------------------------------------------------------------------
# Rapport vide
# ---------------------------------------------------------------------------


class TestEmptyReport:
    def test_empty_counts_returns_empty_entries(self) -> None:
        result, _, _ = _execute(counts=())
        assert result.entries == ()

    def test_empty_is_not_an_error(self) -> None:
        """Aucun coiffeur assigné → état légitime, pas une exception."""
        _execute(counts=())

    def test_empty_report_date_from_echoed(self) -> None:
        result, _, _ = _execute()
        assert result.date_from == _DATE_FROM

    def test_empty_report_date_to_echoed(self) -> None:
        result, _, _ = _execute()
        assert result.date_to == _DATE_TO


# ---------------------------------------------------------------------------
# Lecture pure (§11.4)
# ---------------------------------------------------------------------------


class TestReadOnly:
    def test_no_write_on_queue_ticket_repo(self) -> None:
        """Aucune méthode d'écriture ne doit être appelée sur le dépôt queue_ticket."""
        _execute()  # NotImplementedError si une écriture était déclenchée

    def test_no_append_on_cash_journal_repo(self) -> None:
        """Le dépôt caisse est en lecture seule — append lèverait NotImplementedError."""
        _execute()


# ---------------------------------------------------------------------------
# Résultat : champs du rapport
# ---------------------------------------------------------------------------


class TestReportFields:
    def test_cancellation_rate_computed(self) -> None:
        """Le taux d'annulation est calculé par la couche domaine."""
        counts = (_counts_fixture(cancelled_count=3, total_count=64),)
        result, _, _ = _execute(counts=counts)
        assert result.entries[0].cancellation_rate == decimal.Decimal("0.0469")

    def test_services_completed_preserved(self) -> None:
        counts = (_counts_fixture(services_completed=42),)
        result, _, _ = _execute(counts=counts)
        assert result.entries[0].services_completed == 42

    def test_name_preserved(self) -> None:
        counts = (_counts_fixture(name="Mariame Traoré"),)
        result, _, _ = _execute(counts=counts)
        assert result.entries[0].name == "Mariame Traoré"

    def test_hairdresser_id_preserved(self) -> None:
        counts = (_counts_fixture(hairdresser_id=_H_ID_1),)
        result, _, _ = _execute(counts=counts)
        assert result.entries[0].hairdresser_id == _H_ID_1

    def test_no_client_pii_in_result(self) -> None:
        """Le résultat ne porte aucun identifiant ou donnée de contact client (§11.3)."""
        counts = (_counts_fixture(),)
        result, _, _ = _execute(counts=counts)
        entry = result.entries[0]
        assert not hasattr(entry, "client_id")
        assert not hasattr(entry, "phone")
        assert not hasattr(entry, "email")
        assert not hasattr(entry, "queue_ticket_id")
