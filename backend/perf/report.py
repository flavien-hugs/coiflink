"""Statistiques de latence, **verdict vs budget §12.1** et sérialisation du rapport.

Module **pur** (stdlib) : aucune dépendance applicative, aucun I/O réseau, aucun
besoin de l'extra `perf`. Toute la logique **déterministe** de la suite vit ici —
percentiles, classement PASS/WARN/FAIL, formats CSV/JSON/Markdown, garde anti-PII —
et est donc couvrable par des tests unitaires rapides **sans** exécuter de charge.

Invariant §11.3/§11.4 : le rapport **agrège et compte**, il n'**affiche jamais** de
donnée personnelle. Les seules chaînes émises sont des **libellés de groupe** et des
**gabarits de route** (`/salons/{salon_id}/queue/tickets`) — jamais un numéro, un
jeton, un e-mail, un nom ou un montant nominatif. `assert_no_pii` verrouille cet
invariant sur la sortie sérialisée.
"""

from __future__ import annotations

import csv
import enum
import io
import json
import math
from dataclasses import dataclass, field

from . import config


# ─── Percentiles (déterministes, nearest-rank) ────────────────────────────────


def percentile(samples: list[float], p: float) -> float:
    """Percentile `p` (0..100) d'un échantillon, méthode **nearest-rank**.

    Déterministe et sans dépendance : `rank = ceil(p/100 * n)`, borné à `[1, n]`, on
    renvoie l'élément trié à `rank - 1`. Un échantillon vide renvoie `0.0`.
    """

    if not samples:
        return 0.0
    if not 0 <= p <= 100:
        raise ValueError("percentile hors de [0, 100].")
    ordered = sorted(samples)
    if p <= 0:
        return ordered[0]
    rank = math.ceil((p / 100.0) * len(ordered))
    rank = min(max(rank, 1), len(ordered))
    return ordered[rank - 1]


# ─── Verdict vs budget ────────────────────────────────────────────────────────


class Verdict(str, enum.Enum):
    """Résultat d'un groupe confronté à son budget §12.1."""

    PASS = "PASS"   # sous le seuil d'alerte
    WARN = "WARN"   # entre le seuil d'alerte et le budget (dérive à surveiller)
    FAIL = "FAIL"   # au-dessus du budget §12.1

    def __str__(self) -> str:  # rapport lisible
        return self.value


def classify(
    measured_ms: float, budget_ms: int, *, alert_margin: float = config.ALERT_MARGIN
) -> Verdict:
    """Classe une latence mesurée (le percentile de décision) contre son budget.

    - `FAIL` si `measured > budget` (dépassement franc du budget §12.1) ;
    - `WARN` si `alert < measured <= budget` (dérive : au-dessus de la marge d'alerte
      sans dépasser le budget) ;
    - `PASS` sinon (`measured <= alert`).

    Les bornes sont **inclusives vers le bas** : à exactement le budget → `WARN`
    (dans la bande d'alerte, mais **pas** `FAIL`) ; à exactement le seuil d'alerte
    → `PASS`.
    """

    alert = config.alert_threshold_ms(budget_ms, alert_margin)
    if measured_ms > budget_ms:
        return Verdict.FAIL
    if measured_ms > alert:
        return Verdict.WARN
    return Verdict.PASS


# ─── Résultat par groupe & rapport agrégé ─────────────────────────────────────


@dataclass(frozen=True)
class EndpointResult:
    """Mesures agrégées d'un **groupe de budget**, prêtes pour le verdict/rapport.

    `latencies_ms` est l'échantillon du **régime établi** (warm-up déjà exclu par le
    pilote). Les percentiles sont dérivés à la construction pour un rapport stable.
    """

    group: str
    route_label: str          # gabarit de route (aucune PII)
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0
    duration_s: float = 0.0

    @property
    def count(self) -> int:
        return len(self.latencies_ms)

    @property
    def requests_total(self) -> int:
        return self.count + self.errors

    @property
    def p50(self) -> float:
        return percentile(self.latencies_ms, 50)

    @property
    def p95(self) -> float:
        return percentile(self.latencies_ms, config.DECISION_PERCENTILE)

    @property
    def p99(self) -> float:
        return percentile(self.latencies_ms, config.SURVEILLANCE_PERCENTILE)

    @property
    def throughput_rps(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        return self.count / self.duration_s

    @property
    def error_rate(self) -> float:
        total = self.requests_total
        return (self.errors / total) if total else 0.0

    @property
    def budget_ms(self) -> int:
        return config.BUDGETS_MS[self.group]

    @property
    def verdict(self) -> Verdict:
        """Verdict sur le **percentile de décision** (p95) vs budget §12.1."""

        return classify(self.p95, self.budget_ms)

    def as_row(self) -> dict[str, object]:
        """Ligne plate (CSV/JSON) — **uniquement** libellés, gabarits et nombres."""

        return {
            "group": self.group,
            "route": self.route_label,
            "budget_ms": self.budget_ms,
            "requests": self.count,
            "errors": self.errors,
            "error_rate": round(self.error_rate, 4),
            "p50_ms": round(self.p50, 1),
            "p95_ms": round(self.p95, 1),
            "p99_ms": round(self.p99, 1),
            "throughput_rps": round(self.throughput_rps, 2),
            "verdict": str(self.verdict),
        }


@dataclass(frozen=True)
class PerfReport:
    """Rapport complet : métadonnées non nominatives + résultats par groupe."""

    results: list[EndpointResult]
    target: str = ""            # URL cible (host:port) — pas de PII
    load_users: int = 0
    steady_state_s: float = 0.0
    percentile: int = config.DECISION_PERCENTILE
    generated_at: str = ""      # horodatage ISO 8601 (non nominatif)

    @property
    def overall(self) -> Verdict:
        """Verdict global : `FAIL` si un groupe échoue, sinon `WARN` si dérive, sinon `PASS`."""

        verdicts = {r.verdict for r in self.results}
        if Verdict.FAIL in verdicts:
            return Verdict.FAIL
        if Verdict.WARN in verdicts:
            return Verdict.WARN
        return Verdict.PASS

    # ── Sérialisations (toutes sans PII par construction) ────────────────────

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "generated_at": self.generated_at,
            "load_users": self.load_users,
            "steady_state_s": self.steady_state_s,
            "decision_percentile": self.percentile,
            "overall_verdict": str(self.overall),
            "budgets_source": "PRD §12.1",
            "results": [r.as_row() for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)

    def to_csv(self) -> str:
        buffer = io.StringIO()
        fieldnames = [
            "group",
            "route",
            "budget_ms",
            "requests",
            "errors",
            "error_rate",
            "p50_ms",
            "p95_ms",
            "p99_ms",
            "throughput_rps",
            "verdict",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for result in self.results:
            writer.writerow(result.as_row())
        return buffer.getvalue()

    def to_markdown(self) -> str:
        lines = [
            "# Rapport de charge — endpoints critiques (budgets PRD §12.1)",
            "",
            f"- Cible : `{self.target or 'n/a'}`",
            f"- Généré : {self.generated_at or 'n/a'}",
            f"- Charge : {self.load_users} VUs · palier {self.steady_state_s:g}s "
            f"· décision p{self.percentile}",
            f"- **Verdict global : {self.overall}**",
            "",
            "| Groupe | Route | Budget | Req. | Err. | p50 | p95 | p99 | req/s | Verdict |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
        ]
        for r in self.results:
            row = r.as_row()
            lines.append(
                f"| {row['group']} | `{row['route']}` | {row['budget_ms']} ms | "
                f"{row['requests']} | {row['errors']} | {row['p50_ms']} | "
                f"{row['p95_ms']} | {row['p99_ms']} | {row['throughput_rps']} | "
                f"{row['verdict']} |"
            )
        lines += [
            "",
            "> **Informatif par défaut** : un `WARN`/`FAIL` **n'échoue pas** le job "
            "(sauf `--strict`). En cas de `FAIL`, ouvrir une **issue d'optimisation "
            "dédiée** (index manquant, N+1, pagination, cache Redis M5) — #52 **mesure**, "
            "il ne corrige pas le code de production. Verdict de référence : viser "
            "**staging Railway** (matériel stable) via `PERF_TARGET_URL`.",
        ]
        return "\n".join(lines) + "\n"


# ─── Garde anti-PII (§11.3/§11.4) ─────────────────────────────────────────────

#: Marqueurs de fuite : leur présence dans une sortie de rapport est une régression.
_PII_MARKERS = (
    config.RESERVED_PHONE_PREFIX,  # numéro seedé
    "Bearer ",                     # jeton d'accès
    config.SEED_PASSWORD,          # mot de passe de test
    "access_token",
    "refresh_token",
    "@",                           # e-mail
    "password",
)


def find_pii(serialized: str) -> list[str]:
    """Retourne les marqueurs de PII présents dans une sortie sérialisée (vide = sain)."""

    lowered = serialized.lower()
    hits: list[str] = []
    for marker in _PII_MARKERS:
        if marker.lower() in lowered:
            hits.append(marker)
    return hits


def assert_no_pii(serialized: str) -> None:
    """Lève `AssertionError` si la sortie contient un marqueur de PII (cf. `find_pii`)."""

    hits = find_pii(serialized)
    if hits:
        raise AssertionError(
            f"Fuite de PII dans le rapport de perf : marqueurs {hits!r}. "
            "Le rapport doit agréger/compter, jamais afficher de donnée personnelle (§11.3)."
        )


__all__ = [
    "percentile",
    "Verdict",
    "classify",
    "EndpointResult",
    "PerfReport",
    "find_pii",
    "assert_no_pii",
]
