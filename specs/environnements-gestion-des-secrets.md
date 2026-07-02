# Environnements (dev/staging/prod) & gestion des secrets

> Spécification de planification pour l'issue GitHub **#5 — Environnements & gestion des secrets**
> (`infra` · `security` · Should · Effort M · PRD §10.2 / §11 / §12.2 / §18 Sprint 0).
> **Dépend de #4** (pipeline CI/CD applicatif & empaquetage Docker) — **satisfaite** : `ci.yml`
> construit les images `backend`/`web-dashboard` (build-seul, non-root, config par variables
> d'environnement, aucun secret dans l'image ; cf. [ADR-0010](../docs/adr/0010-ci-cd-docker-packaging.md)).
> **Cette spec ne produit pas de code.** Elle décrit le travail d'infrastructure/documentation à
> réaliser dans une phase d'implémentation ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, specs). Les en-têtes de
> section ci-dessous sont conservés en anglais car ils sont attendus par le gabarit du pipeline ADW ;
> le contenu livré (docs, ADR, fichiers de config) reste en français hors identifiants techniques.

## Problem Statement

Le dépôt applique déjà l'invariant **« aucun secret en clair dans le dépôt »** et le principe
**« configuration par variables d'environnement »** (session backend qui lit `DATABASE_URL` depuis
l'environnement, `main.py` qui lit `APP_*`, `.env.example` en placeholders non secrets, `.gitignore`
qui exclut les `.env` réels, CONTRIBUTING « Secrets », images Docker sans secret intégré). En
revanche, **rien n'est encore formalisé ni outillé** pour ce que l'issue #5 exige :

- **Aucune définition des environnements** *dev / staging / prod* : ni topologie de services, ni
  matrice de configuration par environnement, ni procédure de provisionnement. On ne peut donc pas
  **reproduire un `staging`** (critère d'acceptation).
- **Aucun magasin de secrets ni mécanisme d'injection décidé** : les secrets réels (DSN Postgres,
  `REDIS_URL`, `JWT_SECRET`, clés S3/FCM/SMS) sont aujourd'hui laissés *vides* dans les gabarits, sans
  dire **où ils vivent** en staging/prod, **comment ils sont injectés hors dépôt**, ni **qui y accède**.
- **Aucune politique de secrets écrite** : rotation, périmètre d'accès, conduite en cas de fuite,
  règles de non-journalisation — le critère « politique de secrets documentée » n'est pas couvert.
- **Aucune sauvegarde activée** : le PRD (§10.2, §12.2) exige des **sauvegardes automatiques
  quotidiennes** ; l'[ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md) renvoie explicitement
  ce point à **#5**. Aujourd'hui : rien.
- **Décisions différées en attente de #5** (cf. [index ADR](../docs/adr/README.md)) : plateforme
  d'hébergement & région des données (ADR de déploiement), push d'images vers un registre (renvoyé
  par ADR-0010), fournisseur de stockage objet (ADR-0005), fournisseur SMS (ADR-0006), interaction
  *required checks* ↔ phase `merge` du pipeline ADW (ADR-0010).

Besoin (issue #5, critères d'acceptation) : **secrets injectés hors dépôt**, **`staging`
reproductible**, **politique de secrets documentée** — le tout sans jamais committer de valeur réelle.

## Goals

- **Modèle d'environnements documenté** *dev / staging / prod* : rôle de chaque environnement, sources
  de données/valeurs, isolation, et **matrice de configuration** (quelles variables chaque service —
  `backend`, `web-dashboard` — consomme dans chaque environnement).
- **Mécanisme d'injection des secrets hors dépôt** décidé et documenté, cohérent avec les invariants
  existants : les secrets vivent dans un **magasin de secrets** (natif à la plateforme et/ou GitHub
  Environments pour la CI/CD), jamais dans le dépôt ni dans les images ; injection **par variables
  d'environnement** à l'exécution.
- **`staging` reproductible** : un **runbook de provisionnement** + une **configuration déclarative
  non secrète versionnée** (topologie des services) permettant de recréer `staging` depuis zéro, sans
  connaissance tacite. `staging` **reflète** `prod` (mêmes images, mêmes clés de config, données non
  réelles).
- **Sauvegardes activées** : **sauvegarde automatique quotidienne** de PostgreSQL (PRD §12.2), avec
  **rétention**, **procédure de restauration documentée** et **test de restauration** périodique ;
  note sur la sauvegarde/versionnement du stockage objet.
- **Politique de secrets documentée** : inventaire des secrets, magasin, injection, **rotation**,
  **périmètre d'accès (moindre privilège)**, **conduite en cas de fuite**, règles de
  **non-journalisation** — au format d'un document opérationnel + un **ADR de décision**.
- **Trancher (ou re-différer explicitement) les décisions rattachées à #5** : plateforme
  d'hébergement & région des données (ADR de déploiement), stratégie de registre d'images, stockage
  objet, protection de branche `main` (checks requis) et son interaction avec la phase `merge` ADW.
- **Zéro régression / zéro secret** : ne casser ni la CI applicative (`ci.yml`) ni le control plane
  (`adw-sdlc.yml`) ; ne committer/journaliser aucun secret ; conserver les `*.env.example` comme seuls
  fichiers d'exemple (placeholders).

## Non-Goals

- **Implémenter la *consommation* des secrets par des fonctionnalités** : l'authentification JWT
  (`JWT_SECRET`, issue #8/M1), les uploads S3 (logos/photos, M2), les notifications FCM/SMS (M5) ne
  sont **pas** câblées ici. #5 **prépare** la surface de configuration/secrets ; les features la
  consommeront plus tard. Ne pas laisser croire que ces intégrations existent.
- **Construire un pipeline de déploiement continu complet** (auto-deploy sur merge, promotions
  automatiques, blue/green, rollback automatisé). #5 vise la **reproductibilité de `staging`** et la
  **base opérationnelle** ; l'automatisation CD avancée est une évolution ultérieure (à cadrer, cf.
  Risks). Un déploiement peut rester **manuel/documenté** au MVP.
- **Choisir le fournisseur SMS concret** (agrégateur local) — décision **opérationnelle** rattachée à
  la mise en œuvre des notifications (M5) ; #5 se limite à **documenter la surface** de secrets SMS
  (cf. ADR-0006). De même, le **runner de tâches async** (Celery/arq/RQ) reste hors périmètre.
- **Modifier le schéma / les migrations (#3)**, la logique métier des paquets, ou les commandes de
  build/test (#2). #5 est **infra + documentation + configuration**, pas du code applicatif métier.
- **Modifier le contrat de secrets du pipeline ADW** (`adw_sdlc/src/env.ts`, `lint:env`, rétention de
  `GH_TOKEN`). Ce périmètre — les secrets **du pipeline** — est déjà en place et sert de **précédent**,
  pas d'objet de refonte. #5 traite les secrets **de l'application déployée**.
- **Durcir le scan de dépendances** (bloquant High/Critical) et **épingler les actions par SHA** :
  suivis *recommandés mais optionnels* hérités d'ADR-0010 ; à traiter seulement s'ils sont explicitement
  retenus (voir Risks) — pas un critère d'acceptation de #5.

## Relevant Repository Context

**Nature du dépôt.** Monorepo greenfield outillé pour livraison agentique. Trois paquets applicatifs
scaffoldés (`app-mobile/` Flutter, `web-dashboard/` Next.js, `backend/` FastAPI), un control plane
`adw_sdlc/`, une CI applicative `ci.yml` (#4) et une CI control plane `adw-sdlc.yml`.

**Invariants sécurité déjà en place (à préserver, ne pas affaiblir).**
- **Aucun secret committé** : seuls les `*.env.example` (placeholders) sont versionnés ; les `.env`
  réels sont gitignorés (`.gitignore` : `backend/.env`, `web-dashboard/.env*.local`, `app-mobile/.env`,
  `scripts/adw.env`). CONTRIBUTING « Secrets » : *« La gestion des secrets hors dépôt est l'objet de
  l'issue #5. »*
- **Config par variables d'environnement, sans défaut secret codé en dur** :
  `backend/coiflink_api/adapters/sortant/persistance/session.py` lit `DATABASE_URL` et **lève** une
  erreur explicite si absent ; `backend/coiflink_api/main.py` lit `APP_NAME`/`APP_ENV` ;
  `migrations/env.py` lit `DATABASE_URL` (jamais de secret dans `alembic.ini`).
- **Images Docker sans secret** (#4/ADR-0010) : `backend/Dockerfile` et `web-dashboard/Dockerfile` —
  base slim épinglée, **utilisateur non-root**, `APP_ENV`/`NODE_ENV=production`, config **injectée à
  l'exécution**, `.dockerignore` excluant `.env*`. **Build-seul** en CI ; **push registre différé #5**.
- **Frontière de secrets du pipeline ADW** : l'orchestrateur **détient tout git/gh** et **retient
  `GH_TOKEN`** (jamais exposé à l'agent) ; `adw-sdlc.yml` inclut la garde `lint:env`. Modèle de
  référence pour la discipline « secrets hors de portée de l'agent ».
- **Préférence utilisateur** : **aucun marqueur « généré par IA »** dans le code, les commits, les PR
  ou la doc.

**Gabarits de configuration existants (surface à consolider).**

| Fichier | Variables (placeholders non secrets) |
| --- | --- |
| `backend/.env.example` | `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET` (vide), `APP_NAME`, `APP_ENV` |
| `web-dashboard/.env.example` | `NEXT_PUBLIC_API_BASE_URL` (⚠ `NEXT_PUBLIC_*` = **exposé au navigateur**, jamais un secret) |
| `scripts/adw.env.example` | config **du pipeline ADW** (hors périmètre applicatif #5) |

**Décisions différées dont #5 est le point de rattachement** (cf. [`docs/adr/README.md`](../docs/adr/README.md)
et *Conséquences* des ADR) :
- **Plateforme d'hébergement & région des données** — ADR de déploiement (#4/#5). #4 a tranché la
  partie « CI/CD GitHub Actions & empaquetage Docker » (ADR-0010) ; **l'hébergeur, la région et le push
  registre restent ouverts → #5**.
- **Fournisseur de stockage objet** (AWS S3 / MinIO / R2 / bucket plateforme) — déploiement #4/#5
  (ADR-0005 : *clés S3 gérées hors dépôt, injectées par l'environnement, #5*).
- **Sauvegardes automatiques** — ADR-0004 : *« sauvegardes automatiques (§10.2, §12.2) →
  environnements / #5 »*.
- **Injection des secrets de connexion réels** — ADR-0009 : *« → #5 »*.
- **Fournisseur SMS concret / clés FCM** — ADR-0006 (opérations, #5 ; concret à M5).
- **Push GHCR + `permissions: packages: write`**, **protection de branche `main`** (checks requis) et
  **interaction avec la phase `merge` ADW** — suivis explicites d'ADR-0010 rattachés à #5.

**Références PRD.** §10.2 (Déploiement : Docker · CI/CD GitHub Actions · **Hébergement cloud
sécurisé** · **Sauvegardes automatiques**) ; §11.3 (données personnelles, **sauvegardes sécurisées**,
chiffrement au repos *si nécessaire*) ; §11.4 (journalisation d'actions sensibles — ne jamais y mettre
de secret/PII) ; §12.2 (**sauvegarde automatique quotidienne**, disponibilité 99 %, monitoring) ; §18
Sprint 0 (livrable **« Environnements de développement »**).

**Outillage d'hébergement présent dans l'environnement de travail.** Le dépôt est outillé avec un
**serveur MCP `railway`** et une **skill `use-railway`** (provisionnement de projets/services/bases,
buckets de stockage objet, environnements, variables, domaines). C'est un **signal fort** que
**Railway** est le candidat d'hébergement de référence (voir *Proposed Implementation* et *Risks* :
la décision reste à **acter par un ADR**).

**Statut du code applicatif pour ce périmètre.** Il **n'existe aujourd'hui aucun** artefact
d'environnement/déploiement dans le dépôt : pas de `docker-compose.yml`, pas de dossier `deploy/`, pas
de doc d'environnements, pas d'ADR de déploiement. #5 **crée** ces artefacts (documentation + config
non secrète), sans introduire de logique métier.

## Proposed Implementation

Approche d'ensemble : **décider** (ADR) le socle de déploiement (plateforme, magasin de secrets,
modèle d'environnements, sauvegardes), puis **matérialiser** cette décision en **documentation
opérationnelle** + **configuration déclarative non secrète versionnée**, sans jamais committer de
secret. La plateforme concrète est **stack-dépendante** : recommandation **Railway** (tooling déjà
câblé), à **confirmer par ADR-0011** ; le plan reste **portable** (principes valables pour Render,
Fly.io, un VPS + Docker Compose, ou un cloud managé).

### 1. Acter la décision de déploiement — `docs/adr/0011-deploiement-environnements-secrets.md`

Rédiger un ADR (format MADR simplifié, cf. [ADR-0000](../docs/adr/0000-processus-et-gabarit-adr.md) :
Statut, Contexte, Options, Décision, Justification, Conséquences) qui tranche :

- **Plateforme d'hébergement** (recommandation : **Railway**) et **région des données** (proximité
  Afrique de l'Ouest / résidence — voir Risks). Justifier vs alternatives (Render, Fly.io, VPS+Compose,
  AWS/GCP). Clôt le point différé « ADR de déploiement (#4/#5) ».
- **Magasin de secrets & injection** :
  - **Runtime applicatif** : secrets **par environnement** dans le magasin natif de la plateforme
    (p. ex. *variables d'environnement Railway* scoping par environnement), injectés au conteneur au
    démarrage — jamais dans l'image ni le dépôt.
  - **CI/CD** : si la CI pousse des images ou déclenche des déploiements, utiliser des **GitHub
    Environments** (`staging`, `production`) avec **secrets scoping par environnement** + *required
    reviewers* sur `production`. Sinon, `GITHUB_TOKEN` minimal uniquement.
  - **Développement local** : `.env` (gitignoré) copié depuis `.env.example` ; aucune valeur réelle
    partagée via le dépôt.
  - *(Alternative à évaluer)* secrets chiffrés versionnés via **SOPS + age** si l'on veut une source
    de vérité dans le dépôt indépendante de la plateforme (voir Risks).
- **Stratégie de registre d'images** : push vers **GHCR** sur `main`/tags (avec `permissions:
  packages: write` + `GITHUB_TOKEN`, jamais de PAT en clair) **ou** *deploy-from-source* géré par la
  plateforme. Lève le point différé d'ADR-0010.
- **Modèle d'environnements** dev/staging/prod (voir §2) et **stockage objet** (bucket managé vs S3/R2/
  MinIO — peut rester différé jusqu'à la première feature d'upload M2 si non requis ici ; documenter la
  surface).
- **Sauvegardes** : politique (fréquence, rétention, restauration) — voir §4.

Mettre à jour l'**index** `docs/adr/README.md` (ligne ADR-0011 ; convertir les points différés
correspondants en « tranchés par ADR-0011 » ; laisser SMS concret / stockage objet différés si tel est
le choix).

### 2. Modèle d'environnements & matrice de configuration

Décrire les **trois environnements** et leur **isolation stricte** (secrets, bases et buckets
**distincts** par environnement) :

| Environnement | Rôle | Données | Où vivent les valeurs | Accès |
| --- | --- | --- | --- | --- |
| **dev** | Poste développeur / local | Données synthétiques jetables | `.env` local (gitignoré), `deploy/docker-compose.yml` | Développeur |
| **staging** | Pré-production **reproductible**, reflète prod | **Non réelles** (jeu de démo/anonymisé) | Magasin de secrets plateforme (env `staging`) + GitHub Environment `staging` | Équipe (large) |
| **prod** | Production | Données réelles (PII) | Magasin de secrets plateforme (env `production`) + GitHub Environment `production` (reviewers requis) | Restreint (moindre privilège) |

Publier une **matrice de configuration** listant, **par service** (`backend`, `web-dashboard`) et **par
environnement**, chaque variable, sa nature (**secret** vs **non secret**), sa source, et si elle est
**exposée au navigateur** (`NEXT_PUBLIC_*`). Inventaire **actuellement consommé par le code** (à ne pas
étendre au-delà du réel — cf. contrainte « ne pas impliquer de comportement non implémenté ») :

- `backend` : `DATABASE_URL` *(secret)*, `REDIS_URL` *(secret)*, `JWT_SECRET` *(secret, requis dès #8)*,
  `APP_NAME` *(non secret)*, `APP_ENV` *(non secret : `development`/`staging`/`production`)`.
- `web-dashboard` : `NEXT_PUBLIC_API_BASE_URL` *(non secret, exposé navigateur)*.
- **Surface *future* (documentée comme réservée, non câblée)** : stockage objet (`S3_ENDPOINT`,
  `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`), FCM, SMS — **inventoriée dans
  la politique de secrets**, marquée « issue future », **sans** l'ajouter aux `.env.example` tant que le
  code ne la lit pas (éviter d'impliquer une intégration inexistante).

### 3. `staging` reproductible — configuration déclarative + runbook

- **Configuration déclarative non secrète versionnée** décrivant la **topologie** (services `backend`
  + `web-dashboard`, dépendances managées Postgres 16 + Redis 7, éventuel bucket objet, réseau,
  variables **non secrètes** et **références** de secrets par *nom*). Deux briques complémentaires :
  - `deploy/docker-compose.yml` (**nouveau**) : orchestration locale/dev (et base de parité staging)
    des images `backend`/`web` + Postgres 16 + Redis 7 ; **valeurs via `.env`/variables**, **aucun
    secret en clair** ; ne fait que **référencer** les images buildées par #4.
  - Config plateforme reproductible : selon la décision d'ADR-0011, soit un fichier déclaratif
    committé (p. ex. `railway.json`/service config **sans secret**), soit un **runbook** décrivant la
    recréation de l'environnement `staging` via la skill/MCP `use-railway` (créer projet/environnement,
    provisionner Postgres/Redis/bucket, poser les **variables non secrètes**, référencer les secrets).
- **Runbook `staging`** (dans la doc d'environnements) : étapes ordonnées et **idempotentes** pour
  recréer `staging` de zéro — provisionnement des services managés, application des migrations
  (`alembic upgrade head`, cf. #3/#4 ; l'extension `btree_gist` doit être disponible — voir Risks
  Postgres managé), déploiement des images, *smoke tests* (`GET /health` backend, page d'accueil web,
  déjà éprouvés en CI #4), seed de données **non réelles**. Objectif : **« staging reproductible »**
  = un opérateur suit le runbook et obtient un environnement fonctionnel sans savoir tacite.

### 4. Sauvegardes activées + restauration

- **PostgreSQL** : activer la **sauvegarde automatique quotidienne** (PRD §12.2) via le mécanisme
  managé de la plateforme (ou un `pg_dump` planifié documenté à défaut) ; définir la **rétention**
  (proposition : 7 jours glissants minimum, à confirmer) et le **chiffrement au repos** des
  sauvegardes.
- **Procédure de restauration documentée** + **test de restauration** périodique (restaurer une
  sauvegarde `prod` vers un environnement jetable et vérifier l'intégrité) : une sauvegarde non testée
  n'est pas une sauvegarde.
- **Stockage objet** (si provisionné) : activer le **versionnement**/backup du bucket ; sinon
  documenter que le point est différé jusqu'à la première feature d'upload (M2).
- **Redis** : rappeler que Redis est **cache/queue**, **pas** source de vérité (ADR-0004) — pas de
  sauvegarde critique requise ; documenter la reconstruction depuis Postgres.

### 5. Politique de secrets documentée — `docs/environnements-et-secrets.md`

Document opérationnel unique (satisfait *« politique de secrets documentée »* + héberge la matrice §2,
le runbook §3 et la procédure de sauvegarde §4). Sections :

1. **Modèle d'environnements** (§2) et **matrice de configuration** par service/env.
2. **Politique de secrets** : **inventaire** (nom, environnement, magasin, propriétaire) ; **où ils
   vivent** (magasin plateforme / GitHub Environments, **jamais le dépôt**) ; **injection** (variables
   d'environnement à l'exécution) ; **moindre privilège** (qui accède à quoi ; prod restreint) ;
   **rotation** (fréquence, procédure, rotation immédiate en cas de fuite) ; **conduite en cas de
   fuite** (révoquer, régénérer, purger, auditer) ; **règles de non-journalisation** (ne jamais logger
   secrets ni PII — renvoi PRD §11.3/§11.4 ; ne pas `echo`/dumper l'environnement en CI).
3. **Runbook `staging` reproductible** (§3) et **provisionnement**.
4. **Sauvegardes & restauration** (§4).
5. **Renvois** : CONTRIBUTING « Secrets », ADR-0011, invariants CI (#4/ADR-0010), frontière de secrets
   ADW (`adw_sdlc/src/env.ts`, `lint:env`).

### 6. Consolidation de la surface de configuration (léger)

- **Aligner les `.env.example`** existants sur la matrice §2 (commentaires précisant : *secret* vs
  *non secret*, environnement cible, et pour le web l'avertissement `NEXT_PUBLIC_*` = exposé
  navigateur). **Ne pas** y injecter de valeur réelle ; **ne pas** ajouter de variable non lue par le
  code (surface future → politique de secrets seulement).
- *(Optionnel — décision, voir Risks)* introduire un **module de configuration typé** côté backend
  (`pydantic-settings`) validant/centralisant les variables au démarrage (fail-fast si un secret requis
  manque). **Nouvelle dépendance** — peut être **reporté à #8** (auth, où `JWT_SECRET` devient
  obligatoire). Au MVP, la lecture `os.environ` existante suffit ; ne pas sur-construire.

### 7. Verrouillage du merge & registre (suivis d'ADR-0010)

- **Protection de branche `main`** : consigner la **liste des status checks requis** (`backend`, `web`,
  `mobile`, `docker-backend`, `docker-web` ; `dependency-scan` informatif) et l'**appliquer** (réglage
  dépôt, **non versionnable** — Settings → Branches / `gh api`, par un administrateur). **Documenter
  l'interaction avec la phase `merge` du pipeline ADW** : confirmer qu'elle **attend** les checks (pas
  de contournement) — sinon « CI verte obligatoire avant merge » n'est pas réellement garanti.
- **Registre d'images** : selon ADR-0011, activer le **push GHCR** (least-privilege `packages: write`)
  ou le *deploy-from-source*. Si push : n'élargir les `permissions:` que sur le job concerné.

> **Contrainte transverse (planning-only).** Aucune de ces étapes ne provisionne réellement quoi que
> ce soit pendant la phase de *planification* : cette spec **décrit** le travail. La phase
> d'implémentation ultérieure pourra utiliser la skill/MCP `use-railway` pour provisionner, en
> respectant strictement « aucun secret dans le dépôt ni dans les logs ».

## Affected Files / Packages / Modules

À **créer** (issue #5) :
- `docs/adr/0011-deploiement-environnements-secrets.md` — décision : hébergement/région, magasin de
  secrets & injection, modèle d'environnements, stratégie de registre, sauvegardes.
- `docs/environnements-et-secrets.md` — doc opérationnelle : modèle d'environnements + matrice de
  config, **politique de secrets**, runbook `staging` reproductible, sauvegardes & restauration.
- `deploy/docker-compose.yml` — topologie non secrète (backend + web + Postgres 16 + Redis 7),
  valeurs par variables/`.env`, référence les images de #4 (aucun secret en clair).
- *(Selon ADR-0011)* config plateforme déclarative non secrète (p. ex. `railway.json`/service config)
  **ou** section runbook `use-railway` équivalente.
- *(Optionnel)* `deploy/.env.example` — gabarit non secret pour `docker-compose` (si utile).

À **modifier** :
- `backend/.env.example`, `web-dashboard/.env.example` — commentaires alignés sur la matrice (secret vs
  non secret, env cible, avertissement `NEXT_PUBLIC_*`) ; **aucune valeur réelle ajoutée**.
- `.gitignore` — si `deploy/` introduit des `.env` locaux, garantir qu'ils sont ignorés (et **ne
  jamais** ignorer les `*.env.example`).
- `README.md` (racine) — §4 (ligne « Déploiement » : refléter l'hébergement/environnements/sauvegardes
  tranchés par ADR-0011) + une note « Environnements & secrets » renvoyant à
  `docs/environnements-et-secrets.md` ; §5 (structure : `deploy/`).
- `docs/adr/README.md` — index : ajouter ADR-0011 ; mettre à jour les points différés désormais
  tranchés (hébergement/région, registre, sauvegardes ; laisser SMS/stockage objet différés si tel est
  le choix).
- `CONTRIBUTING.md` — « Secrets » : renvoyer à la politique désormais écrite
  (`docs/environnements-et-secrets.md`) au lieu de « objet de l'issue #5 ».
- *(Optionnel)* `backend/pyproject.toml` — ajout de `pydantic-settings` si le module de config typé est
  retenu (sinon **ne pas** modifier).

À **lire** pour construire juste :
- `specs/pipeline-ci-cd-github-actions.md`, `docs/adr/0010-ci-cd-docker-packaging.md` (invariants
  CI/Docker, points différés à #5).
- `backend/Dockerfile`, `web-dashboard/Dockerfile`, `.github/workflows/ci.yml`, `.github/dependabot.yml`.
- `backend/coiflink_api/main.py`, `.../persistance/session.py`, `backend/migrations/env.py`,
  `backend/pyproject.toml` (surface de config réellement consommée).
- `*.env.example`, `.gitignore`, `CONTRIBUTING.md` (« Secrets »).
- ADR-0004 (sauvegardes/Redis), ADR-0005 (stockage objet/clés S3), ADR-0006 (FCM/SMS), ADR-0009
  (`DATABASE_URL`/`btree_gist`), `docs/adr/README.md` ; PRD §10.2/§11/§12.2/§18.

À **ne pas toucher** : `adw_sdlc/`, `adw/`, `scripts/` (frontière de secrets du pipeline ADW),
`.claude/`, `.pi/`, le schéma/migrations #3, la logique métier des paquets, `adw-sdlc.yml`, et les
`*.env.example` en tant que **placeholders** (aucune valeur réelle).

## API / Interface Changes

- **API réseau / publique** : **none.** #5 n'ajoute ni ne modifie aucune route (le backend garde son
  seul `GET /health`) ni aucun contrat client. Seules changent la **configuration** et l'**exploitation**.
- **Surface opérateur / développeur (nouvelle, documentée)** :
  - **Environnements nommés** `dev`/`staging`/`prod` comme concepts d'exploitation (magasin de secrets,
    GitHub Environments), avec un **jeu de variables** contractualisé par la matrice de config.
  - **Commande locale** `docker compose -f deploy/docker-compose.yml up` (parité dev/staging) —
    interface développeur nouvelle, documentée.
  - **`APP_ENV`** prend des valeurs explicites (`development`/`staging`/`production`) — convention
    documentée (pas de changement de code requis : déjà lu par `main.py`).
  - *(Selon ADR-0011)* **images publiées** vers un registre (tags) — interface de distribution nouvelle.
- Aucun changement aux interfaces du pipeline ADW (`scripts/run-issue.sh`, `MX_AGENT_*`,
  `adw-sdlc.yml`) ni à celles de la CI applicative au-delà d'un éventuel push registre.

## Data Model / Protocol Changes

**None.** #5 ne modifie ni schéma, ni migration (#3), ni format de sérialisation. Le runbook
**exécute** les migrations existantes (`alembic upgrade head`) contre les bases *staging*/*prod*
managées, sans changer leur contenu. Les **sauvegardes** portent sur les **données** (dumps Postgres),
pas sur un changement de modèle. La seule « nouveauté persistée » hors code est **opérationnelle** :
artefacts de sauvegarde (chiffrés, hors dépôt) et valeurs de configuration (dans le magasin de
secrets, hors dépôt).

## Security & Privacy Considerations

- **Secrets — invariant critique (cœur de #5).** Aucun secret ne doit **jamais** être committé,
  journalisé ou intégré à une image. Les secrets réels vivent **hors dépôt** (magasin plateforme /
  GitHub Environments) et sont **injectés par variables d'environnement** à l'exécution. Les
  `*.env.example` restent des **placeholders** ; les fichiers de config versionnés (`docker-compose`,
  config plateforme) ne contiennent que du **non secret** et des **références** de secrets par nom.
- **Isolation par environnement** : bases, buckets et secrets **distincts** dev/staging/prod ; **moindre
  privilège** sur `prod` (accès restreint, reviewers requis sur le GitHub Environment `production`).
  `staging` n'utilise **jamais** de données réelles (PII) — jeu de démo/anonymisé (PRD §11.3 : collecte
  minimale, données personnelles protégées).
- **Rotation & fuite** : politique de **rotation** documentée + **conduite en cas de fuite** (révoquer,
  régénérer, purger l'historique si un secret a fuité, auditer les accès). Prévoir la rotation
  immédiate de tout secret exposé.
- **Non-journalisation** : ne jamais logger secrets ni **PII** (PRD §11.3/§11.4 journalise des
  *actions*, pas des *valeurs*) ; en CI/scripts, ne pas `echo` ni dumper l'environnement ; masquer les
  variables sensibles côté plateforme.
- **Sauvegardes** : **chiffrées au repos**, accès restreint, **rétention** définie ; la restauration ne
  doit pas exposer de PII hors du périmètre autorisé ; tester la restauration sur environnement isolé.
- **Résidence / région des données** : le PRD cible la Côte d'Ivoire / l'Afrique de l'Ouest ; la
  **région d'hébergement** (latence + éventuelle résidence) est une **décision à acter** (ADR-0011) —
  le dépôt ne documente pas d'obligation légale de résidence à ce jour ; à confirmer (voir Risks).
- **Chaîne d'approvisionnement** : conserver Dependabot + le scan de dépendances (#4) ; le
  **durcissement bloquant** et l'**épinglage SHA** des actions sont des suivis recommandés (ADR-0010),
  optionnels ici. Si push GHCR : `permissions: packages: write` **scopé** au job, `GITHUB_TOKEN` (jamais
  de PAT en clair).
- **Cohérence avec la frontière de secrets ADW** : les secrets **du pipeline** (`GH_TOKEN`, clé runner)
  restent gérés par `adw_sdlc/src/env.ts`/`lint:env` — #5 ne les touche pas ; la politique renvoie à ce
  précédent comme modèle.
- **Préférence utilisateur** : aucun marqueur « généré par IA » dans les docs, ADR, ou fichiers de
  config produits.

## Testing Plan

La « valeur testée » de #5 est **opérationnelle et documentaire** (pas de code métier). À vérifier :

- **Reproductibilité de `staging`** : suivre le **runbook** de zéro doit produire un `staging`
  fonctionnel — services up, migrations appliquées (`alembic upgrade head` réussit ; `btree_gist`
  disponible), **smoke tests** verts (`GET /health` → 200 ; page d'accueil web répond, comme en CI #4),
  seed non réel chargé. Idempotence : relancer le runbook ne casse rien.
- **Parité locale** : `docker compose -f deploy/docker-compose.yml up` démarre backend + web + Postgres
  16 + Redis 7 ; `GET /health` répond ; **aucun secret** requis en clair (valeurs via `.env` gitignoré).
- **Injection des secrets hors dépôt** : vérifier qu'un secret **absent** fait échouer proprement
  (backend `database_url()` lève déjà si `DATABASE_URL` manquant) ; qu'un secret **présent** provient du
  magasin/env et **n'apparaît pas** dans le dépôt ni dans les logs (relire les logs de déploiement/CI).
- **Sauvegardes/restauration** : déclencher/valider une sauvegarde Postgres ; **restaurer** vers un
  environnement jetable et vérifier l'intégrité (compte de tables/lignes attendu) — au moins une fois,
  puis périodiquement.
- **Zéro secret dans le dépôt** : `git grep`/revue ciblée + un **contrôle de secrets** (p. ex.
  `gitleaks` / scan de patterns) sur les fichiers ajoutés (`deploy/`, docs, config) — **aucune**
  détection ; les `*.env.example` ne contiennent que des placeholders.
- **Non-régression CI** : `ci.yml` (#4) et `adw-sdlc.yml` restent verts et indépendants ; si push GHCR
  ajouté, le job pousse **uniquement** avec `packages: write` scopé et ne fuit aucun token.
- **Documentation** : liens valides (README → doc environnements → ADR-0011) ; la matrice de config
  couvre toutes les variables réellement lues par le code ; la politique de secrets est complète
  (inventaire, rotation, fuite, non-journalisation).

> Note : #5 **n'ajoute pas** de tests métier ni e2e (#50) ; les vérifications sont des contrôles
> opérationnels/documentaires. Aucun test unitaire nouveau n'est requis, sauf si le module de config
> typé optionnel est retenu (alors : test de fail-fast sur variable requise manquante).

## Documentation Updates

- **`docs/environnements-et-secrets.md`** *(nouveau)* : modèle d'environnements + matrice de config,
  **politique de secrets** (inventaire, magasin, injection, rotation, fuite, non-journalisation),
  runbook `staging` reproductible, sauvegardes & restauration.
- **`docs/adr/0011-deploiement-environnements-secrets.md`** *(nouveau)* : décision hébergement/région,
  magasin de secrets, environnements, registre d'images, sauvegardes.
- **`docs/adr/README.md`** : ajouter ADR-0011 à l'index ; mettre à jour les points différés tranchés
  (hébergement/région, registre, sauvegardes) ; conserver différés ceux qui le restent (SMS concret,
  éventuellement stockage objet).
- **`README.md`** (racine) : §4 (« Déploiement » : hébergement/environnements/sauvegardes) + note
  « Environnements & secrets » ; §5 (ajout `deploy/`) ; renvoi vers la nouvelle doc et ADR-0011.
- **`CONTRIBUTING.md`** : « Secrets » — remplacer « objet de l'issue #5 » par un renvoi à la politique
  écrite.
- **READMEs de paquet** *(léger)* : `backend/README.md` / `web-dashboard/README.md` — pointer vers la
  doc d'environnements pour la configuration par environnement (sans dupliquer).
- **`*.env.example`** : commentaires alignés sur la matrice (secret vs non secret ; `NEXT_PUBLIC_*`
  exposé navigateur) — **placeholders uniquement**.

## Risks and Open Questions

- **Plateforme d'hébergement & région (décision structurante, à acter).** Recommandation **Railway**
  (tooling `use-railway`/MCP déjà câblé ; environnements, Postgres/Redis managés + sauvegardes,
  variables par env, buckets, domaines natifs). **Alternatives** : Render, Fly.io, VPS + Docker Compose,
  AWS/GCP. **Question ouverte** : **région/résidence des données** pour l'Afrique de l'Ouest (latence +
  contrainte légale éventuelle non documentée à ce jour). À trancher dans ADR-0011.
- **Magasin de secrets — natif plateforme vs externe (à confirmer).** Recommandation MVP : **natif**
  (variables par environnement) + **GitHub Environments** pour la CI/CD. Alternative portable :
  **SOPS + age** (secrets chiffrés versionnés). Compromis : simplicité/couplage plateforme vs
  portabilité/complexité.
- **Périmètre CD (à cadrer).** #5 garantit la **reproductibilité** de `staging` (runbook + config) ;
  faut-il un **déploiement continu automatisé** (auto-deploy sur merge, promotions, rollback) ? Proposé
  **hors périmètre** MVP (déploiement manuel/documenté acceptable) — à confirmer, sinon issue dédiée.
- **Stockage objet — provisionner maintenant ou différer (à confirmer).** Aucune feature d'upload avant
  M2 ; option : **documenter la surface** (clés hors dépôt, ADR-0005) et **différer** le provisionnement
  concret, ou provisionner un bucket dès `staging`. Recommandation : documenter maintenant, provisionner
  quand la première feature d'upload arrive.
- **Registre d'images (à trancher).** Push **GHCR** (`packages: write` scopé) vs **deploy-from-source**
  géré par la plateforme. Impacte `ci.yml` (permissions) et le runbook.
- **Protection de branche `main` (réglage dépôt, non versionnable).** L'application des **checks
  requis** dépend d'un administrateur ; tant qu'elle n'est pas posée, « CI verte obligatoire » n'est pas
  techniquement forcé. **Interaction `merge` ADW** : confirmer que la phase `merge` **attend** les
  checks (pas de contournement) — décision d'exploitation à acter.
- **`btree_gist` sur Postgres managé (rappel ADR-0009).** La migration initiale requiert
  `CREATE EXTENSION btree_gist` ; sur un Postgres managé **restreint**, ce privilège peut manquer.
  Vérifier la disponibilité sur l'hébergeur retenu (le runbook doit l'inclure comme prérequis).
- **Module de config typé backend (optionnel).** `pydantic-settings` améliore la validation fail-fast
  mais **ajoute une dépendance** et touche du code applicatif. À reporter à #8 (auth) si l'on veut
  garder #5 purement infra/doc. Décision à confirmer.
- **Rétention/coût des sauvegardes.** Fréquence quotidienne (PRD §12.2) actée ; **rétention** exacte,
  **coût** et **fenêtre de restauration** cible (RPO/RTO) à confirmer.
- **Durcissements optionnels (ADR-0010).** Scan bloquant High/Critical et épinglage SHA des actions :
  décider s'ils entrent dans #5 ou restent suivis.

## Implementation Checklist

1. **Relire le contexte** : ADR-0010 + `specs/pipeline-ci-cd-github-actions.md` (points différés à #5) ;
   `Dockerfile`s, `ci.yml`, `dependabot.yml` ; surface de config réellement lue (`main.py`, `session.py`,
   `migrations/env.py`, `pyproject.toml`) ; `*.env.example`, `.gitignore`, CONTRIBUTING ; ADR-0004/0005/
   0006/0009 ; PRD §10.2/§11/§12.2/§18.
2. **Trancher les décisions ouvertes** (et les tracer dans ADR-0011) : (a) **hébergement + région**
   (Railway recommandé) ; (b) **magasin de secrets & injection** (natif + GitHub Environments ; ou
   SOPS+age) ; (c) **registre d'images** (GHCR vs deploy-from-source) ; (d) **stockage objet** (différer
   ou provisionner) ; (e) **périmètre CD** (manuel documenté vs automatisé) ; (f) **rétention
   sauvegardes** (RPO/RTO).
3. **Rédiger `docs/adr/0011-deploiement-environnements-secrets.md`** (format ADR-0000) et **mettre à
   jour `docs/adr/README.md`** (index + points différés désormais tranchés).
4. **Rédiger `docs/environnements-et-secrets.md`** : modèle d'environnements + **matrice de config** par
   service/env ; **politique de secrets** (inventaire, magasin, injection, moindre privilège, rotation,
   conduite en cas de fuite, non-journalisation) ; **runbook `staging` reproductible** ; **sauvegardes
   & restauration**.
5. **Créer `deploy/docker-compose.yml`** : backend + web + Postgres 16 + Redis 7 ; images de #4 ;
   valeurs par variables/`.env` (gitignoré) ; **aucun secret en clair** ; *(optionnel)* `deploy/.env.example`.
6. **Config plateforme reproductible** (selon ADR-0011) : committer un descriptif déclaratif **non
   secret** (p. ex. `railway.json`) **ou** documenter le runbook `use-railway` équivalent (créer
   projet/env `staging`, provisionner Postgres/Redis/bucket, poser variables **non secrètes**,
   référencer les secrets par nom).
7. **Aligner les `.env.example`** (commentaires secret/non-secret, env cible, avertissement
   `NEXT_PUBLIC_*`) — **aucune valeur réelle**, **aucune variable non lue par le code**.
8. **Activer les sauvegardes** Postgres (quotidiennes, rétention, chiffrées) + **documenter et tester**
   la restauration sur environnement jetable.
9. **(Selon ADR-0011) Push GHCR** : ajouter le push sur `main`/tags avec `permissions: packages: write`
   **scopé** au job, `GITHUB_TOKEN` (jamais de PAT) — sinon ne pas modifier `ci.yml`.
10. **Protection de branche `main`** : consigner la liste des checks requis (`backend`, `web`, `mobile`,
    `docker-backend`, `docker-web`) et l'appliquer (réglage dépôt, administrateur) ; **documenter
    l'interaction avec la phase `merge` ADW**.
11. **(Optionnel) Module de config typé backend** (`pydantic-settings`) avec fail-fast + test de
    variable requise manquante — sinon reporter à #8.
12. **Docs transverses** : mettre à jour `README.md` (§4 déploiement + note environnements/secrets ; §5
    `deploy/`), `CONTRIBUTING.md` (« Secrets » → renvoi politique), READMEs de paquet (renvoi léger).
13. **Vérifs finales (critères d'acceptation)** : **secrets injectés hors dépôt** (aucun secret dans le
    dépôt/les logs ; scan `gitleaks` propre) ; **`staging` reproductible** (runbook rejoué de zéro,
    smoke tests verts, idempotent) ; **politique de secrets documentée** (inventaire/rotation/fuite/
    non-journalisation) ; **sauvegardes activées** + restauration testée ; `ci.yml` et `adw-sdlc.yml`
    non régressés ; **aucun marqueur « généré par IA »**.
