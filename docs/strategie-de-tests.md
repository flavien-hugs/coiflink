# Stratégie de tests & test gate ADW

> Document de référence de la stratégie de tests de CoifLink (issue **#6**). Il définit la pyramide de
> tests (unitaire → intégration → e2e), **quelle couche tourne où** (gate local ADW / CI applicative #4 /
> e2e #50), et documente le **test gate** du pipeline (`MX_AGENT_TEST_CMD` → [`scripts/test-gate.sh`](../scripts/test-gate.sh)).

## 1. Trois lieux d'exécution des tests

Les tests tournent à trois endroits complémentaires, du plus rapide/local au plus lourd/intégré :

| Lieu | Quand | Portée | Objectif |
| --- | --- | --- | --- |
| **Gate ADW** (`MX_AGENT_TEST_CMD`) | pendant un run du pipeline, avant PR et avant merge | **sous-ensemble unitaire rapide et déterministe** des 3 paquets | garde-fou local : la boucle `resolve` corrige les régressions *avant* de pousser |
| **CI applicative** ([`ci.yml`](../.github/workflows/ci.yml), #4) | à chaque PR / push `main` | unitaire **+ intégration** (Alembic/PostgreSQL 16) + lint + build + images Docker | référence bloquante avant merge |
| **e2e** (#50) | job `backend` de [`ci.yml`](../.github/workflows/ci.yml) (livré) | parcours critiques §5 au **niveau HTTP backend** (routers → cas d'usage → DB) | non-régression bout-en-bout |

Le **gate ADW est un sous-ensemble rapide de la CI** : il exécute exactement les mêmes commandes de test
unitaire (`pytest` / `npm test` / `flutter test`), pas les étapes lourdes (round-trip Alembic, build APK,
images Docker) qui ralentiraient chaque itération de la boucle d'auto-réparation.

## 2. La pyramide de tests

### Unitaire — base de la pyramide (rapide, sans I/O externe)

Fonctions pures et adaptateurs testés avec des *fakes* (cf. architecture hexagonale
[ADR-0008](adr/0008-architecture-hexagonale.md)). **Tourne dans le gate ADW et en CI.**

| Paquet | Stack (ADR) | Commande | Runner | Exemple de test trivial présent |
| --- | --- | --- | --- | --- |
| [`backend/`](../backend/README.md) | FastAPI ([0003](adr/0003-backend-fastapi.md)) | `pytest` | pytest | `backend/tests/test_health.py`, `test_session.py`, `test_secrets_policy.py` |
| [`web-dashboard/`](../web-dashboard/README.md) | Next.js ([0002](adr/0002-web-gerant-admin-nextjs.md)) | `npm test` (`vitest run`) | vitest | `web-dashboard/test/site.test.ts` |
| [`app-mobile/`](../app-mobile/README.md) | Flutter ([0001](adr/0001-app-mobile-flutter.md)) | `flutter test` | flutter test | `app-mobile/test/widget_test.dart` |

Ce sont **exactement** les commandes exécutées par les jobs `backend` / `web` / `mobile` de la CI
(chacune dans son `working-directory:`), garantissant la parité local ↔ CI.

### Intégration — dépend d'infra (PostgreSQL 16, Redis 7)

Round-trip des migrations Alembic et tests de routes API sur une base de test
([`deploy/docker-compose.yml`](../deploy/), [ADR-0009](adr/0009-orm-migrations-sqlalchemy-alembic.md)).
**Référence en CI** (job `backend` : service `postgres:16` + round-trip `alembic upgrade/downgrade`).
**Exclus du gate ADW par défaut** (trop lents / dépendants d'infra pour la boucle `resolve`). Un
sous-ensemble local reste possible quand `docker compose` est démarré, mais n'est **pas imposé** par le gate.

### End-to-end — parcours critiques (§5)

Flux complets bout-en-bout. **Périmètre de l'issue #50** — **livré** : les trois parcours critiques du
PRD §5 (réservation client §5.1, gestion RDV gérant §5.2, encaissement §5.3) sont exercés en **un seul
parcours continu** partagé (le même salon, le même client, le même RDV) au **niveau HTTP du backend**
(`TestClient` → routers → cas d'usage → dépôts SQL → PostgreSQL) — le contrat que consomment web/mobile,
cohérent avec 100 % des `*_e2e.py` existants. Ils **câblent** ce que les suites par-fonctionnalité
vérifient isolément, pour attraper les régressions d'**intégration inter-modules**. Fichier :
[`backend/tests/test_critical_journeys_e2e.py`](../backend/tests/test_critical_journeys_e2e.py).

L'e2e d'**IU** (Playwright web / `integration_test` Flutter) n'est **pas** dans le périmètre de #50 : aucune
infra de ce type n'existe et la CI n'orchestre pas d'app vivante — extension possible hors périmètre.
**Jamais dans le gate ADW local** (pas de `DATABASE_URL` → suites `*_e2e.py` skippées).

Comme les autres `*_e2e.py`, la suite **s'exécute déjà** dans le job `backend` de `ci.yml` (où
`DATABASE_URL` est défini au niveau du job et `alembic upgrade head` précède `pytest`) — **sans aucune
modification du workflow** : sa réussite est donc une **condition de merge** (le job `backend` est un
status check requis). Skip propre sans `DATABASE_URL` (fixture + `skipif`), plage de téléphones réservée
(`+225068999`), nettoyage FK-safe avant/après chaque test.

### Tests de sécurité — authz / JWT / brute-force / journalisation (#51, §11)

Suite de sécurité **transverse** qui vérifie le socle §11 « comme un tout », du point de vue d'un
attaquant, sur toute la surface d'API montée. Deux niveaux, cohérents avec la pyramide ci-dessus :

- **Rapide (gate ADW + CI, sans base)** — matrice **rôle × route réelle** dérivée de `ROLE_PERMISSIONS`
  (`test_security_authz_matrix.py` : rôle non habilité → `403` générique, sans jeton → `401`, `role`
  d'inscription ignoré) ; propriétés **JWT/refresh** consolidées (`test_security_jwt.py` : `alg=none`,
  confusion d'algorithme, signature altérée, claims manquants, expiration, mauvais `type`, `503` sans
  secret) ; **non-divulgation** & régression de `PUBLIC_ROUTE_PATHS` (`test_security_no_leak.py`).
- **e2e (CI job `backend`, PostgreSQL requis)** — **isolation inter-salons** sur routes réelles
  (`test_security_isolation_e2e.py` : lecture/écriture inter-salons → `403` sans écriture, anti-oracle,
  filtre `client_id` étranger → vide, révocation immédiate, rotation du refresh) ; **brute-force** HTTP de
  `POST /auth/login` (`test_security_bruteforce_e2e.py` : `429` + `Retry-After`, `401` générique identique,
  succès qui réinitialise, verrou par identifiant) ; **journalisation** §11.3/§11.4
  (`test_security_audit_e2e.py` : présence des entrées sensibles, atomicité échec → 0 entrée, **invariant
  de non-fuite** balayant `audit_logs`). #51 **teste l'existant** : les actions §11.4 non encore câblées
  (`Connexion`, `Création rendez-vous`, `Création employé`, `Désactivation salon`) ne sont pas assertées.

Plages de téléphones **réservées** aux e2e de sécurité (distinctes des autres suites) : `+225089991`
(isolation), `+225089992` (brute-force), `+225089993` (audit). Skip propre sans `DATABASE_URL`, nettoyage
FK-safe (`audit_logs`/`notifications`/`campaigns`/`customer_profiles` avant `salons`/`users`).

## 3. Le test gate ADW (`MX_AGENT_TEST_CMD`)

Le pipeline ADW ([`adw_sdlc/`](../adw_sdlc/README.md)) lit `MX_AGENT_TEST_CMD` (ou `--test-cmd`) et exécute
cette commande à deux moments : dans la phase `resolve` (auto-réparation jusqu'à `--max-resolve` tentatives)
et comme **gate pré-merge** (aucun merge tant qu'il n'est pas vert). Une valeur **vide** désactive le gate
(traité comme vert) — c'était l'état avant #6.

### `scripts/test-gate.sh` — point d'entrée agrégé

Le gate est découpé par simple séparation argv (guillemets seulement) **puis lancé sans shell** : aucun
opérateur (`&&`, `;`, `|`, `>`, glob, `$VAR`) n'est interprété. Un enchaînement multi-paquets ne peut donc
pas s'écrire en one-liner dans `MX_AGENT_TEST_CMD` ; toute la logique vit dans un script committé,
[`scripts/test-gate.sh`](../scripts/test-gate.sh), invoqué via une commande argv triviale.

Le wrapper :

- **se réancre à la racine du dépôt** quel que soit le répertoire d'appel (comportement identique depuis la
  racine ou depuis `adw_sdlc/`) ;
- **enchaîne les paquets sélectionnés** avec les mêmes commandes que la CI (`pytest` / `npm test` /
  `flutter test`), chacun dans son répertoire ;
- **agrège les codes de sortie** : `0` si tous passent, `≠ 0` si au moins un échoue (il n'interrompt pas au
  premier échec — tous les paquets s'exécutent et chaque `rc` est rapporté) ;
- est **fail-closed** : si le toolchain d'un paquet *sélectionné* est absent, le gate **échoue** (jamais un
  vert silencieux).

### Sélectionner les paquets — `TEST_GATE_PACKAGES`

Variable optionnelle (mots séparés par des espaces). **Défaut : les trois paquets** (parité CI). Restreindre
le gate aux paquets dont le toolchain est présent dans l'environnement d'exécution du pipeline :

```bash
scripts/test-gate.sh                                  # backend + web + mobile (défaut)
TEST_GATE_PACKAGES="backend" scripts/test-gate.sh     # backend seul (Python présent)
TEST_GATE_PACKAGES="backend web" scripts/test-gate.sh # backend + web
```

### Câblage dans `scripts/adw.env`

`scripts/run-issue.sh` fait `cd adw_sdlc/` avant de lancer l'orchestrateur : le cwd du gate est donc
`adw_sdlc/`. Le wrapper se réancrant lui-même, il suffit de le référencer relativement à ce cwd :

```bash
# scripts/adw.env (gitignoré — jamais committé)
MX_AGENT_TEST_CMD=bash ../scripts/test-gate.sh
# éventuellement, pour scoper : TEST_GATE_PACKAGES=backend
```

> **Contrainte de cwd :** cet exemple suppose le point d'entrée documenté (`run-issue.sh`, cwd `adw_sdlc/`).
> Lancé depuis un autre répertoire, ajustez le chemin du wrapper (le *contenu* du gate, lui, ne dépend pas
> du cwd). L'exemple versionné et commenté est dans [`scripts/adw.env.example`](../scripts/adw.env.example).

## 4. Tableau « quoi tourne où »

| Couche de test | Gate ADW (`MX_AGENT_TEST_CMD`) | CI applicative (#4) | e2e (#50 / #51) |
| --- | :---: | :---: | :---: |
| Unitaire backend (`pytest`) | ✅ | ✅ | — |
| Unitaire web (`vitest`) | ✅ | ✅ | — |
| Unitaire mobile (`flutter test`) | ✅ | ✅ | — |
| Lint (`ruff` / `eslint` / `flutter analyze`) | — | ✅ | — |
| Intégration (Alembic + PostgreSQL 16) | — (sous-ensemble local optionnel) | ✅ | — |
| Build (wheel / `next build` / APK) | — | ✅ | — |
| Images Docker (build + smoke test) | — | ✅ | — |
| End-to-end parcours critiques (§5, backend-HTTP) | — | ✅ (job `backend`) | ✅ |
| Sécurité rapide (authz / JWT / non-divulgation, §11, #51) | ✅ | ✅ | — |
| Sécurité e2e (isolation / brute-force / audit, §11, #51) | — | ✅ (job `backend`) | ✅ |
| **Performance / charge (§12.1, #52)** | — | — | job **`perf`** opt-in (`perf.yml`), **non requis** |

> **Ligne « performance »** : les tests de charge (#52) ne sont **ni** dans le gate ADW **ni** dans la CI
> applicative requise (`ci.yml`). Ils tournent dans un **job dédié opt-in** ([`perf.yml`](../.github/workflows/perf.yml),
> `workflow_dispatch`/nocturne) — voir [§4bis](#4bis-tests-de-performance-52-1221).

## 4bis. Tests de performance (#52, §12.1)

La suite de **charge** (#52) mesure la latence des **endpoints critiques** contre un **serveur réel**
(uvicorn + PostgreSQL 16 peuplée d'un jeu représentatif), **jamais** via `TestClient` (transport ASGI
en-processus mono-thread : ne mesure ni la latence réelle sous concurrence, ni le pool de connexions).
Elle confronte le **p95** serveur (régime établi, warm-up exclu) aux **budgets §12.1** — recherche salon
`< 2 s`, création de RDV `< 3 s`, dashboard gérant agrégé `< 3 s`, API générale `< 3 s` — et émet un
rapport PASS/WARN/FAIL (CSV/JSON/Markdown).

- **Où** : harnais isolé sous [`backend/perf/`](../backend/perf/README.md) — **hors** du package
  `coiflink_api`, **hors** de `backend/tests/` (non collecté par `pytest`), **hors** de l'image Docker,
  **hors** du test gate ADW. Dépendance de dev **optionnelle** : extra `perf` (`httpx` + `locust`).
- **Exécution** : `DATABASE_URL=… python -m perf.run` (uvicorn local, secret JWT **de test**) ou
  `PERF_TARGET_URL=…` (cible externe). Job CI **opt-in** `perf.yml` (jamais sur chaque PR, jamais status
  check requis : la variabilité des runners partagés rendrait un seuil dur flaky).
- **Verdict de référence** : viser **staging** (matériel stable, proche prod) via `PERF_TARGET_URL` ; le
  job CI local reste un **indicateur de dérive**. Mode **informatif** par défaut (un FAIL n'échoue pas le
  job, sauf `--strict`).
- **Plage de téléphones réservée** : `+225059990…` (distincte de toutes les plages e2e), pour un
  **nettoyage FK-safe** (`notifications`/`campaigns` avant `appointments`/`payments`/`cash_journal`/
  `salons`/`users` — mémoire `notifications-fk-restrict`). Secret JWT **de test** uniquement ; **aucun**
  secret ni PII dans la sortie, le rapport ou les logs (le rapport passe `assert_no_pii`, cohérent §6).
- **Que faire en cas de FAIL** : #52 **mesure**, il n'optimise pas — documenter le dépassement et ouvrir
  une **issue d'optimisation dédiée** (index, N+1, pagination, cache Redis M5), sans modifier la prod.

Les **fonctions pures** du harnais (budgets, verdict PASS/WARN/FAIL, sérialisation du rapport, mix de
trafic) sont **déterministes** et couvertes par des tests unitaires rapides sous `backend/tests/`
(collectés par `pytest`, **sans** exécuter de charge) — sûrs dans le gate et la CI.

## 5. Comment ajouter un test

- **backend** (`pytest`) : ajouter un fichier `backend/tests/test_*.py`. Tests unitaires sans I/O
  (fonctions pures, adaptateurs avec fakes). Les tests base/intégration réels tournent en CI contre
  PostgreSQL 16.
- **backend e2e / parcours** (`pytest`, PostgreSQL requis) : ajouter un fichier
  `backend/tests/test_*_e2e.py` (p. ex. `test_critical_journeys_e2e.py` pour les parcours §5). Convention
  de sélection = **le nom de fichier** `*_e2e.py` + un `@pytest.mark.skipif(not DATABASE_URL, …)` sur la
  classe et un `pytest.skip(...)` en fixture (skip propre sans base). Réserver une **plage de téléphones
  distincte** (grep les préfixes déjà pris) et **nettoyer FK-safe** avant/après chaque test
  (`notifications`/`campaigns` avant `appointments`/`salons`/`users` — mémoire `notifications-fk-restrict`).
  Jeton **JWT de test factice** injecté par `app.state` ; argent en chaîne `NUMERIC(12,2)`. Lancer :
  `DATABASE_URL=… alembic upgrade head && DATABASE_URL=… pytest tests/test_critical_journeys_e2e.py -v`.
  Ne **jamais** journaliser jeton, mot de passe ni téléphone en sortie (§6).
- **web-dashboard** (`vitest`) : ajouter un `web-dashboard/test/*.test.ts`. Composants, hooks, utilitaires.
- **app-mobile** (`flutter test`) : ajouter un `app-mobile/test/*_test.dart`. Widgets et unités.

Après ajout, valider localement avec le gate : `TEST_GATE_PACKAGES="<paquet>" scripts/test-gate.sh`.

## 6. Sécurité — jamais de secret ni de PII dans la sortie de test

En cas d'échec, la sortie du gate est **tronquée et transmise à l'agent** (phase `resolve`). Les tests ne
doivent donc **jamais journaliser de secret, jeton ou donnée personnelle** (invariant PRD §11, vérifié par
[`backend/tests/test_secrets_policy.py`](../backend/tests/test_secrets_policy.py)). De même, **aucun secret
ne doit être embarqué dans `MX_AGENT_TEST_CMD`** : la valeur apparaît dans les logs de progression
(`run-issue.sh`, orchestrateur). Le gate reste une simple invocation d'outils de test.
