"""Moteur de charge **alternatif** Locust (opt-in, extra `perf`) — #52.

Pilote les **mêmes** fonctions de scénario que le pilote intégré (`scenarios.py`) :
aucune duplication de la logique de trafic. Le pilote intégré (`driver.py` / `run.py`)
reste le moteur **par défaut** et le seul à émettre la **table de verdict vs budgets
§12.1** ; Locust fournit ses propres statistiques (p50/p95/p99, RPS) et son UI web,
utiles pour l'exploration et les paliers longs.

Prérequis : la cible doit être **seedée** au préalable. Ce fichier seede **au
démarrage** (événement `init`, une fois) contre l'hôte Locust (`--host`) ou
`PERF_TARGET_URL`. Nettoyage après coup : `python -m perf.run --teardown-only`.

Lancement (headless) :
    cd backend
    locust -f perf/locustfile.py --headless -u 20 -r 5 -t 70s \
        --host http://127.0.0.1:8000

**Hygiène §11** : les jetons du seed ne sont **jamais** tracés ; Locust nomme les
requêtes par **gabarit de route** (aucune PII dans les stats).
"""

from __future__ import annotations

import logging
import os
import random

from locust import HttpUser, between, events, task

from . import config, scenarios
from .scenarios import SeedContext, TimedResponse

logger = logging.getLogger("perf.locust")

# Contexte de seed **partagé** par tous les VUs du processus Locust (headless mono-
# processus : l'`init` seede une fois, les tâches lisent ce global).
_CONTEXT: SeedContext | None = None


@events.init.add_listener
def _seed_on_init(environment, **_kwargs) -> None:
    """Seede la cible une fois au démarrage (désactivable via `PERF_LOCUST_SEED=0`)."""

    global _CONTEXT
    if os.environ.get("PERF_LOCUST_SEED", "1").strip() in ("0", "false", "no"):
        logger.info("PERF_LOCUST_SEED désactivé : la cible est supposée déjà seedée.")
        return
    base_url = (os.environ.get("PERF_TARGET_URL", "").strip() or environment.host or "").rstrip("/")
    if not base_url:
        logger.error("Aucun hôte : passez --host ou PERF_TARGET_URL. Seed ignoré.")
        return
    from .seed import seed as seed_target

    _CONTEXT = seed_target(base_url, config.dataset_profile_from_env())
    logger.info("Seed Locust terminé (%d salons).", len(_CONTEXT.salons))


class LocustTimedHttp:
    """Adapte la session HTTP Locust au protocole `TimedHttp` des scénarios."""

    def __init__(self, http_session) -> None:
        self._session = http_session

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
        headers = {"Authorization": f"Bearer {token}"} if token else None
        # `name=label` regroupe les stats Locust par gabarit de route (aucune PII).
        resp = self._session.request(
            method, path, params=params, json=json, headers=headers, name=label
        )
        elapsed_ms = resp.elapsed.total_seconds() * 1000.0
        body = None
        if resp.content:
            try:
                body = resp.json()
            except ValueError:
                body = None
        return TimedResponse(status=resp.status_code, elapsed_ms=elapsed_ms, json=body)


class CoifLinkLoadUser(HttpUser):
    """Utilisateur virtuel : mix pondéré des scénarios §12.1 (mêmes poids que le pilote)."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self._http = LocustTimedHttp(self.client)
        self._rng = random.Random()

    def _ready(self) -> bool:
        return _CONTEXT is not None and _CONTEXT.is_ready()

    @task(scenarios.SCENARIO_WEIGHTS[config.BUDGET_SALON_SEARCH])
    def salon_search(self) -> None:
        if self._ready():
            scenarios.run_salon_search(self._http, _CONTEXT, self._rng)

    @task(scenarios.SCENARIO_WEIGHTS[config.BUDGET_API_GENERAL])
    def api_general(self) -> None:
        if self._ready():
            scenarios.run_api_general(self._http, _CONTEXT, self._rng)

    @task(scenarios.SCENARIO_WEIGHTS[config.BUDGET_DASHBOARD])
    def manager_dashboard(self) -> None:
        if self._ready():
            scenarios.run_manager_dashboard(self._http, _CONTEXT, self._rng)

    @task(scenarios.SCENARIO_WEIGHTS[config.BUDGET_APPOINTMENT_CREATE])
    def appointment_create(self) -> None:
        if self._ready():
            scenarios.run_appointment_create(self._http, _CONTEXT, self._rng)


__all__ = ["CoifLinkLoadUser", "LocustTimedHttp"]
