# Connexion (téléphone/email + mot de passe, JWT + refresh, anti-bruteforce)

> Spécification de planification pour l'issue GitHub **#10 — US-1.2 · Connexion (téléphone/email +
> mot de passe, JWT)** (`feature` `security` · Must · Effort S · PRD §6 Épic 1, §11.1).
> **Dépend de #8** (US-1.1 — inscription client : ports/adapters d'auth, hachage argon2, table
> `users` peuplée). Réutilise aussi les patterns de #9 (inscription gérant).
> **Cette spec ne produit pas de code.** Elle décrit l'API de connexion et de rafraîchissement de
> jeton, l'anti-bruteforce, les ports/adapters à ajouter et les contraintes de sécurité, à
> implémenter dans une phase ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, commentaires). Les
> en-têtes de section ci-dessous sont conservés en anglais car attendus par le gabarit du pipeline
> ADW ; le contenu reste en français, hors identifiants techniques (noms de tables/colonnes, routes,
> enums, symboles de code).

## Problem Statement

L'inscription (#8/#9) crée des comptes mais **n'émet aucun jeton** : un utilisateur inscrit ne peut
donc pas encore *ouvrir une session* ni accéder à une ressource protégée. Le PRD (§6, US-1.2 ;
§11.1) exige une **connexion émettant un JWT** accompagné d'un **refresh token sécurisé**, et une
**protection contre les tentatives répétées** (anti-bruteforce). Les critères d'acceptation de #10
sont :

- **une connexion valide émet un JWT** ; **des identifiants invalides sont refusés** ;
- **rate-limit sur les échecs de connexion**.

État actuel du dépôt (post-#8/#9, vérifié dans `backend/coiflink_api/`) :

- La couche d'auth existe côté **inscription uniquement** : router `POST /auth/register` et
  `POST /auth/register/manager` (`adapters/inbound/auth.py`), cas d'usage `RegisterUser`
  (`application/registration.py`), ports `UserRepository` / `PasswordHasher` / `OtpRepository` /
  `OtpSender`, adapters `SqlUserRepository`, `Argon2Hasher`, stubs OTP.
- **Aucune capacité de connexion** : pas de vérification de mot de passe à l'entrée HTTP, **aucune
  émission de JWT**, **aucun refresh token**, **aucun anti-bruteforce**. Le port `UserRepository`
  n'expose que `phone_exists()` et `create()` — **pas de recherche d'un utilisateur par identifiant**,
  et l'entité de domaine `User` **exclut volontairement** `password_hash` (aucun moyen actuel de
  récupérer le condensat pour le vérifier).
- Le port `PasswordHasher` expose déjà `verify(plain, hashed) -> bool` (implémenté par
  `Argon2Hasher`) — **la brique de vérification existe**, elle n'est simplement pas appelée.
- La configuration (`config.py`, `.env.example`) prévoit `JWT_SECRET` (**laissé vide**, annoté
  « requis dès l'émission de jetons, issue #10 ») ; **aucune bibliothèque JWT** n'est encore
  déclarée dans `pyproject.toml`.
- **Redis 7** est provisionné dans l'infra (`deploy/`, ADR-0004) mais **non câblé** au code ; l'OTP
  et (par cohérence) l'anti-bruteforce peuvent démarrer en **mémoire** et migrer vers Redis plus tard.

Le besoin de #10 : **livrer l'API de connexion de bout en bout côté backend** — (1) authentifier par
**téléphone ou e-mail + mot de passe**, (2) **émettre un JWT d'accès + un refresh token** à la
connexion valide, (3) **refuser** proprement des identifiants invalides sans divulguer lequel est
faux, (4) **limiter les tentatives répétées** (rate-limit sur les échecs), et (5) permettre de
**rafraîchir** le jeton d'accès. #10 introduit les patterns de jeton réutilisés par le RBAC (#12,
routes protégées) et la réinitialisation de mot de passe (#11).

## Goals

- **Endpoint de connexion** : `POST /auth/login` acceptant un **identifiant** (téléphone **ou**
  e-mail) + mot de passe ; en cas de succès, émet un **JWT d'accès** (courte durée) et un **refresh
  token** (longue durée) ; sinon renvoie `401` **générique**.
- **Émission de JWT signé** derrière un **port** (`TokenService`) implémenté par un adapter sortant
  (bibliothèque JWT à acter — recommandé **PyJWT**, algorithme symétrique **HS256** avec `JWT_SECRET`).
  Claims minimaux : `sub` (id utilisateur), `role`, `type` (`access`/`refresh`), `iat`, `exp`, `jti`.
- **Refresh token sécurisé** : endpoint `POST /auth/refresh` échangeant un refresh valide contre un
  **nouveau** jeton d'accès (et, recommandé, un refresh **rotaté**). Refus d'un refresh
  expiré/altéré/de mauvais `type`.
- **Anti-bruteforce (rate-limit sur les échecs)** : après un seuil d'**échecs** de connexion sur une
  fenêtre glissante (par identifiant et/ou IP), les tentatives suivantes sont **bloquées** (`429 Too
  Many Requests` + `Retry-After`), derrière un **port** (`LoginRateLimiter`) implémenté d'abord **en
  mémoire** (Redis différé). Un succès **réinitialise** le compteur.
- **Refus des identifiants invalides sans énumération de comptes** : même réponse `401` et même
  message (« Identifiants invalides ») que l'utilisateur soit inconnu, le mot de passe faux, ou le
  compte non `ACTIVE` — pas de divulgation de l'existence d'un compte.
- **Respecter l'hexagonal (ADR-0008)** : domaine pur, cas d'usage `application/` dépendant de ports,
  adapters entrant (HTTP) / sortants (JWT, rate-limit, persistance) seuls à connaître le framework et
  l'I/O ; câblage dans le composition root (`main.py`).
- **Documenter l'API publique** : schémas Pydantic requête/réponse (→ OpenAPI auto-générée, ADR-0003)
  et mise à jour du `backend/README.md`.
- **Acter les décisions structurantes** (nouvel **ADR-0013**) : **bibliothèque JWT**, **stratégie de
  refresh** (rotation, révocation), **algorithme/TTL**, **stratégie d'anti-bruteforce** — ferme le
  « Suivi » d'ADR-0003 côté JWT.

## Non-Goals

- **Middleware d'autorisation / RBAC (#12)** : la **vérification** du JWT sur les routes protégées,
  le *deny-by-default* et l'isolation par salon (§11.2) relèvent de #12. #10 **émet** les jetons et
  fournit la **capacité de décodage** (port `TokenService.decode`) mais **ne protège encore aucune
  route métier** ni n'ajoute de dépendance « utilisateur courant ». *(Interface partagée à confirmer
  avec #12 — voir Open Questions.)*
- **Réinitialisation de mot de passe par OTP (#11)** : hors périmètre ; #11 réutilisera le hacheur et
  (le cas échéant) l'invalidation de sessions.
- **Déconnexion / révocation explicite (`/auth/logout`)** : la révocation d'un refresh (liste de
  déni) est un **choix ouvert** (voir Open Questions) ; par défaut, #10 peut s'en tenir à
  l'expiration + rotation. Un `/auth/logout` complet peut être différé.
- **Vérification bloquante du téléphone (gating OTP)** : ADR-0012 a acté un OTP **non bloquant** ; le
  compte est `ACTIVE` dès l'inscription. #10 **n'exige pas** de téléphone vérifié pour se connecter.
- **Journalisation d'audit structurée des connexions (§11.4)** : l'audit (« Connexion » listée en
  §11.4) est un item transverse (M6) ; #10 se contente de **ne jamais journaliser** de secret/PII et
  peut émettre des logs **non sensibles** (voir Security).
- **UI mobile Flutter / web Next.js de connexion** (§7.1) : les paquets front sont des squelettes ;
  le câblage des écrans est un travail distinct. #10 se concentre sur l'**API backend** (tous les
  critères d'acceptation sont vérifiables côté backend). *À confirmer — voir Open Questions.*
- **Adapter Redis de l'anti-bruteforce / du store de refresh** : cohérent avec #8 (OTP en mémoire),
  l'implémentation concrète Redis est **différée** ; #10 livre un adapter **en mémoire** + le port.
- **Multi-appareils / gestion de sessions avancée, MFA, verrouillage progressif (captcha)** : hors
  MVP.

## Relevant Repository Context

- **Statut** : greenfield outillé ; socle M0 livré (#1–#6) ; **#8 (inscription client)** et **#9
  (inscription gérant)** livrés. #10 est la **3ᵉ feature M1** et la **première à émettre des jetons**.
- **Stack figée (ADR)** :
  - Backend **FastAPI** · Python **≥ 3.12** · API REST + **JWT** (ADR-0003). OpenAPI auto-générée à
    partir des modèles Pydantic. Le « Suivi » d'ADR-0003 renvoie explicitement le **choix de la
    bibliothèque JWT à M1** — **#10 doit l'acter**.
  - Persistance **SQLAlchemy 2.0 + Alembic + psycopg 3**, **PostgreSQL 16** (ADR-0009). Session
    **synchrone** request-scoped déjà câblée (`get_session`, commit/rollback encadrés).
  - **Redis 7** (ADR-0004) présent dans l'infra, **non câblé** au code (candidat pour l'anti-bruteforce
    et un store de refresh partagés/persistants — **différé**).
  - **Architecture hexagonale** (ADR-0008) : dépendance toujours vers l'intérieur ; toute brique
    externe passe par un **port + un adapter sortant** ; le domaine n'importe jamais FastAPI/SQLAlchemy.
  - **Hachage argon2id** acté par **ADR-0012** ; le port `PasswordHasher.verify` est déjà disponible.
- **Sécurité ancrée (PRD §11.1 ; ADR-0003 « Conséquences »)** — à livrer par #10 : **JWT + refresh
  token sécurisés**, **protection anti-bruteforce sur les connexions**. §12.1 impose un budget API
  **< 3 s** (la vérification argon2 reste sous ce budget).
- **Table `users` (livrée par #3)** — `adapters/outbound/persistence/models.py` : `phone`
  `String(32)` **unique** (`uq_users_phone`), `email` `String(255)` nullable **unique partiel**
  (`uq_users_email`, `WHERE email IS NOT NULL`), `password_hash` `NOT NULL`, `role`/`status`
  (`CHECK` dérivé de `domain/enums.py` : `Role` {CLIENT, HAIRDRESSER, MANAGER, ADMIN},
  `UserStatus` {ACTIVE, INACTIVE, SUSPENDED}). **Tout est déjà présent pour authentifier ;
  aucune évolution de schéma n'est requise pour la connexion de base.**
- **Patterns d'auth posés par #8/#9 (à réutiliser tels quels)** :
  - Router `/auth` (`APIRouter(prefix="/auth", tags=["auth"])`) dans `adapters/inbound/auth.py` —
    **#10 y ajoute** `POST /auth/login` et `POST /auth/refresh`.
  - Cas d'usage assemblé par **injection de dépendances FastAPI** (`Depends`), erreurs de domaine
    **neutres** traduites en HTTP à l'entrée (`PhoneAlreadyInUse → 409`, `Invalid* → 422`).
  - Ports = `typing.Protocol` (`application/ports/`) ; adapters sortants = seuls à connaître
    l'I/O/framework ; entités de domaine `dataclass` **sans secret** (`User` n'expose pas le hash).
  - `AuthConfig` (`config.py`) lue **depuis l'environnement** via `load_auth_config`, déposée sur
    `app.state`, relue à l'injection ; RNG/horloge **injectables** (patron déjà présent pour l'OTP).
  - Adapters singletons (`otp_sender`, `otp_repository`) posés sur `app.state` par `main.py` —
    **même mécanisme** pour le `TokenService` et le `LoginRateLimiter`.
- **Config / secrets (ADR-0011)** : tout réglage lu **depuis l'environnement** ; **aucun secret
  committé** (seulement `.env.example`). `JWT_SECRET` est un **secret** (staging/prod, magasin de la
  plateforme) — **utilisé pour la première fois par #10**.
- **Conventions** : Conventional Commits ; **aucune signature IA** dans code/commits/PR ; specs à
  en-têtes anglais / contenu français ; lint `ruff check` (`F`, `E4/E7/E9`, `B`, `W`, ligne 100) ;
  test gate `pytest` (#6) — les suites existantes doivent **rester vertes**.

## Proposed Implementation

> Approche recommandée pour un agent d'implémentation. Les points marqués *(à confirmer)* renvoient à
> *Risks and Open Questions*. Un fil directeur : **calquer** l'inscription (#8/#9) — mêmes couches,
> mêmes conventions d'injection et de traduction d'erreurs.

### 1. Domaine (`coiflink_api/domain/`) — pur, sans dépendance framework/I/O

- **`credentials.py`** *(ou extension de `user.py`)* — nouvelle `dataclass` **interne**
  `UserCredentials` (ou `StoredUser`) portant `id`, `role`, `status`, **`password_hash`**. *Rationale*
  : l'entité `User` exclut volontairement le condensat (jamais renvoyé) ; la connexion a besoin du
  condensat pour `verify`. Cette dataclass **n'est jamais** sérialisée en réponse HTTP. Prévoir une
  conversion `UserCredentials → User` (drop du hash) pour la réponse éventuelle.
- **`identifier.py`** *(léger)* — classement d'un identifiant de connexion : contient `@` → e-mail
  (normalisé : `strip`, **casse à confirmer** — voir Open Questions) ; sinon → téléphone, **normalisé
  via `normalize_phone`** (réutilise `domain/phone.py`, garantit que `0700…` et `+2250700…` visent le
  **même** compte). *Rationale* : sans normalisation cohérente entre inscription et connexion, un
  numéro valide échouerait à s'authentifier.
- **`errors.py` (modifier)** — ajouter des erreurs **neutres** : `InvalidCredentials` (identifiant
  inconnu **ou** mot de passe faux **ou** compte non `ACTIVE` — **volontairement indistinctes** pour
  l'anti-énumération), `TooManyLoginAttempts` (anti-bruteforce ; peut porter un `retry_after`),
  `InvalidToken` / `ExpiredToken` (refresh). Aucune ne transporte de secret/PII.
- **`tokens.py`** *(optionnel, valeurs pures)* — types de domaine décrivant un jeu de jetons émis
  (`TokenPair` : `access_token`, `refresh_token`, `token_type="bearer"`, `expires_in`) et les
  **claims** attendus (`sub`, `role`, `type`, `exp`, `iat`, `jti`) **sans** logique de signature (la
  signature est un adapter). Garde le domaine agnostique de la lib JWT.

### 2. Application (`coiflink_api/application/` + `ports/`) — cas d'usage + interfaces

Ports (`application/ports/`, `typing.Protocol`) :

- **`user_repository.py` (modifier)** — ajouter au port `UserRepository` :
  `find_by_phone(phone) -> UserCredentials | None` et `find_by_email(email) -> UserCredentials | None`
  (ou un unique `find_by_identifier`). Retourne l'entité **porteuse du condensat** (nécessaire à la
  vérification) ou `None`.
- **`token_service.py` (nouveau)** — `TokenService` :
  `issue_pair(user_id, role) -> TokenPair`, `decode(token) -> Claims` (lève `InvalidToken`/
  `ExpiredToken`), `verify_refresh(token) -> Claims` (vérifie `type == "refresh"`). Implémenté par un
  adapter sortant JWT.
- **`login_rate_limiter.py` (nouveau)** — `LoginRateLimiter` : `check(key) -> None` (lève
  `TooManyLoginAttempts` si verrouillé), `record_failure(key) -> None`, `reset(key) -> None`.
  Injecte l'horloge. Implémenté d'abord en mémoire (fenêtre glissante / compteur + verrou temporisé).

Cas d'usage (`application/authentication.py`) :

- **`AuthenticateUser`** (`execute(command: LoginCommand) -> TokenPair`) :
  1. classer/normaliser l'identifiant (domaine) → clé de rate-limit (identifiant normalisé ± IP) ;
  2. **`rate_limiter.check(key)`** → `TooManyLoginAttempts` si verrouillé (**avant** tout accès base) ;
  3. **rechercher** l'utilisateur (`find_by_phone`/`find_by_email`) ;
  4. **vérifier** le mot de passe (`PasswordHasher.verify`) **et** le statut `ACTIVE`. En cas
     d'utilisateur introuvable, exécuter une vérification **factice** contre un condensat *dummy*
     (atténuation d'oracle temporel — voir Security), puis lever `InvalidCredentials` ;
  5. **échec** → `rate_limiter.record_failure(key)` puis lever `InvalidCredentials` ;
  6. **succès** → `rate_limiter.reset(key)`, émettre la paire de jetons
     (`token_service.issue_pair`), retourner `TokenPair`.
- **`RefreshTokens`** (`execute(refresh_token) -> TokenPair`) : `token_service.verify_refresh` →
  (recommandé) recharger l'utilisateur pour re-lire `role`/`status` courants et **rejeter** un compte
  devenu non `ACTIVE` ; émettre une **nouvelle** paire (rotation) ; *(si révocation retenue)*
  invalider l'ancien `jti` et détecter la réutilisation. Lève `InvalidToken`/`ExpiredToken`.

Le mot de passe en clair ne vit que le temps de `verify()` ; **jamais** journalisé/retourné.

### 3. Adapters sortants (`coiflink_api/adapters/outbound/`)

- **`security/jwt_token_service.py` (nouveau)** — implémente `TokenService` avec la lib JWT
  **(recommandé PyJWT)**. Signe en **HS256** avec `JWT_SECRET` ; pose `sub`, `role`, `type`, `iat`,
  `exp` (TTL access court, refresh long), `jti` (UUID). `decode` vérifie signature + `exp` et mappe
  les exceptions lib → `InvalidToken`/`ExpiredToken` (**aucune fuite** de détail lib). Secret/algo/TTL
  injectés (issus de la config).
- **`security/login_rate_limiter_memory.py` (nouveau)** — implémente `LoginRateLimiter` en **mémoire**
  (dict `key -> (compteur, fenêtre, verrou_jusqu'à)`), horloge injectée, purge paresseuse. Suffisant
  pour dev/test ; adapter **Redis à TTL différé** (note ADR-0013). *(Limite connue : non partagé entre
  workers — acceptable au MVP, cf. OTP.)*
- **`persistence/user_repository.py` (modifier)** — implémenter `find_by_phone`/`find_by_email` :
  `SELECT` sur `models.User` filtré par `phone` (resp. `email`), mappé en `UserCredentials` (avec
  `password_hash`), `None` si absent. Ne journalise ni le condensat ni le numéro.

### 4. Adapter entrant (`coiflink_api/adapters/inbound/auth.py` — modifier)

- **Schémas Pydantic** (documentation OpenAPI) :
  - `LoginRequest` : `identifier: str` (téléphone **ou** e-mail), `password: str` (jamais renvoyé/
    logué). *(Alternative : deux champs `phone`/`email` exclusifs — à confirmer.)*
  - `TokenResponse` : `access_token: str`, `refresh_token: str`, `token_type: "bearer"`,
    `expires_in: int` (secondes). **Aucun** champ secret côté serveur (le `JWT_SECRET` n'apparaît
    jamais).
  - `RefreshRequest` : `refresh_token: str`.
- **`POST /auth/login`** → assemble `AuthenticateUser` par `Depends` (session + `PasswordHasher` +
  `TokenService` + `LoginRateLimiter` depuis `app.state`), passe l'IP client (`request.client.host`)
  à la clé de rate-limit *(à confirmer : IP + identifiant vs identifiant seul)*, exécute, traduit :
  `InvalidCredentials → 401` (message générique) ; `TooManyLoginAttempts → 429` (+ en-tête
  `Retry-After`). **`200 OK`** + `TokenResponse` en cas de succès.
- **`POST /auth/refresh`** → assemble `RefreshTokens`, exécute, traduit :
  `InvalidToken`/`ExpiredToken → 401`. **`200 OK`** + `TokenResponse`.
- Réutilise le patron d'assemblage `_build_*` / `Depends` de #8/#9 ; **aucune** règle métier dans le
  router.

### 5. Configuration (`config.py` — modifier) & composition root (`main.py` — modifier)

- **`config.py`** : ajouter un `JwtConfig`/étendre `AuthConfig` avec `jwt_secret` (lu de
  `JWT_SECRET`, **secret**), `jwt_algorithm` (défaut `HS256`), `access_ttl` (défaut ~15 min),
  `refresh_ttl` (défaut ~30 j), et les paramètres d'anti-bruteforce (`login_max_attempts` défaut ~5,
  `login_window_seconds` défaut ~300, `login_lockout_seconds` défaut ~900). Le secret **n'a pas de
  défaut** ; prévoir une **validation** (fail-fast clair à l'assemblage du `TokenService` si
  `JWT_SECRET` absent — sans casser `GET /health`). *(à confirmer : moment exact de la validation.)*
- **`main.py`** : instancier `JwtTokenService(config)` et `InMemoryLoginRateLimiter(clock)` et les
  déposer sur `app.state` (comme `otp_sender`/`otp_repository`) ; le router `auth` les relit. **Aucune
  règle métier** — assemblage uniquement.

## Affected Files / Packages / Modules

**Paquet concerné : `backend/` uniquement** (front hors périmètre — voir Non-Goals).

**À créer :**
- `coiflink_api/domain/credentials.py` (ou extension de `domain/user.py`) — `UserCredentials`.
- `coiflink_api/domain/identifier.py` — classement/normalisation identifiant (téléphone/e-mail).
- `coiflink_api/domain/tokens.py` *(optionnel)* — `TokenPair`, description des claims.
- `coiflink_api/application/authentication.py` — `LoginCommand`, `AuthenticateUser`, `RefreshTokens`.
- `coiflink_api/application/ports/token_service.py` — port `TokenService`.
- `coiflink_api/application/ports/login_rate_limiter.py` — port `LoginRateLimiter`.
- `coiflink_api/adapters/outbound/security/jwt_token_service.py` — adapter JWT (PyJWT).
- `coiflink_api/adapters/outbound/security/login_rate_limiter_memory.py` — anti-bruteforce en mémoire.
- Tests : `tests/test_identifier.py`, `tests/test_jwt_token_service.py`,
  `tests/test_login_rate_limiter.py`, `tests/test_authentication_usecase.py`,
  `tests/test_login_api.py`, `tests/test_refresh_api.py`, (intégration Postgres, skip si pas de DSN)
  `tests/test_login_integration.py`.

**À modifier :**
- `coiflink_api/domain/errors.py` — `InvalidCredentials`, `TooManyLoginAttempts`, `InvalidToken`,
  `ExpiredToken`.
- `coiflink_api/application/ports/user_repository.py` — `find_by_phone` / `find_by_email`.
- `coiflink_api/adapters/outbound/persistence/user_repository.py` — implémentation des recherches.
- `coiflink_api/adapters/inbound/auth.py` — routes `POST /auth/login` + `POST /auth/refresh`,
  schémas Pydantic, mapping erreurs → `401`/`429`, DI.
- `coiflink_api/config.py` — `jwt_secret`, algo, TTL access/refresh, paramètres anti-bruteforce.
- `coiflink_api/main.py` — câblage `TokenService` + `LoginRateLimiter` sur `app.state`.
- `backend/pyproject.toml` — ajouter la **lib JWT** (recommandé `pyjwt>=2.8`).
- `backend/.env.example` — `JWT_SECRET` (secret, désormais **requis** pour la connexion), TTL access/
  refresh, paramètres d'anti-bruteforce ; algorithme.
- `backend/README.md` — table des endpoints (`POST /auth/login`, `POST /auth/refresh`) + section
  connexion/JWT/anti-bruteforce ; rappel « mot de passe/jeton jamais journalisés ».
- `docs/adr/` — **ADR-0013** (JWT lib + stratégie refresh + anti-bruteforce), indexé dans
  `docs/adr/README.md` ; ferme le « Suivi » d'ADR-0003 côté JWT.

**À lire (contexte) :** `prd-coiflink.md` (§6, §11.1, §12.1), `docs/adr/0003`, `0004`, `0008`, `0011`,
`0012`, `specs/inscription-client-telephone-mot-de-passe.md`,
`specs/inscription-gerant-compte-proprietaire.md`, et sous `backend/coiflink_api/` :
`adapters/inbound/auth.py`, `application/registration.py`, `application/ports/*.py`,
`adapters/outbound/persistence/{user_repository,models,session}.py`,
`adapters/outbound/security/argon2_hasher.py`, `domain/{user,phone,password,errors,enums}.py`,
`config.py`, `main.py`, `backend/README.md`.

## API / Interface Changes

**Nouveaux endpoints HTTP publics (à documenter — OpenAPI auto-générée, ADR-0003) :**

- **`POST /auth/login`**
  - **Corps (JSON)** : `identifier` (string, requis — téléphone **ou** e-mail), `password` (string,
    requis). *(Forme du champ à confirmer : `identifier` unique vs `phone`/`email`.)*
  - **`200 OK`** : `{ access_token, refresh_token, token_type: "bearer", expires_in }`.
  - **`401 Unauthorized`** : identifiants invalides — **message générique**, identique quel que soit
    le motif (inconnu / mot de passe faux / compte non `ACTIVE`).
  - **`429 Too Many Requests`** : trop d'échecs (anti-bruteforce) ; en-tête **`Retry-After`**.
  - **`422 Unprocessable Entity`** : corps malformé (champ manquant, types).
- **`POST /auth/refresh`**
  - **Corps (JSON)** : `refresh_token` (string, requis).
  - **`200 OK`** : nouvelle paire (rotation recommandée) — même schéma `TokenResponse`.
  - **`401 Unauthorized`** : refresh invalide/expiré/altéré/de mauvais `type` — message générique.
- *(optionnel, différé)* **`POST /auth/logout`** : révoque un refresh (si liste de déni retenue) —
  voir Open Questions.

**Jeton d'accès (contrat pour #12)** : JWT signé (HS256 par défaut) ; claims `sub` (id utilisateur),
`role`, `type=access`, `iat`, `exp`, `jti`. Le format des claims est un **contrat inter-issue** : à
**figer avec #12** (le middleware RBAC consommera ces claims). Schéma d'auth : **Bearer** (en-tête
`Authorization: Bearer <token>`).

**Endpoints existants inchangés** : `GET /health`, `POST /auth/register`, `POST /auth/register/manager`.
**CLI / autres interfaces réseau : none.**

## Data Model / Protocol Changes

- **Connexion de base : none.** La table `users` (#3) porte `phone` (unique), `email` (unique
  partiel), `password_hash`, `role`, `status` — suffisant pour authentifier. **Aucune migration** pour
  la connexion, l'émission de JWT ni l'anti-bruteforce en mémoire.
- **Anti-bruteforce** : compteurs d'échecs **hors schéma** (adapter **en mémoire** ; Redis à TTL
  **différé**) → **aucune migration**.
- **Refresh token / révocation — dépend de la stratégie retenue** :
  - **Recommandé (#10)** : refresh **stateless** = JWT signé (`type=refresh`, `jti`, `exp`) **+
    rotation** ; aucune persistance → **aucune migration**.
  - **Si révocation/liste de déni serveur** (logout, détection de réutilisation) : nécessiterait un
    **store de `jti` révoqués** (adapter **en mémoire**/Redis → aucune migration ; **ou** table
    `refresh_tokens` → **migration Alembic** `0002_*` + modèle ORM). **Non retenu par défaut** (voir
    Open Questions).
- **Sérialisation** : nouveaux schémas **Pydantic** (`LoginRequest`, `RefreshRequest`,
  `TokenResponse`) côté adapter entrant — **ne modifient pas** le schéma relationnel. Le contenu des
  **claims JWT** est un format de protocole à documenter dans l'ADR-0013.

## Security & Privacy Considerations

- **Mot de passe (§11.1)** : vérifié via `PasswordHasher.verify` (argon2id, ADR-0012) ; **jamais** en
  clair au repos, **jamais** journalisé ni renvoyé. Le clair ne vit que le temps de l'appel.
- **Anti-énumération de comptes** : réponse `401` **générique et uniforme** (utilisateur inconnu, mot
  de passe faux, compte non `ACTIVE` → même statut, même message). **Atténuation d'oracle temporel** :
  quand l'utilisateur est introuvable, exécuter une vérification argon2 **factice** contre un condensat
  *dummy* pré-calculé, pour égaliser grossièrement le temps de réponse. *(Rigueur constant-time non
  garantie ; documenter la limite.)*
- **Anti-bruteforce (§11.1, critère d'acceptation)** : rate-limit sur les **échecs** (seuil + fenêtre
  glissante), verrou temporisé (`429` + `Retry-After`), **réinitialisé au succès**. Clé recommandée :
  **identifiant normalisé + IP** *(à confirmer)*, en tenant compte des proxys (IP réelle derrière
  Railway — **à confirmer** : `X-Forwarded-For` de confiance). Éviter qu'un attaquant verrouille le
  compte d'un tiers (préférer un blocage combiné IP+identifiant plutôt qu'identifiant seul, ou une
  temporisation plutôt qu'un verrou dur) — **compromis à acter**.
- **JWT / secret (ADR-0011)** : `JWT_SECRET` est un **secret** lu **depuis l'environnement**, **jamais
  committé** ni journalisé ; forte entropie exigée en staging/prod (magasin de la plateforme). Access
  token **court** (limite la fenêtre de vol) ; refresh **long** mais **rotaté** (et, si retenu,
  révocable). Claims **minimaux** : `sub`, `role`, `type`, `exp`, `iat`, `jti` — **aucune PII** (ni
  téléphone, ni e-mail, ni nom) dans le jeton. Algorithme **fixé côté serveur** (HS256) et `decode`
  qui **impose** l'algo attendu (rejeter `alg=none` et la confusion d'algorithme).
- **PII (§11.3)** : `phone`/`email`/`full_name` sont des données personnelles → **jamais**
  journalisées. Les logs de connexion (si présents) restent **non sensibles** (pas d'identifiant en
  clair, pas de jeton) — l'audit structuré (§11.4) est différé (M6).
- **Statut de compte** : seuls les comptes `ACTIVE` peuvent se connecter ; `INACTIVE`/`SUSPENDED`
  refusés via le **même** `401` générique (pas de divulgation de l'état du compte).
- **Résidence / budgets** : budget API **< 3 s** (§12.1) — argon2 (coût par défaut) + signature JWT
  restent bien en dessous. Pas de contrainte de résidence au niveau feature (hébergement `europe-west4`
  géré par ADR-0011).
- **Transport** : jetons **Bearer** — l'exposition suppose **HTTPS** (terminaison TLS Railway,
  ADR-0011) ; #10 ne gère pas la terminaison TLS.

## Testing Plan

Test gate : **`pytest`** (ADR-0003 ; agrégé `MX_AGENT_TEST_CMD`, #6). Les suites existantes
(`test_auth_api`, `test_manager_auth_api`, `test_registration_usecase`, `test_health`, `test_session`,
`test_secrets_policy`, `test_config`, …) doivent **rester vertes** ; `ruff check` doit passer.

- **Unitaires (sans base, rapides)** :
  - `identifier` : `@` → e-mail (normalisé) ; sinon téléphone **via `normalize_phone`** (`0700…` et
    `+2250700…` → **même** clé) ; rejet des entrées vides/malformées.
  - `jwt_token_service` : `issue_pair` produit access+refresh distincts, claims corrects (`sub`,
    `role`, `type`, `jti`, `exp` cohérent avec le TTL) ; `decode` accepte un jeton valide, **rejette**
    signature invalide / expiré (horloge injectée) / `alg` inattendu / `type` erroné pour refresh.
  - `login_rate_limiter` : sous le seuil → passe ; au seuil → `TooManyLoginAttempts` (horloge
    injectée) ; **expiration** de la fenêtre → de nouveau autorisé ; **`reset` au succès** ré-autorise.
  - `AuthenticateUser` (ports **fakes**) : succès (bon mot de passe → `TokenPair`, compteur
    **reset**) ; mauvais mot de passe → `InvalidCredentials` + `record_failure` ; utilisateur
    introuvable → `InvalidCredentials` (**et** `verify` factice appelé) ; compte non `ACTIVE` →
    `InvalidCredentials` ; verrou actif → `TooManyLoginAttempts` **avant** accès base ; connexion par
    **téléphone** et par **e-mail** toutes deux fonctionnelles.
  - `RefreshTokens` : refresh valide → nouvelle paire (rotation) ; refresh expiré/altéré/`type=access`
    → `InvalidToken`/`ExpiredToken` ; compte devenu non `ACTIVE` → refus *(si re-check retenu)*.
- **API (FastAPI `TestClient`/`httpx`, ports fakes, sans base réelle)** :
  - `POST /auth/login` valides → **`200`** + `{access_token, refresh_token, token_type, expires_in}` ;
  - identifiants invalides → **`401`** générique (mêmes statut/corps pour inconnu vs mauvais mot de
    passe vs compte inactif — **assertion d'indistinguabilité**) ;
  - au-delà du seuil d'échecs → **`429`** + en-tête `Retry-After` ;
  - `POST /auth/refresh` valide → **`200`** + nouvelle paire ; refresh invalide → **`401`** ;
  - **assertion de non-fuite** : réponses **et** logs capturés ne contiennent **jamais** mot de
    passe / `JWT_SECRET` / condensat (le jeton signé est attendu dans la réponse, pas le secret).
- **Intégration (PostgreSQL 16, skip propre si pas de `DATABASE_URL`)** — patron
  `test_manager_registration_integration` :
  - inscrire (réutiliser `RegisterUser`) puis **se connecter** par téléphone **et** par e-mail → `200`
    + jeton décodable ; mauvais mot de passe → `401` ; connexion sur compte passé `INACTIVE` → `401`.
- **Résilience / sécurité** : le rate-limit borne effectivement des échecs répétés (`429`) ; un succès
  après quelques échecs (sous le seuil) réinitialise le compteur ; un jeton **falsifié** (mauvais
  secret) est rejeté.
- **Documentation** : vérifier (revue) que `backend/README.md` documente `POST /auth/login` et
  `POST /auth/refresh` et que l'OpenAPI expose les endpoints avec des schémas **sans secret**.

## Documentation Updates

- **`backend/README.md`** : ajouter `POST /auth/login` et `POST /auth/refresh` à la table des
  endpoints ; section « Connexion / JWT » (identifiant téléphone **ou** e-mail, émission access +
  refresh, rotation, anti-bruteforce `429`/`Retry-After`, schéma **Bearer**) ; rappel sécurité « mot
  de passe / jeton / secret jamais journalisés » et `401` **générique** anti-énumération.
- **`backend/.env.example`** : documenter `JWT_SECRET` (**secret**, désormais requis pour la
  connexion — retirer la mention « laissé vide / non utilisé par #8 »), `JWT_ALGORITHM` (défaut
  `HS256`), `JWT_ACCESS_TTL_SECONDS` / `JWT_REFRESH_TTL_SECONDS`, et les paramètres d'anti-bruteforce
  (`LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`, `LOGIN_LOCKOUT_SECONDS`). **Aucune valeur réelle** ;
  rappeler que le secret vit hors dépôt (ADR-0011).
- **`docs/adr/0013-*.md` (nouveau)** : acter **bibliothèque JWT** (recommandé PyJWT), **algorithme**
  (HS256) & **TTL**, **stratégie de refresh** (rotation ; révocation retenue ou différée),
  **stratégie d'anti-bruteforce** (clé, seuils, verrou, store en mémoire → Redis différé). Ferme le
  « Suivi » d'ADR-0003 côté JWT ; entrée dans `docs/adr/README.md` (mettre à jour l'index/état).
- **OpenAPI** : auto-générée par FastAPI (aucune rédaction manuelle) ; s'assurer que les schémas
  **excluent** tout champ sensible et documentent le schéma d'auth Bearer.
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).

## Risks and Open Questions

- **Bibliothèque & algorithme JWT** *(à acter — ADR-0013)* : **PyJWT** (simple, bien maintenu ;
  recommandé) vs `python-jose` (plus large, JOSE complet) vs `authlib`. **HS256** (secret symétrique,
  simple pour un monolithe ; recommandé) vs **RS256** (asymétrique, utile si la vérification est
  distribuée à d'autres services — non nécessaire au MVP). Décision réutilisée par #12 (vérification).
- **Stratégie de refresh & révocation** *(à acter)* : (a) refresh **stateless** signé + **rotation**,
  sans persistance (recommandé #10, aucune migration) ; vs (b) **révocation serveur** (logout,
  détection de réutilisation) via store de `jti` (**mémoire/Redis** = aucune migration ; **table
  `refresh_tokens`** = migration). La rotation seule ne permet pas la déconnexion immédiate côté
  serveur — compromis à trancher.
- **Forme de l'identifiant** *(à confirmer)* : champ **unique `identifier`** (auto-détection
  e-mail/téléphone ; recommandé, plus proche de l'UX « téléphone **ou** e-mail ») vs deux champs
  exclusifs `phone`/`email`.
- **Normalisation de l'e-mail** *(à confirmer)* : l'inscription (#8) **ne met pas** l'e-mail en
  minuscules avant stockage ; une connexion insensible à la casse exigerait de **normaliser à
  l'inscription et à la connexion** de façon cohérente (sinon un e-mail en casse différente échouerait,
  ou un doublon insensible à la casse passerait). Décider d'une politique commune (probable
  `strip` + `lower`) — **impacte #8/#9** (petit ajustement) et l'unicité de l'e-mail.
- **Clé & politique d'anti-bruteforce** *(à confirmer)* : identifiant seul (risque de verrouillage
  d'un tiers) vs **IP + identifiant** (recommandé) vs IP seule ; verrou dur vs temporisation
  progressive. Fiabilité de l'IP derrière le proxy Railway (`X-Forwarded-For` de confiance) — **à
  valider**. Seuils par défaut (ex. 5 échecs / 5 min → verrou 15 min) à confirmer.
- **Emplacement du store anti-bruteforce/refresh** *(à confirmer)* : **mémoire** (recommandé #10,
  cohérent avec l'OTP ; non partagé entre workers/instances) vs **Redis** (partagé/persistant ;
  déjà provisionné mais non câblé — câblage différé). Impacte l'efficacité réelle en multi-instances.
- **Contrat de claims partagé avec #12** *(à coordonner)* : format des claims (`sub`, `role`,
  `type`, `jti`, `exp`, `iat`) et exposition d'une capacité `decode`/« utilisateur courant » que #12
  consommera. À **figer** ici pour éviter une reprise en #12.
- **Fail-fast `JWT_SECRET`** *(à confirmer)* : valider la présence/entropie du secret **au démarrage**
  (clair mais peut gêner `GET /health` en env mal configuré) vs **à l'assemblage du `TokenService`**
  (échec seulement sur `/auth/*`). Recommandé : validation à l'usage des routes d'auth, message
  explicite, sans casser `/health`.
- **Auto-login après inscription** *(reporté de #8)* : l'inscription **n'émet pas** de jeton ; #10
  fournit désormais la connexion explicite. Décider si le front enchaîne inscription → login (UX) —
  décision produit/front, hors backend.
- **Périmètre front** *(à confirmer)* : #10 se limite-t-il à l'**API backend** (recommandé ; tous les
  critères d'acceptation sont backend) ou doit-il livrer les écrans Flutter/Next.js de connexion ?
- **`/auth/logout`** *(portée)* : livré en #10 (dépend de la révocation) ou différé — voir stratégie
  de refresh.

## Implementation Checklist

1. **Acter les décisions structurantes (ADR-0013)** : lib JWT (**PyJWT** recommandé), algorithme
   (**HS256**) & TTL (access court / refresh long), **stratégie de refresh** (rotation ; révocation
   retenue ou différée), **anti-bruteforce** (clé identifiant+IP, seuils, verrou, store mémoire →
   Redis différé). Indexer dans `docs/adr/README.md` ; noter la fermeture du « Suivi » JWT d'ADR-0003.
2. **Dépendance** : ajouter `pyjwt>=2.8` (ou lib retenue) à `backend/pyproject.toml` ; vérifier
   `pip install -e ".[dev]"`.
3. **Domaine** : `credentials.py` (`UserCredentials` avec `password_hash`), `identifier.py`
   (classement/normalisation, réutilise `normalize_phone`), `tokens.py` *(optionnel)* ; **étendre**
   `errors.py` (`InvalidCredentials`, `TooManyLoginAttempts`, `InvalidToken`, `ExpiredToken`). **Zéro**
   import framework/I/O.
4. **Ports** : étendre `UserRepository` (`find_by_phone`/`find_by_email`) ; créer
   `token_service.py` (`TokenService`) et `login_rate_limiter.py` (`LoginRateLimiter`)
   (`typing.Protocol`).
5. **Cas d'usage** : `application/authentication.py` — `AuthenticateUser` (check rate-limit →
   recherche → `verify` + statut `ACTIVE` → succès émet la paire & reset / échec `record_failure` +
   `InvalidCredentials` ; vérification **factice** si utilisateur introuvable) et `RefreshTokens`
   (verify refresh → re-check statut → nouvelle paire).
6. **Adapters sortants** : `security/jwt_token_service.py` (PyJWT, HS256, claims, mapping exceptions →
   `InvalidToken`/`ExpiredToken`) ; `security/login_rate_limiter_memory.py` (fenêtre glissante,
   horloge injectée) ; **implémenter** `find_by_phone`/`find_by_email` dans
   `persistence/user_repository.py`.
7. **Adapter entrant** : dans `adapters/inbound/auth.py`, ajouter schémas Pydantic (`LoginRequest`,
   `TokenResponse`, `RefreshRequest`) + routes `POST /auth/login` (200/401/429 + `Retry-After`) et
   `POST /auth/refresh` (200/401) ; DI via `Depends` ; passer l'IP client à la clé de rate-limit.
8. **Configuration** : étendre `config.py` (`jwt_secret` sans défaut, algo, TTL access/refresh,
   paramètres anti-bruteforce) + validation fail-fast du secret ; câbler `TokenService` et
   `LoginRateLimiter` sur `app.state` dans `main.py`.
9. **Config env** : mettre à jour `backend/.env.example` (`JWT_SECRET` requis, `JWT_ALGORITHM`, TTL,
   `LOGIN_*`) ; retirer la mention « JWT_SECRET non utilisé (#8) ».
10. **Tests** : unitaires (identifier, JWT service, rate-limiter, cas d'usage avec fakes), API
    (`TestClient` : 200/401/429 + refresh + **indistinguabilité** + non-fuite), intégration Postgres
    (**skip si pas de DSN** : inscription→login par téléphone/e-mail, mauvais mot de passe, compte
    `INACTIVE`). Garder les suites existantes vertes.
11. **Documentation** : `backend/README.md` (endpoints + section connexion/JWT/anti-bruteforce +
    rappels sécurité) ; vérifier l'OpenAPI (schémas sans secret, Bearer) ; ADR-0013 indexé.
12. **Garde-fous** : confirmer qu'**aucun secret/PII/mot de passe/jeton** n'est journalisé ; que le
    `401` reste **générique** (anti-énumération) ; qu'aucune valeur réelle n'est committée (seulement
    `.env.example`) ; que le domaine n'importe pas FastAPI/SQLAlchemy/JWT (ADR-0008) ; qu'**aucune
    signature IA** n'est présente dans code/commits/PR.
13. **Sanity** : `pytest` vert (unitaires + API sans base ; intégration si DSN dispo), `ruff check`
    propre, `pip install -e .` OK.
