# Ajout & gestion des prestations d'un salon (US-2.3, issue #17)

> Issue GitHub **#17** — `feature` · Priorité **Must** · Effort **M** · PRD §6 Épic 2
> Dépend de **#15** (création d'un salon) — livré. S'appuie aussi sur #12 (RBAC), #14 (shell dashboard).
> Troisième item du jalon **M2** (salons & prestations).

## Problem Statement

La tranche salon est livrée : un gérant crée son salon (#15, `POST /salons`) et configure ses
horaires (#16, `PUT /salons/{id}/opening-hours`). Le RBAC (#12) définit déjà les permissions
`SERVICE_MANAGE` (gérant) et `SERVICE_READ` (gérant, coiffeur, client), et le schéma PostgreSQL
contient **déjà** la table `services` (PRD §9.3, créée dans la migration initiale `0001`).

**Mais aucune prestation ne peut être créée, modifiée, listée ni supprimée** : il n'existe ni route
HTTP, ni cas d'usage, ni dépôt pour l'entité `Service`. Conséquences concrètes aujourd'hui :

- les permissions `SERVICE_MANAGE` / `SERVICE_READ` de la matrice §4.1 ne sont câblées sur **aucune**
  route ;
- la section **Prestations** du dashboard gérant (§7.2) est marquée `coming-soon` dans
  `web-dashboard/src/domain/navigation/sections.ts` — elle n'a aucun écran ;
- toute la suite M2–M3 est bloquée : la consultation client d'un salon (#18/#19, US-2.4) affiche
  « prestations, prix » et la réservation (#21+, US-3.1) exige de « choisir une prestation ». Sans
  catalogue de prestations, ces flux n'ont aucune donnée à présenter (`appointments.service_id` et la
  jonction `appointment_services` référencent un `service_id` qui n'existe pas).

US-2.3 demande de **gérer les prestations** : nom, durée, prix, description, catégorie ;
ajout/modification/suppression. Les critères d'acceptation sont : **(1)** prestations **CRUD par
salon** ; **(2)** **durée et prix obligatoires** ; **(3)** **modification journalisée (§11.4)**.

Le troisième critère est le point réellement nouveau : **aucune infrastructure de journalisation
(§11.4) n'existe encore** dans le dépôt. Le backend ne configure aucun logger applicatif (aucun
`import logging`), et #13 (« Création employé », pourtant listée au §11.4) n'a mis en place **aucune**
journalisation. #17 est donc la **première** issue dont un critère d'acceptation exige explicitement
la journalisation §11.4 — il faut donc **établir le mécanisme**, en le concevant pour être réutilisé
par les issues §11.4 suivantes (modification RDV, paiement, correction de caisse, désactivation salon).

## Goals

1. **CRUD complet des prestations, par salon** : créer, lister, consulter, modifier et supprimer
   (au sens §7 « désactiver ») une prestation **rattachée à un salon**, avec isolation stricte par
   salon (§11.2).
2. **Porter tous les champs de US-2.3** : `name`, `description`, `price`, `duration_minutes`,
   `category` (+ `is_active`) — exactement les champs déjà au schéma (PRD §9.3).
3. **Rendre durée et prix obligatoires et validés** : `price` requis et `>= 0`,
   `duration_minutes` requis et `> 0` — validés dans le domaine pur **avant** toute écriture (les
   contraintes `CHECK` de la table sont un filet de sécurité base, pas la validation métier).
4. **Journaliser les modifications (§11.4)** en établissant un **mécanisme d'audit réutilisable**
   (voir *Proposed Implementation* et *Open Questions* — décision recommandée : journal **persisté**),
   qui enregistre *qui* a fait *quelle* action sur *quelle* prestation de *quel* salon, *quand* —
   **sans jamais journaliser de secret ni de PII**.
5. **Réutiliser le socle existant sans le réinventer** : table `services` déjà au schéma, permissions
   `SERVICE_MANAGE` / `SERVICE_READ` déjà en matrice, gardes `require_permission` +
   `require_salon_scope`, patron de router/cas d'usage/dépôt de #15/#16.
6. **Permettre au gérant de gérer ses prestations depuis le dashboard** (#14) : faire passer la
   section **Prestations** de `coming-soon` à `available` (pas de nouvelle entrée de navigation).
7. **Ne pas affaiblir le deny-by-default** : aucune route publique ; toutes les routes sont protégées
   par permission **et** portée salon.

## Non-Goals

Ces sujets appartiennent à d'autres issues et **ne doivent pas** être implémentés ici :

- **Consultation client des prestations / catalogue public** (affichage §7 côté app mobile, liste et
  filtres par catégorie) — **#18/#19 (US-2.4)**, avec leurs propres règles de visibilité (§8.3 : seuls
  les salons `ACTIVE` sont visibles côté client). Ce spec n'ajoute **aucune** route de prestations
  publique ; la lecture y est réservée aux rôles du salon (gérant/coiffeur), pas au `CLIENT`.
- **Réservation d'une prestation** et **liaison RDV ↔ prestation** (`appointment_services`,
  `price_at_booking`) — **#21+ (US-3.1)**. Ce spec livre le **catalogue** de prestations ; il n'ajoute
  aucune logique de créneau, de disponibilité ni de prix figé à la réservation.
- **Statistiques « prestations les plus demandées »** (US-6.3) — M5.
- **Journal d'audit *exposé* (route de lecture du journal, écran admin de supervision)** — ce spec
  **écrit** les entrées d'audit ; leur **consultation** relève de la supervision plateforme (M5/M6).
  Aucune route de lecture du journal n'est ajoutée ici.
- **Généralisation de l'audit à toutes les actions §11.4** (RDV, paiement, caisse, désactivation
  salon) — #17 **établit le mécanisme** et le câble sur les prestations ; les autres actions le
  réutiliseront dans leurs issues respectives.
- **Réordonnancement / tri personnalisé des prestations, images par prestation, variantes/options,
  TVA/remises** — hors périmètre MVP (le schéma §9.3 ne les porte pas).

## Relevant Repository Context

### Architecture (figée par les ADR — source de vérité)

- **Backend** : Python ≥ 3.12, **FastAPI**, API REST, JWT ([ADR-0003](../docs/adr/0003-backend-fastapi.md)).
- **Architecture hexagonale** ([ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) :
  `domain/` (pur, zéro dépendance framework/I/O) → `application/` (cas d'usage + `ports/`) →
  `adapters/inbound/` (routers FastAPI) et `adapters/outbound/` (SQLAlchemy).
- **Données** : **PostgreSQL 16**, ORM **SQLAlchemy 2.0**, migrations **Alembic**
  ([ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md),
  [ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).
- **Autorisation** : RBAC **deny-by-default**
  ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) — gardes en **dépendances
  FastAPI**, pas en middleware ASGI.
- **Web gérant** : **Next.js** (App Router, TypeScript), zone protégée `/gerant`, BFF + cookie
  `httpOnly` ([ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md), #14).
- **Salon** : la tranche salon (#15/#16) est décrite par
  [ADR-0017](../docs/adr/0017-creation-salon-medias-et-reservabilite.md) et
  [ADR-0018](../docs/adr/0018-configuration-horaires-salon.md). Une prestation est **rattachée à un
  salon** (`services.salon_id`) : elle hérite de la même convention d'isolation par salon.

### Ce qui existe déjà et qu'il faut réutiliser (ne rien réinventer)

| Élément | Chemin | Rôle pour #17 |
| --- | --- | --- |
| Table `services` | `backend/coiflink_api/adapters/outbound/persistence/models.py:248` | **Déjà au schéma** (`0001_schema_initial`) : `id`, `salon_id`, `name`, `description`, `price` (`NUMERIC(12,2)`), `duration_minutes` (`INTEGER`), `category`, `is_active` (`bool`, défaut `true`), `created_at`, `updated_at`. `CHECK price >= 0`, `CHECK duration_minutes > 0`, `UniqueConstraint(salon_id, id)`, FK `salon_id → salons.id` **`ON DELETE RESTRICT`**, `Index(salon_id)`. **Aucune migration de structure `services` n'est nécessaire.** |
| Permissions | `backend/coiflink_api/domain/permissions.py:49` | `SERVICE_MANAGE` (MANAGER), `SERVICE_READ` (MANAGER, HAIRDRESSER, CLIENT). **Aucune permission nouvelle à créer.** |
| Gardes RBAC | `backend/coiflink_api/adapters/inbound/security.py` | `require_permission(...)`, `require_any_permission(...)`, `require_salon_scope` (lit `salon_id` **du chemin** — d'où la convention `/salons/{salon_id}/…`), `PUBLIC_ROUTE_PATHS`, invariant `unprotected_routes(app)`. **Aucune garde nouvelle.** |
| Patron « router protégé » | `backend/coiflink_api/adapters/inbound/salons.py` | Le modèle à copier : DI du cas d'usage, gardes composées, traduction erreurs de domaine → 404/409/422, `responses=` OpenAPI documentés, jamais `str(exc)` sur un refus RBAC. |
| Patron « cas d'usage » | `backend/coiflink_api/application/salons.py`, `.../employees.py` | Dépend **uniquement de ports**, `dataclass` de commande, validation avant écriture, `find_by_id` avant écriture pour distinguer `404`/`422`. |
| Patron « dépôt SQL » | `backend/coiflink_api/adapters/outbound/persistence/salon_repository.py` | `flush()` **sans** `commit()` (le commit est piloté par `get_session`), mapping ORM ↔ domaine, absence → erreur de **domaine**. |
| Patron « port » | `backend/coiflink_api/application/ports/salon_repository.py` | `Protocol`, docstrings, aucune dépendance framework. |
| Enums | `backend/coiflink_api/domain/enums.py` | `Role`, `SalonStatus`, `_StrEnum`, `values(...)`. Une action d'audit peut être un `_StrEnum` du même patron. |
| Erreurs de domaine | `backend/coiflink_api/domain/errors.py` | Ajouter `InvalidService*` / `ServiceNotFound` sur le patron de `InvalidSalonName` / `SalonNotFound` (messages neutres). |
| Fakes de test | `backend/tests/conftest.py` | À étendre : `FakeServiceRepository`, `FakeAuditLog` (patron `FakeSalonRepository`). |
| Session / commit | `backend/coiflink_api/adapters/outbound/persistence/session.py` | `get_session` pilote commit/rollback : l'audit **doit** partager la même `Session` que l'écriture métier (voir *Proposed Implementation*). |
| Navigation dashboard | `web-dashboard/src/domain/navigation/sections.ts:21` | Section `prestations` **déjà déclarée**, statut `coming-soon` → passer à `available`. |
| Passerelle front | `web-dashboard/src/adapters/api/http-salon-gateway.ts`, `app/api/salons/*` | Patron BFF + cookie `httpOnly` (jeton lu côté serveur, jamais exposé) à copier pour une `http-service-gateway`. |

### Écart / point d'attention identifié

1. **`suppression` (issue) vs `désactiver` (PRD §7)**. L'issue dit « suppression » ; le PRD §7 liste
   « Ajouter / Modifier / **Désactiver** une prestation » et la table porte `is_active`. Surtout, la FK
   `fk_appointment_services_service` est **`ON DELETE RESTRICT`** : une prestation déjà référencée par
   un rendez-vous **ne peut pas** être supprimée physiquement (la base le refuse). La conception doit
   donc trancher entre suppression physique et **désactivation** (soft-delete). Voir *Proposed
   Implementation* et *Open Questions* (recommandation : **désactivation** comme « suppression »
   canonique).

2. **Journalisation §11.4 inexistante**. Aucun logger ni table d'audit. #17 doit créer le mécanisme.
   Décision structurante à tracer (ADR de suivi recommandé) — voir *Open Questions*.

### Commandes (déjà en place, ne pas réinventer)

- Backend : `pytest`, `ruff check`, migrations Alembic (round-trip vérifié en CI contre PostgreSQL 16).
- Web : `npm test` (Vitest), `npm run lint`, `npm run build`.
- Test gate agrégé du pipeline : `scripts/test-gate.sh` (parité CI) — cf. `docs/strategie-de-tests.md`.

## Proposed Implementation

### Vue d'ensemble

Une **tranche verticale hexagonale** pour les prestations, calquée sur #15/#16, **plus** un mécanisme
d'**audit transverse** minimal et réutilisable pour honorer le critère §11.4.

```
domain/service.py                    (pur : entités, validation prix/durée/nom/catégorie)
domain/audit.py                      (pur : AuditAction, AuditEntry — vocabulaire du journal §11.4)
        ▲
application/services.py              (CreateService, ListSalonServices, GetService,
                                      UpdateService, DeactivateService[/DeleteService])
application/ports/service_repository.py     (port de persistance des prestations)
application/ports/audit_log.py              (port d'écriture du journal §11.4)
        ▲
adapters/inbound/services.py         (router FastAPI sous /salons/{salon_id}/services, gardes RBAC)
adapters/outbound/persistence/service_repository.py   (SQLAlchemy)
adapters/outbound/persistence/audit_log_repository.py (SQLAlchemy — écrit dans audit_logs)
```

### 1. Domaine — prestations (`backend/coiflink_api/domain/service.py`) — nouveau, pur

Module sans dépendance framework/I/O (ADR-0008). Entités et validation propres à la prestation.

```python
SERVICE_NAME_MAX_LENGTH = 255
CATEGORY_MAX_LENGTH = 128
_PRICE_MIN = decimal.Decimal("0")
# Bornes de robustesse (budget stockage/latence, PRD §12) — à confirmer :
_DURATION_MAX_MINUTES = 24 * 60          # une prestation ne dure pas plus d'une journée
_PRICE_MAX = decimal.Decimal("99999999.99")   # cohérent avec NUMERIC(12,2)

@dataclass(frozen=True)
class ServiceToCreate:        # intention d'écriture (salon_id imposé par la portée)
    salon_id: uuid.UUID
    name: str
    price: decimal.Decimal
    duration_minutes: int
    description: str | None = None
    category: str | None = None

@dataclass(frozen=True)
class ServiceUpdate:          # champs modifiables (partiel possible — voir PUT vs PATCH)
    name: str
    price: decimal.Decimal
    duration_minutes: int
    description: str | None = None
    category: str | None = None

@dataclass(frozen=True)
class Service:                # entité lue
    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    description: str | None
    price: decimal.Decimal
    duration_minutes: int
    category: str | None
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
```

Fonctions pures de validation (chacune lève une erreur de domaine neutre) :

- `validate_service_name(name) -> str` : `strip()`, non vide, `≤ SERVICE_NAME_MAX_LENGTH` →
  `InvalidServiceName` sinon. (Ne **pas** réutiliser `validate_salon_name` : erreur distincte,
  mappée distinctement.)
- `validate_price(price) -> Decimal` : **requis**, numérique, `>= 0`, `≤ _PRICE_MAX`, au plus 2
  décimales → `InvalidServicePrice` sinon. (Critère « prix obligatoire ».)
- `validate_duration(minutes) -> int` : **requis**, entier `> 0`, `≤ _DURATION_MAX_MINUTES` →
  `InvalidServiceDuration` sinon. (Critère « durée obligatoire ».)
- `normalize_category(category) -> str | None` : `strip()`, `None` si vide, `≤ CATEGORY_MAX_LENGTH`
  → `InvalidServiceCategory` sinon. Catégorie **libre** au MVP (pas d'énumération figée — le PRD ne
  fixe pas de liste ; voir *Open Questions*).

Nouvelles erreurs dans `domain/errors.py` (patron `InvalidSalonName`, ajout à `__all__`) :
`InvalidServiceName`, `InvalidServicePrice`, `InvalidServiceDuration`, `InvalidServiceCategory`,
`ServiceNotFound` (traduite en `404` **après** validation de portée).

### 2. Domaine — vocabulaire d'audit (`backend/coiflink_api/domain/audit.py`) — nouveau, pur

Le domaine définit **ce qui est journalisable** (§11.4) sans savoir *comment* c'est persisté :

```python
@unique
class AuditAction(_StrEnum):
    # Prestations (§11.4 « Modification prestation ») — #17.
    SERVICE_CREATED = "SERVICE_CREATED"
    SERVICE_UPDATED = "SERVICE_UPDATED"
    SERVICE_DEACTIVATED = "SERVICE_DEACTIVATED"
    SERVICE_REACTIVATED = "SERVICE_REACTIVATED"
    # (Les actions §11.4 futures — RDV, paiement, caisse, désactivation salon —
    #  s'ajouteront ici au fil des issues qui réutiliseront ce mécanisme.)

@dataclass(frozen=True)
class AuditEntry:
    """Une ligne du journal §11.4 — neutre, sans PII ni secret."""
    action: str                 # une valeur d'AuditAction
    actor_user_id: uuid.UUID    # qui (le Principal authentifié)
    salon_id: uuid.UUID | None  # portée
    entity_type: str            # "service"
    entity_id: uuid.UUID        # la prestation visée
    metadata: dict              # neutre : p.ex. {"changed": ["price", "duration_minutes"]}
```

**Contenu de `metadata` — règle de non-fuite** : n'y placer que des **noms de champs modifiés** et
des valeurs **non sensibles** strictement utiles à la traçabilité. Les champs d'une prestation
(nom, prix, durée, catégorie) sont des **données métier**, pas des données personnelles — mais le
`metadata` ne doit **jamais** contenir de PII (téléphone, adresse) ni de secret. Recommandation MVP :
stocker uniquement la **liste des champs modifiés** (`changed`), pas les valeurs avant/après, pour
minimiser le volume et écarter tout risque de fuite (voir *Open Questions* si l'audit « diff » est
souhaité plus tard).

### 3. Ports (`backend/coiflink_api/application/ports/`)

`service_repository.py` — `Protocol` :

```python
class ServiceRepository(Protocol):
    def create(self, service: ServiceToCreate) -> Service: ...
    def find_by_id(self, salon_id: uuid.UUID, service_id: uuid.UUID) -> Service | None: ...
    def list_for_salon(self, salon_id: uuid.UUID, *, include_inactive: bool = True) -> tuple[Service, ...]: ...
    def update(self, salon_id: uuid.UUID, service_id: uuid.UUID, changes: ServiceUpdate) -> Service: ...
    def set_active(self, salon_id: uuid.UUID, service_id: uuid.UUID, active: bool) -> Service: ...
    # (Optionnel, décision Open Questions) suppression physique conditionnelle :
    def delete(self, salon_id: uuid.UUID, service_id: uuid.UUID) -> bool: ...
```

> **Toutes** les méthodes portent `salon_id` **en plus** de `service_id` : les lectures/écritures
> filtrent sur le couple `(salon_id, id)` (isolation §11.2 **au niveau du dépôt**, jamais uniquement à
> l'entrée) — miroir de `delete_photo(salon_id, photo_id)` de #15.

`audit_log.py` — `Protocol` :

```python
class AuditLog(Protocol):
    def record(self, entry: AuditEntry) -> None:
        """Écrit une entrée du journal §11.4 dans la **même unité de travail** que
        l'action métier (même Session ⇒ commit/rollback atomique). Ne lève pas
        pour un contenu neutre bien formé ; ne journalise jamais de secret/PII."""
        ...
```

### 4. Application (`backend/coiflink_api/application/services.py`)

Cas d'usage dépendant **uniquement de ports** (`ServiceRepository`, `AuditLog`). Chaque **mutation**
enregistre une entrée d'audit **dans la même Session** que l'écriture métier (atomicité — patron
`CreateEmployee` qui écrit user + membership dans la même Session).

- **`CreateService`** : `execute(command, *, actor_user_id) -> Service`. `salon_id` provient de la
  **portée validée** (argument, pas du corps). Séquence : `validate_service_name` →
  `validate_price` → `validate_duration` → `normalize_category` → `repository.create(...)` →
  `audit.record(AuditEntry(SERVICE_CREATED, ...))`.
- **`ListSalonServices`** : `execute(salon_id, *, include_inactive) -> tuple[Service, ...]`. Lecture
  (pas d'audit). Le dashboard gérant liste actives **et** inactives ; le futur catalogue client
  (#18) ne verra que les actives — non traité ici.
- **`GetService`** : `execute(salon_id, service_id) -> Service` ; `ServiceNotFound` si absent.
- **`UpdateService`** : `execute(salon_id, service_id, changes, *, actor_user_id) -> Service`. Valide
  (prix/durée/nom obligatoires **restent** obligatoires), `find_by_id` avant écriture (→ `404` vs
  `422`), calcule les **champs modifiés** (diff neutre), écrit, puis
  `audit.record(SERVICE_UPDATED, metadata={"changed": [...]})`. **C'est le cœur du critère « modification
  journalisée ».**
- **`DeactivateService`** : `execute(salon_id, service_id, *, actor_user_id) -> Service`. Passe
  `is_active=False` (soft-delete = « suppression » canonique, voir *Open Questions*), audit
  `SERVICE_DEACTIVATED`. Une réactivation (`is_active=True`) journalise `SERVICE_REACTIVATED`.
- *(Optionnel — décision)* **`DeleteService`** : suppression **physique** autorisée **seulement** si
  la prestation n'est référencée par aucun rendez-vous ; sinon l'`IntegrityError` (`ON DELETE
  RESTRICT`) est retraduite en erreur de domaine `ServiceInUse` → `409`. Recommandation : **ne pas**
  livrer la suppression physique au MVP (désactivation suffit), pour éviter la perte de traçabilité et
  les incohérences d'historique. À confirmer.

### 5. Adapter entrant (`backend/coiflink_api/adapters/inbound/services.py`)

Router **imbriqué sous le salon** pour hériter de `require_salon_scope` (le `salon_id` est dans le
chemin) :

| Route | Garde(s) | Rôles effectifs (matrice §4.1) | Journalisé §11.4 |
| --- | --- | --- | --- |
| `POST /salons/{salon_id}/services` | `require_permission(SERVICE_MANAGE)` + `require_salon_scope` | **MANAGER** (son salon) | `SERVICE_CREATED` |
| `GET /salons/{salon_id}/services` | `require_permission(SERVICE_READ)` + `require_salon_scope` | MANAGER, HAIRDRESSER (son salon) | — |
| `GET /salons/{salon_id}/services/{service_id}` | `require_permission(SERVICE_READ)` + `require_salon_scope` | MANAGER, HAIRDRESSER (son salon) | — |
| `PUT /salons/{salon_id}/services/{service_id}` | `require_permission(SERVICE_MANAGE)` + `require_salon_scope` | **MANAGER** (son salon) | `SERVICE_UPDATED` |
| `DELETE /salons/{salon_id}/services/{service_id}` | `require_permission(SERVICE_MANAGE)` + `require_salon_scope` | **MANAGER** (son salon) | `SERVICE_DEACTIVATED` |

> **Choix `SERVICE_READ` + `require_salon_scope`** : bien que `CLIENT` détienne `SERVICE_READ`, il n'a
> **aucune portée** sur un salon dont il n'est ni gérant ni employé → `require_salon_scope` lui renvoie
> le `403` générique. La lecture *publique* client (sans portée salon) est **#18/#19**, avec sa propre
> route et ses règles §8.3. Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ici.

Schémas Pydantic (documentation OpenAPI incluse, patron `salons.py`) :

```python
class CreateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")   # aucun salon_id/id/is_active accepté du corps
    name: str = Field(min_length=1, max_length=255, examples=["Coupe homme"])
    price: Decimal = Field(examples=["5000.00"])            # requis
    duration_minutes: int = Field(examples=[30])            # requis
    description: str | None = Field(default=None)
    category: str | None = Field(default=None, examples=["Coupe"])

class UpdateServiceRequest(CreateServiceRequest):
    """Mêmes champs (sémantique *replace*) — prix/durée restent requis."""

class ServiceResponse(BaseModel):
    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int
    category: str | None
    is_active: bool
    created_at: object
    updated_at: object
```

- L'**actor** de l'audit est `principal.id` (le `Principal` renvoyé par `require_permission`), passé
  en argument `actor_user_id` aux cas d'usage de mutation — **jamais** lu du corps.
- **Traduction des erreurs** (patron `salons.py`, jamais `str(exc)` sur un refus RBAC) :
  `InvalidServiceName` / `InvalidServicePrice` / `InvalidServiceDuration` / `InvalidServiceCategory` →
  **422** ; `ServiceNotFound` → **404** *(seulement après portée validée)* ; *(si suppression physique
  livrée)* `ServiceInUse` → **409**.
- **Ne pas** ajouter les chemins à `PUBLIC_ROUTE_PATHS`. Câbler le router dans `main.py`
  (`include_router(services_router)`).

### 6. Adapter sortant — persistance des prestations (`.../persistence/service_repository.py`)

`SqlServiceRepository` sur le patron `SqlSalonRepository` : `flush()` **sans** `commit()`,
mapping ORM `models.Service` ↔ domaine `Service`, filtre systématique sur `(salon_id, id)`, retraduit
l'absence en `ServiceNotFound` et *(si suppression physique)* l'`IntegrityError` de la FK RESTRICT en
`ServiceInUse`.

### 7. Adapter sortant — journal d'audit (`.../persistence/audit_log_repository.py`)

`SqlAuditLog` implémente le port `AuditLog` sur la **même `Session`** que l'écriture métier (injectée
via `get_session`, comme les dépôts). Il insère une ligne dans la **nouvelle table `audit_logs`**
(voir *Data Model*). `flush()` sans `commit()` : l'entrée d'audit et l'action métier sont committées
**ensemble** — si l'action échoue, l'audit est rollbacké (pas d'audit « fantôme »), et réciproquement.

> **Alternative plus légère** (voir *Open Questions* #1) : un `LoggingAuditLog` écrivant une ligne de
> log structurée (module `logging` standard, niveau `INFO`, sans PII) au lieu d'une table. Simple, sans
> migration, mais **non durable ni requêtable** (les logs Railway tournent). Recommandation : **journal
> persisté** (durable, base de la supervision §11.3 et des issues §11.4 suivantes).

### 8. Web dashboard (`web-dashboard/`)

Cible : la section **Prestations** (déjà déclarée `coming-soon`).

- `src/domain/navigation/sections.ts` : `prestations` → `available` ; ajuster
  `test/navigation-sections.test.ts`.
- `src/domain/service/service.ts` — type `Service` + validateur `validateService(...)` **parité
  stricte** avec le domaine Python (prix `>= 0`, durée `> 0`, nom non vide). Tester la parité.
- `src/application/ports/service-gateway.ts` — port `ServiceGateway` (`list`, `create`, `update`,
  `deactivate`) + un type de résultat aux motifs génériques (`invalid` / `forbidden` /
  `unauthenticated` / `not-found`).
- `src/adapters/api/http-service-gateway.ts` — appelle le backend **côté serveur**, jeton lu du cookie
  `httpOnly`, **jamais** journalisé ni exposé au navigateur (patron `http-salon-gateway.ts`).
- `app/api/salons/[id]/services/route.ts` (+ `.../[serviceId]/route.ts`) — routes BFF.
- `app/(gerant)/gerant/prestations/page.tsx` — Server Component : liste des prestations du salon du
  gérant (actives + inactives, badge « désactivée »), formulaire d'ajout, édition en ligne,
  bouton « désactiver ». S'appuie sur le salon déjà chargé (0 salon → message « créez d'abord votre
  salon »).
- `src/adapters/ui/service-form.tsx` — formulaire client (nom, prix, durée, description, catégorie),
  validation côté client avant envoi (le backend reste l'autorité).

## Affected Files / Packages / Modules

### `backend/` (paquet principal)

**À créer**
- `coiflink_api/domain/service.py`
- `coiflink_api/domain/audit.py`
- `coiflink_api/application/services.py`
- `coiflink_api/application/ports/service_repository.py`
- `coiflink_api/application/ports/audit_log.py`
- `coiflink_api/adapters/inbound/services.py`
- `coiflink_api/adapters/outbound/persistence/service_repository.py`
- `coiflink_api/adapters/outbound/persistence/audit_log_repository.py`
- `migrations/versions/0004_audit_logs.py` (`down_revision = "0003"`) — table `audit_logs`
- Tests : `tests/test_domain_service.py`, `tests/test_domain_audit.py`,
  `tests/test_service_usecases.py`, `tests/test_service_api.py`, `tests/test_service_e2e.py`,
  `tests/test_audit_log.py`

**À modifier**
- `coiflink_api/domain/errors.py` — `InvalidServiceName`, `InvalidServicePrice`,
  `InvalidServiceDuration`, `InvalidServiceCategory`, `ServiceNotFound`, *(opt.)* `ServiceInUse` (+ `__all__`)
- `coiflink_api/adapters/outbound/persistence/models.py` — modèle ORM `AuditLog` (**source de vérité
  du schéma** — la table `services` existe déjà, elle n'est pas modifiée)
- `coiflink_api/main.py` — `include_router(services_router)` + assemblage `SqlAuditLog`
- `tests/conftest.py` — `FakeServiceRepository`, `FakeAuditLog`
- `tests/test_secrets_policy.py` — vérifier qu'aucune entrée d'audit ne porte de secret/PII (au besoin)
- `backend/README.md` — routes prestations + note sur le journal §11.4

**À NE PAS modifier**
- `models.py::Service` (déjà au schéma), `domain/permissions.py` (aucune permission nouvelle),
  `security.py` (aucune garde nouvelle), `PUBLIC_ROUTE_PATHS`.

### `web-dashboard/`

**À créer** : `src/domain/service/service.ts`, `src/application/ports/service-gateway.ts`,
`src/adapters/api/http-service-gateway.ts`, `src/adapters/ui/service-form.tsx`,
`app/api/salons/[id]/services/route.ts`, `app/api/salons/[id]/services/[serviceId]/route.ts`,
`app/(gerant)/gerant/prestations/page.tsx`, tests Vitest associés.

**À modifier** : `src/domain/navigation/sections.ts` (`prestations` → `available`),
`test/navigation-sections.test.ts`, `README.md`.

### Racine / docs

- `docs/adr/0019-…md` (ADR de suivi recommandé : mécanisme de journalisation §11.4 + soft-delete des
  prestations) ; `docs/adr/README.md` (index).
- `README.md` (racine) — module 2 « Gestion des salons » (prestations) et section 6 (« M2 en cours »).

## API / Interface Changes

**Nouvelles routes REST** (toutes **protégées** ; aucun ajout à `PUBLIC_ROUTE_PATHS`), imbriquées sous
`/salons/{salon_id}/services` pour hériter de `require_salon_scope` :

### `POST /salons/{salon_id}/services` → `201 Created`

```jsonc
// Requête — AUCUN salon_id / id / is_active dans le corps
{
  "name": "Coupe homme",       // requis, 1..255
  "price": "5000.00",          // requis, >= 0
  "duration_minutes": 30,      // requis, > 0
  "description": "Coupe aux ciseaux et finitions.",
  "category": "Coupe"          // optionnel, libre
}
```

```jsonc
// Réponse 201
{
  "id": "…uuid…", "salon_id": "…uuid…",
  "name": "Coupe homme", "description": "…",
  "price": "5000.00", "duration_minutes": 30, "category": "Coupe",
  "is_active": true, "created_at": "…", "updated_at": "…"
}
```

Codes : `201` · `401` · `403` (rôle ≠ MANAGER **ou** salon hors périmètre — générique) · `422`
(nom/prix/durée/catégorie invalides). **Journalise** `SERVICE_CREATED`.

### Autres routes

| Route | Réponse | Codes notables | Audit |
| --- | --- | --- | --- |
| `GET /salons/{salon_id}/services` | `ServiceResponse[]` | `200`, `401`, `403` | — |
| `GET /salons/{salon_id}/services/{service_id}` | `ServiceResponse` | `200`, `401`, `403`, `404` | — |
| `PUT /salons/{salon_id}/services/{service_id}` | `ServiceResponse` | `200`, `401`, `403`, `404`, `422` | `SERVICE_UPDATED` |
| `DELETE /salons/{salon_id}/services/{service_id}` | `204` (désactivation) | `204`, `401`, `403`, `404` *(, `409` si suppression physique livrée)* | `SERVICE_DEACTIVATED` |

> **Sémantique de `DELETE`** : par défaut **désactivation** (`is_active=false`) — voir *Open Questions*
> #2. Documenter clairement le comportement retenu dans l'OpenAPI et le README (ne pas laisser croire à
> une suppression physique si ce n'en est pas une).

**Nouvelles interfaces internes documentées** : ports `ServiceRepository` et `AuditLog` (docstrings de
module) ; enum `AuditAction` et `AuditEntry` (`domain/audit.py`) ; cas d'usage de
`application/services.py`.

**Variables d'environnement** : aucune nouvelle attendue (le journal partage la base PostgreSQL
existante). **CLI** : aucun changement.

## Data Model / Protocol Changes

**Table `services`** : **aucune modification**. Tous les champs de US-2.3 existent déjà (§9.3,
migration `0001`), y compris les contraintes `CHECK price >= 0` / `CHECK duration_minutes > 0` et
l'unicité `(salon_id, id)`. Aucune migration de structure pour les prestations.

**Nouvelle table `audit_logs`** — support du journal §11.4 (le point réellement nouveau). Modèle ORM
dans `models.py` (**source de vérité**) + migration Alembic **`0004_audit_logs.py`**
(`down_revision = "0003"`), reflet exact, avec `downgrade()` réversible :

| Colonne | Type | Contraintes |
| --- | --- | --- |
| `id` | `UUID` | PK, `server_default gen_random_uuid()` |
| `action` | `TEXT` (≤ 64) | non nul — valeur d'`AuditAction` |
| `actor_user_id` | `UUID` | non nul, **FK → `users.id` `ON DELETE RESTRICT`**, indexé (qui) |
| `salon_id` | `UUID` | **nullable**, FK → `salons.id` `ON DELETE RESTRICT`, indexé (portée) |
| `entity_type` | `TEXT` (≤ 64) | non nul (`"service"`) |
| `entity_id` | `UUID` | non nul (la prestation) |
| `metadata` | `JSONB` | non nul, défaut `{}` — **neutre** (noms de champs modifiés ; ni PII ni secret) |
| `created_at` | `timestamptz` | non nul, défaut `now()`, indexé (ordre chronologique) |

Index : `ix_audit_logs_salon_id_created_at (salon_id, created_at desc)`,
`ix_audit_logs_entity (entity_type, entity_id)`, `ix_audit_logs_actor (actor_user_id)`.

> **`ON DELETE RESTRICT`** sur `actor_user_id`/`salon_id` : un journal d'audit **ne doit pas** perdre
> ses lignes quand un compte/salon est supprimé (traçabilité). Cohérent avec la convention `RESTRICT`
> par défaut du module (`models.py` en-tête). À justifier dans la docstring de la migration.

**Atomicité** : l'entrée d'audit est écrite dans la **même `Session`/transaction** que l'action
métier (commit/rollback conjoints via `get_session`).

**Compatibilité** : la table `services` étant aujourd'hui vide (aucune route ne la peuplait), il n'y a
**aucune donnée existante** à migrer. `audit_logs` est une table neuve.

**Validation** : dans le **domaine** (`domain/service.py`), pas seulement par les `CHECK` SQL (qui
restent un filet de sécurité). Cohérent avec la frontière hexagonale.

## Security & Privacy Considerations

Contraintes **documentées** par le dépôt et touchées par ce changement :

1. **RBAC deny-by-default** ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) —
   *invariant à ne jamais affaiblir*. Les routes sont sous `/salons/{salon_id}/services`, protégées par
   `require_permission(SERVICE_MANAGE|SERVICE_READ)` **et** `require_salon_scope`. Aucun chemin ajouté
   à `PUBLIC_ROUTE_PATHS` ; `unprotected_routes(app)` doit rester **vide** (couvert par
   `test_security_guards.py`).

2. **Isolation par salon** (PRD §11.2) — chaque route porte `salon_id` dans le chemin ; l'accès
   inter-salons renvoie le **`403` générique** (message constant, **aucun oracle d'existence**). Le
   `404` `ServiceNotFound` n'est renvoyé qu'**après** validation de portée. En profondeur, le **dépôt**
   filtre sur `(salon_id, service_id)` : impossible de lire/modifier/désactiver la prestation d'un
   autre salon même si l'`service_id` est deviné.

3. **Anti-élévation / champs privilégiés** — `salon_id`, `id`, `is_active` et l'**acteur** de l'audit
   ne sont **jamais** lus du corps : `salon_id` vient du chemin (portée validée), l'acteur vient du
   `Principal`. `is_active` ne se change que via la route `DELETE` (désactivation) / une réactivation
   explicite, jamais par un champ libre de `PUT`.

4. **Journalisation §11.4 — ne jamais fuiter** (PRD §11.3/§11.4, invariant du dépôt) :
   - le `metadata` d'audit est **neutre** : noms de champs modifiés uniquement (recommandation MVP),
     **jamais** de secret (jeton, hash) ni de PII (téléphone/adresse) ;
   - l'`actor_user_id` est un **UUID opaque** (pas le nom ni le téléphone de la personne) ;
   - le journal ne remplace pas et n'expose pas les secrets : `test_secrets_policy.py` reste vert.
   - Le journal enregistre *l'action*, pas *le contenu sensible* — les valeurs d'une prestation (prix)
     sont métier et non personnelles, mais rester minimal écarte tout risque.

5. **Validation d'entrée stricte** : prix/durée/nom obligatoires et bornés dans le domaine avant
   écriture ; catégorie bornée. Bornes de robustesse (durée ≤ 24 h, prix ≤ `NUMERIC(12,2)`) pour éviter
   des valeurs aberrantes (budget PRD §12).

6. **Front (#14)** : le jeton d'accès reste dans un cookie `httpOnly`, lu **côté serveur** par le BFF ;
   il n'atteint jamais le navigateur. La passerelle ne journalise ni jeton ni PII.

Le dépôt ne documente **aucune contrainte de résidence ou de chiffrement spécifique** aux prestations
(donnée métier non sensible) au-delà des invariants ci-dessus. La journalisation, elle, matérialise
« Journalisation des accès sensibles » (§11.3) et la liste §11.4.

## Testing Plan

### Backend — unitaires (`pytest`, sans base ni réseau)

- `tests/test_domain_service.py` :
  - `validate_service_name` : vide / espaces / > 255 → `InvalidServiceName` ; `strip()` appliqué ;
  - `validate_price` (**prix obligatoire**) : `None` / non numérique → erreur ; négatif → erreur ;
    `> _PRICE_MAX` → erreur ; > 2 décimales → erreur ; `0` et `5000.00` → acceptés ;
  - `validate_duration` (**durée obligatoire**) : `None` / `0` / négatif → erreur ; `> 24 h` → erreur ;
    `30` → accepté ;
  - `normalize_category` : vide → `None` ; > 128 → erreur ; trim appliqué.
- `tests/test_domain_audit.py` : `AuditAction` fermé ; `AuditEntry` neutre (aucun champ PII) ;
  construction du diff `changed` (ensemble des champs modifiés, ordre stable).
- `tests/test_service_usecases.py` (fakes de `conftest.py`) :
  - `CreateService` : `salon_id` vient de l'argument (portée), pas du corps ; validation **avant**
    écriture ; **une entrée `SERVICE_CREATED`** enregistrée avec le bon acteur ;
  - `UpdateService` : `ServiceNotFound` si absent ; **une entrée `SERVICE_UPDATED`** avec
    `metadata.changed` correct (cœur du critère « modification journalisée ») ; aucune entrée si la
    validation échoue (rien n'est écrit, rien n'est journalisé) ;
  - `DeactivateService` : passe `is_active=false`, **entrée `SERVICE_DEACTIVATED`** ; réactivation →
    `SERVICE_REACTIVATED` ;
  - **atomicité** : si l'écriture métier échoue, aucune entrée d'audit n'est « laissée » (via le fake,
    vérifier l'ordre d'appel et l'absence d'entrée en cas d'exception).

### Backend — API / intégration (`TestClient`, `dependency_overrides`)

- `tests/test_service_api.py` :
  - **matrice RBAC** : `MANAGER` (son salon) → `201/200/204` ; `HAIRDRESSER` → `200` en lecture,
    `403` sur les mutations (pas `SERVICE_MANAGE`) ; `CLIENT` → `403` (pas de portée salon) ; `ADMIN` →
    `403` (l'admin supervise, il n'exploite pas — §4.1) ; sans jeton → `401` ;
  - **isolation** : `MANAGER` visant le salon d'un **autre** gérant → `403` **générique** (pas `404`) ;
    `GET/PUT/DELETE` d'un `service_id` d'un autre salon → `403`/`404` sans fuite ;
  - **validation** : corps sans `price` ou sans `duration_minutes` → `422` ; prix négatif / durée nulle
    → `422` ;
  - **journalisation** : après `PUT`, une entrée d'audit `SERVICE_UPDATED` existe (via un `FakeAuditLog`
    ou une lecture directe du dépôt d'audit en test d'intégration) ;
  - **réponse** : ne contient aucun secret ; `is_active` reflété.
- `tests/test_audit_log.py` : `SqlAuditLog.record` insère une ligne neutre ; committée **avec**
  l'action métier (rollback conjoint testé).
- `tests/test_security_guards.py` (existant) : `unprotected_routes(app)` reste **vide**.
- `tests/test_domain_permissions.py` (existant) : inchangé et vert (aucune permission nouvelle).

### Backend — end-to-end (`tests/test_service_e2e.py`, patron `test_salon_e2e.py`)

Parcours : inscription gérant (#9) → login (#10) → `POST /salons` (#15) →
`POST /salons/{id}/services` → `GET …/services` (la prestation apparaît) →
`PUT …/services/{sid}` (modification) → `GET …/services/{sid}` (valeurs à jour) →
`DELETE …/services/{sid}` (désactivée, `is_active=false`) → vérifier qu'une **trace d'audit** existe
pour la création, la modification et la désactivation.

### Migration

Round-trip Alembic `upgrade` → `downgrade` contre **PostgreSQL 16** (job `backend`) pour
`0004_audit_logs.py` ; vérifier que `models.py` (modèle `AuditLog`) et la migration ne divergent pas.

### Web dashboard (Vitest)

- `test/service-domain.test.ts` — validateur TS : **mêmes cas** que le domaine Python (prix, durée,
  nom) — parité stricte ;
- `test/service-gateway.test.ts` / extension `http-service-gateway` — mapping `200/201/204/401/403/404/422` ;
  **le jeton n'est jamais journalisé ni renvoyé au client** ;
- extension des tests de routes BFF — `/api/salons/[id]/services*` exigent le cookie de session ;
- `test/navigation-sections.test.ts` (existant) — `prestations` passe à `available`.

## Documentation Updates

- **ADR de suivi recommandé** (`docs/adr/0019-journalisation-audit-et-prestations.md`) : le dépôt trace
  chaque décision structurante (0015–0018). À couvrir : (a) le **mécanisme de journalisation §11.4**
  (table `audit_logs` persistée vs logs structurés, port `AuditLog`, atomicité même-Session,
  vocabulaire `AuditAction` extensible) ; (b) « **suppression = désactivation** » des prestations
  (`is_active`, FK RESTRICT depuis `appointment_services`) ; (c) sémantique *replace* du `PUT` ;
  (d) catégorie libre au MVP. Indexer dans `docs/adr/README.md`. *(Alternative : docstrings + README si
  l'ADR est jugé disproportionné — voir Open Questions.)*
- **`README.md` (racine)** : module 2 « Gestion des salons » — mentionner les routes
  `/salons/{id}/services` (CRUD) et la journalisation §11.4. Mettre à jour la section 6 (M2 : #17 livré
  après #16).
- **`backend/README.md`** : routes prestations, comportement du `DELETE` (désactivation), note sur le
  journal `audit_logs` (§11.4) et l'invariant « aucun secret/PII dans l'audit ».
- **`web-dashboard/README.md`** : section Prestations (liste, ajout, édition, désactivation).
- **OpenAPI** : `summary`/`responses`/docstrings des routes (documentation publique de l'API).

## Risks and Open Questions

### Décisions à confirmer

1. **Journal §11.4 : table persistée vs logs structurés** *(recommandé : table persistée)*. Aucune
   infra n'existe. Une **table `audit_logs`** est durable, requêtable et sert de base à la supervision
   (§11.3) et aux issues §11.4 suivantes ; coût : une migration + un port. Un **logger structuré** est
   plus léger (aucune migration) mais éphémère (logs Railway rotatifs) et non requêtable.
   **Recommandation : table persistée.** À confirmer, car c'est un choix d'architecture transverse.

2. **« Suppression » = désactivation (soft-delete) ou suppression physique ?** *(recommandé :
   désactivation)*. La FK `fk_appointment_services_service` est **`ON DELETE RESTRICT`** : une
   prestation référencée par un RDV **ne peut pas** être supprimée physiquement. La désactivation
   (`is_active=false`) préserve l'historique et le prix figé des RDV passés (`price_at_booking`), et
   correspond au PRD §7 (« Désactiver une prestation »). **Recommandation : `DELETE` = désactivation**,
   pas de suppression physique au MVP ; réactivation possible. Alternative : autoriser la suppression
   physique **uniquement** si la prestation n'est référencée par aucun RDV (`409 ServiceInUse` sinon) —
   plus proche du mot « suppression » de l'issue mais plus risqué. À trancher **avant** l'implémentation
   (impacte le contrat du `DELETE`).

3. **Étendue de la journalisation** : le critère dit « **modification** journalisée ». Faut-il aussi
   journaliser la **création** et la **désactivation** ? **Recommandation : journaliser toutes les
   mutations** (create/update/deactivate/reactivate) pour une traçabilité cohérente ; le minimum exigé
   reste la modification. À confirmer.

4. **Contenu du `metadata` d'audit** : liste des **champs modifiés** seulement (recommandé, minimal),
   ou **diff avant/après** des valeurs (plus riche, mais volume et prudence accrus) ? Recommandation :
   `changed` (noms de champs) au MVP ; le diff détaillé pourra venir plus tard sous réserve de
   confirmer qu'aucune valeur sensible n'y entre.

5. **Catégorie : libre ou énumérée ?** Le PRD ne fixe pas de liste de catégories. **Recommandation :
   texte libre borné** au MVP (une énumération figée relèverait d'une décision produit ultérieure).

6. **`PUT` (replace) vs `PATCH` (partiel)** pour la modification : `PUT` remplace tous les champs
   (prix/durée restent requis), simple à raisonner et à journaliser. **Recommandation : `PUT`
   replace.** Un `PATCH` partiel compliquerait le calcul du diff et la garantie « prix/durée toujours
   présents ». À confirmer.

7. **ADR dédié ou docstrings ?** Le mécanisme d'audit §11.4 est structurant (réutilisé par plusieurs
   issues). **Recommandation : ADR-0019** ; à défaut, docstrings + README.

### Risques

- **Divergence de parité front/back du validateur** (prix/durée) : deux implémentations (Python + TS)
  des mêmes règles. Mitigation : tests de parité explicites ; le backend reste l'autorité.
- **Sur-ingénierie de l'audit** : introduire un sous-système d'audit trop générique gonflerait l'effort
  au-delà de « M ». Mitigation : livrer un mécanisme **minimal** (une table, un port, un enum), câblé
  **uniquement** sur les prestations dans #17 ; les autres actions §11.4 le réutiliseront sans le
  ré-architecturer.
- **Atomicité audit ↔ action** : si l'audit était écrit hors transaction, un rollback métier
  laisserait une trace « fantôme » (ou l'inverse). Mitigation : **même `Session`**, commit conjoint via
  `get_session` (patron `CreateEmployee`).
- **Prestation référencée par un RDV** (une fois #21+ livré) : un `DELETE` physique échouerait
  (`RESTRICT`). La désactivation contourne le problème — d'où la recommandation #2.
- **Le dashboard suppose 0 ou 1 salon** (héritage #15). Si un gérant a N salons, l'écran Prestations
  devra suivre le même sélecteur que la fiche salon — à cadrer avec l'évolution multi-salon de l'UI.

## Implementation Checklist

> Ordre conçu pour vérifier chaque étape isolément (domaine → application → adapters → UI).

### Backend — domaine

1. Créer `domain/service.py` : bornes, `ServiceToCreate`, `ServiceUpdate`, `Service`,
   `validate_service_name`, `validate_price`, `validate_duration`, `normalize_category`. Zéro import
   framework/I/O.
2. Créer `domain/audit.py` : `AuditAction` (`_StrEnum` fermé), `AuditEntry` (neutre). Zéro I/O.
3. Ajouter les erreurs à `domain/errors.py` (`InvalidServiceName`, `InvalidServicePrice`,
   `InvalidServiceDuration`, `InvalidServiceCategory`, `ServiceNotFound`, *(opt.)* `ServiceInUse`) +
   `__all__`.
4. Écrire `tests/test_domain_service.py` et `tests/test_domain_audit.py`. ✅ verts avant de continuer.

### Backend — application

5. Créer les ports `application/ports/service_repository.py` et `application/ports/audit_log.py`
   (`Protocol`, docstrings, `salon_id` systématique côté service repo).
6. Créer `application/services.py` : `CreateService`, `ListSalonServices`, `GetService`,
   `UpdateService`, `DeactivateService` *(+ `DeleteService` si décision #2)*. Chaque mutation écrit une
   `AuditEntry` **dans la même Session** ; validation avant écriture ; `find_by_id` avant update/deactivate.
7. Étendre `tests/conftest.py` (`FakeServiceRepository`, `FakeAuditLog`) et écrire
   `tests/test_service_usecases.py` (dont **`SERVICE_UPDATED` avec `metadata.changed`** et l'atomicité).

### Backend — persistance & migration

8. Ajouter le modèle ORM `AuditLog` à `models.py` (conventions de l'en-tête : `_pk()`, `_created_at()`,
   FK `RESTRICT`, index) + `__all__`.
9. Écrire `migrations/versions/0004_audit_logs.py` (`down_revision = "0003"`), reflet exact,
   `downgrade()` réversible, docstring justifiant `RESTRICT`.
10. Créer `adapters/outbound/persistence/service_repository.py` (`SqlServiceRepository`, filtre
    `(salon_id, id)`, `flush()` sans `commit()`, `ServiceNotFound`, *(opt.)* `IntegrityError → ServiceInUse`).
11. Créer `adapters/outbound/persistence/audit_log_repository.py` (`SqlAuditLog`, même Session,
    `flush()` sans `commit()`).
12. Vérifier le round-trip Alembic contre PostgreSQL 16.

### Backend — adapter entrant

13. Créer `adapters/inbound/services.py` : schémas Pydantic (aucun `salon_id`/`id`/`is_active` du
    corps) et les 5 routes du tableau (`require_permission(SERVICE_MANAGE|SERVICE_READ)` +
    `require_salon_scope`). L'acteur d'audit = `principal.id`.
14. Traduire les erreurs (422 / 404 / *(opt.)* 409) ; jamais `str(exc)` sur un refus RBAC. **Ne pas**
    toucher à `PUBLIC_ROUTE_PATHS`.
15. Câbler dans `main.py` : `include_router(services_router)` + assemblage `SqlAuditLog`.
16. Écrire `tests/test_service_api.py`, `tests/test_audit_log.py`, `tests/test_service_e2e.py`.
17. Vérifier : `unprotected_routes(app)` vide, `test_domain_permissions.py` et `test_secrets_policy.py`
    verts, `ruff check` propre.

### Web dashboard

18. `src/domain/service/service.ts` (type + `validateService`, **parité stricte** avec le backend) ;
    tests `service-domain`.
19. `src/application/ports/service-gateway.ts` + `src/adapters/api/http-service-gateway.ts` (jeton du
    cookie côté serveur, aucune journalisation de jeton/PII).
20. Routes BFF `app/api/salons/[id]/services/route.ts` (+ `.../[serviceId]/route.ts`).
21. `src/adapters/ui/service-form.tsx` + `app/(gerant)/gerant/prestations/page.tsx` (liste + ajout +
    édition + désactivation) ; validation client avant envoi.
22. `src/domain/navigation/sections.ts` : `prestations` → `available` ; ajuster
    `test/navigation-sections.test.ts`.
23. Tests Vitest ; `npm run lint`, `npm test`, `npm run build`.

### Documentation

24. Rédiger l'ADR-0019 (mécanisme §11.4 + soft-delete prestations + replace + catégorie libre) et
    l'indexer dans `docs/adr/README.md` *(ou docstrings + README si jugé disproportionné — décision 7)*.
25. Mettre à jour `README.md` (racine, module 2 + section 6), `backend/README.md`,
    `web-dashboard/README.md`.
26. Relire : rien dans la doc ne doit laisser entendre que la **réservation** (#21+) ou le **catalogue
    client public** (#18/#19) existent — ce spec livre le **CRUD des prestations** et la
    **journalisation** de leurs modifications.

### Vérification finale

27. `scripts/test-gate.sh` vert (parité CI : `pytest` + `npm test` + `flutter test`).
