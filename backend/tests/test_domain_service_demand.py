"""Tests unitaires — domaine `service_demand.py` (US-6.3, #41).

Couvre la fonction pure `rank_service_demand`, les objets-valeur `ServiceDemand` et
`ServiceDemandRanking`. Aucun I/O — domaine pur.

Couvre :
- `ServiceDemand` : frozen (immuable), champs (`service_id`, `name`, `volume`,
  `revenue`), pas de PII (`client_id`, `appointment_id`) ;
- `ServiceDemandRanking` : frozen, valeurs par défaut (tuples vides, dates `None`,
  devise `XOF`) ;
- `rank_service_demand` :
  - entrée vide → deux classements vides ;
  - un seul item → présent dans les deux classements ;
  - `by_volume` : tri `-volume`, puis `-revenue`, puis `name` croissant, puis
    `str(service_id)` croissant ;
  - `by_revenue` : tri `-revenue`, puis `-volume`, puis `name` croissant, puis
    `str(service_id)` croissant ;
  - égalité de volume → départage par revenu (décroissant) ;
  - égalité de revenu → départage par volume (décroissant) ;
  - égalité volume + revenu → départage par `name` puis `service_id` ;
  - deux prestations avec le même libellé mais des `service_id` distincts → séparées ;
  - `Decimal` conservé (aucun arrondi, jamais de flottant) ;
  - `date_from`, `date_to`, `currency` transmis au `ServiceDemandRanking` ;
  - `by_volume` et `by_revenue` contiennent exactement les mêmes entrées.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.service_demand import (
    ServiceDemand,
    ServiceDemandRanking,
    rank_service_demand,
)

# ---------------------------------------------------------------------------
# Helpers & constantes de test
# ---------------------------------------------------------------------------

_SID_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SID_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_SID_C = uuid.UUID("cccccccc-0000-0000-0000-000000000003")


def _demand(
    service_id: uuid.UUID | None = None,
    name: str = "Prestation",
    volume: int = 1,
    revenue: str = "1000.00",
) -> ServiceDemand:
    return ServiceDemand(
        service_id=service_id or uuid.uuid4(),
        name=name,
        volume=volume,
        revenue=decimal.Decimal(revenue),
    )


# ---------------------------------------------------------------------------
# ServiceDemand — objet-valeur
# ---------------------------------------------------------------------------


class TestServiceDemand:
    def test_fields_accessible(self) -> None:
        d = _demand(service_id=_SID_A, name="Coupe", volume=5, revenue="5000.00")
        assert d.service_id == _SID_A
        assert d.name == "Coupe"
        assert d.volume == 5
        assert d.revenue == decimal.Decimal("5000.00")

    def test_frozen_cannot_mutate(self) -> None:
        d = _demand()
        with pytest.raises((AttributeError, TypeError)):
            d.volume = 99  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        sid = uuid.uuid4()
        a = _demand(service_id=sid, name="X", volume=3, revenue="100.00")
        b = _demand(service_id=sid, name="X", volume=3, revenue="100.00")
        assert a == b

    def test_revenue_is_decimal(self) -> None:
        d = _demand(revenue="12345.67")
        assert isinstance(d.revenue, decimal.Decimal)

    def test_no_client_id_field(self) -> None:
        assert not hasattr(_demand(), "client_id"), "client_id est une PII interdite (§11.3)"

    def test_no_appointment_id_field(self) -> None:
        assert not hasattr(_demand(), "appointment_id"), "appointment_id est une PII interdite (§11.3)"

    def test_has_four_expected_fields(self) -> None:
        d = _demand()
        for field in ("service_id", "name", "volume", "revenue"):
            assert hasattr(d, field), f"champ manquant : {field}"


# ---------------------------------------------------------------------------
# ServiceDemandRanking — objet-valeur
# ---------------------------------------------------------------------------


class TestServiceDemandRanking:
    def test_default_by_volume_is_empty_tuple(self) -> None:
        assert ServiceDemandRanking().by_volume == ()

    def test_default_by_revenue_is_empty_tuple(self) -> None:
        assert ServiceDemandRanking().by_revenue == ()

    def test_default_date_from_is_none(self) -> None:
        assert ServiceDemandRanking().date_from is None

    def test_default_date_to_is_none(self) -> None:
        assert ServiceDemandRanking().date_to is None

    def test_default_currency_is_xof(self) -> None:
        r = ServiceDemandRanking()
        assert r.currency == DEFAULT_CURRENCY
        assert r.currency == "XOF"

    def test_frozen_cannot_mutate(self) -> None:
        r = ServiceDemandRanking()
        with pytest.raises((AttributeError, TypeError)):
            r.by_volume = ()  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert ServiceDemandRanking() == ServiceDemandRanking()

    def test_no_client_id_field(self) -> None:
        assert not hasattr(ServiceDemandRanking(), "client_id"), "PII interdite (§11.3)"

    def test_no_appointment_id_field(self) -> None:
        assert not hasattr(ServiceDemandRanking(), "appointment_id"), "PII interdite (§11.3)"


# ---------------------------------------------------------------------------
# rank_service_demand — entrée vide
# ---------------------------------------------------------------------------


class TestRankServiceDemandEmpty:
    def test_empty_input_returns_ranking(self) -> None:
        assert isinstance(rank_service_demand(()), ServiceDemandRanking)

    def test_empty_input_by_volume_is_empty(self) -> None:
        assert rank_service_demand(()).by_volume == ()

    def test_empty_input_by_revenue_is_empty(self) -> None:
        assert rank_service_demand(()).by_revenue == ()

    def test_empty_default_currency_is_xof(self) -> None:
        assert rank_service_demand(()).currency == DEFAULT_CURRENCY


# ---------------------------------------------------------------------------
# rank_service_demand — un seul item
# ---------------------------------------------------------------------------


class TestRankServiceDemandSingleItem:
    def test_single_item_in_by_volume(self) -> None:
        d = _demand(service_id=_SID_A)
        r = rank_service_demand((d,))
        assert len(r.by_volume) == 1
        assert r.by_volume[0] == d

    def test_single_item_in_by_revenue(self) -> None:
        d = _demand(service_id=_SID_A)
        r = rank_service_demand((d,))
        assert len(r.by_revenue) == 1
        assert r.by_revenue[0] == d


# ---------------------------------------------------------------------------
# rank_service_demand — tri by_volume
# ---------------------------------------------------------------------------


class TestRankByVolume:
    def test_higher_volume_first(self) -> None:
        """Le plus grand volume est classé en première position."""
        low = _demand(service_id=_SID_B, volume=5, revenue="5000.00")
        high = _demand(service_id=_SID_A, volume=42, revenue="1000.00")
        r = rank_service_demand((low, high))
        assert r.by_volume[0] == high
        assert r.by_volume[1] == low

    def test_volume_tie_broken_by_revenue_desc(self) -> None:
        """À volume égal, le revenu plus élevé passe devant."""
        lower_rev = _demand(service_id=_SID_B, name="B", volume=10, revenue="1000.00")
        higher_rev = _demand(service_id=_SID_A, name="A", volume=10, revenue="5000.00")
        r = rank_service_demand((lower_rev, higher_rev))
        assert r.by_volume[0] == higher_rev

    def test_volume_revenue_tie_broken_by_name_asc(self) -> None:
        """À volume+revenu égaux, le nom alphabétiquement inférieur passe devant."""
        z = _demand(service_id=_SID_B, name="Zeste", volume=10, revenue="1000.00")
        a = _demand(service_id=_SID_A, name="Abricot", volume=10, revenue="1000.00")
        r = rank_service_demand((z, a))
        assert r.by_volume[0] == a

    def test_volume_revenue_name_tie_broken_by_service_id(self) -> None:
        """À v+r+nom égaux, l'ordre lexicographique de str(service_id) est le dernier départage."""
        # _SID_A < _SID_B (comparaison de chaîne UUID)
        b = ServiceDemand(service_id=_SID_B, name="Même", volume=10, revenue=decimal.Decimal("1000.00"))
        a = ServiceDemand(service_id=_SID_A, name="Même", volume=10, revenue=decimal.Decimal("1000.00"))
        r = rank_service_demand((b, a))
        assert r.by_volume[0] == a

    def test_three_items_ordered_by_volume_desc(self) -> None:
        items = (
            _demand(service_id=_SID_C, volume=5),
            _demand(service_id=_SID_A, volume=42),
            _demand(service_id=_SID_B, volume=20),
        )
        r = rank_service_demand(items)
        volumes = [d.volume for d in r.by_volume]
        assert volumes == sorted(volumes, reverse=True)


# ---------------------------------------------------------------------------
# rank_service_demand — tri by_revenue
# ---------------------------------------------------------------------------


class TestRankByRevenue:
    def test_higher_revenue_first(self) -> None:
        """Le revenu le plus élevé est classé en première position."""
        low = _demand(service_id=_SID_B, volume=100, revenue="1000.00")
        high = _demand(service_id=_SID_A, volume=1, revenue="200000.00")
        r = rank_service_demand((low, high))
        assert r.by_revenue[0] == high

    def test_revenue_tie_broken_by_volume_desc(self) -> None:
        """À revenu égal, le volume plus élevé passe devant."""
        lower_vol = _demand(service_id=_SID_B, name="B", volume=5, revenue="10000.00")
        higher_vol = _demand(service_id=_SID_A, name="A", volume=50, revenue="10000.00")
        r = rank_service_demand((lower_vol, higher_vol))
        assert r.by_revenue[0] == higher_vol

    def test_revenue_volume_tie_broken_by_name_asc(self) -> None:
        z = _demand(service_id=_SID_B, name="Zeste", volume=10, revenue="5000.00")
        a = _demand(service_id=_SID_A, name="Abricot", volume=10, revenue="5000.00")
        r = rank_service_demand((z, a))
        assert r.by_revenue[0] == a

    def test_revenue_volume_name_tie_broken_by_service_id(self) -> None:
        b = ServiceDemand(service_id=_SID_B, name="Même", volume=10, revenue=decimal.Decimal("5000.00"))
        a = ServiceDemand(service_id=_SID_A, name="Même", volume=10, revenue=decimal.Decimal("5000.00"))
        r = rank_service_demand((b, a))
        assert r.by_revenue[0] == a

    def test_three_items_ordered_by_revenue_desc(self) -> None:
        items = (
            _demand(service_id=_SID_C, revenue="5000.00"),
            _demand(service_id=_SID_A, revenue="200000.00"),
            _demand(service_id=_SID_B, revenue="60000.00"),
        )
        r = rank_service_demand(items)
        revenues = [d.revenue for d in r.by_revenue]
        assert revenues == sorted(revenues, reverse=True)


# ---------------------------------------------------------------------------
# rank_service_demand — même libellé, service_id distincts → non fusionnés
# ---------------------------------------------------------------------------


class TestRankSharedName:
    def test_same_name_different_id_not_merged(self) -> None:
        """Deux prestations avec le même libellé mais des service_id distincts ne sont pas fusionnées."""
        a = _demand(service_id=_SID_A, name="Coupe", volume=10)
        b = _demand(service_id=_SID_B, name="Coupe", volume=20)
        r = rank_service_demand((a, b))
        assert len(r.by_volume) == 2
        ids = {d.service_id for d in r.by_volume}
        assert _SID_A in ids and _SID_B in ids


# ---------------------------------------------------------------------------
# rank_service_demand — Decimal conservé, jamais de flottant
# ---------------------------------------------------------------------------


class TestRankDecimal:
    def test_decimal_preserved_in_by_volume(self) -> None:
        rev = decimal.Decimal("12345.67")
        d = ServiceDemand(service_id=_SID_A, name="X", volume=1, revenue=rev)
        r = rank_service_demand((d,))
        assert r.by_volume[0].revenue == rev
        assert isinstance(r.by_volume[0].revenue, decimal.Decimal)

    def test_decimal_preserved_in_by_revenue(self) -> None:
        rev = decimal.Decimal("99999.99")
        d = ServiceDemand(service_id=_SID_A, name="X", volume=1, revenue=rev)
        r = rank_service_demand((d,))
        assert r.by_revenue[0].revenue == rev
        assert isinstance(r.by_revenue[0].revenue, decimal.Decimal)

    def test_no_float_conversion(self) -> None:
        """Le tri ne convertit pas les Decimal en flottant."""
        rev = decimal.Decimal("210000.00")
        d = ServiceDemand(service_id=_SID_A, name="X", volume=42, revenue=rev)
        r = rank_service_demand((d,))
        assert type(r.by_volume[0].revenue) is decimal.Decimal


# ---------------------------------------------------------------------------
# rank_service_demand — passthrough date_from / date_to / currency
# ---------------------------------------------------------------------------


class TestRankPassthrough:
    def test_date_from_echoed(self) -> None:
        df = datetime.date(2026, 1, 1)
        assert rank_service_demand((), date_from=df).date_from == df

    def test_date_to_echoed(self) -> None:
        dt = datetime.date(2026, 12, 31)
        assert rank_service_demand((), date_to=dt).date_to == dt

    def test_custom_currency_echoed(self) -> None:
        assert rank_service_demand((), currency="EUR").currency == "EUR"

    def test_default_currency_is_xof(self) -> None:
        assert rank_service_demand(()).currency == DEFAULT_CURRENCY

    def test_none_dates_by_default(self) -> None:
        r = rank_service_demand(())
        assert r.date_from is None
        assert r.date_to is None


# ---------------------------------------------------------------------------
# rank_service_demand — by_volume et by_revenue contiennent les mêmes entrées
# ---------------------------------------------------------------------------


class TestRankSameSets:
    def test_same_count_in_both_classements(self) -> None:
        items = (
            _demand(service_id=_SID_A, volume=10, revenue="5000.00"),
            _demand(service_id=_SID_B, volume=5, revenue="20000.00"),
            _demand(service_id=_SID_C, volume=20, revenue="1000.00"),
        )
        r = rank_service_demand(items)
        assert len(r.by_volume) == len(r.by_revenue) == 3

    def test_same_service_ids_in_both_classements(self) -> None:
        items = (
            _demand(service_id=_SID_A, volume=10, revenue="5000.00"),
            _demand(service_id=_SID_B, volume=5, revenue="20000.00"),
        )
        r = rank_service_demand(items)
        assert {d.service_id for d in r.by_volume} == {d.service_id for d in r.by_revenue}

    def test_different_order_between_classements(self) -> None:
        """Un classement par volume et un par revenu peuvent avoir des ordres distincts."""
        # A : plus de volume ; B : plus de revenu
        a = _demand(service_id=_SID_A, name="A", volume=100, revenue="1000.00")
        b = _demand(service_id=_SID_B, name="B", volume=1, revenue="200000.00")
        r = rank_service_demand((a, b))
        assert r.by_volume[0] == a
        assert r.by_revenue[0] == b
