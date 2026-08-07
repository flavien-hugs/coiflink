"""Harnais de **tests de charge** des endpoints critiques §12.1 (issue #52).

Ce paquet vit **hors** du package applicatif `coiflink_api` et **hors** de
`backend/tests/` (non collecté par `pytest`) : c'est de l'**outillage de test de
performance**, opt-in, isolé de l'image de production et du *test gate* ADW.

Il ne modifie **aucun** code de production : il **mesure** la latence des routes
livrées contre un **serveur réel** (uvicorn) + **PostgreSQL 16** peuplée d'un jeu
de données représentatif, puis **confronte** les percentiles aux budgets §12.1.

Modules :
- `config`    — budgets §12.1, percentile de décision, charge nominale, warm-up
  (paramètres versionnés et révisables). **Pur** (stdlib) : testable sans charge.
- `report`    — statistiques de latence (p50/p95/p99), verdict PASS/WARN/FAIL vs
  budget, sérialisation CSV/JSON/Markdown **sans PII**. **Pur** : testable sans charge.
- `scenarios` — description des requêtes de chaque groupe de budget (source unique
  partagée par le pilote intégré et le `locustfile`).
- `seed`      — peuplement/teardown d'un jeu de données représentatif borné à une
  **plage de téléphones réservée** (nettoyage FK-safe), via l'API réelle (HTTP).
- `driver`    — pilote de charge **intégré** (httpx + threads), sans binaire externe.
- `run`       — orchestration : migrate → seed → uvicorn/URL → charge → rapport →
  teardown.
- `locustfile` — scénarios Locust (moteur **alternatif** opt-in, extra `perf`).

Voir `backend/perf/README.md`.
"""

from __future__ import annotations

__all__: list[str] = []
