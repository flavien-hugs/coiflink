"""Tests unitaires de `perf.config` — budgets §12.1, profils de charge/jeu de données (#52).

Module **pur** (stdlib uniquement) : aucun I/O, aucune charge, aucun besoin de
l'extra `perf`. Vérifie les invariants statiques et déterministes du harnais :
budgets §12.1, percentile de décision, profils de charge et de données, plage
de téléphones réservée (unicité, format), helpers purs.

Ces tests peuvent tourner dans le *test gate* ADW et la CI : rapides, déterministes,
aucun accès réseau ni base de données.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from perf import config

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _TESTS_DIR.parent


# ─── Budgets §12.1 ────────────────────────────────────────────────────────────


class TestBudgets:
    """Les quatre budgets §12.1 sont présents avec les bonnes valeurs."""

    def test_all_four_budget_group_constants_defined(self) -> None:
        assert config.BUDGET_SALON_SEARCH
        assert config.BUDGET_TICKET_CREATE
        assert config.BUDGET_DASHBOARD
        assert config.BUDGET_API_GENERAL

    def test_budgets_ms_covers_all_four_groups(self) -> None:
        expected = {
            config.BUDGET_SALON_SEARCH,
            config.BUDGET_TICKET_CREATE,
            config.BUDGET_DASHBOARD,
            config.BUDGET_API_GENERAL,
        }
        assert set(config.BUDGETS_MS.keys()) == expected

    def test_salon_search_budget_is_2000_ms(self) -> None:
        """PRD §12.1 : recherche salon < 2 s."""
        assert config.BUDGETS_MS[config.BUDGET_SALON_SEARCH] == 2000

    def test_ticket_create_budget_is_3000_ms(self) -> None:
        """PRD §12.1 : émission d'un ticket walk-in < 3 s."""
        assert config.BUDGETS_MS[config.BUDGET_TICKET_CREATE] == 3000

    def test_dashboard_budget_is_3000_ms(self) -> None:
        """PRD §12.1 : dashboard gérant (agrégat 5 lectures) < 3 s."""
        assert config.BUDGETS_MS[config.BUDGET_DASHBOARD] == 3000

    def test_api_general_budget_is_3000_ms(self) -> None:
        """PRD §12.1 : API générale (échantillon de lectures) < 3 s."""
        assert config.BUDGETS_MS[config.BUDGET_API_GENERAL] == 3000

    def test_budget_labels_covers_all_groups(self) -> None:
        assert set(config.BUDGET_LABELS.keys()) == set(config.BUDGETS_MS.keys())

    def test_budget_labels_are_non_empty_strings(self) -> None:
        for label in config.BUDGET_LABELS.values():
            assert isinstance(label, str) and label.strip()

    def test_budget_labels_contain_no_pii(self) -> None:
        """Les libellés sont des gabarits de route, jamais des données personnelles."""
        for label in config.BUDGET_LABELS.values():
            assert "@" not in label
            assert config.RESERVED_PHONE_PREFIX not in label
            assert "password" not in label.lower()

    def test_decision_percentile_is_95(self) -> None:
        assert config.DECISION_PERCENTILE == 95

    def test_surveillance_percentile_is_99(self) -> None:
        assert config.SURVEILLANCE_PERCENTILE == 99

    def test_alert_margin_strictly_between_0_and_1(self) -> None:
        """La marge d'alerte doit créer une bande WARN en-deçà du budget."""
        assert 0 < config.ALERT_MARGIN < 1


# ─── Seuil d'alerte ───────────────────────────────────────────────────────────


class TestAlertThreshold:
    def test_default_margin_applies_to_budget(self) -> None:
        expected = 2000 * config.ALERT_MARGIN
        assert config.alert_threshold_ms(2000) == pytest.approx(expected)

    def test_custom_margin_50_percent(self) -> None:
        assert config.alert_threshold_ms(3000, 0.5) == pytest.approx(1500.0)

    def test_margin_zero_gives_threshold_zero(self) -> None:
        assert config.alert_threshold_ms(3000, 0.0) == pytest.approx(0.0)

    def test_margin_one_gives_threshold_equal_to_budget(self) -> None:
        assert config.alert_threshold_ms(2000, 1.0) == pytest.approx(2000.0)

    def test_threshold_strictly_less_than_budget_with_default_margin(self) -> None:
        budget = 2000
        assert config.alert_threshold_ms(budget) < budget


# ─── LoadProfile ──────────────────────────────────────────────────────────────


class TestLoadProfile:
    def test_default_users(self) -> None:
        assert config.LoadProfile().users == 20

    def test_default_spawn_rate(self) -> None:
        assert config.LoadProfile().spawn_rate == pytest.approx(5.0)

    def test_default_warmup_s(self) -> None:
        assert config.LoadProfile().warmup_s == pytest.approx(10.0)

    def test_default_steady_state_s(self) -> None:
        assert config.LoadProfile().steady_state_s == pytest.approx(60.0)

    def test_total_duration_is_warmup_plus_steady(self) -> None:
        p = config.LoadProfile()
        assert p.total_duration_s == pytest.approx(p.warmup_s + p.steady_state_s)

    def test_custom_total_duration(self) -> None:
        p = config.LoadProfile(warmup_s=5.0, steady_state_s=30.0)
        assert p.total_duration_s == pytest.approx(35.0)

    def test_is_frozen(self) -> None:
        p = config.LoadProfile()
        with pytest.raises((AttributeError, TypeError)):
            p.users = 100  # type: ignore[misc]


class TestLoadProfileFromEnv:
    def test_empty_env_returns_defaults(self) -> None:
        assert config.load_profile_from_env({}) == config.LoadProfile()

    def test_override_users(self) -> None:
        p = config.load_profile_from_env({"PERF_USERS": "5"})
        assert p.users == 5

    def test_override_spawn_rate(self) -> None:
        p = config.load_profile_from_env({"PERF_SPAWN_RATE": "2.5"})
        assert p.spawn_rate == pytest.approx(2.5)

    def test_override_warmup(self) -> None:
        p = config.load_profile_from_env({"PERF_WARMUP_S": "20"})
        assert p.warmup_s == pytest.approx(20.0)

    def test_override_steady_state(self) -> None:
        p = config.load_profile_from_env({"PERF_STEADY_STATE_S": "120"})
        assert p.steady_state_s == pytest.approx(120.0)

    def test_malformed_users_falls_back_to_default(self) -> None:
        p = config.load_profile_from_env({"PERF_USERS": "not-a-number"})
        assert p.users == config.LoadProfile().users

    def test_empty_var_uses_default(self) -> None:
        p = config.load_profile_from_env({"PERF_USERS": "  "})
        assert p.users == config.LoadProfile().users

    def test_multiple_overrides_combined(self) -> None:
        p = config.load_profile_from_env({"PERF_USERS": "3", "PERF_STEADY_STATE_S": "10"})
        assert p.users == 3
        assert p.steady_state_s == pytest.approx(10.0)


# ─── DatasetProfile ───────────────────────────────────────────────────────────


class TestDatasetProfile:
    def test_default_salons(self) -> None:
        assert config.DatasetProfile().salons == 10

    def test_default_services_per_salon(self) -> None:
        assert config.DatasetProfile().services_per_salon == 6

    def test_default_hairdressers_per_salon(self) -> None:
        assert config.DatasetProfile().hairdressers_per_salon == 3

    def test_default_clients(self) -> None:
        assert config.DatasetProfile().clients == 100

    def test_default_completed_tickets(self) -> None:
        assert config.DatasetProfile().completed_tickets == 200

    def test_default_token_clients(self) -> None:
        d = config.DatasetProfile()
        assert d.token_clients > 0

    def test_is_frozen(self) -> None:
        d = config.DatasetProfile()
        with pytest.raises((AttributeError, TypeError)):
            d.salons = 99  # type: ignore[misc]


class TestDatasetProfileFromEnv:
    def test_empty_env_returns_defaults(self) -> None:
        assert config.dataset_profile_from_env({}) == config.DatasetProfile()

    def test_override_salons(self) -> None:
        d = config.dataset_profile_from_env({"PERF_SALONS": "5"})
        assert d.salons == 5

    def test_override_clients(self) -> None:
        d = config.dataset_profile_from_env({"PERF_CLIENTS": "50"})
        assert d.clients == 50

    def test_override_services_per_salon(self) -> None:
        d = config.dataset_profile_from_env({"PERF_SERVICES_PER_SALON": "3"})
        assert d.services_per_salon == 3

    def test_malformed_value_falls_back_to_default(self) -> None:
        d = config.dataset_profile_from_env({"PERF_SALONS": "xyz"})
        assert d.salons == config.DatasetProfile().salons


# ─── Plage de téléphones réservée ─────────────────────────────────────────────


class TestPhoneRange:
    """Unicité et format E.164 de la plage réservée au harnais de perf."""

    def test_reserved_prefix_starts_with_225(self) -> None:
        assert config.RESERVED_PHONE_PREFIX.startswith("+225")

    def test_local_phone_0_maps_to_reserved_prefix(self) -> None:
        local = config.local_phone(0)
        full_e164 = "+225" + local
        assert full_e164.startswith(config.RESERVED_PHONE_PREFIX)

    def test_local_phone_9999_maps_to_reserved_prefix(self) -> None:
        local = config.local_phone(9999)
        full_e164 = "+225" + local
        assert full_e164.startswith(config.RESERVED_PHONE_PREFIX)

    def test_local_phone_index_1_zero_pads_correctly(self) -> None:
        local = config.local_phone(1)
        assert local.endswith("0001")

    def test_local_phone_index_100(self) -> None:
        local = config.local_phone(100)
        assert local.endswith("0100")

    def test_local_phone_negative_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="plage réservée"):
            config.local_phone(-1)

    def test_local_phone_too_large_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="plage réservée"):
            config.local_phone(10000)

    def test_local_phone_boundary_9999_does_not_raise(self) -> None:
        config.local_phone(9999)  # pas d'exception attendue

    def test_local_phone_boundary_0_does_not_raise(self) -> None:
        config.local_phone(0)  # pas d'exception attendue

    def test_all_local_phones_have_same_length(self) -> None:
        lengths = {len(config.local_phone(i)) for i in (0, 1, 100, 999, 9999)}
        assert len(lengths) == 1, "Tous les numéros locaux doivent avoir la même longueur."

    def test_reserved_prefix_not_used_in_e2e_suites(self) -> None:
        """Le préfixe `+225059990` ne doit figurer dans aucune autre suite e2e."""
        conflicts = [
            p.name
            for p in _TESTS_DIR.glob("test_*_e2e.py")
            if config.RESERVED_PHONE_PREFIX in p.read_text()
        ]
        assert not conflicts, (
            f"Le préfixe {config.RESERVED_PHONE_PREFIX!r} est déjà utilisé dans "
            f"{conflicts!r} — collision de nettoyage FK possible en CI. Réserver "
            "une plage distincte pour le harnais de perf (#52)."
        )

    def test_reserved_prefix_not_used_in_integration_tests(self) -> None:
        conflicts = [
            p.name
            for p in _TESTS_DIR.glob("test_*_integration.py")
            if config.RESERVED_PHONE_PREFIX in p.read_text()
        ]
        assert not conflicts, (
            f"Le préfixe {config.RESERVED_PHONE_PREFIX!r} est déjà utilisé dans "
            f"{conflicts!r}."
        )


class TestSeedConstants:
    """Les constantes de seed (secret JWT de test, mot de passe) sont lisiblement synthétiques."""

    def test_default_test_jwt_secret_not_a_real_token(self) -> None:
        """Le secret JWT de test local ne ressemble pas à un vrai jeton de production."""
        suspicious = re.compile(
            r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|ey[A-Za-z0-9]{40,}"
        )
        assert not suspicious.search(config.DEFAULT_TEST_JWT_SECRET), (
            "DEFAULT_TEST_JWT_SECRET ressemble à un vrai secret de production — "
            "utiliser une chaîne clairement synthétique."
        )

    def test_default_test_jwt_secret_contains_synthetic_marker(self) -> None:
        lower = config.DEFAULT_TEST_JWT_SECRET.lower()
        assert any(kw in lower for kw in ("perf", "test", "local", "seed")), (
            "DEFAULT_TEST_JWT_SECRET doit contenir un marqueur lisible ('perf', 'test', "
            "'local', 'seed') pour indiquer qu'il n'est pas un secret de production."
        )

    def test_seed_password_contains_synthetic_marker(self) -> None:
        lower = config.SEED_PASSWORD.lower()
        assert any(kw in lower for kw in ("perf", "seed", "load", "test")), (
            "SEED_PASSWORD doit être lisiblement synthétique (contenir 'perf', 'seed', etc.)."
        )

    def test_jwt_secret_env_var_name_is_jwt_secret(self) -> None:
        assert config.JWT_SECRET_ENV == "JWT_SECRET"
