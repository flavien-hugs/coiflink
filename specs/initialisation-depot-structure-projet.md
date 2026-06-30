# Initialisation du dépôt & structure du projet

> Spécification de planification pour l'issue GitHub **#2 — Initialisation du dépôt & structure du
> projet** (`infra` · Must · Effort S · PRD §18 Sprint 0). **Dépend de #1** (stack figée par les ADR).
> **Cette spec ne produit pas de code.** Elle décrit le scaffolding du monorepo à exécuter dans une
> phase d'implémentation ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR). Les en-têtes de
> section ci-dessous sont conservés en anglais car ils sont attendus par le gabarit du pipeline ADW ;
> le contenu livré (README, LICENSE, CONTRIBUTING, scaffolds) est en français (hors identifiants
> techniques et licences standard).

## Problem Statement

Le dépôt est à l'état **greenfield outillé** : le PRD, le backlog (55 issues), le pipeline ADW
(`adw_sdlc/`) et les ADR de stack (#1) existent, mais **aucun paquet applicatif n'a encore été
créé**. Le README §5 le dit explicitement :

> « Le code applicatif (`app-mobile/`, `web-dashboard/`, `backend/`…) n'existe pas encore : il sera
> créé par l'issue #2 (initialisation) une fois la stack tranchée par l'ADR #1. »

La stack étant désormais figée par les ADR `docs/adr/0001`–`0006` (Flutter, Next.js/React/TS,
FastAPI/Python, PostgreSQL + Redis, stockage S3-compatible, FCM + SMS), plusieurs issues du socle et
toutes les fonctionnalités M1→ sont **bloquées** tant que l'arborescence n'existe pas :

- **#3** (modèle de données / migrations PostgreSQL) — dépend de #1, **#2** ;
- **#4** (CI/CD GitHub Actions, jobs séparés mobile/web/backend) — dépend de **#2** ;
- **#6** (plan de tests & câblage du test gate `MX_AGENT_TEST_CMD`) — dépend de #1, #4, et présuppose
  des paquets dotés de commandes de test réelles ;
- toute issue de fonctionnalité (M1→) écrit du code dans `app-mobile/`, `web-dashboard/`, `backend/`.

Le besoin : **matérialiser l'arborescence du monorepo, une licence, des READMEs documentant le
build/test de chaque paquet, le `.gitignore` et les conventions de commits**, de sorte que (a) la
structure attendue par le backlog et le pipeline ADW existe, (b) chaque paquet expose une commande de
build/test **réelle** documentée, et (c) aucune issue suivante ne soit bloquée par l'absence de socle.

## Goals

- Créer l'arborescence de paquets manquante : **`app-mobile/`** (Flutter), **`web-dashboard/`**
  (Next.js), **`backend/`** (FastAPI). Vérifier (idempotent) la présence de `docs/`, `docs/adr/`,
  `specs/` — **déjà créés par #1**.
- Fournir un **squelette minimal mais réel** par paquet : manifeste de paquet + point d'entrée stub +
  **un test trivial qui passe** + `README.md` de paquet + `.env.example` (le cas échéant), afin que
  les commandes de build/test documentées soient **exécutables** (et non fictives) et que #4/#6
  puissent s'y brancher.
- Ajouter une **licence** à la racine (`LICENSE`) — *le type de licence est une décision à confirmer,
  voir Risks*.
- Mettre à jour le **README racine** : §5 (arborescence — retirer la note « n'existe pas encore »),
  et ajouter, pour **chaque paquet**, la **commande de build et la commande de test** (critère
  d'acceptation explicite de #2).
- Documenter les **conventions de commits** (Conventional Commits, déjà suivies par l'historique git)
  dans un `CONTRIBUTING.md` racine.
- Étendre la stratégie **`.gitignore`** pour couvrir les artefacts/dépendances/fichiers d'environnement
  des trois nouveaux paquets, **sans jamais committer de secret** (uniquement des `.env.example`).
- **Figer les versions de référence** différées par les ADR (Flutter/Dart, Python, Node, et
  versions cibles PostgreSQL/Redis pour mémo) dans des manifestes/contraintes versionnés — *valeurs
  recommandées, à confirmer (voir Risks)*.
- Garantir que **les chemins attendus par le pipeline ADW existent** (`specs/`, `docs/`, `docs/adr/`,
  `.claude/commands/`, `.pi/prompts/`) et ne sont pas cassés par le scaffolding.

## Non-Goals

- **Implémenter une quelconque fonctionnalité MVP** (auth, salons, RDV, caisse, notifications…) — ce
  sont les issues M1→. Le squelette se limite à un point d'entrée stub (p. ex. endpoint `/health`) +
  test trivial.
- **Implémenter le schéma de données / les migrations** PostgreSQL — issue **#3**.
- **Configurer la CI/CD** (GitHub Actions applicatif, build d'images Docker, scan de dépendances) —
  issue **#4**. *(La CI du pipeline `adw-sdlc.yml` existe déjà et est hors périmètre.)*
- **Mettre en place les environnements dev/staging/prod et la gestion des secrets** — issue **#5**.
- **Câbler le test gate** `MX_AGENT_TEST_CMD` dans `scripts/adw.env` ni rédiger la stratégie de tests —
  issue **#6**. #2 fournit seulement des commandes de test réelles par paquet ; le choix de la commande
  agrégée du gate revient à #6.
- **Rédiger les ADR de stack** — faits en #1. #2 *consomme* leurs décisions, ne les réécrit pas.
- **Choisir l'hébergeur, le fournisseur SMS concret, le fournisseur de stockage objet, l'ORM/runner
  async** — décisions différées (voir ADR-0003/0005/0006 et l'index `docs/adr/README.md`).
- **Modifier `adw_sdlc/`, `adw/`, `scripts/`** (hors `.gitignore` racine si nécessaire) — hors périmètre.

## Relevant Repository Context

**Nature du dépôt.** Monorepo greenfield outillé pour une livraison agentique. Tout vit dans un seul
dépôt : outillage de pipeline + (bientôt) paquets applicatifs.

**Stack figée (source de vérité = `docs/adr/`).** Voir l'index `docs/adr/README.md` :

| Couche | Décision | ADR | Impact #2 |
| --- | --- | --- | --- |
| Mobile | **Flutter** (Dart, Android prioritaire) | 0001 | `app-mobile/`, gate `flutter test` (#6) ; versions Flutter/Dart **à arrêter en #2** |
| Web gérant/admin | **Next.js** (React, TypeScript) | 0002 | `web-dashboard/` ; **1 app vs 2 apps** renvoyé à #2 ; versions Node/Next à arrêter en #2 |
| Backend | **FastAPI** (Python, REST + JWT) | 0003 | `backend/`, gate `pytest` (#6) ; version Python **à arrêter en #2** |
| Données | **PostgreSQL + Redis** | 0004 | pas de code en #2 ; versions de référence notables pour mémo |
| Stockage | **objet S3-compatible** | 0005 | pas de code en #2 |
| Notifications | **FCM + SMS** | 0006 | pas de code en #2 |

**Arborescence actuelle (vérifiée).**

```
coiflink/
├── prd-coiflink.md            # PRD (source de vérité produit)
├── BACKLOG.md                 # 55 issues M0–M6
├── README.md                  # §5 documente la structure (note "n'existe pas encore" à retirer)
├── docs/adr/                  # ADR 0000–0006 + README (créés par #1)        ✅ existe
├── specs/                     # specs de planification (créé par #1)         ✅ existe
├── adw_sdlc/                  # control plane TypeScript du pipeline          (hors périmètre)
├── adw/                       # contrat d'état inter-langage                  (hors périmètre)
├── .claude/commands/  .pi/prompts/   # prompts de phases ADW                  ✅ existent
├── .github/workflows/adw-sdlc.yml    # CI du pipeline                         (hors périmètre)
├── scripts/                   # run-issue.sh, create-backlog-issues.sh, adw.env.example
├── agents/                    # workspaces de run (gitignoré)
└── .gitignore                 # couvre node_modules, adw_sdlc/dist, agents/, scripts/adw.env, caches
        # MANQUANTS, à créer par #2 :  app-mobile/   web-dashboard/   backend/   LICENSE   CONTRIBUTING.md
```

**Chemins attendus par le pipeline ADW (vérifiés dans `adw_sdlc/src`).**
- La phase **plan** écrit `specs/<file>.md` et l'enregistre dans `state.planFile`
  (`adw_sdlc/src/phases.ts:258`, `orchestrator.ts:577`). → `specs/` doit exister (✅).
- Les prompts de phases sont résolus depuis `.claude/commands/<name>.md` (runner claude) et
  `.pi/prompts/<name>.md` (`phases.ts:79–82`). → existent (✅).
- `agents/` (workspaces par run) est **gitignoré** et créé à l'exécution — ne pas committer.
- Le test gate est `MX_AGENT_TEST_CMD` (vide aujourd'hui dans `scripts/adw.env.example` ⇒ ignoré /
  traité comme vert) ; son câblage est l'objet de #6, pas de #2.
→ **Conclusion** : « les chemins attendus par le pipeline existent » est déjà vrai pour `specs/`,
  `docs/`, `.claude/`, `.pi/` ; #2 ajoute les paquets applicatifs sans casser ces chemins.

**Conventions de commits (historique git).** L'historique suit **Conventional Commits** :
`docs:`, `feat:`, `ci:`, `chore:`, `fix:` (ex. `docs: ADR de la stack technique (#1)`,
`feat: pivot vers CoifLink…`, `ci: add adw_sdlc GitHub Actions workflow`). Le pipeline ADW **détient
tout git/gh** (branches `ci/<n>-<adwid>-<slug>`, commits, PR) ; les conventions documentées servent à
cadrer les messages produits (par l'agent et par les humains).

**PRD §18 Sprint 0** liste « Choix technologiques », « Architecture technique », « Backlog initial »,
etc. comme livrables de socle ; #2 matérialise la partie « structure du dépôt » de ce socle.

**Décisions encore ouvertes au démarrage de #2** (héritées des ADR, à trancher ici) :
arborescence interne `web-dashboard/` (1 app Next.js vs 2 apps gérant/admin — ADR-0002 *Suivi*) ;
versions de référence Flutter/Dart, Python, Node (ADR-0001/0002/0003 *Suivi* + `docs/adr/README.md`).
Décision **business/légale** propre à #2 : **type de licence** (le backlog impose « licence » sans la
nommer).

## Proposed Implementation

Approche d'ensemble : **monorepo à trois paquets applicatifs**, chacun scaffoldé au **minimum
exécutable** (manifeste + entrée stub + test trivial vert + README de paquet), plus les fichiers
racine (`LICENSE`, `CONTRIBUTING.md`, README mis à jour, `.gitignore` étendu). Les outils natifs de
chaque stack (`flutter create`, `create-next-app`, gabarit FastAPI) sont la base recommandée, **élagués
au strict nécessaire** pour ne pas introduire de fonctionnalité.

> **Principe directeur** : un squelette *réel mais vide de métier*. Les commandes de build/test
> documentées doivent **fonctionner immédiatement** (sinon le critère d'acceptation et #4/#6 sont
> fragilisés), tout en n'implémentant **aucune** user story.

### `app-mobile/` — Flutter (ADR-0001)

- Générer un projet Flutter minimal (équivalent `flutter create`, organisation Android prioritaire,
  iOS conservé). Conserver : `pubspec.yaml` (avec **contrainte de SDK Dart/Flutter** = version de
  référence à figer), `lib/main.dart` (écran d'accueil neutre « CoifLink »), `test/` avec **un widget
  test trivial qui passe**.
- Élaguer le compteur de démo si présent au profit d'un écran vide neutre (pas de fonctionnalité).
- `app-mobile/README.md` : prérequis (Flutter SDK version X), **build** (`flutter build apk`),
  **test** (`flutter test`), lancement dev (`flutter run`).
- `.gitignore` Flutter (`.dart_tool/`, `build/`, `.flutter-plugins*`, `*.iml`, etc.) — au niveau du
  paquet ou agrégé à la racine.

### `web-dashboard/` — Next.js / React / TypeScript (ADR-0002)

- **Décision d'arborescence à confirmer (ADR-0002 *Suivi*)** : **recommandation = une seule
  application Next.js** avec zones protégées par rôle (`/gerant`, `/admin`), plus simple à outiller
  pour le MVP et cohérent avec un RBAC backend unique (§11.2). Alternative : deux apps séparées
  (`web-dashboard/gerant/`, `web-dashboard/admin/`). *Voir Risks — décision à acter dans #2.*
- Générer un projet Next.js minimal (TypeScript, App Router) : `package.json` (avec champ **`engines`**
  fixant la version Node de référence), `tsconfig.json`, une page d'accueil neutre, **un test trivial
  vert** (runner à choisir : Vitest ou Jest — recommandation Vitest pour cohérence avec l'outillage
  `adw_sdlc` déjà en Vitest, *non bloquant*).
- `web-dashboard/README.md` : prérequis (Node version X), **build** (`npm run build`), **test**
  (`npm test`), dev (`npm run dev`). Inclure une commande de **lint** (`npm run lint`).
- `.gitignore` Node/Next (`node_modules/` — déjà couvert globalement, `.next/`, `out/`,
  `*.tsbuildinfo`, `web-dashboard/.env*.local`).
- `web-dashboard/.env.example` (placeholders **non secrets** : `NEXT_PUBLIC_API_BASE_URL=`).

### `backend/` — FastAPI / Python (ADR-0003)

- Disposition recommandée : paquet importable `coiflink_api/` + `tests/` + `pyproject.toml`.
  - `pyproject.toml` : `requires-python` = version Python de référence ; dépendances minimales
    (`fastapi`, serveur ASGI `uvicorn`, `pytest`, `httpx` pour le client de test). **Ne pas** ajouter
    ORM/migrations/auth (relève de #3/M1).
  - `coiflink_api/main.py` : application FastAPI exposant **uniquement** un endpoint de santé
    `GET /health` → `{"status": "ok"}` (stub de scaffolding standard, **pas** une fonctionnalité MVP ;
    documente l'API publique réellement ajoutée, voir *API / Interface Changes*).
  - `tests/test_health.py` : **un test** vérifiant que `/health` répond 200 (test trivial vert).
  - `backend/.env.example` : placeholders **non secrets** (`DATABASE_URL=`, `REDIS_URL=`,
    `JWT_SECRET=` laissé **vide** avec commentaire « injecté hors dépôt, voir #5 »).
- `backend/README.md` : prérequis (Python version X), création d'environnement
  (`python -m venv` / `pip install -e .[dev]`), **lancement** (`uvicorn coiflink_api.main:app`),
  **test** (`pytest`).
- `.gitignore` Python (`.venv/`, `*.egg-info/`, `__pycache__/`, `.pytest_cache/` — ces deux derniers
  déjà couverts globalement, `backend/.env`).

### Fichiers racine

- **`LICENSE`** : créer la licence retenue (voir Risks — recommandation par défaut **propriétaire /
  « Tous droits réservés »** pour un SaaS commercial à abonnements, titulaire du copyright à préciser ;
  alternative OSS si l'équipe le décide). Le manifeste de chaque paquet doit refléter le même choix
  (champ `license` de `package.json`/`pyproject.toml`/`pubspec.yaml`).
- **`CONTRIBUTING.md`** : conventions de commits **Conventional Commits** (types `feat/fix/docs/chore/
  ci/refactor/test`, portée optionnelle, référence d'issue), rappel que **le pipeline ADW détient
  git/gh** (branches/commits/PR automatisés), langue (français), et lien vers `docs/adr/` pour les
  décisions d'architecture. *(Ne pas y documenter de préférence interne « pas de marqueur IA » — c'est
  une préférence utilisateur privée, pas une règle projet publique ; simplement n'en émettre aucun.)*
- **`README.md`** (racine, à modifier) :
  - §5 : retirer la note « n'existe pas encore » ; refléter `app-mobile/`, `web-dashboard/`,
    `backend/` créés ; lier `LICENSE` et `CONTRIBUTING.md`.
  - **Nouveau** : un tableau « build/test par paquet » (critère d'acceptation explicite), p. ex. :
    | Paquet | Build | Test |
    | --- | --- | --- |
    | `app-mobile/` (Flutter) | `flutter build apk` | `flutter test` |
    | `web-dashboard/` (Next.js) | `npm run build` | `npm test` |
    | `backend/` (FastAPI) | `pip install -e .` | `pytest` |
  - Renseigner les **versions de référence** retenues (Flutter/Dart, Node, Python) dans §4 ou §7.
- **`.gitignore`** (racine, à étendre) : ajouter les motifs Flutter (`app-mobile/build/`,
  `app-mobile/.dart_tool/`, …), Next (`web-dashboard/.next/`, `web-dashboard/out/`,
  `*.tsbuildinfo` déjà présent), env applicatifs (`backend/.env`, `web-dashboard/.env*.local`,
  `app-mobile/.env`). **Ne jamais** ignorer les `*.env.example` (ils doivent être versionnés).
  *Option* : préférer des `.gitignore` par paquet (générés par les outils) à un fichier racine
  surchargé — décision de style, recommandation = par paquet pour Flutter/Node, motifs env à la racine.

### Versions de référence (à figer ici, recommandées — voir Risks)

Les ADR renvoient explicitement le figeage des versions à #2 (`docs/adr/README.md`). Recommandations
(à confirmer ; ancrer dans les manifestes et éventuellement un `.tool-versions` racine) :
Flutter **stable** / Dart **3.x**, Node **LTS 20+**, Python **3.12**, et pour mémo (runtime, pas de
code en #2) PostgreSQL **16**, Redis **7**.

## Affected Files / Packages / Modules

À **créer** (cette issue) :
- `app-mobile/` : `pubspec.yaml`, `lib/main.dart`, `test/widget_test.dart`, `README.md`, `.gitignore`
  (+ dossiers `android/`/`ios/` générés).
- `web-dashboard/` : `package.json`, `tsconfig.json`, page d'accueil, config de test, un test trivial,
  `README.md`, `.gitignore`, `.env.example`.
- `backend/` : `pyproject.toml`, `coiflink_api/__init__.py`, `coiflink_api/main.py`,
  `tests/test_health.py`, `README.md`, `.env.example`.
- Racine : `LICENSE`, `CONTRIBUTING.md`.
- *(Optionnel)* `.tool-versions` racine pour les versions de référence.

À **modifier** :
- `README.md` (racine) — §5 + nouveau tableau build/test + versions de référence.
- `.gitignore` (racine) — motifs des nouveaux paquets + fichiers d'environnement.

À **lire** pour scaffolder juste :
- `docs/adr/0001`–`0003` (stack mobile/web/backend) et `docs/adr/README.md` (versions différées).
- `BACKLOG.md` (entrée #2 et items dépendants #3/#4/#6).
- `prd-coiflink.md` §10 (architecture), §11 (sécurité — invariants à préserver), §18 (Sprint 0).
- `scripts/adw.env.example`, `adw_sdlc/src/phases.ts`/`orchestrator.ts` (chemins attendus du pipeline).

À **vérifier comme existants** (créés par #1, ne pas recréer) : `docs/`, `docs/adr/`, `specs/`.

À **ne pas toucher** : `adw_sdlc/`, `adw/`, `scripts/` (hors lecture), `.github/workflows/adw-sdlc.yml`,
`.claude/`, `.pi/`, `agents/`.

## API / Interface Changes

- **Surface réseau / API publique** : *quasi-none.* Le seul endpoint réellement ajouté est
  `GET /health` (FastAPI), un stub de scaffolding standard renvoyant `{"status": "ok"}`. Il doit être
  documenté dans `backend/README.md` comme **endpoint de santé**, et **n'implémente aucune** logique
  métier MVP. Aucune autre route, aucun contrat d'API client n'est introduit.
- **Surface dev / ligne de commande** : ajout de commandes **build/test/dev par paquet** documentées
  dans les READMEs (`flutter build apk`/`flutter test` ; `npm run build`/`npm test`/`npm run dev` ;
  `uvicorn …`/`pytest`). Ce sont des interfaces *développeur*, pas des API publiques.
- Aucun changement aux interfaces du pipeline ADW (`scripts/run-issue.sh`, `MX_AGENT_*`).

## Data Model / Protocol Changes

**None.** Aucun schéma, migration, format de stockage ou de sérialisation. Le scaffolding backend
n'inclut **ni ORM, ni migrations, ni modèle** : le modèle de données PostgreSQL est l'objet de l'issue
**#3**. Les `*.env.example` ne contiennent que des **placeholders non secrets** (clés vides + URL de
forme `postgresql://…`/`redis://…` à titre d'exemple), sans valeur réelle.

## Security & Privacy Considerations

- **Secrets / credentials — invariant critique** : ne **jamais** committer de secret. #2 ne crée que
  des `*.env.example` avec des **placeholders vides** ; les vraies valeurs (DSN BD/Redis, `JWT_SECRET`,
  clés FCM, identifiants SMS, accès S3) sont injectées **hors dépôt** (issue #5). Le `.gitignore` doit
  ignorer les `.env` réels (`backend/.env`, `web-dashboard/.env*.local`, `app-mobile/.env`) **mais
  versionner** les `.env.example`. Vérifier qu'aucun outil de scaffolding n'a généré de fichier
  contenant un secret par défaut.
- **PII & journalisation** : aucune donnée utilisateur n'est traitée en #2. Le stub `/health` ne logge
  aucune PII. Les exigences §11 (hachage des mots de passe, JWT/refresh, OTP, anti-bruteforce, RBAC,
  pas de log d'OTP/numéros/corps de message) sont **ancrées dans ADR-0003/0006** et **implémentées en
  M1/M5**, pas ici — ne pas les affaiblir, ne pas les pré-implémenter.
- **Préserver les invariants documentés** : le scaffolding doit *permettre* (et non contredire) la
  configuration par variables d'environnement (PRD §11, ADR-0005/0006 « secrets hors dépôt »). Le
  point d'entrée backend lit sa config depuis l'environnement, jamais depuis une constante en dur.
- **Résidence / hébergement** : non documenté par le PRD ; décision de déploiement différée (#4/#5).
  Aucun choix d'hébergement n'est figé par #2.
- **Préférence utilisateur** : aucun marqueur « généré par IA » dans le code, les commits, les PR, ni
  la documentation (README/CONTRIBUTING/LICENSE/scaffolds).

## Testing Plan

#2 introduit du code de scaffolding ; la validation porte sur l'**existence de la structure** et sur
des **tests triviaux verts** par paquet (qui serviront de point d'ancrage à #6) :

- **Tests triviaux par paquet** (doivent passer) :
  - `app-mobile/` : un *widget test* (`flutter test`) sur l'écran d'accueil neutre.
  - `web-dashboard/` : un test unitaire trivial (Vitest/Jest, `npm test`).
  - `backend/` : `tests/test_health.py` vérifiant `GET /health == 200` (`pytest`).
- **Vérifications structurelles** (manuelles ou via un script de revue ; à automatiser plus tard en
  #4) : présence de `app-mobile/`, `web-dashboard/`, `backend/`, `docs/`, `docs/adr/`, `specs/`,
  `LICENSE`, `CONTRIBUTING.md` ; chaque paquet possède un `README.md` documentant **build + test**.
- **Build réel** : `flutter build apk` (ou au moins `flutter analyze`/`flutter test`),
  `npm run build`, `pip install -e . && pytest` doivent réussir sur le squelette (sinon les commandes
  documentées sont fictives).
- **Liens & doc** : les liens du README racine (vers `LICENSE`, `CONTRIBUTING.md`, ADR) résolvent ;
  le tableau build/test correspond aux commandes réelles.
- **Garde secrets** : aucun fichier `.env` réel n'est suivi par git ; tous les `.env.example` le sont.
- **Non-régression pipeline** : `specs/`, `.claude/commands/`, `.pi/prompts/` toujours présents ;
  `scripts/run-issue.sh --dry-run` reste fonctionnel (le scaffolding ne casse pas la résolution des
  chemins de phases).

> Note : #2 **ne câble pas** `MX_AGENT_TEST_CMD` (c'est #6). Tant que le gate est vide, le pipeline le
> traite comme vert ; #2 garantit seulement que des commandes de test **réelles** existent par paquet.

## Documentation Updates

- **README.md** (racine) : §5 (arborescence sans la note « n'existe pas encore ») ; **nouveau tableau
  build/test par paquet** ; versions de référence retenues ; liens `LICENSE`/`CONTRIBUTING.md`.
- **`CONTRIBUTING.md`** (nouveau) : conventions Conventional Commits, rôle du pipeline ADW sur git/gh,
  langue, renvoi vers `docs/adr/`.
- **READMEs de paquet** (nouveaux) : `app-mobile/README.md`, `web-dashboard/README.md`,
  `backend/README.md` — prérequis + build + test + dev pour chacun.
- **`LICENSE`** (nouveau) : texte de la licence retenue.
- **`docs/adr/`** : *pas de nouvel ADR requis par #2*. **Optionnel** : si la décision « 1 app vs 2
  apps » web et/ou le figeage des versions méritent une trace, ajouter un **ADR-0007** (arborescence
  monorepo & versions de référence) — *recommandé pour traçabilité, à confirmer* ; sinon, consigner
  ces choix dans le README. Mettre à jour `docs/adr/README.md` si un ADR-0007 est créé.
- **`specs/`** : la présente spec (`specs/initialisation-depot-structure-projet.md`).

## Risks and Open Questions

- **Type de licence (décision business/légale — bloquant pour le fichier `LICENSE`)** : le backlog
  impose « licence » sans la nommer. CoifLink est un **SaaS commercial à abonnements** (PRD) ⇒
  recommandation par défaut = **licence propriétaire / « Tous droits réservés »** avec titulaire du
  copyright à préciser. Alternative : licence OSS (MIT/Apache-2.0) si l'équipe veut ouvrir le code.
  **À confirmer auprès du porteur** — ne pas présumer une licence OSS pour un produit commercial.
- **`web-dashboard/` : une app Next.js vs deux apps (gérant/admin)** — différé d'ADR-0002 à #2.
  Recommandation = **une app unique** à zones protégées par rôle (plus simple MVP, cohérent RBAC
  unique). À acter ; un ADR-0007 ou une note README peut le tracer.
- **Profondeur du scaffolding** : *squelette runnable* (recommandé — commandes de build/test réelles,
  de-risque #4/#6) **vs** *dossiers nus + placeholders*. Le squelette runnable est recommandé mais doit
  rester **vide de métier** ; risque à surveiller = qu'un outil (`flutter create`/`create-next-app`)
  génère plus que le strict nécessaire (à élaguer) ou un fichier contenant un secret par défaut (à
  vérifier).
- **Versions de référence** (Flutter/Dart, Node, Python ; PostgreSQL/Redis pour mémo) — à figer ici
  (les ADR le renvoient à #2). Valeurs recommandées indicatives ; **à confirmer** par l'équipe selon la
  disponibilité d'outillage CI (#4) et l'environnement cible.
- **Runner de test web** (Vitest vs Jest) et **outil d'environnement Python** (venv+pip vs uv/poetry) :
  sous-choix non bloquants ; recommandations données (Vitest, venv+pip ou uv), à confirmer ; cohérence
  souhaitée avec #4 (CI) et #6 (gate).
- **Dépendance #1** : satisfaite (ADR 0001–0006 `Accepté`). Si une décision de stack changeait, le
  scaffolding devrait suivre — non anticipé.
- **Interaction avec #4/#6** : #2 fournit des commandes de test *par paquet* ; la **commande agrégée**
  du test gate ADW et la matrice CI relèvent de #4/#6. Éviter de pré-câbler `MX_AGENT_TEST_CMD`.

## Implementation Checklist

1. **Vérifier les prérequis** : ADR 0001–0006 présents et `Accepté` (`docs/adr/`) ; `docs/`,
   `docs/adr/`, `specs/` existent (créés par #1) — ne pas les recréer.
2. **Trancher les décisions ouvertes** (consigner le choix dans README et/ou un ADR-0007 optionnel) :
   (a) type de **licence** ; (b) `web-dashboard/` = **1 app** (recommandé) vs 2 apps ; (c) **versions
   de référence** Flutter/Dart, Node, Python.
3. **Scaffolder `backend/`** : `pyproject.toml` (`requires-python`, deps minimales `fastapi`/`uvicorn`/
   `pytest`/`httpx`), `coiflink_api/main.py` (app + `GET /health`), `tests/test_health.py` (test vert),
   `.env.example` (placeholders **vides**, `JWT_SECRET` commenté « injecté hors dépôt #5 »),
   `backend/README.md` (prérequis/build/test/dev). Vérifier `pytest` vert.
4. **Scaffolder `web-dashboard/`** : projet Next.js (TS, App Router) minimal, `package.json` avec
   `engines` (Node), `tsconfig.json`, page d'accueil neutre, runner de test + **un test trivial vert**,
   script `lint`, `.env.example` (placeholders non secrets), `web-dashboard/README.md`. Vérifier
   `npm install && npm run build && npm test`.
5. **Scaffolder `app-mobile/`** : projet Flutter minimal (Android prioritaire, iOS conservé),
   `pubspec.yaml` avec contrainte SDK, `lib/main.dart` (écran neutre, **sans** compteur de démo),
   `test/widget_test.dart` (test vert), `app-mobile/README.md`. Vérifier `flutter test`.
6. **`LICENSE`** : créer la licence retenue (étape 2a) ; refléter le champ `license` dans
   `pyproject.toml` / `package.json` / `pubspec.yaml`.
7. **`CONTRIBUTING.md`** : Conventional Commits, rôle ADW sur git/gh, langue, renvoi `docs/adr/`.
8. **`.gitignore` racine** : ajouter motifs Flutter/Next/Python et `.env` applicatifs réels ; **garder
   les `*.env.example` versionnés** ; ne pas dupliquer ce qui est déjà couvert globalement.
9. **README.md racine** : retirer la note « n'existe pas encore » (§5) ; ajouter le **tableau build/test
   par paquet** ; renseigner les versions de référence ; lier `LICENSE`/`CONTRIBUTING.md`.
10. **(Optionnel) ADR-0007** : tracer arborescence monorepo + versions + 1-vs-2-apps ; mettre à jour
    `docs/adr/README.md`.
11. **Vérifier les critères d'acceptation** : structure en place ; `README` documente build **et** test
    de chaque paquet ; chemins ADW (`specs/`, `docs/`, `docs/adr/`, `.claude/`, `.pi/`) intacts ; tests
    triviaux verts par paquet ; aucun secret committé (seuls les `.env.example` suivis) ; aucun marqueur
    « généré par IA » ; liens du README valides.
