# Chiffre d'affaires — jour / semaine / mois (dashboard gérant) (US-6.2, #40)

> Épic 6 (Statistiques / Dashboard) · Priorité **Must** · Effort **M** · PRD §6 (US-6.2) / §8.1 /
> §8.2 / §11.2 / §11.3 / §12.1
> **Dépend de #33** (US-5.1 — enregistrement d'un paiement : table `payments`, ligne `PAYMENT` du
> journal de caisse `cash_journal`, correction par `ADJUSTMENT` #34). Repose aussi sur le shell du
> dashboard gérant (#14, zone `/gerant`), la permission `STATS_READ_SALON` (RBAC #12 / ADR-0015,
> **déjà** réservée au `MANAGER`, premier consommateur #39) et la tranche RDV du jour (#39) dont ce
> KPI **prolonge** l'affichage.

## Problem Statement

Le gérant dispose, depuis #39 (US-6.1), d'un **décompte du jour par statut** sur son tableau de bord
(`/gerant`). Il n'a en revanche **aucune visibilité sur ses revenus** : le PRD (§6, US-6.2) demande
*« en tant que gérant, je veux voir mon chiffre d'affaires »* avec pour spécification **« CA
journalier, hebdomadaire, mensuel »**, et l'invariant produit §8.1 : *« un rendez-vous annulé ne
doit pas être comptabilisé dans le chiffre d'affaires »*.

Le gap est double :

1. **Backend** — il n'existe **aucune** lecture agrégée du CA d'**un** salon. Les surfaces livrées
   côté encaissement sont :
   - `POST /salons/{salon_id}/payments` (#33) — enregistre un paiement `VALIDATED`, écrit une ligne
     `PAYMENT` au journal (`cash_journal`) ;
   - `GET /salons/{salon_id}/payments` (#35) — **liste** filtrable des transactions (pas d'agrégat
     de montant) ;
   - `GET /salons/{salon_id}/cash-journal` (#34) — **liste** paginée des opérations ;
   - `GET /admin/transactions/summary` (#37) — agrégat **inter-salons** (montant net **par salon**),
     réservé à l'`ADMIN` (`STATS_READ_PLATFORM`) — **pas** une lecture qu'un gérant peut appeler, et
     **pas** ventilée par période (jour/semaine/mois).
   Aucune de ces routes ne renvoie au **gérant** son CA **par période**.
2. **Web** — le dashboard `/gerant` (Server Component livré par #39) affiche les tuiles RDV mais
   **aucun indicateur financier**.

L'US-6.2 comble ce gap par une **lecture agrégée salon-scopée** exposant le CA du salon sur trois
périodes (jour, semaine, mois) et par un **jeu de tuiles KPI** sur le dashboard, prolongeant #39.

## Goals

- Exposer une **lecture agrégée salon-scopée** renvoyant, pour une **date de référence** (jour civil
  `Africa/Abidjan`, convention #21, défaut = aujourd'hui), le **chiffre d'affaires du salon** sur
  **trois périodes** : le **jour** de référence, la **semaine** civile qui le contient
  (lundi → dimanche) et le **mois** civil qui le contient (1er → dernier jour). Chaque période porte
  ses bornes (`date_from`/`date_to`), un **total** (`Decimal`, `NUMERIC(12,2)`) et la devise (`XOF`).
- Dériver le CA de la **même source de vérité** que les autres lectures financières : le **journal de
  caisse** (`cash_journal`, #34), via la **somme signée** des lignes `PAYMENT`/`ADJUSTMENT` — un
  paiement corrigé (#34) fait donc **baisser** le CA (net des corrections, comme le « montant net »
  de #37). C'est bien un CA **« calculé à partir des paiements »** (AC #40) : la ligne `PAYMENT` du
  journal **est** le paiement (1:1, même montant, invariant #34/#37).
- Garantir **« annulés exclus »** (AC #40, §8.1) : un **RDV annulé** (`CANCELLED`) ne génère **aucun**
  paiement, donc **aucune** ligne de journal, donc **aucune** contribution au CA — l'exclusion est
  vraie **par construction** de la source de vérité (voir Open Questions pour la lecture stricte de
  §8.1).
- Garder cette lecture par la **permission `STATS_READ_SALON`** (déjà `MANAGER` dans
  `ROLE_PERMISSIONS`) **+** `require_salon_scope` (isolation §11.2) — **sans modifier** la matrice des
  droits.
- Calculer les agrégats **en base** (`SUM` sur un intervalle indexé), **sans** rapatrier de ligne de
  paiement ni aucune PII : la réponse ne porte **que** des montants, des dates et une devise (§11.3).
- Afficher, sur le **dashboard gérant** (`/gerant`), les **trois tuiles CA** (Jour · Semaine · Mois)
  **sous** les tuiles RDV du jour (#39), en réutilisant le patron Server Component + gateway serveur
  (jeton du cookie `httpOnly`, jamais exposé — invariant #14).
- Préserver le **deny-by-default** (#12 / ADR-0015) : la route porte une garde de `Principal`, n'est
  **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` ; l'isolation §11.2 est **ré-affirmée en SQL** (filtre
  `salon_id` inconditionnel), en défense en profondeur de la garde HTTP.
- Rester **additif et rétro-compatible** : aucune signature existante modifiée, **aucune migration**
  de schéma (l'index `ix_cash_journal_salon_id (salon_id, created_at)` couvre déjà la requête).

## Non-Goals

- **Aucune série temporelle ni graphique / courbe** : trois **totaux ponctuels** (jour, semaine,
  mois), pas d'historique par jour ni de sparkline. Les courbes/tendances relèvent d'évolutions
  post-MVP (PRD §16/§21).
- **Aucune ventilation** du CA par prestation, par coiffeur ou par mode de paiement : ce sont
  d'autres US de l'Épic 6 (US-6.3 #41 « prestations les plus demandées », US-6.5 #43 « performance
  des coiffeurs ») et de l'admin (US-6.6 #44).
- **Aucun agrégat inter-salons ni vue admin** : #40 est **salon-scopé** (le gérant voit **son**
  salon). L'agrégat plateforme existe déjà (#37) et le KPI admin est #44.
- **Aucune plage de dates arbitraire** exposée à l'appelant : le seul paramètre est la **date de
  référence** ; les trois périodes en sont **dérivées côté serveur**. (Un endpoint « range libre »
  est écarté — voir Open Questions.)
- **Aucune écriture / aucun audit §11.4** : lecture pure (comme #34/#35/#36/#37/#39). La consultation
  d'un KPI n'est **pas** journalisée.
- **Aucune modification de `ROLE_PERMISSIONS`** ni des droits `CLIENT`/`HAIRDRESSER`/`ADMIN`.
- **Aucune personnalisation du fuseau ou du début de semaine par salon** : jour civil `Africa/Abidjan`
  (UTC+0, convention #21), semaine **lundi → dimanche** (voir Open Questions).

## Relevant Repository Context

**Stack (figée par ADR).** Backend **Python FastAPI**, **architecture hexagonale** (ADR-0008) :
`domain/` (pur) → `application/` (cas d'usage + `ports/`) → `adapters/inbound|outbound/`. Persistance
**PostgreSQL 16 / SQLAlchemy 2.0 + Alembic** (ADR-0004/0009). RBAC **deny-by-default** (ADR-0015,
#12). Web gérant **Next.js** (ADR-0002) en **BFF** (cookie `httpOnly`, jeton jamais exposé au
navigateur — invariant #14). Mono-devise **XOF** (`domain/payment.py::DEFAULT_CURRENCY`, §9.6).

**Source de vérité financière : le journal de caisse (`cash_journal`, #34).** Précédent **direct** à
imiter, la **supervision agrégée #37** :

- `domain/platform_transactions.py` — objet-valeur de lecture `SalonTransactionSummary` +
  `PlatformSummaryFilter` / `validate_platform_summary_filter` (validation de plage + conversion de
  bornes de dates en UTC via `domain/time_window.py`). **Modèle** du domaine pur d'agrégation.
- `application/platform_transactions.py` — `SummarizeSalonTransactions` (lecture pure, `(page, total)`).
- `application/ports/platform_transaction_repository.py` — `PlatformTransactionRepository` (`Protocol`).
- `adapters/outbound/persistence/platform_transaction_repository.py` —
  `SqlPlatformTransactionRepository` : `total_amount = func.coalesce(func.sum(CashJournal.amount), 0)`
  quantifié au centime (`Decimal`, jamais un flottant), bornes de dates conditionnelles sur
  `created_at`, `GROUP BY salon_id`. **Modèle** du calcul SQL du « montant net ».
- `adapters/inbound/admin.py` — route `GET /admin/transactions/summary`, schéma Pydantic **explicite**
  (jamais `orm_mode`/`extra`), OpenAPI documenté, `InvalidPlatformSummaryFilter → 422`.

> **Différence-clé #37 → #40 :** #37 est **inter-salons** (d'où un **port dédié** groupant sur tous
> les salons, réservé `ADMIN`) ; #40 est **salon-scopé** (un seul salon, réservé `MANAGER`). Le
> raisonnement du port #37 (« ne pas réutiliser `CashJournalRepository` car il est **inconditionnellement**
> salon-scopé ») **s'inverse** ici : puisque #40 est justement salon-scopé, `CashJournalRepository`
> **est** le bon foyer (voir Proposed Implementation).

**Journal de caisse (existant).**
- `domain/cash_journal.py` — `CashJournalEntry` (montant **signé** : positif pour `PAYMENT`, signé
  pour `ADJUSTMENT`), `CashJournalToAppend`. Append-only §8.2.
- `application/ports/cash_journal_repository.py` — `CashJournalRepository` (`Protocol` :
  `append` + `list_for_salon` + `count_for_salon`), **inconditionnellement salon-scopé** (§11.2). On
  y **ajoute** une méthode d'agrégation `net_revenue_between(...)` (additive, rétro-compatible).
- `adapters/outbound/persistence/cash_journal_repository.py` — `SqlCashJournalEntryRepository` (à
  compléter par la requête `SUM`).
- `adapters/outbound/persistence/models.py` — `CashJournal` : `id`, `salon_id`, `transaction_id?`,
  `operation_type` (CHECK dérivé de `CashOperationType`), `amount NUMERIC(12,2)`, `performed_by`,
  `description?`, `created_at`. **Index couvrant `ix_cash_journal_salon_id (salon_id, created_at)`** —
  la requête `WHERE salon_id = :sid AND created_at BETWEEN :from AND :to` l'exploite. **Aucune**
  modification de schéma requise.
- `domain/enums.py` — `CashOperationType = PAYMENT | REFUND | ADJUSTMENT | CASH_OPENING |
  CASH_CLOSING` ; `PaymentStatus = PENDING | VALIDATED | CANCELLED | ADJUSTED`. **Au MVP, seuls
  `PAYMENT` et `ADJUSTMENT` sont produits** (#33/#34 ne créent ni `REFUND`, ni `CASH_OPENING/CLOSING`,
  ni paiement `CANCELLED`) — cf. `payment_repository.py` (`create` → `VALIDATED`, `mark_adjusted` →
  `ADJUSTED`, aucun `delete`).

**Fuseau / bornes de jour civil (existant, `domain/time_window.py`).**
- `SALON_TIMEZONE = ZoneInfo("Africa/Abidjan")` (UTC+0). `day_start_utc(day)` / `day_end_utc(day)`
  convertissent un **jour civil** en bornes UTC **inclusives** — `[jour 00:00:00, jour 23:59:59.999999]`
  — pour comparer à `cash_journal.created_at` (`timezone-aware`). **À réutiliser** (aucune
  duplication ; miroir de #35/#37). Contrairement à #39 (qui compare une colonne `Date`), ici la
  comparaison porte sur un **timestamp**, donc la conversion UTC est **requise**.

**Permission & assemblage.**
- `domain/permissions.py` — `STATS_READ_SALON` est **déjà** au `MANAGER` (et **seulement** lui) ;
  premier consommateur = #39. #40 en est le **deuxième**. **Ne pas** modifier `ROLE_PERMISSIONS`.
- `adapters/inbound/security.py` — `require_permission(...)` et `require_salon_scope` (à composer).
- `adapters/inbound/appointments.py` (#39) — la route stats `GET
  /salons/{salon_id}/appointments/daily-summary` (garde `STATS_READ_SALON` + `require_salon_scope`)
  est le **patron d'inbound stats salon-scopé** le plus récent à imiter.
- `main.py` — monte `FastAPI(dependencies=[Depends(require_authenticated)])` (deny-by-default global)
  et `include_router(...)` par adapter. L'invariant `unprotected_routes(app) == []` est **testé** :
  toute route ajoutée doit porter une garde de `Principal`.

**Web gérant (existant, `web-dashboard/`).**
- `app/(gerant)/gerant/page.tsx` — **Server Component** (#39) : résout le salon (`http-salon-gateway`),
  charge `dailySummary` via `http-appointment-gateway` (jeton serveur), rend `<DailySummaryTiles>`.
  **Cible d'extension** : ajouter le chargement du CA + un composant de tuiles CA sous les tuiles RDV.
- `src/adapters/api/http-payment-gateway.ts` — gateway HTTP encaissement existant (#33/#35) ; on y
  ajoute (ou dans un gateway « stats » dédié) un appel `revenueSummary(salonId, dateIso)`.
- `src/adapters/ui/daily-summary-tiles.tsx` — patron de tuiles KPI (#39) à imiter pour les tuiles CA.
- `src/domain/payments/` et `src/domain/appointment/planning-view.ts` (`todayIso()`) — types de
  domaine web + helper « aujourd'hui `Africa/Abidjan` ».

## Proposed Implementation

**Approche recommandée : backend-first, endpoint agrégé dédié (3 périodes en une réponse) + tranche
web.** On **ne réutilise pas** `GET …/payments` ni `GET …/cash-journal` pour sommer côté web : cela
rapatrierait des lignes (montants, `client_name`) pour un simple besoin de totaux, déplacerait la
règle métier (bornes de période, net des corrections) hors backend, et paginerait sur potentiellement
beaucoup de lignes. Un endpoint agrégé respecte la minimisation (§11.3) et la garde de coût (§12.1),
et suit le précédent #37. La règle « quelles bornes pour jour/semaine/mois » vit **dans le domaine**.

### Backend

1. **Domaine — objet-valeur + bornes de période (`domain/revenue.py`, nouveau, pur).**
   - `RevenuePeriodTotal` (`dataclass(frozen=True)`) : `date_from: datetime.date`,
     `date_to: datetime.date`, `total: decimal.Decimal`, `currency: str = DEFAULT_CURRENCY`.
   - `RevenueSummary` (`dataclass(frozen=True)`) : `reference_date: datetime.date`,
     `day: RevenuePeriodTotal`, `week: RevenuePeriodTotal`, `month: RevenuePeriodTotal`,
     `currency: str = DEFAULT_CURRENCY`.
   - **Fonctions pures de bornes** (jour civil, sans I/O, testables sans base) :
     - `day_bounds(d) -> (d, d)` ;
     - `week_bounds(d) -> (monday, sunday)` avec `monday = d - timedelta(days=d.weekday())` (lundi = 0)
       et `sunday = monday + timedelta(days=6)` ;
     - `month_bounds(d) -> (first, last)` avec `first = d.replace(day=1)` et
       `last = d.replace(day=calendar.monthrange(d.year, d.month)[1])` (stdlib `calendar`, aucune
       dépendance nouvelle).
   - Ces fonctions **encapsulent la sémantique des périodes** — c'est *la* règle métier de l'US-6.2 —
     et garantissent des bornes cohérentes (`date_from ≤ date_to`, semaine ⊇ jour, mois ⊇ jour).
     Exporter le tout dans `__all__`.

2. **Port (`application/ports/cash_journal_repository.py`, additif).**
   Ajouter au `Protocol CashJournalRepository` :
   ```python
   def net_revenue_between(
       self,
       salon_id: uuid.UUID,
       *,
       created_at_from: datetime.datetime,
       created_at_to: datetime.datetime,
   ) -> decimal.Decimal:
       ...
   ```
   Docstring : renvoie la **somme signée** des `cash_journal.amount` du salon dont `created_at` est
   dans `[created_at_from, created_at_to]` **inclus**, **restreinte aux opérations `PAYMENT` /
   `ADJUSTMENT`** (le CA est net des corrections ; les autres types — `REFUND`/`CASH_OPENING`/
   `CASH_CLOSING` — n'existent pas au MVP et **ne sont pas** du chiffre d'affaires). Isolation §11.2
   **imposée en SQL** (`WHERE salon_id`), défense en profondeur de `require_salon_scope`. Lecture pure ;
   `Decimal` quantifié au centime, jamais un flottant ; `0.00` si aucune ligne.
   *(Placement : `CashJournalRepository` est **inconditionnellement salon-scopé** — le foyer naturel
   d'une lecture salon-scopée sur `cash_journal`. C'est l'inverse exact du choix #37, qui a créé un
   port dédié **parce que** l'agrégat était inter-salons. Alternative « port stats dédié » en Open
   Questions.)*

3. **Use case (`application/revenue.py`, nouveau).**
   `SummarizeRevenue(cash_journal_repository)` avec `execute(salon_id, reference_date) ->
   RevenueSummary` :
   - calcule les trois paires de bornes civiles via `day_bounds` / `week_bounds` / `month_bounds` ;
   - convertit chaque paire en bornes UTC via `time_window.day_start_utc(from)` /
     `day_end_utc(to)` (miroir #35/#37) ;
   - appelle `net_revenue_between` **une fois par période** (trois requêtes indexées, bornées — pas de
     plage arbitraire, pas de pagination) ;
   - assemble et renvoie `RevenueSummary`. Aucune écriture, aucun audit. Ajouter au `__all__`.
   *(Les périodes se chevauchant — le jour ⊂ la semaine, la semaine croise parfois deux mois — on ne
   combine pas les sommes : trois `SUM` indépendants et lisibles.)*

4. **Adapter outbound (`adapters/outbound/persistence/cash_journal_repository.py`).**
   Implémenter `net_revenue_between` (miroir de `SqlPlatformTransactionRepository`) :
   ```python
   stmt = (
       select(func.coalesce(func.sum(models.CashJournal.amount), 0))
       .where(
           models.CashJournal.salon_id == salon_id,
           models.CashJournal.created_at >= created_at_from,
           models.CashJournal.created_at <= created_at_to,
           models.CashJournal.operation_type.in_(_REVENUE_OPERATION_TYPES),
       )
   )
   return decimal.Decimal(self._session.scalar(stmt) or 0).quantize(_AMOUNT_QUANTUM)
   ```
   avec `_REVENUE_OPERATION_TYPES = (CashOperationType.PAYMENT.value,
   CashOperationType.ADJUSTMENT.value)` et `_AMOUNT_QUANTUM = Decimal("0.01")`. La requête est couverte
   par `ix_cash_journal_salon_id (salon_id, created_at)`. Lecture pure : aucun `flush`.

5. **Adapter inbound — nouveau router `adapters/inbound/stats.py` (recommandé).**
   Router `APIRouter(prefix="/salons", tags=["stats"])`. Route :
   `GET /salons/{salon_id}/revenue/summary`
   - Gardes : `require_salon_scope` **+** `require_permission(Permission.STATS_READ_SALON)` (deuxième
     consommateur, après #39). `salon_id` du chemin ; le dépôt refiltre en SQL.
   - Query param **`date` optionnel** (`AAAA-MM-JJ`) : défaut = jour courant `Africa/Abidjan`
     (`datetime.datetime.now(SALON_TIMEZONE).date()`, via un helper de module). Une `date` mal formée
     → `422` (validation FastAPI). *(Aucune borne de plage : les périodes sont dérivées.)*
   - Réponse `RevenueSummaryResponse` (Pydantic **explicite**, jamais `orm_mode`/`extra`) :
     `reference_date`, `currency`, et `day` / `week` / `month` : chacun un `RevenuePeriodResponse`
     (`date_from`, `date_to`, `total`). `total` sérialisé en **chaîne décimale** (`NUMERIC(12,2)`,
     jamais un flottant — patron #35/#37). Documenter OpenAPI (`summary`, `responses` 200/401/403/422)
     sur le patron de `summarize_salon_transactions`. **Aucune PII** au schéma (montants + dates +
     devise **uniquement**).
   - DI : `get_cash_journal_repository` (réutiliser celui de `payments.py` **ou** en dupliquer un
     local minimal ; surchargeable en test via `app.dependency_overrides`).
   - Monter dans `main.py` : `app.include_router(stats_router)` avec un commentaire d'assemblage sur
     le patron #37 (lecture salon-scopée, `STATS_READ_SALON`, jamais publique).
   *(Alternative : ajouter la route à `payments.py` — voir Open Questions. #39 a placé sa route stats
   sur le router de sa source de données ; ici la source est le journal de caisse, servi par
   `payments.py`. Recommandation : un `stats.py` dédié, pour séparer la surface `STATS_READ_SALON` de
   la surface caisse `CASH_JOURNAL_READ`/`PAYMENT_RECORD` et préparer l'Épic 6.)*

### Web (tranche dashboard)

6. **Gateway (`web-dashboard/src/adapters/api/`).**
   Ajouter `revenueSummary(salonId, dateIso)` au `http-payment-gateway.ts` **ou** un
   `http-stats-gateway.ts` dédié : `GET {API}/salons/{id}/revenue/summary?date=…`, jeton du cookie
   `httpOnly` (jamais exposé), mapping de la réponse en type de domaine `RevenueSummary` (dans
   `src/domain/payments/`). Les montants restent des **chaînes** décimales côté transport (pas de
   flottant JS).

7. **Type de domaine + formatage (`web-dashboard/src/domain/payments/`).**
   Type `RevenueSummary` (`referenceDate`, `currency`, `day`/`week`/`month` = `{ dateFrom, dateTo,
   total }`) et un formateur monétaire **XOF** (entier, séparateur de milliers ; XOF n'a pas de
   sous-unité usuelle — arrondi/affichage à confirmer, cf. Open Questions). Réutiliser le formateur
   existant s'il y en a un (`record-payment-form.tsx` / `transaction-history.tsx` affichent déjà des
   montants).

8. **Tuiles CA + page (`src/adapters/ui/revenue-tiles.tsx` + `app/(gerant)/gerant/page.tsx`).**
   - Composant `revenue-tiles.tsx` (patron `daily-summary-tiles.tsx`) : trois tuiles **Jour ·
     Semaine · Mois**, chacune affichant le total formaté et, en légende, la plage (`date_from →
     date_to`).
   - Étendre le Server Component `page.tsx` (#39) : après le chargement de `dailySummary`, charger
     `revenueSummary(salon.id, today)` (même jeton serveur) et rendre `<RevenueTiles>` **sous** les
     tuiles RDV. Gérer « aucun salon » (déjà géré par #39) et « erreur backend » (panneau d'erreur
     existant). Un salon **sans activité** → tuiles à `0` XOF (pas une erreur).

## Affected Files / Packages / Modules

**Backend (`backend/coiflink_api/`)**
- `domain/revenue.py` — **créer** (`RevenuePeriodTotal`, `RevenueSummary`, `day_bounds`/`week_bounds`/
  `month_bounds`, `__all__`).
- `application/ports/cash_journal_repository.py` — **modifier** (ajouter `net_revenue_between` au
  `Protocol`).
- `application/revenue.py` — **créer** (`SummarizeRevenue`).
- `adapters/outbound/persistence/cash_journal_repository.py` — **modifier** (implémenter
  `net_revenue_between`).
- `adapters/inbound/stats.py` — **créer** (router + schémas `RevenueSummaryResponse` /
  `RevenuePeriodResponse` + helper « jour courant » + route `GET /salons/{salon_id}/revenue/summary`).
- `main.py` — **modifier** (`include_router(stats_router)` + commentaire d'assemblage).
- `domain/time_window.py`, `domain/permissions.py`, `domain/payment.py` (`DEFAULT_CURRENCY`),
  `domain/enums.py` (`CashOperationType`), `adapters/inbound/security.py` — **lire** (réutilisation ;
  pas de modification attendue).
- `backend/README.md` — **modifier** (documenter la route + deuxième usage de `STATS_READ_SALON`).

**Web (`web-dashboard/`)**
- `app/(gerant)/gerant/page.tsx` — **modifier** (charger + rendre les tuiles CA).
- `src/adapters/api/http-payment-gateway.ts` (ou nouveau `http-stats-gateway.ts`) — **modifier/créer**.
- `src/domain/payments/revenue.ts` (ou fichier proche) — **créer** (type `RevenueSummary` + formatage).
- `src/adapters/ui/revenue-tiles.tsx` — **créer** (tuiles KPI).
- `src/domain/appointment/planning-view.ts` — **lire** (`todayIso`).
- `web-dashboard/README.md` — **modifier** (le dashboard affiche désormais le CA jour/semaine/mois).

**Tests** — voir Testing Plan.

## API / Interface Changes

**Nouvelle route HTTP (backend) :**

`GET /salons/{salon_id}/revenue/summary`
- **Auth** : `Principal` requis (deny-by-default). Permission **`STATS_READ_SALON`** (`MANAGER`) **+**
  portée salon (`require_salon_scope`).
- **Query** : `date` *optionnel* (`AAAA-MM-JJ`) — date de **référence** ; défaut = aujourd'hui
  (`Africa/Abidjan`).
- **200** — corps :
  ```json
  {
    "reference_date": "2026-08-02",
    "currency": "XOF",
    "day":   { "date_from": "2026-08-02", "date_to": "2026-08-02", "total": "35000.00" },
    "week":  { "date_from": "2026-07-27", "date_to": "2026-08-02", "total": "210000.00" },
    "month": { "date_from": "2026-08-01", "date_to": "2026-08-31", "total": "185000.00" }
  }
  ```
  (`total` = chaîne décimale ≥ `0.00` **ou négative** si les corrections excèdent les paiements sur la
  période ; semaine = lundi→dimanche contenant `reference_date` ; mois = mois civil contenant
  `reference_date`).
- **401** jeton absent/invalide · **403** rôle insuffisant **ou** salon hors périmètre (générique,
  aucun oracle) · **422** `date` mal formée.

**OpenAPI** : documenté via les schémas Pydantic + `responses`. Aucune autre surface (CLI, autres
endpoints) modifiée.

**Web** : nouveau contenu de la page `/gerant` (pas d'URL nouvelle). Aucun Route Handler BFF ajouté si
le fetch serveur direct est retenu (patron #39).

## Data Model / Protocol Changes

**None.** Aucune table, colonne, contrainte ou migration Alembic. La feature lit la table
`cash_journal` existante ; l'index `ix_cash_journal_salon_id (salon_id, created_at)` couvre déjà la
requête `SUM` par intervalle. `CashOperationType`, `PaymentStatus` et `ROLE_PERMISSIONS` sont
réutilisés tels quels (pas de nouvelle valeur d'énum, pas de nouvelle permission).

## Security & Privacy Considerations

- **Isolation §11.2 (multi-tenant).** Route salon-scopée : `require_salon_scope` (portée propriété du
  gérant) **+** re-filtrage `WHERE salon_id = :salon_id` **inconditionnel** en SQL (défense en
  profondeur). Un salon hors périmètre est un **403 générique** indiscernable (aucun oracle
  d'existence). Le dépôt ne somme **jamais** les lignes d'un autre salon.
- **Deny-by-default (#12 / ADR-0015).** La route porte une garde de `Principal`
  (`require_permission(STATS_READ_SALON)`) ; **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` (une donnée
  financière n'est jamais publique) ; l'invariant testé `unprotected_routes(app) == []` reste vert.
- **RBAC inchangé.** `STATS_READ_SALON` est **déjà** au `MANAGER` (et seulement lui) — **ne pas**
  modifier `ROLE_PERMISSIONS`. `CLIENT`/`HAIRDRESSER`/`ADMIN` ne l'ont pas → 403. (L'`ADMIN` a la vue
  **plateforme** #37, pas cette lecture d'exploitation salon.)
- **Minimisation des données (§11.3).** La réponse ne contient **que** des montants (`Decimal` en
  chaîne), des dates et une devise : **aucun** `client_id`, nom de client, `reference`,
  `recorded_by`/`performed_by`, `appointment_id`, ni ligne de paiement/journal. Le CA est calculé en
  base (`SUM`), pas en rapatriant les lignes. Le schéma Pydantic est **explicite** et **figé par un
  test** qui échoue si un champ interdit apparaît (patron #37).
- **Exactitude monétaire.** Somme **en `Decimal`** quantifiée au centime (`NUMERIC(12,2)`) — **jamais**
  un flottant, backend **et** web (transport en chaîne). Cohérente avec le « montant net » #37 et le
  journal #34.
- **Logs / redaction.** Aucun secret ni PII dans cette surface ; ne pas logger le corps. Le jeton
  reste dans le cookie `httpOnly` côté web (invariant #14), jamais exposé au navigateur ni passé en
  query.
- **Coût / latence (§12.1).** **Trois** requêtes indexées agrégées, bornées à des périodes fixes
  (jour/semaine/mois) — pas de plage arbitraire, donc pas de garde `MAX_*_RANGE` nécessaire. Charge
  négligeable. *(Micro-optimisation possible — un seul passage `SUM … FILTER` par période — laissée en
  option ; non requise au MVP.)*

## Testing Plan

**Backend — domaine (pur, sans I/O) — `domain/revenue.py`**
- `week_bounds` : un mardi → (lundi, dimanche) corrects ; un **dimanche** → semaine se terminant ce
  jour (borne haute = le dimanche lui-même) ; un **lundi** → `date_from == d`. Semaine à cheval sur
  deux mois. Semaine à cheval sur deux **années** (fin décembre).
- `month_bounds` : mois de 28 (février non bissextile), **29** (février bissextile, ex. 2028), 30 et
  31 jours ; `date_from == 1er`, `date_to == dernier jour`.
- `day_bounds` : `(d, d)`. Invariants : `week` ⊇ `day` ⊇ (rien), `month` ⊇ `day`, toutes bornes
  `date_from ≤ date_to`.

**Backend — application — `SummarizeRevenue` (fake `CashJournalRepository`)**
- Assemble un `RevenueSummary` cohérent : passe **les bonnes bornes UTC** au port pour chaque période
  (jour/semaine/mois), en dérivant de `day_start_utc`/`day_end_utc` ; renvoie les trois totaux à leur
  place ; devise `XOF` ; aucune écriture/audit déclenchée. Vérifier que le fake reçoit exactement les
  bornes attendues (frontières de jour civil `Africa/Abidjan`).

**Backend — inbound (FastAPI `TestClient`)**
- `200` : totaux corrects pour un salon peuplé (mélange de lignes `PAYMENT` et d'une `ADJUSTMENT`
  négative → le CA de la période **baisse**) ; toutes les périodes présentes ; `total` en chaîne.
- **Paramètre `date`** : sans `date` → jour courant `Africa/Abidjan` ; avec `date` explicite → périodes
  dérivées de cette date ; une ligne d'une **autre** semaine/mois **exclue** de la période concernée.
- **« Annulés exclus »** : un **RDV `CANCELLED`** (donc sans paiement/ligne de journal) ne contribue
  **pas** ; un paiement `VALIDATED` normal contribue. *(Si l'Open Question « exclusion stricte §8.1 »
  est tranchée « oui », ajouter : un paiement rattaché à un RDV passé `CANCELLED` **après** encaissement
  est exclu — sinon documenter qu'il reste compté.)*
- **Corrections (#34)** : après un `ADJUSTMENT` négatif sur un paiement de la période, le CA net =
  paiement − |ajustement| (cohérent avec le « montant net » #37).
- `403` : `CLIENT`/`HAIRDRESSER`/`ADMIN` (sans `STATS_READ_SALON`) ; gérant d'**un autre salon** (hors
  portée) → 403 générique.
- `401` : sans jeton.
- `422` : `date` mal formée.
- **Isolation** : une ligne de journal d'un **autre salon** dans la même période n'apparaît **pas**
  dans le CA.
- **Non-PII** : la réponse ne contient aucune clé autre que `reference_date`/`currency`/`day`/`week`/
  `month` (et `date_from`/`date_to`/`total` par période) — test qui **échoue** si un champ interdit
  apparaît.

**Backend — e2e PostgreSQL réel** *(patron des suites `test(#…)` récentes, cf.
`test_admin_transactions_e2e.py`, `test_daily_summary_e2e.py`, `specs/supervision-agregee-transactions-admin.md`)*
sur `coiflink-e2e-pg` (port 55433) : couvrir le chemin SQL réel du `SUM` par intervalle sur
`cash_journal`, l'usage de l'index `(salon_id, created_at)`, la **frontière de jour civil**
`Africa/Abidjan` (une ligne à 23:30 UTC un jour donné tombe dans le **bon** jour civil), et le net des
corrections.

**Web (`web-dashboard/test/`, Vitest)**
- Rendu `/gerant` : tuiles **Jour/Semaine/Mois** avec les valeurs/plages du gateway, **sous** les
  tuiles RDV (#39) ; cas « 0 activité » → tuiles à `0` XOF ; cas « erreur backend » → panneau d'erreur.
- Gateway `revenueSummary` : construit la bonne URL (`date` = `todayIso()` par défaut), passe le jeton
  en en-tête **serveur** (jamais exposé), mappe la réponse (montants en chaîne, pas de flottant) ;
  erreur backend gérée proprement.
- Formatage monétaire XOF (entier, séparateur de milliers ; cohérent avec l'affichage existant).

## Documentation Updates

- **`backend/README.md`** — ajouter la route `GET /salons/{salon_id}/revenue/summary` à la liste des
  endpoints et **signaler le deuxième usage de `STATS_READ_SALON`** (après #39).
- **`web-dashboard/README.md`** — noter que le dashboard `/gerant` affiche désormais le **CA
  jour/semaine/mois** (US-6.2), sous le décompte RDV du jour (US-6.1).
- **`README.md` racine** — ajouter US-6.2 (#40) à l'avancement du MVP (Épic 6), cohérent avec le suivi
  des issues livrées (M5).
- **ADR** — *a priori* **aucun ADR nouveau** : route additive dans un module existant, patron
  d'agrégation « montant net = somme signée `cash_journal` » **déjà acté par ADR-0029/#37**, réutilisé
  ici en version **salon-scopée**. Si l'équipe veut fixer la **sémantique des périodes** (semaine
  lundi→dimanche, mois civil, fuseau) ou la convention « endpoints stats salon `*/summary` de l'Épic
  6 », un court ADR pourra la documenter — à confirmer (Open Questions).
- **BACKLOG.md** — marquer #40 livré le cas échéant (géré hors phase de code par le pipeline).

## Risks and Open Questions

1. **Source & sens du CA : net des corrections (recommandé) vs brut.** Recommandation : **CA = somme
   signée des lignes `cash_journal` `PAYMENT`/`ADJUSTMENT`** — donc **net des corrections** (#34), en
   cohérence directe avec le « montant net » de #37. C'est la définition la plus honnête pour un KPI de
   revenus. Alternative « brut » : sommer `payments.amount WHERE status = VALIDATED`, mais un paiement
   corrigé porte encore son montant **d'origine** (`status = ADJUSTED`, cf. #35) → il faudrait alors
   soustraire les ajustements pour ne pas surcompter, ce qui **revient** au journal net. Confirmer que
   « net » est l'attendu.
2. **« Annulés exclus » — lecture par construction (recommandé) vs stricte §8.1.** Un **RDV annulé**
   n'a pas de paiement, donc pas de ligne de journal, donc **est exclu par construction** — ce qui
   satisfait l'AC #40 et §8.1 dans le flux normal. **Cas limite** : `RecordPayment` (#33) **ne vérifie
   pas** le statut du RDV — un paiement pourrait théoriquement exister pour un RDV encaissé **puis**
   passé `CANCELLED`. Faut-il **exclure défensivement** les paiements dont le RDV lié est `CANCELLED`
   (jointure `cash_journal → payments → appointments.status`) ? Recommandation MVP : **non** (garder le
   CA « à partir des paiements », simple et aligné #37) — mais **confirmer** ; si « oui », la requête
   gagne une jointure et un filtre `status != CANCELLED` (à tester explicitement).
3. **Types d'opération dans la somme.** Recommandation : sommer **uniquement** `PAYMENT` + `ADJUSTMENT`
   (les seuls produits au MVP ; `REFUND`/`CASH_OPENING`/`CASH_CLOSING` ne sont pas du CA). #37 somme
   **toutes** les lignes (numériquement identique aujourd'hui). Divergence assumée et **plus correcte
   sémantiquement** si ces types apparaissent un jour — confirmer l'alignement souhaité avec #37.
4. **Définition de « semaine ».** Recommandation : **semaine civile lundi → dimanche** contenant la
   date de référence (usage FR/CI, standard ISO du lundi). Alternatives : semaine glissante (7 derniers
   jours) ou dimanche→samedi. À **confirmer** ; c'est une règle métier visible par le gérant.
5. **Forme de l'endpoint : 3 périodes en une réponse (recommandé) vs paramétré vs range libre.**
   Recommandation : **une réponse portant les trois totaux** (jour/semaine/mois) — colle exactement à
   l'AC et au dashboard, garde la sémantique des périodes côté serveur, 1 aller-retour. Alternatives
   écartées : `?granularity=day|week|month` (3 appels), ou `?date_from&date_to` (déplace la règle de
   période vers le web). Confirmer.
6. **Foyer de la route : `stats.py` dédié (recommandé) vs `payments.py`.** Recommandation : nouveau
   `adapters/inbound/stats.py` (sépare `STATS_READ_SALON` de la caisse, prépare l'Épic 6). #39 a placé
   sa route stats sur `appointments.py` (routeur de sa source) ; par symétrie, `payments.py`
   (routeur du journal de caisse) serait acceptable et **plus léger** (DI déjà câblée). Trancher.
7. **Foyer du dépôt : extension de `CashJournalRepository` (recommandé) vs port stats dédié.**
   Recommandation : **étendre `CashJournalRepository`** (lecture salon-scopée sur `cash_journal` — son
   foyer naturel ; l'inverse du choix #37, justifié car #40 est salon-scopé). Alternative : un port
   `SalonStatsRepository` dédié (plus « propre » pour un futur module stats, mais plus de surface).
8. **Périmètre : backend + web, ou backend seul ?** L'AC #40 parle de « voir » le CA → la **tranche
   web** (tuiles dashboard) est attendue. Confirmer qu'elle est dans la même issue (recommandé) ou
   différée (comme la partie web de #34/#36/#37).
9. **Affichage/arrondi XOF.** Le XOF n'a pas de sous-unité usuelle mais la colonne est `NUMERIC(12,2)`.
   Le backend renvoie 2 décimales (source de vérité) ; le web décide de l'affichage (entier vs 2
   décimales). Recommandation : afficher **en entier** avec séparateur de milliers, sans altérer la
   valeur transportée. À confirmer.
10. **Fuseau « aujourd'hui / frontières de période ».** Figé à `Africa/Abidjan` (UTC+0, convention
    #21). Un salon hors de ce fuseau verrait des frontières décalées — hors périmètre MVP (convention
    globale). La conversion `created_at` (timestamp) ↔ jour civil **doit** passer par
    `time_window.day_start_utc`/`day_end_utc` (piège classique : ne pas comparer un `date` à un
    `datetime` UTC brut).
11. **Collision de routage.** Vérifier que `/salons/{salon_id}/revenue/summary` (littéral) n'entre pas
    en conflit avec une route paramétrée du même préfixe ; monter le router `stats` sans ambiguïté
    (test de non-régression sur `unprotected_routes` + résolution de route).

## Implementation Checklist

**Backend**
1. `domain/revenue.py` : créer `RevenuePeriodTotal`, `RevenueSummary`, et les fonctions pures
   `day_bounds` / `week_bounds` (lundi→dimanche) / `month_bounds` (mois civil, `calendar.monthrange`) ;
   `__all__`.
2. `application/ports/cash_journal_repository.py` : ajouter `net_revenue_between(salon_id, *,
   created_at_from, created_at_to) -> Decimal` au `Protocol` (docstring : somme signée `PAYMENT`/
   `ADJUSTMENT`, isolation §11.2 en SQL, `0.00` si vide).
3. `application/revenue.py` : créer `SummarizeRevenue(cash_journal_repository)` —
   `execute(salon_id, reference_date) -> RevenueSummary` (bornes domaine → UTC via `time_window` → 3×
   `net_revenue_between` → assemblage, aucune écriture/audit) ; `__all__`.
4. `adapters/outbound/persistence/cash_journal_repository.py` : implémenter `net_revenue_between`
   (`select(func.coalesce(func.sum(amount), 0)).where(salon_id, created_at BETWEEN, operation_type IN
   (PAYMENT, ADJUSTMENT))`, quantifié `Decimal("0.01")`).
5. `adapters/inbound/stats.py` : créer le router `/salons` (tag `stats`), les schémas
   `RevenuePeriodResponse` / `RevenueSummaryResponse` (explicites, `total` en chaîne décimale), un
   helper « jour courant `Africa/Abidjan` », et la route `GET /salons/{salon_id}/revenue/summary`
   (gardes `require_salon_scope` + `require_permission(STATS_READ_SALON)`, `date` optionnel, OpenAPI
   documenté). DI `get_cash_journal_repository`.
6. `main.py` : `include_router(stats_router)` + commentaire d'assemblage (lecture salon-scopée,
   `STATS_READ_SALON`, jamais publique). Vérifier `unprotected_routes(app) == []` et le non-conflit de
   routage.
7. Tests domaine (bornes de période) + application (bornes UTC passées au port) + inbound
   (200/401/403/422, isolation, non-PII, `date` défaut, net des corrections, « annulés exclus »).
8. Suite e2e PostgreSQL réelle du chemin `SUM` par intervalle (frontière de jour civil, index, net).
9. Lint/format (`ruff check`) et gate de tests du repo (backend) au vert.

**Web**
10. Ajouter le type `RevenueSummary` (`src/domain/payments/`) + formateur XOF, et l'appel
    `revenueSummary(salonId, dateIso)` au gateway (jeton serveur, jamais exposé ; montants en chaîne).
11. Créer `src/adapters/ui/revenue-tiles.tsx` (tuiles **Jour/Semaine/Mois** + plages) et étendre
    `app/(gerant)/gerant/page.tsx` pour charger le CA (`todayIso()`) et rendre `<RevenueTiles>` sous
    les tuiles RDV ; gérer « 0 activité » et « erreur backend ».
12. Tests Vitest (page + gateway + formatage).

**Documentation**
13. Mettre à jour `backend/README.md`, `web-dashboard/README.md`, `README.md` racine (avancement
    Épic 6 / US-6.2). Aucun ADR sauf décision explicite (Open Questions 2/3/4).
