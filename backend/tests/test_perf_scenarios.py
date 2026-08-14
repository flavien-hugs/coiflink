"""Tests unitaires des scénarios de charge (`perf.scenarios`) — sans I/O ni charge (#52).

Ces tests exercent la logique de chaque scénario via un `MockTimedHttp` déterministe
et vérifient les invariants comportementaux **sans** exécuter la moindre charge ni
se connecter à un serveur :

- `SeedContext.is_ready()` — pré-condition des scénarios.
- `run_salon_search()` — route publique, variation de paramètres.
- `run_ticket_create()` — fiche walk-in (borne) → émission de ticket, jeton borne.
- `run_manager_dashboard()` — 4 lectures agrégées, jeton gérant, agrégat de latence.
- `run_api_general()` — lecture protégée, jeton requis.
- `weighted_groups()` — tous les groupes présents, poids relatifs cohérents.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import pytest

from perf import config
from perf.scenarios import (
    SCENARIO_WEIGHTS,
    SalonFixture,
    SeedContext,
    TimedResponse,
    run_api_general,
    run_manager_dashboard,
    run_salon_search,
    run_ticket_create,
    weighted_groups,
)


# ─── Mock de transport ────────────────────────────────────────────────────────


@dataclass
class _Call:
    """Enregistrement d'un appel au mock."""

    method: str
    label: str
    path: str
    params: dict | None = None
    json_body: dict | None = None
    token: str | None = None


class MockTimedHttp:
    """Transport de test : renvoie `status` / `elapsed_ms` / `body` identiques pour tous les appels."""

    def __init__(
        self,
        status: int = 200,
        elapsed_ms: float = 50.0,
        body: Any = None,
    ) -> None:
        self._status = status
        self._elapsed_ms = elapsed_ms
        self._body = body
        self.calls: list[_Call] = []

    def send(
        self,
        method: str,
        label: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        token: str | None = None,
    ) -> TimedResponse:
        self.calls.append(_Call(method, label, path, params, json, token))
        return TimedResponse(status=self._status, elapsed_ms=self._elapsed_ms, json=self._body)


# ─── Fixtures de contexte ─────────────────────────────────────────────────────


def _make_context(n_salons: int = 2, n_clients: int = 3) -> SeedContext:
    salons = [
        SalonFixture(
            salon_id=f"salon-{i}",
            manager_token=f"mgr-token-{i}",
            terminal_token=f"term-token-{i}",
            service_ids=[f"svc-{i}-1", f"svc-{i}-2"],
            hairdresser_ids=[f"hd-{i}-1"],
            name=f"Salon {i}",
            city="Abidjan",
            commune="Cocody",
        )
        for i in range(n_salons)
    ]
    return SeedContext(
        salons=salons,
        client_tokens=[f"cli-token-{j}" for j in range(n_clients)],
        search_terms=["coupe", "coloration"],
    )


# ─── SeedContext.is_ready() ───────────────────────────────────────────────────


class TestSeedContext:
    def test_is_ready_true_when_populated(self) -> None:
        assert _make_context().is_ready() is True

    def test_is_ready_false_when_no_salons(self) -> None:
        ctx = SeedContext(salons=[], client_tokens=["tok"])
        assert ctx.is_ready() is False

    def test_is_ready_false_when_no_client_tokens(self) -> None:
        ctx = SeedContext(
            salons=[SalonFixture("s", "t", "term", ["svc"], ["hd"], "Nom")],
            client_tokens=[],
        )
        assert ctx.is_ready() is False

    def test_is_ready_false_when_both_empty(self) -> None:
        assert SeedContext().is_ready() is False


# ─── Scénario 1 : Recherche salon ─────────────────────────────────────────────


class TestSalonSearch:
    def test_returns_salon_search_group(self) -> None:
        http = MockTimedHttp()
        sample = run_salon_search(http, _make_context(), random.Random(0))
        assert sample.group == config.BUDGET_SALON_SEARCH

    def test_uses_get_method(self) -> None:
        http = MockTimedHttp()
        run_salon_search(http, _make_context(), random.Random(0))
        assert all(c.method == "GET" for c in http.calls)

    def test_calls_catalog_salons_path(self) -> None:
        http = MockTimedHttp()
        run_salon_search(http, _make_context(), random.Random(0))
        assert any("/catalog/salons" in c.path for c in http.calls)

    def test_exactly_one_request_per_call(self) -> None:
        http = MockTimedHttp()
        run_salon_search(http, _make_context(), random.Random(0))
        assert len(http.calls) == 1

    def test_ok_when_200(self) -> None:
        http = MockTimedHttp(status=200)
        sample = run_salon_search(http, _make_context(), random.Random(0))
        assert sample.ok is True

    def test_not_ok_when_500(self) -> None:
        http = MockTimedHttp(status=500)
        sample = run_salon_search(http, _make_context(), random.Random(0))
        assert sample.ok is False

    def test_not_ok_when_401(self) -> None:
        http = MockTimedHttp(status=401)
        sample = run_salon_search(http, _make_context(), random.Random(0))
        assert sample.ok is False

    def test_elapsed_matches_transport_elapsed(self) -> None:
        http = MockTimedHttp(elapsed_ms=123.4)
        sample = run_salon_search(http, _make_context(), random.Random(0))
        assert sample.elapsed_ms == pytest.approx(123.4)

    def test_no_auth_token_on_public_route(self) -> None:
        """La route catalogue est publique : aucun token ne doit être envoyé."""
        http = MockTimedHttp()
        run_salon_search(http, _make_context(), random.Random(0))
        assert all(c.token is None for c in http.calls)

    def test_sends_pagination_params(self) -> None:
        http = MockTimedHttp()
        run_salon_search(http, _make_context(), random.Random(0))
        params = http.calls[0].params or {}
        assert "limit" in params
        assert "offset" in params


# ─── Scénario 3 : Dashboard gérant ────────────────────────────────────────────


class TestManagerDashboard:
    def test_returns_dashboard_group(self) -> None:
        http = MockTimedHttp()
        sample = run_manager_dashboard(http, _make_context(), random.Random(0))
        assert sample.group == config.BUDGET_DASHBOARD

    def test_makes_exactly_four_requests(self) -> None:
        """Le dashboard agrège les 4 lectures (#39 #40 #41 #43)."""
        http = MockTimedHttp()
        run_manager_dashboard(http, _make_context(), random.Random(0))
        assert len(http.calls) == 4

    def test_requests_total_is_four(self) -> None:
        http = MockTimedHttp()
        sample = run_manager_dashboard(http, _make_context(), random.Random(0))
        assert sample.requests == 4

    def test_all_requests_carry_manager_token(self) -> None:
        """Les 4 endpoints du dashboard exigent le jeton gérant (portée salon §11.2)."""
        http = MockTimedHttp()
        run_manager_dashboard(http, _make_context(), random.Random(0))
        assert all(c.token is not None for c in http.calls)

    def test_elapsed_is_sum_of_four_calls(self) -> None:
        http = MockTimedHttp(elapsed_ms=100.0)
        sample = run_manager_dashboard(http, _make_context(), random.Random(0))
        assert sample.elapsed_ms == pytest.approx(400.0)

    def test_ok_when_all_200(self) -> None:
        http = MockTimedHttp(status=200)
        sample = run_manager_dashboard(http, _make_context(), random.Random(0))
        assert sample.ok is True

    def test_not_ok_when_any_call_fails(self) -> None:
        """Un seul endpoint en erreur suffit à dégrader le verdict agrégé."""
        idx = [0]

        class PartialHttp:
            calls: list = field(default_factory=list)

            def send(self, method, label, path, *, params=None, json=None, token=None):
                idx[0] += 1
                status = 500 if idx[0] == 3 else 200
                return TimedResponse(status=status, elapsed_ms=10.0)

        sample = run_manager_dashboard(PartialHttp(), _make_context(), random.Random(0))
        assert sample.ok is False

    def test_dashboard_calls_cover_all_four_endpoints(self) -> None:
        """Les 4 routes du dashboard (#39–#41, #43) doivent toutes figurer dans les appels."""
        http = MockTimedHttp()
        run_manager_dashboard(http, _make_context(), random.Random(0))
        paths = {c.path for c in http.calls}
        expected_fragments = [
            "dashboard/kpis",
            "revenue",
            "service-demand",
            "hairdresser-performance",
        ]
        for fragment in expected_fragments:
            assert any(fragment in p for p in paths), (
                f"L'endpoint '{fragment}' est absent du scénario dashboard — "
                "il doit figurer parmi les 4 lectures du tableau de bord."
            )


# ─── Scénario 4 : API générale ────────────────────────────────────────────────


class TestApiGeneral:
    def test_returns_api_general_group(self) -> None:
        http = MockTimedHttp()
        sample = run_api_general(http, _make_context(), random.Random(0))
        assert sample.group == config.BUDGET_API_GENERAL

    def test_makes_exactly_one_request(self) -> None:
        http = MockTimedHttp()
        run_api_general(http, _make_context(), random.Random(0))
        assert len(http.calls) == 1

    def test_ok_when_200(self) -> None:
        http = MockTimedHttp(status=200)
        sample = run_api_general(http, _make_context(), random.Random(0))
        assert sample.ok is True

    def test_not_ok_when_403(self) -> None:
        http = MockTimedHttp(status=403)
        sample = run_api_general(http, _make_context(), random.Random(0))
        assert sample.ok is False

    def test_uses_auth_token(self) -> None:
        """Les lectures protégées exigent un token (deny-by-default §11.2)."""
        http = MockTimedHttp()
        run_api_general(http, _make_context(), random.Random(0))
        assert all(c.token is not None for c in http.calls)

    def test_elapsed_matches_single_call(self) -> None:
        http = MockTimedHttp(elapsed_ms=77.0)
        sample = run_api_general(http, _make_context(), random.Random(0))
        assert sample.elapsed_ms == pytest.approx(77.0)

    def test_chooses_from_multiple_routes(self) -> None:
        """Le scénario doit varier les routes sur plusieurs itérations (mix de trafic)."""
        routes_seen: set[str] = set()
        for seed in range(20):
            http = MockTimedHttp()
            run_api_general(http, _make_context(), random.Random(seed))
            for call in http.calls:
                routes_seen.add(call.label)
        assert len(routes_seen) > 1, (
            "run_api_general doit sélectionner parmi plusieurs routes différentes "
            "(diversité du trafic réel)."
        )


# ─── Pondération du trafic (weighted_groups) ──────────────────────────────────


class TestWeightedGroups:
    def test_all_four_groups_present(self) -> None:
        plan = weighted_groups()
        for group in config.BUDGETS_MS:
            assert group in plan, f"Le groupe {group!r} est absent du plan de charge."

    def test_salon_search_has_highest_count(self) -> None:
        """La recherche salon est le scénario le plus fréquent (catalogue public)."""
        plan = weighted_groups()
        counts = {g: plan.count(g) for g in config.BUDGETS_MS}
        assert counts[config.BUDGET_SALON_SEARCH] == max(counts.values()), (
            "BUDGET_SALON_SEARCH doit avoir le poids le plus élevé (trafic catalogue dominant)."
        )

    def test_ticket_create_has_lowest_count(self) -> None:
        """L'émission de ticket (écriture + effets de bord) est la moins fréquente."""
        plan = weighted_groups()
        counts = {g: plan.count(g) for g in config.BUDGETS_MS}
        assert counts[config.BUDGET_TICKET_CREATE] == min(counts.values()), (
            "BUDGET_TICKET_CREATE doit avoir le poids le plus faible (écriture limitée)."
        )

    def test_total_length_equals_sum_of_weights(self) -> None:
        plan = weighted_groups()
        expected_total = sum(SCENARIO_WEIGHTS.values())
        assert len(plan) == expected_total

    def test_all_scenario_weights_are_positive(self) -> None:
        for group, w in SCENARIO_WEIGHTS.items():
            assert w > 0, f"Le poids de {group!r} doit être strictement positif."


# ─── Scénario 2 : émission de ticket walk-in ──────────────────────────────────


class TestTicketCreate:
    """`run_ticket_create()` : fiche walk-in (borne) → émission de ticket."""

    def test_returns_ticket_create_group(self) -> None:
        http = MockTimedHttp(status=201, body={"customer_id": "cust-1"})
        sample = run_ticket_create(http, _make_context(), random.Random(0))
        assert sample.group == config.BUDGET_TICKET_CREATE

    def test_makes_exactly_two_requests_on_success(self) -> None:
        """Fiche walk-in puis ticket : deux appels quand tout aboutit."""
        http = MockTimedHttp(status=201, body={"customer_id": "cust-1"})
        run_ticket_create(http, _make_context(), random.Random(0))
        assert len(http.calls) == 2

    def test_second_call_uses_customer_id_from_first(self) -> None:
        """Le ticket référence la fiche walk-in tout juste créée."""
        http = MockTimedHttp(status=201, body={"customer_id": "cust-1"})
        run_ticket_create(http, _make_context(), random.Random(0))
        assert http.calls[1].json_body["customer_profile_id"] == "cust-1"

    def test_uses_terminal_token(self) -> None:
        """L'émission de ticket exige le jeton borne (`QUEUE_TICKET_CREATE`, TERMINAL uniquement)."""
        http = MockTimedHttp(status=201, body={"customer_id": "cust-1"})
        run_ticket_create(http, _make_context(), random.Random(0))
        assert all(c.token is not None for c in http.calls)

    def test_elapsed_is_sum_of_two_calls(self) -> None:
        http = MockTimedHttp(status=201, elapsed_ms=40.0, body={"customer_id": "cust-1"})
        sample = run_ticket_create(http, _make_context(), random.Random(0))
        assert sample.elapsed_ms == pytest.approx(80.0)

    def test_ok_when_both_calls_succeed(self) -> None:
        http = MockTimedHttp(status=201, body={"customer_id": "cust-1"})
        sample = run_ticket_create(http, _make_context(), random.Random(0))
        assert sample.ok is True

    def test_stops_after_one_request_when_customer_creation_fails(self) -> None:
        """Une fiche walk-in refusée n'entraîne aucune tentative d'émission de ticket."""
        http = MockTimedHttp(status=422)
        sample = run_ticket_create(http, _make_context(), random.Random(0))
        assert len(http.calls) == 1
        assert sample.ok is False

    def test_not_ok_when_ticket_creation_fails(self) -> None:
        calls = {"n": 0}

        class PartialHttp:
            calls: list = field(default_factory=list)

            def send(self, method, label, path, *, params=None, json=None, token=None):
                calls["n"] += 1
                status = 201 if calls["n"] == 1 else 422
                return TimedResponse(status=status, elapsed_ms=10.0, json={"customer_id": "cust-1"})

        sample = run_ticket_create(PartialHttp(), _make_context(), random.Random(0))
        assert sample.ok is False
