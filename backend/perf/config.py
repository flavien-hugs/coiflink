"""Paramètres de charge & **budgets §12.1** — fichier unique, versionné, révisable.

Ce module est **pur** (stdlib uniquement) : aucun import applicatif, aucun I/O, aucun
besoin de l'extra `perf`. Il est donc importable dans le *test gate* ADW et couvrable
par des tests unitaires **sans** exécuter la moindre charge.

Toutes les valeurs sont des **hypothèses documentées et révisables** (voir
`Risks & Open Questions` de la spec), **pas** des SLA contractuels. Le PRD §12.1 fige
les **seuils de temps** ; il ne définit **ni** la « charge nominale » **ni** le
percentile de décision — ce sont les paramètres figés ici, à confirmer avec le
mainteneur.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ─── Budgets §12.1 (source de vérité : PRD §12.1) ─────────────────────────────
#
# Un seuil de temps de réponse (en **millisecondes**) par **groupe de budget**. Le
# groupe est l'unité de mesure du rapport : une route (ou un agrégat de routes) est
# rattachée à exactement un groupe. Les quatre groupes couvrent les quatre budgets
# §12.1 (cf. tableau de la spec).

BUDGET_SALON_SEARCH = "salon_search"
BUDGET_TICKET_CREATE = "ticket_create"
BUDGET_DASHBOARD = "dashboard"
BUDGET_API_GENERAL = "api_general"

#: Budgets §12.1 par groupe, en millisecondes. **Ne pas** modifier à la baisse pour
#: « faire passer » un run : la suite compare au budget, elle ne le redéfinit pas.
BUDGETS_MS: dict[str, int] = {
    BUDGET_SALON_SEARCH: 2000,     # Recherche salon    — §12.1 « < 2 s »
    BUDGET_TICKET_CREATE: 3000,    # Émission de ticket — §12.1 « < 3 s »
    BUDGET_DASHBOARD: 3000,        # Dashboard gérant   — §12.1 « < 3 s »
    BUDGET_API_GENERAL: 3000,      # API générale       — §12.1 « < 3 s »
}

#: Libellé humain de chaque groupe (rapport lisible). Aucune PII.
BUDGET_LABELS: dict[str, str] = {
    BUDGET_SALON_SEARCH: "Recherche salon (GET /catalog/salons)",
    BUDGET_TICKET_CREATE: "Émission d'un ticket walk-in (POST /salons/{id}/queue/tickets)",
    BUDGET_DASHBOARD: "Dashboard gérant (4 lectures agrégées)",
    BUDGET_API_GENERAL: "API générale (échantillon de lectures protégées)",
}

# ─── Métrique de décision ─────────────────────────────────────────────────────

#: Percentile **de décision** : le budget est comparé au p95 serveur (régime établi).
DECISION_PERCENTILE = 95

#: Percentile **de surveillance** : rapporté à titre indicatif, ne décide pas.
SURVEILLANCE_PERCENTILE = 99

#: Marge d'alerte : un run est **WARN** (dérive) dès que la latence dépasse
#: `budget * ALERT_MARGIN` sans encore dépasser le budget. `1.0` désactiverait
#: l'alerte (WARN ne se déclencherait qu'au budget, indistinct de PASS).
ALERT_MARGIN = 0.8


def alert_threshold_ms(budget_ms: int, margin: float = ALERT_MARGIN) -> float:
    """Seuil d'alerte (informatif) en dessous du budget dur. Voir `report.classify`."""

    return budget_ms * margin


# ─── Charge nominale (hypothèse MVP/pilote — révisable) ───────────────────────


@dataclass(frozen=True)
class LoadProfile:
    """Modèle de **charge nominale** — volontairement modeste (MVP mono-ville).

    Documenté comme **hypothèse**, pas comme SLA. La fenêtre de `warmup_s` est
    **exclue** du calcul des percentiles (montée du pool de connexions, caches
    SQLAlchemy) : seul le **régime établi** (`steady_state_s`) décide.
    """

    users: int = 20            # utilisateurs virtuels concurrents
    spawn_rate: float = 5.0    # utilisateurs démarrés par seconde
    warmup_s: float = 10.0     # fenêtre de chauffe exclue de la mesure
    steady_state_s: float = 60.0  # palier mesuré

    @property
    def total_duration_s(self) -> float:
        """Durée totale d'un run (chauffe + palier), hors seed/teardown."""

        return self.warmup_s + self.steady_state_s


def load_profile_from_env(env: dict[str, str] | None = None) -> LoadProfile:
    """Construit un `LoadProfile` en surchargeant les défauts par l'environnement.

    Variables (toutes optionnelles) : `PERF_USERS`, `PERF_SPAWN_RATE`,
    `PERF_WARMUP_S`, `PERF_STEADY_STATE_S`. Permet d'alléger un run CI sans éditer
    le code. Une valeur illisible retombe silencieusement sur le défaut.
    """

    src = os.environ if env is None else env
    base = LoadProfile()

    def _num(name: str, current: float) -> float:
        raw = src.get(name, "").strip()
        if not raw:
            return current
        try:
            return float(raw)
        except ValueError:
            return current

    return LoadProfile(
        users=int(_num("PERF_USERS", base.users)),
        spawn_rate=_num("PERF_SPAWN_RATE", base.spawn_rate),
        warmup_s=_num("PERF_WARMUP_S", base.warmup_s),
        steady_state_s=_num("PERF_STEADY_STATE_S", base.steady_state_s),
    )


# ─── Volumétrie du jeu de données représentatif (seed) ────────────────────────


@dataclass(frozen=True)
class DatasetProfile:
    """Volume **représentatif MVP** du jeu de données de perf (révisable).

    Délibérément modeste pour garder un seed borné et rapide, tout en produisant des
    agrégats **non triviaux** (la « garde de coût §12.1 » des stats à l'épreuve).
    """

    salons: int = 10
    services_per_salon: int = 6
    hairdressers_per_salon: int = 3
    clients: int = 100
    completed_tickets: int = 200  # tickets `done` + paiement associé
    token_clients: int = 20       # clients pour lesquels un jeton est pré-émis


def dataset_profile_from_env(env: dict[str, str] | None = None) -> DatasetProfile:
    """Surcharge la volumétrie par l'environnement (`PERF_SALONS`, `PERF_CLIENTS`, …)."""

    src = os.environ if env is None else env
    base = DatasetProfile()

    def _int(name: str, current: int) -> int:
        raw = src.get(name, "").strip()
        if not raw:
            return current
        try:
            return int(raw)
        except ValueError:
            return current

    return DatasetProfile(
        salons=_int("PERF_SALONS", base.salons),
        services_per_salon=_int("PERF_SERVICES_PER_SALON", base.services_per_salon),
        hairdressers_per_salon=_int("PERF_HAIRDRESSERS_PER_SALON", base.hairdressers_per_salon),
        clients=_int("PERF_CLIENTS", base.clients),
        completed_tickets=_int("PERF_COMPLETED_TICKETS", base.completed_tickets),
        token_clients=_int("PERF_TOKEN_CLIENTS", base.token_clients),
    )


# ─── Données de test : plage de téléphones réservée & secret JWT de test ──────
#
# Plage **réservée** aux tests de perf, **distincte** de toutes les plages e2e déjà
# prises (grep obligatoire — cf. spec). Vérifié libre à l'implémentation : aucun
# `*_e2e.py` n'utilise le préfixe `+225059990`. Tout le jeu de données de perf est
# borné à cette plage → **nettoyage FK-safe** ciblé (cf. `seed._wipe_perf_data`).

RESERVED_PHONE_PREFIX = "+225059990"

#: Mot de passe **de test** partagé par les comptes seedés (non secret, non PII).
SEED_PASSWORD = "perf-load-suite-seed-password-2026"

#: Nom de variable d'environnement portant le **secret JWT de test** du serveur local
#: démarré par `run.py`. **Jamais** le `JWT_SECRET` de production. Sur une cible
#: externe (`PERF_TARGET_URL`), le serveur a déjà son propre secret : les jetons de
#: charge sont obtenus par **login HTTP réel**, ce secret local n'est alors pas utilisé.
JWT_SECRET_ENV = "JWT_SECRET"

#: Secret JWT **de test** par défaut du serveur local de perf. Local, jetable, non
#: destiné à la production (documenté). `run.py` ne l'utilise que pour un uvicorn local.
DEFAULT_TEST_JWT_SECRET = "perf-load-suite-local-only-jwt-secret-not-for-production"


def local_phone(index: int) -> str:
    """Numéro **local** déterministe dans la plage réservée (10 chiffres).

    `+225` + ce local → E.164 commençant par `RESERVED_PHONE_PREFIX`. La plage
    `059990` + 4 chiffres offre 10 000 numéros — largement au-delà des besoins du seed.
    """

    if not 0 <= index <= 9999:
        raise ValueError("index de téléphone hors de la plage réservée (0..9999).")
    return f"059990{index:04d}"


__all__ = [
    "BUDGET_SALON_SEARCH",
    "BUDGET_TICKET_CREATE",
    "BUDGET_DASHBOARD",
    "BUDGET_API_GENERAL",
    "BUDGETS_MS",
    "BUDGET_LABELS",
    "DECISION_PERCENTILE",
    "SURVEILLANCE_PERCENTILE",
    "ALERT_MARGIN",
    "alert_threshold_ms",
    "LoadProfile",
    "load_profile_from_env",
    "DatasetProfile",
    "dataset_profile_from_env",
    "RESERVED_PHONE_PREFIX",
    "SEED_PASSWORD",
    "JWT_SECRET_ENV",
    "DEFAULT_TEST_JWT_SECRET",
    "local_phone",
]
