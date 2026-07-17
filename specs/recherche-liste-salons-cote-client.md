# Recherche & liste des salons (côté client) — US-2.3 / issue #18

> Issue GitHub **#18** — `feature` `ux` · Priorité **Must** · Effort **M** · PRD §7.1 (écran
> « Recherche de salons »), §5.1 (parcours client, étape 3 « il recherche un salon »), §8.3
> (visibilité : « un salon inactif ne doit plus être visible dans l'application client »).
> **Dépend de #15** (création d'un salon — livrée). Jalon **M2** (salons & prestations).

## Problem Statement

Un gérant peut désormais créer son salon (#15), configurer ses horaires (#16) et ses prestations
(#17). Toute cette matière est **invisible pour le client** : il n'existe **aucun moyen, côté
client, de lister ou de rechercher les salons**.

Deux manques concrets, l'un côté backend, l'autre côté application cliente :

1. **Backend** — les seules routes de lecture de salons sont orientées **gestion** :
   - `GET /salons` (`SqlSalonRepository.list_for_owner`) liste les salons **du gérant authentifié**
     (`require_permission(SALON_READ_OWN)`) ;
   - `GET /salons/{salon_id}` exige `require_salon_scope` (le salon doit être **dans le périmètre**
     du principal — gérant propriétaire, coiffeur membre, ou admin).

   Aucune de ces routes ne convient à un client : un client n'est ni propriétaire, ni membre. La
   permission `SALON_READ_ANY` du rôle `CLIENT` (matrice §4.1,
   `backend/coiflink_api/domain/permissions.py:87`) **n'est câblée sur aucune route**. Il n'existe
   donc **aucun catalogue** de salons destiné au client, ni **aucun filtre `status = ACTIVE`** (la
   règle de visibilité §8.3).

2. **Application cliente (Flutter, `app-mobile/`)** — le paquet est un **squelette d'initialisation**
   (#2) : `main.dart` → `adapters/ui/app.dart` n'affiche qu'un écran d'accueil neutre (« CoifLink »).
   Il n'a **ni couche réseau, ni client HTTP, ni domaine, ni cas d'usage, ni configuration
   d'URL d'API**. L'écran §7.1 « Recherche de salons » n'existe pas, et rien ne permet encore
   d'appeler le backend.

**Critère d'acceptation (issue #18)** : *un client liste/recherche les salons actifs ; un salon
désactivé n'apparaît pas.* Le cœur testable est donc : (a) un endpoint qui **ne renvoie que les
salons `ACTIVE`**, avec recherche/filtre ; (b) un écran client qui l'affiche.

## Goals

1. **Exposer un catalogue de salons côté client** : un point d'entrée HTTP qui liste et recherche
   les salons **`ACTIVE` uniquement** (§8.3), avec au minimum une **recherche par nom** et un
   **filtre par zone** (ville / commune), et une **pagination** bornée.
2. **Garantir la règle §8.3 de manière testable** : un salon `INACTIVE`/`SUSPENDED` **n'apparaît
   jamais** dans les résultats ni dans la consultation par identifiant côté client. Le filtre est
   appliqué **au niveau de la requête SQL** (jamais en post-filtrage applicatif faillible).
3. **Ne renvoyer qu'une projection publique** du salon : les champs de vitrine (nom, description,
   localisation, logo signé, `is_bookable`), **sans** `owner_id` ni aucune donnée de gestion.
4. **Poser la couche réseau de l'application mobile** (client HTTP, configuration de l'URL d'API,
   gestion d'erreurs, mapping JSON → domaine) — première brique data du paquet `app-mobile/`,
   réutilisable par #19 (détail salon) et #21+ (réservation).
5. **Livrer l'écran §7.1 « Recherche de salons »** (version MVP) : champ de recherche, filtre de
   zone, liste des résultats (nom, localisation, logo, badge « réservable » / « bientôt
   disponible »), états **chargement / vide / erreur**.
6. **Ne pas affaiblir les invariants documentés** : deny-by-default (ADR-0015), non-journalisation
   de la PII (§11.3), agnosticisme du fournisseur de stockage (ADR-0005).

## Non-Goals

Périmètre explicitement **hors** de cette issue :

- **Consultation détaillée d'un salon** (horaires, prestations, prix, disponibilités, bouton
  réserver) — **#19 / US-2.4**. Ici, on livre la **liste/recherche** ; le détail est l'issue
  suivante (qui dépend de #16, #17 **et** #18).
- **Réservation** et calcul de **disponibilité** — **#21+**. Le filtre « par disponibilité » de
  §7.1 dépend des horaires (#16) et des RDV (#21) : **différé**.
- **Filtre « par type de prestation »** de §7.1 — dépend du catalogue de prestations (#17) exposé
  côté client (non encore fait) : **différé** (mention en Risques).
- **Affichage carte** (vue « liste ou carte » de §7.1) — nécessite une intégration cartographique
  et la géolocalisation : **différé**. On livre la **vue liste**.
- **Inscription / connexion client sur mobile** (#8, #10) — le backend d'auth client existe, mais
  **aucune UI mobile** ne l'implémente. Cette issue **ne construit pas** l'auth mobile (voir la
  décision d'authentification du catalogue en *Risks and Open Questions*).
- **Mise en avant des « salons populaires »** (§7.1 accueil) — nécessite une métrique de popularité
  (nombre de RDV / notes) inexistante au MVP : **hors périmètre**.
- **Désactivation / suspension d'un salon** (permission `SALON_SET_STATUS`, admin) — non câblée ;
  cette issue **consomme** le champ `status` en lecture, elle ne l'écrit pas.
- **Notation / avis clients**, **tri par distance** — hors MVP.

## Relevant Repository Context

### Architecture (figée par les ADR — source de vérité)

- **Application cliente** : **Flutter** / Dart `^3.12`, Android prioritaire
  ([ADR-0001](../docs/adr/0001-app-mobile-flutter.md)) — c'est **le** « côté client » de cette issue.
- **Backend** : **FastAPI**, API REST, JWT, **architecture hexagonale**
  ([ADR-0003](../docs/adr/0003-backend-fastapi.md), [ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) :
  `domain/` → `application/` (+ `ports/`) → `adapters/inbound|outbound/`.
- **Données** : PostgreSQL 16, SQLAlchemy 2.0, Alembic
  ([ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md), [ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).
- **Autorisation** : RBAC **deny-by-default**, gardes en **dépendances FastAPI**
  ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) — toute route est fermée sauf
  celles listées dans `PUBLIC_ROUTE_PATHS` (choix conscient et revu).
- **Stockage objet** : S3-compatible, **buckets privés**, accès par **URLs signées** à durée
  limitée, clés **sans PII** ([ADR-0005](../docs/adr/0005-stockage-objet-s3-compatible.md),
  [ADR-0017](../docs/adr/0017-creation-salon-medias-et-reservabilite.md)).

### Ce qui existe déjà et qu'il faut réutiliser (ne rien réinventer)

| Élément | Chemin | Rôle pour #18 |
| --- | --- | --- |
| Table `salons` | `backend/coiflink_api/adapters/outbound/persistence/models.py:136` | Colonnes `name`, `description`, `address`, `city`, `commune`, `latitude`, `longitude`, `logo_object_key`, `status`, `opening_hours`. **Index déjà présents** : `ix_salons_status` et `ix_salons_city_commune` — exactement ce qu'exige le filtre §8.3 + zone. Aucune migration nécessaire. |
| Enum `SalonStatus` | `backend/coiflink_api/domain/enums.py:50` | `ACTIVE` / `INACTIVE` / `SUSPENDED` — la valeur du filtre de visibilité (§8.3). |
| Permission `SALON_READ_ANY` | `backend/coiflink_api/domain/permissions.py:87` | Déjà attribuée à `CLIENT` (et `ADMIN`) ; **non encore câblée**. |
| Domaine `Salon` + `is_bookable` | `backend/coiflink_api/domain/salon.py` | Entité de lecture et prédicat §8.3 (`status == ACTIVE and bool(opening_hours)`). À réutiliser tel quel. |
| Port `SalonRepository` | `backend/coiflink_api/application/ports/salon_repository.py` | À **étendre** d'une méthode de recherche `ACTIVE`-only (voir plus bas). |
| Dépôt SQL | `backend/coiflink_api/adapters/outbound/persistence/salon_repository.py` | Patron `select(...).where(...).order_by(...)` (cf. `list_for_owner`) à copier. |
| Lecture + URLs signées | `backend/coiflink_api/application/salons.py:290` (`_SalonReader`, `SalonView`) | Résolution logo → URL signée à réutiliser pour la projection publique. |
| Router salons + `_salon_response` | `backend/coiflink_api/adapters/inbound/salons.py` | Patron de router, DI, réponses OpenAPI. **Ne pas** surcharger `GET /salons` (sémantique « mes salons ») — le catalogue client est une **ressource distincte** (voir Proposed Implementation). |
| Gardes & invariant | `backend/coiflink_api/adapters/inbound/security.py:104` (`PUBLIC_ROUTE_PATHS`), `:432` (`require_any_permission`), `:227` (`unprotected_routes`) | Décision d'auth du catalogue (public vs `SALON_READ_ANY`) à trancher **ici** (voir Risques). |
| Tests deny-by-default | `backend/tests/test_security_guards.py` | Énumère les routes et exige : publique-listée **ou** gardée. Toute nouvelle route y est soumise automatiquement. |
| App mobile (squelette) | `app-mobile/lib/main.dart`, `app-mobile/lib/adapters/ui/app.dart` | **Aucune** couche `domain/`, `application/`, `adapters/data/` n'existe encore — à créer. |

### État de l'application mobile — à connaître avant d'estimer

Le paquet `app-mobile/` ne contient que trois fichiers Dart (`main.dart`, `adapters/ui/app.dart`,
`test/widget_test.dart`). **Il n'y a ni client HTTP, ni configuration d'URL d'API, ni gestion d'état,
ni modèle de données.** Livrer l'écran de recherche implique donc de **poser la fondation réseau du
paquet** (voir *Proposed Implementation §B*). C'est le premier vrai flux data du mobile : le faire
proprement (hexagonal, testable sans réseau) bénéficie à #19 et #21+.

### Commandes (déjà en place)

- Backend : `pytest`, `ruff check`, round-trip Alembic (CI, PostgreSQL 16).
- Mobile : `flutter test`, `flutter analyze`, `flutter build apk`.
- Test gate agrégé : `scripts/test-gate.sh` (parité CI — `pytest` + `npm test` + `flutter test`).

## Proposed Implementation

Deux tranches : **(A)** un endpoint de catalogue backend `ACTIVE`-only ; **(B)** la couche réseau +
l'écran de recherche côté mobile. La tranche (A) porte à elle seule le **critère d'acceptation
testable** et peut être validée par `pytest` indépendamment de (B).

### A. Backend — catalogue de salons `ACTIVE`-only

#### A.1 Ressource distincte (ne pas surcharger `/salons`)

Le catalogue client est **une ressource différente** de `GET /salons` (« mes salons », portée
gérant) et de `GET /salons/{salon_id}` (portée salon). Pour éviter toute collision de routage avec
`/salons/{salon_id}` (typé `uuid.UUID`) et garder une sémantique lisible, **créer un router dédié** :

```
adapters/inbound/catalog.py   →  APIRouter(prefix="/catalog", tags=["catalog"])
    GET /catalog/salons        (liste/recherche, ACTIVE-only)   ← #18
    # GET /catalog/salons/{salon_id}  → réservé au détail client (#19), NON livré ici
```

Ce découpage rend #19 (détail client) naturel (même router) sans jamais réutiliser une route de
gestion.

#### A.2 Décision d'authentification — **à confirmer** (voir Risques, décision 1)

Deux options, isolées à **une seule ligne** (la garde du router) :

- **Option publique (recommandée)** : `GET /catalog/salons` est ajouté à `PUBLIC_ROUTE_PATHS` — une
  **addition consciente et revue** (comme `/auth/login`), documentée par un nouvel ADR. Justification :
  (i) débloque le mobile **sans** exiger que l'auth client soit d'abord construite (l'app est un
  squelette) ; (ii) correspond à §7.1 (accueil qui met en avant des salons **avant** connexion) et
  au parcours §5.1 (recherche possible dès l'ouverture) ; (iii) n'expose que des **données de
  vitrine publiques** (nom, ville, logo), sans `owner_id` ni PII de gestion.
- **Option authentifiée (repli conservateur)** : `require_permission(SALON_READ_ANY)` (rôle `CLIENT`
  ou `ADMIN`). Ne touche pas `PUBLIC_ROUTE_PATHS`, mais **suppose l'auth client livrée sur mobile**
  (elle ne l'est pas) → bloque de fait la tranche (B) tant que #8/#10 mobile ne sont pas faits.

Quelle que soit l'option, la **projection publique** (A.4) et le **filtre `ACTIVE`** (A.3) sont
identiques. Le reste du spec est écrit pour l'**option publique** ; passer à l'option authentifiée
ne change que la déclaration de dépendance du router et retire l'ajout à `PUBLIC_ROUTE_PATHS`.

#### A.3 Port & dépôt — recherche `ACTIVE`-only au niveau SQL

Étendre le port `SalonRepository` (ou introduire un port de lecture dédié `SalonCatalogRepository`
si l'on veut isoler la lecture publique — **recommandé** pour ne pas gonfler le port de gestion) :

```python
@dataclass(frozen=True)
class SalonSearchQuery:
    text: str | None = None       # recherche par nom (ILIKE, insensible casse/accents si dispo)
    city: str | None = None       # filtre de zone
    commune: str | None = None
    limit: int = 20               # borné (ex. 1..50)
    offset: int = 0               # >= 0

class SalonCatalogRepository(Protocol):
    def search_active(self, query: SalonSearchQuery) -> tuple[Salon, ...]: ...
    def count_active(self, query: SalonSearchQuery) -> int: ...   # pour la pagination
    def get_active(self, salon_id: uuid.UUID) -> Salon | None: ...  # préparé pour #19
```

Implémentation SQL (patron `list_for_owner`), **filtre `status` non négociable** :

```python
stmt = select(models.Salon).where(models.Salon.status == SalonStatus.ACTIVE.value)
if query.text:
    stmt = stmt.where(models.Salon.name.ilike(f"%{escape_like(query.text)}%"))
if query.city:
    stmt = stmt.where(models.Salon.city.ilike(query.city))
if query.commune:
    stmt = stmt.where(models.Salon.commune.ilike(query.commune))
stmt = stmt.order_by(models.Salon.name.asc()).limit(query.limit).offset(query.offset)
```

- Le filtre `status == ACTIVE` est **le premier `where`**, appliqué en base : un salon
  `INACTIVE`/`SUSPENDED` ne peut pas remonter, même sur `get_active` (→ `None` → 404 côté #19).
- **Échapper** les métacaractères `LIKE` (`%`, `_`) de `query.text` pour éviter un filtrage
  inattendu (utilitaire `escape_like`, non une faille SQL — SQLAlchemy paramètre déjà la valeur).
- S'appuie sur `ix_salons_status` et `ix_salons_city_commune` (déjà présents).

#### A.4 Cas d'usage & projection publique

Nouveau cas d'usage `SearchSalons` dans `application/catalog.py` (ou `application/salons.py`),
réutilisant `_SalonReader` pour la **résolution du logo en URL signée** :

```python
class SearchSalons:
    def __init__(self, repo: SalonCatalogRepository, media: MediaStorage | None): ...
    def execute(self, query: SalonSearchQuery) -> PublicSalonPage: ...
```

**Projection publique** (`PublicSalonView` / `PublicSalonResponse`) — champs exposés :

| Exposé | Raison |
| --- | --- |
| `id`, `name`, `description` | vitrine |
| `address`, `city`, `commune`, `latitude`, `longitude` | localisation (donnée d'établissement, publique) |
| `logo_url` (**signé** ou `null`) | vitrine ; jamais la clé d'objet brute |
| `is_bookable` | §8.3 — badge « réservable » vs « bientôt disponible » |

| **Jamais exposé** | Raison |
| --- | --- |
| `owner_id` | identifiant de compte — non pertinent, potentiel oracle |
| `status` | seul `ACTIVE` est renvoyé → redondant ; ne pas divulguer l'état de modération |
| `opening_hours` (détail brut) | relève du détail #19 ; ici seul `is_bookable` suffit |
| `phone` du salon | reporté au détail #19 (choix produit — allège la liste) |
| `created_at` / `updated_at` | interne |

Réponse paginée : `{ "items": PublicSalonResponse[], "total": int, "limit": int, "offset": int }`.

#### A.5 Câblage

- `main.py` : `include_router(catalog_router)` ; réutiliser `app.state.media_storage` (peut être
  `None` → `logo_url: null`, jamais d'erreur).
- Si option publique : ajouter `"/catalog/salons"` à `PUBLIC_ROUTE_PATHS` (avec commentaire de
  revue de sécurité) — sinon `unprotected_routes(app)` échouera (c'est le garde-fou attendu).
- **Ne pas** modifier la matrice de permissions ni les routes `/salons` existantes.

### B. Application mobile (Flutter) — couche réseau + écran de recherche

Tranche hexagonale (ADR-0008), testable **sans réseau** (le port est mocké en test) :

```
app-mobile/lib/
  domain/salon/salon_summary.dart        # entité de lecture (id, name, city, commune, logoUrl, isBookable, ...)
  application/
    ports/salon_catalog_gateway.dart      # port : Future<SalonPage> searchSalons(SalonSearchQuery)
    use_cases/search_salons.dart          # orchestration + validation d'entrée
  adapters/
    data/
      api_config.dart                      # URL d'API via --dart-define (API_BASE_URL), aucun secret
      http_salon_catalog_gateway.dart      # http/dio → GET /catalog/salons ; mapping JSON → domaine
    ui/
      salon_search_screen.dart             # champ recherche + filtre zone + liste + états
      widgets/salon_card.dart              # nom, localisation, logo, badge is_bookable
```

- **Client HTTP** : ajouter la dépendance `http` (ou `dio`) à `pubspec.yaml` (première dépendance
  réseau du paquet — passera par l'audit de dépendances CI).
- **Configuration** : `API_BASE_URL` **injecté au build** (`--dart-define`), jamais en dur, jamais
  de secret. Documenter dans `app-mobile/README.md`.
- **Recherche** : champ texte avec *debounce* (~300 ms) → `SearchSalons` → gateway → liste. Filtre
  zone (ville/commune) optionnel. **Pagination** : chargement incrémental (scroll) borné.
- **États** : chargement (spinner), **résultat vide** (« Aucun salon trouvé »), **erreur réseau**
  (message + bouton « Réessayer »). Le badge d'un salon `is_bookable == false` affiche « Bientôt
  disponible » (cohérent §8.3 — le salon est visible mais pas encore réservable).
- **Point d'entrée** : depuis l'écran d'accueil (`app.dart`), remplacer/compléter l'écran neutre par
  un accès à l'écran de recherche (bouton ou route).
- Le domaine et les cas d'usage **ne dépendent pas de Flutter** ; seuls `adapters/ui` et
  `adapters/data` importent `flutter`/`http`.

## Affected Files / Packages / Modules

### `backend/`

**À créer**
- `coiflink_api/adapters/inbound/catalog.py` (router `/catalog`)
- `coiflink_api/application/catalog.py` (cas d'usage `SearchSalons`, `SalonSearchQuery`,
  projection publique) — *ou* section dédiée dans `application/salons.py`
- `coiflink_api/application/ports/salon_catalog_repository.py` (port de lecture publique)
- `coiflink_api/adapters/outbound/persistence/salon_catalog_repository.py` (SQLAlchemy)
- Tests : `tests/test_catalog_api.py`, `tests/test_search_salons_usecase.py`,
  `tests/test_salon_catalog_repository.py` (ou intégration)

**À modifier**
- `coiflink_api/main.py` — `include_router(catalog_router)`
- `coiflink_api/adapters/inbound/security.py` — `PUBLIC_ROUTE_PATHS` **si** option publique retenue
- `tests/conftest.py` — `FakeSalonCatalogRepository` (données `ACTIVE` + non-`ACTIVE` pour le test §8.3)
- `backend/README.md` — nouvelle route catalogue
- Éventuellement `coiflink_api/domain/salon.py` (helper `escape_like`) ou un util partagé

**Sans modification** : `models.py` (index déjà présents), `permissions.py`, table `salons`,
migrations (aucune).

### `app-mobile/`

**À créer** : `lib/domain/salon/salon_summary.dart`,
`lib/application/ports/salon_catalog_gateway.dart`, `lib/application/use_cases/search_salons.dart`,
`lib/adapters/data/api_config.dart`, `lib/adapters/data/http_salon_catalog_gateway.dart`,
`lib/adapters/ui/salon_search_screen.dart`, `lib/adapters/ui/widgets/salon_card.dart`, tests
associés sous `test/`.

**À modifier** : `pubspec.yaml` (dépendance `http`), `lib/adapters/ui/app.dart` (accès à l'écran de
recherche), `app-mobile/README.md`.

### Racine / doc

`README.md` (module 2, section 6 « M2 en cours »), nouvel ADR
`docs/adr/00XX-catalogue-salons-cote-client.md` + `docs/adr/README.md` (surtout si l'option
publique — décision de sécurité à tracer).

## API / Interface Changes

**Nouvelle route REST** :

### `GET /catalog/salons` → `200 OK`

Liste/recherche les salons **`ACTIVE` uniquement** (§8.3).

Paramètres de requête (tous optionnels) :

| Param | Type | Défaut | Rôle |
| --- | --- | --- | --- |
| `q` | string | — | recherche par nom (`ILIKE`, sous-chaîne, métacaractères échappés) |
| `city` | string | — | filtre par ville |
| `commune` | string | — | filtre par commune |
| `limit` | int (1..50) | `20` | taille de page (borné) |
| `offset` | int (≥ 0) | `0` | décalage de page |

```jsonc
// Réponse 200
{
  "items": [
    {
      "id": "…uuid…",
      "name": "Salon Élégance",
      "description": "Coiffure afro et tresses.",
      "address": "Rue des Jardins, Cocody",
      "city": "Abidjan",
      "commune": "Cocody",
      "latitude": 5.359952,
      "longitude": -3.996643,
      "logo_url": "https://…signée…",   // ou null
      "is_bookable": false               // §8.3 : ACTIVE mais sans horaire ⇒ pas encore réservable
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Codes : `200` ; `422` (paramètres de pagination hors bornes). Si **option authentifiée** :
ajouter `401` (non authentifié) et `403` (rôle sans `SALON_READ_ANY`).

**Aucun champ `owner_id`/`status`/`opening_hours`/`phone`/timestamps** dans la projection publique.

**Interfaces internes documentées** : nouveau port `SalonCatalogRepository` (docstring de module,
comme les ports existants) ; cas d'usage `SearchSalons`. **Aucune** permission nouvelle ; **aucun**
changement CLI.

**Mobile** : nouveau port Dart `SalonCatalogGateway` (contrat interne au paquet) ; variable de build
`API_BASE_URL` (`--dart-define`, non secrète).

## Data Model / Protocol Changes

**Aucune.** La table `salons` porte déjà toutes les colonnes nécessaires et les index
`ix_salons_status` + `ix_salons_city_commune` qui servent exactement le filtre §8.3 + zone. **Aucune
migration Alembic.** Le format sur le fil est du JSON REST ; `latitude`/`longitude` sérialisés en
nombres (comme `SalonResponse`).

## Security & Privacy Considerations

1. **Deny-by-default** ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) —
   invariant à ne jamais affaiblir. **Si l'option publique est retenue**, l'ajout de
   `"/catalog/salons"` à `PUBLIC_ROUTE_PATHS` est une **décision de sécurité consciente**, à
   documenter (nouvel ADR) et justifier : la route est **lecture seule**, ne renvoie que des
   **données de vitrine publiques** de salons **`ACTIVE`**, sans `owner_id` ni PII de gestion. Le
   test `unprotected_routes(app)` reste l'arbitre : soit la route est publique-listée (option
   publique), soit elle porte une garde de `Principal` (option authentifiée) — **jamais ni l'un ni
   l'autre**.

2. **Règle de visibilité §8.3** — le filtre `status == ACTIVE` est appliqué **en base**, en premier
   `where`, sur la liste **et** sur la future lecture par id (#19). Ne jamais post-filtrer en
   Python (faillible). **À figer par un test** : un salon `INACTIVE`/`SUSPENDED` inséré n'apparaît
   pas dans les résultats.

3. **Projection minimale / pas d'oracle** — la réponse publique **n'expose pas `owner_id`** ni
   `status`. Un salon inactif est **absent** (pas d'entrée « masquée » qui révélerait son
   existence). La lecture par id (#19) d'un salon non-`ACTIVE` renverra `404` — cohérent avec
   « absent du catalogue ».

4. **Stockage objet** ([ADR-0005](../docs/adr/0005-stockage-objet-s3-compatible.md)) — `logo_url`
   est **toujours une URL signée** (réutiliser `_SalonReader._sign`), jamais une clé d'objet ni une
   URL de bucket. Si le stockage n'est pas configuré (`media_storage is None`), `logo_url: null` —
   pas d'erreur.

5. **Non-journalisation** (§11.3) — ne jamais journaliser d'URL signée (secret porteur), ni les
   termes de recherche s'ils peuvent contenir de la donnée personnelle, ni la localisation.
   `backend/tests/test_secrets_policy.py` doit rester vert.

6. **Robustesse de la recherche** — `q` est **paramétré** par SQLAlchemy (pas d'injection) ; en plus,
   **échapper** `%`/`_` pour un `ILIKE` prévisible. Borner `limit`/`offset` (déni de service par
   page géante → `422`).

7. **Mobile** — `API_BASE_URL` injecté au build (`--dart-define`), **jamais** de secret embarqué
   dans l'APK ; en option publique, **aucun jeton** n'est manipulé par l'app pour cet écran. La
   couche data ne journalise ni URL signée ni PII.

8. **Résidence des données** — inchangée (ADR-0011, `europe-west4`) ; cette issue n'introduit aucun
   nouveau stockage.

Si le dépôt ne documente pas d'autre contrainte pertinente, aucune n'est ajoutée ici.

## Testing Plan

### Backend — unitaires (`pytest`, sans base ni réseau)

- `tests/test_search_salons_usecase.py` (avec `FakeSalonCatalogRepository`) :
  - seuls les salons `ACTIVE` sont renvoyés (le fake contient `ACTIVE` + `INACTIVE` + `SUSPENDED`) ;
  - la recherche par nom filtre correctement ; filtre ville/commune ;
  - `logo_url` résolu en URL signée via `FakeMediaStorage` ; `null` si `media_storage=None` ;
  - `owner_id`/`status`/`opening_hours` **absents** de la projection publique ;
  - pagination : `limit`/`offset` respectés ; `total` cohérent.

### Backend — API / intégration (`TestClient`)

- `tests/test_catalog_api.py` :
  - **critère d'acceptation §8.3** : un salon `INACTIVE`/`SUSPENDED` **n'apparaît pas** dans
    `GET /catalog/salons` (test central de l'issue) ;
  - recherche `?q=` et filtre `?city=`/`?commune=` ;
  - pagination `?limit=&offset=` ; `limit` hors bornes → `422` ;
  - la réponse **ne contient jamais** `owner_id` ni de clé d'objet brute ;
  - **si option publique** : la route répond **sans jeton** (`200`) ; `unprotected_routes(app)`
    reste cohérent (la route est publique-listée) ;
  - **si option authentifiée** : sans jeton → `401` ; rôle `MANAGER`/`HAIRDRESSER` sans
    `SALON_READ_ANY` → `403` ; `CLIENT`/`ADMIN` → `200`.
- `tests/test_security_guards.py` (existant) : reste vert — la nouvelle route est soit
  publique-listée, soit gardée (jamais orpheline).

### Backend — intégration base (si dépôt SQL testé contre PostgreSQL)

- Vérifier que `status == ACTIVE` s'applique bien en SQL et que l'`ILIKE` + l'échappement `LIKE`
  fonctionnent (sur un jeu de salons mélangés).

### Mobile (`flutter test`)

- `test/search_salons_test.dart` — cas d'usage avec un **faux gateway** : mapping, filtre, gestion
  d'une réponse vide.
- `test/http_salon_catalog_gateway_test.dart` — mapping JSON → `SalonSummary` (avec `logo_url` null),
  gestion d'erreur HTTP (non-200 → exception domaine), **aucune** URL/PII journalisée.
- `test/salon_search_screen_test.dart` (widget) — états chargement / liste / vide / erreur ; badge
  « Bientôt disponible » quand `isBookable == false`.
- `flutter analyze` propre ; `flutter build apk` réussit avec `--dart-define=API_BASE_URL=…`.

### Documentation

- Vérifier que la doc décrit la route **liste/recherche** livrée et **ne laisse pas entendre** que
  le détail salon (#19) ou la réservation (#21+) existent.

## Documentation Updates

- **Nouvel ADR** `docs/adr/00XX-catalogue-salons-cote-client.md` : (a) ressource distincte
  `/catalog/salons` (ne pas surcharger `/salons`) ; (b) **décision d'authentification** du catalogue
  (publique vs `SALON_READ_ANY`) et sa justification de sécurité ; (c) projection publique minimale
  (pas d'`owner_id`, filtre `ACTIVE` en base). Indexer dans `docs/adr/README.md`.
- **`README.md` (racine)** : module 2 « Gestion des salons » — mentionner le catalogue client
  `GET /catalog/salons` (ACTIVE-only, §8.3) ; mettre à jour la section 6 (« M2 en cours »).
- **`backend/README.md`** : nouvelle route et ses paramètres.
- **`app-mobile/README.md`** : couche réseau, `API_BASE_URL` (`--dart-define`), écran de recherche,
  dépendance `http`.
- **OpenAPI** : `summary`/`responses`/docstring de la route (patron `salons.py`).

## Risks and Open Questions

### Décisions à confirmer

1. **Authentification du catalogue : public ou `SALON_READ_ANY` ?** *(recommandé : public,
   via ajout revu à `PUBLIC_ROUTE_PATHS` + ADR)*. C'est **la** décision structurante de l'issue :
   - **Public** : débloque le mobile (l'auth client n'existe pas encore côté app), colle à §7.1/§5.1
     (browse avant connexion), n'expose que de la vitrine ; **coût** : une addition consciente à
     `PUBLIC_ROUTE_PATHS` (invariant sensible — à revoir et tracer en ADR).
   - **Authentifié** (`SALON_READ_ANY`) : ne touche pas l'invariant public, mais **suppose #8/#10
     livrés sur mobile** — ils ne le sont pas → la tranche (B) devient bloquée par un travail hors
     périmètre. À trancher **avant** l'implémentation, car cela conditionne la faisabilité de (B).

2. **Port dédié `SalonCatalogRepository` vs extension de `SalonRepository` ?** *(recommandé :
   port dédié)* — la lecture publique (`ACTIVE`-only, projection réduite) a des invariants
   différents de la gestion ; l'isoler évite qu'un futur appel de gestion oublie le filtre `ACTIVE`.

3. **Champs de la projection publique** — inclure ou non `phone` du salon et les coordonnées
   `latitude`/`longitude` dès la liste ? *(recommandé : coordonnées oui — utiles à une future carte
   et non personnelles ; `phone` reporté au détail #19)*. À confirmer côté produit.

4. **Recherche insensible aux accents** — un `ILIKE` simple ne gère pas « Elegance » vs « Élégance ».
   Le MVP peut s'en contenter ; une normalisation (`unaccent` PostgreSQL) est une amélioration à
   tracer (nécessiterait l'extension `unaccent` → décision d'infra).

### Risques

- **Poser la couche réseau mobile est le vrai coût de (B).** L'app est un squelette : client HTTP,
  configuration, gestion d'erreurs et de états, mapping — tout est neuf. Bien fait, c'est réutilisé
  par #19/#21 ; mal cadré, l'effort **M** dérive. Une **coupe légitime** si l'effort déborde :
  livrer (A) + les tests §8.3 (qui portent le critère d'acceptation), et une version mobile
  minimale (liste sans filtre zone ni pagination incrémentale), le reste en suivi.
- **`API_BASE_URL` mobile** — un défaut manquant fait « marcher en test, casser en device ». À
  documenter et à passer par `--dart-define` (émulateur Android : `10.0.2.2`, pas `localhost`).
- **Filtre « type de prestation »/« disponibilité » de §7.1** — dépendent de #17/#16/#21 non exposés
  côté client ; les livrer ici serait hors périmètre et fragile. Explicitement **différés**.
- **Collision de routage** — évitée en n'utilisant **pas** `/salons/...` littéral (déjà occupé par
  `/salons/{salon_id}` typé `uuid.UUID`), d'où le prefix `/catalog`.
- **Pagination non bornée** — sans borne sur `limit`, une page géante est un vecteur de charge ;
  borner (1..50) et renvoyer `422` hors bornes.

## Implementation Checklist

> Ordre conçu pour livrer d'abord le cœur testable (A), puis l'écran (B).

### Backend — catalogue `ACTIVE`-only (tranche A)

1. **Trancher la décision 1** (public vs authentifié) — conditionne le câblage et un test.
2. Créer le port `application/ports/salon_catalog_repository.py` (`SalonSearchQuery`,
   `SalonCatalogRepository` : `search_active`, `count_active`, `get_active`).
3. Créer le dépôt SQL `adapters/outbound/persistence/salon_catalog_repository.py` :
   `where(status == ACTIVE)` **en premier**, `ILIKE` échappé sur `name`, filtre ville/commune,
   `order_by(name)`, `limit`/`offset`. S'appuyer sur `ix_salons_status`/`ix_salons_city_commune`.
4. Créer le cas d'usage `application/catalog.py` : `SearchSalons` + projection publique
   (`PublicSalonView`/`PublicSalonResponse`, **sans** `owner_id`/`status`), logo → URL signée via
   `_SalonReader._sign`.
5. Ajouter `FakeSalonCatalogRepository` à `tests/conftest.py` (jeu mêlant `ACTIVE` et non-`ACTIVE`) ;
   écrire `tests/test_search_salons_usecase.py`. ✅ vert.
6. Créer le router `adapters/inbound/catalog.py` (`prefix="/catalog"`, `GET /catalog/salons`,
   validation des bornes `limit`/`offset` → `422`, docstrings OpenAPI).
7. Câbler dans `main.py` (`include_router`) ; **si option publique**, ajouter `"/catalog/salons"` à
   `PUBLIC_ROUTE_PATHS` (commentaire de revue) ; **si authentifié**,
   `require_permission(SALON_READ_ANY)`.
8. Écrire `tests/test_catalog_api.py` — dont le **test §8.3** (un salon `INACTIVE`/`SUSPENDED`
   n'apparaît pas) et l'absence d'`owner_id` dans la réponse. Vérifier `test_security_guards.py` et
   `test_secrets_policy.py` verts, `ruff check` propre.

### Mobile — couche réseau + écran (tranche B)

9. `pubspec.yaml` : ajouter `http` (ou `dio`) ; `flutter pub get`.
10. `lib/domain/salon/salon_summary.dart` : entité de lecture + `isBookable`.
11. `lib/application/ports/salon_catalog_gateway.dart` + `lib/application/use_cases/search_salons.dart`.
12. `lib/adapters/data/api_config.dart` (`API_BASE_URL` via `--dart-define`) +
    `lib/adapters/data/http_salon_catalog_gateway.dart` (mapping JSON → domaine, erreurs, **aucune**
    journalisation d'URL/PII).
13. `lib/adapters/ui/salon_search_screen.dart` + `widgets/salon_card.dart` : recherche (debounce),
    filtre zone, pagination, états chargement/vide/erreur, badge `is_bookable`.
14. Brancher l'écran depuis `lib/adapters/ui/app.dart`.
15. Tests : `search_salons_test.dart`, `http_salon_catalog_gateway_test.dart`,
    `salon_search_screen_test.dart` ; `flutter analyze` ; `flutter build apk --dart-define=API_BASE_URL=…`.

### Documentation & vérification

16. Rédiger le nouvel ADR (décision d'auth + ressource distincte + projection) + l'indexer.
17. Mettre à jour `README.md` (racine, module 2 + section 6), `backend/README.md`,
    `app-mobile/README.md`.
18. Relire : **rien** dans la doc ne doit laisser entendre que le **détail salon** (#19) ou la
    **réservation** (#21+) sont implémentés.
19. `scripts/test-gate.sh` vert (parité CI : `pytest` + `npm test` + `flutter test`).
