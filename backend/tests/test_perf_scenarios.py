"""Tests unitaires des scénarios de charge (`perf.scenarios`) — sans I/O ni charge (#52).

Ces tests exercent la logique de chaque scénario via un `MockTimedHttp` déterministe
et vérifient les invariants comportementaux **sans** exécuter la moindre charge ni
se connecter à un serveur :

- `SeedContext.is_ready()` — pré-condition des scénarios.
- `run_salon_search()` — route publique, variation de paramètres.
- `run_manager_dashboard()` — 5 lectures agrégées, jeton gérant, agrégat de latence.
- `run_api_general()` — lecture protégée, jeton requis.
- `run_appointment_create()` — parcours 3 étapes, arrêt anticipé sur erreur/pas de créneau.
- `weighted_groups()` — tous les groupes présents, poids relatifs cohérents.
- `_future_slot_date()` — toujours un lundi futur en format ISO.
"""

from __future__ import annotations

import datetime
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
    run_appointment_create,
    run_manager_dashboard,
    run_salon_search,
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


class _SequentialMockHttp:
    """Transport de test séquentiel : chaque appel consomme la prochaine `TimedResponse`."""

    def __init__(self, responses: list[TimedResponse]) -> None:
        self._responses = responses
        self._idx = 0
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
        resp = (
            self._responses[self._idx]
            if self._idx < len(self._responses)
            else self._responses[-1]
        )
        self._idx += 1
        return resp


# ─── Fixtures de contexte ─────────────────────────────────────────────────────


def _make_context(n_salons: int = 2, n_clients: int = 3) -> SeedContext:
    salons = [
        SalonFixture(
            salon_id=f"salon-{i}",
            manager_token=f"mgr-token-{i}",
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


def _availability_body() -> dict:
    """Corps de disponibilités minimal avec un créneau libre."""
    return {"slots": [{"start": "09:00", "end": "09:30"}]}


# ─── SeedContext.is_ready() ───────────────────────────────────────────────────


class TestSeedContext:
    def test_is_ready_true_when_populated(self) -> None:
        assert _make_context().is_ready() is True

    def test_is_ready_false_when_no_salons(self) -> None:
        ctx = SeedContext(salons=[], client_tokens=["tok"])
        assert ctx.is_ready() is False

    def test_is_ready_false_when_no_client_tokens(self) -> None:
        ctx = SeedContext(
            salons=[SalonFixture("s", "t", ["svc"], ["hd"], "Nom")],
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

    def test_makes_exactly_five_requests(self) -> None:
        """Le dashboard agrège les 5 lectures (#39 #40 #41 #42 #43)."""
        http = MockTimedHttp()
        run_manager_dashboard(http, _make_context(), random.Random(0))
        assert len(http.calls) == 5

    def test_requests_total_is_five(self) -> None:
        http = MockTimedHttp()
        sample = run_manager_dashboard(http, _make_context(), random.Random(0))
        assert sample.requests == 5

    def test_all_requests_carry_manager_token(self) -> None:
        """Les 5 endpoints du dashboard exigent le jeton gérant (portée salon §11.2)."""
        http = MockTimedHttp()
        run_manager_dashboard(http, _make_context(), random.Random(0))
        assert all(c.token is not None for c in http.calls)

    def test_elapsed_is_sum_of_five_calls(self) -> None:
        http = MockTimedHttp(elapsed_ms=100.0)
        sample = run_manager_dashboard(http, _make_context(), random.Random(0))
        assert sample.elapsed_ms == pytest.approx(500.0)

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

    def test_dashboard_calls_cover_all_five_endpoints(self) -> None:
        """Les 5 routes du dashboard (#39–#43) doivent toutes figurer dans les appels."""
        http = MockTimedHttp()
        run_manager_dashboard(http, _make_context(), random.Random(0))
        paths = {c.path for c in http.calls}
        expected_fragments = [
            "daily-summary",
            "revenue",
            "service-demand",
            "active-clients",
            "hairdresser-performance",
        ]
        for fragment in expected_fragments:
            assert any(fragment in p for p in paths), (
                f"L'endpoint '{fragment}' est absent du scénario dashboard — "
                "il doit figurer parmi les 5 lectures du tableau de bord."
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


# ─── Scénario 2 : Création de rendez-vous ─────────────────────────────────────


class TestAppointmentCreate:
    def test_returns_appointment_group(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.group == config.BUDGET_APPOINTMENT_CREATE

    def test_happy_path_makes_three_requests(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        run_appointment_create(http, _make_context(), random.Random(0))
        assert len(http.calls) == 3

    def test_first_call_is_get_salon_detail(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        run_appointment_create(http, _make_context(), random.Random(0))
        first = http.calls[0]
        assert first.method == "GET"
        assert "/catalog/salons/" in first.path

    def test_second_call_is_availability(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        run_appointment_create(http, _make_context(), random.Random(0))
        assert "availability" in http.calls[1].path

    def test_third_call_is_post_appointment(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        run_appointment_create(http, _make_context(), random.Random(0))
        third = http.calls[2]
        assert third.method == "POST"
        assert "/appointments" in third.path

    def test_third_call_uses_client_token(self) -> None:
        """La création de RDV exige un jeton client (#21)."""
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        run_appointment_create(http, _make_context(), random.Random(0))
        assert http.calls[2].token is not None

    def test_third_call_has_json_payload(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        run_appointment_create(http, _make_context(), random.Random(0))
        payload = http.calls[2].json_body
        assert payload is not None
        assert "date" in payload
        assert "start_time" in payload
        assert "service_ids" in payload

    def test_elapsed_is_sum_of_three_calls(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=100.0, body=_availability_body())
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.elapsed_ms == pytest.approx(300.0)

    def test_ok_on_happy_path(self) -> None:
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body=_availability_body())
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.ok is True

    def test_stops_early_when_salon_detail_fails(self) -> None:
        """Si le détail salon répond 404, on arrête après 1 appel."""
        http = MockTimedHttp(status=404)
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.ok is False
        assert len(http.calls) == 1

    def test_stops_early_when_no_available_slots(self) -> None:
        """Si les disponibilités sont vides, on arrête après 2 appels (pas de création)."""
        http = MockTimedHttp(status=200, elapsed_ms=50.0, body={"slots": []})
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.ok is False
        assert len(http.calls) == 2

    def test_stops_early_when_availability_returns_error(self) -> None:
        """Si GET availability renvoie 500 (pas de créneaux lisibles), on s'arrête après 2 appels."""
        responses = [
            TimedResponse(status=200, elapsed_ms=50.0, json={"name": "Salon"}),  # détail OK
            TimedResponse(status=500, elapsed_ms=50.0, json=None),               # availability KO
        ]
        http = _SequentialMockHttp(responses)
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.ok is False
        assert len(http.calls) == 2

    def test_not_ok_when_booking_post_fails_with_409(self) -> None:
        """Un 409 (double-réservation sous concurrence) est compté comme erreur."""
        responses = [
            TimedResponse(status=200, elapsed_ms=50.0, json={"name": "Salon"}),
            TimedResponse(status=200, elapsed_ms=50.0, json=_availability_body()),
            TimedResponse(status=409, elapsed_ms=50.0, json={"detail": "conflict"}),
        ]
        http = _SequentialMockHttp(responses)
        sample = run_appointment_create(http, _make_context(), random.Random(0))
        assert sample.ok is False
        assert len(http.calls) == 3


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

    def test_appointment_create_has_lowest_count(self) -> None:
        """La création de RDV (écriture + effets de bord) est la moins fréquente."""
        plan = weighted_groups()
        counts = {g: plan.count(g) for g in config.BUDGETS_MS}
        assert counts[config.BUDGET_APPOINTMENT_CREATE] == min(counts.values()), (
            "BUDGET_APPOINTMENT_CREATE doit avoir le poids le plus faible (écriture limitée)."
        )

    def test_total_length_equals_sum_of_weights(self) -> None:
        plan = weighted_groups()
        expected_total = sum(SCENARIO_WEIGHTS.values())
        assert len(plan) == expected_total

    def test_all_scenario_weights_are_positive(self) -> None:
        for group, w in SCENARIO_WEIGHTS.items():
            assert w > 0, f"Le poids de {group!r} doit être strictement positif."


# ─── _future_slot_date() ──────────────────────────────────────────────────────


class TestFutureSlotDate:
    """Garanties de déterminisme de `_future_slot_date()` — aucune I/O."""

    def _call(self, seed: int = 42) -> str:
        from perf.scenarios import _future_slot_date

        return _future_slot_date(random.Random(seed))

    def test_returns_valid_iso_date(self) -> None:
        datetime.date.fromisoformat(self._call())  # lève si invalide

    def test_is_strictly_in_the_future(self) -> None:
        date = datetime.date.fromisoformat(self._call())
        assert date > datetime.date.today()

    def test_is_always_a_monday(self) -> None:
        for seed in range(10):
            date = datetime.date.fromisoformat(self._call(seed))
            assert date.weekday() == 0, (
                f"_future_slot_date() a renvoyé {date.strftime('%A')} ({date}) "
                "pour seed={seed} — doit toujours être un lundi."
            )

    def test_within_nine_weeks_from_next_monday(self) -> None:
        today = datetime.date.today()
        days_ahead = (7 - today.weekday()) % 7 or 7
        next_monday = today + datetime.timedelta(days=days_ahead)
        max_date = next_monday + datetime.timedelta(weeks=8)
        for seed in range(10):
            date = datetime.date.fromisoformat(self._call(seed))
            assert date <= max_date, (
                f"_future_slot_date() a renvoyé {date} qui dépasse la fenêtre "
                f"attendue (max {max_date})."
            )

    def test_same_seed_gives_same_result(self) -> None:
        assert self._call(seed=99) == self._call(seed=99)

    def test_different_seeds_produce_variation(self) -> None:
        results = {self._call(seed=i) for i in range(10)}
        assert len(results) > 1, (
            "_future_slot_date() doit varier selon le seed (étaler les créneaux "
            "réduit les collisions de réservation sous concurrence)."
        )
