# Clients actifs — segmentation nouveaux / récurrents / inactifs (dashboard gérant) (US-6.4, #42)

> Spécification de planification pour l'issue GitHub **#42 — US-6.4 : Clients actifs**
> (`feature` · Must · Effort **M** · PRD §6 Épic 6 US-6.4 / §8.1 / §11.2 / §11.3 / §12.1).
> **Dépend de #29** (US-4.2 — historique des visites d'un client) selon le backlog ; en pratique la
> brique réutilisée est **la notion de « visite »** = RDV `COMPLETED` et le **lien compte ↔ salon**
> (`appointments.client_id` → `users.id`) matérialisé par #29 — voir *Risks & Open Questions §1*.
> Repose aussi sur le shell du dashboard gérant (#14, zone `/gerant`), la permission
> `STATS_READ_SALON` (RBAC #12 / ADR-0015, **déjà** réservée au `MANAGER`, consommée par #39/#40/#41)
> et le **router stats dédié** `adapters/inbound/stats.py` (livré par #40, étendu par #41) — que ce
> KPI **étend** à son tour.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants
> techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés. **Aucune signature
> IA** dans le code, les commits ou la PR. **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.

## Problem Statement

Le PRD (§6 Épic 6, US-6.4) pose le besoin : **« en tant que gérant, je veux segmenter mes clients
(nouveaux, récurrents, inactifs) afin d'adapter ma relation client »**. Le critère d'acceptation de
l'issue #42 est :

- **Segmentation des clients sur une période donnée.**

C'est le **quatrième KPI du tableau de bord gérant** de l'Épic 6, après le décompte des RDV du jour
(#39, US-6.1), le chiffre d'affaires jour/semaine/mois (#40, US-6.2) et les prestations les plus
demandées (#41, US-6.3). Il transforme la vue « combien d'activité / combien de revenu / quelles
prestations » en une vue **par population de clients** : le gérant voit *combien de clients il a
gagnés, fidélisés et perdus* sur une période, pour orienter sa relance et sa fidélisation.

État actuel du dépôt (après #39/#40/#41) — établi par **lecture du code**, pas par hypothèse :

- **Aucune lecture « par client » agrégée au niveau salon n'existe.** Les lectures « client » livrées
  sont **fiche-scopées** : `SqlCustomerRepository.list_visits` (#29, `GET
  /salons/{salon_id}/customers/{customer_id}/appointments`) liste les RDV `COMPLETED` **d'une fiche**,
  et `domain/visit.py::favourite_services` (#31) agrège les prestations **d'une fiche**. Aucune ne
  segmente **l'ensemble** des clients d'un salon. #42 est une agrégation **à l'échelle du salon** —
  sur **tous** les RDV `COMPLETED`, groupés **par client** — qui appelle une **agrégation SQL**
  (`GROUP BY client_id`), pas un chargement de toutes les lignes en mémoire.
- **Le patron d'agrégation salon-scopée « en base » existe et est mûr (#39/#41).**
  `SqlAppointmentRepository::count_by_status_for_day` (#39) fait un `GROUP BY status` filtré
  `salon_id` + jour ; `SqlAppointmentRepository::demand_by_service` (#41) fait un `GROUP BY service_id`
  avec `COUNT` + `SUM(price_at_booking)`, **sans rapatrier de ligne** ni de PII. #42 est le **même
  geste** avec un `GROUP BY client_id` et des agrégats de dates/comptes (première visite, visites dans
  la période, visites avant la période).
- **Le router `stats` salon-scopé existe (#40/#41).** `adapters/inbound/stats.py`
  (`APIRouter(prefix="/salons", tags=["stats"])`) porte déjà `GET /salons/{salon_id}/revenue/summary`
  (#40) et `GET /salons/{salon_id}/service-demand` (#41) sous la garde `require_salon_scope` +
  `require_permission(STATS_READ_SALON)`, avec une DI `get_appointment_repository` surchargeable en
  test (livrée par #41). Son en-tête documente `STATS_READ_SALON` comme ayant « **trois** consommateurs
  ». #42 y **ajoute une route** — c'est le **quatrième** consommateur de `STATS_READ_SALON`.
- **La « visite » = RDV `COMPLETED` est une définition métier établie.** `domain/appointment.py::
  REVENUE_STATUSES == (COMPLETED,)` (recette §8.1) et `domain/visit.py::HISTORY_STATUSES ==
  (COMPLETED,)` (historique #29) portent la même population. #42 réutilise cette borne : un client est
  « vu » un jour donné s'il a un RDV `COMPLETED` ce jour-là.
- **Le lien client ↔ salon passe par `appointments.client_id` (compte utilisateur).** Un
  `Appointment` porte `client_id` → FK `users.id` (`models.py:325`, index `ix_appointments_client_id`).
  Le « client » d'un RDV est donc un **compte utilisateur** (réservation mobile #21). Les **fiches**
  (`customer_profiles`) sont, elles, **salon-scopées** avec un `user_id` **nullable** — et **walk-in**
  (`user_id = NULL`) pour toutes celles créées par le gérant (#28). Segmenter **les fiches** ne
  refléterait donc quasiment aucune donnée (elles ne se relient à aucun RDV) : c'est le **point dur**
  hérité de #29 (*Open Questions §1*). #42 segmente donc **les comptes qui ont réellement des visites**
  (`appointments.client_id`), pas les fiches.
- **Le dashboard `/gerant` (Server Component) est le point d'accrochage.** `app/(gerant)/gerant/
  page.tsx` charge déjà, côté serveur (jeton du cookie `httpOnly`, invariant #14), le salon puis
  `dailySummary` (#39), `revenueSummary` (#40) et `serviceDemand` (#41) via `http-stats-gateway.ts`, et
  rend `DailySummaryTiles` + `RevenueTiles` + `ServiceDemandPanel`. #42 **étend** cette page d'un
  panneau « Clients actifs » sous le panneau des prestations.

Le gap que #42 comble : une **lecture agrégée salon-scopée** répartissant les clients du salon en
**trois segments** (nouveaux, récurrents, inactifs) **sur une période donnée**, exposée par un
**nouvel endpoint** sur le router `stats` et rendue par un **panneau** sur le dashboard gérant.
**Sans** migration ni changement de schéma : tout est dérivé en lecture des tables existantes.

## Goals

- **Segmenter les clients du salon sur une période donnée** (critère d'acceptation). Pour un salon et
  une période `[date_from, date_to]`, répartir ses clients (comptes ayant des RDV `COMPLETED` au
  salon) en **trois compteurs** :
  - **Nouveaux** (`new`) : clients dont la **première** visite réalisée au salon tombe **dans** la
    période (aucune visite antérieure) ;
  - **Récurrents** (`recurring`) : clients ayant **au moins une** visite réalisée **dans** la période
    **et** au moins une visite **avant** la période (client fidèle qui revient) ;
  - **Inactifs** (`inactive`) : clients ayant des visites réalisées **avant** la période mais
    **aucune** dans la période (client silencieux / perdu).
  Ces trois segments sont **mutuellement exclusifs** : `{new, recurring}` partitionnent les clients
  **actifs sur la période** ; `inactive` est disjoint. *(Définition alternative « récurrent = ≥ 2
  visites au total » discutée en Open Questions §2.)*
- **Agréger « en base » (`GROUP BY client_id`), sans rapatrier de PII** : la réponse ne renvoie que
  des **compteurs** (entiers) et les bornes de période — **jamais** un `client_id`, un `appointment_id`,
  un nom, un téléphone, ni une ligne de RDV (§11.3, patron #39/#41). La **règle de classification** (ce
  qui rend un client nouveau/récurrent/inactif) est une **fonction pure** du domaine (testable sans
  base).
- **« Visite » = RDV `COMPLETED` uniquement** (réalisés), en cohérence avec l'invariant §8.1
  (`REVENUE_STATUSES == (COMPLETED,)`) et avec #29/#31 (`HISTORY_STATUSES`). Un RDV
  `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` **ne compte pas** comme une visite — « annulés exclus »
  (§8.1) est vrai **par construction** du filtre de statut, décidé côté serveur.
- **Anti-oracle par construction (§11.1/§11.3, ADR-0026).** #42 n'expose **que des comptes agrégés** :
  il ne renvoie **jamais** l'identité, l'existence ni le nombre exact de RDV d'un compte donné. Le lien
  fiche ↔ compte n'est **pas** touché (aucune jointure `customer_profiles` requise) ; segmenter des
  `client_id` **sans jamais les émettre** ne crée aucun oracle d'existence de compte.
- **Réutiliser strictement `STATS_READ_SALON`** (déjà détenue par le seul `MANAGER`) **+**
  `require_salon_scope` (isolation §11.2) — **sans** modifier `ROLE_PERMISSIONS`, exactement comme
  #39/#40/#41. **Quatrième** consommateur de cette permission.
- **Isolation §11.2, en profondeur.** Route salon-scopée (`require_salon_scope` → `403` **générique**,
  aucun oracle) **et** re-filtrage `WHERE appointments.salon_id = :salon_id` **inconditionnel** en SQL
  (défense en profondeur derrière la garde HTTP). Le dépôt ne segmente **jamais** les clients d'un
  autre salon ; un client vu **dans un autre salon** ne pèse pas ici (cloisonnement strict — un compte
  « nouveau » au salon A peut être « récurrent » au salon B, chaque salon voit **sa** relation).
- **Lecture pure, sans effet de bord.** Aucune écriture, **aucune** entrée d'audit §11.4 (patron des
  lectures #34/#35/#37/#39/#40/#41), aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` (une donnée
  d'exploitation salon n'est jamais publique).
- **Panneau « Clients actifs » sur le dashboard `/gerant`**, sous le panneau des prestations les plus
  demandées (#41), en réutilisant le patron Server Component + `http-stats-gateway` (jeton serveur,
  jamais exposé). État **vide explicite** : « Aucun client sur la période » (salon sans RDV
  `COMPLETED`) — **pas** une erreur. Dégradation **locale** sur panne (aligné #41).
- **Additif et rétro-compatible** : aucune signature existante modifiée, **aucune migration** de schéma
  (les index `ix_appointments_salon_id (salon_id, appointment_date)` et `ix_appointments_client_id
  (client_id)` couvrent la requête).
- **Couverture de tests** : domaine (classification déterministe des trois segments, bornes de période,
  vide), cas d'usage (statut `COMPLETED` imposé, bornes passées au port), API
  (`200`/`401`/`403`/`422`, absence de PII), e2e PostgreSQL (segmentation réelle, isolation
  inter-salons, filtre `COMPLETED`, bornes) ; web (mapping/formatage, gateway, rendu du panneau).

## Non-Goals

- **Aucune liste nominative de clients par segment.** #42 renvoie des **compteurs**, jamais la liste
  des clients d'un segment (ce serait de la PII salon-wide + un oracle). La consultation nominative
  d'un client reste la **fiche** (#28/#29/#31, permission `CUSTOMER_MANAGE`, fiche-scopée). Un éventuel
  « drill-down » nominatif est un suivi produit distinct (Open Questions §6).
- **Aucun rattachement fiche ↔ compte.** #42 **n'écrit pas** `customer_profiles.user_id` et ne relie
  pas les fiches walk-in aux comptes (écarté par #28 pour anti-oracle ; pré-requis fonctionnel signalé
  par #29). Il segmente les **comptes qui réservent** (`appointments.client_id`) — un axe qui **ne
  dépend pas** du rattachement des fiches (Open Questions §1).
- **Aucune ventilation par coiffeur, prestation ou mode de paiement.** Ce sont d'autres US (perf
  coiffeurs US-6.5 #43, prestations #41). #42 segmente **par client** uniquement.
- **Aucun agrégat inter-salons ni vue admin.** #42 est **salon-scopé** (le gérant voit **son** salon).
  Les KPI plateforme relèvent de l'admin (#37 livré, #44 à venir).
- **Aucune série temporelle / courbe / cohorte multi-périodes.** Une **répartition** ponctuelle sur une
  période, pas d'historique par mois ni de graphe de rétention (post-MVP, PRD §16/§21).
- **Aucun recalcul du CA ni du nombre de visites par client exposé.** #42 ne renvoie **pas** de montant
  ni de compte de visites par client — seulement l'effectif de chaque segment.
- **Aucune écriture / aucun audit §11.4.** Lecture pure (comme #39/#40/#41).
- **Aucune modification de `ROLE_PERMISSIONS`** ni des droits `CLIENT`/`HAIRDRESSER`/`ADMIN`.
- **Aucune statistique côté client / mobile.** #42 est un parcours **gérant** (web) ; `app-mobile/`
  n'est **pas** touché.
- **Aucune colonne dénormalisée / compteur persisté.** #42 **dérive en lecture** ; aucun *trigger*,
  aucun couplage dans `SetAppointmentStatus` (#25). Les colonnes `customer_profiles.last_visit_at` /
  `total_visits` restent à leurs défauts (non écrites, cf. #29).
- **Aucune migration / changement de schéma.** Aucun. #42 est une lecture dérivée d'`appointments`.

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

`docs/adr/` s'arrête à **ADR-0030**. #39/#40/#41 (KPI dashboard) ont plié leurs décisions dans les
README (pas d'ADR). Un ADR pour #42 est **optionnel** (voir Open Questions §8) : #42 ne change pas le
schéma et réutilise les patrons #39/#41 (agrégat salon-scopé « en base », router stats, permission
`STATS_READ_SALON`, réponse counts-only sans PII).

### Backend — patrons à réutiliser tels quels

- **Agrégat salon-scopé « en base » (#39/#41)** : `SqlAppointmentRepository::count_by_status_for_day`
  (`GROUP BY status`) et `::demand_by_service` (`GROUP BY service_id`, `COUNT` + `SUM`), filtre
  `salon_id`, index `(salon_id, appointment_date)`, aucune ligne/PII rapatriée. #42 est le même geste
  avec `GROUP BY client_id` et des agrégats de dates/comptes.
- **Endpoint stats salon-scopé (#40/#41)** : `adapters/inbound/stats.py` — schémas Pydantic
  **explicites** (jamais `orm_mode`/`extra`), montants/compteurs documentés, OpenAPI (`summary`,
  `responses` 200/401/403/422), gardes `require_salon_scope` + `require_permission(STATS_READ_SALON)`,
  DI `get_appointment_repository` **déjà** présente et surchargeable en test. Modèle **direct** de la
  nouvelle route ; la garde explicite `date_to < date_from → 422` de `get_service_demand` est à
  **répliquer**.
- **Use case de lecture pure (#41)** : `application/service_demand.py::SummarizeServiceDemand` (dépend
  d'un **port**, aucune I/O framework, aucun audit, impose `REVENUE_STATUSES`). Modèle direct de
  `SummarizeActiveClients`.
- **Règle métier pure dans le domaine (#40/#41)** : `domain/revenue.py` (`day_bounds`/`week_bounds`/
  `month_bounds`), `domain/service_demand.py::rank_service_demand` (tri déterministe). #42 y ajoute la
  **classification** pure `classify_client_segments`.
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` ; `403` **générique** ; l'invariant deny-by-default est vérifié mécaniquement
  par `unprotected_routes(app)` (`test_security_guards.py`) — **une route ajoutée sans garde fait
  échouer les tests**.
- **Tests** : fakes en mémoire (`tests/conftest.py`) + `TestClient` + `app.dependency_overrides` ;
  **e2e** adossés à un vrai PostgreSQL (`coiflink-e2e-pg`, port 55433 — cf. mémoire projet), patron
  `test_daily_summary_e2e.py` / `test_admin_transactions_e2e.py`. Fichiers de tests unitaires nommés
  par sujet : `test_domain_revenue.py`, `test_revenue_usecase.py`, `test_stats_api.py`.

### Modèle de données pertinent (schéma #3, aucun changement)

```
appointments (id, salon_id, client_id → users.id, status, appointment_date, start_time, end_time, …)
```

- Filtre : `appointments.salon_id = :salon_id AND appointments.status = 'COMPLETED'`.
- Agrégat : `GROUP BY client_id` (jamais émis), avec **par client** :
  - `first_visit = MIN(appointment_date)` — date de la première visite réalisée au salon ;
  - `visits_in_period = COUNT(*) FILTER (WHERE appointment_date BETWEEN :date_from AND :date_to)` ;
  - `visits_before = COUNT(*) FILTER (WHERE appointment_date < :date_from)`.
- Index couvrants **déjà présents** : `ix_appointments_salon_id (salon_id, appointment_date)`,
  `ix_appointments_client_id (client_id)`. **Aucune migration** : #42 n'ajoute aucune colonne,
  contrainte ni index (un index dédié `(salon_id, client_id, appointment_date)` reste une **option**
  d'optimisation, Open Questions §7 — non requise au MVP).
- **Pas de jointure `customer_profiles`** : #42 segmente les comptes qui réservent, pas les fiches.

### Web gérant — patrons à réutiliser (#40/#41)

- `app/(gerant)/gerant/page.tsx` — Server Component + composition root : lit le cookie, appelle les
  gateways **côté serveur**, rend tuiles/panneaux. #42 y ajoute un chargement + un panneau, avec
  **dégradation locale** sur panne (patron `serviceDemand` #41 : `demand.ok ? … : null`).
- `src/application/ports/stats-gateway.ts` + `src/adapters/api/http-stats-gateway.ts` — port + adapter
  HTTP en **union discriminée** (`{ ok: true, … } | { ok: false, reason }`), jeton jamais dans le
  résultat. `serviceDemand(...)` est le modèle direct de `activeClients(...)`.
- `src/adapters/ui/service-demand-panel.tsx` / `revenue-tiles.tsx` — patrons d'affichage (panneau /
  tuiles) à imiter pour le panneau de segmentation (trois compteurs + état vide).

### Contraintes transverses documentées

- **PRD §11.2** : un gérant ne voit que les données de son salon. **§11.3** : collecte minimale, pas de
  PII en logs ni en réponse superflue. **§11.1/ADR-0026** : anti-oracle d'existence de compte. **§8.1**
  : le réalisé ne compte que les RDV `COMPLETED`. **§12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**.
- **Test gate** : `scripts/test-gate.sh` (`pytest` + `npm test` + `flutter test`) ; CI `ci.yml` (ruff,
  pytest, round-trip Alembic contre PostgreSQL 16, build, lint/test/build web).

## Proposed Implementation

**Approche recommandée : backend-first, endpoint agrégé dédié (trois compteurs en une réponse) +
tranche web**, sur le patron #41. On **ne réutilise pas** `list_visits` (#29, chargé par fiche) ni une
liste de RDV : à l'échelle du salon, on **agrège en base** (`GROUP BY client_id`) et on ne rapatrie
que des lignes agrégées **sans `client_id`** — respect de la minimisation (§11.3), de l'anti-oracle
(ADR-0026) et de la garde de coût (§12.1). La règle métier « comment classer » (les trois segments)
vit **dans le domaine** (fonction pure).

### (A) Backend — domaine (classification, pur)

**`domain/client_segments.py`** — **créer** (module frère de `domain/service_demand.py`, pur, sans
I/O) :

```python
@dataclass(frozen=True)
class ClientVisitProfile:
    """Profil de visite **agrégé** d'un client au salon (US-6.4, #42) — sans identité.

    Produit par le dépôt (`GROUP BY client_id`) : il **ne porte pas** le `client_id`
    (anti-oracle §11.1/§11.3) — seulement les grandeurs nécessaires à la
    classification. `first_visit` = date de la première visite `COMPLETED` au salon ;
    `visits_in_period` = nombre de visites dans `[date_from, date_to]` ;
    `visits_before` = nombre de visites strictement avant `date_from`.
    """
    first_visit: datetime.date
    visits_in_period: int
    visits_before: int


@dataclass(frozen=True)
class ClientSegments:
    """Répartition des clients d'un salon sur une période (US-6.4, #42).

    `new` / `recurring` / `inactive` = effectifs des trois segments (mutuellement
    exclusifs). `active = new + recurring` (clients vus sur la période) est un
    dérivé de commodité. `date_from`/`date_to` échoient la période demandée. Ne
    porte **que** des compteurs et des dates (§11.3) : aucune identité de client.
    """
    new: int = 0
    recurring: int = 0
    inactive: int = 0
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None

    @property
    def active(self) -> int:
        return self.new + self.recurring


def classify_client_segments(
    profiles: tuple[ClientVisitProfile, ...],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> ClientSegments:
    """Compte les clients par segment (fonction **pure**, déterministe).

    Pour chaque profil (un client) :
      - **new**      si `visits_in_period > 0` et `visits_before == 0`
                     (première visite dans la période) ;
      - **recurring** si `visits_in_period > 0` et `visits_before > 0`
                     (revient après une visite antérieure) ;
      - **inactive** si `visits_in_period == 0` et `visits_before > 0`
                     (vu avant, silencieux sur la période).
    Un profil sans visite ni dans la période ni avant (uniquement postérieure à
    `date_to`, cas de bord) n'est compté dans **aucun** segment. `first_visit` est
    porté pour la robustesse/les tests mais la classification s'appuie sur les
    compteurs (cohérence : `visits_before == 0 ⟺ first_visit ≥ date_from`).
    """
```

- Exporter `ClientVisitProfile`, `ClientSegments`, `classify_client_segments` dans `__all__`.
- **Pourquoi une classification domaine et une agrégation SQL** : l'agrégat (`GROUP BY client_id`,
  `MIN`/`COUNT FILTER`) est fait en base (minimisation, index), mais la **règle** « qui est
  nouveau/récurrent/inactif » est une décision métier **pure et testable** — miroir #39
  (`build_daily_summary`) et #41 (`rank_service_demand`).
- *(Alternative « tout en SQL » — le dépôt renvoie directement `ClientSegments` (3 entiers) via une
  sous-requête par client + `COUNT` externe par segment — voir Open Questions §5. Recommandation :
  garder la classification **pure** pour la testabilité, quitte à rapatrier un profil agrégé **sans
  PII** par client.)*

### (B) Backend — port (lecture agrégée)

**`application/ports/appointment_repository.py`** — **ajouter** au `Protocol AppointmentRepository`
(foyer naturel : c'est déjà le port des agrégats salon-scopés sur `appointments`, cf.
`count_by_status_for_day`, `demand_by_service`) :

```python
def segment_active_clients(
    self,
    salon_id: uuid.UUID,
    *,
    statuses: tuple[str, ...],
    date_from: datetime.date,
    date_to: datetime.date,
) -> tuple[ClientVisitProfile, ...]:
    ...
```

Docstring : renvoie, **par client** (`GROUP BY client_id`, `client_id` **jamais émis**), un
`ClientVisitProfile` (première visite, visites dans la période, visites avant la période) pour les RDV
du salon dont le `status ∈ statuses`. Isolation §11.2 **imposée en SQL** (`WHERE appointments.salon_id`).
Lecture pure ; anti-oracle par construction (aucune identité de compte n'est renvoyée). Un client sans
aucune visite `COMPLETED` au salon **n'apparaît pas** (il n'a jamais réservé/été réalisé).

*(Alternative : un port `SalonStatsRepository` dédié — voir Open Questions §4. Recommandation : étendre
`AppointmentRepository`, foyer des agrégats sur `appointments`, comme #39/#41.)*

### (C) Backend — cas d'usage

**`application/client_segments.py`** — **créer** (dépend du seul port `AppointmentRepository`) :

```python
class SummarizeActiveClients:
    """Segmentation des clients d'un salon sur une période (lecture — pas d'audit, #42)."""

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> ClientSegments:
        profiles = self._appointments.segment_active_clients(
            salon_id,
            statuses=HISTORY_STATUSES,      # (COMPLETED,) — une « visite » réalisée (#29/§8.1)
            date_from=date_from,
            date_to=date_to,
        )
        return classify_client_segments(
            profiles, date_from=date_from, date_to=date_to
        )
```

- Réutilise `HISTORY_STATUSES` (`domain/visit.py`, égal à `REVENUE_STATUSES`) — **décidé serveur**,
  jamais soumis par l'appelant (« réalisées uniquement » garanti par construction). Lecture pure →
  **aucun** audit (patron `SummarizeServiceDemand`/`SummarizeRevenue`). Ajouter au `__all__`.
- Le cas d'usage reçoit une période **résolue** (deux dates non nulles) : la résolution du défaut
  (mois courant, cf. Open Questions §3) est faite par l'adapter entrant, comme #40 résout `date`
  (`_today()`).

### (D) Backend — adapter outbound (SQL)

**`adapters/outbound/persistence/appointment_repository.py`** — **implémenter**
`segment_active_clients` (miroir `count_by_status_for_day` / `demand_by_service`) :

```python
in_period = case(
    (
        models.Appointment.appointment_date.between(date_from, date_to),
        1,
    ),
    else_=0,
)
before = case(
    (models.Appointment.appointment_date < date_from, 1),
    else_=0,
)
stmt = (
    select(
        func.min(models.Appointment.appointment_date).label("first_visit"),
        func.coalesce(func.sum(in_period), 0).label("visits_in_period"),
        func.coalesce(func.sum(before), 0).label("visits_before"),
    )
    .where(
        models.Appointment.salon_id == salon_id,
        models.Appointment.status.in_(statuses),
    )
    .group_by(models.Appointment.client_id)      # client_id groupé mais **non sélectionné**
)
rows = self._session.execute(stmt).all()
return tuple(
    ClientVisitProfile(
        first_visit=row.first_visit,
        visits_in_period=int(row.visits_in_period),
        visits_before=int(row.visits_before),
    )
    for row in rows
)
```

- Filtrer sur `appointments.salon_id` (défense en profondeur §11.2). **Ne pas** sélectionner
  `client_id` (anti-oracle : l'identité ne quitte jamais la base). Lecture pure : aucun `flush`.
- `COUNT(*) FILTER (WHERE …)` PostgreSQL peut aussi s'écrire via `func.count().filter(...)` (SQLAlchemy
  2.0) plutôt que `SUM(CASE …)` — équivalent, choisir la forme la plus lisible et vérifiée par l'e2e.
- Requête couverte par `ix_appointments_salon_id (salon_id, appointment_date)` (filtre salon + statut,
  bornes de date dans l'agrégat). Le `GROUP BY client_id` sur un seul salon reste borné par la base de
  clients du salon (petit au MVP) — voir Open Questions §7 pour un index dédié optionnel.

### (E) Backend — adapter inbound (route sur le router `stats` existant)

**`adapters/inbound/stats.py`** — **ajouter une route** au router `stats` (#40/#41), **sans** créer de
router :

```python
@router.get(
    "/{salon_id}/active-clients",
    response_model=ClientSegmentsResponse,
    summary="Clients actifs du salon : nouveaux / récurrents / inactifs (US-6.4 §6)",
    responses={200: {...}, 401: {...}, 403: {...}, 422: {...}},
)
def get_active_clients(
    salon_id: uuid.UUID,
    appointment_repo: Annotated[AppointmentRepository, Depends(get_appointment_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[Principal, Depends(require_permission(Permission.STATS_READ_SALON))],
    date_from: Annotated[datetime.date | None, Query(...)] = None,
    date_to: Annotated[datetime.date | None, Query(...)] = None,
) -> ClientSegmentsResponse: ...
```

- **Chemin `/{salon_id}/active-clients`** (segment **distinct**). ⚠️ **Ne pas** utiliser
  `/{salon_id}/customers/…` : ce préfixe appartient au router `customers.py` (permission
  `CUSTOMER_MANAGE`, fiche-scopé) — le réutiliser mélangerait deux surfaces de permission. Le segment
  `active-clients` (ou `client-segments`) est stats-scopé (`STATS_READ_SALON`). Voir Open Questions §5.
- **Gardes** : `require_salon_scope` **+** `require_permission(STATS_READ_SALON)` (**quatrième**
  consommateur). `salon_id` du chemin ; le dépôt refiltre en SQL.
- **Query** `date_from` / `date_to` (`AAAA-MM-JJ`, `Africa/Abidjan`) : **par défaut** le **mois civil
  courant** (résolu serveur via `month_bounds(_today())`, réutilisé de `domain/revenue.py` — symétrie
  #40), une date mal formée → `422` (FastAPI), `date_to < date_from` → `422` (garde explicite,
  répliquer `get_service_demand`). *(Défaut de période : voir Open Questions §3 — « mois courant »
  recommandé car l'US impose « une période donnée » et le dashboard doit afficher une valeur par
  défaut sans saisie.)*
- **DI** : réutiliser `get_appointment_repository` (déjà déclarée dans `stats.py` par #41,
  surchargeable en test).
- **Schémas Pydantic** (explicites, OpenAPI, patron #40/#41) :
  - `ClientSegmentsResponse` : `date_from: date`, `date_to: date`, `new: int`, `recurring: int`,
    `inactive: int`, `active: int` (dérivé, exposé pour éviter un recalcul front).
  - **Aucune PII** (pas de `client_id`/`appointment_id`/nom) : figer la forme par un test qui échoue
    si un champ interdit apparaît (patron #37/#40/#41).
- **`main.py` inchangé** : le router `stats` est **déjà** monté (#40). Actualiser seulement le
  commentaire d'assemblage / d'en-tête du router `stats` pour mentionner le **quatrième** endpoint
  (#42) et le passage de `STATS_READ_SALON` à **quatre** consommateurs.

### (F) Web gérant — panneau « Clients actifs »

1. **Domaine TS** — `src/domain/customers/segments.ts` (ou `src/domain/stats/…`) : type
   `ClientSegments` (`dateFrom`, `dateTo`, `new`, `recurring`, `inactive`, `active`). Helper de
   formatage de la période (`formatPeriodRange`, réutilisable de `src/domain/payments/revenue.ts` s'il
   existe). Le backend reste **l'autorité** des chiffres ; le front **formate** seulement.
2. **Port & gateway** — étendre `src/application/ports/stats-gateway.ts` (type `ActiveClientsResult` en
   union discriminée, `reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable"`) +
   `src/adapters/api/http-stats-gateway.ts` avec `activeClients(salonId, dateFromIso?, dateToIso?)` :
   `GET {API}/salons/{id}/active-clients?date_from&date_to`, jeton du cookie `httpOnly` (jamais exposé
   ni journalisé), compteurs en **entiers**. Mapping `200/401/403/422/503` (miroir `serviceDemand`).
3. **UI** — `src/adapters/ui/active-clients-panel.tsx` : un panneau à **trois compteurs** (Nouveaux /
   Récurrents / Inactifs) avec la période affichée, un total « actifs » (nouveaux + récurrents), et un
   état **vide** (« Aucun client réalisé sur la période »). Style aligné sur `service-demand-panel.tsx`
   / `revenue-tiles.tsx`.
4. **Page** — étendre `app/(gerant)/gerant/page.tsx` : après `serviceDemand`, charger
   `activeClients(salon.id)` (même jeton serveur, période par défaut backend = mois courant) et rendre
   `<ActiveClientsPanel>` **sous** `<ServiceDemandPanel>`. **Dégrader localement** sur panne
   (`segments.ok ? segments.segments : null`) sans casser la page — patron #41.

### (G) Documentation

- `backend/README.md` : ajouter `GET /salons/{salon_id}/active-clients` (route, permission, réponses,
  note « segmentation par compte ayant des RDV `COMPLETED` ; nouveaux/récurrents/inactifs relatifs à la
  période »), signaler le **quatrième** usage de `STATS_READ_SALON`.
- `web-dashboard/README.md` : le dashboard `/gerant` affiche désormais la segmentation des clients
  (US-6.4), sous les prestations les plus demandées (US-6.3).
- `README.md` racine §6 : phrase de statut « clients actifs (#42) livré » ; cohérence du suivi M5.

## Affected Files / Packages / Modules

**Backend (`backend/coiflink_api/`)**
- `domain/client_segments.py` — **créer** (`ClientVisitProfile`, `ClientSegments`,
  `classify_client_segments`, `__all__`).
- `application/ports/appointment_repository.py` — **modifier** (ajouter `segment_active_clients` au
  `Protocol` + docstring : `GROUP BY client_id` non émis, isolation §11.2 en SQL, anti-oracle).
- `application/client_segments.py` — **créer** (`SummarizeActiveClients`).
- `adapters/outbound/persistence/appointment_repository.py` — **modifier** (implémenter
  `segment_active_clients` : `GROUP BY client_id`, `MIN`, `COUNT FILTER` in-period/before).
- `adapters/inbound/stats.py` — **modifier** (schéma `ClientSegmentsResponse`, route `GET /salons/
  {salon_id}/active-clients`, garde `date_to < date_from → 422`, défaut mois courant ; réutilise
  `get_appointment_repository`).
- `main.py` — **modifier** (uniquement le **commentaire** d'assemblage / l'en-tête du router `stats` :
  quatrième endpoint / usage `STATS_READ_SALON`). *Router déjà monté (#40) — pas de `include_router`.*
- `domain/visit.py` (`HISTORY_STATUSES`), `domain/appointment.py` (`REVENUE_STATUSES`),
  `domain/revenue.py` (`month_bounds`), `adapters/inbound/security.py`, `domain/permissions.py` —
  **lire** (réutilisation ; pas de modif).
- `backend/README.md` — **modifier**.

**Backend — tests**
- `tests/test_domain_client_segments.py` — **créer** (classification déterministe des trois segments,
  bornes de période, vide, cas de bord « visite postérieure à la période »).
- `tests/test_client_segments_usecase.py` — **créer** (statut `HISTORY_STATUSES` imposé, bornes passées
  au port, `ClientSegments` assemblé) via un fake `AppointmentRepository`.
- `tests/test_stats_api.py` — **étendre** (ou `tests/test_active_clients_api.py` **créer**) : API
  `200`/`401`/`403`/`422`, absence de PII, isolation, défaut mois courant.
- `tests/conftest.py` — **modifier** (ajouter `segment_active_clients` au `FakeAppointmentRepository`
  s'il existe ; sinon fake local).
- `tests/test_active_clients_e2e.py` — **créer** (agrégat SQL réel : segmentation, isolation
  inter-salons, filtre `COMPLETED`, bornes de période, absence de PII).

**Web (`web-dashboard/`)**
- `src/application/ports/stats-gateway.ts` — **modifier** (`ActiveClientsResult` + `activeClients(...)`).
- `src/adapters/api/http-stats-gateway.ts` — **modifier** (implémentation `activeClients`).
- `src/domain/customers/segments.ts` — **créer** (type + formatage).
- `src/adapters/ui/active-clients-panel.tsx` — **créer** (panneau trois compteurs + état vide).
- `app/(gerant)/gerant/page.tsx` — **modifier** (charger + rendre le panneau sous `<ServiceDemandPanel>`).
- `web-dashboard/README.md` — **modifier**.
- `test/active-clients-panel.test.ts`, `test/active-clients-gateway.test.ts` — **créer** (Vitest).

**Documentation (racine)** : `README.md` ; (option) `docs/adr/0031-…` + `docs/adr/README.md`.

**À lire (sans modifier) pour rester fidèle aux patrons** : `adapters/inbound/stats.py`,
`application/service_demand.py`, `domain/service_demand.py`, `adapters/outbound/persistence/
appointment_repository.py` (`count_by_status_for_day`, `demand_by_service`), `domain/revenue.py`
(`month_bounds`), `domain/visit.py` (`HISTORY_STATUSES`), `web-dashboard/app/(gerant)/gerant/page.tsx`,
`src/adapters/api/http-stats-gateway.ts`, `src/adapters/ui/service-demand-panel.tsx`.

## API / Interface Changes

**Nouvelle route HTTP (backend), protégée** ; aucune route existante modifiée ; aucun chemin ajouté à
`PUBLIC_ROUTE_PATHS`.

`GET /salons/{salon_id}/active-clients`
- **Auth** : `Principal` requis (deny-by-default). Permission **`STATS_READ_SALON`** (`MANAGER`) **+**
  portée salon (`require_salon_scope`).
- **Query** : `date_from`, `date_to` *optionnels* (`AAAA-MM-JJ`, `Africa/Abidjan`). Absents = **mois
  civil courant** (résolu serveur). `date_to < date_from` → `422` ; date mal formée → `422`.
- **200** — corps :
  ```json
  {
    "date_from": "2026-08-01",
    "date_to": "2026-08-31",
    "new": 12,
    "recurring": 27,
    "inactive": 8,
    "active": 39
  }
  ```
  (`new`/`recurring`/`inactive`/`active` = entiers ≥ 0 ; `active = new + recurring` ; tous à `0` si
  aucun RDV `COMPLETED` — état normal, pas d'erreur.)
- **401** jeton absent/invalide · **403** rôle insuffisant **ou** salon hors périmètre (générique,
  aucun oracle) · **422** `date_from`/`date_to` mal formée ou incohérente.

**OpenAPI** : documenté via schéma Pydantic + `responses`. **Web** : nouveau contenu de `/gerant` (pas
d'URL nouvelle) ; aucun Route Handler BFF ajouté si le fetch serveur direct est retenu (patron
#40/#41). Aucune autre surface (CLI, autres endpoints, variable d'environnement) modifiée.

## Data Model / Protocol Changes

**None.** Aucune table, colonne, contrainte ou migration Alembic. #42 est une **lecture dérivée**
d'`appointments` : `GROUP BY client_id` avec `MIN(appointment_date)` et deux `COUNT FILTER`. Les index
`ix_appointments_salon_id (salon_id, appointment_date)` et `ix_appointments_client_id (client_id)`
couvrent la requête (un index composite `(salon_id, client_id, appointment_date)` reste une
optimisation **optionnelle**, non introduite ici — Open Questions §7). `HISTORY_STATUSES` /
`AppointmentStatus` / `ROLE_PERMISSIONS` réutilisés tels quels (aucune nouvelle valeur d'énum, aucune
nouvelle permission). Aucune colonne dénormalisée n'est écrite. La réponse ne porte que des compteurs
(entiers) et des dates — jamais de PII.

## Security & Privacy Considerations

- **Anti-oracle par construction (§11.1/§11.3, ADR-0026).** #42 **n'émet que des compteurs agrégés** :
  le `client_id` est **groupé mais jamais sélectionné** en SQL et ne remonte ni au domaine, ni à la
  réponse, ni aux logs. La réponse ne révèle **ni** l'identité, **ni** l'existence, **ni** le nombre de
  visites d'un compte donné — seulement des effectifs. C'est un anti-oracle **plus fort** que #29 (qui
  exposait des données nominatives fiche-scopées) : aucune donnée nominative n'est produite.
- **Isolation §11.2 (multi-tenant).** Route salon-scopée (`require_salon_scope`) **+** re-filtrage
  `WHERE appointments.salon_id = :salon_id` **inconditionnel** en SQL (défense en profondeur). Un salon
  hors périmètre est un **403 générique** indiscernable (aucun oracle). Le dépôt ne segmente **jamais**
  les clients d'un autre salon ; un même compte est segmenté **par salon** (relation cloisonnée : un
  client peut être « nouveau » ici et « récurrent » ailleurs).
- **Deny-by-default (#12 / ADR-0015).** La route porte une garde de `Principal`
  (`require_permission(STATS_READ_SALON)`) ; **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` (donnée
  d'exploitation salon) ; l'invariant testé `unprotected_routes(app) == []` reste vert.
- **RBAC inchangé.** `STATS_READ_SALON` est **déjà** au `MANAGER` (et seulement lui). **Ne pas**
  modifier `ROLE_PERMISSIONS`. `CLIENT`/`HAIRDRESSER`/`ADMIN` → 403.
- **Minimisation des données (§11.3).** La réponse ne contient **que** `date_from`, `date_to`, `new`,
  `recurring`, `inactive`, `active` : **aucun** `client_id`, nom, téléphone, `appointment_id`, ni ligne
  de RDV. L'agrégat est calculé **en base** (`GROUP BY`), pas en rapatriant les lignes ni les identités.
  Le schéma Pydantic est **explicite** et **figé par un test** qui échoue si un champ interdit apparaît
  (patron #37/#40/#41).
- **Aucune PII ni secret dans les logs.** Ni `logger`/`print` ni messages `4xx` ne portent d'identité
  client ; les compteurs (exposés au gérant légitime) ne sont **jamais** journalisés. Le jeton reste
  dans le cookie `httpOnly` côté web (invariant #14), jamais exposé ni passé en query.
- **Lecture pure — aucun effet de bord.** Aucune écriture, **aucune** entrée d'audit §11.4 (patron des
  lectures #39/#40/#41) ; la consultation d'un KPI n'est pas journalisée.
- **Coût / latence (§12.1).** Un `GROUP BY client_id` filtré par salon + statut, borné par la base de
  clients du **salon** (petit au MVP). Les bornes `appointment_date` de l'agrégat exploitent
  `ix_appointments_salon_id`. Sur un très gros salon, un index composite dédié reste une option (Open
  Questions §7) — non requis au MVP.

Le dépôt ne documente **aucune** contrainte supplémentaire (résidence, chiffrement applicatif) au-delà
de celles ci-dessus pour cette lecture.

## Testing Plan

**Backend — domaine (pur, sans I/O) — `tests/test_domain_client_segments.py`**
- `classify_client_segments` :
  - **new** : `visits_in_period > 0` et `visits_before == 0` → compté nouveau (première visite dans la
    période) ;
  - **recurring** : `visits_in_period > 0` et `visits_before > 0` → compté récurrent ;
  - **inactive** : `visits_in_period == 0` et `visits_before > 0` → compté inactif ;
  - **cas de bord** : profil sans visite ni dans ni avant la période (visite postérieure à `date_to`)
    → compté dans **aucun** segment ; profils multiples → effectifs corrects ; `active = new +
    recurring` ; entrée vide → tous les compteurs à `0`.
  - **mutuelle exclusivité** : `new + recurring + inactive ≤ nombre de profils` (les profils « futurs
    uniquement » ne comptent pas).

**Backend — application — `tests/test_client_segments_usecase.py` (fake `AppointmentRepository`)**
- `SummarizeActiveClients.execute` : passe **`HISTORY_STATUSES` (`COMPLETED`)** et les **bornes**
  reçues au port `segment_active_clients` (vérifier les arguments exacts) ; assemble un
  `ClientSegments` cohérent (période échoée) ; **aucune** écriture/audit déclenchée. Cas « aucun
  profil » → tous compteurs à `0`.

**Backend — inbound (FastAPI `TestClient` + `app.dependency_overrides`) — `tests/test_stats_api.py`
(ou `test_active_clients_api.py`)**
- `200` : segmentation correcte pour un salon peuplé (clients nouveaux, récurrents, inactifs) ; réponse
  = compteurs + bornes ; `active = new + recurring`.
- **Défaut de période** : sans `date_from`/`date_to` → le backend applique le **mois civil courant**
  (`month_bounds(_today())`) ; avec bornes → segmentation relative à la fenêtre fournie.
- **Filtre de statut** : un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne compte **pas** comme
  visite (« annulés exclus », §8.1) — un client dont **tous** les RDV sont non-`COMPLETED` n'apparaît
  dans aucun segment.
- **Bornes** : `date_to < date_from` → `422` ; date mal formée → `422`.
- `403` : `CLIENT`/`HAIRDRESSER`/`ADMIN` (sans `STATS_READ_SALON`) ; gérant d'**un autre salon** (hors
  portée) → 403 générique.
- `401` : sans jeton.
- **Isolation** : un client vu dans un **autre salon** ne pèse pas ici ; un client vu **dans les deux**
  est segmenté indépendamment par salon.
- **Non-PII** : la réponse ne contient **aucune** clé autre que `date_from`/`date_to`/`new`/`recurring`/
  `inactive`/`active` — test qui **échoue** si un champ interdit (`client_id`, nom…) apparaît.
- **`unprotected_routes(app) == []`** couvre automatiquement la nouvelle route ; vérifier qu'aucun
  chemin `active-clients` n'entre dans `PUBLIC_ROUTE_PATHS`, et **la non-collision** avec les routes
  `customers.py` (`/{salon_id}/customers/…`) et `services.py`.

**Backend — e2e PostgreSQL réel — `tests/test_active_clients_e2e.py`** *(patron
`test_daily_summary_e2e.py` / `test_admin_transactions_e2e.py`, sur `coiflink-e2e-pg` port 55433)* :
couvrir le chemin SQL réel du `GROUP BY client_id` (`MIN(appointment_date)`, `COUNT FILTER`
in-period/before), l'usage des index, le filtre `COMPLETED`, les bornes `appointment_date`, l'**isolation
inter-salons** (un client d'un autre salon exclu) et l'absence de PII. Scénarios : (a) un compte avec
une seule visite **dans** la période → **nouveau** ; (b) un compte avec une visite **avant** + une
visite **dans** la période → **récurrent** ; (c) un compte avec des visites **avant** seulement →
**inactif** ; (d) un compte du **même** utilisateur avec une visite `COMPLETED` dans un **autre** salon
→ non compté ici. (Comme #29, l'insertion de RDV `COMPLETED` liés à un compte peut nécessiter une
écriture directe en base — le rattachement fiche/compte n'ayant pas d'endpoint — cf. Open Questions §1.)

**Web (`web-dashboard/test/`, Vitest)**
- Rendu `/gerant` : le panneau « Clients actifs » s'affiche **sous** le panneau des prestations (#41),
  avec les trois compteurs et la période ; cas « 0 activité » → état vide ; cas « erreur backend » →
  dégradation locale (`null`), sans casser la page (patron #41).
- Gateway `activeClients` : construit la bonne URL (`date_from`/`date_to` optionnels), passe le jeton
  en en-tête **serveur** (jamais exposé), mappe la réponse (compteurs entiers), gère proprement
  `401/403/422/503`.
- Formatage : cohérence de l'affichage de la période et des compteurs avec les panneaux existants.

**Documentation / non-régression** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test) ;
`ruff check` propre ; `npm run lint && npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`backend/README.md`** — sous-section « Statistiques salon — clients actifs (US-6.4, #42) » : route,
  permission (**quatrième** usage de `STATS_READ_SALON`), réponses, définitions des trois segments
  (relatives à la période), note « segmentation par compte ayant des RDV `COMPLETED` — les fiches
  walk-in sans compte ne pèsent pas, cf. #29 » ; exemple `curl`.
- **`web-dashboard/README.md`** — mention du panneau « Clients actifs » sur `/gerant`, sous les
  prestations les plus demandées (US-6.3), et de l'extension du `http-stats-gateway`.
- **`README.md` racine** — §6 : phrase de statut « clients actifs (#42) livré » dans le style des
  paragraphes M5 existants (Épic 6), cohérence du tableau des jalons.
- **OpenAPI** — `summary`/`responses`/docstrings documentent la nouvelle API (visible sur `/docs`).
- **(Option) ADR** — *a priori* **aucun ADR nouveau** (route additive, patrons #39/#41 réutilisés). Si
  l'équipe veut acter la **définition des segments** (relatifs à la période vs seuil de récence) ou le
  **choix de segmenter les comptes plutôt que les fiches**, un court ADR-0031 pourra la documenter — à
  confirmer (Open Questions §1/§2/§8).
- **BACKLOG.md** — marquer #42 livré le cas échéant (géré hors phase de code par le pipeline).

## Risks and Open Questions

1. **[Décision structurante] Segmenter les *comptes qui réservent* (`appointments.client_id`) plutôt
   que les *fiches* (`customer_profiles`).** Recommandation : **segmenter les comptes** — c'est la
   **seule** source qui porte des visites réelles (`appointments`). Segmenter les fiches serait
   quasiment vide : toutes les fiches créées par le gérant sont **walk-in** (`user_id = NULL`, #28) et
   ne se relient à aucun RDV — le point dur hérité de #29 (*Open Questions §1* de #29). **Conséquence à
   assumer et documenter** : (a) un **client walk-in fiché sans compte** n'apparaît dans aucun segment
   (il n'a pas de RDV `COMPLETED` lié) ; (b) « client » = **compte utilisateur** ayant réservé et été
   réalisé, pas « fiche ». C'est cohérent avec le fait que #42 est un **KPI agrégé** (counts-only), pas
   une exploitation nominative. Le **rattachement fiche ↔ compte** (auto ou explicite), déjà signalé
   comme déblocage par #29, améliorerait la couverture mais **n'est pas** un pré-requis de #42.
   **Confirmer.**
2. **Définition de « récurrent » (et des trois segments).** Recommandation : **relative à la période** —
   nouveau = première visite dans la période ; récurrent = actif dans la période **et** vu avant ;
   inactif = vu avant, silencieux sur la période. Ce découpage colle à « segmentation **sur une période
   donnée** » et donne trois segments **mutuellement exclusifs**. Alternative : « récurrent = ≥ 2
   visites au total (toutes périodes) » et « nouveau = 1 seule visite » — mais alors « nouveau » et
   « inactif » se recouvrent mal avec la période. **À confirmer** (la règle exacte est la vraie
   substance de l'US ; à acter en README ou ADR §8).
3. **Défaut de période.** L'US impose « une période donnée » mais l'AC ne fixe pas de défaut.
   Recommandation : **`date_from`/`date_to` optionnels, défaut = mois civil courant** (`month_bounds`,
   symétrie #40) — le dashboard affiche une valeur immédiate sans saisie, et un gérant peut fournir une
   fenêtre explicite. Alternatives : plage **obligatoire** (422 si absente) ; défaut « 30 derniers
   jours glissants ». **À confirmer.**
4. **Foyer du port : `AppointmentRepository` (recommandé) vs port stats dédié.** Recommandation :
   **étendre `AppointmentRepository`** (déjà foyer des agrégats salon-scopés sur `appointments`, cf.
   `count_by_status_for_day`/`demand_by_service`). Alternative : un `SalonStatsRepository` dédié (plus
   « propre » pour un futur module stats, mais plus de surface et un nouveau câblage DI). **À confirmer.**
5. **[Vérification technique] Nom du segment de route & non-collision.** Recommandation :
   **`/{salon_id}/active-clients`** (ou `/{salon_id}/client-segments`) sur le router `stats` — **pas**
   `/{salon_id}/customers/…` (préfixe du router `customers.py`, permission `CUSTOMER_MANAGE`,
   fiche-scopé) pour ne pas mêler deux surfaces de permission. Vérifier par un test de résolution que la
   requête atteint bien la route `stats` (`STATS_READ_SALON`) et non une route `customers`/`services`.
   **À confirmer** (le littéral exact est une décision d'API publique).
6. **Classification pure (domaine) vs tout-en-SQL.** Recommandation : **classification pure**
   (`classify_client_segments`) sur des profils agrégés **sans `client_id`** — testable sans base,
   patron #39/#41. Alternative : le dépôt renvoie directement `ClientSegments` (3 entiers) via une
   sous-requête par client + `COUNT` externe par segment (rapatriement minimal, mais règle métier
   enfouie en SQL, moins testable unitairement). **À confirmer** ; la recommandation privilégie la
   testabilité, le surcoût de rapatrier un profil **anonyme** par client restant borné (base clients
   d'un salon, §12.1).
7. **Index de couverture.** Le `GROUP BY client_id` filtré `salon_id` + statut n'a pas d'index composite
   parfait (`ix_appointments_salon_id` couvre `(salon_id, appointment_date)`, `ix_appointments_client_id`
   couvre `(client_id)`). Recommandation : **aucun nouvel index au MVP** (volume salon faible, §12.1
   tenu). Un index `(salon_id, client_id, appointment_date)` reste une **optimisation future** si un
   salon à très gros volume le justifie — décision différée (mesure d'abord). **À confirmer.**
8. **Un ADR est-il nécessaire ?** #39/#40/#41 ont plié leurs décisions dans les README. Recommandation :
   ADR **optionnel** (README suffit) ; un ADR-0031 ne se justifie que pour acter la **définition des
   segments** (§2) ou le **choix comptes-vs-fiches** (§1). **À confirmer.**
9. **Absence de drill-down nominatif.** #42 ne renvoie **que** des compteurs (anti-oracle, §11.3). Si le
   produit veut, plus tard, la **liste** des clients inactifs (pour une relance), ce serait une
   **nouvelle** US fiche-scopée (permission `CUSTOMER_MANAGE`, pas `STATS_READ_SALON`) — à ne pas
   confondre avec #42. À **assumer explicitement** dans le README.
10. **Cohérence temporelle avec le fuseau.** Les bornes de période sont des **jours civils
    `Africa/Abidjan`** (UTC+0, convention #21) comparés à `appointments.appointment_date` (déjà une
    `date`, sans fuseau) — pas de conversion UTC nécessaire (contrairement au CA #40 qui compare des
    `datetime`). À **vérifier** que la comparaison reste en `date` de bout en bout (pas de dérive de
    fuseau). **À confirmer** dans les tests.

## Implementation Checklist

**Backend**
1. **Lire** `adapters/inbound/stats.py`, `application/service_demand.py`, `domain/service_demand.py`,
   `adapters/outbound/persistence/appointment_repository.py` (`count_by_status_for_day`,
   `demand_by_service`), `domain/revenue.py` (`month_bounds`), `domain/visit.py` (`HISTORY_STATUSES`) —
   s'imprégner des patrons #39/#40/#41.
2. **Trancher** les Open Questions 1–7 (comptes vs fiches, définition des segments, défaut de période,
   foyer du port, nom de route, classification pure vs SQL, index) et consigner la décision (README, ou
   ADR-0031 selon §8).
3. **Domaine** : créer `domain/client_segments.py` (`ClientVisitProfile`, `ClientSegments`,
   `classify_client_segments`) ; `__all__`. Écrire `tests/test_domain_client_segments.py` **avant** le
   cas d'usage.
4. **Port** : ajouter `segment_active_clients(salon_id, *, statuses, date_from, date_to) ->
   tuple[ClientVisitProfile, ...]` au `Protocol AppointmentRepository` (docstring : `GROUP BY client_id`
   **non émis**, isolation §11.2 en SQL, anti-oracle, lecture pure).
5. **Cas d'usage** : créer `application/client_segments.py::SummarizeActiveClients` (impose
   `HISTORY_STATUSES`, passe les bornes, appelle `classify_client_segments` ; aucune écriture/audit) ;
   `__all__`. Écrire `tests/test_client_segments_usecase.py` via un fake (compléter `conftest.py`).
6. **Adapter outbound** : implémenter `segment_active_clients` dans `SqlAppointmentRepository`
   (`select` `MIN(appointment_date)` + `COUNT FILTER` in-period/before + `where salon_id, status` +
   `group_by client_id` **sans** sélectionner `client_id`).
7. **Adapter inbound** : ajouter à `stats.py` le schéma `ClientSegmentsResponse` (explicite, aucune
   PII) et la route `GET /salons/{salon_id}/active-clients` (gardes `require_salon_scope` +
   `require_permission(STATS_READ_SALON)`, `date_from`/`date_to` optionnels + défaut mois courant +
   garde `date_to < date_from → 422`, OpenAPI documenté) ; réutiliser `get_appointment_repository`.
   **Ne pas** toucher `PUBLIC_ROUTE_PATHS` ; actualiser le **commentaire** d'assemblage / l'en-tête du
   router `stats` dans `main.py` (quatrième endpoint / usage `STATS_READ_SALON`).
8. **Tests API & e2e** : `tests/test_stats_api.py` (ou `test_active_clients_api.py`) —
   200/401/403/422, défaut mois courant, isolation, filtre `COMPLETED`, bornes, **non-PII**,
   non-collision de routage, `unprotected_routes == []` ; `tests/test_active_clients_e2e.py` (agrégat
   SQL réel, index, isolation, scénarios nouveau/récurrent/inactif). Exécuter `pytest` (+ `DATABASE_URL`
   pour l'e2e) et `ruff check`.
9. **Documentation backend** : `backend/README.md` (route + 4ᵉ usage `STATS_READ_SALON` + définitions
   des segments + note comptes vs fiches walk-in).

**Web**
10. **Domaine & accès** : `src/domain/customers/segments.ts` (type + formatage de période) (+ test) ;
    étendre `stats-gateway.ts` (`ActiveClientsResult` + `activeClients`) et `http-stats-gateway.ts`
    (implémentation, jeton serveur, compteurs entiers) (+ test).
11. **UI & page** : `src/adapters/ui/active-clients-panel.tsx` (trois compteurs + période + état vide) ;
    brancher `activeClients(salon.id)` dans `app/(gerant)/gerant/page.tsx` et rendre le panneau **sous**
    `<ServiceDemandPanel>` (dégradation locale sur panne, patron #41).
12. **Tests Vitest** (panneau + gateway + formatage) ; `web-dashboard/README.md`.

**Documentation & vérification finale**
13. Mettre à jour `README.md` racine (avancement Épic 6 / US-6.4). (Option) ADR-0031 + entrée
    `docs/adr/README.md` selon Open Questions §8.
14. `scripts/test-gate.sh` au vert (pytest + npm test + flutter test), `ruff check`, `npm run lint &&
    npm run build` ; relire la PR : **aucune PII/secret** (`client_id`, nom, téléphone, jeton) en logs
    ou messages d'erreur, **aucune signature IA** introduite.
