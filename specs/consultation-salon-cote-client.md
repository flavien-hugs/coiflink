# Consultation d'un salon (côté client) — US-2.4 / issue #19

> Issue GitHub **#19** — `feature` `ux` · Priorité **Must** · Effort **M** · PRD §6 (Épic 2, US-2.4),
> §7.1 (« Fiche salon » / détail depuis la recherche), §5.1 (parcours client : étape 4, il consulte
> un salon avant de réserver), §8.3 (visibilité : un salon inactif n'est jamais visible côté client).
> **Dépend de #16** (horaires — livrée), **#17** (prestations — livrée), **#18** (catalogue/recherche
> client — livrée). Jalon **M2** (salons & prestations, consultation client).

## Problem Statement

Le client peut désormais **rechercher et lister** les salons `ACTIVE` (#18) via `GET /catalog/salons`,
qui renvoie une **projection de vitrine minimale** (nom, localisation, logo signé, `is_bookable`).
Mais il **ne peut pas ouvrir la fiche d'un salon** : il n'existe **aucune vue de détail** exposant les
**prestations**, les **horaires**, les **prix**, la **localisation complète** et l'indication de
**disponibilité** — les informations dont il a besoin pour décider de réserver.

Deux manques concrets, backend et mobile :

1. **Backend** — la ressource `/catalog` (livrée par #18, `adapters/inbound/catalog.py`) n'expose que
   `GET /catalog/salons` (liste/recherche). Le port de lecture publique `SalonCatalogRepository`
   possède déjà une méthode **`get_active(salon_id)`** — écrite et testée par #18 mais **volontairement
   non exposée** (« préparé pour #19 », cf. ADR-0020 §Conséquences). Aucune route ne l'appelle, et la
   projection actuelle (`PublicSalonView`) **n'inclut ni les horaires, ni les prestations, ni le
   téléphone** (ce dernier explicitement « reporté au détail #19 », ADR-0020 §3). Les prestations
   `ACTIVE` d'un salon (table `services`, #17) et les horaires (`salons.opening_hours`, #16) existent en
   base mais **ne sont accessibles qu'aux routes de gestion** (`/salons/{id}/services`,
   `/salons/{id}/opening-hours`, gardées par la portée gérant) — **jamais** côté client.

2. **Application cliente (Flutter, `app-mobile/`)** — #18 a posé la première couche réseau (domaine
   `SalonSummary`, port `SalonCatalogGateway`, cas d'usage `SearchSalons`, adapter
   `HttpSalonCatalogGateway`, écran `salon_search_screen.dart`). Mais **taper sur un salon ne mène nulle
   part** : il n'y a ni entité de **détail**, ni méthode de gateway pour lire un salon, ni écran de fiche,
   ni navigation depuis la liste.

**Critères d'acceptation (issue #19)** :
- *le détail d'un salon montre prestations + horaires + disponibilité* ;
- *c'est le point d'entrée de la réservation*.

Le cœur testable est donc : (a) un endpoint `GET /catalog/salons/{salon_id}` qui, **pour un salon
`ACTIVE` seulement**, renvoie les prestations `ACTIVE`, les horaires et un indicateur de disponibilité
(§8.3), et **404** pour un salon inexistant ou non-`ACTIVE` ; (b) un écran de fiche qui l'affiche et
pose le **point d'entrée** de la réservation (la réservation elle-même est #21+).

## Goals

1. **Exposer une fiche salon publique** côté client : `GET /catalog/salons/{salon_id}`, réservé aux
   salons **`ACTIVE`** (§8.3), qui agrège en une seule réponse : identité + localisation complète
   (avec `phone`, reporté de #18), **horaires** structurés (#16), **prestations actives** avec **prix**
   et **durée** (#17), logo + photos signés, et l'indicateur `is_bookable`.
2. **Réutiliser `get_active` sans réintroduire de filtre faillible** : la fiche s'appuie sur
   `SalonCatalogRepository.get_active` (filtre `status = ACTIVE` **en SQL**, déjà livré par #18) ; un
   salon non-`ACTIVE` ou inexistant renvoie **404** (« absent du catalogue », pas d'oracle d'existence,
   ADR-0020 §3).
3. **N'exposer que des prestations `ACTIVE`** dans la fiche : une prestation désactivée (soft-delete
   #17, `is_active=false`) **n'apparaît jamais** côté client — filtre au niveau de la lecture, jamais en
   post-filtrage applicatif.
4. **Poser le « point d'entrée de la réservation »** sans implémenter la réservation : la fiche mobile
   expose une action « Réserver » dont l'état dérive de `is_bookable` (§8.3), mais **ne déclenche aucun
   flux de réservation** (#21+ non livré) — l'affordance est présente et honnête (désactivée / « bientôt
   disponible »), jamais une promesse de comportement inexistant.
5. **Étendre la couche réseau mobile** (domaine `SalonDetail`, méthode `getSalon` du gateway, cas
   d'usage `GetSalonDetail`, écran de fiche, navigation depuis la liste) en réutilisant l'architecture
   hexagonale posée par #18, testable sans réseau.
6. **Ne pas affaiblir les invariants documentés** : deny-by-default (ADR-0015), non-journalisation des
   URL signées et de la PII (§11.3), projection publique minimale sans donnée de gestion (ADR-0020),
   agnosticisme du stockage objet (ADR-0005).

## Non-Goals

Périmètre explicitement **hors** de cette issue :

- **Réservation** (choix de créneau, création de RDV, anti double-réservation) — **#21+ / Épic 3**.
  La fiche est le *point d'entrée* ; le flux de réservation lui-même n'est **pas** construit ici.
- **Disponibilité au créneau** (« ce salon a-t-il un créneau libre demain à 15 h ? ») — dépend des RDV
  (#21+) et d'un moteur de calcul de créneaux inexistant. Au MVP, la « disponibilité » affichée se
  limite à l'indicateur **`is_bookable`** (§8.3 : `ACTIVE` **et** horaires configurés) et à l'affichage
  des **horaires d'ouverture** ; le calcul de créneaux libres est **différé** (mention en Risques).
- **Filtres du catalogue par « type de prestation » / « disponibilité »** (§7.1) — restent différés
  (déjà hors périmètre en #18) ; cette issue ajoute le **détail**, pas de nouveau filtre de liste.
- **Vue carte / itinéraire** — la fiche renvoie `latitude`/`longitude` (déjà en projection #18), mais
  l'intégration cartographique et la navigation GPS sont **hors périmètre** (différées, comme en #18).
- **Notation / avis clients**, **partage**, **favoris** — hors MVP.
- **Auth / connexion client sur mobile** (#8, #10) — non implémentée côté app ; la fiche reste
  **publique** (cohérent avec la décision d'auth du catalogue, ADR-0020 §4). Cette issue ne construit
  pas l'auth mobile.
- **Écriture** de quoi que ce soit : la fiche est **strictement en lecture**. Aucune route de gestion
  (`/salons/...`) n'est réutilisée ni modifiée.
- **Consultation du journal d'audit** (#17/ADR-0019) — sans rapport avec la lecture client.

## Relevant Repository Context

### Architecture (figée par les ADR — source de vérité)

- **Application cliente** : **Flutter** / Dart `^3.12`, Android prioritaire
  ([ADR-0001](../docs/adr/0001-app-mobile-flutter.md)).
- **Backend** : **FastAPI**, API REST, **architecture hexagonale**
  ([ADR-0003](../docs/adr/0003-backend-fastapi.md), [ADR-0008](../docs/adr/0008-architecture-hexagonale.md)) :
  `domain/` → `application/` (+ `ports/`) → `adapters/inbound|outbound/`.
- **Données** : PostgreSQL 16, SQLAlchemy 2.0, Alembic
  ([ADR-0004](../docs/adr/0004-donnees-postgresql-redis.md), [ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)).
- **Autorisation** : RBAC **deny-by-default**, gardes en dépendances FastAPI
  ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) — toute route est fermée sauf
  celles listées dans `PUBLIC_ROUTE_PATHS` (choix conscient et revu ; **correspondance exacte** du
  `route.path`, cf. `is_public_path`).
- **Stockage objet** : S3-compatible, buckets privés, **URLs signées** à durée limitée, clés **sans
  PII** ([ADR-0005](../docs/adr/0005-stockage-objet-s3-compatible.md),
  [ADR-0017](../docs/adr/0017-creation-salon-medias-et-reservabilite.md)).
- **Catalogue client** : ressource distincte `/catalog` (jamais de route de gestion réutilisée),
  projection publique minimale, filtre `ACTIVE` au niveau du dépôt
  ([ADR-0020](../docs/adr/0020-catalogue-salons-cote-client.md)).

### Ce qui existe déjà et qu'il faut réutiliser (ne rien réinventer)

| Élément | Chemin | Rôle pour #19 |
| --- | --- | --- |
| Router catalogue | `backend/coiflink_api/adapters/inbound/catalog.py` | **Router cible** — y ajouter `GET /catalog/salons/{salon_id}` (même prefix `/catalog`, même patron DI). Contient déjà `PublicSalonResponse`, `_public_salon_response`, `get_salon_catalog_repository`, `get_optional_media_storage`. |
| Port catalogue + **`get_active`** | `backend/coiflink_api/application/ports/salon_catalog_repository.py` | **`get_active(salon_id) -> Salon \| None`** déjà défini et implémenté (filtre `ACTIVE` en SQL) — le socle du détail. À **étendre** d'une lecture des prestations actives (voir Proposed Implementation). |
| Dépôt SQL catalogue | `backend/coiflink_api/adapters/outbound/persistence/salon_catalog_repository.py` | `get_active` implémenté (`where(id == …, status == ACTIVE)`) ; ajouter la lecture des prestations `ACTIVE` du salon. |
| Cas d'usage catalogue | `backend/coiflink_api/application/catalog.py` | `SearchSalons`, `PublicSalonView`, `_sign` (logo → URL signée). Y ajouter `GetPublicSalon` + une **projection de détail** (`PublicSalonDetailView`). |
| Domaine `Salon` + `is_bookable` | `backend/coiflink_api/domain/salon.py` | Entité de lecture ; `opening_hours: dict \| None` ; propriété `is_bookable` (§8.3). Réutilisée telle quelle. |
| Domaine prestation | `backend/coiflink_api/domain/service.py` ; port `application/ports/service_repository.py` ; dépôt `adapters/outbound/persistence/service_repository.py` | `Service` (name, description, price `Decimal`, duration_minutes, category, is_active). `ServiceRepository.list_for_salon(salon_id, include_inactive=False)` renvoie **déjà** les actives seulement — lecture directement réutilisable (voir décision « port dédié vs réutilisation »). |
| Domaine horaires | `backend/coiflink_api/domain/opening_hours.py` | Contrat JSONB `{ version, timezone, weekly, exceptions }` **normalisé** (déjà validé à l'écriture #16). La fiche l'expose en lecture (donnée d'établissement, publique). |
| Réponse prestation (patron) | `backend/coiflink_api/adapters/inbound/services.py` (`ServiceResponse` : price, duration_minutes, category, is_active) | Patron de sérialisation d'une prestation ; la fiche publique en dérive une variante **sans** `is_active`/`salon_id`. |
| Lecture médias signés | `backend/coiflink_api/application/salons.py` (`_SalonReader._sign`, `list_photos`) | Résolution logo **et photos** → URLs signées, à réutiliser dans la projection de détail. |
| Gardes & invariant public | `backend/coiflink_api/adapters/inbound/security.py` (`PUBLIC_ROUTE_PATHS`, `is_public_path`, `unprotected_routes`) | Ajouter le **chemin littéral** `"/catalog/salons/{salon_id}"` (correspondance exacte du `route.path`) si l'on garde l'option publique. |
| Tests deny-by-default | `backend/tests/test_security_guards.py` | Toute nouvelle route y est soumise : publique-listée **ou** gardée, jamais orpheline. |
| Couche réseau mobile (#18) | `app-mobile/lib/domain/salon/salon_summary.dart`, `lib/application/ports/salon_catalog_gateway.dart`, `lib/application/use_cases/search_salons.dart`, `lib/adapters/data/http_salon_catalog_gateway.dart`, `lib/adapters/data/api_config.dart`, `lib/adapters/ui/salon_search_screen.dart`, `widgets/salon_card.dart` | **À étendre** : nouvelle entité de détail, méthode `getSalon`, cas d'usage, écran de fiche, navigation depuis la carte/liste. |

### État à connaître avant d'estimer

- **`get_active` est déjà là.** La moitié « accès sécurisé §8.3 » du backend est faite (#18) ; #19
  consiste surtout à **agréger** (prestations + horaires + médias) et à **projeter** proprement, puis à
  exposer la route (publique-listée) et à construire l'**écran mobile + la navigation**.
- **La réservation n'existe pas** (aucune route ni écran #21+). Le « point d'entrée » se limite donc à
  une **affordance honnête** (bouton dérivé de `is_bookable`), pas à un flux réel.
- **Le mobile a désormais une couche réseau** (#18) : le détail réutilise le même patron hexagonal
  (domaine pur, port, cas d'usage, adapter HTTP, écran). La navigation entre écrans est en revanche
  **neuve** (l'app n'a aujourd'hui que la recherche).

### Commandes (déjà en place)

- Backend : `pytest`, `ruff check`, round-trip Alembic (CI, PostgreSQL 16).
- Mobile : `flutter test`, `flutter analyze`, `flutter build apk`.
- Test gate agrégé : `scripts/test-gate.sh` (parité CI).

## Proposed Implementation

Deux tranches : **(A)** l'endpoint de détail backend (`ACTIVE`-only, agrégeant prestations + horaires) ;
**(B)** l'écran de fiche mobile + la navigation. La tranche (A) porte le **critère d'acceptation
testable** et se valide par `pytest` indépendamment de (B).

### A. Backend — fiche salon publique `GET /catalog/salons/{salon_id}`

#### A.1 Route dans le router `/catalog` existant

Ajouter dans `adapters/inbound/catalog.py` (ne créer **aucun** nouveau router) :

```
GET /catalog/salons/{salon_id}   (salon_id: uuid.UUID)   → 200 | 404
```

Le `salon_id` est typé `uuid.UUID` : une valeur mal formée renvoie **422** (validation FastAPI), un
UUID inconnu ou non-`ACTIVE` renvoie **404** (via le cas d'usage). Cette route **suit** `GET
/catalog/salons` dans le même router — pas de collision (le prefix `/catalog` isole déjà des routes de
gestion `/salons/...`).

#### A.2 Authentification — **route publique** (cohérent ADR-0020 §4)

Recommandé : **publique**, comme `GET /catalog/salons`. Ajouter le **chemin littéral**
`"/catalog/salons/{salon_id}"` à `PUBLIC_ROUTE_PATHS` (`is_public_path` compare le `route.path` **à
l'identique**, placeholder compris — un préfixe ne suffit pas). Justification identique à #18 : lecture
seule, données de **vitrine publiques** d'un salon `ACTIVE` (l'auth cliente mobile n'existe pas encore ;
parcours §7.1/§5.1 « consulter avant connexion »). Le test `unprotected_routes(app)` reste l'arbitre.

> **Décision à confirmer** (voir Risques) : si l'on retenait plutôt l'option **authentifiée**
> (`require_permission(SALON_READ_ANY)`), la projection et le filtre `ACTIVE` seraient **inchangés** —
> seule la garde du router changerait, et il ne faudrait **pas** ajouter le chemin à
> `PUBLIC_ROUTE_PATHS`. Mais cela suppose l'auth client livrée sur mobile (elle ne l'est pas) → bloque
> la tranche (B). Le spec est écrit pour l'**option publique**.

#### A.3 Lecture des données — réutiliser `get_active`, ajouter la lecture des prestations actives

Le salon lui-même vient de **`SalonCatalogRepository.get_active(salon_id)`** (déjà livré) : `None`
si absent ou non-`ACTIVE` → `SalonNotFound` → **404**.

Pour les **prestations actives**, deux options (voir Risques, décision 2) :

- **Recommandé — méthode de lecture dédiée sur le port catalogue** : ajouter
  `list_active_services(salon_id) -> tuple[Service, ...]` à `SalonCatalogRepository` (implémentée dans
  `SqlSalonCatalogRepository` par `select(models.Service).where(salon_id == …, is_active.is_(True))`,
  triée). Motif ADR-0020 §2 : le catalogue **n'hérite d'aucune capacité de gestion** — on ne lui confie
  pas le `ServiceRepository` complet (qui porte `create`/`update`/`set_active`). Le filtre `is_active`
  vit ainsi côté lecture publique, non négociable.
- **Alternative — réutiliser `ServiceRepository.list_for_salon(salon_id, include_inactive=False)`** :
  déjà « actives seulement ». Moins de code, mais expose au cas d'usage un port de gestion (surface
  d'écriture) — à éviter au regard de l'invariant d'isolation d'ADR-0020.

Les **photos** et le **logo** sont résolus en URLs signées comme dans `_SalonReader` (réutiliser la
logique `_sign` déjà présente dans `application/catalog.py`, et `repository.list_photos` — soit via une
lecture ajoutée au port catalogue, soit en gardant les photos hors périmètre au MVP, voir décision 3).

#### A.4 Cas d'usage & projection de détail

Nouveau cas d'usage `GetPublicSalon` dans `application/catalog.py`, sur le patron de `SearchSalons` /
`GetSalon` :

```python
class GetPublicSalon:
    def __init__(self, repo: SalonCatalogRepository, media: MediaStorage | None): ...
    def execute(self, salon_id: uuid.UUID) -> PublicSalonDetailView:
        salon = self._repo.get_active(salon_id)
        if salon is None:
            raise SalonNotFound("Salon introuvable.")   # → 404 côté adapter
        services = self._repo.list_active_services(salon_id)
        ...  # projeter, signer logo + photos, exposer opening_hours + is_bookable
```

**Projection de détail** `PublicSalonDetailView` / `PublicSalonDetailResponse` — étend la vitrine (#18)
des champs de détail :

| Exposé | Origine | Raison |
| --- | --- | --- |
| `id`, `name`, `description` | `Salon` | vitrine |
| `address`, `city`, `commune`, `latitude`, `longitude` | `Salon` | localisation complète |
| **`phone`** | `Salon.phone` | **reporté de #18 au détail** (ADR-0020 §3) — donnée d'établissement, publique |
| `logo_url` (signé ou `null`) | `MediaStorage` | vitrine ; jamais la clé brute |
| **`photos`** : `[{ id, url }]` (signées) | `list_photos` | galerie de la fiche *(peut être différé, décision 3)* |
| **`opening_hours`** : `{ timezone, weekly, exceptions }` | `Salon.opening_hours` | **horaires (critère #19)** — JSONB normalisé, publié tel quel ; `null` si non configuré |
| **`services`** : `[{ id, name, description, price, duration_minutes, category }]` | `list_active_services` | **prestations + prix (critère #19)**, **actives seulement** |
| `is_bookable` | `Salon.is_bookable` | **disponibilité (critère #19)** — §8.3 |

| **Jamais exposé** | Raison |
| --- | --- |
| `owner_id` | identifiant de compte — oracle potentiel |
| `status` | seul `ACTIVE` est renvoyé → redondant ; ne pas divulguer l'état de modération |
| `is_active` / `salon_id` d'une prestation | interne (§gestion) ; seules les actives remontent, `salon_id` est déjà celui de la fiche |
| `created_at` / `updated_at` (salon & prestations) | interne |
| clés d'objet brutes (logo/photos) | jamais — uniquement des URLs signées (ADR-0005) |

Le montant `price` est sérialisé comme dans `ServiceResponse` (`decimal.Decimal`) ; `latitude` /
`longitude` en nombres (comme la vitrine #18).

#### A.5 Câblage

- La route est ajoutée au **router existant** (déjà `include_router`é dans `main.py`) — rien à câbler
  côté `main.py`.
- `PUBLIC_ROUTE_PATHS` : ajouter `"/catalog/salons/{salon_id}"` (commentaire de revue de sécurité), sinon
  `unprotected_routes(app)` échoue (garde-fou attendu).
- Réutiliser `get_optional_media_storage` (déjà importé dans `catalog.py`) : `None` → `logo_url`/photos
  `null`, jamais d'erreur.
- **Ne pas** modifier la matrice de permissions, ni les routes `/salons/...`, ni la liste/recherche
  `GET /catalog/salons`.

### B. Application mobile (Flutter) — fiche salon + navigation

Tranche hexagonale (ADR-0008), testable **sans réseau**, réutilisant la couche #18 :

```
app-mobile/lib/
  domain/salon/
    salon_detail.dart          # entité de détail : identité + phone + localisation
                               # + openingHours + services + photos + isBookable
    salon_service.dart         # prestation de vitrine (name, description, price, durationMinutes, category)
    opening_hours.dart         # horaires : timezone + weekly (jour→intervalles) + exceptions
  application/
    ports/salon_catalog_gateway.dart     # + Future<SalonDetail> getSalon(String id)
    use_cases/get_salon_detail.dart      # orchestration + gestion d'erreur (404 → introuvable)
  adapters/
    data/http_salon_catalog_gateway.dart # + GET /catalog/salons/{id} ; mapping JSON → SalonDetail
    ui/
      salon_detail_screen.dart           # fiche : logo/photos, description, localisation,
                                         # horaires, prestations+prix, badge is_bookable, CTA « Réserver »
      widgets/service_list_tile.dart     # ligne prestation (nom, prix, durée)
      widgets/opening_hours_view.dart    # horaires par jour (+ jours fermés)
```

- **Gateway** : ajouter `getSalon(String id)` au port `SalonCatalogGateway` existant et l'implémenter
  dans `HttpSalonCatalogGateway` (mapping JSON → `SalonDetail`, y compris `services`, `opening_hours`,
  `photos`) ; **404 → une exception domaine dédiée** (« salon introuvable ») distincte d'une erreur
  réseau générique, pour que l'écran affiche un état « introuvable » propre.
- **Cas d'usage** `GetSalonDetail` : prend un `id`, appelle le gateway, remonte le détail ou l'erreur.
- **Navigation** : rendre la `salon_card` (liste #18) **cliquable** → pousse `salon_detail_screen` (via
  `Navigator`). Introduire la navigation entre écrans (aujourd'hui l'app n'a que la recherche).
- **Écran de fiche** : en-tête (logo/photos, nom, localisation, badge `is_bookable`), section
  **horaires** (par jour, jours fermés lisibles ; « Horaires non renseignés » si `null`), section
  **prestations** (nom, **prix**, durée ; « Aucune prestation » si vide), **téléphone** (action
  d'appel facultative), et le **point d'entrée réservation** : un bouton « Réserver » **dérivé de
  `is_bookable`** — désactivé + « Bientôt disponible » si `false` ; si `true`, bouton présent mais
  **explicitement non fonctionnel** (« Réservation bientôt disponible », #21+) — **ne pas** simuler un
  flux inexistant (voir décision 4).
- **États** : chargement (spinner), **erreur réseau** (message + « Réessayer »), **salon introuvable**
  (404 → message dédié, retour à la liste).
- Le domaine et les cas d'usage **ne dépendent pas de Flutter** ; seuls `adapters/ui` et
  `adapters/data` importent `flutter`/`http`. Aucune journalisation d'URL signée ni de PII.

## Affected Files / Packages / Modules

### `backend/`

**À modifier**
- `coiflink_api/adapters/inbound/catalog.py` — nouvelle route `GET /catalog/salons/{salon_id}`,
  `PublicSalonDetailResponse` (+ sous-modèles `PublicServiceResponse`, `OpeningHoursResponse`,
  `PublicSalonPhotoResponse`), mappeur `_public_salon_detail_response`, DI du cas d'usage.
- `coiflink_api/application/catalog.py` — `GetPublicSalon`, `PublicSalonDetailView` (+ sous-vues).
- `coiflink_api/application/ports/salon_catalog_repository.py` — ajouter `list_active_services`
  (et, si photos incluses, une lecture des photos) au `Protocol`.
- `coiflink_api/adapters/outbound/persistence/salon_catalog_repository.py` — implémenter
  `list_active_services` (`select(models.Service).where(salon_id, is_active)`), (+ photos si retenu).
- `coiflink_api/adapters/inbound/security.py` — ajouter `"/catalog/salons/{salon_id}"` à
  `PUBLIC_ROUTE_PATHS` (si option publique).
- `tests/conftest.py` — enrichir `FakeSalonCatalogRepository` (prestations actives + inactives, un
  salon non-`ACTIVE`) pour les tests de fiche.
- `backend/README.md` — documenter la nouvelle route.

**À créer**
- `tests/test_get_public_salon_usecase.py` (cas d'usage, fakes).
- `tests/test_catalog_detail_api.py` (API/intégration `TestClient`).

**Sans modification** : `models.py`, migrations (**aucune**), `permissions.py`, domaine
`salon.py`/`service.py`/`opening_hours.py` (réutilisés en lecture), routes `/salons/...`.

### `app-mobile/`

**À créer** : `lib/domain/salon/salon_detail.dart`, `lib/domain/salon/salon_service.dart`,
`lib/domain/salon/opening_hours.dart`, `lib/application/use_cases/get_salon_detail.dart`,
`lib/adapters/ui/salon_detail_screen.dart`, `lib/adapters/ui/widgets/service_list_tile.dart`,
`lib/adapters/ui/widgets/opening_hours_view.dart`, tests associés sous `test/`.

**À modifier** : `lib/application/ports/salon_catalog_gateway.dart` (+ `getSalon`),
`lib/adapters/data/http_salon_catalog_gateway.dart` (mapping détail), `lib/adapters/ui/salon_search_screen.dart`
et/ou `widgets/salon_card.dart` (navigation au tap), `app-mobile/README.md`.

### Racine / doc

`README.md` (module 2 / section 6 « M2 en cours »), nouvel ADR
`docs/adr/0021-consultation-salon-cote-client.md` + `docs/adr/README.md`.

## API / Interface Changes

**Nouvelle route REST** :

### `GET /catalog/salons/{salon_id}` → `200 OK` | `404 Not Found`

Fiche publique d'un salon **`ACTIVE` uniquement** (§8.3). `salon_id` : `uuid.UUID`.

```jsonc
// Réponse 200
{
  "id": "…uuid…",
  "name": "Salon Élégance",
  "description": "Coiffure afro et tresses.",
  "phone": "+2250700000000",
  "address": "Rue des Jardins, Cocody",
  "city": "Abidjan",
  "commune": "Cocody",
  "latitude": 5.359952,
  "longitude": -3.996643,
  "logo_url": "https://…signée…",        // ou null
  "photos": [ { "id": "…uuid…", "url": "https://…signée…" } ],  // ou [] (voir décision 3)
  "opening_hours": {                      // ou null si non configuré
    "timezone": "Africa/Abidjan",
    "weekly": { "mon": [ { "start": "08:00", "end": "18:00" } ], "sun": [] },
    "exceptions": [ { "date": "2026-12-25", "closed": true, "intervals": [] } ]
  },
  "services": [                           // prestations ACTIVE uniquement
    {
      "id": "…uuid…",
      "name": "Coupe homme",
      "description": "…",
      "price": "5000.00",
      "duration_minutes": 30,
      "category": "Coupe"
    }
  ],
  "is_bookable": false                    // §8.3 : ACTIVE mais sans horaire ⇒ pas encore réservable
}
```

Codes : `200` ; `404` (salon inexistant **ou** non-`ACTIVE`) ; `422` (`salon_id` mal formé). Si **option
authentifiée** : ajouter `401` (non authentifié) / `403` (rôle sans `SALON_READ_ANY`).

**Aucun champ** `owner_id`/`status`/timestamps ; aucune prestation `is_active=false` ; aucune clé d'objet
brute. Le corps `404` réutilise le format d'erreur générique existant (message neutre).

**Interfaces internes documentées** : port `SalonCatalogRepository` étendu de `list_active_services`
(docstring de module) ; cas d'usage `GetPublicSalon`. **Aucune** permission nouvelle ; **aucun**
changement CLI.

**Mobile** : port `SalonCatalogGateway` étendu de `getSalon(String id)` (contrat interne au paquet) ;
aucune nouvelle variable de build (réutilise `API_BASE_URL` via `--dart-define`, #18).

## Data Model / Protocol Changes

**Aucune.** Toutes les données existent : colonnes de `salons` (dont `phone`, `opening_hours`,
`logo_object_key`), table `services` (#17), table `salon_photos` (#15). **Aucune migration Alembic.**
Le format sur le fil est du JSON REST ; `opening_hours` est le JSONB **normalisé** déjà validé à
l'écriture (#16), republié en lecture.

## Security & Privacy Considerations

1. **Deny-by-default** ([ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)) — invariant à
   ne jamais affaiblir. En option publique, l'ajout de `"/catalog/salons/{salon_id}"` à
   `PUBLIC_ROUTE_PATHS` est une **décision de sécurité consciente** à documenter (ADR-0021) : route
   **lecture seule**, données de **vitrine publiques** d'un salon `ACTIVE`, sans `owner_id` ni PII de
   gestion. `is_public_path` faisant une **correspondance exacte** du `route.path`, il faut le chemin
   **avec** le placeholder `{salon_id}` (un préfixe n'expose rien). `unprotected_routes(app)` reste
   l'arbitre : publique-listée **ou** gardée, jamais orpheline.
2. **Règle de visibilité §8.3** — la fiche s'appuie **exclusivement** sur `get_active` (filtre
   `status = ACTIVE` en SQL) : un salon `INACTIVE`/`SUSPENDED` ou inexistant → `None` → **404**. Pas
   d'oracle : « absent » plutôt que « masqué ». **À figer par test.**
3. **Prestations actives seulement** — le filtre `is_active = true` est appliqué **en base** (jamais
   post-filtrage). Une prestation soft-deletée (#17) ne fuit jamais côté client. **À figer par test.**
4. **Projection minimale** — pas d'`owner_id`, pas de `status`, pas de `is_active`/`salon_id`/timestamps
   de prestation, jamais de clé d'objet brute. Le `phone` du salon est une **donnée d'établissement**
   (numéro professionnel), volontairement publié au détail (ADR-0020 §3) — **pas** un numéro personnel
   de client.
5. **Stockage objet** ([ADR-0005](../docs/adr/0005-stockage-objet-s3-compatible.md)) — `logo_url` et
   `photos[].url` sont **toujours des URLs signées** (réutiliser `_sign`), jamais des clés/URL de bucket.
   `media_storage is None` → `null`/`[]`, pas d'erreur.
6. **Non-journalisation** (§11.3) — ne jamais journaliser d'URL signée (secret porteur), ni le `phone`,
   ni les coordonnées. `backend/tests/test_secrets_policy.py` doit rester vert.
7. **Mobile** — `API_BASE_URL` injecté au build (`--dart-define`), **jamais** de secret dans l'APK ; en
   option publique, **aucun jeton** manipulé pour cet écran. La couche data ne journalise ni URL signée
   ni PII.
8. **Résidence des données** — inchangée (ADR-0011, `europe-west4`) ; aucune nouvelle donnée stockée.

Aucune autre contrainte documentée n'est touchée.

## Testing Plan

### Backend — unitaires (`pytest`, sans base ni réseau)

- `tests/test_get_public_salon_usecase.py` (avec `FakeSalonCatalogRepository` enrichi) :
  - salon `ACTIVE` → détail complet ; salon `INACTIVE`/`SUSPENDED`/inconnu → `SalonNotFound` ;
  - `services` ne contient **que** les prestations `is_active=true` ;
  - `opening_hours` remontés tels quels ; `null` si non configuré → `is_bookable=false` (§8.3) ;
  - `logo_url`/`photos` signés via `FakeMediaStorage` ; `null`/`[]` si `media_storage=None` ;
  - `owner_id`/`status`/`is_active`/`salon_id`/timestamps **absents** de la projection.

### Backend — API / intégration (`TestClient`)

- `tests/test_catalog_detail_api.py` :
  - **critère §8.3** : `GET /catalog/salons/{id}` d'un salon `INACTIVE`/`SUSPENDED` → **404** ;
    UUID inconnu → **404** ; `salon_id` mal formé → **422** ;
  - salon `ACTIVE` → **200** avec `services` (**actives seulement**), `opening_hours`, `price`,
    `is_bookable` ; une prestation désactivée n'apparaît pas ;
  - la réponse **ne contient jamais** `owner_id`, ni clé d'objet brute, ni prestation `is_active` ;
  - **option publique** : répond **sans jeton** (`200`/`404`) ; `unprotected_routes(app)` cohérent ;
  - (**si option authentifiée** : sans jeton → `401` ; rôle sans `SALON_READ_ANY` → `403`).
- `tests/test_security_guards.py` (existant) : reste vert — nouvelle route publique-listée **ou** gardée.

### Backend — intégration base (si dépôt SQL testé contre PostgreSQL)

- `get_active` + `list_active_services` : vérifier que `status = ACTIVE` et `is_active = true`
  s'appliquent bien en SQL (jeu de salons/prestations mixtes).

### Mobile (`flutter test`)

- `test/get_salon_detail_test.dart` — cas d'usage avec **faux gateway** : mapping du détail, salon
  introuvable (404 → exception domaine dédiée).
- `test/http_salon_catalog_gateway_detail_test.dart` — mapping JSON → `SalonDetail` (services,
  opening_hours, photos, `logo_url` null), `404` → exception « introuvable », autre non-200 → exception
  réseau ; **aucune** URL/PII journalisée.
- `test/salon_detail_screen_test.dart` (widget) — états chargement / détail / introuvable / erreur ;
  prestations + prix rendus ; horaires par jour ; badge/CTA « Réserver » dérivé de `is_bookable`
  (désactivé + « Bientôt disponible » si `false`) et **jamais** de flux de réservation déclenché.
- Navigation : taper une `salon_card` ouvre la fiche (test widget).
- `flutter analyze` propre ; `flutter build apk --dart-define=API_BASE_URL=…` réussit.

### Documentation

- Vérifier que la doc décrit la **consultation** livrée et **ne laisse pas entendre** que la
  **réservation** (#21+) ou un **calcul de créneaux** existent.

## Documentation Updates

- **Nouvel ADR** `docs/adr/0021-consultation-salon-cote-client.md` : (a) route de détail dans le router
  `/catalog` réutilisant `get_active` (§8.3, 404 sans oracle) ; (b) **décision d'authentification**
  (publique — cohérence ADR-0020 — vs `SALON_READ_ANY`) ; (c) **projection de détail** (prestations
  **actives**, horaires, `phone` reporté de #18, photos, `is_bookable` comme « disponibilité » MVP) ;
  (d) décision « port de lecture dédié `list_active_services` vs réutilisation de `ServiceRepository` » ;
  (e) le « point d'entrée réservation » est une **affordance**, la réservation restant #21+. Indexer
  dans `docs/adr/README.md`.
- **`README.md` (racine)** : module 2 — mentionner `GET /catalog/salons/{salon_id}` (fiche client,
  `ACTIVE`-only, prestations + horaires + `is_bookable`) ; mettre à jour la section 6 (« M2 en cours »).
- **`backend/README.md`** : nouvelle route et sa réponse.
- **`app-mobile/README.md`** : écran de fiche, navigation depuis la liste, méthode `getSalon`.
- **OpenAPI** : `summary`/`responses`/docstring de la route (patron `catalog.py`/`salons.py`).

## Risks and Open Questions

### Décisions à confirmer

1. **Authentification de la fiche : publique ou `SALON_READ_ANY` ?** *(recommandé : publique, cohérent
   avec ADR-0020 §4)*. Publique débloque le mobile (pas d'auth client) et colle au parcours §7.1/§5.1 ;
   coût : une addition revue à `PUBLIC_ROUTE_PATHS` (chemin **avec** placeholder). L'option authentifiée
   ne change que la garde du router mais **suppose #8/#10 mobile livrés** (ils ne le sont pas) → bloque
   (B). À trancher **avant** l'implémentation.
2. **Lecture des prestations : méthode dédiée sur le port catalogue vs réutilisation de
   `ServiceRepository` ?** *(recommandé : `list_active_services` sur `SalonCatalogRepository`)* — garde
   l'invariant ADR-0020 (le catalogue n'hérite d'aucune capacité de gestion) et loge le filtre
   `is_active` côté lecture publique. La réutilisation de `ServiceRepository.list_for_salon(...,
   include_inactive=False)` est plus courte mais expose un port d'écriture au cas d'usage.
3. **Photos dans la fiche MVP : incluses ou différées ?** *(recommandé : inclure — la galerie enrichit la
   décision d'achat et la lecture signée est déjà écrite)*. Si l'effort déborde, `photos: []` (ou champ
   omis) est une **coupe légitime** ; le logo suffit à la vitrine. À confirmer côté produit.
4. **Forme du « point d'entrée réservation » sans réservation (#21+).** *(recommandé : bouton
   « Réserver » présent mais **désactivé/placeholder**, état dérivé de `is_bookable`)*. Il **ne faut
   pas** simuler un flux inexistant ni laisser croire que la réservation marche. Alternative : n'afficher
   qu'un badge de disponibilité sans bouton. À trancher côté produit/UX.
5. **Périmètre du champ `opening_hours` publié** — publier le JSONB normalisé complet (`weekly` +
   `exceptions` + `timezone`) ou un sous-ensemble « affichage » ? *(recommandé : publier tel quel — c'est
   de la donnée d'établissement publique, déjà normalisée ; le formatage est une responsabilité du
   client)*.

### Risques

- **La « disponibilité » attendue par l'issue ≠ disponibilité au créneau.** Le critère « prestations +
  horaires + disponibilité » est satisfait au MVP par `is_bookable` (§8.3) + horaires ; le **calcul de
  créneaux libres** dépend des RDV (#21+) et est **explicitement différé**. À énoncer clairement dans
  l'ADR pour ne pas sur-promettre.
- **« Point d'entrée de la réservation » sans réservation.** Risque de laisser croire que la réservation
  existe. Mitigation : CTA honnête (décision 4) et relecture doc (aucune mention d'un flux #21+ livré).
- **Navigation mobile neuve.** L'app n'a aujourd'hui que l'écran de recherche ; introduire la navigation
  (liste → fiche) est un petit coût structurel réutilisé par #21+. À faire simplement (`Navigator.push`).
- **Coût d'agrégation backend faible mais réel** — jointure logique salon + prestations + photos ;
  attention au N+1 (une requête prestations, une requête photos par fiche — acceptable pour un détail
  unitaire). Coupe légitime si l'effort déborde : livrer (A) + tests §8.3/prestations-actives (le cœur
  du critère) et un écran mobile minimal (identité + horaires + prestations, photos et CTA en suivi).
- **Correspondance exacte de `PUBLIC_ROUTE_PATHS`** — oublier le placeholder `{salon_id}` rendrait la
  route orpheline (échec `unprotected_routes`) : bien ajouter `"/catalog/salons/{salon_id}"`.

## Implementation Checklist

> Ordre conçu pour livrer d'abord le cœur testable (A), puis l'écran (B).

### Backend — fiche `ACTIVE`-only (tranche A)

1. **Trancher les décisions 1 à 5** (au minimum 1 et 2 — elles conditionnent le câblage et un test).
2. Étendre le port `application/ports/salon_catalog_repository.py` :
   `list_active_services(salon_id) -> tuple[Service, ...]` (+ lecture photos si décision 3 = inclure).
3. Implémenter dans `SqlSalonCatalogRepository` : `list_active_services`
   (`select(Service).where(salon_id == …, is_active.is_(True)).order_by(...)`), (+ photos).
4. Ajouter `GetPublicSalon` et `PublicSalonDetailView` (+ sous-vues) à `application/catalog.py` :
   `get_active` → `404` si `None` ; agrégation prestations/horaires/médias ; logo & photos signés via
   `_sign` ; **jamais** `owner_id`/`status`/`is_active`.
5. Enrichir `FakeSalonCatalogRepository` (`tests/conftest.py`) : prestations actives **et** inactives,
   un salon non-`ACTIVE`. Écrire `tests/test_get_public_salon_usecase.py`. ✅ vert.
6. Ajouter la route `GET /catalog/salons/{salon_id}` à `adapters/inbound/catalog.py`
   (`PublicSalonDetailResponse` + sous-modèles, `_public_salon_detail_response`, DI, docstrings OpenAPI,
   `404` sur `SalonNotFound`).
7. **Option publique** : ajouter `"/catalog/salons/{salon_id}"` à `PUBLIC_ROUTE_PATHS` (commentaire de
   revue) ; **option authentifiée** : `require_permission(SALON_READ_ANY)`.
8. Écrire `tests/test_catalog_detail_api.py` — **404 pour non-`ACTIVE`**, prestations **actives
   seulement**, absence d'`owner_id`, `is_bookable` cohérent. Vérifier `test_security_guards.py` et
   `test_secrets_policy.py` verts, `ruff check` propre.

### Mobile — fiche + navigation (tranche B)

9. `lib/domain/salon/salon_service.dart`, `opening_hours.dart`, `salon_detail.dart` (entités pures).
10. Étendre `lib/application/ports/salon_catalog_gateway.dart` : `Future<SalonDetail> getSalon(String id)`
    + exception domaine « salon introuvable » (distincte de `SalonCatalogException`).
11. `lib/application/use_cases/get_salon_detail.dart`.
12. Étendre `lib/adapters/data/http_salon_catalog_gateway.dart` : `GET /catalog/salons/{id}`, mapping
    JSON → `SalonDetail` (services, opening_hours, photos), `404` → exception « introuvable », autre
    non-200 → exception réseau ; **aucune** journalisation d'URL/PII.
13. `lib/adapters/ui/salon_detail_screen.dart` + `widgets/service_list_tile.dart` +
    `widgets/opening_hours_view.dart` : identité, localisation, horaires, prestations+prix, badge/CTA
    « Réserver » dérivé de `is_bookable` (honnête, sans flux #21+), états chargement/introuvable/erreur.
14. Rendre `salon_card` cliquable → `Navigator.push` vers la fiche (depuis `salon_search_screen.dart`).
15. Tests : `get_salon_detail_test.dart`, `http_salon_catalog_gateway_detail_test.dart`,
    `salon_detail_screen_test.dart`, navigation ; `flutter analyze` ;
    `flutter build apk --dart-define=API_BASE_URL=…`.

### Documentation & vérification

16. Rédiger l'ADR `0021-consultation-salon-cote-client.md` (décisions 1–5) + l'indexer dans
    `docs/adr/README.md`.
17. Mettre à jour `README.md` (racine, module 2 + section 6), `backend/README.md`, `app-mobile/README.md`.
18. Relire : **rien** dans la doc ne doit laisser entendre que la **réservation** (#21+) ou un **calcul
    de créneaux** sont implémentés — la fiche est le *point d'entrée*, pas le flux.
19. `scripts/test-gate.sh` vert (parité CI : `pytest` + `npm test` + `flutter test`).
