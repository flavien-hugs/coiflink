# Pipeline CI/CD applicatif (GitHub Actions)

> Spécification de planification pour l'issue GitHub **#4 — Pipeline CI/CD (GitHub Actions)**
> (`infra` · Must · Effort M · PRD §10 / §18 Sprint 0). **Dépend de #2** (arborescence du monorepo)
> — satisfaite : `app-mobile/`, `web-dashboard/`, `backend/` existent, avec des commandes de build/test
> réelles. **Cette spec ne produit pas de code.** Elle décrit le pipeline CI/CD applicatif à construire
> dans une phase d'implémentation ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, specs). Les en-têtes de
> section ci-dessous sont conservés en anglais car ils sont attendus par le gabarit du pipeline ADW ;
> le contenu livré (workflows, Dockerfiles, README, ADR) reste en français hors identifiants techniques.

## Problem Statement

Le dépôt possède aujourd'hui **une seule CI** : `.github/workflows/adw-sdlc.yml`, qui valide **uniquement
le control plane** du pipeline ADW (`adw_sdlc/` — typecheck, tests Vitest, garde de rétention des secrets
`lint:env`). **Aucune CI ne couvre les trois paquets applicatifs** (`app-mobile/`, `web-dashboard/`,
`backend/`) que les issues #2/#3 ont scaffoldés. En conséquence :

- une PR qui casse le build ou les tests d'un paquet applicatif **n'est bloquée par aucun garde-fou** ;
- rien ne produit d'**artefacts de build** (APK mobile, sortie Next.js, wheel backend) ni d'**images
  Docker** ;
- aucun **scan de dépendances** ne signale une vulnérabilité connue ou une dépendance obsolète ;
- les issues du socle qui en dépendent sont bloquées : **#5** (environnements & secrets — *dépend de #4*),
  **#6** (câblage du test gate `MX_AGENT_TEST_CMD` — *dépend de #4*), et **#50** (tests e2e *« intégrés à
  la CI (#4) »*).

Le besoin (issue #4, critères d'acceptation) : **une CI applicative déclenchée à chaque PR** qui exécute
**lint + tests unitaires + build** pour chaque paquet dans des **jobs séparés mobile/web/backend**, ajoute
un **scan de dépendances**, **produit des artefacts de build** et **construit les images Docker** — le tout
avec une **CI verte rendue obligatoire avant merge**.

## Goals

- **Nouveau workflow CI applicatif** (p. ex. `.github/workflows/ci.yml`) déclenché sur `pull_request` (et
  `push` sur `main`), **distinct** de `adw-sdlc.yml` qui reste dédié au control plane.
- **Trois jobs de paquet séparés** (critère d'acceptation explicite), chacun exécutant, sur la stack et la
  version de référence figées par [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md) :
  - **`backend/`** (Python ≥ 3.12) : lint → tests (`pytest`) → build (installation du paquet + build
    d'un artefact distribuable) ; **exécution des migrations Alembic** contre un service PostgreSQL 16
    (renvoi *Suivi* d'[ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).
  - **`web-dashboard/`** (Node ≥ 20) : lint (`npm run lint`) → tests (`npm test`) → build (`npm run build`).
  - **`app-mobile/`** (Flutter stable / Dart ^3.12) : analyse (`flutter analyze`) → tests (`flutter test`)
    → build (`flutter build apk`).
- **Scan de dépendances** à chaque PR : détection des vulnérabilités connues par écosystème (Python, Node,
  Dart) + configuration **Dependabot** pour les mises à jour automatisées.
- **Artefacts de build produits** et téléversés (`actions/upload-artifact`) : APK Android, sortie de build
  Next.js, artefact distribuable backend.
- **Images Docker construites** pour les services *serveur* (backend, et web-dashboard en mode `standalone`) ;
  décision *push vers un registre* renvoyée à #5 (voir Risks) — par défaut **build seul** en #4.
- **CI verte obligatoire avant merge** : définir la liste des **status checks requis** et documenter la
  **protection de branche** `main` correspondante (réglage dépôt, non versionnable), en cohérence avec la
  phase `merge` du pipeline ADW.
- **Least-privilege & zéro secret** : `permissions:` minimales par job, aucun secret journalisé, aucun
  secret ajouté au dépôt (les `.env.example` restent des placeholders — cf. invariant #2/#5).
- **Reproductibilité & coût maîtrisé** : cache des dépendances par écosystème ; `concurrency` avec
  `cancel-in-progress` (comme `adw-sdlc.yml`) ; filtrage par chemin envisagé (voir Risks — subtilité des
  *required checks*).

## Non-Goals

- **Déployer** quoi que ce soit (staging/prod), **choisir l'hébergeur** ou **pousser les images vers un
  registre en production** — relèvent de **#5** (environnements & secrets) et de l'ADR de déploiement
  différé (cf. [index ADR](../docs/adr/README.md) : « Plateforme d'hébergement & région des données —
  ADR de déploiement (#4/#5) »). #4 se limite à **construire** les images et **produire** les artefacts.
- **Câbler le test gate ADW** `MX_AGENT_TEST_CMD` dans `scripts/adw.env` ni rédiger la stratégie de tests —
  issue **#6**. #4 exécute les commandes de test **par paquet** ; l'agrégation côté gate est #6.
- **Ajouter des tests e2e** ou des tests métier — #4 exécute les tests **existants** (triviaux/scaffold) ;
  les e2e sont **#50** (qui s'intégrera *dans* la CI de #4).
- **Modifier `adw-sdlc.yml`** (control plane) au-delà d'un éventuel ajustement de `concurrency`/nommage pour
  éviter les collisions — le workflow control plane reste sa propre responsabilité.
- **Implémenter une fonctionnalité MVP** (auth, salons, RDV, caisse, notifications) — issues M1→.
- **Modifier le schéma de données / les migrations** — #3 (l'ADR-0009 est *consommé*, pas réécrit) ; #4 ne
  fait qu'**exécuter** les migrations en CI.
- **Gérer les secrets applicatifs réels** (DSN prod, `JWT_SECRET`, clés FCM/SMS/S3) — #5. La seule
  « credential » de #4 est le mot de passe **éphémère et non secret** du service Postgres de test.

## Relevant Repository Context

**Nature du dépôt.** Monorepo greenfield outillé pour livraison agentique. Trois paquets applicatifs
scaffoldés (#2, #3), un control plane (`adw_sdlc/`), et une CI existante limitée au control plane.

**CI existante (à ne pas confondre / à ne pas casser).** `.github/workflows/adw-sdlc.yml` :
- déclencheurs `push: [main]` + `pull_request`, `working-directory: adw_sdlc`, matrice Node `20`/`22` ;
- étapes : `npm ci` → `npm run typecheck` → `npm test` → `npm run lint:env` (garde de rétention des secrets) ;
- `concurrency: adw-sdlc-${{ github.ref }}` avec `cancel-in-progress: true`.
→ **Modèle de référence** pour la nouvelle CI applicative (setup + cache + concurrency + least-privilege).

**Stack & versions de référence figées ([ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md)).**

| Paquet | Stack (ADR) | Version réf. | Lint | Test | Build |
| --- | --- | --- | --- | --- | --- |
| `backend/` | FastAPI/Python ([0003](../docs/adr/0003-backend-fastapi.md)) | Python **≥ 3.12** | *(aucun linter configuré — voir Risks)* | `pytest` | `pip install -e .` (+ build distribuable) |
| `web-dashboard/` | Next.js/React/TS ([0002](../docs/adr/0002-web-gerant-admin-nextjs.md)) | Node **≥ 20** | `npm run lint` (eslint) | `npm test` (`vitest run`) | `npm run build` (`next build`) |
| `app-mobile/` | Flutter/Dart ([0001](../docs/adr/0001-app-mobile-flutter.md)) | Flutter **stable** / Dart **^3.12** | `flutter analyze` (`flutter_lints`) | `flutter test` | `flutter build apk` |

**Manifestes vérifiés.**
- `backend/pyproject.toml` : `requires-python = ">=3.12"` ; deps `fastapi`, `uvicorn[standard]`, `sqlalchemy`,
  `alembic`, `psycopg[binary]` ; extra `dev` = `pytest`, `httpx` ; `[build-system]` setuptools ;
  `testpaths = ["tests"]`. **Aucun linter** (ruff/flake8/black) déclaré.
- `web-dashboard/package.json` : scripts `dev/build/start/lint/test` ; `engines.node = ">=20"` ; Next `16.2.9`,
  React `19`, `vitest`, `eslint` + `eslint-config-next`. `vitest.config.ts` inclut `test/**/*.test.ts`.
- `app-mobile/pubspec.yaml` : `environment.sdk: ^3.12.0` ; `flutter_lints ^6` ; test `test/widget_test.dart`.

**Persistance & migrations ([ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).**
Migrations Alembic sous `backend/migrations/versions/0001_schema_initial.py` ; `alembic.ini` sans identifiant ;
`migrations/env.py` lit `DATABASE_URL` (jamais de secret) et normalise vers `postgresql+psycopg://`. L'ADR-0009
*Suivi* renvoie explicitement **« exécution des migrations en CI + service Postgres → #4 »**. Le round-trip
`upgrade head → downgrade base → upgrade head` est réversible/idempotent et requiert l'extension `btree_gist`
(privilège `CREATE EXTENSION`, disponible sur l'image `postgres:16` officielle). Le `backend/README.md` note
que les tests Postgres **skippent** en l'absence de `DATABASE_URL` : la CI #4 doit **fournir** un `DATABASE_URL`
de test pour les exécuter réellement.

**PRD.** §10.2 « Déploiement : Docker · CI/CD GitHub Actions · Hébergement cloud sécurisé · Sauvegardes ».
§18 Sprint 0 = socle (stack, dépôt, données, **CI**, environnements). Le README §4 marque la ligne
« Déploiement » comme *« à figer par l'ADR de déploiement (#4/#5) »*.

**Invariants sécurité (transverses).** Ne **jamais** committer/journaliser un secret ; seuls les `*.env.example`
(placeholders) sont versionnés (CONTRIBUTING.md « Secrets », ADR-0009 « Sécurité »). Le control plane ADW
**détient tout git/gh** et **retient `GH_TOKEN`** (jamais exposé à l'agent) ; `adw-sdlc.yml` inclut une garde
`lint:env` de rétention des secrets. **Préférence utilisateur** : aucun marqueur « généré par IA » dans le code,
les commits, les PR ou la doc.

**Décisions encore ouvertes au démarrage de #4** (voir Risks) : linter backend (aucun aujourd'hui) ;
outils de scan de dépendances par écosystème + seuil de sévérité bloquant ; périmètre des images Docker
(backend + web ? mobile non) et build-seul vs push GHCR ; filtrage par chemin vs exécution systématique ;
opportunité d'un **ADR de déploiement/CI-CD** (ADR-0010) ; interaction *required checks* ↔ phase `merge` ADW.

## Proposed Implementation

Approche d'ensemble : **un workflow CI applicatif** (`.github/workflows/ci.yml`) à **jobs indépendants**,
chacun cadré sur un paquet, plus un job de **scan de dépendances**, plus des jobs de **build d'images Docker**.
Réutiliser les conventions de `adw-sdlc.yml` (setup officiels, cache, `concurrency`, `permissions` minimales).

### 0. Déclencheurs, concurrence, permissions (en-tête du workflow)

```yaml
name: CI applicative
on:
  push: { branches: [main] }
  pull_request:
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
permissions:
  contents: read           # least-privilege par défaut ; élargi par job si besoin (packages: write pour GHCR)
```

> Garder un **groupe de concurrence distinct** de `adw-sdlc.yml` (`adw-sdlc-…` vs `ci-…`) pour ne pas
> s'annuler mutuellement.

### 1. Job `backend` (Python 3.12)

- `runs-on: ubuntu-latest`, `defaults.run.working-directory: backend`.
- **Service PostgreSQL 16** (`services: postgres: image: postgres:16`) avec `env` de test
  **éphémères et non secrets** (`POSTGRES_PASSWORD` = valeur de test documentée comme jetable) et un
  `healthcheck` (`pg_isready`) ; exposer `DATABASE_URL=postgresql://…@localhost:5432/…` en `env` du job.
- Étapes : `actions/setup-python@v5` (3.12, `cache: pip`) → `pip install -e ".[dev]"` →
  **lint** (voir Risks — recommandation **ruff** : `ruff check` + `ruff format --check`) →
  **tests** `pytest` (exécute aussi le round-trip Alembic puisque `DATABASE_URL` est fourni) →
  **build distribuable** (`python -m build` → wheel + sdist) → `actions/upload-artifact` (dist backend).
- Séparément (ou dans le même job) : `alembic upgrade head` puis `alembic downgrade base` pour valider
  explicitement le round-trip de migration contre Postgres 16 (couvre le *Suivi* ADR-0009).

### 2. Job `web` (Node 20)

- `runs-on: ubuntu-latest`, `defaults.run.working-directory: web-dashboard`.
- Étapes : `actions/setup-node@v4` (`node-version: 20`, `cache: npm`,
  `cache-dependency-path: web-dashboard/package-lock.json`) → `npm ci` → `npm run lint` → `npm test`
  → `npm run build` → `actions/upload-artifact` (sortie de build ; pour un artefact et une image lean,
  activer `output: 'standalone'` dans `next.config.ts` — voir *Affected Files*).

### 3. Job `mobile` (Flutter stable)

- `runs-on: ubuntu-latest`, `defaults.run.working-directory: app-mobile`.
- Étapes : setup Java (`actions/setup-java`, Temurin) + Flutter (`subosito/flutter-action`, canal
  **stable**, `cache: true`) → `flutter pub get` → `flutter analyze` → `flutter test` →
  `flutter build apk --debug` (ou `--release` non signé) → `actions/upload-artifact` (APK).
- iOS **non construit** en CI (nécessiterait un runner macOS coûteux ; Android est prioritaire — ADR-0001).

### 4. Job `dependency-scan`

- **Par écosystème** (recommandations, à confirmer — voir Risks) :
  - Python : `pip-audit` (ou `osv-scanner`) sur `backend/`.
  - Node : `npm audit --audit-level=high` sur `web-dashboard/` (ou `osv-scanner`).
  - Dart : `dart pub outdated`/`osv-scanner` sur `app-mobile/`.
  - *Option unifiée* : `google/osv-scanner` sur tout le monorepo (couvre les trois lockfiles).
- **Seuil bloquant** : recommandation = échec sur **High/Critical**, avertissement sinon (à confirmer).
- **Dependabot** : ajouter `.github/dependabot.yml` (écosystèmes `pip`, `npm`, `pub`, `github-actions`)
  pour les mises à jour automatisées — complément du scan par PR.
- *(Optionnel)* activer **CodeQL** (JS/TS + Python) dans un workflow séparé si l'analyse statique de
  sécurité est souhaitée — non requis par le critère d'acceptation.

### 5. Jobs `docker-*` (build d'images)

- **Aucun Dockerfile n'existe** aujourd'hui : les créer (voir *Affected Files*).
  - `backend/Dockerfile` : image Python 3.12 slim, install du paquet, `CMD uvicorn coiflink_api.main:app`
    (config **par variables d'environnement**, aucun secret dans l'image ; utilisateur non-root).
  - `web-dashboard/Dockerfile` : build multi-stage Node 20 → runtime `standalone` Next.js (utilisateur
    non-root).
  - **Mobile : pas d'image Docker** (l'artefact livrable est l'**APK**, pas un service serveur).
- Chaque `docker-*` : `docker/setup-buildx-action` → `docker/build-push-action` avec **`push: false`**
  par défaut (build-seul, cache GHA) — le **push vers GHCR** est différé à #5 (voir Risks). Ajouter
  `*.dockerignore` pour exclure `.venv/`, `node_modules/`, `.next/`, tests, `.env*`.

### 6. « CI verte obligatoire avant merge »

- Définir la **liste des status checks requis** (les jobs ci-dessus) et documenter la **protection de
  branche `main`** exigeant ces checks + PR à jour. C'est un **réglage dépôt** (Settings → Branches, ou
  `gh api`), **non versionnable** dans le repo → à consigner dans la doc/ADR et à appliquer par un
  humain/administrateur (voir Risks — interaction avec la phase `merge` du pipeline ADW).
- **Attention filtrage par chemin** : si des jobs sont conditionnés par `paths:`, un job requis mais
  *skippé* peut **bloquer** la fusion (un check requis « skipped » ≠ « success » selon la config). Deux
  parades : (a) ne pas filtrer (exécuter les 3 jobs à chaque PR — simple, recommandé au MVP), ou
  (b) utiliser un job « gate » d'agrégation qui réussit si les jobs pertinents réussissent. Recommandation
  MVP : **pas de filtrage**, quitte à optimiser plus tard.

## Affected Files / Packages / Modules

À **créer** (cette issue) :
- `.github/workflows/ci.yml` — workflow CI applicatif (jobs `backend`, `web`, `mobile`, `dependency-scan`,
  `docker-backend`, `docker-web`).
- `.github/dependabot.yml` — mises à jour de dépendances (`pip`, `npm`, `pub`, `github-actions`).
- `backend/Dockerfile` + `backend/.dockerignore`.
- `web-dashboard/Dockerfile` + `web-dashboard/.dockerignore`.
- *(Selon décision lint backend)* configuration **ruff** dans `backend/pyproject.toml` (`[tool.ruff]`) et
  ajout de `ruff` à l'extra `dev`.
- *(Optionnel, recommandé pour traçabilité)* `docs/adr/0010-ci-cd-docker-packaging.md` (décisions CI/CD +
  empaquetage Docker ; **n'arrête pas** l'hébergeur, différé #5).

À **modifier** :
- `web-dashboard/next.config.ts` — ajouter `output: 'standalone'` (image Docker lean + artefact).
- `README.md` (racine) — §4 (ligne « Déploiement » : refléter la CI/CD GitHub Actions livrée) et une note
  « CI applicative » (checks requis, artefacts, images) ; lier `docs/adr/0010` si créé.
- `docs/adr/README.md` — index : ajouter ADR-0010 si créé ; noter que #4 clôt la partie « CI/CD » du point
  différé « ADR de déploiement (#4/#5) » (l'hébergement restant à #5).
- *(Optionnel)* `.gitignore` — motifs de build supplémentaires éventuels (déjà couverts pour l'essentiel).

À **lire** pour construire juste :
- `.github/workflows/adw-sdlc.yml` (modèle setup/cache/concurrency/permissions).
- Manifestes : `backend/pyproject.toml`, `web-dashboard/package.json`, `app-mobile/pubspec.yaml`.
- `backend/alembic.ini`, `backend/migrations/env.py` (variable `DATABASE_URL`, driver psycopg 3).
- ADR-0001/0002/0003/0007/0009 et `docs/adr/README.md` ; `BACKLOG.md` (#4 et dépendants #5/#6/#50).
- `prd-coiflink.md` §10.2 (déploiement), §11 (sécurité), §18 (Sprint 0).

À **ne pas toucher** : `adw_sdlc/`, `adw/`, `scripts/`, `.claude/`, `.pi/`, le schéma/migrations `#3`,
le contenu métier des paquets, et les `*.env.example` (aucun secret ajouté).

## API / Interface Changes

- **API réseau / publique** : **none.** #4 n'ajoute ni ne modifie aucune route (le backend garde son seul
  `GET /health`) ni aucun contrat client. Les `Dockerfile` **empaquettent** l'app existante sans changer
  son interface HTTP.
- **Surface CI / développeur (nouvelle)** :
  - Workflow **`ci.yml`** avec des **status checks** nommés (jobs `backend`/`web`/`mobile`/`dependency-scan`/
    `docker-*`) qui deviennent des interfaces de contrôle observables sur chaque PR (et candidats aux
    *required checks*).
  - **Artefacts de build** téléversés (noms d'artefacts à documenter : APK, sortie web, dist backend).
  - **Images Docker** nommées (tags), construites en CI ; leur push/registre est différé (#5).
  - *(Si lint backend retenu)* nouvelles commandes développeur `ruff check` / `ruff format` documentées.
- Aucun changement aux interfaces du pipeline ADW (`scripts/run-issue.sh`, `MX_AGENT_*`, `adw-sdlc.yml`).

## Data Model / Protocol Changes

**None.** #4 ne modifie ni schéma, ni migration, ni format de sérialisation. Il **exécute** les migrations
existantes (#3) contre un PostgreSQL 16 **éphémère** en CI pour valider le round-trip Alembic — sans changer
leur contenu. Aucune donnée persistée ; la base de CI est jetée en fin de job.

## Security & Privacy Considerations

- **Secrets / credentials — invariant critique.** #4 ne doit **ni committer ni journaliser** de secret.
  - `permissions:` **least-privilege** par workflow/job (`contents: read` par défaut ; n'élargir à
    `packages: write` que si/quand un push GHCR est décidé — sinon jamais).
  - Aucun secret applicatif réel n'est requis par #4 : DSN prod, `JWT_SECRET`, clés FCM/SMS/S3 relèvent de
    **#5** et **ne doivent pas** apparaître dans les workflows.
  - **Exception documentée** : le **mot de passe du service Postgres de test** est une valeur **éphémère,
    jetable et non secrète** (base recréée à chaque run) — l'écrire en clair dans le workflow est acceptable
    et **n'est pas** un secret au sens de l'invariant. Ne pas y mettre un identifiant réutilisé ailleurs.
  - Ne pas activer de logs verbeux susceptibles de dumper l'environnement ; ne pas `echo` des variables.
  - `.env.example` **inchangés** (aucun ajout de valeur) ; aucun `.env` réel n'entre en CI.
- **Cohérence avec la rétention des secrets du control plane** : `adw-sdlc.yml` retient `GH_TOKEN` via
  `lint:env`. La CI applicative n'utilise que le `GITHUB_TOKEN` d'Actions (scoping minimal) ; documenter
  qu'aucun token à privilèges larges n'est exposé aux étapes de build/scan.
- **Images Docker** : ne **jamais** copier `.env`, clés ou identifiants dans l'image ; config **par
  variables d'environnement** à l'exécution (#5). Utilisateur **non-root**, base d'image à jour ;
  `*.dockerignore` pour exclure secrets potentiels et artefacts locaux.
- **PII & journalisation** : aucune donnée utilisateur n'est traitée ; les tests utilisent des données
  synthétiques. Les logs Alembic/CI ne dumpent pas de PII (cf. ADR-0009 « Sécurité »).
- **Chaîne d'approvisionnement** : le scan de dépendances et Dependabot **réduisent** le risque de
  dépendance vulnérable — c'est une mesure de sécurité, à ne pas affaiblir (seuil bloquant à définir).
  Épingler les actions tierces (`subosito/flutter-action`, etc.) à une version/`sha` pour limiter le risque
  d'action compromise (recommandé).
- **Résidence / hébergement** : non figé par #4 (différé #5) ; aucune donnée réelle ne quitte la CI.
- **Préférence utilisateur** : aucun marqueur « généré par IA » dans les workflows, Dockerfiles, ADR ou doc.

## Testing Plan

La « valeur testée » de #4 est le **pipeline lui-même** : la CI doit être **verte sur le squelette** et
**rouge quand un paquet casse**. À vérifier :

- **Exécution locale préalable** (sanity, avant push) : sur chaque paquet, reproduire les commandes CI —
  `pip install -e ".[dev]" && pytest` (+ `ruff check` si retenu) ; `npm ci && npm run lint && npm test &&
  npm run build` ; `flutter pub get && flutter analyze && flutter test && flutter build apk`.
- **Round-trip Alembic** : contre un Postgres 16 local/CI avec `DATABASE_URL` défini,
  `alembic upgrade head && alembic downgrade base && alembic upgrade head` **réussit** (extension
  `btree_gist` créée) ; les tests Postgres du backend **ne skippent plus** (car `DATABASE_URL` fourni).
- **Artefacts** : chaque job de paquet **téléverse** son artefact (APK, sortie web, wheel/sdist) et
  l'artefact est téléchargeable depuis le run.
- **Images Docker** : `docker build` réussit pour `backend/` et `web-dashboard/` ; l'image backend démarre
  et répond `GET /health` → 200 (smoke test optionnel en CI) ; l'image web sert la page d'accueil.
- **Scan de dépendances** : le job s'exécute et **rapporte** ; sur une dépendance vulnérable simulée, il
  **échoue** au seuil retenu (test manuel ponctuel).
- **Garde-fou merge** : sur une PR volontairement cassée (test qui échoue), la CI passe **au rouge** et le
  check requis empêche la fusion (vérification manuelle une fois la protection de branche appliquée).
- **Non-régression control plane** : `adw-sdlc.yml` continue de tourner indépendamment (groupes de
  concurrence distincts, pas de collision de nom de job/check).
- **Zéro secret** : relire les logs de run — aucune valeur sensible affichée ; `permissions:` minimales
  effectives.

> Note : #4 **n'ajoute pas** de tests e2e (#50) ni ne câble `MX_AGENT_TEST_CMD` (#6) ; il exécute les tests
> **existants** par paquet.

## Documentation Updates

- **`README.md`** (racine) : §4 — mettre à jour la ligne « Déploiement » pour indiquer la **CI/CD GitHub
  Actions livrée** (jobs séparés, artefacts, images) ; ajouter une courte section « CI applicative » listant
  les checks requis et les artefacts produits ; préciser que l'hébergement/push registre reste #5.
- **`docs/adr/0010-ci-cd-docker-packaging.md`** *(optionnel, recommandé)* : tracer les décisions — structure
  CI (jobs séparés), outils de scan + seuil, périmètre Docker (backend + web, mobile = APK), build-seul vs
  push, filtrage par chemin. Mettre à jour **`docs/adr/README.md`** (index + note sur le point différé
  « ADR de déploiement »).
- **READMEs de paquet** : mentionner la commande Docker (`docker build …`) dans `backend/README.md` et
  `web-dashboard/README.md` si un Dockerfile y est ajouté ; noter le linter backend si `ruff` est retenu.
- **`CONTRIBUTING.md`** : *(optionnel)* mentionner que toute PR doit passer la CI applicative verte avant
  fusion (renvoi vers la nouvelle section README).
- **`specs/`** : la présente spec (`specs/pipeline-ci-cd-github-actions.md`).

## Risks and Open Questions

- **Lint backend — aucun linter configuré aujourd'hui (à trancher).** `pyproject.toml` ne déclare ni ruff,
  ni flake8, ni black. Le critère « lint » impose un outil. **Recommandation : ruff** (`ruff check` +
  `ruff format --check`), léger et standard FastAPI. Alternative : flake8 + black. **À confirmer** ; sinon
  le job backend n'a pas d'étape de lint réelle.
- **Outils de scan de dépendances + seuil bloquant (à confirmer).** Par écosystème (`pip-audit`/`npm audit`/
  `dart pub outdated`) **ou** unifié (`osv-scanner`). Seuil recommandé : échec sur High/Critical. Décider
  aussi si le scan est **bloquant** (échec de la CI) ou **informatif** au MVP.
- **Périmètre Docker & push (à confirmer, en partie différé #5).** Recommandation : images pour **backend**
  et **web-dashboard** (services serveur), **mobile = APK** (pas d'image). **Build-seul** en #4 ; le
  **push vers un registre (GHCR)** et le choix du registre relèvent de #5/l'ADR de déploiement. Si l'équipe
  veut publier des images dès #4, prévoir `permissions: packages: write` + `GITHUB_TOKEN` (jamais de PAT en
  clair).
- **Interaction *required checks* ↔ phase `merge` du pipeline ADW (à clarifier).** Le control plane ADW
  **détient le merge**. Si la protection de branche exige des checks requis, confirmer que la phase `merge`
  **attend** ces checks (et n'a pas de privilège de contournement) — sinon « CI verte obligatoire avant
  merge » ne serait pas réellement garanti. Décision d'exploitation à acter avec #5.
- **Filtrage par chemin (monorepo).** Conditionner les jobs par `paths:` réduit le coût mais **complique les
  required checks** (un check requis *skippé* peut bloquer la fusion). Recommandation MVP : **pas de
  filtrage** ; optimiser plus tard via un job « gate ».
- **Coût / durée runners.** Flutter (`flutter build apk`) et les builds Docker sont lents ; prévoir le cache
  (`cache: true` Flutter, cache pip/npm, cache buildx GHA). iOS non construit (macOS coûteux, Android
  prioritaire ADR-0001).
- **Next.js `standalone`.** L'image web lean suppose `output: 'standalone'` dans `next.config.ts` ; à ajouter
  et vérifier que `next build` reste vert.
- **`btree_gist` en CI.** L'image `postgres:16` officielle permet `CREATE EXTENSION btree_gist` (le round-trip
  Alembic en dépend). Le *Suivi* ADR-0009 rappelle que sur un **Postgres managé restreint** (hébergement #5)
  ce privilège pourrait manquer — hors périmètre #4 (CI utilise l'image officielle).
- **Épinglage des actions tierces.** Épingler `subosito/flutter-action`, `docker/*`, `osv-scanner` à une
  version/`sha` (sécurité chaîne d'appro) — recommandé.
- **Dépendance #2** : satisfaite. Si une version de référence (ADR-0007) évoluait, la matrice CI devrait
  suivre.

## Implementation Checklist

1. **Vérifier les prérequis** : paquets présents et build/test réels (`backend/`, `web-dashboard/`,
   `app-mobile/`) ; `adw-sdlc.yml` en place (ne pas casser) ; versions de référence ADR-0007.
2. **Trancher les décisions ouvertes** (et les tracer, README/ADR-0010) : (a) **linter backend** (ruff
   recommandé) ; (b) **outil(s) de scan** + seuil bloquant ; (c) **périmètre Docker** (backend + web ;
   mobile = APK) et **build-seul vs push** ; (d) **filtrage par chemin** (recommandé : non) ; (e) opportunité
   d'un **ADR-0010**.
3. **Créer `.github/workflows/ci.yml`** : en-tête (`on` PR + push main, `concurrency: ci-…`,
   `permissions: contents: read`).
4. **Job `backend`** : setup Python 3.12 + cache pip ; **service Postgres 16** (mot de passe de test
   éphémère, healthcheck, `DATABASE_URL`) ; `pip install -e ".[dev]"` ; lint (ruff si retenu) ; `pytest` ;
   round-trip `alembic upgrade head → downgrade base → upgrade head` ; `python -m build` ; upload artefact.
5. **Job `web`** : setup Node 20 + cache npm ; `npm ci` ; `npm run lint` ; `npm test` ; `npm run build` ;
   upload artefact (activer `output: 'standalone'` dans `next.config.ts`).
6. **Job `mobile`** : setup Java + Flutter stable (cache) ; `flutter pub get` ; `flutter analyze` ;
   `flutter test` ; `flutter build apk` ; upload APK.
7. **Job `dependency-scan`** : scan par écosystème (ou `osv-scanner` unifié) au seuil retenu ; créer
   `.github/dependabot.yml` (pip, npm, pub, github-actions).
8. **Jobs `docker-*`** : créer `backend/Dockerfile` (+ `.dockerignore`, non-root, config par env) et
   `web-dashboard/Dockerfile` (multi-stage, `standalone`, non-root, `.dockerignore`) ; buildx +
   `build-push-action` avec `push: false` (build-seul) ; smoke test `GET /health` optionnel.
9. **(Si retenu) lint backend** : ajouter `[tool.ruff]` à `pyproject.toml` et `ruff` à l'extra `dev`.
10. **(Optionnel) ADR-0010** : rédiger `docs/adr/0010-ci-cd-docker-packaging.md` ; mettre à jour
    `docs/adr/README.md`.
11. **Doc** : mettre à jour `README.md` (§4 + section CI applicative) ; noter Docker dans les READMEs de
    paquet concernés ; *(optionnel)* CONTRIBUTING.
12. **Protection de branche** : définir la **liste des status checks requis** et l'appliquer sur `main`
    (réglage dépôt, hors versionnement) ; documenter l'interaction avec la phase `merge` ADW.
13. **Vérifier les critères d'acceptation** : jobs **séparés** mobile/web/backend ; lint + tests + build par
    paquet ; **scan de dépendances** actif ; **artefacts** produits ; **images Docker** construites ; CI
    **verte requise avant merge** ; aucun secret committé/journalisé ; aucun marqueur « généré par IA » ;
    `adw-sdlc.yml` non régressé.
