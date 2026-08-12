# Photo de prestation dans le catalogue public (US-8.4)

> Spécification de planification pour l'issue GitHub **#158 — US-8.4 : Photo de prestation dans
> le catalogue public** (`feature` · Should · Effort S · PRD §17 « Borne Intelligente d'Accueil »,
> promu au jalon **M7 — Borne client (kiosque libre-service)**, Épic 8). **Dépend de : aucune.**
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon M7 (US-8.5, #159) doit afficher les prestations sur une borne tactile en gros boutons,
« adaptés à un usage à distance de bras ». Une liste purement textuelle (nom, prix, durée) est le
seul rendu possible aujourd'hui, faute de photo dans la réponse consommée par le client : #158
comble ce manque en exposant l'illustration déjà associée à chaque prestation dans le catalogue
**public**, préalable nécessaire à #159 (qui en dépend explicitement, `#155, #156, #157, #158`) et
utile indépendamment à la fiche salon consultée par l'app mobile cliente hors borne.

État actuel du dépôt (vérifié par lecture directe) :

- **La donnée existe déjà en base et côté gérant, mais pas côté public.** `Service`
  (`backend/coiflink_api/domain/service.py:192-216`) porte `image_object_key: str | None` — « la
  clé d'objet S3-compatible de l'illustration (ADR-0005), jamais une URL » (docstring
  `service.py:196-198`). La colonne ORM correspondante existe déjà
  (`adapters/outbound/persistence/models.py:279`, `String(1024)`, migration `0010`, format
  `services/{salon_id}/{uuid}.png`). **Aucune migration n'est nécessaire pour #158.**
- **Le mécanisme de résolution en URL signée est déjà écrit et éprouvé côté gérant.** La route
  `GET /salons/{salon_id}/services` (gérant) résout `image_url` dans `_service_response`
  (`adapters/inbound/services.py:198-225`) :
  ```python
  image_url = (
      storage.presign_download(service.image_object_key)
      if storage is not None and service.image_object_key
      else None
  )
  ```
  `storage` est un `MediaStorage | None` (`application/ports/media_storage.py`) injecté par
  `get_optional_media_storage` (`adapters/inbound/salons.py:235-241`), qui lit
  `request.app.state.media_storage` — `None` si le stockage objet n'est pas configuré, auquel cas
  les lectures **tolèrent l'absence** et renvoient `image_url: null` plutôt que d'échouer. C'est
  exactement ce même mécanisme, sans variante, que #158 doit réutiliser côté catalogue public.
- **Le catalogue public charge déjà l'objet `Service` complet mais le filtre en aval.** L'endpoint
  `GET /catalog/salons/{salon_id}` (`adapters/inbound/catalog.py:295-330`, **public**, sans jeton)
  s'appuie sur `GetPublicSalon.execute` (`application/catalog.py:212-240`), qui appelle
  `self._repository.list_active_services(salon_id)`
  (`adapters/outbound/persistence/salon_catalog_repository.py:90-103`). Ce dépôt lit chaque ligne
  via `_service_to_domain` — le **même** mapper utilisé par `SqlServiceRepository`
  (`salon_catalog_repository.py:31-32`, `from ... import _to_domain as _service_to_domain`) — donc
  `image_object_key` **est déjà en mémoire** dans chaque `Service` reçu par `GetPublicSalon`.
  C'est la couche applicative/HTTP qui, volontairement, ne le reporte pas plus loin :
  - `PublicServiceView` (`application/catalog.py:121-136`) ne porte que `id`, `name`,
    `description`, `price`, `duration_minutes`, `category` ;
  - `_to_service_view` (`application/catalog.py:242-251`) construit cette vue **sans** lire
    `service.image_object_key` ;
  - `PublicServiceResponse` (`adapters/inbound/catalog.py:90-103`) et le mapping
    `_public_salon_detail_response` (`catalog.py:207-217`) répètent la même omission côté HTTP.
- **`GetPublicSalon` est déjà câblé à un `MediaStorage` optionnel — pour le logo et les photos
  uniquement.** Son constructeur (`application/catalog.py:204-210`) accepte déjà
  `media_storage: MediaStorage | None = None` et une méthode privée `_sign`
  (`catalog.py:261-266`, strictement identique à celle de `services.py`) l'utilise pour
  `logo_url` et pour chaque `PublicSalonPhotoView.url`. Le routeur (`catalog.py:305-330`) injecte
  déjà `storage` via `Depends(get_optional_media_storage)` et le passe à
  `GetPublicSalon(repository, storage)`. **Aucune nouvelle dépendance FastAPI, aucun nouveau
  paramètre de constructeur, aucun câblage supplémentaire dans `main.py` n'est requis** : il suffit
  d'appeler `self._sign(...)` une fois de plus, dans `_to_service_view`.
- **Aucun consommateur mobile n'affiche de photo de prestation aujourd'hui.** `SalonService`
  (`app-mobile/lib/domain/salon/salon_service.dart:9-36`) n'a pas de champ image ; le parsing JSON
  (`adapters/data/http_salon_catalog_gateway.dart:167-177`, `_serviceFromJson`) ne lit pas
  `image_url`. Les deux seuls consommateurs — `ServiceListTile`
  (`adapters/ui/widgets/service_list_tile.dart:11-37`, fiche salon) et `_ServiceStep`
  (`adapters/ui/booking/booking_flow_screen.dart:489-534`, tunnel de réservation) — construisent
  leur propre `ListTile` champ par champ (nom, durée, prix) : aucun des deux ne sérialise
  `SalonService` en retour vers le backend, donc y ajouter un champ optionnel est **strictement
  additif** de leur point de vue.
- **Aucun test existant n'affirme l'absence du champ.** `tests/test_get_public_salon_usecase.py`
  construit ses fixtures `Service` avec `image_object_key=None` (ligne 85) mais ne teste aucune
  absence de champ `image_url` dans la vue — ajouter le champ ne casse donc pas d'assertion
  d'« exhaustivité » de schéma côté tests unitaires actuels ; les tests d'API (`test_catalog_api.py`
  / équivalent détail) sont à vérifier de la même façon avant modification (voir *Testing Plan*).

## Goals

- **Exposer `image_url` dans `PublicServiceView` (`application/catalog.py`) et
  `PublicServiceResponse` (`adapters/inbound/catalog.py`)**, réutilisant *exactement* le mécanisme
  déjà en place pour `logo_url`/`photos` dans `GetPublicSalon` (méthode privée `_sign`,
  `media_storage.presign_download`) — pas un mécanisme parallèle ou dupliqué.
- **Champ additif, jamais de rupture.** `image_url` est ajouté en fin de schéma, toujours présent
  dans la réponse (comme `logo_url`), valant `null` si la prestation n'a pas d'illustration **ou**
  si le stockage objet n'est pas configuré (miroir exact du comportement `services.py`). Aucun
  champ existant n'est renommé, retiré ni retypé ; aucune route existante n'est supprimée.
- **Aucune migration de schéma.** `image_object_key` existe déjà (migration `0010`) ; #158 ne
  touche ni `models.py` ni `migrations/versions/`.
- **Répercuter le champ côté app mobile cliente** : `SalonService` (domaine Flutter) gagne un
  champ `imageUrl` optionnel, lu par `_serviceFromJson`
  (`http_salon_catalog_gateway.dart`) — sans modifier le contrat des écrans qui ne l'utilisent pas
  encore (`ServiceListTile`, `_ServiceStep`), pour qu'ils puissent l'exploiter plus tard sans
  nouveau changement de modèle (et pour que le futur écran « choix de prestation » de la borne
  kiosque, #159, puisse le consommer dès sa livraison).
- **Couverture de tests** garantissant : image présente + stockage configuré → `image_url` signée ;
  image absente → `null` ; stockage non configuré → `null` (jamais une exception) ; jamais la clé
  d'objet brute dans la réponse ; non-régression des consommateurs existants de
  `GET /catalog/salons/{salon_id}` (réservation #22, fiche client #19).

## Non-Goals

- **Téléversement ou gestion de l'illustration.** #158 ne touche ni `POST
  /salons/{salon_id}/services/media/upload-url`, ni `PUT
  /salons/{salon_id}/services/{service_id}/image` (déjà livrés, gérant uniquement, #17) : la
  photo est **déjà** posée par le gérant, #158 se contente de la **rendre visible** au client.
- **Photo dans `GET /catalog/salons` (liste/recherche, US-2.3, #18).** `PublicSalonResponse` (fiche
  de vitrine, sans détail de prestations) ne porte pas de champ `services` : seule la fiche de
  détail (`GET /catalog/salons/{salon_id}`) est concernée.
- **Rendu visuel sur la borne (grille de boutons avec photo, mise en cache d'image, etc.).** Objet
  de #159 (mode kiosque de l'app mobile) et #160 (ticket imprimé) ; #158 livre uniquement la
  **donnée**, pas l'écran.
- **Rappel des frontières du jalon M7 dans son ensemble** (au-delà de cette issue) : restent hors
  scope de M7 — vérification/check-in d'un rendez-vous existant depuis la borne, identification par
  QR code ou code de réservation, affichage temps réel des coiffeurs disponibles avant affectation,
  paiement autonome sur la borne. Ces points ne sont pas traités par #158 ni par aucune autre issue
  de ce jalon.

## Relevant Repository Context

### Stack & architecture (rappel, inchangées par #158)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | Hexagonale : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| Stockage objet & URLs signées | Bucket privé, jamais de clé brute exposée | [0005](../docs/adr/0005-stockage-objet-s3-compatible.md) |
| Catalogue public | `GET /catalog/salons`, `/catalog/salons/{salon_id}`, projection publique minimale | [0020](../docs/adr/0020-catalogue-salons-cote-client.md), [0021](../docs/adr/0021-consultation-salon-cote-client.md) |

### Fichiers à lire avant implémentation (patron à reproduire à l'identique)

- `backend/coiflink_api/adapters/inbound/services.py:198-225` (`_service_response`) — le mécanisme
  de résolution `image_url` **côté gérant**, à reproduire trait pour trait côté public.
- `backend/coiflink_api/application/catalog.py:121-136, 194-267` (`PublicServiceView`,
  `GetPublicSalon`, `_sign`) — la classe à étendre, dont le constructeur accepte déjà un
  `media_storage` optionnel utilisé pour `logo_url`/`photos`.
- `backend/coiflink_api/adapters/inbound/catalog.py:90-103, 186-227, 295-330`
  (`PublicServiceResponse`, `_public_salon_detail_response`, `get_public_salon`) — schéma et
  mapping HTTP à étendre ; la route est **déjà** publique-listée, aucun changement de garde.
- `backend/coiflink_api/domain/service.py:192-216` et
  `backend/coiflink_api/adapters/outbound/persistence/models.py:264-282` — confirment que
  `image_object_key` existe déjà et n'a besoin d'aucune migration.
- `backend/tests/conftest.py:640-665` (`FakeMediaStorage`) et `:788-` (`FakeSalonCatalogRepository`)
  — fakes déjà présents pour écrire les tests unitaires du cas d'usage étendu.
- `app-mobile/lib/domain/salon/salon_service.dart` et
  `app-mobile/lib/adapters/data/http_salon_catalog_gateway.dart:167-177` (`_serviceFromJson`) —
  modèle et parsing à étendre côté Flutter.
- `app-mobile/lib/adapters/ui/widgets/service_list_tile.dart:11-37` et
  `app-mobile/lib/adapters/ui/booking/booking_flow_screen.dart:489-534` (`_ServiceStep`) — les deux
  seuls consommateurs de `SalonService`, à ne **pas** modifier fonctionnellement (le champ ajouté
  reste inutilisé par eux, ce qui prouve la non-régression).

### Contraintes transverses documentées

- **ADR-0005** : « aucun objet n'est lisible publiquement ; tout accès passe par une URL signée à
  durée limitée » — `image_url` doit suivre cette règle comme `logo_url`/`photos.url` le font déjà.
- **PRD §A.4 (projection publique minimale)** : le catalogue public n'expose jamais de donnée de
  gestion (`is_active`, `salon_id`, clé d'objet brute, timestamps) — `image_url` ne doit rien ajouter
  de plus qu'une URL signée.
- **PRD §12.1** : réponse API < 3 s — la résolution d'`image_url` est un simple appel de signature
  locale (pas d'appel réseau bloquant vers le stockage objet côté lecture), au même coût que
  `logo_url`/`photos` déjà résolus dans le même appel.

## Proposed Implementation

### (A) Backend — cas d'usage (`application/catalog.py`)

1. **`PublicServiceView`** (ligne ~121) : ajouter un champ `image_url: str | None` en fin de
   dataclass, avec un ajout de docstring expliquant qu'il s'agit d'une URL **signée** (miroir
   `logo_url`), jamais une clé d'objet.
2. **`GetPublicSalon._to_service_view`** (ligne ~242) : passer de `@staticmethod` à méthode
   d'instance (elle doit désormais accéder à `self._sign`), et ajouter
   `image_url=self._sign(service.image_object_key)` à la construction de `PublicServiceView`.
   Aucun autre changement de signature de `GetPublicSalon` : le `media_storage` est déjà reçu par
   le constructeur (ligne ~207) et déjà utilisé pour `logo_url`/`photos` — `_to_service_view`
   emprunte simplement la même méthode privée `_sign` (ligne ~261), déjà partagée.
3. Mettre à jour le docstring de `PublicSalonDetailView`/`GetPublicSalon` pour mentionner que les
   prestations portent désormais aussi une illustration signée (cohérence avec la mention déjà
   faite pour `logo_url`/`photos`).

### (B) Backend — adapter entrant (`adapters/inbound/catalog.py`)

1. **`PublicServiceResponse`** (ligne ~90) : ajouter `image_url: str | None` en fin de modèle
   Pydantic, avec la même formule de docstring que `ServiceResponse.image_url`
   (`services.py:124-126`) : « URL signée de lecture (ou `null` si aucune image ou stockage non
   configuré) — jamais la clé d'objet brute ».
2. **`_public_salon_detail_response`** (ligne ~207) : dans la liste en compréhension qui construit
   `PublicServiceResponse` depuis chaque `PublicServiceView`, ajouter
   `image_url=service.image_url`.
3. **Aucun changement de garde ni de route.** `GET /catalog/salons/{salon_id}` reste publique
   (déjà dans `PUBLIC_ROUTE_PATHS`), aucun nouveau chemin, aucune nouvelle dépendance FastAPI : le
   paramètre `storage` (`Depends(get_optional_media_storage)`) est **déjà** présent sur la route
   `get_public_salon` (ligne ~310) et déjà transmis à `GetPublicSalon(repository, storage)`
   (ligne ~325).

### (C) Backend — documentation inline

Mettre à jour le docstring d'en-tête de `PublicSalonDetailResponse`
(`adapters/inbound/catalog.py:129-139`) et de `PublicServiceView`/`PublicSalonDetailView`
(`application/catalog.py`) pour lister `image_url` parmi les champs de vitrine désormais exposés,
à la même place que la mention actuelle de `logo_url`/`photos` — pour que la liste des champs
« jamais exposés » (`is_active`, `salon_id`, timestamps, clé d'objet brute) reste correcte et
que rien ne suggère que la clé brute transite.

### (D) App mobile (Flutter) — modèle & parsing

1. **`app-mobile/lib/domain/salon/salon_service.dart`** : ajouter un champ optionnel
   `final String? imageUrl;` au constructeur `const SalonService({..., this.imageUrl})`, avec un
   commentaire rappelant qu'il s'agit d'une URL signée à durée limitée (comme `SalonDetail.logoUrl`,
   `salon_detail.dart:65-66`) — pas une URL permanente à mettre en cache indéfiniment côté client.
2. **`app-mobile/lib/adapters/data/http_salon_catalog_gateway.dart:167-177`**
   (`_serviceFromJson`) : lire `image_url` du JSON, `json['image_url'] as String?`, et le passer au
   constructeur `SalonService`.
3. **Aucun changement dans `ServiceListTile` ni `_ServiceStep`** au périmètre de #158 : le champ est
   ajouté au modèle et au parsing uniquement, pour que #159 (mode kiosque) puisse s'en servir dès sa
   propre implémentation sans retoucher le modèle de données. Un affichage optionnel de vignette
   dans la fiche salon actuelle (hors borne) reste une amélioration possible mais n'est **pas**
   requis par l'acceptation de #158 (voir *Goals*) ; à trancher séparément si le porteur produit le
   souhaite (voir *Risks and Open Questions*).

### (D-bis) Esquisses de code (patch de référence, vérifié contre le code actuel)

> Ces extraits sont fournis pour que la phase d'implémentation applique le changement quasi
> tel quel. Ils reflètent le code **effectivement présent** sur la branche (vérifié par lecture
> directe : `application/catalog.py:122-136, 242-266`, `adapters/inbound/catalog.py:90-103,
> 207-217`, `salon_service.dart`, `http_salon_catalog_gateway.dart`). Adapter au besoin si le
> code a évolué entre-temps.

**`application/catalog.py` — `PublicServiceView` (ajout du champ en fin de dataclass) :**

```python
@dataclass(frozen=True)
class PublicServiceView:
    id: object
    name: str
    description: str | None
    price: decimal.Decimal
    duration_minutes: int
    category: str | None
    image_url: str | None  # URL signée (miroir logo_url) ou None ; jamais la clé d'objet
```

**`application/catalog.py` — `_to_service_view` passe de `@staticmethod` à méthode d'instance :**

```python
    def _to_service_view(self, service: Service) -> PublicServiceView:
        return PublicServiceView(
            id=service.id,
            name=service.name,
            description=service.description,
            price=service.price,
            duration_minutes=service.duration_minutes,
            category=service.category,
            image_url=self._sign(service.image_object_key),
        )
```

Le site d'appel (`execute`, ligne ~235) reste inchangé : il appelle déjà
`self._to_service_view(service)`. `_sign` (ligne ~261) renvoie déjà `None` si la clé est `None`
**ou** si `media_storage is None` — aucune garde supplémentaire à écrire.

**`adapters/inbound/catalog.py` — `PublicServiceResponse` (ajout du champ) :**

```python
class PublicServiceResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    price: decimal.Decimal
    duration_minutes: int
    category: str | None
    image_url: str | None  # URL signée de lecture (ou null) ; jamais la clé d'objet brute
```

**`adapters/inbound/catalog.py` — mapping dans `_public_salon_detail_response` (compréhension `services`) :**

```python
        services=[
            PublicServiceResponse(
                id=service.id,
                name=service.name,
                description=service.description,
                price=service.price,
                duration_minutes=service.duration_minutes,
                category=service.category,
                image_url=service.image_url,
            )
            for service in view.services
        ],
```

**`app-mobile/lib/domain/salon/salon_service.dart` — champ optionnel `imageUrl` :**

```dart
  const SalonService({
    required this.id,
    required this.name,
    this.description,
    this.price,
    this.durationMinutes,
    this.category,
    this.imageUrl,
  });

  // ... champs existants ...

  /// URL **signée** à durée limitée de l'illustration (ou null si aucune image /
  /// stockage non configuré). Comme `SalonDetail.logoUrl` : ne pas mettre en cache
  /// au-delà de sa validité.
  final String? imageUrl;
```

**`app-mobile/lib/adapters/data/http_salon_catalog_gateway.dart` — `_serviceFromJson` :**

```dart
    return SalonService(
      // ... champs existants (id, name, description, price, durationMinutes, category) ...
      imageUrl: json['image_url'] as String?,
    );
```

### (E) Ce qui ne change pas

- Aucune migration Alembic, aucune modification de `models.py`.
- Aucune modification de `PUBLIC_ROUTE_PATHS`, de `security.py`, ni des routes gérant
  (`services.py`) — le mécanisme y est déjà correct et sert de référence, pas de cible.
- Aucun changement de `GET /catalog/salons` (liste) ni de son `PublicSalonResponse`.
- Aucun changement du tunnel de réservation (`POST /salons/{salon_id}/appointments`) : `image_url`
  est un champ de lecture pure, jamais transmis en retour par le client.

## Affected Files / Packages / Modules

### Backend (`backend/coiflink_api/`) — à modifier

| Fichier | Modification |
| --- | --- |
| `application/catalog.py` | `PublicServiceView.image_url` ; `GetPublicSalon._to_service_view` devient méthode d'instance et appelle `self._sign(...)` |
| `adapters/inbound/catalog.py` | `PublicServiceResponse.image_url` ; mapping dans `_public_salon_detail_response` |

### Backend — tests à modifier/ajouter

| Fichier | Modification |
| --- | --- |
| `tests/test_get_public_salon_usecase.py` | cas `image_object_key` renseigné + `FakeMediaStorage` → `image_url` signée ; `image_object_key=None` → `image_url is None` ; pas de `FakeMediaStorage` → `image_url is None` |
| `tests/test_catalog_detail_api.py` (384 lignes, confirmé — teste `GET /catalog/salons/{salon_id}`) | étendre `test_active_salon_returns_full_detail`, `test_service_item_has_no_management_fields` ; ajouter les cas image signée/absente/stockage non configuré (patron `test_logo_url_is_signed_not_raw_key` / `test_logo_and_photos_null_without_storage`) |

### App mobile (`app-mobile/lib/`) — à modifier

| Fichier | Modification |
| --- | --- |
| `domain/salon/salon_service.dart` | champ `imageUrl` optionnel |
| `adapters/data/http_salon_catalog_gateway.dart` | `_serviceFromJson` lit `image_url` |

### App mobile — tests à modifier

| Fichier | Modification |
| --- | --- |
| `test/http_salon_catalog_gateway_detail_test.dart` | cas de mapping avec `image_url` renseigné et avec `image_url: null`/absent (c'est ce fichier — et non `http_salon_catalog_gateway_test.dart`, dédié à la liste/`SalonSummary` — qui teste le mapping des `services` du détail, groupe `mapping JSON → SalonDetail`, lignes 98-221) |

### Non modifiés (référence)

`backend/coiflink_api/domain/service.py`, `adapters/outbound/persistence/models.py`,
`adapters/outbound/persistence/salon_catalog_repository.py`, `adapters/inbound/services.py`,
`adapters/inbound/security.py`, `migrations/versions/`, `app-mobile/lib/adapters/ui/widgets/service_list_tile.dart`,
`app-mobile/lib/adapters/ui/booking/booking_flow_screen.dart`, `web-dashboard/` (aucun consommateur
de `GET /catalog/salons/{salon_id}` côté web gérant — vérifié par recherche, cette route est
strictement destinée à l'app mobile cliente et, désormais, à la borne).

## API / Interface Changes

**Aucune nouvelle route.** Une seule route existante voit son schéma de réponse étendu de façon
additive :

| Méthode | Chemin | Garde | Changement |
| --- | --- | --- | --- |
| `GET` | `/catalog/salons/{salon_id}` | **public** (déjà dans `PUBLIC_ROUTE_PATHS`) | chaque objet de `services[]` gagne `image_url: string \| null` |

```jsonc
// Réponse 200 — GET /catalog/salons/{salon_id} (extrait, après #158)
{
  // ... champs inchangés (id, name, description, phone, address, city, commune,
  //     latitude, longitude, logo_url, photos, opening_hours, hairdressers, is_bookable) ...
  "services": [
    {
      "id": "…uuid…",
      "name": "Coupe homme",
      "description": "Coupe aux ciseaux.",
      "price": "5000.00",
      "duration_minutes": 30,
      "category": "Coupe",
      "image_url": "https://…signée…"   // nouveau ; null si aucune image ou stockage non configuré
    }
  ]
}
```

- **Compatibilité ascendante garantie.** Le champ est **additif** : tout consommateur existant
  (app mobile actuelle, réservation #22, fiche client #19) qui désérialise cette réponse en ignorant
  les clés inconnues continue de fonctionner sans modification — c'est précisément le comportement
  de `_serviceFromJson` (Flutter) qui ne lit que les clés qu'il connaît, et celui de tout client HTTP
  générique consommant l'OpenAPI. Aucun champ n'est renommé, retiré, retypé, ni rendu obligatoire
  côté requête (c'est une route `GET` sans corps).
- **`GET /catalog/salons` (liste, sans détail des prestations) : inchangé** — `PublicSalonResponse`
  ne porte pas de champ `services`, `image_url` n'y apparaît donc pas.
- **Aucun changement d'OpenAPI cassant** : `image_url` s'ajoute à `PublicServiceResponse` avec la
  même sémantique `null`-tolérante que `logo_url` déjà documentée.

## Data Model / Protocol Changes

**Aucune.** `image_object_key` existe déjà sur la table `services` depuis la migration `0010`
(`backend/migrations/versions/`) et sur `models.Service`
(`adapters/outbound/persistence/models.py:279`) : #158 ne lit qu'une colonne déjà écrite par le
parcours gérant existant (#17, attachement d'image), elle n'ajoute, ne modifie et ne supprime
aucune colonne, contrainte ou index. Aucune migration Alembic n'est créée par cette issue.

## Security & Privacy Considerations

- **Jamais de clé d'objet brute exposée (ADR-0005).** `image_url` est **toujours** une URL signée
  à durée limitée (`MediaStorage.presign_download`) ou `null` — jamais `image_object_key`. C'est le
  même contrat que `logo_url`/`photos[].url`, déjà en production sur cette route ; #158 ne fait
  qu'étendre une garantie existante à un champ de plus, pas en introduire une nouvelle.
- **Aucune PII supplémentaire.** Une photo de prestation (coupe, coiffure) n'est pas une donnée
  personnelle identifiante au sens du PRD §11.3 — contrairement aux fiches client (#28, #156) ou aux
  notes internes, ce n'est pas un champ sensible ; il reste toutefois soumis à la même politique de
  bucket privé et d'URL signée que toute autre image du produit (logo, photos de salon), par
  cohérence et défense en profondeur, pas par nécessité de confidentialité propre à la photo
  elle-même.
- **Pas de nouvelle surface publique.** La route `GET /catalog/salons/{salon_id}` est **déjà**
  publique et documentée comme telle (`catalog.py:9-21`) ; #158 n'ajoute aucun chemin à
  `PUBLIC_ROUTE_PATHS`, ne modifie aucune garde d'authentification/autorisation, et n'introduit
  aucun nouveau rôle ni permission.
- **Résilience du stockage non configuré.** Comme pour `logo_url`, l'absence de `MediaStorage`
  configuré (`app.state.media_storage is None`) ne doit **jamais** produire une erreur `5xx` : la
  réponse reste `200` avec `image_url: null` sur chaque prestation concernée — cohérent avec
  l'exigence de résilience réseau du jalon M7 (décision 9, catalogue pouvant tolérer un mode
  dégradé côté média sans bloquer l'affichage des prestations sur la borne).
- **Pas d'implication pour l'anti-oracle ADR-0026.** Cette issue ne touche à aucune donnée de
  `CustomerProfile`/`User` ni à la recherche par téléphone (#156) : aucun lien avec la règle
  anti-oracle du dépôt.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_get_public_salon_usecase.py`** (patron des tests déjà présents pour `logo_url`) :
  - une prestation avec `image_object_key` renseigné + `GetPublicSalon` construit avec
    `FakeMediaStorage` (`tests/conftest.py:640-665`) → `PublicServiceView.image_url` vaut l'URL
    déterministe renvoyée par `FakeMediaStorage.presign_download` ;
  - une prestation avec `image_object_key=None` → `image_url is None`, **quel que soit** l'état du
    stockage ;
  - `GetPublicSalon` construit **sans** `media_storage` (valeur par défaut `None`, cas déjà couvert
    pour `logo_url`/`photos`) → `image_url is None` pour toute prestation, même avec
    `image_object_key` renseigné (pas d'exception) ;
  - la projection reste minimale : `PublicServiceView` n'expose toujours pas `is_active`,
    `salon_id` ni timestamps (non-régression de l'invariant existant).
- Vérifier qu'aucun test existant n'échoue par ajout du champ (recherche de toute assertion
  d'égalité stricte de dataclass/dict qui énumérerait explicitement tous les champs de
  `PublicServiceView`/`PublicServiceResponse` — à adapter le cas échéant plutôt que contourner).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_catalog_detail_api.py`** (fichier confirmé par lecture directe, 384 lignes,
  déjà structuré par thème — détail complet, exclusion des prestations désactivées, absence de
  champs de gestion, résolution des URLs signées, invariant deny-by-default) :
  - étendre `test_active_salon_returns_full_detail` (ligne 182) : une prestation avec
    `image_object_key` renseigné + `FakeMediaStorage` (patron `test_logo_url_is_signed_not_raw_key`,
    ligne 310) → `services[0]["image_url"]` est une URL signée non vide (contient `"?"`, diffère de
    la clé brute) ;
  - nouveau cas miroir de `test_logo_and_photos_null_without_storage` (ligne 335) : sans
    `MediaStorage` (`storage=None`) → `image_url is None` même si `image_object_key` est renseigné,
    **pas** d'exception ;
  - `test_service_item_has_no_management_fields` (ligne 298) n'affirme que l'**absence** de
    certaines clés (`is_active`, `salon_id`, `created_at`) — vérifié par lecture, ce n'est **pas**
    une égalité stricte de l'ensemble des clés : ajouter `image_url` au schéma ne le fait donc
    **pas** échouer ; y ajouter l'assertion que la **clé d'objet brute** (p. ex. le préfixe
    `services/{salon_id}/`) n'apparaît jamais dans `resp.text` lorsqu'un stockage est configuré
    (miroir `test_photos_signed_and_no_raw_key_leaks`, ligne 321) ;
  - non-régression : tous les champs déjà testés (`id`, `name`, `price`, `duration_minutes`,
    `category`, `logo_url`, `photos`, `hairdressers`, `is_bookable`) restent présents et inchangés,
    `test_no_unprotected_routes_after_detail_route` (ligne 381) continue de passer sans changement de
    garde.

### App mobile (`flutter test`)

- **`test/http_salon_catalog_gateway_detail_test.dart`** (le fichier qui teste `getSalon` et le
  mapping des services du détail — `http_salon_catalog_gateway_test.dart` ne couvre que la
  liste/`SalonSummary`) : étendre le patron déjà utilisé pour `_serviceFromJson`/`_photoFromJson`
  (groupe `mapping JSON → SalonDetail`, p. ex. `champ category d'un service mappé`, ligne 197) —
  - JSON de service avec `image_url` renseigné → `SalonService.imageUrl` égal à la valeur reçue ;
  - JSON sans clé `image_url` (rétro-compatibilité si l'app est redéployée avant le backend, ou
    inversement) → `SalonService.imageUrl == null`, **sans exception de parsing** (cohérent avec le
    traitement déjà tolérant de `logo_url`/`description`/`category`, tous castés en `String?`).
- Aucune modification attendue des tests de `ServiceListTile` ni de `_ServiceStep` (pas de widget
  test existant identifié pour ces widgets à ce jour ; si l'un existe, vérifier qu'il continue de
  passer sans changement, le champ ajouté n'étant pas lu par eux).

### Non-régression transverse

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre.
- Vérification manuelle ou test dédié : le tunnel de réservation mobile (#22) et la fiche salon
  (#19) continuent de fonctionner sans erreur de désérialisation après l'ajout du champ.

## Documentation Updates

- **`backend/README.md`** — section « Fiche salon client — détail (US-2.4, #19 — ADR-0021) » :
  ajouter `image_url` à l'exemple JSON de `services[]` et une phrase rappelant qu'il s'agit d'une
  URL signée (miroir de la phrase déjà présente pour `logo_url`/`photos`), avec une référence à
  #158 et au jalon M7.
- **Docstrings inline** (voir *Proposed Implementation* §C) : `PublicServiceView`,
  `PublicSalonDetailView`, `PublicServiceResponse`, `PublicSalonDetailResponse` — mentionner
  `image_url` parmi les champs de vitrine exposés.
- **`app-mobile/lib/domain/salon/salon_service.dart`** — commentaire d'en-tête déjà existant sur les
  champs reflétés depuis `GET /catalog/salons/{salon_id}` : ajouter `image_url` à la liste.
- **Pas de nouvel ADR.** Le mécanisme de résolution d'URL signée est déjà couvert par l'ADR-0005 et
  son application au catalogue public par l'ADR-0021 ; #158 n'introduit aucune décision
  d'architecture nouvelle (contrairement à #155 — ADR-0041, authentification de la borne — et #157 —
  ADR-0042, file d'attente walk-in — qui en nécessitent chacune une, committée avec leur
  implémentation respective). La documentation transverse du jalon M7 (runbook de provisioning,
  index `docs/adr/README.md`, vue d'ensemble) reste portée par #161 en fin de jalon.
- **PRD/BACKLOG** : pas de mise à jour immédiate — #161 (dernière issue du jalon) prévoit la mise à
  jour du PRD/BACKLOG une fois **l'ensemble** du jalon M7 livré.

## Risks and Open Questions

Cette section reprend uniquement les décisions de la liste des choix d'architecture retenus pour
M7 qui concernent directement #158, à valider par le porteur produit avant l'implémentation.

1. **Décision 9 (résilience réseau) — « catalogue pouvant être mis en cache court-terme ».** Le PRD
   ne précise pas si la borne doit mettre en cache les `image_url` signées (durées d'expiration
   généralement courtes, alignées sur `presign_download`, cf. `PresignedUpload.expires_in` côté
   upload). *Recommandation technique* : ne rien changer côté backend pour #158 (les URLs restent à
   durée limitée, comme le logo) et laisser #159 décider, à son niveau, d'une stratégie de cache
   d'image côté client kiosque (l'URL signée devra alors être **rafraîchie** à chaque nouvel appel
   catalogue plutôt que mise en cache au-delà de sa validité) — **à confirmer par le porteur produit
   avant l'implémentation de #159**, sans bloquer #158 qui ne fait qu'exposer le champ.
2. **Portée de l'affichage côté app mobile cliente (hors borne).** La mission de #158 exige
   d'ajouter le champ au modèle Flutter et au parsing « sans casser le tunnel de réservation
   existant », mais ne dit pas explicitement s'il faut déjà afficher la vignette dans
   `ServiceListTile`/`_ServiceStep` (fiche salon / réservation, hors borne). *Recommandation
   technique* : ne pas l'afficher dans #158 (ce n'est pas dans l'acceptation de l'issue, qui porte
   sur le catalogue public, pas sur l'UI mobile existante) et laisser cette amélioration UI à une
   décision produit séparée, éventuellement lors de #159. **À confirmer** : si le porteur produit
   souhaite l'affichage immédiat côté fiche salon, cela reste un ajout mineur et sans risque
   (widget `Image.network(imageUrl)` conditionnel), mais élargirait le périmètre `S` de l'issue.

## Implementation Checklist

> Les patches concrets, prêts à appliquer, sont regroupés en *Proposed Implementation §(D-bis)
> Esquisses de code* — s'y référer pour chaque étape de code ci-dessous.

1. **Lire** `adapters/inbound/services.py:198-225`, `application/catalog.py:122-266`,
   `adapters/inbound/catalog.py:90-330`, `tests/conftest.py` (`FakeMediaStorage` ligne 640,
   `FakeSalonCatalogRepository` ligne 788) — s'imprégner du mécanisme existant avant de le
   reproduire.
2. **`application/catalog.py`** : ajouter `image_url: str | None` à `PublicServiceView` (ligne 122) ;
   transformer `_to_service_view` (ligne 243, actuellement `@staticmethod`) en méthode d'instance de
   `GetPublicSalon` appelant `self._sign(service.image_object_key)` (réutilise `_sign`, ligne 261).
3. **`adapters/inbound/catalog.py`** : ajouter `image_url: str | None` à `PublicServiceResponse`
   (ligne 90) ; propager `image_url=service.image_url` dans la liste en compréhension de
   `_public_salon_detail_response` (ligne 186).
4. **Tests backend** : étendre `tests/test_get_public_salon_usecase.py` (image présente/absente,
   stockage configuré/non configuré) puis `tests/test_catalog_detail_api.py` (fichier confirmé,
   cf. *Testing Plan*).
5. **`app-mobile/lib/domain/salon/salon_service.dart`** : ajouter le champ `imageUrl` optionnel.
6. **`app-mobile/lib/adapters/data/http_salon_catalog_gateway.dart`** : lire `image_url` dans
   `_serviceFromJson` (ligne 167).
7. **Tests Flutter** : étendre `test/http_salon_catalog_gateway_detail_test.dart` (présence/absence
   de la clé `image_url` dans le mapping des services du détail).
8. **Documentation** : mettre à jour l'exemple JSON et les phrases de `backend/README.md` (section
   fiche salon client, US-2.4/#19), les docstrings inline concernées, et le commentaire d'en-tête de
   `salon_service.dart`.
9. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test),
   `ruff check` ; relire la PR pour confirmer qu'aucune clé d'objet brute ne transite dans une
   réponse HTTP et qu'**aucune signature IA** n'a été introduite dans le code, les commits ou la PR.
