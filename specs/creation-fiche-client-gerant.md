# Création d'une fiche client (gérant) (US-4.1)

> Spécification de planification pour l'issue GitHub **#28 — US-4.1 : Création d'une fiche client
> (gérant)** (`feature` · Must · Effort M · PRD §6 Épic 4 / §7.2 « Clients » / §9.5). **Dépend de #12**
> (RBAC deny-by-default) et ouvre le jalon **M4 — Clients, encaissement & journal de caisse**.
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 4, US-4.1) pose le besoin : **« en tant que gérant, je veux créer une fiche client
afin de suivre ses visites »**, avec pour spécification fonctionnelle **« nom, téléphone, genre
optionnel, notes internes »**. Le PRD §7.2 range la section **Clients** dans l'interface web gérant
(liste, recherche, création de fiche, historique, notes internes). Le critère d'acceptation de
l'issue #28 est :

- **Le gérant crée une fiche client rattachée à son salon ; isolation par salon (§11.2).**

C'est le **premier module « gestion clients »** du produit. Toute la chaîne du sprint 4 en dépend :
#29 (historique des visites d'un client), #32 (note client privée) et #49 (campagnes/messages aux
clients) portent tous « Dépend de #28 ».

État actuel du dépôt (après #12 → #27) :

- **Aucun code client n'existe.** Une recherche `customer` sur `backend/coiflink_api`,
  `web-dashboard/src` et `app-mobile/lib` ne remonte que trois choses : le modèle ORM
  `CustomerProfile` (`adapters/outbound/persistence/models.py:394`), la permission
  `Permission.CUSTOMER_MANAGE` (`domain/permissions.py:65`) et les tests de matrice qui la figent.
  **Aucun domaine, aucun port, aucun cas d'usage, aucun dépôt, aucune route, aucune page.**
- **La table `customer_profiles` est déjà au schéma mais n'a jamais été écrite.** Créée par la
  migration initiale `0001_schema_initial.py` (PRD §9.5), elle porte `id`, `salon_id` (FK `RESTRICT`,
  indexée), `user_id` **nullable** (« supporte les clients walk-in »), `full_name`, `phone`, `notes`,
  `last_visit_at`, `total_visits`, `created_at`, `updated_at`, plus un index unique partiel
  `uq_customer_profiles_salon_user` sur `(salon_id, user_id) WHERE user_id IS NOT NULL`. **Aucune
  ligne n'est écrite aujourd'hui** — aucun writer n'existe dans le code.
- **Il manque la colonne `gender`.** Ni le PRD §9.5, ni `models.py`, ni la migration `0001` ne
  portent de champ « genre ». L'issue #28 l'exige (« genre optionnel ») : **une migration est
  nécessaire** (la première depuis `0004_audit_logs`).
- **`CUSTOMER_MANAGE` existe dans la matrice §4.1 mais n'est câblée sur aucune route.** Elle est
  détenue par le seul `MANAGER` (`domain/permissions.py:117`) et explicitement **refusée** au
  `CLIENT`, au `HAIRDRESSER` et à l'`ADMIN` (tests `test_domain_permissions.py`). #28 est sa
  **première mise en service** — exactement comme #26 l'a fait pour `APPOINTMENT_READ_SALON`.
- **Côté web gérant, la section « Clients » est `coming-soon`.**
  `web-dashboard/src/domain/navigation/sections.ts` déclare l'entrée `clients`
  (`href: "/gerant/clients"`, `status: "coming-soon"`, catégorie `operations`) **sans page** sous
  `app/(gerant)/gerant/`.
- **Le socle est mûr.** Les patrons à réutiliser tels quels sont éprouvés par #15/#16/#17/#20/#26 :
  ressource **imbriquée sous `/salons/{salon_id}/…`** pour hériter de `require_salon_scope`
  (isolation §11.2), tranche hexagonale `domain/ → application/ (+ ports) → adapters/`,
  journalisation §11.4 via le port `AuditLog` **dans la même `Session`** que l'écriture métier, et
  côté web *Server Component → gateway HTTP (jeton lu du cookie `httpOnly`) → Route Handler BFF →
  mutation + `router.refresh()`*.

Le gap que #28 comble : **(1)** une **migration** ajoutant le genre optionnel (et l'unicité du
téléphone dans le salon) ; **(2)** une tranche backend complète **`/salons/{salon_id}/customers`**
câblant `CUSTOMER_MANAGE` + `require_salon_scope` ; **(3)** la page web gérant **`/gerant/clients`**
qui rend la section disponible.

## Goals

- **Créer une fiche client rattachée au salon.** `POST /salons/{salon_id}/customers` crée une ligne
  `customer_profiles` avec `full_name` (**requis**), `phone` (optionnel, **normalisé E.164**),
  `gender` (optionnel, **énumération fermée**) et `notes` (optionnel, **internes**). Réponse `201`.
- **`salon_id` imposé par la portée, jamais par le corps.** Comme pour les prestations (#17) et les
  salons (#15), le `salon_id` provient du **chemin validé** par `require_salon_scope` ; un champ
  privilégié présent dans le corps (`salon_id`, `id`, `user_id`, `total_visits`, `last_visit_at`) est
  **ignoré** (`extra="ignore"`).
- **Isolation par salon (§11.2) — critère d'acceptation.** La route est salon-scopée
  (`require_salon_scope` → `403` **générique** hors périmètre, sans oracle d'existence) **et** le
  dépôt refiltre `salon_id` en SQL sur toute lecture/écriture d'une fiche existante (défense en
  profondeur, miroir de `SqlServiceRepository`). Un gérant ne voit **que** les fiches de son salon.
- **Première mise en service de `CUSTOMER_MANAGE`.** Les routes câblent la permission §4.1 déjà
  présente dans la matrice — **sans** modifier `ROLE_PERMISSIONS` (aucun élargissement de droits).
- **Lectures minimales pour rendre la création observable.** `GET /salons/{salon_id}/customers`
  (liste paginée du salon) et `GET /salons/{salon_id}/customers/{customer_id}` (fiche) — le strict
  nécessaire pour que la page « Clients » affiche ce qui vient d'être créé et pour que #29 dispose
  d'un point d'entrée. Voir *Risks and Open Questions* §4 (décision de périmètre à confirmer).
- **Refus des doublons de téléphone dans le salon.** Un téléphone déjà présent dans **le même salon**
  est refusé par `409` (`CustomerAlreadyExists`), garanti par un **index unique partiel** base — deux
  fiches pour le même numéro fausseraient l'historique de visites (#29) et les statistiques (#31).
- **Journalisation §11.4 / §11.3.** Chaque création enregistre une `AuditEntry` **neutre**
  (`CUSTOMER_CREATED`, entité `customer`) dans la **même unité de travail** que l'écriture : la
  création d'une fiche est une **collecte de données personnelles** (§11.3 « journalisation des accès
  sensibles »). Aucun nom, téléphone, genre ni note n'entre dans `metadata`.
- **Aucune PII journalisée, aucune route publique.** Les chemins `/salons/{salon_id}/customers…` ne
  sont **jamais** ajoutés à `PUBLIC_ROUTE_PATHS` ; ni les logs applicatifs, ni les messages d'erreur,
  ni le journal d'audit ne portent de nom, téléphone ou note.
- **Page web gérant `/gerant/clients`.** Formulaire de création + liste des fiches du salon, la
  section passant de `coming-soon` à `available` dans `navigation/sections.ts`. Le jeton d'accès
  reste lu **côté serveur** depuis le cookie `httpOnly` (invariant #14) — jamais exposé au
  navigateur, jamais journalisé.
- **Couverture de tests.** Backend : domaine (validation nom/téléphone/genre/notes), cas d'usage
  (portée, audit, doublon), API (`201`/`401`/`403`/`404`/`409`/`422`), e2e PostgreSQL (isolation
  inter-salons, traçabilité, absence de PII dans l'audit), round-trip Alembic. Web : domaine de
  validation, gateway HTTP, Route Handlers BFF, navigation.

## Non-Goals

- **Historique des visites d'un client (US-4.2, #29).** Les colonnes `last_visit_at` et
  `total_visits` existent au schéma et sont initialisées à leurs **défauts** (`NULL` / `0`) ; #28 ne
  les calcule ni ne les met à jour, et n'agrège **aucun** rendez-vous, prestation ou montant.
- **Modification / suppression d'une fiche.** L'édition de la **note privée** est explicitement
  l'objet de **US-4.5 (#32, `Could`)**. #28 livre la **création** (+ lecture) ; ni `PUT`, ni `PATCH`,
  ni `DELETE` ne sont ajoutés.
- **Statistiques par client (US-4.3, #31)** et **historique côté mobile (US-4.4, #30)** : hors
  périmètre, dépendent de #29.
- **Rattachement d'une fiche à un compte utilisateur (`user_id`).** #28 crée des fiches
  **`user_id = NULL`** (walk-in). Un rattachement automatique « par téléphone » est **écarté pour
  raison de sécurité** : interroger `users` par numéro transformerait la route en **oracle
  d'existence de compte** (§11.1/§11.3). Le rattachement explicite reste une évolution ultérieure
  (l'index unique partiel `uq_customer_profiles_salon_user` est déjà au schéma pour l'accueillir).
- **Recherche plein texte / filtres avancés sur la liste.** La liste est **paginée et triée**
  (`limit`/`offset`, plus récentes d'abord) ; la « Recherche » du PRD §7.2 est un suivi (voir *Open
  Questions* §7).
- **Import/export de fichier clients, campagnes et messages (#49), effacement RGPD-like / droit à
  l'oubli.** Hors périmètre MVP ; à traiter au durcissement (M6, #52).
- **Chiffrement applicatif au repos des notes.** Le PRD §11.3 le mentionne « si nécessaire » ; la
  décision est **documentée mais différée** (voir *Security & Privacy* et *Open Questions* §6).
- **Application mobile (Flutter).** US-4.1 est un parcours **gérant** (web). Le paquet `app-mobile/`
  n'est **pas** touché.
- **Modification de la matrice de permissions §4.1.** `CUSTOMER_MANAGE` existe déjà et est détenue
  par le seul `MANAGER` : #28 la **câble**, il ne l'élargit pas (l'`ADMIN` **n'a pas** ce droit —
  supervision ≠ exploitation, ADR-0015).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Journal d'audit | Table `audit_logs` + port `AuditLog`, entrées **neutres** | [0019](../docs/adr/0019-journalisation-audit-et-prestations.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0025** (annulation client) : le prochain numéro libre est
**ADR-0026**.

### Backend — patrons à réutiliser tels quels

- **Tranche « ressource de salon » (#17, prestations)** — le gabarit le plus proche de #28 :
  `domain/service.py` (validation pure + `ServiceToCreate`/`Service`) → `application/ports/
  service_repository.py` (`Protocol`) → `application/services.py` (cas d'usage + audit) →
  `adapters/outbound/persistence/service_repository.py` (SQLAlchemy) → `adapters/inbound/services.py`
  (router `prefix="/salons"`, routes `"/{salon_id}/services"`).
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` sur chaque route ; `403` **générique et constant** (`"Accès refusé."`) pour un
  rôle insuffisant **comme** pour un accès inter-salons ; l'invariant deny-by-default est vérifié
  mécaniquement par `unprotected_routes(app)` (test `test_security_guards.py`) — **une route ajoutée
  sans garde fait échouer les tests**.
- **Journalisation §11.4** : port `application/ports/audit_log.py`, entrée `domain/audit.py::AuditEntry`
  (`action`, `actor_user_id`, `salon_id`, `entity_type`, `entity_id`, `metadata`), adapter
  `SqlAuditLog` ; `get_audit_log` et le dépôt métier partagent la **même** `Session` (FastAPI met
  `get_session` en cache par requête) → commit/rollback atomique. `ENTITY_TYPE_SERVICE`,
  `ENTITY_TYPE_SALON`, `ENTITY_TYPE_APPOINTMENT` sont déjà déclarés.
- **Écritures `flush()` sans `commit()`** : le commit est piloté par `get_session` (cf.
  `SqlServiceRepository`), condition de l'atomicité mutation + audit.
- **Téléphone canonique** : `domain/phone.py::normalize_phone` (E.164, indicatif par défaut `+225`,
  idempotent, lève `InvalidPhone`). Déjà utilisé par l'inscription (#8/#9) — **à réutiliser** pour le
  téléphone d'une fiche client.
- **Nom** : `domain/user.py::validate_name` (trim, non vide, ≤ `NAME_MAX_LENGTH`) — patron à
  décliner en `validate_customer_name` (erreur **distincte**, mappée distinctement, comme
  `validate_service_name` l'est de `validate_salon_name`).
- **Énumérations** : `domain/enums.py` (héritent de `str`), `models.enum_check(column, enum_cls,
  name=...)` **dérive la contrainte `CHECK` SQL de l'énumération du domaine** — pas de divergence
  Python ↔ SQL, et pas de type `ENUM` PostgreSQL (évolutif sans `ALTER TYPE`).
- **Refus de doublon** : patron `EmployeeAlreadyInSalon` (#13) → `409` sur unicité
  `(salon_id, user_id)`.
- **Tests** : fakes en mémoire dans `tests/conftest.py` (un par port : `FakeServiceRepository`,
  `FakeAuditLog`, `FakeSalonScopeRepository`…) + fixtures ; tests d'API via `TestClient` et
  `app.dependency_overrides` ; **tests e2e** adossés à un vrai PostgreSQL, sautés si `DATABASE_URL`
  est absent, avec une **plage de numéros de téléphone réservée** et nettoyage avant/après.

### Modèle de données pertinent (schéma #3, `models.py:394`)

```python
class CustomerProfile(Base):                    # table customer_profiles
    id, salon_id (FK salons RESTRICT, indexée), user_id (FK users RESTRICT, NULLABLE),
    full_name String(255) NOT NULL, phone String(32) NULL, notes Text NULL,
    last_visit_at timestamptz NULL, total_visits Integer NOT NULL DEFAULT 0,
    created_at, updated_at
    # CHECK total_visits >= 0
    # UNIQUE partiel (salon_id, user_id) WHERE user_id IS NOT NULL
    # INDEX (salon_id)
```

**Manque `gender`** → migration `0005` (tête actuelle : `0004_audit_logs`). La table étant **vide en
pratique** (aucun writer dans le code), l'ajout d'une colonne *nullable* et d'un index unique partiel
est **sans risque de rupture** sur les données existantes.

### Web gérant — patrons à réutiliser (#14 → #26)

- `app/(gerant)/gerant/<section>/page.tsx` = **Server Component + composition root** : lit le cookie
  (`createCookieSessionStore().read()`), appelle les gateways HTTP côté serveur, rend l'UI.
- `src/adapters/api/http-*-gateway.ts` : `fetch` vers le backend avec `Authorization: Bearer`,
  résultat en **union discriminée** (`{ok:true,…} | {ok:false, reason:"forbidden"|"unauthenticated"|
  "invalid"|"not-found"|…}`) — jamais d'exception qui remonterait un détail réseau à l'UI.
- `app/api/salons/[id]/…/route.ts` : **Route Handlers BFF** qui revalident le corps (parité domaine),
  lisent le jeton du cookie et proxifient ; messages d'erreur **neutres** en français.
- Formulaires client-side + `router.refresh()` après mutation (cf. `service-form.tsx` /
  `service-list.tsx`).
- `src/domain/navigation/sections.ts` : ajouter/activer une section = changer `status` + créer la page.

### Contraintes transverses documentées

- **PRD §11.2** : « un gérant ne peut voir que les données de son salon ».
- **PRD §11.3** : collecte **minimale**, consentement, journalisation des accès sensibles,
  sauvegardes sécurisées, chiffrement au repos « si nécessaire ».
- **PRD §11.4** : journalisation des actions importantes (entrées **neutres**, ADR-0019).
- **PRD §12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI applicative
  `ci.yml` (ruff, pytest, **round-trip Alembic contre PostgreSQL 16**, build, lint/test/build web).

## Proposed Implementation

### (A) Migration `0005` — genre optionnel & unicité du téléphone dans le salon

Nouveau fichier `backend/migrations/versions/0005_customer_gender.py` (`revision = "0005"`,
`down_revision = "0004"`), **reflet versionné** du modèle ORM mis à jour :

1. `op.add_column("customer_profiles", sa.Column("gender", sa.String(length=16), nullable=True))`.
2. `op.create_check_constraint("ck_customer_profiles_gender", "customer_profiles",
   "gender IN ('FEMALE','MALE','OTHER')")` — valeurs **dérivées de l'énumération de domaine**
   `Gender` (cf. `models.enum_check`) ; `NULL` reste autorisé (genre **non renseigné**).
3. Index unique **partiel** :
   ```python
   op.create_index(
       "uq_customer_profiles_salon_phone",
       "customer_profiles",
       ["salon_id", "phone"],
       unique=True,
       postgresql_where=sa.text("phone IS NOT NULL"),
   )
   ```
   Miroir exact de `uq_customer_profiles_salon_user` déjà présent. C'est la **garantie base** du refus
   de doublon (le pré-contrôle applicatif ne suffit pas en concurrence).
4. `downgrade()` : `drop_index` → `drop_constraint` → `drop_column` (réversion complète, exigée par
   le round-trip Alembic de la CI).

Mise à jour miroir de `models.py::CustomerProfile` : colonne `gender: Mapped[str | None] =
mapped_column(String(16), nullable=True)`, `enum_check("gender", enums.Gender, name="gender")` et le
nouvel `Index(..., unique=True, postgresql_where=text("phone IS NOT NULL"))` dans `__table_args__`.

### (B) Backend — domaine

**`domain/enums.py`** — nouvelle énumération fermée :

```python
@unique
class Gender(_StrEnum):
    """Genre d'une fiche client (US-4.1, #28) — optionnel : `NULL` = non renseigné."""
    FEMALE = "FEMALE"
    MALE = "MALE"
    OTHER = "OTHER"
```

Le PRD ne fixe pas de liste : trois valeurs neutres et l'absence (`NULL`) couvrent le besoin
(« optionnel »). Aucune valeur `UNSPECIFIED` — l'absence est portée par `NULL` (une seule
représentation du « non renseigné »). Ajouter `Gender` à `__all__`.

**`domain/errors.py`** — nouvelles erreurs de domaine (docstrings référençant US-4.1, #28) :
`InvalidCustomerName`, `InvalidCustomerGender`, `InvalidCustomerNotes`, `CustomerNotFound`,
`CustomerAlreadyExists`.

**`domain/customer.py`** (nouveau, **pur** — ni FastAPI ni SQLAlchemy) :

- Bornes : `CUSTOMER_NAME_MAX_LENGTH = 255` (aligné `String(255)`), `NOTES_MAX_LENGTH = 2000`
  (la colonne est `TEXT` : la borne est **applicative**, pour ne pas accepter un corps non borné).
- `validate_customer_name(name) -> str` : trim, non vide, ≤ borne → `InvalidCustomerName`.
- `normalize_customer_phone(phone: str | None) -> str | None` : `None`/vide → `None` (téléphone
  **optionnel**, cf. *Open Questions* §1) ; sinon `normalize_phone(...)` (E.164) qui lève
  `InvalidPhone`. La forme canonique est ce qui rend l'unicité `(salon_id, phone)` **effective**
  (sans elle, `0700000000` et `+2250700000000` créeraient deux fiches).
- `normalize_gender(value: str | None) -> str | None` : `None`/vide → `None` ; sinon valeur
  **exactement** membre de `Gender` (comparaison sur la valeur, sans deviner) → `InvalidCustomerGender`.
- `normalize_notes(notes: str | None) -> str | None` : trim, vide → `None`, ≤ `NOTES_MAX_LENGTH` →
  `InvalidCustomerNotes`.
- `@dataclass(frozen=True) CustomerToCreate` : `salon_id`, `full_name`, `phone`, `gender`, `notes`
  — **pas** de `user_id`, `total_visits`, `last_visit_at` (défauts base), **pas** d'`id`.
- `@dataclass(frozen=True) Customer` : `id`, `salon_id`, `full_name`, `phone`, `gender`, `notes`,
  `last_visit_at`, `total_visits`, `created_at`, `updated_at`.

**`domain/audit.py`** : `ENTITY_TYPE_CUSTOMER = "customer"` et `AuditAction.CUSTOMER_CREATED`
(commentaire : §11.3 « journalisation des accès sensibles » — collecte de données personnelles).

### (C) Backend — port & adapter de persistance

**`application/ports/customer_repository.py`** (`Protocol`, docstring rappelant l'isolation §11.2) :

```python
def create(self, customer: CustomerToCreate) -> Customer: ...
def find_by_id(self, salon_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None: ...
def list_for_salon(self, salon_id, *, limit: int, offset: int) -> tuple[Customer, ...]: ...
def count_for_salon(self, salon_id) -> int: ...
def phone_exists(self, salon_id: uuid.UUID, phone: str) -> bool: ...
```

Toutes les méthodes portant sur une fiche existante prennent `salon_id` **en plus** de l'identifiant
et filtrent sur le couple `(salon_id, id)` : une fiche d'un autre salon est **indiscernable d'une
fiche inexistante**.

**`adapters/outbound/persistence/customer_repository.py`** — `SqlCustomerRepository` :

- `create` : `session.add(models.CustomerProfile(...))` → `flush()` → `refresh()` → entité de
  domaine. **`flush()` sans `commit()`** (atomicité avec l'audit). La violation de
  `uq_customer_profiles_salon_phone` (`IntegrityError`) est **retraduite** en
  `CustomerAlreadyExists` (jamais de détail SQLAlchemy remonté) — c'est le filet **concurrent** du
  pré-contrôle applicatif.
- `find_by_id` / `list_for_salon` / `count_for_salon` : `select(...).where(salon_id == ...)`, tri
  `created_at DESC` (patron `list_for_salon` des prestations), `limit`/`offset` appliqués en SQL.
- `phone_exists` : `select(1).where(salon_id == ..., phone == ...)`.
- `_to_domain(row)` privé, comme `SqlServiceRepository`.

### (D) Backend — cas d'usage

**`application/customers.py`** (ne dépend que des ports `CustomerRepository` et `AuditLog`) :

- `@dataclass(frozen=True) CustomerCommand` : `full_name`, `phone=None`, `gender=None`, `notes=None`
  — **ni** `salon_id` **ni** `id` (le `salon_id` vient de la portée).
- `_validate(command)` : nom → téléphone → genre → notes, **ordre stable** (messages d'erreur
  déterministes), **avant toute écriture** (aucun appel au dépôt si un champ est invalide).
- `CreateCustomer.execute(salon_id, command, *, actor_user_id) -> Customer` :
  1. validation domaine ;
  2. si `phone is not None` et `repository.phone_exists(salon_id, phone)` → `CustomerAlreadyExists`
     (message neutre, sans rappeler le numéro) ;
  3. `repository.create(CustomerToCreate(salon_id=salon_id, ...))` ;
  4. `audit_log.record(AuditEntry(action=CUSTOMER_CREATED, actor_user_id=..., salon_id=...,
     entity_type=ENTITY_TYPE_CUSTOMER, entity_id=customer.id, metadata={}))` — `metadata` **vide** :
     aucun nom, téléphone, genre ni note (invariant §11.3/§11.4).
- `ListSalonCustomers.execute(salon_id, *, limit, offset) -> tuple[tuple[Customer, ...], int]`
  (page + total ; lecture → **pas d'audit**).
- `GetCustomer.execute(salon_id, customer_id) -> Customer` → `CustomerNotFound` si absent (lecture →
  pas d'audit).

### (E) Backend — adapter entrant (HTTP)

**`adapters/inbound/customers.py`** — `router = APIRouter(prefix="/salons", tags=["customers"])`,
calqué sur `services.py` :

- Schémas Pydantic documentés (OpenAPI) : `CreateCustomerRequest` (`model_config =
  ConfigDict(extra="ignore")` ; `full_name: str = Field(min_length=1, max_length=255)`,
  `phone: str | None = None`, `gender: str | None = None`, `notes: str | None = None`),
  `CustomerResponse`, `CustomerPageResponse` (`items`, `total`, `limit`, `offset`).
- Chaque route déclare **`require_salon_scope`** *et*
  **`require_permission(Permission.CUSTOMER_MANAGE)`** (le `principal` retourné fournit
  `actor_user_id` — **jamais** lu du corps).
- Traduction des erreurs de domaine :
  `InvalidCustomerName | InvalidPhone | InvalidCustomerGender | InvalidCustomerNotes` → **422**
  (`detail=str(exc)`, messages métier sans PII) ; `CustomerAlreadyExists` → **409** ;
  `CustomerNotFound` → **404** (*uniquement* après validation de portée).
- Pagination : `limit: int = Query(default=50, ge=1, le=200)`, `offset: int = Query(default=0, ge=0)`.
- **Aucun chemin n'est ajouté à `PUBLIC_ROUTE_PATHS`.**

**`main.py`** : `app.include_router(customers_router)` avec un commentaire de câblage dans le style
existant (permission, portée, audit).

### (F) Web gérant — section « Clients »

1. **Domaine TypeScript pur** — `src/domain/customer/customer.ts` : types `Customer`,
   `CustomerDraft` ; `validateCustomer(draft)` (parité avec le domaine backend : nom requis/borné,
   notes bornées, genre ∈ `GENDER_VALUES`, téléphone non vide si fourni) ; `GENDER_OPTIONS`
   (libellés **français** : « Femme », « Homme », « Autre », « Non renseigné » → `null`).
2. **Port & gateway** — `src/application/ports/customer-gateway.ts` +
   `src/adapters/api/http-customer-gateway.ts` (`list(salonId, {limit, offset})`,
   `create(salonId, draft)`, `get(salonId, customerId)`), résultats en union discriminée avec
   `reason: "invalid" | "duplicate" | "forbidden" | "unauthenticated" | "not-found" | "unavailable"`.
3. **BFF** — `app/api/salons/[id]/customers/route.ts` (`GET` liste, `POST` création) : revalidation
   du corps, lecture du jeton depuis le cookie `httpOnly`, messages neutres
   (`409` → « Une fiche existe déjà pour ce numéro dans ce salon. »).
4. **Page** — `app/(gerant)/gerant/clients/page.tsx` (Server Component) : charge le salon du gérant
   (`http-salon-gateway.list()`), puis ses fiches ; sans salon → invite à en créer un
   (**Paramètres**, #15), comme la page Prestations.
5. **UI** — `src/adapters/ui/customer-form.tsx` (nom, téléphone, genre `<select>`, notes internes,
   avec la mention explicite « visible uniquement par le salon ») et
   `src/adapters/ui/customer-list.tsx` (liste + états vide/erreur) ; après création,
   `router.refresh()`.
6. **Navigation** — `src/domain/navigation/sections.ts` : `clients` passe à `status: "available"`.

### (G) Documentation & ADR

- **ADR-0026 — « Fiche client : portée salon, genre optionnel et unicité du téléphone »** :
  contexte (US-4.1, table `customer_profiles` inutilisée, `CUSTOMER_MANAGE` non câblée), décisions
  (fiche **walk-in** `user_id = NULL` ; genre = énumération fermée nullable ; unicité
  `(salon_id, phone)` partielle ; audit `CUSTOMER_CREATED` au titre de §11.3 ; **pas** de recherche
  `users` par téléphone — anti-oracle), conséquences et suivis (rattachement à un compte, chiffrement
  des notes, recherche/pagination avancée). Ajouter l'entrée à `docs/adr/README.md`.
- `backend/README.md` : nouvelle section « Clients — fiche client (US-4.1, #28) » avec le tableau
  routes / permission / réponses / audit (gabarit de la section « Gestion des prestations »).
- `web-dashboard/README.md` : ligne `/gerant/clients` dans le tableau des routes + sous-section
  « Clients — fiches du salon (#28) ».
- `README.md` (racine) : phrase de statut dans §6 (M4 amorcé : création de fiche client) et, si
  besoin, mention du jalon M4 dans la roadmap.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/domain/customer.py` | entités + validation pures (nom, téléphone, genre, notes) |
| `coiflink_api/application/ports/customer_repository.py` | port `Protocol` de persistance |
| `coiflink_api/application/customers.py` | cas d'usage `CreateCustomer`, `ListSalonCustomers`, `GetCustomer` |
| `coiflink_api/adapters/outbound/persistence/customer_repository.py` | `SqlCustomerRepository` |
| `coiflink_api/adapters/inbound/customers.py` | router `/salons/{salon_id}/customers` |
| `migrations/versions/0005_customer_gender.py` | colonne `gender` + `CHECK` + index unique partiel |
| `tests/test_domain_customer.py`, `tests/test_customer_usecases.py`, `tests/test_customer_api.py`, `tests/test_customer_e2e.py` | tests |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/enums.py` | énumération `Gender` (+ `__all__`) |
| `coiflink_api/domain/errors.py` | `InvalidCustomerName`, `InvalidCustomerGender`, `InvalidCustomerNotes`, `CustomerNotFound`, `CustomerAlreadyExists` |
| `coiflink_api/domain/audit.py` | `ENTITY_TYPE_CUSTOMER`, `AuditAction.CUSTOMER_CREATED` |
| `coiflink_api/adapters/outbound/persistence/models.py` | `CustomerProfile.gender` + `enum_check` + index unique partiel `(salon_id, phone)` |
| `coiflink_api/main.py` | `include_router(customers_router)` + commentaire de câblage |
| `backend/README.md` | section « Clients » |
| `tests/conftest.py` | `FakeCustomerRepository` + fixture `fake_customer_repository` |
| `tests/test_domain_audit.py` | nouvelle action/entité couvertes |

### Web (`web-dashboard/`)

À créer : `src/domain/customer/customer.ts`, `src/application/ports/customer-gateway.ts`,
`src/adapters/api/http-customer-gateway.ts`, `app/api/salons/[id]/customers/route.ts`,
`app/(gerant)/gerant/clients/page.tsx`, `src/adapters/ui/customer-form.tsx`,
`src/adapters/ui/customer-list.tsx`, `test/customer-domain.test.ts`,
`test/http-customer-gateway.test.ts`, `test/customers-bff.test.ts`.
À modifier : `src/domain/navigation/sections.ts` (`clients` → `available`),
`test/navigation-sections.test.ts`, `web-dashboard/README.md`.

### Documentation (racine)

`docs/adr/0026-fiche-client-portee-salon.md` (nouveau), `docs/adr/README.md`, `README.md`.

### À lire (sans modifier) pour rester fidèle aux patrons

`adapters/inbound/services.py`, `application/services.py`, `domain/service.py`,
`adapters/outbound/persistence/service_repository.py`, `adapters/inbound/security.py`,
`domain/permissions.py`, `domain/phone.py`, `migrations/versions/0004_audit_logs.py`,
`web-dashboard/app/(gerant)/gerant/prestations/page.tsx`,
`web-dashboard/app/api/salons/[id]/services/route.ts`,
`web-dashboard/src/adapters/api/http-service-gateway.ts`.

## API / Interface Changes

Trois **nouveaux** endpoints REST, tous **protégés** (`CUSTOMER_MANAGE` + portée salon) ; aucune
route existante n'est modifiée ; aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/customers` | `CUSTOMER_MANAGE` + portée | `201` fiche · `401` · `403` · `409` doublon · `422` champ invalide |
| `GET` | `/salons/{salon_id}/customers?limit=&offset=` | `CUSTOMER_MANAGE` + portée | `200` page · `401` · `403` |
| `GET` | `/salons/{salon_id}/customers/{customer_id}` | `CUSTOMER_MANAGE` + portée | `200` fiche · `401` · `403` · `404` |

```jsonc
// POST /salons/{salon_id}/customers — corps
{
  "full_name": "Awa Koné",
  "phone": "0700000000",        // optionnel ; normalisé en +2250700000000
  "gender": "FEMALE",           // optionnel ; FEMALE | MALE | OTHER ; null = non renseigné
  "notes": "Préfère le samedi matin."   // optionnel, interne au salon, ≤ 2000 caractères
}

// 201 — réponse (identique pour les GET)
{
  "id": "…uuid…",
  "salon_id": "…uuid…",
  "full_name": "Awa Koné",
  "phone": "+2250700000000",
  "gender": "FEMALE",
  "notes": "Préfère le samedi matin.",
  "last_visit_at": null,        // défaut ; alimenté par #29
  "total_visits": 0,            // défaut ; alimenté par #29
  "created_at": "2026-07-24T09:00:00Z",
  "updated_at": "2026-07-24T09:00:00Z"
}

// 200 — GET liste
{ "items": [ /* fiches */ ], "total": 12, "limit": 50, "offset": 0 }
```

- **`user_id` n'est pas exposé** : il vaut toujours `NULL` dans ce périmètre et son exposition
  renseignerait sur l'existence d'un compte (voir *Security & Privacy*).
- Champs privilégiés du corps (`salon_id`, `id`, `user_id`, `total_visits`, `last_visit_at`) :
  **ignorés** (`extra="ignore"`).

**Interfaces web (BFF, internes à Next.js)** : `GET|POST /api/salons/[id]/customers`. **Aucune**
modification de CLI, de variable d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**Oui** — une migration Alembic (`0005`, `down_revision = "0004"`), reflet du modèle ORM :

1. `customer_profiles.gender` : `VARCHAR(16) NULL` (`NULL` = non renseigné).
2. `CHECK ck_customer_profiles_gender` : `gender IN ('FEMALE','MALE','OTHER')`, **dérivé** de
   `domain.enums.Gender` via `models.enum_check` (jamais un type `ENUM` PostgreSQL — ADR-0009 /
   conventions `models.py`).
3. Index unique **partiel** `uq_customer_profiles_salon_phone` sur `(salon_id, phone)
   WHERE phone IS NOT NULL` — garantit **en base** l'unicité du téléphone **dans un salon** (deux
   salons peuvent avoir une fiche pour le même numéro : les fiches sont **cloisonnées par salon**,
   §11.2).
4. `downgrade()` symétrique (index → contrainte → colonne), exigé par le **round-trip Alembic** de la
   CI.

Colonnes **inchangées** : `user_id` (reste `NULL` en #28), `last_visit_at`, `total_visits` (défauts
`NULL` / `0`, alimentés par #29). Aucun changement de format de sérialisation ailleurs ; aucune
migration de données (la table est vide en pratique).

## Security & Privacy Considerations

**Ce module manipule des données personnelles (PII) — c'est sa principale sensibilité.** Nom,
téléphone, genre et notes internes d'un client sont couverts par le **PRD §11.3** (collecte minimale,
consentement, journalisation des accès sensibles, sauvegardes sécurisées).

- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur chaque route (portée
  **chargée en base**, jamais déduite du corps) **et** filtre `salon_id` en SQL dans le dépôt. Un
  accès inter-salons renvoie le **`403` générique et constant** (`"Accès refusé."`), identique à
  celui d'un rôle insuffisant : **aucun oracle d'existence** d'une fiche ou d'un salon. `404` n'est
  renvoyé qu'**après** validation de portée (fiche absente **du salon du gérant**).
- **Deny-by-default (ADR-0015).** Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ; l'invariant est
  vérifié mécaniquement (`unprotected_routes(app)`). Une fiche client ne doit **jamais** être
  lisible sans jeton, ni apparaître dans le catalogue public (#18/#19) ou la disponibilité (#21).
- **Permission `CUSTOMER_MANAGE` seule (§4.1).** Détenue par le seul `MANAGER`. Le `HAIRDRESSER`
  **ne lit pas** les fiches clients (il n'a que son planning) et l'`ADMIN` non plus (supervision ≠
  exploitation, ADR-0015). La matrice `ROLE_PERMISSIONS` **n'est pas modifiée**.
- **Pas d'oracle d'existence de compte.** Le cas d'usage **n'interroge jamais** la table `users` par
  téléphone (ni pour rattacher `user_id`, ni pour suggérer un compte) : un gérant pourrait sinon
  tester des numéros arbitraires et apprendre qui possède un compte CoifLink. `user_id` reste `NULL`
  et **n'est pas exposé** dans les réponses.
- **Aucune PII dans le journal d'audit (§11.4, ADR-0019).** `CUSTOMER_CREATED` porte
  `actor_user_id` (UUID opaque), `salon_id`, `entity_type="customer"`, `entity_id` et
  **`metadata = {}`** — jamais le nom, le téléphone, le genre ni la note. Un test l'exige
  explicitement (parité avec `test_service_e2e.py`).
- **Aucune PII ni secret dans les logs.** Aucun `print`/`logger` ne reçoit le corps de requête, le
  téléphone, le nom ou les notes ; les messages `4xx` restent **métier et neutres** (« Une fiche
  existe déjà pour ce numéro dans ce salon. » sans rappeler le numéro).
- **Notes internes = données potentiellement sensibles.** Le PRD (US-4.5) cite « allergies » : les
  notes peuvent contenir des informations relevant de la santé. En conséquence : elles ne sont
  exposées **qu'aux** routes `CUSTOMER_MANAGE` du salon, **jamais** au client ni à l'application
  mobile, jamais journalisées, et l'UI web affiche la mention « visible uniquement par le salon ». Le
  **chiffrement applicatif au repos** (§11.3 « si nécessaire ») est **différé et documenté** dans
  l'ADR-0026 comme suivi (le chiffrement disque/sauvegardes de la plateforme reste couvert par
  ADR-0011).
- **Collecte minimale (§11.3).** Seuls les quatre champs de l'issue sont saisissables ; le genre
  reste **optionnel** et n'est **jamais déduit** du prénom ou d'une autre donnée. Aucun champ
  supplémentaire (date de naissance, adresse, e-mail) n'est ajouté.
- **Consentement (§11.3).** Une fiche walk-in est créée **par le gérant**, hors présence de
  l'application cliente : le recueil du consentement est un **processus métier** hors code au MVP —
  à mentionner dans l'ADR-0026 et à traiter au durcissement (#52). *Aucune fonctionnalité de
  suppression/effacement n'est promise par cette issue.*
- **Bornes d'entrée.** `full_name` ≤ 255, `notes` ≤ 2000, `phone` E.164 (≤ 15 chiffres), `gender`
  ∈ énumération fermée ; `limit` ≤ 200 : pas de stockage ni de réponse non bornés (budget §12.1).
- **Jeton jamais exposé côté web (#14).** La page et les Route Handlers lisent le cookie `httpOnly`
  **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.
- **Intégrité concurrente.** Le refus de doublon repose **in fine** sur l'index unique base : un
  pré-contrôle applicatif seul serait sujet à une course (deux requêtes simultanées) — l'
  `IntegrityError` est retraduite en `409`.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_domain_customer.py`** : `validate_customer_name` (vide/blanc/> 255/trim) ;
  `normalize_customer_phone` (`None`/vide → `None` ; `0700000000` → `+2250700000000` ;
  idempotence ; invalide → `InvalidPhone`) ; `normalize_gender` (valeurs valides, `None`/vide →
  `None`, valeur inconnue et casse différente → `InvalidCustomerGender`) ; `normalize_notes`
  (trim, vide → `None`, > 2000 → `InvalidCustomerNotes`).
- **`tests/test_customer_usecases.py`** (fakes de `conftest.py`) :
  - le `salon_id` persisté provient de l'**argument de portée**, jamais de la commande ;
  - `CUSTOMER_CREATED` est enregistrée **une fois**, avec le bon `actor_user_id`, `salon_id`,
    `entity_type`/`entity_id`, et **`metadata == {}`** (aucune PII) ;
  - validation invalide → **aucune** écriture **et aucune** entrée d'audit ;
  - téléphone déjà présent dans le salon → `CustomerAlreadyExists`, **sans** écriture ni audit ;
  - même téléphone dans **un autre salon** → accepté (cloisonnement §11.2) ;
  - `GetCustomer` d'un id d'un autre salon → `CustomerNotFound` ;
  - `ListSalonCustomers` : ne renvoie que les fiches du salon, respecte `limit`/`offset` et le total.
- **`tests/test_domain_audit.py`** : `CUSTOMER_CREATED` / `ENTITY_TYPE_CUSTOMER` présentes et
  cohérentes.
- **`tests/test_domain_permissions.py`** : inchangé (vérifie déjà que seul le `MANAGER` détient
  `CUSTOMER_MANAGE`) — s'assurer qu'aucune modification n'est nécessaire.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_customer_api.py`** : `201` + corps attendu (téléphone normalisé, `total_visits = 0`,
  `last_visit_at = null`, **pas de `user_id`**) ; corps portant `salon_id`/`user_id`/`total_visits`
  → **ignorés** ; `422` par champ invalide (nom, téléphone, genre, notes) ; `409` doublon ; `404`
  fiche d'un autre salon ; `403` hors portée / rôle non `MANAGER` (message **constant**) ; `401` sans
  jeton sur les trois routes ; bornes de `limit`/`offset`.
- **`tests/test_security_guards.py`** : l'invariant `unprotected_routes(app) == []` couvre
  automatiquement les nouvelles routes ; vérifier explicitement qu'**aucun** chemin `customers`
  n'entre dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_customer_e2e.py`** (patron `test_service_e2e.py`, plage de téléphones réservée,
  nettoyage avant/après) :
  1. parcours complet : inscription gérant → connexion → création salon → **création de fiche** →
     la fiche apparaît dans la liste → la consultation renvoie les mêmes valeurs ;
  2. **isolation inter-salons** (critère d'acceptation) : le jeton du gérant B est refusé (`403`
     générique) sur les fiches du salon de A, et la fiche de A n'apparaît **jamais** dans la liste
     de B ;
  3. **unicité** : recréer la même fiche (même téléphone, même salon) → `409` ; **le même téléphone
     dans le salon de B** → `201` (cloisonnement) ;
  4. **traçabilité** : une ligne `audit_logs` `CUSTOMER_CREATED` avec le bon acteur, et **aucune
     PII** dans `metadata` (assertion explicite sur nom/téléphone/notes absents) ;
  5. deny-by-default : sans jeton → `401` sur les trois routes.
- **Migration** : le round-trip Alembic de la CI (`upgrade head` → `downgrade` → `upgrade`) couvre
  `0005` ; vérifier localement que `downgrade` retire index, `CHECK` et colonne.

### Web (`vitest`)

- `test/customer-domain.test.ts` : `validateCustomer` (parité des règles backend), `GENDER_OPTIONS`.
- `test/http-customer-gateway.test.ts` : mapping des statuts backend → `reason`
  (`409 → "duplicate"`, `403 → "forbidden"`, `401 → "unauthenticated"`, `422 → "invalid"`,
  `404 → "not-found"`), en-tête `Authorization` posé, **jeton jamais renvoyé** dans le résultat.
- `test/customers-bff.test.ts` : `401` sans cookie ; `422` corps invalide ; `409` propagé avec
  message neutre ; **aucune PII ni jeton** dans les réponses d'erreur.
- `test/navigation-sections.test.ts` : `clients` est désormais `available` et pointe
  `/gerant/clients`.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ;
  `npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`docs/adr/0026-fiche-client-portee-salon.md`** (nouveau) — décisions : fiche **walk-in**
  (`user_id = NULL`), genre = énumération fermée nullable, **unicité `(salon_id, phone)`** partielle,
  audit `CUSTOMER_CREATED` au titre de §11.3, **pas** de recherche `users` par téléphone
  (anti-oracle), notes internes non exposées au client. Suivis : rattachement à un compte,
  chiffrement au repos des notes, recherche/pagination avancée, consentement (#52).
- **`docs/adr/README.md`** — entrée d'index pour ADR-0026 + mention dans le paragraphe
  « Journalisation d'audit » (nouvelle action §11.4/§11.3).
- **`backend/README.md`** — section « Clients — fiche client (US-4.1, #28) » : tableau
  routes/permission/réponses/audit, exemple `curl`, règles de validation, note d'isolation §11.2.
- **`web-dashboard/README.md`** — ligne `/gerant/clients` dans le tableau des routes protégées +
  sous-section « Clients — fiches du salon (#28) » (Server Component, BFF, `router.refresh()`).
- **`README.md`** (racine) — §6 : phrase de statut « M4 amorcé : création d'une fiche client (#28) »
  dans le style des paragraphes existants ; vérifier la cohérence du tableau des jalons.
- **OpenAPI** — les `summary`/`responses`/docstrings des routes documentent la nouvelle API publique
  (visible sur `/docs`), y compris les codes `409`/`422`.

## Risks and Open Questions

1. **Le téléphone est-il obligatoire ?** L'énoncé « Nom, téléphone, genre optionnel, notes internes »
   est ambigu (« optionnel » qualifie explicitement le genre). *Recommandation : **optionnel**,* car
   (a) la colonne `customer_profiles.phone` est **nullable** au schéma #3, (b) le modèle documente
   explicitement le support des **clients walk-in**, (c) exiger un numéro empêcherait de ficher un
   client de passage. L'UI le présente comme **fortement recommandé**. **À confirmer** — si le
   téléphone doit être requis, la validation passe à `InvalidPhone` sur absence et la colonne peut
   rester nullable (compatibilité).
2. **Quelles valeurs de genre ?** Le PRD ne les fixe pas. *Recommandation : `FEMALE | MALE | OTHER`,
   nullable (`NULL` = non renseigné)*, stockées en `text` + `CHECK` dérivé du domaine — évolutif sans
   `ALTER TYPE`. Alternative écartée : texte libre (non exploitable pour les statistiques #31,
   qualité de donnée médiocre). **À confirmer** (notamment le besoin d'une valeur explicite
   « préfère ne pas répondre », distincte de `NULL`).
3. **Unicité `(salon_id, phone)` : quel compromis ?** Elle protège l'historique (#29) et les
   statistiques (#31) des doublons, mais **refuse deux fiches partageant un numéro** — cas réel sur le
   marché cible (téléphone familial partagé). *Recommandation : conserver l'unicité* (échappatoire :
   créer la seconde fiche **sans téléphone**), et documenter le compromis dans l'ADR-0026.
   **Alternative si refusée** : pas d'index unique, et détection de doublon **informative** côté UI
   (aucune garantie base) — décision à trancher avant l'implémentation, car elle conditionne la
   migration.
4. **Les lectures (`GET` liste/fiche) sont-elles dans le périmètre de #28 ?** L'issue ne demande que
   la **création**. *Recommandation : les inclure*, à titre de **complément minimal** — sans elles la
   page « Clients » est un formulaire aveugle, l'isolation §11.2 n'est pas démontrable en lecture, et
   #29 (« historique d'un client ») n'aurait pas de point d'entrée. Elles n'ajoutent **aucun** droit
   (même permission, même portée). **À confirmer** ; si refusé, la page se limite au formulaire et
   les `GET` basculent sur #29.
5. **Faut-il journaliser la création (§11.4) ?** La liste §11.4 du PRD ne cite pas explicitement la
   « création de fiche client » (elle cite la création d'employé). *Recommandation : journaliser*,
   au titre de §11.3 (« journalisation des accès sensibles » — la création d'une fiche est une
   **collecte de PII**) et par cohérence avec #13/#17/#20. Coût nul (socle `AuditLog` existant).
6. **Chiffrement au repos des notes (§11.3 « si nécessaire »).** Les notes peuvent contenir des
   données de santé (allergies, US-4.5). *Recommandation : différer* (chiffrement plateforme/
   sauvegardes ADR-0011, accès restreint `CUSTOMER_MANAGE`) et **inscrire le suivi dans l'ADR-0026**
   pour arbitrage en M6 (#52). Un chiffrement applicatif rendrait par ailleurs la future recherche
   sur notes impossible.
7. **Pagination et recherche.** *Recommandation : `limit` (défaut 50, max 200) + `offset`*, comme le
   catalogue (#18) ; la **recherche** du PRD §7.2 (par nom/téléphone) est un suivi — elle touche à la
   PII et mérite sa propre revue (fuite par temps de réponse, journalisation des critères).
8. **Concurrence & TOCTOU.** Le pré-contrôle `phone_exists` ne suffit pas : la garantie est l'index
   unique base + retraduction de l'`IntegrityError` en `409`. À couvrir par un test unitaire (fake
   levant `CustomerAlreadyExists` depuis `create`).
9. **Un ADR est-il requis ?** #26 et #27 n'en ont pas produit. *Recommandation : oui pour #28*, car
   la migration `0005` **modifie le schéma** et les choix (unicité téléphone, anti-oracle, genre
   fermé, notes sensibles) engagent les issues #29/#31/#32/#49. **À confirmer** — à défaut, replier
   ces décisions dans `backend/README.md`.
10. **Compatibilité `models.py` ↔ migration.** `models.py` est déclaré « source de vérité du
    schéma » : toute divergence entre le modèle ORM et `0005` casserait le round-trip Alembic de la
    CI. Les deux doivent être modifiés **dans le même commit**.

## Implementation Checklist

1. **Lire** `adapters/inbound/services.py`, `application/services.py`, `domain/service.py`,
   `adapters/outbound/persistence/service_repository.py`, `adapters/inbound/security.py`,
   `domain/phone.py`, `migrations/versions/0004_audit_logs.py` — s'imprégner des patrons.
2. **Trancher** les questions ouvertes 1 à 4 (téléphone requis ?, valeurs de genre, unicité
   téléphone, périmètre des `GET`) et consigner la décision dans l'ADR-0026.
3. **Domaine** : ajouter `Gender` à `domain/enums.py` ; ajouter les cinq erreurs à `domain/errors.py`
   ; créer `domain/customer.py` (bornes, `validate_customer_name`, `normalize_customer_phone`,
   `normalize_gender`, `normalize_notes`, `CustomerToCreate`, `Customer`).
4. **Audit** : ajouter `ENTITY_TYPE_CUSTOMER` et `AuditAction.CUSTOMER_CREATED` à `domain/audit.py`.
5. **Tests de domaine** : écrire `tests/test_domain_customer.py` (et compléter
   `tests/test_domain_audit.py`) — **avant** la persistance.
6. **Schéma** : ajouter `gender` (+ `enum_check`) et l'index unique partiel `(salon_id, phone)` à
   `models.py::CustomerProfile` ; écrire `migrations/versions/0005_customer_gender.py`
   (`down_revision = "0004"`) avec un `downgrade()` complet ; vérifier
   `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` sur PostgreSQL 16.
7. **Port** : créer `application/ports/customer_repository.py` (`create`, `find_by_id`,
   `list_for_salon`, `count_for_salon`, `phone_exists` — tous salon-scopés).
8. **Cas d'usage** : créer `application/customers.py` (`CustomerCommand`, `_validate`,
   `CreateCustomer`, `ListSalonCustomers`, `GetCustomer`) ; `metadata={}` dans l'`AuditEntry`.
9. **Fakes & tests applicatifs** : ajouter `FakeCustomerRepository` + fixture à `tests/conftest.py` ;
   écrire `tests/test_customer_usecases.py` (portée, audit sans PII, doublon, cloisonnement).
10. **Adapter sortant** : créer `adapters/outbound/persistence/customer_repository.py`
    (`flush()` sans `commit()`, retraduction `IntegrityError` → `CustomerAlreadyExists`, filtres
    `(salon_id, id)`).
11. **Adapter entrant** : créer `adapters/inbound/customers.py` (schémas Pydantic documentés,
    `extra="ignore"`, `require_salon_scope` + `require_permission(CUSTOMER_MANAGE)`, mapping
    `422`/`409`/`404`) ; **ne pas** toucher `PUBLIC_ROUTE_PATHS`.
12. **Câblage** : `app.include_router(customers_router)` dans `main.py` avec commentaire de câblage.
13. **Tests API & e2e** : écrire `tests/test_customer_api.py` puis `tests/test_customer_e2e.py`
    (isolation inter-salons, unicité, traçabilité sans PII, deny-by-default) ; exécuter
    `pytest` (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
14. **Web — domaine & accès** : `src/domain/customer/customer.ts` (+ test),
    `src/application/ports/customer-gateway.ts`, `src/adapters/api/http-customer-gateway.ts`
    (+ test).
15. **Web — BFF** : `app/api/salons/[id]/customers/route.ts` (`GET`/`POST`, messages neutres) +
    `test/customers-bff.test.ts`.
16. **Web — UI** : `app/(gerant)/gerant/clients/page.tsx` (Server Component, cas « aucun salon »),
    `src/adapters/ui/customer-form.tsx`, `src/adapters/ui/customer-list.tsx` ; passer `clients` à
    `available` dans `navigation/sections.ts` et mettre à jour
    `test/navigation-sections.test.ts`.
17. **Documentation** : ADR-0026 + entrée dans `docs/adr/README.md` ; sections dédiées dans
    `backend/README.md` et `web-dashboard/README.md` ; phrase de statut dans le `README.md` racine.
18. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test),
    `ruff check`, `npm run lint && npm run build` ; relire la PR pour s'assurer qu'**aucune PII et
    aucun secret** n'apparaissent dans les logs, l'audit ou les messages d'erreur, et qu'**aucune
    signature IA** n'a été introduite.
