# Réinitialisation du mot de passe par OTP (SMS ou e-mail)

> Spec de planification — **issue #11 · US-1.3** (`Must` · `S` · labels `feature` `security`).
> Ne pas implémenter : ce document décrit le travail pour un agent de codage ultérieur.
> Dépend de **#8** (inscription client) ; réutilise le socle d'auth posé par **#8/#9/#10**
> (ADR-0012 hachage argon2 + stratégie OTP, ADR-0013 JWT/refresh/anti-bruteforce).

## Problem Statement

Un utilisateur (client, gérant, coiffeur, admin) qui **oublie son mot de passe** n'a aujourd'hui
**aucun moyen de le réinitialiser**. Le socle d'authentification livré jusqu'ici couvre :

- l'**inscription** (`POST /auth/register`, `POST /auth/register/manager` — #8/#9),
- la **connexion** et le **rafraîchissement de jeton** (`POST /auth/login`, `POST /auth/refresh` — #10).

Le PRD (§11.1) exige une « **réinitialisation par OTP** » et le backlog (#11) précise le critère
d'acceptation : *« parcours de reset complet ; OTP à usage unique et expirant ; ancien mot de passe
invalidé »*. Il manque donc un **parcours de reset de bout en bout** : demander un code à usage unique
(par SMS **ou** e-mail), le vérifier, puis fixer un nouveau mot de passe qui **invalide l'ancien**.

Le cœur OTP nécessaire (**génération/vérification pures, usage unique, expiration, limite d'essais**)
existe déjà dans le domaine (`coiflink_api/domain/otp.py`, posé par #8 et acté par ADR-0012) mais
n'est encore câblé à **aucun parcours métier** : l'inscription se contente d'émettre un OTP
non bloquant (capacité testable, envoi *stub*). La réinitialisation est le **premier parcours qui
consomme réellement l'OTP** et le **premier où l'OTP est bloquant** (le reset ne peut aboutir sans un
code valide).

## Goals

- **Parcours de reset complet en deux étapes**, exposé via l'API HTTP :
  1. **Demande** d'un code de réinitialisation à partir d'un identifiant (téléphone **ou** e-mail) ;
  2. **Confirmation** : soumission du code + d'un nouveau mot de passe, qui remplace l'ancien.
- **OTP à usage unique et expirant** : réutiliser la logique de domaine `otp.py`
  (`generate_otp_challenge` / `verify_otp_challenge`) — code d'une longueur configurable, fenêtre
  d'expiration, **consommation unique**, **limite d'essais**.
- **Ancien mot de passe invalidé** : à la confirmation, le condensat (`password_hash`) du compte est
  **remplacé** par celui du nouveau mot de passe ; l'ancien ne s'authentifie plus jamais via
  `POST /auth/login`.
- **Support des deux canaux** SMS et e-mail pour la remise du code (envoi réel *stub*, cf. Non-Goals).
- **Anti-énumération** : ni la demande ni la confirmation ne révèlent si un compte existe pour
  l'identifiant fourni (réponse générique uniforme), dans la continuité du `401` générique de #10.
- **Anti-abus** : la demande de code est **rate-limitée** (protection contre le flood d'OTP /
  « SMS bombing »), et le nombre d'essais de code est borné par la limite d'essais de l'OTP.
- **Aucune régression de secret** : mot de passe en clair, condensat, code OTP, numéro et e-mail ne
  sont **jamais journalisés ni renvoyés** (PRD §11.1/§11.3, invariants ADR-0012/0013).
- Respect de l'**architecture hexagonale** (ADR-0008) : cas d'usage dépendant de **ports** ; aucun
  couplage à FastAPI/SQLAlchemy/PyJWT/argon2 dans `domain/` et `application/`.
- **Pas de migration de schéma** si l'on retient le stockage OTP hors base (cohérent ADR-0012).

## Non-Goals

- **Envoi réel du code par SMS ou e-mail.** L'infra notifications (SMS) est livrée en **M5**
  (ADR-0006) ; l'e-mail transactionnel n'a **pas** d'ADR à ce jour. Comme en #8, l'acheminement reste
  un **stub no-op** (aucun envoi, aucune journalisation). Seul le **contrat de canal** est posé ici.
- **Révocation immédiate des sessions existantes** après reset (déconnexion serveur des jetons
  d'accès/refresh déjà émis). Le refresh est **stateless et non révocable** par choix d'ADR-0013 :
  invalider les jetons en cours nécessiterait un mécanisme de versionnement/révocation **hors scope**
  (voir *Risks and Open Questions*). Le critère « ancien mot de passe invalidé » porte sur le
  **mot de passe**, pas sur les jetons déjà en circulation.
- **Auto-connexion** après reset (émission d'une paire de jetons à la confirmation) : l'utilisateur se
  reconnecte via `POST /auth/login` avec son nouveau mot de passe.
- **Store OTP partagé/persistant** (Redis à TTL ou table dédiée) : différé (M5, cf. ADR-0004/0012),
  sauf décision contraire tranchée dans l'ADR d'accompagnement (voir *Open Questions*).
- **Changement de mot de passe par un utilisateur déjà connecté** (« change password » avec ancien
  mot de passe) : parcours distinct, non demandé par #11.
- **Politique de mot de passe renforcée** (complexité, historique de réutilisation) : on réutilise
  telle quelle la politique existante (`domain/password.py` : longueur 8–128).
- Toute évolution des **front-ends** (app-mobile Flutter, web-dashboard Next.js) : #11 porte sur
  l'API backend. L'intégration UI est un travail ultérieur.

## Relevant Repository Context

**Stack (figée par ADR) :** backend **Python ≥ 3.12 / FastAPI** (ADR-0003), **architecture
hexagonale** (ADR-0008), **PostgreSQL 16 + SQLAlchemy 2.0 / Alembic** (ADR-0009), **argon2id** pour le
hachage (ADR-0012), **PyJWT/HS256** pour les jetons (ADR-0013). Tests : `pytest` (test gate `#6`).

**Découpage hexagonal du backend (`backend/coiflink_api/`) :**

- `domain/` — pur, sans I/O :
  - `otp.py` — **réutilisable tel quel** : `OtpChallenge(code, expires_at, attempts_left, consumed)`,
    `OtpStatus` (`VALID` / `INVALID` / `EXPIRED` / `TOO_MANY_ATTEMPTS` / `ALREADY_CONSUMED`),
    `generate_otp_challenge(rng, now, *, length, ttl, max_attempts)` et
    `verify_otp_challenge(challenge, submitted_code, now)` (comparaison **temps constant**
    `hmac.compare_digest`, mutation en place : `consumed=True` sur succès, `attempts_left` décrémenté
    sur échec). Ne journalise jamais le code.
  - `password.py` — `validate_password` (8–128), `MIN_LENGTH` / `MAX_LENGTH`.
  - `identifier.py` — `classify_identifier(raw) -> LoginIdentifier(kind, value)` : `@` ⇒ e-mail
    (`strip`, casse conservée) ; sinon téléphone **E.164** via `normalize_phone`. Lève `InvalidPhone`
    pour un téléphone inexploitable. **Directement réutilisable** pour router le canal (phone→SMS,
    email→e-mail) et retrouver le compte.
  - `phone.py` — `normalize_phone` (forme canonique E.164).
  - `credentials.py` — `UserCredentials(id, role, status, password_hash)` (entité interne, jamais
    sérialisée).
  - `errors.py` — erreurs neutres : `InvalidOtp`, `OtpExpired` (déjà déclarées, encore inutilisées),
    `InvalidPassword`, `InvalidPhone`, `InvalidCredentials`, `TooManyLoginAttempts`, etc.
  - `enums.py` — `UserStatus.ACTIVE/INACTIVE/SUSPENDED`, `NotificationChannel.SMS/EMAIL/…`.
- `application/` — cas d'usage + `ports/` (`typing.Protocol`) :
  - `registration.py` (`RegisterUser`) — émet un OTP **non bloquant** via `_issue_otp(phone)` (RNG
    `SystemRandom` par défaut, horloge injectable). Modèle à suivre pour l'injection RNG/horloge.
  - `authentication.py` (`AuthenticateUser`, `RefreshTokens`) — anti-énumération (`InvalidCredentials`
    générique), atténuation d'oracle temporel (condensat *dummy*), anti-bruteforce via
    `LoginRateLimiter`.
  - `ports/` : `user_repository.py` (`phone_exists`, `create`, `find_by_phone`, `find_by_email`,
    `find_by_id` — **pas de méthode de mise à jour du mot de passe**), `password_hasher.py`
    (`hash`/`verify`), `otp_repository.py` (`save`/`get`/`delete`, **keyé par un `str` nommé `phone`**),
    `otp_sender.py` (`send(phone, code)` — **orienté SMS**, contrat « ne journalise jamais »),
    `token_service.py`, `login_rate_limiter.py` (`check`/`record_failure`/`reset`).
- `adapters/inbound/auth.py` — router FastAPI `/auth` : schémas Pydantic, injection de dépendances,
  traduction erreurs de domaine ⇒ codes HTTP. Helper `_client_ip(request)` (IP du pair direct),
  message générique `_INVALID_CREDENTIALS_DETAIL`.
- `adapters/outbound/`
  - `persistence/user_repository.py` (`SqlUserRepository`) — SQLAlchemy 2.0 ; `create` retraduit
    `IntegrityError` (`uq_users_phone`/`uq_users_email`) en erreurs de domaine ; `_to_credentials`
    mappe la ligne ORM → `UserCredentials`.
  - `persistence/models.py` — table `users` (`id` UUID, `phone` unique, `email` unique partiel,
    `password_hash`, `role`, `status`, `created_at`, `updated_at`). **Aucune table OTP.**
  - `security/otp_in_memory.py` (`InMemoryOtpRepository`) — `dict` de process, **non partagé, non
    persistant** ; stocke `OtpChallenge` **en clair en mémoire**.
  - `security/argon2_hasher.py`, `security/jwt_token_service.py`, `security/login_rate_limiter_memory.py`.
  - `notifications/otp_sender_stub.py` (`StubOtpSender`) — `send` no-op, aucune journalisation.
- `config.py` — `AuthConfig` + `load_auth_config(env)` (lecture d'environnement, défauts sûrs).
  Champs OTP existants : `otp_enabled` (**défaut `false`**), `otp_length`, `otp_ttl`,
  `otp_max_attempts`. **`OTP_ENABLED` ne gouverne que l'OTP optionnel d'inscription** — le reset ne
  doit **pas** en dépendre.
- `main.py` — composition root : dépose sur `app.state` `auth_config`, `otp_sender`,
  `otp_repository`, `login_rate_limiter`, `login_dummy_hash`, `token_service` (`None` si `JWT_SECRET`
  absent — les routes qui émettent des jetons répondent alors `503`).

**Tests (`backend/tests/`) :** `conftest.py` fournit des fakes (`FakeUserRepository`,
`FakeAuthUserRepository`, `FakeHasher`, `FakeOtpRepository`, `FakeOtpSender`, `FakeTokenService`,
`FakeLoginRateLimiter`). Patterns existants : `test_otp.py` (domaine OTP), `test_registration_usecase.py`,
`test_authentication_usecase.py`, `test_auth_api.py`, `test_login_api.py`, `test_login_e2e.py`
(pile complète PostgreSQL + argon2 + JWT réels, avec plage de téléphones réservée et nettoyage).

**Documentation de socle :** `README.md` (§4 stack), `backend/README.md`, `backend/.env.example`,
`docs/adr/` (index `README.md`), `prd-coiflink.md` (§11 sécurité). **Prochain n° d'ADR libre : 0014.**

**Statut :** aucune route ni cas d'usage de réinitialisation n'existe. Le domaine OTP, la politique de
mot de passe, la classification d'identifiant et le hacheur argon2 sont **présents et réutilisables**.

## Proposed Implementation

Parcours **en deux étapes**, entièrement adossé aux ports existants (plus deux petites extensions). Le
cas d'usage reste **pur** (aucun import framework) ; RNG (`SystemRandom` par défaut) et horloge sont
**injectables** comme dans `RegisterUser`.

### 1. Domaine (`coiflink_api/domain/`) — réutilisation, très peu de nouveau code

- **Réutiliser** `otp.py` sans modification : `generate_otp_challenge` (usage unique + expiration +
  limite d'essais) et `verify_otp_challenge` (temps constant). Ce module **couvre déjà** le critère
  « OTP à usage unique et expirant ».
- **Réutiliser** `identifier.classify_identifier` pour :
  (a) déterminer le **canal** (`EMAIL` ⇒ e-mail, `PHONE` ⇒ SMS) et
  (b) retrouver le compte (`find_by_email` / `find_by_phone`) et calculer la **clé de stockage OTP**
  (valeur normalisée).
- **Réutiliser** `password.validate_password` pour le nouveau mot de passe.
- `errors.py` : réutiliser `InvalidOtp` / `OtpExpired` (déjà présents). Au niveau HTTP, **tous** les
  échecs d'OTP (invalide, expiré, trop d'essais, déjà consommé, ou aucun défi) sont fusionnés en une
  **réponse générique unique** (anti-énumération). Optionnel : ajouter une erreur neutre
  `PasswordResetChallengeNotFound` **uniquement** si utile en interne — elle ne doit jamais changer la
  réponse HTTP par rapport à un code faux.

### 2. Application — nouveau module `application/password_reset.py`

Deux cas d'usage (ou une classe à deux méthodes), dépendant uniquement de ports :

```
RequestPasswordReset(
    repository: UserRepository,
    otp_repository: OtpRepository,           # instance dédiée « reset »
    otp_sender: OtpSender,                    # router SMS/e-mail (stub)
    *, rng=SystemRandom(), clock=_utc_now,
    otp_length, otp_ttl, otp_max_attempts,
)
ConfirmPasswordReset(
    repository: UserRepository,
    otp_repository: OtpRepository,
    hasher: PasswordHasher,
    *, clock=_utc_now,
)
```

Commandes (`@dataclass(frozen=True)`, mot de passe en clair éphémère) :

- `PasswordResetRequestCommand(identifier: str, client_ip: str | None = None)`
- `PasswordResetConfirmCommand(identifier: str, code: str, new_password: str)`

**`RequestPasswordReset.execute(cmd)` (idempotent côté réponse) :**
1. `raw = cmd.identifier.strip()` ; classer via `classify_identifier` (gérer `InvalidPhone`/vide en
   **silence** — mêmes suites qu'un identifiant inconnu, aucune divulgation).
2. Rechercher le compte (`find_by_email` / `find_by_phone`). **Si absent ou non `ACTIVE`** : ne rien
   stocker/envoyer et **retourner normalement** (la route répond le même 202 générique).
3. Sinon : `challenge = generate_otp_challenge(rng, clock(), length=…, ttl=…, max_attempts=…)`.
4. `otp_repository.save(key, challenge)` avec `key` = valeur normalisée (E.164 ou e-mail). Un nouvel
   appel **remplace** le défi précédent (invalide un code antérieur non encore utilisé).
5. `otp_sender.send(recipient=key, code=challenge.code, channel=<SMS|EMAIL>)` (stub). **Ne jamais**
   retourner ni journaliser le code.
6. Ne renvoie **aucune** donnée sensible (idéalement `None`).

**`ConfirmPasswordReset.execute(cmd)` :**
1. `validate_password(cmd.new_password)` ⇒ lève `InvalidPassword` (⇒ 422). *(Ne divulgue pas
   l'existence du compte : porte sur la politique, pas sur le compte.)*
2. Classer l'identifiant (échecs de classification traités comme « pas de défi »).
3. `challenge = otp_repository.get(key)`. **Si `None`** ⇒ lever `InvalidOtp` (⇒ 400 générique).
4. `status = verify_otp_challenge(challenge, cmd.code, clock())` :
   - `VALID` : continuer ; le défi est marqué `consumed` (mutation en place).
   - sinon (`INVALID`/`EXPIRED`/`TOO_MANY_ATTEMPTS`/`ALREADY_CONSUMED`) :
     **persister l'état muté** (`otp_repository.save(key, challenge)` pour matérialiser la décrémente
     d'essais sur `INVALID`) puis lever `InvalidOtp` (⇒ 400 générique). *(Un seul et même 400 pour
     tous les cas — pas d'oracle sur la cause exacte.)*
5. Retrouver le compte (`find_by_email`/`find_by_phone`) pour obtenir `UserCredentials.id`. Si
   introuvable/non `ACTIVE` (course rare) ⇒ 400 générique (supprimer le défi).
6. `new_hash = hasher.hash(cmd.new_password)`.
7. `repository.update_password(user_id, new_hash)` (nouvelle méthode — voir §Ports).
8. `otp_repository.delete(key)` (usage unique **garanti** par suppression après succès).
9. Retour sans secret. **Effet net : l'ancien mot de passe ne s'authentifie plus** (critère #11).

> **Usage unique — double garantie** : `verify_otp_challenge` refuse un `challenge.consumed`
> (`ALREADY_CONSUMED`) **et** le défi est **supprimé** du dépôt après succès. Un code rejoué renvoie
> le 400 générique.

### 3. Ports (`application/ports/`) — deux extensions minimes

- **`UserRepository`** : ajouter
  `update_password(self, user_id: uuid.UUID | str, new_password_hash: str) -> None`
  (met à jour `password_hash` ; bump implicite d'`updated_at`). Documenter l'invariant « ne reçoit
  qu'un condensat, jamais un mot de passe en clair ».
- **`OtpSender`** : généraliser la remise multi-canal. Recommandation : faire évoluer la signature
  vers `send(recipient: str, code: str, channel: str) -> None` (avec `channel ∈ NotificationChannel`
  `SMS`/`EMAIL`) **et** mettre à jour l'unique appelant existant (`RegisterUser._issue_otp` → `channel=SMS`).
  *Alternative moins intrusive :* garder `send(phone, code)` pour l'inscription et introduire un port
  distinct `OtpDelivery`/second adapter e-mail. **Décision à confirmer** (voir *Open Questions*).
- **`OtpRepository`** : le contrat `save/get/delete(str, …)` convient tel quel. Pour lever l'ambiguïté
  sémantique, **renommer le paramètre `phone` → `key`** (ou `recipient`) dans le port, l'adapter en
  mémoire et l'appelant d'inscription (refactor purement nominal, comportement inchangé).

### 4. Adapters sortants (`adapters/outbound/`)

- **Dépôt OTP de reset dédié** : réutiliser `InMemoryOtpRepository` **en tant qu'instance séparée**
  (`app.state.password_reset_otp_repository`) pour que **jamais** un OTP d'inscription ne puisse servir
  à un reset (ni l'inverse). Alternative : préfixer les clés (`pwreset:<identifier>`). L'instance
  dédiée est préférée (séparation physique claire).
- **Remise multi-canal (stub)** : selon la décision §3, soit un `StubOtpSender` qui ignore le
  `channel`, soit deux stubs (`StubSmsOtpSender`, `StubEmailOtpSender`) routés par le canal. Dans tous
  les cas : **no-op, aucune journalisation** (contrat de sécurité).
- **`SqlUserRepository.update_password`** : `UPDATE users SET password_hash=:h WHERE id=:id` via
  `session.get`/`update` (SQLAlchemy 2.0) ; commit piloté par la dépendance de session
  (`get_session`). Idempotent si l'`id` n'existe pas (0 ligne) — le cas d'usage a déjà vérifié l'OTP.

### 5. Adapter entrant (`adapters/inbound/auth.py` — modifier)

Ajouter **deux routes** + schémas Pydantic + assemblage par injection de dépendances (analogue à
`get_authenticate_user` / `get_login_rate_limiter`). Aucune règle métier dans la route : uniquement
traduction commande ⇄ HTTP.

- `POST /auth/password/reset/request` — corps `PasswordResetRequestSchema { identifier }` ;
  **toujours** `202 Accepted` + message générique, y compris compte inexistant ; `429` + `Retry-After`
  si rate-limité.
- `POST /auth/password/reset/confirm` — corps
  `PasswordResetConfirmSchema { identifier, code, new_password }` ; `200 OK` (ou `204`) générique ;
  `422` si `InvalidPassword` ; `400` **générique** pour tout échec d'OTP (`InvalidOtp`/`OtpExpired`) et
  identifiant inconnu.

Détails :
- `new_password` : `min_length=MIN_LENGTH`, `max_length=MAX_LENGTH` (comme `RegisterRequest`).
- `code` : `min_length=1` (jamais la longueur exacte, pour ne pas divulguer la politique OTP).
- Réutiliser `_client_ip(request)` pour la clé de rate-limit.
- Ces routes **ne dépendent pas** de `token_service` : elles fonctionnent même si `JWT_SECRET` est
  absent (pas de `503`, contrairement à `/auth/login`).

### 6. Anti-abus (rate-limit de la demande)

Réutiliser le **port `LoginRateLimiter`** (implémentation en mémoire) via une **instance dédiée**
`app.state.password_reset_rate_limiter`, clé = `identifiant normalisé + IP` (comme #10). `check` avant
tout accès base ; `record_failure`/incrément à chaque demande ; `429 + Retry-After` au seuil. La
confirmation est bornée par la **limite d'essais de l'OTP** (`attempts_left`) ; on peut optionnellement
la protéger aussi par un limiteur. Seuils configurables (réutiliser les défauts login ou introduire des
`PASSWORD_RESET_*`).

### 7. Configuration (`config.py`) & composition root (`main.py`) — modifier

- `AuthConfig` : réutiliser `otp_length`/`otp_ttl`/`otp_max_attempts` pour le reset (l'OTP de reset est
  **toujours actif**, indépendant de `otp_enabled`). Optionnel : `PASSWORD_RESET_OTP_TTL_SECONDS`,
  `PASSWORD_RESET_OTP_MAX_ATTEMPTS`, `PASSWORD_RESET_MAX_ATTEMPTS`/`_WINDOW_SECONDS`/`_LOCKOUT_SECONDS`
  pour un réglage indépendant (défauts sûrs si absents).
- `main.py` : déposer `app.state.password_reset_otp_repository` (instance dédiée),
  `app.state.password_reset_rate_limiter`, et le(s) sender(s) de reset. **Aucun secret en dur.**

## Affected Files / Packages / Modules

**À lire (contexte) :** `backend/coiflink_api/domain/otp.py`, `.../domain/identifier.py`,
`.../domain/password.py`, `.../domain/credentials.py`, `.../domain/errors.py`, `.../domain/enums.py`,
`.../application/registration.py`, `.../application/authentication.py`, `.../adapters/inbound/auth.py`,
`.../adapters/outbound/persistence/user_repository.py`, `.../adapters/outbound/security/otp_in_memory.py`,
`.../adapters/outbound/notifications/otp_sender_stub.py`, `.../config.py`, `.../main.py`,
`backend/tests/conftest.py`, `backend/tests/test_login_e2e.py`, ADR-0012, ADR-0013.

**À créer :**
- `backend/coiflink_api/application/password_reset.py` — `RequestPasswordReset`,
  `ConfirmPasswordReset`, commandes.
- (Selon décision) `backend/coiflink_api/adapters/outbound/notifications/` — stub(s) e-mail/multi-canal.
- `backend/tests/test_password_reset_usecase.py` — cas d'usage (fakes).
- `backend/tests/test_password_reset_api.py` — routes HTTP (TestClient + overrides).
- `backend/tests/test_password_reset_e2e.py` — pile complète (PostgreSQL + argon2), *skip* sans
  `DATABASE_URL` (modèle `test_login_e2e.py`).
- `docs/adr/0014-reinitialisation-mot-de-passe-otp.md` — décisions (voir Documentation Updates).

**À modifier :**
- `backend/coiflink_api/adapters/inbound/auth.py` — 2 routes, schémas, DI, mapping d'erreurs.
- `backend/coiflink_api/application/ports/user_repository.py` — `update_password`.
- `backend/coiflink_api/application/ports/otp_sender.py` — signature multi-canal (si retenu) + doc.
- `backend/coiflink_api/application/ports/otp_repository.py` — renommage nominal `phone`→`key` (si retenu).
- `backend/coiflink_api/adapters/outbound/persistence/user_repository.py` — `update_password`.
- `backend/coiflink_api/adapters/outbound/security/otp_in_memory.py` — renommage nominal (si retenu).
- `backend/coiflink_api/adapters/outbound/notifications/otp_sender_stub.py` — canal (si retenu).
- `backend/coiflink_api/application/registration.py` — adapter l'appel `otp_sender.send(…, channel=SMS)`
  si la signature change.
- `backend/coiflink_api/config.py` — champs de reset (optionnels).
- `backend/coiflink_api/main.py` — câblage des instances dédiées de reset.
- `backend/tests/conftest.py` — ajouter `update_password` aux fakes de dépôt ; adapter `FakeOtpSender`
  au canal si la signature change.
- `backend/README.md`, `backend/.env.example`, `docs/adr/README.md` — doc (voir plus bas).

## API / Interface Changes

Deux **nouveaux endpoints REST** sous le router `/auth` existant. Documentés via schémas Pydantic
(OpenAPI auto-générée, ADR-0003). Aucune réponse ne transporte de secret ni de PII inutile.

**`POST /auth/password/reset/request`**
- Corps : `{ "identifier": "<téléphone ou e-mail>" }`
- `202 Accepted` (**toujours**, y compris identifiant inconnu) :
  `{ "detail": "Si un compte correspond à cet identifiant, un code de réinitialisation a été envoyé." }`
- `429 Too Many Requests` (+ en-tête `Retry-After`) si rate-limité — message générique.
- `422` uniquement pour un corps structurellement invalide (validation Pydantic : champ manquant).

**`POST /auth/password/reset/confirm`**
- Corps : `{ "identifier": "…", "code": "123456", "new_password": "<nouveau>" }`
- `200 OK` (ou `204 No Content`) : `{ "detail": "Mot de passe réinitialisé." }`
- `400 Bad Request` **générique** : `{ "detail": "Code de réinitialisation invalide ou expiré." }`
  pour **tout** échec d'OTP (invalide, expiré, trop d'essais, déjà consommé) **et** identifiant sans
  défi (anti-énumération : cause exacte jamais divulguée).
- `422 Unprocessable Entity` si le **nouveau mot de passe** viole la politique (`InvalidPassword`).

Le reste de la surface d'auth (`/auth/register*`, `/auth/login`, `/auth/refresh`) est **inchangé**.
Aucun changement CLI. Contrats de **ports** modifiés en interne (`UserRepository.update_password`,
`OtpSender.send(recipient, code, channel)` et renommage `OtpRepository` — non publics hors backend).

## Data Model / Protocol Changes

**Aucune migration de schéma** dans l'approche recommandée :

- Le reset **réécrit** la colonne existante `users.password_hash` (et bump `updated_at`) — pas de
  nouvelle colonne ni table.
- Le défi OTP reste **hors schéma relationnel** (dépôt en mémoire dédié), cohérent avec ADR-0012
  (« aucune migration »). Le code n'est **jamais** persisté en base.

**Décisions différées / conditionnelles** (⇒ migration seulement si retenues, voir *Open Questions*) :
- **Store OTP persistant/partagé** (Redis à TTL ou table `password_reset_otp`) — requis pour la
  fiabilité multi-instances (voir Risks) ; une table imposerait une migration Alembic.
- **Invalidation des jetons existants** — un `users.password_changed_at` (ou `token_version`) et sa
  vérification dans les claims imposeraient une **migration** + coordination avec le middleware RBAC
  (#12). **Hors scope #11**, mais à trancher explicitement.

## Security & Privacy Considerations

Contraintes documentées touchées (PRD §11.1/§11.3, ADR-0012/0013) — **à préserver, jamais affaiblir** :

- **Ne jamais journaliser ni renvoyer** : mot de passe en clair, `password_hash`, **code OTP**,
  numéro de téléphone, e-mail. Le clair ne vit que le temps de `validate_password`/`hash`. Les
  senders (stub) **ne journalisent rien** (contrat `OtpSender`). Les messages d'erreur de domaine ne
  portent aucun secret.
- **OTP à usage unique et expirant** : garanti par `verify_otp_challenge` (consommation + `expires_at`
  + `attempts_left`, comparaison **temps constant** `hmac.compare_digest`) **et** par la suppression du
  défi après succès. Un nouveau défi **écrase** le précédent (invalidation implicite).
- **Anti-énumération** (continuité du `401` générique de #10) :
  - *Demande* : réponse **202 uniforme**, qu'un compte existe ou non ; ne jamais confirmer/infirmer
    l'existence, ni via le corps, ni via le code de statut.
  - *Confirmation* : **un seul 400 générique** pour tout échec d'OTP et pour un identifiant sans défi.
  - *Atténuation d'oracle temporel* (recommandé) : à la demande, égaliser grossièrement le temps
    de réponse même quand aucun compte ne correspond (analogue au condensat *dummy* de #10) —
    p. ex. générer un défi jeté. À défaut, documenter la limite (rigueur *constant-time* non garantie).
- **Séparation des usages** : l'OTP de reset vit dans un **dépôt dédié** ; impossible de réutiliser un
  OTP d'inscription pour reset (ou l'inverse).
- **Anti-abus / anti-flood** : la demande est **rate-limitée** (identifiant + IP) pour éviter le
  « SMS/e-mail bombing » et le brute-force d'OTP. La confirmation est bornée par `attempts_left`.
- **Portée de « mot de passe invalidé »** : le reset **remplace** le condensat ⇒ l'ancien mot de passe
  est refusé à la connexion. **Limite assumée (ADR-0013)** : les **jetons déjà émis restent valides**
  jusqu'à expiration (refresh stateless non révocable). À **documenter** ; ne **pas** laisser croire à
  une déconnexion immédiate. Réduction du risque : TTL d'accès court (15 min) + reset qui empêche toute
  **nouvelle** connexion avec l'ancien secret. Invalidation immédiate ⇒ suivi (voir Open Questions).
- **Comptes non `ACTIVE`** : un compte `INACTIVE`/`SUSPENDED` ne reçoit pas d'OTP et ne peut pas être
  réinitialisé (traité comme inexistant côté réponse — pas de divulgation).
- **Transport** : Bearer/HTTPS (terminaison TLS Railway, ADR-0011). Le canal e-mail réel devra
  respecter la même exigence de non-journalisation à l'arrivée de l'infra (M5).
- **Secrets de config** : aucun secret en dur ; toute nouvelle variable suit la politique
  `docs/environnements-et-secrets.md` (ADR-0011). Les endpoints de reset **ne dépendent pas** de
  `JWT_SECRET`.

## Testing Plan

Aligné sur le test gate `#6` (`pytest`) et les patterns existants.

**Domaine (`test_otp.py` — déjà couvert, vérifier/compléter) :** longueur, expiration, usage unique,
limite d'essais, comparaison temps constant. (Aucun nouveau code de domaine attendu.)

**Cas d'usage (`test_password_reset_usecase.py`, fakes) :**
- *Demande* : compte téléphone existant ⇒ défi stocké (clé E.164) + `send` appelé (canal `SMS`) ;
  compte e-mail existant ⇒ défi + `send` (canal `EMAIL`) ; **compte inexistant / non `ACTIVE`** ⇒
  **aucun** `save`/`send` **mais retour normal** ; identifiant vide/malformé ⇒ pas d'erreur divulgante ;
  une nouvelle demande **remplace** le défi précédent.
- *Confirmation* : code correct ⇒ `update_password(new_hash)` appelé **et** défi **supprimé** ;
  ancien condensat remplacé (assert nouveau `hash:` via `FakeHasher`) ; code faux ⇒ `InvalidOtp`, essais
  décrémentés **persistés**, `update_password` **non** appelé ; code expiré (horloge injectée > `ttl`)
  ⇒ `InvalidOtp` ; **réutilisation** d'un code déjà consommé ⇒ `InvalidOtp` (usage unique) ; dépassement
  d'essais ⇒ `InvalidOtp` ; identifiant **sans défi** ⇒ `InvalidOtp` (même chemin qu'un code faux) ;
  nouveau mot de passe hors politique ⇒ `InvalidPassword`, `update_password` **non** appelé, code non
  journalisé.

**API (`test_password_reset_api.py`, TestClient + `dependency_overrides`) :**
- `request` : `202` pour compte connu **et** inconnu (corps **identique**) ; `429` + `Retry-After`
  au seuil du limiteur ; le corps de réponse **ne contient pas** l'identifiant/numéro.
- `confirm` : `200`/`204` sur code valide ; `400` **générique** pour code faux / expiré / réutilisé /
  identifiant inconnu (message identique, cause non divulguée) ; `422` pour mot de passe trop court ;
  aucune réponse ne contient le code OTP ni le mot de passe.

**E2E (`test_password_reset_e2e.py`, PostgreSQL + argon2 réels ; *skip* sans `DATABASE_URL`) :**
Modèle `test_login_e2e.py` (plage de téléphones réservée, nettoyage avant/après). Pour piloter le code
sans SMS réel, capturer le défi via un dépôt OTP réel injecté sur `app.state` (ou un `FakeOtpSender`
qui enregistre le code) :
- **Parcours complet téléphone** : register → request → lire le code (dépôt/sender de test) → confirm →
  **`login` avec l'ancien mot de passe ⇒ `401`** et **`login` avec le nouveau ⇒ `200`** (assert direct
  du critère « ancien mot de passe invalidé »).
- **Parcours complet e-mail** : idem via l'identifiant e-mail.
- **Usage unique bout en bout** : rejouer le même code après succès ⇒ `400`.
- **Expiration bout en bout** : horloge/`ttl` court ⇒ `400`.
- *(Documenté, non testé comme un succès)* : un jeton d'accès émis **avant** le reset **reste** décodable
  jusqu'à `exp` — refléter la limite ADR-0013 (ne pas asserter une révocation inexistante).

**Résilience / doc :** vérifier via `test_secrets_policy.py` (ou équivalent) qu'aucun log ne contient
code/mot de passe/PII ; s'assurer que le round-trip Alembic reste vert **si** aucune migration n'est
ajoutée (approche recommandée).

## Documentation Updates

- **`docs/adr/0014-reinitialisation-mot-de-passe-otp.md`** (nouveau) — acter : réutilisation du domaine
  OTP (ADR-0012) et des ports d'auth ; parcours **request/confirm** ; **anti-énumération** ; **dépôt OTP
  dédié** ; **OTP bloquant** (vs non bloquant à l'inscription) et **indépendant d'`OTP_ENABLED`** ;
  **canal e-mail** (stub, réel différé M5, hors ADR-0006) ; **pas de migration** ; **limite de
  non-révocation des jetons** (renvoi ADR-0013) et suivi (`password_changed_at`/`token_version`).
- **`docs/adr/README.md`** — ajouter la ligne d'index 0014 (issue #11) et, le cas échéant, mentionner en
  « Décisions différées » : store OTP Redis/persistant et invalidation immédiate des jetons.
- **`backend/README.md`** — documenter les deux endpoints (corps, codes de statut, comportement
  anti-énumération) aux côtés de `login`/`refresh`.
- **`backend/.env.example`** — ajouter (commentées) les éventuelles variables `PASSWORD_RESET_*` et
  préciser que le reset **ne dépend pas** d'`OTP_ENABLED` ni de `JWT_SECRET` ; envoi réel *stub* (M5).
- **`prd-coiflink.md`** — aucune modification nécessaire (le PRD §11.1 couvre déjà « réinitialisation
  par OTP ») ; ne pas dupliquer.

## Risks and Open Questions

1. **Non-révocation des jetons existants (sécurité).** Après reset, les jetons d'accès/refresh déjà
   émis **restent valides** (refresh stateless, ADR-0013). Le critère #11 (« ancien mot de passe
   invalidé ») est satisfait au sens strict, mais une invalidation **complète** des sessions demande un
   mécanisme de versionnement (`password_changed_at`/`token_version` + vérification dans les claims,
   coordonné avec le RBAC #12) ⇒ **migration** et travail hors scope. **À confirmer** : accepter la
   limite en M1 (documentée) ou l'inclure ? *Recommandation : accepter + suivi explicite.*
2. **Store OTP en mémoire pour un OTP bloquant (fiabilité).** Contrairement à l'OTP d'inscription (non
   bloquant), le reset **dépend** de l'OTP. Un dépôt en mémoire n'est **ni partagé entre workers/
   instances ni persistant** : un code émis sur une instance peut être invérifiable sur une autre, ou
   perdu au redéploiement. Acceptable en dev/mono-instance ; **risque réel en multi-instances**.
   **À confirmer** : Redis à TTL (ADR-0004, déjà provisionné) dès #11, ou différé M5 avec limite
   documentée ? *Recommandation : câbler Redis si le staging est multi-instances ; sinon documenter.*
3. **Canal e-mail non tranché par un ADR.** ADR-0006 couvre FCM + SMS, **pas** l'e-mail transactionnel.
   L'issue demande « SMS **ou** e-mail ». **À confirmer** : fournisseur e-mail et surface de secrets
   (différés M5) ; d'ici là, stub. À acter dans l'ADR-0014.
4. **Forme du port `OtpSender`.** Généraliser `send(recipient, code, channel)` (impacte l'appelant
   d'inscription) **ou** introduire un port/adapter e-mail distinct ? *Recommandation : signature
   multi-canal (une seule abstraction), refactor minime de l'appelant d'inscription.*
5. **Nommage `OtpRepository.phone` → `key`/`recipient`.** Refactor nominal souhaitable (le reset keye
   par e-mail aussi) ; sans risque comportemental mais touche l'adapter et l'appelant d'inscription.
   *Recommandation : renommer.*
6. **Réponse de la confirmation.** `200 { detail }` vs `204 No Content` ? *Recommandation : `200` avec
   message générique, cohérent avec les autres routes d'auth.*
7. **Atténuation d'oracle temporel à la demande.** Faut-il générer un défi « jeté » pour un compte
   inexistant afin d'égaliser le temps de réponse ? *Recommandation : oui si peu coûteux ; sinon
   documenter la limite (comme le condensat *dummy* de #10).*
8. **Réglages dédiés vs réutilisation.** TTL/essais/seuils de reset propres (`PASSWORD_RESET_*`) ou
   réutilisation des valeurs OTP/login existantes ? *Recommandation : réutiliser par défaut, variables
   dédiées optionnelles.*
9. **Normalisation e-mail insensible à la casse.** Comme #10, la casse de l'e-mail est **conservée** ;
   un e-mail saisi avec une casse différente de l'inscription ne trouvera pas le compte (⇒ 202/400
   générique). Limite déjà connue (ADR-0013), à ne pas régler ici.

## Implementation Checklist

1. **Lire** ADR-0012, ADR-0013, `domain/otp.py`, `domain/identifier.py`, `application/registration.py`,
   `adapters/inbound/auth.py`, `test_login_e2e.py` — confirmer les invariants (anti-énumération,
   non-journalisation, RNG/horloge injectés).
2. **Trancher les Open Questions** 1–8 (idéalement dans l'ADR-0014) avant de coder les contrats de ports.
3. **Ports** : ajouter `UserRepository.update_password(user_id, new_password_hash)` ; faire évoluer
   `OtpSender.send(recipient, code, channel)` (+ doc) ; renommer `OtpRepository` param `phone`→`key`.
4. **Application** : créer `application/password_reset.py` (`RequestPasswordReset`,
   `ConfirmPasswordReset`, commandes) — pur, RNG `SystemRandom` + horloge injectables ; réutiliser
   `classify_identifier`, `generate_otp_challenge`/`verify_otp_challenge`, `validate_password`. Aucun
   secret journalisé.
5. **Adapters sortants** : implémenter `SqlUserRepository.update_password` ; instancier un dépôt OTP de
   reset dédié (`InMemoryOtpRepository`) ; fournir le(s) sender(s) stub multi-canal (no-op, no-log).
   Adapter l'appel `otp_sender.send(…, channel=SMS)` dans `RegisterUser._issue_otp`.
6. **Adapter entrant** : ajouter `POST /auth/password/reset/request` (202 générique, 429) et
   `POST /auth/password/reset/confirm` (200 ; 400 générique unifié ; 422 politique de mot de passe) ;
   schémas Pydantic ; DI (`get_*`), `_client_ip` ; **pas** de dépendance à `token_service`.
7. **Config & composition root** : (optionnel) champs `PASSWORD_RESET_*` dans `AuthConfig` /
   `load_auth_config` ; déposer sur `app.state` le dépôt OTP de reset, le rate-limiter de reset et le(s)
   sender(s). Le reset **ne lit pas** `OTP_ENABLED`.
8. **Anti-abus** : brancher le rate-limiter de reset (clé identifiant+IP) sur la route `request` ;
   `429 + Retry-After` au seuil.
9. **Tests** : conftest (ajouter `update_password` aux fakes, adapter `FakeOtpSender` au canal) ;
   `test_password_reset_usecase.py`, `test_password_reset_api.py`, `test_password_reset_e2e.py`
   (couvrir : parcours complet phone **et** e-mail, ancien mot de passe ⇒ 401 / nouveau ⇒ 200, usage
   unique, expiration, limite d'essais, anti-énumération 202/400 uniformes, non-journalisation).
10. **Documentation** : rédiger `docs/adr/0014-…md` ; indexer dans `docs/adr/README.md` ; documenter
    les endpoints dans `backend/README.md` ; compléter `backend/.env.example`.
11. **Vérifier** : `ruff check` + `pytest` verts (test gate `#6`) ; round-trip Alembic **inchangé** si
    aucune migration (approche recommandée) ; relire les diffs pour s'assurer qu'**aucun** log/retour ne
    contient code OTP, mot de passe, condensat ni PII.
