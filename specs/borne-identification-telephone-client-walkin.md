# Identification téléphone & création client walk-in sur la borne (US-8.2)

> Spécification de planification pour l'issue GitHub **#156 — US-8.2 : Identification téléphone &
> création client walk-in** (`feature` · Must · Effort M · PRD §17 « Borne Intelligente d'Accueil »,
> promu au jalon **M7 — Borne client (kiosque libre-service)**, Épic 8).
> **Dépend de : #155, #28.** **Cette spec ne produit pas de code** : elle décrit l'approche à
> implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon M7 (bloc M7 de `BACKLOG.md:408-487`) promeut le parcours « client sans rendez-vous » du
PRD §17 au rang de fonctionnalité livrable. Dans ce parcours, la borne doit répondre à une question
avant toute délivrance de ticket : **qui se présente ?** Le texte de l'issue #156
(`BACKLOG.md:437-444`) l'exprime ainsi : un nouveau `find_by_phone` (port + repository + endpoint)
sur `CustomerProfile`, réservé au rôle `KIOSK`, **sans jamais interroger `users` par téléphone**
(préserve l'anti-oracle ADR-0026), et une ouverture ciblée de la création de fiche client à ce même
rôle. Critère d'acceptation : la borne retrouve une fiche existante par téléphone (salon de la borne
uniquement) et n'affiche que le **prénom** du client ; si absente, crée une fiche
nom/prénom/téléphone **sans mot de passe** ; isolation par salon respectée (§11.2).

État du dépôt, vérifié par lecture directe (code à l'état du commit `f5374b2`) :

- **Aucune recherche de fiche client par téléphone n'existe.** Le port `CustomerRepository`
  (`coiflink_api/application/ports/customer_repository.py`) n'expose que
  `phone_exists(salon_id, phone) -> bool` (lignes 75-82), un **pré-contrôle d'unicité** utilisé par
  `CreateCustomer`/`UpdateCustomer` — jamais un `find_by_phone(...) -> Customer | None`. Son
  implémentation SQL (`adapters/outbound/persistence/customer_repository.py:162-169`) fait un
  `select(CustomerProfile.id)` filtré `(salon_id, phone)` et ne retourne qu'un booléen. Le seul
  filtre de liste, `CustomerFilter.q`, cherche par **nom** (`ILIKE` sur `full_name`,
  `customer_repository.py:154-159`), jamais par téléphone.
- **La création de fiche est un parcours gérant authentifié, inaccessible à un terminal.**
  `POST /salons/{salon_id}/customers` (`adapters/inbound/customers.py:436-...`) exige
  `require_salon_scope` **et** `require_permission(Permission.CUSTOMER_MANAGE)`
  (`customers.py:453-456`), permission détenue par le **seul** `MANAGER`
  (`domain/permissions.py:121`). Le cas d'usage `CreateCustomer.execute`
  (`application/customers.py:94-100`) exige un `actor_user_id` — le `Principal` d'un compte
  personnel. Aucun rôle existant ne convient à un terminal public partagé : les 4 rôles sont fermés
  (`CLIENT`/`HAIRDRESSER`/`MANAGER`/`ADMIN`, `domain/enums.py:31-37`) et la matrice
  `ROLE_PERMISSIONS` (`domain/permissions.py:84-139`) est **figée par des tests d'exhaustivité**
  (`tests/test_domain_permissions.py:37,53,111,150,173`).
- **L'anti-oracle ADR-0026 est une règle documentée dans le code.**
  `application/customers.py:21-24` : le cas d'usage n'interroge **jamais** la table `users` par
  téléphone — ce serait offrir un **oracle d'existence de compte** (§11.1/§11.3). Le `find_by_phone`
  qui existe sur le port `UserRepository` (`application/ports/user_repository.py:34`) n'est utilisé
  que par l'authentification et le reset de mot de passe. La décision est actée dans
  `docs/adr/0026-fiche-client-portee-salon.md` (décision 3). #156 doit ajouter une recherche par
  téléphone **sans réintroduire ce problème** — c'est le cœur de l'analyse de sécurité de cette spec
  (voir *Security & Privacy Considerations*).
- **Le socle de données est prêt, aucune migration n'est nécessaire.** `CustomerProfile`
  (`adapters/outbound/persistence/models.py:414-467`) porte `full_name` (obligatoire), `phone`
  **nullable** (`models.py:424`), `user_id` **nullable** (« walk-in », `models.py:421-422`), et
  l'index unique **partiel** `uq_customer_profiles_salon_phone` sur `(salon_id, phone) WHERE phone
  IS NOT NULL` (`models.py:459-465`) : l'unicité du téléphone est **par salon**, pas globale — deux
  salons peuvent ficher le même numéro (commentaire `models.py:455-458`). Le téléphone stocké est
  toujours en forme canonique **E.164** (`normalize_customer_phone`, `domain/customer.py:81-98` →
  `normalize_phone`, `domain/phone.py:36-69`, indicatif par défaut `+225`), ce qui rend une
  recherche par **égalité stricte** correcte et indexée.
- **Le RBAC est deny-by-default et mécaniquement vérifié.** `require_authenticated` est une
  dépendance **globale** (`main.py:51-56`) ; toute route est fermée sauf inscription explicite dans
  `PUBLIC_ROUTE_PATHS` (`adapters/inbound/security.py:104-135`, « revue de sécurité obligatoire »,
  `security.py:44`) ; l'invariant `unprotected_routes(app)` (`security.py:248-260`) échoue si une
  route n'est ni publique-listée ni gardée.
- **Les specs sœurs de M7 s'alignent déjà sur le contrat de #156.**
  `specs/borne-app-mobile-mode-kiosque.md` (#159) consomme via son `identityGateway`
  `findByPhone(salonId, phone)` → `{customerId, firstName}` si trouvé, `404`/équivalent sinon, et
  `createCustomer(salonId, {firstName, lastName, phone})` → `{customerId, firstName}` **sans mot
  de passe** ;
  `specs/borne-ticket-file-attente-walkin.md` (#157) attend un `customer_profile_id` résolu par #156
  et n'affiche que `customer_first_name` (« jamais le nom complet — miroir décision #156 »). #156
  est donc la source d'autorité du contrat d'identification : cette spec le fixe.

Le gap que #156 comble : **(1)** un `find_by_phone` salon-scopé sur le port `CustomerRepository` et
son implémentation SQL ; **(2)** deux endpoints dédiés au rôle `KIOSK` (#155) — recherche par
téléphone à réponse **minimale** (prénom seul) et création de fiche walk-in sans mot de passe — sans
jamais élargir `CUSTOMER_MANAGE` ni toucher la table `users`.

## Goals

- **`find_by_phone` sur le port et le dépôt SQL, salon-scopé.**
  `find_by_phone(salon_id, phone) -> Customer | None` s'ajoute à
  `application/ports/customer_repository.py`, avec l'implémentation dans
  `SqlCustomerRepository` : filtre `(salon_id, phone)` **inconditionnel** — jamais de recherche
  cross-salon, une fiche d'un autre salon est **indiscernable d'une fiche inexistante** (miroir des
  invariants du port, `customer_repository.py:8-12`).
- **Recherche kiosque à exposition minimale.** Nouvel endpoint réservé au rôle `KIOSK` (#155) :
  soumission du téléphone en **corps de requête** (jamais en query string — pas de PII dans les
  URL/logs d'accès), réponse limitée à `{customer_id, first_name}` — **jamais** le nom complet, le
  téléphone, le genre, les notes ni les compteurs de visites.
- **Création de fiche walk-in depuis la borne, sans mot de passe.** Nouvel endpoint `KIOSK` créant
  une `CustomerProfile` à partir de **prénom + nom + téléphone** uniquement (`user_id = NULL`,
  aucun compte, aucun mot de passe) — réutilise la validation domaine de #28
  (`validate_customer_name`, `normalize_phone`) et l'unicité `(salon_id, phone)` existante.
- **Préservation stricte de l'anti-oracle ADR-0026.** Ni le cas d'usage ni l'adapter n'importent le
  moindre port `users` : la recherche porte **exclusivement** sur `customer_profiles`. Un téléphone
  titulaire d'un compte CoifLink mais sans fiche dans le salon répond « introuvable » — aucun repli
  vers `users`, démontré par un test e2e dédié.
- **Mitigations PII explicites** (voir *Security & Privacy Considerations*) : prénom seul à
  l'écran, limitation de débit des tentatives par device/IP (patron `LoginRateLimiter`,
  ADR-0013), messages d'erreur neutres, journalisation applicative **sans aucun numéro soumis**.
- **Isolation §11.2 en profondeur.** Garde de portée device→salon (contrat consommé de #155) sur
  chaque route **et** refiltre `salon_id` en SQL dans le dépôt (défense en profondeur, patron
  existant du module clients).
- **Aucun élargissement des rôles existants.** `CUSTOMER_MANAGE` reste MANAGER-seul ; les nouvelles
  routes portent des permissions **dédiées et minimales** détenues par le seul rôle `KIOSK` ; tests
  RBAC négatifs ajoutés (un JWT `CLIENT`/`MANAGER`/`HAIRDRESSER`/`ADMIN` est refusé sur les routes
  kiosque, un credential `KIOSK` est refusé sur les routes gérant).
- **Aucune migration de schéma.** La table `customer_profiles`, ses index et sa validation couvrent
  déjà le besoin — #156 est purement additif côté code.

## Non-Goals

Rappel du périmètre du jalon M7 dans son ensemble (bloc M7 de `BACKLOG.md`) — ce qui suit reste
différé, réévaluable plus tard, et n'est traité par **aucune** issue de M7 :

- **Vérification/check-in d'un rendez-vous existant depuis la borne** (« J'ai un rendez-vous »,
  PRD §17.3 « Vérification rendez-vous ») ;
- **Identification par QR code ou code de réservation** (PRD §17.3) — l'identification M7 est le
  téléphone, point ;
- **Affichage temps réel des coiffeurs disponibles avant affectation** ;
- **Paiement autonome sur la borne** (« Version future » du PRD §17.3 lui-même).

Hors périmètre de #156 en particulier :

- **Le rôle `KIOSK`, son credential device, sa garde de portée et son provisioning** : livrables de
  #155 (et #161 pour la procédure). #156 **consomme** ces briques ; les points de contrat exacts à
  coordonner sont listés dans *Risks and Open Questions*.
- **Le ticket de passage et la file d'attente walk-in** (#157) : #156 s'arrête à l'identité
  (`customer_id` + prénom) que #157 consommera comme `customer_profile_id`.
- **Toute l'UI borne** (écrans de saisie, clavier tactile, timer d'inactivité) : #159. Cette spec
  fixe seulement le **contrat HTTP** que ces écrans appelleront.
- **La recherche par nom** (PRD §17.3 liste « Nom du client » parmi les options d'identification) :
  écartée — une recherche par nom depuis un terminal public serait un outil d'énumération de PII
  bien plus large qu'une égalité stricte sur téléphone (voir *Security*).
- **Le rattachement d'une fiche à un compte utilisateur (`user_id`)** : la fiche créée par la borne
  est walk-in (`user_id = NULL`), comme en #28. Aucun rapprochement automatique avec `users`, ni
  maintenant ni par téléphone — c'est précisément l'anti-oracle.
- **Modification/suppression de fiche, notes, genre depuis la borne.** La borne ne collecte que
  prénom/nom/téléphone (collecte minimale §11.3) et ne peut rien éditer. `PATCH`/notes restent
  MANAGER-seuls (#144/#32).
- **Recherche cross-salon ou déduplication multi-salons** : la portée est le salon de la borne,
  cohérent avec l'unicité par salon en base (décision 6 de M7, voir *Risks*).
- **SMS/notification au client identifié** : rien n'est envoyé par #156.
- **Aucune modification des routes gérant existantes** (`/salons/{salon_id}/customers…`) : elles
  restent MANAGER-seules, contrat inchangé.

## Relevant Repository Context

### Backend — module clients (#28/#32/#144), la fondation directe

- **Port** `application/ports/customer_repository.py` : `Protocol` avec `create`, `find_by_id`,
  `list_for_salon`, `count_for_salon`, `phone_exists` (lignes 75-82), `update_notes`, `update`,
  `list_visits`, `list_payments`. Invariant documenté (lignes 8-12) : toutes les méthodes sur une
  fiche existante prennent `salon_id` **en plus** de l'identifiant — une fiche d'un autre salon est
  indiscernable d'une fiche inexistante.
- **Dépôt SQL** `adapters/outbound/persistence/customer_repository.py` : `phone_exists` (162-169)
  est le gabarit direct de `find_by_phone` ; `_to_domain` (421-433) mappe ORM → entité ;
  la retraduction `IntegrityError` → `CustomerAlreadyExists` sur l'index
  `uq_customer_profiles_salon_phone` (`_is_phone_duplicate`, 401-418) couvre la course concurrente
  à la création.
- **Cas d'usage** `application/customers.py` : `CreateCustomer` (87-139) — validation domaine →
  pré-contrôle `phone_exists` → `create` → `AuditEntry(CUSTOMER_CREATED, metadata={})` (aucune PII
  au journal, lignes 128-138). Docstring anti-oracle : lignes 21-24.
- **Domaine** `domain/customer.py` : `validate_customer_name` (59-78, trim, non vide, ≤ 255) ;
  `normalize_customer_phone` (81-98, optionnel → `None`, sinon E.164) ; entité `Customer` (163-181)
  qui **n'expose pas** `user_id` (commentaire 166-170, anti-oracle). `domain/phone.py` :
  `DEFAULT_COUNTRY_CODE = "225"` (24), bornes 8-15 chiffres (28-29), séparateurs tolérés
  `[\s.\-()]` (33), `normalize_phone` (36-69) idempotente, `00` → `+` (51-53), numéro national
  préfixé `+225` **sans retirer le 0 de tête** (57-60) : `0700000000` → `+2250700000000`.
- **ORM** `models.py::CustomerProfile` (414-467) : `phone` `String(32)` nullable (424), index
  unique partiel `(salon_id, phone) WHERE phone IS NOT NULL` (459-465) — il sert aussi la
  **recherche** par égalité `(salon_id, phone)` (parcours d'index, aucun index à ajouter).
- **Adapter entrant** `adapters/inbound/customers.py` : patron de garde à répliquer —
  `require_salon_scope` + `require_permission(Permission.CUSTOMER_MANAGE)` (453-456), mapping
  erreurs domaine → `422`/`409`/`404` (12-15), messages neutres sans PII.

### Sécurité, RBAC, limitation de débit

- `adapters/inbound/security.py` : mode d'emploi de protection d'une route (33-42), avertissement
  `PUBLIC_ROUTE_PATHS` (44), liste publique (104-135), `unprotected_routes` (248-260),
  `require_authenticated` (325), `require_permission` (437), `require_salon_scope` (479). `403`
  générique et constant, jamais d'oracle.
- `domain/permissions.py` : enum `Permission` (33-78), matrice fermée `ROLE_PERMISSIONS` (84-139),
  `permissions_for` tolérant (142-153 : rôle inconnu = aucun droit). Les tests
  `tests/test_domain_permissions.py` figent la matrice **à l'égalité stricte** (lignes 53, 111,
  150, 173) : ajouter un rôle/une permission impose de les mettre à jour dans la même PR (#155 en
  est propriétaire ; #156 s'y coordonne).
- **Anti-bruteforce existant, patron à décliner** : port `LoginRateLimiter`
  (`application/ports/login_rate_limiter.py:17-34` — `check`/`record_failure`/`reset`, clé opaque
  construite par le cas d'usage) ; adapter fenêtre glissante en mémoire
  (`adapters/outbound/security/login_rate_limiter_memory.py`, seuils par défaut 5 échecs / 300 s,
  verrou 900 s, horloge injectable) ; mapping `TooManyLoginAttempts` → `429` + `Retry-After`
  (`adapters/inbound/auth.py:380-386` et 569-575). ADR-0013 documente le choix (adapter Redis
  différé).
- **Journal d'audit** : `AuditEntry.actor_user_id` est un `uuid.UUID` **non nullable**
  (`domain/audit.py:141-159`) et la colonne `audit_logs.actor_user_id` est `NOT NULL` avec FK
  `users.id` `ON DELETE RESTRICT` (`models.py:715,731`). **Conséquence structurante** : un device
  `KIOSK` ne peut être acteur d'audit que si #155 matérialise le device par une ligne `users` (ou
  décide d'assouplir ce point) — voir *Risks*.

### Anti-oracle ADR-0026 — le précédent à ne pas trahir

`docs/adr/0026-fiche-client-portee-salon.md`, décision 3 : interroger `users` par numéro
transformerait la route en oracle d'existence de **compte** — un gérant pourrait tester des numéros
arbitraires et apprendre qui possède un compte CoifLink. Le `find_by_phone` de `UserRepository`
(`application/ports/user_repository.py:34`, impl `user_repository.py:39`) n'est consommé que par
l'authentification/le reset. La distinction compte (`users`, avec mot de passe, portée plateforme)
vs fiche (`customer_profiles`, sans authentification, portée salon) fonde toute l'analyse de
sécurité de #156 (voir *Security & Privacy Considerations*).

### Specs sœurs M7 (contrats croisés)

- `specs/borne-ticket-file-attente-walkin.md` (#157) : le ticket porte un `customer_profile_id`
  nullable résolu par #156 ; la réponse de file n'expose que `customer_first_name` ; coordination
  de nommage des permissions `KIOSK` (nom retenu : `QUEUE_TICKET_CREATE`, fixé par #155).
- `specs/borne-app-mobile-mode-kiosque.md` (#159) : contrats `identityGateway.findByPhone` /
  `createCustomer` que la présente spec officialise et sur lesquels #159 est désormais aligné
  (`findByPhone` → `{customerId, firstName}` ; `createCustomer` → `{customerId, firstName}`) ;
  hypothèse de numérotation des libellés US-00x (38-46) reprise ici (voir *Proposed Implementation
  §E* et *Risks*).
- `specs/borne-role-authentification-kiosque.md` (#155) : fixe le rôle `KIOSK`, ses permissions
  dédiées (`CUSTOMER_LOOKUP_KIOSK`, `CUSTOMER_CREATE_WALKIN`, `QUEUE_TICKET_CREATE`) et le login
  device `POST /auth/kiosk/login`, dont la réponse porte le `salon_id` de la borne — la garde de
  portée device→salon et le `Principal` device que #156 consomme.

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
(`customer_repository.py:162-169`) mais `select(models.CustomerProfile)` complet +
`_to_domain(row)` — lecture seule, aucun flush. L'index unique partiel existant sert la requête
(parcours d'index sur `(salon_id, phone)`), aucun index supplémentaire.

`phone_exists` est **conservé tel quel** (consommé par `CreateCustomer`/`UpdateCustomer`) ;
optionnellement, son implémentation peut déléguer à `find_by_phone is not None` — micro-refactor
laissé au choix de l'implémenteur, le contrat du port ne change pas.

### (B) Domaine — identité minimale walk-in et dérivation du prénom

Dans `domain/customer.py` (pur, aucune dépendance) :

- **`walk_in_first_name(full_name: str) -> str`** : premier token de `full_name.split()` (la
  chaîne est déjà validée non vide par `validate_customer_name`). C'est la **projection d'affichage
  borne** exigée par le critère d'acceptation (« n'affiche que le prénom »). Le modèle ne stocke
  qu'un `full_name` (`models.py:423`) : plutôt qu'une migration (colonne `first_name`), la
  dérivation est garantie exacte pour les fiches **créées par la borne** (composition contrôlée,
  ci-dessous) et assumée heuristique pour les fiches historiques saisies par le gérant (voir
  *Risks* §5).
- **`@dataclass(frozen=True) WalkInIdentity`** : `customer_id: uuid.UUID`, `first_name: str` — la
  **seule** projection qui franchit la frontière HTTP kiosque. Ni téléphone, ni nom complet, ni
  genre, ni notes, ni compteurs : l'entité `Customer` complète ne sort **jamais** vers la borne.
- **`@dataclass(frozen=True) WalkInCustomerCommand`** : `first_name: str`, `last_name: str`,
  `phone: str` — les trois champs de l'acceptation (« nom/prénom/téléphone sans mot de passe »),
  tous **requis** au kiosque. Validation :
  1. `first_name` et `last_name` : trim, non vides (réutilise la mécanique de
     `validate_customer_name` — erreur `InvalidCustomerName`, messages neutres) ;
  2. composition **ordonnée** `full_name = f"{first_name} {last_name}"` puis
     `validate_customer_name(full_name)` (borne ≤ 255 respectée sur le résultat composé) — l'ordre
     « Prénom Nom » garantit `walk_in_first_name(full_name) == first_name` saisi ;
  3. `phone` : **requis** (contrairement au flux gérant #28 où il est optionnel) — c'est la clé
     d'identification de la borne, une fiche kiosque sans téléphone serait introuvable à la
     prochaine visite. Normalisation par `normalize_phone` (`domain/phone.py:36`) directement
     (sémantique « requis » : vide → `InvalidPhone`), pas par le wrapper optionnel
     `normalize_customer_phone`. La colonne reste nullable — aucune migration.

Nouvelle erreur de domaine (`domain/errors.py`) : **`TooManyKioskAttempts`** (miroir de
`TooManyLoginAttempts`, `errors.py:526`, avec `retry_after` indicatif) → `429`.

### (C) Cas d'usage — `application/kiosk_customers.py` (nouveau module)

Module applicatif dédié (les cas d'usage gérant de `application/customers.py` restent inchangés),
dépendant **uniquement** des ports `CustomerRepository`, `AuditLog` et du limiteur (§D) — et
**surtout pas** de `UserRepository` : l'absence de tout import `users` dans ce module est le miroir
exécutable de l'anti-oracle (docstring de module explicite, comme `application/customers.py:21-24`).

- **`IdentifyWalkInCustomer.execute(salon_id, raw_phone, *, rate_key) -> WalkInIdentity | None`** :
  1. `limiter.check(rate_key)` — lève `TooManyKioskAttempts` si la fenêtre est verrouillée ;
  2. `normalize_phone(raw_phone)` — un format invalide lève `InvalidPhone` **avant** tout accès
     base, et compte comme tentative (`record_failure`) : sonder des formats ne contourne pas la
     limite ;
  3. `repository.find_by_phone(salon_id, phone)` — le `salon_id` provient de la **portée device
     validée** (garde #155), jamais du corps ;
  4. fiche trouvée → `limiter.reset(rate_key)` puis projection
     `WalkInIdentity(customer_id, walk_in_first_name(full_name))` ; absente →
     `limiter.record_failure(rate_key)` puis `None` (l'adapter mappe en `404` neutre).
  Lecture **sans audit** : cohérent avec ADR-0026 décision 8 (les lectures de fiches ne sont pas
  journalisées — coût/bruit) et indispensable ici (un terminal public générerait un volume d'audit
  par simple usage nominal). La traçabilité opérationnelle passe par la limitation de débit et des
  logs applicatifs **sans le numéro soumis**.
- **`CreateWalkInCustomer.execute(salon_id, command, *, actor_user_id) -> WalkInIdentity`** :
  1. validation/composition domaine (§B) **avant tout accès base** ;
  2. pré-contrôle `phone_exists(salon_id, phone)` → `CustomerAlreadyExists` (message neutre
     existant : « Une fiche existe déjà pour ce numéro dans ce salon. ») — en concurrence, l'index
     unique base tranche et le dépôt retraduit (patron #28 inchangé) ;
  3. `repository.create(CustomerToCreate(salon_id=salon_id, full_name=..., phone=...,
     gender=None, notes=None))` — `user_id` reste `NULL` (walk-in), genre et notes **jamais**
     collectés par la borne (collecte minimale §11.3) ;
  4. `audit_log.record(AuditEntry(action=CUSTOMER_CREATED, actor_user_id=actor_user_id,
     salon_id=..., entity_type=ENTITY_TYPE_CUSTOMER, entity_id=..., metadata={}))` — même action
     et même neutralité que #28 ; l'acteur est le principal **device** fourni par la garde #155
     (point de coordination : voir *Risks* §2) ;
  5. retour `WalkInIdentity` (jamais la fiche complète).

### (D) Limitation de débit — port dédié, adapter réutilisé

Nouveau port `application/ports/kiosk_rate_limiter.py::KioskLookupRateLimiter`, contrat identique
à `LoginRateLimiter` (`check`/`record_failure`/`reset`, clé opaque). L'adapter réutilise la
mécanique de `InMemoryLoginRateLimiter` (fenêtre glissante + verrou temporisé, horloge injectable)
avec des **seuils propres au kiosque** (proposition de départ : 10 échecs / 5 min, verrou 10 min —
un client légitime peut se tromper deux fois de numéro sans être bloqué, un énumérateur est freiné ;
valeurs à ajuster, *Risks* §7) et l'erreur `TooManyKioskAttempts`. La clé est construite par
l'adapter entrant : `principal device + IP client` (même mécanique d'extraction d'IP que la
connexion #10, ADR-0013). Ne comptent que les **échecs** (`404` fiche absente, `422` format
invalide) ; une identification réussie réinitialise la fenêtre — un salon à fort trafic légitime
n'est jamais pénalisé. Comme pour la connexion, l'implémentation mémoire est un choix MVP assumé
(mono-process ; adapter Redis différé, parité ADR-0013).

### (E) Adapter entrant — `adapters/inbound/kiosk_customers.py` (nouveau router)

Router `APIRouter(prefix="/salons", tags=["kiosk"])`, un fichier par ressource (convention du
dépôt). Deux routes, toutes deux **protégées** (jamais dans `PUBLIC_ROUTE_PATHS`) :

- **`POST /salons/{salon_id}/kiosk/customers/lookup`** — recherche par téléphone. `POST` et non
  `GET` : le numéro voyagerait sinon en query string (PII dans les logs d'accès, l'historique des
  proxies, les URL de trace). Corps `{"phone": "..."}` (`extra="ignore"`). Réponses : `200`
  `{customer_id, first_name}` · `404` neutre (« Aucune fiche pour ce numéro dans ce salon. » — sans
  rappeler le numéro) · `422` `InvalidPhone` · `429` + `Retry-After` (`TooManyKioskAttempts`,
  patron `auth.py:380-386`) · `401`/`403` par les gardes.
- **`POST /salons/{salon_id}/kiosk/customers`** — création walk-in. Corps
  `{"first_name", "last_name", "phone"}` (`extra="ignore"` : tout champ privilégié — `salon_id`,
  `user_id`, `notes`, `gender`, `total_visits` — est ignoré). Réponses : `201`
  `{customer_id, first_name}` · `409` doublon (le parcours borne ré-exécute alors le lookup : la
  fiche existe désormais, le flux continue — contrat documenté pour #159) · `422` champ invalide ·
  `401`/`403`.

Gardes sur chaque route, dans le style `security.py:33-42` : la **garde de portée device→salon
livrée par #155** (le `salon_id` du chemin doit être **exactement** celui du provisioning du
device — l'équivalent kiosque de `require_salon_scope`) **et**
`require_permission(Permission.CUSTOMER_LOOKUP_KIOSK)` / `(Permission.CUSTOMER_CREATE_WALKIN)` —
deux permissions **nouvelles, dédiées et minimales**, détenues par le **seul** rôle `KIOSK`
(noms canoniques fixés par #155 qui possède la matrice, cf. *Risks* §3). Aucun rôle existant ne les
reçoit : un JWT `MANAGER` est refusé sur les routes kiosque (il a ses propres routes, plus riches),
un credential `KIOSK` reste incapable d'atteindre `CUSTOMER_MANAGE` ou `APPOINTMENT_BOOK`
(acceptation #155). Câblage `main.py` : `app.include_router(kiosk_customers_router)` avec le
commentaire de garde habituel (patron `main.py:120-216`).

### (F) Mapping parcours borne → champs et validations existantes

Les libellés « US-00x » du jalon M7 ne sont définis nulle part de façon autoritaire ; la spec sœur
#159 (`specs/borne-app-mobile-mode-kiosque.md:38-46`) retient comme **hypothèse de travail** la
numérotation des étapes du parcours borne PRD §17.4 (`prd-coiflink.md:1349-1362`). Sous cette
hypothèse, #156 est la **logique** derrière les étapes 4 (« Il s'identifie par téléphone ») et 5
(« La borne vérifie ses informations ») — les écrans étant à #159. Le mapping des saisies borne
vers le domaine existant :

| Saisie borne (UI #159) | Champ backend #156 | Validation/normalisation existante |
| --- | --- | --- |
| Numéro saisi au clavier tactile (formats libres) | `phone` (lookup **et** création) | `normalize_phone` (`domain/phone.py:36-69`) : séparateurs espace/point/tiret/parenthèses retirés (`phone.py:33`), `00` → `+` (51-53), numéro national préfixé **`+225`** sans retirer le `0` de tête (57-60), bornes 8-15 chiffres (28-29), idempotente |
| Prénom | `first_name` → 1er composant de `full_name` | trim + non vide (mécanique `validate_customer_name`, `domain/customer.py:59-78`) |
| Nom | `last_name` → 2e composant de `full_name` | idem ; composition « Prénom Nom » puis `validate_customer_name` sur le tout (≤ 255) |
| *(non collectés)* | `gender`, `notes`, mot de passe, `user_id` | jamais demandés ni acceptés par la borne (collecte minimale §11.3 ; `extra="ignore"`) |

**Comportement quand le format de saisie borne diffère du web/mobile classique** (clavier virtuel
numérique, à distance de bras) : la normalisation est **côté serveur, unique et idempotente** — la
même `normalize_phone` que l'inscription (#8/#9) et la fiche gérant (#28). Conséquence garantie :
`07 00 00 00 00`, `0700000000`, `+225 07-00-00-00-00` et `0022507000000 00` produisent tous
`+2250700000000` et retrouvent **la même fiche**, qu'elle ait été créée par le gérant au dashboard
ou par la borne elle-même (les fiches sont stockées canoniques depuis #28 —
`domain/customer.py:81-98`). Le pavé numérique de #159 peut restreindre les caractères saisissables
(confort), mais cette pré-normalisation UI n'est **jamais** autoritaire : le contrat est défini par
le backend seul. Une saisie hors tolérance (lettres, `#`, longueur hors 8-15) lève `InvalidPhone` →
`422` à message neutre (jamais l'écho du numéro) ; la borne propose une nouvelle saisie et
l'échec compte dans la fenêtre de débit (§D).

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/application/kiosk_customers.py` | cas d'usage `IdentifyWalkInCustomer`, `CreateWalkInCustomer` (aucun import `users`) |
| `coiflink_api/application/ports/kiosk_rate_limiter.py` | port `KioskLookupRateLimiter` (miroir `LoginRateLimiter`) |
| `coiflink_api/adapters/inbound/kiosk_customers.py` | router `/salons/{salon_id}/kiosk/customers[...]` |
| `tests/test_kiosk_customer_usecases.py`, `tests/test_kiosk_customer_api.py`, `tests/test_kiosk_customer_e2e.py` | tests (voir *Testing Plan*) |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/application/ports/customer_repository.py` | méthode `find_by_phone` (docstring isolation §11.2 + forme canonique) |
| `coiflink_api/adapters/outbound/persistence/customer_repository.py` | implémentation `find_by_phone` (lecture seule, gabarit `phone_exists:162-169`) |
| `coiflink_api/domain/customer.py` | `walk_in_first_name`, `WalkInIdentity`, `WalkInCustomerCommand` + validation/composition |
| `coiflink_api/domain/errors.py` | `TooManyKioskAttempts` |
| `coiflink_api/domain/permissions.py` | `Permission.CUSTOMER_LOOKUP_KIOSK` / `CUSTOMER_CREATE_WALKIN` + entrée `Role.KIOSK` dans `ROLE_PERMISSIONS` — **copropriété #155**, même PR ou coordination stricte (cf. *Risks* §3) |
| `coiflink_api/adapters/outbound/security/` | adapter de débit kiosque (réutilisation de la mécanique `login_rate_limiter_memory.py`) |
| `coiflink_api/main.py` | `include_router(kiosk_customers_router)` + assemblage du limiteur (singleton, patron du limiteur de connexion) |
| `tests/conftest.py` | `find_by_phone` sur `FakeCustomerRepository` + fake du limiteur kiosque |
| `tests/test_domain_customer.py` | cas `walk_in_first_name` + commande walk-in |
| `tests/test_domain_permissions.py` | matrice étendue (avec #155) : `KIOSK` n'a que ses permissions dédiées, aucun rôle existant ne les gagne |
| `backend/README.md` | section « Borne — identification & création walk-in (US-8.2, #156) » |

### Non touchés (garde-fous)

`app-mobile/` (#159), `web-dashboard/` (aucun écran gérant ne change), `migrations/` (**aucune
migration**), `adapters/inbound/customers.py` et `application/customers.py` (routes et cas d'usage
gérant inchangés), `application/ports/user_repository.py` (jamais importé par le nouveau module),
`PUBLIC_ROUTE_PATHS` (rien n'y entre).

## API / Interface Changes

Deux **nouveaux** endpoints, tous deux **protégés** (garde de portée device #155 + permission
`KIOSK` dédiée) ; aucune route existante ne change ; rien n'entre dans `PUBLIC_ROUTE_PATHS`
(« réservé au rôle KIOSK » signifie *atteignable par un device provisionné*, pas *public*). Pas de
préfixe `/v1` : routes strictement additives, cohérent avec tout le dépôt (décision 10 de M7).

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/kiosk/customers/lookup` | portée device→salon (#155) + `CUSTOMER_LOOKUP_KIOSK` | `200` identité · `404` neutre · `422` téléphone invalide · `429` + `Retry-After` · `401`/`403` |
| `POST` | `/salons/{salon_id}/kiosk/customers` | portée device→salon (#155) + `CUSTOMER_CREATE_WALKIN` | `201` identité · `409` doublon · `422` champ invalide · `401`/`403` |

```jsonc
// POST /salons/{salon_id}/kiosk/customers/lookup — corps
{ "phone": "07 00 00 00 00" }        // tout format toléré par normalize_phone ; jamais en query string

// 200 — trouvé (projection MINIMALE : jamais nom complet, téléphone, genre, notes, visites)
{ "customer_id": "…uuid…", "first_name": "Awa" }

// 404 — introuvable dans CE salon (message neutre, sans écho du numéro)
{ "detail": "Aucune fiche pour ce numéro dans ce salon." }
```

```jsonc
// POST /salons/{salon_id}/kiosk/customers — corps (extra="ignore")
{ "first_name": "Awa", "last_name": "Koné", "phone": "0700000000" }   // les 3 champs requis

// 201 — créé (user_id = NULL en base, jamais exposé ; téléphone stocké +2250700000000)
{ "customer_id": "…uuid…", "first_name": "Awa" }

// 409 — une fiche porte déjà ce numéro dans ce salon (la borne relance alors le lookup)
{ "detail": "Une fiche existe déjà pour ce numéro dans ce salon." }
```

Contrats croisés fixés par cette API : le `customer_id` retourné est le `customer_profile_id`
attendu par la création de ticket #157 ; le corps de création `{first_name, last_name, phone}` et
la réponse `{customer_id, first_name}` sont le contrat canonique du jalon, sur lequel
l'`identityGateway` Flutter de #159 (`specs/borne-app-mobile-mode-kiosque.md`) est désormais
aligné : `findByPhone` → `{customerId, firstName}`, `createCustomer(salonId, {firstName,
lastName, phone})` → `{customerId, firstName}` — le `customerId` restant nécessaire à #157
(`customer_profile_id` du ticket). Aucune modification de CLI, de variable
d'environnement ni de contrat inter-paquet existant.

## Data Model / Protocol Changes

**Aucune migration.** Le schéma actuel couvre le besoin :

- `customer_profiles` porte déjà `full_name`/`phone`/`user_id NULL` (walk-in) — la fiche créée par
  la borne est **exactement** celle de #28, sans genre ni notes (colonnes laissées `NULL`) ;
- l'index unique partiel `uq_customer_profiles_salon_phone` (`models.py:459-465`) garantit
  l'unicité **et** sert la recherche par égalité `(salon_id, phone)` — aucun index à ajouter ;
- la forme canonique E.164 stockée depuis #28 rend l'égalité stricte correcte (pas de recherche
  floue, pas de `LIKE`).

Aucun changement de format de sérialisation ailleurs ; le protocole d'authentification device
(jeton, en-têtes) appartient à #155, dont la migration `0013_kiosk_role.py` (compte de service
`users` + `salon_members`, pas de table de credentials séparée) ne touche pas au schéma clients —
#156 n'en dépend donc pas au niveau du schéma.

## Security & Privacy Considerations

**Pourquoi ce `find_by_phone` ne réintroduit pas l'oracle interdit par l'ADR-0026 — et quel risque
différent il crée.** L'analyse tient en trois points :

1. **L'oracle ADR-0026 protège les *comptes*, pas les *fiches*.** Une ligne `users` porte un mot de
   passe et une existence **plateforme** : savoir qu'un numéro possède un compte CoifLink ouvre des
   attaques ciblées (bruteforce de connexion, sondage du reset OTP, phishing crédible) et révèle un
   fait **global**, valable pour tous les salons. C'est pourquoi `application/customers.py:21-24`
   interdit toute requête `users` par téléphone. Une `CustomerProfile` est tout autre chose : un
   dossier métier **local à un salon**, sans matériel d'authentification — savoir qu'elle existe
   n'ouvre **aucune** attaque sur un credential (il n'y en a pas).
2. **Le fait divulgué reste dans la frontière de données du salon (§11.2).** `find_by_phone` révèle
   « ce numéro a une fiche dans **ce** salon » — une information que le salon possède déjà
   intégralement : son `MANAGER` liste toutes ses fiches via `CUSTOMER_MANAGE`
   (`GET /salons/{salon_id}/customers`, #28). Le device `KIOSK` est un agent du même salon, borné
   au même périmètre. La nouveauté n'est donc **pas** ce que le salon apprend, mais **qui d'autre**
   pourrait l'apprendre : la personne debout devant l'écran, ou un porteur du credential device
   volé.
3. **Le risque réel est une exposition de PII sur un écran public partagé** (associer un nom à un
   numéro composé par n'importe qui), plus une **énumération** salon-locale par un attaquant
   physique ou un credential exfiltré. Les mitigations ciblent exactement cela :

- **Prénom seul, projection minimale par construction.** `WalkInIdentity` ne porte que
  `customer_id` + `first_name` : le nom complet, le téléphone (même celui qui vient d'être saisi),
  le genre, les notes (données potentiellement de santé, US-4.5) et les compteurs de visites ne
  franchissent **jamais** la frontière HTTP kiosque. Décision cohérente avec #157 qui n'affiche que
  `customer_first_name` dans la file.
- **Limitation de débit par device + IP** (§D) : fenêtre glissante sur les échecs (`404`/`422`),
  verrou temporisé, `429` + `Retry-After` — l'énumération d'un annuaire téléphonique devient
  impraticable au rythme d'un terminal. Patron éprouvé de la connexion (ADR-0013).
- **Portée device→salon** (#155) : le credential d'une borne du salon X ne peut interroger que le
  salon X — l'énumération cross-salons est structurellement impossible, en plus du refiltre SQL
  `salon_id` du dépôt (défense en profondeur, patron `customer_repository.py:14-17`).
- **Jamais `users`.** Le module applicatif n'importe aucun port `users` ; un numéro titulaire d'un
  compte CoifLink mais sans fiche dans le salon répond `404` — indiscernable d'un numéro inconnu de
  la plateforme. Test e2e dédié (voir *Testing Plan*) : la route ne peut pas servir d'oracle de
  compte, même par canal auxiliaire.
- **Aucune PII dans les logs, l'audit ni les erreurs.** Le numéro soumis n'apparaît dans aucun log
  applicatif ni message d'erreur (messages neutres constants, patron §11.3 du module clients) ; la
  clé de débit est opaque (device + IP, jamais le numéro) ; la création journalise
  `CUSTOMER_CREATED` avec `metadata = {}` (parité stricte #28) ; les lookups ne sont pas audités
  (ADR-0026 décision 8 — et un terminal public inonderait le journal par usage nominal).
- **Téléphone en corps de requête, jamais en URL** : pas de PII dans les logs d'accès,
  l'historique des proxies ou les traces.
- **Deny-by-default intact** : aucune entrée `PUBLIC_ROUTE_PATHS`, invariant `unprotected_routes`
  au vert ; permissions **dédiées** au rôle `KIOSK`, aucun élargissement de `CUSTOMER_MANAGE`
  (MANAGER-seul, `permissions.py:121`) ni d'`APPOINTMENT_BOOK` (CLIENT-seul, `permissions.py:92`) ;
  tests RBAC négatifs dans les deux sens (acceptation #155).
- **Collecte minimale (§11.3)** : prénom, nom, téléphone — rien d'autre n'est demandé ni accepté
  (`extra="ignore"`). Pas de mot de passe : aucune promesse d'authentification n'est faite au
  client, aucune surface de credential n'est créée. `salon_id` vient toujours du chemin validé par
  la garde de portée, jamais du corps (anti-élévation, patron #28).
- **Bornes d'entrée** : nom composé ≤ 255, téléphone E.164 8-15 chiffres — pas de corps non borné
  (budget §12.1).
- **Sécurité résiduelle assumée** : un client légitime peut composer le numéro d'un tiers présent
  dans le salon et voir son prénom. Résidu jugé acceptable pour le MVP : information minimale
  (prénom seul), débit limité, et le contexte physique (borne dans le salon, personnel à
  proximité) rend l'abus observable. Consigné pour l'ADR-0041 (livrée avec #155, présence
  vérifiée par #161).

## Testing Plan

### Domaine (`pytest`, sans I/O) — `tests/test_domain_customer.py` (étendu)

- `walk_in_first_name` : `"Awa Koné"` → `"Awa"` ; nom simple sans espace → lui-même ; espaces
  multiples/trim.
- `WalkInCustomerCommand` : prénom ou nom vide/blanc → `InvalidCustomerName` ; téléphone absent ou
  vide → `InvalidPhone` (requis au kiosque, contrairement à #28) ; composition « Prénom Nom » →
  `walk_in_first_name` restitue exactement le prénom saisi ; composé > 255 → `InvalidCustomerName` ;
  formats de saisie borne (`"07 00 00 00 00"`, `"+225 07-00-00-00-00"`, `"0022507…"`) → même forme
  canonique `+2250700000000` (idempotence incluse).

### Cas d'usage (fakes de `conftest.py`) — `tests/test_kiosk_customer_usecases.py`

- **Lookup** : normalisation **avant** l'appel dépôt (le fake reçoit la forme canonique quel que
  soit le format soumis) ; fiche trouvée → `WalkInIdentity` au prénom seul, `reset` appelé ;
  absente → `None` + `record_failure` ; format invalide → `InvalidPhone` + `record_failure`,
  **aucun** appel dépôt ; limiteur verrouillé → `TooManyKioskAttempts`, **aucun** appel dépôt ;
  le `salon_id` transmis au dépôt est **celui de la portée**, jamais dérivé du corps ; aucune
  entrée d'audit sur un lookup.
- **Création** : fiche persistée avec `full_name` composé, téléphone canonique, `gender`/`notes`
  `None` ; `CUSTOMER_CREATED` enregistrée une fois, `metadata == {}` (aucune PII), acteur =
  principal device fourni ; doublon → `CustomerAlreadyExists` sans écriture ni audit ; validation
  invalide → aucune écriture, aucun audit ; même téléphone dans un **autre** salon → accepté
  (cloisonnement §11.2).
- **Anti-oracle structurel** : le module `application/kiosk_customers.py` n'importe aucun port
  `users` (assertion d'import, dans l'esprit des tests d'invariant du dépôt).

### API (`TestClient` + `app.dependency_overrides`) — `tests/test_kiosk_customer_api.py`

- `200` lookup : corps **exactement** `{customer_id, first_name}` — assertions d'**absence** de
  `full_name`, `phone`, `gender`, `notes`, `user_id`, `total_visits` ; `404` neutre (sans écho du
  numéro) ; `422` téléphone invalide ; `429` + en-tête `Retry-After` quand le limiteur est
  verrouillé.
- `201` création : corps minimal, champs privilégiés du corps (`salon_id`, `user_id`, `notes`,
  `gender`) **ignorés** ; `409` doublon ; `422` par champ manquant/invalide.
- **RBAC négatif** (matrice #155 étendue) : `401` sans credential sur les deux routes ; `403` pour
  un JWT `CLIENT`, `MANAGER`, `HAIRDRESSER`, `ADMIN` sur les routes kiosque ; le principal `KIOSK`
  est refusé (`403` constant) sur `GET/POST /salons/{salon_id}/customers` (routes
  `CUSTOMER_MANAGE`) et sur `POST /salons/{salon_id}/appointments` (`APPOINTMENT_BOOK`) ; device du
  salon X → `403` sur le salon Y (portée).
- `tests/test_security_guards.py` : `unprotected_routes(app) == []` couvre mécaniquement les
  nouvelles routes ; vérifier qu'aucun chemin `kiosk` n'entre dans `PUBLIC_ROUTE_PATHS`.

### e2e (PostgreSQL réel, sauté sans `DATABASE_URL`) — `tests/test_kiosk_customer_e2e.py`

Patron `test_customer_e2e.py` (plage de téléphones réservée, nettoyage avant/après — attention aux
`notifications` à purger d'abord, contrainte connue du dépôt) :

1. **Parcours nominal** : gérant crée une fiche au dashboard (#28, numéro au format local) →
   lookup kiosque du même numéro **dans un autre format de saisie** → `200`, prénom attendu —
   preuve de la canonisation croisée des canaux ;
2. **Création borne** : lookup `404` → création `201` → second lookup `200` avec le même
   `customer_id` → la fiche apparaît dans la liste gérant #28 (`user_id` absent de la réponse,
   `gender`/`notes` `NULL`) ;
3. **Isolation §11.2** : fiche du salon A introuvable (`404`) depuis le device du salon B ; même
   numéro fiché dans A et B → chaque device retrouve **sa** fiche ;
4. **Anti-oracle `users`** : créer un compte `CLIENT` (table `users`) avec un téléphone sans fiche
   dans le salon → lookup kiosque de ce numéro → `404`, indiscernable d'un numéro inconnu de la
   plateforme ;
5. **Traçabilité** : la création borne écrit une ligne `audit_logs` `CUSTOMER_CREATED` avec
   l'acteur device et `metadata` vide (aucune PII — assertion explicite) ; aucun lookup n'écrit
   d'audit ;
6. **Concurrence** : deux créations simultanées du même numéro → un `201` + un `409` (index unique
   partiel, retraduction existante).

### Non-régression

`scripts/test-gate.sh` au vert (pytest + npm test + flutter test — web et mobile sans changement
attendu) ; `ruff check` propre ; suites #28/#32/#144 inchangées (routes gérant intactes).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Borne — identification téléphone & création walk-in
  (US-8.2, #156) » : tableau routes/permission/réponses, règles de normalisation téléphone
  (formats acceptés → forme canonique), note d'isolation §11.2 et renvoi vers l'analyse
  anti-oracle (gabarit des sections existantes du README).
- **ADR** : #156 ne crée **pas** d'ADR propre — le modèle d'authentification borne et son volet
  identité (décision produit M7 n°1) sont consignés par
  `docs/adr/0041-authentification-borne-kiosque.md`, committée avec l'implémentation de **#155**
  (#161 vérifie sa présence, l'écrit si elle manque encore à ce stade et met à jour l'index
  `docs/adr/README.md`). Cette spec fournit à cette ADR le matériau à consigner : distinction
  oracle compte/fiche, projection prénom seul, limitation de débit, lookups non audités, risque
  résiduel assumé. Si #155 tarde, un paragraphe « décisions de sécurité » du README backend fait
  foi temporairement.
- **`docs/adr/0026-fiche-client-portee-salon.md`** : ne pas le modifier — la décision 3 (jamais
  `users` par téléphone) reste vraie mot pour mot. L'ADR-0041 la **référencera** en expliquant
  pourquoi `find_by_phone` sur `customer_profiles` ne la contredit pas.
- **`BACKLOG.md` / `README.md` racine** : mise à jour de statut du jalon M7 une fois l'issue
  livrée (phrase de statut, convention des livraisons précédentes) ; la mise à jour PRD/BACKLOG de
  fin de jalon appartient à #161.
- **OpenAPI** : `summary`/`responses`/docstrings des deux routes (visibles sur `/docs`), y compris
  `404`/`409`/`422`/`429` et la mention explicite « réponse minimale : prénom seul ».

## Risks and Open Questions

Décisions d'architecture M7 concernant directement #156 — présentées comme des **choix à valider
par le porteur produit avant l'implémentation**, avec leur justification technique :

1. **Recherche limitée à `CustomerProfile`, jamais `users` ; prénom seul à l'écran — second volet
   de la décision produit M7 n°1, dont l'autre volet (rôle `KIOSK` + credential device) est porté
   par #155.** Justification : la distinction compte/fiche (voir *Security*) permet d'offrir
   l'identification borne sans créer d'oracle de compte ; le prénom seul borne l'exposition PII sur
   un écran public au minimum utilisable (« Bonjour Awa »). Coût assumé : un client homonyme ne
   peut pas se distinguer à l'écran — jugé sans conséquence (le `customer_id` sous-jacent est, lui,
   exact). **À valider.**
2. **Acteur d'audit pour un device (`actor_user_id` NOT NULL, FK `users.id`,
   `models.py:715,731`).** Réglé par la spec #155 (`specs/borne-role-authentification-kiosque.md`) :
   chaque device est matérialisé par un compte de service dans `users` (rôle `KIOSK`) rattaché au
   salon via `salon_members` — l'option d'une table de credentials séparée y est explicitement
   écartée. `CUSTOMER_CREATED` fonctionne donc sans aucun changement d'`audit_logs` :
   `actor_user_id` reçoit l'id du compte device. Plus de point bloquant ; seule la cohérence à
   l'implémentation reste à vérifier.
3. **Nommage et propriété des permissions `KIOSK`.** Les noms canoniques sont fixés par la spec
   #155 (`specs/borne-role-authentification-kiosque.md`) : `CUSTOMER_LOOKUP_KIOSK` et
   `CUSTOMER_CREATE_WALKIN` pour #156, `QUEUE_TICKET_CREATE` pour #157 (cohérents avec le patron
   `<RESSOURCE>_<ACTION>`, `permissions.py:34-39`). La matrice étant figée
   par tests d'égalité stricte (`test_domain_permissions.py:53,111,150,173`), l'ajout du rôle
   `KIOSK` et de ses permissions doit être livré de façon **coordonnée** (#155 propriétaire ;
   ordre de merge à fixer, même problème que celui documenté par la spec #157). **Nommage
   tranché ; ordre de merge à coordonner.**
4. **Portée téléphone = salon de la borne (décision M7 n°6).** Justification : cohérent avec
   l'unicité par salon en base (`uq_customer_profiles_salon_phone`) et avec le cloisonnement §11.2
   (un numéro fiché ailleurs est un fait d'un autre salon) ; un client connu du salon B mais pas du
   salon A est simplement un **nouveau client de A** — comportement métier assumé (il re-saisit son
   nom une fois). **À valider.**
5. **Dérivation du prénom = premier token de `full_name`.** Exacte pour toute fiche créée par la
   borne (composition contrôlée « Prénom Nom ») ; **heuristique** pour les fiches historiques
   saisies par le gérant (un `full_name` « Koné Awa » afficherait « Koné »). Alternatives écartées :
   colonne `first_name` (migration + rétro-remplissage impossible à fiabiliser), afficher le nom
   complet (contraire au critère d'acceptation). Résidu accepté : l'affichage sert un salut et une
   confirmation visuelle, pas une identification légale. **À valider (avec l'option d'une consigne
   de saisie « Prénom Nom » côté dashboard gérant en documentation).**
6. **Recherche et création toujours en direct, sans mode dégradé (décision M7 n°9).** Justification
   technique : une identification ou une création en file locale (offline) créerait des doublons et
   des conflits d'unicité `(salon_id, phone)` à la resynchronisation ; l'écran « borne
   indisponible » (#159) est le comportement dégradé. Conséquence de contrat pour #156 : les deux
   endpoints doivent rester **rapides** (égalité indexée, budget §12.1) car ils sont sur le chemin
   critique du parcours borne. **À valider.**
7. **Seuils de limitation de débit.** Proposition de départ : 10 échecs / 5 min par clé
   (device + IP), verrou 10 min — plus permissif que la connexion (5/300 s/900 s,
   `login_rate_limiter_memory.py`) car l'erreur de saisie tactile est plus fréquente qu'une erreur
   de mot de passe, et la borne est physiquement surveillable. Les valeurs exactes sont un réglage
   produit/terrain à piloter sur les 2-3 salons pilotes (recommandation « Risque 5 » du PRD reprise
   par le jalon). **À ajuster en pilote.**
8. **Numérotation « US-00x » non autoritaire.** Le mapping de cette spec (étapes 4-5 du parcours
   §17.4, `prd-coiflink.md:1349-1362`) suit l'hypothèse de travail déjà posée par la spec #159
   (`borne-app-mobile-mode-kiosque.md:38-46`) ; aucune table de correspondance officielle n'existe
   dans le dépôt. **À confirmer par le porteur produit** (sans impact sur le contenu technique :
   les champs et validations mappés restent identiques quelle que soit la numérotation retenue).
9. **Téléphone partagé (compromis ADR-0026 décision 6).** L'unicité `(salon_id, phone)` interdit
   deux fiches pour un même numéro : à la borne, le second membre d'une famille partageant un
   téléphone retombera sur la fiche du premier (`200` + prénom d'un autre). L'échappatoire du
   dashboard (fiche sans téléphone) n'est **pas** offerte à la borne (le téléphone y est la clé).
   Comportement proposé pour M7 : la borne affiche le prénom trouvé avec un bouton « Ce n'est pas
   moi » qui oriente vers l'accueil humain (écran #159) — #156 n'ajoute aucun contournement
   d'unicité. **À valider comme limitation produit assumée du pilote.**
10. **Race création/lookup entre deux canaux.** Un gérant et la borne peuvent créer le même numéro
    simultanément : l'index unique tranche, le perdant reçoit `409`, et le parcours borne ré-exécute
    le lookup (contrat documenté pour #159). Couvert par le test e2e §6 — risque résiduel nul.

## Implementation Checklist

1. **Vérifier l'état de #155** (spec et/ou code livré) : forme du `Principal` device, garde de
   portée device→salon, existence d'une ligne `users` par device (question ouverte §2), nommage
   des permissions (§3). Trancher les questions ouvertes 1-9 avec le porteur produit.
2. **Lire** pour s'imprégner des patrons : `adapters/inbound/customers.py`,
   `application/customers.py`, `domain/customer.py`, `domain/phone.py`,
   `adapters/outbound/persistence/customer_repository.py`, `adapters/inbound/security.py`,
   `application/ports/login_rate_limiter.py` + son adapter mémoire, et les specs sœurs #157/#159.
3. **Domaine** : `walk_in_first_name`, `WalkInIdentity`, `WalkInCustomerCommand` (+ validation et
   composition « Prénom Nom ») dans `domain/customer.py` ; `TooManyKioskAttempts` dans
   `domain/errors.py` ; étendre `tests/test_domain_customer.py` (formats de saisie borne inclus).
4. **Port & dépôt** : `find_by_phone` sur `application/ports/customer_repository.py` (docstring
   §11.2 + forme canonique) et `SqlCustomerRepository` (lecture seule) ; `find_by_phone` sur le
   `FakeCustomerRepository` de `tests/conftest.py`.
5. **Limitation de débit** : port `KioskLookupRateLimiter` + adapter (mécanique de
   `login_rate_limiter_memory.py`, seuils kiosque, horloge injectable) + fake de test.
6. **Cas d'usage** : `application/kiosk_customers.py` (`IdentifyWalkInCustomer`,
   `CreateWalkInCustomer` — aucun import `users`, docstring anti-oracle) ;
   `tests/test_kiosk_customer_usecases.py` (normalisation avant dépôt, prénom seul, audit
   `metadata={}`, limiteur, cloisonnement).
7. **Permissions** (coordonné avec #155) : `CUSTOMER_LOOKUP_KIOSK`/`CUSTOMER_CREATE_WALKIN` dans
   `domain/permissions.py`, rôle `KIOSK` seul détenteur ; mise à jour de
   `tests/test_domain_permissions.py` (égalité stricte + négatifs sur les rôles existants).
8. **Adapter entrant** : `adapters/inbound/kiosk_customers.py` (deux routes `POST`, téléphone en
   corps, `extra="ignore"`, gardes portée device + permission, mapping
   `404`/`409`/`422`/`429 + Retry-After`, messages neutres) ; **ne pas** toucher
   `PUBLIC_ROUTE_PATHS`.
9. **Câblage** : `include_router` + assemblage du limiteur dans `main.py`, commentaire de garde
   dans le style existant.
10. **Tests API & e2e** : `tests/test_kiosk_customer_api.py` (projection minimale par assertions
    d'absence, RBAC négatif bidirectionnel, `429`) puis `tests/test_kiosk_customer_e2e.py`
    (canonisation croisée des canaux, isolation inter-salons, anti-oracle `users` §4, traçabilité,
    concurrence) — purge `notifications` avant `appointments`/`users`/`salons` au nettoyage.
11. **Documentation** : section `backend/README.md` ; transmettre à #155 le matériau de
    l'ADR-0041 (analyse anti-oracle, prénom seul, débit, risque résiduel) ; OpenAPI relue sur
    `/docs`.
12. **Vérification finale** : `scripts/test-gate.sh` au vert, `ruff check` propre ; relire la PR —
    aucun numéro de téléphone ni nom dans les logs/erreurs/audit, aucune route publique ajoutée,
    routes gérant intactes, **aucune signature IA** nulle part.
