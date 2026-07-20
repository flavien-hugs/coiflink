# ADR-0021 : Consultation d'un salon côté client — fiche publique de détail, agrégation `ACTIVE`-only & point d'entrée réservation

- **Statut** : Accepté
- **Date** : 2026-07-17
- **Décideurs** : équipe CoifLink
- **Issue** : #19 (US-2.4 — Consultation d'un salon, côté client)
- **Référence PRD** : §7.1 (« Fiche salon » depuis la recherche), §5.1 (parcours client, étape 4 :
  consulter un salon avant de réserver), §8.3 (visibilité : un salon inactif n'est jamais visible côté
  client), §11.2/§11.3 (isolation, PII), §12 (budget)
- **S'appuie sur** : [ADR-0020](./0020-catalogue-salons-cote-client.md) (ressource `/catalog`, port de
  lecture dédié, filtre `ACTIVE`, projection de vitrine, route publique),
  [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, liste blanche testée),
  [ADR-0005](./0005-stockage-objet-s3-compatible.md) (URLs signées),
  [ADR-0018](./0018-configuration-horaires-salon.md) (contrat JSONB des horaires),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (prestations, soft-delete `is_active`),
  [ADR-0017](./0017-creation-salon-medias-et-reservabilite.md) (`is_bookable` dérivé),
  [ADR-0001](./0001-app-mobile-flutter.md) (application mobile Flutter)

## Contexte et problème

Le catalogue client (#18) permet de **rechercher/lister** les salons `ACTIVE` (`GET /catalog/salons`),
avec une **projection de vitrine minimale** (nom, localisation, logo signé, `is_bookable`). Mais le
client **ne peut pas ouvrir la fiche d'un salon** : aucune vue de détail n'expose les **prestations**,
les **horaires**, les **prix**, la **localisation complète** ni la **disponibilité** — les
informations nécessaires pour décider de réserver. Le port `SalonCatalogRepository.get_active` était
préparé par #18 mais **non exposé**, et les prestations/horaires n'étaient accessibles qu'aux routes
de **gestion** (portée gérant), jamais côté client.

US-2.4 demande que le détail d'un salon montre **prestations + horaires + disponibilité** et serve de
**point d'entrée** à la réservation.

## Décision

1. **Route de détail dans le router `/catalog` existant** : `GET /catalog/salons/{salon_id}`
   (`salon_id: uuid.UUID`), ajoutée à `adapters/inbound/catalog.py` — **aucun** nouveau router,
   **aucune** route de gestion réutilisée. S'appuie **exclusivement** sur
   `SalonCatalogRepository.get_active` (filtre `status = ACTIVE` en SQL, #18) : un salon
   `INACTIVE`/`SUSPENDED` ou inexistant → `None` → `SalonNotFound` → **404** (« absent du catalogue »,
   **pas d'oracle d'existence**, §8.3). Un `salon_id` mal formé → **422** (validation FastAPI).

2. **Route publique** (cohérence ADR-0020 §4). Le chemin **littéral** `"/catalog/salons/{salon_id}"`
   est ajouté à `PUBLIC_ROUTE_PATHS` — addition **consciente et revue** : `is_public_path` compare le
   `route.path` **à l'identique** (placeholder compris ; un préfixe ne suffit pas). Justification
   identique à #18 : lecture seule, données de **vitrine publiques** d'un salon `ACTIVE`, sans
   `owner_id` ni PII de gestion ; débloque le parcours §7.1/§5.1 (consulter avant connexion) alors que
   l'auth cliente n'existe pas encore côté mobile. `unprotected_routes(app)` reste l'arbitre. L'option
   `require_permission(SALON_READ_ANY)` resterait possible sans toucher à la projection ni au filtre,
   mais supposerait l'auth cliente livrée (elle ne l'est pas) → bloquerait le mobile.

3. **Lecture des prestations : méthode dédiée sur le port catalogue.**
   `SalonCatalogRepository.list_active_services(salon_id)` (filtre `is_active = true` **en SQL**,
   triée par nom) est **préférée** à la réutilisation de `ServiceRepository.list_for_salon(...,
   include_inactive=False)` : le catalogue **n'hérite d'aucune capacité de gestion** (le
   `ServiceRepository` porte `create`/`update`/`set_active`) et le filtre `is_active` vit côté lecture
   publique, non négociable. Une prestation soft-deletée (#17) ne peut **jamais** fuir côté client.
   La lecture des photos (`list_photos`) est ajoutée au même port pour la galerie.

4. **Projection de détail** (`PublicSalonDetailView` / `PublicSalonDetailResponse`) : étend la vitrine
   (#18) de `phone` (**reporté de #18**, donnée d'établissement publique), `photos` (URLs **signées**),
   `opening_hours` (**JSONB normalisé publié tel quel**, `null` si non configuré ; le formatage est une
   responsabilité du client), `services` (prestations **actives** avec `price` `Decimal` + durée) et
   `is_bookable`. Restent **exclus** : `owner_id`, `status`, `is_active`/`salon_id`/timestamps de
   prestation, timestamps de salon et **toute clé d'objet brute** (uniquement des URLs signées,
   ADR-0005 ; `media_storage is None` → `null`/`[]`, jamais d'erreur).

5. **« Point d'entrée réservation » = affordance honnête, pas un flux.** La réservation (#21+) n'existe
   pas. La fiche mobile expose un bouton « Réserver » **dérivé de `is_bookable`** : désactivé
   (« Bientôt disponible ») si `false` ; présent mais **non fonctionnel** si `true` (message
   « Réservation bientôt disponible »). Aucun flux de réservation n'est simulé.

6. **« Disponibilité » MVP = `is_bookable` + horaires.** Le critère « prestations + horaires +
   disponibilité » est satisfait par l'indicateur `is_bookable` (§8.3 : `ACTIVE` **et** horaires
   configurés) et l'affichage des horaires. Le **calcul de créneaux libres** dépend des RDV (#21+) et
   est **explicitement différé**.

7. **Application mobile (Flutter)** : extension hexagonale de la couche #18 — domaine `SalonDetail`,
   `SalonService`, `SalonOpeningHours`/`SalonPhoto`, méthode `getSalon(id)` du port
   `SalonCatalogGateway` (avec `SalonNotFoundException` distincte de l'erreur réseau), cas d'usage
   `GetSalonDetail`, adapter HTTP (`GET /catalog/salons/{id}`), écran de fiche + widgets
   (`OpeningHoursView`, `ServiceListTile`) et **navigation** liste → fiche (nouveauté : l'app n'avait
   que la recherche). Testable sans réseau ; aucune journalisation d'URL signée ni de PII.

**Aucune migration Alembic** : toutes les données existent (`salons.phone`/`opening_hours`/
`logo_object_key`, table `services` #17, table `salon_photos` #15). Le contrat de données est inchangé.

## Conséquences

- **Positives** : le critère §8.3 (fiche `ACTIVE`-only, 404 sans oracle) et le filtre
  prestations-actives sont **figés au niveau SQL** et testables indépendamment du mobile ; la fiche
  réutilise `get_active` (aucun filtre faillible réintroduit) ; le port dédié empêche toute fuite de
  salon non-`ACTIVE` ou de prestation désactivée ; la ressource `/catalog` prépare #21+ (réservation) ;
  la navigation mobile posée est réutilisable.
- **Négatives / suivis** : l'ajout à `PUBLIC_ROUTE_PATHS` élargit la surface publique (mitigé :
  lecture seule, vitrine uniquement, aucune PII de gestion) ; le **calcul de créneaux libres** (« un
  créneau demain à 15 h ? ») reste **différé** (dépend de #21+) — la « disponibilité » se limite à
  `is_bookable` + horaires ; **vue carte / itinéraire**, **avis/notation**, **favoris/partage** et
  **auth cliente mobile** (#8/#10 côté app) restent hors périmètre ; l'appel d'agrégation fait une
  requête prestations + une requête photos par fiche (N+1 acceptable pour un détail unitaire).
