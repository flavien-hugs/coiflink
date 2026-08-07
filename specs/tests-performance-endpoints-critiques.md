# Tests de performance — charge sur les endpoints critiques (budgets §12.1)

> Issue GitHub **#52** — `Should` · Effort `M` · labels `tests` · Jalon **M6** (Sprint 6, durcissement).
> Dépend des jalons **M3** (rendez-vous : réservation, statuts, planning — #21–#27) et **M4** (clients,
> encaissement & journal de caisse — #28–#38). Réfère PRD **§12.1** (Performance) et, pour la surface
> testée, **§5** (parcours critiques). Ne dépend d'**aucune** issue de sécurité (#51) : périmètre disjoint.

## Problem Statement

Le PRD fixe au **§12.1** quatre budgets de temps de réponse — *garde-fous non fonctionnels* du produit —
qui n'ont **jamais été mesurés** :

| Budget PRD §12.1 | Cible | Surface backend qui le porte |
| --- | --- | --- |
| Temps de réponse API | **< 3 s** | toute route de `main.app` |
| Chargement du dashboard principal | **< 3 s** | agrégat des lectures du dashboard gérant (`daily-summary`, `revenue/summary`, `active-clients`, `hairdresser-performance`, `service-demand`) |
| Recherche salon | **< 2 s** | `GET /catalog/salons` (catalogue client, #18) |
| Création rendez-vous | **< 3 s** | `POST /salons/{salon_id}/appointments` (#21) |

Aujourd'hui :

- **Aucune infrastructure de test de performance/charge n'existe** dans le dépôt (vérifié : pas de
  `locust`, `k6`, `pytest-benchmark`, ni harnais de mesure de latence sous `backend/`). Les ~une
  soixantaine de routes livrées (M1→M5) n'ont **jamais** été exercées **sous charge**.
- La suite de tests actuelle est **fonctionnelle** : les `*_e2e.py` prouvent la *correction* via
  `TestClient` (transport ASGI **en-processus**, mono-thread), qui **ne mesure ni le temps de réponse
  réel** (pas de serveur ASGI, pas de réseau, pas de pool de connexions sous contention) **ni le
  comportement sous concurrence**. Ils sont donc **inaptes** à valider un budget §12.1.
- Les critères d'acceptation de #52 exigent explicitement : *« Temps de réponse dans les budgets du §12
  sous charge nominale »*. Or ni **« charge nominale »** ni le **percentile** de mesure ne sont définis
  dans le PRD — ce sont des **paramètres à figer** (voir *Risks & Open Questions*).

L'issue #52 comble ce manque : une **suite de tests de charge** dédiée qui exerce les endpoints critiques
du §12.1 contre un **serveur réel** (uvicorn + PostgreSQL 16) sur un **jeu de données représentatif**,
mesure les latences (p50/p95/p99) et les **compare aux budgets §12.1** — **sans introduire de
fonctionnalité ni modifier le code de production**.

## Goals

- **Définir et documenter** un modèle de **charge nominale** (nombre d'utilisateurs virtuels concurrents,
  débit cible, montée en charge, durée de palier) cohérent avec l'échelle MVP/pilote, et le **percentile
  de décision** (recommandé : **p95** cible, **p99** en surveillance) — paramètres explicites, versionnés,
  révisables.
- Fournir des **scénarios de charge** reproductibles couvrant les **quatre** budgets §12.1 :
  1. **Recherche salon** — `GET /catalog/salons` (avec `q`/`city`/`commune`/pagination) → **< 2 s**.
  2. **Création de rendez-vous** — `POST /salons/{salon_id}/appointments` (chemin réservation #21, y
     compris la consultation de disponibilités qui la précède) → **< 3 s**.
  3. **Dashboard gérant** — les lectures qui composent le tableau de bord (RDV du jour #39, CA #40,
     clients actifs #42, performance coiffeurs #43, prestations demandées #41) → agrégat **< 3 s**.
  4. **API générale** — un échantillon représentatif de routes de lecture protégées → **< 3 s**.
- Exercer ces scénarios contre un **serveur réel** (uvicorn) et une **PostgreSQL 16** peuplée d'un **jeu
  de données représentatif** (salons, prestations, clients, RDV, paiements) — pas via `TestClient`.
- Produire un **rapport de latences** (p50/p95/p99, débit, taux d'erreur) par endpoint, **confronté aux
  budgets §12.1**, exploitable en artefact CI (format lisible + machine : CSV/JSON).
- Intégrer la suite au dépôt de façon **non bloquante et déterministe d'exécution** : un job/`Makefile`
  **opt-in** (déclenchement manuel `workflow_dispatch` et/ou planifié), **hors** du *test gate* ADW et
  **hors** des status checks requis (les mesures de perf sont sensibles à l'environnement — voir *Risks*).
- **Respecter les invariants §11** : données de test **synthétiques**, secret JWT **de test**, **jamais**
  de secret ni de PII dans les logs, la sortie ou les artefacts de perf ; nettoyage FK-safe.

## Non-Goals

- **Ne pas implémenter de fonctionnalité, ni d'optimisation.** #52 **mesure** ; il ne modifie **aucun**
  code de production, n'ajoute **aucune** route, **aucun** index, **aucune** migration, **aucun** cache.
  Si une cible §12.1 est dépassée, #52 **documente le dépassement** (et éventuellement ouvre une issue
  d'optimisation dédiée) — il ne corrige pas (voir *Risks & Open Questions*).
- **Ne pas transformer les mesures de perf en gate de merge bloquant.** La variabilité des runners
  partagés rendrait un seuil dur **instable** (flaky). La suite est **informative** par défaut ; la
  *décision* d'en faire un gate (et sur quel environnement de référence) est une question ouverte.
- **Pas de perf frontend** : le « chargement du dashboard » et la « recherche salon » du §12.3/§12.1 au
  sens **UX bout-en-bout** incluent le rendu web/mobile (Next.js / Flutter) — **hors périmètre backend**.
  #52 mesure la **part API** que porte le backend ; la part IU relève d'un outillage distinct (Lighthouse
  / profilage Flutter), non couvert ici.
- **Pas de tests de sécurité/charge d'attaque** (brute-force, DoS) : le brute-force `POST /auth/login`
  relève de **#51** ; #52 n'exécute **aucun** scénario destructif ni de saturation malveillante.
- **Pas de tests de scalabilité §12.4** (multi-villes, multi-pays, montée en charge extrême) : hors MVP.
- **Pas de benchmark de micro-fonctions** (profilage CPU d'une requête SQL isolée) : #52 mesure la
  **latence d'endpoint bout-en-bout côté serveur sous charge**, pas le coût unitaire d'une fonction pure.
- **Pas de tests de disponibilité §12.2** (uptime, sauvegardes, alerting) : hors périmètre.

## Relevant Repository Context

Stack **figée par ADR** (aucune décision de toolchain applicatif à trancher pour la surface testée) :
backend **FastAPI** (Python ≥ 3.12, [ADR-0003](../docs/adr/0003-backend-fastapi.md)), **PostgreSQL 16**
([ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md) / [ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)),
**architecture hexagonale** ([ADR-0008](../docs/adr/0008-architecture-hexagonale.md)). Hébergement
**Railway**, région `europe-west4` ([ADR-0011](../docs/adr/0011-deploiement-environnements-secrets.md)) —
l'environnement **staging** reproductible y est décrit (`docs/environnements-et-secrets.md`).

> **Choix de l'outillage de charge — décision ouverte (voir *Risks*).** Aucun outil de charge n'est encore
> retenu dans le dépôt. Le PRD ne fige que la stack *applicative* ; l'outil de **test de charge** est un
> choix à confirmer. La recommandation par défaut de cette spec est **Locust** (Python, `pip`-installable,
> scénarios en code, s'aligne sur `pytest`/`ruff` déjà présents), avec **k6** (Grafana) en alternative si
> l'on préfère un outil dédié hors chaîne Python. Ce choix est **isolé dans une dépendance de dev optionnelle**
> et **n'entre ni dans l'image de production ni dans les status checks requis**.

### Surface testée — endpoints critiques §12.1 (livrés, vérifiés dans le code)

Tous montés sur `coiflink_api.main.app`, protégés par la dépendance globale `require_authenticated`
(deny-by-default, [ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) sauf les routes
publiques du catalogue.

| Budget §12.1 | Endpoint(s) | Router | Permission / accès |
| --- | --- | --- | --- |
| Recherche salon **< 2 s** | `GET /catalog/salons` (`q`, `city`, `commune`, `limit`, `offset`) | `adapters/inbound/catalog.py` | **public** (catalogue client #18) |
| Création RDV **< 3 s** | `GET /catalog/salons/{id}` (fiche, #19) → `GET /catalog/salons/{id}/availability` (disponibilités, #21) → `POST /salons/{id}/appointments` (#21) | `catalog.py`, `appointments.py` | réservation client (#21, #23) |
| Dashboard **< 3 s** | `GET /salons/{id}/appointments/daily-summary` (#39), `GET /salons/{id}/revenue/summary` (#40), `GET /salons/{id}/active-clients` (#42), `GET /salons/{id}/hairdresser-performance` (#43), `GET /salons/{id}/service-demand` (#41) | `appointments.py`, `stats.py` | `require_salon_scope` (gérant, portée §11.2) |
| API générale **< 3 s** | échantillon lecture : `GET /appointments/history` (#30), `GET /me/receipts` (#38), `GET /salons/{id}/appointments` (#25), `GET /salons/{id}/payments` (#34/#35) | `appointments.py`, `receipts.py`, `payments.py` | selon rôle |

Ces endpoints **calculent en base** (`COUNT`/`SUM`, agrégations) — la « garde de coût §12.1 » est déjà
citée dans le README pour `GET /admin/kpis` et les stats : #52 **vérifie** que cette garde tient **sous
charge**, sur des volumes représentatifs.

### Conventions de test réutilisables (patrons à suivre)

- **e2e backend** (`docs/strategie-de-tests.md` §5) : fichiers `backend/tests/test_*_e2e.py`,
  `@pytest.mark.skipif(not DATABASE_URL, …)`, **plage de téléphones réservée**, **nettoyage FK-safe**
  (`notifications`/`campaigns` **avant** `appointments`/`payments`/`cash_journal`/`salons`/`users` — FK
  `RESTRICT`, mémoire *notifications-fk-restrict-cleanup*), **JWT de test factice** injecté sur `app.state`
  (jamais un vrai secret), argent en chaîne `NUMERIC(12,2)`, **jamais** journaliser jeton/mot de
  passe/téléphone. Le patron de peuplement + auth réelle est dans `test_critical_journeys_e2e.py` et
  `test_appointment_notification_e2e.py`.
- **Plages de téléphones déjà prises** (`+225068999`, `+225069998`, `+225070000`, `+225071999`…
  `+225089993`) : #52 doit **grep** et **réserver une plage libre distincte** (candidat : `+225059990x` —
  **à confirmer libre à l'implémentation**).
- **CI backend** (`.github/workflows/ci.yml`, job `backend`) : `runs-on: ubuntu-latest`, service
  `postgres:16`, `DATABASE_URL` défini au niveau du job, `alembic upgrade head` **avant** `pytest`. Ce job
  exécute déjà les `*_e2e.py` — mais **ne convient pas** à un test de charge (le budget de temps du runner
  et sa variabilité). #52 introduit un **job distinct**, opt-in, non requis.
- **Runner local recommandé pour l'itération** : instance PostgreSQL locale `coiflink-e2e-pg` sur le port
  `55433` (mémoire *local-e2e-postgres*) ; `docker compose -f deploy/docker-compose.yml up` monte
  backend + web + PostgreSQL 16 + Redis 7 pour un serveur réel local.

### Ce qui n'existe pas encore (à créer par #52)

- Aucun outil ni script de charge (`locustfile.py` / scénarios k6).
- Aucun **jeu de données de perf** (seed) représentatif ni son script de peuplement/nettoyage.
- Aucun **job CI de perf** ni cible `Makefile`/script d'exécution.
- Aucune **documentation** des budgets §12.1 comme cibles opérationnelles (seul le PRD les liste).

## Proposed Implementation

Ajouter un **harnais de test de charge** isolé sous `backend/perf/` (répertoire **hors** du package
`coiflink_api` et **hors** de `backend/tests/` collecté par `pytest`), piloté par un outil de charge
**opt-in**, avec un **seed** représentatif et un **rapport** confronté aux budgets §12.1. Cinq briques :

### 1. Paramètres de charge & budgets — `backend/perf/config.py` (ou `perf.toml`)

Fichier **unique, versionné, commenté** qui fige les paramètres (tous **révisables**, valeurs de départ à
**confirmer** avec le mainteneur — voir *Risks*) :

- **Budgets §12.1** en une table déclarative `{endpoint_group: seuil_ms}` :
  `salon_search = 2000`, `appointment_create = 3000`, `dashboard = 3000`, `api_general = 3000`.
- **Métrique de décision** : `percentile = 95` (p95), **p99 rapporté en surveillance**. Le budget est
  comparé au **percentile serveur** de la latence, mesuré en **régime établi** (après une **fenêtre de
  warm-up** excluant les premières requêtes : montée du pool de connexions, caches SQLAlchemy).
- **Charge nominale** (MVP/pilote — **à confirmer**) : p. ex. `users = 20` utilisateurs virtuels
  concurrents, `spawn_rate = 5/s`, `steady_state = 60 s`, `warmup = 10 s`. Volumétrie **délibérément
  modeste** (le MVP est un pilote mono-ville) ; documentée comme **hypothèse** et non comme SLA contractuel.
- **Marge d'alerte** : un seuil « informatif » plus strict (p. ex. 80 % du budget) pour signaler une
  **dérive** avant le dépassement franc, sans faire échouer.

### 2. Jeu de données représentatif — `backend/perf/seed.py`

Peupler une base **dédiée** (jamais la prod) avec un volume **représentatif MVP** via l'API réelle
(cohérence garantie) ou par insertion directe SQL bornée (plus rapide pour le volume), **à trancher** :

- **N salons** actifs (p. ex. 20), chacun avec **prestations** (5–10), **horaires**, **coiffeurs** (2–5).
- **Clients** (p. ex. 200) répartis, avec **historique** de RDV (`PENDING`/`CONFIRMED`/`COMPLETED`/
  `CANCELLED`) et **paiements**/`cash_journal` associés — pour que `daily-summary`, `revenue/summary`,
  `active-clients`, `hairdresser-performance` renvoient des agrégats **non triviaux** (volume qui met la
  garde de coût §12.1 à l'épreuve).
- **Plage de téléphones réservée** distincte (grep obligatoire) ; **toutes** les données de perf sont
  bornées par cette plage pour un **nettoyage FK-safe** (patron `_wipe_test_data`).
- **Idempotent** : `seed` puis `teardown` réutilisables ; le seed ne journalise **aucune** PII (compter,
  pas afficher).
- **Jetons d'accès réels** pré-émis pour les rôles nécessaires (gérant, client, coiffeur) via un
  `JwtTokenService` **de test** (secret local sur `app.state` / variable d'environnement de test),
  **jamais** un secret de prod — fournis aux scénarios de charge sans jamais être journalisés.

### 3. Scénarios de charge — `backend/perf/locustfile.py` (recommandé) *ou* `backend/perf/k6/*.js`

Un scénario par **groupe de budget** (poids relatifs représentatifs d'un trafic réaliste : beaucoup de
lectures catalogue, moins de créations de RDV) :

- **`SalonSearchUser`** — `GET /catalog/salons` avec variation de `q`/`city`/`commune`/pagination (données du
  seed). Cible **< 2 s** p95.
- **`BookingUser`** — enchaîne fiche salon (`GET /catalog/salons/{id}`) → consultation des disponibilités
  (`GET /catalog/salons/{id}/availability`) → `POST /salons/{id}/appointments` sur un créneau **futur**
  libre (déterminisme : pas de collision avec le seed).
  Cible **< 3 s** p95 sur la **création** (mesurer l'étape POST isolément, et le parcours complet).
  ⚠ La création **écrit** en base et **émet des notifications** (#45/#46/#47) : borner à la plage réservée
  et **nettoyer** après le run (les lignes `notifications`/`appointments` créées par la charge).
- **`ManagerDashboardUser`** — appelle **en séquence** les 5 lectures du dashboard pour un salon du seed ;
  mesurer **chaque** appel **et** l'**agrégat** (somme des temps serveur) contre **< 3 s**.
- **`ApiGeneralUser`** — échantillon de lectures protégées (`/appointments/history`, `/me/receipts`,
  `/salons/{id}/appointments`, `/salons/{id}/payments`) avec jetons de rôle appropriés → **< 3 s**.

Chaque requête est **authentifiée** avec un jeton **réel** du bon rôle (respect deny-by-default / portée
§11.2) ; les scénarios **n'exercent que des chemins autorisés** (un 401/403 fausserait la mesure de latence
utile). Les identifiants et jetons proviennent du seed et **ne sont jamais tracés**.

### 4. Exécution & rapport — `backend/perf/run.py` (ou cible `Makefile`/script)

- Point d'entrée unique : (1) vérifie `DATABASE_URL` (skip propre sinon), (2) `alembic upgrade head`,
  (3) `seed`, (4) démarre **uvicorn** sur un port local (serveur **réel**, pas `TestClient`) **ou** cible
  une **URL externe** (`PERF_TARGET_URL`, p. ex. staging Railway) si fournie, (5) lance l'outil de charge
  avec les paramètres du §1, (6) collecte les métriques, (7) `teardown`.
- **Rapport** : par endpoint → p50/p95/p99, débit (req/s), taux d'erreur ; puis une **table de verdict**
  `mesuré vs budget §12.1` (PASS/WARN/FAIL) écrite en **CSV + JSON** (artefact) et résumée en **Markdown**
  lisible. **WARN/FAIL n'échoue pas** le job par défaut (mode informatif) — un drapeau `--strict`
  (opt-in) peut inverser ce comportement pour un environnement de référence stable (staging).
- **Warm-up** exclu du calcul ; **régime établi** seul retenu ; horloge **monotone** côté mesure.

### 5. Intégration CI — job `perf` **opt-in, non requis** (`.github/workflows/`)

- **Nouveau workflow** (p. ex. `.github/workflows/perf.yml`) déclenché par **`workflow_dispatch`** (manuel)
  et/ou **`schedule`** (nocturne) — **jamais** sur chaque PR, **jamais** en status check requis (variabilité
  runner → flaky). Service `postgres:16` (patron du job `backend`), `alembic upgrade head`, seed, run,
  **upload de l'artefact** de rapport. Le job **réussit** même en WARN/FAIL (informatif) sauf `--strict`.
- **Test gate ADW** : **inchangé**. La suite de perf n'y entre **pas** (trop lourde/variable pour la boucle
  `resolve`) ; aucun fichier `test_*.py` collecté par `pytest` n'exécute de charge.
- **Documenter** que la mesure **de référence** (pour un verdict fiable §12.1) doit viser **staging Railway**
  (matériel stable, proche prod) via `PERF_TARGET_URL`, le job CI local restant un **indicateur de dérive**.

> **Réutilisation vs création** : réutiliser les **patrons** e2e (seed via API réelle, plage de téléphones
> réservée, nettoyage FK-safe, JWT de test sur `app.state`) mais **isoler** le harnais hors de `pytest`
> (répertoire `backend/perf/`, dépendance de dev optionnelle) pour ne pas alourdir le gate ni la CI requise.

## Affected Files / Packages / Modules

**Nouveaux fichiers (probables)** — tout sous `backend/perf/` (hors package prod, hors `tests/`) :

- `backend/perf/README.md` — comment lancer, paramètres, interprétation du rapport, cibles §12.1.
- `backend/perf/config.py` (ou `perf.toml`) — budgets §12.1, percentile, charge nominale, warm-up.
- `backend/perf/seed.py` — peuplement/teardown du jeu de données représentatif (plage réservée, FK-safe).
- `backend/perf/locustfile.py` (recommandé) **ou** `backend/perf/k6/*.js` — scénarios par groupe de budget.
- `backend/perf/run.py` — orchestration (migrate → seed → uvicorn/URL → charge → rapport → teardown).
- `.github/workflows/perf.yml` — job **opt-in** (`workflow_dispatch`/`schedule`), non requis.

**Dépendances de dev (optionnelles)** :

- `backend/pyproject.toml` — ajouter un extra `perf` (p. ex. `locust>=2`) **distinct** de `dev`, **hors**
  dépendances de production et **hors** image Docker. (Si k6 est retenu : binaire externe, pas de dépendance
  Python — documenter l'installation dans le README perf.)

**À lire / réutiliser (sans modifier le comportement de production)** :

- `backend/coiflink_api/main.py` (assemblage de l'app, `app.state`), `adapters/inbound/{catalog,appointments,stats,payments,receipts}.py` (routes cibles),
  `adapters/inbound/security.py` (auth deny-by-default), `adapters/outbound/persistence/session.py` (engine/pool),
  `adapters/outbound/security/jwt_token_service.py` (émission de jetons de test).
- `backend/tests/test_critical_journeys_e2e.py`, `test_appointment_notification_e2e.py` (patrons seed/auth/nettoyage FK-safe).
- `deploy/docker-compose.yml` (serveur réel local), `.github/workflows/ci.yml` (patron du job `backend` + service `postgres:16`).
- `docs/strategie-de-tests.md`, `docs/environnements-et-secrets.md` (staging Railway comme cible de référence).

**Documentation à mettre à jour** : `README.md` (§6/roadmap M6), `docs/strategie-de-tests.md` (nouvelle
ligne « tests de performance »), éventuellement `backend/README.md`.

## API / Interface Changes

**None.** Aucune route, aucun schéma de requête/réponse, aucun paramètre CLI de l'API ne change. #52 n'ajoute
que des **scripts de test de charge** et un **workflow CI opt-in**. Les seuls nouveaux « points d'entrée »
sont : la commande d'exécution du harnais (`python backend/perf/run.py` / cible `Makefile` / `locust -f …`)
et le déclenchement `workflow_dispatch` du job `perf` — **outillage de test**, pas surface produit.

## Data Model / Protocol Changes

**None.** Aucune migration, aucune table, aucune colonne, aucun index. Le seed **insère puis nettoie** des
données dans une **plage de téléphones réservée** (nettoyage FK-safe) sur une base **de test/staging**,
jamais la prod ; il **n'altère pas le schéma**. Les scénarios de lecture ne mutent rien ; le scénario de
création de RDV écrit des lignes bornées à la plage réservée, **supprimées au teardown**.

> Remarque : si les mesures révèlent qu'une cible §12.1 n'est pas tenue **à cause** d'un accès non indexé,
> l'**ajout d'index** est une **optimisation** relevant d'une **issue distincte** (feature/perf work), **pas**
> de #52 — voir *Risks & Open Questions*. #52 **constate et documente**, il n'optimise pas.

## Security & Privacy Considerations

Le PRD documente des contraintes directement pertinentes ici — #52 les **respecte** et n'en **affaiblit
aucune** :

- **Budgets de latence §12.1** : ce sont **précisément** les contraintes que #52 mesure. Aucun compromis :
  la suite compare au budget, elle ne le redéfinit pas à la baisse.
- **Jamais de secret ni de PII dans la sortie/les artefacts** (§11.3/§11.4 ; `docs/strategie-de-tests.md`
  §6 ; `backend/tests/test_secrets_policy.py`). La sortie de charge et le **rapport artefact** ne doivent
  contenir **aucun** jeton, mot de passe, téléphone, e-mail, nom, montant nominatif : agréger et **compter**,
  jamais **afficher** une donnée personnelle. Les identifiants/jetons du seed restent **hors logs**.
- **Secret JWT de test uniquement** : émettre les jetons de charge avec un `JwtTokenService`/secret **local
  de test** (patron e2e, sur `app.state` ou variable d'environnement de test), **jamais** `JWT_SECRET` de
  prod. **Aucun secret** ne doit être embarqué dans une commande CI ni un workflow versionné (il apparaîtrait
  dans les logs) — cf. `docs/environnements-et-secrets.md`.
- **Cible d'exécution** : la charge s'exécute contre une base/serveur **de test** ou **staging** — **jamais**
  contre la **prod** (un test de charge sur la prod est un incident de disponibilité §12.2, et manipulerait
  des PII réelles). Si `PERF_TARGET_URL` pointe vers staging, utiliser des **comptes/données synthétiques**
  seedés, non des utilisateurs réels ; respecter la **résidence** `europe-west4` (ADR-0011) — ne pas exfiltrer
  de données vers un service tiers.
- **Deny-by-default / portée §11.2** : les scénarios s'authentifient avec des jetons de **rôle correct** et
  n'exercent que des chemins **autorisés** ; ils ne contournent ni ne testent l'autorisation (c'est #51).
- **Plage de téléphones réservée + nettoyage FK-safe** : préfixe **non utilisé** (grep obligatoire), toutes
  les données bornées, `notifications`/`campaigns` supprimées **avant** `appointments`/`payments`/
  `cash_journal`/`salons`/`users` (FK `RESTRICT`).
- **Pas de nouvelle surface d'attaque** : le harnais vit hors du package prod et **hors de l'image Docker**
  (dépendance de dev optionnelle) ; aucune route de production n'est ajoutée.

## Testing Plan

Cette issue **est** un plan de tests de performance. « Ajouter/mettre à jour des tests » signifie ici
**produire les scénarios de charge et leur harnais**, ainsi que quelques garde-fous de non-régression du
harnais lui-même :

- **Scénarios de charge (le cœur de #52)** — un par budget §12.1 (recherche salon, création RDV, dashboard
  agrégé, API générale), exécutés contre un **serveur réel** + PostgreSQL 16 peuplée, mesurant p50/p95/p99
  et confrontant au budget. Exécution : `workflow_dispatch`/`schedule` (CI) et localement
  (`DATABASE_URL=… python backend/perf/run.py`, Postgres local `coiflink-e2e-pg:55433`).
- **Tests unitaires du harnais (rapides, `pytest`, sans charge)** — pour rendre le harnais **maintenable
  sans introduire de flakiness dans le gate** :
  - `config` : la table des budgets couvre les **quatre** cibles §12.1 avec les bonnes valeurs (2000/3000 ms).
  - **Verdict** : la fonction `mesuré vs budget` classe correctement PASS/WARN/FAIL (cas limites autour du
    seuil et de la marge d'alerte) — logique **déterministe**, testable sans exécuter de charge.
  - **Rapport** : sérialisation CSV/JSON stable et **exempte de PII** (assertion : aucune clé/valeur
    personnelle) — cohérent avec `test_secrets_policy.py`.
  - **Skip propre** : le harnais **skippe** proprement sans `DATABASE_URL` et sans l'extra `perf` installé.
  - Ces tests unitaires **peuvent** vivre sous `backend/tests/` (collectés par `pytest`, rapides, sans I/O
    de charge) et donc tourner dans le gate + CI ; **aucune** exécution de charge n'y est déclenchée.
- **Résilience** : documenter le comportement en cas d'échec du seed / d'indisponibilité de la cible
  (`PERF_TARGET_URL` injoignable) → sortie non ambiguë, pas de faux PASS.
- **Documentation** : le README perf explique comment lire un rapport et **quoi faire** en cas de FAIL
  (ouvrir une issue d'optimisation, ne pas modifier #52).

> Déterminisme : les **résultats de perf** ne sont **pas** déterministes (dépendants matériel/charge) — d'où
> le mode **informatif** et la cible **staging** pour un verdict fiable. En revanche, la **logique** du
> harnais (budgets, verdict, rapport, skip) est **entièrement déterministe** et couverte par les tests
> unitaires ci-dessus.

## Documentation Updates

- **`backend/perf/README.md`** (nouveau) : prérequis, commande d'exécution (local + CI + staging via
  `PERF_TARGET_URL`), paramètres de charge nominale, budgets §12.1, lecture du rapport, conduite en cas de
  FAIL.
- **`docs/strategie-de-tests.md`** : ajouter une entrée « **tests de performance (#52)** » — préciser que ce
  n'est **ni** dans le gate ADW **ni** un status check requis (job opt-in), documenter la **plage de
  téléphones réservée** et la cible de référence (staging). Mettre à jour le tableau « quoi tourne où ».
- **`README.md`** (§6 chronologie M6 / roadmap) : mention factuelle que #52 est livrée (suite de perf sur
  les endpoints critiques §12.1), après #50/#51. Rester factuel, **sans signature IA**.
- **`backend/README.md`** : éventuellement lister le répertoire `perf/` et l'extra `perf`.
- **ADR** : **aucun requis** par défaut (issue de tests, aucune décision d'architecture applicative). **Si**
  le **choix de l'outil de charge** (Locust vs k6) ou la **décision d'en faire un gate sur staging** est
  jugé structurant, un **ADR court** peut être ouvert — **à confirmer** avec le mainteneur (voir *Risks*).
- **Pas de nouvelle API publique** → aucune documentation d'endpoint à produire.

## Risks and Open Questions

- **« Charge nominale » et percentile non définis dans le PRD (décision à confirmer).** Le §12.1 donne des
  seuils de temps **sans** modèle de charge ni percentile. *Recommandation* : figer **p95** comme métrique de
  décision (p99 en surveillance) et une charge **modeste MVP** (~20 VUs concurrents, palier 60 s, warm-up
  exclu), **documentée comme hypothèse révisable**. **À valider** avant l'implémentation.
- **Environnement de référence & flakiness (décision à confirmer).** Les runners CI partagés sont **variables**
  → un seuil dur y serait **flaky**. *Recommandation* : suite **informative** en CI (indicateur de dérive) +
  verdict **de référence** contre **staging Railway** (`PERF_TARGET_URL`), matériel stable. **Ne pas** en faire
  un status check requis sans environnement de référence dédié. Décision : garder informatif, ou promouvoir en
  gate sur staging ?
- **Outil de charge : Locust vs k6 (décision à confirmer).** *Recommandation* : **Locust** (chaîne Python
  déjà présente, scénarios en code, extra `perf` isolé). k6 (Go/JS) est un excellent outil dédié mais ajoute
  un toolchain hors Python. **À trancher** ; le reste de la spec est agnostique.
- **Que faire si une cible §12.1 est dépassée ?** #52 **mesure**, il **n'optimise pas**. *Recommandation* :
  documenter le dépassement dans le rapport + **ouvrir une issue d'optimisation dédiée** (index manquant,
  N+1, pagination, cache Redis différé M5) ; **ne pas** modifier le code de production dans #52. **À confirmer**
  que ce découpage convient (vs bloquer #52 jusqu'à correction).
- **`TestClient` inadapté à la charge.** Le transport ASGI en-processus mono-thread **ne mesure pas** la
  latence réelle sous concurrence : #52 **doit** viser un **serveur réel** (uvicorn) ou une URL externe.
  Risque si un contributeur ré-emploie `TestClient` par habitude e2e — **documenter** explicitement.
- **Coût & durée d'un run de charge.** Un palier de 60 s + seed peut dépasser le budget d'un job CI standard.
  *Mitigation* : job **séparé** (`schedule`/manuel), paramètres modestes, seed borné, teardown systématique.
- **Effets de bord du scénario de création de RDV.** La création **écrit** (RDV + notifications #45/#46/#47)
  et pourrait **saturer** la base de test si non bornée. *Mitigation* : créneaux futurs bornés à la plage
  réservée, **teardown** obligatoire, éventuellement plafonner le nombre de créations par run.
- **Collision de plage téléphone.** Beaucoup de préfixes `+225…` sont pris — **grep obligatoire** avant de
  figer la plage (candidat `+225059990x`, à confirmer libre).
- **Isolation vis-à-vis des autres suites en CI.** Si le job perf partage une base avec d'autres `*_e2e.py`,
  risque d'interférence : *recommandation* — base **dédiée** au job perf (service `postgres:16` propre au
  workflow), jamais partagée.
- **Stack applicative** : rien d'incertain — backend Python/FastAPI/PostgreSQL **figé par ADR**. La **seule**
  incertitude de toolchain est l'**outil de charge** (isolé, opt-in), traitée ci-dessus.

## Implementation Checklist

1. **Reconnaissance** : relire `main.py` (assemblage/`app.state`), les routers cibles
   (`catalog`/`appointments`/`stats`/`payments`/`receipts`), `session.py` (pool), `jwt_token_service.py`,
   et les patrons e2e (`test_critical_journeys_e2e.py`, `test_appointment_notification_e2e.py`). **Grep** les
   préfixes téléphone pris et **réserver** une plage libre (constante dédiée).
2. **Confirmer les décisions ouvertes** avec le mainteneur **avant de coder** : charge nominale + percentile,
   environnement de référence (informatif CI vs gate staging), outil de charge (Locust vs k6), traitement d'un
   dépassement §12.1 (issue d'optimisation séparée), éventuel ADR.
3. **`backend/perf/config.py`** (ou `perf.toml`) : budgets §12.1 (2000/3000 ms) par groupe, `percentile=95`,
   charge nominale, `warmup`, marge d'alerte. Tests unitaires : les 4 cibles présentes/correctes.
4. **`backend/perf/seed.py`** : peuplement représentatif (salons/prestations/coiffeurs/clients/RDV/paiements)
   borné à la plage réservée + `teardown` **FK-safe** (notifications/campaigns d'abord) ; jetons de rôle
   pré-émis via `JwtTokenService` **de test** ; **aucune** PII journalisée.
5. **`backend/perf/locustfile.py`** (ou `k6/`) : scénarios `SalonSearchUser`, `BookingUser`,
   `ManagerDashboardUser`, `ApiGeneralUser` — requêtes **authentifiées** (jetons du seed), chemins
   **autorisés** uniquement, création de RDV bornée à la plage réservée.
6. **`backend/perf/run.py`** : `DATABASE_URL` (skip propre sinon) → `alembic upgrade head` → `seed` →
   **uvicorn** local **ou** `PERF_TARGET_URL` → run de charge → **rapport** (p50/p95/p99, débit, erreurs) →
   **table de verdict vs §12.1** (CSV+JSON+Markdown) → `teardown`. Warm-up exclu ; `--strict` opt-in.
7. **Tests unitaires du harnais** sous `backend/tests/` (rapides, `pytest`, **sans charge**) : couverture des
   budgets, logique de verdict (PASS/WARN/FAIL), rapport **sans PII**, skip propre. Ne déclenchent **aucune**
   charge → sûrs dans le gate + CI.
8. **Dépendance de dev optionnelle** : extra `perf` dans `pyproject.toml` (`locust>=2`), **distinct** de `dev`,
   **hors** prod et **hors** image Docker. (k6 : documenter l'install binaire.)
9. **`.github/workflows/perf.yml`** : job **opt-in** (`workflow_dispatch`/`schedule`), service `postgres:16`
   dédié, `alembic upgrade head` + seed + run + **upload artefact** du rapport. **Non requis**, **hors** gate
   ADW. Réussit même en WARN/FAIL sauf `--strict`.
10. **Exécuter localement** : `DATABASE_URL=… python backend/perf/run.py` contre `coiflink-e2e-pg:55433` (ou
    `docker compose -f deploy/docker-compose.yml up`) ; vérifier `ruff check` sur `backend/perf/`.
11. **Vérifier l'hygiène §11** : aucun secret/PII dans la sortie, le rapport ou les logs de workflow ;
    `test_secrets_policy.py` reste vert ; secret JWT **de test** uniquement ; teardown effectif.
12. **Documentation** : `backend/perf/README.md`, entrée `docs/strategie-de-tests.md`, mention `README.md`
    §6/M6, éventuellement `backend/README.md`. **Documenter** quoi faire en cas de FAIL (issue d'optimisation
    séparée). **Aucune signature IA** dans le code, les commits ou la PR.
