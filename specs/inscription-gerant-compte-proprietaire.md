# Inscription gérant & création du compte propriétaire

> Spécification de planification pour l'issue GitHub **#9 — Inscription gérant & création du compte
> propriétaire** (`feature` `security` · Must · Effort M · PRD §18 Sprint 1, §4). Onboarding du
> **gérant** (compte propriétaire d'un salon), **prérequis de US-2.1** (#15, création d'un salon).
> **Dépend de #3** (modèle de données & schéma PostgreSQL — table `users` livrée). En pratique,
> #9 **réutilise et généralise** les briques d'auth livrées par **#8** (inscription client).
> **Cette spec ne produit pas de code.** Elle décrit l'API d'inscription gérant, la généralisation
> du cas d'usage d'inscription et les contraintes de sécurité à implémenter dans une phase ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR, commentaires). Les
> en-têtes de section ci-dessous sont conservés en anglais car attendus par le gabarit du pipeline
> ADW ; le contenu reste en français, hors identifiants techniques (noms de tables/colonnes, routes,
> enums, symboles de code). Depuis #79, **le code applicatif est nommé en anglais** (modules, classes,
> routes) : cette spec suit cette convention (`RegisterUser`, `/auth/register/manager`, etc.).

## Problem Statement

Le PRD (§4, §18 Sprint 1) distingue le **Gérant** (responsable du salon : gère salon, employés,
prestations, RDV, caisse, statistiques) des autres rôles. Pour qu'un gérant puisse ensuite
**créer et configurer son salon** (US-2.1, #15), il faut d'abord qu'il dispose d'un **compte
propriétaire** portant le rôle `MANAGER`. Le critère d'acceptation de #9 est explicite :

> *un gérant crée son compte ; le rôle `Gérant` est attribué ; prêt à créer un salon.*

État actuel du dépôt (M1 en cours) :

- **#8 (inscription client) est livré** : le backend expose déjà `POST /auth/register` qui crée un
  utilisateur de rôle `CLIENT`, avec toute la mécanique d'auth réutilisable — cas d'usage
  `RegisterClient` (`application/registration.py`), normalisation E.164 du téléphone
  (`domain/phone.py`), politique de mot de passe (`domain/password.py`), hachage **argon2id**
  (`adapters/outbound/security/argon2_hasher.py`, ADR-0012), dépôt SQLAlchemy
  (`adapters/outbound/persistence/user_repository.py`), capacité OTP testable, schémas Pydantic +
  gestion d'erreurs HTTP (`adapters/inbound/auth.py`). **#8 avait explicitement annoncé** poser ces
  patterns « que les issues d'auth suivantes (#9 inscription gérant…) réutiliseront ».
- **Le rôle `MANAGER` existe déjà** dans le domaine (`domain/enums.py` → `Role.MANAGER = "MANAGER"`)
  et la colonne `users.role` porte un `CHECK` **dérivé mécaniquement de `enums.values(Role)`**
  (`models.py`), qui **autorise donc déjà `MANAGER`**. La table `users` porte tout le nécessaire
  (`full_name`, `phone` unique, `email?`, `password_hash`, `role`, `status`). La table `salons`
  porte déjà `owner_id → users` (FK livrée par #3). **Aucune évolution de schéma n'est nécessaire.**

Le manque : il n'existe **aucun point d'entrée** pour créer un compte de rôle `MANAGER`. L'endpoint
`POST /auth/register` fixe `role=CLIENT` **en dur** (côté serveur — voir *Security*), et il ne faut
**surtout pas** ajouter un champ `role` librement choisi par l'appelant (élévation de privilège).

Le besoin de #9 : **livrer l'inscription gérant de bout en bout côté backend** — un point d'entrée
dédié qui (1) crée un compte de rôle `MANAGER`, (2) réutilise le refus de doublon, le hachage et la
normalisation de #8, (3) **attribue le rôle côté serveur** (jamais depuis la requête), et (4) laisse
le compte **prêt à créer un salon** (la création effective du salon relève de #15). L'occasion est
aussi de **généraliser** le cas d'usage d'inscription de #8 pour éviter toute duplication (#10, #13
en bénéficieront).

## Goals

- **Endpoint d'inscription gérant** créant un utilisateur de rôle `MANAGER`, statut `ACTIVE` par
  défaut, à partir d'un **nom**, d'un **téléphone**, d'un **mot de passe** (e-mail optionnel) —
  mêmes champs que l'inscription client. Chemin recommandé : **`POST /auth/register/manager`**
  (*à confirmer* — voir *Open Questions*).
- **Rôle attribué côté serveur (invariant de sécurité)** : `role=MANAGER` est fixé par l'endpoint,
  **jamais** lu depuis le corps de requête. Aucun champ `role` public n'est introduit → pas
  d'élévation de privilège possible via l'API d'inscription.
- **Réutilisation maximale (DRY, hexagonal)** : **généraliser** le cas d'usage `RegisterClient` en un
  `RegisterUser` **paramétré par le rôle**, réutilisant à l'identique domaine (téléphone, mot de
  passe, OTP), ports (`UserRepository`, `PasswordHasher`, `OtpSender`, `OtpRepository`) et adapters
  (argon2, SQLAlchemy, stub OTP). Aucune nouvelle logique métier — seul le **rôle cible** change.
- **Refus du doublon de téléphone** : un numéro déjà inscrit (quel que soit son rôle) est rejeté
  proprement (HTTP `409`), garanti par la pré-vérification applicative **et** la contrainte base
  `uq_users_phone`, comme pour #8.
- **Mot de passe jamais en clair** : hachage **argon2id** (ADR-0012) via le port `PasswordHasher` ;
  ni le mot de passe, ni le condensat, ni l'OTP, ni le téléphone ne sont **jamais journalisés** ni
  renvoyés.
- **Compte « prêt à créer un salon »** : le compte `MANAGER` existe et est activé ; la **création du
  salon** (US-2.1) et le rattachement `salons.owner_id` sont **hors périmètre** (#15). #9 fournit le
  prérequis.
- **Documenter l'API publique** : schémas Pydantic → OpenAPI auto-générée (ADR-0003) et mise à jour
  du `backend/README.md`.

## Non-Goals

- **Création / configuration du salon (US-2.1, #15)** : #9 crée le **compte propriétaire**, pas le
  salon. Le rattachement `salons.owner_id → users` et le formulaire de salon relèvent de #15 (M2).
- **Connexion & JWT (US-1.2, #10)** : l'inscription **n'émet aucun JWT / refresh token**. L'émission
  de jetons, la lib JWT et le rate-limit anti-bruteforce à la connexion sont hors périmètre. (Une
  décision *auto-login après inscription* reste en *Open Questions*, comme pour #8.)
- **RBAC / middleware d'autorisation & isolation par salon (#12)** : `MANAGER` ne confère par
  lui-même **aucun pouvoir inter-salon**. La protection des routes par rôle (deny-by-default) et
  l'isolation « un gérant ne voit que son salon » (§11.2) arrivent avec **#12** (qui dépend de #10).
- **Invitation / création de comptes employés (#13)** : le gérant qui invite des coiffeurs est une
  issue distincte, dépendant du RBAC (#12).
- **Réinitialisation de mot de passe (US-1.3, #11)** et **envoi SMS réel de l'OTP** (infra
  notifications, M5, ADR-0006) : hors périmètre ; #9 réutilise seulement la **capacité OTP testable**
  et l'**adapter stub** déjà en place.
- **UI web gérant (dashboard, #14 ; §7.2)** : le paquet `web-dashboard/` est un squelette ; l'écran
  d'inscription/onboarding gérant est un travail front distinct. #9 se concentre sur l'**API
  backend** (le critère d'acceptation est vérifiable côté backend). *À confirmer* — voir *Open
  Questions*.
- **Modération / approbation admin du compte gérant** : le PRD ne spécifie pas d'étape d'approbation ;
  l'inscription est self-service par défaut (voir *Open Questions*).
- **Journalisation d'audit structurée (§11.4)** et **consentement/RGPD-like (§11.3)** : items
  transverses (M6) ; #9 se contente de **ne jamais journaliser** de secret/PII.

## Relevant Repository Context

- **Statut** : greenfield outillé ; socle M0 (#1–#6) et **inscription client #8** livrés. #9 est la
  **deuxième feature d'auth** de M1 et **réutilise** l'ossature de #8.
- **Stack figée (ADR)** — inchangée par #9 :
  - Backend **FastAPI** · Python **≥ 3.12** · REST (ADR-0003). OpenAPI auto-générée depuis Pydantic.
  - Persistance **SQLAlchemy 2.0 + Alembic + psycopg 3**, **PostgreSQL 16** (ADR-0009).
  - **Architecture hexagonale** (ADR-0008) : dépendance toujours vers l'intérieur ; toute brique
    externe passe par un **port** + un **adapter sortant** ; `domain/` et `application/` n'importent
    jamais FastAPI/SQLAlchemy.
  - **Hachage argon2id + stratégie OTP** actés par **ADR-0012** (port `PasswordHasher` ; OTP pur,
    testable, désactivé par défaut, envoi *stub*, dépôt en mémoire). **Réutilisés tels quels.**
- **Briques d'auth livrées par #8 (à réutiliser)** :
  - `domain/` : `phone.py` (normalisation **E.164**, `+225` par défaut), `password.py` (politique,
    `MIN_LENGTH`/`MAX_LENGTH`), `otp.py` (défi OTP pur), `errors.py` (`PhoneAlreadyInUse`,
    `EmailAlreadyInUse`, `InvalidPhone`, `InvalidPassword`, `InvalidName`, `InvalidEmail`, …),
    `user.py` (`validate_name`, `UserToCreate`, `User` — **déjà paramétrable par `role`/`status`**).
  - `application/` : `registration.py` → `RegisterCommand` (**déjà indépendant du rôle** :
    `full_name`, `phone`, `password`, `email`) et `RegisterClient` (fixe `role=CLIENT.value` dans
    `execute()`). Ports dans `application/ports/`.
  - `adapters/outbound/` : `persistence/user_repository.py` (`SqlUserRepository` : `phone_exists`,
    `create` avec fallback `IntegrityError → PhoneAlreadyInUse/EmailAlreadyInUse`),
    `security/argon2_hasher.py`, `security/otp_in_memory.py`, `notifications/otp_sender_stub.py`,
    `persistence/session.py` (`get_session`).
  - `adapters/inbound/auth.py` : router `prefix="/auth"`, `RegisterRequest`/`UserResponse` (sans
    secret), `get_password_hasher`, `get_register_client` (assemble le cas d'usage via `Depends`),
    route `POST /auth/register`, mapping erreurs → `409`/`422`.
  - `config.py` : `AuthConfig`/`load_auth_config` (drapeaux OTP) déposés sur `app.state` par
    `main.py`.
  - `tests/conftest.py` : fakes réutilisables (`FakeHasher`, `FakeUserRepository`,
    `FakeUserRepositoryRaisingDuplicate`, `FakeOtpSender`, `FakeOtpRepository`).
- **Schéma `users` (livré par #3)** : `role` `String(32)` `NOT NULL` avec `CHECK` **dérivé de
  `enums.values(Role)`** — inclut déjà `MANAGER`. `status` défaut `ACTIVE`. `phone` unique
  (`uq_users_phone`), `email` unique partiel (`uq_users_email`). Table `salons` déjà présente avec
  `owner_id → users` (pour #15). **Aucune migration requise pour #9.**
- **Conventions** : Conventional Commits ; **aucune signature IA** dans code/commits/PR ;
  code applicatif **en anglais** (depuis #79), specs à en-têtes anglais / contenu français ; lint
  `ruff check` ; test gate `pytest` (#6, agrégé `MX_AGENT_TEST_CMD`).

## Proposed Implementation

> Approche recommandée pour un agent d'implémentation. Les points marqués *(à confirmer)* renvoient à
> *Risks and Open Questions*. **Principe directeur : réutiliser #8 sans le dupliquer**, en généralisant
> le cas d'usage d'inscription par un **paramètre de rôle fixé côté serveur**.

### 1. Généraliser le cas d'usage d'inscription (`application/registration.py`) — recommandé

Le parcours d'inscription est **identique** pour un client et un gérant : valider → normaliser le
téléphone → pré-check doublon → hacher → persister → OTP optionnel → retourner l'entité. **Seul le
rôle cible diffère.** Deux variantes possibles (à trancher — voir *Open Questions*) :

- **(A, recommandé) Généraliser en `RegisterUser` paramétré par le rôle.** Introduire un cas d'usage
  `RegisterUser` dont le constructeur reçoit un `role: str` (validé comme membre de `Role`) ; son
  `execute()` construit `UserToCreate(..., role=self._role, status=UserStatus.ACTIVE.value)`. Fournir
  deux points d'assemblage minces (client → `Role.CLIENT`, gérant → `Role.MANAGER`). Conserver la
  **compatibilité de #8** : soit renommer `RegisterClient` → `RegisterUser` en mettant à jour les
  deux références (import dans `auth.py` + tests), soit garder `RegisterClient` comme mince
  spécialisation (`role` figé à `CLIENT`). *Rationale* : une seule implémentation du parcours,
  réutilisée par #9/#10 (vérif) et cohérente avec l'hexagonal.
- **(B) Ajouter un `RegisterManager` distinct** dupliquant/déléguant la logique. Plus simple à isoler
  mais introduit de la duplication ; non recommandé.

`RegisterCommand` est **déjà agnostique du rôle** et n'a **pas** à changer.

> **Invariant** : le rôle est un **paramètre de configuration du cas d'usage** (injecté au câblage),
> **jamais** un champ de `RegisterCommand` ni de la requête HTTP. Un appelant ne peut pas choisir son
> rôle.

### 2. Adapter entrant (`adapters/inbound/auth.py`) — nouvelle route gérant

- **`POST /auth/register/manager`** *(chemin à confirmer)* :
  - **Requête** : réutiliser le schéma `RegisterRequest` existant (`full_name`, `phone`, `password`,
    `email?`) **tel quel** — **aucun** champ `role`. (Si un `role` est envoyé dans le corps, il est
    ignoré : `RegisterRequest` ne le déclare pas → non lié par Pydantic.)
  - **Réponse `201 Created`** : `UserResponse` existant → `{ id, full_name, phone, email, role:
    "MANAGER", status, created_at }`. **Jamais** `password`/`password_hash`.
  - **Erreurs** : `409 Conflict` (doublon téléphone / e-mail) ; `422 Unprocessable Entity`
    (validation Pydantic + domaine). Mapping **identique** à `POST /auth/register`.
  - **DI** : ajouter `get_register_manager(...)` symétrique de `get_register_client`, assemblant
    `RegisterUser(SqlUserRepository(session), hasher, role=Role.MANAGER.value, otp_*=…)`. Réutilise
    `get_session`, `get_password_hasher`, la config OTP sur `app.state`.
  - **Factorisation** : extraire la partie commune « exécuter le cas d'usage + traduire les erreurs
    domaine en HTTP + construire `UserResponse` » dans un petit helper partagé par les deux routes,
    pour éviter de recopier les blocs `try/except` (à l'appréciation de l'implémenteur — garder la
    lisibilité). *(à confirmer : route dédiée vs paramétrage — voir Open Questions.)*

### 3. Composition root (`main.py`) — inchangé ou quasi

- Le router `auth` est **déjà monté** ; ajouter la route gérant **dans le même router** ne demande
  aucun câblage supplémentaire. La config OTP et les adapters singletons (`otp_sender`,
  `otp_repository`) sur `app.state` sont **réutilisés tels quels**. Aucun nouveau réglage d'env.

### 4. Domaine / persistance — aucun changement

- `Role.MANAGER` existe déjà ; le `CHECK` de `users.role` l'autorise déjà (dérivé de l'enum).
- `SqlUserRepository`, `UserToCreate`, `User` sont **déjà paramétrés par `role`** → réutilisés sans
  modification. **Aucune migration Alembic.**

## Affected Files / Packages / Modules

**Paquet concerné : `backend/` uniquement** (front web gérant hors périmètre — voir *Non-Goals*).

**À modifier :**
- `coiflink_api/application/registration.py` — généraliser en `RegisterUser` paramétré par `role`
  (option A recommandée), en préservant le comportement de #8 (client).
- `coiflink_api/adapters/inbound/auth.py` — ajouter la route `POST /auth/register/manager`, la
  dépendance `get_register_manager`, et (optionnel) un helper commun d'exécution/mapping d'erreurs ;
  mettre à jour les imports (`Role`, `RegisterUser`) et `__all__`.
- `backend/README.md` — table des endpoints (ajouter `POST /auth/register/manager`) et section
  « inscription gérant » (rôle `MANAGER`, prérequis de la création de salon #15).
- *(si `RegisterClient` est renommé)* `tests/test_registration_usecase.py`, `tests/test_auth_api.py`
  — mise à jour des imports/références pour rester verts.

**À créer :**
- `tests/test_manager_registration_usecase.py` — cas d'usage `RegisterUser` avec `role=MANAGER`
  (fakes de `conftest.py`).
- `tests/test_manager_auth_api.py` — API `POST /auth/register/manager` (`201`/`409`/`422`,
  `role=="MANAGER"`, non-fuite du secret, **anti-escalade** : un champ `role` dans le corps est
  ignoré).
- *(optionnel)* extension de `tests/test_registration_integration.py` (si présent) ou nouvel
  `tests/test_manager_registration_integration.py` (Postgres, **skip si pas de `DATABASE_URL`**) :
  persistance `role=MANAGER` + `uq_users_phone`.

**À lire (contexte) :** `specs/inscription-client-telephone-mot-de-passe.md`, `prd-coiflink.md`
(§4, §7.2, §11, §18), `docs/adr/0003`, `0008`, `0009`, `0012`,
`backend/coiflink_api/application/registration.py`, `.../adapters/inbound/auth.py`,
`.../adapters/outbound/persistence/user_repository.py`, `.../domain/enums.py`, `.../domain/user.py`,
`.../config.py`, `.../main.py`, `backend/tests/conftest.py`, `backend/tests/test_auth_api.py`,
`backend/README.md`.

## API / Interface Changes

**Nouvel endpoint HTTP public (documenté via OpenAPI auto-générée, ADR-0003) :**

- **`POST /auth/register/manager`** *(chemin/versionnement à confirmer — voir Open Questions)*
  - **Corps (JSON)** : `full_name` (string, requis), `phone` (string, requis), `password` (string,
    requis, longueur `MIN_LENGTH..MAX_LENGTH`), `email` (string, optionnel). **Aucun champ `role`.**
  - **`201 Created`** : `{ id, full_name, phone, email, role: "MANAGER", status, created_at }`.
    **Jamais** `password` ni `password_hash`.
  - **`409 Conflict`** : téléphone (ou e-mail) déjà inscrit.
  - **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/e-mail invalides, champ
    manquant).

**Inchangé :** `GET /health`, `POST /auth/register` (client). L'inscription gérant **n'émet aucun
JWT** (la connexion est #10). **CLI / autres interfaces réseau : none.**

## Data Model / Protocol Changes

**none.** La table `users` (#3) porte déjà `role` avec un `CHECK` **incluant `MANAGER`** (dérivé de
`domain/enums.py`) et `status` défaut `ACTIVE`. Aucune colonne, aucune contrainte, aucune migration
Alembic n'est requise. La table `salons` (`owner_id → users`) existe déjà mais **n'est pas touchée**
par #9 (le rattachement propriétaire relève de #15). Les seuls nouveaux artefacts de sérialisation
sont **réutilisés** de #8 (`RegisterRequest`/`UserResponse`) — pas de nouveau schéma.

## Security & Privacy Considerations

- **Attribution du rôle côté serveur (invariant critique)** : `role=MANAGER` est **fixé par
  l'endpoint / le câblage**, jamais lu depuis la requête. **Ne pas** introduire de champ `role`
  public dans `RegisterRequest` (ni dans `RegisterCommand`) : sinon un appelant pourrait s'auto-
  attribuer `MANAGER`/`ADMIN` (**élévation de privilège**). Un test anti-escalade doit verrouiller ce
  comportement (un `role` envoyé dans le corps est ignoré).
- **Signup gérant self-service** *(à confirmer, produit)* : par défaut, l'inscription gérant est
  ouverte (comme l'inscription client). C'est **acceptable au MVP** car, tant que **#12 (RBAC)** et
  **#15 (salon)** n'existent pas, le rôle `MANAGER` seul **ne confère aucun accès à des données d'un
  autre tenant** : l'isolation par salon (§11.2) est appliquée par #12 et les ressources sont
  rattachées à `salons.owner_id`. Si le produit veut une **approbation admin** ou une **invitation**,
  c'est une décision à acter (voir *Open Questions*) — sans quoi ne pas sur-concevoir.
- **Mot de passe (§11.1, ADR-0012)** : **jamais en clair**, jamais journalisé, jamais renvoyé.
  Hachage **argon2id** (`argon2-cffi`) via le port `PasswordHasher` ; le clair ne vit que le temps de
  l'appel `hash()`.
- **Refus de doublon & normalisation téléphone** : réutilisés de #8. La **normalisation E.164** reste
  une **exigence de sécurité** (sans forme canonique, l'unicité `uq_users_phone` et le refus de
  doublon sont contournables). Le doublon est garanti au niveau application **et** base (fallback
  `IntegrityError → 409`).
- **PII (§11.3)** : `full_name`, `phone`, `email` sont des données personnelles → **jamais
  journalisées** ; collecte minimale. Le message du `409` **ne divulgue pas** le numéro (cf. tests de
  non-fuite de #8) — attention à l'énumération de comptes (compromis produit, cf. *Open Questions*).
- **Secrets / config (ADR-0011)** : aucun nouveau secret. `JWT_SECRET` reste **inutilisé** par #9.
  Réglages OTP réutilisés depuis l'environnement ; aucune valeur réelle committée.
- **Budgets (§12.1)** : API **< 3 s** — le coût argon2 par défaut reste largement dans le budget
  (déjà validé en #8/ADR-0012).
- **Contraintes documentées non applicables à #9** : chiffrement au repos (hébergement #5), audit
  structuré (§11.4, M6), rate-limiting anti-bruteforce (surtout la connexion #10 / RBAC #12).

## Testing Plan

Test gate : **`pytest`** (ADR-0003 ; agrégé `MX_AGENT_TEST_CMD`, #6). **Toutes les suites #8 doivent
rester vertes** (`test_auth_api.py`, `test_registration_usecase.py`, `test_phone.py`,
`test_password.py`, `test_otp.py`, `test_password_hasher.py`, `test_health.py`, `test_session.py`,
`test_secrets_policy.py`, `test_config.py`). `ruff check` doit passer.

- **Cas d'usage (`RegisterUser`, ports fakes de `conftest.py`)** :
  - succès `role=MANAGER` : l'entité créée porte `role == Role.MANAGER.value`, `status == ACTIVE` ;
    le **mot de passe haché** (jamais le clair) est passé au dépôt ;
  - **doublon → `PhoneAlreadyInUse`** (pré-check et fallback via
    `FakeUserRepositoryRaisingDuplicate`) ;
  - validations (nom vide, mot de passe trop court, téléphone invalide) déclenchées ;
  - OTP émis seulement si activé (faux `OtpSender`/`OtpRepository`), **sans exposer** le code ;
  - **non-régression #8** : le parcours client produit toujours `role=CLIENT`.
- **API (`TestClient`, dépôt fake, sans base réelle)** — cf. patron `test_auth_api.py` :
  - `POST /auth/register/manager` valide → **`201`** + `role == "MANAGER"` ;
  - corps **sans** `password`/`password_hash` (assertions de non-fuite : le clair et le condensat
    fake n'apparaissent pas dans `r.text`) ;
  - doublon → **`409`** (dont doublon via un téléphone au format local vs E.164) ; le `detail` du
    `409` **ne contient pas** le numéro ;
  - entrée invalide (champ manquant, e-mail malformé, mot de passe court, nom vide, bornes de
    longueur) → **`422`** ;
  - **anti-escalade** : envoyer `{"role": "ADMIN", ...}` dans le corps → la réponse reste
    `role == "MANAGER"` (le champ est ignoré) ;
  - `GET /auth/register/manager` → **`405`**.
- **Intégration (PostgreSQL 16, skip propre si pas de `DATABASE_URL`)** :
  - l'inscription gérant **persiste** un `users` avec `role=MANAGER`, `status=ACTIVE`,
    `password_hash` ≠ clair ;
  - **doublon de téléphone** rejeté par `uq_users_phone` même en contournant le pré-check (fallback
    `IntegrityError → 409`) — y compris entre un compte `CLIENT` existant et une inscription `MANAGER`
    sur le **même** numéro.
- **Documentation** : vérifier (revue) que `backend/README.md` documente `POST
  /auth/register/manager` et que l'OpenAPI expose l'endpoint avec un schéma de réponse **sans** champ
  sensible.

## Documentation Updates

- **`backend/README.md`** : ajouter `POST /auth/register/manager` à la table des endpoints ; section
  « inscription gérant » (rôle `MANAGER`, self-service, **prérequis de la création de salon #15**,
  aucun JWT émis, mêmes garanties sécurité que l'inscription client) ; rappel « rôle attribué côté
  serveur, jamais depuis la requête ».
- **`backend/.env.example`** : **aucun nouveau réglage** (OTP/argon2 réutilisés). Rappel que
  `JWT_SECRET` reste inutilisé par #9.
- **`specs/`** : cette spec.
- **`docs/adr/`** : **aucun nouvel ADR requis** — #9 réutilise **ADR-0012** (hachage/OTP), **ADR-0008**
  (hexagonal), **ADR-0003** (FastAPI). *Optionnel* : une courte note (dans le README backend ou un
  ADR léger) actant la décision « **rôle fixé côté serveur / signup gérant self-service** » si
  l'équipe veut la tracer formellement (voir *Open Questions*).
- **OpenAPI** : auto-générée par FastAPI (aucune rédaction manuelle) ; s'assurer que `UserResponse`
  **exclut** tout champ sensible.
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).

## Risks and Open Questions

- **Généralisation vs duplication du cas d'usage** *(à trancher)* : **(A) `RegisterUser` paramétré par
  le rôle** (recommandé, DRY, réutilisé par #10/#13) — implique de renommer/adapter `RegisterClient`
  (touche les tests #8) ; vs **(B) `RegisterManager` séparé** (isolé mais dupliqué). Décision
  structurante pour la suite de l'auth.
- **Chemin & forme de l'API** *(à confirmer)* : **`POST /auth/register/manager`** (recommandé, rôle
  explicite dans le chemin, cohérent avec `/auth/register`) vs `POST /auth/managers` vs un **champ
  `role` dans le corps** de `POST /auth/register` — **cette dernière option est rejetée** (risque
  d'élévation de privilège). Tenir la cohérence avec les routes d'auth futures (#10/#11).
- **Self-service vs approbation/invitation du gérant** *(décision produit)* : faut-il qu'un gérant
  s'inscrive librement, ou via **approbation admin** / **invitation** ? Le PRD ne tranche pas. Par
  défaut : **self-service** (le rôle seul ne donne aucun accès inter-tenant avant #12/#15). Impacte
  éventuellement le `status` initial (`ACTIVE` vs un état « en attente ») — mais un état « en
  attente » **nécessiterait une migration** (nouvelle valeur `UserStatus`) : à éviter sauf besoin
  produit avéré.
- **E-mail requis pour un gérant ?** *(à confirmer)* : le gérant est un contact professionnel ;
  l'e-mail pourrait être **obligatoire** (utile pour #11 reset, notifications). Par défaut : **garder
  optionnel** (aligné sur le schéma `users.email` nullable et sur l'inscription client). Décision
  produit mineure.
- **Auto-login après inscription** *(à confirmer)* : renvoyer un JWT à l'inscription (UX plus fluide)
  vs exiger une connexion explicite (#10). Recommandé : **pas de JWT en #9** (émission = #10), comme
  pour #8.
- **Énumération de comptes** *(à confirmer, produit)* : le `409` sur doublon révèle l'existence d'un
  compte pour ce numéro. Compromis UX/anti-énumération hérité de #8 ; à trancher globalement.
- **Rate-limiting de l'inscription** *(à confirmer)* : porté par #9 (limite d'essais OTP au minimum,
  déjà dans la logique) ou délégué à #10/#12. §11.1 vise surtout la connexion.
- **Périmètre front web gérant** *(à confirmer)* : #9 se limite-t-il à l'**API backend** (recommandé,
  le critère d'acceptation est backend) ou doit-il aussi livrer l'**écran** d'inscription/onboarding
  du dashboard (§7.2, #14) ? Le paquet `web-dashboard/` est un squelette.

## Implementation Checklist

1. **Acter les décisions structurantes** : généralisation du cas d'usage (option A `RegisterUser`
   paramétré recommandée), chemin d'API (`POST /auth/register/manager` recommandé), self-service vs
   approbation, e-mail optionnel, no-JWT — cf. *Open Questions*. (Aucun nouvel ADR requis ; note
   optionnelle si l'équipe veut tracer « rôle côté serveur / self-service ».)
2. **Généraliser le cas d'usage** (`application/registration.py`) : introduire `RegisterUser` avec un
   paramètre `role` (validé comme membre de `Role`), `execute()` construisant `UserToCreate(...,
   role=self._role, status=ACTIVE)` ; **préserver le comportement client** de #8 (renommage compatible
   ou spécialisation `role=CLIENT`). Ne **pas** ajouter de `role` à `RegisterCommand`.
3. **Adapter entrant** (`adapters/inbound/auth.py`) : ajouter `get_register_manager` (assemble
   `RegisterUser(..., role=Role.MANAGER.value)`) et la route `POST /auth/register/manager` réutilisant
   `RegisterRequest`/`UserResponse` ; factoriser (optionnel) l'exécution + le mapping d'erreurs
   domaine → `409`/`422` partagé avec la route client ; mettre à jour imports et `__all__`.
4. **Composition root** : vérifier que le router `auth` (déjà monté) expose la nouvelle route ; aucun
   nouveau câblage/env attendu (OTP et adapters réutilisés depuis `app.state`).
5. **Vérifier l'absence de changement de schéma** : `Role.MANAGER` autorisé par le `CHECK` de
   `users.role` (dérivé de l'enum) ; **aucune migration Alembic**. Ne pas toucher `salons`.
6. **Tests** : ajouter `test_manager_registration_usecase.py` (rôle `MANAGER`, doublon, validations,
   OTP off/on) et `test_manager_auth_api.py` (`201`/`409`/`422`, `role=="MANAGER"`, non-fuite,
   **anti-escalade** d'un `role` envoyé dans le corps, `405` sur GET) ; intégration Postgres
   optionnelle (**skip si pas de DSN**). **Garder les suites #8 vertes** (adapter les imports si
   renommage).
7. **Documentation** : mettre à jour `backend/README.md` (endpoint + section gérant + rappels
   sécurité) ; vérifier l'OpenAPI ; pas de nouveau réglage `.env.example`.
8. **Garde-fous** : confirmer que le **rôle n'est jamais lu depuis la requête** (anti-escalade),
   qu'**aucun secret/PII/OTP/mot de passe** n'est journalisé ni renvoyé, que le domaine/l'application
   n'importent pas SQLAlchemy/FastAPI (ADR-0008), et qu'**aucune signature IA** n'est présente dans
   code/commits/PR.
9. **Sanity** : `pytest` vert (unitaires + API sans base ; intégration si DSN dispo), `ruff check`
   propre, `pip install -e .` OK.
