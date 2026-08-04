"""Tests unitaires — cas d'usage `ComputePlatformKpis` (US-6.6, #44).

Port remplacé par un fake : pas de base, pas de réseau.

Couvre :
- `execute` appelle `compute_snapshot` exactement une fois (lecture pure) ;
- bornes `month_from`/`month_to` dérivées de `month_bounds(reference_date)` ;
- bornes UTC `revenue_from_utc`/`revenue_to_utc` dérivées de `day_start_utc`/
  `day_end_utc` du 1er et du dernier jour du mois (Africa/Abidjan = UTC+0) ;
- bornes UTC timezone-aware ;
- des dates de référence dans des mois différents produisent des bornes différentes ;
- `PlatformKpiSnapshot` assemblé : compteurs, revenus, `reference_date`, bornes de
  période, devise XOF ;
- gestion correcte de février (28 jours) et d'une année bissextile (29 jours) ;
- plateforme vide : zéros légitimes retournés ;
- revenus négatifs préservés (corrections > paiements).
"""

from __future__ import annotations

import datetime
import decimal

from coiflink_api.application.platform_kpis import ComputePlatformKpis
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.platform_kpis import PlatformKpiCounts
from coiflink_api.domain.revenue import month_bounds
from coiflink_api.domain.time_window import day_end_utc, day_start_utc

# ---------------------------------------------------------------------------
# Fake PlatformKpiRepository
# ---------------------------------------------------------------------------


class FakePlatformKpiRepository:
    """Fake du port `PlatformKpiRepository` (US-6.6, #44) — aucun I/O.

    `counts` est le `PlatformKpiCounts` retourné par `compute_snapshot`.
    `calls` enregistre chaque appel avec ses arguments pour vérifier que le
    cas d'usage transmet correctement les bornes de période et bornes UTC.
    """

    def __init__(self, counts: PlatformKpiCounts | None = None) -> None:
        self._counts = counts or _make_zero_counts()
        self.calls: list[dict] = []

    def compute_snapshot(
        self,
        *,
        month_from: datetime.date,
        month_to: datetime.date,
        revenue_from_utc: datetime.datetime,
        revenue_to_utc: datetime.datetime,
    ) -> PlatformKpiCounts:
        self.calls.append(
            {
                "month_from": month_from,
                "month_to": month_to,
                "revenue_from_utc": revenue_from_utc,
                "revenue_to_utc": revenue_to_utc,
            }
        )
        return self._counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REF_DATE = datetime.date(2026, 8, 3)


def _make_zero_counts() -> PlatformKpiCounts:
    return PlatformKpiCounts(
        salons_total=0,
        salons_active=0,
        clients_total=0,
        appointments_total=0,
        appointments_this_month=0,
        revenue_total=decimal.Decimal("0.00"),
        revenue_this_month=decimal.Decimal("0.00"),
    )


def _make_counts(**kwargs) -> PlatformKpiCounts:
    defaults = dict(
        salons_total=5,
        salons_active=3,
        clients_total=100,
        appointments_total=300,
        appointments_this_month=25,
        revenue_total=decimal.Decimal("750000.00"),
        revenue_this_month=decimal.Decimal("62500.00"),
    )
    defaults.update(kwargs)
    return PlatformKpiCounts(**defaults)


# ---------------------------------------------------------------------------
# Transmission des bornes au port
# ---------------------------------------------------------------------------


class TestComputePlatformKpisArgForwarding:
    def test_compute_snapshot_called_once(self) -> None:
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        assert len(repo.calls) == 1

    def test_month_from_matches_month_bounds(self) -> None:
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        expected_from, _ = month_bounds(_REF_DATE)
        assert repo.calls[0]["month_from"] == expected_from

    def test_month_to_matches_month_bounds(self) -> None:
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        _, expected_to = month_bounds(_REF_DATE)
        assert repo.calls[0]["month_to"] == expected_to

    def test_revenue_from_utc_is_day_start_of_month_from(self) -> None:
        """Borne basse revenue = 00:00:00 UTC du 1er du mois (Africa/Abidjan = UTC+0)."""
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        month_from, _ = month_bounds(_REF_DATE)
        expected = day_start_utc(month_from)
        assert repo.calls[0]["revenue_from_utc"] == expected

    def test_revenue_to_utc_is_day_end_of_month_to(self) -> None:
        """Borne haute revenue = 23:59:59.999999 UTC du dernier jour du mois."""
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        _, month_to = month_bounds(_REF_DATE)
        expected = day_end_utc(month_to)
        assert repo.calls[0]["revenue_to_utc"] == expected

    def test_revenue_from_utc_is_timezone_aware(self) -> None:
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        assert repo.calls[0]["revenue_from_utc"].tzinfo is not None

    def test_revenue_to_utc_is_timezone_aware(self) -> None:
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        assert repo.calls[0]["revenue_to_utc"].tzinfo is not None

    def test_bornes_differ_across_months(self) -> None:
        """Des dates de référence dans des mois différents produisent des bornes différentes."""
        repo_jul = FakePlatformKpiRepository()
        repo_aug = FakePlatformKpiRepository()
        ComputePlatformKpis(repo_jul).execute(reference_date=datetime.date(2026, 7, 15))
        ComputePlatformKpis(repo_aug).execute(reference_date=datetime.date(2026, 8, 3))
        assert repo_jul.calls[0]["month_from"] != repo_aug.calls[0]["month_from"]
        assert repo_jul.calls[0]["month_to"] != repo_aug.calls[0]["month_to"]


# ---------------------------------------------------------------------------
# Assemblage du PlatformKpiSnapshot
# ---------------------------------------------------------------------------


class TestComputePlatformKpisSnapshot:
    def _execute(
        self,
        counts: PlatformKpiCounts | None = None,
        *,
        ref: datetime.date = _REF_DATE,
    ):
        repo = FakePlatformKpiRepository(counts=counts)
        return ComputePlatformKpis(repo).execute(reference_date=ref)

    def test_salons_total_propagated(self) -> None:
        snap = self._execute(_make_counts(salons_total=42))
        assert snap.salons_total == 42

    def test_salons_active_propagated(self) -> None:
        snap = self._execute(_make_counts(salons_active=18))
        assert snap.salons_active == 18

    def test_clients_total_propagated(self) -> None:
        snap = self._execute(_make_counts(clients_total=5421))
        assert snap.clients_total == 5421

    def test_appointments_total_propagated(self) -> None:
        snap = self._execute(_make_counts(appointments_total=18342))
        assert snap.appointments_total == 18342

    def test_appointments_this_month_propagated(self) -> None:
        snap = self._execute(_make_counts(appointments_this_month=1204))
        assert snap.appointments_this_month == 1204

    def test_revenue_total_propagated(self) -> None:
        snap = self._execute(_make_counts(revenue_total=decimal.Decimal("12500000.00")))
        assert snap.revenue_total == decimal.Decimal("12500000.00")

    def test_revenue_this_month_propagated(self) -> None:
        snap = self._execute(_make_counts(revenue_this_month=decimal.Decimal("980000.00")))
        assert snap.revenue_this_month == decimal.Decimal("980000.00")

    def test_reference_date_stored(self) -> None:
        snap = self._execute(ref=_REF_DATE)
        assert snap.reference_date == _REF_DATE

    def test_month_from_is_first_of_month(self) -> None:
        snap = self._execute(ref=datetime.date(2026, 8, 15))
        assert snap.month_from == datetime.date(2026, 8, 1)

    def test_month_to_is_last_day_of_month(self) -> None:
        snap = self._execute(ref=datetime.date(2026, 8, 15))
        assert snap.month_to == datetime.date(2026, 8, 31)

    def test_month_to_handles_thirty_day_month(self) -> None:
        """Juin = 30 jours."""
        snap = self._execute(ref=datetime.date(2026, 6, 10))
        assert snap.month_to == datetime.date(2026, 6, 30)

    def test_month_to_handles_february_non_leap(self) -> None:
        """2026 n'est pas une année bissextile : février = 28 jours."""
        snap = self._execute(ref=datetime.date(2026, 2, 10))
        assert snap.month_to == datetime.date(2026, 2, 28)

    def test_month_to_handles_february_leap_year(self) -> None:
        """2024 est une année bissextile : février = 29 jours."""
        snap = self._execute(ref=datetime.date(2024, 2, 10))
        assert snap.month_to == datetime.date(2024, 2, 29)

    def test_currency_is_xof(self) -> None:
        snap = self._execute()
        assert snap.currency == DEFAULT_CURRENCY
        assert snap.currency == "XOF"

    def test_revenue_negative_preserved(self) -> None:
        """Revenu négatif (corrections > paiements) doit être préservé dans le snapshot."""
        snap = self._execute(_make_counts(revenue_total=decimal.Decimal("-500.00")))
        assert snap.revenue_total == decimal.Decimal("-500.00")

    def test_empty_platform_all_zeros(self) -> None:
        """Plateforme vide : compteurs et revenus à zéro — état initial légitime."""
        snap = self._execute(_make_zero_counts())
        assert snap.salons_total == 0
        assert snap.appointments_total == 0
        assert snap.revenue_total == decimal.Decimal("0.00")
        assert snap.revenue_this_month == decimal.Decimal("0.00")

    def test_reference_date_first_of_month(self) -> None:
        """Une date de référence au 1er du mois : month_from == reference_date."""
        snap = self._execute(ref=datetime.date(2026, 8, 1))
        assert snap.month_from == datetime.date(2026, 8, 1)
        assert snap.reference_date == datetime.date(2026, 8, 1)

    def test_reference_date_last_of_month(self) -> None:
        """Une date de référence au dernier jour du mois : month_to == reference_date."""
        snap = self._execute(ref=datetime.date(2026, 8, 31))
        assert snap.month_to == datetime.date(2026, 8, 31)
        assert snap.reference_date == datetime.date(2026, 8, 31)


# ---------------------------------------------------------------------------
# Lecture pure — aucune écriture
# ---------------------------------------------------------------------------


class TestComputePlatformKpisPurity:
    def test_calls_compute_snapshot_exactly_once(self) -> None:
        repo = FakePlatformKpiRepository()
        ComputePlatformKpis(repo).execute(reference_date=_REF_DATE)
        assert len(repo.calls) == 1

    def test_second_execute_makes_second_call(self) -> None:
        """Deux appels successifs font deux appels au port (pas de cache)."""
        repo = FakePlatformKpiRepository()
        use_case = ComputePlatformKpis(repo)
        use_case.execute(reference_date=_REF_DATE)
        use_case.execute(reference_date=_REF_DATE)
        assert len(repo.calls) == 2
