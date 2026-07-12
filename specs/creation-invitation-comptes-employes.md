# Création / invitation de comptes employés (coiffeurs) — US-1.4 (issue #13)

## Problem Statement

Aujourd'hui, le backend CoifLink sait **inscrire un client** (`POST /auth/register`, #8) et un
**gérant** (`POST /auth/register/manager`, #9), **authentifier** tout le monde (JWT + refresh, #10),
**réinitialiser un mot de passe par OTP** (#11) et **autoriser** les requêtes par un RBAC
deny-by-default avec isolation par salon (#12, ADR-0015). Mais **il n'existe aucun moyen pour un
gérant de créer le compte d'un employé (coiffeur)** ni de le rattacher à son salon.

Conséquences concrètes du manque :

- Un salon structuré (« M. Kouadio a 5 coiffeurs », PRD §2 / §21.1) ne peut pas donner d'accès à ses
  employés : le rôle `HAIRDRESSER` existe dans le domaine (`domain/enums.py`) et dans la matrice de
  permissions (`domain/permissions.py`), mais **aucun compte ne peut recevoir ce rôle** — l'inscription
  fixe le rôle à `CLIENT` ou `MANAGER` côté serveur, jamais `HAIRDRESSER`.
- La **portée (scope) d'un coiffeur est aujourd'hui un palliatif documenté** : le schéma **n'a pas**
  de table d'appartenance employé↔salon, donc `SqlSalonScopeRepository` dérive la portée d'un
  `HAIRDRESSER` des **rendez-vous qui lui sont assignés**. Un coiffeur **sans aucun RDV** a donc une
  portée **vide** et « ne voit rien » — sûr, mais insuffisant pour un employé fraîchement créé
  (ADR-0015, section *Conséquences* ; docstrings de `salon_scope_repository.py` et du port
  `SalonScopeRepository`). Ce suivi est **explicitement rattaché à #13** dans `docs/adr/README.md`.

US-1.4 (PRD §6, tableau US-1.4 ; BACKLOG #13) demande donc : *« En tant que gérant, je veux inviter
ou créer des employés afin de leur donner accès au salon »*, avec pour **critère d'acceptation** :
**un gérant crée un compte coiffeur ; le coiffeur se connecte avec un périmètre restreint.**

## Goals

1. **Créer** le modèle d'appartenance **employé↔salon** manquant (table `salon_members` + migration
   Alembic + modèle ORM), source d'autorité de la portée d'un employé.
2. Exposer un **endpoint protégé** permettant à un **gérant** de créer un compte **coiffeur**
   rattaché à **son** salon : `POST /salons/{salon_id}/employees`, gardé par la permission
   `EMPLOYEE_MANAGE` (matrice §4.1, déjà attribuée au `MANAGER`) **et** par la portée salon
   (`require_salon_scope`, isolation §11.2).
3. Attribuer le rôle `HAIRDRESSER` **côté serveur** (jamais lu depuis la requête) — garde-fou
   anti-élévation de privilège, cohérent avec l'inscription client/gérant (#8/#9, PRD §11.1).
4. Permettre au coiffeur créé de **se connecter** via le flux existant `POST /auth/login` (#10) et
   d'obtenir un **périmètre restreint** : sa portée salon provient désormais de `salon_members`
   (non plus des seuls RDV assignés) — il « voit » son salon dès sa création, mais **rien** hors de
   ce salon.
5. **Mettre à jour la lecture de portée** (`SqlSalonScopeRepository` pour `HAIRDRESSER`) pour lire la
   table d'appartenance — **sans** changer le port `SalonScopeRepository` ni aucune garde
   d'autorisation (invariant posé par ADR-0015 : « seule la requête change »).
6. Refuser proprement les cas d'erreur (doublon de téléphone/e-mail → `409`, hors périmètre → `403`,
   permission absente → `403`) avec des **messages génériques** conformes à l'existant.
7. Documenter la décision (ADR-0016) et clore le suivi #13 dans `docs/adr/README.md`, les docstrings
   du scope repository et du port.

## Non-Goals

- **Interface web** de gestion des employés (dashboard Next.js) : le squelette du dashboard est #14,
  et la gestion visuelle des employés relèvera d'une issue UX ultérieure. #13 livre l'**API backend**.
- **Application mobile coiffeur** : hors MVP (PRD §21.3 « application coiffeur dédiée » = V2+).
- **Gestion complète du cycle de vie employé** (lister / modifier / désactiver / retirer un employé,
  réaffecter, historiser) : `EMPLOYEE_MANAGE` couvre à terme tout cela, mais l'AC de #13 se limite à
  la **création** + **connexion**. Une route de **liste** (`GET /salons/{salon_id}/employees`) est
  proposée comme extension raisonnable et faible risque ; **modification/désactivation** sont hors
  scope (voir *Risks and Open Questions*).
- **Flux d'invitation par lien magique / e-mail** (« invitation » du titre) au sens complet
  (jeton à usage unique envoyé par e-mail, employé qui choisit son mot de passe) : le canal e-mail
  réel est **différé M5** (ADR-0006/0014) et l'infra SMS est un **stub**. Voir la décision proposée
  (création directe avec mot de passe initial) et les alternatives en *Open Questions*.
- **Rôles employés multiples** (réceptionniste, assistant…) : le seul rôle employé du MVP est
  `HAIRDRESSER` (PRD §4 / §9.1). Aucun nouvel `enum` de rôle.
- **Journalisation d'audit persistée** des accès sensibles (PRD §11.4 « Création employé ») :
  l'infra d'audit est **rattachée à #52** (ADR-0015). #13 émet au plus un log non-PII ; pas de
  table d'audit.
- **Invalidation des jetons** existants / rotation de secret : inchangé par cette issue.

## Relevant Repository Context

**Stack (figée par ADR — ne pas ré-arbitrer)** : backend **Python ≥ 3.12 / FastAPI** (ADR-0003),
**architecture hexagonale** (ADR-0008), **SQLAlchemy 2.0 + Alembic + psycopg 3**, **PostgreSQL 16**
(ADR-0009), hachage **argon2id** (ADR-0012), **JWT HS256 + refresh** (ADR-0013), **RBAC
deny-by-default** (ADR-0015). Tests : `pytest` (paquet `backend/`).

**Découpage hexagonal du paquet `backend/coiflink_api/`** (à respecter strictement — `domain/` et
`application/` n'importent **jamais** FastAPI ni SQLAlchemy) :

- `domain/` — entités et règles pures :
  - `enums.py` : `Role` (`CLIENT`, `HAIRDRESSER`, `MANAGER`, `ADMIN`), `UserStatus`
    (`ACTIVE`/`INACTIVE`/`SUSPENDED`), helper `values()` qui **dérive les `CHECK` SQL du domaine**.
  - `user.py` : `UserToCreate` (porte le condensat, jamais le clair), `User` (entité publique sans
    secret), `validate_name`.
  - `permissions.py` : matrice §4.1 **fermée**. Le `MANAGER` possède déjà **`EMPLOYEE_MANAGE`** ;
    l'`ADMIN` ne l'a **pas**. **Aucun changement de matrice n'est nécessaire.**
  - `access.py` : `SalonScope`, `can_access_salon`, `can_access_appointment` (isolation §11.2).
  - `principal.py`, `errors.py`, `password.py`, `phone.py`, `credentials.py`.
- `application/` :
  - `registration.py` : `RegisterUser` (cas d'usage **générique paramétré par le rôle**, rôle injecté
    au câblage, jamais lu de la requête) et `RegisterClient`. **Patron directement réutilisable.**
  - `authorization.py` : `AccessPolicy` (`require_roles`, `require_permission`, `require_salon`,
    `scope_of`).
  - `ports/` : `user_repository.py`, `password_hasher.py`, `salon_scope_repository.py`, etc.
    (interfaces `Protocol`).
- `adapters/inbound/` :
  - `auth.py` : router `/auth` (register, login, refresh, reset, `GET /auth/me`). Montre le patron
    « traduire HTTP↔domaine, rôle fixé côté serveur, réponses sans secret ».
  - `security.py` : le « middleware » RBAC en dépendances FastAPI — `require_authenticated` (globale),
    `get_current_principal` (rôle/statut **relus en base**), fabriques `require_roles` /
    `require_permission(...)` / `require_salon_scope`, liste blanche `PUBLIC_ROUTE_PATHS`, invariant
    deny-by-default **testé** (`unprotected_routes`). **Toute nouvelle route protégée s'appuie sur ces
    gardes** ; le mode d'emploi est en tête de fichier (route sous `/salons/{salon_id}/…`).
- `adapters/outbound/persistence/` :
  - `models.py` : **source de vérité du schéma** (ORM). `Salon.owner_id` → `users.id` ; conventions :
    PK `UUID gen_random_uuid()`, `created_at`/`updated_at timestamptz now()`, énumérations en `text`
    + `CHECK` dérivé du domaine (`enum_check`), FK `ON DELETE RESTRICT`, unicité composite
    `(salon_id, id)` pour les FK composites d'isolation.
  - `user_repository.py` : `SqlUserRepository` (create avec retraduction `IntegrityError` →
    `PhoneAlreadyInUse`/`EmailAlreadyInUse` ; `flush` sans commit, commit piloté par `get_session`).
  - `salon_scope_repository.py` : `SqlSalonScopeRepository` — **le point unique** à faire évoluer
    pour la portée `HAIRDRESSER` (voir docstring qui référence déjà #13).
  - `session.py` : `get_session` (ouvre/commit/rollback la session par requête).
- `main.py` : composition root — `FastAPI(dependencies=[Depends(require_authenticated)])`,
  `include_router`.

**Migrations** : une seule révision `0001_schema_initial.py` (`revision="0001"`,
`down_revision=None`) → la table `salons` **existe déjà** (avec `owner_id`). La nouvelle migration
sera **`0002`**, `down_revision="0001"`. #12 n'a ajouté **aucune** migration.

**État de la dépendance #12** : livré (RBAC en place). **Décisions déjà tranchées, à ne pas rouvrir** :
rôle relu en base, deny-by-default, `403` uniforme sur l'accès inter-salons (aucun oracle
d'existence), messages `401`/`403` **constants**, aucun secret/PII journalisé.

**ADR à venir** : le prochain numéro libre est **ADR-0016** (dernier accepté : 0015).

## Proposed Implementation

Approche recommandée : **création directe** d'un compte coiffeur par le gérant, avec **mot de passe
initial** fourni dans la requête (défini par le gérant, communiqué hors bande / à changer au premier
usage via le reset OTP #11). C'est le chemin qui **satisfait l'AC** (« crée un compte coiffeur ; le
coiffeur se connecte ») sans dépendre d'un canal e-mail/SMS réel (différé M5). Le volet
« invitation » (lien/jeton) est documenté comme évolution (voir *Open Questions*).

### 1. Domaine (`domain/`)

- **`domain/enums.py`** — aucun nouvel enum requis (`Role.HAIRDRESSER`, `UserStatus` existent). Si le
  statut d'appartenance justifie sa propre énumération, réutiliser `UserStatus` (évite la
  prolifération). *(Décision par défaut : réutiliser `UserStatus`.)*
- **`domain/user.py`** — `UserToCreate` accepte déjà `role` : réutilisable tel quel avec
  `role=Role.HAIRDRESSER.value`.
- **(Optionnel) `domain/membership.py`** — petite dataclass `SalonMembershipToCreate(salon_id,
  user_id, role, status)` si l'on veut garder le use case purement domaine-orienté. Rester minimal.

### 2. Ports (`application/ports/`)

- **Nouveau port `salon_member_repository.py`** (`Protocol`), p. ex. :
  - `add_member(salon_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None` — insère l'appartenance
    (statut `ACTIVE`), retraduit une violation d'unicité `(salon_id, user_id)` en erreur de domaine
    (`EmployeeAlreadyInSalon`, nouvelle erreur).
  - `salon_ids_for_member(user_id: uuid.UUID) -> frozenset[uuid.UUID]` — salons **actifs** dont
    l'utilisateur est membre (utilisé par la lecture de portée). *(Peut aussi vivre comme méthode
    additionnelle du scope repository ; garder la responsabilité « lire la portée » côté
    `SalonScopeRepository`.)*

### 3. Cas d'usage (`application/`)

- **Nouveau `application/employees.py` → `CreateEmployee`** (ne connaît ni HTTP ni SQL) :
  - Dépendances (ports) : `UserRepository`, `PasswordHasher`, `SalonMemberRepository`.
  - `execute(command: CreateEmployeeCommand) -> User` où `CreateEmployeeCommand(salon_id, full_name,
    phone, password, email=None)`.
  - Séquence : `validate_name` → `validate_password` → `normalize_phone` → pré-check doublon
    (`phone_exists`) → `hash` → `create` user avec **`role=HAIRDRESSER`, `status=ACTIVE`** →
    `add_member(salon_id, user.id, HAIRDRESSER)` → retourner l'entité `User` (sans secret).
  - **Atomicité** : les deux écritures (user + membership) passent par la **même `Session`** ; elles
    sont `flush`ées puis **committées ensemble** par `get_session`. Si `add_member` lève, la requête
    est rollbackée → **pas de compte orphelin** sans salon.
  - Le rôle `HAIRDRESSER` est **fixé dans le use case / au câblage**, jamais lu du `command`
    (anti-élévation de privilège, comme `RegisterUser`).
  - Le mot de passe en clair n'est **ni journalisé ni conservé** au-delà du `hash`.
  - *Réutilisation possible* : `CreateEmployee` peut envelopper `RegisterUser(role=HAIRDRESSER)` puis
    ajouter l'appartenance ; privilégier un use case dédié pour porter l'atomicité et le `salon_id`.

### 4. Adapters sortants (`adapters/outbound/persistence/`)

- **`models.py` — nouvelle table `salon_members`** (nom au choix : `salon_members` recommandé) :
  - `id UUID` PK (`gen_random_uuid()`).
  - `salon_id UUID` NOT NULL — FK `salons.id` `ON DELETE RESTRICT`.
  - `user_id UUID` NOT NULL — FK `users.id` `ON DELETE RESTRICT`.
  - `role text` NOT NULL — `CHECK` **dérivé de `Role`** via `enum_check(...)` (valeur `HAIRDRESSER`
    pour le MVP ; contrainte laisse la porte ouverte à d'autres rôles employés sans `ALTER`).
  - `status text` NOT NULL default `'ACTIVE'` — `CHECK` dérivé de `UserStatus`.
  - `created_at` / `updated_at timestamptz` default `now()`.
  - `UniqueConstraint("salon_id", "user_id", name="uq_salon_members_salon_user")` (un utilisateur
    n'est employé qu'une fois par salon).
  - `UniqueConstraint("salon_id", "id", name="uq_salon_members_salon_id")` (cible de futures FK
    composites d'isolation, cohérent avec la convention `models.py`).
  - `Index("ix_salon_members_user_id", "user_id")` (lecture de portée par utilisateur) et
    `Index("ix_salon_members_salon_id", "salon_id")` (liste des employés d'un salon).
- **`salon_scope_repository.py` — mise à jour de la branche `HAIRDRESSER`** : lire les `salon_id`
  depuis `salon_members WHERE user_id = principal AND status = 'ACTIVE'` (au lieu du `DISTINCT` sur
  `appointments.hairdresser_id`). Le port `SalonScopeRepository` **ne change pas**. Mettre à jour la
  docstring (retirer « la table arrive avec #13 » → « lue depuis `salon_members` »).
  - *Décision à confirmer* : conserver ou non l'**union** avec les RDV assignés (rétro-compat). Par
    défaut : **remplacer** (l'appartenance devient l'autorité ; l'assignation d'un RDV reste gérée
    séparément par `can_access_appointment`, inchangé).
- **`salon_member_repository.py` — `SqlSalonMemberRepository`** : implémente le nouveau port
  (`add_member` avec `flush` + retraduction `IntegrityError` → `EmployeeAlreadyInSalon` sur
  `uq_salon_members_salon_user`).

### 5. Migration Alembic (`migrations/versions/0002_salon_members.py`)

- `revision="0002"`, `down_revision="0001"`.
- `upgrade()` : `CREATE TABLE salon_members` reflétant **exactement** le modèle ORM (mêmes noms de
  contraintes/index). Générer les `CHECK` avec la même liste de valeurs que le domaine.
- `downgrade()` : `DROP TABLE salon_members`.
- Vérifier le **round-trip Alembic** en CI (`backend` job — cf. README §Build & test).

### 6. Adapter entrant (`adapters/inbound/`)

- **Nouveau router `employees.py`** (préfixe `/salons`, tag `employees`) — ou section dédiée ; monté
  dans `main.py` via `include_router`. **Ne pas** ajouter le chemin à `PUBLIC_ROUTE_PATHS` (route
  **protégée**).
- **`POST /salons/{salon_id}/employees`** :
  - Gardes (dépendances) : `require_permission(Permission.EMPLOYEE_MANAGE)` **et**
    `require_salon_scope` (lit `salon_id` du chemin ; charge la portée du gérant, refuse `403` si le
    salon n'est pas le sien — aucun oracle d'existence). *(Composer les deux : `require_salon_scope`
    fournit déjà le `Principal` via son arbre ; `require_permission` fournit le contrôle §4.1.)*
  - Corps `CreateEmployeeRequest` (Pydantic) : `full_name`, `phone`, `password`
    (`min_length=MIN_LENGTH`), `email: EmailStr | None`. **Aucun champ `role`** (fixé côté serveur).
  - Assemble `CreateEmployee` (câblage `role=HAIRDRESSER`) via DI (à l'image de
    `get_register_manager`).
  - Traduction des erreurs de domaine → HTTP, **identique à l'existant** :
    `PhoneAlreadyInUse`/`EmailAlreadyInUse`/`EmployeeAlreadyInSalon` → **409** ;
    `InvalidPhone`/`InvalidPassword`/`InvalidName`/`InvalidEmail` → **422**.
  - Réponse **201** `UserResponse` (réutiliser le schéma existant) — **jamais** de secret.
- **(Optionnel, extension) `GET /salons/{salon_id}/employees`** : liste les coiffeurs du salon
  (gardée par `require_salon_scope` + une permission de lecture) — utile au dashboard #14. À trancher.
- **Connexion du coiffeur** : **aucun changement** — `POST /auth/login` (#10) authentifie tout
  compte `ACTIVE` par téléphone/e-mail + mot de passe.

### 7. Composition root (`main.py`)

- `app.include_router(employees_router)`. Aucun secret nouveau. Le use case est assemblé par DI dans
  l'adapter (mêmes patrons que `auth.py`).

## Affected Files / Packages / Modules

**À créer :**
- `backend/coiflink_api/application/employees.py` (`CreateEmployee`, `CreateEmployeeCommand`).
- `backend/coiflink_api/application/ports/salon_member_repository.py` (port `Protocol`).
- `backend/coiflink_api/adapters/outbound/persistence/salon_member_repository.py`
  (`SqlSalonMemberRepository`).
- `backend/coiflink_api/adapters/inbound/employees.py` (router `/salons/{salon_id}/employees`).
- `backend/migrations/versions/0002_salon_members.py`.
- `docs/adr/0016-comptes-employes-appartenance-salon.md`.
- `backend/tests/test_create_employee_usecase.py`, `.../test_employees_api.py`,
  `.../test_employees_e2e.py` (+ compléments scope).

**À modifier :**
- `backend/coiflink_api/adapters/outbound/persistence/models.py` (table `salon_members`).
- `backend/coiflink_api/adapters/outbound/persistence/salon_scope_repository.py` (branche
  `HAIRDRESSER` → `salon_members` ; docstring).
- `backend/coiflink_api/application/ports/salon_scope_repository.py` (docstring : retirer « arrive
  avec #13 »).
- `backend/coiflink_api/domain/errors.py` (nouvelle erreur `EmployeeAlreadyInSalon`).
- `backend/coiflink_api/main.py` (`include_router`).
- `backend/README.md` (nouvel endpoint + tableau des routes).
- `README.md` (module 1 — mention de la création d'employés).
- `docs/adr/README.md` (clore le suivi #13 « table d'appartenance employé↔salon »).
- Éventuellement `backend/coiflink_api/domain/user.py` / un nouveau `domain/membership.py`.

**À lire (référence de patrons) :** `adapters/inbound/auth.py`, `adapters/inbound/security.py`,
`application/registration.py`, `tests/test_manager_registration_integration.py`,
`tests/test_rbac_e2e.py`, `tests/test_domain_access.py`, `tests/test_authorization_policy.py`.

## API / Interface Changes

**Nouvel endpoint (protégé — RBAC #12) :**

- `POST /salons/{salon_id}/employees` → **201 Created**
  - **Auth** : `Authorization: Bearer <access_token>` d'un compte **`MANAGER` actif** propriétaire du
    `salon_id`.
  - **Gardes** : `EMPLOYEE_MANAGE` (§4.1) + portée salon (§11.2).
  - **Body** (`application/json`) : `{ "full_name": str, "phone": str, "password": str, "email":
    str|null }` — **pas** de champ `role`.
  - **Réponses** : `201` `UserResponse` (`id, full_name, phone, email, role="HAIRDRESSER", status,
    created_at`, **sans secret**) ; `401` (non authentifié) ; `403` (pas `MANAGER` / hors périmètre —
    message **générique** identique) ; `409` (téléphone ou e-mail déjà pris, ou employé déjà membre) ;
    `422` (nom/téléphone/mot de passe/e-mail invalides) ; `503` (`JWT_SECRET` non configuré).
- **(Optionnel) `GET /salons/{salon_id}/employees`** → `200` liste `UserResponse` (à confirmer).

**Endpoints inchangés** : `POST /auth/login` sert la connexion du coiffeur (aucune modification).

Toutes les routes sont **documentées automatiquement dans OpenAPI** (`/docs`, ADR-0003).
`PUBLIC_ROUTE_PATHS` **n'est pas** modifié (les nouvelles routes restent protégées — invariant
deny-by-default vérifié par test).

## Data Model / Protocol Changes

**Nouvelle table `salon_members`** (migration `0002`, `down_revision="0001"`) :

| Colonne | Type | Contraintes |
| --- | --- | --- |
| `id` | `uuid` | PK, `gen_random_uuid()` |
| `salon_id` | `uuid` | NOT NULL, FK `salons.id` `ON DELETE RESTRICT` |
| `user_id` | `uuid` | NOT NULL, FK `users.id` `ON DELETE RESTRICT` |
| `role` | `text` | NOT NULL, `CHECK` dérivé de `Role` (MVP : `HAIRDRESSER`) |
| `status` | `text` | NOT NULL default `'ACTIVE'`, `CHECK` dérivé de `UserStatus` |
| `created_at` | `timestamptz` | NOT NULL default `now()` |
| `updated_at` | `timestamptz` | NOT NULL default `now()` |

Contraintes : `uq_salon_members_salon_user (salon_id, user_id)`, `uq_salon_members_salon_id
(salon_id, id)` ; index `ix_salon_members_user_id`, `ix_salon_members_salon_id`. Les `CHECK` sont
**générés depuis le domaine** (`enum_check` / `enums.values`) — pas de valeurs SQL en dur divergentes.

**Changement de comportement de lecture (pas de changement de contrat)** : la portée d'un
`HAIRDRESSER` (`SqlSalonScopeRepository.salon_ids_for`) est désormais lue depuis `salon_members`
(statut `ACTIVE`) au lieu des RDV assignés. Le port `SalonScopeRepository` et toutes les gardes
restent **identiques**.

Aucune modification des tables existantes ni des jetons JWT. Aucun changement de format de
sérialisation des réponses (réutilisation de `UserResponse`).

## Security & Privacy Considerations

- **Anti-élévation de privilège (PRD §11.1)** : le rôle `HAIRDRESSER` est **imposé côté serveur** ;
  `CreateEmployeeRequest` **ne déclare aucun** champ `role`. Un gérant ne peut créer ni `MANAGER`, ni
  `ADMIN`, ni `CLIENT` via cette route.
- **Autorisation (§4.1 / §11.2)** : la route est **protégée** par `EMPLOYEE_MANAGE` **et** par la
  portée salon. Seul un **gérant** (l'`ADMIN` n'a **pas** `EMPLOYEE_MANAGE`) et **uniquement sur son
  propre salon** peut créer un employé. Un accès hors périmètre renvoie le **`403` générique**
  identique à un rôle insuffisant (**aucun oracle d'existence** de salon — invariant ADR-0015).
- **Isolation stricte** : l'appartenance `(salon_id, user_id)` est écrite en base et fait autorité
  pour la portée ; un coiffeur créé pour le salon A **n'obtient aucune portée** sur le salon B.
- **Secrets & PII (PRD §11.1 / §11.3, ADR-0012/0013)** :
  - Le mot de passe initial est **haché argon2id** ; **jamais** stocké/renvoyé/journalisé en clair.
  - `UserResponse` n'expose **ni** `password` **ni** `password_hash`.
  - Le `Principal` reste **sans PII** ; les logs de refus ne contiennent que `user_id`/`role`/route
    (ADR-0015) — **jamais** téléphone, e-mail, nom, ni jeton.
- **Journalisation (§11.4)** : « Création employé » est un événement d'audit. L'infra d'audit
  persistée est **#52** ; #13 se limite à un éventuel log **non-PII** (id de l'acteur, id du salon,
  id du compte créé, rôle) sans secret. Ne rien ajouter qui journalise un mot de passe ou un
  identifiant personnel.
- **Réutilisation d'un téléphone existant** : si le téléphone appartient déjà à un compte (p. ex. un
  client), la création échoue en `409` (contrainte `uq_users_phone`) — **pas** de « fusion » ni de
  ré-attribution silencieuse de rôle (éviterait une escalade). Comportement à documenter (voir
  *Open Questions*).
- **Connexion du nouvel employé** : le flux `POST /auth/login` (#10) applique déjà l'anti-bruteforce
  et les messages génériques. Le coiffeur peut changer son mot de passe via le reset OTP (#11).

## Testing Plan

**Unitaires (domaine/application, sans base ni serveur) :**
- `CreateEmployee.execute` : crée l'utilisateur avec `role=HAIRDRESSER`, `status=ACTIVE`, appelle
  `add_member(salon_id, user.id, HAIRDRESSER)` ; ne retourne aucun secret ; ne journalise pas le clair
  (ports simulés / *fakes*).
- Validation : nom/mot de passe/téléphone/e-mail invalides → erreurs de domaine attendues.
- Pré-check doublon téléphone → `PhoneAlreadyInUse`.
- Portée : `can_access_salon` / matrice inchangées — figer que `MANAGER` a `EMPLOYEE_MANAGE` et
  `ADMIN`/`HAIRDRESSER`/`CLIENT` ne l'ont pas (compléter `test_domain_permissions.py`).

**Intégration (base PostgreSQL, session réelle) :**
- Insertion `salon_members` : unicité `(salon_id, user_id)` → `EmployeeAlreadyInSalon` ; `CHECK`
  `role`/`status` rejettent une valeur hors domaine ; FK `RESTRICT` respectées.
- `SqlSalonScopeRepository.salon_ids_for(HAIRDRESSER)` retourne le(s) salon(s) d'appartenance
  **ACTIVE** et **exclut** ceux d'un autre utilisateur / un membre `INACTIVE`.
- **Atomicité** : si `add_member` échoue, l'utilisateur n'est **pas** persisté (rollback de requête).
- Round-trip **Alembic** `0002` (upgrade/downgrade) contre PostgreSQL 16 (parité CI).

**API (`TestClient`, dépendances surchargées) :**
- Gérant crée un coiffeur sur **son** salon → `201`, `role=HAIRDRESSER`, réponse sans secret.
- Gérant tente sur un salon **d'un autre** gérant / inexistant → `403` générique.
- `CLIENT` / `HAIRDRESSER` (permission absente) → `403`. Non authentifié → `401`. Sans `JWT_SECRET`
  → `503`.
- Champ `role` fourni dans le corps → **ignoré** (compte créé en `HAIRDRESSER`).
- Doublon téléphone/e-mail → `409` ; entrées invalides → `422`.
- **Invariant deny-by-default** : `unprotected_routes(app)` reste vide après l'ajout du router
  (test existant `test_security_guards.py` / `test_authorization_policy.py`).

**End-to-end (AC de #13) :**
- Parcours complet : (1) inscription gérant (#9) → (2) [salon inséré/possédé par le gérant] → (3)
  connexion gérant (#10) → (4) `POST /salons/{salon_id}/employees` → **201** → (5) connexion du
  coiffeur via `POST /auth/login` → **200** (jetons) → (6) le coiffeur accède à une ressource à
  portée de **son** salon → autorisé, et à un **autre** salon → `403`. (Fichier
  `tests/test_employees_e2e.py`, à l'image de `test_rbac_e2e.py`.)

**Régression :** relire/mettre à jour `test_rbac_e2e.py` et `test_domain_access.py` si un test
supposait la portée `HAIRDRESSER` **dérivée des RDV** (elle devient dérivée de l'appartenance).

## Documentation Updates

- **`docs/adr/0016-comptes-employes-appartenance-salon.md`** (nouveau) : décision — table
  `salon_members` (autorité de la portée employé), rôle `HAIRDRESSER` fixé côté serveur, route
  `/salons/{salon_id}/employees` gardée par `EMPLOYEE_MANAGE` + portée, création directe avec mot de
  passe initial (invitation par lien différée), remplacement de la dérivation par RDV. Conséquences :
  un membre `INACTIVE` perd sa portée ; audit persisté → #52.
- **`docs/adr/README.md`** : clore le suivi « table d'appartenance employé↔salon → #13 » (renvoyer
  vers ADR-0016) ; noter que la lecture de portée `HAIRDRESSER` ne dépend plus des RDV.
- **`backend/README.md`** : ajouter l'endpoint au tableau des routes ; décrire le flux gérant→coiffeur.
- **`README.md`** (racine, §3 module 1) : mentionner la **création de comptes employés** livrée.
- **Docstrings** : `salon_scope_repository.py` (branche `HAIRDRESSER`) et port
  `salon_scope_repository.py` — retirer les mentions « la table arrive avec #13 ».
- **OpenAPI** : auto-générée ; vérifier `summary`/`responses` de la nouvelle route.

## Risks and Open Questions

1. **Ordre de dépendances #13 vs #15 (création de salon).** #13 ne dépend que de #12, mais un
   employé se rattache à **un salon**. La table `salons` **existe** (schéma initial), donc l'endpoint
   et ses tests sont réalisables (salon inséré directement, `owner_id` = gérant). Cependant, en
   production, un gérant n'a **pas encore** d'API pour créer un salon (**#15**) : la route sera
   pleinement exploitable côté produit **après #15**. **À confirmer** : livrer #13 avec un salon
   pré-inséré en test (recommandé, débloque l'AC) vs attendre #15.
2. **« Création » vs « invitation ».** Décision proposée : **création directe** avec mot de passe
   initial fourni par le gérant (satisfait l'AC, indépendant des canaux e-mail/SMS différés M5).
   **Alternatives à confirmer** : (a) créer le compte **sans** mot de passe utilisable puis forcer un
   *set-password* via le reset OTP (#11) ; (b) vrai **flux d'invitation** par jeton à usage unique
   (nécessite canal e-mail réel → M5). Impacte le corps de la requête.
3. **Portée `HAIRDRESSER` : remplacer ou unir ?** Par défaut **remplacer** la dérivation par RDV par
   la lecture d'appartenance. À confirmer si une **union** (appartenance ∪ RDV assignés) est
   souhaitée pour rétro-compatibilité — a priori non nécessaire (`can_access_appointment` gère déjà
   l'assignation).
4. **Membre `INACTIVE`.** Un employé désactivé (statut d'appartenance) perd sa portée (query filtre
   `ACTIVE`). Confirmer si le **statut du compte utilisateur** et le **statut d'appartenance** doivent
   être distincts (recommandé : oui — retirer d'un salon ≠ désactiver le compte).
5. **Étendue de `EMPLOYEE_MANAGE` dans #13.** L'AC ne couvre que **création** (+ **liste** proposée).
   Modification/désactivation/retrait d'employé : hors scope #13 (issue de suivi ?).
6. **Nom de la table** (`salon_members` vs `salon_employees`) et **énumération du statut**
   d'appartenance (réutiliser `UserStatus` — recommandé). Cosmétique mais à figer avant migration.
7. **Réutilisation d'un téléphone existant** (client devenant coiffeur) : décision par défaut = **`409`**
   (pas de fusion / pas de changement de rôle d'un compte existant). À confirmer produit.

## Implementation Checklist

1. **Domaine** : ajouter l'erreur `EmployeeAlreadyInSalon` (`domain/errors.py`) ; (option) dataclass
   `SalonMembershipToCreate` (`domain/membership.py`). Ne pas toucher la matrice `permissions.py`.
2. **Port** : créer `application/ports/salon_member_repository.py` (`add_member`,
   `salon_ids_for_member`).
3. **Cas d'usage** : créer `application/employees.py` (`CreateEmployee`, `CreateEmployeeCommand`,
   rôle `HAIRDRESSER` **fixé au câblage**, atomicité user+membership, aucun secret journalisé).
4. **ORM** : ajouter la table `salon_members` dans `models.py` (conventions PK/`enum_check`/FK
   RESTRICT/unicité composite/index).
5. **Migration** : `migrations/versions/0002_salon_members.py` (`down_revision="0001"`), reflet exact
   du modèle ; `downgrade` = `DROP TABLE`. Vérifier le round-trip Alembic.
6. **Adapters sortants** : `SqlSalonMemberRepository` (retraduction `IntegrityError` →
   `EmployeeAlreadyInSalon`) ; mettre à jour `SqlSalonScopeRepository` (branche `HAIRDRESSER` →
   `salon_members` `ACTIVE`) + docstring.
7. **Adapter entrant** : `adapters/inbound/employees.py` — `POST /salons/{salon_id}/employees`, gardé
   par `require_permission(EMPLOYEE_MANAGE)` + `require_salon_scope` ; `CreateEmployeeRequest` **sans
   `role`** ; DI du use case (`role=HAIRDRESSER`) ; mapping d'erreurs (`409`/`422`) ; réponse `201`
   `UserResponse`. (Option) `GET /salons/{salon_id}/employees`.
8. **Composition root** : `app.include_router(employees_router)` dans `main.py`.
9. **Tests** : unitaires (use case, permissions), intégration (membership, scope, atomicité, Alembic),
   API (201/401/403/409/422/503, `role` ignoré, deny-by-default), e2e (gérant crée coiffeur →
   coiffeur se connecte → périmètre restreint). Mettre à jour les tests de portée impactés.
10. **Docs** : ADR-0016 ; clôture du suivi #13 dans `docs/adr/README.md` ; `backend/README.md` ;
    `README.md` racine ; docstrings scope repository/port.
11. **Vérifs finales** : `ruff check`, `pytest` (paquet backend) au vert ; invariant
    `unprotected_routes(app)` vide ; aucun secret/PII dans les logs ou les réponses.
