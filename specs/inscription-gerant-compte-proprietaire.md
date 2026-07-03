# Inscription gérant & création du compte propriétaire

> Spécification de planification pour l'issue GitHub **#9 — Inscription gérant & création du compte
> propriétaire** (`feature` `security` · Must · Effort M · PRD §4 « Gérant », §18 Sprint 1).
> **Dépend de #3** (modèle de données & schéma PostgreSQL — table `users` et rôle `MANAGER` livrés).
> **Prérequis de #15** (US-2.1 · Création d'un salon), qui `Dépend de #9, #14`.
> **Cette spec ne produit pas de code.** Elle décrit l'ajout d'un parcours d'inscription **gérant**
> réutilisant la machinerie d'authentification déjà livrée par **#8** (US-1.1), et les contraintes de
> sécurité (notamment l'**anti-élévation de privilège**) à respecter dans une phase ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, commentaires) et le
> **code en anglais** (identifiants, modules, arborescence — cf. commit `refactor: nommage du code en
> anglais`). Les en-têtes de section ci-dessous sont conservés en anglais car attendus par le gabarit
> du pipeline ADW ; le contenu reste en français, hors identifiants techniques (tables/colonnes,
> routes, enums, symboles de code).

## Problem Statement

Le jalon M1 (Authentification) doit permettre à un **gérant** de créer son **compte propriétaire**
afin de pouvoir ensuite créer et administrer un salon. Le PRD attribue au rôle **Gérant** la capacité
de « créer un salon » (§4 « Gérant »), et §8.3 précise qu'« un gérant peut créer un ou plusieurs
salons ». La roadmap (§18 Sprint 1) liste explicitement « Inscription gérant » comme livrable, et le
backlog en fait le **prérequis de US-2.1** (#15) : sans compte de rôle `MANAGER`, la création de salon
(`salons.owner_id → users.id`) n'a pas de propriétaire à rattacher.

**Critère d'acceptation (backlog/issue) :** *un gérant crée son compte ; le rôle `Gérant` (`MANAGER`)
est attribué ; le compte est prêt à créer un salon.*

État actuel du dépôt (vérifié dans le code) :

- **#8 a livré l'ossature complète d'inscription** côté backend (`backend/`) : endpoint
  `POST /auth/register` (rôle **`CLIENT` codé en dur**), cas d'usage `RegisterClient`
  (`application/registration.py`), ports (`UserRepository`, `PasswordHasher`, `OtpSender`,
  `OtpRepository`), adapters (`SqlUserRepository`, `Argon2Hasher`, `StubOtpSender`,
  `InMemoryOtpRepository`), domaine (`phone.normalize_phone`, `password.validate_password`,
  `user.validate_name`, `otp`, `errors`) et configuration (`AuthConfig`). Voir
  [inscription-client-telephone-mot-de-passe.md](./inscription-client-telephone-mot-de-passe.md).
- **Le rôle `MANAGER` existe déjà** (`domain/enums.py` : `Role.MANAGER = "MANAGER"`) et est **déjà
  autorisé par la contrainte base** `ck_users_role` (dérivée de `enums.Role` par `enum_check`,
  `adapters/outbound/persistence/models.py`). La table `salons` (avec `owner_id → users.id`,
  `ondelete="RESTRICT"`) est **déjà présente** (#3), mais **sa création n'est pas exposée** (endpoint
  salon = #15, hors périmètre).
- **Aucun chemin d'inscription gérant n'existe** : `RegisterClient.execute` fixe
  `role=Role.CLIENT.value` sans paramètre, et l'endpoint `/auth/register` ne produit que des `CLIENT`.

Le besoin de #9 : **exposer une inscription gérant** produisant un compte `role=MANAGER`,
`status=ACTIVE`, en **réutilisant** l'ossature #8, **sans** permettre à un appelant de choisir
librement son rôle (risque d'élévation de privilège), et **sans** créer de salon (c'est #15).

## Goals

- **Parcours d'inscription gérant** produisant un utilisateur `role=MANAGER`, `status=ACTIVE`, à
  partir des mêmes entrées que le client (nom, téléphone, mot de passe, email optionnel).
- **Rôle attribué côté serveur** : le rôle `MANAGER` est déterminé par le **chemin d'inscription
  choisi** (endpoint / assemblage du cas d'usage), **jamais** par un champ de la requête → pas
  d'élévation de privilège (un client ne peut pas se déclarer `MANAGER` ni `ADMIN`).
- **Réutilisation maximale de #8 (DRY)** : mêmes hachage argon2id (ADR-0012), normalisation
  téléphone, refus de doublon (`409` + garde-fou base `uq_users_phone`/`uq_users_email`), schémas de
  requête/réponse **sans secret**, capacité OTP testable désactivée par défaut. Généraliser le cas
  d'usage plutôt que dupliquer la logique.
- **Compte « prêt à créer un salon »** : à l'issue de l'inscription, le compte porte le rôle exigé par
  #15 pour être `owner_id` d'un salon. #9 **ne crée pas** le salon et **n'émet pas** de JWT.
- **Aucune évolution de schéma** : `MANAGER` est déjà une valeur d'enum valide et déjà couverte par
  le `CHECK` base ; aucune migration Alembic n'est requise.
- **Respect de l'hexagonal (ADR-0008)** : domaine pur, cas d'usage déclarant ses besoins via ports,
  adapters seuls à connaître FastAPI/SQLAlchemy/argon2, câblage au composition root.
- **Documenter l'API publique** : nouvel endpoint dans l'OpenAPI auto-générée (ADR-0003) et
  `backend/README.md`.

## Non-Goals

- **Création du salon (US-2.1, #15)** : #9 s'arrête au **compte** de rôle `MANAGER`. L'endpoint de
  création de salon, le rattachement `owner_id` et les règles §8.3 (salon sans horaire non
  réservable) relèvent de #15 (qui dépend de #9). **Ne rien implémenter côté `salons`.**
- **Connexion & JWT (US-1.2, #10)** : l'inscription gérant **n'émet pas** de jeton. L'authentification
  du gérant sur le dashboard web, le refresh token et l'anti-bruteforce sont hors périmètre.
- **RBAC / middleware d'autorisation (#12)** : la protection des routes par rôle et l'isolation par
  salon (§11.2 « un gérant ne voit que son salon ») arrivent avec #12. #9 se limite à **attribuer** le
  rôle, pas à **contrôler** les accès protégés.
- **Création/invitation d'employés (US-1.4, #13)** : les comptes `HAIRDRESSER` sont créés par un
  gérant authentifié (dépend de #12) — hors périmètre.
- **Comptes `ADMIN`** : jamais créés par une inscription publique ; hors périmètre (approvisionnés
  hors ligne / via un futur outillage admin).
- **UI web du dashboard gérant (#14)** : l'écran d'inscription/onboarding côté `web-dashboard/`
  (squelette Next.js) est un travail front distinct. Les critères d'acceptation de #9 sont tous
  vérifiables **côté API backend** — *à confirmer* (voir *Open Questions*).
- **Envoi SMS/OTP réel** : différé à M5 (ADR-0006), comme pour #8 ; #9 hérite de l'adapter *stub* et
  du dépôt OTP en mémoire.
- **Onboarding « salon » guidé, plans/abonnements** (§8.3 « selon son plan ») : la notion de plan et
  le multi-salon avancé sont V2+ (PRD §16/§21) — hors périmètre.

## Relevant Repository Context

- **Statut** : greenfield outillé ; socle M0 (#1–#6) livré ; **#8 (première feature M1) mergée**.
  #9 est une **extension incrémentale** de l'ossature auth de #8.
- **Stack figée (ADR)** — inchangée par #9 :
  - Backend **FastAPI** · Python **≥ 3.12** · API REST (ADR-0003) ; OpenAPI auto-générée.
  - Persistance **SQLAlchemy 2.0 + Alembic + psycopg 3**, **PostgreSQL 16** (ADR-0009).
  - **Architecture hexagonale** (ADR-0008) : dépendance vers l'intérieur ; toute brique externe
    derrière un port + adapter ; le domaine n'importe jamais FastAPI/SQLAlchemy.
  - **Hachage argon2id + stratégie OTP** figés par **ADR-0012** (issu de #8) — **réutilisés tels
    quels** par #9.
- **Machinerie #8 réutilisable (chemins réels)** :
  - `coiflink_api/application/registration.py` — `RegisterCommand` (dataclass : `full_name`, `phone`,
    `password`, `email`) et `RegisterClient` (constructeur injectant les ports ; `execute` fixe
    **`role=Role.CLIENT.value`**, `status=UserStatus.ACTIVE.value`). **Point d'extension central.**
  - `coiflink_api/adapters/inbound/auth.py` — `APIRouter(prefix="/auth")`, schémas Pydantic
    `RegisterRequest` (**pas de champ `role`**) / `UserResponse` (expose `role`, jamais de secret),
    dépendances `get_password_hasher`, `get_register_client` (lit `AuthConfig` + adapters OTP depuis
    `app.state`), route `POST /auth/register`. Mapping erreurs : `PhoneAlreadyInUse`/`EmailAlreadyInUse`
    → `409` ; `Invalid*` → `422`.
  - `coiflink_api/domain/user.py` — `UserToCreate` (défaut `role=Role.CLIENT.value`), `User`,
    `validate_name`. `coiflink_api/domain/enums.py` — `Role.{CLIENT,HAIRDRESSER,MANAGER,ADMIN}`,
    `UserStatus`. `coiflink_api/domain/errors.py` — erreurs neutres (sans HTTP).
  - `coiflink_api/adapters/outbound/persistence/user_repository.py` — `SqlUserRepository`
    (`phone_exists`, `create` avec fallback `IntegrityError` → erreurs de domaine). **Générique sur le
    rôle** : il persiste le `role` porté par `UserToCreate`, donc **aucune modification** requise.
  - `coiflink_api/adapters/outbound/security/argon2_hasher.py`, `.../notifications/otp_sender_stub.py`,
    `.../security/otp_in_memory.py` ; `coiflink_api/config.py` (`AuthConfig`, `load_auth_config`) ;
    `coiflink_api/main.py` (composition root déposant `auth_config`, `otp_sender`, `otp_repository`
    sur `app.state`).
- **Table `users` (livrée #3)** — `role` `String(32)` `NOT NULL` + `CHECK` `ck_users_role` dérivé de
  `enums.Role` (inclut déjà `MANAGER`) ; `phone` unique (`uq_users_phone`) ; `email` unique partiel
  (`uq_users_email`). **`MANAGER` est déjà une valeur acceptée en base — aucune migration.**
- **Tests existants (patrons à suivre)** : `tests/conftest.py` (fakes partagés :
  `FakeUserRepository`, `FakeHasher`, `FakeOtp*`), `tests/test_auth_api.py` (FastAPI `TestClient` +
  `app.dependency_overrides[get_register_client]`), `tests/test_registration_usecase.py`. Ces suites
  **doivent rester vertes**.
- **Conventions** : Conventional Commits ; **aucune signature IA** dans code/commits/PR ; lint
  `ruff check` (ligne 100) ; test gate `pytest` (#6, agrégé `MX_AGENT_TEST_CMD`).

## Proposed Implementation

> Approche recommandée pour un agent d'implémentation. Les points *(à confirmer)* renvoient à *Risks
> and Open Questions*. Principe directeur : **réutiliser #8, ne pas dupliquer**, et **interdire au
> client de choisir son rôle**.

### 1. Généraliser le cas d'usage (`application/registration.py`)

Rendre le rôle **paramétrable côté serveur** au lieu de le coder en dur, tout en gardant la sécurité
« liste blanche de rôles auto-inscriptibles ».

- Introduire une **constante de domaine** des rôles ouverts à l'auto-inscription, p. ex. dans
  `domain/user.py` (ou `domain/enums.py`) : `SELF_REGISTERABLE_ROLES = frozenset({Role.CLIENT,
  Role.MANAGER})`. **Exclut explicitement `ADMIN` et `HAIRDRESSER`** (créés par d'autres voies).
- **Recommandé** : renommer/généraliser `RegisterClient` en **`RegisterUser`** avec un paramètre de
  constructeur `role: Role = Role.CLIENT`, validé à la construction (`role in
  SELF_REGISTERABLE_ROLES`, sinon lever une erreur de programmation/domaine). `execute` utilise
  `self._role.value` au lieu de `Role.CLIENT.value`. Le reste (validation → normalisation téléphone →
  pré-check doublon → hachage → persistance → OTP optionnel) est **inchangé**.
  - **Compatibilité** : conserver `RegisterClient` comme **alias/fabrique fine** (`RegisterClient =
    RegisterUser` avec `role=Role.CLIENT`, ou fonction `register_client_usecase(...)`) pour ne pas
    casser `test_auth_api.py`/`test_registration_usecase.py` qui importent `RegisterClient`. *(à
    confirmer : renommage vs. ajout d'une sous-classe `RegisterManager` — voir Open Questions.)*
- **Alternative minimale** (si l'on veut zéro churn sur #8) : ajouter une sous-classe/fabrique
  `RegisterManager` qui réutilise `RegisterUser`/`RegisterClient` avec `role=Role.MANAGER`. Moins DRY
  au niveau nommage, même sécurité.

### 2. Exposer l'inscription gérant (`adapters/inbound/auth.py`)

- **Nouvel endpoint** `POST /auth/register/manager` *(chemin à confirmer — voir Open Questions)* qui
  **réutilise** `RegisterRequest`/`UserResponse` (schémas identiques ; `RegisterRequest` **ne porte
  pas** de champ `role`, ce qui **empêche** de choisir le rôle).
- Nouvelle dépendance d'assemblage `get_register_manager` calquée sur `get_register_client`, mais
  câblant le cas d'usage avec **`role=Role.MANAGER`** (même `SqlUserRepository`, `Argon2Hasher`,
  config/adapters OTP relus depuis `app.state`).
- La route gérant appelle `usecase.execute(command)` et retraduit les erreurs **exactement** comme la
  route client (`PhoneAlreadyInUse`/`EmailAlreadyInUse` → `409` ; `Invalid*` → `422`) ; réponse
  `201` avec `role="MANAGER"`, `status="ACTIVE"`, **sans** secret.
- **Durcissement anti-injection de rôle** *(recommandé)* : ajouter
  `model_config = ConfigDict(extra="forbid")` à `RegisterRequest` afin qu'un champ inattendu (p. ex.
  `role` glissé par un client malveillant) provoque un `422` au lieu d'être **silencieusement
  ignoré**. Appliquer aussi à la route client (cohérence, aucun changement de contrat sur les champs
  légitimes). *(à confirmer.)*

### 3. Composition root (`main.py`)

- **Aucun changement structurel attendu** : les adapters (hacheur, OTP sender/repo) et `AuthConfig`
  sont déjà déposés sur `app.state` et relus par les dépendances FastAPI. Le nouvel endpoint est monté
  par le **même** `auth_router` (déjà `include_router`), donc `main.py` reste inchangé — **à vérifier**
  lors de l'implémentation.

### 4. Domaine / persistance

- **Domaine** : ajout de la constante `SELF_REGISTERABLE_ROLES` (garde-fou). Éventuellement une erreur
  dédiée si un rôle non auto-inscriptible est demandé au cas d'usage (erreur **de programmation**, pas
  une entrée utilisateur — ne doit pas être atteignable via l'API publique).
- **Persistance** : **rien à faire** — `SqlUserRepository.create` persiste déjà le `role` porté par
  `UserToCreate` ; le `CHECK` base couvre `MANAGER`.

## Affected Files / Packages / Modules

**Paquet concerné : `backend/` uniquement** (front web hors périmètre — voir *Non-Goals*).

**À modifier :**
- `coiflink_api/application/registration.py` — généraliser `RegisterClient` → `RegisterUser(role=…)`
  (+ alias de compat) et valider le rôle contre `SELF_REGISTERABLE_ROLES`.
- `coiflink_api/adapters/inbound/auth.py` — ajouter la dépendance `get_register_manager` et la route
  `POST /auth/register/manager` ; *(recommandé)* `extra="forbid"` sur `RegisterRequest`.
- `coiflink_api/domain/user.py` (ou `domain/enums.py`) — ajouter `SELF_REGISTERABLE_ROLES`.
- `coiflink_api/main.py` — **seulement si** l'assemblage l'exige (a priori inchangé ; à vérifier).
- `backend/README.md` — table des endpoints (ajouter `POST /auth/register/manager`) + section
  « inscription gérant » (rôle `MANAGER`, rôle **non choisi par le client**, prérequis de #15).

**À créer :**
- `backend/tests/test_auth_manager_api.py` — tests API du nouvel endpoint (201 + `role="MANAGER"`,
  non-fuite de secret, 409 doublon, 422 validation, **refus d'injection de rôle**).
- *(si généralisation du cas d'usage)* compléter `backend/tests/test_registration_usecase.py` avec des
  cas `role=MANAGER` et le refus d'un rôle hors liste blanche.
- *(optionnel, si DSN dispo)* extension d'un test d'intégration Postgres : un `MANAGER` est bien
  persisté et accepté par `ck_users_role`.

**À lire (contexte) :** `specs/inscription-client-telephone-mot-de-passe.md`, `docs/adr/0003`, `0008`,
`0009`, `0012`, `prd-coiflink.md` (§4, §8.3, §9.1/§9.2, §11, §18), `backend/coiflink_api/adapters/
inbound/auth.py`, `.../application/registration.py`, `.../domain/{user,enums,errors}.py`,
`.../adapters/outbound/persistence/{user_repository,models}.py`, `backend/tests/{conftest,
test_auth_api}.py`, `backend/README.md`.

## API / Interface Changes

**Nouvel endpoint HTTP public (OpenAPI auto-générée, ADR-0003) :**

- **`POST /auth/register/manager`** *(chemin/versionnement à confirmer)*
  - **Corps (JSON)** : `full_name` (string, requis), `phone` (string, requis), `password` (string,
    requis), `email` (string, optionnel). **Aucun champ `role`** (le rôle est imposé côté serveur ;
    tout champ superflu est *recommandé* rejeté en `422` via `extra="forbid"`).
  - **`201 Created`** : `{ id, full_name, phone, email, role: "MANAGER", status: "ACTIVE",
    created_at }`. **Jamais** `password` ni `password_hash`.
  - **`409 Conflict`** : téléphone (ou email) déjà inscrit.
  - **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/email invalides, champ
    manquant, champ interdit).

**Inchangé :** `POST /auth/register` (client, US-1.1/#8) et `GET /health`. **Aucune émission de JWT**
(la connexion est #10). **CLI / autres interfaces réseau : none.**

## Data Model / Protocol Changes

**none.** Le rôle `MANAGER` est déjà une valeur de `enums.Role` et déjà autorisé par la contrainte
`ck_users_role` de la table `users` (#3). La table `salons` (`owner_id → users.id`) existe déjà mais
**n'est pas touchée** par #9 (création de salon = #15). Aucune migration Alembic, aucun changement de
sérialisation persistée. Les schémas Pydantic réutilisés (`RegisterRequest`/`UserResponse`) ne
modifient pas le schéma relationnel.

## Security & Privacy Considerations

- **Anti-élévation de privilège (contrainte centrale, label `security`)** : le rôle **ne doit jamais**
  provenir de la requête. Il est fixé **côté serveur** par le chemin d'inscription (endpoint + câblage
  du cas d'usage). Défense en profondeur : (1) `RegisterRequest` **ne déclare pas** de champ `role` ;
  (2) *recommandé* `extra="forbid"` pour transformer un `role` injecté en `422` plutôt qu'un silence ;
  (3) **liste blanche** `SELF_REGISTERABLE_ROLES = {CLIENT, MANAGER}` au niveau du cas d'usage, si
  bien que même un défaut de câblage ne peut pas produire un `ADMIN`/`HAIRDRESSER` via cette voie.
- **Mot de passe (§11.1, ADR-0012)** : hérité de #8 — **argon2id**, jamais en clair, jamais journalisé,
  jamais renvoyé. Le clair ne vit que le temps de l'appel `hash()`.
- **PII (§11.3)** : `full_name`, `phone`, `email` — **jamais journalisés** ; collecte minimale (mêmes
  champs que le client). Les messages `409` ne divulguent pas le numéro/email (le test #8
  `test_duplicate_response_detail_does_not_contain_phone` établit le patron à suivre).
- **Refus de doublon** : identique à #8 — pré-check applicatif (`409`) **et** garde-fou base
  (`uq_users_phone`/`uq_users_email` → `IntegrityError` retraduite). La **normalisation du téléphone**
  reste une exigence de sécurité (unicité contournable sans forme canonique). Un gérant partageant un
  numéro déjà inscrit (par un client, p. ex.) est **refusé** — voir *Open Questions* (un numéro = un
  compte, tous rôles confondus).
- **Auto-inscription ouverte, non authentifiée** : comme le client, l'inscription gérant est publique.
  **Anti-abus / rate-limiting** : `a minima` réutiliser la limite d'essais OTP ; le rate-limit
  d'endpoint et l'anti-bruteforce global sont portés par #10/#12 (§11.1 vise surtout la connexion) —
  **à confirmer**. Un gérant auto-inscrit n'obtient **aucun** accès protégé tant que RBAC (#12) n'est
  pas en place ; #9 n'ouvre donc **aucune** donnée sensible.
- **OTP** : hérité de #8 (désactivé par défaut, jamais journalisé/renvoyé, stockage haché, usage
  unique, expiration). Aucune nouveauté.
- **Secrets / config (ADR-0011)** : aucun nouveau secret ; `JWT_SECRET` reste **inutilisé** par #9.
  Aucun réglage secret n'est committé (seul `.env.example`).
- **Budget latence (§12.1, API < 3 s)** : coût argon2 par défaut déjà validé en #8 ; #9 n'ajoute pas
  de coût notable.
- **Contraintes documentées non applicables** : #9 ne touche ni au chiffrement au repos (#5), ni à la
  journalisation d'audit structurée (§11.4, M6), ni à l'isolation par salon (§11.2, #12 — #9 attribue
  le rôle, ne contrôle pas les accès).

## Testing Plan

Test gate : **`pytest`** (ADR-0003 ; agrégé `MX_AGENT_TEST_CMD`, #6). Les suites existantes
(`test_auth_api.py`, `test_registration_usecase.py`, `test_health.py`, `test_session.py`,
`test_secrets_policy.py`, etc.) **doivent rester vertes**. `ruff check` doit passer.

- **Cas d'usage (`test_registration_usecase.py`, ports fakes)** :
  - inscription avec `role=MANAGER` → `UserToCreate.role == "MANAGER"`, `status="ACTIVE"`, mot de
    passe **haché** passé au dépôt (jamais le clair) ;
  - `role=CLIENT` **inchangé** (non-régression #8) ;
  - **refus d'un rôle hors liste blanche** (`ADMIN`/`HAIRDRESSER`) → erreur (garde-fou domaine).
- **API gérant (`test_auth_manager_api.py`, FastAPI `TestClient` + `dependency_overrides`)**, calqué
  sur `test_auth_api.py` :
  - `POST /auth/register/manager` valide → **`201`** + `role == "MANAGER"`, `status == "ACTIVE"` ;
  - **non-fuite** : `password`/`password_hash` absents de la réponse et du corps brut ;
  - doublon téléphone → **`409`** (formats local `0700…` et E.164 `+225…` reconnus comme doublon via
    normalisation) ; message `409` **ne contient pas** le numéro ;
  - validation → **`422`** (champ manquant, email invalide, mot de passe trop court, nom vide,
    bornes de longueur) ;
  - **anti-injection de rôle** : un corps contenant `"role": "ADMIN"` (ou `"MANAGER"`/`"CLIENT"`)
    **n'altère pas** le rôle attribué → réponse `role == "MANAGER"` (et `422` si `extra="forbid"`
    retenu). *Test de sécurité clé.*
- **Intégration (PostgreSQL 16, skip propre si pas de `DATABASE_URL`)** *(optionnel mais recommandé)* :
  un `MANAGER` est **persisté** avec `password_hash` ≠ clair et **accepté** par `ck_users_role` ;
  doublon de téléphone rejeté même en contournant le pré-check (fallback `IntegrityError` → `409`).
- **Documentation** : vérifier (revue) que `backend/README.md` documente le nouvel endpoint et que
  l'OpenAPI l'expose sans champ sensible en sortie.

## Documentation Updates

- **`backend/README.md`** : ajouter `POST /auth/register/manager` à la table des endpoints ; section
  « Authentification — inscription gérant » (rôle `MANAGER` **attribué côté serveur**, jamais choisi
  par le client ; mêmes règles que le client : hachage argon2, refus de doublon, OTP désactivé par
  défaut) ; noter que le compte est **prêt à créer un salon** (#15) et que #9 **ne crée pas** de salon.
- **`backend/.env.example`** : *aucun nouveau réglage* (OTP/argon2 déjà documentés par #8) ; rappel
  que `JWT_SECRET` reste inutilisé.
- **OpenAPI** : auto-générée par FastAPI ; s'assurer que le schéma de réponse **exclut** tout secret.
- **`docs/adr/`** : *aucun nouvel ADR requis* (ADR-0012 couvre hachage/OTP). La **politique
  d'attribution des rôles** (rôle imposé côté serveur, liste blanche d'auto-inscription) est décrite
  ici et dans le README ; sa formalisation transverse revient à l'**ADR RBAC de #12** — lien à poser
  depuis #12 vers cette spec. *(à confirmer.)*
- **`prd-coiflink.md`** / **`BACKLOG.md`** : **ne pas modifier** (sources de vérité).

## Risks and Open Questions

- **Chemin de l'endpoint** *(à confirmer)* : `POST /auth/register/manager` (recommandé) vs.
  `POST /auth/register-manager` vs. `POST /auth/managers` vs. un préfixe versionné
  (`/api/v1/...`). #8 a posé `/auth/register` sans versionnement ; tenir la cohérence auth (#10/#11).
- **Généralisation vs. duplication du cas d'usage** *(à confirmer)* : renommer `RegisterClient` →
  `RegisterUser(role=…)` avec alias de compat (recommandé, DRY) vs. ajouter une fabrique/sous-classe
  `RegisterManager`. Impacte les imports de `test_auth_api.py`/`test_registration_usecase.py` — prévoir
  l'alias pour ne pas casser #8.
- **`extra="forbid"` sur `RegisterRequest`** *(à confirmer)* : durcit l'anti-injection de rôle mais
  change légèrement le contrat (un champ superflu passe de « ignoré » à `422`). Recommandé pour la
  sécurité ; à appliquer de façon cohérente aux deux routes.
- **Un numéro = un compte, tous rôles confondus** *(à confirmer)* : la contrainte `uq_users_phone` est
  **globale**. Une personne à la fois cliente et gérante ne peut pas réutiliser le même numéro pour
  deux comptes → décision produit (compte multi-rôles ? second numéro ?). Le PRD ne tranche pas ; #9
  conserve « un numéro = un compte » (comportement base actuel).
- **Email requis pour un gérant ?** *(à confirmer)* : le gérant se connecte au **dashboard web** et la
  connexion (#10) accepte téléphone **ou** email. Faut-il **exiger** l'email à l'inscription gérant
  (utile pour le reset #11 et l'accès web) alors qu'il est optionnel pour le client ? Recommandé :
  **garder l'email optionnel** en #9 (cohérence, aucun blocage), réévaluer avec #10/#14.
- **Auto-inscription gérant ouverte vs. modérée** *(à confirmer)* : le MVP autorise l'auto-inscription
  gérant (comme le critère d'acceptation le suggère). Une modération/validation admin (activation de
  salon = rôle admin, §4) est **différée** ; à noter si le produit veut vérifier les gérants avant de
  les laisser exploiter un salon (interagit avec §8.3 et le rôle Admin).
- **Rate-limiting inscription** *(à confirmer)* : porté par #9 (limite OTP au minimum) ou délégué à
  #10/#12. L'inscription publique non authentifiée mérite une limite anti-abus à terme.
- **Périmètre front web** *(à confirmer)* : #9 se limite-t-il à l'**API backend** (recommandé, tous les
  critères d'acceptation sont backend) ou doit-il livrer un écran d'onboarding `web-dashboard/` ? Le
  paquet Next.js est un squelette ; l'UI gérant recoupe #14.

## Implementation Checklist

1. **Acter les décisions** : chemin d'endpoint (`/auth/register/manager` recommandé), généralisation
   du cas d'usage (`RegisterUser(role=…)` + alias `RegisterClient`), `extra="forbid"`, email optionnel,
   périmètre backend-only. (Voir *Open Questions*.)
2. **Domaine** : ajouter `SELF_REGISTERABLE_ROLES = frozenset({Role.CLIENT, Role.MANAGER})`
   (`domain/user.py` ou `domain/enums.py`) ; *(optionnel)* erreur dédiée pour un rôle hors liste.
   **Zéro** import framework/I/O.
3. **Cas d'usage** (`application/registration.py`) : généraliser en `RegisterUser` avec
   `role: Role = Role.CLIENT` validé contre la liste blanche ; utiliser `self._role.value` dans
   `UserToCreate` ; conserver `RegisterClient` comme alias/fabrique (`role=CLIENT`) pour la compat.
4. **Adapter entrant** (`adapters/inbound/auth.py`) : ajouter `get_register_manager` (câble
   `role=Role.MANAGER`, mêmes adapters/`AuthConfig` que le client) et la route
   `POST /auth/register/manager` (réutilise `RegisterRequest`/`UserResponse`) ; mapping erreurs
   identique à la route client ; *(recommandé)* `extra="forbid"` sur `RegisterRequest`.
5. **Composition root** (`main.py`) : vérifier que l'assemblage existant suffit (a priori **inchangé** :
   même `auth_router`, adapters déjà sur `app.state`).
6. **Persistance** : **rien** (l'adapter persiste déjà le `role` de `UserToCreate` ; `CHECK` couvre
   `MANAGER`). Confirmer qu'aucune migration n'est nécessaire.
7. **Tests** : créer `tests/test_auth_manager_api.py` (201 + `role="MANAGER"`, non-fuite, 409 doublon,
   422 validation, **anti-injection de rôle**) ; compléter `test_registration_usecase.py` (cas
   `MANAGER` + refus hors liste blanche) ; *(optionnel)* intégration Postgres (persistance + `CHECK`,
   skip si pas de DSN). Garder les suites #8 vertes.
8. **Documentation** : `backend/README.md` (endpoint + section inscription gérant + rappels sécurité +
   « prêt à créer un salon », pas de création de salon) ; vérifier l'OpenAPI.
9. **Garde-fous** : confirmer qu'**aucun rôle n'est acceptable via la requête**, qu'**aucun
   secret/PII/OTP/mot de passe** n'est journalisé/renvoyé, que le domaine n'importe pas
   SQLAlchemy/FastAPI (ADR-0008), qu'**aucune migration** n'a été ajoutée, et qu'**aucune signature
   IA** n'est présente dans code/commits/PR.
10. **Sanity** : `pytest` vert (unitaires + API sans base ; intégration si DSN dispo), `ruff check`
    propre, `pip install -e .` OK.
