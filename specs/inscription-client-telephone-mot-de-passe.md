# Inscription client (nom, téléphone, mot de passe)

> Spécification de planification pour l'issue GitHub **#8 — US-1.1 · Inscription client (nom,
> téléphone, mot de passe)** (`feature` `security` · Must · Effort M · PRD §6 Épic 1, §11.1).
> **Dépend de #3** (modèle de données & schéma PostgreSQL — table `users` livrée).
> **Cette spec ne produit pas de code.** Elle décrit l'API d'inscription, les cas d'usage, les
> ports/adapters et les contraintes de sécurité à implémenter dans une phase ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, commentaires). Les
> en-têtes de section ci-dessous sont conservés en anglais car attendus par le gabarit du pipeline
> ADW ; le contenu reste en français, hors identifiants techniques (noms de tables/colonnes, routes,
> enums, symboles de code).

## Problem Statement

Le premier jalon fonctionnel (M1 — Authentification) est bloqué tant qu'un utilisateur ne peut pas
créer de compte. Le PRD (§6, US-1.1) demande qu'**un client crée un compte avec son nom, son numéro
de téléphone et un mot de passe** afin de pouvoir ensuite réserver un rendez-vous ; la vérification
**OTP est recommandée** ; le **mot de passe doit être chiffré** (§11.1, « chiffré avec un algorithme
sécurisé »).

État actuel du dépôt :

- Le schéma relationnel est en place (#3) : la table **`users`** existe déjà avec exactement les
  colonnes nécessaires — `full_name`, `phone` (**unique**, `uq_users_phone`), `email` (optionnel,
  unique partiel), `password_hash` (`NOT NULL`), `role` (CHECK sur `enums.Role`), `status` (CHECK sur
  `enums.UserStatus`, défaut `ACTIVE`), `created_at`, `updated_at`. **Aucune évolution de schéma
  n'est nécessaire pour l'inscription de base.**
- Le backend (`backend/`) est un squelette hexagonal (ADR-0008) : il n'expose que `GET /health` et
  **ne contient aucun cas d'usage, aucun router métier, aucun repository concret, ni couche
  d'authentification**. `domaine/` ne contient que des `enum.Enum`. `application/ports/` est vide.
  `adapters/sortant/persistance/session.py` fournit une fabrique d'engine SQLAlchemy **non câblée**
  à l'app.

Le besoin de #8 : **livrer l'API d'inscription client de bout en bout côté backend** — endpoint HTTP,
cas d'usage, ports et adapters — qui (1) crée un compte client, (2) **refuse un doublon de
téléphone**, (3) **ne stocke jamais le mot de passe en clair** (hachage), et (4) fournit une capacité
**OTP testable**. C'est aussi la **première feature qui introduit** un router métier, un repository
concret et la couche de hachage de mot de passe : elle pose les patterns que les issues d'auth
suivantes (#9 inscription gérant, #10 connexion/JWT, #11 reset OTP, #12 RBAC) réutiliseront.

## Goals

- **Endpoint d'inscription client** : `POST /auth/register` (nom, téléphone, mot de passe, email
  optionnel) créant un utilisateur de rôle `CLIENT`, statut `ACTIVE` par défaut.
- **Refus du doublon de téléphone** : un numéro déjà inscrit est rejeté proprement (HTTP `409`),
  avec la contrainte base `uq_users_phone` comme garde-fou d'ultime recours (course concurrente).
- **Mot de passe jamais en clair** : hachage par un algorithme robuste (recommandation **argon2**)
  derrière un **port** (`application/ports/`) implémenté par un **adapter sortant**. Ni le mot de
  passe, ni le condensat, ni l'OTP, ni le téléphone ne sont **jamais journalisés**.
- **OTP testable** : logique de génération/vérification d'OTP **pure et injectable** (RNG + horloge
  injectés), couverte par des tests unitaires — **sans dépendre** d'un envoi SMS réel (l'infra SMS
  relève de M5, Épic 7, ADR-0006). L'OTP est **désactivé par défaut** (drapeau de configuration) pour
  que l'inscription fonctionne de bout en bout sans SMS.
- **Respecter l'hexagonal (ADR-0008)** : domaine pur (entité/valeurs), cas d'usage dans
  `application/` déclarant ses besoins via des ports, adapters entrant (HTTP) et sortants
  (persistance, hachage) seuls à connaître le framework et l'I/O ; câblage dans le composition root
  (`main.py`).
- **Documenter l'API publique** : schéma de requête/réponse (Pydantic → OpenAPI auto-générée,
  ADR-0003) et mise à jour du `backend/README.md`.
- **Poser les patterns d'auth réutilisables** : port `DepotUtilisateur` (repository), port
  `HacheurMotDePasse`, normalisation du téléphone, gestion d'erreurs HTTP, dépendance de session
  FastAPI — repris par #9/#10/#11/#12.

## Non-Goals

- **Connexion & JWT (US-1.2, #10)** : l'inscription **n'émet pas** de JWT / refresh token. L'émission
  de jetons, le rate-limit anti-bruteforce sur la connexion et le `JWT_SECRET` sont hors périmètre
  (une décision *auto-login après inscription* est laissée en *Open Questions*).
- **Réinitialisation de mot de passe par OTP (US-1.3, #11)** : hors périmètre ; #8 ne livre que la
  **capacité OTP testable** réutilisable, pas le parcours de reset.
- **Inscription gérant / création du salon (#9, US-2.1)** : rôle `MANAGER` et onboarding propriétaire
  traités par une issue dédiée.
- **RBAC / middleware d'autorisation (#12)** : la protection des routes par rôle et l'isolation par
  salon (§11.2) arrivent avec #12.
- **Envoi SMS / push réel de l'OTP** : dépend de l'infra notifications (FCM + SMS via file Redis,
  ADR-0006) livrée en **M5 (Épic 7)** ; l'adapter d'envoi concret est **différé**. #8 s'arrête à un
  adapter d'envoi *stub* (sans journaliser le code) ou en mémoire pour les tests.
- **UI mobile Flutter d'inscription** (§7.1 « Inscription / Connexion ») : le paquet `app-mobile/`
  est un squelette ; le câblage de l'écran est un travail front distinct. #8 se concentre sur l'**API
  backend** (les critères d'acceptation sont tous vérifiables côté backend). *À confirmer* — voir
  *Open Questions*.
- **Journalisation des accès sensibles (§11.4)** : l'audit structuré est un item transverse (M6) ;
  #8 se contente de **ne jamais journaliser** de secret/PII.
- **Consentement / RGPD-like (§11.3)** : la capture explicite du consentement n'est pas spécifiée
  au niveau feature ; hors périmètre #8 (mentionné en *Open Questions*).

## Relevant Repository Context

- **Statut** : greenfield outillé ; socle M0 livré (#1–#6). #8 est la **première feature M1**.
- **Stack figée (ADR)** :
  - Backend **FastAPI** · Python **≥ 3.12** · API REST + **JWT** (ADR-0003). OpenAPI auto-générée à
    partir des modèles Pydantic — sert l'exigence « documenter les API publiques ».
  - Persistance **SQLAlchemy 2.0 + Alembic + psycopg 3**, **PostgreSQL 16** (ADR-0009). Driver DSN
    normalisé psycopg 3 par `session.py`.
  - **Redis 7** (cache/queue, ADR-0004) : présent dans l'infra (`deploy/`) mais **non câblé** au code.
  - Notifications **FCM + SMS via file Redis** (ADR-0006) : **SMS = canal de l'OTP**, mais livré en
    **M5** ; fournisseur SMS concret = décision opérationnelle différée (#5).
  - **Architecture hexagonale** (ADR-0008) : dépendance toujours vers l'intérieur ; **toute brique
    externe passe par un port + un adapter sortant** ; le domaine n'importe jamais FastAPI/SQLAlchemy.
- **Sécurité ancrée (ADR-0003 « Conséquences », §11.1)** — à implémenter en M1 : mot de passe **haché
  par algorithme robuste (argon2 ou bcrypt), jamais en clair** ; JWT + refresh (#10) ; **OTP à usage
  unique et expirant** ; anti-bruteforce ; RBAC strict deny-by-default (#12). Les **bibliothèques
  JWT / hachage** sont explicitement laissées à **M1** par le « Suivi » d'ADR-0003 — **#8 doit donc
  acter le choix de la lib de hachage** (voir *Risks*).
- **Table `users` (livrée par #3)** — `backend/coiflink_api/adapters/sortant/persistance/modeles.py` :
  `phone` `String(32)` **unique** ; `email` `String(255)` nullable, **unique partiel** (`WHERE email
  IS NOT NULL`) ; `password_hash` `String(255)` `NOT NULL` (commentaire : « Jamais de mot de passe en
  clair ») ; `role`/`status` = `text` + `CHECK` dérivé de `domaine/enums.py` (`Role`, `UserStatus`).
- **Arborescence backend actuelle** :
  - `coiflink_api/domaine/enums.py` — `Role`, `UserStatus`, … (enums purs).
  - `coiflink_api/application/` + `application/ports/` — **vides** (à peupler).
  - `coiflink_api/adapters/entrant/sante.py` — router `/health` (patron d'adapter entrant).
  - `coiflink_api/adapters/sortant/persistance/{base,modeles,session}.py`.
  - `coiflink_api/main.py` — composition root : lit l'env, monte les routers.
- **Config** : lue **depuis l'environnement** (`backend/.env.example`), jamais de secret en dur.
  `JWT_SECRET` déjà prévu (vide) et annoté « requis dès #8 (auth) ». `DATABASE_URL` pilote app +
  Alembic.
- **Conventions** : Conventional Commits ; **aucune signature IA** dans code/commits/PR ; specs à
  en-têtes anglais / contenu français ; lint `ruff check` (règles `F`, `E4/E7/E9`, `B`, `W`,
  ligne 100) ; test gate `pytest` (#6).

## Proposed Implementation

> Approche recommandée pour un agent d'implémentation. Les points marqués *(à confirmer)* renvoient à
> *Risks and Open Questions* : décision à acter avant/pendant l'implémentation.

### 1. Domaine (`coiflink_api/domaine/`) — pur, sans dépendance framework/I/O

- **`telephone.py`** — normalisation & validation du numéro. Objet-valeur `NumeroTelephone` (ou
  fonction `normaliser_telephone(str) -> str`) produisant une **forme canonique unique** (recommandé :
  **E.164**, indicatif **Côte d'Ivoire `+225`** par défaut pour un numéro local). *Rationale* : la
  colonne `phone` est unique ; sans canonicalisation, `0700000000` et `+2250700000000` créeraient deux
  comptes et **contourneraient** le refus de doublon. Rejeter les numéros invalides (longueur, chiffres
  autorisés). *(à confirmer : plan de numérotation et pays par défaut.)*
- **`mot_de_passe.py`** — **politique** de mot de passe pure : longueur minimale (recommandé **≥ 8**),
  non vide, éventuellement bornes. Renvoie une erreur de domaine explicite si invalide. **Ne fait pas**
  le hachage (c'est un port). *(à confirmer : règles de complexité.)*
- **`otp.py`** — logique OTP **pure et injectable** : génération d'un code (longueur, ex. 6 chiffres)
  via un **RNG injecté**, et vérification donnée une **horloge injectée** (expiration) + compteur
  d'essais + usage unique. Aucune I/O, aucun envoi, **aucun log du code**. C'est le cœur du critère
  « OTP testable ».
- **`erreurs.py`** (ou exceptions dans chaque module) — erreurs métier : `TelephoneDejaUtilise`,
  `TelephoneInvalide`, `MotDePasseInvalide`, `OtpInvalide`/`OtpExpire`. Le domaine lève des erreurs
  **neutres** (pas de HTTP) ; l'adapter entrant les traduit en codes HTTP.
- **`utilisateur.py`** *(optionnel, léger)* — entité/représentation de domaine d'un utilisateur à
  créer (nom, téléphone canonique, email, rôle, statut, condensat) découplée de l'ORM. Peut rester un
  simple `dataclass`. *(à confirmer : entité de domaine dédiée vs passage direct du modèle ORM par le
  repository — recommandé : dataclass de domaine pour ne pas fuiter SQLAlchemy dans l'application.)*

### 2. Application (`coiflink_api/application/` + `ports/`) — cas d'usage + interfaces

Ports (interfaces `typing.Protocol`, cf. README backend) dans `application/ports/` :

- **`depot_utilisateur.py`** — `DepotUtilisateur` : `telephone_existe(phone) -> bool`,
  `creer(utilisateur) -> Utilisateur` (retourne l'entité créée avec `id`). Implémenté par un adapter
  sortant de persistance.
- **`hacheur_mot_de_passe.py`** — `HacheurMotDePasse` : `hacher(clair) -> str`,
  `verifier(clair, condensat) -> bool`. Implémenté par un adapter sortant crypto.
- **`expediteur_otp.py`** — `ExpediteurOtp` : `envoyer(telephone, code) -> None` (adapter d'envoi ;
  **stub/différé** en #8). **Contrat : ne journalise jamais le code ni le téléphone.**
- **`depot_otp.py`** *(si OTP persisté)* — `DepotOtp` : `enregistrer(telephone, condensat_otp,
  expiration)`, `recuperer(telephone)`, `consommer(...)`. Implémenté en mémoire pour #8 (voir §3).
  *(à confirmer : stockage OTP — voir Data Model / Open Questions.)*

Cas d'usage :

- **`inscription.py`** — `InscrireClient` (constructeur injectant les ports). `executer(commande)` :
  1. valider les entrées (nom non vide, mot de passe conforme à la politique, email optionnel bien
     formé) ;
  2. **normaliser le téléphone** en forme canonique (domaine) ;
  3. **pré-vérifier le doublon** via `DepotUtilisateur.telephone_existe` → lever
     `TelephoneDejaUtilise` si présent ;
  4. **hacher** le mot de passe via `HacheurMotDePasse.hacher` (le clair n'est jamais conservé
     au-delà de l'appel) ;
  5. **persister** l'utilisateur (`role=CLIENT`, `status=ACTIVE` — ou état non vérifié si OTP activé,
     voir §4) via `DepotUtilisateur.creer` ; **capturer l'`IntegrityError`** de la contrainte unique
     comme *fallback* concurrent et la retraduire en `TelephoneDejaUtilise` ;
  6. si `OTP_ENABLED` : générer un OTP (domaine), l'enregistrer haché (`DepotOtp`), déclencher l'envoi
     (`ExpediteurOtp`, stub en #8) ;
  7. retourner l'entité créée **sans** mot de passe ni condensat.

### 3. Adapters sortants (`coiflink_api/adapters/sortant/`) — I/O, framework

- **`persistance/depot_utilisateur.py`** — implémente `DepotUtilisateur` avec une `Session`
  SQLAlchemy 2.0 sur le modèle `User` (`modeles.py`). `telephone_existe` = `SELECT` sur `phone` ;
  `creer` = `add` + `flush`/`commit`, mappe l'entité domaine ↔ modèle ORM.
- **`securite/hacheur.py`** — implémente `HacheurMotDePasse`. **Recommandé : argon2** (via
  `argon2-cffi`, ou `pwdlib[argon2]`). *Rationale* : argon2 évite la **troncature à 72 octets** de
  bcrypt et est recommandé par l'OWASP. `verifier` gère aussi le *rehash* futur. *(à confirmer : lib &
  algorithme — voir Risks.)*
- **`securite/otp_memoire.py`** *(si OTP persisté via port)* — implémentation **en mémoire** du
  `DepotOtp` (dict avec TTL), suffisante pour tests/dev ; adapter Redis/DB **différé**.
- **`notifications/expediteur_otp_stub.py`** — implémentation *no-op* d'`ExpediteurOtp` pour #8 (ne
  fait rien / renvoie un statut « différé »), **sans journaliser** le code. L'adapter SMS réel arrive
  en M5 (ADR-0006).
- **`persistance/session.py`** *(modifier)* — ajouter une fabrique **`sessionmaker`** et une
  dépendance de session request-scoped exploitable par FastAPI (`get_session`). Réutilise
  `database_url()`/`get_engine()` existants. *(à confirmer : session **sync** (simple, cohérente avec
  l'engine sync actuel) vs **async** (ADR-0009 évoque un câblage async futur) — recommandé : **sync**
  pour #8, endpoints `def` exécutés en threadpool par FastAPI, migration async possible plus tard.)*

### 4. Adapter entrant (`coiflink_api/adapters/entrant/auth.py`) — router HTTP

- **`POST /auth/register`** *(chemin à confirmer — voir Open Questions)* :
  - **Requête** (Pydantic) : `full_name: str`, `phone: str`, `password: str` (jamais logué, jamais
    renvoyé), `email: str | None`. Validation Pydantic (types, longueurs, format email) + validation
    domaine (téléphone, politique mot de passe).
  - **Réponse `201 Created`** : `{ id, full_name, phone, email, role, status, created_at }` — **jamais**
    `password` ni `password_hash`. Si `OTP_ENABLED` et gating retenu : `202 Accepted` + indication de
    vérification requise (voir §4 gating, *Open Questions*).
  - **Erreurs** : `409 Conflict` (doublon téléphone) ; `422 Unprocessable Entity` (validation) ;
    `500` non spécifique en dernier recours (sans fuite de détail interne).
  - **DI** : injecte le cas d'usage `InscrireClient` assemblé avec les adapters, via `Depends`
    (session + adapters), sans référence directe aux clients d'infra dans le domaine/application.
- **Gating OTP (si activé)** : deux options (à trancher) — (a) créer le compte `ACTIVE` et n'utiliser
  l'OTP que comme **confirmation non bloquante** (aucun changement de schéma) ; (b) créer le compte en
  **état non vérifié** et exiger la vérification avant activation → nécessite un **état/colonne
  supplémentaire** (`phone_verified` ou valeur d'enum `UserStatus`) = **changement de schéma**.
  **Recommandé pour #8 : (a)** — OTP désactivé par défaut, capacité testable livrée, gating
  bloquant différé à l'arrivée de l'infra SMS (M5). *(à confirmer.)*

### 5. Composition root (`main.py` — modifier)

- Lire les nouveaux réglages d'env (`OTP_ENABLED`, éventuels paramètres OTP/hachage).
- Instancier les adapters sortants et les injecter dans `InscrireClient` ; monter le router `auth`.
- Aucune règle métier ici ; assemblage uniquement (comme pour `sante_router`).

## Affected Files / Packages / Modules

**Paquet concerné : `backend/` uniquement** (le front mobile est hors périmètre — voir *Non-Goals*).

**À créer :**
- `coiflink_api/domaine/telephone.py`, `mot_de_passe.py`, `otp.py`, `erreurs.py`, (optionnel)
  `utilisateur.py`.
- `coiflink_api/application/inscription.py` (cas d'usage `InscrireClient`).
- `coiflink_api/application/ports/depot_utilisateur.py`, `hacheur_mot_de_passe.py`,
  `expediteur_otp.py`, (si OTP persisté) `depot_otp.py`.
- `coiflink_api/adapters/sortant/persistance/depot_utilisateur.py`.
- `coiflink_api/adapters/sortant/securite/__init__.py`, `hacheur.py`, (si OTP persisté)
  `otp_memoire.py`.
- `coiflink_api/adapters/sortant/notifications/__init__.py`, `expediteur_otp_stub.py`.
- `coiflink_api/adapters/entrant/auth.py` (router + schémas Pydantic, ou `schemas.py` dédié).
- Tests : `tests/test_telephone.py`, `tests/test_mot_de_passe.py`, `tests/test_otp.py`,
  `tests/test_hacheur.py`, `tests/test_inscription_usecase.py`, `tests/test_auth_api.py`,
  (intégration Postgres, skip si pas de DSN) `tests/test_inscription_integration.py`.

**À modifier :**
- `coiflink_api/main.py` — câblage router + DI + lecture des nouveaux réglages.
- `coiflink_api/adapters/sortant/persistance/session.py` — ajouter `sessionmaker` + dépendance
  `get_session`.
- `backend/pyproject.toml` — ajouter la **lib de hachage** (recommandé `argon2-cffi>=23` **ou**
  `pwdlib[argon2]`) ; `pydantic[email]` si validation email native souhaitée (`email-validator`).
- `backend/.env.example` — `OTP_ENABLED` (défaut `false`) et paramètres éventuels (TTL OTP, longueur) ;
  rappel que `JWT_SECRET` reste **non utilisé** par #8 (l'inscription n'émet pas de JWT).
- `backend/README.md` — table des endpoints (ajouter `POST /auth/register`), section config (drapeaux
  OTP), rappel « mot de passe jamais en clair / jamais logué ».
- `docs/adr/` **(recommandé)** — acter le choix **lib de hachage + stratégie OTP** (nouvel
  **ADR-0012** *ou* note fermant le « Suivi » d'ADR-0003) ; indexer dans `docs/adr/README.md`.

**À lire (contexte) :** `prd-coiflink.md` (§6, §7.1, §11), `docs/adr/0003`, `0006`, `0008`, `0009`,
`backend/coiflink_api/adapters/sortant/persistance/modeles.py`, `.../session.py`,
`backend/coiflink_api/domaine/enums.py`, `backend/coiflink_api/adapters/entrant/sante.py`,
`backend/coiflink_api/main.py`, `backend/README.md`.

## API / Interface Changes

**Nouvel endpoint HTTP public (à documenter — OpenAPI auto-générée, ADR-0003) :**

- **`POST /auth/register`** *(chemin/versionnement à confirmer)*
  - **Corps (JSON)** : `full_name` (string, requis), `phone` (string, requis), `password` (string,
    requis), `email` (string, optionnel).
  - **`201 Created`** : `{ id, full_name, phone, email, role: "CLIENT", status, created_at }`.
    **Jamais** `password` ni `password_hash` dans la réponse.
  - **`409 Conflict`** : téléphone déjà inscrit.
  - **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/email invalides, champ
    manquant).
  - *(optionnel, si gating OTP retenu)* **`202 Accepted`** + indicateur de vérification requise, et un
    endpoint `POST /auth/verify-otp` — **différé** par défaut (voir *Open Questions*).

**CLI / autres interfaces réseau : none** (aucune nouvelle commande ; `GET /health` inchangé). L'API
d'inscription **n'émet aucun JWT** (la connexion est #10).

## Data Model / Protocol Changes

- **Inscription de base : none.** La table `users` (#3) porte déjà `full_name`, `phone` (unique),
  `email`, `password_hash`, `role`, `status`. Aucune migration n'est requise pour créer un client.
- **OTP — dépend de la stratégie retenue :**
  - **Recommandé (#8)** : OTP stocké **hors schéma** via le port `DepotOtp` (adapter **en mémoire**
    pour tests/dev ; adapter **Redis à TTL** ou table différé) → **aucune migration**.
  - **Si gating bloquant** (compte non vérifié avant activation) : nécessiterait soit une **colonne**
    `users.phone_verified boolean` (ou `phone_verified_at timestamptz`), soit une **nouvelle valeur
    d'enum** `UserStatus` (ex. `PENDING_VERIFICATION`) alignée sur le `CHECK ck_users_status` — donc
    **une migration Alembic** (`0002_*`) et une mise à jour de `domaine/enums.py`. **Non retenu** par
    défaut en #8 (voir *Open Questions*).
- **Sérialisation** : nouveaux schémas **Pydantic** de requête/réponse pour `/auth/register` (couche
  adapter entrant) — ne modifient pas le schéma relationnel.

## Security & Privacy Considerations

- **Mot de passe (§11.1)** : **jamais en clair**, jamais logué, jamais renvoyé. Hachage par
  algorithme robuste (**argon2** recommandé ; argon2 évite la troncature 72 octets de bcrypt). Le
  clair ne vit que le temps de l'appel `hacher()` ; aucune persistance/log du clair ni du condensat.
- **OTP** : **jamais journalisé**, ni transmis dans les réponses/erreurs. Stockage **haché** (pas de
  code en clair au repos), **usage unique**, **expiration**, **limite d'essais**. L'envoi réel (SMS,
  ADR-0006) — et donc l'exposition à un tiers — est **différé** (M5) ; l'adapter stub de #8 ne logue
  rien.
- **PII (§11.3)** : `full_name`, `phone`, `email` sont des données personnelles → **jamais
  journalisées** ; **collecte minimale** (s'en tenir aux champs de US-1.1). Les messages d'erreur ne
  divulguent pas d'existence de compte au-delà du strict nécessaire (attention à l'énumération de
  comptes — cf. *Open Questions* sur le message de `409`).
- **Refus de doublon** : géré au niveau application (pré-check → `409`) **et** garanti au niveau base
  par `uq_users_phone` (fallback anti-course : `IntegrityError` retraduite en `409`). La
  **normalisation du téléphone** est une **exigence de sécurité** ici : sans forme canonique, l'unicité
  et le refus de doublon sont contournables.
- **Secrets / config (ADR-0011)** : tout réglage lu **depuis l'environnement** ; **aucun secret
  committé** (seulement `.env.example`). `JWT_SECRET` reste **inutilisé** par #8. Les paramètres de
  hachage (coût argon2) sont non secrets mais configurables par env.
- **Anti-abus** : le rate-limiting (anti-bruteforce §11.1) vise surtout la connexion (#10) ; pour
  l'inscription/OTP, prévoir *a minima* une **limite d'essais OTP** côté logique. Un rate-limit
  d'endpoint HTTP est **recommandé** mais peut être porté par #10/#12 (à confirmer).
- **Résidence / budgets** : budget API **< 3 s** (§12.1) — le coût argon2 doit rester raisonnable
  (paramètres par défaut de la lib) ; pas de contrainte de résidence documentée au niveau feature.
- **Contrainte documentée non applicable** : #8 ne touche pas au chiffrement au repos (disque/
  sauvegardes → hébergement #5) ni à la journalisation d'audit structurée (§11.4, M6).

## Testing Plan

Test gate : **`pytest`** (ADR-0003 ; agrégé `MX_AGENT_TEST_CMD`, #6). `tests/test_health.py`,
`test_session.py`, `test_secrets_policy.py` doivent **rester verts**. `ruff check` doit passer.

- **Unitaires (sans base, rapides)** :
  - `telephone` : normalisation E.164 (numéro local → canonique), rejet des invalides, **idempotence**
    (`0700…` et `+2250700…` produisent la **même** forme → doublon détecté).
  - `mot_de_passe` : politique (rejet trop court/vide ; acceptation valide).
  - `otp` : génération de la bonne longueur (RNG injecté déterministe), vérification **OK/KO**,
    **expiration** (horloge injectée), **usage unique**, **limite d'essais** — *le critère « OTP
    testable »*.
  - `hacheur` : `hacher(clair) != clair` ; deux hachages du même clair diffèrent (sel) ;
    `verifier(clair, condensat)` vrai ; `verifier(mauvais, condensat)` faux ; le clair **n'apparaît
    pas** dans le condensat.
  - `InscrireClient` (cas d'usage avec **ports fakes**) : succès (utilisateur créé, mot de passe
    **haché** passé au dépôt, jamais le clair) ; **doublon → `TelephoneDejaUtilise`** ; validation
    déclenchée ; OTP émis seulement si activé (via faux `ExpediteurOtp`/`DepotOtp`), **sans exposer**
    le code.
- **API (FastAPI `TestClient`/`httpx`, dépôt fake, sans base réelle)** :
  - `POST /auth/register` valide → **`201`** + corps **sans** `password`/`password_hash` ;
  - doublon → **`409`** ; entrée invalide → **`422`** ;
  - **assertion de non-fuite** : la réponse (et les logs capturés) ne contiennent **jamais** le mot de
    passe/condensat/OTP.
- **Intégration (PostgreSQL 16, skip propre si pas de `DATABASE_URL`)** — cohérent avec le patron
  `test_migrations_postgres`/`test_session` :
  - l'inscription **persiste** un `users` avec `password_hash` ≠ mot de passe clair, `role=CLIENT`,
    `status=ACTIVE` ;
  - **doublon de téléphone** rejeté (`uq_users_phone`) même en contournant le pré-check (fallback
    `IntegrityError` → `409`).
- **Résilience** : course concurrente sur le même téléphone → un seul compte créé, l'autre `409`
  (démontré via le fallback `IntegrityError`).
- **Documentation** : vérifier (revue) que `backend/README.md` documente `POST /auth/register` et les
  réglages OTP, et que l'OpenAPI expose l'endpoint.

> Note : tant que l'infra SMS (M5) n'existe pas, les tests OTP portent sur la **logique** (génération/
> vérification) et l'**adapter stub/mémoire**, jamais sur un envoi réel.

## Documentation Updates

- **`backend/README.md`** : ajouter `POST /auth/register` à la table des endpoints ; section
  « Authentification / inscription » (rôle `CLIENT`, refus de doublon, hachage argon2, OTP désactivé
  par défaut & testable) ; rappel sécurité « mot de passe/OTP/PII jamais journalisés ».
- **`backend/.env.example`** : documenter `OTP_ENABLED` (défaut `false`) et paramètres éventuels
  (TTL/longueur OTP, coût argon2) ; préciser que `JWT_SECRET` n'est **pas** utilisé par #8.
- **`docs/adr/`** *(recommandé)* : **ADR-0012** (ou note) actant **lib de hachage** (argon2) +
  **stratégie OTP** (capacité testable, envoi différé M5, gating non bloquant) — ferme le « Suivi »
  d'ADR-0003 côté hachage ; entrée dans `docs/adr/README.md`.
- **OpenAPI** : auto-générée par FastAPI (aucune rédaction manuelle) ; s'assurer que les schémas
  Pydantic **excluent** tout champ sensible en sortie.
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit). L'OTP « recommandé » traité
  comme capacité optionnelle est tracé ici et dans l'ADR, sans réécrire le PRD.

## Risks and Open Questions

- **Lib & algorithme de hachage** *(à acter)* : **argon2** (`argon2-cffi` ou `pwdlib[argon2]`)
  recommandé (pas de troncature 72 octets, OWASP) vs **bcrypt** (`passlib[bcrypt]`, très répandu mais
  tronque à 72 octets). Décision structurante réutilisée par #10 (vérification à la connexion) et
  #11 (reset). À figer en ADR-0012.
- **Stratégie & stockage OTP** *(à acter)* : (a) **capacité testable, envoi différé, gating non
  bloquant, stockage hors schéma via port** (recommandé #8, aucune migration) ; vs (b) **gating
  bloquant** (compte non vérifié) → **migration** (`phone_verified` ou enum `PENDING_VERIFICATION`) +
  dépendance à l'infra SMS (M5). L'acceptation « OTP testable » est satisfaite par (a).
- **Normalisation du téléphone** *(à confirmer)* : plan de numérotation et pays par défaut (Côte
  d'Ivoire `+225` ?), acceptation de numéros internationaux, dépendance optionnelle
  (`phonenumbers`) vs normalisation maison. **Impacte directement** le refus de doublon.
- **Chemin & versionnement de l'API** *(à confirmer)* : `POST /auth/register` vs préfixe versionné
  (`/api/v1/auth/register`) vs libellé français (`/auth/inscription`). Aucune convention de route
  n'est encore posée (seul `/health` existe) ; #8 la **fixe** pour l'auth — cohérence à tenir avec
  #9/#10/#11.
- **Session sync vs async** *(à confirmer)* : engine **sync** actuel (simple, recommandé #8) vs câblage
  **async** évoqué par ADR-0009 (« engine/session FastAPI » en M1→). Décision réutilisée par toutes
  les features backend.
- **Auto-login après inscription** *(à confirmer)* : renvoyer un JWT à l'inscription (UX plus fluide)
  **ou** exiger une connexion explicite (#10). Recommandé : **pas de JWT en #8** (l'émission est #10).
- **Énumération de comptes** *(à confirmer)* : le message/statut du `409` sur doublon révèle
  l'existence d'un compte. Compromis UX vs anti-énumération — décision produit (le PRD ne tranche pas).
- **Rate-limiting inscription/OTP** *(à confirmer)* : porté par #8 (limite d'essais OTP au minimum) ou
  délégué à #10/#12 (anti-bruteforce global). §11.1 vise surtout la connexion.
- **Périmètre front mobile** *(à confirmer)* : #8 se limite-t-il à l'**API backend** (recommandé, tous
  les critères d'acceptation sont backend) ou doit-il aussi livrer l'**écran Flutter** d'inscription
  (§7.1) ? Le paquet `app-mobile/` est un squelette.
- **Consentement (§11.3)** *(hors périmètre, à noter)* : capture du consentement non spécifiée au
  niveau feature ; à trancher hors #8.
- **Dépendance `email-validator`** *(mineur)* : nécessaire pour la validation email native de Pydantic
  (`EmailStr`) — à ajouter si retenu, sinon validation légère maison.

## Implementation Checklist

1. **Acter les décisions structurantes** : lib de hachage (**argon2** recommandé), **stratégie OTP**
   (capacité testable + envoi différé + gating non bloquant recommandés), normalisation téléphone,
   chemin d'API, session sync/async, no-JWT à l'inscription. Rédiger **ADR-0012** (ou note) et
   l'indexer dans `docs/adr/README.md`.
2. **Dépendances** : ajouter la lib de hachage (`argon2-cffi` ou `pwdlib[argon2]`) et, si retenu,
   `pydantic[email]`/`email-validator` à `backend/pyproject.toml`. Vérifier `pip install -e ".[dev]"`.
3. **Domaine** : créer `telephone.py` (normalisation/validation), `mot_de_passe.py` (politique),
   `otp.py` (génération/vérification pures, RNG + horloge injectés), `erreurs.py`, (optionnel)
   `utilisateur.py`. **Zéro** import framework/I/O.
4. **Ports** : créer `application/ports/depot_utilisateur.py`, `hacheur_mot_de_passe.py`,
   `expediteur_otp.py`, (si OTP persisté) `depot_otp.py` (`typing.Protocol`).
5. **Cas d'usage** : `application/inscription.py` — `InscrireClient` orchestrant validation →
   normalisation → pré-check doublon → hachage → persistance (avec fallback `IntegrityError`) → OTP
   optionnel ; retourne l'entité sans secret.
6. **Adapters sortants** : `persistance/depot_utilisateur.py` (SQLAlchemy `User`),
   `securite/hacheur.py` (argon2), `notifications/expediteur_otp_stub.py` (no-op, aucun log), (si OTP
   persisté) `securite/otp_memoire.py`. Modifier `persistance/session.py` (`sessionmaker` +
   `get_session`).
7. **Adapter entrant** : `adapters/entrant/auth.py` — schémas Pydantic (requête/réponse **sans**
   secret) + route `POST /auth/register` ; mapping erreurs domaine → `409`/`422` ; DI via `Depends`.
8. **Composition root** : câbler le router `auth` et l'injection des adapters dans `main.py` ; lire
   `OTP_ENABLED` et paramètres depuis l'env.
9. **Config** : mettre à jour `backend/.env.example` (`OTP_ENABLED`, params OTP/argon2 ; `JWT_SECRET`
   inutilisé par #8).
10. **Tests** : ajouter les tests unitaires (téléphone, mot de passe, OTP, hacheur, cas d'usage avec
    fakes), API (`TestClient` : 201/409/422 + non-fuite), et intégration Postgres (**skip si pas de
    DSN** : persistance + `uq_users_phone`). Garder les suites existantes vertes.
11. **Documentation** : `backend/README.md` (endpoint + config + rappels sécurité) ; vérifier
    l'OpenAPI ; ADR indexé.
12. **Garde-fous** : confirmer qu'**aucun secret/PII/OTP/mot de passe** n'est journalisé ou renvoyé,
    qu'aucune valeur réelle n'est committée (seulement `.env.example`), que le domaine n'importe pas
    SQLAlchemy/FastAPI (ADR-0008), et qu'**aucune signature IA** n'est présente dans code/commits/PR.
13. **Sanity** : `pytest` vert (unitaires + API sans base ; intégration si DSN dispo), `ruff check`
    propre, `pip install -e .` OK.
