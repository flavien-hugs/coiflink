"""Scénarios de charge par **groupe de budget §12.1** — source **unique** partagée.

Ces scénarios sont **agnostiques du moteur** : ils s'expriment via un petit protocole
`TimedHttp.send(...)` que fournissent **aussi bien** le pilote intégré (`driver.py`,
httpx) que le `locustfile.py` (moteur Locust opt-in). Aucune duplication de la logique
de trafic entre les deux moteurs.

Chaque scénario **n'exerce que des chemins autorisés** (respect deny-by-default /
portée §11.2) : les jetons proviennent du seed et **ne sont jamais tracés**. Un
appel non-2xx attendu (p. ex. `409` de double-réservation sous concurrence) est compté
comme **erreur**, jamais mêlé aux latences « utiles ».

Mesure :
- `salon_search` / `api_general` : un appel → la latence de cet appel.
- `ticket_create` : **parcours** borne — fiche walk-in → émission de ticket ; la
  latence retenue est la **somme** (le budget §12.1 « émission de ticket » couvre le
  chemin complet, création de fiche comprise). Contrairement à l'ancien RDV, aucun
  état « complet »/indisponible à gérer : un ticket peut toujours être émis.
- `dashboard` : les **quatre** lectures du tableau de bord en séquence ; la latence
  retenue est l'**agrégat** (somme des temps serveur), confronté au budget « < 3 s ».
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import config


# ─── Contexte issu du seed (produit par seed.py, consommé par les moteurs) ────


@dataclass
class SalonFixture:
    """Un salon seedé, walk-in, avec ses prestations, coiffeurs et sa borne (aucune PII)."""

    salon_id: str
    manager_token: str  # jeton gérant (jamais tracé)
    terminal_token: str  # jeton borne (jamais tracé) — émission de tickets/fiches walk-in
    service_ids: list[str]
    hairdresser_ids: list[str]
    name: str
    city: str | None = None
    commune: str | None = None


@dataclass
class SeedContext:
    """Décor complet nécessaire aux scénarios (identités bornées à la plage réservée)."""

    salons: list[SalonFixture] = field(default_factory=list)
    client_tokens: list[str] = field(default_factory=list)  # jetons clients (jamais tracés)
    search_terms: list[str] = field(default_factory=list)

    def is_ready(self) -> bool:
        return bool(self.salons and self.client_tokens)


# ─── Protocole de transport chronométré (implémenté par chaque moteur) ────────


@dataclass
class TimedResponse:
    """Réponse d'un appel chronométré : statut, latence serveur mesurée, corps JSON."""

    status: int
    elapsed_ms: float
    json: Any = None


class TimedHttp(Protocol):
    """Transport minimal que chaque moteur (httpx / locust) fournit aux scénarios."""

    def send(
        self,
        method: str,
        label: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> TimedResponse:
        """Exécute et **chronomètre** un appel HTTP (horloge monotone côté moteur).

        `label` est le **gabarit de route** (aucune PII) utilisé pour le rapport ;
        `path` est le chemin concret. `token` (jeton Bearer) n'est **jamais** tracé.
        """
        ...


# ─── Résultat d'un scénario (une itération) ───────────────────────────────────


@dataclass(frozen=True)
class ScenarioSample:
    """Résultat d'une itération : latence du chemin mesuré + comptage d'appels/erreurs."""

    group: str
    route_label: str
    elapsed_ms: float
    ok: bool
    requests: int = 1


def _ok(status: int) -> bool:
    return 200 <= status < 300


# ─── Scénario 1 — Recherche salon (< 2 s) ─────────────────────────────────────


def run_salon_search(http: TimedHttp, ctx: SeedContext, rng: random.Random) -> ScenarioSample:
    """`GET /catalog/salons` avec variation `q`/`city`/`commune` + pagination (public)."""

    params: dict[str, Any] = {"limit": rng.choice([10, 20, 50]), "offset": 0}
    mode = rng.choice(["q", "city", "commune", "page"])
    if mode == "q" and ctx.search_terms:
        params["q"] = rng.choice(ctx.search_terms)
    elif mode == "city":
        cities = [s.city for s in ctx.salons if s.city]
        if cities:
            params["city"] = rng.choice(cities)
    elif mode == "commune":
        communes = [s.commune for s in ctx.salons if s.commune]
        if communes:
            params["commune"] = rng.choice(communes)
    else:  # pagination profonde
        params["offset"] = rng.choice([0, 10, 20])

    resp = http.send("GET", "/catalog/salons", "/catalog/salons", params=params)
    return ScenarioSample(
        config.BUDGET_SALON_SEARCH, "/catalog/salons", resp.elapsed_ms, _ok(resp.status)
    )


# ─── Scénario 2 — Émission d'un ticket walk-in (< 3 s) ────────────────────────


def run_ticket_create(http: TimedHttp, ctx: SeedContext, rng: random.Random) -> ScenarioSample:
    """Parcours borne : création d'une fiche walk-in → émission d'un ticket de passage.

    ⚠ La création **écrit** (fiche + ticket) : bornée à la plage réservée, nettoyée
    au teardown. La fiche est **salon-scopée** (`customer_profiles.phone` unique par
    salon) : un doublon de téléphone sous concurrence (`409`) est compté comme
    **erreur**, jamais mêlé aux latences « utiles » — aucune contrainte d'exclusion
    de créneau ici (contrairement à l'ancien RDV, un ticket est toujours émissible).
    """

    salon = rng.choice(ctx.salons)
    service_id = rng.choice(salon.service_ids)
    total = 0.0
    requests = 0

    customer = http.send(
        "POST",
        "/salons/{id}/terminal/customers",
        f"/salons/{salon.salon_id}/terminal/customers",
        json={
            "first_name": "Perf",
            "last_name": f"WalkIn{rng.randint(0, 999_999)}",
            "phone": config.local_phone(rng.randint(0, 9999)),
        },
        token=salon.terminal_token,
    )
    total += customer.elapsed_ms
    requests += 1
    if not _ok(customer.status):
        return ScenarioSample(
            config.BUDGET_TICKET_CREATE, "POST /salons/{id}/queue/tickets", total, False, requests
        )
    customer_profile_id = (customer.json or {}).get("customer_id")

    ticket = http.send(
        "POST",
        "/salons/{id}/queue/tickets",
        f"/salons/{salon.salon_id}/queue/tickets",
        json={"customer_profile_id": customer_profile_id, "service_ids": [service_id]},
        token=salon.terminal_token,
    )
    total += ticket.elapsed_ms
    requests += 1
    return ScenarioSample(
        config.BUDGET_TICKET_CREATE,
        "POST /salons/{id}/queue/tickets",
        total,
        _ok(ticket.status),
        requests,
    )


# ─── Scénario 3 — Dashboard gérant (agrégat < 3 s) ────────────────────────────

#: Les quatre lectures qui composent le tableau de bord gérant (#40/#41/#43/#148).
_DASHBOARD_READS: tuple[tuple[str, str], ...] = (
    ("/salons/{id}/dashboard/kpis", "/salons/{sid}/dashboard/kpis"),
    ("/salons/{id}/revenue/summary", "/salons/{sid}/revenue/summary"),
    ("/salons/{id}/service-demand", "/salons/{sid}/service-demand"),
    ("/salons/{id}/hairdresser-performance", "/salons/{sid}/hairdresser-performance"),
)


def run_manager_dashboard(
    http: TimedHttp, ctx: SeedContext, rng: random.Random
) -> ScenarioSample:
    """Les 4 lectures du dashboard en séquence (portée salon, gérant) → agrégat < 3 s."""

    salon = rng.choice(ctx.salons)
    total = 0.0
    requests = 0
    ok = True
    for label, template in _DASHBOARD_READS:
        path = template.format(sid=salon.salon_id)
        resp = http.send("GET", label, path, token=salon.manager_token)
        total += resp.elapsed_ms
        requests += 1
        ok = ok and _ok(resp.status)
    return ScenarioSample(config.BUDGET_DASHBOARD, "dashboard (4 lectures)", total, ok, requests)


# ─── Scénario 4 — API générale (échantillon de lectures protégées, < 3 s) ─────


def run_api_general(http: TimedHttp, ctx: SeedContext, rng: random.Random) -> ScenarioSample:
    """Un échantillon de lectures protégées (rôle correct) — budget API générale."""

    salon = rng.choice(ctx.salons)
    client_token = rng.choice(ctx.client_tokens)
    choices: list[tuple[str, str, str, str, dict[str, Any] | None]] = [
        ("GET", "/me/receipts", "/me/receipts", client_token, None),
        (
            "GET",
            "/salons/{id}/queue/tickets",
            f"/salons/{salon.salon_id}/queue/tickets",
            salon.manager_token,
            None,
        ),
        (
            "GET",
            "/salons/{id}/payments",
            f"/salons/{salon.salon_id}/payments",
            salon.manager_token,
            None,
        ),
    ]
    method, label, path, token, params = rng.choice(choices)
    resp = http.send(method, label, path, params=params, token=token)
    return ScenarioSample(config.BUDGET_API_GENERAL, label, resp.elapsed_ms, _ok(resp.status))


# ─── Pondération réaliste du trafic ───────────────────────────────────────────
#
# Beaucoup de lectures catalogue, moins d'émissions de tickets (écriture) — profil
# proche d'un trafic client réel. Poids relatifs (révisables).

SCENARIOS: dict[str, Any] = {
    config.BUDGET_SALON_SEARCH: run_salon_search,
    config.BUDGET_TICKET_CREATE: run_ticket_create,
    config.BUDGET_DASHBOARD: run_manager_dashboard,
    config.BUDGET_API_GENERAL: run_api_general,
}

SCENARIO_WEIGHTS: dict[str, int] = {
    config.BUDGET_SALON_SEARCH: 5,
    config.BUDGET_API_GENERAL: 3,
    config.BUDGET_DASHBOARD: 2,
    config.BUDGET_TICKET_CREATE: 1,
}


def weighted_groups() -> list[str]:
    """Liste plate de groupes répétés selon leur poids (tirage uniforme dessus)."""

    plan: list[str] = []
    for group, weight in SCENARIO_WEIGHTS.items():
        plan.extend([group] * weight)
    return plan


__all__ = [
    "SalonFixture",
    "SeedContext",
    "TimedResponse",
    "TimedHttp",
    "ScenarioSample",
    "run_salon_search",
    "run_ticket_create",
    "run_manager_dashboard",
    "run_api_general",
    "SCENARIOS",
    "SCENARIO_WEIGHTS",
    "weighted_groups",
]
