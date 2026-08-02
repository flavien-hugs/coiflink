# Prestations les plus demandées — classement volume / revenu (dashboard gérant) (US-6.3, #41)

> Spécification de planification pour l'issue GitHub **#41 — US-6.3 : Prestations les plus
> demandées** (`feature` · Must · Effort **M** · PRD §6 Épic 6 US-6.3 / §8.1 / §11.2 / §11.3 / §12.1).
> **Dépend de #33** (US-5.1 — enregistrement d'un paiement) selon le backlog ; en pratique la brique
> réutilisée est **le prix figé des prestations réalisées** (`appointment_services.price_at_booking`
> des RDV `COMPLETED`, livré avec #21/#25), déjà exploitée par #31 — voir *Risks & Open Questions §1*.
> Repose aussi sur le shell du dashboard gérant (#14, zone `/gerant`), la permission
> `STATS_READ_SALON` (RBAC #12 / ADR-0015, **déjà** réservée au `MANAGER`, consommée par #39 puis #40)
> et le **router stats dédié** `adapters/inbound/stats.py` livré par #40 — que ce KPI **étend**.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants
> techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés. **Aucune signature
> IA** dans le code, les commits ou la PR. **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.

## Problem Statement

Le PRD (§6 Épic 6, US-6.3) pose le besoin : **« en tant que gérant, je veux connaître mes prestations
les plus demandées »**, spécification **« classement par volume et revenu généré »**. Le critère
d'acceptation de l'issue #41 est :

- **Top prestations par volume et par revenu.**

C'est le **troisième KPI du tableau de bord gérant** de l'Épic 6, après le décompte des RDV du jour
(#39, US-6.1) et le chiffre d'affaires jour/semaine/mois (#40, US-6.2). Il transforme la vue « combien
d'activité / combien de revenu » (agrégats globaux) en une vue **par prestation** : le gérant voit
*quelles prestations tirent son activité et son revenu*, pour ajuster son offre, sa tarification et son
staffing.

État actuel du dépôt (après #39/#40) — établi par **lecture du code**, pas par hypothèse :

- **Aucune lecture « par prestation » agrégée au niveau salon n'existe.** Le read model livré le plus
  proche, `domain/visit.py::favourite_services` (#31, US-4.3), classe les prestations d'**une fiche
  client** (`count` d'occurrences + `total_amount` = somme des `price_at_booking`, RDV `COMPLETED`), en
  agrégeant **en mémoire** les visites d'un seul client renvoyées par `CustomerRepository.list_visits`.
  #41 a **la même sémantique métier** (compter les occurrences réalisées, sommer les prix figés) mais à
  l'**échelle du salon** — sur **tous** les RDV `COMPLETED`, pas ceux d'une fiche —, ce qui appelle une
  **agrégation SQL** (`GROUP BY service_id`), pas un chargement de toutes les lignes en mémoire.
- **Le patron d'agrégation salon-scopée « en base » existe.** `SqlAppointmentRepository::
  count_by_status_for_day` (#39) fait déjà un `GROUP BY status` filtré `salon_id` + jour, renvoyant une
  map partielle `(status → count)` **sans rapatrier de ligne** ni de PII. #41 est le **même geste** avec
  un `GROUP BY service_id` et deux agrégats (`COUNT(*)` volume, `SUM(price_at_booking)` revenu).
- **Le router `stats` salon-scopé existe (#40).** `adapters/inbound/stats.py`
  (`APIRouter(prefix="/salons", tags=["stats"])`) porte `GET /salons/{salon_id}/revenue/summary` sous
  la garde `require_salon_scope` + `require_permission(STATS_READ_SALON)`. Son en-tête documente qu'il a
  été créé **précisément** pour accueillir « prestations les plus demandées #41 ». #41 y **ajoute une
  route** — c'est le **troisième** consommateur de `STATS_READ_SALON` (après #39/#40).
- **Le prix figé par prestation réalisée est la seule source de « revenu par prestation ».** La table
  `appointment_services` porte `price_at_booking` (`NUMERIC(12,2)`) par ligne (RDV × prestation) ; c'est
  le prix **facturé** de cette prestation dans ce RDV. Ni `payments` (lié à un RDV **ou** une prestation,
  un paiement de RDV multi-prestations n'étant **pas ventilé** par prestation) ni `cash_journal`
  (aucune dimension prestation) ne permettent un revenu **par prestation** — voir *Open Questions §1*.
- **Le libellé de prestation reste résoluble même après désactivation.** `services.name` est joignable
  (FK composite `(salon_id, service_id)`), et une prestation soft-deletée (`is_active = false`) reste en
  table (FK `RESTRICT`) : une prestation « top » retirée du catalogue **reste nommable** (miroir #31).
- **Le dashboard `/gerant` (Server Component) est le point d'accrochage.** `app/(gerant)/gerant/
  page.tsx` charge déjà, côté serveur (jeton du cookie `httpOnly`, invariant #14), le salon puis
  `dailySummary` (#39) et `revenueSummary` (#40) via `http-stats-gateway.ts`, et rend `DailySummaryTiles`
  + `RevenueTiles`. #41 **étend** cette page d'un panneau « Prestations les plus demandées » sous les
  tuiles CA.

Le gap que #41 comble : une **lecture agrégée salon-scopée** classant les prestations du salon par
**volume** (occurrences réalisées) **et** par **revenu généré** (somme des `price_at_booking`), exposée
par un **nouvel endpoint** sur le router `stats` et rendue par un **panneau** sur le dashboard gérant.
**Sans** migration ni changement de schéma : tout est dérivé en lecture des tables existantes.

## Goals

- **Classer les prestations du salon par volume et par revenu** (critère d'acceptation). Pour un salon,
  agréger ses RDV `COMPLETED` en une **liste de prestations** — chacune avec son `service_id`, son
  `name`, un **volume** (nombre d'occurrences réalisées) et un **revenu** (somme des `price_at_booking`
  de cette prestation) — et exposer **deux classements** : **par volume décroissant** et **par revenu
  décroissant**, chacun avec un ordre de départage **déterministe** (stable pour les tests).
- **Agréger « en base » (`GROUP BY service_id`), sans rapatrier de ligne ni de PII** : la lecture
  renvoie seulement `(service_id, name, volume, revenue)` par prestation — jamais un `client_id`, un
  `appointment_id`, un nom de client ni une ligne de RDV/paiement (§11.3, patron #39). Le tri
  déterministe des deux classements est une **fonction pure** du domaine (testable sans base).
- **Volume & revenu dérivés des RDV `COMPLETED` uniquement** (réalisés), en cohérence avec l'invariant
  §8.1 (`REVENUE_STATUSES == (COMPLETED,)`) et avec #31 (`HISTORY_STATUSES`). Un RDV
  `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne pèse **ni** en volume **ni** en revenu — « annulés
  exclus » (§8.1) est vrai **par construction** du filtre de statut. *(Interprétation « demande = toutes
  les réservations non annulées » discutée en Open Questions §2.)*
- **Revenu = somme des `price_at_booking`** (prix **figés** à la réservation, jamais le tarif courant),
  devise **XOF** (§9.6), `Decimal` de bout en bout (`NUMERIC(12,2)`, sérialisé en **chaîne** décimale,
  jamais de flottant) — même base de « revenu par prestation » que #31. La divergence assumée avec le CA
  du salon (#40, dérivé du **journal de caisse net**) est documentée (Open Questions §1).
- **Réutiliser strictement `STATS_READ_SALON`** (déjà détenue par le seul `MANAGER`) **+**
  `require_salon_scope` (isolation §11.2) — **sans** modifier `ROLE_PERMISSIONS`, exactement comme
  #39/#40. Troisième consommateur de cette permission.
- **Isolation §11.2, en profondeur.** Route salon-scopée (`require_salon_scope` → `403` **générique**,
  aucun oracle) **et** re-filtrage `WHERE salon_id = :salon_id` **inconditionnel** en SQL (défense en
  profondeur derrière la garde HTTP). Le dépôt n'agrège **jamais** les prestations d'un autre salon.
- **Lecture pure, sans effet de bord.** Aucune écriture, **aucune** entrée d'audit §11.4 (patron des
  lectures #34/#35/#37/#39/#40), aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` (une donnée d'exploitation
  salon n'est jamais publique).
- **Panneau « Prestations les plus demandées » sur le dashboard `/gerant`**, sous les tuiles CA (#40),
  en réutilisant le patron Server Component + `http-stats-gateway` (jeton serveur, jamais exposé). État
  **vide explicite** : « Aucune prestation réalisée sur la période » (salon sans RDV `COMPLETED`) —
  **pas** une erreur.
- **Additif et rétro-compatible** : aucune signature existante modifiée, **aucune migration** de schéma
  (les index `ix_appointments_salon_id (salon_id, appointment_date)` et
  `ix_appointment_services_service_id` couvrent la requête).
- **Couverture de tests** : domaine (tri déterministe des deux classements, montants figés, vide),
  cas d'usage (portée, filtre `COMPLETED`, bornes de période, cloisonnement inter-salons), API
  (`200`/`401`/`403`/`422`, absence de PII), e2e PostgreSQL (agrégat réel, isolation, index) ; web
  (mapping/formatage, gateway, rendu du panneau + bascule volume/revenu).

## Non-Goals

- **Aucune ventilation par coiffeur, par client ou par mode de paiement.** Ce sont d'autres US : la
  **performance des coiffeurs** (US-6.5 #43) et les **clients actifs** (US-6.4 #42). #41 agrège **par
  prestation** uniquement.
- **Aucun agrégat inter-salons ni vue admin.** #41 est **salon-scopé** (le gérant voit **son** salon).
  Les KPI plateforme relèvent de l'admin (#37 livré, #44 à venir).
- **Aucune série temporelle / courbe / tendance.** Un **classement** ponctuel sur une période, pas
  d'historique par jour ni de sparkline (post-MVP, PRD §16/§21).
- **Aucun recalcul du CA du salon.** #41 n'est **pas** une nouvelle source de vérité du chiffre
  d'affaires : le CA du salon reste #40 (journal de caisse net). Le « revenu par prestation » de #41
  (somme des `price_at_booking` `COMPLETED`) mesure une **grandeur différente** et peut ne pas
  s'additionner au CA #40 (Open Questions §1).
- **Aucune écriture / aucun audit §11.4.** Lecture pure (comme #39/#40).
- **Aucune modification de `ROLE_PERMISSIONS`** ni des droits `CLIENT`/`HAIRDRESSER`/`ADMIN`.
- **Aucune personnalisation du fuseau / du début de période par salon** : jour civil `Africa/Abidjan`
  (UTC+0, convention #21) si un filtre de période est retenu.
- **Aucune statistique côté client / mobile.** #41 est un parcours **gérant** (web) ; `app-mobile/`
  n'est **pas** touché.
- **Aucune colonne dénormalisée / compteur persisté.** #41 **dérive en lecture** ; aucun *trigger*,
  aucun couplage dans `SetAppointmentStatus` (#25) ou `RecordPayment` (#33).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Journalisation & prestations | Audit §11.4, prestations soft-delete | [0019](../docs/adr/0019-journalisation-audit-et-prestations.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête à **ADR-0030**. #39/#40 (KPI dashboard) ont plié leurs décisions dans les README
(pas d'ADR). Un ADR pour #41 est **optionnel** (voir Open Questions §8) : #41 ne change pas le schéma et
réutilise les patrons #31 (revenu par prestation via `price_at_booking`) et #39/#40 (agrégat salon-scopé
« en base », router stats, permission `STATS_READ_SALON`).

### Backend — patrons à réutiliser tels quels

- **Agrégat salon-scopé « en base » (#39)** : `SqlAppointmentRepository::count_by_status_for_day`
  (`GROUP BY status`, filtre `salon_id`, index `(salon_id, appointment_date)`, map partielle complétée
  par le domaine `build_daily_summary`). #41 est le même geste avec `GROUP BY service_id` + `COUNT` +
  `SUM(price_at_booking)`, joint à `appointment_services` et `services`.
- **Revenu par prestation via `price_at_booking` (#31)** : `domain/visit.py::favourite_services` définit
  déjà « occurrences réalisées » + « somme des prix figés » et un **tri déterministe** (fréquence, puis
  montant décroissant, puis `name`, puis `service_id`). #41 reprend cette sémantique à l'échelle salon,
  avec **deux** ordres (volume, revenu).
- **Endpoint stats salon-scopé (#40)** : `adapters/inbound/stats.py` — schémas Pydantic **explicites**
  (jamais `orm_mode`/`extra`), `total`/montant en **chaîne** décimale, OpenAPI documenté (`summary`,
  `responses` 200/401/403/422), gardes `require_salon_scope` + `require_permission(STATS_READ_SALON)`, DI
  surchargeable en test. Modèle **direct** de la nouvelle route.
- **Use case de lecture pure (#40)** : `application/revenue.py::SummarizeRevenue` (dépend d'un **port**,
  aucune I/O framework, aucun audit). Modèle direct de `SummarizeServiceDemand`.
- **Gardes de sécurité** (`adapters/inbound/security.py`) : `require_permission(Permission.X)` +
  `require_salon_scope` ; `403` **générique** ; l'invariant deny-by-default est vérifié mécaniquement par
  `unprotected_routes(app)` (`test_security_guards.py`) — **une route ajoutée sans garde fait échouer les
  tests**.
- **Tests** : fakes en mémoire (`tests/conftest.py`) + `TestClient` + `app.dependency_overrides` ; **e2e**
  adossés à un vrai PostgreSQL (`coiflink-e2e-pg`, port 55433 — cf. mémoire projet), patron
  `test_daily_summary_e2e.py` / `test_admin_transactions_e2e.py`. Fichiers de tests unitaires nommés par
  sujet : `test_domain_revenue.py`, `test_revenue_usecase.py`, `test_stats_api.py` (à **étendre** ou
  décliner en `*_service_demand_*`).

### Modèle de données pertinent (schéma #3, aucun changement)

```
appointments (id, salon_id, client_id, status, appointment_date, …)
  └─ appointment_services (appointment_id, service_id, salon_id, price_at_booking NUMERIC(12,2))
        └─ services (salon_id, id, name, is_active, …)            ← libellé (FK composite salon_id,service_id)
```

- Filtre : `appointments.salon_id = :salon_id AND appointments.status = 'COMPLETED'` (+ éventuelles
  bornes `appointment_date`), joint à `appointment_services` (`appointment_id`) puis `services`
  (composite `(salon_id, service_id)` — garantit l'appartenance salon du libellé).
- Agrégat : `GROUP BY appointment_services.service_id, services.name` ; `COUNT(*)` = volume,
  `COALESCE(SUM(appointment_services.price_at_booking), 0)` = revenu.
- Index couvrants **déjà présents** : `ix_appointments_salon_id (salon_id, appointment_date)`,
  `ix_appointment_services_service_id`. **Aucune migration** : #41 n'ajoute aucune colonne, contrainte ni
  index.

### Web gérant — patrons à réutiliser (#40)

- `app/(gerant)/gerant/page.tsx` — Server Component + composition root : lit le cookie, appelle les
  gateways **côté serveur**, rend les tuiles. #41 y ajoute un chargement + un panneau.
- `src/application/ports/stats-gateway.ts` + `src/adapters/api/http-stats-gateway.ts` — port + adapter
  HTTP en **union discriminée** (`{ ok: true, … } | { ok: false, reason }`), jeton jamais dans le
  résultat. `revenueSummary(...)` est le modèle direct de `serviceDemand(...)`.
- `src/domain/payments/revenue.ts` — types de domaine + formatage (`formatXof`, `formatPeriodRange`).
  `src/domain/customer/stats.ts` (#31) porte `formatOccurrences("×N fois")` réutilisable.
- `src/adapters/ui/revenue-tiles.tsx` / `customer-service-stats.tsx` — patrons d'affichage (tuiles /
  liste classée) à imiter pour le panneau.

### Contraintes transverses documentées

- **PRD §11.2** : un gérant ne voit que les données de son salon. **§11.3** : collecte minimale, pas de
  PII en logs. **§8.1** : le CA/le réalisé ne comptent que les RDV `COMPLETED` ; devise unique **XOF** ;
  montants `NUMERIC(12,2)` (jamais de flottant). **§12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**.
- **Test gate** : `scripts/test-gate.sh` (`pytest` + `npm test` + `flutter test`) ; CI `ci.yml` (ruff,
  pytest, round-trip Alembic contre PostgreSQL 16, build, lint/test/build web).

## Proposed Implementation

**Approche recommandée : backend-first, endpoint agrégé dédié (deux classements en une réponse) +
tranche web**, sur le patron #40. On **ne réutilise pas** `list_visits` (#31, chargé par fiche) ni une
liste de RDV : à l'échelle du salon, on **agrège en base** (`GROUP BY service_id`) et on ne rapatrie que
les lignes agrégées — respect de la minimisation (§11.3) et de la garde de coût (§12.1), miroir #39. La
règle métier « comment classer » (deux ordres déterministes) vit **dans le domaine**.

### (A) Backend — domaine (agrégation + tri, pur)

**`domain/service_demand.py`** — **créer** (module frère de `domain/revenue.py`, pur, sans I/O) :

```python
@dataclass(frozen=True)
class ServiceDemand:
    """Une prestation dans le classement du salon (US-6.3, #41).

    `volume` = nombre d'occurrences **réalisées** (une ligne `appointment_services`
    par occurrence, RDV `COMPLETED`) ; `revenue` = somme des `price_at_booking` de
    cette prestation (prix **figés**, XOF, jamais le tarif courant). `name` = libellé
    **courant** (`services.name`), résoluble même si la prestation est soft-deletée.
    Clé métier = `service_id` (deux prestations distinctes partageant un libellé ne
    sont pas fusionnées). `Decimal` de bout en bout, jamais de flottant.
    """
    service_id: uuid.UUID
    name: str
    volume: int
    revenue: decimal.Decimal


@dataclass(frozen=True)
class ServiceDemandRanking:
    """Classement des prestations d'un salon : mêmes entrées, deux ordres (US-6.3).

    `by_volume` = tri **volume décroissant** ; `by_revenue` = tri **revenu
    décroissant**. Chaque entrée porte **les deux** métriques (le web affiche « ×N
    fois · M FCFA » quel que soit l'onglet). `date_from`/`date_to` échoient la période
    couverte (`None` si toute l'histoire, cf. Open Questions §3). Ranking vide si aucun
    RDV réalisé (état normal, pas une erreur).
    """
    by_volume: tuple[ServiceDemand, ...] = ()
    by_revenue: tuple[ServiceDemand, ...] = ()
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    currency: str = DEFAULT_CURRENCY


def rank_service_demand(
    rows: tuple[ServiceDemand, ...],
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> ServiceDemandRanking:
    """Trie les prestations agrégées en deux classements déterministes (fonction pure).

    `by_volume` : `-volume`, puis `-revenue`, puis `name`, puis `str(service_id)`.
    `by_revenue` : `-revenue`, puis `-volume`, puis `name`, puis `str(service_id)`.
    Départages **stables** (indépendants de l'ordre SQL, utiles aux tests). Les `rows`
    proviennent d'un `GROUP BY service_id` (déjà dédupliquées par prestation) ; cette
    fonction **ne ré-agrège pas**, elle **ordonne**.
    """
```

- Réutiliser `DEFAULT_CURRENCY` (`domain/payment.py`). Exporter `ServiceDemand`, `ServiceDemandRanking`,
  `rank_service_demand` dans `__all__`.
- **Pourquoi un tri domaine et une agrégation SQL** : l'agrégat (`GROUP BY`) est fait en base (volume,
  index, minimisation), mais l'**ordre des deux classements** et les départages sont une règle métier
  **pure et testable** — miroir #39 (SQL fait le `GROUP BY`, `build_daily_summary` complète/ordonne).

### (B) Backend — port (lecture agrégée)

**`application/ports/appointment_repository.py`** — **ajouter** au `Protocol AppointmentRepository`
(foyer naturel : c'est déjà le port de l'agrégat salon-scopé sur `appointments`, cf.
`count_by_status_for_day`) :

```python
def demand_by_service(
    self,
    salon_id: uuid.UUID,
    *,
    statuses: tuple[str, ...],
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[ServiceDemand, ...]:
    ...
```

Docstring : renvoie, **par prestation**, le volume (`COUNT`) et le revenu (`SUM(price_at_booking)`) des
lignes `appointment_services` des RDV du salon dont le `status ∈ statuses` (et, si bornes fournies, dont
`appointment_date` est dans `[date_from, date_to]` **inclus**). Isolation §11.2 **imposée en SQL**
(`WHERE appointments.salon_id`). Lecture pure ; `Decimal` quantifié au centime ; ordre **non garanti**
(le domaine ordonne). *(Retourne des `ServiceDemand` non triés ; le use case appelle `rank_service_demand`.)*

*(Alternative : un port `SalonStatsRepository` dédié — voir Open Questions §7. Recommandation : étendre
`AppointmentRepository`, foyer de l'agrégat sur `appointments`, comme #39.)*

### (C) Backend — cas d'usage

**`application/service_demand.py`** — **créer** (dépend du seul port `AppointmentRepository`) :

```python
class SummarizeServiceDemand:
    """Classement des prestations d'un salon par volume et revenu (lecture — pas d'audit, #41)."""

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> ServiceDemandRanking:
        rows = self._appointments.demand_by_service(
            salon_id,
            statuses=REVENUE_STATUSES,           # (COMPLETED,) — §8.1 / cohérent #31
            date_from=date_from,
            date_to=date_to,
        )
        return rank_service_demand(
            rows, date_from=date_from, date_to=date_to
        )
```

- Réutilise `REVENUE_STATUSES` (`domain/appointment.py`) — **décidé serveur**, jamais soumis par
  l'appelant (« réalisées uniquement » garanti par construction). Lecture pure → **aucun** audit
  (patron `SummarizeRevenue`/`SummarizeDailyAppointments`). Ajouter au `__all__`.

### (D) Backend — adapter outbound (SQL)

**`adapters/outbound/persistence/appointment_repository.py`** — **implémenter** `demand_by_service`
(miroir `count_by_status_for_day` + `SqlPlatformTransactionRepository`) :

```python
stmt = (
    select(
        models.AppointmentService.service_id,
        models.Service.name,
        func.count().label("volume"),
        func.coalesce(func.sum(models.AppointmentService.price_at_booking), 0).label("revenue"),
    )
    .join(models.Appointment, models.Appointment.id == models.AppointmentService.appointment_id)
    .join(
        models.Service,
        (models.Service.id == models.AppointmentService.service_id)
        & (models.Service.salon_id == models.AppointmentService.salon_id),
    )
    .where(
        models.Appointment.salon_id == salon_id,
        models.Appointment.status.in_(statuses),
    )
    .group_by(models.AppointmentService.service_id, models.Service.name)
)
if date_from is not None:
    stmt = stmt.where(models.Appointment.appointment_date >= date_from)
if date_to is not None:
    stmt = stmt.where(models.Appointment.appointment_date <= date_to)
rows = self._session.execute(stmt).all()
return tuple(
    ServiceDemand(
        service_id=row.service_id,
        name=row.name,
        volume=int(row.volume),
        revenue=decimal.Decimal(row.revenue or 0).quantize(_AMOUNT_QUANTUM),
    )
    for row in rows
)
```

avec `_AMOUNT_QUANTUM = decimal.Decimal("0.01")`. Filtrer sur `appointments.salon_id` (défense en
profondeur §11.2) ; joindre `services` par la **composite** `(salon_id, service_id)` (appartenance
salon). Lecture pure : aucun `flush`. Requête couverte par `ix_appointments_salon_id` et
`ix_appointment_services_service_id`. *(Grouper aussi par `services.name` évite de porter une colonne
non agrégée ; un `service_id` a un `name` unique — pas de sur-découpe.)*

### (E) Backend — adapter inbound (route sur le router `stats` existant)

**`adapters/inbound/stats.py`** — **ajouter une route** au router `stats` (#40), **sans** créer de
router :

```python
@router.get(
    "/{salon_id}/service-demand",
    response_model=ServiceDemandResponse,
    summary="Prestations les plus demandées du salon (volume & revenu, US-6.3 §6)",
    responses={200: {...}, 401: {...}, 403: {...}, 422: {...}},
)
def get_service_demand(
    salon_id: uuid.UUID,
    appointment_repo: Annotated[AppointmentRepository, Depends(get_appointment_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[Principal, Depends(require_permission(Permission.STATS_READ_SALON))],
    date_from: Annotated[datetime.date | None, Query(...)] = None,
    date_to: Annotated[datetime.date | None, Query(...)] = None,
) -> ServiceDemandResponse: ...
```

- **Chemin `/{salon_id}/service-demand`** (segment **distinct**, jamais sous `/services/…`). ⚠️
  **Ne pas** utiliser `/{salon_id}/services/…` : `services.py` possède `GET /{salon_id}/services/
  {service_id}` (UUID typé) — un littéral (`demand`, `ranking`) y serait parsé comme `service_id` et
  renverrait `422`. Voir Open Questions §5.
- **Gardes** : `require_salon_scope` **+** `require_permission(STATS_READ_SALON)` (troisième
  consommateur). `salon_id` du chemin ; le dépôt refiltre en SQL.
- **Query** `date_from` / `date_to` **optionnels** (`AAAA-MM-JJ`, `Africa/Abidjan`) : absents = **toute
  l'histoire** ; une date mal formée → `422` (FastAPI). Si un seul est fourni, l'autre borne reste
  ouverte (semi-intervalle) ; si `date_to < date_from`, `422` (garde explicite, patron
  `list_salon_appointments`). *(Défaut de période : voir Open Questions §3.)*
- **DI** : réutiliser `get_appointment_repository` de `appointments.py` **ou** en déclarer un local dans
  `stats.py` (surchargeable en test via `app.dependency_overrides`).
- **Schémas Pydantic** (explicites, OpenAPI, patron #40) :
  - `ServiceDemandItemResponse` : `service_id: UUID`, `name: str`, `volume: int`,
    `revenue: Decimal` (sérialisé **chaîne**, `NUMERIC(12,2)`).
  - `ServiceDemandResponse` : `currency: str`, `date_from: date | None`, `date_to: date | None`,
    `by_volume: list[ServiceDemandItemResponse]`, `by_revenue: list[ServiceDemandItemResponse]`.
  - **Aucune PII** (pas de `client_id`/`appointment_id`/ligne de RDV) : figer la forme par un test qui
    échoue si un champ interdit apparaît (patron #37/#40).
- **`main.py` inchangé** : le router `stats` est **déjà** monté (#40). Actualiser seulement le
  commentaire d'assemblage du router `stats` pour mentionner le troisième endpoint (#41).

### (F) Web gérant — panneau « Prestations les plus demandées »

1. **Domaine TS** — `src/domain/payments/service-demand.ts` (ou `src/domain/stats/…`) : types
   `ServiceDemandItem` (`serviceId`, `name`, `volume`, `revenue: string`) et `ServiceDemandRanking`
   (`currency`, `dateFrom?`, `dateTo?`, `byVolume: []`, `byRevenue: []`). Réutiliser `formatXof`
   (`src/domain/payments/payment.ts`) et `formatOccurrences` (`src/domain/customer/stats.ts`). Le
   backend reste **l'autorité** des chiffres **et de l'ordre** ; le front **formate** et **bascule**
   entre deux listes **déjà triées** (jamais de re-tri côté front — invariant #31).
2. **Port & gateway** — étendre `src/application/ports/stats-gateway.ts` (type `ServiceDemandResult` en
   union discriminée, `reason: "forbidden" | "unauthenticated" | "invalid" | "unavailable"`) +
   `src/adapters/api/http-stats-gateway.ts` avec `serviceDemand(salonId, dateFromIso?, dateToIso?)` :
   `GET {API}/salons/{id}/service-demand?date_from&date_to`, jeton du cookie `httpOnly` (jamais exposé
   ni journalisé), montants en **chaîne**. Mapping `200/401/403/422/503` (miroir `revenueSummary`).
3. **UI** — `src/adapters/ui/service-demand-panel.tsx` : un panneau avec **bascule Volume / Revenu**
   (deux boutons/onglets rendant `byVolume` ou `byRevenue`), chaque ligne « rang · nom · ×N fois · M
   FCFA », état **vide** (« Aucune prestation réalisée sur la période ») et cap d'affichage top-N côté
   UI (Open Questions §4). Style aligné sur `revenue-tiles.tsx` / `customer-service-stats.tsx`.
4. **Page** — étendre `app/(gerant)/gerant/page.tsx` : après `revenueSummary`, charger
   `serviceDemand(salon.id)` (même jeton serveur) et rendre `<ServiceDemandPanel>` **sous**
   `<RevenueTiles>`. Un échec `serviceDemand` peut soit dégrader localement (message neutre) sans casser
   la page, soit retomber sur l'`ErrorPanel` global (aligner sur le comportement #40, qui casse la page
   sur erreur — Open Questions §6).

### (G) Documentation

- `backend/README.md` : ajouter `GET /salons/{salon_id}/service-demand` (route, permission, réponses,
  note « volume + revenu dérivés des `price_at_booking` des RDV `COMPLETED` »), signaler le **troisième**
  usage de `STATS_READ_SALON`.
- `web-dashboard/README.md` : le dashboard `/gerant` affiche désormais les prestations les plus demandées
  (US-6.3), sous le CA (US-6.2).
- `README.md` racine §6 : phrase de statut « prestations les plus demandées (#41) livré » ; cohérence du
  suivi M5.

## Affected Files / Packages / Modules

**Backend (`backend/coiflink_api/`)**
- `domain/service_demand.py` — **créer** (`ServiceDemand`, `ServiceDemandRanking`, `rank_service_demand`,
  `__all__`).
- `application/ports/appointment_repository.py` — **modifier** (ajouter `demand_by_service` au `Protocol`).
- `application/service_demand.py` — **créer** (`SummarizeServiceDemand`).
- `adapters/outbound/persistence/appointment_repository.py` — **modifier** (implémenter
  `demand_by_service` : `GROUP BY service_id`, `COUNT`, `SUM(price_at_booking)`).
- `adapters/inbound/stats.py` — **modifier** (schémas `ServiceDemandItemResponse`/`ServiceDemandResponse`,
  route `GET /salons/{salon_id}/service-demand`, `get_appointment_repository` en DI).
- `main.py` — **modifier** (uniquement le **commentaire** d'assemblage du router `stats` : ajouter le
  troisième endpoint / usage `STATS_READ_SALON`). *Router déjà monté (#40) — pas de `include_router`.*
- `domain/appointment.py` (`REVENUE_STATUSES`), `domain/payment.py` (`DEFAULT_CURRENCY`),
  `adapters/inbound/security.py`, `domain/permissions.py` — **lire** (réutilisation ; pas de modif).
- `backend/README.md` — **modifier**.

**Backend — tests**
- `tests/test_domain_service_demand.py` — **créer** (tri déterministe des deux classements, montants,
  vide).
- `tests/test_service_demand_usecase.py` — **créer** (statuts `COMPLETED` imposés, bornes passées au
  port, ranking assemblé) via un fake `AppointmentRepository`.
- `tests/test_stats_api.py` — **étendre** (ou `tests/test_service_demand_api.py` **créer**) : API
  `200`/`401`/`403`/`422`, absence de PII, isolation.
- `tests/conftest.py` — **modifier** (ajouter `demand_by_service` au `FakeAppointmentRepository` s'il
  existe ; sinon fake local).
- `tests/test_service_demand_e2e.py` — **créer** (agrégat SQL réel, isolation, filtre `COMPLETED`,
  bornes de période, absence de PII).

**Web (`web-dashboard/`)**
- `src/application/ports/stats-gateway.ts` — **modifier** (`ServiceDemandResult` + `serviceDemand(...)`).
- `src/adapters/api/http-stats-gateway.ts` — **modifier** (implémentation `serviceDemand`).
- `src/domain/payments/service-demand.ts` — **créer** (types + formatage).
- `src/adapters/ui/service-demand-panel.tsx` — **créer** (panneau + bascule volume/revenu + état vide).
- `app/(gerant)/gerant/page.tsx` — **modifier** (charger + rendre le panneau sous les tuiles CA).
- `web-dashboard/README.md` — **modifier**.
- `test/service-demand-panel.test.ts`, `test/service-demand-gateway.test.ts` — **créer** (Vitest).

**Documentation (racine)** : `README.md` ; (option) `docs/adr/0031-…` + `docs/adr/README.md`.

**À lire (sans modifier) pour rester fidèle aux patrons** : `adapters/inbound/stats.py`,
`application/revenue.py`, `domain/revenue.py`, `adapters/outbound/persistence/appointment_repository.py`
(`count_by_status_for_day`), `domain/visit.py` (`favourite_services`), `web-dashboard/app/(gerant)/gerant/
page.tsx`, `src/adapters/api/http-stats-gateway.ts`, `src/adapters/ui/revenue-tiles.tsx`.

## API / Interface Changes

**Nouvelle route HTTP (backend), protégée** ; aucune route existante modifiée ; aucun chemin ajouté à
`PUBLIC_ROUTE_PATHS`.

`GET /salons/{salon_id}/service-demand`
- **Auth** : `Principal` requis (deny-by-default). Permission **`STATS_READ_SALON`** (`MANAGER`) **+**
  portée salon (`require_salon_scope`).
- **Query** : `date_from`, `date_to` *optionnels* (`AAAA-MM-JJ`, `Africa/Abidjan`). Absents = **toute
  l'histoire**. `date_to < date_from` → `422`.
- **200** — corps (les deux classements portent les **mêmes** entrées, ordres différents) :
  ```json
  {
    "currency": "XOF",
    "date_from": null,
    "date_to": null,
    "by_volume": [
      { "service_id": "…", "name": "Coupe homme", "volume": 42, "revenue": "210000.00" },
      { "service_id": "…", "name": "Barbe",        "volume": 30, "revenue": "60000.00"  }
    ],
    "by_revenue": [
      { "service_id": "…", "name": "Coupe homme", "volume": 42, "revenue": "210000.00" },
      { "service_id": "…", "name": "Tresses",      "volume": 12, "revenue": "180000.00" }
    ]
  }
  ```
  (`volume` = entier ≥ 0 ; `revenue` = chaîne décimale ≥ `0.00` ; ranking **vide** si aucun RDV
  `COMPLETED` sur la période — état normal, pas d'erreur.)
- **401** jeton absent/invalide · **403** rôle insuffisant **ou** salon hors périmètre (générique, aucun
  oracle) · **422** `date_from`/`date_to` mal formée ou incohérente.

**OpenAPI** : documenté via schémas Pydantic + `responses`. **Web** : nouveau contenu de `/gerant` (pas
d'URL nouvelle) ; aucun Route Handler BFF ajouté si le fetch serveur direct est retenu (patron #40).
Aucune autre surface (CLI, autres endpoints, variable d'environnement) modifiée.

## Data Model / Protocol Changes

**None.** Aucune table, colonne, contrainte ou migration Alembic. #41 est une **lecture dérivée** de
`appointments` / `appointment_services` / `services` : `GROUP BY service_id` avec `COUNT` +
`SUM(price_at_booking)`. Les index `ix_appointments_salon_id (salon_id, appointment_date)` et
`ix_appointment_services_service_id` couvrent la requête. `REVENUE_STATUSES`, `AppointmentStatus`,
`ROLE_PERMISSIONS` réutilisés tels quels (aucune nouvelle valeur d'énum, aucune nouvelle permission).
Aucune colonne dénormalisée n'est écrite ; les montants sont lus tels quels (`price_at_booking`), agrégés
en `Decimal`, sérialisés en chaîne — jamais de flottant.

## Security & Privacy Considerations

- **Isolation §11.2 (multi-tenant).** Route salon-scopée (`require_salon_scope`) **+** re-filtrage
  `WHERE appointments.salon_id = :salon_id` **inconditionnel** en SQL (défense en profondeur). Un salon
  hors périmètre est un **403 générique** indiscernable (aucun oracle). Le dépôt n'agrège **jamais** les
  prestations d'un autre salon ; la jointure `services` par composite `(salon_id, service_id)` interdit
  d'emprunter un libellé hors salon.
- **Deny-by-default (#12 / ADR-0015).** La route porte une garde de `Principal`
  (`require_permission(STATS_READ_SALON)`) ; **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` (donnée
  d'exploitation salon) ; l'invariant testé `unprotected_routes(app) == []` reste vert.
- **RBAC inchangé.** `STATS_READ_SALON` est **déjà** au `MANAGER` (et seulement lui). **Ne pas** modifier
  `ROLE_PERMISSIONS`. `CLIENT`/`HAIRDRESSER`/`ADMIN` → 403.
- **Minimisation des données (§11.3).** La réponse ne contient **que** `service_id`, `name`, `volume`
  (entier) et `revenue` (`Decimal` en chaîne) par prestation, plus la période et la devise : **aucun**
  `client_id`, nom de client, `appointment_id`, `hairdresser_id`, ni ligne de RDV/paiement. L'agrégat est
  calculé **en base** (`GROUP BY`), pas en rapatriant les lignes. Le schéma Pydantic est **explicite** et
  **figé par un test** qui échoue si un champ interdit apparaît (patron #37/#40).
- **Exactitude monétaire.** `SUM(price_at_booking)` en **`Decimal`** quantifié au centime
  (`NUMERIC(12,2)`) — **jamais** un flottant, backend **et** web (transport en chaîne). Prix **figés** :
  le classement est stable et fidèle même après changement de tarif.
- **Aucune PII ni secret dans les logs.** Ni `logger`/`print` ni messages `4xx` ne portent de nom,
  téléphone ou détail client ; les libellés de prestation et montants (exposés au gérant légitime) ne
  sont **jamais** journalisés. Le jeton reste dans le cookie `httpOnly` côté web (invariant #14), jamais
  exposé ni passé en query.
- **Lecture pure — aucun effet de bord.** Aucune écriture, **aucune** entrée d'audit §11.4 (patron des
  lectures #39/#40) ; la consultation d'un KPI n'est pas journalisée.
- **Coût / latence (§12.1).** Un `GROUP BY` indexé par salon, borné par le **catalogue** (petit nombre de
  prestations distinctes). Sur période fournie, les bornes `appointment_date` exploitent
  `ix_appointments_salon_id`. Sans période (toute l'histoire), la charge reste un agrégat groupé (miroir
  #37) — acceptable au MVP ; un cap de période/`limit` reste une option (Open Questions §3/§4).

Le dépôt ne documente **aucune** contrainte supplémentaire (résidence, chiffrement applicatif) au-delà de
celles ci-dessus pour cette lecture.

## Testing Plan

**Backend — domaine (pur, sans I/O) — `tests/test_domain_service_demand.py`**
- `rank_service_demand` : `by_volume` trié `-volume` puis départages (`-revenue`, `name`, `service_id`) ;
  `by_revenue` trié `-revenue` puis départages (`-volume`, `name`, `service_id`) ; **égalités** testées
  (deux prestations à volume égal → départage par revenu ; à revenu égal → départage par `name` puis
  `service_id`) ; deux prestations partageant un **libellé** mais des `service_id` distincts restent
  **séparées** ; entrée vide → deux classements vides ; `Decimal` conservé (pas d'arrondi, pas de
  flottant).

**Backend — application — `tests/test_service_demand_usecase.py` (fake `AppointmentRepository`)**
- `SummarizeServiceDemand.execute` : passe **`REVENUE_STATUSES` (`COMPLETED`)** et les **bornes**
  reçues au port `demand_by_service` (vérifier les arguments exacts) ; assemble un `ServiceDemandRanking`
  cohérent (les deux ordres corrects, devise `XOF`, période échoée) ; **aucune** écriture/audit
  déclenchée. Cas « aucune ligne » → ranking vide.

**Backend — inbound (FastAPI `TestClient` + `app.dependency_overrides`) — `tests/test_stats_api.py` (ou
`test_service_demand_api.py`)**
- `200` : classements corrects pour un salon peuplé (plusieurs prestations, plusieurs RDV `COMPLETED`
  multi-prestations) ; `by_volume` et `by_revenue` ordonnés ; `revenue` en **chaîne**.
- **Filtre de statut** : un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne pèse **ni** en volume
  **ni** en revenu (« annulés exclus », §8.1).
- **Bornes de période** : sans `date_from`/`date_to` → toute l'histoire ; avec bornes → seules les
  prestations des RDV de la fenêtre comptent ; `date_to < date_from` → `422` ; date mal formée → `422`.
- `403` : `CLIENT`/`HAIRDRESSER`/`ADMIN` (sans `STATS_READ_SALON`) ; gérant d'**un autre salon** (hors
  portée) → 403 générique.
- `401` : sans jeton.
- **Isolation** : une prestation réalisée dans un **autre salon** n'apparaît **pas**.
- **Non-PII** : la réponse ne contient **aucune** clé autre que `currency`/`date_from`/`date_to`/
  `by_volume`/`by_revenue` (et `service_id`/`name`/`volume`/`revenue` par entrée) — test qui **échoue**
  si un champ interdit apparaît.
- **`unprotected_routes(app) == []`** couvre automatiquement la nouvelle route ; vérifier qu'aucun chemin
  `service-demand` n'entre dans `PUBLIC_ROUTE_PATHS`, et **la non-collision** avec `/{salon_id}/services/
  {service_id}` (une requête sur `/service-demand` atteint bien la route stats, pas un `422` de parsing
  UUID).

**Backend — e2e PostgreSQL réel — `tests/test_service_demand_e2e.py`** *(patron
`test_daily_summary_e2e.py` / `test_admin_transactions_e2e.py`, sur `coiflink-e2e-pg` port 55433)* :
couvrir le chemin SQL réel du `GROUP BY service_id` (`COUNT` + `SUM(price_at_booking)`), l'usage des
index, le filtre `COMPLETED`, les bornes `appointment_date`, l'**isolation inter-salons** (une prestation
d'un autre salon exclue) et l'absence de PII. Vérifier qu'une prestation **soft-deletée** (`is_active =
false`) mais présente dans un RDV `COMPLETED` reste **nommée** dans le classement.

**Web (`web-dashboard/test/`, Vitest)**
- Rendu `/gerant` : le panneau « Prestations les plus demandées » s'affiche **sous** les tuiles CA (#40),
  avec la bascule Volume/Revenu montrant respectivement `byVolume`/`byRevenue` **sans re-tri** ; cas « 0
  activité » → état vide ; cas « erreur backend » → dégradation (aligner sur #40).
- Gateway `serviceDemand` : construit la bonne URL (`date_from`/`date_to` optionnels), passe le jeton en
  en-tête **serveur** (jamais exposé), mappe la réponse (montants en chaîne, pas de flottant), gère
  proprement `401/403/422/503`.
- Formatage : `formatXof` (FCFA, entier, séparateur d'espace) et `formatOccurrences` (« ×N fois »)
  réutilisés ; cohérence avec l'affichage existant.

**Documentation / non-régression** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test) ;
`ruff check` propre ; `npm run lint && npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`backend/README.md`** — sous-section « Statistiques salon — prestations les plus demandées (US-6.3,
  #41) » : route, permission (**troisième** usage de `STATS_READ_SALON`), réponses, note « volume +
  revenu dérivés des `price_at_booking` des RDV `COMPLETED` » et la distinction avec le CA #40 (Open
  Questions §1) ; exemple `curl`.
- **`web-dashboard/README.md`** — mention du panneau « Prestations les plus demandées » sur `/gerant`,
  sous le CA (US-6.2), et de l'extension du `http-stats-gateway`.
- **`README.md` racine** — §6 : phrase de statut « prestations les plus demandées (#41) livré » dans le
  style des paragraphes M5 existants (Épic 6), cohérence du tableau des jalons.
- **OpenAPI** — `summary`/`responses`/docstrings documentent la nouvelle API (visible sur `/docs`).
- **(Option) ADR** — *a priori* **aucun ADR nouveau** (route additive, patrons #31/#39/#40 réutilisés).
  Si l'équipe veut acter la **définition de « revenu par prestation »** (`price_at_booking` `COMPLETED`
  vs paiements) ou la **convention de statut** (« demandées » = `COMPLETED`), un court ADR-0031 pourra la
  documenter — à confirmer (Open Questions §1/§2/§8).
- **BACKLOG.md** — marquer #41 livré le cas échéant (géré hors phase de code par le pipeline).

## Risks and Open Questions

1. **Source & définition du « revenu par prestation ».** Recommandation : **`SUM(appointment_services.
   price_at_booking)` sur les RDV `COMPLETED`** — la **seule** source d'un revenu **par prestation**
   (les `payments` d'un RDV multi-prestations ne sont **pas** ventilés par prestation ; `cash_journal`
   n'a **aucune** dimension prestation). C'est aussi la base « revenu par prestation » **déjà** livrée
   par #31. **Conséquence à assumer et documenter** : ce revenu **peut différer** du CA du salon (#40,
   dérivé du **journal de caisse net** — paiements réellement encaissés, net des `ADJUSTMENT`) : un RDV
   `COMPLETED` **non payé** compte ici mais pas dans le CA #40 ; une correction (#34) baisse le CA #40
   mais pas ce revenu. Ils mesurent des grandeurs différentes (valeur des prestations réalisées vs cash
   net encaissé). Le backlog note « Dépend de #33 » ; le **lien réel** est `price_at_booking` (#21/#25).
   **Confirmer** ce choix, ou trancher explicitement pour une définition payment-derived (non réalisable
   par prestation en l'état).
2. **« Demandées » = réalisées (`COMPLETED`) vs demandées (toutes réservations non annulées).**
   Recommandation : **`COMPLETED`** (réalisées), pour que **volume et revenu partagent la même
   population** (un classement cohérent) et rester aligné §8.1 / `REVENUE_STATUSES` / #31. Alternative :
   compter le **volume** sur toutes les réservations non `CANCELLED` (vraie « demande »), le **revenu**
   restant sur `COMPLETED` — mais deux populations rendent le classement ambigu. **À confirmer.**
3. **Période du classement.** Recommandation : **`date_from`/`date_to` optionnels** (Africa/Abidjan) ;
   absents = **toute l'histoire**. Alternatives : défaut **mois civil courant** (symétrie #40), ou plage
   **obligatoire** bornée (garde de coût, patron `MAX_PLANNING_RANGE_DAYS`). L'AC est **muette** sur la
   période — trancher le défaut le plus utile au dashboard (all-time simple, ou mois courant plus
   parlant). **À confirmer.**
4. **Top-N vs classement complet.** « Top prestations » suggère une **liste courte**. Recommandation :
   renvoyer le **classement complet** côté API (catalogue petit) et **capper l'affichage** côté UI (ex.
   top 5, avec « voir tout ») — miroir #31. Alternative : paramètre `limit` borné côté API. **À confirmer.**
5. **[Bloquant technique] Collision de routage.** `services.py` possède `GET /{salon_id}/services/
   {service_id}` (UUID typé) — **tout** chemin `/{salon_id}/services/<littéral>` (`demand`, `ranking`,
   `summary`) serait parsé comme `service_id` et renverrait `422`. Recommandation : **`/{salon_id}/
   service-demand`** (segment distinct). Alternatives : `/{salon_id}/stats/services`, `/{salon_id}/
   top-services`. **Vérifier** par un test de résolution de route (la requête atteint la route stats, pas
   un `422` de parsing). **À confirmer** (le littéral exact est une décision d'API publique).
6. **Dégradation du panneau si `serviceDemand` échoue.** #40 **casse la page** (`ErrorPanel` global) sur
   erreur. Recommandation : **s'aligner sur #40** au MVP (cohérence), ou dégrader **localement** le
   panneau (message neutre) en gardant tuiles RDV + CA lisibles (plus robuste, comme discuté pour #31).
   **À confirmer.**
7. **Foyer du port : `AppointmentRepository` (recommandé) vs port stats dédié.** Recommandation :
   **étendre `AppointmentRepository`** (déjà foyer de l'agrégat salon-scopé sur `appointments`, cf.
   `count_by_status_for_day`). Alternative : un `SalonStatsRepository` dédié (plus « propre » pour un
   futur module stats, mais plus de surface et un nouveau câblage DI). **À confirmer.**
8. **Un ADR est-il nécessaire ?** #39/#40 ont plié leurs décisions dans les README. Recommandation : ADR
   **optionnel** (README suffit) ; un ADR-0031 ne se justifie que pour acter la **définition de revenu
   par prestation** (§1) ou la **convention de statut** (§2). **À confirmer.**
9. **Deux classements en une réponse (recommandé) vs un seul classement + `sort` param.** Recommandation :
   **`by_volume` + `by_revenue`** (deux ordres, mêmes entrées) — colle à l'AC (« par volume **et** par
   revenu »), garde l'**ordre côté serveur** (invariant #31 « le front ne re-trie rien »), payload
   négligeable (borné par le catalogue). Alternative : une seule liste + `?sort=volume|revenue` (2 appels
   ou re-tri front). **À confirmer.**
10. **Prestation soft-deletée dans le classement.** Une prestation `is_active = false` présente dans un
    RDV `COMPLETED` reste **nommée** (FK `RESTRICT`, `services.name` joignable) — cohérent #31/#29. À
    **assumer explicitement** dans le README (le classement reflète l'historique réalisé, pas le catalogue
    courant).

## Implementation Checklist

**Backend**
1. **Lire** `adapters/inbound/stats.py`, `application/revenue.py`, `domain/revenue.py`,
   `adapters/outbound/persistence/appointment_repository.py` (`count_by_status_for_day`),
   `domain/visit.py` (`favourite_services`), `domain/appointment.py` (`REVENUE_STATUSES`) — s'imprégner
   des patrons #31/#39/#40.
2. **Trancher** les Open Questions 1–6 & 9 (source du revenu, statut, période, top-N, dégradation, forme
   de réponse) et consigner la décision (README, ou ADR-0031 selon §8).
3. **Domaine** : créer `domain/service_demand.py` (`ServiceDemand`, `ServiceDemandRanking`,
   `rank_service_demand` avec les **deux** tris déterministes) ; `__all__`. Écrire
   `tests/test_domain_service_demand.py` **avant** le cas d'usage.
4. **Port** : ajouter `demand_by_service(salon_id, *, statuses, date_from, date_to) ->
   tuple[ServiceDemand, ...]` au `Protocol AppointmentRepository` (docstring : `GROUP BY service_id`,
   `COUNT`/`SUM(price_at_booking)`, isolation §11.2 en SQL, `Decimal` centime).
5. **Cas d'usage** : créer `application/service_demand.py::SummarizeServiceDemand` (impose
   `REVENUE_STATUSES`, passe les bornes, appelle `rank_service_demand` ; aucune écriture/audit) ;
   `__all__`. Écrire `tests/test_service_demand_usecase.py` via un fake (compléter `conftest.py`).
6. **Adapter outbound** : implémenter `demand_by_service` dans `SqlAppointmentRepository` (`select` +
   `join` `appointment_services`/`services` composite + `where salon_id, status, [dates]` + `group_by
   service_id, name`, `func.count`, `func.coalesce(func.sum(price_at_booking), 0)`, quantize `0.01`).
7. **Adapter inbound** : ajouter à `stats.py` les schémas `ServiceDemandItemResponse`/
   `ServiceDemandResponse` (explicites, `revenue` en chaîne, aucune PII) et la route `GET /salons/
   {salon_id}/service-demand` (gardes `require_salon_scope` + `require_permission(STATS_READ_SALON)`,
   `date_from`/`date_to` optionnels + garde `date_to < date_from` → 422, OpenAPI documenté) ; DI
   `get_appointment_repository`. **Ne pas** toucher `PUBLIC_ROUTE_PATHS` ; actualiser le **commentaire**
   d'assemblage du router `stats` dans `main.py`.
8. **Tests API & e2e** : `tests/test_stats_api.py` (ou `test_service_demand_api.py`) —
   200/401/403/422, isolation, filtre `COMPLETED`, bornes, **non-PII**, non-collision de routage,
   `unprotected_routes == []` ; `tests/test_service_demand_e2e.py` (agrégat SQL réel, index, isolation,
   soft-delete nommée). Exécuter `pytest` (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
9. **Documentation backend** : `backend/README.md` (route + 3ᵉ usage `STATS_READ_SALON` + note revenu vs
   CA #40).

**Web**
10. **Domaine & accès** : `src/domain/payments/service-demand.ts` (types + réutilise
    `formatXof`/`formatOccurrences`) (+ test) ; étendre `stats-gateway.ts` (`ServiceDemandResult` +
    `serviceDemand`) et `http-stats-gateway.ts` (implémentation, jeton serveur, montants en chaîne) (+
    test).
11. **UI & page** : `src/adapters/ui/service-demand-panel.tsx` (bascule Volume/Revenu, top-N,
    état vide) ; brancher `serviceDemand(salon.id)` dans `app/(gerant)/gerant/page.tsx` et rendre le
    panneau **sous** `<RevenueTiles>` (aligner la gestion d'erreur sur #40).
12. **Tests Vitest** (panneau + gateway + formatage) ; `web-dashboard/README.md`.

**Documentation & vérification finale**
13. Mettre à jour `README.md` racine (avancement Épic 6 / US-6.3). (Option) ADR-0031 + entrée
    `docs/adr/README.md` selon Open Questions §8.
14. `scripts/test-gate.sh` au vert (pytest + npm test + flutter test), `ruff check`, `npm run lint &&
    npm run build` ; relire la PR : **aucune PII/secret** (client, `appointment_id`, jeton) en logs ou
    messages d'erreur, **aucune signature IA** introduite.
