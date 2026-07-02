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
| **e2e** (#50) | CI dédiée (à venir) | flux cross-composants (mobile/web ↔ backend ↔ DB) | non-régression bout-en-bout |

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

### End-to-end — cross-composants

Flux complets mobile/web ↔ backend ↔ DB. **Périmètre de l'issue #50** (« Tests e2e intégrés à la CI »).
**Jamais dans le gate ADW local.** Cette stratégie les *positionne* ; #50 les câble.

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

| Couche de test | Gate ADW (`MX_AGENT_TEST_CMD`) | CI applicative (#4) | e2e (#50) |
| --- | :---: | :---: | :---: |
| Unitaire backend (`pytest`) | ✅ | ✅ | — |
| Unitaire web (`vitest`) | ✅ | ✅ | — |
| Unitaire mobile (`flutter test`) | ✅ | ✅ | — |
| Lint (`ruff` / `eslint` / `flutter analyze`) | — | ✅ | — |
| Intégration (Alembic + PostgreSQL 16) | — (sous-ensemble local optionnel) | ✅ | — |
| Build (wheel / `next build` / APK) | — | ✅ | — |
| Images Docker (build + smoke test) | — | ✅ | — |
| End-to-end cross-composants | — | — | ✅ |

## 5. Comment ajouter un test

- **backend** (`pytest`) : ajouter un fichier `backend/tests/test_*.py`. Tests unitaires sans I/O
  (fonctions pures, adaptateurs avec fakes). Les tests base/intégration réels tournent en CI contre
  PostgreSQL 16.
- **web-dashboard** (`vitest`) : ajouter un `web-dashboard/test/*.test.ts`. Composants, hooks, utilitaires.
- **app-mobile** (`flutter test`) : ajouter un `app-mobile/test/*_test.dart`. Widgets et unités.

Après ajout, valider localement avec le gate : `TEST_GATE_PACKAGES="<paquet>" scripts/test-gate.sh`.

## 6. Sécurité — jamais de secret ni de PII dans la sortie de test

En cas d'échec, la sortie du gate est **tronquée et transmise à l'agent** (phase `resolve`). Les tests ne
doivent donc **jamais journaliser de secret, jeton ou donnée personnelle** (invariant PRD §11, vérifié par
[`backend/tests/test_secrets_policy.py`](../backend/tests/test_secrets_policy.py)). De même, **aucun secret
ne doit être embarqué dans `MX_AGENT_TEST_CMD`** : la valeur apparaît dans les logs de progression
(`run-issue.sh`, orchestrateur). Le gate reste une simple invocation d'outils de test.
