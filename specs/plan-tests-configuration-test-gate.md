# Plan de tests & configuration du test gate ADW (`MX_AGENT_TEST_CMD`)

> Spécification de planification pour l'issue GitHub **#6 — Plan de tests & configuration du test gate
> ADW** (`docs` · `infra` · Should · Effort S · PRD §18 Sprint 0). **Dépend de #1** (stack figée par les
> ADR — satisfaite : [ADR-0001…0003](../docs/adr/README.md) tranchent Flutter / Next.js / FastAPI) et
> **#4** (CI/CD applicative — satisfaite : [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
> exécute lint + tests + build par paquet). **Cette spec ne produit pas de code.** Elle définit la
> stratégie de tests et décrit le câblage concret du test gate à réaliser dans une phase
> d'implémentation ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, specs). Les en-têtes de
> section ci-dessous sont conservés en anglais car ils sont attendus par le gabarit du pipeline ADW ; le
> contenu livré (docs, scripts, commentaires) reste en français hors identifiants techniques.

## Problem Statement

Le pipeline ADW (`adw_sdlc/`) possède un **test gate** intégré — la variable `MX_AGENT_TEST_CMD` — mais il
n'est **pas câblé** : dans `scripts/adw.env.example` et `scripts/adw.env`, `MX_AGENT_TEST_CMD=` est vide, et
la valeur par défaut du control plane est vide (`DEFAULT_TEST_CMD = ''`, `adw_sdlc/src/orchestrator.ts`).
Un gate vide est **ignoré et traité comme vert** (`resolveLoop` retourne `true` sans rien exécuter,
`finalizeGates` ne contribue aucun gate de test). En conséquence :

- pendant un run d'issue, la phase `tests`/`resolve` **ne vérifie jamais** que les tests du dépôt passent :
  le pipeline peut ouvrir puis (avec `--yes`) **merger une PR sans exécuter un seul test** en local ;
- le seul garde-fou de test actuel est la **CI GitHub Actions** (`ci.yml`, #4), qui s'exécute *après* le
  push — trop tard pour que la boucle d'auto-réparation (`resolve`) du pipeline corrige les régressions
  avant de pousser ;
- il n'existe **aucun document** décrivant la stratégie de tests (unitaire / intégration / e2e), ni ce qui
  doit tourner *où* (gate local ADW vs CI vs e2e #50).

Le besoin (issue #6, critères d'acceptation) : **définir la stratégie de tests** et **câbler
`MX_AGENT_TEST_CMD`** de sorte qu'il soit **documenté et fonctionnel** — *un test trivial passe via le
gate* (et, symétriquement, un test qui échoue fait échouer le gate).

## Goals

- **Documenter la stratégie de tests** du projet (pyramide unitaire → intégration → e2e) : pour chacun des
  trois paquets (`app-mobile/` Flutter, `web-dashboard/` Next.js, `backend/` FastAPI), quels tests
  existent, où ils vivent, et **quelle couche tourne où** — gate local ADW, CI applicative (#4), e2e (#50).
- **Câbler un `MX_AGENT_TEST_CMD` fonctionnel** dans `scripts/adw.env` (et son gabarit
  `scripts/adw.env.example`) qui, exécuté par l'orchestrateur, retourne **code 0 quand les tests passent**
  et **≠ 0 quand un test échoue** — satisfaisant le critère « un test trivial passe via le gate ».
- **Respecter les contraintes d'exécution réelles du gate** (vérifiées dans le code, cf. *Relevant
  Repository Context*) : la commande est découpée par `shellSplit` (guillemets simples/doubles uniquement)
  puis lancée par `spawnSync` **sans shell** (donc pas de `&&`, `;`, `|`, `>`, glob ni expansion de
  variables) et **sans `cwd` explicite** (le répertoire courant est hérité de l'orchestrateur).
- **Fournir un point d'entrée de gate agrégé** (script wrapper) capable d'enchaîner les tests des paquets
  concernés en une seule commande argv-safe, avec un **code de sortie agrégé** (échoue si un paquet échoue).
- **Aligner** la commande du gate sur les commandes de test déjà exécutées par la CI (`ci.yml`) pour éviter
  toute divergence local ↔ CI.
- **Valider** de bout en bout : un test trivial vert → gate vert ; une régression volontaire → gate rouge
  qui déclenche la boucle `resolve`.

## Non-Goals

- **Écrire de nouveaux tests métier** ou augmenter la couverture des paquets : les squelettes exposent déjà
  des tests triviaux passants (widget Flutter, `vitest`, `pytest` santé). #6 câble le gate, il n'écrit pas
  la suite de tests fonctionnelle (celle-ci arrive avec les features M1+ et le durcissement **#50**).
- **Les tests end-to-end cross-composants** (mobile/web ↔ backend ↔ DB) : périmètre explicite de **#50**
  (« Tests e2e intégrés à la CI »). Cette spec les *positionne* dans la stratégie mais ne les câble pas dans
  le gate local (trop lents / dépendants d'infra pour la boucle `resolve`).
- **Modifier la CI applicative** (`ci.yml`, #4) : elle reste la référence des tests « lourds »
  (intégration Alembic/PostgreSQL, build APK, images Docker). Le gate ADW en est un **sous-ensemble rapide**.
- **La protection de branche `main`** / status checks requis : réglage dépôt non versionné (cf. ADR-0010),
  hors périmètre.
- **Changer les runners** ou le contrat d'état inter-langage (`adw/state.schema.json`).

## Relevant Repository Context

### Où et comment le gate est consommé (vérifié dans le code)

- **Lecture de la valeur** — `adw_sdlc/src/cli.ts:298` :
  `const testCmd = str('--test-cmd') ?? env['MX_AGENT_TEST_CMD'];` → propagé dans `opts.testCmd`. Le flag
  `--test-cmd` a priorité sur la variable d'environnement.
- **Défaut vide** — `adw_sdlc/src/orchestrator.ts` : `DEFAULT_TEST_CMD = ''` ; un `testCmd` vide/`trim()===''`
  fait que `resolveLoop` logue *« no test command configured; skipping test gate »* et **retourne `true`**
  (traité comme vert), et `finalizeGates` **n'ajoute aucun gate de test**.
- **Deux points d'exécution** du gate :
  1. **`resolveLoop`** (phase `tests`/`resolve`, `orchestrator.ts:325`) : exécute le gate ; s'il échoue,
     invoque l'agent pour réparer, jusqu'à `--max-resolve` tentatives (défaut **3**). S'il reste rouge → le
     run échoue avant la PR.
  2. **`finalizeAndMerge` / `finalizeGates`** (`orchestrator.ts:626`, `:666`) : avant commit/push/merge, le
     gate de test **puis** les gates supplémentaires `MX_AGENT_FINALIZE_GATES` (séparés par des retours à la
     ligne) doivent **tous** retourner 0, sinon `AdwError('pre-merge gate failed: …')` — pas de merge.
- **Découpage & exécution** (contrainte structurante) :
  - `shellSplit(command)` (`adw_sdlc/src/common.ts:139`) ne gère **que** le groupement par guillemets
    simples/doubles — **aucun opérateur shell** (`&&`, `;`, `|`, `>`, `*`, `$VAR`).
  - `capture(cmd)` (`adw_sdlc/src/exec.ts:96`) fait `spawnSync(bin, args, { encoding: 'utf8' })` : **pas de
    `shell: true`, pas de `cwd`**. Le gate hérite donc du `process.cwd()` de l'orchestrateur. Un binaire
    absent → code **127** synthétique (donc *échec* — le gate n'est jamais « silencieusement vert » par
    binaire manquant).
- **Répertoire courant effectif** : `scripts/run-issue.sh` fait `cd "$adw_dir"` puis
  `exec npx tsx src/cli.ts` — le `process.cwd()` de l'orchestrateur est donc **`adw_sdlc/`**, pas la racine du
  dépôt (aucun `process.chdir` dans `adw_sdlc/src`). Les opérations git fonctionnent depuis ce sous-répertoire
  (git remonte jusqu'à `.git`), **mais une commande de gate à chemin relatif se résout depuis `adw_sdlc/`**.
  → C'est la contrainte centrale de conception de cette issue (voir *Proposed Implementation* et *Risks*).
- **Environnement du gate** : `runCmd` exécute les gates avec l'environnement hérité normal (commentaire
  `orchestrator.ts:185` : « gate commands are build tools … legitimately use the normal environment »). La
  frontière de secrets `MX_AGENT_*` / `MATRIX_*` s'applique à l'**agent**, pas aux outils de build du gate.

### Paquets et tests existants (squelettes runnables — #2/#3)

| Paquet | Stack (ADR) | Commande de test | Test trivial présent |
| --- | --- | --- | --- |
| [`app-mobile/`](../app-mobile/README.md) | Flutter ([0001](../docs/adr/0001-app-mobile-flutter.md)) | `flutter test` | `app-mobile/test/widget_test.dart` |
| [`web-dashboard/`](../web-dashboard/README.md) | Next.js ([0002](../docs/adr/0002-web-gerant-admin-nextjs.md)) | `npm test` → `vitest run` (`package.json`) | `web-dashboard/test/` (+ `vitest.config.ts`) |
| [`backend/`](../backend/README.md) | FastAPI ([0003](../docs/adr/0003-backend-fastapi.md)) | `pytest` | `backend/tests/test_health.py`, `test_session.py`, `test_secrets_policy.py` |

La CI applicative (`ci.yml`, #4) exécute déjà ces commandes, chacune avec un `working-directory:` dédié
(`backend`, `web-dashboard`, `app-mobile`), plus lint et build. Le gate ADW doit refléter **les mêmes
commandes de test** pour éviter toute divergence.

### Documentation existante à mettre à jour

- `README.md` §5 et §7 affichent explicitement que le gate « reste à câbler en #6 » / « tant qu'il est vide,
  le gate est ignoré (traité comme vert) » — à corriger une fois câblé.
- `adw_sdlc/README.md` (tableau *Configuration*) documente déjà `MX_AGENT_TEST_CMD` génériquement.
- `scripts/adw.env.example` porte le commentaire et la ligne `MX_AGENT_TEST_CMD=` (vide) à renseigner.

## Proposed Implementation

Approche recommandée en trois volets : **(A)** un script wrapper de gate agrégé, **(B)** le câblage de
`MX_AGENT_TEST_CMD`, **(C)** un document de stratégie de tests. Un point de décision structurant (répertoire
d'exécution du gate) est isolé ci-dessous.

### A. Script wrapper de gate agrégé — `scripts/test-gate.sh`

Parce que le gate est exécuté **sans shell** et **en une seule commande argv**, un enchaînement multi-paquets
(`flutter test` + `npm test` + `pytest`) ne peut **pas** s'écrire en one-liner dans `MX_AGENT_TEST_CMD`. La
solution robuste est un script wrapper committé, exécutable, qui :

1. **S'ancre à la racine du dépôt indépendamment du cwd** — p. ex. `cd "$(cd "$(dirname "$0")/.." && pwd)"`
   (ou `git rev-parse --show-toplevel`), de sorte que le *contenu* du gate ne dépende pas du répertoire
   d'appel.
2. **Enchaîne les tests de chaque paquet** dans son propre répertoire, en réutilisant **exactement** les
   commandes de `ci.yml` :
   - `backend/` : `pytest`
   - `web-dashboard/` : `npm test` (soit `vitest run`)
   - `app-mobile/` : `flutter test`
3. **Agrège les codes de sortie** : exécute les paquets sélectionnés, mémorise le premier échec, et retourne
   **≠ 0 si au moins un paquet échoue**, **0 si tous passent** (`set -euo pipefail` avec collecte explicite du
   `rc` par paquet, pour ne pas s'arrêter au premier et rapporter tous les échecs).
4. **Gère l'absence de toolchain de façon explicite** (décision à confirmer, voir *Risks*) : soit
   *fail-closed* (un toolchain attendu absent = échec, le plus sûr), soit *skip-with-warning* filtré par une
   variable (p. ex. `TEST_GATE_PACKAGES="backend web mobile"`), pour permettre un gate scopé au(x) paquet(s)
   dont le toolchain est présent dans l'environnement d'exécution du pipeline.
5. **N'imprime jamais de secret ni de PII** (les tests santé/secrets existants ne doivent rien logger de
   sensible ; le stdout/stderr du gate est tronqué et transmis à l'agent en cas d'échec — cf. *Security*).

> Emplacement alternatif possible : un `Makefile`/`justfile` racine avec une cible `test`. Le script
> `scripts/*.sh` est privilégié pour rester cohérent avec l'outillage existant (`run-issue.sh`,
> `check-adw-sdlc-env.sh`) et sans nouvelle dépendance (`make`/`just`).

### B. Câblage de `MX_AGENT_TEST_CMD`

Renseigner la variable dans `scripts/adw.env` (fichier local gitignoré) et documenter l'exemple recommandé
dans `scripts/adw.env.example` (versionné, sans valeur secrète).

**Choix du répertoire d'exécution du gate** — deux options, à trancher (voir *Risks*) :

- **Option 1 (recommandée) — rendre le gate robuste au cwd via une petite évolution du control plane** :
  faire exécuter les gates (test + finalize) depuis la racine du dépôt en passant `cwd: REPO_ROOT` à
  `spawnSync` (dans `defaultDeps().runCmd` / la boucle `finalizeGates`, `adw_sdlc/src/`). Alors
  `MX_AGENT_TEST_CMD=scripts/test-gate.sh` (ou `bash scripts/test-gate.sh`) fonctionne quel que soit le point
  d'entrée, et **tous les exemples existants** (`npm run lint`, `pytest`, …) prennent enfin leur sens attendu
  « depuis la racine ». Cette évolution touche `adw_sdlc/` (control plane, CI `adw-sdlc.yml`, tests
  d'isolation de secrets) : à confirmer car #6 est étiquetée `docs infra`.
- **Option 2 — aucun changement de code, invocation relative au cwd de `run-issue.sh`** : puisque
  `run-issue.sh` garantit `cwd = adw_sdlc/`, régler `MX_AGENT_TEST_CMD=bash ../scripts/test-gate.sh` (le
  wrapper se réancre ensuite à la racine). Fonctionne pour le point d'entrée documenté, mais **fragile** si
  l'orchestrateur est lancé depuis un autre répertoire ; à documenter comme tel.

Dans les deux cas, le wrapper (A) neutralise la dépendance au cwd pour le *contenu* du gate ; le point de
décision ne porte que sur la **résolution du chemin du wrapper**.

Pour un premier câblage **minimal et sûr** satisfaisant strictement le critère d'acceptation (« un test
trivial passe via le gate ») avec le moins d'hypothèses sur les toolchains présents, on peut démarrer avec le
seul paquet **backend** (`pytest`, toolchain Python le plus probablement présent dans l'environnement ADW) —
via le wrapper filtré `TEST_GATE_PACKAGES=backend` — puis élargir à web/mobile une fois leurs toolchains
garantis dans l'environnement d'exécution. Cet arbitrage (gate agrégé 3 paquets vs gate backend d'abord) est
une décision à confirmer.

### C. Document de stratégie de tests — `docs/strategie-de-tests.md`

Nouveau document (français) définissant la pyramide et l'exécution :

- **Unitaire** (base de la pyramide, rapide, sans I/O externe) : `pytest` (fonctions pures, adaptateurs avec
  fakes — cf. architecture hexagonale [ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) ; `vitest`
  (composants, hooks, utilitaires) ; `flutter test` (widgets/unités). → **tournent dans le gate ADW et en CI**.
- **Intégration** (dépend d'infra : PostgreSQL 16, Redis 7 via [`deploy/docker-compose.yml`](../deploy/)) :
  round-trip Alembic + tests de routes API sur DB de test (déjà partiellement en CI, #4). → **CI de
  référence** ; **exclus du gate ADW par défaut** (trop lents/infra-dépendants pour la boucle `resolve`), avec
  possibilité d'un sous-ensemble local quand `docker compose` est up (documenté, non imposé).
- **End-to-end** (cross-composants) : périmètre **#50**, intégrés à la CI. → **jamais dans le gate ADW local**.
- **Tableau « quoi tourne où »** : gate ADW (`MX_AGENT_TEST_CMD`) = sous-ensemble unitaire rapide et
  déterministe ; CI (#4) = unitaire + intégration + build + Docker ; #50 = e2e. Plus une section « comment
  ajouter un test » par paquet.

L'opportunité d'un **ADR-0012 « stratégie de tests & test gate »** (le dépôt est très ADR-orienté) est à
confirmer ; par défaut, un document sous `docs/` + mises à jour README suffisent pour une issue Effort S.

## Affected Files / Packages / Modules

**À créer :**

- `scripts/test-gate.sh` — wrapper de gate agrégé (exécutable, `#!/usr/bin/env bash`, réancré à la racine).
- `docs/strategie-de-tests.md` — document de stratégie de tests (pyramide + « quoi tourne où »).
- *(optionnel, à confirmer)* `docs/adr/0012-strategie-de-tests-test-gate.md` — ADR dédié.

**À modifier :**

- `scripts/adw.env.example` — renseigner un exemple concret de `MX_AGENT_TEST_CMD` + commentaires sur les
  contraintes (pas de shell / cwd / wrapper).
- `scripts/adw.env` — *(fichier local gitignoré)* régler la valeur effective de `MX_AGENT_TEST_CMD` **sans
  jamais committer ce fichier**.
- `README.md` — §5 (note « test gate reste à câbler en #6 ») et §7 (bloc « tant qu'il est vide, le gate est
  ignoré ») : marquer le gate comme **câblé**, pointer vers `docs/strategie-de-tests.md` et
  `scripts/test-gate.sh`.
- *(éventuel)* `adw_sdlc/README.md`, `docs/adr/README.md` — liens vers le nouveau doc/ADR.

**À modifier uniquement si l'Option 1 (cwd du gate) est retenue :**

- `adw_sdlc/src/orchestrator.ts` (`defaultDeps().runCmd`, boucle `finalizeGates`) et/ou `adw_sdlc/src/exec.ts`
  (`capture`) — exécuter les gates avec `cwd: REPO_ROOT` ; plus les tests associés (`adw_sdlc/test/`) et la CI
  du control plane (`.github/workflows/adw-sdlc.yml`).

**À lire (référence, non modifiés) :**

- `adw_sdlc/src/cli.ts`, `adw_sdlc/src/orchestrator.ts`, `adw_sdlc/src/common.ts`, `adw_sdlc/src/exec.ts`,
  `scripts/run-issue.sh`, `.github/workflows/ci.yml`, `app-mobile/`, `web-dashboard/`, `backend/`,
  `specs/pipeline-ci-cd-github-actions.md`.

## API / Interface Changes

- **Ligne de commande** : aucune nouvelle option. `--test-cmd` / `MX_AGENT_TEST_CMD` existent déjà ; #6 les
  *renseigne*, il ne les crée pas.
- **Nouveau script public** : `scripts/test-gate.sh` devient une **interface CLI** du dépôt (point d'entrée
  de test agrégé) — à documenter : usage, code de sortie (0 = tous verts, ≠ 0 sinon), et variable optionnelle
  de sélection de paquets (p. ex. `TEST_GATE_PACKAGES`).
- **Option 1 (si retenue)** : changement de comportement interne au control plane (cwd des gates), sans
  nouvelle option CLI ; à documenter dans `adw_sdlc/README.md`.
- Aucun endpoint réseau ni API applicative touchés.

## Data Model / Protocol Changes

None. Aucune modification de schéma, de stockage, de persistance, ni du contrat d'état inter-langage
(`adw/state.schema.json`). Le fichier `scripts/adw.env` n'est pas un format de données versionné (config
locale gitignorée).

## Security & Privacy Considerations

- **`scripts/adw.env` reste gitignoré** (`.gitignore:12`) : il contient des **credentials** (clé runner,
  `GH_TOKEN`) et **ne doit jamais être committé**. Le câblage de `MX_AGENT_TEST_CMD` se fait dans ce fichier
  local ; seul le **gabarit** `scripts/adw.env.example` (sans valeur secrète) est versionné. Un
  `GH_TOKEN` réel est présentement stocké dans ce fichier local — le laisser hors du dépôt ; toute exposition
  accidentelle impose une **rotation** du token.
- **Ne jamais embarquer de secret dans `MX_AGENT_TEST_CMD`** : la valeur peut apparaître dans les logs de
  progression (`run-issue.sh` echo « >> test gate: … », `orchestrator` progress). La commande doit rester une
  invocation d'outil de test, sans jeton ni mot de passe en argument.
- **Sortie du gate transmise à l'agent** : en cas d'échec, `resolveLoop` passe la sortie tronquée
  (`truncate(output)`) au prompt `resolve`. Les tests **ne doivent jamais imprimer de secret ni de PII**
  (cf. `backend/tests/test_secrets_policy.py` — invariant de non-journalisation des secrets, PRD §11) : à
  rappeler dans `docs/strategie-de-tests.md`.
- **Frontière de secrets préservée** : le gate s'exécute côté orchestrateur avec l'environnement normal (il
  n'est pas soumis à l'allowlist `MX_AGENT_*`/`MATRIX_*`) ; cette spec ne modifie **pas** la frontière
  (`safeSubprocessEnv`, `scripts/check-adw-sdlc-env.sh`). Si l'Option 1 est retenue, la modification se limite
  au `cwd` d'exécution et ne doit pas altérer la construction d'environnement des runners.
- **Résidence/hébergement** : sans objet pour un gate de test local (aucune donnée transférée hors machine).

## Testing Plan

Le gate étant lui-même l'outil de test, la « validation » porte sur son **comportement** :

- **Validation fonctionnelle (critère d'acceptation)** : exécuter le gate configuré et vérifier
  **rc 0** alors que les tests triviaux existants passent (`flutter test`, `vitest run`, `pytest`).
- **Test de régression volontaire (fail-closed)** : introduire temporairement un test échouant dans un
  paquet, exécuter le gate, vérifier **rc ≠ 0**, puis confirmer que la phase `resolve` du pipeline **déclenche
  bien** la boucle d'auto-réparation (dry-run/observation ; ne pas merger). Retirer le test après validation.
- **Test d'agrégation du wrapper** : vérifier que `scripts/test-gate.sh` retourne ≠ 0 si **n'importe quel**
  paquet échoue et 0 si tous passent (test shell léger — p. ex. `bats` ou assertions dans un job CI — ou, a
  minima, une exécution manuelle documentée dans la PR).
- **Test de robustesse au cwd** : exécuter le gate depuis la racine **et** depuis `adw_sdlc/` et confirmer un
  comportement identique (valide l'Option retenue en B).
- **Parité local ↔ CI** : confirmer que les commandes du gate sont identiques à celles de `ci.yml` (mêmes
  invocations `pytest` / `npm test` / `flutter test`).
- **Tests du control plane (uniquement si Option 1)** : ajouter/mettre à jour un test dans `adw_sdlc/test/`
  vérifiant que `runCmd`/les gates s'exécutent avec `cwd = REPO_ROOT` ; garder verts `npm run typecheck`,
  `npm test`, `npm run lint:env`.
- **Documentation** : relire `docs/strategie-de-tests.md` et les liens README (aucun lien mort).

## Documentation Updates

- **`docs/strategie-de-tests.md`** (nouveau) : pyramide unitaire/intégration/e2e, commandes par paquet,
  tableau « quoi tourne où » (gate ADW / CI #4 / e2e #50), procédure d'ajout de tests, rappel non-log de
  secrets/PII.
- **`scripts/adw.env.example`** : exemple concret de `MX_AGENT_TEST_CMD` + commentaires (pas de shell, cwd,
  usage du wrapper).
- **`README.md`** : §5 (tableau build/test + note #6) et §7 (bloc gate) — marquer le gate **câblé** et
  renvoyer vers le doc de stratégie et `scripts/test-gate.sh`.
- **`adw_sdlc/README.md`** : éventuel renvoi vers `docs/strategie-de-tests.md` depuis la ligne
  `MX_AGENT_TEST_CMD` du tableau *Configuration*.
- **`docs/adr/` + `docs/adr/README.md`** : *(optionnel, à confirmer)* ADR-0012 « stratégie de tests & test
  gate » et son entrée d'index.

## Risks and Open Questions

1. **Répertoire d'exécution du gate (décision structurante)** — le gate hérite de `process.cwd()` =
   `adw_sdlc/` sous `run-issue.sh` et n'est **pas** lancé via un shell. **Option 1** (petit changement control
   plane : `cwd: REPO_ROOT`) est la plus robuste mais élargit le périmètre au-delà de `docs infra` ;
   **Option 2** (`bash ../scripts/test-gate.sh`) évite tout code mais reste liée au cwd de `run-issue.sh`.
   **À confirmer.**
2. **Disponibilité des toolchains dans l'environnement d'exécution ADW** — un gate 3-paquets exige
   `flutter` **et** `node` **et** `python`/`pytest` présents ; un binaire absent → rc 127 (échec). Faut-il un
   gate **agrégé** (fail-closed sur toolchain manquant) ou **scopé** (`TEST_GATE_PACKAGES`, backend d'abord) ?
   **À confirmer** — impacte directement le « fonctionnel » du critère d'acceptation selon la machine.
3. **Périmètre `docs infra`** — l'issue est étiquetée `docs`/`infra` et Effort **S** ; toute modification du
   control plane (Option 1) doit être pesée contre ce cadrage. Le chemin sans code (Option 2 + wrapper) reste
   pleinement viable pour satisfaire l'AC.
4. **Coût/latence de la boucle `resolve`** — un gate lourd (build/APK/intégration DB) ralentirait chaque run
   et l'auto-réparation ; d'où le principe : le gate ADW = sous-ensemble **unitaire rapide**, l'intégration et
   l'e2e restant en CI (#4/#50). Confirmer ce découpage.
5. **`MX_AGENT_FINALIZE_GATES`** — mêmes contraintes (pas de shell, cwd, une ligne par gate). Décider si lint
   (`ruff`, `eslint`, `flutter analyze`) va dans le gate de test, dans les finalize gates, ou reste en CI
   seule. Recommandation par défaut : lint en CI (#4) uniquement pour cette issue.
6. **ADR ou simple doc ?** — trancher entre `docs/strategie-de-tests.md` seul ou + ADR-0012.

## Implementation Checklist

1. **Lire** `adw_sdlc/src/{cli.ts,orchestrator.ts,common.ts,exec.ts}`, `scripts/run-issue.sh`,
   `.github/workflows/ci.yml`, et les `README.md` des trois paquets pour confirmer les commandes de test et le
   comportement du gate décrits ici.
2. **Trancher les décisions ouvertes** (Risks 1, 2, 3, 6) : Option cwd, périmètre paquets du gate,
   `docs infra` vs changement control plane, doc seul vs + ADR.
3. **Créer `scripts/test-gate.sh`** : réancrage racine, enchaînement des paquets sélectionnés (mêmes commandes
   que `ci.yml`), **code de sortie agrégé**, gestion explicite des toolchains absents, aucune fuite de
   secret/PII ; le rendre exécutable (`chmod +x`).
4. *(Si Option 1)* **Modifier le control plane** pour exécuter les gates avec `cwd: REPO_ROOT` ; ajouter/mettre
   à jour les tests `adw_sdlc/test/` ; garder verts `npm run typecheck && npm test && npm run lint:env`.
5. **Câbler `MX_AGENT_TEST_CMD`** dans `scripts/adw.env` (local, non committé) sur le wrapper, selon l'option
   retenue (`scripts/test-gate.sh` ou `bash ../scripts/test-gate.sh`).
6. **Mettre à jour `scripts/adw.env.example`** : exemple + commentaires (pas de shell, cwd, wrapper) ; **aucune
   valeur secrète**.
7. **Rédiger `docs/strategie-de-tests.md`** (pyramide, commandes par paquet, tableau « quoi tourne où »,
   ajout de tests, rappel non-log secrets/PII) ; *(optionnel)* rédiger l'ADR-0012 + entrée d'index.
8. **Mettre à jour `README.md`** (§5 et §7) : gate marqué câblé, liens vers le doc de stratégie et le wrapper.
9. **Valider fonctionnellement** : exécuter le gate → **rc 0** (tests triviaux verts) ; introduire une
   régression volontaire → **rc ≠ 0** + boucle `resolve` déclenchée (observation, sans merge) ; retirer la
   régression.
10. **Vérifier la robustesse au cwd** (racine et `adw_sdlc/`) et la **parité local ↔ CI** des commandes.
11. **Confirmer** qu'aucun secret/PII n'apparaît dans la sortie du gate ni dans les fichiers versionnés, et que
    `scripts/adw.env` reste gitignoré.
