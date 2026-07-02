# ADR-0011 : Déploiement, environnements & gestion des secrets

- **Statut** : Accepté
- **Date** : 2026-07-01
- **Décideurs** : équipe CoifLink
- **Issue** : #5
- **Référence PRD** : §10.2 (déploiement : hébergement cloud sécurisé, sauvegardes automatiques),
  §11.3 (données personnelles, sauvegardes sécurisées), §11.4 (journalisation), §12.2 (sauvegarde
  quotidienne, disponibilité), §18 (Sprint 0 — environnements de développement)

## Contexte et problème

[ADR-0010](./0010-ci-cd-docker-packaging.md) (#4) a tranché la **CI/CD GitHub Actions** et
l'**empaquetage Docker** (images `backend`/`web-dashboard` build-seul, non-root, configurées par
variables d'environnement, sans secret intégré), mais a **explicitement différé à #5** :
l'**hébergeur**, la **région des données**, le **push vers un registre**, la **politique de
protection de branche** appliquée et son interaction avec la phase `merge` du pipeline ADW. En
parallèle, plusieurs ADR renvoient à #5 des décisions d'exploitation : **sauvegardes automatiques**
(ADR-0004), **injection des secrets de connexion réels** (ADR-0009), **clés de stockage objet**
(ADR-0005), **clés FCM / fournisseur SMS** (ADR-0006).

Le dépôt applique déjà les invariants **« aucun secret en clair »** et **« configuration par variables
d'environnement »** (session backend qui lève si `DATABASE_URL` manque, `.env.example` en placeholders,
`.gitignore` excluant les `.env` réels, images sans secret). Mais **rien n'est formalisé** pour ce
qu'exige l'issue #5 : définition des environnements *dev/staging/prod*, magasin de secrets et mécanisme
d'injection, **reproductibilité de `staging`**, **sauvegardes activées**, et **politique de secrets
documentée**. Il faut **acter** ce socle de déploiement sans jamais committer de valeur réelle.

## Options envisagées

- **Plateforme d'hébergement**
  - **Option A — Railway** (PaaS). Environnements natifs, PostgreSQL/Redis managés + **sauvegardes**,
    variables par environnement (magasin de secrets), buckets objet, domaines, **deploy-from-source**
    (build du `Dockerfile`) ou déploiement d'image. Le dépôt est **déjà outillé** (serveur MCP
    `railway`, skill `use-railway`).
  - **Option B — Render / Fly.io** : PaaS comparables, non outillés dans le dépôt.
  - **Option C — VPS + Docker Compose** : portable et bon marché, mais report de toute
    l'exploitation (sauvegardes, TLS, secrets, mises à jour) sur l'équipe.
  - **Option D — Cloud managé (AWS/GCP)** : le plus riche, mais surdimensionné et coûteux en
    complexité pour un MVP.
- **Magasin de secrets & injection**
  - **Option A — Natif plateforme** (variables Railway par environnement) **+ GitHub Environments**
    (`staging`, `production`) pour la CI/CD.
  - **Option B — SOPS + age** : secrets chiffrés **versionnés** dans le dépôt (source de vérité
    indépendante de la plateforme), déchiffrés à l'exécution.
- **Stratégie de registre d'images**
  - **Option A — deploy-from-source** : la plateforme build le `Dockerfile` committé. `ci.yml`
    **inchangé** (build-seul).
  - **Option B — push GHCR** sur `main`/tags (`permissions: packages: write` scopé, `GITHUB_TOKEN`),
    la plateforme tire l'image publiée.
- **Périmètre de déploiement (CD)** : **manuel/documenté** (runbook) vs **continu automatisé**
  (auto-deploy, promotions, rollback).
- **Stockage objet** : **provisionner maintenant** vs **différer** jusqu'à la première feature
  d'upload (M2).

## Décision

- **Hébergement : Railway** (Option A) — le tooling est déjà câblé (`use-railway` / MCP `railway`) et
  couvre nativement les besoins de #5 (environnements, Postgres/Redis managés, sauvegardes, variables
  par environnement, buckets, domaines). **Région des données : Union européenne — Amsterdam
  (`europe-west4`)**, région Railway la **plus proche de la Côte d'Ivoire / l'Afrique de l'Ouest**
  (latence). Aucune obligation légale de résidence n'est documentée à ce jour (à confirmer — voir
  Conséquences). Le plan reste **portable** : les principes ci-dessous valent pour Render, Fly.io ou
  un VPS + Docker Compose.
- **Magasin de secrets & injection : natif plateforme + GitHub Environments** (Option A).
  - **Runtime applicatif** : secrets **par environnement** dans les **variables Railway**, injectés au
    conteneur au démarrage — **jamais** dans l'image ni le dépôt.
  - **CI/CD** : **GitHub Environments** `staging` et `production`, secrets **scoping par
    environnement**, **reviewers requis** sur `production` ; à défaut, `GITHUB_TOKEN` minimal
    uniquement. Les secrets **du pipeline ADW** (`GH_TOKEN`, clé runner) restent gérés par
    `adw_sdlc/src/env.ts` / `lint:env` — **hors périmètre** de cet ADR.
  - **Développement local** : `.env` (gitignoré) copié depuis `.env.example` ; aucune valeur réelle
    partagée via le dépôt.
  - **SOPS + age** (Option B) est **écarté au MVP** (couplage plateforme accepté au profit de la
    simplicité) mais reste l'alternative documentée si une source de vérité dans le dépôt devient
    nécessaire.
- **Registre d'images : deploy-from-source** (Option A) au MVP — Railway build les `Dockerfile`
  committés (`deploy/railway/*.json`). **`ci.yml` reste inchangé** (build-seul, aucune élévation de
  `permissions:`), ce qui **clôt** le point différé « push registre » d'ADR-0010 par un choix qui
  n'exige **ni PAT ni `packages: write`**. Le **push GHCR** (Option B) reste l'évolution documentée.
- **Périmètre CD : déploiement manuel/documenté** au MVP — un **runbook** idempotent
  (`docs/environnements-et-secrets.md`) recrée `staging` de zéro. L'auto-deploy / les promotions /
  le rollback automatisé sont **hors périmètre** (évolution ultérieure).
- **Modèle d'environnements : `dev` / `staging` / `prod`** à **isolation stricte** (bases, buckets et
  secrets **distincts** par environnement), détaillé dans `docs/environnements-et-secrets.md`
  (matrice de configuration par service).
- **Sauvegardes : sauvegarde automatique quotidienne** de PostgreSQL (managée Railway),
  **rétention 7 jours** glissants minimum, **chiffrées au repos**, avec **procédure de restauration
  documentée** et **test de restauration** périodique. Redis n'est **pas** sauvegardé (cache/queue,
  ADR-0004). Cible : **RPO ≤ 24 h**, **RTO** documenté.
- **Stockage objet : différé** jusqu'à la première feature d'upload (M2) — la **surface** de secrets
  (`S3_*`) est **documentée** dans la politique de secrets, **sans** être ajoutée aux `.env.example`
  tant que le code ne la lit pas (ADR-0005). Un bucket Railway sera provisionné à ce moment-là.

## Justification (compromis)

- **Railway** minimise le time-to-staging : les briques exigées par #5 (environnements, Postgres/Redis
  managés + sauvegardes, secrets par environnement, buckets) sont natives, et le dépôt est **déjà
  outillé** pour les piloter. Le **compromis** est un **couplage plateforme** ; il est atténué par des
  images Docker standard, une config par variables d'environnement et un plan portable.
- **Secrets natifs + GitHub Environments** : réutilise le **précédent** de la frontière de secrets ADW
  (secrets hors de portée, injectés) sans introduire l'outillage cryptographique de SOPS+age au MVP.
- **deploy-from-source** : évite d'élargir les permissions CI et de manipuler un PAT/GHCR ; **aucune
  régression** de `ci.yml`. Le push GHCR reste possible plus tard sans dette.
- **CD manuel/documenté** : la valeur de #5 est la **reproductibilité** (runbook + config déclarative),
  pas l'automatisation CD — reportée pour tenir le périmètre MVP.
- **Différer le stockage objet** : aucune feature d'upload avant M2 ; documenter la surface **sans**
  impliquer une intégration inexistante (contrainte « ne pas laisser croire qu'un comportement existe »).

## Conséquences

- **Positives** : les critères d'acceptation de #5 sont adressés — **secrets injectés hors dépôt**
  (magasin plateforme + GitHub Environments), **`staging` reproductible** (runbook + `deploy/`
  déclaratif), **politique de secrets documentée** (`docs/environnements-et-secrets.md`),
  **sauvegardes activées** (quotidiennes, rétention, restauration testée). Les points différés
  d'ADR-0004/0005/0009/0010 rattachés à #5 sont **tranchés ou explicitement re-différés** (SMS
  concret, stockage objet concret).
- **Négatives / risques** :
  - **Couplage Railway** : une migration de plateforme demanderait de reporter la config déclarative
    et le magasin de secrets (atténué par la portabilité du plan).
  - **Région / résidence** : `europe-west4` optimise la latence mais **n'est pas** en Afrique de
    l'Ouest ; si une obligation de résidence apparaît, la région devra être revue (ADR ultérieur).
  - **`btree_gist` sur Postgres managé** (rappel ADR-0009) : la migration initiale exige
    `CREATE EXTENSION btree_gist` ; le privilège doit être disponible sur le Postgres Railway — le
    runbook l'inclut comme **prérequis vérifié**.
  - **Protection de branche `main`** : l'application des **checks requis** (`backend`, `web`,
    `mobile`, `docker-backend`, `docker-web`) reste un **réglage dépôt non versionnable** (par un
    administrateur) ; documenté dans `docs/environnements-et-secrets.md`. La phase `merge` du pipeline
    ADW **doit attendre** ces checks (pas de contournement).
- **Décisions volontairement re-différées** : **fournisseur SMS concret** (ADR-0006, opérationnel, M5)
  et **provisionnement concret du stockage objet** (ADR-0005, M2) restent différés ; leur **surface de
  secrets** est documentée.
- **Suivi / à confirmer (non bloquant)** :
  - **région/résidence légale** des données (Afrique de l'Ouest) — à confirmer avec le métier ;
  - **rétention/coût** exacts des sauvegardes et **RTO** cible ;
  - **module de config typé backend** (`pydantic-settings`, fail-fast) — **reporté à #8** (auth, où
    `JWT_SECRET` devient obligatoire) pour garder #5 purement infra/doc ;
  - **push GHCR** et **durcissement du scan** (bloquant High/Critical) / **épinglage SHA** des actions
    — évolutions optionnelles héritées d'ADR-0010, non retenues ici.
