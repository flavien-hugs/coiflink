# Déploiement production — mise en service, monitoring, sauvegardes vérifiées & rollback

> Spécification de planification pour l'issue GitHub **#54 — Déploiement production**
> (`infra` · Priorité **Must** · Effort **L** · PRD §10.2 / §12.2 / §18 Sprint 6).
> **Dépend de #5** (environnements & gestion des secrets) — **satisfaite** :
> [ADR-0011](../docs/adr/0011-deploiement-environnements-secrets.md) tranche l'hébergement
> (**Railway**, région `europe-west4`), le magasin de secrets, le modèle d'environnements
> *dev/staging/prod*, le registre (*deploy-from-source*) et la **politique** de sauvegardes ;
> [docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md) porte le **runbook `staging`
> reproductible** et la procédure de sauvegarde/restauration.
> **Cette spec ne produit pas de code applicatif métier.** Elle décrit le travail
> d'infrastructure/exploitation/documentation à réaliser dans une phase d'implémentation ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, specs). Les en-têtes de
> section ci-dessous sont conservés en anglais car attendus par le gabarit du pipeline ADW ; le contenu
> livré (docs, ADR, config) reste en français hors identifiants techniques. **Aucun marqueur
> « généré par IA »** (préférence utilisateur) dans les artefacts produits.

## Problem Statement

Le socle de déploiement est **décidé et outillé** par #5, mais **rien n'est réellement en production** :

- **ADR-0011** acte Railway / `europe-west4` / *deploy-from-source* et le modèle *dev/staging/prod* ; le
  **runbook** de `docs/environnements-et-secrets.md` sait recréer **`staging`** de zéro, avec une
  clause de **parité `prod`** (« `prod` suit le même runbook sur l'environnement `production` »). Mais
  l'environnement **`production` n'a pas été provisionné/déployé** dans le cadre de #5 (périmètre
  purement infra/doc).
- La **config déclarative non secrète** existe (`deploy/railway/backend.json`, `deploy/railway/web.json`
  avec `healthcheckPath` `/health` et `restartPolicyType: ON_FAILURE`, `deploy/docker-compose.yml`), et
  les images Docker sont **buildées** en CI (#4, build-seul). Il reste à **mettre en service** l'app.
- Le PRD **§12.2** exige, au-delà du déploiement : **monitoring des services critiques**, **alertes en
  cas d'incident**, **disponibilité ≥ 99 %** et **sauvegarde automatique quotidienne**. Le
  **monitoring/alerting n'est pas encore adressé** (aucun ADR, aucune doc, aucune configuration) — c'est
  un manque net de #54.
- La **politique** de sauvegarde est écrite (#5, §5 de `docs/environnements-et-secrets.md` : quotidienne,
  rétention 7 j, chiffrée, procédure de restauration, test **périodique**), mais aucune sauvegarde n'a été
  **activée ni vérifiée** en réel (RPO/RTO non mesurés, aucun test de restauration consigné).
- Il n'existe **aucune procédure de rollback** documentée (retour à un déploiement antérieur ;
  cohabitation avec les migrations Alembic ; critères de décision, autorisation, communication).

Besoin (issue #54, critères d'acceptation) : **prod déployée et monitorée** ; **sauvegardes vérifiées** ;
**rollback documenté** — sans jamais committer/journaliser de secret ni de PII, et sans laisser croire
qu'une intégration (ex. suivi d'erreurs applicatif) existe si elle n'est pas réellement câblée.

## Goals

- **Production déployée** : provisionner/mettre en service l'environnement **`production`** sur Railway
  (backend + web + PostgreSQL 16 + Redis 7) **par parité stricte** avec le runbook `staging` de #5 —
  migrations appliquées (`alembic upgrade head`), *smoke tests* verts (`GET /health` → `200`, page
  d'accueil web), domaine public + **TLS**, secrets **injectés hors dépôt**, accès **restreint**.
- **Production monitorée** (PRD §12.2) : **monitoring des services critiques** (santé des services,
  métriques ressources, état des déploiements), **alertes en cas d'incident** (échec de déploiement,
  crash/redémarrages, indisponibilité `/health`), **surveillance de disponibilité** externe visant la
  **cible 99 %** — le tout **sans secret ni PII** dans les tableaux de bord, métriques ou alertes.
- **Sauvegardes vérifiées** : **activer** la sauvegarde automatique quotidienne de PostgreSQL
  `production` (rétention ≥ 7 j, chiffrée au repos) **et en prouver la restaurabilité** — au moins **un
  test de restauration** vers un environnement **jetable/isolé**, vérification d'intégrité, **RPO/RTO
  mesurés et consignés** dans un journal de vérification.
- **Rollback documenté** : un **runbook de retour arrière** reproductible et idempotent — retour de
  l'**application** à un déploiement antérieur (Railway *rollback*/redeploy), **stratégie base de
  données** (compatibilité des migrations, `alembic downgrade` vs restauration de sauvegarde), **critères
  de déclenchement**, **autorisation** (prod restreint) et **communication**.
- **Traçabilité de décision** : un **ADR** (proposé **ADR-0038**) actant l'**observabilité** retenue
  (native plateforme + surveillance externe ; suivi d'erreurs applicatif optionnel), la **politique
  d'alerting** et la **stratégie de rollback**.
- **Zéro régression / zéro secret** : ne casser ni `ci.yml` (#4) ni `adw-sdlc.yml` ; ne
  committer/journaliser aucun secret ni PII ; conserver les `*.env.example` comme seuls exemples
  (placeholders) ; préserver tous les invariants sécurité existants (deny-by-default, config par
  variables d'environnement, images non-root sans secret).

## Non-Goals

- **CD automatisé complet** (auto-deploy sur merge, promotions automatiques, blue/green, rollback
  **automatique**). #5 a acté un **déploiement manuel/documenté** au MVP ; #54 **exécute** la mise en
  prod et **documente** le rollback (manuel), il n'introduit **pas** l'automatisation CD avancée — à
  cadrer en évolution ultérieure (voir Risks).
- **Refonte du socle #5** : le modèle d'environnements, la matrice de configuration, la politique de
  secrets et le runbook `staging` sont **acquis** ; #54 les **applique** à `production` et les **étend**
  (monitoring, vérification sauvegardes, rollback), il ne les réécrit pas.
- **Optimisation de performance** (tuning, montée en charge) : mesurée par **#52** (perf, informatif,
  `PERF_TARGET_URL` vise staging). #54 **vérifie la disponibilité**, il ne corrige pas les budgets §12.1.
- **Préparation du pilote & formation des 10 salons** : périmètre de **#55** (dépend de #54). #54
  n'onboarde aucun salon réel et ne charge **aucune PII réelle** hors du strict nécessaire à la mise en
  service (le seed reste **non réel** tant que le pilote n'a pas démarré).
- **Fournisseur SMS concret / clés FCM** (ADR-0006, M5), **provisionnement d'un nouveau fournisseur de
  stockage objet** : hors périmètre ; le bucket médias est **déjà actif depuis #15** — #54 se limite à
  **vérifier** son **versionnement/backup** (ADR-0005), sans en changer le fournisseur.
- **Suivi d'erreurs applicatif obligatoire** (ex. Sentry) : **optionnel** et **décision à confirmer**
  (ajoute une dépendance + un secret `SENTRY_DSN` + une surface de PII à masquer). Par défaut, #54 ne
  **prétend pas** qu'un tel suivi existe ; s'il n'est pas retenu, le monitoring repose sur les
  mécanismes natifs Railway + une sonde de disponibilité externe.
- **Modifier le schéma / les migrations (#3)** ou la **logique métier** des paquets. La seule évolution
  de **code** envisagée est **optionnelle** (sonde de *readiness* — voir Proposed Implementation §3), et
  reste strictement technique (adapter entrant, aucun cas d'usage métier).
- **Toucher la frontière de secrets du pipeline ADW** (`adw_sdlc/src/env.ts`, `lint:env`, rétention de
  `GH_TOKEN`) : hors périmètre, sert de **précédent** (« secrets hors de portée de l'agent »).

## Relevant Repository Context

**Nature du dépôt.** Monorepo greenfield outillé pour livraison agentique : `app-mobile/` (Flutter),
`web-dashboard/` (Next.js), `backend/` (FastAPI, architecture **hexagonale** — ADR-0008), control plane
`adw_sdlc/`, CI applicative `ci.yml` (#4) + CI control plane `adw-sdlc.yml`. **M6 en cours** : e2e (#50),
sécurité (#51), perf (#52), guides utilisateur (#53) livrés ; #54 est la **mise en production**.

**Ce qui est déjà en place et réutilisé par #54.**
- **Décision de socle** — [ADR-0011](../docs/adr/0011-deploiement-environnements-secrets.md) (#5) :
  Railway, **région `europe-west4`**, *deploy-from-source* (Railway build les `Dockerfile` committés),
  magasin de secrets **natif plateforme + GitHub Environments** (`staging` large, `production`
  **reviewers requis / accès restreint**), **isolation stricte** des environnements, **politique de
  sauvegardes** (quotidienne, rétention 7 j, chiffrée, RPO ≤ 24 h, RTO à mesurer au **premier test**).
- **Doc opérationnelle** — [docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md) :
  modèle d'environnements, **matrice de configuration** par service (`backend`, `web-dashboard`),
  **politique de secrets** (inventaire, rotation, conduite en cas de fuite, **non-journalisation**),
  **runbook `staging` reproductible** (9 étapes idempotentes, dont le **prérequis `CREATE EXTENSION
  btree_gist`** d'ADR-0009), et **§5 Sauvegardes & restauration** (procédure + test périodique). La
  **clause de parité `prod`** y figure déjà : #54 l'**exécute** et **complète** ce document (monitoring,
  vérification, rollback).
- **Config déclarative non secrète** — `deploy/railway/backend.json` (`build.builder=DOCKERFILE`,
  `startCommand` uvicorn, **`healthcheckPath: "/health"`**, `restartPolicyType: ON_FAILURE`,
  `restartPolicyMaxRetries: 10`, `numReplicas: 1`) et `deploy/railway/web.json` (`node server.js`,
  `healthcheckPath: "/"`). Ces fichiers sont **partagés** entre environnements ; ce qui diffère par
  environnement, ce sont les **variables** (magasin Railway). `deploy/docker-compose.yml` fournit la
  parité locale (backend + web + Postgres 16 + Redis 7 + MinIO), **aucun secret en clair**.
- **Sonde de santé** — `backend/coiflink_api/adapters/inbound/health.py` : `GET /health` renvoie
  `{"status": "ok"}` **sans** accès base ni PII ; c'est une **sonde de liveness** pure (par choix :
  `security.py` la qualifie de « sonde sans coût »). Elle est **exemptée** du deny-by-default
  (`PUBLIC_ROUTE_PATHS` dans `backend/coiflink_api/adapters/inbound/security.py`, ligne `"/health"`) et
  déjà éprouvée en CI (#4). **Elle ne teste pas la connectivité base** — point clé pour le monitoring
  (voir Proposed Implementation §3).
- **Images Docker** (#4/ADR-0010) : base slim épinglée, **utilisateur non-root**, config **injectée à
  l'exécution**, aucun secret intégré, `.dockerignore` excluant `.env*`. **Build-seul** en CI ; Railway
  déploie **depuis la source** (ADR-0011).
- **Surface de config réellement consommée** (matrice #5) : backend lit `DATABASE_URL` *(secret,
  fail-fast si absent — `.../persistence/session.py`)*, `REDIS_URL`, `JWT_SECRET` *(503 si absent sur
  `/auth/*`, sans casser `/health`)*, `S3_*`/`MEDIA_*` *(503 sur routes médias si absent)*,
  `APP_NAME`/`APP_ENV` ; web lit `NEXT_PUBLIC_API_BASE_URL` *(exposé navigateur, jamais un secret)*.
  `main.py` lit déjà `APP_ENV` (valeur `production` attendue en prod — aucun changement de code requis).
- **Perf/disponibilité** — `.github/workflows/perf.yml` (#52) : job **opt-in, non requis**, vise
  `staging` via `PERF_TARGET_URL` ; **informatif**. #54 ne le rend **pas** bloquant.

**Références PRD.** §10.2 (Déploiement : Docker · CI/CD · **hébergement cloud sécurisé** ·
**sauvegardes automatiques**) ; §12.2 (**Disponibilité ≥ 99 %**, **sauvegarde quotidienne**,
**monitoring des services critiques**, **alertes en cas d'incident**) ; §18 Sprint 6 (**Déploiement
production**, **Monitoring activé** comme critère de sortie) ; §11.3/§11.4 (PII, journalisation
d'**actions** — jamais de secret/valeur/PII dans logs, métriques ou alertes).

**Outillage d'hébergement présent.** Serveur MCP **`railway`** + skill **`use-railway`**
(provisionnement projets/services/bases, buckets, environnements, variables, domaines, **métriques**,
**logs**, **déploiements/rollback**). La phase d'implémentation les utilisera pour provisionner
`production`, activer/vérifier les sauvegardes et configurer le monitoring — **jamais** de secret dans le
dépôt ni dans les logs.

**Statut du code applicatif pour ce périmètre.** Il **n'existe aujourd'hui** ni environnement
`production` provisionné, ni configuration/documentation de **monitoring**, ni **runbook de rollback**,
ni **journal de vérification des sauvegardes**. #54 **crée** ces artefacts (exploitation + documentation
+ config non secrète) et, **optionnellement**, une **sonde de readiness** (code technique). Aucune
logique métier n'est introduite.

## Proposed Implementation

Approche : **exécuter** la mise en production (parité `prod` du runbook #5), **outiller** l'observabilité
et le rollback, **vérifier** les sauvegardes, et **tracer** ces choix (ADR + doc opérationnelle). La
plateforme est **stack-dépendante** : **Railway** est acté par ADR-0011 ; le plan reste **portable**
(principes valables pour Render/Fly.io/VPS). **Contrainte transverse (planning-only)** : cette spec
**décrit** le travail ; le provisionnement réel a lieu en phase d'implémentation via `use-railway`/MCP
`railway`, en respectant strictement « aucun secret dans le dépôt ni dans les logs ».

### 1. Mettre `production` en service (parité stricte du runbook #5)

Suivre le **runbook `staging`** de `docs/environnements-et-secrets.md` §4 sur l'environnement
**`production`**, en respectant les différences de parité (données réelles à terme, **accès restreint**,
**reviewers requis**, sauvegardes **activées**) :

1. **Projet & environnement** : sélectionner le projet CoifLink, créer/sélectionner l'environnement
   `production` (région `europe-west4`).
2. **Dépendances managées** : provisionner **PostgreSQL 16** + **Redis 7** dans `production`.
   **Prérequis vérifié** : `CREATE EXTENSION btree_gist` autorisé (migration initiale, ADR-0009) —
   confirmer le privilège **avant** de migrer.
3. **Services applicatifs** : créer `backend` et `web` en **deploy-from-source** (`deploy/railway/*.json`).
4. **Variables non secrètes** : `APP_ENV=production`, `APP_NAME`, `NEXT_PUBLIC_API_BASE_URL` (URL
   publique de l'API), `API_BASE_URL` (réseau interne web→backend), `S3_ENDPOINT_URL`/`S3_BUCKET`/
   `S3_REGION` (non secrets).
5. **Secrets (hors dépôt)** : `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `S3_ACCESS_KEY_ID`/
   `S3_SECRET_ACCESS_KEY` posés **dans le magasin de l'environnement `production`** — **jamais** dans le
   dépôt ni les logs. Reviewers requis sur le GitHub Environment `production`.
6. **Migrations** : `alembic upgrade head` (contexte backend, `DATABASE_URL` de `production`). Le
   round-trip est validé en CI (#4).
7. **Domaine & TLS** : générer/attacher un **domaine public** (TLS géré par la plateforme) pour
   `backend` et `web`.
8. **Déploiement** : déployer `backend` puis `web`.
9. **Smoke tests prod** : `GET /health` → `200 {"status":"ok"}` ; page d'accueil web répond ;
   `alembic current` = `head`.

**Idempotence** : re-provisionner un service le met à jour sans dupliquer ; réappliquer les migrations
est un no-op si à jour ; re-poser une variable écrase l'ancienne valeur.

### 2. Monitoring & alerting (PRD §12.2)

Retenir une observabilité **native plateforme + surveillance externe**, décidée dans l'ADR (§5) :

- **Santé des services** : conserver le **healthcheck** Railway sur `/health` (backend) et `/` (web) —
  déjà déclaré dans `deploy/railway/*.json`. Le `restartPolicyType: ON_FAILURE` couvre le redémarrage
  automatique.
- **Métriques ressources & déploiements** : activer/consulter les **métriques Railway** (CPU, mémoire,
  réseau, redémarrages) et l'**état des déploiements** (build/deploy/crash) via `use-railway`/MCP.
- **Surveillance de disponibilité externe** : configurer une **sonde d'uptime** indépendante (par
  ex. un moniteur HTTP externe) qui interroge périodiquement `GET /health` du domaine public et
  **alerte** en cas d'échec — mesure la **cible 99 %** (PRD §12.2) hors de la plateforme (détecte aussi
  une panne réseau/plateforme).
- **Alertes en cas d'incident** : activer les **notifications Railway** (échec de déploiement, crash,
  redémarrages répétés) **et** l'alerte de la sonde d'uptime. **Canaux** (e-mail/webhook/chat) à
  décider ; **contrainte** : une alerte **ne doit contenir ni secret ni PII** (identifiant de service,
  code d'état, horodatage — **jamais** de valeur de variable, de jeton, de payload utilisateur).
- **Rétention de logs** : s'appuyer sur les **logs de déploiement** Railway (accès **restreint**) ;
  **ne jamais** logger secret ni PII (§11.3/§11.4 journalise des *actions*, pas des *valeurs*).
- **(Optionnel — décision, voir Risks) Suivi d'erreurs applicatif** (ex. Sentry) : s'il est retenu,
  l'intégrer côté backend (et/ou web) avec un **`SENTRY_DSN`** *(secret, hors dépôt)*, **scrubbing PII**
  actif, `traces_sample_rate` maîtrisé. **Ne pas** l'annoncer comme livré s'il n'est pas câblé.

### 3. (Optionnel) Sonde de *readiness* vérifiant les dépendances — décision à confirmer

Le monitoring « des **services critiques** » gagne à distinguer **liveness** (le process répond —
`/health` actuel) de **readiness** (les **dépendances** sont joignables — base). Deux options :

- **Option A (par défaut, aucun code)** : conserver `/health` en liveness pure ; la disponibilité de la
  base est **implicitement** surveillée par les routes réelles (une panne DB fait échouer `/auth/*`,
  les routes salon, etc.) et par les métriques Railway. **Le healthcheck de déploiement reste `/health`.**
- **Option B (léger, code technique)** : ajouter un **adapter entrant** `GET /health/ready` (ou
  `/health/db`) qui exécute un **`SELECT 1`** borné et renvoie `200` / `503` selon la connectivité base.
  **Contraintes** :
  - route **strictement technique** (aucun cas d'usage métier, patron `health.py`), **sans** exposer de
    détail interne (pas de DSN, pas de message d'exception brut) ;
  - **exemption deny-by-default obligatoire** : ajouter le chemin à `PUBLIC_ROUTE_PATHS`
    (`backend/coiflink_api/adapters/inbound/security.py`) — **avec revue de sécurité** (le module
    l'exige explicitement) ;
  - **ne pas** en faire le `healthcheckPath` du déploiement Railway (un blip DB transitoire
    déclencherait un *restart storm* via `ON_FAILURE`) ; l'utiliser pour la **sonde d'uptime**/le
    monitoring, **pas** pour la politique de redémarrage.

**Recommandation** : Option A au MVP (aucune dette, aucun élargissement de surface publique) ; retenir
l'Option B **seulement** si l'exploitation exige une readiness dédiée — à trancher dans l'ADR.

### 4. Sauvegardes vérifiées

- **Activer** la **sauvegarde automatique quotidienne** de PostgreSQL `production` (mécanisme managé
  Railway ; à défaut, `pg_dump` planifié chiffré et stocké **hors dépôt** — repli documenté par #5),
  **rétention ≥ 7 j** glissants, **chiffrée au repos**. **RPO ≤ 24 h** (ADR-0011).
- **Vérifier la restaurabilité** (« sauvegardes **vérifiées** » = critère d'acceptation) : suivre la
  **procédure de restauration** de `docs/environnements-et-secrets.md` §5 —
  1) sélectionner une sauvegarde ; 2) restaurer vers un **environnement jetable/isolé** (**jamais**
  directement sur `prod`) ; 3) vérifier l'**intégrité** (nombre de tables attendu, comptages cohérents,
  `alembic current` = révision attendue) ; 4) **mesurer le RTO** et le consigner.
- **Consigner** la vérification dans un **journal de vérification des sauvegardes** (date, identifiant de
  sauvegarde, résultat d'intégrité, **RTO mesuré**, opérateur) — **sans PII** ; ce journal vit dans la
  doc opérationnelle (voir §6). *Une sauvegarde non testée n'est pas une sauvegarde.*
- **Périodicité** : au moins **trimestrielle** (rappel #5) ; la restauration ne doit **pas** exposer de
  PII hors périmètre autorisé.
- **Redis** : **pas** de sauvegarde critique (cache/queue, ADR-0004) — reconstructible depuis Postgres.
- **Stockage objet** : le bucket médias est **actif depuis #15** ; **vérifier**/activer son
  **versionnement**/backup côté fournisseur (ADR-0005) — point à ne pas différer davantage.

### 5. Rollback documenté

Rédiger un **runbook de rollback** (idempotent, sans savoir tacite), couvrant :

- **Rollback applicatif** : revenir au **déploiement antérieur** sain via Railway (fonction *rollback*/
  redeploy d'un build précédent). En *deploy-from-source*, un rollback correspond à redéployer le
  **commit/build** précédent connu bon. Étapes ordonnées + **smoke tests** post-rollback (`/health`,
  page web).
- **Rollback base de données** (le point délicat) : arbre de décision explicite —
  - **Migration réversible, schéma seul** : `alembic downgrade <révision>` est envisageable (le
    **round-trip est validé en CI** #4 : `upgrade → downgrade → upgrade`), en cohérence avec le rollback
    applicatif.
  - **Migration avec transformation/perte de données** : **préférer un correctif en avant**
    (*forward-fix*) ou la **restauration d'une sauvegarde** (§4) plutôt qu'un downgrade destructeur.
  - **Règle de compatibilité** : privilégier des migrations **rétro-compatibles** (expand/contract) pour
    qu'un rollback applicatif reste possible **sans** downgrade immédiat.
- **Critères de déclenchement** : quoi observer (échec smoke tests, taux d'erreur, indisponibilité
  `/health`, alerte uptime) et **seuils** de décision.
- **Autorisation & communication** : `production` est **restreint** (reviewers requis) — qui autorise un
  rollback, comment il est communiqué, et **traçabilité** de l'incident (sans PII/secret dans le compte
  rendu).
- **Répétition** : le rollback est **répété sur `staging`** avant d'être considéré fiable (voir Testing).

### 6. Documentation & ADR

- **ADR (proposé `docs/adr/0038-...md`)** — format ADR-0000 (Statut, Contexte, Options, Décision,
  Justification, Conséquences) : acter (a) l'**observabilité** (native Railway + sonde uptime externe ;
  suivi d'erreurs applicatif **optionnel**), (b) la **politique d'alerting** (canaux, non-PII), (c) la
  **stratégie de rollback** (app + base, compatibilité des migrations), (d) le choix
  **liveness-only vs readiness** (§3). Mettre à jour l'**index** `docs/adr/README.md` (nouvelle ligne +
  point différé « monitoring/alerting » désormais tranché).
- **Doc opérationnelle** : **recommandé** — un nouveau document dédié `docs/mise-en-production.md`
  (**runbook `production`** : mise en service, **monitoring & alerting**, **journal de vérification des
  sauvegardes**, **runbook de rollback**), **cross-linké** depuis `docs/environnements-et-secrets.md`
  (§5 renvoie au journal de vérification). *Alternative* : étendre directement
  `docs/environnements-et-secrets.md` (nouvelles sections monitoring/rollback + journal) — au choix de
  l'implémenteur, mais **éviter la duplication** (une seule source par sujet).
- **README** (racine) : §4 (ligne « Déploiement » — refléter prod déployée/monitorée, sauvegardes
  vérifiées, rollback) et §6 (statut M6 : ajouter la mise en production) ; renvoi vers la doc de mise en
  production et l'ADR.

## Affected Files / Packages / Modules

À **créer** :
- `docs/adr/0038-<slug>.md` — décision : observabilité (monitoring/alerting), stratégie de rollback,
  liveness vs readiness. *(numéro à confirmer : prochain libre après ADR-0037.)*
- `docs/mise-en-production.md` *(recommandé)* — runbook `production` + monitoring/alerting + journal de
  vérification des sauvegardes + runbook de rollback. *(ou extension de `docs/environnements-et-secrets.md`.)*

À **modifier** :
- `docs/environnements-et-secrets.md` — §5 Sauvegardes : renvoyer au **journal de vérification** et
  consigner l'activation `production` ; éventuelles sections monitoring/rollback si l'alternative
  « tout dans un doc » est choisie.
- `docs/adr/README.md` — index (ajouter ADR-0038) + section « décisions différées » : marquer
  **monitoring/alerting §12.2** comme **tranché par ADR-0038**.
- `README.md` (racine) — §4 (Déploiement) et §6 (statut M6 — mise en production).
- *(Optionnel, selon décision §3/§2)* :
  - `backend/coiflink_api/adapters/inbound/health.py` — ajout d'une sonde `GET /health/ready` (readiness
    base) **si Option B retenue** ;
  - `backend/coiflink_api/adapters/inbound/security.py` — ajout du chemin à `PUBLIC_ROUTE_PATHS`
    **(avec revue de sécurité)** si readiness ajoutée ;
  - `backend/coiflink_api/main.py` — `include_router` si un nouveau router readiness est créé ;
  - `backend/.env.example` — commentaire `SENTRY_DSN` **si** le suivi d'erreurs est retenu (secret, hors
    dépôt) — **sinon ne rien ajouter** (ne pas impliquer une intégration inexistante).
- `deploy/railway/backend.json` / `deploy/railway/web.json` — **normalement inchangés** (le
  `healthcheckPath` reste `/health` / `/`) ; ne modifier que si une décision explicite l'exige
  (documentée dans l'ADR).

À **lire** pour construire juste :
- [ADR-0011](../docs/adr/0011-deploiement-environnements-secrets.md),
  [docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md) (runbook, secrets,
  sauvegardes), [ADR-0010](../docs/adr/0010-ci-cd-docker-packaging.md) (invariants CI/Docker),
  ADR-0004 (Redis/sauvegardes), ADR-0005 (stockage objet), ADR-0009 (`btree_gist`).
- `deploy/railway/backend.json`, `deploy/railway/web.json`, `deploy/docker-compose.yml`.
- `backend/coiflink_api/adapters/inbound/health.py`, `.../inbound/security.py` (`PUBLIC_ROUTE_PATHS`),
  `backend/coiflink_api/main.py`, `.../outbound/persistence/session.py` (fail-fast `DATABASE_URL`).
- `.github/workflows/ci.yml`, `.github/workflows/perf.yml` ; PRD §10.2/§12.2/§18 ; `specs/environnements-gestion-des-secrets.md`.

À **ne pas toucher** : `adw_sdlc/`, `adw/`, `scripts/` (frontière de secrets ADW), `.claude/`, `.pi/`,
le schéma/migrations (#3), la logique métier des paquets, `adw-sdlc.yml`, et les `*.env.example` en tant
que **placeholders** (aucune valeur réelle).

## API / Interface Changes

- **API réseau / publique** : **none** par défaut. Le backend garde ses routes existantes ; `/health`
  et `/` restent les sondes.
- **Surface optionnelle (décision, §3)** : si l'Option B est retenue, **une** nouvelle route
  **technique** `GET /health/ready` (ou `/health/db`) — **publique** (à ajouter à `PUBLIC_ROUTE_PATHS`
  après revue), renvoyant `200`/`503` selon la connectivité base, **sans** payload sensible. À
  **documenter** comme nouvelle route publique si ajoutée (README backend + doc de mise en production).
- **Surface opérateur (nouvelle, documentée)** : environnement **`production`** comme cible
  d'exploitation (domaine public + TLS, variables/secrets par environnement), **tableaux de bord de
  monitoring**, **sonde d'uptime externe**, **canaux d'alerte**, et un **runbook de rollback**. Aucune
  modification des interfaces du pipeline ADW ni de la CI applicative au-delà de ce périmètre.

## Data Model / Protocol Changes

**None.** #54 ne modifie ni schéma, ni migration (#3), ni format de sérialisation. Le runbook **exécute**
les migrations existantes (`alembic upgrade head`) contre la base `production` managée, sans en changer
le contenu. Les **sauvegardes** portent sur les **données** (dumps/snapshots Postgres), pas sur un
changement de modèle. Une éventuelle sonde de readiness n'exécute qu'un **`SELECT 1`** en lecture (aucune
écriture). La « nouveauté persistée » hors code est **opérationnelle** : artefacts de sauvegarde
(chiffrés, hors dépôt) et valeurs de configuration (magasin de secrets, hors dépôt).

## Security & Privacy Considerations

- **Secrets — invariant critique.** Aucun secret ne doit **jamais** être committé, journalisé ou intégré
  à une image. Les secrets de `production` (`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, clés S3, et
  `SENTRY_DSN` *si* retenu) vivent **hors dépôt** (magasin Railway `production` / GitHub Environment
  `production`) et sont **injectés par variables d'environnement** à l'exécution. Les `*.env.example`
  restent des **placeholders** ; `deploy/railway/*.json` et `docker-compose.yml` ne portent que du
  **non secret**.
- **Moindre privilège & isolation.** `production` est **restreint** (accès limité, **reviewers requis**
  sur le GitHub Environment `production`) ; bases/buckets/secrets **distincts** des autres environnements
  (ADR-0011). Les **logs de déploiement** et **tableaux de bord** de monitoring sont à accès restreint.
- **Non-journalisation / non-fuite dans le monitoring.** Métriques, alertes et logs **ne contiennent
  jamais** de secret ni de **PII** (PRD §11.3/§11.4 : on journalise des *actions*, pas des *valeurs*).
  Une alerte porte un **identifiant de service**, un **code d'état**, un **horodatage** — **jamais** un
  jeton, un DSN, un e-mail, un téléphone ou un payload utilisateur. Si un suivi d'erreurs applicatif est
  retenu, activer le **scrubbing PII** et ne jamais capturer de corps de requête sensible.
- **Sauvegardes.** **Chiffrées au repos**, accès restreint, **rétention** définie ; la restauration se
  fait vers un **environnement isolé** et **ne doit pas exposer de PII** hors périmètre autorisé ; le
  **journal de vérification** ne contient **aucune PII** (dates, identifiants techniques, RTO, résultat).
- **Sonde de readiness (si ajoutée).** Ne **jamais** divulguer de détail interne (DSN, exception brute) ;
  ajout à `PUBLIC_ROUTE_PATHS` **uniquement après revue de sécurité** (le module l'exige) ; **ne pas**
  la brancher sur la politique de redémarrage (`ON_FAILURE`) pour éviter un *restart storm*.
- **Résidence / région.** `europe-west4` optimise la latence Afrique de l'Ouest ; **aucune obligation
  légale de résidence** documentée à ce jour (question ouverte d'ADR-0011 — à confirmer avec le métier
  avant de charger de la PII réelle **prod** au pilote #55).
- **Disponibilité & TLS.** Domaine public **en TLS** (chiffrement en transit) ; cible **99 %**
  surveillée. **`btree_gist`** doit être autorisé sur le Postgres managé `production` (prérequis #5).
- **Cohérence avec la frontière de secrets ADW.** `GH_TOKEN`/clé runner restent gérés par
  `adw_sdlc/src/env.ts`/`lint:env` — hors périmètre de #54.
- **Préférence utilisateur.** Aucun marqueur « généré par IA » dans les docs, ADR ou config produits.

## Testing Plan

La « valeur testée » de #54 est **opérationnelle** (mise en service + vérifications) et **documentaire** ;
un seul volet **code** possible (readiness optionnelle) porte des tests unitaires. À vérifier :

- **Prod déployée (smoke tests réels)** : `GET /health` du domaine `production` → `200
  {"status":"ok"}` ; page d'accueil web répond (TLS valide) ; `alembic current` = `head` ; les routes
  protégées répondent `401` sans jeton (deny-by-default toujours actif). Idempotence : rejouer le runbook
  ne casse rien.
- **Monitoring vérifié** : healthcheck de déploiement **vert** ; métriques Railway visibles ; **sonde
  d'uptime externe** active et « up ». **Test d'alerte** : provoquer une indisponibilité **dans un
  environnement jetable/staging** (arrêt de service) et vérifier que **l'alerte se déclenche** puis se
  résout — **sans** fuite de secret/PII dans le message.
- **Sauvegardes vérifiées** : confirmer l'activation quotidienne + rétention + chiffrement ; **restaurer**
  une sauvegarde vers un environnement **isolé** ; **vérifier l'intégrité** (nombre de tables, comptages,
  `alembic current`) ; **mesurer/consigner RPO/RTO** dans le journal. Répéter **au moins une fois** (puis
  trimestriellement).
- **Rollback répété** : sur **`staging`**, effectuer un **rollback applicatif** vers un build antérieur et
  vérifier la reprise (smoke tests) ; **répéter un `alembic downgrade`** sur une base **jetable** (le
  round-trip est déjà validé en CI #4) pour valider le chemin schéma-seul.
- **Zéro secret dans le dépôt** : revue ciblée + **contrôle de secrets** (`gitleaks`/scan de patterns) sur
  les artefacts ajoutés (`docs/`, `deploy/`, éventuel code) — **aucune** détection ; `*.env.example` =
  placeholders uniquement ; **aucun secret dans les logs** de déploiement (relecture).
- **Non-régression CI** : `ci.yml` (#4) et `adw-sdlc.yml` restent verts et indépendants ; `perf.yml`
  reste **opt-in/non requis**.
- **Sonde de readiness (si Option B)** : test(s) unitaire(s)/intégration — `200` quand la base répond,
  `503` quand elle est injoignable (simulée), **sans** divulgation d'erreur brute ; test **deny-by-default**
  confirmant que le nouveau chemin est bien **listé** dans `PUBLIC_ROUTE_PATHS` (et qu'aucune autre route
  ne l'est par erreur).
- **Documentation** : liens valides (README → doc de mise en production → ADR-0038) ; runbook `production`
  et **runbook de rollback** complets et **idempotents** ; journal de vérification des sauvegardes présent.

> Note : #54 **n'ajoute pas** de tests métier ni e2e (#50). Les vérifications sont
> **opérationnelles/documentaires**, plus d'éventuels tests unitaires **uniquement** si la readiness
> optionnelle est retenue.

## Documentation Updates

- **`docs/mise-en-production.md`** *(nouveau, recommandé)* : runbook `production` (mise en service),
  **monitoring & alerting** (santé, métriques, sonde uptime, canaux, non-PII), **journal de vérification
  des sauvegardes** (dates, RPO/RTO, intégrité), **runbook de rollback** (app + base, critères,
  autorisation). *(Alternative : étendre `docs/environnements-et-secrets.md`.)*
- **`docs/adr/0038-<slug>.md`** *(nouveau)* : observabilité, alerting, rollback, liveness vs readiness.
- **`docs/adr/README.md`** : index (ADR-0038) + « décisions différées » — **monitoring/alerting §12.2**
  marqué **tranché**.
- **`docs/environnements-et-secrets.md`** : §5 Sauvegardes — renvoi au journal de vérification et à
  l'activation `production` ; note de **parité `prod`** désormais **exécutée**.
- **`README.md`** (racine) : §4 (Déploiement — prod déployée/monitorée, sauvegardes vérifiées, rollback
  documenté) ; §6 (statut M6 — mise en production) ; §9 (renvoi vers la doc de mise en production).
- **`backend/README.md`** *(léger, si readiness ajoutée)* : documenter la nouvelle route technique
  `GET /health/ready` (publique, `200`/`503`).
- **`*.env.example`** : **inchangés** sauf décision explicite (ex. commentaire `SENTRY_DSN` **si** suivi
  d'erreurs retenu) — **placeholders uniquement**, jamais de valeur réelle.

## Risks and Open Questions

- **Périmètre CD (à cadrer).** #54 livre un **déploiement manuel/documenté** + **rollback documenté**
  (cohérent avec #5). Faut-il un **auto-deploy** (sur merge `main`) et/ou un **rollback automatisé** ?
  **Proposé hors périmètre** MVP — à confirmer, sinon issue dédiée.
- **Suivi d'erreurs applicatif (Sentry ou équivalent) — décision.** Améliore l'observabilité mais
  **ajoute une dépendance + un secret `SENTRY_DSN` + une surface de PII** à masquer. Recommandation :
  **optionnel** ; ne **pas** l'annoncer comme livré s'il n'est pas câblé. Trancher dans l'ADR.
- **Readiness dédiée (Option B, §3) — décision.** Petit code technique + **élargissement de la surface
  publique** (revue de sécurité requise). Recommandation : **Option A** (liveness-only) au MVP, Option B
  seulement si l'exploitation l'exige.
- **Canaux d'alerte & seuils.** Quels canaux (e-mail/webhook/chat), quels **seuils** de déclenchement du
  rollback (taux d'erreur, indisponibilité, durée) ? À définir dans l'ADR/doc, **sans PII** dans les
  messages.
- **RPO/RTO & rétention/coût des sauvegardes.** Quotidienne (RPO ≤ 24 h) actée ; **RTO** à **mesurer au
  premier test** ; rétention (≥ 7 j) et **coût** à confirmer sur l'offre Railway retenue.
- **`btree_gist` sur Postgres managé `production`.** Prérequis à **vérifier** avant migration (ADR-0009) —
  le runbook doit l'inclure ; risque de blocage si le privilège est indisponible.
- **Migrations non réversibles ↔ rollback base.** Un `alembic downgrade` peut être **destructeur** ;
  privilégier des migrations **rétro-compatibles** (expand/contract) et documenter clairement l'arbre de
  décision *forward-fix vs downgrade vs restauration*.
- **Résidence des données (Afrique de l'Ouest).** Question ouverte d'ADR-0011 : `europe-west4` optimise
  la latence mais n'est pas en région ; **confirmer** l'absence d'obligation légale **avant** le pilote
  #55 (PII réelle).
- **Réglage dépôt non versionnable.** La **protection de branche `main`** (checks requis) et
  l'**interaction avec la phase `merge` ADW** restent des réglages **hors dépôt** (rappel #5/ADR-0010) —
  s'assurer qu'ils sont posés avant d'ouvrir la prod au trafic réel.
- **Domaine & TLS.** Nom de domaine public à décider/attacher ; TLS géré par la plateforme — vérifier le
  renouvellement automatique.
- **Choix du document** (nouveau `docs/mise-en-production.md` vs extension d'`environnements-et-secrets.md`).
  Recommandation : document dédié **cross-linké**, pour éviter un fichier surchargé — à confirmer.

## Implementation Checklist

1. **Relire le contexte** : ADR-0011 + `docs/environnements-et-secrets.md` (runbook, secrets,
   sauvegardes §5) ; ADR-0010/0004/0005/0009 ; `deploy/railway/*.json`, `deploy/docker-compose.yml` ;
   `health.py`, `security.py` (`PUBLIC_ROUTE_PATHS`), `main.py`, `session.py` ; `ci.yml`, `perf.yml` ;
   PRD §10.2/§12.2/§18.
2. **Trancher les décisions ouvertes** (et les tracer dans l'ADR) : (a) **observabilité** (native Railway
   + sonde uptime externe ; suivi d'erreurs **optionnel**) ; (b) **liveness-only vs readiness** (§3) ;
   (c) **canaux/seuils d'alerte** ; (d) **stratégie de rollback** (app + base) ; (e) **RPO/RTO/rétention**.
3. **Rédiger `docs/adr/0038-<slug>.md`** (format ADR-0000) et **mettre à jour `docs/adr/README.md`**
   (index + « monitoring/alerting §12.2 tranché »).
4. **Provisionner `production`** (via `use-railway`/MCP) par **parité stricte** du runbook #5 : projet/env,
   Postgres 16 + Redis 7 (**`btree_gist` vérifié**), services `backend`/`web` deploy-from-source,
   variables **non secrètes**, **secrets hors dépôt** (`production`), `alembic upgrade head`, **domaine +
   TLS**, déploiement, **smoke tests** verts.
5. **Configurer le monitoring** : healthchecks (déjà déclarés), métriques/déploiements Railway, **sonde
   d'uptime externe** sur `/health`, **alertes** (Railway + uptime) **sans secret ni PII** ; tester le
   déclenchement d'alerte sur un env jetable/staging.
6. **(Optionnel) Sonde de readiness** `GET /health/ready` (`SELECT 1`, `200`/`503`, aucun détail interne),
   **ajout à `PUBLIC_ROUTE_PATHS` après revue**, **hors** politique de redémarrage ; tests unitaires
   (`200`/`503`) + test deny-by-default — **sinon ne pas modifier le code**.
7. **Activer les sauvegardes** Postgres `production` (quotidiennes, rétention ≥ 7 j, chiffrées) ;
   **vérifier** l'activation du **versionnement/backup** du **bucket médias** (ADR-0005).
8. **Vérifier les sauvegardes** : restaurer vers un env **isolé**, contrôler l'intégrité
   (tables/comptages/`alembic current`), **mesurer RPO/RTO**, **consigner** dans le **journal de
   vérification** (sans PII).
9. **Rédiger le runbook de rollback** (app Railway + base : downgrade réversible vs restauration ;
   critères, autorisation, communication) et **le répéter sur `staging`**.
10. **Rédiger `docs/mise-en-production.md`** (runbook prod + monitoring/alerting + journal sauvegardes +
    rollback) et **cross-linker** depuis `docs/environnements-et-secrets.md` §5.
11. **Docs transverses** : `README.md` §4 (Déploiement) + §6 (statut M6) + §9 (renvoi) ; `backend/README.md`
    si readiness ajoutée.
12. **Vérifs finales (critères d'acceptation)** : **prod déployée et monitorée** (smoke tests verts,
    healthcheck + uptime + alerte testée) ; **sauvegardes vérifiées** (restauration réussie, RPO/RTO
    consignés) ; **rollback documenté** (runbook répété sur staging) ; **aucun secret/PII** dans le dépôt,
    les logs, les métriques ou les alertes (scan `gitleaks` propre) ; `ci.yml`/`adw-sdlc.yml` non
    régressés ; **aucun marqueur « généré par IA »**.
