# Rôle et authentification de la borne terminal (US-8.1)

> Spécification de planification pour l'issue GitHub **#155 — US-8.1 · Rôle & authentification
> borne** (`feature`, `security` · Must · Effort M · jalon **M7 — Borne client (terminal
> libre-service), Épic 8**). **Dépend de : #12** (RBAC deny-by-default). #155 est l'issue
> **fondatrice** du jalon : #156, #157, #159 et #161 en dépendent directement.
> **Cette spec ne produit pas de code : elle décrit l'approche à implémenter dans une phase
> ultérieure.**
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon M7 (BACKLOG.md, promu depuis le PRD §17 « Borne Intelligente d'Accueil ») installe une
**borne tactile physique en salon** sur laquelle un client **sans rendez-vous** s'identifie par
téléphone (ou crée une fiche), choisit une prestation et reçoit un ticket de passage imprimé.
Cette borne est un **terminal public partagé** : elle doit appeler le backend en son nom propre,
en continu, sans qu'aucun humain ne s'y connecte.

Or **rien dans le dépôt ne permet d'authentifier un terminal** :

- **Le RBAC est fermé sur exactement quatre rôles personnels.** `Role` déclare `CLIENT`,
  `HAIRDRESSER`, `MANAGER`, `ADMIN` (`backend/coiflink_api/domain/enums.py:30-37`) et la matrice
  `ROLE_PERMISSIONS` (`domain/permissions.py:84-139`) est « exhaustive et fermée » (commentaire
  `permissions.py:81-83`) : un rôle absent de la table n'a **aucune** permission
  (`permissions_for`, `permissions.py:142-153`).
- **Aucun rôle existant ne convient à la borne.** Le parcours walk-in exige de retrouver/créer une
  fiche client **et** de créer un ticket de passage. Créer une fiche
  (`POST /salons/{salon_id}/customers`) exige `Permission.CUSTOMER_MANAGE`
  (`adapters/inbound/customers.py:453-456`), détenue par le **seul** `MANAGER`
  (`permissions.py:121`) — un credential `MANAGER` sur une borne publique exposerait la caisse,
  les fiches complètes (notes privées, allergies) et la gestion du salon. Réserver un rendez-vous
  exige `Permission.APPOINTMENT_BOOK` (`adapters/inbound/appointments.py:538-551`), détenue par le
  **seul** `CLIENT` (`permissions.py:92`), et `client_id` provient toujours du `Principal` JWT —
  une session `CLIENT` partagée sur une borne mélangerait les rendez-vous de tous les passants sur
  **un** compte. Aucun rôle ne peut faire les deux, et c'est voulu.
- **L'authentification actuelle est exclusivement personnelle.** `POST /auth/login`
  (`adapters/inbound/auth.py:360-400`) authentifie un **compte** (téléphone/e-mail + mot de passe,
  `application/authentication.py:80-120`) et émet une paire JWT courte (accès 15 min par défaut,
  `adapters/outbound/security/jwt_token_service.py:44-45`). Chaque requête protégée vérifie la
  signature sans I/O (`adapters/inbound/security.py:298-319`) puis **relit** rôle et statut en base
  (`security.py:381-412`, anti-élévation). Aucun mécanisme de clé API, de jeton « par salon » ou de
  compte « device » n'existe.
- **Le deny-by-default est mécaniquement verrouillé.** `require_authenticated` est une dépendance
  globale (`main.py:51-56`) ; toute route publique doit être listée dans `PUBLIC_ROUTE_PATHS`
  (`security.py:104-135`) avec revue de sécurité obligatoire (`security.py:44`, `security.py:102`) ;
  l'invariant `unprotected_routes(app) == []` (`security.py:248-260`, exécuté par
  `tests/test_security_guards.py`) fait échouer la CI sur toute route ni publique-listée ni gardée.

Le gap que #155 comble : **une identité de terminal** — rôle dédié, credential de device longue
durée provisionné par le gérant, portée figée sur **un** salon, permissions minimales — sur laquelle
#156 (recherche téléphone + fiche walk-in), #157 (ticket de passage) et #159 (mode terminal de l'app)
pourront poser leurs gardes **sans jamais** accorder `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK`. Les
specs sœurs du jalon comptent explicitement sur #155 pour ce socle :
`specs/borne-ticket-file-attente-walkin.md` consomme une garde et une permission posées ici
(proposition `Permission.QUEUE_TICKET_CREATE`), et `specs/borne-app-mobile-mode-kiosque.md` attend
de #155 « la forme du credential device » et son contrat HTTP.

## Goals

- **Introduire une identité de terminal `TERMINAL`** : cinquième membre de l'énumération fermée
  `Role`, avec une entrée dédiée dans `ROLE_PERMISSIONS` — jamais un JWT `CLIENT`/`MANAGER`
  personnel partagé sur la borne (décision d'architecture n°1 du jalon, à valider — voir *Risks*).
- **Permissions minimales et dédiées**, définies par #155 et consommées par #156/#157 :
  `CUSTOMER_LOOKUP_TERMINAL` (recherche d'une fiche par téléphone, restreinte au salon de la borne),
  `CUSTOMER_CREATE_WALKIN` (création de fiche nom/prénom/téléphone sans mot de passe),
  `QUEUE_TICKET_CREATE` (création d'un ticket de passage). Le rôle `TERMINAL` détient **exactement**
  ces trois permissions — ni `CUSTOMER_MANAGE`, ni `APPOINTMENT_BOOK`, ni aucune autre.
- **Lecture du catalogue sans droit supplémentaire.** Le critère « lecture catalogue » de l'issue
  est satisfait par les routes **publiques** existantes `/catalog/salons/{salon_id}`
  (`security.py:118-133`), que #158 enrichit d'une photo — accorder `SERVICE_READ` à la borne
  ouvrirait la vue **gérant** (prestations inactives incluses) : refusé au titre du moindre
  privilège.
- **Provisioning par le gérant** : `POST /salons/{salon_id}/terminal-devices` (nouvelle permission
  `TERMINAL_PROVISION`, `MANAGER` uniquement, gardée par `require_salon_scope`) crée un **compte de
  service device** (ligne `users` au rôle `TERMINAL` + rattachement `salon_members` au salon) et
  retourne **une seule fois** un secret aléatoire ; le secret n'est stocké que **haché** (argon2id,
  port `PasswordHasher` existant). Lecture (`GET`) et révocation (`DELETE`) minimales incluses.
- **Credential device longue durée, distinct des JWT personnels** : la borne détient le couple
  `(device_id, secret)` durablement, et l'échange contre une paire JWT **standard et courte** via
  `POST /auth/terminal/login` (rate-limité, message d'échec générique). Les JWT restent courts : c'est
  le **secret révocable** qui est long, jamais le jeton porteur.
- **Portée mono-salon figée au provisioning** : la portée du device est lue en base depuis
  `salon_members` (extension de `SqlSalonScopeRepository.salon_ids_for`,
  `adapters/outbound/persistence/salon_scope_repository.py:38-53`, et de `can_access_salon`,
  `domain/access.py:81-97`) — jamais déduite d'un paramètre de requête (décision n°8 du jalon).
- **Révocation à effet immédiat** : suspendre le compte device (`users.status`) coupe l'accès à la
  requête suivante, grâce à la relecture en base de `get_current_principal`
  (`security.py:381-412`) — aucun jeton à invalider.
- **Test RBAC négatif ajouté à la matrice existante** (critère d'acceptation) : `Role.TERMINAL` entre
  dans `_ALL_ROLES` de `tests/test_security_authz_matrix.py:66`, ce qui l'exerce mécaniquement en
  `403` sur toutes les routes échantillonnées (dont `CUSTOMER_MANAGE` et `APPOINTMENT_BOOK`) ; la
  matrice de domaine (`tests/test_domain_permissions.py`) gagne un jeu `_TERMINAL_EXPECTED` exact.
- **Journalisation §11.4** du provisioning et de la révocation (`TERMINAL_DEVICE_PROVISIONED`,
  `TERMINAL_DEVICE_REVOKED`), sans secret ni PII dans `metadata`.
- **Décision d'architecture tracée** : `docs/adr/0041-authentification-borne-kiosque.md`,
  committée avec l'implémentation de #155 (voir *Documentation Updates* et *Risks*).

## Non-Goals

- **Les endpoints métier de la borne.** La recherche par téléphone et la création de fiche walk-in
  sont l'objet de **#156** ; le ticket de passage et l'ETA de **#157**. #155 pose le rôle, le
  credential, la portée et les permissions qu'ils consommeront — pas leurs routes.
- **L'app mobile en mode terminal (#159)** : le stockage sécurisé du credential sur le device et
  l'écran de saisie du credential au premier lancement sont livrés par #159 (port de stockage
  dédié + écran, cf. `specs/borne-app-mobile-mode-kiosque.md`), de même que les autres écrans et
  le timer d'inactivité — hors périmètre ici ; #155 fournit le contrat HTTP et le format du
  credential.
- **L'impression du ticket (#160)** et **la procédure opérationnelle de provisioning** (PIN gérant,
  sortie du mode terminal, mise à jour applicative — **#161**). #155 livre l'API de provisioning et
  sa documentation technique, pas le mode opératoire terrain.
- **Interface web gérant de gestion des bornes.** Le provisioning V1 est exploitable par API
  (documenté par un exemple `curl` dans `backend/README.md`) ; une page dédiée du dashboard est un
  suivi possible, non exigé par l'issue (voir *Risks* §7).
- **Hors scope du jalon M7 tout entier** (rappel des frontières, différées mais réévaluables) :
  vérification/check-in d'un rendez-vous existant depuis la borne, identification par QR code ou
  code de réservation (PRD §17.3), affichage temps réel des coiffeurs disponibles avant
  affectation, paiement autonome sur la borne.
- **Mécanismes matériels ou réseau avancés** : MDM, attestation de device, mTLS, rotation
  automatique de secret, allowlist d'IP — hors périmètre MVP (documentés comme suivis dans l'ADR).
- **Aucune modification des droits des rôles existants.** `CLIENT`, `HAIRDRESSER` et `ADMIN` sont
  inchangés ; `MANAGER` ne gagne **que** `TERMINAL_PROVISION` (aucun retrait, aucun élargissement
  d'un droit existant).

## Relevant Repository Context

### RBAC et authentification (état vérifié)

- **Rôles fermés** : `Role` = `CLIENT`/`HAIRDRESSER`/`MANAGER`/`ADMIN`
  (`domain/enums.py:30-37`), énumérations `str` dont la persistance **dérive** les contraintes
  `CHECK` (`enums.py:1-15`, helper `enum_check`, `adapters/outbound/persistence/models.py:99-109`).
- **Matrice** : `Permission` (`domain/permissions.py:33-79`) et `ROLE_PERMISSIONS`
  (`permissions.py:84-139`), « unique source de vérité des droits » (`permissions.py:1-8`).
  `CUSTOMER_MANAGE` : `MANAGER` seul (`permissions.py:121`) ; `APPOINTMENT_BOOK` : `CLIENT` seul
  (`permissions.py:92`) ; `EMPLOYEE_MANAGE` : `MANAGER` seul (`permissions.py:120`).
- **Chaîne d'autorisation** (`adapters/inbound/security.py`) : garde globale
  `require_authenticated` (`main.py:51-56`) → `get_current_principal` (relecture base,
  `security.py:381-412`) → `require_permission` (`security.py:437-450`) → `require_salon_scope`
  (`security.py:479-501`). Refus `403` **constant et générique** (`security.py:88`,
  `application/authorization.py:30-32`).
- **Portée salon** : `AccessPolicy.scope_of`/`require_salon`
  (`application/authorization.py:53-79`) → `can_access_salon` (`domain/access.py:81-97`, qui
  n'accorde une portée salon qu'aux rôles listés **explicitement** ligne 95) →
  `SqlSalonScopeRepository.salon_ids_for` (`salon_scope_repository.py:38-53` : `MANAGER` via
  `salons.owner_id`, `HAIRDRESSER` via `salon_members` `ACTIVE`, tout autre rôle → portée vide).
- **JWT** : `JwtTokenService` (PyJWT, HS256, claims `sub/role/type/iat/exp/jti` sans PII,
  `jwt_token_service.py:36-121`), assemblé dans `main.py:96-103`. Le claim `role` est
  **informatif** (`domain/tokens.py:15-18`) : seul le rôle relu en base autorise.
- **Login personnel** : `POST /auth/login` (`auth.py:360-400`), classification téléphone/e-mail
  (`application/authentication.py:109-120`), anti-bruteforce via le port `LoginRateLimiter`
  (`auth.py:306-318`, `429` + `Retry-After` `auth.py:383-388`). `normalize_phone` produit toujours
  `+<chiffres>` (`domain/phone.py:36-69`) — fait exploité en §D ci-dessous.
- **Hachage** : port `PasswordHasher` (`application/ports/password_hasher.py:14-21`), adapter
  argon2id (`adapters/outbound/security/argon2_hasher.py:1-8`).

### Tests qui figent les rôles et la matrice (impact direct — point (b) de l'issue)

Un grep `Role`/`ROLE_PERMISSIONS` sur `backend/tests/` identifie **trois verrous** :

1. **`tests/test_domain_permissions.py:203`** — `set(ROLE_PERMISSIONS.keys()) == set(Role)` : la
   table doit couvrir **tous** les membres de `Role`. Ajouter `TERMINAL` à l'enum **sans** entrée dans
   `ROLE_PERMISSIONS` fait échouer ce test (et `:35-37`, qui exige chaque rôle dans la table).
   Aucun test ne fige le **nombre** de rôles à quatre : il fige l'**alignement** enum ↔ matrice.
2. **`tests/test_domain_permissions.py`** — jeux exacts par rôle : `_CLIENT_EXPECTED` (`:44-53`),
   `_HAIRDRESSER_EXPECTED` (`:111`), `_MANAGER_EXPECTED` (`:150`), `_ADMIN_EXPECTED` (`:173`).
   `MANAGER` gagnant `TERMINAL_PROVISION`, `_MANAGER_EXPECTED` **doit** être mis à jour ; un
   `_TERMINAL_EXPECTED` exact est à ajouter (avec les tests négatifs miroirs, patron `:77-89`).
3. **`tests/test_security_authz_matrix.py:66`** — `_ALL_ROLES` est un tuple **écrit à la main** des
   quatre rôles ; les rôles refusés d'une route en sont dérivés (`:185-197`, `denied =
   set(_ALL_ROLES) - route.allowed_roles`). Ajouter `Role.TERMINAL` à ce tuple suffit pour que la
   matrice négative **exerce automatiquement** `TERMINAL` en `403` sur chaque route échantillonnée —
   c'est exactement le « test RBAC négatif ajouté à la matrice existante » du critère
   d'acceptation.

Les autres suites (`test_domain_access.py:117-122`, `test_authorization_policy.py`) paramètrent des
listes de rôles à la main mais ne cassent pas à l'ajout d'un membre : elles sont à **compléter**
(couverture `TERMINAL`), pas à réparer.

### Schéma et migrations (impact base)

- `users` : `role String(32) NOT NULL` + `CHECK` dérivé de `Role`
  (`models.py:126`, `models.py:135` → contrainte `ck_users_role` par convention de nommage) ;
  `phone String(32) NOT NULL` + `UNIQUE uq_users_phone` (`models.py:121`, `:134`) ;
  `password_hash NOT NULL` (`models.py:125`) ; `status` avec défaut `ACTIVE` (`models.py:127-129`).
- `salon_members` : `role String(32)` + `CHECK ck_salon_members_role` dérivé de `Role`
  (`models.py:198`, `:223`), unicité `(salon_id, user_id)` (`:219`), `status` (`:224`).
- **Patron de régénération d'un `CHECK` d'enum** : migrations `0007`/`0008`
  (`migrations/versions/0007_notification_new_booking_type.py:55-73` — drop + recreate, downgrade
  symétrique, round-trip CI). Tête actuelle : **`0012`** (`0012_payment_receipt_number.py`).

### Précédent « compte créé par le gérant » (patron du provisioning)

`CreateEmployee` (`application/employees.py`) : le gérant crée un compte `HAIRDRESSER` (ligne
`users` + rattachement `salon_members`) sous `EMPLOYEE_MANAGE`
(`adapters/inbound/employees.py:238-260`), écritures atomiques et audit `EMPLOYEE_CREATED`
(`domain/audit.py:128`) sans secret journalisé (`employees.py:18`). Le provisioning d'une borne est
le **même geste** — compte de service au lieu de compte personnel, secret généré au lieu d'un mot
de passe choisi.

### Coordination avec les specs sœurs du jalon

- `specs/borne-ticket-file-attente-walkin.md` (#157) suppose le rôle `TERMINAL`, sa garde de portée
  device→salon et propose le nom `Permission.QUEUE_TICKET_CREATE` en précisant que « sa définition
  formelle relève de #155 » — repris tel quel ici.
- `specs/borne-app-mobile-mode-kiosque.md` (#159) attend de #155 la forme du credential ; la
  réponse de login **porte le `salon_id`** — mécanisme retenu pour tout le jalon (un APK unique
  pour toutes les bornes, pas de `--dart-define` de salon par device en production), alignement
  inter-specs acté, #159 s'y conforme (voir *API / Interface Changes*).
- `specs/borne-adr-provisioning-documentation.md` (#161) vérifie la présence des **deux ADR** du
  jalon — `0041-authentification-borne-kiosque.md` committée avec #155,
  `0042-file-attente-walkin-queue-ticket.md` committée avec #157 —, met à jour l'index
  `docs/adr/README.md` pour les deux et porte le runbook de provisioning (`docs/adr/` s'arrête à
  `0040-impression-recu-encaissement-gerant.md` : prochain numéro libre **`0041`**). Voir
  *Documentation Updates* et *Risks* §6.

## Proposed Implementation

### (A) Décision structurante : deux options évaluées, une retenue

**Option 1 — étendre l'enum `Role` d'un cinquième membre `TERMINAL`, le device étant un compte de
service dans `users` (retenue).**

- La borne devient un `Principal` ordinaire : **toute** la chaîne existante est réutilisée sans
  duplication — émission JWT (`JwtTokenService`), garde globale, relecture base
  (`get_current_principal`), matrice `ROLE_PERMISSIONS`, `require_permission`,
  `require_salon_scope`, invariant `unprotected_routes`, audit (`actor_user_id` FK `users`).
- Coûts, tous bornés et mécaniquement vérifiés : entrée `ROLE_PERMISSIONS[Role.TERMINAL]` (verrou
  `test_domain_permissions.py:203`) ; migration régénérant `ck_users_role` et
  `ck_salon_members_role` (patron `0007`) ; ajout explicite de `Role.TERMINAL` dans
  `can_access_salon` (`access.py:95`) et `salon_ids_for` (`salon_scope_repository.py:43-47`) ;
  `Role.TERMINAL` dans `_ALL_ROLES` (`test_security_authz_matrix.py:66`).
- Verrue assumée : `users.phone` est `NOT NULL UNIQUE` — un device n'a pas de téléphone. Traitée
  en §D par une **valeur sentinelle inerte** (et une alternative documentée, *Risks* §4).

**Option 2 — mécanisme d'authentification device entièrement parallèle au `Principal` JWT
personnel (écartée).** Table `terminal_devices` autonome, clé API ou type de jeton dédié, famille de
gardes `require_terminal_device` distincte. Écartée car chaque brique de sécurité existante devrait
être **dupliquée puis re-prouvée** :

- une seconde famille de gardes devrait être marquée `_PRINCIPAL_GUARD_ATTR`
  (`security.py:141-154`) pour que `unprotected_routes` (`security.py:248-260`) la reconnaisse —
  sinon l'invariant deny-by-default devient faux ou aveugle ;
- les droits du device vivraient **hors** de `ROLE_PERMISSIONS`, en contradiction frontale avec
  « l'unique source de vérité des droits » (`permissions.py:1-8`) et avec la matrice négative
  dérivée (`test_security_authz_matrix.py`), qui ne verrait jamais ce principal ;
- les routes de #156/#157 devraient accepter **deux** types de principal (device pour la borne,
  `Principal` pour d'éventuels usages gérant), doublant gardes et tests ;
- l'audit (`actor_user_id` → `users`) et la révocation immédiate (relecture du statut,
  `security.py:381-412`) devraient être réinventés pour les devices.

Deux systèmes d'autorisation parallèles dans un backend dont la sécurité repose sur des invariants
**centralisés et testés** : le risque de divergence dépasse largement le gain de pureté du modèle.
**Recommandation : Option 1**, en notant que le compte de service `users` reste un détail
d'implémentation encapsulé (un port `TerminalDeviceRepository` dédié permettrait de migrer plus tard
vers une table propre sans toucher les gardes).

### (B) Domaine — rôle, permissions, portée

1. **`domain/enums.py`** — cinquième membre :

   ```python
   @unique
   class Role(_StrEnum):
       """Rôles utilisateur (PRD §9.1) + identité de terminal (US-8.1, #155)."""
       CLIENT = "CLIENT"
       HAIRDRESSER = "HAIRDRESSER"
       MANAGER = "MANAGER"
       ADMIN = "ADMIN"
       # Compte de service d'une borne terminal (jalon M7) : jamais un humain.
       TERMINAL = "TERMINAL"
   ```

2. **`domain/permissions.py`** — quatre nouvelles permissions dans `Permission` (docstrings
   référençant US-8.1/#155 et leurs consommateurs) :
   - `CUSTOMER_LOOKUP_TERMINAL` — recherche d'une fiche `CustomerProfile` par téléphone, restreinte
     au salon de la borne, réponse minimale (consommée par #156) ;
   - `CUSTOMER_CREATE_WALKIN` — création d'une fiche walk-in nom/prénom/téléphone **sans**
     compte ni mot de passe (consommée par #156) ;
   - `QUEUE_TICKET_CREATE` — création d'un ticket de passage walk-in (consommée par #157 ; nom
     déjà anticipé par sa spec) ;
   - `TERMINAL_PROVISION` — provisionner/lister/révoquer les bornes de **son** salon (consommée par
     #155 lui-même, `MANAGER` uniquement).

   Matrice :

   ```python
   Role.TERMINAL: frozenset(
       {
           Permission.CUSTOMER_LOOKUP_TERMINAL,
           Permission.CUSTOMER_CREATE_WALKIN,
           Permission.QUEUE_TICKET_CREATE,
       }
   ),
   ```

   et `Permission.TERMINAL_PROVISION` ajoutée au bloc `Role.MANAGER` (`permissions.py:110-126`).
   Ni `CUSTOMER_MANAGE`, ni `APPOINTMENT_BOOK`, ni aucune permission de lecture gérant n'entrent
   dans le jeu `TERMINAL` — c'est le cœur du critère d'acceptation négatif.

3. **`domain/access.py`** — `can_access_salon` (`access.py:81-97`) : ajouter `Role.TERMINAL.value` au
   tuple des rôles à portée explicite (ligne 95). `can_access_appointment` (`access.py:100-123`)
   reste **inchangé** : `TERMINAL` tombe dans le `return False` final (aucun accès aux rendez-vous) —
   propriété à figer par un test.

### (C) Persistance — portée et migration `0013`

1. **`adapters/outbound/persistence/salon_scope_repository.py`** — `salon_ids_for`
   (`:38-53`) : la branche `HAIRDRESSER` (lecture `salon_members` `ACTIVE`) devient
   `role in (Role.HAIRDRESSER.value, Role.TERMINAL.value)` — la portée d'une borne est son
   rattachement d'appartenance, exactement comme un employé (ADR-0016). Une borne révoquée
   (`salon_members.status = INACTIVE`) perd sa portée par le même filtre.
2. **Migration `migrations/versions/0013_kiosk_role.py`** (`down_revision = "0012"`) — patron
   exact de `0007` (`0007_notification_new_booking_type.py:55-73`) :
   - `upgrade()` : drop + recreate de `ck_users_role` et `ck_salon_members_role` avec la liste
     incluant `'TERMINAL'` (valeurs dérivées de `enums.Role`) ;
   - `downgrade()` : symétrique (listes sans `'TERMINAL'`) — round-trip Alembic exigé par la CI.
     Le `downgrade` échouerait si des lignes `TERMINAL` existent : comportement acceptable et
     documenté (même sémantique que retirer une valeur d'enum utilisée).
   - **Aucune nouvelle table, aucune nouvelle colonne** : c'est l'argument de poids de l'Option 1.
   - Coordination : ordre acté avec #157 — #155 livre `0013_kiosk_role.py`
     (`down_revision = "0012"`), #157 enchaîne avec `0014_queue_tickets.py`
     (`down_revision = "0013"`) ; numéros à revalider selon l'ordre réel de merge (réserve
     portée par les deux specs).

### (D) Identité du device — compte de service `users` + rattachement `salon_members`

Un device provisionné = deux lignes, créées atomiquement (même `Session`, patron
`CreateEmployee`) :

- **`users`** : `id` (UUID = `device_id` public), `role = 'TERMINAL'`, `status = 'ACTIVE'`,
  `full_name` = libellé donné par le gérant (ex. « Borne entrée »), `password_hash` =
  argon2id(secret généré), `email = NULL`.
  - **`phone`** (colonne `NOT NULL UNIQUE`, `models.py:121/:134`) : valeur **sentinelle**
    `id.hex` (32 caractères hexadécimaux — tient exactement dans `String(32)`, unique par
    construction). Innocuité vérifiable : `normalize_phone` produit **toujours** une chaîne
    commençant par `+` (`domain/phone.py:69`) et `classify_identifier` du login ne résout que des
    téléphones normalisés ou des e-mails (`application/authentication.py:109-120`) — la sentinelle
    est donc **inatteignable** depuis `/auth/login`, le reset de mot de passe et toute recherche
    par téléphone. Alternative (rendre `users.phone` nullable) écartée en V1 mais documentée
    (*Risks* §4).
- **`salon_members`** : `(salon_id, user_id=device_id, role='TERMINAL', status='ACTIVE')` — porte la
  portée mono-salon (décision n°8 du jalon : le `salon_id` est figé **une fois**, au
  provisioning ; aucune sélection de salon à l'écran de la borne).

**Révocation** = `users.status → SUSPENDED` **et** `salon_members.status → INACTIVE` (défense en
profondeur : le premier coupe tout via `get_current_principal`, `security.py:409-410` ; le second
vide la portée). Effet **immédiat**, sans invalidation de jeton : c'est la conséquence directe de
la relecture en base par requête (ADR-0015).

### (E) Provisioning — port, cas d'usage, endpoints gérant

1. **Port `application/ports/terminal_device_repository.py`** (`Protocol`, salon-scopé) :
   `create(device: TerminalDeviceToCreate) -> TerminalDevice`,
   `list_for_salon(salon_id) -> tuple[TerminalDevice, ...]`,
   `find_by_id(salon_id, device_id) -> TerminalDevice | None`,
   `find_credentials(device_id) -> TerminalDeviceCredentials | None` (pour le login),
   `revoke(salon_id, device_id) -> TerminalDevice`. L'implémentation SQL encapsule le fait que le
   device vit dans `users` + `salon_members` — les cas d'usage n'en savent rien.
2. **Domaine `domain/terminal_device.py`** (pur) : `validate_device_label` (trim, non vide, ≤ 255,
   erreur dédiée `InvalidTerminalDeviceLabel`), dataclasses gelées `TerminalDeviceToCreate`,
   `TerminalDevice` (`id`, `salon_id`, `label`, `status`, `created_at` — **jamais** le secret ni son
   hash), `TerminalDeviceCredentials` (`id`, `salon_id`, `password_hash`, `status` — usage interne
   login). Erreurs `TerminalDeviceNotFound`, `TerminalDeviceRevoked`.
3. **Cas d'usage `application/terminal_devices.py`** :
   - `ProvisionTerminalDevice.execute(salon_id, command, *, actor_user_id) -> (TerminalDevice, str)` :
     valide le libellé ; génère le secret (`secrets.token_urlsafe(32)`, ~43 caractères, entropie
     256 bits) ; hache via le port `PasswordHasher` ; crée les deux lignes ; journalise
     `TERMINAL_DEVICE_PROVISIONED` (`metadata = {}` — ni secret, ni hash, ni libellé) ; retourne
     l'entité **et le secret en clair, une seule fois** — jamais persisté, jamais journalisé,
     jamais relisible.
   - `ListTerminalDevices.execute(salon_id)` (lecture, pas d'audit).
   - `RevokeTerminalDevice.execute(salon_id, device_id, *, actor_user_id)` → audit
     `TERMINAL_DEVICE_REVOKED`.
4. **Router `adapters/inbound/terminal_devices.py`** (`prefix="/salons"`, patron
   `employees.py:83/:238-260`) — trois routes, toutes `require_salon_scope` +
   `require_permission(Permission.TERMINAL_PROVISION)` : `POST /{salon_id}/terminal-devices` (`201`),
   `GET /{salon_id}/terminal-devices` (`200`), `DELETE /{salon_id}/terminal-devices/{device_id}`
   (`200`, révocation logique — jamais de suppression physique, traçabilité §11.4). **Aucune** de
   ces routes n'entre dans `PUBLIC_ROUTE_PATHS`.
5. **Audit** : `domain/audit.py` gagne `ENTITY_TYPE_TERMINAL_DEVICE = "terminal_device"` et les actions
   `TERMINAL_DEVICE_PROVISIONED` / `TERMINAL_DEVICE_REVOKED` (patron `EMPLOYEE_CREATED`,
   `audit.py:128-131`).

### (F) Authentification du device — `POST /auth/terminal/login`

Nouvel endpoint dans `adapters/inbound/auth.py` (ou module frère), **ajouté à
`PUBLIC_ROUTE_PATHS`** avec le commentaire de revue de sécurité obligatoire (`security.py:102`)
— c'est un endpoint d'authentification, au même titre que `/auth/login` :

- corps `{ "device_id": "<uuid>", "secret": "<secret>" }` ;
- cas d'usage `AuthenticateTerminalDevice` : rate-limiting par le port `LoginRateLimiter` existant
  (clé = `device_id`, patron `auth.py:306-318`, `429` + `Retry-After`) ; charge
  `find_credentials(device_id)` ; vérifie le hash (`PasswordHasher.verify`) **et**
  `status == ACTIVE` ; tout échec (device inconnu, secret faux, device révoqué) → **même `401`
  générique** (aucun oracle sur l'existence ou l'état d'un device) ;
- succès → `token_service.issue_pair(device_id, Role.TERMINAL.value)` : paire JWT **standard**
  (accès 15 min, refresh 30 j — TTL applicatifs inchangés, `main.py:96-103`). La réponse ajoute
  `salon_id` au `TokenResponse` terminal (voir *API / Interface Changes*) pour que l'app borne
  apprenne son salon au provisioning sans configuration compilée — mécanisme retenu pour tout le
  jalon : un APK unique pour toutes les bornes, pas de `--dart-define` de salon par device en
  production (alignement inter-specs acté, la spec #159 s'y conforme).

La « longue durée » exigée par l'issue est portée par le **secret device révocable** (stocké côté
borne, propriété de #159/#161), pas par un JWT à TTL étendu : un jeton porteur long sur un terminal
public serait irrévocable pendant toute sa durée de vie (`_verify_access` est stateless,
`security.py:298-319`), alors que secret long + jetons courts + relecture du statut par requête
donne une révocation immédiate. Le device ré-échange son secret quand son refresh expire.

### (G) Câblage et tests d'invariants

`main.py` : `app.include_router(terminal_devices_router)` avec le commentaire de câblage standard
(permission, portée, audit). L'invariant `unprotected_routes(app) == []`
(`tests/test_security_guards.py`) couvre automatiquement les nouvelles routes ; la mise à jour des
verrous de tests est détaillée dans *Testing Plan*.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/domain/terminal_device.py` | entités + validation pures (libellé, erreurs dédiées) |
| `coiflink_api/application/ports/terminal_device_repository.py` | port `Protocol` (création, liste, credentials, révocation) |
| `coiflink_api/application/terminal_devices.py` | `ProvisionTerminalDevice`, `ListTerminalDevices`, `RevokeTerminalDevice` |
| `coiflink_api/application/terminal_authentication.py` | `AuthenticateTerminalDevice` (rate-limit, verify, issue_pair) |
| `coiflink_api/adapters/outbound/persistence/terminal_device_repository.py` | implémentation SQL (`users` + `salon_members`, encapsulé) |
| `coiflink_api/adapters/inbound/terminal_devices.py` | router `/salons/{salon_id}/terminal-devices` (`TERMINAL_PROVISION`) |
| `migrations/versions/0013_kiosk_role.py` | régénération `ck_users_role` + `ck_salon_members_role` |
| `tests/test_domain_terminal_device.py`, `tests/test_terminal_device_usecases.py`, `tests/test_terminal_device_api.py`, `tests/test_terminal_auth_api.py`, `tests/test_terminal_e2e.py` | tests |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/enums.py` | `Role.TERMINAL` (l'enum reste fermée : cinq membres) |
| `coiflink_api/domain/permissions.py` | 4 permissions ; entrée `Role.TERMINAL` ; `TERMINAL_PROVISION` au `MANAGER` |
| `coiflink_api/domain/access.py` | `can_access_salon` : `Role.TERMINAL` parmi les rôles à portée explicite (`:95`) |
| `coiflink_api/domain/audit.py` | `ENTITY_TYPE_TERMINAL_DEVICE`, `TERMINAL_DEVICE_PROVISIONED`, `TERMINAL_DEVICE_REVOKED` |
| `coiflink_api/domain/errors.py` | `InvalidTerminalDeviceLabel`, `TerminalDeviceNotFound`, `TerminalDeviceRevoked` |
| `coiflink_api/adapters/outbound/persistence/salon_scope_repository.py` | branche `TERMINAL` (lecture `salon_members`, `:38-53`) |
| `coiflink_api/adapters/inbound/auth.py` | `POST /auth/terminal/login` (+ schémas Pydantic) |
| `coiflink_api/adapters/inbound/security.py` | `"/auth/terminal/login"` dans `PUBLIC_ROUTE_PATHS` + commentaire de revue |
| `coiflink_api/main.py` | `include_router(terminal_devices_router)` + commentaire de câblage |
| `tests/test_domain_permissions.py` | `_TERMINAL_EXPECTED` exact ; `_MANAGER_EXPECTED` + `TERMINAL_PROVISION` ; négatifs `CUSTOMER_MANAGE`/`APPOINTMENT_BOOK` refusés à `TERMINAL` |
| `tests/test_security_authz_matrix.py` | `Role.TERMINAL` dans `_ALL_ROLES` (`:66`) |
| `tests/test_domain_access.py` | portée `TERMINAL` (couvert/non couvert), `can_access_appointment` → `False` |
| `tests/test_authorization_policy.py` | `scope_of` d'un principal `TERMINAL` |
| `tests/conftest.py` | `FakeTerminalDeviceRepository` + fixtures |
| `backend/README.md` | section « Borne terminal — rôle, provisioning & authentification (US-8.1, #155) » |

Aucun fichier de `web-dashboard/` ni d'`app-mobile/` n'est modifié par #155 (le provisioning V1
est API-first ; l'app borne est #159).

### À lire (sans modifier) pour rester fidèle aux patrons

`adapters/inbound/employees.py`, `application/employees.py`, `application/authentication.py`,
`adapters/inbound/security.py`, `application/authorization.py`, `domain/permissions.py`,
`migrations/versions/0007_notification_new_booking_type.py`,
`specs/borne-ticket-file-attente-walkin.md`, `specs/borne-app-mobile-mode-kiosque.md`,
`specs/borne-adr-provisioning-documentation.md`.

## API / Interface Changes

Quatre **nouveaux** endpoints ; aucune route existante modifiée ; seule `/auth/terminal/login` entre
dans `PUBLIC_ROUTE_PATHS` (revue de sécurité tracée en commentaire).

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/terminal-devices` | `TERMINAL_PROVISION` + portée salon | `201` device + secret (une fois) · `401` · `403` · `422` |
| `GET` | `/salons/{salon_id}/terminal-devices` | `TERMINAL_PROVISION` + portée salon | `200` liste (sans secret) · `401` · `403` |
| `DELETE` | `/salons/{salon_id}/terminal-devices/{device_id}` | `TERMINAL_PROVISION` + portée salon | `200` device révoqué · `401` · `403` · `404` |
| `POST` | `/auth/terminal/login` | publique-listée, rate-limitée | `200` paire JWT + `salon_id` · `401` générique · `429` |

```jsonc
// POST /salons/{salon_id}/terminal-devices — corps
{ "label": "Borne entrée" }

// 201 — LE SECRET N'EST RENVOYÉ QU'ICI, UNE SEULE FOIS
{
  "id": "…uuid…",                    // device_id à saisir sur la borne
  "salon_id": "…uuid…",
  "label": "Borne entrée",
  "status": "ACTIVE",
  "created_at": "2026-08-10T09:00:00Z",
  "secret": "k7Yw…43-caractères…Qc"   // jamais stocké en clair, jamais relisible
}

// POST /auth/terminal/login — corps
{ "device_id": "…uuid…", "secret": "k7Yw…Qc" }

// 200 — TokenResponse terminal
{
  "access_token": "…jwt…",           // claims: sub=device_id, role="TERMINAL", type="access"
  "refresh_token": "…jwt…",
  "token_type": "bearer",
  "expires_in": 900,
  "salon_id": "…uuid…"               // retenu pour tout le jalon : pas de --dart-define salon par device (#159 s'aligne)
}
```

- `GET`/`DELETE` ne renvoient **jamais** ni secret ni hash (le champ n'existe pas dans
  `TerminalDevice`).
- Échec de `/auth/terminal/login` (device inconnu, secret faux, device révoqué) : `401` **générique
  constant**, patron `auth.py:389-394` — aucun oracle d'existence de device.
- Contrat consommé en aval : #156/#157 poseront leurs gardes
  `require_permission(CUSTOMER_LOOKUP_TERMINAL | CUSTOMER_CREATE_WALKIN | QUEUE_TICKET_CREATE)` +
  `require_salon_scope` sur leurs routes — **aucune** interface supplémentaire n'est requise de
  #155. Aucune modification de CLI ni de variable d'environnement.

## Data Model / Protocol Changes

**Oui — une migration Alembic (`0013`, `down_revision = "0012"`), sans nouvelle table ni
colonne :**

1. Régénération de `ck_users_role` (drop + recreate incluant `'TERMINAL'`), patron exact de
   `0007_notification_new_booking_type.py:55-63`.
2. Régénération de `ck_salon_members_role` (idem — la table d'appartenance porte le rattachement
   device→salon, `models.py:223`).
3. `downgrade()` symétrique (listes sans `'TERMINAL'`) pour le round-trip CI ; il suppose qu'aucune
   ligne `TERMINAL` n'existe (sémantique standard du retrait d'une valeur d'enum).
4. Aucun backfill : les lignes existantes portent des valeurs déjà autorisées.

**Conventions de données du device** (aucun changement de schéma, mais des invariants à
documenter en commentaire dans le repository SQL) : `users.phone = id.hex` (sentinelle 32 car.,
inatteignable par les flux téléphone — `normalize_phone` produit toujours `+…`,
`domain/phone.py:69`) ; `users.password_hash` = argon2id du secret device ; `full_name` = libellé
de borne (pas une PII).

**Protocole JWT inchangé** : mêmes claims (`sub`/`role`/`type`/`iat`/`exp`/`jti`,
`domain/tokens.py:30-44`), mêmes TTL, même algorithme. Le claim `role` vaut `"TERMINAL"` et reste
purement informatif (le rôle qui fait foi est relu en base, ADR-0015).

## Security & Privacy Considerations

**La borne est un terminal public partagé installé physiquement chez un tiers : le modèle de
menace inclut le vol du device, l'extraction de son credential et l'abus de ses endpoints.** Tout
le dessin découle de là.

- **Moindre privilège strict.** `TERMINAL` détient exactement trois permissions dédiées ; il ne peut
  **ni** obtenir `CUSTOMER_MANAGE` (pas de lecture des fiches complètes, des notes privées ni de
  l'historique), **ni** `APPOINTMENT_BOOK` (pas de réservation au nom d'un compte), ni aucun droit
  caisse/stats/employés. Le refus est garanti par la matrice fermée (`permissions.py:84-139`) et
  figé par les tests exacts (`test_domain_permissions.py`) + la matrice négative
  (`test_security_authz_matrix.py`) — critère d'acceptation de l'issue.
- **Rayon d'explosion borné à un salon.** La portée du device est son rattachement
  `salon_members`, relu en base à chaque requête (`salon_scope_repository.py:38-53` étendu) ; un
  `salon_id` forgé dans un chemin renvoie le `403` générique de `require_salon_scope`
  (`security.py:479-501`). Un credential volé n'expose que le parcours walk-in **d'un** salon.
- **Credential : ce qui est long est révocable, ce qui est porteur est court.** Secret 256 bits
  (`secrets.token_urlsafe(32)`), stocké uniquement en argon2id (port `PasswordHasher`, adapter
  `argon2_hasher.py`), affiché **une seule fois** au provisioning, jamais journalisé, jamais
  relisible. Les JWT émis gardent leurs TTL courts : un jeton exfiltré expire en 15 min, et la
  suspension du compte device (`users.status`) coupe l'accès **à la requête suivante** grâce à la
  relecture de `get_current_principal` (`security.py:409-410`) — pas de fenêtre de 30 jours.
- **Aucun oracle.** `/auth/terminal/login` répond un `401` constant pour device inconnu, secret faux
  et device révoqué, et est rate-limité par `device_id` (port `LoginRateLimiter`, `429` +
  `Retry-After`, patron `auth.py:306-318/:383-388`). La sentinelle `users.phone = id.hex` est
  inatteignable depuis `/auth/login` et le reset OTP (`classify_identifier` ne produit que des
  téléphones normalisés `+…` ou des e-mails, `authentication.py:109-120`) : le compte device ne
  crée **aucun** nouveau vecteur d'énumération.
- **Anti-oracle ADR-0026 préservé par construction.** La règle « ne jamais interroger `users` par
  téléphone » (`application/customers.py:21-24`) protège les **comptes** à mot de passe. #155 n'y
  touche pas : `CUSTOMER_LOOKUP_TERMINAL` est définie pour ne viser que `CustomerProfile` (fiches
  sans compte), périmètre que #156 devra expliciter dans sa propre spec (risque différent :
  exposition de PII sur écran public, mitigée par l'affichage du prénom seul et le débit limité —
  propriété de #156, rendue **possible et bornée** par la permission dédiée posée ici).
- **Provisioning = acte sensible du gérant.** `TERMINAL_PROVISION` est détenue par le seul `MANAGER`,
  gardée par `require_salon_scope` (un gérant ne provisionne que **son** salon, §11.2), et
  journalisée (`TERMINAL_DEVICE_PROVISIONED`/`TERMINAL_DEVICE_REVOKED`, `metadata = {}` — ni secret, ni
  hash ; §11.4, décision n°11 du jalon pour le volet journalisation). La révocation est logique,
  jamais une suppression (traçabilité).
- **Deny-by-default intact.** Une seule route entre dans `PUBLIC_ROUTE_PATHS`
  (`/auth/terminal/login`, endpoint d'authentification par nature), avec le commentaire de revue
  obligatoire (`security.py:102`) ; l'invariant `unprotected_routes(app) == []` couvre tout le
  reste. Les routes de provisioning ne sont **jamais** publiques.
- **Aucune PII nouvelle.** Un device n'a ni nom de personne, ni téléphone réel, ni e-mail ; le
  `Principal` terminal reste sans PII (`domain/principal.py:9-12`) ; les réponses de provisioning
  ne portent que des identifiants opaques et un libellé de machine.
- **Ce que #155 ne mitige pas (assumé, documenté dans l'ADR)** : compromission physique du
  terminal (verrouillage Android et PIN gérant — #159/#161), rotation périodique du secret
  (suivi), attestation du device (hors MVP).

## Testing Plan

### Domaine (`pytest`, sans I/O)

- **`tests/test_domain_permissions.py`** (mise à jour des verrous identifiés) :
  `_TERMINAL_EXPECTED == {CUSTOMER_LOOKUP_TERMINAL, CUSTOMER_CREATE_WALKIN, QUEUE_TICKET_CREATE}`
  (égalité **exacte**) ; négatifs explicites `CUSTOMER_MANAGE not in` / `APPOINTMENT_BOOK not in`
  `ROLE_PERMISSIONS[Role.TERMINAL]` ; `_MANAGER_EXPECTED` + `TERMINAL_PROVISION` ; aucun autre rôle ne
  détient les quatre nouvelles permissions ; `:35-37` et `:203` passent (alignement enum ↔
  matrice) ; `permissions_for("TERMINAL")` cohérent, `permissions_for("terminal")` → vide.
- **`tests/test_domain_access.py`** : `can_access_salon` pour un principal `TERMINAL` — vrai si le
  salon est dans la portée, faux sinon, faux si `status != ACTIVE` ; `can_access_appointment`
  → **toujours `False`** pour `TERMINAL` (une borne ne lit jamais un rendez-vous).
- **`tests/test_domain_terminal_device.py`** : validation du libellé (vide/blanc/> 255/trim) ;
  les dataclasses `TerminalDevice` n'exposent ni secret ni hash.

### Cas d'usage (fakes de `conftest.py`)

- **`tests/test_terminal_device_usecases.py`** : provisioning — le secret retourné vérifie
  `hasher.verify(secret, hash_stocké)` ; le secret n'apparaît **ni** dans l'entité, **ni** dans
  l'entrée d'audit (`metadata == {}`) ; le `salon_id` persisté vient de l'argument de portée,
  jamais de la commande ; audit `TERMINAL_DEVICE_PROVISIONED` une fois ; révocation → statut modifié
  + `TERMINAL_DEVICE_REVOKED` ; libellé invalide → aucune écriture, aucun audit.
- **`tests/test_authorization_policy.py`** : `scope_of` d'un `TERMINAL` délègue au port (pas de
  court-circuit plateforme) ; portée vide → `require_salon` refuse.
- **`AuthenticateTerminalDevice`** : succès → paire émise avec `sub = device_id`, `role = "TERMINAL"` ;
  device inconnu / secret faux / device révoqué → **même** erreur générique ; dépassement du
  rate-limit → `TooManyLoginAttempts`.

### API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_terminal_device_api.py`** : `201` avec `secret` présent une fois ; `GET` liste sans
  aucun champ secret ; `DELETE` → `200` + statut révoqué, `404` device d'un autre salon (après
  portée) ; `403` générique pour `CLIENT`/`HAIRDRESSER`/`ADMIN`/`TERMINAL` (une borne ne provisionne
  pas de borne) ; `401` sans jeton ; `422` libellé invalide.
- **`tests/test_terminal_auth_api.py`** : `200` + `salon_id` dans la réponse ; `401` générique
  (device inconnu = secret faux = révoqué, corps de réponse **identique**) ; `429` + `Retry-After`
  après N échecs ; le refresh émis fonctionne sur `/auth/refresh`.
- **`tests/test_security_authz_matrix.py`** : `Role.TERMINAL` ajouté à `_ALL_ROLES` (`:66`) — la
  dérivation `denied = _ALL_ROLES - allowed` (`:185-197`) exerce alors `TERMINAL` en `403` sur
  toutes les routes échantillonnées (création de fiche `CUSTOMER_MANAGE`, réservation
  `APPOINTMENT_BOOK`, caisse, stats…) : **c'est le test RBAC négatif du critère d'acceptation.**
- **`tests/test_security_guards.py`** : `unprotected_routes(app) == []` couvre les nouvelles
  routes ; vérifier explicitement que seule `/auth/terminal/login` a été ajoutée à
  `PUBLIC_ROUTE_PATHS`.

### e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent — patron des suites existantes)

- **`tests/test_terminal_e2e.py`** : parcours complet — inscription gérant → création salon →
  provisioning d'une borne (le secret n'est présent que dans la réponse `201`) →
  `/auth/terminal/login` → avec le jeton terminal : `403` sur `POST /salons/{id}/customers`, `403`
  sur `POST /salons/{id}/appointments`, `403` sur un salon **tiers** ; catalogue public lisible
  sans jeton ; révocation par le gérant → la requête suivante du device est refusée (`403`
  « Compte désactivé. ») et `/auth/terminal/login` répond `401` ; lignes `audit_logs`
  provisioning/révocation présentes, sans secret dans `metadata` ; la sentinelle `phone` du device
  ne permet **pas** de se connecter via `/auth/login`.
- **Migration** : round-trip Alembic CI (`upgrade head` → `downgrade` → `upgrade`) sur `0013` ;
  vérifier localement l'insertion d'un `users.role = 'TERMINAL'` après upgrade et son rejet avant.

### Non-régression

`scripts/test-gate.sh` au vert (pytest + npm test + flutter test — web et mobile ne sont pas
touchés mais le gate est global) ; `ruff check` propre.

## Documentation Updates

- **ADR sur le modèle d'authentification borne** — exigée par le texte de l'issue (« ADR requise,
  même exigence que l'anti-oracle ADR-0026 »). Prochain numéro libre : **`0041`**
  (`docs/adr/` s'arrête à `0040-impression-recu-encaissement-gerant.md`). **Décision actée**
  (une décision = une ADR, sur le modèle d'ADR-0039 avec #148 et d'ADR-0040 avec #154) : #155
  committe `docs/adr/0041-authentification-borne-kiosque.md` avec son implémentation (contexte,
  options 1/2, décision, conséquences, suivis : rotation de secret, table dédiée, attestation) —
  ADR-0026 a suivi ce modèle (committée avec l'implémentation qu'elle norme, pas six issues plus
  tard). Le volet `QueueTicket` a sa **propre** ADR-0042
  (`docs/adr/0042-file-attente-walkin-queue-ticket.md`), committée avec #157 ; #161 ne rédige
  pas d'ADR consolidée : il vérifie la présence des deux ADR (les écrit si elles manquent à ce
  stade), met à jour l'index pour les deux et porte le runbook de provisioning.
- **`docs/adr/README.md`** : entrée d'index pour l'ADR-0041, ajoutée par #155 au moment du
  commit (#161 revérifie l'index pour les deux ADR du jalon en fin de jalon).
- **`backend/README.md`** : section « Borne terminal — rôle, provisioning & authentification
  (US-8.1, #155) » — tableau routes/permission/réponses/audit, exemple `curl` de provisioning
  (avec l'avertissement « le secret n'est affiché qu'une fois »), cycle de vie d'un device
  (provisionné → actif → révoqué), rappel du jeu de permissions `TERMINAL`.
- **`README.md`** (racine) : phrase de statut « M7 amorcé : rôle et authentification borne
  (#155) » dans le style des paragraphes de jalon existants.
- **OpenAPI** : `summary`/`responses`/docstrings des quatre routes (visibles sur `/docs`), y
  compris le `429` du login terminal et la remise unique du secret.
- **BACKLOG.md** : aucun changement par #155 (la mise à jour de fin de jalon est portée par #161).

## Risks and Open Questions

Les décisions d'architecture du jalon reprises ci-dessous sont des **choix proposés, à valider par
le porteur produit avant l'implémentation** — avec la justification technique de cette spec.

1. **Décision n°1 du jalon — identité borne : rôle `TERMINAL` + credential de device par salon,
   jamais un JWT personnel partagé.** Justification technique : un credential `MANAGER` sur un
   terminal public exposerait caisse et PII (`CUSTOMER_MANAGE`, `permissions.py:121`) ; une
   session `CLIENT` partagée fusionnerait les parcours des passants sur un compte
   (`client_id = principal.id`, `appointments.py:538-551`) ; et l'analyse §A montre que l'option
   « mécanisme parallèle » duplique chaque invariant de sécurité testé du dépôt. **À valider** —
   c'est la décision structurante de l'issue, à figer dans l'ADR-0041.
2. **Périmètre exact des permissions `TERMINAL` (point de coordination #156/#157).** Les noms
   `CUSTOMER_LOOKUP_TERMINAL`, `CUSTOMER_CREATE_WALKIN`, `QUEUE_TICKET_CREATE` sont posés ici
   (`QUEUE_TICKET_CREATE` déjà anticipé par la spec de #157) mais leurs routes n'existeront
   qu'avec #156/#157 : à l'issue de #155, deux de ces permissions ne sont câblées sur **aucune**
   route (comme `CUSTOMER_MANAGE` l'était avant #28). Risque faible (permission sans route =
   droit inerte) ; les specs de #156/#157 reprennent désormais ces noms **à l'identique**
   (`CUSTOMER_LOOKUP_TERMINAL` / `CUSTOMER_CREATE_WALKIN` / `QUEUE_TICKET_CREATE`) — point de
   coordination réglé.
3. **La lecture catalogue sans permission dédiée.** Recommandation : la borne consomme les routes
   publiques `/catalog/...` (`security.py:118-133`), pas la vue gérant `SERVICE_READ`. Si le
   produit exige plus tard une vue catalogue enrichie réservée aux bornes, une permission
   `CATALOG_READ_TERMINAL` s'ajoutera sans casse. **À valider.**
4. **Sentinelle `users.phone = id.hex` vs migration `phone` nullable.** La sentinelle évite une
   migration à risque sur une colonne centrale (`uq_users_phone`, login, reset OTP) et son
   innocuité est démontrable (`normalize_phone` → `+…`, `phone.py:69`) — mais c'est une valeur
   non-téléphone dans une colonne nommée `phone` (dette lisible). Alternative : rendre `phone`
   nullable + index unique partiel (patron `uq_users_email`, `models.py:138-143`) — plus propre,
   plus invasif. *Recommandation : sentinelle en V1, bascule documentée comme suivi dans
   l'ADR-0041.* **À trancher avant la migration `0013`.**
5. **Décision n°8 du jalon — borne mono-salon, `salon_id` figé au provisioning.** Porté ici par le
   rattachement unique `salon_members` et le retour de `salon_id` dans la réponse de login —
   mécanisme retenu pour tout le jalon et acté entre les specs : un APK unique pour toutes les
   bornes, pas de `--dart-define` de salon par device en production (#159 s'aligne ; toléré
   uniquement comme override de développement local, marqué comme tel). Un salon multi-bornes est
   supporté (plusieurs devices) ; une borne multi-salons ne l'est pas (assumé). **À valider.**
6. **Qui committe l'ADR-0041, et quand ? — Tranché.** #155 committe
   `docs/adr/0041-authentification-borne-kiosque.md` avec son implémentation — un cinquième rôle
   et un credential de device ne devraient pas tourner en production sans décision tracée, et
   ADR-0026 (citée en référence par l'issue elle-même) a été committée avec son implémentation.
   Le volet `QueueTicket` a sa propre ADR-0042, committée avec #157 (une décision = une ADR) ;
   #161 ne rédige pas d'ADR consolidée : il vérifie la présence des deux ADR (les écrit si elles
   manquent à ce stade), met à jour l'index `docs/adr/README.md` et porte le runbook de
   provisioning.
7. **Le gérant provisionne-t-il via API seule en V1 ?** Recommandation : oui (exemple `curl`
   documenté, cohérent avec l'effort M de l'issue) ; la page dashboard est un suivi. La procédure
   terrain (qui saisit le secret sur la borne, PIN, décision n°11 du jalon pour le volet
   opérationnel) appartient à #159/#161. **À confirmer.**
8. **Rotation et péremption du secret device.** Hors périmètre V1 (un secret compromis se révoque
   et se re-provisionne en deux appels). Une rotation périodique imposée exigerait un état
   supplémentaire (date d'émission, période de grâce) — documentée comme suivi de l'ADR-0041.
   **À valider comme dette assumée.**
9. **Numérotation de migration avec #157 — ordre acté.** #155 livre `0013_kiosk_role.py`
   (`down_revision = "0012"`), #157 enchaîne avec `0014_queue_tickets.py`
   (`down_revision = "0013"`). Numéros à revalider au moment du merge réel selon l'ordre effectif
   des PR (réserve portée par les deux specs).
10. **`ADMIN` et les bornes.** `TERMINAL_PROVISION` n'est pas accordée à l'`ADMIN` (supervision ≠
    exploitation, ADR-0015, même logique que `CUSTOMER_MANAGE`). Un besoin de supervision
    plateforme des bornes (parc, dernier contact) serait une évolution distincte. **À valider.**

## Implementation Checklist

1. **Lire** `adapters/inbound/security.py`, `domain/permissions.py`, `domain/access.py`,
   `application/authorization.py`, `application/employees.py`, `application/authentication.py`,
   `migrations/versions/0007_notification_new_booking_type.py`, et les specs sœurs
   `borne-ticket-file-attente-walkin.md` / `borne-app-mobile-mode-kiosque.md` /
   `borne-adr-provisioning-documentation.md`.
2. **Trancher** la question ouverte 4 (sentinelle vs `phone` nullable) et consigner la décision —
   les questions 2 et 6 sont réglées : les specs de #156/#157 reprennent les noms de permissions
   à l'identique, et #155 committe l'ADR-0041 avec son implémentation (le volet `QueueTicket`
   relève de l'ADR-0042 de #157).
3. **Domaine** : `Role.TERMINAL` (`domain/enums.py`) ; quatre permissions + entrée
   `ROLE_PERMISSIONS[Role.TERMINAL]` + `TERMINAL_PROVISION` au `MANAGER` (`domain/permissions.py`) ;
   `Role.TERMINAL` dans `can_access_salon` (`domain/access.py:95`) ; erreurs dédiées
   (`domain/errors.py`) ; `domain/terminal_device.py` (libellé, dataclasses sans secret).
4. **Verrous de tests domaine** : mettre à jour `tests/test_domain_permissions.py`
   (`_TERMINAL_EXPECTED`, `_MANAGER_EXPECTED`, négatifs `CUSTOMER_MANAGE`/`APPOINTMENT_BOOK`) et
   `tests/test_domain_access.py` — **avant** la persistance.
5. **Audit** : `ENTITY_TYPE_TERMINAL_DEVICE`, `TERMINAL_DEVICE_PROVISIONED`, `TERMINAL_DEVICE_REVOKED`
   (`domain/audit.py`) + couverture `tests/test_domain_audit.py`.
6. **Migration `0013`** : régénérer `ck_users_role` et `ck_salon_members_role` (patron `0007`,
   downgrade symétrique) ; vérifier `alembic upgrade head && alembic downgrade -1 &&
   alembic upgrade head` sur PostgreSQL 16.
7. **Portée** : branche `TERMINAL` dans `SqlSalonScopeRepository.salon_ids_for`
   (`salon_scope_repository.py:38-53`) + tests `test_authorization_policy.py`.
8. **Port & adapter device** : `application/ports/terminal_device_repository.py` ;
   `adapters/outbound/persistence/terminal_device_repository.py` (compte `users` + `salon_members`
   atomiques, sentinelle `phone = id.hex` commentée, `flush()` sans `commit()`).
9. **Cas d'usage** : `application/terminal_devices.py` (provisioning avec
   `secrets.token_urlsafe(32)` + hachage argon2id, liste, révocation, audit `metadata={}`) ;
   `application/terminal_authentication.py` (rate-limit, verify, `issue_pair`, erreur générique
   unique) ; fakes + `tests/test_terminal_device_usecases.py`.
10. **Adapters entrants** : `adapters/inbound/terminal_devices.py` (trois routes
    `TERMINAL_PROVISION` + `require_salon_scope`, secret présent uniquement dans le `201`) ;
    `POST /auth/terminal/login` dans `adapters/inbound/auth.py` ; `"/auth/terminal/login"` dans
    `PUBLIC_ROUTE_PATHS` avec commentaire de revue de sécurité (`security.py:102`).
11. **Câblage** : `app.include_router(terminal_devices_router)` dans `main.py` + commentaire.
12. **Tests API & matrice** : `tests/test_terminal_device_api.py`, `tests/test_terminal_auth_api.py` ;
    `Role.TERMINAL` dans `_ALL_ROLES` (`tests/test_security_authz_matrix.py:66`) ; vérifier
    `unprotected_routes(app) == []` (`tests/test_security_guards.py`).
13. **e2e** : `tests/test_terminal_e2e.py` (provisioning → login → refus `CUSTOMER_MANAGE`/
    `APPOINTMENT_BOOK`/salon tiers → révocation immédiate → audit sans secret → sentinelle
    inerte sur `/auth/login`), avec `DATABASE_URL`.
14. **Documentation** : `docs/adr/0041-authentification-borne-kiosque.md` (committée avec cette
    implémentation) + entrée d'index `docs/adr/README.md` ; section dédiée `backend/README.md` ;
    phrase de statut `README.md` racine ; OpenAPI relue sur `/docs`.
15. **Vérification finale** : `scripts/test-gate.sh` au vert, `ruff check` propre ; relire la PR
    pour garantir qu'**aucun secret, aucune PII et aucune signature IA** n'apparaissent dans le
    code, les logs, l'audit, les commits ou la description de PR.
