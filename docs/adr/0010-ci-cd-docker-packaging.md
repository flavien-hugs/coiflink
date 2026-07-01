# ADR-0010 : Pipeline CI/CD applicatif & empaquetage Docker

- **Statut** : Accepté
- **Date** : 2026-07-01
- **Décideurs** : équipe CoifLink
- **Issue** : #4
- **Référence PRD** : §10.2 (déploiement : Docker · CI/CD GitHub Actions), §11 (sécurité),
  §18 (Sprint 0 — socle CI)

## Contexte et problème

Le dépôt ne possédait qu'une CI dédiée au **control plane** ADW
(`.github/workflows/adw-sdlc.yml`). **Aucune CI ne couvrait les trois paquets applicatifs**
(`app-mobile/`, `web-dashboard/`, `backend/`) scaffoldés par #2/#3 : une PR pouvant casser leur
build ou leurs tests n'était bloquée par aucun garde-fou, aucun artefact ni image Docker n'était
produit, et aucun scan de dépendances ne signalait de vulnérabilité connue. L'issue #4 exige une
**CI applicative à chaque PR** (lint + tests + build par paquet, **jobs séparés** mobile/web/backend),
un **scan de dépendances**, la **production d'artefacts**, le **build d'images Docker**, et une
**CI verte obligatoire avant merge**.

Plusieurs points étaient laissés ouverts par la spec (`specs/pipeline-ci-cd-github-actions.md`) :
linter backend (aucun n'était configuré), outil(s) de scan + seuil bloquant, périmètre Docker et
build-seul vs push, filtrage par chemin, et l'interaction des *required checks* avec la phase `merge`
du pipeline ADW.

## Options envisagées

- **Structure CI — Option A : un workflow `ci.yml` à jobs indépendants** (un par paquet + scan +
  Docker), calqué sur les conventions de `adw-sdlc.yml`. **Option B : plusieurs workflows séparés**
  (un fichier par paquet). **Option C : réutiliser/étendre `adw-sdlc.yml`.**
- **Linter backend — Option A : ruff** (`ruff check`). **Option B : flake8 + black.** **Option C :
  aucun** (non conforme au critère « lint »).
- **Scan de dépendances — Option A : par écosystème** (`pip-audit`, `npm audit`, `osv-scanner`).
  **Option B : unifié** (`osv-scanner` sur tous les lockfiles). **Seuil** : bloquant (échec CI) vs
  informatif.
- **Périmètre Docker — Option A : images backend + web** (services serveur), **mobile = APK**.
  **Option B : ajouter une image mobile** (sans objet : l'artefact mobile est un APK).
- **Publication d'images — Option A : build-seul** (#4). **Option B : push GHCR** dès #4.
- **Filtrage par chemin — Option A : exécuter tous les jobs à chaque PR.** **Option B : conditionner
  par `paths:`.**

## Décision

- **Structure : un workflow applicatif unique `ci.yml`** (Option A), à **jobs séparés**
  `backend`, `web`, `mobile`, `dependency-scan`, `docker-backend`, `docker-web`. Il réutilise les
  conventions de `adw-sdlc.yml` (setups officiels, cache par écosystème, `concurrency` avec
  `cancel-in-progress`, `permissions: contents: read`). **Groupe de concurrence distinct** (`ci-…`
  vs `adw-sdlc-…`) : `adw-sdlc.yml` n'est **pas** modifié.
- **Chaque job de paquet** exécute lint → tests → build sur la version de référence figée par
  [ADR-0007](./0007-arborescence-monorepo-versions.md) et **téléverse son artefact** :
  - **backend** (Python 3.12) : `ruff check` → `pytest` → **round-trip Alembic**
    (`upgrade head → downgrade base → upgrade head`) contre un **service PostgreSQL 16**, puis
    `python -m build` → artefact `backend-dist` (wheel + sdist).
  - **web** (Node 20) : `npm run lint` → `npm test` → `npm run build` → artefact
    `web-dashboard-build` (sortie **standalone** Next.js).
  - **mobile** (Flutter stable) : `flutter analyze` → `flutter test` → `flutter build apk --debug`
    → artefact `app-mobile-apk`.
- **Linter backend : ruff** (Option A). Jeu de règles **conservateur** — défaut de ruff (`F` +
  `E4/E7/E9`) étendu à `B` (bugbear) et `W` — que le code #2/#3 passe **sans reformatage**. La CI
  exécute **`ruff check`** (lint) ; le **formatage n'est pas imposé** au MVP pour ne pas réécrire les
  fichiers formatés (black) livrés par les issues précédentes (invariant « ne pas toucher le
  schéma/migrations #3 »). `ruff` est ajouté à l'extra `dev` de `backend/pyproject.toml`.
- **Scan de dépendances : par écosystème** (Option A), **informatif au MVP** :
  `pip-audit` (Python) · `npm audit --audit-level=high` (Node) · `osv-scanner` (Dart, lit
  `pubspec.lock`). Le job **reporte** à chaque PR sans être bloquant (`continue-on-error`), afin de
  ne **pas verrouiller les merges du dépôt** sur une CVE transitive nouvellement divulguée. La
  **remédiation automatisée** passe par **Dependabot** (`.github/dependabot.yml` : `pip`, `npm`,
  `pub`, `github-actions`, plus `adw_sdlc/`).
- **Images Docker : backend + web-dashboard** (services serveur), **mobile = APK** (Option A).
  **Build-seul** en #4 (`push: false`, cache buildx GHA) ; le **push vers un registre (GHCR)** et le
  choix du registre sont **différés à #5**. Chaque image : base slim épinglée, **utilisateur
  non-root**, **config par variables d'environnement** (aucun secret dans l'image), `*.dockerignore`
  excluant `.venv/`, `node_modules/`, `.next/`, `tests/`, `.env*`. Un **smoke test** vérifie
  `GET /health` (backend) et la page d'accueil (web).
- **Pas de filtrage par chemin** au MVP (Option A) : les jobs s'exécutent à chaque PR — plus simple
  et compatible avec des *required checks* (un check requis « skipped » peut bloquer la fusion).
- **CI verte obligatoire avant merge** : les **status checks requis** sont `backend`, `web`,
  `mobile`, `docker-backend`, `docker-web` (le job `dependency-scan` reste **informatif**, non
  requis). La **protection de branche `main`** exigeant ces checks est un **réglage dépôt**
  (Settings → Branches / `gh api`), **non versionnable** — à appliquer par un administrateur (voir
  Conséquences).

## Justification (compromis)

- **Un workflow à jobs séparés** satisfait directement le critère « jobs séparés mobile/web/backend »,
  garde la CI applicative lisible et indépendante du control plane, et réutilise des conventions
  déjà éprouvées (setups, cache, concurrence, least-privilege).
- **ruff (check-only)** : linter standard et rapide de l'écosystème FastAPI, sans dépendance lourde ;
  le mode *check* couvre le critère « lint » (imports inutilisés, noms indéfinis, bugs `B`) tout en
  **respectant l'invariant** de non-réécriture des fichiers #2/#3 (le formatage black existant est
  préservé ; `ruff format` reste disponible en local sans être un gate).
- **Scan informatif + Dependabot** : introduit une mesure de sécurité chaîne d'approvisionnement
  **là où il n'y en avait aucune**, visible à chaque PR, tout en évitant le risque opérationnel d'un
  **verrouillage global des merges** dû à une CVE transitive sans correctif immédiat. Le durcissement
  « bloquant sur High/Critical » est un **suivi** (voir ci-dessous), cohérent avec le fait que #5
  actera la politique d'exploitation.
- **Build-seul** : #4 se limite à **construire** images et artefacts ; **déployer**, choisir
  l'hébergeur et pousser vers un registre relèvent de **#5** (cf. [index ADR](./README.md) — point
  différé « ADR de déploiement (#4/#5) »). Les images non-root, sans secret et configurées par
  environnement sont **prêtes** pour ce push ultérieur.
- **Pas de filtrage par chemin** : évite la subtilité « check requis *skippé* ≠ *success* » qui peut
  bloquer une fusion ; l'optimisation de coût (job « gate » d'agrégation) est reportée si nécessaire.
- **Compromis acceptés** : builds Flutter/Docker plus lents (atténués par les caches) ; scan non
  bloquant au MVP ; iOS non construit (runner macOS coûteux, Android prioritaire — ADR-0001).

## Conséquences

- **Positives** : toute PR est désormais gardée par lint + tests + build des trois paquets ; les
  migrations Alembic sont **exécutées et validées** en CI contre Postgres 16 (clôt le « Suivi »
  d'[ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) : *exécution des migrations en CI +
  service Postgres → #4*) ; des artefacts (APK, sortie web, wheel/sdist) et des images Docker sont
  produits ; le risque de dépendance vulnérable est **surveillé** (scan + Dependabot).
- **Négatives / risques** :
  - la **protection de branche** (checks requis) est un réglage dépôt **non versionné** : sa mise en
    place dépend d'un administrateur ; tant qu'elle n'est pas appliquée, « CI verte obligatoire » n'est
    pas techniquement forcé.
  - **Interaction avec la phase `merge` ADW** : le control plane **détient le merge** ; il faut
    confirmer que cette phase **attend** les checks requis (pas de contournement) — décision
    d'exploitation à acter avec **#5**.
  - le scan non bloquant au MVP est un signal **informatif** : une vulnérabilité High/Critical n'arrête
    pas la fusion tant que le durcissement n'est pas activé.
  - actions tierces épinglées à une **version majeure** (`subosito/flutter-action@v2`) et binaire
    `osv-scanner` épinglé à une version : l'épinglage par **SHA** est un durcissement recommandé (suivi).
- **Clôture partielle du point différé** : #4 tranche la partie **« CI/CD GitHub Actions »** et
  **empaquetage Docker** du point « ADR de déploiement (#4/#5) » ; l'**hébergement, la région des
  données et le push registre** restent ouverts et rattachés à **#5**.
- **Suivi / à confirmer (non bloquant)** :
  - **#5** : environnements & secrets réels, push GHCR (`permissions: packages: write`), politique de
    protection de branche appliquée, interaction `merge`/required-checks, durcissement du scan
    (bloquant High/Critical), épinglage SHA des actions, ADR de déploiement (hébergeur/région) ;
  - **#6** : câblage du test gate agrégé `MX_AGENT_TEST_CMD` (la CI #4 exécute les tests **par paquet**) ;
  - **#50** : tests e2e, intégrés *dans* cette CI.
