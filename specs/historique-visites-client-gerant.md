# Historique des visites d'un client (gérant) (US-4.2)

> Spécification de planification pour l'issue GitHub **#29 — US-4.2 : Historique des visites d'un
> client (gérant)** (`feature` · Must · Effort M · PRD §6 Épic 4 / §7.2 « Clients » / §8.1). **Dépend
> de #25** (cycle de statuts gérant — le statut `COMPLETED` existe et est atteignable) **et de #28**
> (création d'une fiche client, section « Clients » ouverte). Poursuit le jalon **M4 — Clients,
> encaissement & journal de caisse**. **Cette spec ne produit pas de code** : elle décrit l'approche
> à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 4, US-4.2) pose le besoin : **« en tant que gérant, je veux consulter l'historique
des visites d'un client afin de personnaliser le service »**, avec pour spécification fonctionnelle
**« liste des RDV passés, prestations, montants »**. Le PRD §7.2 range explicitement l'**historique**
dans la section **Clients** de l'interface web gérant (liste, recherche, création de fiche,
historique, notes internes). Le critère d'acceptation de l'issue #29 est :

- **L'historique liste les RDV terminés du client avec prestations et montants.**

C'est le **second module « gestion clients »**, immédiatement après la création de fiche (#28). Il
transforme la fiche client — aujourd'hui statique (nom, téléphone, genre, notes) — en un **dossier de
suivi** : le gérant voit ce que le client a consommé, quand, et pour quel montant.

État actuel du dépôt (après #28) — établi par lecture du code, **pas** d'hypothèse :

- **La fiche client (#28) est livrée mais isolée des rendez-vous.** `POST/GET
  /salons/{salon_id}/customers` existent (`adapters/inbound/customers.py`), la fiche
  (`domain/customer.py::Customer`) porte déjà `last_visit_at` et `total_visits` — mais **à leurs
  défauts** (`NULL` / `0`) : #28 les initialise sans jamais les calculer (cf. son *Non-Goals* « #29
  ne les calcule ni ne les met à jour »). Le champ `Customer` **n'expose volontairement pas**
  `user_id` (anti-oracle §11.1/§11.3, ADR-0026).
- **Le cycle de statuts gérant (#25) est livré.** La machine à états
  (`domain/appointment.py::ALLOWED_STATUS_TRANSITIONS`) permet `CONFIRMED → COMPLETED` (« prestation
  réalisée ») via `POST /salons/{salon_id}/appointments/{id}/status` ; `COMPLETED` est **terminal**.
  Le domaine porte déjà l'invariant de recette :
  `domain/appointment.py::REVENUE_STATUSES == (COMPLETED,)` et `counts_towards_revenue(status)` — «
  le CA ne compte que les RDV réalisés ». Aucun calcul de montant n'est encore livré.
- **Les montants existent, figés, au niveau de la jonction.** `appointment_services.price_at_booking`
  (`models.py:369`, `Numeric(12, 2)`) capture le **prix figé à la réservation** ; le domaine
  `BookedService` (`domain/appointment.py:35`) le porte déjà. Mais l'entité `BookedService` **ne
  porte pas le nom** de la prestation, et l'`AppointmentResponse` de #21 n'expose que
  `service_id + price_at_booking` (pas de nom, pas de total) : **une lecture enrichie manque** pour
  afficher « prestations + montants » de façon lisible.
- **Le lien fiche ↔ rendez-vous n'existe qu'via `user_id`.** Un `Appointment` porte `client_id` → FK
  `users.id` (`models.py:325`) : le « client » d'un RDV est un **compte utilisateur** (réservation
  mobile #21). Une `CustomerProfile` porte `user_id` **nullable** (`models.py:402`). **Le seul pont
  possible aujourd'hui** entre une fiche et des RDV est `customer_profiles.user_id ==
  appointments.client_id` (dans le même salon). Or #28 crée **exclusivement** des fiches walk-in
  (`user_id = NULL`) : en pratique, **aucune** fiche existante ne se relie à des RDV. C'est le point
  dur de #29 — voir *Risks and Open Questions* §1 (décision structurante à confirmer).
- **Aucune route « historique client » n'existe.** Une recherche `history`/`visit`/`historique` sur
  `backend/coiflink_api` et `web-dashboard/src` ne remonte rien. La page web `/gerant/clients` (#28)
  liste les fiches mais n'offre **aucune vue détaillée** ni historique.
- **Le socle est mûr.** Les patrons à réutiliser sont éprouvés : ressource **imbriquée sous
  `/salons/{salon_id}/customers/{customer_id}/…`** pour hériter de `require_salon_scope` (isolation
  §11.2) + `require_permission(CUSTOMER_MANAGE)` ; tranche hexagonale `domain/ → application/
  (+ ports) → adapters/` ; **lecture pure sans audit** (patrons `ListSalonCustomers` #28,
  `ListSalonAppointments` #26) ; côté web *Server Component → gateway HTTP (jeton du cookie
  `httpOnly`) → BFF → rendu*.

Le gap que #29 comble : une **lecture enrichie, salon-scopée et fiche-scopée** des RDV **terminés**
d'un client (prestations nommées + montant par visite + total), exposée par un **nouvel endpoint**
`GET /salons/{salon_id}/customers/{customer_id}/appointments`, et rendue par une **page de détail
de fiche** `/gerant/clients/{customer_id}`. **Sans** migration ni changement de schéma : tout est
dérivé en lecture des tables existantes.

## Goals

- **Lister les RDV terminés d'un client, avec prestations et montants** (critère d'acceptation).
  `GET /salons/{salon_id}/customers/{customer_id}/appointments` renvoie, pour la fiche visée, ses
  visites **`COMPLETED`** — chacune avec sa date, ses prestations (nom + prix figé) et son **montant
  total** (somme des `price_at_booking`), triées **de la plus récente à la plus ancienne**.
- **Rattachement fiche → RDV par `user_id`, encapsulé dans le dépôt.** Le lien
  `customer_profiles.user_id == appointments.client_id` (dans le **même salon**) est calculé **en
  SQL**, jamais exposé : l'`user_id` de la fiche ne quitte **pas** la couche de persistance
  (invariant anti-oracle §11.1/§11.3, ADR-0026). Une fiche walk-in (`user_id = NULL`) renvoie une
  **liste vide** (aucune visite reliable) — comportement **documenté**, pas une erreur.
- **Isolation par salon (§11.2), en profondeur.** L'endpoint est salon-scopé
  (`require_salon_scope` → `403` **générique**) **et** fiche-scopé : la fiche est résolue via
  `(salon_id, customer_id)` (réutilise `GetCustomer` de #28 → `404` **après** portée si la fiche
  n'est pas du salon, sans oracle) **et** la lecture des RDV refiltre `salon_id` **et** `client_id`
  en SQL. Un gérant ne voit **que** l'historique des fiches de son salon, et **que** les RDV **de son
  salon** (jamais les RDV du même client dans un autre salon — cloisonnement §11.2).
- **Montants exacts et figés.** Le montant d'une visite est la **somme des `price_at_booking`** de
  ses prestations (prix **figé à la réservation**, jamais le tarif courant — un changement de tarif
  ne réécrit pas l'historique, invariant #21). Devise **XOF** (unique au MVP, §9.6). Aucun arrondi
  (`Numeric(12, 2)`, jamais de flottant).
- **Statut « terminé » = `COMPLETED`.** L'historique des **visites** liste les RDV **réalisés**
  (`COMPLETED`), aligné sur le critère d'acceptation « RDV terminés » et sur l'invariant
  `REVENUE_STATUSES` du domaine. Les RDV `CANCELLED`/`NO_SHOW`/actifs (`PENDING`/`CONFIRMED`) **ne
  figurent pas** dans l'historique des visites (voir *Open Questions* §3).
- **Agrégats dérivés en lecture** (pas de dénormalisation). La réponse expose un **résumé** —
  nombre de visites (`total_visits`) et **date de dernière visite** (`last_visit_at`) — **calculé à
  la volée** depuis les RDV `COMPLETED`, **sans** écrire les colonnes homonymes de
  `customer_profiles` (voir *Open Questions* §5). Reflète toujours la vérité, sans chemin d'écriture
  fragile.
- **Réutilisation stricte de `CUSTOMER_MANAGE`.** L'endpoint câble la permission §4.1 déjà présente
  (détenue par le seul `MANAGER`) — **sans** modifier `ROLE_PERMISSIONS` (aucun élargissement de
  droits), exactement comme #28.
- **Lecture pure, sans effet de bord.** Aucune écriture, **aucune** entrée d'audit (patron des
  lectures #26/#28), aucun chemin ajouté à `PUBLIC_ROUTE_PATHS`.
- **Page de détail de fiche `/gerant/clients/{customer_id}`.** Affiche la fiche (réutilise
  `GET customers/{id}` de #28) et son **historique de visites** (date, prestations, montant, total),
  avec un lien depuis la liste `/gerant/clients` (#28). Jeton lu **côté serveur** (cookie `httpOnly`,
  invariant #14).
- **Aucune PII journalisée.** Ni les logs applicatifs, ni les messages d'erreur ne portent de nom,
  téléphone, note ou détail de visite. L'endpoint n'est **jamais** public.
- **Couverture de tests.** Backend : domaine (montant d'une visite), cas d'usage (portée, filtre
  `COMPLETED`, tri, fiche walk-in → vide, cloisonnement inter-salons, prix figé), API
  (`200`/`401`/`403`/`404`), e2e PostgreSQL (isolation, montants réels, absence de PII). Web : domaine
  de formatage (montant/date), gateway HTTP, BFF, navigation.

## Non-Goals

- **Rattachement d'une fiche à un compte utilisateur (`user_id`).** #29 **lit** le lien `user_id`
  s'il existe mais **ne le crée pas**. Tant que le rattachement (auto ou explicite) n'est pas livré
  (écarté par #28 pour raison d'anti-oracle), l'historique d'une fiche walk-in reste **légitimement
  vide**. Le rattachement est une évolution ultérieure (voir *Open Questions* §1) — **pré-requis
  fonctionnel** pour que l'historique soit peuplé en production, à trancher avec le produit.
- **Écriture / maintenance des colonnes dénormalisées `last_visit_at` / `total_visits`.** #29 les
  **dérive en lecture** et ne les écrit pas ; aucun *trigger*, aucun couplage dans `SetAppointmentStatus`
  (#25). Leur alimentation persistée reste une décision différée (voir *Open Questions* §5).
- **Historique côté client / mobile (US-4.4, #30).** #29 est un parcours **gérant** (web). Le paquet
  `app-mobile/` n'est **pas** touché. « Mes rendez-vous » côté client (#23) est une lecture distincte,
  déjà livrée.
- **Statistiques par client (US-4.3, #31).** Fréquence, panier moyen, prestations préférées et autres
  agrégats analytiques dépendent de #29 mais en sont **hors périmètre** — #29 fournit la brique de
  lecture, pas les KPI.
- **Encaissement / paiements (US-4.x, #33+).** Les montants affichés sont les **prix figés des
  prestations réservées** (`price_at_booking`), **pas** des paiements encaissés (`payments`, non
  livrés). L'historique reflète ce qui a été **réalisé**, pas ce qui a été **payé** — distinction à
  matérialiser quand l'encaissement arrivera (voir *Open Questions* §4).
- **Modification / suppression d'une visite ou d'une fiche depuis l'historique.** #29 est **en
  lecture seule**. L'édition de la note privée reste US-4.5 (#32).
- **Pagination avancée / recherche / filtres de l'historique.** L'historique d'**un** client est
  borné en pratique ; #29 renvoie la liste complète des visites `COMPLETED` (voir *Open Questions*
  §6 pour un garde-fou de volume). La recherche §7.2 reste un suivi.
- **Inclusion des RDV `NO_SHOW` / `CANCELLED` / actifs** dans l'historique des **visites** : hors
  périmètre du critère « RDV terminés » (voir *Open Questions* §3).
- **Migration / changement de schéma.** Aucun. #29 est une lecture dérivée des tables existantes
  (`appointments`, `appointment_services`, `services`, `customer_profiles`).

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
**ADR-0027**. Un ADR pour #29 est **optionnel** (voir *Open Questions* §7) — la décision de lien
`user_id` et de dérivation en lecture peut être consignée dans l'ADR-0027 ou repliée dans les README.

### Backend — patrons à réutiliser tels quels

- **Tranche « fiche client » (#28)** — le gabarit le plus proche : `domain/customer.py` →
  `application/ports/customer_repository.py` (`Protocol`) → `application/customers.py`
  (`GetCustomer`, `ListSalonCustomers`) → `adapters/outbound/persistence/customer_repository.py`
  (`SqlCustomerRepository`) → `adapters/inbound/customers.py` (router `prefix="/salons"`, routes
  `"/{salon_id}/customers…"`). #29 **étend** cette tranche.
- **Lecture salon-scopée sans audit (#26, `ListSalonAppointments`)** — patron de **lecture pure** :
  aucune écriture, aucun audit ; la portée salon est assurée par `require_salon_scope` **et
  ré-affirmée en SQL** par le dépôt (défense en profondeur §11.2). Le **groupement/format** est un
  concern d'affichage porté par le web.
- **Montants & prestations d'un RDV** — `appointment_services` (`models.py:353`) porte
  `price_at_booking` (prix figé) et les FK composites `(salon_id, appointment_id)` /
  `(salon_id, service_id)` qui **garantissent en base** que RDV et prestation appartiennent au même
  salon. `services.name` fournit le libellé (une prestation soft-deletée `is_active = false` reste
  en table — FK `RESTRICT` — donc son nom reste résoluble pour l'historique).
- **Invariant de recette** — `domain/appointment.py::REVENUE_STATUSES` / `counts_towards_revenue` :
  seul `COMPLETED` compte. #29 réutilise cette borne pour définir « RDV terminés ».
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` sur chaque route ; `403` **générique et constant** ; l'invariant
  deny-by-default est vérifié mécaniquement par `unprotected_routes(app)`
  (`test_security_guards.py`) — **une route ajoutée sans garde fait échouer les tests**.
- **Anti-oracle (ADR-0026)** : `Customer` **n'expose pas** `user_id` ; #29 le **conserve
  encapsulé** dans le dépôt (le lien se fait en SQL, jamais renvoyé). On **n'interroge jamais**
  `users` par téléphone (le lien passe **uniquement** par `user_id`, jamais par matching de numéro).
- **Tests** : fakes en mémoire dans `tests/conftest.py` (un par port) + fixtures ; tests d'API via
  `TestClient` et `app.dependency_overrides` ; **tests e2e** adossés à un vrai PostgreSQL, sautés si
  `DATABASE_URL` absent, avec plage de numéros réservée et nettoyage avant/après.

### Modèle de données pertinent (schéma #3, aucun changement)

```
appointments (client_id → users.id, salon_id, status, appointment_date, start_time, end_time)
  └─ appointment_services (appointment_id, service_id, salon_id, price_at_booking)   ← montant figé
        └─ services (id, salon_id, name, …)                                          ← libellé
customer_profiles (id, salon_id, user_id NULLABLE, full_name, phone, last_visit_at, total_visits, …)
```

Pont fiche → RDV : `customer_profiles.user_id == appointments.client_id` **ET** même `salon_id`.
Index utiles **déjà présents** : `ix_appointments_salon_id (salon_id, appointment_date)`,
`ix_appointments_client_id (client_id)`, `ix_appointment_services_service_id`. **Aucune migration
nécessaire** ; #29 n'ajoute **aucune** colonne, contrainte ni index.

### Web gérant — patrons à réutiliser (#14 → #28)

- `app/(gerant)/gerant/<section>/[param]/page.tsx` = **Server Component + composition root** : lit le
  cookie (`createCookieSessionStore().read()`), appelle les gateways HTTP côté serveur, rend l'UI.
- `src/adapters/api/http-*-gateway.ts` : `fetch` vers le backend avec `Authorization: Bearer`,
  résultat en **union discriminée** (`{ok:true,…} | {ok:false, reason:…}`) — jamais d'exception qui
  remonterait un détail réseau/jeton à l'UI.
- `app/api/salons/[id]/…/route.ts` : **Route Handlers BFF** qui lisent le jeton du cookie et
  proxifient ; messages d'erreur **neutres** en français.
- `src/domain/customer/customer.ts` : domaine TS pur (à étendre pour le formatage montant/date).

### Contraintes transverses documentées

- **PRD §11.2** : « un gérant ne peut voir que les données de son salon ».
- **PRD §11.3** : collecte minimale, **journalisation des accès sensibles**, données personnelles
  protégées.
- **PRD §8.1 / §8.2** : « un RDV terminé ne peut plus être modifié » ; le CA ne compte que les RDV
  réalisés ; devise unique **XOF** ; montants `NUMERIC(12,2)` (jamais de flottant).
- **PRD §12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI applicative
  `ci.yml` (ruff, pytest, round-trip Alembic contre PostgreSQL 16, build, lint/test/build web).

## Proposed Implementation

### (A) Backend — domaine (lecture enrichie, pur)

**`domain/visit.py`** (nouveau, **pur** — ni FastAPI ni SQLAlchemy) :

```python
@dataclass(frozen=True)
class VisitService:
    """Prestation d'une visite terminée : libellé + prix figé (US-4.2, #29)."""
    service_id: uuid.UUID
    name: str
    price_at_booking: decimal.Decimal

@dataclass(frozen=True)
class CustomerVisit:
    """RDV terminé d'un client, vue « historique » (prestations nommées + montant)."""
    appointment_id: uuid.UUID
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    status: str                         # toujours COMPLETED dans ce périmètre
    services: tuple[VisitService, ...]
    total_amount: decimal.Decimal       # somme des price_at_booking

@dataclass(frozen=True)
class VisitHistory:
    """Historique agrégé d'une fiche : visites + résumé dérivé (jamais dénormalisé)."""
    visits: tuple[CustomerVisit, ...]
    total_visits: int                   # len(visits)
    last_visit_at: datetime.datetime | None   # date/heure de la visite la plus récente
    total_amount: decimal.Decimal       # somme des totaux de visite
    currency: str = "XOF"
```

- `visit_total(services: tuple[VisitService, ...]) -> decimal.Decimal` : somme **pure** des
  `price_at_booking` (fonction testable sans I/O). Une visite **sans** prestation ne devrait pas
  exister (invariant §8.1 « ≥ 1 prestation »), mais la somme d'un tuple vide vaut `Decimal("0")`
  (robustesse, sans erreur).
- `build_history(visits) -> VisitHistory` : construit le résumé (`total_visits = len`,
  `last_visit_at` = date+heure de la visite en tête après tri décroissant, `total_amount` = somme).
  **Pur** : le tri est appliqué par le dépôt (SQL) mais `build_history` ne suppose que l'ordre
  « plus récent d'abord » (il prend `visits[0]` pour `last_visit_at`, ou `None` si vide).
- `HISTORY_STATUSES: tuple[str, ...] = (AppointmentStatus.COMPLETED.value,)` — la définition de « RDV
  terminés » de #29, **nommée distinctement** de `REVENUE_STATUSES` (même valeur aujourd'hui, mais
  deux décisions métier séparées, susceptibles de diverger — patron `CLIENT_CANCELLABLE_STATUSES`).

Ajouter les symboles à `__all__`.

### (B) Backend — port & adapter de persistance

**`application/ports/customer_repository.py`** — **étendre** le `Protocol` existant (pas de nouveau
port : l'historique est fiche-scopé, il appartient à la tranche « clients ») :

```python
def list_visits(
    self,
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    statuses: tuple[str, ...],
) -> tuple[CustomerVisit, ...]: ...
```

Docstring : renvoie les RDV du **compte lié** à la fiche `(salon_id, customer_id)` dont le `status`
est dans `statuses`, avec leurs prestations (nom + prix figé), triés **date décroissante** puis
`start_time` décroissant. **Encapsule le lien `user_id`** : si la fiche est walk-in
(`user_id IS NULL`) ou introuvable dans le salon, renvoie un **tuple vide** — l'`user_id` n'est
**jamais** exposé (anti-oracle ADR-0026). Filtre **`salon_id`** sur les RDV (cloisonnement §11.2 :
jamais les RDV du même compte dans un autre salon).

**`adapters/outbound/persistence/customer_repository.py`** — implémenter `list_visits` sur
`SqlCustomerRepository` :

- Une **seule requête** (ou deux ciblées) jointe :
  `customer_profiles` (filtre `id = :customer_id AND salon_id = :salon_id`, projette `user_id`) →
  si `user_id IS NULL` retourner `()` sans toucher aux RDV ;
  sinon `appointments` (`WHERE salon_id = :salon_id AND client_id = :user_id AND status IN
  :statuses`) ⋈ `appointment_services` ⋈ `services` (pour le nom), `ORDER BY appointment_date DESC,
  start_time DESC`.
- Regrouper les lignes plates (une par prestation) en `CustomerVisit` (prestations agrégées par RDV,
  ordre de prestation stable par `service_id` ou `created_at` de la jonction). Calculer
  `total_amount` via `domain.visit.visit_total`.
- `_visit_to_domain(...)` privé, comme `_to_domain`. **Lecture seule** : aucun `flush`, aucun
  `commit` (piloté par `get_session`).

> **Encapsulation de l'`user_id`** : la jointure se fait **entièrement en SQL** ; ni le port, ni le
> cas d'usage, ni la réponse HTTP ne voient l'`user_id` de la fiche. C'est l'invariant anti-oracle
> d'ADR-0026 tenu de bout en bout.

### (C) Backend — cas d'usage

**`application/customers.py`** — ajouter un cas d'usage de lecture (ne dépend que du port
`CustomerRepository`) :

```python
class GetCustomerVisitHistory:
    def execute(self, salon_id, customer_id) -> VisitHistory:
        # 1. Résout la fiche DANS le salon (réutilise GetCustomer) → CustomerNotFound (404) sinon.
        GetCustomer(self._repository).execute(salon_id, customer_id)
        # 2. Lit les RDV terminés liés (COMPLETED), user_id encapsulé côté dépôt.
        visits = self._repository.list_visits(salon_id, customer_id, HISTORY_STATUSES)
        # 3. Construit le résumé dérivé (pur).
        return build_history(visits)
```

- **Réutilise `GetCustomer`** pour la sémantique `404` **après** portée (isolation §28) : une fiche
  d'un autre salon est indiscernable d'une inexistante (aucun oracle). L'étape 2 refiltre `salon_id`
  en défense en profondeur.
- **Lecture pure → aucun audit** (patron `ListSalonCustomers` / `ListSalonAppointments`). Voir
  *Open Questions* §8 (§11.3 « accès sensibles ») si l'on décide d'auditer les lectures d'historique.

### (D) Backend — adapter entrant (HTTP)

**`adapters/inbound/customers.py`** — ajouter **une** route au router existant (`prefix="/salons"`) :

```python
@router.get(
    "/{salon_id}/customers/{customer_id}/appointments",
    response_model=CustomerVisitHistoryResponse,
    summary="Historique des visites terminées d'un client (prestations + montants)",
    responses={401: {...}, 403: {...}, 404: {...}},
)
def get_customer_history(
    salon_id: uuid.UUID,
    customer_id: uuid.UUID,
    repository: ... = Depends(get_customer_repository),
    _scope: SalonScope = Depends(require_salon_scope),
    _principal: Principal = Depends(require_permission(Permission.CUSTOMER_MANAGE)),
) -> CustomerVisitHistoryResponse: ...
```

- Schémas Pydantic documentés (OpenAPI) : `VisitServiceResponse` (`service_id`, `name`,
  `price_at_booking`), `CustomerVisitResponse` (`appointment_id`, `date`, `start_time`, `end_time`,
  `status`, `services`, `total_amount`), `CustomerVisitHistoryResponse` (`customer_id`, `items`,
  `total_visits`, `last_visit_at`, `total_amount`, `currency`).
- Traduction d'erreur : `CustomerNotFound` → **404** (uniquement après validation de portée).
  Aucune autre erreur de domaine attendue (lecture).
- **Garde** : `require_salon_scope` **et** `require_permission(Permission.CUSTOMER_MANAGE)`.
  **Aucun** chemin ajouté à `PUBLIC_ROUTE_PATHS`.
- **Nom du sous-chemin** : `…/appointments` (les visites *sont* des rendez-vous) plutôt que
  `…/history` — cohérence REST avec `/salons/{salon_id}/appointments` (#26). À confirmer (*Open
  Questions* §2) ; `…/history` acceptable si le produit le préfère.

`main.py` : **aucun** changement (le router `customers` est déjà inclus par #28).

### (E) Web gérant — page de détail & historique

1. **Domaine TypeScript** — étendre `src/domain/customer/customer.ts` (ou nouveau
   `src/domain/customer/visit.ts`) : types `CustomerVisit`, `VisitService`, `VisitHistory` ;
   helpers **purs** de formatage `formatAmountXof(value)` (séparateur de milliers, suffixe
   « FCFA »/« XOF ») et `formatVisitDate(iso)` (fuseau Africa/Abidjan). Le backend reste l'autorité
   des montants ; le front **formate** seulement.
2. **Port & gateway** — étendre `src/application/ports/customer-gateway.ts` +
   `src/adapters/api/http-customer-gateway.ts` avec `history(salonId, customerId)` et `get(salonId,
   customerId)` (si absent), résultats en union discriminée (`reason: "forbidden" |
   "unauthenticated" | "not-found" | "unavailable"`). **Jamais** le jeton dans le résultat.
3. **BFF** — `app/api/salons/[id]/customers/[customerId]/appointments/route.ts` (`GET`) : lit le
   jeton du cookie `httpOnly`, proxifie, messages neutres. (Et `…/[customerId]/route.ts` pour la
   fiche si non couvert par #28.)
4. **Page** — `app/(gerant)/gerant/clients/[customerId]/page.tsx` (Server Component) : charge le
   salon du gérant, la fiche puis son historique ; rend l'en-tête de fiche + un **tableau des
   visites** (date, prestations, montant) et un **résumé** (nombre de visites, dernière visite,
   total). État **vide explicite** : « Aucune visite terminée pour ce client » (cas walk-in / pas
   encore de RDV réalisé) — **pas** une erreur.
5. **UI** — `src/adapters/ui/customer-visit-history.tsx` (tableau + états vide/erreur) ; lien
   « Voir l'historique » depuis chaque ligne de `customer-list.tsx` (#28) vers
   `/gerant/clients/{id}`.
6. **Navigation** — aucun changement (`clients` est déjà `available` depuis #28) ; le fil
   d'Ariane/retour vers `/gerant/clients` suffit.

### (F) Documentation & (option) ADR

- **`backend/README.md`** : sous-section « Clients — historique des visites (US-4.2, #29) » — route,
  permission, réponses, note sur le lien `user_id` (fiche walk-in → historique vide) et les montants
  figés (`price_at_booking`, XOF).
- **`web-dashboard/README.md`** : ligne `/gerant/clients/{id}` + BFF associé.
- **`README.md`** (racine) §6 : phrase de statut « historique des visites d'un client (#29) livré ».
- **(Option) `docs/adr/0027-historique-visites-client.md`** + entrée `docs/adr/README.md` : décisions
  (lien **uniquement** par `user_id` — jamais par téléphone ; agrégats **dérivés en lecture**, pas de
  dénormalisation ; « terminé » = `COMPLETED` ; montants figés). Voir *Open Questions* §7 (peut être
  replié dans les README si un ADR n'est pas jugé nécessaire).

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/domain/visit.py` | read models `VisitService`/`CustomerVisit`/`VisitHistory`, `visit_total`, `build_history`, `HISTORY_STATUSES` |
| `tests/test_domain_visit.py` | tests du domaine (montant, résumé) |
| `tests/test_customer_history_api.py` | tests API (`200`/`401`/`403`/`404`) |
| `tests/test_customer_history_e2e.py` | tests e2e PostgreSQL (isolation, montants réels, absence de PII) |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/application/ports/customer_repository.py` | méthode `list_visits(salon_id, customer_id, statuses)` |
| `coiflink_api/adapters/outbound/persistence/customer_repository.py` | implémentation SQL jointe (`user_id` encapsulé) |
| `coiflink_api/application/customers.py` | cas d'usage `GetCustomerVisitHistory` |
| `coiflink_api/adapters/inbound/customers.py` | route `GET …/{customer_id}/appointments` + schémas de réponse |
| `tests/conftest.py` | `FakeCustomerRepository.list_visits` (données de visite en mémoire) |
| `tests/test_customer_usecases.py` | cas `GetCustomerVisitHistory` (portée, filtre, tri, walk-in vide, cloisonnement) |
| `backend/README.md` | sous-section « historique des visites » |

### Web (`web-dashboard/`)

À créer : `app/(gerant)/gerant/clients/[customerId]/page.tsx`,
`app/api/salons/[id]/customers/[customerId]/appointments/route.ts`,
(si besoin) `app/api/salons/[id]/customers/[customerId]/route.ts`,
`src/adapters/ui/customer-visit-history.tsx`,
`test/customer-visit-history.test.ts`, `test/customer-history-gateway.test.ts`,
`test/customer-history-bff.test.ts`.
À modifier : `src/domain/customer/customer.ts` (ou nouveau `visit.ts`) — types + formatage ;
`src/application/ports/customer-gateway.ts` + `src/adapters/api/http-customer-gateway.ts`
(`history`, `get`) ; `src/adapters/ui/customer-list.tsx` (lien « historique ») ;
`web-dashboard/README.md`.

### Documentation (racine)

`README.md` ; (option) `docs/adr/0027-historique-visites-client.md`, `docs/adr/README.md`.

### À lire (sans modifier) pour rester fidèle aux patrons

`adapters/inbound/customers.py`, `application/customers.py`, `domain/customer.py`,
`adapters/outbound/persistence/customer_repository.py`, `adapters/inbound/appointments.py`
(schéma de réponse RDV + statut `COMPLETED`), `application/appointments.py`
(`ListSalonAppointments`, `SetAppointmentStatus`), `domain/appointment.py` (`REVENUE_STATUSES`,
`BookedService`), `adapters/outbound/persistence/models.py` (`Appointment`, `AppointmentService`,
`Service`, `CustomerProfile`), `adapters/inbound/security.py`, `domain/permissions.py`,
`web-dashboard/app/(gerant)/gerant/clients/page.tsx`,
`web-dashboard/src/adapters/ui/customer-list.tsx`.

## API / Interface Changes

**Un** nouvel endpoint REST, **protégé** (`CUSTOMER_MANAGE` + portée salon) ; aucune route existante
n'est modifiée ; aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/customers/{customer_id}/appointments` | `CUSTOMER_MANAGE` + portée | `200` historique · `401` · `403` · `404` fiche hors salon |

```jsonc
// 200 — réponse
{
  "customer_id": "…uuid…",
  "items": [
    {
      "appointment_id": "…uuid…",
      "date": "2026-07-20",
      "start_time": "09:00:00",
      "end_time": "10:00:00",
      "status": "COMPLETED",
      "services": [
        { "service_id": "…", "name": "Coupe homme", "price_at_booking": "5000.00" },
        { "service_id": "…", "name": "Barbe",        "price_at_booking": "2000.00" }
      ],
      "total_amount": "7000.00"
    }
  ],
  "total_visits": 1,                       // dérivé (nombre de visites COMPLETED)
  "last_visit_at": "2026-07-20T09:00:00Z", // dérivé (visite la plus récente) ; null si aucune
  "total_amount": "7000.00",               // dérivé (somme des visites)
  "currency": "XOF"
}
```

- **Fiche walk-in (`user_id = NULL`) ou sans RDV terminé** → `200` avec `items: []`,
  `total_visits: 0`, `last_visit_at: null`, `total_amount: "0.00"` (comportement **normal**, pas une
  erreur).
- **`user_id` / `client_id` ne sont jamais exposés** (anti-oracle ADR-0026) : la réponse ne porte que
  l'`appointment_id` et des données de visite.
- **Interfaces web (BFF, internes à Next.js)** : `GET
  /api/salons/[id]/customers/[customerId]/appointments`. **Aucune** modification de CLI, de variable
  d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**None.** #29 est une **lecture dérivée** des tables existantes (`appointments`,
`appointment_services`, `services`, `customer_profiles`) : aucune migration Alembic, aucune colonne,
contrainte ou index ajouté. Les colonnes `customer_profiles.last_visit_at` / `total_visits` restent
à leurs défauts (`NULL` / `0`) — l'historique et son résumé sont **calculés à la lecture**, jamais
persistés (voir *Open Questions* §5 pour la décision de dénormalisation différée). Les montants sont
lus **tels quels** depuis `appointment_services.price_at_booking` (`NUMERIC(12,2)`, jamais de
flottant), sérialisés en chaîne décimale.

## Security & Privacy Considerations

**Ce module lit des données personnelles (PII) — historique de consommation d'un client — c'est sa
principale sensibilité** (PRD §11.3).

- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur la route (portée
  **chargée en base**, jamais déduite du corps) **et** double filtre SQL : la fiche est résolue via
  `(salon_id, customer_id)` (`GetCustomer`, `404` **après** portée si hors salon, sans oracle) **et**
  les RDV sont filtrés `salon_id = :salon_id AND client_id = :user_id`. Un gérant ne voit **jamais**
  les visites du même client dans un **autre** salon (cloisonnement strict), ni la fiche d'un autre
  salon.
- **Anti-oracle d'existence de compte (ADR-0026), tenu de bout en bout.** Le lien
  `customer_profiles.user_id == appointments.client_id` est calculé **uniquement en SQL** ;
  `user_id`/`client_id` ne sont **jamais** renvoyés ni journalisés. On **n'interroge jamais** `users`
  par téléphone. Une fiche walk-in renvoie un historique **vide** — indiscernable d'une fiche liée
  sans visite terminée : aucun signal sur l'existence d'un compte.
- **Deny-by-default (ADR-0015).** Aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` ; l'invariant est
  vérifié mécaniquement (`unprotected_routes(app)`). Un historique client n'est **jamais** lisible
  sans jeton, ni exposé au client, au coiffeur ou au catalogue public (#18/#19).
- **Permission `CUSTOMER_MANAGE` seule (§4.1).** Détenue par le seul `MANAGER`. Le `HAIRDRESSER` ne
  lit **pas** l'historique client (il n'a que son planning), l'`ADMIN` non plus (supervision ≠
  exploitation, ADR-0015). La matrice `ROLE_PERMISSIONS` **n'est pas modifiée**.
- **Aucune PII ni secret dans les logs.** Aucun `print`/`logger` ne reçoit le nom, le téléphone, les
  notes ni le détail des visites ; les messages `4xx` restent **neutres**. Le montant et le nom de
  prestation, exposés dans la **réponse** au gérant légitime, ne sont **jamais** journalisés.
- **Lecture pure — aucun effet de bord.** Aucune écriture, aucune entrée d'audit par défaut (patron
  des lectures #26/#28). Si l'on juge la lecture d'historique comme un « accès sensible » à tracer
  (§11.3), l'ajout d'un audit **neutre** (acteur + `customer_id`, jamais le détail des visites) est
  une **option** (voir *Open Questions* §8) — à décider avant l'implémentation.
- **Montants figés & devise unique.** Les montants sont les `price_at_booking` (prix figés à la
  réservation), jamais recalculés au tarif courant : l'historique est **stable** et fidèle. Devise
  **XOF** (§9.6). `NUMERIC(12,2)` sérialisé en décimal — jamais de flottant (perte de précision
  monétaire).
- **Budget de latence (§12.1).** La lecture est bornée par l'historique d'**un** client (volume
  faible en pratique) et couverte par `ix_appointments_client_id` / `ix_appointments_salon_id`. Un
  garde-fou de volume (limite haute) est discuté en *Open Questions* §6 par précaution.
- **Jeton jamais exposé côté web (#14).** La page et le Route Handler lisent le cookie `httpOnly`
  **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.

Le dépôt ne documente **aucune** contrainte supplémentaire (résidence, chiffrement applicatif requis)
au-delà de celles ci-dessus pour cette lecture.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_domain_visit.py`** : `visit_total` (somme de plusieurs `price_at_booking` ; tuple
  vide → `Decimal("0")` ; pas de flottant) ; `build_history` (`total_visits = len`, `last_visit_at`
  = visite en tête, `total_amount` = somme ; historique vide → `total_visits = 0`,
  `last_visit_at = None`, `total_amount = 0`).
- **`tests/test_customer_usecases.py`** (fakes de `conftest.py`), cas `GetCustomerVisitHistory` :
  - fiche introuvable / d'un autre salon → `CustomerNotFound` (avant toute lecture de RDV) ;
  - fiche walk-in (fake sans lien) → historique **vide** ;
  - fiche liée : seules les visites **`COMPLETED`** sont renvoyées (un RDV `PENDING`/`CONFIRMED`/
    `CANCELLED`/`NO_SHOW` du même compte est **exclu**) ;
  - **tri** plus récent d'abord ; **montant** = somme des prix figés (et non du tarif courant) ;
  - **cloisonnement** : un RDV `COMPLETED` du même compte dans un **autre** salon n'apparaît pas ;
  - le `statuses` passé au dépôt vaut bien `HISTORY_STATUSES` (`(COMPLETED,)`).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_customer_history_api.py`** : `200` + corps attendu (visites, prestations nommées,
  `total_amount`, résumé dérivé) ; `404` fiche d'un autre salon (message **neutre**) ; `403` hors
  portée / rôle non `MANAGER` (message **constant**) ; `401` sans jeton ; **`user_id`/`client_id`
  absents** de la réponse ; fiche walk-in → `200` `items: []`.
- **`tests/test_security_guards.py`** : l'invariant `unprotected_routes(app) == []` couvre
  automatiquement la nouvelle route ; vérifier explicitement qu'**aucun** chemin d'historique n'entre
  dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_customer_history_e2e.py`** (patron `test_service_e2e.py`, plage de téléphones
  réservée, nettoyage avant/après) :
  1. **Historique peuplé** : créer un compte client + un salon + une prestation, réserver un RDV
     (#21), le confirmer puis le marquer `COMPLETED` (#25), **insérer une fiche liée**
     (`customer_profiles` avec `user_id = <client>`, écriture directe en base — le rattachement
     n'ayant pas d'endpoint) → `GET …/appointments` renvoie la visite avec le bon nom de prestation
     et le montant figé.
  2. **Isolation inter-salons** (critère d'acceptation) : le jeton du gérant B est refusé (`403`) sur
     l'historique d'une fiche du salon de A ; un RDV `COMPLETED` du même compte dans le salon de B
     n'apparaît **pas** dans l'historique côté A.
  3. **Filtre de statut** : un RDV `CANCELLED`/`NO_SHOW`/actif du même compte est **absent** de
     l'historique.
  4. **Fiche walk-in** (`user_id = NULL`, créée via #28) → `200` `items: []`.
  5. **Absence de PII** : la réponse ne contient ni `user_id` ni `client_id` ; aucun log ne porte de
     détail de visite.
  6. Deny-by-default : sans jeton → `401`.

> Le test **1** doit **écrire directement** une fiche liée (`user_id`) car #28/#29 n'exposent aucun
> rattachement — dépendance documentée (voir *Risks* §1). Le chemin « non peuplé » (walk-in) est,
> lui, entièrement couvrable par les endpoints livrés.

### Web (`vitest`)

- `test/customer-visit-history.test.ts` : formatage montant (`formatAmountXof`) et date, calcul/rendu
  du résumé, état **vide** (« Aucune visite terminée »).
- `test/customer-history-gateway.test.ts` : mapping des statuts backend → `reason`
  (`403 → "forbidden"`, `401 → "unauthenticated"`, `404 → "not-found"`), en-tête `Authorization`
  posé, **jeton jamais renvoyé** dans le résultat.
- `test/customer-history-bff.test.ts` : `401` sans cookie ; `404`/`403` propagés avec message neutre ;
  **aucune PII ni jeton** dans les réponses d'erreur.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ;
  `npm run lint && npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`backend/README.md`** — sous-section « Clients — historique des visites (US-4.2, #29) » : route,
  permission, réponses, **note sur le lien `user_id`** (fiche walk-in → historique vide) et sur les
  **montants figés** (`price_at_booking`, XOF) ; exemple `curl`.
- **`web-dashboard/README.md`** — ligne `/gerant/clients/{id}` (page de détail + historique) dans le
  tableau des routes + BFF associé.
- **`README.md`** (racine) — §6 : phrase de statut « historique des visites d'un client (#29) livré »
  dans le style des paragraphes existants ; cohérence du tableau des jalons M4.
- **(Option) `docs/adr/0027-historique-visites-client.md`** + entrée `docs/adr/README.md` — si un ADR
  est retenu (*Open Questions* §7) : décisions de lien `user_id`, dérivation en lecture, définition de
  « terminé », montants figés.
- **OpenAPI** — `summary`/`responses`/docstrings de la route documentent la nouvelle API publique
  (visible sur `/docs`), y compris le `404`.

## Risks and Open Questions

1. **[BLOQUANT FONCTIONNEL] Le lien fiche ↔ rendez-vous n'existe qu'via `user_id`, laissé `NULL` par
   #28.** Aujourd'hui, toute fiche créée par le gérant est walk-in (`user_id = NULL`) : son historique
   sera **toujours vide** tant qu'un **rattachement fiche ↔ compte** n'est pas livré (écarté par #28
   pour raison d'anti-oracle). *Recommandation :* livrer #29 **tel quel** (lien par `user_id`,
   historique vide pour les fiches non liées) — l'endpoint et l'UI sont corrects et prêts à se peupler
   dès que le rattachement existera ; **et** remonter au produit que le **rattachement** (auto par
   `user_id` à la réservation, ou explicite par le gérant) est le vrai déblocage fonctionnel, à
   planifier (probable pré-requis de #31). **Alternative écartée** : relier par **téléphone**
   (`customer_profiles.phone` ↔ `users.phone`) — rejetée car (a) elle transforme la route en **oracle
   d'existence de compte** (ADR-0026), (b) le téléphone d'une fiche est optionnel et non fiable comme
   clé. **À confirmer** avant l'implémentation.
2. **Nom du sous-chemin.** `…/customers/{id}/appointments` (cohérence REST avec les RDV) vs
   `…/customers/{id}/history` (langage métier §7.2). *Recommandation : `…/appointments`*. **À
   confirmer.**
3. **Quels statuts comptent comme « terminés » ?** Le critère dit « RDV terminés » ; le domaine dit
   `REVENUE_STATUSES == (COMPLETED,)`. *Recommandation : `COMPLETED` uniquement* (une **visite** =
   une prestation réalisée ; un `NO_SHOW` n'est pas une visite, un `CANCELLED` non plus). **À
   confirmer** — si le produit veut un « historique complet » incluant `NO_SHOW`/`CANCELLED` (avec un
   badge), le paramètre `statuses` du dépôt le permet sans refonte (mais alors « montants » perd son
   sens pour les non-réalisés).
4. **Montants = prix figés, pas paiements.** L'encaissement (#33+) n'est pas livré : le montant
   affiché est la **somme des `price_at_booking`** (ce qui *aurait dû* être facturé), pas un paiement
   encaissé. *Recommandation : l'assumer et le documenter* (« montant de la prestation », pas «
   encaissé ») ; réconcilier avec `payments` quand l'encaissement arrivera. **À confirmer** le libellé
   côté UI.
5. **Faut-il alimenter les colonnes dénormalisées `last_visit_at` / `total_visits` ?** #28 les a
   laissées en forward-reference vers #29. *Recommandation : **dériver en lecture** et ne PAS les
   écrire* — les maintenir imposerait un chemin d'écriture dans `SetAppointmentStatus` (#25) couplé au
   lien `user_id` (inexistant pour les walk-in), fragile et source d'incohérence. La dérivation reflète
   toujours la vérité. **À confirmer** ; si un besoin de tri/filtre par « dernière visite » sur la
   **liste** des fiches émerge (#31), une dénormalisation (ou une vue) pourra être décidée alors.
6. **Volume de l'historique.** L'historique d'un client est petit en pratique, mais non borné par
   construction. *Recommandation : renvoyer la liste complète* (simple, budget §12.1 tenu par les
   index existants) et **ajouter une limite haute de sécurité** (`ORDER BY date DESC LIMIT N`, N élevé
   p. ex. 500) avec un `log()` si tronqué. **À confirmer** (pagination complète jugée superflue au
   MVP).
7. **Un ADR est-il nécessaire ?** #26/#27 n'en ont pas produit ; #28 l'a fait (changement de schéma).
   #29 **ne change pas le schéma**. *Recommandation : ADR **optionnel*** — replier les décisions (lien
   `user_id`, dérivation, définition de « terminé ») dans `backend/README.md` suffit ; produire
   l'ADR-0027 seulement si l'équipe le souhaite pour tracer le compromis anti-oracle. **À confirmer.**
8. **Journaliser la lecture d'historique (§11.3 « accès sensibles ») ?** Les lectures ne sont pas
   auditées ailleurs (#26/#28). *Recommandation : ne pas auditer* (cohérence + coût), en réservant
   l'option d'une entrée **neutre** (`CUSTOMER_HISTORY_VIEWED`, acteur + `customer_id`, jamais le
   détail) si une exigence de traçabilité des consultations émerge au durcissement (#52). **À
   confirmer.**
9. **Nom de prestation d'une prestation désactivée.** Une prestation soft-deletée (`is_active =
   false`) reste en table (FK `RESTRICT`) : son nom **courant** est affiché. C'est cohérent (le nom
   n'est pas figé, seul le prix l'est) — à assumer explicitement dans l'ADR/README.
10. **Cohérence port / read model.** `list_visits` retourne un read model d'appointment depuis le
    **port client** (`CustomerRepository`) : c'est un choix de cohésion de tranche (endpoint
    fiche-scopé) au prix d'un dépôt client qui lit `appointments`. *Recommandation : l'assumer* (le
    lien `user_id` doit rester encapsulé côté fiche) ; alternative (méthode sur
    `AppointmentRepository` prenant un `user_id`) rejetée car elle **exposerait** l'`user_id` au cas
    d'usage.

## Implementation Checklist

1. **Lire** `adapters/inbound/customers.py`, `application/customers.py`, `domain/customer.py`,
   `adapters/outbound/persistence/customer_repository.py`, `adapters/inbound/appointments.py`,
   `domain/appointment.py` (`REVENUE_STATUSES`, `BookedService`), `models.py` (`Appointment`,
   `AppointmentService`, `Service`, `CustomerProfile`) — s'imprégner des patrons.
2. **Trancher** les questions ouvertes 1 à 5 (lien `user_id` vs suivi de rattachement, nom du
   sous-chemin, statuts « terminés », montants = prix figés, dérivation vs dénormalisation) et
   consigner la décision (README ou ADR-0027 selon §7).
3. **Domaine** : créer `domain/visit.py` (`VisitService`, `CustomerVisit`, `VisitHistory`,
   `visit_total`, `build_history`, `HISTORY_STATUSES`) ; ajouter à `__all__`.
4. **Tests de domaine** : écrire `tests/test_domain_visit.py` — **avant** la persistance.
5. **Port** : étendre `application/ports/customer_repository.py` avec `list_visits(salon_id,
   customer_id, statuses)` (docstring : lien `user_id` encapsulé, filtre salon, tri, walk-in → vide).
6. **Fakes & tests applicatifs** : ajouter `list_visits` au `FakeCustomerRepository`
   (`tests/conftest.py`) ; écrire le volet `GetCustomerVisitHistory` de `tests/test_customer_usecases.py`
   (portée/`404`, filtre `COMPLETED`, tri, walk-in vide, cloisonnement, montant figé).
7. **Cas d'usage** : ajouter `GetCustomerVisitHistory` à `application/customers.py` (réutilise
   `GetCustomer` pour le `404`, aucune écriture, aucun audit).
8. **Adapter sortant** : implémenter `list_visits` dans `SqlCustomerRepository` (jointure
   `customer_profiles → appointments → appointment_services → services`, `user_id` **jamais** exposé,
   filtres `salon_id`/`client_id`/`status`, tri `date DESC, start_time DESC`, regroupement par RDV,
   `total_amount` via `visit_total`).
9. **Adapter entrant** : ajouter la route `GET /{salon_id}/customers/{customer_id}/appointments` à
   `adapters/inbound/customers.py` (schémas `VisitServiceResponse`/`CustomerVisitResponse`/
   `CustomerVisitHistoryResponse`, `require_salon_scope` + `require_permission(CUSTOMER_MANAGE)`,
   mapping `CustomerNotFound → 404`) ; **ne pas** toucher `PUBLIC_ROUTE_PATHS` ni `main.py`.
10. **Tests API & e2e** : écrire `tests/test_customer_history_api.py` puis
    `tests/test_customer_history_e2e.py` (historique peuplé via fiche liée insérée en base, isolation
    inter-salons, filtre de statut, walk-in vide, absence de PII, deny-by-default) ; exécuter `pytest`
    (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
11. **Web — domaine & accès** : étendre `src/domain/customer/customer.ts` (ou `visit.ts`) avec les
    types + formatage montant/date (+ test) ; étendre `customer-gateway.ts` et
    `http-customer-gateway.ts` (`history`, `get`) (+ test).
12. **Web — BFF** : `app/api/salons/[id]/customers/[customerId]/appointments/route.ts` (`GET`,
    messages neutres) (+ `…/[customerId]/route.ts` si la fiche n'est pas déjà proxifiée) +
    `test/customer-history-bff.test.ts`.
13. **Web — UI** : `app/(gerant)/gerant/clients/[customerId]/page.tsx` (Server Component, en-tête de
    fiche + tableau des visites + résumé + état vide explicite) ;
    `src/adapters/ui/customer-visit-history.tsx` ; lien « historique » dans `customer-list.tsx`.
14. **Documentation** : sous-sections dédiées dans `backend/README.md` et `web-dashboard/README.md` ;
    phrase de statut dans le `README.md` racine ; (option) ADR-0027 + entrée `docs/adr/README.md`.
15. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test),
    `ruff check`, `npm run lint && npm run build` ; relire la PR pour s'assurer qu'**aucune PII et
    aucun secret** (nom, téléphone, notes, `user_id`, détail de visite) n'apparaissent dans les logs
    ou les messages d'erreur, et qu'**aucune signature IA** n'a été introduite.
