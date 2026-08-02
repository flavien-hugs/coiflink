"""Tests unitaires — cas d'usage `SummarizeServiceDemand` (US-6.3, #41).

Port remplacé par un fake : aucun I/O, aucune base.

Couvre :
- `execute` appelle `demand_by_service` avec `REVENUE_STATUSES` (jamais soumis par
  l'appelant) ;
- les bornes `date_from`/`date_to` (None ou fournies) sont transmises telles quelles
  au port ;
- le `salon_id` est transmis au port ;
- le `ServiceDemandRanking` assemblé contient les deux classements issus du domaine ;
- cas « aucune ligne » → classements vides (état normal, ≠ erreur) ;
- devise `XOF` par défaut ;
- lecture pure : les méthodes de mutation lèvent `NotImplementedError`.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.service_demand import SummarizeServiceDemand
from coiflink_api.domain.appointment import REVENUE_STATUSES
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.service_demand import ServiceDemand

# ---------------------------------------------------------------------------
# Fake AppointmentRepository (lecture seule)
# ---------------------------------------------------------------------------


class FakeServiceDemandAppointmentRepository:
    """Fake du port `AppointmentRepository` pour `SummarizeServiceDemand` (#41).

    `results` est le tuple de `ServiceDemand` retourné par `demand_by_service`.
    `demand_by_service_calls` enregistre chaque appel pour vérification.
    Les méthodes de mutation lèvent `NotImplementedError` pour rendre toute
    écriture accidentelle visible immédiatement (lecture pure, §11.4).
    """

    def __init__(self, results: tuple[ServiceDemand, ...] = ()) -> None:
        self._results = results
        self.demand_by_service_calls: list[dict] = []

    def demand_by_service(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from=None, date_to=None
    ) -> tuple[ServiceDemand, ...]:
        self.demand_by_service_calls.append(
            {
                "salon_id": salon_id,
                "statuses": statuses,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return self._results

    def create(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError("SummarizeServiceDemand ne doit pas écrire")

    def count_by_status_for_day(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def booked_slots(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_owned(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def update(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def cancel(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_in_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def set_status(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def assign_hairdresser(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_client(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_hairdresser(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_DATE_FROM = datetime.date(2026, 8, 1)
_DATE_TO = datetime.date(2026, 8, 31)

_DEMAND_A = ServiceDemand(
    service_id=uuid.UUID("aaaaaaaa-1111-0000-0000-000000000001"),
    name="Coupe homme",
    volume=42,
    revenue=decimal.Decimal("210000.00"),
)
_DEMAND_B = ServiceDemand(
    service_id=uuid.UUID("bbbbbbbb-2222-0000-0000-000000000002"),
    name="Barbe",
    volume=30,
    revenue=decimal.Decimal("60000.00"),
)


# ---------------------------------------------------------------------------
# Arguments transmis au port
# ---------------------------------------------------------------------------


class TestSummarizeServiceDemandPortArgs:
    def test_demand_by_service_called_once(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert len(repo.demand_by_service_calls) == 1

    def test_salon_id_forwarded(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert repo.demand_by_service_calls[0]["salon_id"] == _SALON_ID

    def test_revenue_statuses_imposed(self) -> None:
        """Seul REVENUE_STATUSES (COMPLETED) est imposé — jamais soumis par l'appelant."""
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert repo.demand_by_service_calls[0]["statuses"] == REVENUE_STATUSES

    def test_date_from_forwarded(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID, date_from=_DATE_FROM)
        assert repo.demand_by_service_calls[0]["date_from"] == _DATE_FROM

    def test_date_to_forwarded(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID, date_to=_DATE_TO)
        assert repo.demand_by_service_calls[0]["date_to"] == _DATE_TO

    def test_date_from_none_by_default(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert repo.demand_by_service_calls[0]["date_from"] is None

    def test_date_to_none_by_default(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert repo.demand_by_service_calls[0]["date_to"] is None

    def test_both_date_bounds_forwarded(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO)
        call = repo.demand_by_service_calls[0]
        assert call["date_from"] == _DATE_FROM
        assert call["date_to"] == _DATE_TO

    def test_no_write_triggered(self) -> None:
        """Lecture pure : aucune méthode d'écriture ne doit être appelée."""
        repo = FakeServiceDemandAppointmentRepository()
        SummarizeServiceDemand(repo).execute(_SALON_ID)


# ---------------------------------------------------------------------------
# Assemblage du ServiceDemandRanking
# ---------------------------------------------------------------------------


class TestSummarizeServiceDemandAssembly:
    def test_ranking_has_by_volume(self) -> None:
        repo = FakeServiceDemandAppointmentRepository(results=(_DEMAND_A, _DEMAND_B))
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert hasattr(ranking, "by_volume")

    def test_ranking_has_by_revenue(self) -> None:
        repo = FakeServiceDemandAppointmentRepository(results=(_DEMAND_A, _DEMAND_B))
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert hasattr(ranking, "by_revenue")

    def test_ranking_currency_is_xof(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert ranking.currency == DEFAULT_CURRENCY

    def test_ranking_date_from_echoed(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID, date_from=_DATE_FROM)
        assert ranking.date_from == _DATE_FROM

    def test_ranking_date_to_echoed(self) -> None:
        repo = FakeServiceDemandAppointmentRepository()
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID, date_to=_DATE_TO)
        assert ranking.date_to == _DATE_TO

    def test_by_volume_sorted_by_volume_desc(self) -> None:
        """Le classement by_volume est trié par volume décroissant. A=42 > B=30 → A en tête."""
        repo = FakeServiceDemandAppointmentRepository(results=(_DEMAND_B, _DEMAND_A))
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert ranking.by_volume[0] == _DEMAND_A

    def test_by_revenue_sorted_by_revenue_desc(self) -> None:
        """Le classement by_revenue est trié par revenu décroissant. A=210000 > B=60000 → A en tête."""
        repo = FakeServiceDemandAppointmentRepository(results=(_DEMAND_B, _DEMAND_A))
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert ranking.by_revenue[0] == _DEMAND_A


# ---------------------------------------------------------------------------
# Cas « aucune ligne »
# ---------------------------------------------------------------------------


class TestSummarizeServiceDemandEmpty:
    def test_empty_results_by_volume_empty(self) -> None:
        repo = FakeServiceDemandAppointmentRepository(results=())
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert ranking.by_volume == ()

    def test_empty_results_by_revenue_empty(self) -> None:
        repo = FakeServiceDemandAppointmentRepository(results=())
        ranking = SummarizeServiceDemand(repo).execute(_SALON_ID)
        assert ranking.by_revenue == ()

    def test_empty_not_an_error(self) -> None:
        """Un salon sans RDV réalisé retourne un classement vide, pas une erreur."""
        repo = FakeServiceDemandAppointmentRepository(results=())
        SummarizeServiceDemand(repo).execute(_SALON_ID)
