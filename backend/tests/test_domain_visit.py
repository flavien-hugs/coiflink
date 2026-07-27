"""Tests unitaires — domaine « historique des visites » (US-4.2, #29) et
« prestations préférées » (US-4.3, #31).

Couvre `domain/visit.py` sans I/O ni base de données.

Cas traités :
- `visit_total` : tuple vide → `Decimal("0")`, un service, plusieurs services,
  valeurs décimales exactes (jamais de flottant) ;
- `build_history` : visites vides → résumé à défauts, une visite, plusieurs
  visites (somme + `last_visit_at` = première du tuple), devise conservée ;
- `HISTORY_STATUSES` : contient uniquement `COMPLETED` (séparé de `REVENUE_STATUSES`) ;
- `favourite_services` : agrégation, tri déterministe, montants Decimal, vide.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.visit import (
    HISTORY_STATUSES,
    CustomerServiceStats,
    CustomerVisit,
    ServiceFrequency,
    VisitHistory,
    VisitService,
    build_history,
    favourite_services,
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


# ---------------------------------------------------------------------------
# favourite_services (US-4.3, #31)
# ---------------------------------------------------------------------------

_SERVICE_ID_C = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
_SERVICE_ID_D = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
_APT_ID_3 = uuid.UUID("33333333-0000-0000-0000-000000000003")
_APT_ID_4 = uuid.UUID("44444444-0000-0000-0000-000000000004")


def _make_visit_with_services(
    appointment_id: uuid.UUID,
    services_data: list[tuple[uuid.UUID, str, str]],
) -> CustomerVisit:
    """Crée une visite COMPLETED avec les prestations (id, nom, prix)."""
    services = tuple(
        VisitService(
            service_id=sid,
            name=name,
            price_at_booking=decimal.Decimal(price),
        )
        for sid, name, price in services_data
    )
    return CustomerVisit(
        appointment_id=appointment_id,
        date=_DATE_RECENT,
        start_time=_TIME_09,
        end_time=_TIME_10,
        status=AppointmentStatus.COMPLETED.value,
        services=services,
        total_amount=sum((decimal.Decimal(p) for _, _, p in services_data), decimal.Decimal("0")),
    )


class TestFavouriteServicesEmpty:
    def test_empty_visits_returns_customer_service_stats(self) -> None:
        result = favourite_services(())
        assert isinstance(result, CustomerServiceStats)

    def test_empty_visits_services_tuple_is_empty(self) -> None:
        result = favourite_services(())
        assert result.services == ()

    def test_empty_visits_total_visits_is_zero(self) -> None:
        result = favourite_services(())
        assert result.total_visits == 0

    def test_empty_visits_total_services_is_zero(self) -> None:
        result = favourite_services(())
        assert result.total_services == 0

    def test_empty_visits_currency_is_xof(self) -> None:
        result = favourite_services(())
        assert result.currency == "XOF"

    def test_custom_currency_preserved(self) -> None:
        result = favourite_services((), currency="EUR")
        assert result.currency == "EUR"


class TestFavouriteServicesSingleVisit:
    def test_single_service_count_is_one(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((visit,))
        assert len(result.services) == 1
        assert result.services[0].count == 1

    def test_single_service_total_amount_correct(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((visit,))
        assert result.services[0].total_amount == decimal.Decimal("5000.00")

    def test_single_service_name_preserved(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((visit,))
        assert result.services[0].name == "Coupe homme"

    def test_single_service_id_preserved(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((visit,))
        assert result.services[0].service_id == _SERVICE_ID_A

    def test_total_visits_is_one(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((visit,))
        assert result.total_visits == 1

    def test_total_services_is_one(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((visit,))
        assert result.total_services == 1

    def test_two_different_services_in_one_visit(self) -> None:
        visit = _make_visit_with_services(
            _APT_ID_1,
            [(_SERVICE_ID_A, "Coupe homme", "5000.00"), (_SERVICE_ID_B, "Barbe", "2000.00")],
        )
        result = favourite_services((visit,))
        assert len(result.services) == 2
        assert result.total_services == 2

    def test_total_amount_is_decimal_type(self) -> None:
        visit = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe", "1234.56")])
        result = favourite_services((visit,))
        assert isinstance(result.services[0].total_amount, decimal.Decimal)


class TestFavouriteServicesAggregation:
    def test_same_service_in_two_visits_count_is_two(self) -> None:
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        result = favourite_services((v1, v2))
        assert len(result.services) == 1
        assert result.services[0].count == 2

    def test_same_service_total_amount_summed(self) -> None:
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe homme", "5000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe homme", "6000.00")])
        result = favourite_services((v1, v2))
        assert result.services[0].total_amount == decimal.Decimal("11000.00")

    def test_total_visits_counts_visits(self) -> None:
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        result = favourite_services((v1, v2))
        assert result.total_visits == 2

    def test_total_services_counts_occurrences(self) -> None:
        v1 = _make_visit_with_services(
            _APT_ID_1,
            [(_SERVICE_ID_A, "Coupe", "5000.00"), (_SERVICE_ID_B, "Barbe", "2000.00")],
        )
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        result = favourite_services((v1, v2))
        assert result.total_services == 3

    def test_aggregation_key_is_service_id_not_name(self) -> None:
        """Deux prestations avec le même nom mais des service_id distincts ne sont pas fusionnées."""
        v = _make_visit_with_services(
            _APT_ID_1,
            [(_SERVICE_ID_A, "Coupe", "5000.00"), (_SERVICE_ID_B, "Coupe", "5000.00")],
        )
        result = favourite_services((v,))
        assert len(result.services) == 2
        ids = {s.service_id for s in result.services}
        assert _SERVICE_ID_A in ids
        assert _SERVICE_ID_B in ids

    def test_decimal_precision_no_rounding(self) -> None:
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe", "1000.50")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe", "999.50")])
        result = favourite_services((v1, v2))
        assert result.services[0].total_amount == decimal.Decimal("2000.00")


class TestFavouriteServicesSorting:
    def test_sorted_by_count_descending(self) -> None:
        """Prestation la plus fréquente en premier."""
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        v3 = _make_visit_with_services(_APT_ID_3, [(_SERVICE_ID_B, "Barbe", "2000.00")])
        result = favourite_services((v1, v2, v3))
        assert result.services[0].service_id == _SERVICE_ID_A
        assert result.services[1].service_id == _SERVICE_ID_B

    def test_tiebreak_by_total_amount_descending(self) -> None:
        """Même count → prestation avec le plus grand total en premier."""
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe", "8000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_B, "Barbe", "2000.00")])
        result = favourite_services((v1, v2))
        assert result.services[0].service_id == _SERVICE_ID_A
        assert result.services[1].service_id == _SERVICE_ID_B

    def test_tiebreak_by_name_ascending_when_same_count_and_amount(self) -> None:
        """Même count et même total → ordre alphabétique du nom (croissant)."""
        v1 = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Zinc", "5000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_B, "Aile", "5000.00")])
        result = favourite_services((v1, v2))
        assert result.services[0].name == "Aile"
        assert result.services[1].name == "Zinc"

    def test_tiebreak_by_service_id_ascending_when_all_equal(self) -> None:
        """Count, total_amount et nom identiques → service_id (str) croissant."""
        sid_high = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
        sid_low = uuid.UUID("00000000-0000-0000-0000-000000000001")
        v1 = _make_visit_with_services(_APT_ID_1, [(sid_high, "Coupe", "5000.00")])
        v2 = _make_visit_with_services(_APT_ID_2, [(sid_low, "Coupe", "5000.00")])
        result = favourite_services((v1, v2))
        assert result.services[0].service_id == sid_low
        assert result.services[1].service_id == sid_high

    def test_sort_is_deterministic_with_three_services(self) -> None:
        """Ordre déterministe : fréquence décroissante, puis montant décroissant."""
        v1 = _make_visit_with_services(
            _APT_ID_1,
            [
                (_SERVICE_ID_A, "Coupe", "5000.00"),
                (_SERVICE_ID_B, "Barbe", "2000.00"),
                (_SERVICE_ID_C, "Soin", "1000.00"),
            ],
        )
        v2 = _make_visit_with_services(_APT_ID_2, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        v3 = _make_visit_with_services(_APT_ID_3, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        result = favourite_services((v1, v2, v3))
        # Coupe (count=3) > Barbe (count=1) > Soin (count=1, lower amount)
        assert result.services[0].service_id == _SERVICE_ID_A
        # Barbe has higher amount than Soin with same count
        assert result.services[1].service_id == _SERVICE_ID_B
        assert result.services[2].service_id == _SERVICE_ID_C

    def test_result_services_are_service_frequency_instances(self) -> None:
        v = _make_visit_with_services(_APT_ID_1, [(_SERVICE_ID_A, "Coupe", "5000.00")])
        result = favourite_services((v,))
        assert all(isinstance(s, ServiceFrequency) for s in result.services)
