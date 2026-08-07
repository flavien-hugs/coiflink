# ADR-0038 : Mise en production — observabilité (monitoring/alerting native Railway + sonde de disponibilité externe), stratégie de rollback (app + base) & liveness-only

- **Statut** : Accepté
- **Date** : 2026-08-07
- **Décideurs** : équipe CoifLink
- **Issue** : #54 (Déploiement production)
- **Référence PRD** : §10.2 (déploiement : hébergement cloud sécurisé, sauvegardes automatiques),
  §11.3/§11.4 (données personnelles, journalisation d'*actions* — jamais de secret/valeur/PII dans
  logs, métriques ou alertes), §12.2 (**disponibilité ≥ 99 %**, **sauvegarde quotidienne**,
  **monitoring des services critiques**, **alertes en cas d'incident**), §18 Sprint 6 (déploiement
  production, monitoring activé comme critère de sortie)
- **S'appuie sur** : [ADR-0011](./0011-deploiement-environnements-secrets.md) (Railway, région
  `europe-west4`, deploy-from-source, environnements `dev`/`staging`/`prod`, politique de sauvegardes),
  [ADR-0010](./0010-ci-cd-docker-packaging.md) (invariants CI/Docker, build-seul, images non-root sans
  secret), [ADR-0004](./0004-donnees-postgresql-redis.md) (Redis = cache/queue, non sauvegardé),
  [ADR-0005](./0005-stockage-objet-s3-compatible.md) (stockage objet, versionnement/backup du bucket),
  [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) (Alembic, prérequis `btree_gist`),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (deny-by-default, `PUBLIC_ROUTE_PATHS`)

## Contexte et problème

[ADR-0011](./0011-deploiement-environnements-secrets.md) (#5) a tranché le **socle** de déploiement
(Railway, région `europe-west4`, *deploy-from-source*, modèle `dev`/`staging`/`prod`, magasin de
secrets, **politique** de sauvegardes) et [`docs/environnements-et-secrets.md`](../environnements-et-secrets.md)
porte le **runbook `staging` reproductible** + la **procédure de sauvegarde/restauration**, avec une
**clause de parité `prod`** (« `prod` suit le même runbook sur l'environnement `production` »). Mais
**rien n'est réellement en production** : l'environnement `production` n'a pas été provisionné (#5 était
purement infra/doc), et il subsiste **trois manques nets** au regard des critères d'acceptation de #54
et du PRD §12.2 :

1. **Monitoring & alerting non adressés.** Aucun ADR, aucune doc, aucune configuration ne couvre le
   *monitoring des services critiques*, les *alertes en cas d'incident* ni la *surveillance de
   disponibilité* (cible **99 %**). Le healthcheck Railway sur `/health` (déclaré dans
   `deploy/railway/backend.json`) et le `restartPolicyType: ON_FAILURE` existent, mais **aucune
   observabilité de bout en bout** n'est décidée ni documentée.
2. **Sauvegardes non vérifiées.** La **politique** est écrite (§5 de `docs/environnements-et-secrets.md` :
   quotidienne, rétention 7 j, chiffrée, restauration testée) mais **aucune sauvegarde n'a été activée
   ni vérifiée** en réel : **RPO/RTO non mesurés**, aucun test de restauration consigné.
3. **Aucune procédure de rollback.** Retour à un déploiement antérieur, cohabitation avec les migrations
   Alembic, critères de décision, autorisation et communication ne sont **documentés nulle part**.

Deux **décisions transverses** doivent en outre être tranchées, chacune touchant la surface publique ou
la surface de secrets :

- **Liveness-only vs readiness dédiée.** `GET /health` est une **sonde de liveness pure** (renvoie
  `{"status":"ok"}` sans accès base ni PII, exemptée du deny-by-default via `PUBLIC_ROUTE_PATHS`) — elle
  **ne teste pas** la connectivité base. Faut-il ajouter une sonde de *readiness* (`SELECT 1`) ?
- **Suivi d'erreurs applicatif (Sentry ou équivalent).** Améliore l'observabilité mais **ajoute une
  dépendance, un secret `SENTRY_DSN` et une surface de PII** à masquer.

Contrainte transverse : #54 **exécute et documente** la mise en production **sans jamais** committer ni
journaliser de secret ou de PII, et **sans laisser croire** qu'une intégration (ex. suivi d'erreurs)
existe si elle n'est pas réellement câblée (PRD §11.3/§11.4).

## Options envisagées

### Observabilité (monitoring & alerting)

- **Option A — Native plateforme + surveillance externe.** Healthchecks Railway (`/health` backend,
  `/` web) + **métriques Railway** (CPU/mémoire/réseau/redémarrages) + **état des déploiements** +
  **notifications Railway** (échec de déploiement, crash, redémarrages) ; **plus** une **sonde d'uptime
  externe indépendante** interrogeant `GET /health` du domaine public (mesure la cible **99 %** hors
  plateforme, détecte aussi une panne réseau/plateforme).
- **Option B — Pile d'observabilité auto-hébergée** (Prometheus + Grafana + Alertmanager, ou
  équivalent). La plus riche, mais **surdimensionnée** au MVP : exploitation, stockage et sécurité d'une
  pile supplémentaire à porter.
- **Option C — Suivi d'erreurs applicatif comme socle** (Sentry/équivalent). Excellent pour le *debug*
  applicatif, mais **n'est pas** un moniteur de disponibilité ; ajoute une dépendance + un secret + une
  surface de PII.

### Sonde de readiness

- **Option A — Liveness-only.** Conserver `/health` en liveness pure ; la disponibilité de la base est
  **implicitement** surveillée par les routes réelles (une panne DB fait échouer `/auth/*`, les routes
  salon, etc.) et par les métriques Railway.
- **Option B — Readiness dédiée.** Ajouter `GET /health/ready` (`SELECT 1` borné, `200`/`503`),
  **publique** (ajout à `PUBLIC_ROUTE_PATHS` **après revue de sécurité**), **hors** politique de
  redémarrage (`ON_FAILURE`).

### Stratégie de rollback

- **Option A — Rollback manuel documenté.** Runbook idempotent : retour applicatif au **déploiement/
  build antérieur** sain (Railway *rollback*/redeploy) + **arbre de décision base** (downgrade réversible
  vs *forward-fix* vs restauration de sauvegarde) + critères, autorisation, communication.
- **Option B — Rollback automatisé.** Détection d'anomalie → bascule automatique. Ajoute de
  l'automatisation CD **explicitement hors périmètre** au MVP (ADR-0011 a acté un **déploiement
  manuel/documenté**).

### Suivi d'erreurs applicatif (Sentry ou équivalent)

- **Option A — Différé/optionnel.** Ne pas l'introduire au MVP ; documenter la surface (secret
  `SENTRY_DSN`, scrubbing PII) comme **évolution optionnelle**, **sans** prétendre qu'elle est livrée.
- **Option B — Retenu maintenant.** L'intégrer côté backend (et/ou web) dès #54.

## Décision

### 1. Observabilité : native plateforme + sonde de disponibilité externe (Option A)

Retenir l'**observabilité native Railway complétée par une sonde d'uptime externe** :

- **Santé des services** : conserver le **healthcheck** Railway sur `/health` (backend) et `/` (web),
  **déjà déclaré** dans `deploy/railway/*.json` ; le `restartPolicyType: ON_FAILURE`
  (`restartPolicyMaxRetries: 10`) couvre le **redémarrage automatique**. **Aucun changement** de ces
  fichiers (le `healthcheckPath` reste `/health` / `/`).
- **Métriques ressources & déploiements** : activer/consulter les **métriques Railway** (CPU, mémoire,
  réseau, redémarrages) et l'**état des déploiements** (build/deploy/crash) via `use-railway`/MCP
  `railway`.
- **Surveillance de disponibilité externe** : configurer une **sonde d'uptime indépendante** (moniteur
  HTTP externe) qui interroge périodiquement `GET /health` du domaine public `production` et **alerte**
  en cas d'échec — c'est elle qui **mesure la cible 99 %** (PRD §12.2) **hors** de la plateforme (elle
  détecte aussi une panne réseau/plateforme qu'un healthcheck interne ne verrait pas).

**Options B/C écartées** : la pile auto-hébergée est surdimensionnée au MVP ; le suivi d'erreurs n'est
pas un moniteur de disponibilité (voir §4).

### 2. Alerting : natif Railway + alerte de la sonde d'uptime, messages non-PII

- **Sources d'alerte** : **notifications Railway** (échec de déploiement, crash, redémarrages répétés)
  **et** alerte de la **sonde d'uptime** (indisponibilité `/health`).
- **Canaux** : e-mail au minimum ; webhook/chat en option. Le choix des canaux est **opérationnel** et
  documenté dans [`docs/mise-en-production.md`](../mise-en-production.md), **sans** figer de valeur dans
  le dépôt.
- **Invariant non-PII / non-secret (§11.3/§11.4)** : une alerte porte un **identifiant de service**, un
  **code d'état**, un **horodatage** — **jamais** une valeur de variable, un jeton, un DSN, un e-mail,
  un téléphone ni un payload utilisateur. Les **logs de déploiement** Railway sont à **accès restreint**
  et ne doivent **jamais** contenir de secret ni de PII (on journalise des *actions*, pas des *valeurs*).

### 3. Sonde de readiness : liveness-only au MVP (Option A)

Conserver `/health` en **liveness pure** ; **aucune modification de code** n'est introduite par #54
(`health.py`, `security.py`, `main.py` inchangés). La connectivité base est **implicitement** surveillée
par les routes réelles (une panne DB fait échouer `/auth/*`, les routes salon, etc.) et par les
**métriques Railway**. Le **healthcheck de déploiement reste `/health`**.

**Motivation** : ajouter `GET /health/ready` **élargit la surface publique** (revue de sécurité requise
sur `PUBLIC_ROUTE_PATHS`) sans bénéfice net au MVP, et **ne doit surtout pas** devenir le
`healthcheckPath` (un blip DB transitoire déclencherait un *restart storm* via `ON_FAILURE`). L'**Option
B** reste documentée comme évolution : si l'exploitation exige une *readiness* dédiée, ajouter un
**adapter entrant technique** `GET /health/ready` (`SELECT 1` borné, `200`/`503`, **aucun** détail
interne : ni DSN ni exception brute), l'ajouter à `PUBLIC_ROUTE_PATHS` **après revue**, le brancher sur
la **sonde d'uptime** et **jamais** sur la politique de redémarrage.

### 4. Suivi d'erreurs applicatif : différé/optionnel (Option A) — non livré, non impliqué

#54 **n'introduit pas** de suivi d'erreurs applicatif (Sentry ou équivalent). La raison : il ajoute une
**dépendance**, un **secret `SENTRY_DSN`** (hors dépôt) et une **surface de PII** à masquer (scrubbing,
`traces_sample_rate`). Le monitoring repose donc sur les **mécanismes natifs Railway + la sonde d'uptime
externe** (§1). La **surface** est documentée comme **évolution optionnelle** ; **rien** dans le dépôt
(code, `*.env.example`, config) ne doit **impliquer** qu'un tel suivi est actif tant qu'il n'est pas
réellement câblé. S'il est retenu plus tard, il faudra : `SENTRY_DSN` **secret hors dépôt**, **scrubbing
PII** actif, **aucune** capture de corps de requête sensible.

### 5. Rollback : manuel documenté (Option A) — app + arbre de décision base

Rédiger un **runbook de rollback** idempotent (dans [`docs/mise-en-production.md`](../mise-en-production.md)),
sans savoir tacite :

- **Rollback applicatif** : revenir au **déploiement/build antérieur** sain via Railway (*rollback*/
  redeploy). En *deploy-from-source*, cela revient à **redéployer le commit/build précédent connu bon**.
  Étapes ordonnées + **smoke tests** post-rollback (`GET /health` → `200`, page web).
- **Rollback base de données** (arbre de décision explicite) :
  - **Migration réversible, schéma seul** : `alembic downgrade <révision>` envisageable — le
    **round-trip `upgrade → downgrade → upgrade` est validé en CI** (#4) — en cohérence avec le rollback
    applicatif ;
  - **Migration avec transformation/perte de données** : **préférer un correctif en avant**
    (*forward-fix*) ou la **restauration d'une sauvegarde** (§4 doc) plutôt qu'un downgrade destructeur ;
  - **Règle de compatibilité** : privilégier des migrations **rétro-compatibles** (expand/contract) pour
    qu'un rollback applicatif reste possible **sans** downgrade immédiat.
- **Critères de déclenchement** : échec des smoke tests, taux d'erreur élevé, indisponibilité `/health`,
  alerte uptime — avec **seuils** documentés.
- **Autorisation & communication** : `production` est **restreint** (reviewers requis) — qui autorise,
  comment on communique, **traçabilité** de l'incident **sans** PII/secret dans le compte rendu.
- **Répétition** : le rollback est **répété sur `staging`** avant d'être considéré fiable.

L'**Option B** (rollback automatisé) reste **hors périmètre** MVP, cohérente avec le choix
« déploiement manuel/documenté » d'ADR-0011.

### 6. Sauvegardes vérifiées & journal de vérification

- **Activer** la **sauvegarde automatique quotidienne** de PostgreSQL `production` (mécanisme managé
  Railway ; à défaut, `pg_dump` planifié chiffré et stocké **hors dépôt** — repli #5), **rétention ≥ 7 j**
  glissants, **chiffrée au repos**, **RPO ≤ 24 h** (ADR-0011).
- **Vérifier la restaurabilité** (« sauvegardes **vérifiées** » = critère d'acceptation) : restaurer vers
  un **environnement jetable/isolé** (**jamais** directement sur `prod`), contrôler l'**intégrité**
  (nombre de tables, comptages, `alembic current` = révision attendue) et **mesurer le RTO**.
- **Consigner** dans un **journal de vérification des sauvegardes** (`docs/mise-en-production.md`) : date,
  identifiant de sauvegarde, résultat d'intégrité, **RTO mesuré**, opérateur — **sans PII**.
  *Une sauvegarde non testée n'est pas une sauvegarde.* Périodicité **au moins trimestrielle** (rappel #5).
- **Redis** : **pas** de sauvegarde critique (cache/queue, ADR-0004), reconstructible depuis Postgres.
- **Stockage objet** : **vérifier**/activer le **versionnement/backup** du **bucket médias** (actif
  depuis #15, ADR-0005) — point à ne pas différer davantage.

## Justification (compromis)

- **Native + externe** minimise le time-to-monitoring : les healthchecks, métriques et notifications sont
  **déjà natifs** de Railway (aucune pile à exploiter) et la **sonde externe** apporte la mesure
  d'**indisponibilité vue de l'extérieur** (la seule qui reflète honnêtement la cible 99 %). Le
  **compromis** est une observabilité **moins fine** que Prometheus/Sentry — accepté au MVP, où la
  priorité est « prod déployée et **monitorée** » sans dette d'exploitation.
- **Liveness-only** évite d'**élargir la surface publique** et le risque de *restart storm*, sans perdre
  la détection d'une panne base (routes réelles + métriques). Zéro code, zéro revue de sécurité
  supplémentaire — cohérent avec « la seule évolution de code envisagée reste optionnelle ».
- **Suivi d'erreurs différé** respecte l'invariant « **ne pas impliquer une intégration inexistante** » :
  aucun `SENTRY_DSN` ajouté, aucune fausse promesse d'observabilité applicative.
- **Rollback manuel documenté** livre la **valeur attendue** (retour arrière **reproductible** et son
  arbre de décision base) sans introduire l'automatisation CD, hors périmètre MVP (ADR-0011).
- **Sauvegardes vérifiées** transforme une **politique** (#5) en **preuve** (restauration testée, RTO
  mesuré, journal) — c'est la différence exacte entre « sauvegardes configurées » et « sauvegardes
  **vérifiées** » exigée par l'AC.

## Conséquences

- **Positives** : les critères d'acceptation de #54 sont **adressables sans dette** — **prod monitorée**
  (healthchecks + métriques + notifications Railway + sonde uptime externe visant 99 %), **alerting
  non-PII** décidé, **sauvegardes vérifiables** (procédure + journal de vérification), **rollback
  documenté** (app + base). Le point différé « **monitoring/alerting §12.2** » de l'index ADR est
  **tranché** par cet ADR. **Aucune** modification de code applicatif ni de `deploy/railway/*.json` ;
  `ci.yml`/`adw-sdlc.yml` **non régressés**.
- **Négatives / risques** :
  - **Couplage Railway** (rappel ADR-0011) : métriques/notifications natives ; une migration de
    plateforme demanderait de reporter le monitoring. La **sonde d'uptime externe** reste, elle,
    portable.
  - **Observabilité applicative limitée** tant que le suivi d'erreurs n'est pas retenu : le *debug* fin
    d'une exception s'appuie sur les **logs de déploiement** (accès restreint, non-PII).
  - **`btree_gist` sur Postgres managé `production`** (rappel ADR-0009) : prérequis à **vérifier avant**
    de migrer ; le runbook `production` l'inclut.
  - **Migrations non réversibles ↔ rollback base** : un `alembic downgrade` peut être **destructeur** ;
    d'où la règle **expand/contract** et l'arbre *forward-fix vs downgrade vs restauration*.
  - **Réglages hors dépôt** : protection de branche `main`, canaux d'alerte, seuils, domaine/TLS et
    accès restreint `production` restent des **réglages non versionnables** (rappel #5/ADR-0010) —
    à poser avant d'ouvrir la prod au trafic réel.
  - **Résidence des données** : `europe-west4` optimise la latence mais n'est pas en région (question
    ouverte d'ADR-0011) — **confirmer** l'absence d'obligation légale **avant** le pilote #55 (PII
    réelle).
- **Décisions volontairement (re-)différées** : **CD automatisé complet** (auto-deploy, promotions,
  rollback automatique) et **suivi d'erreurs applicatif** (Sentry) — hors périmètre MVP, documentés
  comme évolutions ; **readiness dédiée** (Option B) — retenue **seulement** si l'exploitation l'exige.
- **Suivi / à confirmer (non bloquant)** : **canaux d'alerte & seuils** exacts ; **RTO** mesuré au
  premier test ; **rétention/coût** des sauvegardes sur l'offre Railway retenue ; **nom de domaine
  public** à attacher (TLS géré plateforme — vérifier le renouvellement automatique).
