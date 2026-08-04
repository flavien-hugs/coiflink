# KPI globaux de la plateforme (admin) (US-6.6, #44)

> Épic 6 (Tableau de bord) · Priorité **Must** · Effort **M** · PRD §6 (US-6.6), §7.3
> (Interface admin CoifLink — Dashboard admin), §13 (KPI de succès), §11.2 / §11.3 / §12.1.
> **Dépend de #37** (supervision agrégée des transactions admin — router `/admin`,
> permission `STATS_READ_PLATFORM`, revenu net via `cash_journal`, helpers de fuseau
> `domain/time_window.py`). S'appuie aussi sur le RBAC #12 (matrice fermée) et sur le
> socle KPI salon de l'Épic 6 (#39–#43, patron des lectures statistiques en base).

## Problem Statement

L'**Admin CoifLink** (super-administrateur plateforme, PRD §2/§4.1) doit disposer d'un
**tableau de bord de pilotage global** exposant, en un coup d'œil, l'état agrégé de
**toute** la plateforme : combien de salons sont inscrits, combien de rendez-vous ont
été pris, quel revenu transite par CoifLink — indicateurs qui n'appartiennent à aucun
salon en particulier (PRD §7.3 « Dashboard admin », §13.1 Adoption / §13.3 Performance
financière).

Aujourd'hui, **une seule** lecture plateforme existe : `GET /admin/transactions/summary`
(#37), qui renvoie une liste **par salon** d'agrégats de transactions. Il n'existe
**aucune** vue de **KPI globaux consolidés** (compteurs et totaux à l'échelle de la
plateforme entière). Toutes les autres lectures statistiques livrées (Épic 6, #39–#43)
sont **salon-scopées** (`STATS_READ_SALON`, montées sous `/salons/{salon_id}/…`) : elles
sont, par construction, inaccessibles à l'admin (qui ne détient pas `STATS_READ_SALON` et
n'a pas de salon dans sa portée).

Le critère d'acceptation du backlog est :

> **Dashboard admin avec KPI globaux agrégés.** KPI listés : salons inscrits,
> abonnements, rendez-vous, revenus plateforme.

**Écart notable — les « abonnements ».** Le PRD décrit un modèle SaaS par abonnement
(§15.1) et une gestion d'abonnements côté admin (§7.3 « Abonnements » : plans tarifaires,
salons abonnés, échéances, statut paiement, historique facturation ; §7.3 « Dashboard
admin » : « Revenus d'abonnement »). **Or aucun modèle de données d'abonnement /
facturation n'existe dans le backend** (aucune table, aucun domaine, aucun enum ; le terme
n'apparaît que dans le PRD, le backlog et des specs — jamais dans `coiflink_api`). Le KPI
« abonnements » **ne peut donc pas être calculé à partir de données réelles**, et la mise
en place d'un système d'abonnement/facturation est un **épic distinct** (hors backlog M5),
pas le périmètre d'une US de tableau de bord (Effort M). C'est la **décision produit
centrale** à trancher (voir *Risks and Open Questions* #1) — le présent plan **n'introduit
pas** de modèle d'abonnement.

## Goals

- Exposer une **lecture plateforme consolidée** réservée à l'`ADMIN`, renvoyant un
  **instantané unique** (non paginé) de **KPI globaux agrégés** sur toute la plateforme :
  - **Salons inscrits** — nombre total de salons (`salons_total`) et, recommandé,
    nombre de salons **actifs** (`salons_active`, PRD §7.3 « Salons actifs »).
  - **Rendez-vous** — nombre total de RDV (`appointments_total`) et nombre de RDV du
    **mois civil courant** (`appointments_this_month`, PRD §7.3 « Rendez-vous mensuels »).
  - **Revenus plateforme** — **montant net** encaissé sur toute la plateforme, cumulé
    (`revenue_total`) et sur le **mois civil courant** (`revenue_this_month`), dérivé de
    la **même source de vérité** que #37/#40 (somme signée des lignes `cash_journal`).
  - **Clients inscrits** *(recommandé, PRD §7.3/§13.1)* — nombre de comptes `CLIENT`
    (`clients_total`).
- Gérer la lecture par la **permission `STATS_READ_PLATFORM`** (déjà réservée à l'`ADMIN`,
  **deuxième consommateur** après #37) — **sans modifier** la matrice `ROLE_PERMISSIONS`.
- **Réutiliser** le router `/admin` (#37), les helpers de fuseau `domain/time_window.py`
  et les bornes de mois `domain/revenue.py::month_bounds` (#40) — **sans dupliquer**.
- Calculer **tout en base** (COUNT / SUM, jamais en mémoire — garde de coût §12.1),
  **sans écriture, sans migration, sans audit** (lecture pure, parité #37/#39–#43).
- Garantir l'**absence totale de PII** : la réponse ne porte **que des scalaires globaux**
  (compteurs, montants, dates) — **aucune** identité d'entité (ni salon, ni client, ni
  paiement) n'est émise (§11.3).
- Préserver le **deny-by-default** (#12/ADR-0015) : la route porte une garde de
  `Principal`, **jamais** ajoutée à `PUBLIC_ROUTE_PATHS`.
- **Trancher explicitement** le sort du KPI « abonnements » (Open Q. #1) sans inventer de
  comportement de facturation inexistant.

## Non-Goals

- **Aucun système d'abonnement / facturation.** Ce plan **n'introduit ni table, ni
  domaine, ni endpoint** de gestion d'abonnements (plans tarifaires, échéances, statut
  paiement, historique facturation — PRD §7.3/§15.1). Ces surfaces sont un **épic
  distinct**, hors périmètre de #44.
- **Aucun détail par entité / drill-down.** Ce n'est **pas** une liste de salons ni un
  agrégat par salon (c'est déjà `GET /admin/transactions/summary`, #37). #44 renvoie des
  **scalaires globaux** uniquement.
- **Aucune série temporelle / graphique / historisation.** Pas de courbes, pas de
  comparaison période-sur-période, pas de snapshots persistés. Instantané calculé à la
  demande.
- **Aucun KPI de satisfaction / support** (NPS, tickets support, temps de résolution —
  PRD §7.3 « Support », §13.4) : aucune donnée sous-jacente n'existe (pas de module
  support). Hors périmètre.
- **Aucune écriture, aucun audit §11.4** (les consultations ne sont pas journalisées,
  parité #34–#43), **aucune** migration Alembic.
- **Aucune modification de la matrice `ROLE_PERMISSIONS`** ni des droits d'un autre rôle.

## Relevant Repository Context

**Stack (figée par ADR — voir README §4).** Backend **Python FastAPI**, **architecture
hexagonale** (ADR-0008) : `domain/` (pur) → `application/` (cas d'usage + `ports/`) →
`adapters/inbound|outbound/`. Persistance **PostgreSQL 16 / SQLAlchemy 2.0 + Alembic**
(ADR-0004/0009). RBAC **deny-by-default** (ADR-0015, #12). Devise MVP **XOF**
(`DEFAULT_CURRENCY`). Fuseau des jours civils **Africa/Abidjan (UTC+0)** (convention #21).

**Le socle #37 à étendre (dépendance directe).** #37 a introduit **exactement** le patron
que #44 réutilise :
- `adapters/inbound/admin.py` — router `APIRouter(prefix="/admin", tags=["admin"])`,
  route `GET /admin/transactions/summary` gardée par
  `require_permission(Permission.STATS_READ_PLATFORM)` **seule** (pas de
  `require_salon_scope`). **#44 ajoute une route à ce même router.**
- `domain/platform_transactions.py` — VO de lecture immuable + validation de filtre de
  dates neutre. Patron du nouveau `domain/platform_kpis.py`.
- `application/platform_transactions.py` — use case pur `SummarizeSalonTransactions`
  (dépend du seul port). Patron du nouveau `ComputePlatformKpis`.
- `application/ports/platform_transaction_repository.py` — **port dédié** (les ports
  `PaymentRepository`/`CashJournalRepository` sont inconditionnellement salon-scopés ;
  un agrégat inter-salons ne leur appartient pas). Idem pour #44 → port dédié.
- `adapters/outbound/persistence/platform_transaction_repository.py` — implémentation
  SQLAlchemy : agrégation `cash_journal` (net signé), lecture pure, bornes en SQL.
- `domain/time_window.py` — `SALON_TIMEZONE`, `day_start_utc`, `day_end_utc`
  (jour civil `Africa/Abidjan` → bornes UTC inclusives). **À réutiliser** pour la fenêtre
  mensuelle du revenu.

**Décision ADR-0029 (#37) à suivre** (`docs/adr/0029-supervision-agregee-transactions-admin.md`) :
lecture plateforme gardée par `STATS_READ_PLATFORM`, **net via `cash_journal`** (un
paiement corrigé fait baisser le net), non-PII figée par test, port dédié, garde de coût
en SQL, lecture pure sans audit, mono-devise XOF assumée.

**Socle KPI salon (Épic 6, #39–#43) — patron des lectures statistiques.**
- `domain/revenue.py` (#40) — `month_bounds(reference)` (1er → dernier jour du mois civil
  via `calendar.monthrange`), `week_bounds`, `day_bounds`. **`month_bounds` est réutilisé**
  pour la fenêtre mensuelle de #44.
- `application/revenue.py` (#40) — patron « bornes de jour civil → bornes UTC (via
  `time_window`) → `SUM` net du journal ». Le revenu plateforme de #44 en est la variante
  **sans filtre `salon_id`** (somme sur tous les salons).
- `adapters/inbound/stats.py` — routes salon-scopées `STATS_READ_SALON` (#39–#43), non
  réutilisables par l'admin (portée salon). Référence de style (schémas Pydantic non-PII).

**Modèle de données (existant, `adapters/outbound/persistence/models.py`).** Aucune
migration nécessaire — tout se calcule sur des tables et index existants :
- `users` : `id`, `role` (`CLIENT`/`HAIRDRESSER`/`MANAGER`/`ADMIN`), `status`
  (`ACTIVE`/`INACTIVE`/`SUSPENDED`), `created_at`. → `clients_total = COUNT(*) WHERE
  role = 'CLIENT'`.
- `salons` : `id`, `status` (`ACTIVE`/`INACTIVE`/`SUSPENDED`), `created_at`. Index
  `ix_salons_status`. → `salons_total = COUNT(*)`, `salons_active = COUNT(*) WHERE
  status = 'ACTIVE'`.
- `appointments` : `id`, `salon_id`, `status` (`PENDING`/`CONFIRMED`/`CANCELLED`/
  `COMPLETED`/`NO_SHOW`), **`appointment_date` (`Date`, jour civil `Africa/Abidjan`)**,
  `created_at`. Index `ix_appointments_salon_id (salon_id, appointment_date)`.
  → `appointments_total = COUNT(*)`, `appointments_this_month = COUNT(*) WHERE
  appointment_date BETWEEN <month_from> AND <month_to>`. **`appointment_date` est déjà un
  jour civil** → comparaison directe aux bornes de `month_bounds`, **sans** conversion de
  fuseau (contrairement au revenu).
- `cash_journal` : `salon_id`, `operation_type` (`PAYMENT`/`ADJUSTMENT`/…), `amount
  NUMERIC(12,2)` **signé**, `created_at` (timezone-aware). Index `ix_cash_journal_salon_id
  (salon_id, created_at)`. → `revenue_total = SUM(amount)` (net signé) sur **tous** les
  salons ; `revenue_this_month = SUM(amount) WHERE created_at BETWEEN <utc_from> AND
  <utc_to>` (bornes de mois converties en UTC via `time_window`).

**Enums** (`domain/enums.py`) : `Role.CLIENT/HAIRDRESSER/MANAGER/ADMIN`,
`SalonStatus.ACTIVE/INACTIVE/SUSPENDED`, `AppointmentStatus.*`,
`CashOperationType.PAYMENT/ADJUSTMENT/…`.

**Permissions (`domain/permissions.py`, matrice fermée §4.1).** L'`ADMIN` détient
`SALON_READ_ANY`, `SALON_SET_STATUS`, `USER_MANAGE`, **`STATS_READ_PLATFORM`**. `#37` en
est le premier consommateur ; **#44 en est le deuxième**. Aucune modification de la
matrice.

**Assemblage.** `main.py` : `FastAPI(dependencies=[Depends(require_authenticated)])`
(deny-by-default global) + `include_router(admin_router)` (déjà présent depuis #37 —
**rien à ajouter** côté assemblage puisqu'on étend le router existant). L'invariant
`unprotected_routes(app) == []` est **testé** : la nouvelle route, gardée par
`require_permission`, le satisfait automatiquement (pas d'entrée dans
`PUBLIC_ROUTE_PATHS`).

**Web admin (`web-dashboard`).** La zone `/admin` **n'existe pas encore** : seules
`app/(gerant)/…` et `app/(coiffeur)/…` sont livrées (plus `app/api/…` BFF et `app/login`).
#37 a été livré **backend-first** (aucune UI admin). Voir *Risks* #4 pour l'arbitrage sur
la tranche web de #44.

**Décisions encore ouvertes** (voir *Risks*) : (1) sort du KPI « abonnements » (pas de
modèle) ; (2) périmètre exact des KPIs (les 4 du backlog vs +clients/actifs) ; (3)
inclusion des RDV `CANCELLED` dans `appointments_total` ; (4) tranche web `/admin`
(existence de la zone) ; (5) granularité période (cumul seul vs cumul + mois courant) ;
(6) nom de la route.

## Proposed Implementation

Ajouter une **tranche verticale de lecture plateforme** hexagonale, gardée par
`STATS_READ_PLATFORM`, qui **calcule en base** un **instantané unique** de KPI globaux et
l'expose comme **nouvelle route du router `/admin` existant** (#37). Aucune écriture,
aucune migration, aucune PII, aucun audit.

### 1. Domaine — `domain/platform_kpis.py` (nouveau, pur)

- **VO `PlatformKpiSnapshot`** (`@dataclass(frozen=True)`), instantané global immuable :
  - `salons_total: int`
  - `salons_active: int` *(recommandé)*
  - `clients_total: int` *(recommandé)*
  - `appointments_total: int`
  - `appointments_this_month: int`
  - `revenue_total: decimal.Decimal` *(net signé, `NUMERIC(12,2)`, jamais un flottant)*
  - `revenue_this_month: decimal.Decimal`
  - `currency: str = DEFAULT_CURRENCY`
  - `reference_date: datetime.date` *(date de référence de la fenêtre mensuelle)*
  - `month_from: datetime.date`, `month_to: datetime.date` *(bornes du mois civil courant,
    exposées pour la transparence de la période — comme #40)*
  - **Aucun** champ identifiant une entité (pas de `salon_id`, `salon_name`, `client_id`,
    `owner_id`, ni ligne quelconque).
  - **Sort du KPI « abonnements » — voir Open Q. #1.** Recommandation : **ne pas** émettre
    de champ `subscriptions` distinct au MVP (pas de modèle) ; l'UI admin peut **libeller**
    `salons_active` comme « salons abonnés (actifs) ». Alternative documentée : émettre
    `subscriptions: int | None = None` **explicitement nul** avec un commentaire traçant
    l'absence de modèle. **Ne pas** inventer un nombre d'abonnements.
- **Fenêtre de reporting** : réutiliser `domain/revenue.py::month_bounds(reference_date)`
  pour `(month_from, month_to)` ; ne **pas** dupliquer la logique calendaire. Le use case
  convertit ces bornes de **jour civil** en bornes **UTC** (via `time_window.day_start_utc`
  / `day_end_utc`) **uniquement** pour le revenu (colonne `created_at` timezone-aware) ;
  les RDV se comparent **directement** sur `appointment_date` (déjà un jour civil).
- **Pas de filtre utilisateur complexe** : la seule entrée optionnelle est une
  `reference_date` (défaut = « aujourd'hui » à Abidjan). Si un paramètre de requête est
  accepté, sa validation reste triviale (une `datetime.date` bien formée) et ne nécessite
  **pas** de nouvelle erreur de domaine (cf. §5). *(Décision Open Q. #5 : au minimum, un
  cumul sans période ; recommandé, cumul + mois courant dérivé de `reference_date`.)*

### 2. Port — `application/ports/platform_kpi_repository.py` (nouveau)

Un port **dédié** (raison identique à #37 : les compteurs/sommes portent sur **toutes**
les entités de la plateforme ; les ports existants sont salon-scopés) :

```python
class PlatformKpiRepository(Protocol):
    def compute_snapshot(
        self,
        *,
        month_from: datetime.date,
        month_to: datetime.date,
        revenue_from_utc: datetime.datetime,
        revenue_to_utc: datetime.datetime,
    ) -> PlatformKpiCounts: ...
```

- Le port renvoie un petit VO **de transport** `PlatformKpiCounts` (ou un `tuple`/`dict`
  interne) portant les scalaires bruts (`salons_total`, `salons_active`, `clients_total`,
  `appointments_total`, `appointments_this_month`, `revenue_total`, `revenue_this_month`).
  Le use case assemble le `PlatformKpiSnapshot` public (avec `reference_date`, bornes,
  devise). *(Alternative : le port renvoie directement le `PlatformKpiSnapshot` — choix
  d'implémentation mineur ; garder le domaine pur des détails de fenêtre.)*
- **Pas de pagination** : instantané unique. **Pas** de constantes `LIMIT_*`.
- **Lecture pure** : aucune méthode d'écriture.

### 3. Persistance — `adapters/outbound/persistence/platform_kpi_repository.py` (nouveau)

`SqlPlatformKpiRepository(session)` implémentant le port en SQLAlchemy 2.0. Chaque KPI est
un `SELECT` scalaire indépendant (lisible, chacun couvert par un index existant), **ou**
regroupé en quelques requêtes avec `FILTER` :
- `salons_total` : `select(func.count()).select_from(models.Salon)`.
- `salons_active` : `func.count().filter(models.Salon.status == SalonStatus.ACTIVE.value)`
  (ou `WHERE`), couvert par `ix_salons_status`.
- `clients_total` : `func.count()` sur `users` `WHERE role = 'CLIENT'`.
- `appointments_total` : `func.count()` sur `appointments` *(inclusion des `CANCELLED` —
  Open Q. #3 ; recommandé : **compter tous** les RDV créés = volume de la plateforme, et
  **documenter**)*.
- `appointments_this_month` : `func.count()` `WHERE appointment_date BETWEEN month_from
  AND month_to` (comparaison **date**, index `ix_appointments_salon_id` partiellement
  utile ; un index dédié n'est **pas** prévu — cf. Data Model).
- `revenue_total` : `func.coalesce(func.sum(models.CashJournal.amount), 0)` sur **toute**
  la table (net signé — parité #37).
- `revenue_this_month` : idem `WHERE created_at BETWEEN revenue_from_utc AND
  revenue_to_utc`.
- Montants quantifiés au centime (`Decimal(...).quantize(Decimal("0.01"))`, miroir de
  `_AMOUNT_QUANTUM` de #37). **Aucune** écriture, **aucun** commit. Tout est **en SQL**
  (garde de coût §12.1).

### 4. Application — `application/platform_kpis.py` (nouveau)

Use case **pur** `ComputePlatformKpis` (dépend du **seul** port) :

```python
class ComputePlatformKpis:
    def __init__(self, repo: PlatformKpiRepository) -> None: ...
    def execute(self, *, reference_date: datetime.date) -> PlatformKpiSnapshot:
        month_from, month_to = month_bounds(reference_date)
        counts = self._repo.compute_snapshot(
            month_from=month_from,
            month_to=month_to,
            revenue_from_utc=day_start_utc(month_from),
            revenue_to_utc=day_end_utc(month_to),
        )
        return PlatformKpiSnapshot(reference_date=reference_date, month_from=month_from,
                                   month_to=month_to, ...)
```

Lecture pure : **aucun** audit §11.4 (parité #37/#39–#43).

### 5. Adapter entrant — `adapters/inbound/admin.py` (**étendre** le router `/admin` de #37)

- **Nouvelle route** : `GET /admin/kpis` *(nom recommandé — Open Q. #6 ; alternatives :
  `/admin/dashboard`, `/admin/platform/kpis`)*.
- **Garde** : `require_permission(Permission.STATS_READ_PLATFORM)` **uniquement** (pas de
  `require_salon_scope`), **exactement** comme `GET /admin/transactions/summary`. L'`ADMIN`
  est le seul rôle porteur → `401` sans jeton, `403` générique pour tout autre rôle (aucun
  oracle), `403` « Compte désactivé. » pour un admin non `ACTIVE`.
- **Query param** (optionnel, recommandé) : `reference_date` (`date`, jour civil
  `Africa/Abidjan`), défaut = jour courant côté serveur. Une `date` mal formée est
  rejetée en `422` **par la validation Query FastAPI** (pas besoin d'erreur de domaine ;
  aucune contrainte d'ordre à valider puisqu'il n'y a qu'une date). *(Si Open Q. #5 retient
  « cumul seul », la route peut n'accepter aucun paramètre.)*
- **Schéma Pydantic** documenté `PlatformKpiResponse` avec champs **explicites** (jamais
  `orm_mode`/`extra`), miroir non-PII de `SalonTransactionSummaryResponse` :
  `salons_total`, `salons_active`, `clients_total`, `appointments_total`,
  `appointments_this_month`, `revenue_total` (chaîne décimale, `examples=["12500000.00"]`),
  `revenue_this_month`, `currency` (`examples=["XOF"]`), `reference_date`, `month_from`,
  `month_to`. Un test **fige** la forme (échec si un champ interdit — `salon_id`,
  `client_id`, `owner_id`, nom d'entité… — apparaît).
- **Injection** : `get_platform_kpi_repository(session)` (surchargeable en test via
  `app.dependency_overrides`, patron de `get_platform_transaction_repository`).
- **`responses`** OpenAPI : `401`/`403` (+ `422` si un `reference_date` mal formé est
  accepté en query).

### 6. Assemblage — `main.py`

**Rien à modifier** : le router `/admin` est déjà inclus (`include_router(admin_router)`
depuis #37). La nouvelle route hérite de la garde par route. **Ne pas** ajouter `/admin/…`
à `PUBLIC_ROUTE_PATHS` (l'invariant `unprotected_routes` reste vert).

### 7. Web admin (`web-dashboard`) — voir *Risks* #4 (arbitrage de périmètre)

La zone `/admin` n'existe pas. Le critère d'acceptation nomme un « **dashboard admin** »,
ce qui plaide pour une tranche web ; mais **amorcer** la zone `/admin` (layout, garde de
rôle BFF `deny-by-default` — cookie `httpOnly` + vérification `GET /auth/me` côté serveur,
navigation des sections §7.3) représente un effort comparable au **shell gérant #14** et
peut **dépasser** l'estimation M. Deux livrables recommandés à confirmer :
- **(a) Socle backend `GET /admin/kpis`** — **toujours** dans le périmètre (cœur de l'US).
- **(b) Page KPI admin minimale** amorçant `app/(admin)/admin/…` + route BFF
  `app/api/admin/kpis` proxifiant le backend avec le cookie `httpOnly`, sur le patron du
  shell gérant. À **confirmer** comme partie de #44 ou comme livrable séparé.

## Affected Files / Packages / Modules

**À créer (backend) :**
- `backend/coiflink_api/domain/platform_kpis.py` — VO `PlatformKpiSnapshot`
  (+ éventuel VO de transport `PlatformKpiCounts`).
- `backend/coiflink_api/application/ports/platform_kpi_repository.py` — port
  `PlatformKpiRepository`.
- `backend/coiflink_api/adapters/outbound/persistence/platform_kpi_repository.py` —
  `SqlPlatformKpiRepository`.
- `backend/coiflink_api/application/platform_kpis.py` — use case `ComputePlatformKpis`.
- Tests (voir *Testing Plan*) : `tests/test_domain_platform_kpis.py`,
  `tests/test_platform_kpis_usecase.py`, `tests/test_admin_kpis_api.py`,
  `tests/test_admin_kpis_e2e.py`.

**À modifier (backend) :**
- `backend/coiflink_api/adapters/inbound/admin.py` — ajouter la route `GET /admin/kpis`,
  le schéma `PlatformKpiResponse`, le provider `get_platform_kpi_repository`. **Ne pas**
  toucher à la route #37 existante.

**À lire (référence, non modifiés) :**
- `adapters/inbound/admin.py` (route #37), `domain/platform_transactions.py`,
  `application/platform_transactions.py`,
  `application/ports/platform_transaction_repository.py`,
  `adapters/outbound/persistence/platform_transaction_repository.py`,
  `domain/revenue.py` (`month_bounds`), `application/revenue.py`, `domain/time_window.py`,
  `domain/permissions.py`, `adapters/inbound/security.py`,
  `application/authorization.py`, `adapters/outbound/persistence/models.py`,
  `domain/enums.py`, `domain/payment.py` (`DEFAULT_CURRENCY`), `main.py`.

**Documentation :** `README.md` (§6 récit d'avancement M5), `docs/adr/` (ADR-0032 proposé —
voir *Documentation Updates* et Open Q. #7), `docs/adr/README.md` (index).

**Web (si tranche (b) confirmée — voir *Risks* #4) :** `web-dashboard/app/(admin)/admin/…`
(page KPI + layout garde de rôle), `web-dashboard/app/api/admin/kpis/route.ts` (BFF),
`web-dashboard/README.md`.

## API / Interface Changes

**Nouvel endpoint (backend) :**

`GET /admin/kpis` *(nom à confirmer — Open Q. #6)*

- **Auth** : Bearer JWT ; **permission requise** `STATS_READ_PLATFORM` (**ADMIN** seul).
  `401` sans jeton / jeton invalide ; `403` générique pour tout autre rôle (aucun oracle) ;
  `403` « Compte désactivé. » pour un admin non `ACTIVE`.
- **Query params** *(recommandé)* : `reference_date` (`date`, jour civil `Africa/Abidjan`,
  défaut = jour courant serveur). Une `date` mal formée → `422` (validation Query FastAPI).
- **`200` — corps** *(forme recommandée ; le champ `subscriptions` est volontairement
  **absent** — voir Open Q. #1)* :

```json
{
  "salons_total": 128,
  "salons_active": 97,
  "clients_total": 5421,
  "appointments_total": 18342,
  "appointments_this_month": 1204,
  "revenue_total": "12500000.00",
  "revenue_this_month": "980000.00",
  "currency": "XOF",
  "reference_date": "2026-08-03",
  "month_from": "2026-08-01",
  "month_to": "2026-08-31"
}
```

Aucun autre endpoint, CLI ou signature publique n'est modifié. **La route #37
(`GET /admin/transactions/summary`) reste inchangée.**

## Data Model / Protocol Changes

**None.** Aucune migration Alembic : lecture pure agrégée sur les tables existantes
(`salons`, `users`, `appointments`, `cash_journal`). Aucun nouveau champ, aucune nouvelle
table, **aucun modèle d'abonnement** (voir Open Q. #1). Les index existants
(`ix_salons_status`, `ix_appointments_salon_id (salon_id, appointment_date)`,
`ix_cash_journal_salon_id (salon_id, created_at)`) couvrent les compteurs/sommes ; les
compteurs globaux `COUNT(*)` non filtrés font un balayage borné acceptable au MVP
(volumétrie pilote, PRD §14). **Aucun nouvel index n'est prévu** — à réévaluer uniquement
sur preuve d'un plan de requête défavorable sous charge (§12).

## Security & Privacy Considerations

- **Autorisation (RBAC #12, ADR-0015)** : gardée par `STATS_READ_PLATFORM`, détenue par le
  **seul** `ADMIN` dans la matrice **fermée** `ROLE_PERMISSIONS` — **non modifiée**. La
  route **ne réutilise pas** `require_salon_scope` : c'est une lecture **plateforme**
  légitime (l'admin voit toute la plateforme via `AccessPolicy.scope_of` →
  `SalonScope.platform()`, ADR-0015), pas un contournement d'isolation §11.2. Aucun autre
  rôle ne gagne d'accès.
- **Non-PII (§11.3) — plus fort que #37** : la réponse ne porte **que des scalaires
  globaux** (compteurs, montants, dates, devise). **Aucune** identité d'entité n'est émise
  — ni `salon_id`/`salon_name` (contrairement à #37 qui exposait l'identité métier du
  salon comme unité d'agrégation), ni `client_id`, ni `owner_id`, ni `reference`, ni
  `recorded_by`, ni aucune ligne individuelle. La sérialisation Pydantic liste des champs
  **explicites** (pas de fuite par `orm_mode`/`extra`) ; un test d'API **fige** la forme.
- **Deny-by-default (#12)** : la route porte une garde de `Principal` et **n'est pas**
  publique-listée ; l'invariant `unprotected_routes(app) == []` la couvre automatiquement.
- **Messages de refus** : `401`/`403` **constants et génériques** (jamais `str(exc)`),
  aucun oracle sur l'existence d'une entité.
- **Non-journalisation (§11.3/§11.4, ADR-0011)** : lecture → **aucun** audit, **aucun** log
  de compteurs/montants. Aucun secret ni PII ne transite en log.
- **Montants** : `Decimal`/`NUMERIC(12,2)`, sérialisés en **chaîne** (jamais un flottant) —
  parité #37/#40.
- **Garde de coût (§12.1)** : agrégation **en SQL** (jamais en mémoire) ; instantané non
  paginé mais **borné en cardinalité** (une poignée de scalaires), pas de matérialisation
  de lignes.
- **« Revenus plateforme » ≠ « revenus d'abonnement »** : le KPI de revenu de #44 est le
  **flux net encaissé par les salons** (source `cash_journal`), **pas** un revenu de
  facturation SaaS (qui n'existe pas). Cette distinction doit être **explicite** dans les
  libellés (backend docstrings, UI) pour ne pas induire en erreur (voir Open Q. #1).

Le dépôt ne documente **aucune** autre contrainte spécifique (résidence, budget latence
dédié) pour cette lecture au-delà des invariants ci-dessus.

## Testing Plan

**Unitaires — domaine (`tests/test_domain_platform_kpis.py`, sans I/O) :**
- Fenêtre mensuelle : `PlatformKpiSnapshot` / la logique de fenêtre dérive `(month_from,
  month_to)` via `month_bounds` — 1er → dernier jour (février bissextile, mois 30/31)
  (miroir/réutilisation des tests de `domain/revenue.py`).
- Le VO est immuable (`frozen`) et n'expose **aucun** champ d'identité (test de forme).

**Unitaires — application (fake `PlatformKpiRepository`) :**
- `ComputePlatformKpis.execute(reference_date=…)` : passe au port des bornes de mois
  correctes et des bornes UTC correctes (jour civil `Africa/Abidjan` → UTC inclusif) ;
  assemble le snapshot avec `reference_date`/`currency` ; **aucune** écriture/audit.

**API / intégration (FastAPI `TestClient`, dépôts surchargés) :**
- `GET /admin/kpis` — **`200`** pour un `ADMIN` actif ; **`403`** pour `MANAGER`,
  `HAIRDRESSER`, `CLIENT` (message générique) ; **`401`** sans jeton / jeton invalide ;
  **`403`** « Compte désactivé. » pour un admin non `ACTIVE`.
- **Forme de la réponse (non-PII)** : les clés sont **exactement** l'ensemble attendu ;
  un test **échoue** si un champ interdit (`salon_id`, `salon_name`, `client_id`,
  `owner_id`, `reference`, `recorded_by`, ou tout identifiant d'entité) apparaît.
- `reference_date` mal formé → `422` (validation Query) ; défaut (paramètre absent) →
  `200` sur le mois courant.
- **Deny-by-default** : le test d'invariant existant (`unprotected_routes`) reste vert avec
  la route ajoutée.

**Intégration SQL réelle (PostgreSQL 16, chemin dépôt — patron `test_admin_transactions_e2e.py`
et suites e2e caisse ; base `coiflink-e2e-pg`) :**
- **Compteurs corrects** sur un jeu multi-salons : `salons_total` (dont
  `INACTIVE`/`SUSPENDED`) vs `salons_active` ; `clients_total` **n'inclut que** les
  comptes `CLIENT` (exclut `MANAGER`/`HAIRDRESSER`/`ADMIN`).
- **RDV** : `appointments_total` sur tous les salons ; `appointments_this_month` **filtre**
  correctement par `appointment_date` aux **bornes du mois civil** (un RDV le 1er et un le
  dernier jour comptent ; le mois précédent/suivant est exclu) ; inclusion des `CANCELLED`
  conforme à la décision retenue (Open Q. #3) — **figée par test**.
- **Revenu net plateforme** : `revenue_total` = somme signée `cash_journal` sur **tous**
  les salons (un paiement corrigé #34 **fait baisser** le net) ; `revenue_this_month`
  borné correctement aux bornes UTC du mois `Africa/Abidjan` (inclusif aux frontières).
- **Plateforme vide** : aucun salon/RDV/paiement → tous les compteurs `0`, revenus
  `"0.00"` (pas d'exception).

**Documentation :** vérifier que l'exemple OpenAPI du router correspond au schéma (aucun
champ PII, montants en chaîne).

## Documentation Updates

- **`README.md` §6** : ajouter le paragraphe d'avancement **M5 / #44** (endpoint
  `GET /admin/kpis`, KPI globaux agrégés, `STATS_READ_PLATFORM` **deuxième consommateur**,
  revenu net via `cash_journal`, non-PII, **décision sur les abonnements**), sur le patron
  des entrées #37/#39–#43. **Ne rien affirmer d'inexistant** (pas de système d'abonnement).
- **ADR proposé `docs/adr/0032-kpi-globaux-plateforme-admin.md`** *(à confirmer — Open Q.
  #7)* : tracer (a) l'extension du router `/admin` avec un **instantané global non paginé**,
  (b) le **revenu net via `cash_journal`** (cohérence #37/ADR-0029), (c) la distinction
  **« revenus plateforme » ≠ « revenus d'abonnement »** et le **report du KPI abonnements**
  faute de modèle, (d) la non-PII renforcée (aucune identité d'entité). Mettre à jour
  **`docs/adr/README.md`** (ligne 0032, issue #44).
- **OpenAPI** : docstrings + `responses` du router (générés dans `/docs`) — décrire
  `401/403` (+ `422` si `reference_date`) et l'absence de PII.
- **`web-dashboard/README.md`** *(seulement si la tranche web (b) est livrée)* : décrire
  la zone `/admin` amorcée. Sinon, **ne rien documenter d'inexistant**.

## Risks and Open Questions

1. **KPI « abonnements » — aucun modèle de données (décision produit centrale).** Le PRD
   décrit des abonnements SaaS (§7.3/§15.1) mais **rien n'existe** côté backend (ni table,
   ni domaine). Options : **(a, recommandé)** livrer les KPIs **adossés à des données
   réelles** (salons inscrits/actifs, RDV, revenus plateforme, +clients) et **reporter** le
   KPI abonnements — l'UI peut libeller `salons_active` « salons abonnés » sans émettre un
   nombre d'abonnements fictif ; **(b)** émettre `subscriptions: null` explicitement avec
   rationale ; **(c)** ouvrir un **épic distinct** « abonnements/facturation » (hors #44).
   **Ne pas** inventer un modèle d'abonnement dans #44. **À trancher avant l'implémentation.**
2. **Périmètre exact des KPIs.** Le backlog liste 4 KPIs (salons, abonnements, RDV,
   revenus). Le PRD §7.3 en ajoute (salons actifs, clients inscrits). *Recommandé : livrer
   les 4 du backlog **plus** `salons_active` et `clients_total`* (peu de coût, forte valeur,
   alignés PRD §13.1). À confirmer.
3. **RDV `CANCELLED` dans `appointments_total`.** Un « nombre de rendez-vous » de pilotage
   plateforme reflète-t-il le **volume créé** (tous statuts) ou les RDV **effectifs**
   (hors `CANCELLED`) ? *Recommandé : compter **tous** les RDV créés* (volume plateforme),
   distinct du CA où « annulés exclus » (§8.1) est vrai par construction. **Figer par test.**
4. **Tranche web `/admin`.** La zone n'existe pas ; le critère d'acceptation nomme un
   « dashboard admin ». Amorcer `/admin` (layout, garde de rôle BFF, navigation) est un
   effort de type **shell #14**, possiblement **> M**. *Recommandé : backend `GET
   /admin/kpis` **toujours** livré ; page KPI admin minimale **à confirmer** comme partie de
   #44 ou livrable séparé.* Décision produit à confirmer.
5. **Granularité de période.** Cumul seul, ou cumul **+ mois courant** (RDV/revenus) via
   `reference_date` ? *Recommandé : cumul + mois courant* (PRD §7.3 « Rendez-vous mensuels »,
   « Revenus »). Semaine/jour non demandés — hors périmètre.
6. **Nom de la route.** `GET /admin/kpis` (recommandé, concis) vs `/admin/dashboard` vs
   `/admin/platform/kpis`. À confirmer (impact contrat public / BFF).
7. **ADR.** Créer un **ADR-0032** (cadence #37 → ADR-0029) pour tracer le report du KPI
   abonnements et la garde plateforme, **ou** se contenter du spec + README ? *Recommandé :
   ADR-0032.*
8. **Multi-devise.** Mono-devise **XOF** assumée (comme #37/ADR-0029) ; un `SUM` global
   serait faux si des devises hétérogènes coexistaient. À revoir seulement si le modèle
   évolue.
9. **Volumétrie / index.** Les `COUNT(*)` globaux non filtrés balaient toute la table ;
   acceptable à la volumétrie pilote (§14). À profiler avant montée en charge ; tout index
   resterait **additif** (pas dans #44).

## Implementation Checklist

1. **Décisions à confirmer d'abord** : sort du KPI abonnements (Open Q. #1), périmètre des
   KPIs (#2), inclusion `CANCELLED` (#3), tranche web (#4), granularité période (#5), nom de
   route (#6), ADR (#7). Consigner les choix retenus en tête d'implémentation.
2. **Domaine** — créer `domain/platform_kpis.py` : `PlatformKpiSnapshot` (frozen, **sans
   identité d'entité**, montants `Decimal`) ; réutiliser `revenue.month_bounds` pour la
   fenêtre mensuelle (aucune duplication). **Aucun** champ `subscriptions` sauf décision
   contraire (#1).
3. **Port** — créer `application/ports/platform_kpi_repository.py` :
   `PlatformKpiRepository.compute_snapshot(...)` (lecture seule, inter-entités), sans
   pagination.
4. **Persistance** — créer
   `adapters/outbound/persistence/platform_kpi_repository.py` :
   `SqlPlatformKpiRepository` (COUNT `salons`/`salons_active`/`clients`/`appointments`
   [total + mois], SUM net `cash_journal` [total + mois], **en SQL**, bornes de dates,
   quantification centime, lecture pure).
5. **Application** — créer `application/platform_kpis.py` : `ComputePlatformKpis.execute(
   reference_date)` → `PlatformKpiSnapshot` (convertit les bornes de mois en UTC via
   `time_window` pour le revenu ; passe `appointment_date` en jour civil), **sans** audit.
6. **Adapter entrant** — **étendre** `adapters/inbound/admin.py` : route `GET /admin/kpis`,
   garde `require_permission(STATS_READ_PLATFORM)` (**pas** de `require_salon_scope`),
   schéma `PlatformKpiResponse` **non-PII** documenté (champs explicites), provider
   `get_platform_kpi_repository`, query `reference_date?` (`422` si mal formé). **Ne pas**
   modifier la route #37.
7. **Assemblage** — **vérifier** que le router `/admin` reste inclus dans `main.py` (rien à
   ajouter) et que `/admin/kpis` **n'entre pas** dans `PUBLIC_ROUTE_PATHS`.
8. **Tests** — domaine (fenêtre mensuelle, forme sans PII), application (fake repo, bornes),
   API (auth `401/403/200`, forme non-PII, `reference_date` `422`/défaut), intégration SQL
   PostgreSQL (compteurs multi-salons, clients=`CLIENT` seuls, RDV mois, revenu net avec
   ajustements, plateforme vide), invariant deny-by-default vert.
9. **Docs** — README §6 (#44) ; ADR-0032 proposé + index `docs/adr/README.md` (si confirmé,
   #7) ; vérifier OpenAPI.
10. **Test gate** — `ruff check` + `pytest` verts (parité CI `scripts/test-gate.sh`).
11. **(Optionnel, si tranche web (b) confirmée)** — amorcer `app/(admin)/admin/…` (page KPI
    + garde de rôle BFF), route BFF `app/api/admin/kpis`, `web-dashboard/README.md`.
