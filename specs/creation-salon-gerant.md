# Création d'un salon par le gérant (US-2.1, issue #15)

> Issue GitHub **#15** — `feature` · Priorité **Must** · Effort **M** · PRD §6 Épic 2
> Dépend de **#9** (inscription gérant) et **#14** (shell dashboard gérant) — tous deux livrés.
> Premier item du jalon **M2** (salons & prestations).

## Problem Statement

Le socle d'authentification et d'autorisation est livré (M1) : un gérant peut créer son compte
(#9), se connecter (#10), et accéder à une zone `/gerant` protégée (#14). Le RBAC (#12) définit déjà
les permissions `SALON_CREATE` / `SALON_UPDATE` / `SALON_READ_OWN` et l'isolation par salon (PRD
§11.2), et le schéma PostgreSQL contient déjà la table `salons` (#3).

**Mais aucun salon ne peut être créé** : il n'existe ni route HTTP, ni cas d'usage, ni dépôt pour
l'entité `Salon`. Conséquences concrètes aujourd'hui :

- la permission `SALON_CREATE` de la matrice §4.1 n'est câblée sur **aucune** route ;
- `SqlSalonScopeRepository` calcule la portée d'un gérant par `salons.owner_id`, mais **aucun
  gérant ne possède de salon** — sa portée est donc toujours vide, et toutes les routes à portée
  salon (dont `POST /salons/{salon_id}/employees`, #13) lui répondent `403` ;
- tout M2–M5 (horaires #16, prestations #17, recherche client #18, RDV #21+) est bloqué : ces
  entités sont toutes rattachées à un `salon_id` qui n'existe pas.

Le gérant doit pouvoir créer son salon (nom, logo, description, téléphone, localisation, photos) et
le voir apparaître dans son dashboard, avec un signal explicite : **tant qu'aucun horaire n'est
configuré, le salon n'est pas réservable** (PRD §8.3) — la configuration des horaires étant l'objet
de l'issue suivante (#16).

## Goals

1. **Créer un salon rattaché au compte du gérant** : `POST /salons` crée un `Salon` dont
   `owner_id` est **le principal authentifié**, jamais une valeur du corps de requête.
2. **Porter tous les champs de US-2.1** : nom, description, téléphone, localisation (adresse, ville,
   commune, latitude, longitude), **logo** et **photos**.
3. **Rendre la règle §8.3 explicite et testable** : un salon sans horaire (`opening_hours IS NULL`)
   ou non `ACTIVE` **n'est pas réservable**. Exposer un prédicat de domaine `is_bookable` et le
   refléter dans la réponse API et dans le dashboard.
4. **Débloquer la portée du gérant** : après création, `SqlSalonScopeRepository` doit rendre le
   nouveau salon immédiatement visible dans la `SalonScope` du gérant (aucun changement de code
   attendu — à **vérifier par test**, c'est ce qui débloque #13 et toute la suite).
5. **Stocker les médias hors base**, dans un stockage objet **S3-compatible** (ADR-0005), via des
   **URLs signées à durée limitée**, avec des clés d'objet **sans PII**.
6. **Permettre au gérant de créer et consulter son salon depuis le dashboard** (#14), sous la
   section **Paramètres** (PRD §7.2 : « Informations générales · Horaires · Photos · Localisation »).
7. **Ne pas affaiblir le deny-by-default** : aucune nouvelle route publique ; toutes les routes
   salon sont protégées par permission **et** portée.

## Non-Goals

Ces sujets appartiennent à d'autres issues et **ne doivent pas** être implémentés ici :

- **Configuration des horaires d'ouverture** (`opening_hours`) — **#16 / US-2.2**. Ici, la colonne
  reste `NULL` à la création ; on n'expose **aucune** route d'écriture d'horaires.
- **Application effective de la règle §8.3 au moment de réserver** — la *réservation* est **#21+**.
  Ce spec expose le **prédicat** `is_bookable` et l'affiche ; il **n'ajoute aucun** comportement de
  réservation (il n'y a rien à bloquer : aucune route de réservation n'existe encore).
- **Prestations** (#17), **recherche/liste client** (#18), **consultation client d'un salon** (#19).
  → Aucune route salon **publique** n'est ajoutée ici : le catalogue côté client est le périmètre de
  #18/#19, avec ses propres règles de visibilité (§8.3 : seuls les salons `ACTIVE` sont visibles).
- **Modification des informations du salon** (`PATCH /salons/{id}` sur les champs textuels) —
  **#20 / US-2.5**. Ce spec livre la **création** ; seules les routes de médias (logo/photos) sont
  écrites après coup, parce qu'un logo ne peut être téléversé qu'une fois le salon créé (voir
  « Flux de téléversement » plus bas).
- **Désactivation / suspension d'un salon** (`SALON_SET_STATUS`, permission de l'`ADMIN`) — non
  câblée ici ; supervision plateforme (M5/M6).
- **Notion de « plan » d'abonnement** limitant le nombre de salons (§8.3 : « un ou plusieurs salons
  **selon son plan** ») — il n'existe aucun modèle d'abonnement au MVP (voir Risques).
- **Journal d'audit applicatif** (§11.4) : la liste des actions à journaliser du PRD §11.4 ne
  mentionne pas « création de salon » (elle mentionne « désactivation salon »). Aucun journal d'audit
  n'est mis en place ici.

## Relevant Repository Context

### Architecture (figée par les ADR — source de vérité)

- **Backend** : Python ≥ 3.12, **FastAPI**, API REST, JWT ([ADR-0003](../docs/adr/0003-backend-fastapi.md)).
- **Architecture hexagonale** ([ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) :
  `domain/` (pur, zéro dépendance framework/I/O) → `application/` (cas d'usage + `ports/`) →
  `adapters/inbound/` (routers FastAPI) et `adapters/outbound/` (SQLAlchemy, sécurité, notifications).
- **Données** : **PostgreSQL 16**, ORM **SQLAlchemy 2.0**, migrations **Alembic**
  ([ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md),
  [ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).
- **Fichiers** : **stockage objet S3-compatible**, fournisseur **non figé**
  ([ADR-0005](../docs/adr/0005-stockage-objet-s3-compatible.md)) — l'ADR fixe **l'interface**, pas le
  prestataire, et impose : *buckets privés par défaut*, *URLs signées à durée limitée*, *aucune PII
  dans les noms d'objets*, *clés S3 hors dépôt*.
- **Autorisation** : RBAC **deny-by-default**
  ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) — gardes en **dépendances
  FastAPI**, pas en middleware ASGI.
- **Web gérant** : **Next.js** (App Router, TypeScript), zone protégée `/gerant`, BFF + cookie
  `httpOnly` ([ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md), #14).

### Ce qui existe déjà et qu'il faut réutiliser (ne rien réinventer)

| Élément | Chemin | Rôle pour #15 |
| --- | --- | --- |
| Table `salons` | `backend/coiflink_api/adapters/outbound/persistence/models.py:136` | **Déjà au schéma** (#3) : `owner_id`, `name`, `description`, `phone`, `address`, `city`, `commune`, `latitude`, `longitude`, `logo_url`, `status`, `opening_hours` (JSONB, **nullable**). Aucune modification nécessaire. |
| Permissions | `backend/coiflink_api/domain/permissions.py:43` | `SALON_CREATE`, `SALON_UPDATE`, `SALON_READ_OWN` (MANAGER), `SALON_READ_ANY` (CLIENT, ADMIN), `SALON_SET_STATUS` (ADMIN). **Aucune permission nouvelle à créer.** |
| Portée salon | `backend/coiflink_api/adapters/outbound/persistence/salon_scope_repository.py:42` | `MANAGER` → `salons.owner_id`. Créer un salon **donne mécaniquement** la portée à son gérant, sans code supplémentaire. |
| Gardes RBAC | `backend/coiflink_api/adapters/inbound/security.py` | `require_permission(...)`, `require_salon_scope` (lit `salon_id` **du chemin** — d'où la convention `/salons/{salon_id}/…`), `PUBLIC_ROUTE_PATHS`, invariant `unprotected_routes(app)`. |
| Patron « route protégée » | `backend/coiflink_api/adapters/inbound/employees.py` | **Le modèle à copier** : DI du cas d'usage, `require_permission` + `require_salon_scope`, traduction erreurs de domaine → 409/422, **jamais** de champ privilégié lu du corps. |
| Patron « cas d'usage » | `backend/coiflink_api/application/employees.py` | Dépend **uniquement de ports**, `dataclass` de commande, écriture `flush` sans commit. |
| Patron « dépôt SQL » | `backend/coiflink_api/adapters/outbound/persistence/salon_member_repository.py` | `flush()` sans `commit()` (le commit est piloté par `get_session`), `IntegrityError` → erreur de **domaine**. |
| Patron « migration » | `backend/migrations/versions/0002_salon_members.py` | Reflet versionné du modèle ORM ; round-trip Alembic vérifié en CI. |
| Shell dashboard | `web-dashboard/app/(gerant)/`, `web-dashboard/src/` | Sections PRD §7.2 dans `src/domain/navigation/sections.ts` — **`parametres` est `coming-soon`** : c'est là que vivent « Informations générales / Photos / Localisation » (§7.2). BFF : `app/api/auth/*/route.ts`, passerelle `src/adapters/api/http-auth-gateway.ts`, cookie `httpOnly` (le jeton n'atteint **jamais** le navigateur). |
| Tests | `backend/tests/` (`test_employee_api.py`, `test_rbac_e2e.py`, `test_security_guards.py`, `test_secrets_policy.py`), `web-dashboard/test/` (Vitest) | Suites à étendre. `test_security_guards.py` vérifie l'invariant deny-by-default en **énumérant les routes** — il couvrira automatiquement les nouvelles. |

### Écart identifié dans le modèle de données

Le PRD §9.2 (et donc la table `salons`) ne porte **qu'un `logo_url`** — il n'y a **aucun support des
photos (pluriel)**, pourtant explicitement demandées par US-2.1 et par §7.2 (« Photos »). C'est le
**seul** manque du schéma : il faut l'ajouter (voir *Data Model / Protocol Changes*).

### Commandes (déjà en place, ne pas réinventer)

- Backend : `pytest`, `ruff check`, migrations Alembic (round-trip vérifié en CI contre PostgreSQL 16).
- Web : `npm test` (Vitest), `npm run lint`, `npm run build`.
- Test gate agrégé du pipeline : `scripts/test-gate.sh` (parité CI) — cf. `docs/strategie-de-tests.md`.

## Proposed Implementation

### Vue d'ensemble

Une **tranche verticale hexagonale** complète, calquée sur #13 (comptes employés) :

```
domain/salon.py                      (pur : entités, validation, règle §8.3)
        ▲
application/salons.py                (cas d'usage CreateSalon, GetSalon, ListOwnSalons)
application/ports/salon_repository.py       (port de persistance)
application/ports/media_storage.py          (port de stockage objet — ADR-0005)
        ▲
adapters/inbound/salons.py           (router FastAPI, gardes RBAC, traduction HTTP)
adapters/outbound/persistence/salon_repository.py   (SQLAlchemy)
adapters/outbound/storage/s3_media_storage.py       (boto3, S3-compatible)
```

### 1. Domaine (`backend/coiflink_api/domain/salon.py`) — nouveau, pur

```python
@dataclass(frozen=True)
class SalonToCreate:          # intention d'écriture
    owner_id: uuid.UUID       # imposé par le serveur, jamais lu du corps
    name: str
    description: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    commune: str | None = None
    latitude: decimal.Decimal | None = None
    longitude: decimal.Decimal | None = None

@dataclass(frozen=True)
class Salon:                  # entité lue
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    ...                       # + logo_url, status, opening_hours, created_at, updated_at

@dataclass(frozen=True)
class SalonPhoto:
    id: uuid.UUID
    salon_id: uuid.UUID
    object_key: str
    position: int
    created_at: datetime.datetime
```

Fonctions pures à ajouter :

- `validate_salon_name(name) -> str` : `strip()`, non vide, ≤ 255 → `InvalidSalonName` sinon.
  (Ne **pas** réutiliser `validate_name` de `domain/user.py` : ses bornes visent un nom de personne
  et son erreur `InvalidName` est déjà mappée sur l'inscription.)
- `validate_coordinates(latitude, longitude) -> tuple[Decimal | None, Decimal | None]` :
  **les deux ou aucune** ; `-90 ≤ lat ≤ 90`, `-180 ≤ lon ≤ 180` → `InvalidLocation` sinon.
- `normalize_phone(...)` : **réutiliser** `domain/phone.py` (déjà écrit, indicatif CI par défaut) ;
  le téléphone du salon est **optionnel** — ne normaliser que s'il est fourni.
- **`is_bookable(status, opening_hours) -> bool`** — la règle §8.3, isolée et testable :
  ```python
  def is_bookable(status: str, opening_hours: object | None) -> bool:
      """Un salon n'est réservable que s'il est ACTIVE **et** a des horaires (§8.3)."""
      return status == SalonStatus.ACTIVE.value and bool(opening_hours)
  ```
  `bool(opening_hours)` traite `None` **et** `{}` comme « pas d'horaire » — un JSONB vide écrit par
  #16 ne doit pas rendre un salon réservable par accident.

Nouvelles erreurs dans `domain/errors.py` : `InvalidSalonName`, `InvalidLocation`,
`SalonNotFound`, `InvalidMediaType`, `PhotoLimitExceeded`. Messages **neutres** (ni PII, ni détail
SQL), comme le reste du module.

### 2. Ports (`backend/coiflink_api/application/ports/`)

`salon_repository.py` — `Protocol` :

```python
class SalonRepository(Protocol):
    def create(self, salon: SalonToCreate) -> Salon: ...
    def find_by_id(self, salon_id: uuid.UUID) -> Salon | None: ...
    def list_for_owner(self, owner_id: uuid.UUID) -> tuple[Salon, ...]: ...
    def set_logo(self, salon_id: uuid.UUID, object_key: str | None) -> Salon: ...
    def add_photo(self, salon_id: uuid.UUID, object_key: str) -> SalonPhoto: ...
    def list_photos(self, salon_id: uuid.UUID) -> tuple[SalonPhoto, ...]: ...
    def delete_photo(self, salon_id: uuid.UUID, photo_id: uuid.UUID) -> bool: ...
```

`media_storage.py` — `Protocol` (l'interface **S3-compatible** de l'ADR-0005, sans nommer le
fournisseur) :

```python
class MediaStorage(Protocol):
    def presign_upload(self, object_key: str, content_type: str) -> PresignedUpload: ...
    def presign_download(self, object_key: str) -> str: ...   # URL signée, courte durée
    def delete(self, object_key: str) -> None: ...
```

`PresignedUpload` (dataclass de domaine) : `url`, `method` (`"PUT"`), `headers`, `expires_in`.

### 3. Application (`backend/coiflink_api/application/salons.py`)

- **`CreateSalon`** : `execute(CreateSalonCommand) -> Salon`.
  `owner_id` **est un paramètre du cas d'usage fourni par la garde** (le `Principal`), **pas un champ
  de la commande venant du client** — exactement comme le `role` fixé au câblage dans
  `CreateEmployee` (#13). Séquence : `validate_salon_name` → `validate_coordinates` →
  `normalize_phone` si fourni → `repository.create(...)` avec `status=ACTIVE`, `opening_hours=None`.
- **`GetSalon`** / **`ListOwnSalons`** : lectures ; enrichissent chaque salon de ses photos et
  **résolvent les URLs signées** via `MediaStorage.presign_download` (le client ne voit jamais une
  clé d'objet brute ni une URL de bucket non signée).
- **`AttachSalonLogo`** / **`AddSalonPhoto`** / **`RemoveSalonPhoto`** : valident le type MIME
  (`image/jpeg`, `image/png`, `image/webp`) et la limite de photos (`MEDIA_MAX_PHOTOS`, défaut **10**),
  puis écrivent la référence.
- **`IssueMediaUploadUrl`** : fabrique la **clé d'objet** et délègue à `MediaStorage.presign_upload`.

**Fabrication de la clé d'objet** — contrainte dure de l'ADR-0005 (« aucune PII dans les noms
d'objets ») :

```
salons/{salon_id}/logo/{uuid4}.{ext}
salons/{salon_id}/photos/{uuid4}.{ext}
```

`salon_id` et `uuid4` sont des UUID opaques : **jamais** le nom du salon, le téléphone, l'adresse ou
un nom de fichier fourni par le client (qui pourrait contenir de la PII ou une traversée de chemin).
L'extension est **dérivée du type MIME validé**, pas du nom de fichier client.

### 4. Adapter entrant (`backend/coiflink_api/adapters/inbound/salons.py`)

Router `prefix="/salons"`, `tags=["salons"]`. **Aucun chemin n'est ajouté à `PUBLIC_ROUTE_PATHS`.**

| Route | Garde(s) | Rôles effectifs (matrice §4.1) |
| --- | --- | --- |
| `POST /salons` | `require_permission(SALON_CREATE)` | **MANAGER seul** (ni ADMIN, ni client, ni coiffeur) |
| `GET /salons` | `require_permission(SALON_READ_OWN)` | MANAGER, HAIRDRESSER — liste **ses** salons |
| `GET /salons/{salon_id}` | `require_any_permission(SALON_READ_OWN, SALON_READ_ANY)` + `require_salon_scope` | MANAGER (son salon), HAIRDRESSER (son salon), ADMIN (tous) |
| `POST /salons/{salon_id}/media/upload-url` | `require_permission(SALON_UPDATE)` + `require_salon_scope` | MANAGER (son salon) |
| `PUT /salons/{salon_id}/logo` | `require_permission(SALON_UPDATE)` + `require_salon_scope` | MANAGER (son salon) |
| `POST /salons/{salon_id}/photos` | `require_permission(SALON_UPDATE)` + `require_salon_scope` | MANAGER (son salon) |
| `DELETE /salons/{salon_id}/photos/{photo_id}` | `require_permission(SALON_UPDATE)` + `require_salon_scope` | MANAGER (son salon) |

Trois points d'attention **non évidents**, à traiter explicitement :

1. **`POST /salons` ne peut pas utiliser `require_salon_scope`.** Cette garde lit `salon_id` **du
   chemin** — à la création, le salon n'existe pas encore. La protection repose donc **entièrement**
   sur `require_permission(SALON_CREATE)` (seul le `MANAGER` la détient) **et** sur le fait que
   `owner_id = principal.id`. Il **ne doit exister aucun champ `owner_id` dans le corps de
   requête** : c'est l'invariant anti-élévation de privilège de cette issue (miroir exact du champ
   `role` absent de `CreateEmployeeRequest`, #13). À figer par un test.

2. **`require_permission(SALON_READ_OWN)` exclurait l'`ADMIN`** de `GET /salons/{salon_id}` : la
   matrice donne `SALON_READ_ANY` (et non `_OWN`) à l'`ADMIN`. Ajouter dans `security.py` une garde
   composable **`require_any_permission(*permissions)`** (403 si le rôle n'en détient **aucune**),
   marquée `_mark_principal_guard` comme les autres. C'est un **élargissement lisible et testé**, pas
   un contournement : `require_salon_scope` continue de s'appliquer, et il laisse déjà passer l'ADMIN
   via `SalonScope.platform_wide`.

3. **Ordre de déclaration des routes** : ne pas introduire de chemin littéral (`/salons/mine`) qui
   entrerait en collision avec `/salons/{salon_id}` typé `uuid.UUID`. D'où le choix de `GET /salons`
   (liste implicitement limitée au principal) plutôt que `/salons/mine`.

**Traduction des erreurs** (patron `employees.py`, jamais `str(exc)` sur un refus) :
`InvalidSalonName` / `InvalidLocation` / `InvalidPhone` / `InvalidMediaType` → **422** ;
`PhotoLimitExceeded` → **409** ; `SalonNotFound` → **404** *(seulement une fois la portée validée —
un salon hors périmètre a déjà été refusé par un `403` générique, donc pas d'oracle d'existence)* ;
stockage objet injoignable / non configuré → **503** (même logique que `JWT_SECRET` absent).

### 5. Flux de téléversement des médias (décision de conception)

**Le salon est créé d'abord, les médias ensuite.** Le navigateur téléverse **directement** vers le
stockage objet via une **URL signée** ; le binaire ne transite **jamais** par l'API :

```
1. POST /salons                          → 201 { id, is_bookable: false, ... }
2. POST /salons/{id}/media/upload-url    → { url, method: "PUT", headers, object_key, expires_in }
   body: { kind: "logo" | "photo", content_type: "image/png" }
3. PUT <url>  (navigateur → stockage objet, hors API)
4. PUT  /salons/{id}/logo    body: { object_key }     → 200
   POST /salons/{id}/photos body: { object_key }      → 201
```

Pourquoi ce découpage plutôt qu'un `multipart/form-data` en une passe :

- **toutes les routes médias restent sous `/salons/{salon_id}/…`**, donc couvertes par
  `require_salon_scope` — la convention de portée documentée dans `security.py` ;
- l'API ne relaie aucun binaire (pas de budget mémoire/latence, PRD §12) ;
- la clé d'objet est **fabriquée par le serveur** (§ ci-dessus), donc sans PII et sans nom de fichier
  client ;
- conforme à l'ADR-0005 : **bucket privé**, accès par **URL signée à durée limitée**.

**Contrôle du contenu** : l'`object_key` renvoyé à l'étape 4 est **revalidé côté serveur** — il doit
respecter le préfixe `salons/{salon_id}/…` attendu **pour ce salon** ; sinon `422`. Sans cette
revalidation, un gérant pourrait faire référencer par son salon une clé appartenant à un autre salon.
C'est une **règle de sécurité obligatoire**, pas une optimisation.

### 6. Adapter sortant de stockage (`adapters/outbound/storage/s3_media_storage.py`)

Client **boto3** (`boto3`/`botocore` à ajouter aux dépendances de `backend/pyproject.toml`),
configuré par variables d'environnement, **agnostique du fournisseur** (ADR-0005) : un `endpoint_url`
explicite permet de viser MinIO en local, ou n'importe quel service S3-compatible en production.

Conformément à l'ADR-0005 (« tant que le fournisseur n'est pas arrêté, **on développe et teste contre
un service S3-compatible, p. ex. MinIO en local** »), ajouter un service **MinIO** à
`deploy/docker-compose.yml` (image publique, identifiants **de développement uniquement**, lus depuis
`deploy/.env`, jamais committés).

Assemblage dans `main.py`, sur le patron **déjà utilisé** pour `token_service` : si la configuration
S3 est incomplète, `app.state.media_storage = None` et les routes médias répondent **503** — sans
casser `GET /health`, l'authentification, ni **`POST /salons`** (créer un salon sans logo doit
rester possible : le critère d'acceptation de #15 ne dépend pas du stockage objet).

En test unitaire, une `FakeMediaStorage` en mémoire (dans `tests/conftest.py`, à côté des fakes
existants) — **aucun appel réseau**, aucun conteneur requis pour `pytest`.

### 7. Web dashboard (`web-dashboard/`)

La section cible est **Paramètres** : le PRD §7.2 y range explicitement « Informations générales ·
Horaires · Jours fermés · **Photos** · **Localisation** ». Donc **ne pas ajouter de 8ᵉ section de
navigation** — faire passer `parametres` de `coming-soon` à `available` dans
`src/domain/navigation/sections.ts` (et ajuster `test/navigation-sections.test.ts`).

Tranche hexagonale miroir de l'existant (`http-auth-gateway.ts` / `require-manager-session.ts`) :

- `src/domain/salon/salon.ts` — type `Salon`, `isBookable(salon)` (miroir TS de la règle §8.3) ;
- `src/application/ports/salon-gateway.ts` — port `SalonGateway` ;
- `src/application/use-cases/create-salon.ts` — validation + appel de la passerelle ;
- `src/adapters/api/http-salon-gateway.ts` — appelle le backend **côté serveur**, avec le jeton lu du
  cookie `httpOnly` (le jeton **ne doit jamais** atteindre le navigateur — invariant #14) ;
- `app/api/salons/route.ts` (+ `app/api/salons/[id]/…`) — **routes BFF** ;
- `app/(gerant)/gerant/parametres/page.tsx` — Server Component : si le gérant n'a pas de salon →
  **formulaire de création** ; sinon → fiche du salon + gestion logo/photos ;
- `src/adapters/ui/salon-form.tsx` — formulaire client ;
- **Bandeau §8.3** : tant que `is_bookable === false`, afficher un avertissement explicite du type
  « Ce salon n'est pas encore réservable : configurez vos horaires d'ouverture. » — c'est la
  matérialisation visible du second critère d'acceptation.

Le téléversement navigateur → stockage objet (étape 3) exige que le bucket accepte l'origine du
dashboard (**CORS**) — à documenter et à configurer côté bucket, pas dans le code.

## Affected Files / Packages / Modules

### `backend/` (paquet principal)

**À créer**
- `coiflink_api/domain/salon.py`
- `coiflink_api/application/salons.py`
- `coiflink_api/application/ports/salon_repository.py`
- `coiflink_api/application/ports/media_storage.py`
- `coiflink_api/adapters/inbound/salons.py`
- `coiflink_api/adapters/outbound/persistence/salon_repository.py`
- `coiflink_api/adapters/outbound/storage/__init__.py`
- `coiflink_api/adapters/outbound/storage/s3_media_storage.py`
- `migrations/versions/0003_salon_photos.py`
- Tests : `tests/test_domain_salon.py`, `tests/test_create_salon_usecase.py`,
  `tests/test_salon_api.py`, `tests/test_salon_media_api.py`, `tests/test_salon_e2e.py`

**À modifier**
- `coiflink_api/domain/errors.py` — nouvelles erreurs de domaine
- `coiflink_api/adapters/outbound/persistence/models.py` — modèle `SalonPhoto` (**source de vérité du
  schéma**, cf. en-tête du module)
- `coiflink_api/adapters/inbound/security.py` — `require_any_permission(...)`
- `coiflink_api/config.py` — `MediaConfig` + `load_media_config()`
- `coiflink_api/main.py` — `include_router(salons_router)`, `app.state.media_storage`
- `pyproject.toml` — dépendance `boto3`
- `tests/conftest.py` — `FakeSalonRepository`, `FakeMediaStorage`
- `README.md` (backend)

### `web-dashboard/`

**À créer** : `src/domain/salon/salon.ts`, `src/application/ports/salon-gateway.ts`,
`src/application/use-cases/create-salon.ts`, `src/adapters/api/http-salon-gateway.ts`,
`src/adapters/ui/salon-form.tsx`, `app/api/salons/route.ts`, `app/api/salons/[id]/…`,
`app/(gerant)/gerant/parametres/page.tsx`, tests Vitest associés.

**À modifier** : `src/domain/navigation/sections.ts` (`parametres` → `available`),
`test/navigation-sections.test.ts`, `README.md`.

### Racine / infra

`deploy/docker-compose.yml` (service MinIO), `deploy/.env.example`,
`docs/environnements-et-secrets.md` (inventaire des secrets S3), `docs/adr/0017-…md` (nouvel ADR),
`docs/adr/README.md` (index), `README.md` (module 2 « Gestion des salons »).

## API / Interface Changes

**Nouvelles routes REST** (toutes **protégées** ; aucun ajout à `PUBLIC_ROUTE_PATHS`) :

### `POST /salons` → `201 Created`

Crée un salon rattaché au **gérant authentifié**.

```jsonc
// Requête — AUCUN champ `owner_id`, AUCUN champ `status`, AUCUN champ `opening_hours`.
{
  "name": "Salon Élégance",              // requis, 1..255
  "description": "Coiffure afro et tresses.",
  "phone": "0700000000",                 // optionnel, normalisé (domain/phone.py)
  "address": "Rue des Jardins, Cocody",
  "city": "Abidjan",
  "commune": "Cocody",
  "latitude": 5.359952,                  // optionnel — latitude ET longitude, ou aucune
  "longitude": -3.996643
}
```

```jsonc
// Réponse 201
{
  "id": "…uuid…",
  "owner_id": "…uuid…",
  "name": "Salon Élégance",
  "description": "…", "phone": "+2250700000000",
  "address": "…", "city": "Abidjan", "commune": "Cocody",
  "latitude": 5.359952, "longitude": -3.996643,
  "logo_url": null,                      // URL **signée** si un logo est défini, sinon null
  "photos": [],
  "status": "ACTIVE",
  "opening_hours": null,                 // #16
  "is_bookable": false,                  // ← §8.3 : pas d'horaire ⇒ pas réservable
  "created_at": "…", "updated_at": "…"
}
```

Codes : `201` · `401` (non authentifié) · `403` (rôle ≠ MANAGER) · `422` (nom/téléphone/coordonnées
invalides) · `503` (`JWT_SECRET` absent).

### Autres routes

| Route | Réponse | Codes notables |
| --- | --- | --- |
| `GET /salons` | `SalonResponse[]` (salons du principal) | `200`, `401`, `403` |
| `GET /salons/{salon_id}` | `SalonResponse` | `200`, `401`, `403` (hors portée), `404` |
| `POST /salons/{salon_id}/media/upload-url` | `{ url, method, headers, object_key, expires_in }` | `200`, `403`, `422` (MIME refusé), `503` (stockage non configuré) |
| `PUT /salons/{salon_id}/logo` | `SalonResponse` | `200`, `403`, `422` (clé hors préfixe du salon) |
| `POST /salons/{salon_id}/photos` | `SalonPhotoResponse` | `201`, `403`, `409` (limite atteinte), `422` |
| `DELETE /salons/{salon_id}/photos/{photo_id}` | — | `204`, `403`, `404` |

**Nouvelles interfaces internes documentées** : ports `SalonRepository` et `MediaStorage`
(docstrings de module, comme les ports existants) ; garde `require_any_permission(*permissions)`
dans `security.py` (à documenter dans le mode d'emploi en tête de module).

**Variables d'environnement (nouvelles)** :

| Variable | Secret ? | Défaut | Rôle |
| --- | --- | --- | --- |
| `S3_ENDPOINT_URL` | non | *(vide)* | Endpoint S3-compatible (MinIO local, fournisseur en prod) |
| `S3_BUCKET` | non | *(vide)* | Bucket des médias (**privé**) |
| `S3_REGION` | non | `us-east-1` | Région |
| `S3_ACCESS_KEY_ID` | **oui** | *(vide)* | Clé d'accès — **hors dépôt** (ADR-0005/0011) |
| `S3_SECRET_ACCESS_KEY` | **oui** | *(vide)* | Clé secrète — **hors dépôt** |
| `MEDIA_URL_TTL_SECONDS` | non | `900` | Durée de vie des URLs signées |
| `MEDIA_MAX_UPLOAD_BYTES` | non | `5242880` (5 Mio) | Taille max d'un média |
| `MEDIA_MAX_PHOTOS` | non | `10` | Photos max par salon |

**CLI** : aucun changement.

## Data Model / Protocol Changes

**Table `salons`** : **aucune modification**. Toutes les colonnes de US-2.1 existent déjà (#3), y
compris `opening_hours` (JSONB **nullable** — c'est ce `NULL` qui porte « pas encore réservable »).

**Nouvelle table `salon_photos`** — c'est la seule lacune du schéma (§9.2 ne prévoit qu'un
`logo_url` singulier). Modèle ORM dans `models.py` (**source de vérité**) + migration Alembic
**`0003_salon_photos.py`** (`down_revision = "0002"`), reflet exact, avec `downgrade()` réversible :

| Colonne | Type | Contraintes |
| --- | --- | --- |
| `id` | `UUID` | PK, `server_default gen_random_uuid()` |
| `salon_id` | `UUID` | **FK → `salons.id`**, `ON DELETE CASCADE` ✱, indexé |
| `object_key` | `TEXT` (≤ 1024) | non nul — **clé d'objet, jamais une URL publique** |
| `position` | `INTEGER` | non nul, `CHECK position >= 0` (ordre d'affichage) |
| `created_at` | `timestamptz` | non nul, défaut `now()` |

Contraintes / index, alignés sur les conventions du module (cf. en-tête de `models.py`) :
- `UniqueConstraint("salon_id", "id", name="uq_salon_photos_salon_id")` — cible de **futures FK
  composites** (convention d'isolation par salon) ;
- `UniqueConstraint("salon_id", "object_key", name="uq_salon_photos_salon_object_key")` — pas de
  doublon de média ;
- `Index("ix_salon_photos_salon_id", "salon_id", "position")`.

✱ **Écart assumé à documenter** : la convention du module est `ON DELETE RESTRICT` par défaut,
`CASCADE` réservé aux « lignes purement dépendantes ». Une photo **est** purement dépendante de son
salon (elle n'a aucun sens seule, comme `appointment_services`) → `CASCADE` est le bon choix. À
justifier dans la docstring de la migration.

**Stockage du logo** : la colonne existante `salons.logo_url` **change de sémantique** — elle stocke
désormais une **clé d'objet** (`salons/{id}/logo/{uuid}.png`), **pas une URL**. L'URL signée est
calculée **à la lecture** (une URL signée expire : la persister serait un bug). Deux options :
(a) garder le nom `logo_url` et le documenter (aucune migration) ;
(b) renommer la colonne en `logo_object_key` (migration `ALTER TABLE … RENAME COLUMN`).
**Recommandation : (b)** — la table est vide (aucun salon n'existe), le renommage est sans risque, et
un nom qui ment est une dette qui se paiera à chaque lecture du code. À confirmer (voir Risques).

**Aucune PII n'est stockée dans les clés d'objet** (UUID uniquement) — exigence ADR-0005.

**Format sur le fil** : JSON REST (inchangé). `latitude`/`longitude` sérialisés en nombres ;
`NUMERIC(9,6)` en base (jamais de flottant côté stockage).

## Security & Privacy Considerations

Contraintes **documentées** par le dépôt et directement touchées par ce changement :

1. **RBAC deny-by-default** ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) —
   *invariant à ne jamais affaiblir*. Aucun chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : les salons
   **ne sont pas publics** dans cette issue (la visibilité client `ACTIVE`-seulement est le périmètre
   de #18/#19, avec ses propres règles §8.3). Le test `unprotected_routes(app)` doit rester vide.

2. **Anti-élévation de privilège** — `owner_id` est **imposé par le serveur** depuis le `Principal`
   authentifié. Un champ `owner_id` accepté dans le corps de `POST /salons` permettrait à un gérant
   de créer un salon **au nom d'un autre compte** : c'est la faille principale de cette issue.
   Miroir exact de l'invariant « aucun champ `role` » de #13. **À figer par un test explicite** (un
   corps contenant `owner_id` ne doit pas influencer le résultat).

3. **Isolation par salon** (PRD §11.2) — chaque route `/salons/{salon_id}/…` porte
   `require_salon_scope` ; un accès inter-salons renvoie le **`403` générique** (message constant,
   **aucun oracle d'existence** — on ne dit jamais si le salon existe chez autrui). Ne jamais
   remplacer ce `403` par un `404` « informatif ».

4. **Référencement croisé de médias** — l'`object_key` soumis par le client est **revalidé** contre
   le préfixe `salons/{salon_id}/` du salon ciblé. Sans cela, l'isolation §11.2 est contournable *par
   les médias* (un gérant référence l'objet d'un autre salon).

5. **Stockage objet** ([ADR-0005](../docs/adr/0005-stockage-objet-s3-compatible.md), §11.3) —
   contraintes explicites de l'ADR, à respecter telles quelles :
   - **bucket privé par défaut** ; aucun objet en lecture publique ;
   - accès **exclusivement** par **URLs signées à durée limitée** (`MEDIA_URL_TTL_SECONDS`) ;
   - **aucune PII dans les clés d'objet** — jamais le nom du salon, le téléphone, l'adresse, ni le
     nom de fichier fourni par le client (qui peut aussi porter une traversée de chemin) ;
   - **clés S3 hors dépôt**, injectées par l'environnement — jamais committées, jamais journalisées.

6. **Validation du téléversement** : type MIME sur liste blanche (`image/jpeg`, `image/png`,
   `image/webp`), taille bornée (`MEDIA_MAX_UPLOAD_BYTES`, appliquée **par la politique de l'URL
   signée**, pas seulement par le front), nombre de photos borné (`MEDIA_MAX_PHOTOS` → `409`).
   L'extension de la clé est **dérivée du MIME validé**, jamais du nom de fichier client.

7. **Journalisation — ne jamais logger** (PRD §11.3/§11.4, invariant du dépôt) :
   - **une URL signée est un secret porteur** (elle contient la signature) → **jamais** dans les logs,
     jamais dans un message d'erreur ;
   - les **clés d'accès S3** → jamais ;
   - la **PII du salon** : `phone`, `address`, `latitude`/`longitude` sont des données personnelles /
     de localisation → ne pas les journaliser (le `salon_id` UUID suffit à tracer).
   `backend/tests/test_secrets_policy.py` doit rester vert ; l'étendre aux nouvelles variables S3.

8. **Secrets & environnements** ([ADR-0011](../docs/adr/0011-deploiement-environnements-secrets.md),
   `docs/environnements-et-secrets.md`) : `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` rejoignent
   l'**inventaire des secrets** (avec leur politique de rotation). Les identifiants MinIO de
   `deploy/.env.example` sont des **valeurs de développement**, jamais réutilisables ailleurs.

9. **Front (#14)** : le jeton d'accès reste dans un cookie `httpOnly`, lu **côté serveur** par le BFF.
   Le téléversement navigateur → bucket se fait avec l'**URL signée**, **sans** jamais exposer le JWT
   ni les clés S3 au navigateur. La passerelle ne journalise ni jeton, ni PII (invariant
   `http-auth-gateway.ts`).

10. **Résidence des données** : l'hébergement est **Railway, région `europe-west4`** (ADR-0011). Si le
    bucket retenu est ailleurs, c'est une **décision de résidence** à tracer (voir Risques).

## Testing Plan

### Backend — unitaires (`pytest`, sans base ni réseau)

- `tests/test_domain_salon.py` :
  - `validate_salon_name` : vide / espaces / > 255 → `InvalidSalonName` ; `strip()` appliqué ;
  - `validate_coordinates` : latitude seule → `InvalidLocation` ; hors bornes (`91`, `-181`) →
    `InvalidLocation` ; les deux `None` → accepté ;
  - **`is_bookable`** (§8.3) — la table de vérité, cœur du critère d'acceptation :
    | `status` | `opening_hours` | attendu |
    | --- | --- | --- |
    | `ACTIVE` | `None` | **`False`** |
    | `ACTIVE` | `{}` | **`False`** |
    | `ACTIVE` | `{"mon": [...]}` | `True` |
    | `INACTIVE` | `{"mon": [...]}` | **`False`** |
- `tests/test_create_salon_usecase.py` (fakes de `conftest.py`) : `owner_id` **provient du principal**
  et **ignore** tout `owner_id` du corps ; `status=ACTIVE` et `opening_hours=None` à la création ;
  téléphone normalisé si fourni, `None` toléré ; validation avant écriture (pas d'appel au dépôt si
  le nom est invalide).

### Backend — API / intégration (`TestClient`, `dependency_overrides`)

- `tests/test_salon_api.py` :
  - **matrice RBAC de `POST /salons`** : `MANAGER` → `201` ; `CLIENT` → `403` ; `HAIRDRESSER` →
    `403` ; **`ADMIN` → `403`** (l'admin supervise, il n'exploite pas — §4.1) ; sans jeton → `401` ;
  - **anti-élévation** : un corps contenant `"owner_id": "<autre-uuid>"` crée quand même le salon du
    **principal** (champ ignoré / rejeté) ;
  - `GET /salons/{id}` d'un **autre** gérant → `403` **générique** (pas `404`, pas de fuite) ;
  - `GET /salons/{id}` par l'`ADMIN` → `200` (valide `require_any_permission`) ;
  - la réponse de création porte **`is_bookable: false`** et **`opening_hours: null`** ;
  - la réponse ne contient **aucun** secret ni clé d'objet brute.
- `tests/test_salon_media_api.py` (avec `FakeMediaStorage`) : MIME hors liste blanche → `422` ;
  `object_key` d'un **autre** salon → `422` ; `MEDIA_MAX_PHOTOS + 1` → `409` ; `media_storage=None`
  → `503` **et** `POST /salons` reste `201` (le stockage n'est pas un prérequis à la création).
- `tests/test_security_guards.py` (existant) : `unprotected_routes(app)` reste **vide** après ajout du
  router — l'invariant deny-by-default couvre automatiquement les nouvelles routes.
- `tests/test_domain_permissions.py` (existant) : doit rester vert **sans modification** (aucune
  permission nouvelle).

### Backend — end-to-end (`tests/test_salon_e2e.py`, sur le patron de `test_rbac_e2e.py`)

Parcours complet : inscription gérant (#9) → login (#10) → **`POST /salons`** → `GET /salons/{id}` →
`is_bookable == false`. Puis, **régression clé** : le gérant peut désormais appeler
`POST /salons/{id}/employees` (#13) avec **`201`** au lieu du `403` qu'il recevait faute de portée —
c'est la preuve exécutable que la création de salon débloque `SqlSalonScopeRepository`.

### Migration

Round-trip Alembic `upgrade` → `downgrade` contre **PostgreSQL 16** (déjà en CI, job `backend`) ;
vérifier que `models.py` et `0003_salon_photos.py` ne divergent pas.

### Web dashboard (Vitest)

- `test/salon-domain.test.ts` — `isBookable` (mêmes cas que le backend : parité de la règle §8.3) ;
- `test/create-salon.test.ts` — cas d'usage (validation, erreurs de passerelle) ;
- `test/http-salon-gateway.test.ts` — mapping `201/401/403/422/503` ; **le jeton n'est jamais
  journalisé ni renvoyé au client** ;
- `test/bff-routes.test.ts` (existant, à étendre) — les routes BFF `/api/salons` exigent le cookie de
  session ;
- `test/navigation-sections.test.ts` (existant) — `parametres` passe à `available`.

### Documentation

Vérifier que le `README` backend et le `README` racine décrivent les routes livrées **et rien de
plus** (ne pas laisser entendre que les horaires ou la réservation existent).

## Documentation Updates

- **Nouvel ADR — `docs/adr/0017-creation-salon-medias-et-reservabilite.md`** (le dépôt trace chaque
  décision structurante ainsi : 0013, 0014, 0015, 0016). À couvrir : (a) `owner_id` imposé par le
  serveur ; (b) médias via **URL signée** + table `salon_photos` (plutôt qu'un JSONB ou un upload
  multipart à travers l'API) ; (c) `is_bookable` comme **règle de domaine** dérivée, non persistée ;
  (d) `require_any_permission` ; (e) MinIO en développement, fournisseur de production **toujours
  ouvert** (renvoi ADR-0005/0011). Ajouter la ligne dans `docs/adr/README.md`.
- **`README.md` (racine)** : module 2 « Gestion des salons » — mentionner `POST /salons`, le
  rattachement au gérant et la règle §8.3 (« sans horaire ⇒ non réservable »). Mettre à jour la
  section 6 (« M2 en cours »).
- **`backend/README.md`** : nouvelles variables d'environnement (tableau ci-dessus) et prérequis
  MinIO pour les médias en local.
- **`web-dashboard/README.md`** : section Paramètres, flux de téléversement, exigence **CORS** du
  bucket.
- **`docs/environnements-et-secrets.md`** : ajouter `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` à
  l'**inventaire des secrets** (rotation, conduite en cas de fuite).
- **`deploy/.env.example`** + `deploy/docker-compose.yml` : service MinIO (valeurs de développement).
- **OpenAPI** : les `summary`/`responses`/docstrings des routes sont la documentation publique de
  l'API (patron `employees.py`) — les rédiger avec le même soin.

## Risks and Open Questions

### Décisions à confirmer

1. **Renommer `salons.logo_url` en `logo_object_key` ?** *(recommandé : oui)* La colonne stockera une
   **clé d'objet**, pas une URL. La table est vide → migration sans risque. Le coût est une migration
   supplémentaire ; le bénéfice est un schéma qui ne ment pas. **Alternative** : garder `logo_url` et
   le documenter (zéro migration, dette de nommage permanente).
2. **Un gérant peut-il posséder plusieurs salons ?** Le PRD §8.3 dit « un ou plusieurs salons **selon
   son plan** », mais **aucun modèle d'abonnement n'existe au MVP**. Le schéma et
   `SqlSalonScopeRepository` (qui renvoie un **ensemble**) supportent déjà le multi-salon.
   **Recommandation : autoriser N salons sans limite au MVP** (ne pas inventer un « plan »), et
   traiter le plafonnement quand l'abonnement existera. **À confirmer** — la décision inverse (1 seul
   salon par gérant) impose une contrainte d'unicité sur `salons.owner_id` et un `409`, donc doit être
   tranchée **avant** l'implémentation.
3. **Périmètre médias dans #15.** L'issue liste « logo, photos », mais ses **critères d'acceptation**
   ne portent que sur la création du salon et la règle §8.3. Si l'effort **M** doit être tenu, une
   **coupe possible** est de livrer la création + `is_bookable` (critères d'acceptation) et de
   reporter le flux médias à #20 (« modification des informations du salon »). **Recommandation :
   garder les médias ici** (c'est le cœur fonctionnel de US-2.1), mais la coupe est légitime si
   l'implémentation dérive.
4. **Fournisseur du stockage objet** — **toujours ouvert** (ADR-0005 : « fournisseur concret à choisir
   au déploiement »). L'hébergement étant **Railway** (ADR-0011), le **bucket Railway
   (S3-compatible)** est le candidat naturel ; R2/S3/MinIO auto-hébergé restent possibles. **Aucune
   ligne de code ne doit supposer un fournisseur** — c'est précisément pourquoi l'accès passe par le
   port `MediaStorage` + `endpoint_url` configurable.
5. **Résidence des données** : ADR-0011 fixe `europe-west4`. Si le bucket retenu vit dans une autre
   région, c'est une **décision de résidence** à tracer explicitement dans l'ADR-0017 (photos de
   salons : donnée peu sensible, mais la cohérence de la politique doit être assumée, pas subie).

### Risques

- **`require_any_permission` élargit la surface d'autorisation.** C'est un ajout au module le plus
  sensible du dépôt (`security.py`). Il doit être **testé pour lui-même** (rôle sans aucune des
  permissions → `403`) et documenté dans le mode d'emploi en tête de module. Ne pas le transformer en
  « OU » permissif appliqué ailleurs sans revue.
- **Référencement croisé de médias** (point 4 de la section sécurité) : c'est le **contournement
  d'isolation le plus probable** de cette issue. La revalidation du préfixe d'`object_key` n'est pas
  optionnelle.
- **Objets orphelins** : un `presign_upload` suivi d'un téléversement mais **sans** appel à
  `PUT /logo` / `POST /photos` laisse un objet non référencé dans le bucket. Acceptable au MVP
  (coût négligeable) ; à traiter par une politique de cycle de vie du bucket ou un nettoyage
  périodique — **hors périmètre**, à mentionner dans l'ADR.
- **`boto3` est une nouvelle dépendance** du backend : elle passera par `pip-audit` /
  Dependabot / `osv-scanner` (job `dependency-scan` de la CI).
- **CORS du bucket** : le téléversement direct depuis le navigateur échouera silencieusement si le
  bucket n'autorise pas l'origine du dashboard. C'est une **configuration d'infrastructure**, pas de
  code — à documenter, sinon la fonctionnalité « marche en test, casse en staging ».
- **Le dashboard suppose qu'un gérant a 0 ou 1 salon** dans son écran Paramètres. Si la décision (2)
  est « N salons », l'UI devra offrir un sélecteur — à cadrer avant d'écrire la page.

## Implementation Checklist

> Ordre conçu pour que chaque étape soit vérifiable isolément (domaine → application → adapters → UI).

### Backend — domaine & application

1. Créer `domain/salon.py` : `SalonToCreate`, `Salon`, `SalonPhoto`, `validate_salon_name`,
   `validate_coordinates`, **`is_bookable`** (§8.3). Zéro import framework/I/O.
2. Ajouter à `domain/errors.py` : `InvalidSalonName`, `InvalidLocation`, `SalonNotFound`,
   `InvalidMediaType`, `PhotoLimitExceeded` (messages neutres, sans PII).
3. Écrire `tests/test_domain_salon.py` — dont la **table de vérité de `is_bookable`**. ✅ vert avant
   de continuer.
4. Créer les ports `application/ports/salon_repository.py` et `application/ports/media_storage.py`
   (`Protocol`, docstring de module comme les ports existants).
5. Créer `application/salons.py` : `CreateSalon` (+ `CreateSalonCommand` **sans `owner_id`** —
   l'`owner_id` est un argument d'`execute`, fourni par la garde), `GetSalon`, `ListOwnSalons`,
   `IssueMediaUploadUrl`, `AttachSalonLogo`, `AddSalonPhoto`, `RemoveSalonPhoto`.
6. Ajouter `FakeSalonRepository` et `FakeMediaStorage` à `tests/conftest.py` ; écrire
   `tests/test_create_salon_usecase.py`.

### Backend — persistance

7. Ajouter le modèle ORM `SalonPhoto` à `models.py` (conventions de l'en-tête du module :
   `_pk()`, `_created_at()`, unicité `(salon_id, id)`, index) + l'exporter dans `__all__`.
8. Décider (1) *(logo_url → logo_object_key ?)* puis écrire la migration
   `migrations/versions/0003_salon_photos.py` (`down_revision = "0002"`), avec `downgrade()`
   réversible et docstring justifiant le `ON DELETE CASCADE`.
9. Créer `adapters/outbound/persistence/salon_repository.py` (`flush()` **sans** `commit()` ;
   `IntegrityError` → erreur de **domaine**).
10. Vérifier le round-trip Alembic contre PostgreSQL 16.

### Backend — stockage objet

11. Ajouter `boto3` à `backend/pyproject.toml`.
12. Créer `adapters/outbound/storage/s3_media_storage.py` (presign upload/download, delete ;
    `endpoint_url` configurable → **agnostique du fournisseur**, ADR-0005).
13. Ajouter `MediaConfig` + `load_media_config()` à `config.py` (**aucun défaut pour les secrets** —
    même politique que `jwt_secret`).
14. Ajouter le service **MinIO** à `deploy/docker-compose.yml` + les entrées de `deploy/.env.example`
    (identifiants de **développement**, jamais de secret réel).

### Backend — adapter entrant

15. Ajouter **`require_any_permission(*permissions)`** à `adapters/inbound/security.py`
    (`_mark_principal_guard`, `403` générique, documentée dans le mode d'emploi en tête de module).
16. Créer `adapters/inbound/salons.py` : les 7 routes du tableau *API / Interface Changes*.
    - **`POST /salons` : aucun champ `owner_id` / `status` / `opening_hours` dans le modèle Pydantic
      de requête.** `owner_id = principal.id`.
    - Revalider le préfixe de l'`object_key` (`salons/{salon_id}/…`) sur `PUT /logo` et
      `POST /photos`.
    - Traduire les erreurs de domaine (422 / 409 / 404 / 503) ; jamais `str(exc)` sur un refus RBAC.
17. Câbler dans `main.py` : `include_router(salons_router)` + `app.state.media_storage`
    (`None` si config S3 incomplète → `503` sur les routes médias **uniquement**).
18. **Ne pas** toucher à `PUBLIC_ROUTE_PATHS`.
19. Écrire `tests/test_salon_api.py`, `tests/test_salon_media_api.py`, `tests/test_salon_e2e.py`
    (dont la **régression #13** : le gérant obtient `201` sur `POST /salons/{id}/employees` une fois
    son salon créé).
20. Vérifier : `unprotected_routes(app)` vide, `test_domain_permissions.py` inchangé et vert,
    `test_secrets_policy.py` vert (étendu aux variables S3), `ruff check` propre.

### Web dashboard

21. `src/domain/salon/salon.ts` (type `Salon` + `isBookable`, **parité stricte** avec le backend).
22. `src/application/ports/salon-gateway.ts`, `src/application/use-cases/create-salon.ts`.
23. `src/adapters/api/http-salon-gateway.ts` (jeton lu du cookie **côté serveur** ; **ne jamais**
    journaliser jeton ni PII — patron `http-auth-gateway.ts`).
24. Routes BFF `app/api/salons/route.ts` (+ `app/api/salons/[id]/…`).
25. Page `app/(gerant)/gerant/parametres/page.tsx` : formulaire de création si aucun salon, sinon
    fiche + médias ; **bandeau « pas encore réservable — configurez vos horaires »** tant que
    `is_bookable === false`.
26. `src/domain/navigation/sections.ts` : `parametres` → `available` ; ajuster
    `test/navigation-sections.test.ts`.
27. Tests Vitest : `salon-domain`, `create-salon`, `http-salon-gateway`, extension de `bff-routes`.
28. `npm run lint`, `npm test`, `npm run build`.

### Documentation

29. Rédiger `docs/adr/0017-creation-salon-medias-et-reservabilite.md` + l'indexer dans
    `docs/adr/README.md`.
30. Mettre à jour `README.md` (racine, module 2 + section 6), `backend/README.md`,
    `web-dashboard/README.md`, `docs/environnements-et-secrets.md` (secrets S3).
31. Relire : **rien** dans la doc ne doit laisser entendre que les **horaires** (#16) ou la
    **réservation** (#21+) sont implémentés — ce spec livre la création du salon et le **prédicat**
    `is_bookable`, pas son application au moment de réserver.

### Vérification finale

32. `scripts/test-gate.sh` vert (parité CI : `pytest` + `npm test` + `flutter test`).
