# ADR-0043 : Registre d'images GHCR & déploiement Railway depuis l'image

- **Statut** : Accepté
- **Date** : 2026-08-14
- **Décideurs** : équipe CoifLink
- **Issue** : ad hoc
- **Référence PRD** : §10.2 (déploiement) — reformule le point « Stratégie de registre d'images » d'[ADR-0011](./0011-deploiement-environnements-secrets.md) (#5)

## Contexte et problème

[ADR-0011](./0011-deploiement-environnements-secrets.md) (#5) avait tranché **deploy-from-source**
(Option A) : Railway build directement les `Dockerfile` committés (`deploy/railway/*.json`), ce qui
évitait d'élargir les permissions CI et de manipuler un PAT/GHCR (`ci.yml` restait inchangé,
build-seul). Le **push GHCR** (Option B) restait documenté comme évolution possible « sans dette »,
non retenue à l'époque.

La décision opérationnelle change : le déploiement passe au **registre d'images** (Option B
d'ADR-0011). L'ADR-0011 lui-même n'est **pas remplacé** — son modèle d'hébergement (Railway,
`europe-west4`), son magasin de secrets (variables Railway + GitHub Environments), son modèle
d'environnements (`dev`/`staging`/`prod`) et ses sauvegardes restent inchangés. Seul le point
« Stratégie de registre d'images » est reformulé par cet ADR.

## Options envisagées

- **Option A (statu quo) — deploy-from-source** : Railway continue de builder les `Dockerfile` du
  dépôt à chaque déploiement. `ci.yml` reste build-seul.
- **Option B — push GHCR + Railway en source « image »** : `ci.yml` publie les images sur
  `ghcr.io` à chaque push sur `main` ; Railway est reconfiguré pour tirer l'image publiée plutôt que
  de builder depuis le source.
- **Option C — autre registre** (Docker Hub, ECR/GCR/ACR) : écartée — GHCR est déjà le registre
  documenté comme évolution possible par ADR-0011, s'authentifie avec le `GITHUB_TOKEN` intégré
  (aucun compte ni PAT tiers), et supporte l'**auto-update** natif Railway sur les tags non-semver
  (`:latest`) comme semver (`:vX.Y.Z`) — pas de garantie équivalente documentée pour Docker Hub/ECR/
  GCR/ACR côté Railway au moment de la décision.

## Décision

- **CI (`.github/workflows/ci.yml`, jobs `docker-backend`/`docker-web`)** : le build existant
  (`push: false, load: true`, smoke test `GET /health` / page d'accueil) est **conservé tel quel** sur
  toute PR — c'est la porte de validation avant publication. Une **étape de publication** est ajoutée,
  déclenchée **uniquement** sur `push` vers `main` (jamais sur une PR, y compris de fork) :
  - connexion à `ghcr.io` via `docker/login-action` avec le `GITHUB_TOKEN` intégré (aucun PAT) ;
  - tags `latest` + SHA long (`docker/metadata-action`), images
    `ghcr.io/<owner>/coiflink-backend` et `ghcr.io/<owner>/coiflink-web` ;
  - `permissions: packages: write` scopé à ces **deux jobs seulement** (pas au workflow entier — les
    jobs `backend`/`web`/`mobile`/`dependency-scan` restent en lecture seule, cohérent avec le
    least-privilege d'ADR-0010).
- **Railway : bascule des deux services en source « Docker Image »** (`ghcr.io/<owner>/
  coiflink-backend:latest` et `ghcr.io/<owner>/coiflink-web:latest`), avec **Image Auto Updates**
  activé (Railway détecte une nouvelle poussée sur le tag `:latest` et redéploie dans la fenêtre de
  maintenance configurée — cf. documentation Railway « Image Auto Updates »). Cette bascule est un
  **réglage service** (dashboard ou API `serviceInstanceUpdate`), **non exprimable** dans
  `railway.json` (le schéma config-as-code ne couvre que `build`/`deploy` pour un service déjà
  source-typé ; le type de source lui-même — dépôt vs image — est un attribut du service, pas du
  fichier). **Non appliquée par cet ADR** : voir Conséquences.
- **`deploy/railway/backend.json`/`web.json`** : **conservés** comme référence documentaire
  (`startCommand`, `healthcheckPath`, `restartPolicy*`) mais **ne s'appliquent plus** une fois le
  service basculé en source image — Railway ne lit le config-as-code que pour un service dont le
  source est un dépôt connecté. Ces réglages doivent être **reportés manuellement** sur chaque
  service via le dashboard/API au moment de la bascule (voir Suivi).
- **Visibilité du package GHCR** : à vérifier après la première publication — un package GHCR est
  **privé par défaut** indépendamment de la visibilité du dépôt ; Railway doit soit le package
  **public**, soit disposer d'un identifiant avec accès en lecture (voir Suivi).

## Justification (compromis)

- **Image validée avant publication** : le smoke test (`GET /health` / page d'accueil) s'exécute
  **avant** toute publication GHCR — contrairement à deploy-from-source, où Railway build et déploie
  sans étape de vérification préalable équivalente. Une image qui échoue son smoke test n'atteint
  jamais `:latest`.
- **Rollback simple** : chaque image porte aussi son SHA long en tag — revenir à une version
  précédente est un changement de tag sur le service, sans dépendre de l'état du dépôt à un commit
  donné.
- **Portabilité accrue** : le registre est indépendant de la plateforme d'hébergement (une migration
  hors Railway réutilise directement les images publiées), cohérent avec le plan « portable » déjà
  posé par ADR-0011.
- **`GITHUB_TOKEN` natif, aucun PAT** : contrairement à la crainte initiale d'ADR-0011 (« évite … de
  manipuler un PAT/GHCR »), l'authentification CI→GHCR ne requiert **aucun secret supplémentaire** —
  seule la **bascule Railway→GHCR** (lecture, côté plateforme) peut nécessiter un identifiant si le
  package reste privé.
- **Compromis accepté** : élévation de permissions CI (`packages: write`), certes scopée à deux jobs,
  mais une élévation réelle par rapport au « aucune élévation » d'ADR-0011 ; une étape de bascule
  manuelle côté Railway, hors CI, qui doit être appliquée et vérifiée par un administrateur.

## Conséquences

- **Positives** : images publiées, versionnées (SHA) et validées (smoke test) avant tout déploiement ;
  auto-update Railway sur nouvelle poussée `:latest` (pas de redéploiement manuel après merge) ;
  registre portable, indépendant de Railway.
- **Négatives / risques** :
  - **La bascule Railway (source dépôt → source image) n'est pas appliquée par cet ADR ni par le
    changement CI seul** : elle requiert un accès Railway authentifié (dashboard ou
    `railway`/API), non disponible dans cet environnement au moment de la rédaction. Tant qu'elle
    n'est pas appliquée, Railway continue de builder depuis le source (comportement ADR-0011
    inchangé) — la publication GHCR est **sans effet** sur le déploiement réel jusqu'à cette bascule.
  - `deploy/railway/*.json` devient **partiellement obsolète** dès la bascule effectuée : les
    réglages `deploy.*` doivent être reportés sur le service (dashboard/API), sous peine de perdre le
    `healthcheckPath`/`restartPolicy` actuellement lus depuis ces fichiers.
  - **Visibilité GHCR non vérifiée** : si le package reste privé par défaut, Railway ne peut pas tirer
    l'image tant qu'un accès n'est pas accordé.
  - `packages: write` reste une élévation de permission CI réelle, même scopée à deux jobs.
- **Suivi / à confirmer (non bloquant, actions manuelles requises)** :
  - basculer `coiflink-backend`/`coiflink-web` en source « Docker Image » sur Railway
    (`ghcr.io/<owner>/coiflink-backend:latest` / `coiflink-web:latest`) et activer Image Auto Updates
    (choisir la fenêtre de maintenance) ;
  - reporter `startCommand`/`healthcheckPath`/`healthcheckTimeout`/`restartPolicyType`/
    `restartPolicyMaxRetries` de `deploy/railway/*.json` directement sur chaque service Railway ;
  - vérifier/rendre public le package GHCR après la première publication (ou accorder l'accès en
    lecture à Railway) ;
  - mettre à jour `docs/environnements-et-secrets.md` une fois la bascule effectuée et vérifiée.
