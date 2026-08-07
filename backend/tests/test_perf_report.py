"""Tests unitaires de `perf.report` — percentiles, verdict, PerfReport, garde anti-PII (#52).

Module **pur** (stdlib uniquement) : aucun I/O, aucune charge, aucune infrastructure.
Couverture déterministe des invariants du module de rapport :

- `percentile()` : nearest-rank, cas limites (liste vide, un seul élément, p0/p100).
- `classify()` : PASS / WARN / FAIL aux bornes exactes du budget et du seuil d'alerte.
- `EndpointResult` : propriétés calculées (p50/p95/p99, error_rate, throughput_rps,
  verdict, as_row sans PII).
- `PerfReport` : verdict global (FAIL > WARN > PASS), sérialisations CSV/JSON/Markdown
  stables et sans PII.
- `find_pii` / `assert_no_pii` : détection de tous les marqueurs de fuite §11.3/§11.4.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from perf import config
from perf.report import (
    EndpointResult,
    PerfReport,
    Verdict,
    assert_no_pii,
    classify,
    find_pii,
    percentile,
)


# ─── percentile() ─────────────────────────────────────────────────────────────


class TestPercentile:
    def test_empty_returns_zero(self) -> None:
        assert percentile([], 50) == 0.0

    def test_single_element_p0(self) -> None:
        assert percentile([42.0], 0) == 42.0

    def test_single_element_p50(self) -> None:
        assert percentile([42.0], 50) == 42.0

    def test_single_element_p100(self) -> None:
        assert percentile([42.0], 100) == 42.0

    def test_p0_returns_minimum(self) -> None:
        assert percentile([30.0, 10.0, 20.0], 0) == 10.0

    def test_p100_returns_maximum(self) -> None:
        assert percentile([30.0, 10.0, 20.0], 100) == 30.0

    def test_p50_nearest_rank_five_samples(self) -> None:
        # nearest-rank : ceil(50/100 * 5) = 3 → index 2 → 30.0
        assert percentile([10.0, 20.0, 30.0, 40.0, 50.0], 50) == 30.0

    def test_p95_of_100_samples_nearest_rank(self) -> None:
        # ceil(0.95 * 100) = 95 → index 94 → 95.0 (range 1..100)
        samples = [float(i) for i in range(1, 101)]
        assert percentile(samples, 95) == 95.0

    def test_p99_of_100_samples(self) -> None:
        samples = [float(i) for i in range(1, 101)]
        assert percentile(samples, 99) == 99.0

    def test_out_of_range_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile([1.0, 2.0], -1)

    def test_out_of_range_above_100_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile([1.0, 2.0], 101)

    def test_result_is_order_independent(self) -> None:
        samples = [50.0, 10.0, 30.0, 20.0, 40.0]
        assert percentile(samples, 95) == percentile(sorted(samples), 95)

    def test_decision_percentile_matches_p95(self) -> None:
        """Le percentile de décision du module est bien p95."""
        samples = list(range(1, 101))
        assert percentile(samples, config.DECISION_PERCENTILE) == percentile(samples, 95)

    def test_all_same_values(self) -> None:
        samples = [100.0] * 50
        assert percentile(samples, 50) == 100.0
        assert percentile(samples, 95) == 100.0


# ─── classify() ───────────────────────────────────────────────────────────────


class TestClassify:
    """Verdict PASS / WARN / FAIL aux bornes exactes (cas limites documentés dans la spec)."""

    def test_strictly_below_alert_threshold_is_pass(self) -> None:
        budget = 2000
        alert = config.alert_threshold_ms(budget)
        assert classify(alert - 1.0, budget) == Verdict.PASS

    def test_exactly_at_alert_threshold_is_pass(self) -> None:
        """Borne inclusive : mesure = seuil d'alerte → PASS (pas encore dans la bande WARN)."""
        budget = 2000
        alert = config.alert_threshold_ms(budget)
        assert classify(alert, budget) == Verdict.PASS

    def test_one_ms_above_alert_is_warn(self) -> None:
        budget = 2000
        alert = config.alert_threshold_ms(budget)
        assert classify(alert + 1.0, budget) == Verdict.WARN

    def test_exactly_at_budget_is_warn_not_fail(self) -> None:
        """Borne inclusive : mesure = budget → WARN (pas encore FAIL)."""
        budget = 3000
        assert classify(3000.0, budget) == Verdict.WARN

    def test_one_ms_above_budget_is_fail(self) -> None:
        budget = 3000
        assert classify(3001.0, budget) == Verdict.FAIL

    def test_zero_ms_is_always_pass(self) -> None:
        for budget in config.BUDGETS_MS.values():
            assert classify(0.0, budget) == Verdict.PASS

    def test_custom_alert_margin_100_pct(self) -> None:
        """Avec margin=1.0, alert == budget, donc above alert = above budget → FAIL uniquement."""
        budget = 2000
        # alert = 2000, measured = 1999 → ≤ alert → PASS
        assert classify(1999.0, budget, alert_margin=1.0) == Verdict.PASS
        # measured = 2000 → at budget & at alert → PASS (≤ alert)
        assert classify(2000.0, budget, alert_margin=1.0) == Verdict.PASS
        # measured = 2001 → > budget → FAIL
        assert classify(2001.0, budget, alert_margin=1.0) == Verdict.FAIL

    @pytest.mark.parametrize("group", list(config.BUDGETS_MS.keys()))
    def test_zero_passes_for_every_group(self, group: str) -> None:
        assert classify(0.0, config.BUDGETS_MS[group]) == Verdict.PASS

    @pytest.mark.parametrize("group", list(config.BUDGETS_MS.keys()))
    def test_very_large_value_fails_for_every_group(self, group: str) -> None:
        assert classify(999_999.0, config.BUDGETS_MS[group]) == Verdict.FAIL

    def test_salon_search_budget_boundaries(self) -> None:
        budget = config.BUDGETS_MS[config.BUDGET_SALON_SEARCH]
        assert budget == 2000
        assert classify(1999.0, budget) in (Verdict.PASS, Verdict.WARN)
        assert classify(2001.0, budget) == Verdict.FAIL

    def test_verdict_string_representation(self) -> None:
        assert str(Verdict.PASS) == "PASS"
        assert str(Verdict.WARN) == "WARN"
        assert str(Verdict.FAIL) == "FAIL"


# ─── EndpointResult ───────────────────────────────────────────────────────────


def _make_result(
    latencies: list[float],
    errors: int = 0,
    duration_s: float = 60.0,
    group: str = config.BUDGET_SALON_SEARCH,
) -> EndpointResult:
    return EndpointResult(
        group=group,
        route_label=config.BUDGET_LABELS[group],
        latencies_ms=latencies,
        errors=errors,
        duration_s=duration_s,
    )


class TestEndpointResult:
    def test_count_equals_len_latencies(self) -> None:
        r = _make_result([100.0, 200.0, 300.0])
        assert r.count == 3

    def test_requests_total_includes_errors(self) -> None:
        r = _make_result([100.0, 200.0], errors=5)
        assert r.requests_total == 7

    def test_requests_total_zero_when_both_empty(self) -> None:
        r = _make_result([])
        assert r.requests_total == 0

    def test_p50_nearest_rank(self) -> None:
        samples = list(range(1, 101))
        r = _make_result([float(x) for x in samples])
        assert r.p50 == pytest.approx(percentile([float(x) for x in samples], 50))

    def test_p95_of_100_samples(self) -> None:
        r = _make_result([float(i) for i in range(1, 101)])
        assert r.p95 == pytest.approx(95.0)

    def test_p99_of_100_samples(self) -> None:
        r = _make_result([float(i) for i in range(1, 101)])
        assert r.p99 == pytest.approx(99.0)

    def test_empty_latencies_all_percentiles_are_zero(self) -> None:
        r = _make_result([])
        assert r.p50 == 0.0
        assert r.p95 == 0.0
        assert r.p99 == 0.0

    def test_error_rate_zero_when_no_errors(self) -> None:
        r = _make_result([100.0, 200.0], errors=0)
        assert r.error_rate == pytest.approx(0.0)

    def test_error_rate_one_when_all_errors(self) -> None:
        r = _make_result([], errors=10)
        assert r.error_rate == pytest.approx(1.0)

    def test_error_rate_partial(self) -> None:
        r = _make_result([100.0], errors=1)
        assert r.error_rate == pytest.approx(0.5)

    def test_throughput_zero_when_duration_is_zero(self) -> None:
        r = _make_result([100.0, 200.0], duration_s=0.0)
        assert r.throughput_rps == 0.0

    def test_throughput_correct(self) -> None:
        r = _make_result([float(i) for i in range(60)], duration_s=10.0)
        assert r.throughput_rps == pytest.approx(6.0)

    def test_budget_ms_from_config(self) -> None:
        r = _make_result([])
        assert r.budget_ms == config.BUDGETS_MS[config.BUDGET_SALON_SEARCH]

    def test_verdict_pass_when_well_under_budget(self) -> None:
        r = _make_result([10.0] * 100)
        assert r.verdict == Verdict.PASS

    def test_verdict_fail_when_over_budget(self) -> None:
        budget = config.BUDGETS_MS[config.BUDGET_SALON_SEARCH]
        r = _make_result([float(budget + 500)] * 100)
        assert r.verdict == Verdict.FAIL

    def test_as_row_contains_required_keys(self) -> None:
        r = _make_result([100.0])
        row = r.as_row()
        for key in (
            "group", "route", "budget_ms", "requests", "errors",
            "error_rate", "p50_ms", "p95_ms", "p99_ms", "throughput_rps", "verdict",
        ):
            assert key in row, f"Clé manquante dans as_row() : {key!r}"

    def test_as_row_verdict_is_string(self) -> None:
        r = _make_result([10.0] * 50)
        assert r.as_row()["verdict"] in ("PASS", "WARN", "FAIL")

    def test_as_row_no_pii_in_string_repr(self) -> None:
        r = _make_result([100.0])
        row_str = str(r.as_row())
        assert config.RESERVED_PHONE_PREFIX not in row_str
        assert "Bearer " not in row_str
        assert config.SEED_PASSWORD not in row_str


# ─── PerfReport ───────────────────────────────────────────────────────────────


def _result_all_pass() -> list[EndpointResult]:
    return [_make_result([10.0] * 50, group=g) for g in config.BUDGETS_MS]


def _sample_report() -> PerfReport:
    return PerfReport(
        results=_result_all_pass(),
        target="http://127.0.0.1:8000",
        load_users=20,
        steady_state_s=60.0,
        percentile=config.DECISION_PERCENTILE,
        generated_at="2026-01-01T00:00:00+00:00",
    )


class TestPerfReportOverallVerdict:
    def test_overall_pass_when_all_pass(self) -> None:
        r = _sample_report()
        assert r.overall == Verdict.PASS

    def test_overall_fail_when_one_group_fails(self) -> None:
        budget = config.BUDGETS_MS[config.BUDGET_SALON_SEARCH]
        results = [
            _make_result([float(budget + 200)] * 50, group=config.BUDGET_SALON_SEARCH),
        ] + [
            _make_result([10.0] * 50, group=g)
            for g in config.BUDGETS_MS
            if g != config.BUDGET_SALON_SEARCH
        ]
        r = PerfReport(results=results)
        assert r.overall == Verdict.FAIL

    def test_overall_warn_when_one_group_warns_and_none_fails(self) -> None:
        budget = config.BUDGETS_MS[config.BUDGET_SALON_SEARCH]
        alert = config.alert_threshold_ms(budget)
        results = [
            _make_result([alert + 10.0] * 50, group=config.BUDGET_SALON_SEARCH),
        ] + [
            _make_result([10.0] * 50, group=g)
            for g in config.BUDGETS_MS
            if g != config.BUDGET_SALON_SEARCH
        ]
        r = PerfReport(results=results)
        assert r.overall == Verdict.WARN

    def test_overall_fail_dominates_warn(self) -> None:
        budget_search = config.BUDGETS_MS[config.BUDGET_SALON_SEARCH]
        budget_appt = config.BUDGETS_MS[config.BUDGET_APPOINTMENT_CREATE]
        alert_search = config.alert_threshold_ms(budget_search)
        results = [
            _make_result([alert_search + 10.0] * 50, group=config.BUDGET_SALON_SEARCH),  # WARN
            _make_result([float(budget_appt + 500)] * 50, group=config.BUDGET_APPOINTMENT_CREATE),  # FAIL
            _make_result([10.0] * 50, group=config.BUDGET_DASHBOARD),
            _make_result([10.0] * 50, group=config.BUDGET_API_GENERAL),
        ]
        r = PerfReport(results=results)
        assert r.overall == Verdict.FAIL

    def test_overall_empty_results_is_pass(self) -> None:
        """Aucun résultat → aucun échec → PASS (pas d'exception)."""
        r = PerfReport(results=[])
        assert r.overall == Verdict.PASS


class TestPerfReportJson:
    def test_to_json_is_valid_json(self) -> None:
        data = json.loads(_sample_report().to_json())
        assert isinstance(data, dict)

    def test_to_json_contains_results_list(self) -> None:
        data = json.loads(_sample_report().to_json())
        assert isinstance(data.get("results"), list)
        assert len(data["results"]) == len(config.BUDGETS_MS)

    def test_to_json_contains_overall_verdict(self) -> None:
        data = json.loads(_sample_report().to_json())
        assert "overall_verdict" in data
        assert data["overall_verdict"] in ("PASS", "WARN", "FAIL")

    def test_to_json_contains_budgets_source(self) -> None:
        data = json.loads(_sample_report().to_json())
        assert "budgets_source" in data
        assert "§12.1" in data["budgets_source"] or "12.1" in data["budgets_source"]

    def test_to_json_contains_decision_percentile(self) -> None:
        data = json.loads(_sample_report().to_json())
        assert data.get("decision_percentile") == config.DECISION_PERCENTILE

    def test_to_json_no_pii(self) -> None:
        assert_no_pii(_sample_report().to_json())

    def test_to_dict_matches_to_json(self) -> None:
        report = _sample_report()
        assert json.loads(report.to_json()) == report.to_dict()


class TestPerfReportCsv:
    def test_to_csv_has_correct_row_count(self) -> None:
        csv_text = _sample_report().to_csv()
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        assert len(rows) == len(config.BUDGETS_MS)

    def test_to_csv_has_verdict_column(self) -> None:
        csv_text = _sample_report().to_csv()
        for row in csv.DictReader(io.StringIO(csv_text)):
            assert "verdict" in row
            assert row["verdict"] in ("PASS", "WARN", "FAIL")

    def test_to_csv_has_budget_ms_column(self) -> None:
        csv_text = _sample_report().to_csv()
        for row in csv.DictReader(io.StringIO(csv_text)):
            assert "budget_ms" in row
            assert int(row["budget_ms"]) in config.BUDGETS_MS.values()

    def test_to_csv_no_pii(self) -> None:
        assert_no_pii(_sample_report().to_csv())


class TestPerfReportMarkdown:
    def test_to_markdown_starts_with_heading(self) -> None:
        md = _sample_report().to_markdown()
        assert md.startswith("# ")

    def test_to_markdown_contains_overall_verdict(self) -> None:
        md = _sample_report().to_markdown()
        assert any(v.value in md for v in Verdict)

    def test_to_markdown_references_budget_source(self) -> None:
        md = _sample_report().to_markdown()
        assert "§12.1" in md or "12.1" in md

    def test_to_markdown_mentions_informative_mode(self) -> None:
        """Le rapport doit rappeler son mode informatif par défaut (pas de gate bloquant)."""
        md = _sample_report().to_markdown()
        lower = md.lower()
        assert "informatif" in lower or "strict" in lower

    def test_to_markdown_no_pii(self) -> None:
        assert_no_pii(_sample_report().to_markdown())


# ─── Garde anti-PII (§11.3/§11.4) ────────────────────────────────────────────


class TestFindPii:
    def test_empty_string_has_no_pii(self) -> None:
        assert find_pii("") == []

    def test_detects_reserved_phone_prefix(self) -> None:
        hits = find_pii(f"téléphone : {config.RESERVED_PHONE_PREFIX}0001")
        assert config.RESERVED_PHONE_PREFIX in hits

    def test_detects_bearer_token(self) -> None:
        hits = find_pii("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx")
        assert "Bearer " in hits

    def test_detects_seed_password(self) -> None:
        hits = find_pii(f"mot de passe : {config.SEED_PASSWORD}")
        assert config.SEED_PASSWORD in hits

    def test_detects_access_token_key(self) -> None:
        hits = find_pii('{"access_token": "some-token"}')
        assert "access_token" in hits

    def test_detects_refresh_token_key(self) -> None:
        hits = find_pii('{"refresh_token": "xxx"}')
        assert "refresh_token" in hits

    def test_detects_email_address(self) -> None:
        hits = find_pii("utilisateur@exemple.com")
        assert "@" in hits

    def test_detects_password_keyword(self) -> None:
        hits = find_pii("password=secret123")
        assert "password" in hits

    def test_clean_report_line_has_no_pii(self) -> None:
        clean = "group: salon_search, route: /catalog/salons, p95_ms: 150.0, verdict: PASS"
        assert find_pii(clean) == []

    def test_clean_numbers_only_has_no_pii(self) -> None:
        clean = "p50_ms: 42.0, p95_ms: 78.5, p99_ms: 95.2, throughput_rps: 3.5"
        assert find_pii(clean) == []

    def test_case_insensitive_detection(self) -> None:
        """La détection de PII est insensible à la casse."""
        hits = find_pii(f"BEARER {config.RESERVED_PHONE_PREFIX}0000")
        assert any(h.lower() in ("bearer ", config.RESERVED_PHONE_PREFIX.lower()) for h in hits)


class TestAssertNoPii:
    def test_raises_assertion_error_on_pii(self) -> None:
        with pytest.raises(AssertionError, match="[Pp][Ii][Ii]"):
            assert_no_pii(f"leak: {config.RESERVED_PHONE_PREFIX}0001")

    def test_raises_on_bearer_token(self) -> None:
        with pytest.raises(AssertionError):
            assert_no_pii("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx")

    def test_does_not_raise_on_clean_string(self) -> None:
        assert_no_pii("Rapport — p95_ms: 1234.5, verdict: PASS, groupe: salon_search")

    def test_does_not_raise_on_empty_string(self) -> None:
        assert_no_pii("")

    def test_clean_report_passes(self) -> None:
        """Un rapport minimal bien construit passe la garde."""
        report = _sample_report()
        assert_no_pii(report.to_json())
        assert_no_pii(report.to_csv())
        assert_no_pii(report.to_markdown())
