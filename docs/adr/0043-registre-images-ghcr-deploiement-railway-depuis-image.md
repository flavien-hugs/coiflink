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
  `ghcr.io` à chaque push sur une ref de publication ; Railway est reconfiguré pour tirer l'image
  publiée plutôt que de builder depuis le source.
- **Option C — autre registre** (Docker Hub, ECR/GCR/ACR) : écartée — GHCR est déjà le registre
  documenté comme évolution possible par ADR-0011 et supporte l'**auto-update** natif Railway sur les
  tags non-semver (`:latest`, `:dev`) comme semver (`:X.Y.Z`) — pas de garantie équivalente
  documentée pour Docker Hub/ECR/GCR/ACR côté Railway au moment de la décision.
- **Convention de tag d'image — Option A (un seul tag `latest`)** : simple mais ne distingue pas les
  différents stades de release (dev/RC/prod) sur le registre. **Option B (retenue) — tag dérivé de la
  ref déclenchante** : `main`→`latest`, `develop`→`dev`, `rc/<X.Y.Z>`→`<X.Y.Z>_RC`, tag git
  `[v]X.Y.Z`→`<X.Y.Z>`, chaque image portant en plus son SHA long. Aligné sur le modèle
  `dev`/`staging`/`prod` déjà posé par ADR-0011 (§1) : `dev` et `latest` correspondent naturellement
  aux images à faire suivre respectivement par les environnements Railway `staging` et `production`
  (mapping laissé à la bascule manuelle, voir Conséquences — cet ADR ne tranche que la **CI**, pas
  quel environnement Railway suit quel tag).

## Décision

- **Déclencheurs (`on:`)** : `ci.yml` s'exécute désormais aussi sur push vers `develop` et `rc/**`,
  et sur tout tag git (`tags: ["*"]`), en plus de `main` et des PR — **tous les jobs** (`backend`,
  `web`, `mobile`, `dependency-scan`, `docker-*`) tournent sur ces refs, pas seulement les jobs
  Docker : une image n'est jamais publiée sans que la suite de tests complète soit passée sur son
  commit (cohérent avec le principe « CI verte obligatoire » d'ADR-0010).
- **Job `image-tag`** (nouveau, source de vérité unique du tag à publier — évite que
  `docker-backend`/`docker-web` divergent) : calcule, à partir de `github.ref_type`/`github.ref_name`,
  le tag à publier selon la convention ci-dessus ; sort une chaîne **vide** hors d'un push sur une ref
  de publication supportée (PR, ou une future branche non couverte) — traité par les jobs
  consommateurs comme « ne pas publier ».
- **CI (jobs `docker-backend`/`docker-web`)** : le build existant (`push: false, load: true`, smoke
  test `GET /health` / page d'accueil) est **conservé tel quel** sur toute PR — c'est la porte de
  validation avant publication. Une **étape de publication** est ajoutée, gardée par
  `needs.image-tag.outputs.tag != ''` (jamais sur une PR, y compris de fork) :
  - connexion à `ghcr.io` via `docker/login-action` avec le secret dépôt **`MY_GITHUB_TOKEN`** ;
  - deux tags par image : celui calculé par `image-tag` (`latest`/`dev`/`<X.Y.Z>_RC`/`<X.Y.Z>`) **et**
    le SHA long, sur les images `ghcr.io/<owner>/coiflink-backend` et `ghcr.io/<owner>/coiflink-web` ;
  - `permissions: packages: write` scopé à ces **deux jobs seulement** (pas au workflow entier — les
    jobs `backend`/`web`/`mobile`/`dependency-scan`/`image-tag` restent en lecture seule, cohérent
    avec le least-privilege d'ADR-0010).
- **Railway : bascule des deux services en source « Docker Image »**, chaque environnement suivant le
  tag qui lui correspond (`ghcr.io/<owner>/coiflink-backend:latest`/`coiflink-web:latest` pour
  `production`, `:dev` pour `staging` — mapping naturel avec le modèle d'environnements d'ADR-0011,
  à confirmer à la bascule), avec **Image Auto Updates** activé (Railway détecte une nouvelle
  poussée sur le tag suivi et redéploie dans la fenêtre de maintenance configurée — cf. documentation
  Railway « Image Auto Updates »). Cette bascule est un **réglage service** (dashboard ou API
  `serviceInstanceUpdate`), **non exprimable** dans `railway.json` (le schéma config-as-code ne
  couvre que `build`/`deploy` pour un service déjà source-typé ; le type de source lui-même — dépôt vs
  image — est un attribut du service, pas du fichier). **Non appliquée par cet ADR** : voir
  Conséquences.
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
  jamais son tag de publication.
- **Un tag par stade de release** : `dev`/`latest`/`<X.Y.Z>_RC`/`<X.Y.Z>` rendent visibles, sur le
  registre lui-même, quelle image correspond à quel stade — sans avoir à croiser avec l'historique
  git. Le SHA long, présent en second tag sur **chaque** image, reste la référence immuable pour un
  rollback précis indépendant de l'évolution ultérieure d'un tag mobile (`latest`/`dev` pointent vers
  la dernière poussée, contrairement au SHA).
- **Calcul du tag centralisé (`image-tag`)** : un seul job source de vérité pour la convention, plutôt
  que de dupliquer la logique dans `docker-backend` et `docker-web` — un futur ajustement de la
  convention (ex. nouveau préfixe de branche) se fait à un seul endroit.
- **Portabilité accrue** : le registre est indépendant de la plateforme d'hébergement (une migration
  hors Railway réutilise directement les images publiées), cohérent avec le plan « portable » déjà
  posé par ADR-0011.
- **Compromis accepté** : élévation de permissions CI (`packages: write`), certes scopée à deux jobs,
  mais une élévation réelle par rapport au « aucune élévation » d'ADR-0011 ; un secret dépôt dédié
  (`MY_GITHUB_TOKEN`) à provisionner et faire tourner comme tout secret CI ; une étape de bascule
  manuelle côté Railway, hors CI, qui doit être appliquée et vérifiée par un administrateur ; la CI
  s'exécute désormais aussi sur `develop`/`rc/**`/tags (coût runner supplémentaire par rapport au
  périmètre `main`-seul d'avant cet ADR).

## Conséquences

- **Positives** : images publiées, versionnées (tag de stade + SHA) et validées (smoke test) avant
  tout déploiement ; auto-update Railway sur nouvelle poussée du tag suivi (pas de redéploiement
  manuel après merge) ; registre portable, indépendant de Railway ; convention de tag lisible
  directement sur le registre (dev/RC/prod distingués sans consulter l'historique git).
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
  - **`MY_GITHUB_TOKEN` non vérifié par cet ADR** : sa provenance exacte (PAT dédié vs autre) et son
    scope (`write:packages` a minima) n'ont pas été confirmés dans cet environnement — à vérifier avant
    la première publication réelle (un jeton insuffisamment scopé fait échouer `docker/login-action`
    avec un `403`, sans risque de fuite au-delà de l'échec du job).
- **Suivi / à confirmer (non bloquant, actions manuelles requises)** :
  - confirmer que le secret dépôt `MY_GITHUB_TOKEN` (Settings → Secrets and variables → Actions) est
    bien provisionné avec le scope `write:packages` (a minima) ;
  - basculer `coiflink-backend`/`coiflink-web` en source « Docker Image » sur Railway (tag `:latest`
    pour `production`, `:dev` pour `staging` — ou tout autre mapping retenu) et activer Image Auto
    Updates (choisir la fenêtre de maintenance) ;
  - reporter `startCommand`/`healthcheckPath`/`healthcheckTimeout`/`restartPolicyType`/
    `restartPolicyMaxRetries` de `deploy/railway/*.json` directement sur chaque service Railway ;
  - vérifier/rendre public le package GHCR après la première publication (ou accorder l'accès en
    lecture à Railway) ;
  - décider si les images `<X.Y.Z>_RC`/`<X.Y.Z>` (branches `rc/**`, tags git) alimentent un
    environnement Railway dédié ou restent des artefacts de vérification manuelle hors Railway ;
  - mettre à jour `docs/environnements-et-secrets.md` une fois la bascule effectuée et vérifiée.
