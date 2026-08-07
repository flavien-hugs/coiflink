# `perf/` — tests de charge des endpoints critiques (budgets PRD §12.1, issue #52)

Harnais de **test de charge** qui exerce les endpoints critiques du **PRD §12.1** contre
un **serveur réel** (uvicorn + PostgreSQL 16 peuplée d'un jeu représentatif), mesure les
latences (p50/p95/p99, débit, taux d'erreur) et les **confronte aux budgets §12.1**.

> #52 **mesure**, il ne modifie **aucun** code de production, n'ajoute **aucune** route,
> **aucun** index, **aucune** migration, **aucun** cache. Si une cible est dépassée, on
> **documente le dépassement** (rapport + issue d'optimisation dédiée) — on ne corrige pas
> ici (voir [« En cas de FAIL »](#en-cas-de-fail)).

Ce répertoire vit **hors** du package `coiflink_api` et **hors** de `backend/tests/` : il
n'est **pas** collecté par `pytest`, **pas** dans le *test gate* ADW, **pas** dans la CI
applicative requise, et **pas** dans l'image Docker de production.

## Budgets §12.1 (source de vérité : PRD)

| Groupe | Endpoint(s) | Budget |
| --- | --- | ---: |
| `salon_search` | `GET /catalog/salons` (`q`/`city`/`commune`/pagination) | **< 2 s** |
| `appointment_create` | fiche → disponibilités → `POST /salons/{id}/appointments` | **< 3 s** |
| `dashboard` | agrégat des 5 lectures gérant (`daily-summary`, `revenue/summary`, `service-demand`, `active-clients`, `hairdresser-performance`) | **< 3 s** |
| `api_general` | échantillon de lectures protégées (`/appointments/history`, `/me/receipts`, `/salons/{id}/appointments`, `/salons/{id}/payments`) | **< 3 s** |

Métrique de **décision** : **p95** serveur en **régime établi** (warm-up exclu) ; **p99**
rapporté en **surveillance**. Un seuil « informatif » plus strict (80 % du budget) signale
une **dérive** (`WARN`) avant le dépassement franc (`FAIL`). Ces paramètres — et le modèle
de **charge nominale** — sont des **hypothèses documentées et révisables**
(`config.py`), pas des SLA : le PRD §12.1 ne fige que les seuils de temps.

## Prérequis

```bash
cd backend
pip install -e ".[perf]"     # extra distinct de dev : httpx + locust
```

Une **PostgreSQL 16** joignable (locale ou service CI). En local, l'instance
`coiflink-e2e-pg` sur le port `55433` convient ; `docker compose -f deploy/docker-compose.yml up`
monte aussi un serveur réel complet.

## Exécution

### Serveur local (mode par défaut)

`run.py` orchestre tout : `alembic upgrade head` → seed → **uvicorn local** (secret JWT
**de test**, jamais de prod) → charge → rapport → teardown FK-safe.

```bash
cd backend
DATABASE_URL=postgresql://coif:pw@localhost:55433/coif python -m perf.run
```

Sans `DATABASE_URL` ni `PERF_TARGET_URL`, `run.py` **skippe proprement** (code 0).

### Cible externe (staging, verdict de référence)

Pour un verdict §12.1 **fiable**, viser un environnement **stable** (staging Railway,
matériel proche prod), pas un runner CI partagé :

```bash
cd backend
PERF_TARGET_URL=https://staging.example \
PERF_DB_URL=postgresql://…            \  # optionnel : nettoyage FK-safe côté staging
python -m perf.run
```

Respecter la **résidence** `europe-west4` (ADR-0011) : n'exfiltrer aucune donnée vers un
tiers ; n'utiliser que des **comptes/données synthétiques** seedés (plage réservée).

### Moteur alternatif Locust (opt-in)

`run.py` est le moteur **par défaut** et le seul à émettre la table de verdict §12.1.
Locust (UI web, paliers longs) pilote les **mêmes** scénarios :

```bash
cd backend
python -m perf.run --seed-only          # prépare la cible (serveur local ou staging)
locust -f perf/locustfile.py --headless -u 20 -r 5 -t 70s --host http://127.0.0.1:8000
python -m perf.run --teardown-only      # nettoyage FK-safe de la plage réservée
```

### Paramètres (variables d'environnement)

| Variable | Rôle | Défaut |
| --- | --- | ---: |
| `PERF_USERS` | utilisateurs virtuels concurrents | 20 |
| `PERF_SPAWN_RATE` | VUs démarrés par seconde | 5 |
| `PERF_WARMUP_S` | fenêtre de chauffe (exclue) | 10 |
| `PERF_STEADY_STATE_S` | palier mesuré | 60 |
| `PERF_SALONS` / `PERF_CLIENTS` / … | volumétrie du seed | voir `config.py` |
| `PERF_TARGET_URL` | cible externe (sinon uvicorn local) | — |
| `PERF_DB_URL` | base de nettoyage (défaut : `DATABASE_URL`) | `DATABASE_URL` |

Drapeaux `run.py` : `--strict` (échoue en FAIL, pour un env de référence), `--no-migrate`,
`--skip-seed`, `--seed-only`, `--teardown-only`.

## Le rapport

Écrit dans `perf/reports/` (`perf-report.json`, `.csv`, `.md`) et résumé sur stdout. Par
groupe : `p50/p95/p99`, débit (req/s), taux d'erreur, et un **verdict** `mesuré (p95) vs
budget §12.1` :

- **PASS** — p95 ≤ 80 % du budget ;
- **WARN** — 80 % du budget < p95 ≤ budget (dérive à surveiller) ;
- **FAIL** — p95 > budget (dépassement §12.1).

Par construction, le rapport **agrège et compte** : il ne contient **aucune** PII (numéro,
nom, jeton, e-mail, montant nominatif). `report.assert_no_pii` verrouille cet invariant
sur chaque sortie sérialisée avant écriture (cohérent avec `tests/test_secrets_policy.py`).

## En cas de FAIL

Le harnais est **informatif** : un `WARN`/`FAIL` **n'échoue pas** le job (sauf `--strict`
sur un environnement de référence). En cas de `FAIL` confirmé sur staging :

1. **documenter** le dépassement (le rapport CSV/JSON est l'artefact) ;
2. **ouvrir une issue d'optimisation dédiée** (index manquant, N+1, pagination, cache Redis
   différé M5…) ;
3. **ne pas** modifier le code de production dans #52 — l'optimisation est un travail séparé.

## Structure

| Fichier | Rôle | Dépend de l'extra `perf` ? |
| --- | --- | :---: |
| `config.py` | budgets §12.1, percentile, charge nominale, plage réservée | non (stdlib pur) |
| `report.py` | percentiles, verdict PASS/WARN/FAIL, sérialisation, garde anti-PII | non (stdlib pur) |
| `scenarios.py` | scénarios par groupe (source **unique**, agnostique du moteur) | non (stdlib pur) |
| `seed.py` | peuplement/teardown FK-safe via l'API réelle | oui (`httpx`) |
| `driver.py` | pilote de charge intégré (httpx + threads) | oui (`httpx`) |
| `run.py` | orchestration (migrate → seed → uvicorn/URL → charge → rapport → teardown) | oui (`httpx`) |
| `locustfile.py` | moteur alternatif Locust | oui (`locust`) |

`config.py`, `report.py` et `scenarios.py` sont **purs** (stdlib) : leur logique
**déterministe** (budgets, verdict, rapport, mix de trafic) est couverte par des tests
unitaires rapides sous `backend/tests/`, sans exécuter la moindre charge.
