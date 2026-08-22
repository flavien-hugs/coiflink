# Identification téléphone & création client walk-in sur la borne (US-8.2)

> Spécification de planification pour l'issue GitHub **#156 — US-8.2 : Identification téléphone &
> création client walk-in** (`feature` · Must · Effort M · PRD §17 « Borne Intelligente d'Accueil »,
> jalon **M7 — Borne client (terminal libre-service)**, Épic 8).
> **Dépend de : #155 (livrée), #28 (livrée).** **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.
>
> **Note de révision (fondée sur lecture du code livré, commit `b9c5388`).** #155 (US-8.1) est
> désormais **livrée** — pas seulement spécifiée. Le socle qu'elle apporte (rôle `TERMINAL`,
> permissions, compte de service device, portée salon, login device) **résout la plupart des
> risques que la version précédente de cette spec listait comme ouverts** (coordination de la
> matrice de permissions, garde de portée dédiée, acteur d'audit d'un device). La présente version
> réécrit la spec pour la caler sur ce qui existe réellement dans le code : #156 devient **purement
> additif et notablement plus simple** que l'ébauche antérieure ne l'anticipait.
>
> **Amendement (#172).** Cette spec documentait, à plusieurs endroits, l'exclusion **complète** du
> genre de la collecte borne (§11.3, collecte minimale). #172 lève cette restriction **uniquement
> pour le genre** (deux choix à l'écran, Homme/Femme, optionnel) — `notes`/mot de passe/`user_id`
> restent hors de portée de la borne, inchangés. La **réponse** renvoyée au terminal reste la
> projection minimale (`customer_id` + `first_name`) : seule l'**écriture** change, jamais la
> lecture. Les passages ci-dessous qui décrivaient l'exclusion du genre à l'**écriture** ont été mis
> à jour ; ceux qui décrivent la projection de **réponse** minimale restent vrais tels quels.

## Problem Statement

Le jalon M7 promeut le parcours « client sans rendez-vous » (PRD §17) au rang de fonctionnalité
livrable. Dans ce parcours, la borne doit répondre à une question avant toute délivrance de ticket :
**qui se présente ?** L'issue #156 l'exprime ainsi : un nouveau `find_by_phone` (port + repository +
endpoint) sur `CustomerProfile`, réservé au rôle `TERMINAL`, **sans jamais interroger `users` par
téléphone** (préserve l'anti-oracle ADR-0026), et une ouverture ciblée de la création de fiche
client à ce même rôle. Critère d'acceptation : la borne retrouve une fiche existante par téléphone
(salon de la borne uniquement) et n'affiche que le **prénom** du client ; si absente, crée une fiche
nom/prénom/téléphone **sans mot de passe** ; isolation par salon respectée (§11.2).

État du dépôt, vérifié par lecture directe du code livré :

- **Le socle borne (#155) est en place.** `Role.TERMINAL` existe (`domain/enums.py:48`) ; la borne est
  un **compte de service** matérialisé par une ligne `users` (`role = 'TERMINAL'`) + un rattachement
  `salon_members` `ACTIVE` (ADR-0041 §4, `application/terminal_devices.py`). Elle s'authentifie via
  `POST /auth/terminal/login` (route publique-listée, `security.py:119`) et obtient une paire JWT courte
  au rôle `TERMINAL` portant son `salon_id` (`application/terminal_authentication.py`). Elle traverse
  ensuite **toute la chaîne d'autorisation existante comme un `Principal` ordinaire**
  (`get_current_principal`, `security.py:390`).
- **Les deux permissions dont #156 a besoin existent déjà et sont détenues par `TERMINAL` seul.**
  `Permission.CUSTOMER_LOOKUP_TERMINAL` et `Permission.CUSTOMER_CREATE_WALKIN`
  (`domain/permissions.py:77-78`) sont ajoutées par #155 et attribuées à `ROLE_PERMISSIONS[Role.TERMINAL]`
  (`permissions.py:150-156`), qui détient **exactement** `{CUSTOMER_LOOKUP_TERMINAL,
  CUSTOMER_CREATE_WALKIN, QUEUE_TICKET_CREATE}` — **jamais** `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK`.
  **Conséquence majeure : #156 ne modifie pas `domain/permissions.py`.** La coordination de matrice
  que l'ancienne spec traitait comme un risque bloquant est **close**.
- **La garde de portée salon dont #156 a besoin existe déjà et couvre `TERMINAL`.**
  `require_salon_scope` (`security.py:488`) résout la portée via `AccessPolicy.require_salon` →
  `can_access_salon`, qui traite `TERMINAL` **exactement** comme `HAIRDRESSER`
  (`domain/access.py:98-103`) ; `SqlSalonScopeRepository.salon_ids_for` lit le rattachement
  `salon_members` `ACTIVE` pour `TERMINAL` (`salon_scope_repository.py:46-53`). **#156 réutilise donc la
  garde standard `require_salon_scope`** — aucune « garde de portée device→salon » dédiée n'est à
  écrire (l'ancienne spec en supposait une, livrée par #155 ; en réalité c'est la garde générique).
  Le router de provisioning livré `adapters/inbound/terminal_devices.py:168-171` en est le patron exact
  (`require_salon_scope` + `require_permission(...)`).
- **L'acteur d'audit d'un device est résolu.** Le device étant une ligne `users`,
  `AuditEntry.actor_user_id` (`uuid.UUID` NOT NULL, FK `users.id` `RESTRICT`, `models.py:715,731`)
  reçoit tout simplement `principal.id` — l'id du compte de service. `CUSTOMER_CREATED`
  (`domain/audit.py:87`) et `ENTITY_TYPE_CUSTOMER = "customer"` (`audit.py:37`) sont réutilisés
  **tels quels**, `metadata = {}`. Le risque « acteur d'audit d'un device » de l'ancienne spec est
  clos.
- **Aucune recherche de fiche client par téléphone n'existe encore.** Le port `CustomerRepository`
  (`application/ports/customer_repository.py`) n'expose que `phone_exists(salon_id, phone) -> bool`
  (lignes 75-82), un **pré-contrôle d'unicité** consommé par `CreateCustomer`/`UpdateCustomer` —
  jamais un `find_by_phone(...) -> Customer | None`. Son implémentation SQL
  (`adapters/outbound/persistence/customer_repository.py:162-169`) fait un
  `select(CustomerProfile.id)` filtré `(salon_id, phone)` et ne retourne qu'un booléen. Le seul
  filtre de liste, `CustomerFilter.q`, cherche par **nom** (`ILIKE` sur `full_name`,
  `customer_repository.py:154-159`), jamais par téléphone. **C'est le gap principal de #156.**
- **La création de fiche existante est un parcours gérant, inaccessible à un terminal.**
  `POST /salons/{salon_id}/customers` (`adapters/inbound/customers.py:436-484`) exige
  `require_salon_scope` **et** `require_permission(Permission.CUSTOMER_MANAGE)`
  (`customers.py:453-456`), détenue par le **seul** `MANAGER` (`permissions.py:136`). #156 ouvre une
  **route sœur dédiée** au rôle `TERMINAL`, sans jamais élargir `CUSTOMER_MANAGE`.
- **L'anti-oracle ADR-0026 est une règle documentée dans le code.**
  `application/customers.py:21-24` : le cas d'usage n'interroge **jamais** la table `users` par
  téléphone — ce serait offrir un **oracle d'existence de compte** (§11.1/§11.3). Le `find_by_phone`
  qui existe sur le port `UserRepository` (`application/ports/user_repository.py`) n'est utilisé que
  par l'authentification/le reset. #156 doit ajouter une recherche par téléphone **sans réintroduire
  ce problème** — cœur de l'analyse de sécurité ci-dessous.
- **Le socle de données est prêt, aucune migration nécessaire.** `CustomerProfile`
  (`models.py:414-467`) porte `full_name` NOT NULL `String(255)` (423), `phone` **nullable**
  `String(32)` (424), `user_id` **nullable** (« walk-in », 422), et l'index unique **partiel**
  `uq_customer_profiles_salon_phone` sur `(salon_id, phone) WHERE phone IS NOT NULL` (459-465) :
  l'unicité du téléphone est **par salon**, pas globale (commentaire 455-458). Le téléphone stocké
  est toujours en forme canonique **E.164** (`normalize_customer_phone`, `domain/customer.py:81-98`
  → `normalize_phone`, `domain/phone.py:36-69`, indicatif par défaut `+225`), ce qui rend une
  recherche par **égalité stricte** correcte et indexée. La colonne `users.phone` étant `NOT NULL
  UNIQUE`, un device y stocke une **sentinelle** `phone = id.hex` (ADR-0041 §4) — jamais un numéro
  atteignable par une recherche de téléphone.
- **Un limiteur anti-bruteforce générique et réutilisable existe.** Le port `LoginRateLimiter`
  (`application/ports/login_rate_limiter.py`) et l'adapter fenêtre glissante `InMemoryLoginRateLimiter`
  (`adapters/outbound/security/login_rate_limiter_memory.py`, seuils/horloge injectables) sont déjà
  **réutilisés par #155** pour `/auth/terminal/login` : `main`/`auth.py` monte un **second** singleton
  `app.state.terminal_login_rate_limiter` (`auth.py:467-485`), clé `device_id|ip`, mapping
  `TooManyLoginAttempts → 429 + Retry-After` (`auth.py:538-540`), IP extraite par `_client_ip`
  (`auth.py:356`). #156 réutilise **le même** port et le même adapter (voir §D).
- **Le RBAC est deny-by-default et mécaniquement vérifié.** `require_authenticated` est une
  dépendance **globale** (`main.py`) ; toute route est fermée sauf inscription explicite dans
  `PUBLIC_ROUTE_PATHS` (`security.py:104-144`, « revue de sécurité obligatoire ») ; l'invariant
  `unprotected_routes(app)` (`security.py:257-269`) échoue si une route n'est ni publique-listée ni
  gardée. La matrice négative rôle × route `test_security_authz_matrix.py` est **semi-manuelle** :
  elle dérive les rôles autorisés de `ROLE_PERMISSIONS`, mais énumère une **table de routes
  représentatives** (`_ROUTES`) — une route par famille de permission — donc #156 y **ajoute** deux
  entrées (voir *Testing Plan*).
- **Les specs sœurs de M7 s'alignent sur le contrat de #156.**
  `specs/borne-app-mobile-mode-kiosque.md` (#159) consomme `identityGateway.findByPhone(salonId,
  phone)` → `{customerId, firstName}` si trouvé, `404` sinon, et `createCustomer(salonId,
  {firstName, lastName, phone})` → `{customerId, firstName}` **sans mot de passe** ;
  `specs/borne-ticket-file-attente-walkin.md` (#157, **non encore livrée** — le module `queue`
  existant `domain/queue.py`/`application/queue.py` est la **file du Dashboard Manager #148/#150**,
  sans rapport avec le ticket walk-in) attend un `customer_profile_id` résolu par #156 et n'affiche
  que `customer_first_name`. #156 est la source d'autorité du contrat d'identification : cette spec
  le fixe.

Le gap que #156 comble : **(1)** un `find_by_phone` salon-scopé sur le port `CustomerRepository` et
son implémentation SQL ; **(2)** deux endpoints dédiés au rôle `TERMINAL` — recherche par téléphone à
réponse **minimale** (prénom seul) et création de fiche walk-in sans mot de passe — en **réutilisant**
les permissions, la garde de portée, l'audit et le limiteur **déjà livrés**, sans jamais élargir
`CUSTOMER_MANAGE` ni toucher la table `users`.

## Goals

- **`find_by_phone` sur le port et le dépôt SQL, salon-scopé.**
  `find_by_phone(salon_id, phone) -> Customer | None` s'ajoute à
  `application/ports/customer_repository.py`, avec l'implémentation dans `SqlCustomerRepository` :
  filtre `(salon_id, phone)` **inconditionnel** — jamais de recherche cross-salon, une fiche d'un
  autre salon est **indiscernable d'une fiche inexistante** (miroir des invariants du port,
  `customer_repository.py:8-12`).
- **Recherche terminal à exposition minimale.** Nouvel endpoint réservé au rôle `TERMINAL` : soumission
  du téléphone en **corps de requête** (jamais en query string — pas de PII dans les URL/logs
  d'accès), réponse limitée à `{customer_id, first_name}` — **jamais** le nom complet, le téléphone,
  le genre, les notes ni les compteurs de visites.
- **Création de fiche walk-in depuis la borne, sans mot de passe.** Nouvel endpoint `TERMINAL` créant
  une `CustomerProfile` à partir de **prénom + nom + téléphone**, avec un **genre optionnel**
  (Homme/Femme à l'écran — #172) — `user_id = NULL`, aucun compte, aucun mot de passe — réutilise la
  validation domaine de #28 (`validate_customer_name`, `normalize_phone`, `normalize_gender`) et
  l'unicité `(salon_id, phone)` existante.
- **Préservation stricte de l'anti-oracle ADR-0026.** Ni le cas d'usage ni l'adapter n'importent le
  moindre port `users` : la recherche porte **exclusivement** sur `customer_profiles`. Un téléphone
  titulaire d'un compte CoifLink mais sans fiche dans le salon répond « introuvable » — aucun repli
  vers `users`, démontré par un test e2e dédié.
- **Mitigations PII explicites** (voir *Security & Privacy Considerations*) : prénom seul à l'écran,
  limitation de débit des tentatives par device/IP (réutilise `LoginRateLimiter` +
  `InMemoryLoginRateLimiter`), messages d'erreur neutres, journalisation applicative **sans aucun
  numéro soumis**.
- **Isolation §11.2 en profondeur.** `require_salon_scope` (existant, couvre `TERMINAL`) sur chaque
  route **et** refiltre `salon_id` en SQL dans le dépôt (défense en profondeur, patron existant du
  module clients).
- **Aucun élargissement des rôles existants ni de la matrice.** `CUSTOMER_MANAGE` reste MANAGER-seul ;
  les nouvelles routes portent les permissions `TERMINAL` **déjà** dédiées et minimales (livrées par
  #155) ; tests RBAC négatifs ajoutés (un JWT `CLIENT`/`MANAGER`/`HAIRDRESSER`/`ADMIN` est refusé sur
  les routes terminal, un credential `TERMINAL` reste refusé sur les routes gérant et la réservation).
- **Aucune migration de schéma.** La table `customer_profiles`, ses index et sa validation couvrent
  déjà le besoin — #156 est purement additif côté code.

## Non-Goals

Rappel du périmètre du jalon M7 — ce qui suit reste différé et n'est traité par **aucune** issue de
M7 :

- **Vérification/check-in d'un rendez-vous existant depuis la borne** (« J'ai un rendez-vous »,
  PRD §17.3) ;
- **Identification par QR code ou code de réservation** (PRD §17.3) — l'identification M7 est le
  téléphone, point ;
- **Affichage temps réel des coiffeurs disponibles avant affectation** ;
- **Paiement autonome sur la borne** (« Version future » du PRD §17.3).

Hors périmètre de #156 en particulier :

- **Le rôle `TERMINAL`, son credential device, sa garde de portée, ses permissions et son provisioning**
  sont **livrés** par #155 (ADR-0041) : #156 **consomme** ces briques sans les réimplémenter ni les
  modifier.
- **Le ticket de passage et la file d'attente walk-in** (#157, non livrée) : #156 s'arrête à
  l'identité (`customer_id` + prénom) que #157 consommera comme `customer_profile_id`.
- **Toute l'UI borne** (écrans de saisie, clavier tactile, timer d'inactivité) : #159. Cette spec
  fixe seulement le **contrat HTTP** que ces écrans appelleront.
- **La recherche par nom** (PRD §17.3 liste « Nom du client ») : écartée — une recherche par nom
  depuis un terminal public serait un outil d'énumération de PII bien plus large qu'une égalité
  stricte sur téléphone (voir *Security*).
- **Le rattachement d'une fiche à un compte utilisateur (`user_id`)** : la fiche créée par la borne
  est walk-in (`user_id = NULL`), comme en #28. Aucun rapprochement automatique avec `users`, ni
  maintenant ni par téléphone — c'est précisément l'anti-oracle.
- **Modification/suppression de fiche, notes depuis la borne.** La borne collecte
  prénom/nom/téléphone et, depuis #172, un genre optionnel à la création — mais ne peut rien
  **éditer** ensuite. `PATCH`/notes restent MANAGER-seuls (#144/#32).
- **Recherche cross-salon ou déduplication multi-salons** : la portée est le salon de la borne,
  cohérent avec l'unicité par salon en base.
- **SMS/notification au client identifié** : rien n'est envoyé par #156.
- **Aucune modification des routes gérant existantes** (`/salons/{salon_id}/customers…`) ni de la
  matrice `ROLE_PERMISSIONS` (déjà à jour depuis #155).
- **Basculer `users.phone` en nullable** (dette lisible de la sentinelle device, ADR-0041 §4) reste
  un suivi de #155, sans impact sur #156.

## Relevant Repository Context

### Backend — socle borne livré par #155 (ADR-0041), que #156 consomme

- **Rôle & permissions** : `Role.TERMINAL` (`domain/enums.py:43-48`) ; `Permission.CUSTOMER_LOOKUP_TERMINAL`
  / `CUSTOMER_CREATE_WALKIN` / `QUEUE_TICKET_CREATE` (`domain/permissions.py:77-79`) ;
  `ROLE_PERMISSIONS[Role.TERMINAL]` = exactement ces trois (150-156). Matrice figée par
  `tests/test_domain_permissions.py` (déjà mise à jour par #155).
- **Portée salon** : `AccessPolicy.require_salon` (`application/authorization.py:68-79`) →
  `can_access_salon` (`domain/access.py:81-104`, `TERMINAL` traité comme `HAIRDRESSER`) →
  `SqlSalonScopeRepository.salon_ids_for` (`salon_scope_repository.py:41-59`, lecture `salon_members`
  `ACTIVE`). La garde HTTP `require_salon_scope` (`security.py:488-510`) est réutilisable telle
  quelle.
- **Principal device** : `get_current_principal` (`security.py:390-421`) relit le compte en base —
  rôle et statut frais ; une révocation (`users.status → SUSPENDED`, `salon_members.status →
  INACTIVE`) coupe l'accès **à la requête suivante**.
- **Router de provisioning (patron de garde)** : `adapters/inbound/terminal_devices.py` — chaque route
  déclare `require_salon_scope` + `require_permission(...)`, schémas Pydantic sans champ privilégié,
  `salon_id` lu du chemin (anti-élévation). C'est le gabarit exact des routes de #156.
- **Login device** : `POST /auth/terminal/login` (`adapters/inbound/auth.py:508-541`,
  `application/terminal_authentication.py`) — publique-listée, rate-limitée par
  `app.state.terminal_login_rate_limiter`, `401` générique. Modèle de réutilisation du limiteur.

### Backend — module clients (#28/#32/#144), la fondation directe

- **Port** `application/ports/customer_repository.py` : `create`, `find_by_id`, `list_for_salon`,
  `count_for_salon`, `phone_exists` (75-82), `update_notes`, `update`, `list_visits`,
  `list_payments`. Invariant (8-12) : toute méthode sur une fiche existante prend `salon_id`.
- **Dépôt SQL** `adapters/outbound/persistence/customer_repository.py` : `phone_exists` (162-169) est
  le gabarit direct de `find_by_phone` ; `_to_domain` (421-433) mappe ORM → entité ; la retraduction
  `IntegrityError → CustomerAlreadyExists` (`_is_phone_duplicate`, 401-418) couvre la course
  concurrente à la création.
- **Cas d'usage** `application/customers.py::CreateCustomer` (87-139) — validation → pré-contrôle
  `phone_exists` → `create` → `AuditEntry(CUSTOMER_CREATED, metadata={})`. Docstring anti-oracle
  (21-24).
- **Domaine** `domain/customer.py` : `validate_customer_name` (59-78, trim, non vide, ≤ 255) ;
  `normalize_customer_phone` (81-98, optionnel → `None`) ; entité `Customer` (163-181) qui
  **n'expose pas** `user_id` (166-170). `domain/phone.py::normalize_phone` (36-69) idempotente,
  `+225` par défaut, `0700000000` → `+2250700000000`.
- **ORM** `models.py::CustomerProfile` (414-467) : `phone` nullable (424), index unique partiel
  `(salon_id, phone) WHERE phone IS NOT NULL` (459-465) — sert aussi la **recherche** par égalité.
- **Adapter entrant** `adapters/inbound/customers.py` : mapping erreurs domaine →
  `422`/`409`/`404`, messages neutres sans PII ; garde MANAGER `create_customer` (436-484).

### Sécurité, RBAC, limitation de débit

- `adapters/inbound/security.py` : liste publique (104-144), `unprotected_routes` (257-269),
  `require_permission` (446), `require_salon_scope` (488). `403` générique et constant, jamais
  d'oracle.
- `application/ports/login_rate_limiter.py` (`check`/`record_failure`/`reset`, clé opaque) +
  `adapters/outbound/security/login_rate_limiter_memory.py` (fenêtre glissante, verrou, horloge
  injectable) — **déjà réutilisés** par le login terminal de #155. Erreur `TooManyLoginAttempts`
  (`domain/errors.py:555-564`, `retry_after`) → `429` + `Retry-After`.
- **Journal d'audit** : `CUSTOMER_CREATED` (`domain/audit.py:87`), `ENTITY_TYPE_CUSTOMER` (37) ;
  `actor_user_id` NOT NULL FK `users.id` (`models.py:715,731`) — satisfait par `principal.id` du
  compte device.

### Anti-oracle ADR-0026 — le précédent à ne pas trahir

`docs/adr/0026-fiche-client-portee-salon.md`, décision 3 : interroger `users` par numéro
transformerait la route en oracle d'existence de **compte**. La distinction compte (`users`, mot de
passe, portée plateforme) vs fiche (`customer_profiles`, sans authentification, portée salon) fonde
toute l'analyse de sécurité de #156. ADR-0041 (livrée avec #155) **référence** déjà ADR-0026 comme
contrainte de #156.

## Proposed Implementation

### (A) Port — `find_by_phone` sur `CustomerRepository`

Ajout au `Protocol` (`application/ports/customer_repository.py`), à côté de `phone_exists` :

```python
def find_by_phone(self, salon_id: uuid.UUID, phone: str) -> Customer | None:
    """Retourne la fiche du salon portant ce téléphone (forme canonique E.164), sinon `None`.

    Le filtre porte sur `salon_id` **et** `phone` (isolation §11.2) : une fiche
    d'un autre salon est indiscernable d'une fiche inexistante — jamais de
    recherche cross-salon. `phone` est la forme **canonique** produite par
    `domain/phone.py::normalize_phone` : l'appelant normalise **avant** d'appeler
    (les fiches sont stockées canoniques depuis #28, l'égalité stricte suffit).
    Au plus une fiche peut correspondre (index unique partiel
    `uq_customer_profiles_salon_phone`).
    """
    ...
```

Implémentation `SqlCustomerRepository` : même `WHERE` que `phone_exists`
(`customer_repository.py:162-169`) mais `select(models.CustomerProfile)` complet + `_to_domain(row)`
— lecture seule, aucun flush. L'index unique partiel existant sert la requête (parcours d'index sur
`(salon_id, phone)`), aucun index supplémentaire.

`phone_exists` est **conservé tel quel** (consommé par `CreateCustomer`/`UpdateCustomer`) ;
optionnellement, son implémentation peut déléguer à `find_by_phone(...) is not None` — micro-refactor
laissé au choix de l'implémenteur, le contrat du port ne change pas.

### (B) Domaine — identité minimale walk-in et dérivation du prénom

Dans `domain/customer.py` (pur, aucune dépendance) :

- **`walk_in_first_name(full_name: str) -> str`** : premier token de `full_name.split()` (la chaîne
  est déjà validée non vide par `validate_customer_name`). C'est la **projection d'affichage borne**
  exigée par le critère d'acceptation (« n'affiche que le prénom »). Le modèle ne stocke qu'un
  `full_name` (`models.py:423`) : plutôt qu'une migration (colonne `first_name`), la dérivation est
  garantie exacte pour les fiches **créées par la borne** (composition contrôlée, ci-dessous) et
  assumée heuristique pour les fiches historiques saisies par le gérant (voir *Risks*).
- **`@dataclass(frozen=True) WalkInIdentity`** : `customer_id: uuid.UUID`, `first_name: str` — la
  **seule** projection qui franchit la frontière HTTP terminal. Ni téléphone, ni nom complet, ni
  genre, ni notes, ni compteurs : l'entité `Customer` complète ne sort **jamais** vers la borne.
- **`@dataclass(frozen=True) WalkInCustomerCommand`** : `first_name: str`, `last_name: str`,
  `phone: str` — les trois champs de l'acceptation, tous **requis** au terminal — plus
  `gender: str | None = None`, **optionnel** (#172, ajouté après la livraison initiale de #156).
  Validation :
  1. `first_name` et `last_name` : trim, non vides (réutilise la mécanique de
     `validate_customer_name` — erreur `InvalidCustomerName`, messages neutres) ;
  2. composition **ordonnée** `full_name = f"{first_name} {last_name}"` puis
     `validate_customer_name(full_name)` (borne ≤ 255 respectée sur le résultat composé) — l'ordre
     « Prénom Nom » garantit `walk_in_first_name(full_name) == first_name` saisi ;
  3. `phone` : **requis** (contrairement au flux gérant #28 où il est optionnel) — c'est la clé
     d'identification de la borne, une fiche terminal sans téléphone serait introuvable à la prochaine
     visite. Normalisation par `normalize_phone` (`domain/phone.py:36`) **directement** (sémantique
     « requis » : vide → `InvalidPhone`), pas par le wrapper optionnel `normalize_customer_phone`. La
     colonne reste nullable — aucune migration ;
  4. `gender` : **optionnel** — `normalize_gender` (même règle que le flux gérant #28,
     `InvalidCustomerGender` si valeur hors énumération) — #172.

**Aucune nouvelle erreur de domaine à la livraison initiale de #156.** L'ancienne spec proposait un
`TooManyTerminalAttempts` : la présente version **réutilise `TooManyLoginAttempts`** (§D), déjà
mappée en `429 + Retry-After` et déjà employée par le login terminal de #155. #172 rend ce chemin
également capable de lever `InvalidCustomerGender` (type d'erreur préexistant, réutilisé de #28 — pas
une nouvelle classe d'erreur).

### (C) Cas d'usage — `application/terminal_customers.py` (nouveau module)

Module applicatif dédié (les cas d'usage gérant de `application/customers.py` restent inchangés),
dépendant **uniquement** des ports `CustomerRepository`, `AuditLog` et `LoginRateLimiter` — et
**surtout pas** de `UserRepository` : l'absence de tout import `users` dans ce module est le miroir
exécutable de l'anti-oracle (docstring de module explicite, comme `application/customers.py:21-24`).

- **`IdentifyWalkInCustomer.execute(salon_id, raw_phone, *, rate_key) -> WalkInIdentity | None`** :
  1. `rate_limiter.check(rate_key)` — lève `TooManyLoginAttempts` si la fenêtre est verrouillée ;
  2. `normalize_phone(raw_phone)` — un format invalide lève `InvalidPhone` **avant** tout accès base,
     et compte comme tentative (`record_failure`) : sonder des formats ne contourne pas la limite ;
  3. `repository.find_by_phone(salon_id, phone)` — le `salon_id` provient de la **portée validée**
     (`require_salon_scope`), jamais du corps ;
  4. fiche trouvée → `rate_limiter.reset(rate_key)` puis projection
     `WalkInIdentity(customer_id, walk_in_first_name(full_name))` ; absente →
     `rate_limiter.record_failure(rate_key)` puis `None` (l'adapter mappe en `404` neutre).
  Lecture **sans audit** : cohérent avec ADR-0026 (les lectures de fiches ne sont pas journalisées)
  et indispensable ici (un terminal public générerait un volume d'audit par simple usage nominal).
  La traçabilité opérationnelle passe par la limitation de débit et des logs applicatifs **sans le
  numéro soumis**.
- **`CreateWalkInCustomer.execute(salon_id, command, *, actor_user_id) -> WalkInIdentity`** :
  1. validation/composition domaine (§B) **avant tout accès base** ;
  2. pré-contrôle `phone_exists(salon_id, phone)` → `CustomerAlreadyExists` (message neutre
     existant : « Une fiche existe déjà pour ce numéro dans ce salon. ») — en concurrence, l'index
     unique base tranche et le dépôt retraduit (patron #28 inchangé) ;
  3. `repository.create(CustomerToCreate(salon_id=salon_id, full_name=..., phone=...,
     gender=validated_gender, notes=None))` — `user_id` reste `NULL` (walk-in) ; `gender` est
     **optionnel**, normalisé par `normalize_gender` (#172) ; `notes` reste **jamais** collecté par
     la borne (collecte minimale §11.3) ;
  4. `audit_log.record(AuditEntry(action=CUSTOMER_CREATED, actor_user_id=actor_user_id,
     salon_id=..., entity_type=ENTITY_TYPE_CUSTOMER, entity_id=..., metadata={}))` — même action et
     même neutralité que #28 ; l'acteur est `principal.id` du compte device (résolu, pas de risque) ;
  5. retour `WalkInIdentity` (jamais la fiche complète).

### (D) Limitation de débit — réutilisation directe du limiteur existant

**Pas de nouveau port ni de nouvel adapter.** #156 réutilise le port `LoginRateLimiter` et l'adapter
`InMemoryLoginRateLimiter` **exactement comme #155 l'a fait pour `/auth/terminal/login`** : un
**singleton dédié** est monté sur `app.state` (proposition : `terminal_lookup_rate_limiter`) avec des
**seuils propres au lookup** (proposition de départ : 10 échecs / 5 min, verrou 10 min — un client
légitime peut se tromper deux fois de numéro sans être bloqué, un énumérateur est freiné ; valeurs à
ajuster en pilote, *Risks*). La clé est construite par l'adapter entrant : `principal device id + IP
client` (`_client_ip`, `auth.py:356`, à réutiliser/partager). Ne comptent que les **échecs** (`404`
fiche absente, `422` format invalide) ; une identification réussie réinitialise la fenêtre — un salon
à fort trafic légitime n'est jamais pénalisé. L'implémentation mémoire est un choix MVP assumé
(mono-process ; adapter Redis différé, parité ADR-0013).

> *Alternative documentée (écartée par simplicité).* Un port `TerminalLookupRateLimiter` + une erreur
> `TooManyTerminalAttempts` dédiés donneraient une sémantique plus fine, au prix d'un port, d'un adapter
> et d'un mapping HTTP supplémentaires **strictement redondants** avec l'existant. Le message
> `TooManyLoginAttempts` (« Trop de tentatives… ») étant déjà générique, la réutilisation est retenue.
> L'implémenteur peut, s'il le souhaite, renommer le message à l'assemblage sans changer le type.

Faut-il limiter le lookup seul, ou aussi la création ? Le lookup est la surface d'énumération (voir
*Security*) et **doit** être limité. La création est bornée par l'unicité `(salon_id, phone)` et
n'énumère rien ; la limiter est **optionnel** (au choix de l'implémenteur, avec le même singleton).

### (E) Adapter entrant — `adapters/inbound/terminal_customers.py` (nouveau router)

Router `APIRouter(prefix="/salons", tags=["terminal"])`, un fichier par ressource (convention du dépôt).
Deux routes, toutes deux **protégées** (jamais dans `PUBLIC_ROUTE_PATHS`) :

- **`POST /salons/{salon_id}/terminal/customers/lookup`** — recherche par téléphone. `POST` et non
  `GET` : le numéro voyagerait sinon en query string (PII dans les logs d'accès, l'historique des
  proxies, les URL de trace). Corps `{"phone": "..."}` (`extra="ignore"`). Réponses : `200`
  `{customer_id, first_name}` · `404` neutre (« Aucune fiche pour ce numéro dans ce salon. » — sans
  rappeler le numéro) · `422` `InvalidPhone` · `429` + `Retry-After` (`TooManyLoginAttempts`, patron
  `auth.py:538-540`) · `401`/`403` par les gardes.
- **`POST /salons/{salon_id}/terminal/customers`** — création walk-in. Corps
  `{"first_name", "last_name", "phone"}` (`extra="ignore"` : tout champ privilégié — `salon_id`,
  `user_id`, `notes`, `gender`, `total_visits` — est ignoré). Réponses : `201`
  `{customer_id, first_name}` · `409` doublon (le parcours borne ré-exécute alors le lookup : la
  fiche existe désormais, le flux continue — contrat documenté pour #159) · `422` champ invalide ·
  `401`/`403`.

Gardes sur chaque route, dans le style `terminal_devices.py:161-171` : la garde **existante**
`require_salon_scope` (le `salon_id` du chemin doit être dans la portée du device, résolue via
`salon_members`) **et** `require_permission(Permission.CUSTOMER_LOOKUP_TERMINAL)` /
`(Permission.CUSTOMER_CREATE_WALKIN)`. Aucun rôle existant ne reçoit ces permissions : un JWT
`MANAGER`/`CLIENT`/`HAIRDRESSER`/`ADMIN` est refusé (`403` générique) sur les routes terminal ; un
credential `TERMINAL` reste incapable d'atteindre `CUSTOMER_MANAGE` ou `APPOINTMENT_BOOK`. Câblage
`main.py` : `app.include_router(terminal_customers_router)` + montage du singleton
`app.state.terminal_lookup_rate_limiter` (patron `main.py:77-90` / `auth.py:467-485`), avec le
commentaire de garde habituel.

Le router expose deux dépendances FastAPI (surchargeables en test) : `get_terminal_lookup_rate_limiter`
(lit `app.state`) et l'assemblage des cas d'usage (dépôt clients + audit + limiteur), sur le patron
de `terminal_devices.py:110-142`.

### (F) Mapping parcours borne → champs et validations existantes

| Saisie borne (UI #159) | Champ backend #156 | Validation/normalisation existante |
| --- | --- | --- |
| Numéro saisi au clavier tactile (formats libres) | `phone` (lookup **et** création) | `normalize_phone` (`domain/phone.py:36-69`) : séparateurs espace/point/tiret/parenthèses retirés, `00` → `+`, national préfixé **`+225`** sans retirer le `0` de tête, bornes 8-15 chiffres, idempotente |
| Prénom | `first_name` → 1er composant de `full_name` | trim + non vide (mécanique `validate_customer_name`, `domain/customer.py:59-78`) |
| Nom | `last_name` → 2e composant de `full_name` | idem ; composition « Prénom Nom » puis `validate_customer_name` sur le tout (≤ 255) |
| Genre (Homme/Femme, optionnel — #172) | `gender` (création uniquement) | `normalize_gender` (`domain/customer.py:101-119`) : `null`/vide → `None`, valeur fermée sinon (`InvalidCustomerGender`) ; jamais réverbéré dans la réponse |
| *(non collectés)* | `notes`, mot de passe, `user_id` | jamais demandés ni acceptés par la borne (collecte minimale §11.3 ; `extra="ignore"`) |

**Normalisation unique côté serveur, idempotente** : `07 00 00 00 00`, `0700000000`,
`+225 07-00-00-00-00` et `00 225 07000000 00` produisent tous `+2250700000000` et retrouvent **la
même fiche**, qu'elle ait été créée par le gérant au dashboard ou par la borne (les fiches sont
stockées canoniques depuis #28). Le pavé numérique de #159 peut restreindre la saisie (confort), mais
cette pré-normalisation UI n'est **jamais** autoritaire. Une saisie hors tolérance lève
`InvalidPhone → 422` à message neutre (jamais l'écho du numéro) ; l'échec compte dans la fenêtre de
débit (§D).

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/application/terminal_customers.py` | cas d'usage `IdentifyWalkInCustomer`, `CreateWalkInCustomer` (aucun import `users`) |
| `coiflink_api/adapters/inbound/terminal_customers.py` | router `/salons/{salon_id}/terminal/customers[...]` (deux routes `POST`) |
| `tests/test_terminal_customer_usecases.py`, `tests/test_terminal_customer_api.py`, `tests/test_terminal_customer_e2e.py` | tests (voir *Testing Plan*) |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/application/ports/customer_repository.py` | méthode `find_by_phone` (docstring isolation §11.2 + forme canonique) |
| `coiflink_api/adapters/outbound/persistence/customer_repository.py` | implémentation `find_by_phone` (lecture seule, gabarit `phone_exists:162-169`) |
| `coiflink_api/domain/customer.py` | `walk_in_first_name`, `WalkInIdentity`, `WalkInCustomerCommand` + validation/composition ; exports |
| `coiflink_api/main.py` | `include_router(terminal_customers_router)` + `app.state.terminal_lookup_rate_limiter = InMemoryLoginRateLimiter(...)` (seuils terminal) |
| `tests/conftest.py` | `find_by_phone` sur `FakeCustomerRepository` (≈ ligne 1408) ; réutiliser `InMemoryLoginRateLimiter` (horloge injectable) pour les tests de débit |
| `tests/test_domain_customer.py` | cas `walk_in_first_name` + `WalkInCustomerCommand` |
| `tests/test_security_authz_matrix.py` | **deux** entrées `_Route` (lookup → `CUSTOMER_LOOKUP_TERMINAL`, création → `CUSTOMER_CREATE_WALKIN`) pour exercer la matrice négative sur les nouvelles familles |
| `backend/README.md` | section « Borne — identification téléphone & création walk-in (US-8.2, #156) » |

### Non touchés (garde-fous)

`coiflink_api/domain/permissions.py` (**la matrice est déjà à jour** depuis #155 — ne rien y ajouter),
`coiflink_api/domain/enums.py` (`TERMINAL` déjà présent), `coiflink_api/adapters/inbound/security.py`
(garde de portée existante réutilisée, `PUBLIC_ROUTE_PATHS` inchangé), `coiflink_api/domain/errors.py`
(réutilise `TooManyLoginAttempts`/`InvalidPhone`/`CustomerAlreadyExists`),
`application/ports/login_rate_limiter.py` + son adapter (réutilisés tels quels), `app-mobile/` (#159),
`web-dashboard/`, `migrations/` (**aucune migration**), `adapters/inbound/customers.py` et
`application/customers.py` (routes/cas d'usage gérant inchangés),
`application/ports/user_repository.py` (jamais importé par le nouveau module).

## API / Interface Changes

Deux **nouveaux** endpoints, tous deux **protégés** (`require_salon_scope` existant + permission
`TERMINAL` dédiée déjà livrée) ; aucune route existante ne change ; rien n'entre dans
`PUBLIC_ROUTE_PATHS` (« réservé au rôle TERMINAL » signifie *atteignable par un device provisionné*, pas
*public*). Pas de préfixe `/v1` : routes strictement additives, cohérent avec tout le dépôt.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/terminal/customers/lookup` | `require_salon_scope` + `CUSTOMER_LOOKUP_TERMINAL` | `200` identité · `404` neutre · `422` téléphone invalide · `429` + `Retry-After` · `401`/`403` |
| `POST` | `/salons/{salon_id}/terminal/customers` | `require_salon_scope` + `CUSTOMER_CREATE_WALKIN` | `201` identité · `409` doublon · `422` champ invalide · `401`/`403` |

```jsonc
// POST /salons/{salon_id}/terminal/customers/lookup — corps
{ "phone": "07 00 00 00 00" }        // tout format toléré par normalize_phone ; jamais en query string

// 200 — trouvé (projection MINIMALE : jamais nom complet, téléphone, genre, notes, visites)
{ "customer_id": "…uuid…", "first_name": "Awa" }

// 404 — introuvable dans CE salon (message neutre, sans écho du numéro)
{ "detail": "Aucune fiche pour ce numéro dans ce salon." }
```

```jsonc
// POST /salons/{salon_id}/terminal/customers — corps (extra="ignore")
{ "first_name": "Awa", "last_name": "Koné", "phone": "0700000000" }   // les 3 champs requis

// 201 — créé (user_id = NULL en base, jamais exposé ; téléphone stocké +2250700000000)
{ "customer_id": "…uuid…", "first_name": "Awa" }

// 409 — une fiche porte déjà ce numéro dans ce salon (la borne relance alors le lookup)
{ "detail": "Une fiche existe déjà pour ce numéro dans ce salon." }
```

Contrats croisés fixés par cette API : le `customer_id` retourné est le `customer_profile_id` attendu
par la création de ticket #157 ; le corps de création `{first_name, last_name, phone, gender?}`
(`gender` optionnel depuis #172) et la réponse `{customer_id, first_name}` — **inchangée**, jamais
de genre en sortie — sont le contrat canonique du jalon, sur lequel l'`identityGateway` Flutter de
#159 est aligné. Aucune modification de CLI, de variable d'environnement ni de contrat inter-paquet
existant.

## Data Model / Protocol Changes

**Aucune migration.** Le schéma actuel couvre le besoin :

- `customer_profiles` porte déjà `full_name`/`phone`/`gender`/`user_id NULL` (walk-in) — la fiche
  créée par la borne réutilise les mêmes colonnes que #28, `gender` optionnel depuis #172 (`NULL` si
  non renseigné), `notes` toujours laissé `NULL` ;
- l'index unique partiel `uq_customer_profiles_salon_phone` (`models.py:459-465`) garantit l'unicité
  **et** sert la recherche par égalité `(salon_id, phone)` — aucun index à ajouter ;
- la forme canonique E.164 stockée depuis #28 rend l'égalité stricte correcte (pas de `LIKE`).

Le socle borne (#155) a déjà appliqué sa migration `0013` (régénération des `CHECK` `role` pour
`'TERMINAL'`, aucune table/colonne) : #156 n'en dépend pas au niveau du schéma.

## Security & Privacy Considerations

**Pourquoi ce `find_by_phone` ne réintroduit pas l'oracle interdit par l'ADR-0026 — et quel risque
différent il crée.** L'analyse tient en trois points :

1. **L'oracle ADR-0026 protège les *comptes*, pas les *fiches*.** Une ligne `users` porte un mot de
   passe et une existence **plateforme** : savoir qu'un numéro possède un compte CoifLink ouvre des
   attaques ciblées (bruteforce de connexion, sondage du reset OTP, phishing crédible) et révèle un
   fait **global**. C'est pourquoi `application/customers.py:21-24` interdit toute requête `users`
   par téléphone. Une `CustomerProfile` est autre chose : un dossier métier **local à un salon**,
   sans matériel d'authentification — savoir qu'elle existe n'ouvre **aucune** attaque sur un
   credential (il n'y en a pas).
2. **Le fait divulgué reste dans la frontière de données du salon (§11.2).** `find_by_phone` révèle
   « ce numéro a une fiche dans **ce** salon » — une information que le salon possède déjà (son
   `MANAGER` liste toutes ses fiches via `CUSTOMER_MANAGE`, #28). Le device `TERMINAL` est un agent du
   même salon, borné au même périmètre. La nouveauté n'est pas ce que le salon apprend, mais **qui
   d'autre** pourrait l'apprendre : la personne devant l'écran, ou un porteur du credential device
   volé.
3. **Le risque réel est une exposition de PII sur un écran public** (associer un nom à un numéro
   composé par n'importe qui), plus une **énumération** salon-locale par un attaquant physique ou un
   credential exfiltré. Les mitigations ciblent exactement cela :

- **Prénom seul, projection minimale par construction.** `WalkInIdentity` ne porte que `customer_id`
  + `first_name` : nom complet, téléphone (même celui qui vient d'être saisi), genre, notes (données
  potentiellement de santé, US-4.5) et compteurs de visites ne franchissent **jamais** la frontière
  HTTP terminal. Cohérent avec #157 qui n'affiche que `customer_first_name`.
- **Limitation de débit par device + IP** (§D, réutilise `InMemoryLoginRateLimiter`) : fenêtre
  glissante sur les échecs (`404`/`422`), verrou temporisé, `429` + `Retry-After` — l'énumération
  d'un annuaire devient impraticable au rythme d'un terminal.
- **Portée device→salon** (`require_salon_scope`, résolue via `salon_members`) : le credential d'une
  borne du salon X ne peut interroger que le salon X — l'énumération cross-salons est
  structurellement impossible, en plus du refiltre SQL `salon_id` du dépôt (défense en profondeur).
- **Jamais `users`.** Le module applicatif n'importe aucun port `users` ; un numéro titulaire d'un
  compte CoifLink mais sans fiche dans le salon répond `404` — indiscernable d'un numéro inconnu.
  Test e2e dédié (voir *Testing Plan*). La sentinelle `users.phone = id.hex` d'un device (ADR-0041
  §4) n'est de toute façon pas dans `customer_profiles` : aucun croisement possible.
- **Aucune PII dans les logs, l'audit ni les erreurs.** Le numéro soumis n'apparaît dans aucun log
  applicatif ni message d'erreur (messages neutres constants) ; la clé de débit est opaque (device +
  IP, jamais le numéro) ; la création journalise `CUSTOMER_CREATED` avec `metadata = {}` (parité
  stricte #28) ; les lookups ne sont pas audités (ADR-0026 — et un terminal public inonderait le
  journal par usage nominal).
- **Téléphone en corps de requête, jamais en URL** : pas de PII dans les logs d'accès, les proxies
  ou les traces.
- **Deny-by-default intact** : aucune entrée `PUBLIC_ROUTE_PATHS`, invariant `unprotected_routes` au
  vert ; permissions **déjà** dédiées au rôle `TERMINAL`, aucun élargissement de `CUSTOMER_MANAGE`
  (MANAGER-seul, `permissions.py:136`) ni d'`APPOINTMENT_BOOK` (CLIENT-seul) ; tests RBAC négatifs
  bidirectionnels.
- **Collecte minimale (§11.3)** : prénom, nom, téléphone, et depuis #172 un genre optionnel
  (Homme/Femme) — `notes` et mot de passe restent hors de portée (`extra="ignore"`) : aucune surface
  de credential n'est créée. `salon_id` vient toujours du chemin validé par la portée, jamais du
  corps (anti-élévation, patron #28/#155).
- **Bornes d'entrée** : nom composé ≤ 255, téléphone E.164 8-15 chiffres — pas de corps non borné
  (budget §12.1).
- **Sécurité résiduelle assumée** : un client légitime peut composer le numéro d'un tiers présent
  dans le salon et voir son prénom. Résidu jugé acceptable pour le MVP : information minimale (prénom
  seul), débit limité, contexte physique observable. Déjà consigné dans ADR-0041 (« ce que #155 ne
  mitige pas » + risque borné à un salon).

## Testing Plan

### Domaine (`pytest`, sans I/O) — `tests/test_domain_customer.py` (étendu)

- `walk_in_first_name` : `"Awa Koné"` → `"Awa"` ; nom simple sans espace → lui-même ; espaces
  multiples/trim.
- `WalkInCustomerCommand` : prénom ou nom vide/blanc → `InvalidCustomerName` ; téléphone absent/vide
  → `InvalidPhone` (requis au terminal, contrairement à #28) ; composition « Prénom Nom » →
  `walk_in_first_name` restitue exactement le prénom saisi ; composé > 255 → `InvalidCustomerName` ;
  formats de saisie borne (`"07 00 00 00 00"`, `"+225 07-00-00-00-00"`, `"0022507…"`) → même forme
  canonique `+2250700000000` (idempotence incluse).

### Cas d'usage (fakes de `conftest.py`) — `tests/test_terminal_customer_usecases.py`

- **Lookup** : normalisation **avant** l'appel dépôt (le fake reçoit la forme canonique quel que soit
  le format soumis) ; fiche trouvée → `WalkInIdentity` au prénom seul, `reset` appelé ; absente →
  `None` + `record_failure` ; format invalide → `InvalidPhone` + `record_failure`, **aucun** appel
  dépôt ; limiteur verrouillé → `TooManyLoginAttempts`, **aucun** appel dépôt ; le `salon_id`
  transmis au dépôt est **celui de la portée**, jamais du corps ; aucune entrée d'audit sur un
  lookup.
- **Création** : fiche persistée avec `full_name` composé, téléphone canonique, `gender`/`notes`
  `None` ; `CUSTOMER_CREATED` enregistrée une fois, `metadata == {}` (aucune PII), acteur =
  `principal.id` device ; doublon → `CustomerAlreadyExists` sans écriture ni audit ; validation
  invalide → aucune écriture, aucun audit ; même téléphone dans un **autre** salon → accepté
  (cloisonnement §11.2).
- **Anti-oracle structurel** : le module `application/terminal_customers.py` n'importe aucun port
  `users` (assertion d'import, dans l'esprit des tests d'invariant du dépôt).

### API (`TestClient` + `app.dependency_overrides`) — `tests/test_terminal_customer_api.py`

- `200` lookup : corps **exactement** `{customer_id, first_name}` — assertions d'**absence** de
  `full_name`, `phone`, `gender`, `notes`, `user_id`, `total_visits` ; `404` neutre (sans écho du
  numéro) ; `422` téléphone invalide ; `429` + en-tête `Retry-After` quand le limiteur est
  verrouillé.
- `201` création : corps minimal, champs privilégiés du corps (`salon_id`, `user_id`, `notes`,
  `gender`) **ignorés** ; `409` doublon ; `422` par champ manquant/invalide.
- **RBAC négatif** : `401` sans credential sur les deux routes ; `403` pour un JWT `CLIENT`,
  `MANAGER`, `HAIRDRESSER`, `ADMIN` sur les routes terminal ; le principal `TERMINAL` est refusé (`403`
  constant) sur `GET/POST /salons/{salon_id}/customers` (`CUSTOMER_MANAGE`) et sur
  `POST /salons/{salon_id}/appointments` (`APPOINTMENT_BOOK`) ; device du salon X → `403` sur le
  salon Y (portée). Ces deux derniers sens sont **partiellement déjà couverts** par
  `test_security_authz_matrix.py` une fois les deux `_Route` ajoutées.
- `tests/test_security_guards.py` : `unprotected_routes(app) == []` couvre mécaniquement les nouvelles
  routes ; vérifier qu'aucun chemin `terminal/customers` n'entre dans `PUBLIC_ROUTE_PATHS`.

### e2e (PostgreSQL réel, sauté sans `DATABASE_URL`) — `tests/test_terminal_customer_e2e.py`

Patron `test_customer_e2e.py` (plage de téléphones réservée, nettoyage avant/après — **purger les
`notifications` avant `appointments`/`users`/`salons`**, contrainte connue du dépôt) :

1. **Parcours nominal cross-canal** : gérant crée une fiche au dashboard (#28, numéro au format
   local) → lookup terminal du même numéro **dans un autre format de saisie** → `200`, prénom attendu ;
2. **Création borne** : lookup `404` → création `201` → second lookup `200` avec le même
   `customer_id` → la fiche apparaît dans la liste gérant #28 (`user_id` absent de la réponse,
   `gender`/`notes` `NULL`) ;
3. **Isolation §11.2** : fiche du salon A introuvable (`404`) depuis le device du salon B ; même
   numéro fiché dans A et B → chaque device retrouve **sa** fiche ;
4. **Anti-oracle `users`** : créer un compte `CLIENT` (table `users`) avec un téléphone sans fiche
   dans le salon → lookup terminal de ce numéro → `404`, indiscernable d'un numéro inconnu de la
   plateforme ;
5. **Traçabilité** : la création borne écrit une ligne `audit_logs` `CUSTOMER_CREATED` avec l'acteur
   device et `metadata` vide (assertion explicite) ; aucun lookup n'écrit d'audit ;
6. **Concurrence** : deux créations simultanées du même numéro → un `201` + un `409` (index unique
   partiel, retraduction existante) ;
7. **Révocation (intégration #155)** : après révocation du device (`DELETE
   /salons/{id}/terminal-devices/{device_id}`), une requête terminal suivante est refusée (`403`,
   portée vidée) — vérifie que #156 hérite bien de la révocation immédiate.

### Non-régression

`scripts/test-gate.sh` au vert (pytest + npm test + flutter test — web et mobile sans changement) ;
`ruff check` propre ; suites #28/#32/#144/#155 inchangées (routes gérant et provisioning intactes) ;
`test_domain_permissions.py` inchangé (la matrice n'est pas modifiée par #156).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Borne — identification téléphone & création walk-in
  (US-8.2, #156) » : tableau routes/permission/réponses, règles de normalisation téléphone (formats
  acceptés → forme canonique), note d'isolation §11.2 et renvoi vers l'analyse anti-oracle (gabarit
  des sections existantes).
- **ADR** : #156 ne crée **pas** d'ADR propre. Le modèle d'authentification borne et son volet
  identité sont **déjà** consignés par `docs/adr/0041-authentification-borne-kiosque.md` (livrée avec
  #155), qui référence explicitement #156 (« recherche téléphone + fiche walk-in ») et ADR-0026.
  Optionnel : un court paragraphe ou renvoi peut être ajouté à ADR-0041 pour pointer l'implémentation
  #156 une fois livrée — non requis.
- **`docs/adr/0026-fiche-client-portee-salon.md`** : ne pas le modifier — la décision 3 (jamais
  `users` par téléphone) reste vraie mot pour mot ; ADR-0041 explique déjà pourquoi `find_by_phone`
  sur `customer_profiles` ne la contredit pas.
- **`BACKLOG.md` / `README.md` racine** : phrase de statut du jalon M7 une fois l'issue livrée
  (convention des livraisons précédentes) ; la mise à jour PRD/BACKLOG de fin de jalon appartient à
  #161.
- **OpenAPI** : `summary`/`responses`/docstrings des deux routes (visibles sur `/docs`), y compris
  `404`/`409`/`422`/`429` et la mention explicite « réponse minimale : prénom seul ».

## Risks and Open Questions

Les risques structurants que l'ébauche précédente listait comme **ouverts** sont pour la plupart
**clos** par la livraison de #155 ; ils sont rappelés ici avec leur résolution, suivis des seuls
choix restant à valider.

**Résolus par #155 (livrée) — plus d'action requise :**

- ~~Acteur d'audit d'un device~~ : **clos.** Le device est une ligne `users` (`role=TERMINAL`) ;
  `actor_user_id = principal.id` satisfait la FK NOT NULL. `CUSTOMER_CREATED`/`ENTITY_TYPE_CUSTOMER`
  réutilisés sans changement (`domain/audit.py`).
- ~~Nommage et propriété des permissions `TERMINAL`~~ : **clos.** `CUSTOMER_LOOKUP_TERMINAL` et
  `CUSTOMER_CREATE_WALKIN` existent et sont attribuées à `Role.TERMINAL` (`permissions.py:150-156`) ;
  la matrice est déjà figée par `test_domain_permissions.py`. #156 **ne modifie pas** la matrice — il
  n'y a plus d'ordre de merge à coordonner.
- ~~Garde de portée device→salon dédiée~~ : **clos.** `require_salon_scope` couvre `TERMINAL` via
  `salon_members` (`salon_scope_repository.py:46-53`, `access.py:98-103`). #156 réutilise la garde
  générique — aucune garde spéciale à écrire.

**Choix à valider par le porteur produit avant l'implémentation :**

1. **Recherche limitée à `CustomerProfile`, jamais `users` ; prénom seul à l'écran.** Coût assumé :
   un client homonyme ne se distingue pas à l'écran — jugé sans conséquence (le `customer_id`
   sous-jacent est exact). **À valider** (aligné sur ADR-0041/ADR-0026).
2. **Portée téléphone = salon de la borne.** Cohérent avec l'unicité par salon
   (`uq_customer_profiles_salon_phone`) et le §11.2 ; un client connu du salon B mais pas de A est un
   **nouveau client de A** (il re-saisit son nom une fois). **À valider.**
3. **Dérivation du prénom = premier token de `full_name`.** Exacte pour toute fiche créée par la
   borne (composition « Prénom Nom ») ; **heuristique** pour les fiches historiques du gérant (un
   `full_name` « Koné Awa » afficherait « Koné »). Alternatives écartées : colonne `first_name`
   (migration + rétro-remplissage non fiabilisable), afficher le nom complet (contraire au critère).
   **À valider** (avec option d'une consigne « Prénom Nom » côté dashboard gérant en documentation).
4. **Seuils de limitation de débit.** Proposition de départ : 10 échecs / 5 min par clé (device +
   IP), verrou 10 min — plus permissif que la connexion (5/300 s/900 s) car l'erreur de saisie
   tactile est fréquente et la borne est physiquement surveillable. **À ajuster en pilote** (2-3
   salons).
5. **Réutilisation de `TooManyLoginAttempts` / `LoginRateLimiter` plutôt qu'un port et une erreur
   dédiés.** Retenu pour éviter une duplication stricte de l'existant (parité avec le login terminal
   #155). Résidu : un nom d'erreur « login » pour un lookup — le message reste générique. **À
   valider** (l'alternative dédiée reste possible si un jour la sémantique doit diverger).
6. **Téléphone partagé (compromis ADR-0026 décision 6).** L'unicité `(salon_id, phone)` interdit
   deux fiches pour un même numéro : à la borne, le second membre d'une famille partageant un
   téléphone retombera sur la fiche du premier (`200` + prénom d'un autre). L'échappatoire du
   dashboard (fiche sans téléphone) n'est **pas** offerte à la borne (le téléphone y est la clé).
   Comportement proposé pour M7 : la borne affiche le prénom trouvé avec un bouton « Ce n'est pas
   moi » orientant vers l'accueil humain (écran #159) — #156 n'ajoute aucun contournement d'unicité.
   **À valider comme limitation produit du pilote.**
7. **Numérotation « US-00x » non autoritaire.** Aucune table de correspondance officielle
   n'existe ; le mapping suit l'hypothèse de #159. Sans impact technique (champs et validations
   identiques quelle que soit la numérotation). **À confirmer, cosmétique.**
8. **Race création/lookup entre canaux.** Un gérant et la borne peuvent créer le même numéro
   simultanément : l'index unique tranche, le perdant reçoit `409`, le parcours borne ré-exécute le
   lookup (contrat documenté pour #159). Couvert par le test e2e §6 — risque résiduel nul.

## Implementation Checklist

1. **Confirmer les points de contrat #155 par lecture rapide** (déjà vérifiés dans cette spec) :
   `Role.TERMINAL` + permissions dans `ROLE_PERMISSIONS`, `require_salon_scope`/`can_access_salon`
   couvrant `TERMINAL`, device = ligne `users` (acteur d'audit), patron du limiteur terminal
   (`auth.py:467-541`). Trancher les questions ouvertes 1-6 avec le porteur produit.
2. **Lire** pour s'imprégner des patrons : `adapters/inbound/terminal_devices.py`,
   `adapters/inbound/customers.py`, `application/customers.py`, `domain/customer.py`,
   `domain/phone.py`, `adapters/outbound/persistence/customer_repository.py`,
   `adapters/inbound/security.py`, `application/terminal_authentication.py` + `adapters/inbound/auth.py`
   (montage du limiteur terminal), et les specs sœurs #157/#159.
3. **Domaine** : `walk_in_first_name`, `WalkInIdentity`, `WalkInCustomerCommand` (+ validation et
   composition « Prénom Nom ») dans `domain/customer.py` (+ exports) ; étendre
   `tests/test_domain_customer.py` (formats de saisie borne inclus). **Aucune** nouvelle erreur de
   domaine.
4. **Port & dépôt** : `find_by_phone` sur `application/ports/customer_repository.py` (docstring §11.2
   + forme canonique) et `SqlCustomerRepository` (lecture seule, gabarit `phone_exists`) ;
   `find_by_phone` sur le `FakeCustomerRepository` de `tests/conftest.py`.
5. **Cas d'usage** : `application/terminal_customers.py` (`IdentifyWalkInCustomer`,
   `CreateWalkInCustomer` — aucun import `users`, docstring anti-oracle, réutilise `LoginRateLimiter`,
   `CustomerRepository`, `AuditLog`) ; `tests/test_terminal_customer_usecases.py` (normalisation avant
   dépôt, prénom seul, audit `metadata={}`, limiteur, cloisonnement).
6. **Adapter entrant** : `adapters/inbound/terminal_customers.py` (deux routes `POST`, téléphone en
   corps, `extra="ignore"`, gardes `require_salon_scope` + `require_permission(...)`, mapping
   `404`/`409`/`422`/`429 + Retry-After`, messages neutres) ; **ne pas** toucher `PUBLIC_ROUTE_PATHS`.
7. **Câblage** : `include_router(terminal_customers_router)` + montage de
   `app.state.terminal_lookup_rate_limiter = InMemoryLoginRateLimiter(...)` (seuils terminal) dans
   `main.py`, commentaire de garde dans le style existant ; partager/réutiliser `_client_ip`.
8. **Matrice négative** : ajouter deux `_Route` à `tests/test_security_authz_matrix.py` (lookup →
   `CUSTOMER_LOOKUP_TERMINAL`, création → `CUSTOMER_CREATE_WALKIN`).
9. **Tests API & e2e** : `tests/test_terminal_customer_api.py` (projection minimale par assertions
   d'absence, RBAC négatif bidirectionnel, `429`) puis `tests/test_terminal_customer_e2e.py`
   (canonisation croisée, isolation inter-salons, anti-oracle `users` §4, traçabilité, concurrence,
   révocation) — purge `notifications` avant `appointments`/`users`/`salons` au nettoyage.
10. **Documentation** : section `backend/README.md` ; OpenAPI relue sur `/docs`.
11. **Vérification finale** : `scripts/test-gate.sh` au vert, `ruff check` propre ; relire la PR —
    aucun numéro de téléphone ni nom dans les logs/erreurs/audit, aucune route publique ajoutée,
    matrice `ROLE_PERMISSIONS` inchangée, routes gérant/provisioning intactes, **aucune signature
    IA** nulle part.
