# Prestations préférées d'un client — statistiques (gérant) (US-4.3)

> Spécification de planification pour l'issue GitHub **#31 — US-4.3 : Prestations préférées d'un
> client (stats)** (`feature` · Should · Effort S · PRD §6 Épic 4 US-4.3 / §7.2 « Clients »).
> **Dépend de #29** (historique des visites d'un client — la brique de lecture des RDV `COMPLETED`
> d'une fiche, livrée). Poursuit le jalon **M4 — Clients, encaissement & journal de caisse**.
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 4, US-4.3) pose le besoin : **« en tant que gérant, je veux connaître les
prestations préférées d'un client »**, spécification fonctionnelle **« statistiques par client »**.
Le critère d'acceptation de l'issue #31 est :

- **Affichage des prestations les plus fréquentes du client.**

C'est le **troisième module « gestion clients »**, après la création de fiche (#28) et l'historique
des visites (#29). Il transforme le dossier de suivi (aujourd'hui une liste chronologique de visites)
en un **profil de consommation** : le gérant voit *ce que le client prend le plus souvent*, pour
personnaliser l'accueil, anticiper la prestation attendue et orienter le conseil.

État actuel du dépôt (après #29 / #30) — établi par **lecture du code**, pas par hypothèse :

- **La brique de lecture des visites terminées existe et est directement réutilisable (#29).** Le
  port `CustomerRepository.list_visits(salon_id, customer_id, statuses)`
  (`application/ports/customer_repository.py`) renvoie déjà, pour une fiche, **tous** ses RDV
  `COMPLETED` — chacun (`domain/visit.py::CustomerVisit`) portant ses prestations **nommées**
  (`VisitService` = `service_id` + `name` + `price_at_booking` figé) et un `total_amount`. L'adapter
  SQL (`adapters/outbound/persistence/customer_repository.py::list_visits`) encapsule **entièrement
  en SQL** le lien `customer_profiles.user_id == appointments.client_id`, refiltre `salon_id`, et
  n'expose **jamais** `user_id`/`client_id` (anti-oracle ADR-0026). **Aucun nouvel accès base n'est
  requis** pour dériver les statistiques : elles se calculent à partir des mêmes visites.
- **Le cas d'usage et l'endpoint historique existent (#29).** `application/customers.py::
  GetCustomerVisitHistory` résout la fiche dans le salon (`GetCustomer` → `404` **après** portée,
  sans oracle) puis appelle `list_visits` et construit un résumé **dérivé en lecture**
  (`domain/visit.py::build_history`). La route `GET /salons/{salon_id}/customers/{customer_id}/
  appointments` (`adapters/inbound/customers.py`) est protégée par `require_salon_scope` +
  `require_permission(CUSTOMER_MANAGE)`, lecture pure **sans audit**, jamais publique.
- **Le domaine `visit.py` est pur et prêt à accueillir une agrégation.** `HISTORY_STATUSES ==
  (COMPLETED,)`, `visit_total` et `build_history` y vivent, testés sans I/O. Une agrégation
  « fréquence par prestation » a naturellement sa place au même endroit (ou dans un module frère),
  suivant le même patron « dérivé en lecture, jamais dénormalisé ».
- **Le libellé de prestation reste résoluble même après désactivation.** `services.name` est joint
  dans `list_visits` ; une prestation soft-deletée (`is_active = false`) reste en table (FK
  `RESTRICT`), donc une prestation « préférée » qui n'est plus au catalogue **reste nommable**.
- **La page de détail de fiche existe (#29).** `web-dashboard/app/(gerant)/gerant/clients/
  [customerId]/page.tsx` (Server Component) affiche l'en-tête de fiche + l'historique via
  `CustomerGateway.history(...)`. Le domaine TS `src/domain/customer/visit.ts` porte déjà
  `formatAmountXof` / `formatVisitDate`. La page est le **point d'accrochage naturel** d'un panneau
  « Prestations préférées ».
- **Aucune statistique par client n'existe encore.** Une recherche `stats`/`favourite`/`préférée`/
  `frequen` sur `backend/coiflink_api` et `web-dashboard/src` ne remonte rien de client-scopé.

Le gap que #31 comble : une **lecture agrégée, salon-scopée et fiche-scopée** classant les
prestations d'un client par **fréquence** (les plus fréquentes d'abord), exposée par un **nouvel
endpoint** et rendue par un **panneau** sur la page de détail de fiche `/gerant/clients/{id}` déjà
livrée. **Sans** migration ni changement de schéma : tout est dérivé en lecture des visites
`COMPLETED` déjà exposées par #29.

## Goals

- **Classer les prestations d'un client par fréquence** (critère d'acceptation). Pour la fiche
  visée, agréger ses visites `COMPLETED` en une **liste de prestations** — chacune avec son
  `service_id`, son `name`, un **compte d'occurrences** (nombre de fois où la prestation a été
  réalisée) et un **montant cumulé** (somme des `price_at_booking` de cette prestation) —, triée
  **de la plus fréquente à la moins fréquente**, avec un ordre **déterministe** en cas d'égalité.
- **Réutiliser strictement la brique #29 — aucun nouvel accès base.** Les statistiques se dérivent
  des `CustomerVisit` déjà renvoyés par `list_visits(salon_id, customer_id, HISTORY_STATUSES)` :
  l'agrégation est une **fonction pure** du domaine, testable sans I/O. Le lien `user_id` reste
  encapsulé côté dépôt (anti-oracle ADR-0026) — #31 n'en voit **jamais** rien.
- **Isolation par salon (§11.2), en profondeur.** L'endpoint est salon-scopé (`require_salon_scope`
  → `403` **générique**) **et** fiche-scopé : la fiche est résolue via `(salon_id, customer_id)`
  (réutilise `GetCustomer` → `404` **après** portée, sans oracle) **et** la lecture des visites
  refiltre `salon_id`/`client_id` en SQL (hérité de #29). Un gérant ne voit **que** les statistiques
  des fiches de son salon, calculées **uniquement** sur les RDV **de son salon** (jamais ceux du même
  compte dans un autre salon).
- **Fréquence = visites `COMPLETED` uniquement.** Comme l'historique #29, la statistique ne compte
  que les prestations **réalisées** (`HISTORY_STATUSES`). Un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/
  `NO_SHOW` ne pèse **pas** dans les préférences (une préférence est ce que le client a **réellement**
  consommé). Cohérent avec l'invariant `REVENUE_STATUSES` du domaine.
- **Montants exacts et figés.** Le montant cumulé d'une prestation est la **somme des
  `price_at_booking`** (prix figé à la réservation, jamais le tarif courant). Devise **XOF** (unique
  au MVP, §9.6). `Decimal` de bout en bout, jamais de flottant.
- **Réutilisation stricte de `CUSTOMER_MANAGE`.** L'endpoint câble la permission §4.1 déjà présente
  (détenue par le seul `MANAGER`) — **sans** modifier `ROLE_PERMISSIONS`, exactement comme #28/#29.
- **Lecture pure, sans effet de bord.** Aucune écriture, **aucune** entrée d'audit (patron des
  lectures #26/#28/#29), aucun chemin ajouté à `PUBLIC_ROUTE_PATHS`.
- **Panneau « Prestations préférées » sur la page de détail de fiche.** Étend
  `/gerant/clients/{customer_id}` (#29) avec un classement lisible (nom, nombre de fois, montant
  cumulé). État **vide explicite** : « Aucune prestation réalisée pour ce client » (cas walk-in / pas
  encore de visite terminée) — **pas** une erreur. Jeton lu **côté serveur** (cookie `httpOnly`,
  invariant #14).
- **Aucune PII journalisée.** Ni logs applicatifs, ni messages d'erreur ne portent de nom, téléphone,
  note ou détail de consommation. L'endpoint n'est **jamais** public.
- **Couverture de tests.** Backend : domaine (agrégation, tri déterministe, montants figés, vide),
  cas d'usage (portée, filtre `COMPLETED`, walk-in → vide, cloisonnement inter-salons), API
  (`200`/`401`/`403`/`404`, absence de `user_id`/`client_id`), e2e PostgreSQL (statistiques réelles,
  isolation, absence de PII). Web : domaine de mapping/formatage, gateway HTTP, BFF, rendu du panneau.

## Non-Goals

- **Statistiques agrégées du salon / KPI gérant (tableau de bord, #39+).** #31 est une statistique
  **par client** (une fiche). Les KPI transverses (CA du salon, prestations les plus vendues **du
  salon**, fréquentation) relèvent du Tableau de bord (M5) et en sont **hors périmètre**.
- **Panier moyen, récence, fréquence de visite globale, prédiction / recommandation.** Le critère
  d'acceptation cible les **prestations les plus fréquentes**. D'autres indicateurs (panier moyen,
  intervalle entre visites, « next best action ») sont des évolutions ultérieures — l'IA de
  recommandation est explicitement **hors MVP** (PRD §16/§21). Ils **peuvent** être ajoutés au même
  read model plus tard sans refonte, mais ne sont pas livrés ici.
- **Rattachement d'une fiche à un compte utilisateur (`user_id`).** Comme #29, #31 **lit** le lien
  `user_id` s'il existe mais **ne le crée pas**. Une fiche walk-in (`user_id = NULL`) a des
  statistiques **légitimement vides**. Le rattachement (auto ou explicite) reste le vrai déblocage
  fonctionnel — évolution ultérieure à trancher avec le produit (repris de #29 *Open Questions* §1).
- **Écriture / maintenance de colonnes dénormalisées.** #31 **dérive en lecture** ; aucun compteur
  persisté, aucun *trigger*, aucun couplage dans `SetAppointmentStatus` (#25).
- **Encaissement / paiements (#33+).** Les montants cumulés sont des **prix figés de prestations
  réservées** (`price_at_booking`), **pas** des paiements encaissés (`payments`, non livrés).
- **Statistiques côté client / mobile.** #31 est un parcours **gérant** (web). Le paquet
  `app-mobile/` n'est **pas** touché (l'historique client mobile #30 est une lecture distincte, déjà
  livrée).
- **Filtrage temporel / pagination des statistiques.** Le nombre de prestations **distinctes** d'un
  salon est petit en pratique (borné par le catalogue) : #31 renvoie le classement complet. Une
  fenêtre glissante (« 12 derniers mois ») ou un top-N paramétrable sont discutés en *Open Questions*
  §3/§5 mais **hors périmètre** par défaut.
- **Migration / changement de schéma.** Aucun. #31 est une lecture dérivée des tables existantes,
  via la brique #29.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Fiche client | Fiche walk-in `user_id = NULL`, portée salon, anti-oracle | [0026](../docs/adr/0026-fiche-client-portee-salon.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0026** (fiche client) : le prochain numéro libre est
**ADR-0027**. #29 (historique) a plié ses décisions dans les README plutôt que dans un ADR. Un ADR
pour #31 est **optionnel** (voir *Open Questions* §7) — #31 ne change pas le schéma et réutilise
telles quelles les décisions de #29/#26.

### Backend — patrons à réutiliser tels quels

- **Brique historique (#29)** — le gabarit exact à étendre : `domain/visit.py`
  (`CustomerVisit`/`VisitService`/`HISTORY_STATUSES`/`build_history`, purs) →
  `CustomerRepository.list_visits(...)` (port + `SqlCustomerRepository`) →
  `application/customers.py::GetCustomerVisitHistory` → route dans
  `adapters/inbound/customers.py`. #31 **ajoute une agrégation pure au domaine** et **un cas d'usage
  + une route** qui consomment la **même** `list_visits` — **aucun nouveau port ni accès base**.
- **Lecture salon-scopée sans audit (#26/#28/#29)** : aucune écriture, aucun audit ; la portée salon
  est assurée par `require_salon_scope` **et** ré-affirmée en SQL par le dépôt (défense en profondeur
  §11.2). La `404`-après-portée passe par `GetCustomer` (aucun oracle).
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` sur chaque route ; `403` **générique et constant** ; l'invariant
  deny-by-default est vérifié mécaniquement par `unprotected_routes(app)`
  (`test_security_guards.py`) — **une route ajoutée sans garde fait échouer les tests**.
- **Anti-oracle (ADR-0026)** : `list_visits` encapsule le lien `user_id` en SQL ; #31 n'y touche
  pas et ne renvoie **jamais** `user_id`/`client_id`. On **n'interroge jamais** `users` par
  téléphone.
- **Tests** : fakes en mémoire dans `tests/conftest.py` (`FakeCustomerRepository.list_visits` existe
  déjà) + fixtures ; API via `TestClient` et `app.dependency_overrides` ; **e2e** adossés à un vrai
  PostgreSQL, sautés si `DATABASE_URL` absent, plage de numéros réservée, nettoyage avant/après
  (patron `tests/test_customer_history_e2e.py`).

### Modèle de données pertinent (schéma #3, aucun changement)

```
appointments (client_id → users.id, salon_id, status, appointment_date, start_time, end_time)
  └─ appointment_services (appointment_id, service_id, salon_id, price_at_booking)   ← montant figé
        └─ services (id, salon_id, name, …)                                          ← libellé
customer_profiles (id, salon_id, user_id NULLABLE, full_name, phone, …)
```

Pont fiche → RDV : `customer_profiles.user_id == appointments.client_id` **ET** même `salon_id`
(calculé **en SQL** par `list_visits`, jamais exposé). Index déjà présents (`ix_appointments_*`,
`ix_appointment_services_service_id`) : **aucune migration nécessaire** ; #31 n'ajoute **aucune**
colonne, contrainte ni index.

### Web gérant — patrons à réutiliser (#28 → #29)

- `app/(gerant)/gerant/clients/[customerId]/page.tsx` = **Server Component + composition root** : lit
  le cookie (`createCookieSessionStore().read()`), appelle les gateways HTTP côté serveur, rend l'UI.
  #31 **étend** cette page (ajoute une lecture parallèle + un panneau).
- `src/application/ports/customer-gateway.ts` + `src/adapters/api/http-customer-gateway.ts` :
  résultats en **union discriminée** (`{ok:true,…} | {ok:false, reason:…}`), jamais d'exception ni de
  jeton dans le résultat. `history(...)` y est le modèle direct de `stats(...)`.
- `app/api/salons/[id]/customers/[customerId]/appointments/route.ts` : **Route Handler BFF** qui lit
  le jeton du cookie et proxifie ; messages d'erreur **neutres** en français. Modèle du BFF `stats`.
- `src/domain/customer/visit.ts` : domaine TS pur (`formatAmountXof`, `formatVisitDate`) — les
  helpers de formatage montant sont réutilisables tels quels.

### Contraintes transverses documentées

- **PRD §11.2** : « un gérant ne peut voir que les données de son salon ».
- **PRD §11.3** : collecte minimale, journalisation des accès sensibles, données personnelles
  protégées.
- **PRD §8.1 / §8.2** : le CA ne compte que les RDV réalisés ; devise unique **XOF** ; montants
  `NUMERIC(12,2)` (jamais de flottant).
- **PRD §12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI applicative
  `ci.yml` (ruff, pytest, round-trip Alembic contre PostgreSQL 16, build, lint/test/build web).

## Proposed Implementation

Approche recommandée : **dériver les statistiques côté backend, en réutilisant la lecture `list_visits`
de #29** (aucun nouvel accès base), exposées par un endpoint dédié, et rendues par un panneau sur la
page de détail de fiche existante. Le backend reste l'**autorité** des chiffres ; le front formate.
(Deux alternatives — agrégation SQL dédiée, ou calcul côté web à partir de l'historique #29 — sont
pesées en *Open Questions* §2.)

### (A) Backend — domaine (agrégation pure)

**`domain/visit.py`** — **étendre** (le read model de statistiques est cohésif avec l'historique) :

```python
@dataclass(frozen=True)
class ServiceFrequency:
    """Une prestation dans le classement des préférences d'un client (US-4.3, #31).

    `count` = nombre d'occurrences réalisées (COMPLETED) ; `total_amount` = somme
    des `price_at_booking` de cette prestation (prix figés, XOF). `name` est le
    libellé courant (résoluble même si la prestation est soft-deletée).
    """
    service_id: uuid.UUID
    name: str
    count: int
    total_amount: decimal.Decimal


@dataclass(frozen=True)
class CustomerServiceStats:
    """Statistiques « prestations préférées » d'une fiche : classement + totaux dérivés."""
    services: tuple[ServiceFrequency, ...] = ()
    total_visits: int = 0            # nombre de visites COMPLETED considérées
    total_services: int = 0          # nombre d'occurrences de prestations agrégées
    currency: str = DEFAULT_CURRENCY


def favourite_services(
    visits: tuple[CustomerVisit, ...],
    *,
    currency: str = DEFAULT_CURRENCY,
) -> CustomerServiceStats:
    """Classe les prestations d'un client par fréquence (fonction **pure**).

    Parcourt les visites `COMPLETED` (chacune ≥ 1 prestation, invariant §8.1),
    agrège par `service_id` (`count += 1`, `total_amount += price_at_booking`),
    puis trie **fréquence décroissante**, en départageant par `total_amount`
    décroissant puis `name` croissant puis `service_id` (ordre **déterministe**,
    stable pour les tests). Une entrée vide (aucune visite) donne un classement
    vide — comportement normal, pas une erreur. `Decimal` de bout en bout.
    """
```

- **Le nom retenu par `service_id`** : si un même `service_id` apparaît avec des libellés différents
  (impossible aujourd'hui — un service a un nom unique), garder le dernier vu ; en pratique
  `services.name` est stable. Ne **pas** dédupliquer par nom (deux services distincts peuvent partager
  un libellé) — la clé d'agrégation est **toujours** `service_id`.
- **Occurrence vs visite distincte** : `count` compte les **occurrences réalisées** (une ligne
  `appointment_services` par occurrence). Voir *Open Questions* §4 (compter les visites distinctes est
  une variante possible — même agrégation, dénominateur différent).
- Ajouter `ServiceFrequency`, `CustomerServiceStats`, `favourite_services` à `__all__`.

### (B) Backend — cas d'usage

**`application/customers.py`** — ajouter un cas d'usage de lecture (ne dépend que du port
`CustomerRepository`, **aucun** nouveau port) :

```python
class GetCustomerServiceStats:
    """Prestations préférées d'une fiche (lecture — pas d'audit, US-4.3, #31)."""

    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    def execute(self, salon_id, customer_id) -> CustomerServiceStats:
        # 1. Résout la fiche DANS le salon (404 après portée si hors salon/inconnue).
        GetCustomer(self._repository).execute(salon_id, customer_id)
        # 2. Lit les visites COMPLETED liées (user_id encapsulé côté dépôt, #29).
        visits = self._repository.list_visits(salon_id, customer_id, HISTORY_STATUSES)
        # 3. Agrège le classement (pur, jamais persisté).
        return favourite_services(visits)
```

- **Réutilise `GetCustomer`** pour la sémantique `404`-après-portée (isolation §28, sans oracle) et
  **`list_visits`** de #29 (aucun nouvel accès base ; le `salon_id`/`client_id` refiltré en SQL est
  hérité). **Lecture pure → aucun audit** (patron `GetCustomerVisitHistory`).

### (C) Backend — adapter entrant (HTTP)

**`adapters/inbound/customers.py`** — ajouter **une** route au router existant (`prefix="/salons"`) :

```python
@router.get(
    "/{salon_id}/customers/{customer_id}/stats",
    response_model=CustomerServiceStatsResponse,
    summary="Prestations préférées d'un client (les plus fréquentes)",
    responses={401: {...}, 403: {...}, 404: {...}},
)
def get_customer_stats(
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    repository: ... = Depends(get_customer_repository),
    _scope: SalonScope = Depends(require_salon_scope),
    _principal: Principal = Depends(require_permission(Permission.CUSTOMER_MANAGE)),
) -> CustomerServiceStatsResponse: ...
```

- Schémas Pydantic documentés (OpenAPI) : `ServiceFrequencyResponse` (`service_id`, `name`, `count`,
  `total_amount`), `CustomerServiceStatsResponse` (`customer_id`, `services`, `total_visits`,
  `total_services`, `currency`). `total_amount`/`price_at_booking` sérialisés en **chaîne décimale**
  (jamais de flottant), comme #29.
- Traduction d'erreur : `CustomerNotFound` → **404** (uniquement après validation de portée). Aucune
  autre erreur de domaine attendue (lecture).
- **Garde** : `require_salon_scope` **et** `require_permission(Permission.CUSTOMER_MANAGE)`.
  **Aucun** chemin ajouté à `PUBLIC_ROUTE_PATHS`. `main.py` inchangé (router `customers` déjà inclus).
- **Nom du sous-chemin** : `…/stats` (langage produit « statistiques par client »). Alternative
  `…/favourite-services` — voir *Open Questions* §1.

### (D) Web gérant — panneau « Prestations préférées »

1. **Domaine TypeScript** — nouveau `src/domain/customer/stats.ts` (ou extension de `visit.ts`) :
   types `ServiceFrequency`, `CustomerServiceStats` ; réutilise `formatAmountXof` de `visit.ts`.
   Le backend reste l'autorité des chiffres ; le front **formate** seulement.
2. **Port & gateway** — étendre `src/application/ports/customer-gateway.ts` (nouveau type
   `CustomerStatsResult` en union discriminée, `reason: "forbidden" | "unauthenticated" |
   "not-found" | "unavailable"`) + `src/adapters/api/http-customer-gateway.ts` avec
   `stats(salonId, customerId)`. **Jamais** le jeton dans le résultat (miroir de `history`).
3. **BFF** — `app/api/salons/[id]/customers/[customerId]/stats/route.ts` (`GET`) : lit le jeton du
   cookie `httpOnly`, proxifie vers `…/customers/{id}/stats`, messages neutres (miroir du BFF
   `appointments` de #29).
4. **Page** — étendre `app/(gerant)/gerant/clients/[customerId]/page.tsx` : ajouter `gateway.stats(...)`
   à l'appel `Promise.all` existant (à côté de `get` et `history`), et rendre un panneau
   **« Prestations préférées »** sous l'historique. État **vide explicite** : « Aucune prestation
   réalisée pour ce client » (walk-in / pas encore de visite terminée) — **pas** une erreur.
   Un `stats` en échec **non-`not-found`** peut soit dégrader le panneau (message neutre) sans casser
   la page, soit retomber sur l'`ErrorPanel` existant — voir *Open Questions* §6.
5. **UI** — `src/adapters/ui/customer-service-stats.tsx` : liste/tableau classé (rang, nom, « ×N
   fois », montant cumulé) + états vide/erreur, dans le style de `customer-visit-history.tsx`.
6. **Navigation** — aucun changement (la page `/gerant/clients/{id}` existe déjà depuis #29).

### (E) Documentation & (option) ADR

- **`backend/README.md`** : sous-section « Clients — prestations préférées (US-4.3, #31) » — route,
  permission, réponses, note sur la dérivation depuis les visites `COMPLETED` (walk-in → vide) et les
  montants figés (`price_at_booking`, XOF).
- **`web-dashboard/README.md`** : mention du panneau « Prestations préférées » sur
  `/gerant/clients/{id}` + BFF `…/stats` associé.
- **`README.md`** (racine) §6 : phrase de statut « statistiques par client (#31) livré » ; tableau
  des jalons M4 à jour.
- **(Option) `docs/adr/0027-…`** si un ADR est jugé utile (*Open Questions* §7).

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `tests/test_domain_visit.py` (**étendre** ou nouveau `test_domain_customer_stats.py`) | tests de `favourite_services` (agrégation, tri déterministe, montants, vide) |
| `tests/test_customer_stats_api.py` | tests API (`200`/`401`/`403`/`404`, absence de `user_id`/`client_id`) |
| `tests/test_customer_stats_e2e.py` | tests e2e PostgreSQL (statistiques réelles, isolation, filtre `COMPLETED`, walk-in vide, absence de PII) |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/visit.py` | read models `ServiceFrequency`/`CustomerServiceStats`, fonction pure `favourite_services`, `__all__` |
| `coiflink_api/application/customers.py` | cas d'usage `GetCustomerServiceStats` (réutilise `GetCustomer` + `list_visits`) ; `__all__` |
| `coiflink_api/adapters/inbound/customers.py` | route `GET …/{customer_id}/stats` + schémas `ServiceFrequencyResponse`/`CustomerServiceStatsResponse` |
| `tests/test_customer_usecases.py` | volet `GetCustomerServiceStats` (portée/`404`, filtre `COMPLETED`, walk-in vide, cloisonnement) |
| `backend/README.md` | sous-section « prestations préférées » |

> **Aucun** changement à `application/ports/customer_repository.py` ni à
> `adapters/outbound/persistence/customer_repository.py` : `list_visits` de #29 suffit (le
> `FakeCustomerRepository.list_visits` de `tests/conftest.py` sert déjà les tests applicatifs). Voir
> *Open Questions* §2 si l'on préfère une agrégation SQL dédiée (alternative écartée par défaut).

### Web (`web-dashboard/`)

À créer : `app/api/salons/[id]/customers/[customerId]/stats/route.ts` (BFF),
`src/domain/customer/stats.ts` (ou extension de `visit.ts`),
`src/adapters/ui/customer-service-stats.tsx`,
`test/customer-service-stats.test.ts`, `test/customer-stats-gateway.test.ts`,
`test/customer-stats-bff.test.ts`.
À modifier : `src/application/ports/customer-gateway.ts` (type `CustomerStatsResult` + `stats(...)`),
`src/adapters/api/http-customer-gateway.ts` (implémentation `stats`),
`app/(gerant)/gerant/clients/[customerId]/page.tsx` (lecture parallèle + panneau),
`web-dashboard/README.md`.

### Documentation (racine)

`README.md` ; (option) `docs/adr/0027-…`, `docs/adr/README.md`.

### À lire (sans modifier) pour rester fidèle aux patrons

`domain/visit.py`, `application/customers.py` (`GetCustomerVisitHistory`),
`adapters/inbound/customers.py` (route `…/appointments`, schémas, DI),
`adapters/outbound/persistence/customer_repository.py` (`list_visits`),
`application/ports/customer_repository.py`, `adapters/inbound/security.py`, `domain/permissions.py`,
`tests/conftest.py` (`FakeCustomerRepository`), `tests/test_customer_history_*.py`,
`web-dashboard/app/(gerant)/gerant/clients/[customerId]/page.tsx`,
`web-dashboard/src/adapters/ui/customer-visit-history.tsx`,
`web-dashboard/src/adapters/api/http-customer-gateway.ts`,
`web-dashboard/app/api/salons/[id]/customers/[customerId]/appointments/route.ts`.

## API / Interface Changes

**Un** nouvel endpoint REST, **protégé** (`CUSTOMER_MANAGE` + portée salon) ; aucune route existante
n'est modifiée ; aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/customers/{customer_id}/stats` | `CUSTOMER_MANAGE` + portée | `200` classement · `401` · `403` · `404` fiche hors salon |

```jsonc
// 200 — réponse (prestations les plus fréquentes d'abord)
{
  "customer_id": "…uuid…",
  "services": [
    { "service_id": "…", "name": "Coupe homme", "count": 5, "total_amount": "25000.00" },
    { "service_id": "…", "name": "Barbe",        "count": 3, "total_amount": "6000.00"  }
  ],
  "total_visits": 6,        // nombre de visites COMPLETED considérées (dérivé)
  "total_services": 8,      // nombre total d'occurrences de prestations (dérivé)
  "currency": "XOF"
}
```

- **Fiche walk-in (`user_id = NULL`) ou sans visite terminée** → `200` avec `services: []`,
  `total_visits: 0`, `total_services: 0` (comportement **normal**, pas une erreur).
- **`user_id` / `client_id` ne sont jamais exposés** (anti-oracle ADR-0026) : la réponse ne porte
  qu'`appointment`-agnostique — `service_id`, `name`, `count`, `total_amount`.
- **Interfaces web (BFF, internes à Next.js)** : `GET /api/salons/[id]/customers/[customerId]/stats`.
  **Aucune** modification de CLI, de variable d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**None.** #31 est une **lecture dérivée** des tables existantes via la brique `list_visits` de #29
(`appointments`, `appointment_services`, `services`, `customer_profiles`) : aucune migration Alembic,
aucune colonne, contrainte ou index ajouté. Aucune colonne dénormalisée n'est écrite. Les montants
sont lus **tels quels** depuis `appointment_services.price_at_booking` (`NUMERIC(12,2)`), agrégés en
`Decimal` et sérialisés en chaîne décimale — jamais de flottant.

## Security & Privacy Considerations

**Ce module lit des données personnelles (PII) — le profil de consommation d'un client — c'est sa
principale sensibilité** (PRD §11.3). Les invariants sont **identiques à #29** (dont il réutilise la
lecture) :

- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur la route **et** double
  filtre hérité de `list_visits` : la fiche est résolue via `(salon_id, customer_id)` (`GetCustomer`,
  `404` **après** portée si hors salon, sans oracle) **et** les visites sont filtrées `salon_id =
  :salon_id AND client_id = :user_id`. Un gérant ne voit **jamais** les prestations consommées par le
  même client dans un **autre** salon.
- **Anti-oracle d'existence de compte (ADR-0026), tenu de bout en bout.** Le lien
  `customer_profiles.user_id == appointments.client_id` est calculé **uniquement en SQL** (par
  `list_visits`) ; `user_id`/`client_id` ne sont **jamais** renvoyés ni journalisés. On **n'interroge
  jamais** `users` par téléphone. Une fiche walk-in renvoie des statistiques **vides** —
  indiscernable d'une fiche liée sans visite terminée : aucun signal sur l'existence d'un compte.
- **Deny-by-default (ADR-0015).** Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ; l'invariant est
  vérifié mécaniquement (`unprotected_routes(app)`). Les statistiques d'un client ne sont **jamais**
  lisibles sans jeton, ni exposées au client, au coiffeur ou au catalogue public.
- **Permission `CUSTOMER_MANAGE` seule (§4.1).** Détenue par le seul `MANAGER`. Le `HAIRDRESSER` et
  l'`ADMIN` ne lisent **pas** les statistiques client. La matrice `ROLE_PERMISSIONS` **n'est pas
  modifiée**.
- **Aucune PII ni secret dans les logs.** Aucun `print`/`logger` ne reçoit le nom, le téléphone, les
  notes ni le détail de consommation ; les messages `4xx` restent **neutres**. Les noms de prestation
  et montants, exposés dans la **réponse** au gérant légitime, ne sont **jamais** journalisés.
- **Lecture pure — aucun effet de bord.** Aucune écriture, aucune entrée d'audit par défaut (patron
  des lectures #26/#28/#29). Si la lecture de statistiques était jugée « accès sensible » à tracer
  (§11.3), l'option d'un audit **neutre** (acteur + `customer_id`, jamais le détail) est réservée au
  durcissement (#52) — voir *Open Questions* §8.
- **Montants figés & devise unique.** `price_at_booking` (prix figés), jamais recalculés au tarif
  courant : les statistiques sont **stables** et fidèles. Devise **XOF** (§9.6). `NUMERIC(12,2)`
  agrégé en `Decimal`, sérialisé en décimal — jamais de flottant.
- **Budget de latence (§12.1).** La lecture est bornée par l'historique d'**un** client (petit en
  pratique) et l'agrégation est en mémoire, O(nombre d'occurrences). Couverte par les index #29
  existants. Un garde-fou de volume (limite haute sur `list_visits`) est déjà discuté en #29 *Open
  Questions* §6 et resterait valable ici.
- **Jeton jamais exposé côté web (#14).** La page et le Route Handler lisent le cookie `httpOnly`
  **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.

Le dépôt ne documente **aucune** contrainte supplémentaire (résidence, chiffrement applicatif requis)
au-delà de celles ci-dessus pour cette lecture.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **Domaine** (`tests/test_domain_visit.py` étendu ou nouveau `tests/test_domain_customer_stats.py`),
  `favourite_services` :
  - agrégation par `service_id` (`count`, `total_amount` = somme des `price_at_booking`) ;
  - **tri déterministe** : fréquence décroissante ; départage `total_amount` décr., puis `name` cr.,
    puis `service_id` (ordre stable, testé sur des égalités) ;
  - deux prestations distinctes partageant un **libellé** ne sont **pas** fusionnées (clé =
    `service_id`) ;
  - montants en `Decimal`, **jamais** de flottant ; pas d'arrondi ;
  - liste vide (aucune visite) → classement vide, `total_visits = 0`, `total_services = 0`.
- **`tests/test_customer_usecases.py`** (fakes de `conftest.py`), cas `GetCustomerServiceStats` :
  - fiche introuvable / d'un autre salon → `CustomerNotFound` (avant toute agrégation) ;
  - fiche walk-in (fake sans lien) → statistiques **vides** ;
  - seules les visites **`COMPLETED`** comptent (le `statuses` passé à `list_visits` vaut
    `HISTORY_STATUSES`) ;
  - **cloisonnement** : un RDV `COMPLETED` du même compte dans un **autre** salon ne pèse pas (assuré
    par `list_visits`, réaffirmé au niveau du fake).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_customer_stats_api.py`** : `200` + corps attendu (classement, `count`, `total_amount`,
  `total_visits`, `total_services`, `currency`) ; `404` fiche d'un autre salon (message **neutre**) ;
  `403` hors portée / rôle non `MANAGER` (message **constant**) ; `401` sans jeton ;
  **`user_id`/`client_id` absents** de la réponse ; fiche walk-in → `200` `services: []`.
- **`tests/test_security_guards.py`** : l'invariant `unprotected_routes(app) == []` couvre
  automatiquement la nouvelle route ; vérifier qu'**aucun** chemin `…/stats` n'entre dans
  `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_customer_stats_e2e.py`** (patron `test_customer_history_e2e.py`, plage de téléphones
  réservée, nettoyage avant/après) :
  1. **Statistiques peuplées** : compte client + salon + plusieurs prestations, plusieurs RDV réservés
     (#21) confirmés puis `COMPLETED` (#25), **fiche liée** insérée (`customer_profiles.user_id =
     <client>`, écriture directe — le rattachement n'ayant pas d'endpoint) → `GET …/stats` renvoie le
     classement attendu (fréquences et montants cumulés corrects, ordre déterministe).
  2. **Isolation inter-salons** : le jeton du gérant B est refusé (`403`) sur les stats d'une fiche du
     salon de A ; un RDV `COMPLETED` du même compte dans le salon de B **ne pèse pas** côté A.
  3. **Filtre de statut** : un RDV `CANCELLED`/`NO_SHOW`/actif du même compte est **absent** de
     l'agrégation.
  4. **Fiche walk-in** (`user_id = NULL`, créée via #28) → `200` `services: []`.
  5. **Absence de PII** : la réponse ne contient ni `user_id` ni `client_id` ; aucun log ne porte de
     détail de consommation.
  6. Deny-by-default : sans jeton → `401`.

### Web (`vitest`)

- `test/customer-service-stats.test.ts` : mapping réponse → domaine, formatage montant
  (`formatAmountXof`) et libellé « ×N fois », état **vide** (« Aucune prestation réalisée »),
  ordre d'affichage préservé (le tri est fait par le backend).
- `test/customer-stats-gateway.test.ts` : mapping des statuts backend → `reason`
  (`403 → "forbidden"`, `401 → "unauthenticated"`, `404 → "not-found"`), en-tête `Authorization`
  posé, **jeton jamais renvoyé** dans le résultat.
- `test/customer-stats-bff.test.ts` : `401` sans cookie ; `404`/`403` propagés avec message neutre ;
  **aucune PII ni jeton** dans les réponses d'erreur.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ;
  `npm run lint && npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`backend/README.md`** — sous-section « Clients — prestations préférées (US-4.3, #31) » : route,
  permission, réponses, **note sur la dérivation** depuis les visites `COMPLETED` (walk-in → vide),
  **montants figés** (`price_at_booking`, XOF) ; exemple `curl`.
- **`web-dashboard/README.md`** — mention du panneau « Prestations préférées » sur
  `/gerant/clients/{id}` + BFF `…/stats` associé.
- **`README.md`** (racine) — §6 : phrase de statut « statistiques par client (#31) livré » dans le
  style des paragraphes existants ; cohérence du tableau des jalons M4.
- **(Option) `docs/adr/0027-…`** + entrée `docs/adr/README.md` — si un ADR est retenu (*Open
  Questions* §7) : définition de « préférée » (fréquence des `COMPLETED`), agrégation dérivée,
  montants figés.
- **OpenAPI** — `summary`/`responses`/docstrings de la route documentent la nouvelle API (visible sur
  `/docs`), y compris le `404`.

## Risks and Open Questions

1. **Nom du sous-chemin.** `…/customers/{id}/stats` (langage produit « statistiques par client ») vs
   `…/customers/{id}/favourite-services` (colle au critère d'acceptation) vs extension du corps de
   `…/appointments`. *Recommandation : `…/stats`* — extensible à d'autres indicateurs par client sans
   nouvelle route, et concern distinct de l'historique. **À confirmer.**
2. **Où calculer l'agrégation ?** Trois options : (a) **dériver en Python** à partir de `list_visits`
   de #29 (recommandé : aucun nouvel accès base, agrégation pure et testable, réutilise la brique
   existante) ; (b) **agrégation SQL dédiée** (`GROUP BY service_id`, `COUNT`, `SUM`) — plus efficace
   à très gros volume mais duplique le lien `user_id`/portée dans une nouvelle requête et ajoute une
   méthode au port ; (c) **calcul côté web** à partir de l'historique #29 déjà chargé — évite tout
   backend mais rend le front autorité des chiffres et disperse la règle métier. *Recommandation :
   (a)* ; (b) réservée si un profilage montre un problème de latence. **À confirmer.**
3. **Fenêtre temporelle.** « Préférées » sur **toute** l'histoire, ou sur une **période récente**
   (ex. 12 derniers mois) ? *Recommandation : toute l'histoire au MVP* (simple, volume faible ; les
   `price_at_booking` sont déjà figés dans le temps). Une fenêtre pourra être ajoutée comme paramètre
   sans refonte. **À confirmer.**
4. **Unité de fréquence : occurrences vs visites distinctes.** `count` compte-t-il les **occurrences**
   d'une prestation (une ligne `appointment_services`) ou le **nombre de visites distinctes** la
   contenant ? Elles diffèrent si une prestation est réalisée deux fois dans le même RDV.
   *Recommandation : occurrences* (aligné sur « fréquence de consommation » et sur `total_amount`).
   **À confirmer** — la variante « visites distinctes » est la même agrégation avec un compteur
   différent.
5. **Top-N vs classement complet.** « Préférées » suggère une **liste courte**. Renvoyer le classement
   complet (recommandé — le catalogue d'un salon est petit) et laisser l'**UI** afficher un top-N (ex.
   5) avec un « voir tout » ? Ou borner l'API (`limit`) ? *Recommandation : classement complet côté
   API, cap d'affichage côté UI.* **À confirmer.**
6. **Dégradation du panneau si `stats` échoue.** Sur la page de détail, un échec `stats` non-`not-found`
   doit-il casser toute la page (`ErrorPanel` global, comme aujourd'hui pour `history`) ou dégrader
   **seulement** le panneau « préférées » (message neutre local) en gardant fiche + historique
   lisibles ? *Recommandation : dégradation locale* (meilleure robustesse, cohérent avec des lectures
   indépendantes). **À confirmer.**
7. **Un ADR est-il nécessaire ?** #29 a plié ses décisions dans les README (pas d'ADR). #31 ne change
   pas le schéma et réutilise #29/#26. *Recommandation : ADR **optionnel*** — README suffit. **À
   confirmer.**
8. **Journaliser la lecture de statistiques (§11.3 « accès sensibles ») ?** Les lectures ne sont pas
   auditées ailleurs (#26/#28/#29). *Recommandation : ne pas auditer* (cohérence + coût), option d'une
   entrée neutre réservée au durcissement (#52). **À confirmer.**
9. **[Hérité de #29 — bloquant fonctionnel] Fiche non rattachée → statistiques vides.** Tant qu'aucun
   rattachement fiche ↔ compte (`user_id`) n'est livré (écarté par #28 pour raison d'anti-oracle),
   toute fiche walk-in a des statistiques **vides**. L'endpoint et l'UI sont corrects et prêts à se
   peupler dès que le rattachement existera ; le rattachement reste le vrai déblocage fonctionnel, à
   planifier avec le produit. **À remonter** (déjà signalé par #29).
10. **Nom d'une prestation désactivée.** Une prestation soft-deletée (`is_active = false`) reste en
    table (FK `RESTRICT`) : son nom **courant** est affiché dans le classement. Cohérent (le nom n'est
    pas figé, seul le prix l'est). À assumer explicitement dans le README.

## Implementation Checklist

1. **Lire** `domain/visit.py`, `application/customers.py` (`GetCustomerVisitHistory`),
   `adapters/inbound/customers.py` (route `…/appointments` + schémas + DI),
   `adapters/outbound/persistence/customer_repository.py` (`list_visits`), `tests/conftest.py`
   (`FakeCustomerRepository`), et côté web `clients/[customerId]/page.tsx`,
   `http-customer-gateway.ts`, le BFF `…/appointments/route.ts` — s'imprégner des patrons #29.
2. **Trancher** les questions ouvertes 1 à 6 (nom du sous-chemin, lieu d'agrégation, fenêtre,
   occurrences vs visites, top-N, dégradation) et consigner la décision (README ou ADR-0027 selon §7).
3. **Domaine** : étendre `domain/visit.py` avec `ServiceFrequency`, `CustomerServiceStats`,
   `favourite_services` (agrégation par `service_id`, tri déterministe, `Decimal`) ; ajouter à
   `__all__`.
4. **Tests de domaine** : écrire/étendre `tests/test_domain_visit.py` (ou
   `test_domain_customer_stats.py`) — **avant** le cas d'usage.
5. **Cas d'usage** : ajouter `GetCustomerServiceStats` à `application/customers.py` (réutilise
   `GetCustomer` pour le `404`, `list_visits(HISTORY_STATUSES)`, `favourite_services` ; aucune
   écriture, aucun audit) ; ajouter à `__all__`.
6. **Tests applicatifs** : volet `GetCustomerServiceStats` dans `tests/test_customer_usecases.py`
   (portée/`404`, filtre `COMPLETED`, walk-in vide, cloisonnement) via le `FakeCustomerRepository`
   existant.
7. **Adapter entrant** : ajouter la route `GET /{salon_id}/customers/{customer_id}/stats` à
   `adapters/inbound/customers.py` (schémas `ServiceFrequencyResponse`/`CustomerServiceStatsResponse`,
   `require_salon_scope` + `require_permission(CUSTOMER_MANAGE)`, mapping `CustomerNotFound → 404`) ;
   **ne pas** toucher `PUBLIC_ROUTE_PATHS` ni `main.py`.
8. **Tests API & e2e** : écrire `tests/test_customer_stats_api.py` puis `tests/test_customer_stats_e2e.py`
   (statistiques réelles via fiche liée insérée en base, isolation inter-salons, filtre de statut,
   walk-in vide, absence de PII, deny-by-default) ; exécuter `pytest` (+ `DATABASE_URL` pour l'e2e) et
   `ruff check`.
9. **Web — domaine & accès** : `src/domain/customer/stats.ts` (types + réutilise `formatAmountXof`)
   (+ test) ; étendre `customer-gateway.ts` (`CustomerStatsResult` + `stats`) et
   `http-customer-gateway.ts` (+ test).
10. **Web — BFF** : `app/api/salons/[id]/customers/[customerId]/stats/route.ts` (`GET`, messages
    neutres) + `test/customer-stats-bff.test.ts`.
11. **Web — UI & page** : `src/adapters/ui/customer-service-stats.tsx` (classement + états
    vide/erreur) ; brancher `gateway.stats(...)` dans le `Promise.all` de
    `clients/[customerId]/page.tsx` et rendre le panneau « Prestations préférées ».
12. **Documentation** : sous-sections dédiées dans `backend/README.md` et `web-dashboard/README.md` ;
    phrase de statut dans le `README.md` racine ; (option) ADR-0027 + entrée `docs/adr/README.md`.
13. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test),
    `ruff check`, `npm run lint && npm run build` ; relire la PR pour s'assurer qu'**aucune PII et
    aucun secret** (nom, téléphone, notes, `user_id`, détail de consommation) n'apparaissent dans les
    logs ou messages d'erreur, et qu'**aucune signature IA** n'a été introduite.
