# Performance des coiffeurs — prestations réalisées, CA généré, taux d'annulation (dashboard gérant) (US-6.5, #43)

> Spécification de planification pour l'issue GitHub **#43 — US-6.5 : Performance des coiffeurs**
> (`feature` · Should · Effort **M** · PRD §6 Épic 6 US-6.5 / §8.1 / §8.2 / §11.2 / §11.3 / §12.1).
> **Dépend de #27** (US-3.6 — planning personnel du coiffeur : matérialise l'assignation
> `appointments.hairdresser_id` et la lecture assignment-scopée) **et #33** (US-5.1 — enregistrement
> d'un paiement : alimente `payments` et le `cash_journal`). En pratique, les briques réutilisées sont
> **l'assignation d'un RDV à un coiffeur** (`appointments.hairdresser_id`, posée par #25/#27) et **le
> journal de caisse net** (#33/#34, source du CA #40) — voir *Risks & Open Questions §1*.
> Repose aussi sur le shell du dashboard gérant (#14, zone `/gerant`), la permission
> `STATS_READ_SALON` (RBAC #12 / ADR-0015, **déjà** réservée au `MANAGER`, consommée par
> #39/#40/#41/#42) et le **router stats dédié** `adapters/inbound/stats.py` — que ce KPI **étend** à
> son tour (**cinquième** endpoint).
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants
> techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés. **Aucune signature
> IA** dans le code, les commits ou la PR. **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.

## Problem Statement

Le PRD (§6 Épic 6, US-6.5) pose le besoin : **« en tant que gérant, je veux mesurer la performance de
mes coiffeurs »**, spécifié par trois indicateurs : **nombre de prestations réalisées**, **chiffre
d'affaires généré** et **taux d'annulation**. Le critère d'acceptation de l'issue #43 est :

- **Indicateurs par coiffeur cohérents avec le planning et la caisse.**

C'est le **cinquième KPI du tableau de bord gérant** de l'Épic 6, après le décompte des RDV du jour
(#39, US-6.1), le chiffre d'affaires jour/semaine/mois (#40, US-6.2), les prestations les plus
demandées (#41, US-6.3) et les clients actifs (#42, US-6.4). Il transforme les vues « combien
d'activité / combien de revenu / quelles prestations / quels clients » en une vue **par employé** : le
gérant voit *qui réalise combien de prestations, génère combien de CA et concentre quel taux
d'annulation*, pour piloter son staffing, sa répartition de charge et son coaching.

État actuel du dépôt (après #39→#42) — établi par **lecture du code**, pas par hypothèse :

- **L'assignation d'un RDV à un coiffeur existe et fait autorité.** `appointments.hairdresser_id`
  (`models.py:297`, FK **nullable** → `users.id`) est posée par le gérant (`assign_hairdresser`, #25)
  et lue par le planning coiffeur (`list_for_hairdresser`, #27). Un RDV peut être **non assigné**
  (`hairdresser_id IS NULL`). #43 agrège **par `hairdresser_id`** — un axe déjà matérialisé, jamais
  encore agrégé.
- **Aucune lecture « par coiffeur » agrégée au niveau salon n'existe.** `list_for_hairdresser` (#27)
  liste les RDV **d'un** coiffeur (assignment-scopé, route d'appartenance) mais ne compte ni n'agrège.
  Les agrégats salon-scopés livrés groupent **par statut** (#39, `count_by_status_for_day`), **par
  prestation** (#41, `demand_by_service`) ou **par client** (#42, `segment_active_clients`) — **jamais
  par coiffeur**. #43 est le **même geste** avec un `GROUP BY hairdresser_id`.
- **Le router `stats` salon-scopé existe et est mûr (#40→#42).** `adapters/inbound/stats.py`
  (`APIRouter(prefix="/salons", tags=["stats"])`) porte déjà `revenue/summary` (#40), `service-demand`
  (#41) et `active-clients` (#42) sous la garde `require_salon_scope` +
  `require_permission(STATS_READ_SALON)`, avec **deux** DI surchargeables en test :
  `get_appointment_repository` **et** `get_cash_journal_repository`. Son en-tête documente
  `STATS_READ_SALON` comme ayant « **quatre** consommateurs » et **cite explicitement** « prépare
  l'Épic 6 (performance des coiffeurs #43…) ». #43 y **ajoute une route** — **cinquième** consommateur.
- **Le CA du salon est déjà défini comme le net du journal de caisse (#40/#34).**
  `CashJournalRepository.net_revenue_between` somme **signé** les lignes `cash_journal`
  `PAYMENT`/`ADJUSTMENT` sur un intervalle de `created_at` (net des corrections #34). Un `payment`
  référence un `appointment_id` (`models.py:457`, FK composite `(salon_id, appointment_id)`) ou un
  `service_id` — et un `appointment` porte **un** `hairdresser_id`. **Le CA est donc attribuable à un
  coiffeur** par la chaîne `cash_journal → payments.appointment_id → appointments.hairdresser_id`.
  C'est la différence structurante avec #41 (le revenu **par prestation** n'était **pas** attribuable
  depuis `payments` — un paiement multi-prestations n'est pas ventilé — d'où le recours à
  `price_at_booking`). Ici, l'attribution **par coiffeur** est possible : c'est ce qui rend « cohérent
  avec **la caisse** » réalisable (voir *Open Questions §1*).
- **Le libellé d'un coiffeur est résoluble et son émission est déjà une convention acceptée.**
  `appointments.hairdresser_id → users.full_name` donne le **nom d'affichage** de l'employé. Émettre le
  nom d'affichage d'un membre du personnel **n'est pas** un problème §11.3 : `CashJournalRepository.
  list_for_salon` (#34) **résout déjà** `performed_by → users.full_name` « pour l'UI, sans exposer
  d'autre donnée sensible de l'auteur (§11.3) ». #43 réutilise cette convention pour le coiffeur — à la
  différence de #42 (où `client_id` n'est **jamais** émis, anti-oracle client). Voir *Open Questions §3*.
- **Le dashboard `/gerant` (Server Component) est le point d'accrochage.** `app/(gerant)/gerant/
  page.tsx` charge déjà, côté serveur (jeton du cookie `httpOnly`, invariant #14), le salon puis
  `dailySummary` (#39), `revenueSummary` (#40), `serviceDemand` (#41) et `activeClients` (#42) via
  `http-stats-gateway.ts`, et rend les tuiles/panneaux correspondants. #43 **étend** cette page d'un
  panneau « Performance des coiffeurs » sous le panneau des clients actifs.

Le gap que #43 comble : une **lecture agrégée salon-scopée** exposant, **par coiffeur** du salon, le
**nombre de prestations réalisées**, le **CA généré** et le **taux d'annulation** sur une période,
**cohérents** avec le planning (RDV assignés) et la caisse (journal net) — exposée par un **nouvel
endpoint** sur le router `stats` et rendue par un **panneau** sur le dashboard gérant. **Sans**
migration ni changement de schéma : tout est dérivé en lecture des tables existantes.

## Goals

- **Mesurer la performance par coiffeur** (critère d'acceptation). Pour un salon et une période
  `[date_from, date_to]`, produire **une ligne par coiffeur** (compte assigné à ≥ 1 RDV du salon sur
  la période) portant :
  - **`services_completed`** — nombre de **prestations réalisées** : occurrences `appointment_services`
    des RDV **`COMPLETED`** assignés au coiffeur (mêmes « occurrences » que le volume #41, mais
    filtrées par `hairdresser_id`) ;
  - **`revenue`** — **CA généré** : montant net encaissé attribué au coiffeur, **cohérent avec la
    caisse** (net `cash_journal` #40 attribué via `payments.appointment_id → appointments.
    hairdresser_id`) — voir *Open Questions §1* pour la définition retenue et son alternative ;
  - **`cancellation_rate`** — **taux d'annulation** : part des RDV **`CANCELLED`** parmi les RDV
    assignés au coiffeur sur la période (`cancelled_count / total_count`), exposé **avec** ses deux
    compteurs bruts pour la transparence — voir *Open Questions §4/§5*.
- **Agréger « en base » (`GROUP BY hairdresser_id`), sans rapatrier de ligne inutile ni de PII client**
  : les compteurs et sommes sont calculés en SQL (patron #39/#41/#42) ; la réponse ne porte **que**
  l'identité de l'employé (`hairdresser_id` + nom d'affichage), les compteurs, les montants, la période
  et la devise — **jamais** un `client_id`, `appointment_id`, `client_note`, ni le téléphone/e-mail de
  l'employé (§11.3). La **règle métier** (calcul du taux, ordre du classement) est une **fonction
  pure** du domaine (testable sans base).
- **« Réalisé » = RDV `COMPLETED`** (prestations & CA), en cohérence avec l'invariant §8.1
  (`REVENUE_STATUSES == (COMPLETED,)`) et avec #41 (`REVENUE_STATUSES`) / #42 (`HISTORY_STATUSES`). Un
  RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne compte **ni** en prestations réalisées **ni** en
  CA. Le **taux d'annulation** compte, lui, les `CANCELLED` (numérateur) sur le total assigné
  (dénominateur) — statuts **décidés côté serveur**, jamais soumis par l'appelant.
- **Cohérence planning ⇄ caisse (cœur de l'AC).** Prestations réalisées et taux d'annulation dérivent
  **du planning** (`appointments` assignés — même source que #26/#27/#39) ; le CA dérive **de la
  caisse** (net `cash_journal` — même source que #40/#34). Chaque indicateur est ainsi **cohérent avec
  son autorité** (planning ou caisse). Les **écarts de couverture assumés** (CA non attribuable des
  paiements sans RDV ou des RDV non assignés ; axe temporel du CA vs des prestations) sont **documentés**
  (voir *Open Questions §1/§2*).
- **Réutiliser strictement `STATS_READ_SALON`** (déjà détenue par le seul `MANAGER`) **+**
  `require_salon_scope` (isolation §11.2) — **sans** modifier `ROLE_PERMISSIONS`, exactement comme
  #39/#40/#41/#42. **Cinquième** consommateur de cette permission.
- **Isolation §11.2, en profondeur.** Route salon-scopée (`require_salon_scope` → `403` **générique**,
  aucun oracle) **et** re-filtrage `WHERE appointments.salon_id = :salon_id` (et
  `cash_journal.salon_id`) **inconditionnel** en SQL (défense en profondeur derrière la garde HTTP). Le
  dépôt n'agrège **jamais** les coiffeurs d'un autre salon ; un même compte coiffeur membre de deux
  salons est mesuré **par salon** (cloisonnement strict).
- **Lecture pure, sans effet de bord.** Aucune écriture, **aucune** entrée d'audit §11.4 (patron des
  lectures #34/#35/#37/#39/#40/#41/#42), aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` (une donnée
  d'exploitation salon n'est jamais publique).
- **Panneau « Performance des coiffeurs » sur le dashboard `/gerant`**, sous le panneau des clients
  actifs (#42), en réutilisant le patron Server Component + `http-stats-gateway` (jeton serveur, jamais
  exposé). État **vide explicite** : « Aucun coiffeur assigné sur la période » (salon sans RDV assigné)
  — **pas** une erreur. Dégradation **locale** sur panne (aligné #41/#42).
- **Additif et rétro-compatible** : aucune signature existante modifiée, **aucune migration** de schéma
  (les index `ix_appointments_salon_id`, `ix_payments_appointment_id`, `ix_cash_journal_salon_id`
  couvrent la requête ; un index `(salon_id, hairdresser_id)` reste une **optimisation** optionnelle).
- **Couverture de tests** : domaine (calcul déterministe du taux, ordre du classement, division par
  zéro, vide), cas d'usage (statuts imposés, bornes passées aux ports, fusion des deux sources par
  `hairdresser_id`), API (`200`/`401`/`403`/`422`, forme non-PII, isolation), e2e PostgreSQL (agrégat
  réel par coiffeur, attribution du CA via `payments`, filtre `COMPLETED`, isolation inter-salons) ;
  web (mapping/formatage, gateway, rendu du panneau).

## Non-Goals

- **Aucune surface côté coiffeur.** #43 est un KPI **gérant** (Épic 6, tableau de bord du gérant),
  rendu sur `/gerant` — **pas** dans une éventuelle zone `/coiffeur` (#27). Un coiffeur ne consulte
  **pas** ses propres statistiques via #43 (permission `STATS_READ_SALON`, réservée au `MANAGER`).
- **Aucune liste nominative de clients ni de RDV.** #43 renvoie des **agrégats par coiffeur**, jamais
  la liste des RDV d'un coiffeur (c'est `list_for_hairdresser` #27, assignment-scopé) ni l'identité des
  clients (`client_id` **jamais** émis, §11.3). Le drill-down « quels RDV » reste hors périmètre.
- **Aucune ventilation croisée (coiffeur × prestation, coiffeur × jour).** #43 agrège **par coiffeur**
  uniquement. Les croisements (matrice coiffeur×prestation, séries temporelles, cohortes) sont
  post-MVP (PRD §16/§21).
- **Aucun agrégat inter-salons ni vue admin.** #43 est **salon-scopé** (le gérant voit **son** salon).
  Les KPI plateforme relèvent de l'admin (#37 livré, #44 à venir).
- **Aucune écriture / aucun audit §11.4.** Lecture pure (comme #39/#40/#41/#42).
- **Aucune modification de `ROLE_PERMISSIONS`** ni des droits `CLIENT`/`HAIRDRESSER`/`ADMIN`. En
  particulier, `STATS_READ_SALON` n'est **pas** attribuée au `HAIRDRESSER`.
- **Aucun classement / notation qualitative** (score, étoiles, objectif). #43 expose des **grandeurs
  brutes** (compteurs, montants, taux) ; toute évaluation RH est laissée au gérant.
- **Aucune statistique côté client / mobile.** #43 est un parcours **gérant** (web) ; `app-mobile/`
  n'est **pas** touché.
- **Aucune colonne dénormalisée / compteur persisté.** #43 **dérive en lecture** ; aucun *trigger*,
  aucun couplage dans `SetAppointmentStatus` (#25) ou `RecordPayment` (#33).
- **Aucune migration / changement de schéma.** Aucun. #43 est une lecture dérivée d'`appointments` /
  `appointment_services` / `payments` / `cash_journal` / `users`.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Comptes employés | Appartenance `salon_members`, portée coiffeur, `HAIRDRESSER` | [0016](../docs/adr/0016-comptes-employes-appartenance-salon.md) |
| Encaissement | Cohérence montant paiement ↔ prestation, journal de caisse | [0027](../docs/adr/0027-encaissement-coherence-montant.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête à **ADR-0030**. #39/#40/#41/#42 (KPI dashboard) ont plié leurs décisions dans les
README (pas d'ADR). Un ADR pour #43 est **plus justifié** que pour #41/#42 (voir *Open Questions §9*) :
#43 introduit **deux** décisions non triviales — (a) l'**émission de l'identité d'un employé** dans une
réponse stats (départ du patron counts-only #42) et (b) la **définition du « CA par coiffeur »** (caisse
attribuée vs `price_at_booking`) avec ses écarts de couverture. Le prochain numéro libre est **0031**.

### Backend — patrons à réutiliser tels quels

- **Agrégat salon-scopé « en base » (#39/#41/#42)** : `SqlAppointmentRepository::
  count_by_status_for_day` (`GROUP BY status`), `::demand_by_service` (`GROUP BY service_id`, `COUNT` +
  `SUM(price_at_booking)`, join `appointment_services`/`services`), `::segment_active_clients`
  (`GROUP BY client_id`, `MIN` + deux `SUM(CASE …)`). #43 est le **même geste** avec
  `GROUP BY hairdresser_id` et des `COUNT FILTER` par statut (`COMPLETED`, `CANCELLED`, total).
- **CA net de la caisse (#40/#34)** : `CashJournalRepository::net_revenue_between` — somme **signée**
  des lignes `PAYMENT`/`ADJUSTMENT` sur un intervalle de `created_at`, `Decimal` quantifié au centime.
  #43 en fait la **variante attribuée par coiffeur** (join `payments`/`appointments`, `GROUP BY
  appointments.hairdresser_id`). Voir *Proposed Implementation §D*.
- **Résolution du nom d'affichage d'un employé (#34)** : `SqlCashJournalEntryRepository::list_for_salon`
  résout **déjà** `performed_by → users.full_name` « pour l'UI, sans exposer d'autre donnée sensible de
  l'auteur (§11.3) ». #43 réutilise cette convention pour `hairdresser_id → users.full_name`.
- **Endpoint stats salon-scopé (#40→#42)** : `adapters/inbound/stats.py` — schémas Pydantic
  **explicites** (jamais `orm_mode`/`extra`), montants/compteurs documentés, OpenAPI (`summary`,
  `responses` 200/401/403/422), gardes `require_salon_scope` + `require_permission(STATS_READ_SALON)`,
  DI **`get_appointment_repository` et `get_cash_journal_repository`** déjà présentes et surchargeables
  en test. Modèle **direct** de la nouvelle route ; la garde explicite `date_to < date_from → 422` et le
  défaut `month_bounds(_today())` (#42) sont à **répliquer**.
- **Use case de lecture pure (#40/#41/#42)** : `application/revenue.py::SummarizeRevenue`,
  `application/service_demand.py::SummarizeServiceDemand`, `application/client_segments.py::
  SummarizeActiveClients` (dépendent d'un/de **port(s)**, aucune I/O framework, aucun audit, imposent
  les statuts serveur). Modèle direct de `SummarizeHairdresserPerformance`.
- **Règle métier pure dans le domaine (#40/#41/#42)** : `domain/revenue.py`
  (`day_bounds`/`week_bounds`/`month_bounds`), `domain/service_demand.py::rank_service_demand` (tri
  déterministe), `domain/client_segments.py::classify_client_segments` (classification pure). #43 y
  ajoute `rank_hairdresser_performance` (calcul du taux + ordre déterministe).
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` ; `403` **générique** ; l'invariant deny-by-default est vérifié mécaniquement
  par `unprotected_routes(app)` (`test_security_guards.py`) — **une route ajoutée sans garde fait
  échouer les tests**.
- **Tests** : fakes en mémoire (`tests/conftest.py`) + `TestClient` + `app.dependency_overrides` ;
  **e2e** adossés à un vrai PostgreSQL (`coiflink-e2e-pg`, port 55433 — cf. mémoire projet), patron
  `test_daily_summary_e2e.py` / `test_service_demand_e2e.py` / `test_active_clients_e2e.py`. Fichiers de
  tests unitaires nommés par sujet : `test_domain_*`, `test_*_usecase.py`, `test_stats_api.py`.

### Modèle de données pertinent (schéma #3, aucun changement)

```
users (id, full_name, phone, email, role, status, …)            ← nom d'affichage du coiffeur
salon_members (salon_id, user_id, role, status)                 ← appartenance employé (#13)
appointments (id, salon_id, client_id, hairdresser_id NULL → users.id, status, appointment_date, …)
  └─ appointment_services (appointment_id, service_id, salon_id, price_at_booking NUMERIC(12,2))
payments (id, salon_id, appointment_id NULL, service_id NULL, amount, status, created_at, …)
cash_journal (id, salon_id, transaction_id NULL → payments.id, operation_type, amount, created_at, …)
```

- **Prestations réalisées & taux d'annulation (planning)** : agréger `appointments` filtré
  `salon_id = :salon_id AND hairdresser_id IS NOT NULL AND appointment_date ∈ [date_from, date_to]`,
  `GROUP BY hairdresser_id` avec :
  - `services_completed = COUNT(appointment_services)` **des RDV `COMPLETED`** (join
    `appointment_services`) — voir *Open Questions §6* pour « occurrences de prestations » vs « nombre
    de RDV réalisés » ;
  - `completed_count = COUNT(*) FILTER (WHERE status = 'COMPLETED')`,
    `cancelled_count = COUNT(*) FILTER (WHERE status = 'CANCELLED')`,
    `total_count = COUNT(*)` (tous statuts du coiffeur sur la période).
- **CA généré (caisse)** : agréger `cash_journal` filtré `salon_id` + `operation_type ∈ (PAYMENT,
  ADJUSTMENT)`, join `payments` (`transaction_id`) puis `appointments` (`appointment_id`), filtré
  `appointments.hairdresser_id IS NOT NULL` et `appointments.appointment_date ∈ [date_from, date_to]`,
  `GROUP BY appointments.hairdresser_id`, `SUM(cash_journal.amount)` **signée** (net des corrections).
  Les paiements **sans RDV** (`appointment_id IS NULL`, prestation directe) et les RDV **non assignés**
  sont **inattribuables** → exclus des lignes coiffeur (résidu documenté, *Open Questions §2*).
- **Nom d'affichage** : join `appointments.hairdresser_id → users.full_name` (ou `salon_members` →
  `users`). **Jamais** `phone`/`email`/`role`/`status` de l'employé.
- Index couvrants **déjà présents** : `ix_appointments_salon_id (salon_id, appointment_date)`,
  `ix_payments_appointment_id (appointment_id)`, `ix_payments_salon_id (salon_id, created_at)`,
  `ix_cash_journal_salon_id (salon_id, created_at)`. **Aucune migration** : #43 n'ajoute aucune colonne,
  contrainte ni index (un index `(salon_id, hairdresser_id, appointment_date)` reste une **option**
  d'optimisation, *Open Questions §7* — non requise au MVP).

### Web gérant — patrons à réutiliser (#41/#42)

- `app/(gerant)/gerant/page.tsx` — Server Component + composition root : lit le cookie, appelle les
  gateways **côté serveur**, rend tuiles/panneaux. #43 y ajoute un chargement + un panneau, avec
  **dégradation locale** sur panne (patron `activeClients` #42 : `perf.ok ? … : null`).
- `src/application/ports/stats-gateway.ts` + `src/adapters/api/http-stats-gateway.ts` — port + adapter
  HTTP en **union discriminée** (`{ ok: true, … } | { ok: false, reason }`), jeton jamais dans le
  résultat. `activeClients(...)` / `serviceDemand(...)` sont les modèles directs de
  `hairdresserPerformance(...)`.
- `src/adapters/ui/active-clients-panel.tsx` / `service-demand-panel.tsx` / `revenue-tiles.tsx` —
  patrons d'affichage (panneau / liste classée + état vide) à imiter. Réutiliser `formatXof`
  (`src/domain/payments/*`) pour le CA et un formatage de pourcentage pour le taux.

### Contraintes transverses documentées

- **PRD §11.2** : un gérant ne voit que les données de son salon. **§11.3** : collecte minimale, pas de
  PII superflue en réponse ni en logs. **§8.1** : le réalisé/CA ne comptent que les RDV `COMPLETED` ;
  devise unique **XOF** ; montants `NUMERIC(12,2)` (jamais de flottant). **§8.2** : un paiement
  référence un RDV **ou** une prestation ; journal de caisse net des corrections (#34). **§12.1** :
  réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**.
- **Test gate** : `scripts/test-gate.sh` (`pytest` + `npm test` + `flutter test`) ; CI `ci.yml` (ruff,
  pytest, round-trip Alembic contre PostgreSQL 16, build, lint/test/build web).

## Proposed Implementation

**Approche recommandée : backend-first, endpoint agrégé dédié (une ligne par coiffeur, trois
indicateurs) + tranche web**, sur le patron #41/#42. Les indicateurs viennent de **deux sources
distinctes mais chacune autoritaire** : le **planning** (`appointments`, prestations réalisées + taux
d'annulation) et la **caisse** (`cash_journal` net, CA) — fusionnées **par `hairdresser_id`** dans le
cas d'usage. La règle métier (calcul du taux, ordre du classement) vit **dans le domaine** (fonction
pure).

> **Décision structurante à trancher au step `plan` (voir *Open Questions §1*).** Le CA par coiffeur
> peut se définir de deux façons : **(recommandé) net de la caisse** attribué via `payments →
> appointments.hairdresser_id` (« cohérent avec la caisse » #40, mais écarts de couverture documentés) ;
> **(alternative)** somme des `price_at_booking` des RDV `COMPLETED` assignés (« cohérent avec le
> planning », source unique `appointments`, mais divergent du cash net comme #41). La spec décrit la
> variante **recommandée** en détail et l'alternative en encadré ; l'architecture (ports + domaine)
> supporte les deux sans changer la forme de la réponse.

### (A) Backend — domaine (calcul du taux + tri, pur)

**`domain/hairdresser_performance.py`** — **créer** (module frère de `domain/service_demand.py` /
`domain/client_segments.py`, pur, sans I/O) :

```python
@dataclass(frozen=True)
class HairdresserActivity:
    """Agrégats bruts d'un coiffeur au salon sur une période (US-6.5, #43) — issus des dépôts.

    `hairdresser_id` + `name` = identité **d'affichage** de l'employé (jamais
    téléphone/e-mail, §11.3). `services_completed` = occurrences de prestations
    réalisées (RDV `COMPLETED`) ; `revenue` = CA net attribué (caisse) ;
    `cancelled_count` / `total_count` = RDV annulés / total assignés sur la période.
    `Decimal` de bout en bout pour le montant, jamais de flottant.
    """
    hairdresser_id: uuid.UUID
    name: str
    services_completed: int
    revenue: decimal.Decimal
    cancelled_count: int
    total_count: int


@dataclass(frozen=True)
class HairdresserPerformance:
    """Performance dérivée d'un coiffeur (US-6.5) : ajoute le taux d'annulation calculé.

    `cancellation_rate` = `cancelled_count / total_count` (`Decimal` quantifié, ex.
    4 décimales), `Decimal("0")` si `total_count == 0` (garde division par zéro). Porte
    les compteurs bruts pour la transparence (le front peut afficher « 3/20 »).
    """
    hairdresser_id: uuid.UUID
    name: str
    services_completed: int
    revenue: decimal.Decimal
    cancelled_count: int
    total_count: int
    cancellation_rate: decimal.Decimal


@dataclass(frozen=True)
class HairdresserPerformanceReport:
    """Classement des coiffeurs d'un salon sur une période (US-6.5, #43).

    `entries` triées par ordre **déterministe** (voir `rank_hairdresser_performance`).
    `date_from`/`date_to` échoient la période ; `currency` la devise (XOF). `entries`
    vide si aucun coiffeur assigné sur la période (état normal, pas une erreur).
    """
    entries: tuple[HairdresserPerformance, ...] = ()
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    currency: str = DEFAULT_CURRENCY


def rank_hairdresser_performance(
    rows: tuple[HairdresserActivity, ...],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str = DEFAULT_CURRENCY,
) -> HairdresserPerformanceReport:
    """Calcule le taux d'annulation et ordonne le classement (fonction **pure**).

    Pour chaque activité : `cancellation_rate = cancelled_count / total_count`
    (quantifié ; `0` si `total_count == 0`). Ordre par défaut **déterministe** :
    `-revenue`, puis `-services_completed`, puis `name`, puis `str(hairdresser_id)`
    (départages stables pour les tests). Cette fonction **ne ré-agrège pas** (les
    `rows` proviennent déjà d'un `GROUP BY hairdresser_id`) : elle **calcule** et
    **ordonne**.
    """
```

- Réutiliser `DEFAULT_CURRENCY` (`domain/payment.py`). Exporter les trois dataclasses +
  `rank_hairdresser_performance` dans `__all__`.
- **Pourquoi un calcul domaine et une agrégation SQL** : les compteurs/sommes (`COUNT FILTER`, `SUM`)
  sont faits en base (minimisation, index), mais le **taux** (division protégée) et l'**ordre** du
  classement sont une décision métier **pure et testable** — miroir #39/#41/#42.
- **Décimal, pas de flottant** : `cancellation_rate` est un `Decimal` quantifié (ex.
  `Decimal("0.0000")`), transporté en **chaîne** ; le web formate en pourcentage à l'affichage.

### (B) Backend — ports (lectures agrégées)

Deux méthodes, chacune dans le port de sa source (foyers naturels des agrégats salon-scopés déjà
utilisés par le router `stats`) :

**`application/ports/appointment_repository.py`** — **ajouter** au `Protocol AppointmentRepository` :

```python
def performance_by_hairdresser(
    self,
    salon_id: uuid.UUID,
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    completed_statuses: tuple[str, ...],
    cancelled_statuses: tuple[str, ...],
) -> tuple[HairdresserActivityCounts, ...]:
    ...
```

Docstring : renvoie, **par coiffeur** (`GROUP BY hairdresser_id`, `hairdresser_id IS NOT NULL`), les
compteurs `(hairdresser_id, name, services_completed, cancelled_count, total_count)` des RDV du salon
dont `appointment_date ∈ [date_from, date_to]` **inclus** : `services_completed` = `COUNT` des lignes
`appointment_services` des RDV dont `status ∈ completed_statuses` (join `appointment_services`),
`cancelled_count` = `COUNT(*) FILTER (WHERE status ∈ cancelled_statuses)`, `total_count` = `COUNT(*)`.
`name` = `users.full_name` (join, nom d'affichage **seul**). Isolation §11.2 **imposée en SQL**
(`WHERE appointments.salon_id`). Lecture pure. *(Renvoie une valeur `HairdresserActivityCounts` **sans**
le CA ; le use case y adjoint le CA de la caisse — voir §C/§D.)*

**`application/ports/cash_journal_repository.py`** — **ajouter** au `Protocol CashJournalRepository`
(variante attribuée de `net_revenue_between`) :

```python
def net_revenue_by_hairdresser(
    self,
    salon_id: uuid.UUID,
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> Mapping[uuid.UUID, decimal.Decimal]:
    ...
```

Docstring : renvoie `{hairdresser_id: net_amount}` — somme **signée** des lignes `cash_journal`
`PAYMENT`/`ADJUSTMENT` du salon dont le `payment` référence un `appointment` **assigné** (`hairdresser_id
IS NOT NULL`) dont `appointment_date ∈ [date_from, date_to]` — `GROUP BY appointments.hairdresser_id`.
Net des corrections (#34). Les paiements **sans RDV** ou liés à un RDV **non assigné** sont **exclus**
(inattribuables). Isolation §11.2 **imposée en SQL** (`WHERE cash_journal.salon_id`). `Decimal`
quantifié au centime. Lecture pure. **Ne renvoie aucune PII** (ni `client_id`, ni `reference`, ni
`recorded_by`, ni ligne de paiement) — seulement `(hairdresser_id, montant)`.

> **Alternative (Option A, *Open Questions §1*).** Si le CA « planning » (somme `price_at_booking`) est
> retenu, **aucune** méthode `cash_journal` n'est ajoutée : `performance_by_hairdresser` calcule aussi
> `revenue = COALESCE(SUM(price_at_booking) FILTER (WHERE status ∈ completed_statuses), 0)` dans la même
> requête `appointments`. Source unique, use case mono-port. À trancher.

### (C) Backend — cas d'usage

**`application/hairdresser_performance.py`** — **créer** (dépend d'`AppointmentRepository` **et**, pour
la variante caisse, de `CashJournalRepository`) :

```python
class SummarizeHairdresserPerformance:
    """Performance des coiffeurs d'un salon sur une période (lecture — pas d'audit, #43)."""

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        cash_journal_repository: CashJournalRepository,
    ) -> None:
        self._appointments = appointment_repository
        self._cash_journal = cash_journal_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> HairdresserPerformanceReport:
        counts = self._appointments.performance_by_hairdresser(
            salon_id,
            date_from=date_from,
            date_to=date_to,
            completed_statuses=REVENUE_STATUSES,     # (COMPLETED,) — §8.1
            cancelled_statuses=CANCELLED_STATUSES,   # (CANCELLED,) — décidé serveur
        )
        net_by_hd = self._cash_journal.net_revenue_by_hairdresser(
            salon_id, date_from=date_from, date_to=date_to
        )
        activities = tuple(
            HairdresserActivity(
                hairdresser_id=c.hairdresser_id,
                name=c.name,
                services_completed=c.services_completed,
                revenue=net_by_hd.get(c.hairdresser_id, decimal.Decimal("0.00")),
                cancelled_count=c.cancelled_count,
                total_count=c.total_count,
            )
            for c in counts
        )
        return rank_hairdresser_performance(
            activities, date_from=date_from, date_to=date_to
        )
```

- `REVENUE_STATUSES` (`domain/appointment.py`) et un `CANCELLED_STATUSES = (CANCELLED,)` (à ajouter au
  domaine s'il n'existe pas, à côté de `REVENUE_STATUSES` — **décidé serveur**, jamais soumis). Lecture
  pure → **aucun** audit (patron `SummarizeServiceDemand`/`SummarizeActiveClients`). Ajouter au
  `__all__`.
- Le cas d'usage reçoit une période **résolue** (deux dates non nulles) : la résolution du défaut (mois
  courant) est faite par l'adapter entrant, comme #42.
- **Fusion par `hairdresser_id`** : la liste des coiffeurs vient de `performance_by_hairdresser`
  (planning) ; le CA (`net_by_hairdresser`) y est **greffé** (`0.00` si le coiffeur n'a aucun paiement
  attribué). Un coiffeur avec du CA mais **aucun** RDV dans la fenêtre planning (cas de bord : paiement
  attribué mais RDV hors période) n'apparaît **pas** — cohérence « liste = coiffeurs actifs au planning »
  (*Open Questions §2*). *(Variante A : `net_by_hd` est absent, `revenue` vient de `counts`.)*

### (D) Backend — adapters outbound (SQL)

**`adapters/outbound/persistence/appointment_repository.py`** — **implémenter**
`performance_by_hairdresser` (miroir `demand_by_service` / `segment_active_clients`), en veillant à ne
**pas** sur-compter les prestations : le `services_completed` compte des lignes `appointment_services`
et ne doit pas gonfler `total_count`/`cancelled_count` (comptes de **RDV**). Deux approches sûres :

1. **Deux passes / sous-requêtes** : une agrégation RDV (`COUNT(*)`, `COUNT FILTER`) `GROUP BY
   hairdresser_id` sur `appointments`, jointe à une agrégation `COUNT(appointment_services)` des RDV
   `COMPLETED` `GROUP BY hairdresser_id` (LEFT JOIN pour les coiffeurs sans prestation réalisée) ; ou
2. **`COUNT(DISTINCT …)` maîtrisé** — plus fragile ; préférer l'approche (1) pour la clarté.

Esquisse (approche 1, agrégat RDV) :

```python
completed = func.sum(case((models.Appointment.status.in_(completed_statuses), 1), else_=0))
cancelled = func.sum(case((models.Appointment.status.in_(cancelled_statuses), 1), else_=0))
stmt = (
    select(
        models.Appointment.hairdresser_id,
        models.User.full_name,
        func.count().label("total_count"),
        func.coalesce(completed, 0).label("completed_count"),
        func.coalesce(cancelled, 0).label("cancelled_count"),
    )
    .join(models.User, models.User.id == models.Appointment.hairdresser_id)
    .where(
        models.Appointment.salon_id == salon_id,
        models.Appointment.hairdresser_id.is_not(None),
        models.Appointment.appointment_date.between(date_from, date_to),
    )
    .group_by(models.Appointment.hairdresser_id, models.User.full_name)
)
```

`services_completed` (occurrences de prestations réalisées) est **calculé séparément** — sous-requête
`GROUP BY appointments.hairdresser_id` sur `appointment_services` join `appointments` filtré
`status ∈ completed_statuses` + salon + période — puis mappé par `hairdresser_id` (défaut `0`). Filtrer
sur `appointments.salon_id` (défense en profondeur §11.2). **Ne pas** sélectionner de PII client.
Lecture pure (aucun `flush`). Requête couverte par `ix_appointments_salon_id`.

**`adapters/outbound/persistence/cash_journal_repository.py`** — **implémenter**
`net_revenue_by_hairdresser` (variante attribuée de `net_revenue_between`) :

```python
stmt = (
    select(
        models.Appointment.hairdresser_id,
        func.coalesce(func.sum(models.CashJournal.amount), 0).label("net"),
    )
    .join(models.Payment, models.Payment.id == models.CashJournal.transaction_id)
    .join(models.Appointment, models.Appointment.id == models.Payment.appointment_id)
    .where(
        models.CashJournal.salon_id == salon_id,
        models.CashJournal.operation_type.in_(
            (CashOperationType.PAYMENT.value, CashOperationType.ADJUSTMENT.value)
        ),
        models.Appointment.hairdresser_id.is_not(None),
        models.Appointment.appointment_date.between(date_from, date_to),
    )
    .group_by(models.Appointment.hairdresser_id)
)
```

- Retourner `{row.hairdresser_id: Decimal(row.net or 0).quantize(_AMOUNT_QUANTUM)}`. **Réutiliser** les
  mêmes types d'opération que `net_revenue_between` (`PAYMENT`/`ADJUSTMENT` — CA net des corrections).
  **Attribution par le RDV** : le join `payments.appointment_id → appointments` porte le
  `hairdresser_id` **et** la borne `appointment_date` (l'axe planning), pas `cash_journal.created_at` —
  choix qui aligne le CA sur la **même période** que les prestations/annulations (*Open Questions §2*).
  Les lignes sans `transaction_id`/`appointment_id` (paiement de prestation directe) sont **exclues**
  par les joins (inattribuables). Isolation §11.2 : `cash_journal.salon_id`. Lecture pure.

### (E) Backend — adapter inbound (route sur le router `stats` existant)

**`adapters/inbound/stats.py`** — **ajouter une route** au router `stats` (#40→#42), **sans** créer de
router :

```python
@router.get(
    "/{salon_id}/hairdresser-performance",
    response_model=HairdresserPerformanceResponse,
    summary="Performance des coiffeurs du salon : prestations, CA, taux d'annulation (US-6.5 §6)",
    responses={200: {...}, 401: {...}, 403: {...}, 422: {...}},
)
def get_hairdresser_performance(
    salon_id: uuid.UUID,
    appointment_repo: Annotated[AppointmentRepository, Depends(get_appointment_repository)],
    cash_journal_repo: Annotated[CashJournalRepository, Depends(get_cash_journal_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[Principal, Depends(require_permission(Permission.STATS_READ_SALON))],
    date_from: Annotated[datetime.date | None, Query(...)] = None,
    date_to: Annotated[datetime.date | None, Query(...)] = None,
) -> HairdresserPerformanceResponse: ...
```

- **Chemin `/{salon_id}/hairdresser-performance`** (segment **distinct**). ⚠️ Vérifier la
  **non-collision** avec les routes salon existantes (`/{salon_id}/employees` #13, `/{salon_id}/
  appointments` #26, `/{salon_id}/customers`, `/{salon_id}/services`, `/{salon_id}/payments`,
  `/{salon_id}/revenue/summary`, `/{salon_id}/service-demand`, `/{salon_id}/active-clients`) : le
  littéral `hairdresser-performance` est disjoint — aucun n'est parsé comme un UUID. Voir *Open
  Questions §8* (alias possibles : `staff-performance`, `hairdressers/performance`).
- **Gardes** : `require_salon_scope` **+** `require_permission(STATS_READ_SALON)` (**cinquième**
  consommateur). `salon_id` du chemin ; les dépôts refiltrent en SQL.
- **Query** `date_from` / `date_to` (`AAAA-MM-JJ`, `Africa/Abidjan`) : **par défaut** le **mois civil
  courant** (résolu serveur via `month_bounds(_today())`, symétrie #42), date mal formée → `422`,
  `date_to < date_from` → `422` (garde explicite, répliquer `get_active_clients`).
- **DI** : réutiliser `get_appointment_repository` **et** `get_cash_journal_repository` (déjà déclarées
  dans `stats.py`, surchargeables en test). *(Variante A : seul `get_appointment_repository`.)*
- **Schémas Pydantic** (explicites, OpenAPI, patron #40→#42) :
  - `HairdresserPerformanceItemResponse` : `hairdresser_id: UUID`, `hairdresser_name: str`,
    `services_completed: int`, `revenue: Decimal` (chaîne), `cancelled_count: int`,
    `total_count: int`, `cancellation_rate: Decimal` (chaîne, ex. `"0.1500"`).
  - `HairdresserPerformanceResponse` : `currency: str`, `date_from: date`, `date_to: date`,
    `hairdressers: list[HairdresserPerformanceItemResponse]`.
  - **Aucune PII client** (pas de `client_id`/`appointment_id`) ni **PII employé sensible** (pas de
    `phone`/`email`/`role`) : figer la forme par un test qui échoue si un champ interdit apparaît
    (patron #37/#40/#41/#42) — **`hairdresser_name` est le seul champ nominatif autorisé** (nom
    d'affichage de l'employé, convention #34).
- **`main.py` inchangé** : le router `stats` est **déjà** monté (#40). Actualiser seulement le
  **commentaire** d'assemblage / l'en-tête du router `stats` pour mentionner le **cinquième** endpoint
  (#43) et le passage de `STATS_READ_SALON` à **cinq** consommateurs.

### (F) Web gérant — panneau « Performance des coiffeurs »

1. **Domaine TS** — `src/domain/stats/hairdresser-performance.ts` : type `HairdresserPerformanceItem`
   (`hairdresserId`, `hairdresserName`, `servicesCompleted`, `revenue: string`, `cancelledCount`,
   `totalCount`, `cancellationRate: string`) et `HairdresserPerformanceReport` (`currency`, `dateFrom`,
   `dateTo`, `hairdressers: []`). Helper `formatRate` (pourcentage, ex. `15 %`) et réutilisation de
   `formatXof`. Le backend reste **l'autorité** des chiffres **et de l'ordre** ; le front **formate**.
2. **Port & gateway** — étendre `src/application/ports/stats-gateway.ts` (type
   `HairdresserPerformanceResult` en union discriminée, `reason: "forbidden" | "unauthenticated" |
   "invalid" | "unavailable"`) + `src/adapters/api/http-stats-gateway.ts` avec
   `hairdresserPerformance(salonId, dateFromIso?, dateToIso?)` : `GET {API}/salons/{id}/
   hairdresser-performance?date_from&date_to`, jeton du cookie `httpOnly` (jamais exposé ni journalisé),
   montants/taux en **chaîne**. Mapping `200/401/403/422/503` (miroir `activeClients`).
3. **UI** — `src/adapters/ui/hairdresser-performance-panel.tsx` : un tableau/liste **une ligne par
   coiffeur** (nom · prestations réalisées · CA · taux d'annulation « ×/× »), avec la période affichée
   et un état **vide** (« Aucun coiffeur assigné sur la période »). Style aligné sur
   `active-clients-panel.tsx` / `service-demand-panel.tsx`.
4. **Page** — étendre `app/(gerant)/gerant/page.tsx` : après `activeClients`, charger
   `hairdresserPerformance(salon.id)` (même jeton serveur, période par défaut backend = mois courant) et
   rendre `<HairdresserPerformancePanel>` **sous** `<ActiveClientsPanel>`. **Dégrader localement** sur
   panne (`perf.ok ? perf.report : null`) sans casser la page — patron #42.

### (G) Documentation

- `backend/README.md` : ajouter `GET /salons/{salon_id}/hairdresser-performance` (route, permission,
  réponses, définition des trois indicateurs et **leurs sources** — prestations & taux depuis le
  planning ; CA depuis la caisse nette attribuée par RDV), signaler le **cinquième** usage de
  `STATS_READ_SALON` et **documenter les écarts de couverture** (CA inattribuable des paiements sans RDV
  / RDV non assignés ; `hairdresser_name` = nom d'affichage employé, jamais de contact).
- `web-dashboard/README.md` : le dashboard `/gerant` affiche désormais la performance des coiffeurs
  (US-6.5), sous les clients actifs (US-6.4).
- `README.md` racine §6 : phrase de statut « performance des coiffeurs (#43) livré » ; cohérence du
  suivi M5.

## Affected Files / Packages / Modules

**Backend (`backend/coiflink_api/`)**
- `domain/hairdresser_performance.py` — **créer** (`HairdresserActivity`,
  `HairdresserActivityCounts`, `HairdresserPerformance`, `HairdresserPerformanceReport`,
  `rank_hairdresser_performance`, `__all__`).
- `domain/appointment.py` — **modifier** (ajouter `CANCELLED_STATUSES = (CANCELLED,)` à côté de
  `REVENUE_STATUSES`, `__all__`) *si aucune constante équivalente n'existe*.
- `application/ports/appointment_repository.py` — **modifier** (ajouter `performance_by_hairdresser` au
  `Protocol` + docstring : `GROUP BY hairdresser_id`, `hairdresser_id IS NOT NULL`, isolation §11.2 en
  SQL, non-sur-comptage prestations/RDV, nom d'affichage seul).
- `application/ports/cash_journal_repository.py` — **modifier** (ajouter `net_revenue_by_hairdresser` au
  `Protocol` — variante attribuée de `net_revenue_between`). *(Non requis en variante A.)*
- `application/hairdresser_performance.py` — **créer** (`SummarizeHairdresserPerformance`).
- `adapters/outbound/persistence/appointment_repository.py` — **modifier** (implémenter
  `performance_by_hairdresser` : agrégat RDV `COUNT FILTER` + sous-requête `COUNT(appointment_services)`
  des `COMPLETED`, join `users` pour le nom).
- `adapters/outbound/persistence/cash_journal_repository.py` — **modifier** (implémenter
  `net_revenue_by_hairdresser` : join `payments`/`appointments`, `GROUP BY hairdresser_id`, somme
  signée `PAYMENT`/`ADJUSTMENT`). *(Non requis en variante A.)*
- `adapters/inbound/stats.py` — **modifier** (schémas `HairdresserPerformanceItemResponse`/
  `HairdresserPerformanceResponse`, route `GET /salons/{salon_id}/hairdresser-performance`, garde
  `date_to < date_from → 422`, défaut mois courant ; réutilise les deux DI).
- `main.py` — **modifier** (uniquement le **commentaire** d'assemblage / l'en-tête du router `stats` :
  cinquième endpoint / usage `STATS_READ_SALON`). *Router déjà monté (#40) — pas de `include_router`.*
- `domain/appointment.py` (`REVENUE_STATUSES`), `domain/payment.py` (`DEFAULT_CURRENCY`),
  `domain/revenue.py` (`month_bounds`), `domain/enums.py` (`CashOperationType`, `AppointmentStatus`),
  `adapters/inbound/security.py`, `domain/permissions.py` — **lire** (réutilisation ; pas de modif).
- `backend/README.md` — **modifier**.

**Backend — tests**
- `tests/test_domain_hairdresser_performance.py` — **créer** (calcul du taux : division par zéro,
  arrondi `Decimal` ; ordre déterministe du classement ; vide).
- `tests/test_hairdresser_performance_usecase.py` — **créer** (statuts `REVENUE_STATUSES`/
  `CANCELLED_STATUSES` imposés, bornes passées aux ports, **fusion par `hairdresser_id`** du CA caisse,
  `0.00` par défaut) via fakes des deux ports.
- `tests/test_stats_api.py` — **étendre** (ou `tests/test_hairdresser_performance_api.py` **créer**) :
  API `200`/`401`/`403`/`422`, forme non-PII (client **et** contact employé), isolation, défaut mois
  courant, non-collision de routage.
- `tests/conftest.py` — **modifier** (ajouter `performance_by_hairdresser` au fake
  `AppointmentRepository` et `net_revenue_by_hairdresser` au fake `CashJournalRepository`).
- `tests/test_hairdresser_performance_e2e.py` — **créer** (agrégats SQL réels : prestations réalisées,
  taux d'annulation, **attribution du CA via `payments → appointments.hairdresser_id`**, filtre
  `COMPLETED`/`CANCELLED`, RDV non assignés exclus, isolation inter-salons, absence de PII).

**Web (`web-dashboard/`)**
- `src/application/ports/stats-gateway.ts` — **modifier** (`HairdresserPerformanceResult` +
  `hairdresserPerformance(...)`).
- `src/adapters/api/http-stats-gateway.ts` — **modifier** (implémentation `hairdresserPerformance`).
- `src/domain/stats/hairdresser-performance.ts` — **créer** (type + formatage taux/CA).
- `src/adapters/ui/hairdresser-performance-panel.tsx` — **créer** (tableau + état vide).
- `app/(gerant)/gerant/page.tsx` — **modifier** (charger + rendre le panneau sous
  `<ActiveClientsPanel>`).
- `web-dashboard/README.md` — **modifier**.
- `test/hairdresser-performance-panel.test.ts`, `test/hairdresser-performance-gateway.test.ts` —
  **créer** (Vitest).

**Documentation (racine)** : `README.md` ; **(recommandé, *Open Questions §9*)** `docs/adr/0031-…` +
`docs/adr/README.md`.

**À lire (sans modifier) pour rester fidèle aux patrons** : `adapters/inbound/stats.py`,
`application/service_demand.py`, `application/client_segments.py`, `domain/service_demand.py`,
`domain/client_segments.py`, `adapters/outbound/persistence/appointment_repository.py`
(`demand_by_service`, `segment_active_clients`), `adapters/outbound/persistence/
cash_journal_repository.py` (`net_revenue_between`, `list_for_salon` — résolution `full_name`),
`domain/revenue.py` (`month_bounds`), `web-dashboard/app/(gerant)/gerant/page.tsx`,
`src/adapters/api/http-stats-gateway.ts`, `src/adapters/ui/active-clients-panel.tsx`.

## API / Interface Changes

**Nouvelle route HTTP (backend), protégée** ; aucune route existante modifiée ; aucun chemin ajouté à
`PUBLIC_ROUTE_PATHS`.

`GET /salons/{salon_id}/hairdresser-performance`
- **Auth** : `Principal` requis (deny-by-default). Permission **`STATS_READ_SALON`** (`MANAGER`) **+**
  portée salon (`require_salon_scope`).
- **Query** : `date_from`, `date_to` *optionnels* (`AAAA-MM-JJ`, `Africa/Abidjan`). Absents (ou une
  seule fournie) = **mois civil courant** (résolu serveur). `date_to < date_from` → `422` ; date mal
  formée → `422`.
- **200** — corps :
  ```json
  {
    "currency": "XOF",
    "date_from": "2026-08-01",
    "date_to": "2026-08-31",
    "hairdressers": [
      {
        "hairdresser_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "hairdresser_name": "Awa Koné",
        "services_completed": 58,
        "revenue": "290000.00",
        "cancelled_count": 3,
        "total_count": 64,
        "cancellation_rate": "0.0469"
      }
    ]
  }
  ```
  (`services_completed`/`cancelled_count`/`total_count` = entiers ≥ 0 ; `revenue` = chaîne décimale ≥
  `0.00` ; `cancellation_rate` = chaîne décimale ∈ `[0, 1]`, `"0.0000"` si `total_count == 0` ; liste
  **vide** si aucun coiffeur assigné sur la période — état normal, pas d'erreur.)
- **401** jeton absent/invalide · **403** rôle insuffisant **ou** salon hors périmètre (générique,
  aucun oracle) · **422** `date_from`/`date_to` mal formée ou incohérente.

**OpenAPI** : documenté via schémas Pydantic + `responses`. **Web** : nouveau contenu de `/gerant` (pas
d'URL nouvelle) ; aucun Route Handler BFF ajouté si le fetch serveur direct est retenu (patron
#40→#42). Aucune autre surface (CLI, autres endpoints, variable d'environnement) modifiée.

## Data Model / Protocol Changes

**None.** Aucune table, colonne, contrainte ou migration Alembic. #43 est une **lecture dérivée** de
`appointments` / `appointment_services` / `payments` / `cash_journal` / `users` : `GROUP BY
hairdresser_id` avec des `COUNT FILTER` (planning) et une somme signée `PAYMENT`/`ADJUSTMENT` attribuée
via `payments.appointment_id` (caisse). Les index `ix_appointments_salon_id (salon_id,
appointment_date)`, `ix_payments_appointment_id`, `ix_payments_salon_id`, `ix_cash_journal_salon_id`
couvrent la requête (un index composite `(salon_id, hairdresser_id, appointment_date)` reste une
optimisation **optionnelle**, non introduite ici — *Open Questions §7*). `REVENUE_STATUSES`,
`AppointmentStatus`, `CashOperationType`, `ROLE_PERMISSIONS` réutilisés tels quels (aucune nouvelle
valeur d'énum, aucune nouvelle permission ; un `CANCELLED_STATUSES` **domaine** peut être ajouté comme
constante Python, sans effet base). Aucune colonne dénormalisée n'est écrite. La réponse ne porte que
des identifiants/nom d'affichage d'employé, des compteurs, des montants (`Decimal` en chaîne), un taux
(`Decimal` en chaîne) et des dates — jamais de PII client ni de contact employé.

## Security & Privacy Considerations

- **Émission d'identité employé — maîtrisée et conventionnelle (§11.3).** #43 **émet** le
  `hairdresser_id` et le **nom d'affichage** (`users.full_name`) de l'employé : c'est **nécessaire** au
  KPI (« performance **des coiffeurs** ») et **légitime** (le gérant gère ses employés, `EMPLOYEE_MANAGE`
  #13). Cette émission suit une **convention déjà en place** — `CashJournalRepository.list_for_salon`
  (#34) résout `performed_by → users.full_name` « sans exposer d'autre donnée sensible de l'auteur
  (§11.3) ». La réponse **n'émet jamais** `phone`, `email`, `role`, `status` ni condensat de l'employé,
  ni aucune PII **client** (`client_id`/`appointment_id`/nom/téléphone). C'est le **seul** endpoint stats
  nominatif — à la différence de #42 (anti-oracle client, `client_id` jamais émis) ; la distinction est
  **délibérée** (employé du salon ≠ client tiers) et doit être **documentée** (README/ADR).
- **Isolation §11.2 (multi-tenant).** Route salon-scopée (`require_salon_scope`) **+** re-filtrage
  `WHERE appointments.salon_id = :salon_id` (et `cash_journal.salon_id`) **inconditionnel** en SQL
  (défense en profondeur). Un salon hors périmètre est un **403 générique** indiscernable (aucun oracle).
  Le dépôt n'agrège **jamais** les coiffeurs ni la caisse d'un autre salon ; un même compte membre de
  deux salons est mesuré **par salon** (cloisonnement strict). La jointure `users` sur `hairdresser_id`
  ne peut ramener que des employés **effectivement assignés à des RDV du salon** (pas un annuaire global).
- **Deny-by-default (#12 / ADR-0015).** La route porte une garde de `Principal`
  (`require_permission(STATS_READ_SALON)`) ; **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` ; l'invariant
  testé `unprotected_routes(app) == []` reste vert.
- **RBAC inchangé.** `STATS_READ_SALON` est **déjà** au `MANAGER` (et seulement lui). **Ne pas**
  modifier `ROLE_PERMISSIONS`. `CLIENT`/`HAIRDRESSER`/`ADMIN` → 403. En particulier, un coiffeur **ne
  lit pas** sa propre performance via #43 (il n'a pas `STATS_READ_SALON`).
- **Minimisation des données (§11.3).** La réponse ne contient **que** `currency`/`date_from`/
  `date_to`/`hairdressers[]` (et par entrée : `hairdresser_id`, `hairdresser_name`,
  `services_completed`, `revenue`, `cancelled_count`, `total_count`, `cancellation_rate`). Les agrégats
  sont calculés **en base** (`GROUP BY`), pas en rapatriant les lignes de RDV/paiement ni les
  identités clients. Le schéma Pydantic est **explicite** et **figé par un test** qui échoue si un champ
  interdit apparaît.
- **Exactitude monétaire.** CA et taux en **`Decimal`** (revenu quantifié au centime `NUMERIC(12,2)` ;
  taux quantifié à N décimales) — **jamais** un flottant, backend **et** web (transport en chaîne). Le
  CA net suit la même règle de signe que #40/#34 (un paiement corrigé fait **baisser** le CA du coiffeur).
- **Aucune PII ni secret dans les logs.** Ni `logger`/`print` ni messages `4xx` ne portent d'identité
  client ou de contact employé ; les compteurs/montants (exposés au gérant légitime) ne sont **jamais**
  journalisés. Le jeton reste dans le cookie `httpOnly` côté web (invariant #14), jamais exposé ni passé
  en query.
- **Lecture pure — aucun effet de bord.** Aucune écriture, **aucune** entrée d'audit §11.4 (patron des
  lectures #39/#40/#41/#42) ; la consultation d'un KPI n'est pas journalisée.
- **Coût / latence (§12.1).** Deux `GROUP BY hairdresser_id` filtrés par salon + période, bornés par la
  base d'employés du **salon** (petit au MVP) et couverts par `ix_appointments_salon_id` /
  `ix_cash_journal_salon_id`. Sur un très gros salon, un index composite dédié reste une option
  (*Open Questions §7*) — non requis au MVP.

Le dépôt ne documente **aucune** contrainte supplémentaire (résidence, chiffrement applicatif) au-delà
de celles ci-dessus pour cette lecture.

## Testing Plan

**Backend — domaine (pur, sans I/O) — `tests/test_domain_hairdresser_performance.py`**
- `rank_hairdresser_performance` :
  - **taux d'annulation** : `cancelled_count / total_count` quantifié (`Decimal`, pas de flottant) ;
    `total_count == 0` → `Decimal("0")` (**pas** de `ZeroDivisionError`) ; arrondi déterministe ;
  - **ordre** : `-revenue`, puis `-services_completed`, puis `name`, puis `str(hairdresser_id)` ;
    égalités testées (deux coiffeurs à CA égal → départage services puis nom) ;
  - **vide** : `rows == ()` → `entries == ()` (période/devise échoées) ;
  - `HairdresserPerformance` conserve les compteurs bruts (le front peut afficher « 3/64 »).

**Backend — application — `tests/test_hairdresser_performance_usecase.py` (fakes des deux ports)**
- `SummarizeHairdresserPerformance.execute` : passe **`REVENUE_STATUSES`** et **`CANCELLED_STATUSES`**
  et les **bornes** au port `performance_by_hairdresser` (vérifier les arguments exacts) ; passe les
  bornes à `net_revenue_by_hairdresser` ; **fusionne par `hairdresser_id`** (CA `0.00` pour un coiffeur
  sans paiement attribué ; un CA sans ligne planning n'apparaît pas) ; assemble un
  `HairdresserPerformanceReport` cohérent ; **aucune** écriture/audit. Cas « aucun coiffeur » → rapport
  vide.

**Backend — inbound (FastAPI `TestClient` + `app.dependency_overrides`) — `tests/test_stats_api.py` (ou
`test_hairdresser_performance_api.py`)**
- `200` : performance correcte pour un salon peuplé (plusieurs coiffeurs, RDV `COMPLETED`/`CANCELLED`,
  paiements attribués) ; ordre du classement ; `revenue`/`cancellation_rate` en **chaîne**.
- **Défaut de période** : sans bornes (ou une seule) → **mois civil courant** (`month_bounds(_today())`)
  ; avec bornes → performance relative à la fenêtre.
- **Filtres de statut** : un RDV `PENDING`/`CONFIRMED` ne compte **pas** en prestations réalisées ni en
  CA ; un `CANCELLED` compte au numérateur du taux et au dénominateur, pas en prestations réalisées ; un
  `NO_SHOW` **ne compte pas** comme annulation (statut distinct — *Open Questions §5*).
- **Attribution du CA** : un paiement lié à un RDV assigné pèse dans le CA du bon coiffeur ; un paiement
  **sans RDV** (prestation directe) ou lié à un RDV **non assigné** n'apparaît dans **aucune** ligne
  coiffeur (résidu inattribuable) ; un `ADJUSTMENT` fait **baisser** le CA du coiffeur (net des
  corrections).
- **Bornes** : `date_to < date_from` → `422` ; date mal formée → `422`.
- `403` : `CLIENT`/`HAIRDRESSER`/`ADMIN` (sans `STATS_READ_SALON`) ; gérant d'**un autre salon** → 403
  générique.
- `401` : sans jeton.
- **Isolation** : un coiffeur/une caisse d'un **autre salon** n'apparaît pas ; RDV non assignés exclus.
- **Non-PII** : la réponse ne contient **aucune** clé interdite — test qui **échoue** si `client_id`,
  `appointment_id`, ou un **contact employé** (`phone`/`email`/`role`) apparaît ; `hairdresser_name` est
  le **seul** champ nominatif toléré.
- **`unprotected_routes(app) == []`** couvre automatiquement la nouvelle route ; vérifier qu'aucun
  chemin `hairdresser-performance` n'entre dans `PUBLIC_ROUTE_PATHS`, et **la non-collision** avec les
  autres routes `/salons/{salon_id}/…`.

**Backend — e2e PostgreSQL réel — `tests/test_hairdresser_performance_e2e.py`** *(patron
`test_service_demand_e2e.py` / `test_active_clients_e2e.py`, sur `coiflink-e2e-pg` port 55433)* :
couvrir les chemins SQL réels — `GROUP BY hairdresser_id` sur `appointments` (`COUNT FILTER` +
sous-requête `COUNT(appointment_services)` des `COMPLETED`), attribution du CA via `cash_journal →
payments → appointments` (`GROUP BY hairdresser_id`, somme signée `PAYMENT`/`ADJUSTMENT`), usage des
index, filtres de statut, isolation inter-salons et absence de PII. Scénarios : (a) coiffeur avec RDV
`COMPLETED` payés + un `CANCELLED` → prestations, CA net, taux corrects ; (b) `ADJUSTMENT` sur un
paiement du coiffeur → CA net baissé ; (c) RDV non assigné `COMPLETED` payé → **exclu** des lignes
coiffeur ; (d) même coiffeur assigné dans un **autre** salon → non compté ici ; (e) coiffeur sans RDV
sur la période → **absent**. (L'insertion peut nécessiter des écritures directes — assignation
`hairdresser_id`, paiements/journal — cf. patron des e2e existants.)

**Web (`web-dashboard/test/`, Vitest)**
- Rendu `/gerant` : le panneau « Performance des coiffeurs » s'affiche **sous** le panneau des clients
  actifs (#42), une ligne par coiffeur (nom, prestations, CA, taux « ×/× ») ; cas « 0 activité » → état
  vide ; cas « erreur backend » → dégradation locale (`null`), sans casser la page (patron #42).
- Gateway `hairdresserPerformance` : construit la bonne URL (`date_from`/`date_to` optionnels), passe le
  jeton en en-tête **serveur** (jamais exposé), mappe la réponse (montants/taux en chaîne, entiers),
  gère proprement `401/403/422/503`.
- Formatage : `formatXof` (FCFA) pour le CA et un formatage de pourcentage pour le taux ; cohérence avec
  les panneaux existants.

**Documentation / non-régression** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test) ;
`ruff check` propre ; `npm run lint && npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`backend/README.md`** — sous-section « Statistiques salon — performance des coiffeurs (US-6.5,
  #43) » : route, permission (**cinquième** usage de `STATS_READ_SALON`), réponses, **définition des
  trois indicateurs et de leurs sources** (prestations réalisées & taux d'annulation = planning
  `appointments` assignés ; CA = caisse nette attribuée via `payments → appointments.hairdresser_id`),
  **écarts de couverture** (CA inattribuable : paiements sans RDV, RDV non assignés ; `hairdresser_name`
  = nom d'affichage employé, **jamais** de contact) ; exemple `curl`.
- **`web-dashboard/README.md`** — mention du panneau « Performance des coiffeurs » sur `/gerant`, sous
  les clients actifs (US-6.4), et de l'extension du `http-stats-gateway`.
- **`README.md` racine** — §6 : phrase de statut « performance des coiffeurs (#43) livré » dans le style
  des paragraphes M5 existants (Épic 6), cohérence du tableau des jalons.
- **OpenAPI** — `summary`/`responses`/docstrings documentent la nouvelle API (visible sur `/docs`).
- **(Recommandé) ADR-0031** — `docs/adr/0031-performance-des-coiffeurs.md` + entrée
  `docs/adr/README.md` : acter (a) l'**émission de l'identité employé** dans une réponse stats (départ
  assumé du counts-only #42, convention #34) et (b) la **définition du CA par coiffeur** (caisse
  attribuée vs `price_at_booking`) et ses écarts de couverture. Plus justifié que pour #41/#42
  (*Open Questions §9*) — **à confirmer** au step `plan`/`document`.
- **BACKLOG.md** — marquer #43 livré le cas échéant (géré hors phase de code par le pipeline).

## Risks and Open Questions

1. **[Décision structurante] Définition du « CA généré » par coiffeur : caisse attribuée (recommandé)
   vs `price_at_booking`.** L'AC exige « cohérent avec la caisse ». **Recommandation : net de la caisse**
   (`cash_journal` `PAYMENT`/`ADJUSTMENT`, source de vérité #40/#34) **attribué** par la chaîne
   `payments.appointment_id → appointments.hairdresser_id` — **possible ici** (un paiement de RDV a **un**
   coiffeur), là où #41 ne pouvait pas ventiler un paiement multi-prestations. **Conséquence à assumer** :
   le CA inattribuable (paiements sans RDV / RDV non assignés) **n'est pas** réparti — la somme des CA par
   coiffeur **≠** le CA salon #40. *Alternative (Option A)* : `SUM(price_at_booking)` des RDV `COMPLETED`
   assignés — source **unique** (`appointments`, « cohérent avec le planning »), mais **divergent du cash
   net** (RDV réalisé non payé compté, correction #34 ignorée) — même caveat que #41. **À trancher au step
   `plan`** ; la spec supporte les deux sans changer la forme de la réponse.
2. **Axe temporel du CA & résidu inattribuable.** Recommandation : borner le CA par
   **`appointments.appointment_date`** (axe **planning**, comme les prestations/annulations) plutôt que
   par `cash_journal.created_at` (axe #40) — ce qui **aligne les trois indicateurs sur la même période**
   et renforce « cohérent avec le planning **et** la caisse ». Conséquence : le CA d'#43 (borné
   `appointment_date`) peut différer du CA #40 (borné `created_at`) sur une même fenêtre — **à documenter**.
   Le résidu inattribuable (paiements sans RDV, RDV non assignés) est **exclu** des lignes coiffeur ; une
   éventuelle ligne « Non attribué » agrégée est un **suivi produit** (non-goal MVP). **À confirmer.**
3. **[Sécurité/produit] Émission du nom du coiffeur.** Recommandation : **émettre `hairdresser_id` +
   `hairdresser_name` (`users.full_name`)** — nécessaire au KPI et conforme à la convention #34
   (résolution `full_name` pour l'UI, §11.3), **sans** contact (`phone`/`email`). Alternative :
   n'émettre que `hairdresser_id` et résoudre le nom via un futur endpoint « liste des employés »
   (inexistant au MVP → KPI illisible). **À confirmer** (et acter en ADR-0031, §9).
4. **Dénominateur du taux d'annulation.** Recommandation : `total_count` = **tous** les RDV assignés au
   coiffeur sur la période (tous statuts) ; `cancelled_count` = RDV `CANCELLED`. Simple et « cohérent
   avec le planning ». Alternatives : exclure les RDV **encore actifs** (`PENDING`/`CONFIRMED`, futurs)
   du dénominateur (taux « sur RDV clos » : `COMPLETED + CANCELLED + NO_SHOW`) — plus juste pour une
   fenêtre en cours, mais moins lisible. **À confirmer** (borner la définition en README/ADR).
5. **`NO_SHOW` compte-t-il comme annulation ?** Recommandation : **non** — `CANCELLED` et `NO_SHOW` sont
   des statuts **distincts** (annulation vs absence). Le taux d'annulation ne compte que `CANCELLED`. Un
   éventuel « taux d'absence » séparé est un **non-goal** (suivi). **À confirmer.**
6. **« Prestations réalisées » : occurrences de prestations vs nombre de RDV réalisés.** Recommandation :
   **occurrences `appointment_services`** des RDV `COMPLETED` (un RDV à 2 prestations = 2), **cohérent
   avec le volume #41** (« nombre de prestations »). Alternative : compter les **RDV** `COMPLETED`
   (« séances »). **À confirmer** ; veiller à **ne pas** sur-compter `total_count`/`cancelled_count` (qui
   comptent des **RDV**) via le join `appointment_services` (cf. §D, agrégats séparés).
7. **Index de couverture.** Le `GROUP BY hairdresser_id` filtré `salon_id` + période n'a pas d'index
   composite parfait (`ix_appointments_salon_id` couvre `(salon_id, appointment_date)`). Recommandation :
   **aucun nouvel index au MVP** (volume salon faible, §12.1 tenu) ; un index `(salon_id, hairdresser_id,
   appointment_date)` reste une **optimisation future** (mesure d'abord). **À confirmer.**
8. **[Vérification technique] Nom du segment de route & non-collision.** Recommandation :
   **`/{salon_id}/hairdresser-performance`** (segment distinct, sur le router `stats`). Vérifier par un
   test de routage qu'aucune requête n'est captée par `/{salon_id}/employees`, `/{salon_id}/customers/…`,
   `/{salon_id}/services/{service_id}` (parsing UUID) ni les autres routes stats. Alias possibles :
   `staff-performance`, `hairdressers/performance`. **À confirmer** (littéral = décision d'API publique).
9. **Un ADR est-il nécessaire ?** #39→#42 ont plié leurs décisions dans les README. Recommandation :
   **ADR-0031 recommandé** (plus que pour #41/#42) — #43 introduit l'**émission d'identité employé** en
   stats (§3) et la **définition du CA par coiffeur** (§1/§2) ; les acter formellement est utile.
   Alternative : README suffit si l'équipe juge ces choix mineurs. **À confirmer.**
10. **Coiffeurs sans activité sur la période.** Recommandation : **liste dérivée du planning** — seuls
    les coiffeurs **assignés à ≥ 1 RDV** sur la période apparaissent (cohérent #41/#42 : on ne liste que
    les entités actives). Alternative : partir de `salon_members` (rôle `HAIRDRESSER`, `ACTIVE`) pour
    afficher **tous** les coiffeurs, à zéro s'ils n'ont rien fait (utile pour comparer l'équipe) — plus
    coûteux et hors patron. **À confirmer.**
11. **Cohérence temporelle avec le fuseau.** Les bornes sont des **jours civils `Africa/Abidjan`**
    (UTC+0, convention #21) comparés à `appointments.appointment_date` (déjà une `date`, sans fuseau) —
    pas de conversion UTC nécessaire pour les métriques planning. Le CA attribué étant borné par
    `appointment_date` (§2), il partage cet axe. **À vérifier** dans les tests (pas de dérive de fuseau).

## Implementation Checklist

**Backend**
1. **Lire** `adapters/inbound/stats.py`, `application/service_demand.py`, `application/
   client_segments.py`, `domain/service_demand.py`, `domain/client_segments.py`,
   `adapters/outbound/persistence/appointment_repository.py` (`demand_by_service`,
   `segment_active_clients`), `adapters/outbound/persistence/cash_journal_repository.py`
   (`net_revenue_between`, `list_for_salon`), `domain/revenue.py` (`month_bounds`),
   `domain/appointment.py` (`REVENUE_STATUSES`) — s'imprégner des patrons #40→#42.
2. **Trancher** les Open Questions 1–10 (source du CA, axe temporel & résidu, émission du nom,
   dénominateur du taux, `NO_SHOW`, occurrences vs RDV, index, nom de route, ADR, coiffeurs inactifs) et
   consigner la décision (README, et ADR-0031 selon §9).
3. **Domaine** : créer `domain/hairdresser_performance.py` (`HairdresserActivity` /
   `HairdresserActivityCounts`, `HairdresserPerformance`, `HairdresserPerformanceReport`,
   `rank_hairdresser_performance`) ; ajouter `CANCELLED_STATUSES` à `domain/appointment.py` si absent ;
   `__all__`. Écrire `tests/test_domain_hairdresser_performance.py` **avant** le cas d'usage.
4. **Ports** : ajouter `performance_by_hairdresser` à `AppointmentRepository` et (variante caisse)
   `net_revenue_by_hairdresser` à `CashJournalRepository` (docstrings : `GROUP BY hairdresser_id`,
   isolation §11.2 en SQL, non-sur-comptage, attribution via `payments.appointment_id`, non-PII).
5. **Cas d'usage** : créer `application/hairdresser_performance.py::SummarizeHairdresserPerformance`
   (impose `REVENUE_STATUSES`/`CANCELLED_STATUSES`, passe les bornes, **fusionne** les deux sources par
   `hairdresser_id`, appelle `rank_hairdresser_performance` ; aucune écriture/audit) ; `__all__`. Écrire
   `tests/test_hairdresser_performance_usecase.py` via fakes (compléter `conftest.py`).
6. **Adapters outbound** : implémenter `performance_by_hairdresser` (agrégat RDV `COUNT FILTER` +
   sous-requête `COUNT(appointment_services)` des `COMPLETED` + join `users` pour le nom) et
   `net_revenue_by_hairdresser` (join `payments`/`appointments`, `GROUP BY hairdresser_id`, somme signée
   `PAYMENT`/`ADJUSTMENT`, bornes `appointment_date`).
7. **Adapter inbound** : ajouter à `stats.py` les schémas `HairdresserPerformanceItemResponse`/
   `HairdresserPerformanceResponse` (explicites, `revenue`/`cancellation_rate` en chaîne, **aucune PII
   client ni contact employé**) et la route `GET /salons/{salon_id}/hairdresser-performance` (gardes
   `require_salon_scope` + `require_permission(STATS_READ_SALON)`, `date_from`/`date_to` optionnels +
   défaut mois courant + garde `date_to < date_from → 422`, OpenAPI documenté) ; réutiliser les deux DI.
   **Ne pas** toucher `PUBLIC_ROUTE_PATHS` ; actualiser le **commentaire** d'assemblage / l'en-tête du
   router `stats` dans `main.py` (cinquième endpoint / usage `STATS_READ_SALON`).
8. **Tests API & e2e** : `tests/test_stats_api.py` (ou `test_hairdresser_performance_api.py`) —
   200/401/403/422, défaut mois courant, isolation, filtres de statut, attribution du CA, **non-PII**,
   non-collision de routage, `unprotected_routes == []` ; `tests/test_hairdresser_performance_e2e.py`
   (agrégats SQL réels, attribution CA, isolation, RDV non assignés exclus). Exécuter `pytest` (+
   `DATABASE_URL` pour l'e2e) et `ruff check`.
9. **Documentation backend** : `backend/README.md` (route + 5ᵉ usage `STATS_READ_SALON` + définitions &
   sources des indicateurs + écarts de couverture).

**Web**
10. **Domaine & accès** : `src/domain/stats/hairdresser-performance.ts` (type + formatage taux/CA) (+
    test) ; étendre `stats-gateway.ts` (`HairdresserPerformanceResult` + `hairdresserPerformance`) et
    `http-stats-gateway.ts` (implémentation, jeton serveur, montants/taux en chaîne) (+ test).
11. **UI & page** : `src/adapters/ui/hairdresser-performance-panel.tsx` (une ligne par coiffeur : nom,
    prestations, CA, taux + état vide) ; brancher `hairdresserPerformance(salon.id)` dans
    `app/(gerant)/gerant/page.tsx` et rendre le panneau **sous** `<ActiveClientsPanel>` (dégradation
    locale sur panne, patron #42).
12. **Tests Vitest** (panneau + gateway + formatage) ; `web-dashboard/README.md`.

**Documentation & vérification finale**
13. Mettre à jour `README.md` racine (avancement Épic 6 / US-6.5). **(Recommandé)** ADR-0031 + entrée
    `docs/adr/README.md` selon Open Questions §9.
14. `scripts/test-gate.sh` au vert (pytest + npm test + flutter test), `ruff check`, `npm run lint &&
    npm run build` ; relire la PR : **aucune PII client** (`client_id`, nom/téléphone client) ni
    **contact employé** (`phone`/`email`) en réponse, logs ou messages d'erreur ; `hairdresser_name`
    seul champ nominatif ; **aucune signature IA** introduite.
