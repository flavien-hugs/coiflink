"""Tests unitaires — domaine « historique des visites » (US-4.2, #29).

Couvre `domain/visit.py` sans I/O ni base de données.

Cas traités :
- `visit_total` : tuple vide → `Decimal("0")`, un service, plusieurs services,
  valeurs décimales exactes (jamais de flottant) ;
- `build_history` : visites vides → résumé à défauts, une visite, plusieurs
  visites (somme + `last_visit_at` = première du tuple), devise conservée ;
- `HISTORY_STATUSES` : contient uniquement `COMPLETED` (séparé de `REVENUE_STATUSES`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.visit import (
    HISTORY_STATUSES,
    CustomerVisit,
    VisitHistory,
    VisitService,
    build_history,
    visit_total,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SERVICE_ID_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SERVICE_ID_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_APT_ID_1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
_APT_ID_2 = uuid.UUID("22222222-0000-0000-0000-000000000002")

_DATE_RECENT = datetime.date(2026, 7, 20)
_DATE_OLDER = datetime.date(2026, 6, 15)
_TIME_09 = datetime.time(9, 0, 0)
_TIME_10 = datetime.time(10, 0, 0)


def _make_service(
    service_id: uuid.UUID = _SERVICE_ID_A,
    name: str = "Coupe homme",
    price: str = "5000.00",
) -> VisitService:
    return VisitService(
        service_id=service_id,
        name=name,
        price_at_booking=decimal.Decimal(price),
    )


def _make_visit(
    appointment_id: uuid.UUID = _APT_ID_1,
    date: datetime.date = _DATE_RECENT,
    services: tuple[VisitService, ...] = (),
    total_amount: str = "0",
) -> CustomerVisit:
    return CustomerVisit(
        appointment_id=appointment_id,
        date=date,
        start_time=_TIME_09,
        end_time=_TIME_10,
        status=AppointmentStatus.COMPLETED.value,
        services=services,
        total_amount=decimal.Decimal(total_amount),
    )


# ---------------------------------------------------------------------------
# HISTORY_STATUSES
# ---------------------------------------------------------------------------


class TestHistoryStatuses:
    def test_contains_only_completed(self) -> None:
        assert HISTORY_STATUSES == (AppointmentStatus.COMPLETED.value,)

    def test_does_not_contain_pending(self) -> None:
        assert AppointmentStatus.PENDING.value not in HISTORY_STATUSES

    def test_does_not_contain_cancelled(self) -> None:
        assert AppointmentStatus.CANCELLED.value not in HISTORY_STATUSES

    def test_does_not_contain_no_show(self) -> None:
        assert AppointmentStatus.NO_SHOW.value not in HISTORY_STATUSES

    def test_does_not_contain_confirmed(self) -> None:
        assert AppointmentStatus.CONFIRMED.value not in HISTORY_STATUSES


# ---------------------------------------------------------------------------
# visit_total
# ---------------------------------------------------------------------------


class TestVisitTotal:
    def test_empty_tuple_returns_zero(self) -> None:
        assert visit_total(()) == decimal.Decimal("0")

    def test_zero_is_decimal_not_int(self) -> None:
        result = visit_total(())
        assert isinstance(result, decimal.Decimal)

    def test_single_service(self) -> None:
        service = _make_service(price="5000.00")
        assert visit_total((service,)) == decimal.Decimal("5000.00")

    def test_two_services_summed(self) -> None:
        svc_a = _make_service(price="5000.00")
        svc_b = _make_service(service_id=_SERVICE_ID_B, price="2000.00")
        assert visit_total((svc_a, svc_b)) == decimal.Decimal("7000.00")

    def test_result_is_decimal(self) -> None:
        svc = _make_service(price="1234.56")
        result = visit_total((svc,))
        assert isinstance(result, decimal.Decimal)

    def test_decimal_precision_preserved(self) -> None:
        svc_a = _make_service(price="1000.50")
        svc_b = _make_service(service_id=_SERVICE_ID_B, price="999.50")
        assert visit_total((svc_a, svc_b)) == decimal.Decimal("2000.00")

    def test_three_services(self) -> None:
        svc_c = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        svc_a = _make_service(price="5000.00")
        svc_b = _make_service(service_id=_SERVICE_ID_B, price="2000.00")
        svc_c_obj = VisitService(
            service_id=svc_c, name="Soin", price_at_booking=decimal.Decimal("1500.00")
        )
        assert visit_total((svc_a, svc_b, svc_c_obj)) == decimal.Decimal("8500.00")


# ---------------------------------------------------------------------------
# build_history
# ---------------------------------------------------------------------------


class TestBuildHistoryEmpty:
    def test_empty_visits_returns_visit_history(self) -> None:
        result = build_history(())
        assert isinstance(result, VisitHistory)

    def test_empty_visits_total_visits_is_zero(self) -> None:
        result = build_history(())
        assert result.total_visits == 0

    def test_empty_visits_last_visit_at_is_none(self) -> None:
        result = build_history(())
        assert result.last_visit_at is None

    def test_empty_visits_total_amount_is_zero(self) -> None:
        result = build_history(())
        assert result.total_amount == decimal.Decimal("0")

    def test_empty_visits_currency_is_xof(self) -> None:
        result = build_history(())
        assert result.currency == "XOF"

    def test_empty_visits_items_tuple_empty(self) -> None:
        result = build_history(())
        assert result.visits == ()

    def test_custom_currency_preserved(self) -> None:
        result = build_history((), currency="EUR")
        assert result.currency == "EUR"


class TestBuildHistorySingleVisit:
    def setup_method(self) -> None:
        svc = _make_service(price="7000.00")
        self.visit = _make_visit(
            services=(svc,),
            total_amount="7000.00",
        )
        self.history = build_history((self.visit,))

    def test_total_visits_is_one(self) -> None:
        assert self.history.total_visits == 1

    def test_total_amount_matches_visit(self) -> None:
        assert self.history.total_amount == decimal.Decimal("7000.00")

    def test_last_visit_at_combines_date_and_start_time(self) -> None:
        expected = datetime.datetime.combine(_DATE_RECENT, _TIME_09)
        assert self.history.last_visit_at == expected

    def test_visits_contains_the_visit(self) -> None:
        assert self.history.visits == (self.visit,)

    def test_currency_is_xof(self) -> None:
        assert self.history.currency == "XOF"


class TestBuildHistoryMultipleVisits:
    def setup_method(self) -> None:
        svc_a = _make_service(price="5000.00")
        svc_b = _make_service(service_id=_SERVICE_ID_B, price="2000.00")
        self.visit_recent = _make_visit(
            appointment_id=_APT_ID_1,
            date=_DATE_RECENT,
            services=(svc_a,),
            total_amount="5000.00",
        )
        self.visit_older = _make_visit(
            appointment_id=_APT_ID_2,
            date=_DATE_OLDER,
            services=(svc_b,),
            total_amount="2000.00",
        )
        # Caller passes visits ordered most-recent-first (as the SQL repository does)
        self.history = build_history((self.visit_recent, self.visit_older))

    def test_total_visits_is_two(self) -> None:
        assert self.history.total_visits == 2

    def test_total_amount_is_sum_of_all_visits(self) -> None:
        assert self.history.total_amount == decimal.Decimal("7000.00")

    def test_last_visit_at_is_most_recent(self) -> None:
        expected = datetime.datetime.combine(_DATE_RECENT, _TIME_09)
        assert self.history.last_visit_at == expected

    def test_visits_tuple_preserved_in_order(self) -> None:
        assert self.history.visits[0].appointment_id == _APT_ID_1
        assert self.history.visits[1].appointment_id == _APT_ID_2

    def test_total_amount_is_decimal_not_float(self) -> None:
        assert isinstance(self.history.total_amount, decimal.Decimal)
