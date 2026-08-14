"""Pilote de charge **intégré** (httpx + threads) — moteur par défaut de #52.

Exécute les scénarios partagés (`scenarios.py`) contre un **serveur réel** (jamais
`TestClient`) avec un pool d'utilisateurs virtuels concurrents, mesure la latence à
l'**horloge monotone** (`time.perf_counter`), **exclut la fenêtre de warm-up** et
n'agrège que le **régime établi**. Produit un `report.PerfReport` confronté aux
budgets §12.1.

Aucune dépendance à un binaire externe : seul `httpx` (extra `perf`) est requis.
Locust reste un moteur **alternatif** opt-in (`locustfile.py`), pilotant les **mêmes**
fonctions de scénario.
"""

from __future__ import annotations

import datetime
import random
import threading
import time
from dataclasses import dataclass, field

import httpx

from . import config, scenarios
from .report import EndpointResult, PerfReport
from .scenarios import SeedContext, TimedResponse

# Ordre stable des groupes dans le rapport (aligne CSV/JSON/Markdown).
_GROUP_ORDER = (
    config.BUDGET_SALON_SEARCH,
    config.BUDGET_TICKET_CREATE,
    config.BUDGET_DASHBOARD,
    config.BUDGET_API_GENERAL,
)


# ─── Transport chronométré httpx (implémente le protocole `TimedHttp`) ────────


class HttpxTimedHttp:
    """Transport `httpx` qui chronomètre chaque appel à l'horloge monotone."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

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
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        start = time.perf_counter()
        try:
            resp = self._client.request(
                method, path, params=params, json=json, headers=headers
            )
        except httpx.HTTPError:
            # Erreur transport (timeout, connexion) : latence non mesurable, statut 0.
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return TimedResponse(status=0, elapsed_ms=elapsed_ms, json=None)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        body = None
        if resp.content:
            try:
                body = resp.json()
            except ValueError:
                body = None
        return TimedResponse(status=resp.status_code, elapsed_ms=elapsed_ms, json=body)

    def close(self) -> None:
        self._client.close()


# ─── Collecteur thread-safe (régime établi uniquement) ────────────────────────


@dataclass
class _GroupBucket:
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0


class _Collector:
    """Agrège les échantillons du **régime établi** (warm-up déjà exclu à l'appel)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _GroupBucket] = {g: _GroupBucket() for g in _GROUP_ORDER}

    def record(self, sample: scenarios.ScenarioSample) -> None:
        with self._lock:
            bucket = self._buckets[sample.group]
            if sample.ok:
                bucket.latencies_ms.append(sample.elapsed_ms)
            else:
                bucket.errors += 1

    def bucket(self, group: str) -> _GroupBucket:
        return self._buckets[group]


# ─── Boucle de charge ─────────────────────────────────────────────────────────


def run_load(
    base_url: str,
    ctx: SeedContext,
    profile: config.LoadProfile | None = None,
    *,
    timeout: float = 10.0,
    rng_seed: int | None = 1234,
) -> PerfReport:
    """Lance la charge et renvoie le rapport confronté aux budgets §12.1.

    `warmup_s` est **exclu** (les échantillons collectés avant le début du régime
    établi sont ignorés) ; seul le palier `steady_state_s` est agrégé. Chaque VU est
    un thread avec son propre client httpx et son propre `random.Random` (semé de
    façon déterministe pour la reproductibilité du **mix** de trafic, pas des latences).
    """

    profile = profile or config.LoadProfile()
    if not ctx.is_ready():
        raise ValueError(
            "SeedContext incomplet : le seed doit fournir des salons et des jetons clients."
        )

    plan = scenarios.weighted_groups()
    collector = _Collector()

    start = time.monotonic()
    warmup_until = start + profile.warmup_s
    steady_until = warmup_until + profile.steady_state_s

    def worker(worker_ix: int) -> None:
        http = HttpxTimedHttp(base_url, timeout=timeout)
        rng = random.Random(None if rng_seed is None else rng_seed + worker_ix)
        try:
            while True:
                now = time.monotonic()
                if now >= steady_until:
                    break
                group = rng.choice(plan)
                sample = scenarios.SCENARIOS[group](http, ctx, rng)
                if now >= warmup_until:  # régime établi : on retient
                    collector.record(sample)
        finally:
            http.close()

    threads: list[threading.Thread] = []
    spawn_interval = 1.0 / profile.spawn_rate if profile.spawn_rate > 0 else 0.0
    for i in range(profile.users):
        thread = threading.Thread(target=worker, args=(i,), daemon=True, name=f"perf-vu-{i}")
        thread.start()
        threads.append(thread)
        if spawn_interval and i < profile.users - 1:
            time.sleep(spawn_interval)

    for thread in threads:
        thread.join()

    results = [
        EndpointResult(
            group=group,
            route_label=config.BUDGET_LABELS[group],
            latencies_ms=collector.bucket(group).latencies_ms,
            errors=collector.bucket(group).errors,
            duration_s=profile.steady_state_s,
        )
        for group in _GROUP_ORDER
    ]
    return PerfReport(
        results=results,
        target=base_url,
        load_users=profile.users,
        steady_state_s=profile.steady_state_s,
        percentile=config.DECISION_PERCENTILE,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    )


__all__ = ["HttpxTimedHttp", "run_load"]
