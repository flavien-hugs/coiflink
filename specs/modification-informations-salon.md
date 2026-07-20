# Modification des informations du salon (US-2.5, #20)

> Épic 2 · Priorité **Should** · Effort **S** · Dépend de **#15**
> PRD §6 (US-2.5) · Critère d'acceptation : *« Le gérant met à jour son salon ; les
> changements sont reflétés côté client. »*

## Problem Statement

Un gérant doit pouvoir **modifier à tout moment** les informations générales de son salon
(nom, description, téléphone, adresse, ville, commune, coordonnées GPS) depuis le dashboard,
et ces changements doivent **apparaître côté client** (catalogue et fiche publique) sans
étape manuelle supplémentaire.

**État réel du dépôt (constat important).** La plus grande partie de cette user story est
**déjà livrée** — implémentée avec la tranche #15 / dashboard gérant (commit
`f0d83ce feat(dashboard-gerant): édition salon, agenda horaires, activation prestations`).
Sont déjà en place, de bout en bout :

- **Backend** : route `PUT /salons/{salon_id}` (`backend/coiflink_api/adapters/inbound/salons.py`)
  → cas d'usage `UpdateSalon` (`backend/coiflink_api/application/salons.py`) → journalisation
  `SALON_UPDATED` dans `audit_logs` (§11.4), avec diff **neutre** (noms de champs seulement,
  jamais de valeurs) ;
- **Dashboard (Next.js)** : Route Handler BFF `PUT /api/salons/[id]`
  (`web-dashboard/app/api/salons/[id]/route.ts`), cas d'usage `updateSalon`, méthode
  `SalonGateway.update` (`http-salon-gateway.ts`), et UI d'édition
  (`SalonDetails` → bouton « Modifier » → drawer portant `SalonForm` en mode édition) ;
- **Tests existants** : `backend/tests/test_salon_api.py::TestUpdateSalon` (200/401/404/audit),
  `web-dashboard/test/salon-update-bff.test.ts`, `web-dashboard/test/update-salon.test.ts`.

Le **gap réel de #20** n'est donc *pas* d'écrire le chemin de modification, mais de **prouver
et durcir le second membre du critère d'acceptation** — la réflexion côté client — qui
aujourd'hui « fonctionne par construction » mais **n'est couverte par aucun test bout-en-bout**.
Le catalogue client (`GET /catalog/salons`, #18) et la fiche publique
(`GET /catalog/salons/{salon_id}`, #19) projettent les **mêmes lignes** de la table `salons`,
sans couche de cache (Redis n'est pas câblé) : une modification est donc reflétée à la
prochaine lecture. Aucun test ne verrouille ce comportement contre une régression future
(p. ex. l'ajout d'un cache ou d'une projection dénormalisée).

## Goals

- **Documenter** que le chemin de modification des informations du salon est déjà livré et
  ne doit **pas** être ré-implémenté (éviter doublons et régressions).
- **Verrouiller par un test e2e** la garantie de réflexion côté client : après un
  `PUT /salons/{id}` réussi par le gérant, les nouvelles valeurs apparaissent dans
  `GET /catalog/salons` (liste/recherche) **et** `GET /catalog/salons/{id}` (fiche).
- **Couvrir les invariants de visibilité §8.3** dans ce même test : les modifications d'un
  salon `ACTIVE` remontent au catalogue ; un salon non `ACTIVE` reste absent du catalogue
  quelles que soient ses modifications (pas d'oracle d'existence).
- **Vérifier** que le champ `updated_at` est bien rafraîchi par la modification (fraîcheur
  observable), sans exposer de donnée de gestion au client.
- Compléter la **couverture unitaire/intégration** manquante (403 hors périmètre, 422
  validation, atomicité audit) si des cas ne sont pas déjà couverts par `TestUpdateSalon`.
- Mettre à jour la **documentation** (README §6, éventuel ADR) pour acter la livraison de #20.

## Non-Goals

- **Ré-écrire ou modifier** le chemin d'écriture existant (`PUT /salons/{id}`, BFF, use case,
  UI) sauf correction d'un défaut avéré découvert par les tests.
- **Édition des médias** (logo/photos) : couverte par ses propres routes #15
  (`/salons/{id}/logo`, `/salons/{id}/photos`, upload signé) — hors périmètre « informations ».
- **Édition des horaires d'ouverture** : couverte par #16 (`PUT /salons/{id}/opening-hours`).
- **Édition des prestations** : couverte par #17 (`/salons/{id}/services`).
- **Modification du `status`, de l'`owner_id` ou des `opening_hours`** via cette route : ces
  champs sont **volontairement non modifiables** par `PUT /salons/{id}` (invariant conservé).
- **Changement d'application mobile** : les écrans catalogue/fiche (#18/#19) re-lisent le
  backend à l'affichage ; aucune modification de code mobile n'est requise pour la réflexion.
- **Invalidation de cache / temps réel (push)** : aucun cache n'existe aujourd'hui ; la
  réflexion « à la prochaine lecture » suffit au critère d'acceptation.
- **Verrouillage optimiste / gestion de conflit multi-éditeurs** (voir Risques).

## Relevant Repository Context

Stack figée par les ADR (résumé README §4) : backend **FastAPI** (ADR-0003), architecture
**hexagonale** (ADR-0008), ORM **SQLAlchemy + Alembic** (ADR-0009), **PostgreSQL 16**,
dashboard **Next.js** (ADR-0002) avec **BFF + cookie httpOnly** (invariant #14), **RBAC
deny-by-default** (ADR-0015) et **isolation par salon** (§11.2), **audit §11.4** matérialisé
dans `audit_logs` (ADR-0019).

Modules pertinents (déjà existants) :

- **Backend gestion salon** :
  - `adapters/inbound/salons.py` — router `/salons` : `POST`, `GET`, `GET /{id}`,
    **`PUT /{id}`** (modification, `require_permission(SALON_UPDATE)` + `require_salon_scope`),
    médias, `PUT /{id}/opening-hours`.
  - `application/salons.py` — `UpdateSalon` (validation domaine → `find_by_id` (404) → diff
    neutre `_changed_fields` → `repository.update` → `audit_log.record(SALON_UPDATED)`),
    `GetSalon`, `ListOwnSalons`, `CreateSalon`, cas d'usage médias.
  - `domain/salon.py` — `validate_salon_name`, `validate_coordinates`, `SalonUpdate` ;
    `domain/phone.py::normalize_phone` ; `domain/audit.py` (`AuditAction.SALON_UPDATED`,
    `ENTITY_TYPE_SALON`).
  - `adapters/outbound/persistence/salon_repository.py` — `SqlSalonRepository.update(...)`.
- **Backend catalogue client (lecture)** :
  - `adapters/inbound/catalog.py` — `GET /catalog/salons` (#18) et
    `GET /catalog/salons/{salon_id}` (#19), **publics** (`PUBLIC_ROUTE_PATHS`), projections
    minimales sans donnée de gestion.
  - `application/catalog.py` — `SearchSalons`, `GetPublicSalon` ; filtre **`ACTIVE`-only**
    délégué au dépôt (`salon_catalog_repository.py`, SQL).
- **Dashboard** :
  - `app/(gerant)/gerant/parametres/page.tsx` — Server Component ; charge les salons du
    gérant (jeton du cookie), rend `SalonDetails` (édition) + `OpeningHoursForm`.
  - `src/adapters/ui/salon-details.tsx` — fiche lecture + drawer d'édition.
  - `src/adapters/ui/salon-form.tsx` — formulaire création **ou** édition (prop `salon`).
  - `app/api/salons/[id]/route.ts` — BFF `PUT`.
  - `src/application/use-cases/update-salon.ts`, `src/adapters/api/http-salon-gateway.ts`,
    `src/application/ports/salon-gateway.ts` (`UpdateSalonInput = CreateSalonInput`).
- **Tests e2e de référence (patron à suivre)** : `backend/tests/test_service_e2e.py`
  (parcours CRUD prestations → réflexion en liste/consultation + audit + isolation), et
  `backend/tests/test_catalog_api.py` / `test_catalog_detail_api.py`.

Conventions : ADR numérotés séquentiellement (dernier = **0021**, prochain libre = **0022**) ;
tests par paquet réunis par le **test gate** (`scripts/test-gate.sh`, `pytest`/`npm test`/
`flutter test`) ; les e2e PostgreSQL sont **conditionnels** (skip si `DATABASE_URL` absent).

Décisions encore ouvertes : voir §Risks (ADR dédié ou non ; stratégie de conflit multi-éditeur).

## Proposed Implementation

L'implémentation est **majoritairement de la vérification**. Étapes recommandées :

1. **Audit de conformité du chemin existant (lecture, sans modification de code).**
   Confirmer que `PUT /salons/{id}` :
   - est bien gardé par `require_permission(SALON_UPDATE)` **et** `require_salon_scope`
     (isolation §11.2 — 403 générique hors périmètre) ;
   - **ignore/rejette** toute tentative de modifier `owner_id`, `status`, `opening_hours`
     (ces champs ne figurent pas dans `UpdateSalonRequest`) ;
   - journalise `SALON_UPDATED` avec **uniquement des noms de champs** (`metadata.changed`),
     et le fait de façon **atomique** avec la mutation (même session) ;
   - rafraîchit `updated_at`. Si `SqlSalonRepository.update` ne bump pas `updated_at`,
     c'est le **seul** correctif de code backend attendu (sinon aucun).

2. **Nouveau test e2e backend : réflexion côté client** — `backend/tests/test_salon_update_e2e.py`
   (classe `TestSalonUpdateReflectionE2E`, `@pytest.mark.skipif` si pas de `DATABASE_URL`,
   même harnais que `test_service_e2e.py` : `TestClient` → router → use case → dépôt SQL réel
   → audit réel → JWT réel ; plage téléphone de test réservée pour le nettoyage). Scénario
   principal :
   1. inscription gérant → connexion (JWT réel) ;
   2. `POST /salons` (salon `ACTIVE`) ; `PUT /salons/{id}/opening-hours` avec des horaires
      valides pour le rendre **réservable** et **visible** au catalogue ;
   3. lecture initiale : `GET /catalog/salons?q=<ancien nom>` renvoie le salon avec les
      **anciennes** valeurs ; `GET /catalog/salons/{id}` idem ;
   4. `PUT /salons/{id}` avec de nouvelles valeurs (nom, ville, commune, description,
      téléphone, coordonnées) → **200** ;
   5. **assertions de réflexion** : `GET /catalog/salons?q=<nouveau nom>` renvoie le salon
      avec les **nouvelles** valeurs (nom, ville, commune, localisation) et **ne** le renvoie
      **plus** sous l'ancien nom si le filtre ne matche plus ; `GET /catalog/salons/{id}`
      renvoie les nouvelles valeurs (dont `phone`, exposé en détail #19) ;
   6. **assertion d'étanchéité** : la réponse catalogue **n'expose pas** `owner_id`,
      `status`, ni clé d'objet brute (régression de projection) ;
   7. **assertion d'audit** : une entrée `SALON_UPDATED` existe pour le bon acteur/salon, et
      `metadata` **ne contient aucune valeur** de champ ni PII (§11.3/§11.4).

3. **Cas de visibilité §8.3 (même fichier e2e ou voisin).** Pour un salon rendu **non
   `ACTIVE`** (via le mécanisme existant de changement de statut, si accessible en test ; sinon
   directement en base dans la fixture) : après un `PUT /salons/{id}` réussi (le gérant garde
   la main sur son salon), le salon **reste absent** de `GET /catalog/salons` et
   `GET /catalog/salons/{id}` renvoie **404** (pas d'oracle). But : garantir que la réflexion
   **n'ouvre pas** une fuite de visibilité.

4. **Complément de couverture ciblée** (uniquement si non déjà couvert par `TestUpdateSalon`
   et les tests web) : 403 hors périmètre (isolation), 422 validation (nom vide, une seule
   coordonnée fournie), **aucune** entrée d'audit créée quand la validation échoue (atomicité).

5. **Documentation** (voir §Documentation Updates) : README §6, et **ADR-0022** court actant
   « Modification des informations du salon & garantie de réflexion » — décision à confirmer
   (peut être fusionnée dans une note si le comité juge l'ADR superflu, puisque #20 n'introduit
   pas de nouvelle décision d'architecture au-delà de #15/#18/#19/#20-audit).

Contraintes transverses à préserver : messages d'erreur **génériques** (pas d'oracle) ;
**jamais** de secret/PII/jeton journalisé (front comme back) ; le backend reste **autoritatif**
sur la validation ; sémantique **replace** du `PUT` (le corps remplace intégralement les
informations générales, `name` requis).

## Affected Files / Packages / Modules

**À lire (contexte, ne pas modifier sauf défaut avéré) :**

- `backend/coiflink_api/adapters/inbound/salons.py` (route `PUT /{id}`)
- `backend/coiflink_api/application/salons.py` (`UpdateSalon`, `_changed_fields`)
- `backend/coiflink_api/adapters/outbound/persistence/salon_repository.py` (`update`, `updated_at`)
- `backend/coiflink_api/application/catalog.py`, `adapters/inbound/catalog.py`
- `backend/coiflink_api/adapters/outbound/persistence/salon_catalog_repository.py`
- `backend/coiflink_api/domain/audit.py`, `domain/salon.py`, `domain/phone.py`
- `backend/tests/test_salon_api.py` (`TestUpdateSalon`), `test_service_e2e.py`,
  `test_catalog_api.py`, `test_catalog_detail_api.py`
- `web-dashboard/src/adapters/ui/salon-details.tsx`, `salon-form.tsx`,
  `app/api/salons/[id]/route.ts`, `src/application/use-cases/update-salon.ts`,
  `src/adapters/api/http-salon-gateway.ts`

**À créer :**

- `backend/tests/test_salon_update_e2e.py` — e2e réflexion + visibilité §8.3 + audit.
- `docs/adr/0022-modification-informations-salon.md` — ADR (à confirmer, cf. Risks).

**À modifier :**

- `README.md` §6 — acter la livraison de #20.
- `docs/adr/README.md` — index (si ADR-0022 créé).
- Éventuellement `backend/tests/test_salon_api.py` — compléments 403/422/atomicité s'ils manquent.
- Éventuellement `salon_repository.py` — **seulement** si `updated_at` n'est pas rafraîchi.

## API / Interface Changes

**Aucune nouvelle interface attendue.** Le contrat existant est conservé et documenté :

- `PUT /salons/{salon_id}` (dashboard, authentifié) — sémantique *replace* des informations
  générales ; corps `UpdateSalonRequest` (`name` requis + champs optionnels), **sans**
  `owner_id`/`status`/`opening_hours` ; réponses `200/401/403/404/422` ; journalise
  `SALON_UPDATED`.
- `GET /catalog/salons`, `GET /catalog/salons/{salon_id}` (publics, lecture) — inchangés ;
  ils reflètent les modifications à la lecture suivante.

Si l'audit de conformité révélait une divergence entre le code et la doc OpenAPI existante,
la corriger sans élargir la surface.

## Data Model / Protocol Changes

**Aucune.** La table `salons` (colonnes générales + `updated_at`) et `audit_logs` (#19/ADR-0019)
existent déjà ; l'action `SALON_UPDATED` est déjà définie. Aucune migration Alembic nouvelle
n'est attendue. (Si un correctif `updated_at` s'avérait nécessaire au niveau ORM, il n'implique
pas de changement de schéma.)

## Security & Privacy Considerations

- **Autorisation (ADR-0015, §11.2)** : `PUT /salons/{id}` exige `SALON_UPDATE` **et** la portée
  salon ; un gérant ne peut modifier que **son** salon (403 générique sinon). Le test e2e doit
  inclure un cas d'isolation inter-gérants (le jeton de A refusé sur le salon de B).
- **Anti-élévation de privilège** : `owner_id`, `status`, `opening_hours` **non** modifiables
  par cette route (aucun champ correspondant dans le corps) — invariant à **verrouiller par
  test** (un corps contenant `owner_id`/`status` ne doit rien changer).
- **Visibilité §8.3** : la réflexion ne doit **jamais** rendre visible au catalogue un salon
  non `ACTIVE` ; la fiche d'un salon non `ACTIVE` renvoie **404** sans oracle d'existence.
- **Non-fuite dans l'audit (§11.3/§11.4)** : `metadata.changed` ne contient que des **noms de
  champs**, jamais les valeurs (nom, téléphone, adresse, coordonnées = PII/données
  d'établissement). Le test doit l'asserter.
- **BFF / secrets (invariant #14, ADR-0011)** : le jeton d'accès reste dans le cookie httpOnly,
  lu **côté serveur**, jamais exposé au navigateur ni journalisé ; ni le jeton ni la PII salon
  ne doivent apparaître dans les logs (front comme back).
- **Projection publique** : les réponses `/catalog` ne doivent pas exposer `owner_id`/`status`/
  clé d'objet brute — à réasserter dans l'e2e (défense en profondeur contre une régression de
  sérialisation introduite par une future refonte de la réflexion).

Aucune nouvelle contrainte de résidence/hébergement n'est introduite (Railway `europe-west4`,
ADR-0011, inchangé).

## Testing Plan

- **E2E backend (nouveau, PostgreSQL requis, skippable)** —
  `backend/tests/test_salon_update_e2e.py` :
  - réflexion liste + fiche après `PUT /salons/{id}` (nouvelles valeurs visibles) ;
  - `updated_at` rafraîchi ;
  - salon non `ACTIVE` : modifications **non** reflétées, fiche → 404 ;
  - isolation inter-gérants (403) ;
  - audit `SALON_UPDATED` présent, sans valeur/PII dans `metadata` ;
  - projection publique sans `owner_id`/`status`.
- **Unit/intégration backend** — confirmer/compléter `TestUpdateSalon`
  (`backend/tests/test_salon_api.py`) : 200 (valeurs à jour), 401, 403 hors périmètre, 404
  salon inconnu en portée, 422 (nom vide / coordonnée unique), atomicité (aucun audit si
  validation échoue), invariant « owner_id/status ignorés ».
- **Web (existants, à exécuter/vérifier)** — `salon-update-bff.test.ts`, `update-salon.test.ts` ;
  ajouter si utile un test de rendu `SalonDetails`/`SalonForm` (mode édition pré-rempli,
  bouton « Enregistrer les modifications », mapping des statuts d'erreur 403/404/422/401/503).
- **Test gate / CI** — l'ensemble passe via `scripts/test-gate.sh` (`pytest` + `npm test`) ;
  les e2e PostgreSQL restent conditionnels (skip sans `DATABASE_URL`, parité CI).
- **Documentation** — vérifier que l'exemple d'exécution e2e (commande `alembic upgrade head`
  + `pytest tests/test_salon_update_e2e.py`) figure en en-tête du fichier de test, comme pour
  `test_service_e2e.py`.

## Documentation Updates

- **README.md §6** — ajouter une phrase actant #20 : le gérant modifie les informations
  générales de son salon (`PUT /salons/{id}`, journalisé §11.4) depuis **Paramètres**, et ces
  changements sont **reflétés côté client** (catalogue #18 / fiche #19) à la lecture suivante.
- **docs/adr/0022-modification-informations-salon.md** *(à confirmer)* — ADR court : décision
  de **réutiliser** le chemin d'écriture livré avec #15, sémantique *replace*, champs non
  éditables, et **garantie de réflexion sans cache** (lecture directe des mêmes lignes) ;
  conséquences et alternative (cache/dénormalisation) écartée pour le MVP.
- **docs/adr/README.md** — index mis à jour si ADR-0022 créé.
- Pas de nouvelle doc OpenAPI à rédiger : la route est déjà documentée (docstrings/`responses`).

## Risks and Open Questions

- **La story est déjà implémentée** : principal risque = **doublon/régression** si un agent
  ré-implémente le `PUT`. Le plan doit rester en mode vérification. *À confirmer : périmètre de
  #20 = tests + doc, pas de nouveau code produit (hors correctif ponctuel).*
- **ADR-0022 : nécessaire ou non ?** La convention M2 crée un ADR par issue, mais #20
  n'introduit pas de décision d'architecture inédite. **Décision à confirmer** : créer un
  ADR court, ou se contenter du README + en-tête de test.
- **Rafraîchissement de `updated_at`** : à vérifier ; s'il n'est pas bumpé par
  `SqlSalonRepository.update`, faut-il le corriger dans le cadre de #20 ou ouvrir une issue
  dédiée ? *À confirmer.*
- **Conflit multi-éditeurs / verrouillage optimiste** : aujourd'hui *last-write-wins* ; un seul
  `owner` édite, mais un gérant sur deux onglets peut écraser ses propres champs. Hors périmètre
  MVP proposé — **à confirmer** qu'on ne veut pas d'`If-Match`/`version`.
- **Changement de statut en test §8.3** : existe-t-il déjà une voie (API/fixture) pour rendre un
  salon non `ACTIVE` afin de tester la non-réflexion ? Sinon, le test devra manipuler le statut
  directement en base dans sa fixture. *À confirmer.*
- **Cache futur** : si Redis/CDN est câblé plus tard devant `/catalog`, la garantie « reflété à
  la prochaine lecture » nécessitera une invalidation ; le test e2e sert précisément de
  garde-fou de régression le moment venu.
- **Mobile** : la réflexion suppose un re-fetch à l'affichage de l'écran (#18/#19) ; aucun
  changement mobile requis, mais aucune preuve automatisée côté Flutter (le squelette mobile
  reste minimal — cf. mémoire projet).

## Implementation Checklist

1. Lire et confirmer le chemin existant `PUT /salons/{id}` (gardes RBAC + portée, champs non
   éditables, audit neutre atomique) et les projections `/catalog` (#18/#19).
2. Vérifier que `SqlSalonRepository.update` rafraîchit `updated_at` ; noter tout écart.
3. Créer `backend/tests/test_salon_update_e2e.py` (harnais `test_service_e2e.py`, skip sans
   `DATABASE_URL`, plage téléphone de test réservée, nettoyage avant/après).
4. Implémenter le scénario de **réflexion** : création → horaires valides → lecture initiale →
   `PUT /salons/{id}` → assertions liste + fiche (nouvelles valeurs, dont `phone` en détail).
5. Ajouter les assertions d'**étanchéité** (pas d'`owner_id`/`status`/clé brute côté catalogue)
   et d'**audit** (`SALON_UPDATED`, `metadata` sans valeur/PII).
6. Ajouter le cas **§8.3** : salon non `ACTIVE` → modifications non reflétées, fiche 404.
7. Ajouter le cas **isolation** inter-gérants (403 générique) s'il n'est pas déjà couvert.
8. Compléter `TestUpdateSalon` (422 validation + atomicité audit + invariant owner_id/status
   ignorés) si manquant.
9. Exécuter/valider les tests web existants (`salon-update-bff.test.ts`, `update-salon.test.ts`)
   et ajouter un test de rendu du mode édition si utile.
10. Faire passer le **test gate** (`scripts/test-gate.sh` → `pytest` + `npm test`).
11. Mettre à jour **README.md §6** (livraison #20 + réflexion client).
12. Décider (avec le mainteneur) de créer **ADR-0022** ; si oui, l'écrire et mettre à jour
    `docs/adr/README.md`.
13. Relire : aucun secret/PII/jeton journalisé ; messages d'erreur génériques ; backend
    autoritatif ; aucune nouvelle surface d'API/schéma introduite involontairement.
