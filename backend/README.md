# backend/ — API CoifLink (FastAPI)

API REST du backend CoifLink, conformément à **[ADR-0003](../docs/adr/0003-backend-fastapi.md)**
(FastAPI · Python · REST + JWT). Le socle (issues #2–#6) installe l'architecture hexagonale,
la CI, le schéma PostgreSQL et la politique de secrets. L'**inscription client** (US-1.1, #8),
l'**inscription gérant** (#9, compte propriétaire de salon) et la **connexion JWT** (US-1.2, #10 —
émission d'un jeton d'accès + refresh, anti-bruteforce) sont les premières fonctionnalités M1 livrées
(salons, RDV, caisse… continuent en M1→).

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
coiflink_api/
  domain/         # entités & règles métier (zéro dépendance framework/I/O)
  application/    # cas d'usage
    ports/        # interfaces (typing.Protocol)
  adapters/
    inbound/      # driving : routers HTTP FastAPI (ex. health.py → /health)
    outbound/     # driven : Postgres, Redis, S3, FCM/SMS (implémentent les ports)
  main.py         # composition root : assemble l'app + monte les routers
```

La dépendance va toujours **vers l'intérieur** ; toute brique externe passe par un
**port** + un adapter sortant (jamais d'import direct d'un client d'infra depuis le domaine).

## Prérequis

- **Python ≥ 3.12** (version de référence figée par #2 — cf. [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md)).

## Installation (environnement isolé)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dev]"            # installe l'API + les outils de test
```

## Lancement (dev)

```bash
cp .env.example .env               # ignoré par git ; renseigner localement (aucun secret committé)
uvicorn coiflink_api.main:app --reload
```

L'API écoute alors sur `http://127.0.0.1:8000`. Endpoint de santé :

```bash
curl http://127.0.0.1:8000/health   # -> {"status":"ok"}
```

## Build & test

| Action | Commande |
| --- | --- |
| **Build** (installation du paquet) | `pip install -e .` |
| **Test** (test gate, cf. #6) | `pytest` |
| **Lint** (CI #4, cf. [ADR-0010](../docs/adr/0010-ci-cd-docker-packaging.md)) | `ruff check .` (installé via l'extra `dev`) |
| **Image Docker** (build-seul en CI ; config par env, non-root) | `docker build -t coiflink-backend ./backend` |

## Endpoints

| Méthode | Chemin | Réponse | Rôle |
| --- | --- | --- | --- |
| `GET` | `/health` | `{"status":"ok"}` | Sonde de santé (adapter entrant `adapters/inbound/health.py`) — aucune logique métier |
| `POST` | `/auth/register` | `201` + utilisateur (sans secret) | Inscription client (US-1.1, #8) — voir ci-dessous |
| `POST` | `/auth/register/manager` | `201` + utilisateur (sans secret) | Inscription gérant (compte propriétaire de salon, #9) — voir ci-dessous |
| `POST` | `/auth/login` | `200` + paire de jetons | Connexion (téléphone **ou** e-mail + mot de passe, US-1.2, #10) — voir ci-dessous |
| `POST` | `/auth/refresh` | `200` + paire de jetons | Rafraîchit le jeton d'accès depuis un refresh valide (#10) — voir ci-dessous |
| `POST` | `/auth/password/reset/request` | `202` + message générique | Demande un code de réinitialisation (SMS **ou** e-mail, US-1.3, #11) — voir ci-dessous |
| `POST` | `/auth/password/reset/confirm` | `200` + message générique | Confirme la réinitialisation (code + nouveau mot de passe, #11) — voir ci-dessous |

## Authentification — inscription client (US-1.1, #8)

`POST /auth/register` crée un **compte client** (`role=CLIENT`, `status=ACTIVE`) à partir d'un
**nom**, d'un **numéro de téléphone** et d'un **mot de passe** (e-mail optionnel). Adapter entrant :
`adapters/inbound/auth.py` ; cas d'usage : `application/registration.py` (architecture hexagonale,
[ADR-0008](../docs/adr/0008-architecture-hexagonale.md)). Décisions de sécurité actées par
**[ADR-0012](../docs/adr/0012-hachage-argon2-strategie-otp.md)**.

- **Requête** (JSON) : `full_name` (requis), `phone` (requis), `password` (requis, ≥ 8 caractères),
  `email` (optionnel).
- **`201 Created`** : `{ id, full_name, phone, email, role, status, created_at }`. La réponse
  n'expose **jamais** `password` ni `password_hash`.
- **`409 Conflict`** : le numéro de téléphone (ou l'e-mail) est **déjà inscrit** (doublon refusé).
- **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/e-mail invalides, champ manquant).

L'inscription **n'émet aucun JWT** (la connexion est l'issue #10).

**Sécurité & vie privée :**
- **Mot de passe jamais en clair** : haché par **argon2id** (`argon2-cffi`, pas de troncature 72 octets)
  derrière le port `PasswordHasher`. Le clair n'est **ni journalisé ni renvoyé**.
- **Normalisation du téléphone** en **E.164** (indicatif Côte d'Ivoire `+225` par défaut) : garantit
  l'unicité (`uq_users_phone`) — sans forme canonique, le refus de doublon serait contournable.
- **Refus de doublon** garanti à deux niveaux : pré-vérification applicative **et** contrainte base
  (course concurrente retraduite en `409`).
- **OTP** : logique de génération/vérification **pure et testable** (RNG + horloge injectés, usage
  unique, expiration, limite d'essais). **Désactivé par défaut** (`OTP_ENABLED=false`) ; l'envoi SMS
  réel est **différé** à M5 ([ADR-0006](../docs/adr/0006-notifications-fcm-sms.md)) — l'adapter de #8
  est un **stub** qui ne journalise rien. Le code OTP n'est **jamais** renvoyé ni journalisé.
- **PII** (`full_name`, `phone`, `email`) et secrets ne sont **jamais** journalisés (PRD §11.1/§11.3).

## Authentification — inscription gérant (#9)

`POST /auth/register/manager` crée un **compte propriétaire de salon** (`role=MANAGER`,
`status=ACTIVE`) à partir des **mêmes champs** que l'inscription client (**nom**, **téléphone**,
**mot de passe** ; e-mail optionnel). C'est le **prérequis** de la création d'un salon (US-2.1, #15) :
une fois inscrit, le gérant est **prêt à créer son salon** (rattachement `salons.owner_id` traité
par #15). L'inscription est **self-service** et **n'émet aucun JWT** (la connexion est l'issue #10).

Le cas d'usage `application/registration.py` est **généralisé** en `RegisterUser` paramétré par le
rôle ; l'inscription client reste la spécialisation `RegisterClient` (`role=CLIENT`). L'adapter
entrant réutilise les schémas `RegisterRequest`/`UserResponse` de #8.

- **Requête** (JSON) : `full_name` (requis), `phone` (requis), `password` (requis, ≥ 8 caractères),
  `email` (optionnel). **Aucun champ `role`.**
- **`201 Created`** : `{ id, full_name, phone, email, role: "MANAGER", status, created_at }`. La
  réponse n'expose **jamais** `password` ni `password_hash`.
- **`409 Conflict`** : le numéro de téléphone (ou l'e-mail) est **déjà inscrit** — quel que soit le
  rôle du compte existant (doublon refusé, `uq_users_phone`).
- **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/e-mail invalides, champ manquant).

**Sécurité :** le **rôle `MANAGER` est attribué côté serveur**, jamais lu depuis la requête — aucun
champ `role` public n'est déclaré, donc **pas d'élévation de privilège** possible via l'inscription
(un `role` envoyé dans le corps est ignoré). Le rôle `MANAGER` seul ne confère **aucun** accès à des
données d'un autre salon : le RBAC et l'isolation par salon arrivent avec #12. Toutes les autres
garanties de l'inscription client s'appliquent à l'identique (hachage argon2id, normalisation E.164
du téléphone, refus de doublon à deux niveaux, non-journalisation des secrets/PII).

## Authentification — connexion (US-1.2, #10)

`POST /auth/login` authentifie un compte par **identifiant + mot de passe** et émet, en cas de
succès, une **paire de jetons JWT** : un **jeton d'accès** court et un **refresh token** long.
`POST /auth/refresh` échange un refresh valide contre une **nouvelle** paire (rotation). Adapter
entrant : `adapters/inbound/auth.py` ; cas d'usage : `application/authentication.py` (architecture
hexagonale). Décisions actées par **[ADR-0013](../docs/adr/0013-connexion-jwt-refresh-anti-bruteforce.md)**
(PyJWT · HS256 · refresh rotaté · anti-bruteforce en mémoire).

- **`POST /auth/login`** — corps (JSON) : `identifier` (requis — **téléphone ou e-mail**,
  auto-détecté) et `password` (requis). Réponses :
  - **`200 OK`** : `{ access_token, refresh_token, token_type: "bearer", expires_in }`
    (`expires_in` = durée du **jeton d'accès** en secondes). Le `JWT_SECRET` n'apparaît **jamais**.
  - **`401 Unauthorized`** : identifiants invalides — **message générique unique**
    (« Identifiants invalides »), **identique** que le compte soit inconnu, le mot de passe faux ou
    le compte non `ACTIVE` (anti-énumération).
  - **`429 Too Many Requests`** : trop d'échecs (anti-bruteforce), avec l'en-tête **`Retry-After`**.
  - **`422 Unprocessable Entity`** : corps malformé (champ manquant/type invalide).
  - **`503 Service Unavailable`** : `JWT_SECRET` non configuré (émission de jetons impossible) —
    `GET /health` et l'inscription restent disponibles.
- **`POST /auth/refresh`** — corps (JSON) : `refresh_token` (requis). Réponses :
  - **`200 OK`** : nouvelle paire (même schéma que `login`).
  - **`401 Unauthorized`** : refresh invalide / expiré / altéré / de mauvais `type` — message générique.

**Jeton d'accès (contrat pour le RBAC #12)** : JWT **HS256** ; claims `sub` (id utilisateur), `role`,
`type=access`, `iat`, `exp`, `jti` — **aucune PII**. Schéma d'auth **Bearer**
(`Authorization: Bearer <access_token>`). #10 **émet** les jetons et fournit la capacité de décodage
(`TokenService.decode`) ; la **protection** des routes métier (deny-by-default, isolation par salon)
relève de #12.

**Sécurité & vie privée :**
- **Mot de passe** vérifié via argon2id (`PasswordHasher.verify`) ; le clair ne vit que le temps de la
  vérification — **jamais journalisé ni renvoyé**. Le **secret**, le **condensat** et les **jetons**
  ne sont **jamais** journalisés.
- **Anti-énumération** : `401` **générique et uniforme** ; quand aucun compte ne correspond, une
  vérification argon2 **factice** est exécutée pour atténuer l'oracle temporel.
- **Anti-bruteforce (§11.1)** : rate-limit sur les **échecs** (fenêtre glissante par **identifiant +
  IP**), verrou temporisé (`429` + `Retry-After`), **réinitialisé au succès**. Store **en mémoire**
  (non partagé entre instances ; adapter Redis différé, ADR-0013).
- **Refresh** : **rotaté** à chaque rafraîchissement, avec re-lecture du `role`/`status` courant
  (compte devenu non `ACTIVE` refusé). Pas de révocation serveur / `/auth/logout` en #10 (différé).
- **Normalisation de l'identifiant** : téléphone en **E.164** (comme à l'inscription) ; e-mail
  `strip`é (casse conservée, cohérente avec le stockage de #8). Transport **Bearer** supposant HTTPS.

## Authentification — réinitialisation du mot de passe par OTP (US-1.3, #11)

Parcours de **récupération de compte en deux étapes** : demander un code à usage unique (par SMS
**ou** e-mail selon l'identifiant), puis fixer un nouveau mot de passe qui **invalide l'ancien**.
Adapter entrant : `adapters/inbound/auth.py` ; cas d'usage : `application/password_reset.py`
(architecture hexagonale). Décisions actées par
**[ADR-0014](../docs/adr/0014-reinitialisation-mot-de-passe-otp.md)** (réutilisation du domaine OTP,
anti-énumération, dépôt OTP dédié, canal e-mail *stub*, pas de migration).

- **`POST /auth/password/reset/request`** — corps (JSON) : `identifier` (requis — **téléphone ou
  e-mail**, auto-détecté). Réponses :
  - **`202 Accepted`** (**toujours**, y compris identifiant inconnu) : message **générique**
    (`{ "detail": "Si un compte correspond à cet identifiant, un code de réinitialisation a été
    envoyé." }`). Ne confirme **jamais** l'existence d'un compte (anti-énumération).
  - **`429 Too Many Requests`** (+ en-tête **`Retry-After`**) : demande rate-limitée (anti-flood /
    « SMS bombing »), message générique.
  - **`422 Unprocessable Entity`** : corps structurellement invalide (champ manquant).
- **`POST /auth/password/reset/confirm`** — corps (JSON) : `identifier`, `code`, `new_password`
  (requis). Réponses :
  - **`200 OK`** : `{ "detail": "Mot de passe réinitialisé." }`. L'ancien mot de passe ne
    s'authentifie **plus** via `POST /auth/login` ; l'utilisateur se reconnecte avec le nouveau.
  - **`400 Bad Request`** — message **générique unique** (`{ "detail": "Code de réinitialisation
    invalide ou expiré." }`) pour **tout** échec d'OTP (invalide, expiré, trop d'essais, déjà
    consommé) **et** identifiant sans défi (cause exacte jamais divulguée).
  - **`422 Unprocessable Entity`** : le **nouveau mot de passe** viole la politique (longueur 8–128).

**Sécurité & vie privée :**
- **OTP à usage unique et expirant** : logique de domaine réutilisée (ADR-0012) — consommation +
  expiration + limite d'essais + comparaison **temps constant**. Le défi est **supprimé** après
  succès (usage unique doublement garanti) ; une nouvelle demande **écrase** le défi précédent.
- **Ancien mot de passe invalidé** : le condensat (`password_hash`) est **remplacé** ; l'ancien est
  refusé à la connexion. **Limite assumée (ADR-0013)** : les **jetons déjà émis** restent valides
  jusqu'à expiration (refresh stateless non révocable) — **pas** de déconnexion serveur immédiate.
- **Anti-énumération** : `202` uniforme à la demande, `400` générique unique à la confirmation ; un
  défi est **toujours** généré (atténuation d'oracle temporel). Comptes non `ACTIVE` traités comme
  inexistants.
- **Séparation des usages** : l'OTP de reset vit dans un **dépôt dédié** ; impossible de réutiliser
  un OTP d'inscription pour un reset (ou l'inverse).
- **OTP de reset bloquant et toujours actif** : **indépendant** d'`OTP_ENABLED` (qui ne gouverne que
  l'OTP optionnel d'inscription). Les endpoints **ne dépendent pas** de `JWT_SECRET` (**pas** de
  `503`).
- **Non-journalisation** : code OTP, mot de passe en clair, condensat, numéro et e-mail ne sont
  **jamais** journalisés ni renvoyés. L'envoi SMS/e-mail réel est **différé M5** (stub no-op).

## Configuration

La configuration est lue **depuis l'environnement** (jamais en dur). Voir `.env.example` ;
les **secrets réels** (DSN base/Redis, `JWT_SECRET`, etc.) sont injectés **hors dépôt** et ne doivent
**jamais** être committés. Modèle d'environnements, matrice de configuration et politique de secrets :
**[docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md)** (ADR-0011).

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `OTP_ENABLED` | `false` | Active l'OTP à l'inscription (#8). Envoi réel différé à M5 ; capacité testable même désactivée. |
| `OTP_CODE_LENGTH` | `6` | Longueur du code OTP (optionnel). |
| `OTP_TTL_SECONDS` | `300` | Durée de validité de l'OTP en secondes (optionnel). |
| `OTP_MAX_ATTEMPTS` | `3` | Nombre d'essais autorisés par OTP (optionnel). |
| `JWT_SECRET` | *(vide)* | **SECRET** — requis pour la connexion (#10) : signe les JWT (HS256). Absent → `/auth/login` et `/auth/refresh` répondent `503`. Vit hors dépôt (ADR-0011). |
| `JWT_ALGORITHM` | `HS256` | Algorithme de signature JWT (#10, ADR-0013). |
| `JWT_ACCESS_TTL_SECONDS` | `900` | Durée du jeton d'accès (court) en secondes. |
| `JWT_REFRESH_TTL_SECONDS` | `2592000` | Durée du refresh (long, rotaté) en secondes (30 j). |
| `LOGIN_MAX_ATTEMPTS` | `5` | Anti-bruteforce : nombre d'échecs avant verrou (#10). |
| `LOGIN_WINDOW_SECONDS` | `300` | Anti-bruteforce : fenêtre glissante des échecs, en secondes. |
| `LOGIN_LOCKOUT_SECONDS` | `900` | Anti-bruteforce : durée du verrou après seuil, en secondes. |
| `PASSWORD_RESET_OTP_TTL_SECONDS` | *(= `OTP_TTL_SECONDS`)* | Réinitialisation (#11, optionnel) : durée de validité de l'OTP de reset. Défaut = valeur OTP d'inscription. |
| `PASSWORD_RESET_OTP_MAX_ATTEMPTS` | *(= `OTP_MAX_ATTEMPTS`)* | Réinitialisation (#11, optionnel) : essais autorisés par OTP de reset. |
| `PASSWORD_RESET_MAX_ATTEMPTS` | *(= `LOGIN_MAX_ATTEMPTS`)* | Réinitialisation (#11, optionnel) : demandes avant verrou anti-flood. |
| `PASSWORD_RESET_WINDOW_SECONDS` | *(= `LOGIN_WINDOW_SECONDS`)* | Réinitialisation (#11, optionnel) : fenêtre glissante de l'anti-flood, en secondes. |
| `PASSWORD_RESET_LOCKOUT_SECONDS` | *(= `LOGIN_LOCKOUT_SECONDS`)* | Réinitialisation (#11, optionnel) : durée du verrou anti-flood, en secondes. |

> La réinitialisation par OTP (#11) **ne dépend pas** d'`OTP_ENABLED` (OTP de reset **toujours actif**)
> ni de `JWT_SECRET`. La longueur du code de reset réutilise `OTP_CODE_LENGTH`. Les variables
> `PASSWORD_RESET_*` sont **optionnelles** : absentes, elles retombent sur les valeurs OTP (#8) et
> login (#10).

## Modèle de données & migrations

Le schéma relationnel initial (issue #3) matérialise les **8 entités du PRD §9** plus une
table de jonction, avec leurs contraintes d'intégrité critiques. L'outillage est figé par
**[ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)** : **SQLAlchemy 2.0**
(ORM, style typé `Mapped[...]`) · **Alembic** (migrations versionnées) · **psycopg 3**
(driver) · **PostgreSQL 16**.

Conformément à l'hexagonal (ADR-0008), tables ORM, `metadata` et migrations sont un **détail
de persistance** et vivent dans `adapters/outbound/` ; seules les **énumérations métier** sont
des `enum.Enum` purs du `domain/`. Aucun import de SQLAlchemy depuis `domain/` ou
`application/`.

```
coiflink_api/
  domain/enums.py                          # enums purs (Role, AppointmentStatus, ...) — source des CHECK
  adapters/outbound/persistence/
    base.py                                 # DeclarativeBase + metadata + convention de nommage
    models.py                              # tables ORM (source de vérité du schéma)
    session.py                              # fabrique d'engine (lit DATABASE_URL ; non câblée à l'app en #3)
migrations/
  env.py                                    # importe la metadata ; lit DATABASE_URL (jamais de secret)
  versions/0001_schema_initial.py           # migration initiale up/down
alembic.ini                                 # config Alembic (DSN via env, aucun secret)
```

### Prérequis & connexion

- **PostgreSQL 16** accessible.
- `DATABASE_URL` défini dans l'environnement (cf. `.env.example`). Il pilote l'application
  **et** Alembic. La forme `postgresql://…` est automatiquement normalisée en
  `postgresql+psycopg://…` (driver psycopg 3) ; `alembic.ini` ne contient **aucun**
  identifiant.

### Commandes de migration

Exécutées depuis `backend/` (avec l'environnement virtuel activé et `DATABASE_URL` défini) :

| Commande | Effet |
| --- | --- |
| `alembic upgrade head` | Applique toutes les migrations (crée le schéma). |
| `alembic downgrade base` | Réverte tout (revient à un schéma vide). |
| `alembic current` | Affiche la révision appliquée. |
| `alembic history` | Liste l'historique des révisions. |
| `alembic check` | Vérifie que la `metadata` ORM correspond à la base (aucun diff attendu). |
| `alembic revision --autogenerate -m "…"` | Génère une nouvelle migration (à **relire** : les `CHECK`/`EXCLUDE` ne sont pas tous autogénérés). |

Le round-trip `upgrade head` → `downgrade base` → `upgrade head` est **réversible et
idempotent**.

### Diagramme relationnel (ERD)

```mermaid
erDiagram
    users ||--o{ salons : "owner_id"
    users ||--o{ appointments : "client_id"
    users |o--o{ appointments : "hairdresser_id"
    users |o--o{ customer_profiles : "user_id"
    users ||--o{ payments : "recorded_by"
    salons ||--o{ services : ""
    salons ||--o{ appointments : ""
    salons ||--o{ customer_profiles : ""
    salons ||--o{ payments : ""
    salons ||--o{ cash_journal : ""
    appointments ||--o{ appointment_services : ""
    services ||--o{ appointment_services : ""
    appointments |o--o{ payments : "appointment_id"
    services |o--o{ payments : "service_id"
    payments |o--o{ cash_journal : "transaction_id"
    users |o--o{ notifications : "user_id"
    salons |o--o{ notifications : "salon_id"
    appointments |o--o{ notifications : "appointment_id"
```

### Dictionnaire des tables

> Toutes les tables portent `id UUID PK DEFAULT gen_random_uuid()` et `created_at timestamptz`.
> Celles qui sont mutables portent aussi `updated_at timestamptz`. Montants en `NUMERIC(12,2)`
> (devise XOF). Suppression par défaut `ON DELETE RESTRICT`.

| Table | Colonnes notables | Contraintes & index clés |
| --- | --- | --- |
| **`users`** | `full_name`, `phone`, `email?`, `password_hash`, `role`, `status` | `uq_users_phone` ; `uq_users_email` (unique partiel `WHERE email IS NOT NULL`) ; CHECK `role`/`status` |
| **`salons`** | `owner_id→users`, `name`, `description`, `phone`, `address`, `city`, `commune`, `latitude`, `longitude`, `logo_url`, `status`, `opening_hours JSONB` | FK `owner_id` ; CHECK `status` ; index `(city, commune)`, `status` |
| **`services`** | `salon_id→salons`, `name`, `price`, `duration_minutes`, `category`, `is_active` | FK `salon_id` ; `uq_services_salon_id (salon_id, id)` ; CHECK `price >= 0`, `duration_minutes > 0` ; index `salon_id` |
| **`appointments`** | `salon_id→salons`, `client_id→users`, `hairdresser_id?→users`, `appointment_date`, `start_time`, `end_time`, `status`, `cancellation_reason?`, `client_note?`, `slot` (généré) | FK `salon_id`/`client_id` NOT NULL (§8.1) ; `uq_appointments_salon_id (salon_id, id)` ; CHECK `end_time > start_time`, `status` ; **EXCLUDE** anti double-booking ; index `(salon_id, appointment_date)`, `client_id` |
| **`appointment_services`** *(jonction)* | `appointment_id→appointments`, `service_id→services`, `salon_id`, `price_at_booking` | PK `(appointment_id, service_id)` ; **FK composites** `(salon_id, appointment_id)` et `(salon_id, service_id)` (cohérence salon) ; `ON DELETE CASCADE` depuis le RDV ; CHECK `price >= 0` |
| **`customer_profiles`** | `salon_id→salons`, `user_id?→users`, `full_name`, `phone?`, `notes?`, `last_visit_at?`, `total_visits` | FK `salon_id`/`user_id` ; `uq_customer_profiles_salon_user (salon_id, user_id) WHERE user_id IS NOT NULL` ; CHECK `total_visits >= 0` ; index `salon_id` |
| **`payments`** | `salon_id→salons`, `appointment_id?`, `service_id?`, `client_id?→users`, `amount`, `currency`, `payment_method`, `status`, `recorded_by→users`, `reference?` | FK `salon_id`/`recorded_by` NOT NULL (§8.2) ; FK composites vers RDV/prestation ; **CHECK `appointment_id IS NOT NULL OR service_id IS NOT NULL`** (§8.2) ; CHECK `amount >= 0`, `payment_method`, `status` ; index `(salon_id, created_at)`, `appointment_id` |
| **`cash_journal`** *(append-only)* | `salon_id→salons`, `transaction_id?→payments`, `operation_type`, `amount`, `performed_by→users`, `description?` | FK `salon_id`/`performed_by` NOT NULL ; `created_at` horodaté (§8.2) ; CHECK `operation_type` ; index `(salon_id, created_at)` |
| **`notifications`** | `user_id?→users`, `salon_id?→salons`, `appointment_id?→appointments`, `type`, `channel`, `title`, `message`, `status`, `sent_at?` | CHECK `type`/`channel`/`status` ; index `user_id`, `(salon_id, created_at)` |

### Contraintes clés métier

- **RDV → salon + ≥ 1 prestation (§8.1)** : `salon_id` NOT NULL ; la cardinalité « ≥ 1 »
  passe par la jonction `appointment_services`, garantie par insertion transactionnelle côté
  application (M3). Les **FK composites** `(salon_id, …)` interdisent de mêler des entités de
  salons différents (isolation §11.2).
- **Paiement → prestation ou RDV (§8.2)** : `CHECK (appointment_id IS NOT NULL OR service_id IS
  NOT NULL)`.
- **Anti double-réservation (§8.1)** : colonne générée `slot tsrange` (Abidjan = UTC+0) +
  `EXCLUDE USING gist (hairdresser_id WITH =, slot WITH &&)` restreinte aux RDV actifs
  (`PENDING`/`CONFIRMED`) assignés — requiert l'extension `btree_gist`.
- **Journal de caisse (§8.2)** : horodaté et conçu **append-only** (pas de `DELETE`/`UPDATE` ;
  correction = nouvelle ligne `ADJUSTMENT`/`REFUND`).
- **Pas de hard-delete d'un paiement validé (§8.2)** : `ON DELETE RESTRICT` + statut
  `CANCELLED`/`ADJUSTED`.

### Sécurité & données personnelles

`DATABASE_URL` et tout identifiant sont lus **depuis l'environnement** ; aucune valeur réelle
n'est committée (seul `.env.example`). Les colonnes PII (`users`, `customer_profiles`) et le
`password_hash` (jamais de mot de passe en clair) ne doivent **jamais** être journalisés —
les logs Alembic ne dumpent pas de données.

### Tests

Les invariants de schéma (sans base) et le round-trip de migration (PostgreSQL requis,
**skip si aucun `DATABASE_URL`**) sont couverts par la suite de tests. Issue #5 ajoute
`test_session.py` (fail-fast sur `DATABASE_URL`, normalisation du DSN — aucune infra requise)
et `test_secrets_policy.py` (vérifications statiques sur `.gitignore`, `.env.example`,
`docker-compose.yml`, configs Railway et Dockerfiles). La CI (#4) et les environnements &
secrets (#5) sont désormais en place.

Issue #8 complète la suite avec des **tests unitaires** (logique de domaine : téléphone,
mot de passe, OTP, hacheur argon2id), des **tests API** (`TestClient`, sans base réelle :
`201`, `409` doublon, `422` validation, non-fuite du mot de passe/OTP dans la réponse) et un
test de configuration. Les tests d'**intégration Postgres** (persistance réelle +
contrainte `uq_users_phone`) sont inclus et **skippés proprement si `DATABASE_URL` est absent**.

Issue #9 ajoute trois suites dédiées à l'inscription gérant :

- `test_manager_registration_usecase.py` — rôle `MANAGER` attribué côté serveur, statut
  `ACTIVE`, normalisation E.164, mot de passe jamais persisté en clair, doublon (pré-check +
  fallback `IntegrityError`), validations domaine, OTP off/on, rôle inconnu → `ValueError`,
  non-régression #8 (`RegisterClient` reste `CLIENT`).
- `test_manager_auth_api.py` — `201` + `role=="MANAGER"`, non-fuite du secret, `409` doublon
  (format local et E.164, détail sans le numéro), `422` validation et bornes, anti-escalade
  (champ `role` dans le corps ignoré), `405` sur `GET`.
- `test_manager_registration_integration.py` (PostgreSQL, **skip propre sans `DATABASE_URL`**) —
  persistance `role=MANAGER`/`status=ACTIVE`, `password_hash` ≠ clair dans la table,
  contrainte `uq_users_phone` (dont doublon cross-rôle `CLIENT→MANAGER`), fallback
  `IntegrityError` concurrente → `PhoneAlreadyInUse`.

Issue #10 ajoute six suites dédiées à la connexion JWT et à l'anti-bruteforce :

- `test_identifier.py` — classement de l'identifiant : `@` → e-mail (normalisé) ; sinon téléphone
  normalisé en E.164 (`0700…` et `+2250700…` → même clé) ; rejet des entrées vides/malformées.
- `test_jwt_token_service.py` — `JwtTokenService` : `issue_pair` produit access + refresh avec
  claims corrects (`sub`, `role`, `type`, `jti`, `exp` cohérent avec le TTL) ; `decode` accepte un
  jeton valide et rejette signature invalide / jeton expiré (horloge injectée) / `alg` inattendu /
  mauvais `type` pour `verify_refresh`. Non-émission d'un jeton si `JWT_SECRET` vide.
- `test_login_rate_limiter.py` — `InMemoryLoginRateLimiter` (horloge injectée) : sous le seuil →
  passe ; au seuil → `TooManyLoginAttempts` ; expiration de la fenêtre → de nouveau autorisé ;
  `reset` au succès ré-autorise immédiatement.
- `test_authentication_usecase.py` — `AuthenticateUser` et `RefreshTokens` (ports 100 % fakes) :
  succès par téléphone et par e-mail → `TokenPair` + compteur reset ; mauvais mot de passe →
  `InvalidCredentials` + `record_failure` ; utilisateur introuvable → `InvalidCredentials` +
  vérification **factice** appelée (anti-oracle temporel) ; compte non `ACTIVE` → `InvalidCredentials` ;
  verrou actif → `TooManyLoginAttempts` avant tout accès base. `RefreshTokens` : refresh valide →
  nouvelle paire (rotation) ; refresh expiré/altéré/`type=access` → `InvalidToken`/`ExpiredToken` ;
  compte devenu non `ACTIVE` → refus.
- `test_login_api.py` — adapter entrant (FastAPI `TestClient`, ports fakes, sans base) :
  `POST /auth/login` → `200` + structure `{access_token, refresh_token, token_type, expires_in}` ;
  `401` **générique et indistinguable** (inconnu vs mot de passe faux vs compte inactif) ; `429` +
  `Retry-After` ; `422` champ manquant/vide ; `503` sans `TokenService` câblé ; non-fuite du mot de
  passe dans les réponses. `POST /auth/refresh` → `200` + structure ; `401` sur refresh invalide ou
  expiré ; `422` champ manquant ; `405` sur mauvaise méthode.
- `test_login_e2e.py` — deux groupes : (a) **`TestLoginFullStackE2E`** (PostgreSQL requis, **skip
  propre sans `DATABASE_URL`**) : pile complète sans mock (HTTP → cas d'usage → SQL + argon2 + JWT
  réel) — inscription→login par téléphone et par e-mail, vérification des claims du JWT d'accès
  (`sub=user_id`, `role`, `type=access`, **absence de PII**), rotation du refresh, accumulation du
  rate-limiter jusqu'au `429` + `Retry-After`, reset du compteur après succès ; (b)
  **`TestRateLimitAccumulationE2E`** (sans base) : N requêtes HTTP consécutives avec
  `InMemoryLoginRateLimiter` réel capturé en closure — déclenchement du `429` au seuil, présence et
  valeur positive de `Retry-After`, message `429` sans l'identifiant ciblé.

Issue #11 ajoute trois suites dédiées à la réinitialisation par OTP :

- `test_password_reset_usecase.py` — `RequestPasswordReset` et `ConfirmPasswordReset` (ports
  100 % fakes) : succès par téléphone et par e-mail — OTP stocké + envoyé, canal SMS/EMAIL correct ;
  anti-énumération (compte inconnu/inactif/suspendu, identifiant vide/invalide → silencieux, aucun
  envoi) ; rate-limit déclenché avant tout accès base (`TooManyLoginAttempts`, `retry_after`
  propagé) ; `record_failure` systématique (succès **et** échecs, mais pas si verrou) ; confirmation
  — `update_password` appelé + condensat remplacé + ancien mot de passe invalidé + défi supprimé ;
  OTP invalide/expiré/épuisé/déjà consommé/absent → `InvalidOtp` ; mot de passe trop court
  (`InvalidPassword`) vérifié **avant** l'OTP ; indistinguabilité (même `InvalidOtp` pour toutes les
  causes d'échec, code jamais dans le message).
- `test_password_reset_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) :
  `POST /auth/password/reset/request` → `202` générique pour compte actif **et** inconnu (même
  corps, OTP absent de la réponse) ; `429` + `Retry-After` (message générique) ; `422` sur champs
  manquants/vides ; `405` sur mauvaise méthode. `POST /auth/password/reset/confirm` → `200` +
  message générique (`Mot de passe réinitialisé.`) ; `400` **unique** pour OTP faux / absent /
  expiré (indistinguabilité, code OTP jamais dans la réponse) ; `422` sur mot de passe trop court
  (distinct du `400` OTP) ; `422` sur champs manquants ; `405` sur mauvaise méthode.
- `test_password_reset_e2e.py` — trois groupes : (a) **`TestPasswordResetOtpFlowE2E`** (sans
  base) : deux appels HTTP consécutifs partagent un `InMemoryOtpRepository` réel — le code émis par
  `/request` est relu et accepté par `/confirm` (`200`), condensat mis à jour, ancien mot de passe
  invalidé dans le dépôt, OTP à usage unique (second `/confirm` → `400` générique), deuxième
  demande écrase le premier défi ; (b) **`TestPasswordResetRateLimitE2E`** (sans base) : N appels
  HTTP accumulent l'état d'un `InMemoryLoginRateLimiter` dédié réel — `429` au seuil + `Retry-After`
  positif, message générique sans l'identifiant ciblé ; (c) **`TestPasswordResetFullStackE2E`**
  (PostgreSQL requis, **skip propre sans `DATABASE_URL`**) : pile complète sans mock applicatif (SQL
  + argon2 + `InMemoryOtpRepository`) — inscription → reset OTP → connexion (`POST /auth/login`) :
  ancien mot de passe → `401`, nouveau → `200` + paire JWT ; OTP à usage unique sur pile réelle.
