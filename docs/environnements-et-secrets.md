# Environnements & gestion des secrets

> Document opérationnel de CoifLink (issue #5). Décision de socle : **[ADR-0011](./adr/0011-deploiement-environnements-secrets.md)**.
> Il couvre le **modèle d'environnements**, la **matrice de configuration**, la **politique de
> secrets**, le **runbook `staging` reproductible** et les **sauvegardes & restauration**.
>
> **Invariant non négociable** : aucun secret réel n'est **jamais** committé, journalisé ou intégré à
> une image. Les secrets vivent **hors dépôt** (magasin de la plateforme / GitHub Environments) et sont
> **injectés par variables d'environnement** à l'exécution. Seuls les `*.env.example` (placeholders)
> sont versionnés.

## 1. Modèle d'environnements

Trois environnements à **isolation stricte** : bases, buckets et secrets **distincts** par
environnement. Aucun partage de valeur d'un environnement à l'autre.

| Environnement | Rôle | Données | Où vivent les valeurs | Accès |
| --- | --- | --- | --- | --- |
| **dev** | Poste développeur / local | Synthétiques, jetables | `deploy/.env` local (gitignoré) via `deploy/docker-compose.yml` | Développeur |
| **staging** | Pré-production **reproductible**, reflète `prod` | **Non réelles** (démo/anonymisées) | Variables Railway (env `staging`) + GitHub Environment `staging` | Équipe (large) |
| **prod** | Production | Réelles (PII) | Variables Railway (env `production`) + GitHub Environment `production` (reviewers requis) | **Restreint** (moindre privilège) |

- **`staging` reflète `prod`** : **mêmes images**, **mêmes clés de configuration**, seules les
  **valeurs** et les **données** diffèrent (staging n'utilise **jamais** de PII réelle — PRD §11.3).
- **`APP_ENV`** prend une valeur explicite par environnement : `development` / `staging` /
  `production` (déjà lu par `backend/coiflink_api/main.py` — aucun changement de code requis).

## 2. Matrice de configuration

Variables **réellement consommées par le code aujourd'hui** (à ne pas étendre au-delà du réel). Un
secret est une valeur dont la divulgation compromet la sécurité ; il n'est **jamais** committé.

### backend (FastAPI)

| Variable | Nature | Exposée navigateur | Source (staging/prod) | Consommée par |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | **secret** | non | Variable Railway (réf. base managée) | `adapters/outbound/persistence/session.py`, `migrations/env.py` |
| `REDIS_URL` | **secret** | non | Variable Railway (réf. Redis managé) | à câbler (M1→ ; ADR-0004) |
| `JWT_SECRET` | **secret** | non | Variable Railway | requis dès **#10** (connexion/JWT) — **non utilisé par #8** (l'inscription n'émet aucun JWT) |
| `APP_NAME` | non secret | non | Variable Railway / défaut code | `main.py` |
| `APP_ENV` | non secret | non | Variable Railway (`staging`/`production`) | `main.py` |
| `OTP_ENABLED` | non secret | non | `false` (défaut code) | `config.py` (`AuthConfig`) — active l'OTP à l'inscription (#8) ; envoi réel différé à M5 |
| `OTP_CODE_LENGTH` | non secret | non | `6` (défaut code) | `config.py` — longueur du code OTP |
| `OTP_TTL_SECONDS` | non secret | non | `300` (défaut code) | `config.py` — durée de validité OTP en secondes |
| `OTP_MAX_ATTEMPTS` | non secret | non | `3` (défaut code) | `config.py` — nombre d'essais autorisés par OTP |

### web-dashboard (Next.js)

| Variable | Nature | Exposée navigateur | Source (staging/prod) | Consommée par |
| --- | --- | --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | non secret | **oui** (`NEXT_PUBLIC_*`) | Variable Railway | client HTTP web |

> ⚠ **`NEXT_PUBLIC_*` est intégré au bundle envoyé au navigateur** : n'y placer **jamais** un secret.

### Surface future (réservée — **non câblée**, ne pas ajouter aux `.env.example`)

Documentée ici pour l'inventaire de la politique de secrets ; ces variables ne sont **pas** lues par
le code aujourd'hui et ne doivent **pas** être ajoutées aux gabarits tant qu'une feature ne les
consomme pas (éviter d'impliquer une intégration inexistante) :

- **Stockage objet** (ADR-0005, M2) : `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`
  *(secret)*, `S3_SECRET_ACCESS_KEY` *(secret)*.
- **Notifications** (ADR-0006, M5) : clés **FCM** *(secret)*, identifiants **fournisseur SMS**
  *(secret)* — fournisseur concret différé (#5 → M5).

## 3. Politique de secrets

### 3.1 Inventaire

| Secret | Environnements | Magasin | Propriétaire |
| --- | --- | --- | --- |
| `DATABASE_URL` | staging, prod | Variables Railway (réf. base managée) | Ops |
| `REDIS_URL` | staging, prod | Variables Railway (réf. Redis managé) | Ops |
| `JWT_SECRET` | staging, prod (dès **#10**) | Variables Railway | Backend |
| Clés stockage objet `S3_*` | *(futur, M2)* | Variables Railway | Ops |
| Clés FCM / SMS | *(futur, M5)* | Variables Railway | Ops |

> Les secrets **du pipeline ADW** (`GH_TOKEN`, clé runner) ne figurent **pas** ici : ils sont gérés par
> `adw_sdlc/src/env.ts` et la garde `lint:env` (voir §7). #5 ne les touche pas.

### 3.2 Où ils vivent & injection

- **Runtime** : chaque secret est une **variable d'environnement** définie **par environnement** dans
  le magasin Railway, **injectée** au conteneur au démarrage. Jamais dans l'image (les `Dockerfile`
  n'embarquent aucun secret, #4), jamais dans le dépôt.
- **CI/CD** : si un job doit accéder à un secret, il passe par un **GitHub Environment** (`staging` /
  `production`) avec secrets **scoping par environnement**. Sinon, `GITHUB_TOKEN` minimal.
- **Local** : `deploy/.env` (gitignoré) copié depuis `deploy/.env.example`. Aucune valeur réelle
  partagée via le dépôt ni un canal non chiffré.

### 3.3 Moindre privilège

- Accès **prod restreint** ; **reviewers requis** sur le GitHub Environment `production`.
- `staging` accessible plus largement à l'équipe, **sans données réelles**.
- Chaque secret n'est visible que des environnements qui en ont besoin ; pas de secret « global ».

### 3.4 Rotation

- **Rotation planifiée** : au minimum **tous les 6 mois** pour `JWT_SECRET` et les clés d'accès
  (S3/FCM/SMS quand elles existeront) ; DSN base/Redis rotés lors d'un changement d'accès.
- **Rotation immédiate** de tout secret potentiellement exposé (voir §3.5).
- **Procédure** : générer la nouvelle valeur → la poser dans le magasin de l'environnement →
  redéployer/redémarrer le service → invalider l'ancienne valeur. Pour `JWT_SECRET`, la rotation
  invalide les jetons émis (déconnexion) — planifier hors pic.

### 3.5 Conduite en cas de fuite

1. **Révoquer** immédiatement le secret exposé (couper l'accès côté fournisseur/plateforme).
2. **Régénérer** une nouvelle valeur et la déployer (rotation, §3.4).
3. **Purger** la valeur des emplacements où elle a fuité (logs, historique — réécrire l'historique
   git si un secret a été committé, puis forcer la rotation car considérer la valeur comme compromise).
4. **Auditer** les accès pendant la fenêtre d'exposition ; documenter l'incident.

### 3.6 Non-journalisation

- Ne **jamais** journaliser un secret ni une **PII** (PRD §11.3/§11.4 journalise des *actions*, pas des
  *valeurs*). Les logs Alembic ne dumpent aucune donnée (ADR-0009).
- En **CI / scripts / runbook** : ne pas `echo` ni dumper l'environnement (`env`, `printenv`,
  `set -x` sur une commande portant un secret). Masquer les variables sensibles côté plateforme.
- Pas de PII dans les **noms d'objets / chemins** de stockage (ADR-0005), ni dans les messages de
  notification journalisés (ADR-0006).

## 4. Runbook — `staging` reproductible

Objectif : un opérateur suit ces étapes **de zéro** et obtient un `staging` fonctionnel, **sans savoir
tacite**. Les étapes sont **idempotentes** (les rejouer ne casse rien). Le provisionnement s'appuie sur
la skill **`use-railway`** / le serveur MCP `railway` (voir ADR-0011).

> **Aucun secret dans cette procédure ni dans les logs.** Les valeurs sensibles sont posées via
> l'interface/API du magasin de secrets, jamais collées dans un fichier versionné ni un message.

1. **Projet & environnement** : créer (ou sélectionner) le projet CoifLink et l'environnement
   `staging` (région `europe-west4`, ADR-0011).
2. **Dépendances managées** : provisionner **PostgreSQL 16** et **Redis 7** dans `staging`.
   - **Prérequis PostgreSQL** : vérifier que `CREATE EXTENSION btree_gist` est autorisé (requis par la
     migration initiale, ADR-0009). Sur un Postgres managé restreint, confirmer le privilège avant de
     migrer.
3. **Services applicatifs** : créer les services `backend` et `web` en **deploy-from-source** à partir
   des `Dockerfile` committés — config déclarative non secrète : `deploy/railway/backend.json` et
   `deploy/railway/web.json`.
4. **Variables (non secrètes)** : poser `APP_ENV=staging`, `APP_NAME`, et l'URL publique de l'API dans
   `NEXT_PUBLIC_API_BASE_URL` (web).
5. **Secrets (hors dépôt)** : renseigner `DATABASE_URL`, `REDIS_URL` (références aux bases managées) et
   `JWT_SECRET` (dès #8) dans le magasin de secrets de l'environnement `staging`. **Jamais** dans le
   dépôt ni les logs.
6. **Migrations** : appliquer le schéma — `alembic upgrade head` (contexte backend, `DATABASE_URL` de
   `staging`). Le round-trip est validé en CI (#4).
7. **Déploiement** : déployer `backend` puis `web`.
8. **Smoke tests** : `GET /health` du backend → `200 {"status":"ok"}` ; la page d'accueil web répond
   (mêmes contrôles qu'en CI #4).
9. **Seed non réel** : charger un jeu de **données de démo/anonymisées** (jamais de PII réelle).

**Idempotence** : re-provisionner un service déjà présent le met à jour sans le dupliquer ; réappliquer
les migrations est un no-op si le schéma est à jour ; re-poser une variable écrase l'ancienne valeur.

**Parité `prod`** : `prod` suit le même runbook sur l'environnement `production` (reviewers requis,
accès restreint, données réelles, sauvegardes activées §5).

### Parité locale (dev) — `docker-compose`

```bash
cp deploy/.env.example deploy/.env      # gitignoré ; renseigner POSTGRES_PASSWORD + DATABASE_URL
docker compose -f deploy/docker-compose.yml up --build
```

Démarre `backend` + `web` + PostgreSQL 16 + Redis 7. `GET http://localhost:8000/health` répond ;
`http://localhost:3000/` répond. **Aucun secret en clair** n'est requis : les valeurs viennent de
`deploy/.env` (gitignoré). Un secret **absent** (p. ex. `DATABASE_URL`) fait **échouer proprement** le
démarrage (fail-fast attendu — cf. `session.py` qui lève si `DATABASE_URL` manque).

## 5. Sauvegardes & restauration

- **PostgreSQL — sauvegarde automatique quotidienne** (PRD §12.2) via le mécanisme managé Railway,
  **rétention 7 jours** glissants minimum, **chiffrées au repos**. À défaut de planificateur managé, un
  `pg_dump` quotidien planifié (chiffré, stocké hors dépôt) est la solution de repli documentée.
- **Restauration (procédure)** :
  1. Sélectionner la sauvegarde (date) à restaurer.
  2. Restaurer vers un **environnement jetable/isolé** (jamais directement sur `prod` pour un test).
  3. Vérifier l'**intégrité** : nombre de tables attendu, comptages de lignes cohérents, `alembic
     current` = révision attendue.
  4. Pour une vraie reprise `prod`, restaurer sur un service neuf puis basculer le trafic.
- **Test de restauration périodique** : au moins **trimestriel** — restaurer une sauvegarde vers un
  environnement isolé et valider l'intégrité. *Une sauvegarde non testée n'est pas une sauvegarde.* La
  restauration ne doit **pas** exposer de PII hors du périmètre autorisé.
- **Cibles** : **RPO ≤ 24 h** (sauvegarde quotidienne), **RTO** documenté lors du premier test.
- **Redis** : **pas** de sauvegarde critique — cache/queue, **pas** source de vérité (ADR-0004) ;
  reconstructible depuis PostgreSQL.
- **Stockage objet** : lorsqu'il sera provisionné (M2), activer le **versionnement**/backup du bucket ;
  différé jusque-là (ADR-0005).

## 6. Protection de branche & registre d'images

- **Protection de branche `main`** (réglage dépôt, **non versionnable**, à appliquer par un
  administrateur — Settings → Branches ou `gh api`) : exiger les **status checks requis** `backend`,
  `web`, `mobile`, `docker-backend`, `docker-web` (le job `dependency-scan` reste **informatif**, non
  requis) — cf. ADR-0010.
- **Interaction avec la phase `merge` du pipeline ADW** : l'orchestrateur détient le merge ; il **doit
  attendre** ces checks requis (**pas de contournement**), sans quoi « CI verte obligatoire avant
  merge » ne serait pas réellement garanti.
- **Registre d'images** : au MVP, **deploy-from-source** (Railway build les `Dockerfile` committés) —
  `ci.yml` **reste inchangé** (build-seul, aucune élévation de `permissions:`). Le **push GHCR**
  (`permissions: packages: write` **scopé** au job, `GITHUB_TOKEN`, jamais de PAT) reste l'évolution
  documentée (ADR-0011).

## 7. Renvois

- **[ADR-0011](./adr/0011-deploiement-environnements-secrets.md)** — décision hébergement/région,
  magasin de secrets, environnements, registre, sauvegardes.
- **[CONTRIBUTING](../CONTRIBUTING.md)** (« Secrets ») — règle « aucun secret committé ».
- **Invariants CI/Docker** : [ADR-0010](./adr/0010-ci-cd-docker-packaging.md), `.github/workflows/ci.yml`
  (build-seul, images non-root sans secret).
- **Frontière de secrets du pipeline ADW** : `adw_sdlc/src/env.ts`, garde `lint:env`, rétention de
  `GH_TOKEN` (modèle « secrets hors de portée de l'agent » — **hors périmètre** de #5).
- **PRD** : §10.2 (déploiement, sauvegardes), §11.3/§11.4 (PII, journalisation), §12.2 (sauvegarde
  quotidienne).
