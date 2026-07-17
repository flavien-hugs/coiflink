# ADR-0020 : Catalogue de salons côté client — ressource publique distincte, filtre `ACTIVE` & projection de vitrine

- **Statut** : Accepté
- **Date** : 2026-07-17
- **Décideurs** : équipe CoifLink
- **Issue** : #18 (US-2.3 — Recherche & liste des salons, côté client)
- **Référence PRD** : §7.1 (écran « Recherche de salons »), §5.1 (parcours client, étape 3), §8.3
  (visibilité : « un salon inactif ne doit plus être visible dans l'application client »), §4.1
  (permission `SALON_READ_ANY` du rôle `CLIENT`), §11.2/§11.3 (isolation, PII), §12 (budget)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal — port de lecture dédié),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, liste blanche testée),
  [ADR-0005](./0005-stockage-objet-s3-compatible.md) (URLs signées),
  [ADR-0017](./0017-creation-salon-medias-et-reservabilite.md) (`is_bookable` dérivé, jamais persisté),
  [ADR-0001](./0001-app-mobile-flutter.md) (application mobile Flutter)

## Contexte et problème

Un gérant peut créer un salon (#15), configurer ses horaires (#16) et ses prestations (#17). Toute
cette matière est **invisible pour le client** : les seules routes de lecture de salons sont
orientées **gestion** (`GET /salons` = « mes salons », portée gérant ; `GET /salons/{salon_id}` =
portée salon). Aucune ne convient à un client (ni propriétaire, ni membre), et la permission
`SALON_READ_ANY` du rôle `CLIENT` (§4.1) **n'est câblée sur aucune route**. Il n'existe donc **aucun
catalogue** de salons destiné au client, ni **aucun filtre `status = ACTIVE`** (la règle de
visibilité §8.3).

US-2.3 demande qu'un client **liste/recherche les salons actifs**, un salon désactivé n'apparaissant
jamais.

## Décision

1. **Ressource distincte `/catalog/salons`** (nouveau router `adapters/inbound/catalog.py`, prefix
   `/catalog`) : le catalogue client **ne surcharge pas** `/salons` (sémantique « mes salons ») et
   évite toute collision de routage avec `/salons/{salon_id}` (typé `uuid.UUID`). Le détail salon
   (#19) s'y ajoutera naturellement (`GET /catalog/salons/{salon_id}`) sans réutiliser de route de
   gestion.

2. **Filtre `status = ACTIVE` au niveau SQL, en premier `where`** (§8.3), porté par un **port de
   lecture dédié** `SalonCatalogRepository` (`search_active` / `count_active` / `get_active`) —
   distinct de `SalonRepository`. L'isoler garantit qu'un futur appel de gestion ne puisse pas
   contourner le filtre par mégarde, et que le catalogue n'hérite d'aucune capacité d'écriture. Aucun
   post-filtrage applicatif (faillible). S'appuie sur les index déjà présents `ix_salons_status` et
   `ix_salons_city_commune` — **aucune migration**.

3. **Projection publique minimale** (`PublicSalonView` / `PublicSalonResponse`) : n'expose que des
   champs de vitrine — `id`, `name`, `description`, `address`, `city`, `commune`, `latitude`,
   `longitude`, `logo_url` (**signé** ou `null`), `is_bookable`. Sont **exclus** `owner_id` (oracle de
   compte), `status` (seul `ACTIVE` remonte → redondant ; ne pas divulguer l'état de modération),
   `opening_hours` bruts (détail #19), `phone` (détail #19) et les timestamps (interne).

4. **Décision d'authentification : route publique.** `GET /catalog/salons` est ajouté à
   `PUBLIC_ROUTE_PATHS` — addition **consciente et revue** (comme `/auth/login`). Justification :
   (i) débloque le mobile **sans** exiger l'auth client (l'app est un squelette, #8/#10 non livrés) ;
   (ii) colle à §7.1/§5.1 (browse avant connexion) ; (iii) n'expose que des **données de vitrine
   publiques** de salons `ACTIVE`, sans `owner_id` ni PII de gestion. Le test `unprotected_routes(app)`
   reste l'arbitre : la route est publique-listée, jamais orpheline. L'alternative
   `require_permission(SALON_READ_ANY)` reste possible sans toucher à la projection ni au filtre —
   elle supposerait seulement l'auth cliente livrée côté mobile.

5. **Recherche & pagination** : recherche par nom (`ILIKE` sous-chaîne, métacaractères `LIKE`
   **échappés** pour un filtrage prévisible — non une défense anti-injection, SQLAlchemy paramètre
   déjà), filtre de zone (`city`/`commune`, égalité insensible à la casse), **pagination bornée**
   (`limit` ∈ `[1, 50]`, `offset ≥ 0` ; hors bornes → `422`).

6. **Application mobile (Flutter)** : première brique réseau du paquet `app-mobile/` (hexagonal,
   ADR-0008) — domaine `SalonSummary`, port `SalonCatalogGateway`, cas d'usage `SearchSalons`, adapter
   `HttpSalonCatalogGateway` (`http`) et écran de recherche (§7.1). L'URL d'API est injectée au build
   via `--dart-define=API_BASE_URL` (jamais de secret dans l'APK).

## Conséquences

- **Positives** : le critère d'acceptation §8.3 est **figé au niveau SQL** et testable indépendamment
  du mobile ; le port dédié empêche toute fuite de salon non-`ACTIVE` ; la ressource `/catalog` prépare
  #19 (détail) et #21+ (réservation) ; la couche réseau mobile est réutilisable.
- **Négatives / suivis** : l'ajout à `PUBLIC_ROUTE_PATHS` élargit la surface publique (mitigé :
  lecture seule, vitrine uniquement) ; **recherche insensible aux accents** différée (un `ILIKE` simple
  ne gère pas « Elegance » vs « Élégance » — `unaccent` PostgreSQL serait une décision d'infra) ;
  filtres « type de prestation » (#17) / « disponibilité » (#16/#21) et **vue carte** différés (hors
  périmètre §7.1 MVP) ; le **détail salon** (#19) n'est **pas** livré ici (`get_active` est préparé mais
  non exposé).
