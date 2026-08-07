# Mise en production — runbook `production`, monitoring, sauvegardes vérifiées & rollback

> Document opérationnel de CoifLink (issue **#54 — Déploiement production**). Décision de socle :
> **[ADR-0011](./adr/0011-deploiement-environnements-secrets.md)** (Railway, région `europe-west4`,
> *deploy-from-source*, `dev`/`staging`/`prod`, politique de sauvegardes). Décisions
> d'**observabilité, d'alerting et de rollback** : **[ADR-0038](./adr/0038-observabilite-monitoring-rollback.md)**.
> Ce document **exécute et complète** la clause de **parité `prod`** de
> [`docs/environnements-et-secrets.md`](./environnements-et-secrets.md) §4/§5.
>
> **Invariant non négociable** : aucun secret réel n'est **jamais** committé, journalisé ou intégré à
> une image. Les secrets `production` vivent **hors dépôt** (variables Railway `production` / GitHub
> Environment `production`, reviewers requis) et sont **injectés par variables d'environnement** à
> l'exécution. **Aucune PII** ni valeur secrète dans les logs, métriques ou alertes (PRD §11.3/§11.4 :
> on journalise des *actions*, pas des *valeurs*).
>
> **Périmètre.** Ce runbook **décrit** les opérations de mise en service, de monitoring, de vérification
> des sauvegardes et de rollback. Leur **exécution réelle** (provisionnement Railway, activation des
> sauvegardes, configuration des alertes, tests de restauration/rollback) se fait par un **opérateur
> disposant de l'accès `production` restreint**, via la skill **`use-railway`** / le serveur MCP
> `railway`, en respectant strictement « aucun secret dans le dépôt ni dans les logs ».

## Sommaire

1. [Runbook `production` — mise en service (parité stricte du runbook #5)](#1-runbook-production--mise-en-service-parité-stricte-du-runbook-5)
2. [Monitoring & alerting (PRD §12.2)](#2-monitoring--alerting-prd-122)
3. [Sauvegardes vérifiées & journal de vérification](#3-sauvegardes-vérifiées--journal-de-vérification)
4. [Runbook de rollback (app + base)](#4-runbook-de-rollback-app--base)
5. [Vérifications finales (critères d'acceptation #54)](#5-vérifications-finales-critères-dacceptation-54)
6. [Renvois](#6-renvois)

---

## 1. Runbook `production` — mise en service (parité stricte du runbook #5)

Suivre le **runbook `staging`** de [`docs/environnements-et-secrets.md`](./environnements-et-secrets.md) §4
sur l'environnement **`production`**, en respectant les **différences de parité** : données réelles à
terme, **accès restreint**, **reviewers requis**, **sauvegardes activées**. Les étapes sont
**idempotentes** (les rejouer ne casse rien).

> **Aucun secret dans cette procédure ni dans les logs.** Les valeurs sensibles sont posées via
> l'interface/API du magasin de secrets Railway, **jamais** collées dans un fichier versionné, un
> message d'alerte ou un log (`env`, `printenv`, `set -x` sur une commande portant un secret sont
> **interdits**).

1. **Projet & environnement** : sélectionner le projet CoifLink et créer/sélectionner l'environnement
   **`production`** (région **`europe-west4`**, ADR-0011).
2. **Dépendances managées** : provisionner **PostgreSQL 16** et **Redis 7** dans `production`.
   - **Prérequis PostgreSQL vérifié** : `CREATE EXTENSION btree_gist` **autorisé** (requis par la
     migration initiale, ADR-0009). Sur un Postgres managé restreint, **confirmer le privilège avant**
     de migrer — sinon la migration `0001` échoue.
3. **Services applicatifs** : créer `backend` et `web` en **deploy-from-source** à partir des
   `Dockerfile` committés — config déclarative non secrète `deploy/railway/backend.json`
   (`healthcheckPath: /health`, `restartPolicyType: ON_FAILURE`) et `deploy/railway/web.json`
   (`healthcheckPath: /`). **Ces fichiers sont partagés** entre environnements ; ce qui diffère par
   environnement, ce sont les **variables**.
4. **Variables (non secrètes)** : poser `APP_ENV=production`, `APP_NAME`, `NEXT_PUBLIC_API_BASE_URL`
   (URL publique de l'API, exposée navigateur — **jamais** un secret), `API_BASE_URL` (réseau interne
   web→backend), `S3_ENDPOINT_URL` / `S3_BUCKET` / `S3_REGION` (non secrets). `main.py` lit déjà
   `APP_ENV` (valeur `production` attendue — **aucun changement de code requis**).
5. **Secrets (hors dépôt)** : renseigner `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`,
   `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` dans le **magasin de secrets de l'environnement
   `production`** — **jamais** dans le dépôt ni les logs. **Reviewers requis** sur le GitHub Environment
   `production` (moindre privilège, ADR-0011 §3.3).
6. **Migrations** : appliquer le schéma — `alembic upgrade head` (contexte backend, `DATABASE_URL` de
   `production`). Le round-trip `upgrade → downgrade → upgrade` est **validé en CI** (#4).
7. **Domaine & TLS** : générer/attacher un **domaine public** (TLS géré par la plateforme) pour
   `backend` et `web`. Vérifier le **renouvellement automatique** du certificat.
8. **Déploiement** : déployer `backend` **puis** `web`.
9. **Smoke tests `production`** :
   - `GET https://<domaine-backend>/health` → **`200 {"status":"ok"}`** ;
   - page d'accueil `web` répond (TLS valide) ;
   - `alembic current` = **`head`** ;
   - une route protégée sans jeton → **`401`** (deny-by-default toujours actif).

**Idempotence** : re-provisionner un service déjà présent le met à jour sans le dupliquer ; réappliquer
les migrations est un **no-op** si le schéma est à jour ; re-poser une variable **écrase** l'ancienne
valeur.

---

## 2. Monitoring & alerting (PRD §12.2)

Observabilité retenue (**[ADR-0038](./adr/0038-observabilite-monitoring-rollback.md)**) :
**native plateforme + surveillance externe**. **Aucune** PII ni valeur secrète dans les tableaux de
bord, métriques ou alertes.

### 2.1 Santé des services

- **Healthchecks Railway** : `/health` (backend) et `/` (web) — **déjà déclarés** dans
  `deploy/railway/*.json`. Le **`restartPolicyType: ON_FAILURE`** (`restartPolicyMaxRetries: 10`) assure
  le **redémarrage automatique** en cas d'échec.
- **Liveness-only** (ADR-0038 §3) : `GET /health` reste une **sonde de liveness pure** (aucun accès
  base, aucune PII) ; **aucune** sonde de *readiness* n'est ajoutée au MVP. La connectivité base est
  **implicitement** surveillée par les routes réelles et les métriques.

### 2.2 Métriques ressources & état des déploiements

- Activer/consulter les **métriques Railway** — CPU, mémoire, réseau, **redémarrages** — via
  `use-railway`/MCP `railway`.
- Suivre l'**état des déploiements** (build / deploy / crash) et l'historique des builds (utile au
  rollback, §4).

### 2.3 Surveillance de disponibilité externe (cible 99 %)

- Configurer une **sonde d'uptime indépendante** (moniteur HTTP externe) qui interroge périodiquement
  `GET https://<domaine-backend>/health` et **alerte** en cas d'échec.
- C'est **cette sonde** qui **mesure la cible 99 %** (PRD §12.2) **hors** de la plateforme — elle détecte
  aussi une panne réseau/plateforme qu'un healthcheck interne ne verrait pas.

### 2.4 Alertes en cas d'incident

- **Sources** : **notifications Railway** (échec de déploiement, crash, redémarrages répétés) **et**
  alerte de la **sonde d'uptime** (indisponibilité `/health`).
- **Canaux** : e-mail au minimum ; webhook/chat en option (choix opérationnel — à renseigner ici lors de
  la mise en service, **sans** figer de valeur secrète dans le dépôt).
- **Invariant non-PII / non-secret** : une alerte porte un **identifiant de service**, un **code
  d'état**, un **horodatage** — **jamais** une valeur de variable, un jeton, un DSN, un e-mail, un
  téléphone ni un payload utilisateur (§11.3/§11.4).

### 2.5 Logs de déploiement

- S'appuyer sur les **logs de déploiement Railway**, à **accès restreint**. **Ne jamais** logger de
  secret ni de PII. Pas de `env`/`printenv`/`set -x` exposant une variable sensible.

### 2.6 Suivi d'erreurs applicatif — **non livré** (optionnel, différé)

Conformément à ADR-0038 §4, #54 **n'introduit pas** de suivi d'erreurs applicatif (ex. Sentry). Le
monitoring repose sur les mécanismes **natifs Railway + la sonde d'uptime externe**. S'il est retenu
plus tard : `SENTRY_DSN` **secret hors dépôt**, **scrubbing PII** actif, **aucune** capture de corps de
requête sensible. **Rien** dans le dépôt ne doit impliquer qu'un tel suivi est actif tant qu'il n'est
pas câblé.

---

## 3. Sauvegardes vérifiées & journal de vérification

Politique de référence : [`docs/environnements-et-secrets.md`](./environnements-et-secrets.md) §5
(quotidienne, rétention 7 j, chiffrée, restauration testée). #54 **active** et **vérifie**.

### 3.1 Activation

- **PostgreSQL `production`** : **sauvegarde automatique quotidienne** (mécanisme managé Railway ; à
  défaut, `pg_dump` quotidien planifié, **chiffré**, stocké **hors dépôt** — repli documenté par #5),
  **rétention ≥ 7 j** glissants, **chiffrée au repos**. Cible **RPO ≤ 24 h** (ADR-0011).
- **Redis** : **pas** de sauvegarde critique (cache/queue, ADR-0004) — reconstructible depuis Postgres.
- **Bucket médias** (actif depuis #15, ADR-0005) : **vérifier/activer** son **versionnement** et son
  **backup** côté fournisseur — à ne pas différer davantage.

### 3.2 Procédure de vérification (restaurabilité)

Suivre la **procédure de restauration** de `docs/environnements-et-secrets.md` §5 :

1. **Sélectionner** une sauvegarde (date/identifiant).
2. **Restaurer** vers un **environnement jetable/isolé** — **jamais** directement sur `prod`.
3. **Vérifier l'intégrité** : nombre de tables attendu, comptages de lignes cohérents,
   `alembic current` = révision attendue.
4. **Mesurer le RTO** (durée entre le déclenchement de la restauration et un service vérifié sain) et le
   **consigner** (§3.3).

> La restauration **ne doit pas exposer de PII** hors du périmètre autorisé. **Périodicité** : au moins
> **trimestrielle**. *Une sauvegarde non testée n'est pas une sauvegarde.*

### 3.3 Journal de vérification des sauvegardes

Consigner **chaque** vérification ci-dessous — **sans PII** (dates, identifiants techniques, résultat
d'intégrité, RTO, opérateur). Format proposé :

| Date | Env source | ID sauvegarde | Restauré vers | Intégrité (tables / comptages / `alembic current`) | RPO observé | RTO mesuré | Opérateur | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *(à renseigner au 1ᵉʳ test)* | `production` | *(id)* | env. isolé jetable | *(OK/KO)* | ≤ 24 h | *(mesuré)* | *(rôle Ops)* | — |

> Tant qu'aucune ligne n'est renseignée, les sauvegardes sont **configurées mais non vérifiées** : le
> critère d'acceptation « sauvegardes **vérifiées** » n'est atteint qu'après **au moins une** ligne de
> restauration réussie avec RTO mesuré.

---

## 4. Runbook de rollback (app + base)

Décision : **rollback manuel documenté** (**[ADR-0038](./adr/0038-observabilite-monitoring-rollback.md)** §5).
Runbook **idempotent**, sans savoir tacite. `production` étant **restreint**, un rollback requiert
l'**autorisation** prévue au §4.4.

### 4.1 Rollback applicatif

1. Identifier le **dernier déploiement/build sain** (historique des déploiements Railway, §2.2).
2. **Rollback / redeploy** de ce build via Railway (`use-railway`/MCP). En *deploy-from-source*, cela
   revient à **redéployer le commit/build précédent connu bon**.
3. **Smoke tests post-rollback** : `GET /health` → `200`, page web répond, `alembic current` cohérent
   avec la version applicative redéployée.

### 4.2 Rollback base de données — arbre de décision

- **Migration réversible, schéma seul** → `alembic downgrade <révision>` **envisageable** (round-trip
  `upgrade → downgrade → upgrade` **validé en CI** #4), en cohérence avec la version applicative
  redéployée.
- **Migration avec transformation/perte de données** → **ne pas** downgrader (destructeur) : préférer
  un **correctif en avant** (*forward-fix*) ou la **restauration d'une sauvegarde** (§3.2).
- **Règle de compatibilité** → privilégier des migrations **rétro-compatibles** (**expand/contract**)
  pour qu'un rollback applicatif reste possible **sans** downgrade immédiat.

### 4.3 Critères de déclenchement

Observer : échec des **smoke tests**, **taux d'erreur** élevé, **indisponibilité `/health`**, **alerte
uptime** (§2.3). Documenter les **seuils** de décision retenus (opérationnel) ici lors de la mise en
service.

### 4.4 Autorisation & communication

- **Autorisation** : `production` est **restreint** (reviewers requis) — indiquer **qui** autorise un
  rollback.
- **Communication** : canal et destinataires de l'annonce d'incident.
- **Traçabilité** : compte rendu d'incident **sans** PII ni secret (identifiants techniques, horodatage,
  décision).

### 4.5 Répétition sur `staging`

Le rollback est **répété sur `staging`** avant d'être considéré fiable : rollback applicatif vers un
build antérieur (smoke tests) **et** `alembic downgrade` sur une base **jetable** (chemin schéma-seul,
déjà couvert par le round-trip CI #4).

---

## 5. Vérifications finales (critères d'acceptation #54)

- **Prod déployée et monitorée** : smoke tests `production` verts (§1.9) ; healthcheck de déploiement
  **vert** ; métriques Railway visibles ; **sonde d'uptime externe** active et « up » ; **test d'alerte**
  (provoquer une indisponibilité **sur un env jetable/`staging`**, vérifier le déclenchement puis la
  résolution — **sans** fuite de secret/PII dans le message).
- **Sauvegardes vérifiées** : activation quotidienne + rétention + chiffrement confirmés ; **au moins une**
  restauration vers un env **isolé** réussie ; intégrité contrôlée ; **RPO/RTO consignés** (§3.3).
- **Rollback documenté** : runbook §4 complet et **répété sur `staging`**.
- **Zéro secret / zéro PII** : revue ciblée + **scan de secrets** (`gitleaks`/patterns) sur les artefacts
  ajoutés — **aucune** détection ; `*.env.example` = **placeholders** uniquement ; aucun secret/PII dans
  les logs, métriques ou alertes.
- **Non-régression** : `ci.yml` (#4) et `adw-sdlc.yml` restent **verts et indépendants** ; `perf.yml`
  reste **opt-in/non requis** ; `deploy/railway/*.json` **inchangés**.

---

## 6. Renvois

- **[ADR-0038](./adr/0038-observabilite-monitoring-rollback.md)** — observabilité (monitoring/alerting),
  sonde de disponibilité externe, stratégie de rollback, liveness-only.
- **[ADR-0011](./adr/0011-deploiement-environnements-secrets.md)** — hébergement/région, secrets,
  environnements, sauvegardes (socle).
- **[`docs/environnements-et-secrets.md`](./environnements-et-secrets.md)** — modèle d'environnements,
  matrice de configuration, politique de secrets, **runbook `staging`** (§4), **sauvegardes &
  restauration** (§5), protection de branche (§6).
- **Invariants CI/Docker** : [ADR-0010](./adr/0010-ci-cd-docker-packaging.md),
  `.github/workflows/ci.yml` (build-seul, images non-root sans secret).
- **PRD** : §10.2 (déploiement, sauvegardes), §11.3/§11.4 (PII, journalisation), §12.2 (disponibilité,
  sauvegarde quotidienne, monitoring, alertes), §18 Sprint 6.
