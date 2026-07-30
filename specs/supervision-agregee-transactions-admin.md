# Supervision agrégée des transactions (admin) (US-5.6, #37)

> Épic 5 (Encaissement) · Priorité **Should** · Effort **M** · PRD §6 / §11.2 / §11.3
> Dépend de **#34** (journal de caisse horodaté). Repose aussi sur #33 (paiements) et
> le RBAC #12 (permission `STATS_READ_PLATFORM` déjà réservée à l'`ADMIN`).

## Problem Statement

L'**Admin CoifLink** (super-administrateur plateforme, PRD §2/§4.1) doit pouvoir
**superviser l'activité d'encaissement de tous les salons** sans être un exploitant
d'un salon. Aujourd'hui, toutes les lectures financières livrées (journal de caisse
#34, historique filtrable #35, écarts #36) sont **salon-scopées** : elles sont
gardées par `CASH_JOURNAL_READ` (détenue **uniquement** par le `MANAGER`) et montées
sous `/salons/{salon_id}/…`, où `require_salon_scope` bloque tout accès inter-salons
(§11.2). L'admin — qui n'a **ni** `CASH_JOURNAL_READ` **ni** de salon dans sa portée —
ne peut donc consulter **aucune** de ces surfaces, et il n'existe encore **aucune**
route de supervision plateforme des transactions.

Le besoin est une **vue agrégée par salon** : combien de transactions, quel montant
encaissé (net des corrections), par salon — *sans* exposer les **détails sensibles
inutiles** d'un paiement (identité du client, référence, auteur de la saisie, lignes
individuelles). Le critère d'acceptation du backlog est :

> L'admin voit des agrégats par salon **sans PII de paiement superflue** (§11.2/§11.3).

## Goals

- Exposer une **lecture plateforme** réservée à l'`ADMIN` qui renvoie, **par salon**,
  des **agrégats** de transactions : nombre de paiements, nombre de corrections
  (ajustements), **montant total net** encaissé, devise, et l'**identité métier** du
  salon (id + nom).
- Gérer la lecture par la **permission `STATS_READ_PLATFORM`** (déjà réservée à
  l'`ADMIN` dans `ROLE_PERMISSIONS`) — **sans modifier la matrice** des droits ni
  élargir `CASH_JOURNAL_READ` au-delà du `MANAGER`.
- Garantir l'**absence de PII de paiement** dans la réponse : **aucun** `client_id`,
  nom de client, `reference`, `recorded_by`, ni ligne de paiement individuelle — que
  des **compteurs et sommes agrégés** (§11.3).
- Rester **cohérent avec le journal de caisse** (#34) : le **montant net** dérive de
  la même source de vérité (lignes `cash_journal` signées : `PAYMENT` positif,
  `ADJUSTMENT` signé), de sorte qu'un paiement corrigé est correctement reflété.
- **Filtrage optionnel par plage de dates** (jour civil `Africa/Abidjan`, convention
  #21) et **pagination bornée** (garde de coût §12.1), sur le patron des lectures
  caisse existantes.
- Préserver le **deny-by-default** (#12/ADR-0015) : la nouvelle route est protégée par
  une garde de `Principal`, **jamais** ajoutée à `PUBLIC_ROUTE_PATHS`.

## Non-Goals

- **Aucun détail transactionnel** : ce n'est **pas** un « historique inter-salons ».
  Aucune ligne de paiement, aucun `client_id`/nom/`reference`/auteur n'est renvoyé.
  Le drill-down vers le détail d'un salon n'est **pas** l'objet de cette US.
- **Aucun KPI temporel avancé** (CA jour/semaine/mois, séries, graphiques) : ceux-ci
  relèvent de l'épic 6 / dashboard (#40 et suivants), hors périmètre ici.
- **Aucune écriture** : lecture pure, **aucun** audit §11.4 (comme #34/#35/#36, la
  consultation n'est pas journalisée), aucun verbe destructif.
- **Aucune modification de la matrice `ROLE_PERMISSIONS`** ni des droits du `MANAGER`
  / `HAIRDRESSER` / `CLIENT`.
- **UI web admin (`/admin`) : hors périmètre backend de cette US** — voir *Risks and
  Open Questions*. La zone `/admin` du `web-dashboard` **n'existe pas encore** (seules
  `(gerant)` et `(coiffeur)` sont livrées). Un livrable **backend-first** est recommandé
  (parité avec #36, livré « côté backend »). Toute tranche web est optionnelle et à
  confirmer.

## Relevant Repository Context

**Stack (figée par ADR).** Backend **Python FastAPI**, **architecture hexagonale**
(ADR-0008) : `domain/` (pur) → `application/` (cas d'usage + `ports/`) →
`adapters/inbound|outbound/`. Persistance **PostgreSQL 16 / SQLAlchemy + Alembic**
(ADR-0004/0009). RBAC **deny-by-default** (ADR-0015, #12).

**Permissions & rôle admin (déjà en place).**
- `domain/permissions.py` : l'`ADMIN` détient déjà `SALON_READ_ANY`,
  `SALON_SET_STATUS`, `USER_MANAGE` et **`STATS_READ_PLATFORM`**. Le `MANAGER` seul
  détient `PAYMENT_RECORD` et `CASH_JOURNAL_READ`. La matrice est **fermée** et figée
  par des tests ; `STATS_READ_PLATFORM` n'est **encore utilisée par aucune route** —
  cette US en est le **premier consommateur**.
- `application/authorization.py` : `AccessPolicy.scope_of` **court-circuite** le port
  pour l'`ADMIN` (`SalonScope.platform()`). `require_permission(...)` (dans
  `adapters/inbound/security.py`) suffit pour une lecture plateforme — **ne pas**
  utiliser `require_salon_scope` (l'admin n'a pas de salon dans sa portée « propriété »
  et la route n'est pas montée sous `/salons/{salon_id}`).

**Surfaces caisse existantes (à imiter, à ne pas dupliquer).**
- `adapters/inbound/payments.py` — routes salon-scopées `POST …/payments`,
  `GET …/payments` (#35), `GET …/cash-journal` (#34), `GET …/cash-discrepancies` (#36),
  `POST …/payments/{id}/adjustments`. Patron d'injection de dépôts + traduction des
  erreurs de domaine, schémas Pydantic documentés (OpenAPI).
- `application/ports/payment_repository.py` — port `PaymentRepository` (méthodes
  **toutes** salon-scopées ; **aucun** `delete`, invariant append-only §8.2). Bornes de
  pagination `PAYMENTS_LIMIT_DEFAULT/MIN/MAX` = 50/1/200.
- `application/ports/cash_journal_repository.py` — port du journal (`CASH_JOURNAL_LIMIT_*`
  = 50/1/200).
- `domain/transaction.py` — `TransactionFilter` + `validate_transaction_filter` :
  **modèle de référence** de la conversion « jour civil `Africa/Abidjan` → bornes UTC
  inclusives » (`_day_start_utc`/`_day_end_utc`, `SALON_TIMEZONE`) et des messages
  d'erreur **neutres**. La logique de fuseau à réutiliser vit ici.
- `domain/discrepancy.py` + `application/discrepancies.py` — patron du plus récent
  ajout de lecture (#36) : domaine pur (VO + filtre validé), port de rapprochement,
  use case pur, route.

**Modèle de données (existant, `persistence/models.py`).**
- `payments` : `id`, `salon_id`, `client_id?`, `amount NUMERIC(12,2)`, `currency`,
  `payment_method`, `status` (`VALIDATED`/`ADJUSTED`), `recorded_by`, `appointment_id?`,
  `service_id?`, `reference?`, `created_at`. Index `ix_payments_salon_id (salon_id,
  created_at)`. Contrainte `amount >= 0`.
- `cash_journal` : `id`, `salon_id`, `operation_type` (`PAYMENT`/`ADJUSTMENT`/…),
  `amount NUMERIC(12,2)` **signé**, `currency`, `transaction_id? → payments.id`,
  `performed_by`, `description?`, `created_at`. Index `ix_cash_journal_salon_id
  (salon_id, created_at)`.
- `salons` : `id`, `name`, `status` (`ACTIVE`/`INACTIVE`), `owner_id`, … Index
  `ix_salons_status`.

**Enums** (`domain/enums.py`) : `PaymentStatus.VALIDATED/ADJUSTED`,
`CashJournalOperationType.PAYMENT/ADJUSTMENT`, `PaymentMethod.CASH/MOBILE_MONEY_MANUAL/
CARD_MANUAL`, `SalonStatus.ACTIVE/INACTIVE`, devise MVP **XOF** (`DEFAULT_CURRENCY`).

**Assemblage.** `main.py` : `FastAPI(dependencies=[Depends(require_authenticated)])`
(deny-by-default global) + `include_router(...)` par adapter entrant. L'invariant
`unprotected_routes(app) == []` est **testé** : toute route ajoutée doit porter une
garde de `Principal` ou être publique-listée (elle ne le sera pas ici).

**Décisions encore ouvertes** (voir *Risks*) : (a) **agrégat net vs brut** — recommandé
**net via `cash_journal`** ; (b) **granularité devise** (mono-devise XOF au MVP) ;
(c) **existence/étendue d'une UI `/admin`** (non livrée) ; (d) **inclure ou non les
salons sans activité** dans la liste.

## Proposed Implementation

Ajouter une **lecture plateforme** hexagonale, gardée par `STATS_READ_PLATFORM`, qui
agrège les transactions **par salon** à partir de la **source de vérité du journal de
caisse** (#34), sans exposer aucune PII de paiement.

### 1. Domaine — `domain/platform_transactions.py` (nouveau, pur)

- **VO `SalonTransactionSummary`** (`@dataclass(frozen=True)`), agrégat **d'un** salon :
  - `salon_id: uuid.UUID`
  - `salon_name: str` *(identité métier du salon — **pas** une PII de paiement ; l'admin
    a déjà `SALON_READ_ANY`)*
  - `payment_count: int` *(nombre de lignes `PAYMENT` du journal, = paiements
    enregistrés)*
  - `adjustment_count: int` *(nombre de lignes `ADJUSTMENT`, = corrections)*
  - `total_amount: decimal.Decimal` *(**somme signée** des `cash_journal.amount` : net
    des corrections ; `NUMERIC(12,2)`, jamais un flottant)*
  - `currency: str`
  - **Aucun** champ identifiant une personne (pas de `client_id`, nom, `reference`,
    `recorded_by`).
- **VO `PlatformSummaryFilter`** + `validate_platform_summary_filter(...)` : filtre de
  **plage de dates optionnelle** (`date_from`/`date_to`, jours civils `Africa/Abidjan`),
  validé et **converti en bornes UTC inclusives** (`created_at_from`/`created_at_to`),
  strictement sur le patron de `validate_transaction_filter` (plage ordonnée →
  `InvalidPlatformSummaryFilter`, message **neutre**). **Réutiliser** les helpers de
  fuseau : extraire `SALON_TIMEZONE`, `_day_start_utc`, `_day_end_utc` de
  `domain/transaction.py` vers un petit module partagé (p. ex.
  `domain/time_window.py`) importé par les deux, **ou** importer directement depuis
  `domain/transaction.py` — décision d'implémentation mineure, ne pas dupliquer la
  logique de fuseau.
- Nouvelle erreur `InvalidPlatformSummaryFilter` dans `domain/errors.py`.

### 2. Port — `application/ports/platform_transaction_repository.py` (nouveau)

Un port **dédié** (les méthodes existantes de `PaymentRepository`/`CashJournalRepository`
sont **inconditionnellement** salon-scopées ; l'agrégat plateforme **groupe sur tous
les salons**, il ne leur appartient pas) :

```python
class PlatformTransactionRepository(Protocol):
    def summary_by_salon(
        self, *, filter: PlatformSummaryFilter, limit: int, offset: int
    ) -> tuple[SalonTransactionSummary, ...]: ...
    def count_salons(self, *, filter: PlatformSummaryFilter) -> int: ...
```

- `summary_by_salon` : agrège `cash_journal` **`GROUP BY salon_id`** (jointure
  `salons` pour `name`/`currency`), avec `payment_count = COUNT(*) FILTER (WHERE
  operation_type = 'PAYMENT')`, `adjustment_count = COUNT(*) FILTER (WHERE
  operation_type = 'ADJUSTMENT')`, `total_amount = SUM(amount)`. Bornes de dates
  appliquées **en SQL** sur `created_at`. Tri **déterministe** (recommandé
  `salon_name ASC, salon_id ASC`), `limit`/`offset` en SQL.
- `count_salons` : nombre de salons **distincts** apparaissant sous le même filtre
  (cohérent avec la page).
- Constantes de pagination `PLATFORM_SUMMARY_LIMIT_DEFAULT/MIN/MAX` = **50/1/200**
  (alignées sur les autres surfaces caisse).

### 3. Persistance — `adapters/outbound/persistence/platform_transaction_repository.py` (nouveau)

`SqlPlatformTransactionRepository(session)` implémentant le port en SQLAlchemy :
requête d'agrégation sur `cash_journal` jointe à `salons`, `GROUP BY salon_id,
salons.name`, `FILTER`/`SUM` comme ci-dessus, filtre de dates conditionnel, tri +
`limit`/`offset`. **Aucune** écriture, **aucun** commit (lecture pure). L'index
existant `ix_cash_journal_salon_id (salon_id, created_at)` couvre le groupement/filtre ;
**aucun nouvel index requis** (à réévaluer seulement si un plan de requête le justifie).

> **Choix de la source « journal » (et non `payments`)** : justifie la dépendance
> `#37 → #34`. La somme signée du journal donne le **net** (paiements − corrections),
> l'agrégat le plus fidèle. `payment_count`/`adjustment_count` proviennent des mêmes
> lignes, garantissant la cohérence avec la caisse. *(Alternative brute sur `payments`
> — cf. Open Questions.)*

### 4. Application — `application/platform_transactions.py` (nouveau)

Use case **pur** `SummarizeSalonTransactions` (dépend du **seul** port) :

```python
class SummarizeSalonTransactions:
    def __init__(self, repo: PlatformTransactionRepository) -> None: ...
    def execute(self, *, filter, limit, offset) -> tuple[tuple[SalonTransactionSummary, ...], int]:
        page = self._repo.summary_by_salon(filter=filter, limit=limit, offset=offset)
        total = self._repo.count_salons(filter=filter)
        return page, total
```

Lecture pure : **aucun** audit §11.4 (parité #34/#35/#36).

### 5. Adapter entrant — `adapters/inbound/admin.py` (nouveau router `/admin`)

- `router = APIRouter(prefix="/admin", tags=["admin"])`.
- **Route** : `GET /admin/transactions/summary`.
- **Garde** : `require_permission(Permission.STATS_READ_PLATFORM)` **uniquement** (pas
  de `require_salon_scope`). L'`ADMIN` est le seul rôle porteur → `403` générique pour
  `MANAGER`/`HAIRDRESSER`/`CLIENT` (aucun oracle), `401` sans jeton.
- **Query params** : `date_from?`, `date_to?` (jour civil `Africa/Abidjan`),
  `limit` (`ge=MIN, le=MAX`, défaut 50), `offset` (`ge=0`). Validation du filtre →
  `422` (`InvalidPlatformSummaryFilter`), message **neutre**.
- **Schémas Pydantic** documentés : `SalonTransactionSummaryResponse`
  (`salon_id`, `salon_name`, `payment_count`, `adjustment_count`, `total_amount`
  sérialisé en chaîne décimale, `currency`) et `SalonTransactionSummaryPageResponse`
  (`items`, `total`, `limit`, `offset`). **Aucun** champ PII.
- Injection : `get_platform_transaction_repository(session)`. Traduction d'erreur :
  `InvalidPlatformSummaryFilter → 422`.

### 6. Assemblage — `main.py`

`from coiflink_api.adapters.inbound.admin import router as admin_router` puis
`app.include_router(admin_router)`. **Ne pas** ajouter `/admin/...` à
`PUBLIC_ROUTE_PATHS` (la garde `require_permission` satisfait l'invariant
deny-by-default, vérifié par `unprotected_routes`).

### 7. Web admin (`web-dashboard`) — optionnel / hors périmètre par défaut

La zone `/admin` n'existe pas encore. Si (et seulement si) une tranche web est
confirmée, elle suivrait le patron BFF role-gardé du `web-dashboard` (route handler
`app/api/admin/...` proxifiant le backend avec le cookie `httpOnly`, page serveur
`app/(admin)/admin/...`). **À traiter comme un livrable séparé** (voir Open Questions),
et non dans le socle backend de cette US.

## Affected Files / Packages / Modules

**À créer (backend) :**
- `backend/coiflink_api/domain/platform_transactions.py` — VO `SalonTransactionSummary`,
  `PlatformSummaryFilter` + validation.
- `backend/coiflink_api/domain/time_window.py` *(optionnel)* — helpers de fuseau
  partagés extraits de `transaction.py` (sinon import direct).
- `backend/coiflink_api/application/ports/platform_transaction_repository.py` — port +
  constantes de pagination.
- `backend/coiflink_api/adapters/outbound/persistence/platform_transaction_repository.py`
  — implémentation SQL.
- `backend/coiflink_api/application/platform_transactions.py` — use case.
- `backend/coiflink_api/adapters/inbound/admin.py` — router `/admin`.
- Tests (voir *Testing Plan*).

**À modifier (backend) :**
- `backend/coiflink_api/domain/errors.py` — ajouter `InvalidPlatformSummaryFilter`.
- `backend/coiflink_api/main.py` — `include_router(admin_router)`.
- `backend/coiflink_api/domain/transaction.py` *(si extraction des helpers de fuseau)* —
  ré-exporter depuis `time_window.py` pour ne pas casser les imports existants.

**À lire (référence, non modifiés) :**
- `application/authorization.py`, `adapters/inbound/security.py`, `domain/permissions.py`,
  `domain/principal.py`, `adapters/inbound/payments.py`, `domain/transaction.py`,
  `application/ports/payment_repository.py`, `persistence/models.py`.

**Documentation :** `README.md` (§6 récit d'avancement), `docs/adr/` (ADR-0029 proposé),
`docs/adr/README.md` (index).

## API / Interface Changes

**Nouvel endpoint (backend) :**

`GET /admin/transactions/summary`

- **Auth** : Bearer JWT ; **permission requise** `STATS_READ_PLATFORM` (**ADMIN**
  seul). `401` sans jeton / jeton invalide ; `403` générique pour tout autre rôle
  (aucun oracle).
- **Query params** (tous optionnels) :
  - `date_from` (`date`, jour civil `Africa/Abidjan`),
  - `date_to` (`date`, jour civil `Africa/Abidjan`),
  - `limit` (`int`, `1..200`, défaut `50`),
  - `offset` (`int`, `>= 0`, défaut `0`).
- **`200` — corps** :

```json
{
  "items": [
    {
      "salon_id": "…uuid…",
      "salon_name": "Salon Belle Coupe",
      "payment_count": 42,
      "adjustment_count": 3,
      "total_amount": "615000.00",
      "currency": "XOF"
    }
  ],
  "total": 12,
  "limit": 50,
  "offset": 0
}
```

- **`422`** : plage de dates incohérente (`date_from > date_to`) ou mal formée
  (`InvalidPlatformSummaryFilter`) — message **neutre**.

Aucun autre endpoint, CLI ou signature publique n'est modifié.

## Data Model / Protocol Changes

**None.** Aucune migration Alembic : lecture pure agrégée sur les tables existantes
(`cash_journal`, `salons`). Aucun nouveau champ, aucune nouvelle table. L'ajout d'un
index n'est **pas** prévu (l'index `ix_cash_journal_salon_id (salon_id, created_at)`
couvre le groupement/filtre) ; à réévaluer uniquement sur preuve d'un plan de requête
défavorable.

## Security & Privacy Considerations

- **Autorisation (RBAC #12, ADR-0015)** : gardée par `STATS_READ_PLATFORM`, détenue par
  le **seul** `ADMIN` dans la matrice **fermée** `ROLE_PERMISSIONS` — **non modifiée**.
  `CASH_JOURNAL_READ` **reste** exclusivement au `MANAGER` (la supervision n'est pas
  l'exploitation, PRD §4.1). La route **ne réutilise pas** `require_salon_scope` : c'est
  une lecture **plateforme** légitime (l'admin voit tous les salons), pas un
  contournement d'isolation §11.2.
- **Non-PII (§11.3)** — cœur du critère d'acceptation : la réponse ne contient **que**
  des **agrégats** (compteurs, sommes) et l'**identité métier du salon** (`salon_id`,
  `salon_name`). **Jamais** : `client_id`, nom de client, `reference`, `recorded_by`,
  `owner_id`, ni **aucune** ligne de paiement individuelle. La sérialisation Pydantic
  liste des champs **explicites** (pas de fuite par `orm_mode`/`extra`) ; un test
  d'API **fige** la forme (absence des champs interdits).
- **Deny-by-default (#12)** : la route porte une garde de `Principal` et **n'est pas**
  publique-listée ; l'invariant `unprotected_routes(app) == []` la couvre
  automatiquement.
- **Messages de refus** : `401`/`403` **constants et génériques** (jamais `str(exc)`),
  aucun oracle sur l'existence d'un salon ou d'une transaction.
- **Non-journalisation (§11.3, ADR-0011)** : lecture → **aucun** audit §11.4, **aucun**
  log de montants/identifiants. Aucun secret ni PII ne transite en log.
- **Montants** : `Decimal`/`NUMERIC(12,2)`, sérialisés en **chaîne** (jamais un
  flottant) — parité #34/#35.
- **Garde de coût (§12.1)** : pagination bornée `1..200` ; agrégation et bornes **en
  SQL** (jamais en mémoire).

## Testing Plan

**Unitaires — domaine (`tests/`, sans I/O) :**
- `validate_platform_summary_filter` : plage valide → bornes UTC inclusives correctes
  (`Africa/Abidjan`) ; `date_from > date_to` → `InvalidPlatformSummaryFilter` ;
  `None` → « pas de contrainte » ; message **neutre** (ne reprend pas la valeur).
- Frontières de fuseau : un jour civil `Africa/Abidjan` mappe `[00:00:00,
  23:59:59.999999]` UTC (réutilise/miroir des tests de `transaction.py`).

**Unitaires — application (fake `PlatformTransactionRepository`) :**
- `SummarizeSalonTransactions.execute` renvoie `(page, total)` ; passe `filter/limit/
  offset` **tels quels** au port ; **aucune** écriture/audit.

**API / intégration (FastAPI `TestClient`, dépôts surchargés) :**
- `GET /admin/transactions/summary` — **`200`** pour un `ADMIN` actif ; **`403`** pour
  `MANAGER`, `HAIRDRESSER`, `CLIENT` (message générique) ; **`401`** sans jeton /
  jeton invalide ; **`403`** « Compte désactivé. » pour un admin non `ACTIVE`.
- **Forme de la réponse (non-PII)** : les items ne contiennent **que**
  `salon_id`, `salon_name`, `payment_count`, `adjustment_count`, `total_amount`,
  `currency` — un test **échoue** si un champ interdit (`client_id`, `reference`,
  `recorded_by`, nom de client…) apparaît.
- `limit`/`offset` hors bornes → `422` (garde Query) ; `date_from > date_to` → `422`.
- **Deny-by-default** : le test d'invariant existant (`unprotected_routes`) reste vert
  avec la route ajoutée (elle n'entre pas dans `PUBLIC_ROUTE_PATHS`).

**Intégration SQL réelle (PostgreSQL 16, chemin dépôt — patron des tests e2e caisse) :**
- Agrégation **correcte par salon** : `payment_count`/`adjustment_count`/`total_amount`
  sur des lignes `cash_journal` de plusieurs salons ; **net** vérifié = paiements +
  ajustements signés (un paiement corrigé fait **baisser** `total_amount` et **incrémente**
  `adjustment_count`).
- **Filtre de dates** inclusif aux bornes `Africa/Abidjan` ; **pagination**
  déterministe (tri stable, `total` cohérent avec la page).
- Un salon **sans transaction** : comportement conforme à la décision retenue (absent,
  vs présent à `0/0/0.00` — cf. Open Questions) — **fige** la décision par un test.

**Documentation :** vérifier que l'exemple OpenAPI du router correspond au schéma
(pas de champ PII).

## Documentation Updates

- **`README.md` §6** : ajouter le paragraphe d'avancement M4 pour #37 (endpoint
  `GET /admin/transactions/summary`, agrégats par salon, `STATS_READ_PLATFORM`,
  net via journal, non-PII), sur le patron des entrées #34/#35/#36.
- **ADR proposé `docs/adr/0029-supervision-agregee-transactions-admin.md`** *(à
  confirmer — cf. Risks)* : décision « lecture plateforme gardée par
  `STATS_READ_PLATFORM` + agrégat **net** via `cash_journal` + non-PII », avec le
  compromis net-vs-brut et le choix « hors `/salons/{salon_id}` ». Mettre à jour
  **`docs/adr/README.md`** (ligne 0029, issue #37).
- **OpenAPI** : docstrings + `responses` du router (générés automatiquement dans
  `/docs`) — décrire `401/403/422` et l'absence de PII.
- Le cas échéant, `web-dashboard/README.md` si une zone `/admin` est ouverte (sinon,
  ne rien affirmer d'inexistant).

## Risks and Open Questions

1. **Net (journal) vs brut (payments)** — *recommandé : net via `cash_journal`* (fidèle,
   justifie la dépendance #34). Alternative : sommer `payments.amount` (brut, ignore les
   corrections). **À confirmer.** Le VO/nommage (`total_amount` net) et les tests
   dépendent de ce choix.
2. **Salons sans activité** : les inclure (ligne `0/0/0.00`, `LEFT JOIN` depuis
   `salons`) **ou** ne lister que les salons ayant des transactions (`GROUP BY` sur
   `cash_journal`) ? *Recommandé : ne lister que les salons avec activité* (plus simple,
   pas de bruit) — **à confirmer** et **figer par un test**.
3. **Multi-devise** : MVP mono-devise **XOF**. Si des devises hétérogènes coexistaient,
   un `SUM` global serait faux — prévoir alors un groupement `(salon, currency)`.
   *Recommandé : supposer XOF et documenter l'hypothèse* ; à revoir si le modèle évolue.
4. **Périmètre UI `/admin`** : la zone web admin **n'existe pas**. Livrer **backend
   seul** (parité #36) est recommandé ; une UI admin est un livrable **séparé** et un
   **effort supplémentaire** non couvert par l'estimation M. **Décision produit à
   confirmer** avant d'ouvrir une tranche web.
5. **Filtres additionnels** (par `salon_id`, par `payment_method`, par `status`) :
   volontairement **hors périmètre** (agrégat par salon + plage de dates). À ajouter
   ultérieurement si demandé ; ne pas sur-concevoir maintenant.
6. **Tri par défaut** : `salon_name ASC` (lisible) vs `total_amount DESC` (« top salons »).
   *Recommandé : `salon_name ASC, salon_id ASC`* (déterministe, neutre) — à confirmer.
7. **ADR** : créer un ADR-0029 (cohérent avec la cadence #33/#34/#36 → ADR) **ou** se
   contenter du spec + README ? *Recommandé : ADR-0029* pour tracer le choix net-vs-brut
   et la garde plateforme.

## Implementation Checklist

1. **Domaine** — créer `domain/platform_transactions.py` : `SalonTransactionSummary`
   (frozen, sans PII), `PlatformSummaryFilter` + `validate_platform_summary_filter`
   (plage `Africa/Abidjan` → bornes UTC inclusives, message neutre). Réutiliser les
   helpers de fuseau (extraction vers `domain/time_window.py` **ou** import depuis
   `domain/transaction.py`, sans duplication).
2. **Erreurs** — ajouter `InvalidPlatformSummaryFilter` dans `domain/errors.py`.
3. **Port** — créer `application/ports/platform_transaction_repository.py` :
   `PlatformTransactionRepository` (`summary_by_salon`, `count_salons`) +
   `PLATFORM_SUMMARY_LIMIT_DEFAULT/MIN/MAX = 50/1/200`.
4. **Persistance** — créer
   `adapters/outbound/persistence/platform_transaction_repository.py` :
   `SqlPlatformTransactionRepository` (agrégation `cash_journal` `GROUP BY salon_id` +
   jointure `salons`, `COUNT(*) FILTER`, `SUM(amount)` net, filtre de dates + tri +
   `limit`/`offset` **en SQL**, lecture seule). Décider inclusion/exclusion des salons
   sans activité (Open Q. 2).
5. **Application** — créer `application/platform_transactions.py` :
   `SummarizeSalonTransactions.execute` → `(page, total)`, pur, sans audit.
6. **Adapter entrant** — créer `adapters/inbound/admin.py` : router `/admin`, route
   `GET /admin/transactions/summary`, garde `require_permission(STATS_READ_PLATFORM)`
   (**pas** de `require_salon_scope`), schémas Pydantic **non-PII** documentés,
   query params `date_from/date_to/limit/offset`, `InvalidPlatformSummaryFilter → 422`.
7. **Assemblage** — `main.py` : `include_router(admin_router)`. **Vérifier** que
   `/admin/...` **n'entre pas** dans `PUBLIC_ROUTE_PATHS`.
8. **Tests** — domaine (filtre/fuseau), application (fake repo), API (auth 401/403/200,
   forme non-PII, bornes 422), intégration SQL PostgreSQL (net avec ajustements,
   pagination, bornes de dates, salon sans activité), invariant deny-by-default vert.
9. **Docs** — README §6 (#37) ; ADR-0029 proposé + index `docs/adr/README.md` (si
   confirmé, Open Q. 7) ; vérifier OpenAPI.
10. **Test gate** — `ruff check` + `pytest` verts (parité CI `scripts/test-gate.sh`).
11. **Décisions à confirmer avant/pendant l'implémentation** : net-vs-brut (1),
    salons sans activité (2), mono-devise (3), périmètre UI admin (4), tri (6), ADR (7).
