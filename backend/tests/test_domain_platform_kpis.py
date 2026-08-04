"""Tests unitaires — domaine `platform_kpis.py` (US-6.6, #44).

Couvre :
- `PlatformKpiCounts` : immutabilité (frozen), types des champs, champs attendus ;
- `PlatformKpiSnapshot` : immutabilité, devise par défaut XOF, égalité par valeur,
  bornes de période, plateforme vide (zéros légitimes) ;
- **non-PII (§11.3)** : aucun champ identifiant une entité (`salon_id`, `client_id`,
  `owner_id`, `reference`, `recorded_by`) dans les deux VO ;
- **absence de `subscriptions`** : aucun modèle d'abonnement n'existe (ADR-0032) ;
- revenus négatifs acceptés (`revenue_total`/`revenue_this_month` peuvent être < 0).

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import datetime
import decimal

import pytest

from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.platform_kpis import PlatformKpiCounts, PlatformKpiSnapshot

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_REF_DATE = datetime.date(2026, 8, 3)
_MONTH_FROM = datetime.date(2026, 8, 1)
_MONTH_TO = datetime.date(2026, 8, 31)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_counts(**kwargs) -> PlatformKpiCounts:
    defaults = dict(
        salons_total=10,
        salons_active=7,
        clients_total=200,
        appointments_total=500,
        appointments_this_month=42,
        revenue_total=decimal.Decimal("1500000.00"),
        revenue_this_month=decimal.Decimal("125000.00"),
    )
    defaults.update(kwargs)
    return PlatformKpiCounts(**defaults)


def _make_snapshot(**kwargs) -> PlatformKpiSnapshot:
    defaults = dict(
        salons_total=10,
        salons_active=7,
        clients_total=200,
        appointments_total=500,
        appointments_this_month=42,
        revenue_total=decimal.Decimal("1500000.00"),
        revenue_this_month=decimal.Decimal("125000.00"),
        reference_date=_REF_DATE,
        month_from=_MONTH_FROM,
        month_to=_MONTH_TO,
    )
    defaults.update(kwargs)
    return PlatformKpiSnapshot(**defaults)


# ---------------------------------------------------------------------------
# PlatformKpiCounts — valeur interne de transport
# ---------------------------------------------------------------------------


class TestPlatformKpiCounts:
    def test_frozen_cannot_mutate_salons_total(self) -> None:
        c = _make_counts()
        with pytest.raises((AttributeError, TypeError)):
            c.salons_total = 99  # type: ignore[misc]

    def test_frozen_cannot_mutate_revenue_total(self) -> None:
        c = _make_counts()
        with pytest.raises((AttributeError, TypeError)):
            c.revenue_total = decimal.Decimal("0.00")  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        c1 = _make_counts()
        c2 = _make_counts()
        assert c1 == c2

    def test_different_values_not_equal(self) -> None:
        c1 = _make_counts(salons_total=1)
        c2 = _make_counts(salons_total=2)
        assert c1 != c2

    def test_revenue_total_is_decimal(self) -> None:
        c = _make_counts(revenue_total=decimal.Decimal("99999.99"))
        assert isinstance(c.revenue_total, decimal.Decimal)

    def test_revenue_this_month_is_decimal(self) -> None:
        c = _make_counts(revenue_this_month=decimal.Decimal("999.99"))
        assert isinstance(c.revenue_this_month, decimal.Decimal)

    def test_revenue_total_can_be_negative(self) -> None:
        """Un montant net peut être négatif (corrections dépassant les paiements, #34)."""
        c = _make_counts(revenue_total=decimal.Decimal("-500.00"))
        assert c.revenue_total == decimal.Decimal("-500.00")

    def test_revenue_this_month_can_be_negative(self) -> None:
        c = _make_counts(revenue_this_month=decimal.Decimal("-100.00"))
        assert c.revenue_this_month == decimal.Decimal("-100.00")

    def test_revenue_this_month_can_be_zero(self) -> None:
        c = _make_counts(revenue_this_month=decimal.Decimal("0.00"))
        assert c.revenue_this_month == decimal.Decimal("0.00")

    def test_all_zero_counts_accepted(self) -> None:
        """Plateforme vide : tous les scalaires à zéro sont valides (état initial)."""
        c = _make_counts(
            salons_total=0,
            salons_active=0,
            clients_total=0,
            appointments_total=0,
            appointments_this_month=0,
            revenue_total=decimal.Decimal("0.00"),
            revenue_this_month=decimal.Decimal("0.00"),
        )
        assert c.salons_total == 0
        assert c.revenue_total == decimal.Decimal("0.00")

    def test_expected_fields_present(self) -> None:
        c = _make_counts()
        for field in (
            "salons_total",
            "salons_active",
            "clients_total",
            "appointments_total",
            "appointments_this_month",
            "revenue_total",
            "revenue_this_month",
        ):
            assert hasattr(c, field), f"Champ attendu absent : {field}"

    # ---- Non-PII (§11.3) — champs interdits absents du VO ----------------

    def test_no_salon_id_field(self) -> None:
        c = _make_counts()
        assert not hasattr(c, "salon_id"), "salon_id est une PII interdite (§11.3)"

    def test_no_client_id_field(self) -> None:
        c = _make_counts()
        assert not hasattr(c, "client_id"), "client_id est une PII interdite (§11.3)"

    def test_no_owner_id_field(self) -> None:
        c = _make_counts()
        assert not hasattr(c, "owner_id"), "owner_id est une PII interdite (§11.3)"

    def test_no_reference_field(self) -> None:
        c = _make_counts()
        assert not hasattr(c, "reference"), "reference est une PII interdite (§11.3)"

    def test_no_recorded_by_field(self) -> None:
        c = _make_counts()
        assert not hasattr(c, "recorded_by"), "recorded_by est une PII interdite (§11.3)"

    def test_no_subscriptions_field(self) -> None:
        """Aucun modèle d'abonnement n'existe — le champ subscriptions ne doit pas être émis (ADR-0032)."""
        c = _make_counts()
        assert not hasattr(c, "subscriptions")


# ---------------------------------------------------------------------------
# PlatformKpiSnapshot — objet de réponse public (instantané)
# ---------------------------------------------------------------------------


class TestPlatformKpiSnapshot:
    def test_default_currency_is_xof(self) -> None:
        s = _make_snapshot()
        assert s.currency == DEFAULT_CURRENCY

    def test_currency_is_xof_string(self) -> None:
        s = _make_snapshot()
        assert s.currency == "XOF"

    def test_explicit_currency_stored(self) -> None:
        s = _make_snapshot(currency="XOF")
        assert s.currency == "XOF"

    def test_frozen_cannot_mutate_salons_total(self) -> None:
        s = _make_snapshot()
        with pytest.raises((AttributeError, TypeError)):
            s.salons_total = 99  # type: ignore[misc]

    def test_frozen_cannot_mutate_revenue_total(self) -> None:
        s = _make_snapshot()
        with pytest.raises((AttributeError, TypeError)):
            s.revenue_total = decimal.Decimal("0.00")  # type: ignore[misc]

    def test_frozen_cannot_mutate_reference_date(self) -> None:
        s = _make_snapshot()
        with pytest.raises((AttributeError, TypeError)):
            s.reference_date = datetime.date(2025, 1, 1)  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        s1 = _make_snapshot()
        s2 = _make_snapshot()
        assert s1 == s2

    def test_different_values_not_equal(self) -> None:
        s1 = _make_snapshot(salons_total=1)
        s2 = _make_snapshot(salons_total=2)
        assert s1 != s2

    def test_reference_date_stored(self) -> None:
        s = _make_snapshot(reference_date=_REF_DATE)
        assert s.reference_date == _REF_DATE

    def test_month_from_stored(self) -> None:
        s = _make_snapshot(month_from=_MONTH_FROM)
        assert s.month_from == _MONTH_FROM

    def test_month_to_stored(self) -> None:
        s = _make_snapshot(month_to=_MONTH_TO)
        assert s.month_to == _MONTH_TO

    def test_revenue_total_is_decimal(self) -> None:
        s = _make_snapshot()
        assert isinstance(s.revenue_total, decimal.Decimal)

    def test_revenue_this_month_is_decimal(self) -> None:
        s = _make_snapshot()
        assert isinstance(s.revenue_this_month, decimal.Decimal)

    def test_revenue_total_can_be_negative(self) -> None:
        s = _make_snapshot(revenue_total=decimal.Decimal("-500.00"))
        assert s.revenue_total == decimal.Decimal("-500.00")

    def test_revenue_this_month_can_be_negative(self) -> None:
        s = _make_snapshot(revenue_this_month=decimal.Decimal("-100.00"))
        assert s.revenue_this_month == decimal.Decimal("-100.00")

    def test_zero_counts_empty_platform(self) -> None:
        """Plateforme vide : tous les compteurs à zéro et revenus à 0.00 sont légitimes."""
        s = _make_snapshot(
            salons_total=0,
            salons_active=0,
            clients_total=0,
            appointments_total=0,
            appointments_this_month=0,
            revenue_total=decimal.Decimal("0.00"),
            revenue_this_month=decimal.Decimal("0.00"),
        )
        assert s.salons_total == 0
        assert s.revenue_total == decimal.Decimal("0.00")

    def test_expected_fields_present(self) -> None:
        s = _make_snapshot()
        for field in (
            "salons_total",
            "salons_active",
            "clients_total",
            "appointments_total",
            "appointments_this_month",
            "revenue_total",
            "revenue_this_month",
            "reference_date",
            "month_from",
            "month_to",
            "currency",
        ):
            assert hasattr(s, field), f"Champ attendu absent : {field}"

    # ---- Non-PII (§11.3) — champs interdits absents du VO ----------------

    def test_no_salon_id_field(self) -> None:
        s = _make_snapshot()
        assert not hasattr(s, "salon_id"), "salon_id est une PII interdite (§11.3)"

    def test_no_client_id_field(self) -> None:
        s = _make_snapshot()
        assert not hasattr(s, "client_id"), "client_id est une PII interdite (§11.3)"

    def test_no_owner_id_field(self) -> None:
        s = _make_snapshot()
        assert not hasattr(s, "owner_id"), "owner_id est une PII interdite (§11.3)"

    def test_no_reference_field(self) -> None:
        s = _make_snapshot()
        assert not hasattr(s, "reference"), "reference est une PII interdite (§11.3)"

    def test_no_recorded_by_field(self) -> None:
        s = _make_snapshot()
        assert not hasattr(s, "recorded_by"), "recorded_by est une PII interdite (§11.3)"

    def test_no_subscriptions_field(self) -> None:
        """Aucun modèle d'abonnement n'existe — le champ subscriptions ne doit pas être émis (ADR-0032)."""
        s = _make_snapshot()
        assert not hasattr(s, "subscriptions")
