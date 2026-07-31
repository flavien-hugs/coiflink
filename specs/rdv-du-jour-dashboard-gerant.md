# RDV du jour — décompte par statut (dashboard gérant) (US-6.1, #39)

> Épic 6 (Statistiques / Dashboard) · Priorité **Must** · Effort **S** · PRD §6 / §7.2 / §11.2 / §11.3
> Dépend de **#14** (shell du dashboard gérant : zone protégée `/gerant`, layout, navigation)
> et de **#25** (cycle de statuts gérant : `CONFIRMED`/`CANCELLED`/`COMPLETED`/`NO_SHOW`,
> `ALLOWED_STATUS_TRANSITIONS`). Repose aussi sur #21/#26 (RDV & lecture salon-scopée) et
> le RBAC #12/ADR-0015 (permission `STATS_READ_SALON` **déjà réservée** au `MANAGER`).

## Problem Statement

Le gérant, en ouvrant son **tableau de bord** (`/gerant`, livré vide et protégé par #14),
n'a aujourd'hui **aucun indicateur** : la page d'accueil affiche un simple encart
« Bientôt disponible » (`web-dashboard/app/(gerant)/gerant/page.tsx`). Pour piloter sa
journée, il doit ouvrir le **planning** (#26) et compter mentalement les rendez-vous par
état. Le besoin de l'US-6.1 est un **décompte synthétique du jour** :

> **Total, confirmés, annulés, terminés, absents.**
>
> **Critère d'acceptation :** *Le dashboard affiche le décompte du jour par statut.*

Le gap est double :

1. **Backend** — il n'existe **aucune** lecture agrégée des rendez-vous. La seule surface
   salon-scopée livrée est `GET /salons/{salon_id}/appointments` (#26), qui renvoie une
   **liste plate** de RDV (avec `client_note`, une donnée cliente §11.3) sur une plage.
   La permission `STATS_READ_SALON` (matrice RBAC `domain/permissions.py`) est **réservée
   au `MANAGER` mais n'est encore consommée par aucune route** — cette US en est le
   **premier consommateur**.
2. **Web** — la page d'accueil `/gerant` ne charge **aucune** donnée métier.

## Goals

- Exposer une **lecture agrégée salon-scopée** qui renvoie, pour un **jour civil**
  (`Africa/Abidjan`, convention #21, défaut = aujourd'hui), le **décompte des RDV du salon
  par statut** : `total` + un compteur par valeur de `AppointmentStatus`
  (`PENDING`, `CONFIRMED`, `CANCELLED`, `COMPLETED`, `NO_SHOW`).
- Garder cette lecture par la **permission `STATS_READ_SALON`** (déjà `MANAGER` dans
  `ROLE_PERMISSIONS`) **+** `require_salon_scope` — **sans modifier** la matrice des droits.
- Calculer les compteurs **en base** (`GROUP BY status`), **sans** rapatrier les lignes de
  RDV ni aucune PII (pas de `client_id`, pas de `client_note`, pas de `hairdresser_id`) —
  la réponse ne porte **que** des entiers et la date (§11.3).
- Afficher, sur le **dashboard gérant** (`/gerant`), les tuiles demandées par l'AC :
  **Total, Confirmés, Annulés, Terminés, Absents** (US-6.1).
- Préserver le **deny-by-default** (#12/ADR-0015) : la route porte une garde de `Principal`
  et n'est **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` ; l'isolation §11.2 est **ré-affirmée
  en SQL** (filtre `salon_id`), en défense en profondeur de la garde HTTP.
- Rester **additif et rétro-compatible** : aucune signature existante modifiée, aucune
  migration de schéma (l'index `ix_appointments_salon_id (salon_id, appointment_date)`
  couvre déjà la requête).

## Non-Goals

- **Aucune série temporelle ni graphique** (CA jour/semaine/mois, courbes, KPI financiers) :
  ils relèvent des US suivantes de l'Épic 6 (US-6.2+) et de l'encaissement (M4). Ici,
  **un seul jour**, **des compteurs de RDV** — rien d'autre.
- **Aucun détail de RDV** : ce n'est **pas** un « planning du jour ». Le drill-down (liste
  des RDV, ouverture d'une fiche) reste le rôle du planning (#26). L'agrégat ne renvoie
  aucune ligne individuelle.
- **Aucune écriture / aucun audit §11.4** : lecture pure (comme #26/#34/#35), aucun verbe
  destructif, la consultation n'est pas journalisée.
- **Aucune modification de `ROLE_PERMISSIONS`** ni des droits `CLIENT`/`HAIRDRESSER`/`ADMIN`.
- **Aucune vue « multi-salons »** : un gérant ne voit que **son** salon (portée propriété).
- **Aucune personnalisation de la journée par salon** (fuseaux/heures d'ouverture custom) :
  le jour civil est `Africa/Abidjan` (UTC+0), convention figée #21.

## Relevant Repository Context

**Stack (figée par ADR).** Backend **Python FastAPI**, **architecture hexagonale**
(ADR-0008) : `domain/` (pur) → `application/` (cas d'usage + `ports/`) →
`adapters/inbound|outbound/`. Persistance **PostgreSQL 16 / SQLAlchemy + Alembic**
(ADR-0004/0009). RBAC **deny-by-default** (ADR-0015, #12). Web gérant **Next.js**
(ADR-0002) en **BFF** (cookie `httpOnly`, jeton jamais exposé au navigateur, invariant #14).

**Domaine RDV (existant, `domain/appointment.py`, `domain/enums.py`).**
- `AppointmentStatus` = `PENDING | CONFIRMED | CANCELLED | COMPLETED | NO_SHOW` (source de
  vérité des valeurs stockées, PRD §9.4). La fonction `enums.values(AppointmentStatus)`
  fournit les valeurs dans l'ordre déclaré — à réutiliser pour **compléter** un décompte
  partiel (statuts sans RDV du jour = compteur **0**).
- La machine à états gérant (#25) est déjà portée (`ALLOWED_STATUS_TRANSITIONS`,
  `TERMINAL_STATUSES`) : les 4 statuts demandés par l'AC (`CONFIRMED`/`CANCELLED`/
  `COMPLETED`/`NO_SHOW`) sont exactement les cibles pilotées par le gérant.

**Lecture salon-scopée existante (à imiter, à ne pas dupliquer).**
- `adapters/inbound/appointments.py` — `GET /salons/{salon_id}/appointments`
  (`list_salon_appointments`) : **modèle de référence** de la route salon-scopée. Elle
  compose `require_salon_scope` (portée §11.2) **+** `require_permission(APPOINTMENT_READ_SALON)`,
  borne la plage (`MAX_PLANNING_RANGE_DAYS`), traduit les erreurs, et documente OpenAPI.
  La nouvelle route s'aligne sur ce patron mais **remplace la permission par
  `STATS_READ_SALON`** (concept « statistiques salon », pas « lecture du planning »).
- `application/appointments.py` — `ListSalonAppointments` : use case de lecture pure
  (délègue à un port, aucun audit). La nouvelle use case `SummarizeDailyAppointments`
  s'en inspire (même constructeur `__init__(appointment_repository)`).
- `application/ports/appointment_repository.py` — `AppointmentRepository` (`Protocol`) :
  `list_for_salon(salon_id, date_from, date_to, statuses)` en est le miroir. On y **ajoute**
  une méthode de comptage `count_by_status_for_day(...)` (additive, rétro-compatible).
- `adapters/outbound/persistence/appointment_repository.py` — implémentation SQLAlchemy à
  compléter par la requête `GROUP BY`.

**Patron d'agrégation SQL déjà éprouvé (#37, à imiter).**
- `domain/platform_transactions.py` + `application/ports/platform_transaction_repository.py`
  + son implémentation outbound : **modèle** d'un objet-valeur de lecture agrégé
  (`SalonTransactionSummary`) alimenté par une requête `func.count().filter(...)` /
  `group_by(...)`. La US-6.1 en est la contrepartie **RDV** (compteurs par statut).

**Fuseau / « jour du jour » (existant, `domain/time_window.py`).**
- `SALON_TIMEZONE = ZoneInfo("Africa/Abidjan")` (UTC+0, convention #21). La colonne
  `appointments.appointment_date` est un **`Date`** (jour civil, pas un instant) :
  « aujourd'hui » = `datetime.datetime.now(SALON_TIMEZONE).date()`. **Aucune** conversion
  de bornes UTC n'est nécessaire (contrairement à #35/#37 qui comparent un `created_at`
  `timezone-aware`) — la comparaison est `appointment_date = :day`.

**Modèle de données (existant, `persistence/models.py`).**
- `appointments` : `id`, `salon_id`, `client_id`, `hairdresser_id?`, `appointment_date DATE`,
  `start_time`, `end_time`, `status` (CHECK dérivé de `AppointmentStatus`), `client_note?`,
  `created_at`. **Index couvrant `ix_appointments_salon_id (salon_id, appointment_date)`** —
  la requête `WHERE salon_id = :sid AND appointment_date = :day GROUP BY status` l'exploite.
- **Aucune** modification de schéma requise → **pas de migration Alembic**.

**Assemblage / invariant de sécurité.** `main.py` monte
`FastAPI(dependencies=[Depends(require_authenticated)])` (deny-by-default global) et
`include_router(...)` par adapter. L'invariant `unprotected_routes(app) == []` est **testé** :
toute route ajoutée doit porter une garde de `Principal` (elle la portera via
`require_permission` + `require_salon_scope`) — **ne pas** la lister publique.

**Web gérant (existant, `web-dashboard/`).**
- `app/(gerant)/gerant/page.tsx` — page d'accueil **vide** (encart « Bientôt disponible »),
  cible de l'affichage. `layout` `(gerant)` garde déjà l'accès (gérant authentifié).
- `app/(gerant)/gerant/planning/page.tsx` — **Server Component** qui résout le salon du
  gérant (`http-salon-gateway`) puis charge les RDV **côté serveur** avec le jeton du cookie
  `httpOnly` (jamais exposé), via `http-appointment-gateway`. **Modèle de référence** :
  la page d'accueil chargera le décompte du jour de la même manière (fetch serveur direct,
  **pas** besoin d'un Route Handler BFF supplémentaire).
- `src/domain/appointment/planning-view.ts` — `todayIso()` (jour `Africa/Abidjan`) déjà
  disponible pour calculer le paramètre `date` par défaut.
- `src/adapters/api/http-appointment-gateway.ts` — gateway HTTP RDV existant ; on y ajoute
  (ou dans un gateway « stats » dédié) un appel `dailySummary(salonId, date)`.

## Proposed Implementation

**Approche recommandée : backend-first, endpoint agrégé dédié + tranche web.** On **ne
réutilise pas** `GET …/appointments` côté web pour compter les lignes en JavaScript : cela
rapatrierait des RDV entiers (dont `client_note`, PII §11.3) pour un simple besoin de
compteurs, et déplacerait une règle métier (le décompte) hors du backend. Un endpoint agrégé
respecte la minimisation des données (§11.3) et suit le précédent #37. *(Alternative web-only
en Open Questions.)*

### Backend

1. **Domaine — objet-valeur de décompte (`domain/appointment.py`, additif, pur).**
   Ajouter une `dataclass(frozen=True)` `DailyAppointmentSummary` :
   - `date: datetime.date`
   - `total: int`
   - `by_status: Mapping[str, int]` — **une entrée par valeur de `AppointmentStatus`**
     (statuts sans RDV = `0`), dans l'ordre de `enums.values(AppointmentStatus)`.
   Ajouter un constructeur pur `build_daily_summary(day, counts: Mapping[str, int]) ->
   DailyAppointmentSummary` qui **complète** un décompte partiel (issu du `GROUP BY`) : pour
   chaque valeur d'énum, `by_status[v] = counts.get(v, 0)` ; `total = sum(by_status.values())`.
   Fonction **pure**, testable sans base ; garantit par construction que **toutes** les tuiles
   ont une valeur (jamais de `KeyError` côté route/web) et que `total` est cohérent.
   *(Un statut renvoyé par la base et absent de l'énum ne peut pas exister — CHECK contraint ;
   le `build` ignore silencieusement toute clé inconnue plutôt que de fausser `total`.)*

2. **Port (`application/ports/appointment_repository.py`, additif).**
   Ajouter au `Protocol AppointmentRepository` :
   ```python
   def count_by_status_for_day(
       self, salon_id: uuid.UUID, day: datetime.date
   ) -> Mapping[str, int]:
       ...
   ```
   Docstring : renvoie `{status: count}` pour les RDV **du salon** dont
   `appointment_date == day`, **groupés par statut** (statuts sans RDV **absents** de la map —
   le domaine les complète à 0). Isolation §11.2 **imposée en SQL** (`WHERE salon_id`), défense
   en profondeur de `require_salon_scope`. Lecture pure, jamais un RDV d'un autre salon.

3. **Use case (`application/appointments.py`, additif).**
   `SummarizeDailyAppointments(appointment_repository)` avec
   `execute(salon_id, day) -> DailyAppointmentSummary` : appelle
   `count_by_status_for_day` puis `build_daily_summary`. Aucun audit, aucune écriture.
   Ajouter au `__all__`.

4. **Adapter outbound (`adapters/outbound/persistence/appointment_repository.py`).**
   Implémenter `count_by_status_for_day` :
   ```python
   rows = session.execute(
       select(Appointment.status, func.count())
       .where(Appointment.salon_id == salon_id, Appointment.appointment_date == day)
       .group_by(Appointment.status)
   ).all()
   return {status: count for status, count in rows}
   ```
   La requête est couverte par `ix_appointments_salon_id (salon_id, appointment_date)`.

5. **Adapter inbound (`adapters/inbound/appointments.py`, additif).**
   Nouvelle route :
   `GET /salons/{salon_id}/appointments/daily-summary`
   - Gardes : `require_salon_scope` **+** `require_permission(Permission.STATS_READ_SALON)`
     (premier consommateur de cette permission). `salon_id` du chemin ; le dépôt refiltre en SQL.
   - Query param **`date` optionnel** (`AAAA-MM-JJ`) : défaut = jour courant `Africa/Abidjan`
     (`datetime.datetime.now(SALON_TIMEZONE).date()`, via un helper de module analogue à `_now`).
     Une `date` mal formée → `422` (validation FastAPI). *(Aucune borne de plage : un seul jour.)*
   - Réponse `DailyAppointmentsSummaryResponse` (Pydantic) : `date: datetime.date`,
     `total: int`, `by_status: dict[str, int]` (clés = valeurs `AppointmentStatus`, toutes
     présentes). Documenter OpenAPI (`summary`, `responses` 200/401/403/422) sur le patron de
     `list_salon_appointments`. Aucune PII dans le schéma (que des entiers + la date).
   - **Ordre de montage** : déclarer la route **avant** toute route paramétrée susceptible de
     capter `daily-summary` comme segment (ce n'est pas le cas ici — les routes RDV existantes
     sont `/salons/{salon_id}/appointments` et `.../{appointment_id}/...` ; vérifier néanmoins
     qu'`{appointment_id}` ne capte pas `daily-summary`, sinon monter la route littérale avant).

### Web (tranche dashboard)

6. **Gateway (`web-dashboard/src/adapters/api/`).**
   Ajouter `dailySummary(salonId, dateIso)` au gateway RDV (`http-appointment-gateway.ts`)
   **ou** un `http-appointment-stats-gateway.ts` dédié : `GET
   {API}/salons/{id}/appointments/daily-summary?date=…`, jeton du cookie `httpOnly`
   (jamais exposé), mapping de la réponse en type de domaine `DailyAppointmentSummary`
   (dans `src/domain/appointment/`).

7. **Page d'accueil (`web-dashboard/app/(gerant)/gerant/page.tsx`).**
   La convertir en **Server Component** qui : résout le salon du gérant
   (`http-salon-gateway`) ; si aucun salon → invite à en créer un (comme la page planning) ;
   sinon charge le décompte du jour (`todayIso()`) et rend un **jeu de tuiles KPI** :
   **Total · Confirmés · Annulés · Terminés · Absents** (composant UI
   `src/adapters/ui/daily-summary-tiles.tsx`). `PENDING` est renvoyé par l'API mais **non
   affiché** dans les tuiles de l'AC (cf. Open Questions : ajouter éventuellement « En attente »).
   Réutiliser la garde du layout `(gerant)` ; aucun Route Handler BFF nécessaire (fetch
   serveur direct, patron du planning).

## Affected Files / Packages / Modules

**Backend (`backend/coiflink_api/`)**
- `domain/appointment.py` — **modifier** (ajouter `DailyAppointmentSummary` +
  `build_daily_summary`, étendre `__all__`).
- `application/ports/appointment_repository.py` — **modifier** (ajouter
  `count_by_status_for_day` au `Protocol`).
- `application/appointments.py` — **modifier** (ajouter `SummarizeDailyAppointments`,
  étendre `__all__`).
- `adapters/outbound/persistence/appointment_repository.py` — **modifier** (implémenter
  `count_by_status_for_day`).
- `adapters/inbound/appointments.py` — **modifier** (route `GET .../daily-summary`,
  schéma `DailyAppointmentsSummaryResponse`, helper « jour courant »).
- `domain/enums.py`, `domain/permissions.py`, `domain/time_window.py`,
  `adapters/inbound/security.py` — **lire** (réutilisation ; pas de modification attendue).

**Web (`web-dashboard/`)**
- `app/(gerant)/gerant/page.tsx` — **modifier** (Server Component + tuiles).
- `src/adapters/api/http-appointment-gateway.ts` (ou nouveau `…-stats-gateway.ts`) — **modifier/créer**.
- `src/domain/appointment/appointment.ts` (ou nouveau fichier) — **modifier/créer**
  (type `DailyAppointmentSummary`).
- `src/adapters/ui/daily-summary-tiles.tsx` — **créer** (tuiles KPI).
- `src/domain/appointment/planning-view.ts` — **lire** (`todayIso`).

**Tests** — voir Testing Plan.

## API / Interface Changes

**Nouvelle route HTTP (backend) :**

`GET /salons/{salon_id}/appointments/daily-summary`
- **Auth** : `Principal` requis (deny-by-default). Permission **`STATS_READ_SALON`**
  (`MANAGER`) **+** portée salon (`require_salon_scope`).
- **Query** : `date` *optionnel* (`AAAA-MM-JJ`) — défaut = aujourd'hui (`Africa/Abidjan`).
- **200** — corps :
  ```json
  {
    "date": "2026-07-31",
    "total": 12,
    "by_status": {
      "PENDING": 2, "CONFIRMED": 5, "CANCELLED": 1, "COMPLETED": 3, "NO_SHOW": 1
    }
  }
  ```
  (toutes les clés de statut présentes, valeurs ≥ 0 ; `total == somme(by_status)`).
- **401** jeton absent/invalide · **403** rôle insuffisant **ou** salon hors périmètre
  (générique, aucun oracle) · **422** `date` mal formée.

**OpenAPI** : documenté via le schéma Pydantic + `responses`. Aucune autre surface (CLI,
autres endpoints) modifiée.

**Web** : nouveau contenu de la page `/gerant` (pas d'URL nouvelle). Aucun Route Handler BFF
ajouté si le fetch serveur direct est retenu.

## Data Model / Protocol Changes

**None.** Aucune table, colonne, contrainte ou migration Alembic. La feature lit la table
`appointments` existante ; l'index `ix_appointments_salon_id (salon_id, appointment_date)`
couvre déjà la requête `GROUP BY`. `AppointmentStatus` et `ROLE_PERMISSIONS` sont réutilisés
tels quels (pas de nouvelle valeur d'énum, pas de nouvelle permission).

## Security & Privacy Considerations

- **Isolation §11.2 (multi-tenant).** Route salon-scopée : `require_salon_scope` (portée
  propriété du gérant) **+** re-filtrage `WHERE salon_id = :salon_id` en SQL (défense en
  profondeur). Un salon hors périmètre est un **403 générique** indiscernable (aucun oracle
  d'existence).
- **Deny-by-default (#12/ADR-0015).** La route porte une garde de `Principal`
  (`require_permission(STATS_READ_SALON)`) ; **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` ;
  l'invariant testé `unprotected_routes(app) == []` reste vert.
- **RBAC inchangé.** `STATS_READ_SALON` est **déjà** au `MANAGER` — **ne pas** modifier
  `ROLE_PERMISSIONS`. Le `CLIENT`/`HAIRDRESSER`/`ADMIN` ne l'ont pas → 403.
- **Minimisation des données (§11.3).** La réponse ne contient **que** des compteurs entiers
  et une date : **aucun** `client_id`, `client_note`, `hairdresser_id`, identité ou ligne de
  RDV. Le décompte est calculé en base (`GROUP BY`), pas en rapatriant les lignes.
- **Logs / redaction.** Aucun secret ni PII à journaliser (il n'y en a pas dans cette
  surface) ; ne pas logger le corps. Le jeton reste dans le cookie `httpOnly` côté web
  (invariant #14), jamais exposé au navigateur ni passé en query.
- **Coût / latence (§12).** Une seule requête indexée, agrégée, bornée à **un jour** — pas de
  plage, donc pas de garde `MAX_*_RANGE` nécessaire. Charge négligeable.

## Testing Plan

**Backend — domaine (pur, sans I/O)**
- `build_daily_summary` : complète les statuts manquants à `0` ; `total == somme` ; **toutes**
  les valeurs de `AppointmentStatus` présentes dans `by_status` ; décompte vide → tous `0`,
  `total == 0` ; clé inconnue ignorée sans fausser `total`.

**Backend — application**
- `SummarizeDailyAppointments.execute` avec un **fake `AppointmentRepository`** : mappe le
  décompte partiel du port vers un `DailyAppointmentSummary` complet ; passe bien `salon_id`
  et `day` au port ; aucune écriture/audit déclenchée.

**Backend — inbound (FastAPI `TestClient`, dépôt réel ou fake selon le patron du repo)**
- `200` : décompte correct par statut pour un salon peuplé (mélange des 5 statuts) ; `total`
  cohérent ; **toutes** les clés présentes.
- **Paramètre `date`** : sans `date` → jour courant `Africa/Abidjan` ; avec `date` explicite →
  ce jour ; RDV d'un autre jour **exclus**.
- `403` : `CLIENT`/`HAIRDRESSER`/`ADMIN` (sans `STATS_READ_SALON`) ; gérant d'**un autre
  salon** (hors portée) → 403 générique.
- `401` : sans jeton.
- `422` : `date` mal formée.
- **Isolation** : un RDV d'un **autre salon** au même jour n'apparaît **pas** dans le décompte.
- **Non-PII** : la réponse ne contient aucune clé autre que `date`/`total`/`by_status`.

**Backend — e2e PostgreSQL réel** *(patron des suites `test(#…)` récentes, cf.
`specs/suite-e2e-postgresql-module-clients.md` et
`specs/supervision-agregee-transactions-admin.md`)* : couvrir le chemin SQL réel du
`GROUP BY` sur `coiflink-e2e-pg` (port 55433), vérifier l'usage de l'index et le décompte
multi-statuts.

**Web (`web-dashboard/test/`, Vitest)**
- Rendu de la page `/gerant` : tuiles **Total/Confirmés/Annulés/Terminés/Absents** avec les
  valeurs du gateway ; cas « aucun salon » → invite à créer un salon ; cas « 0 RDV » → tuiles
  à `0`.
- Gateway `dailySummary` : construit la bonne URL (`date` = `todayIso()` par défaut), passe le
  jeton en en-tête serveur (jamais exposé), mappe la réponse ; erreur backend gérée proprement.

## Documentation Updates

- **`backend/README.md`** — ajouter la route `GET /salons/{salon_id}/appointments/daily-summary`
  à la liste des endpoints RDV / signaler le **premier usage de `STATS_READ_SALON`**.
- **`web-dashboard/README.md`** — noter que le dashboard `/gerant` affiche désormais le
  décompte du jour (US-6.1).
- **`README.md` racine** — cocher/ajouter US-6.1 (#39) dans l'avancement du MVP (Épic 6),
  cohérent avec le suivi des issues livrées.
- **ADR** — *a priori* **aucun ADR nouveau** (pas de décision d'architecture structurante :
  route additive dans un module existant, patron d'agrégation déjà acté par #37). Si l'équipe
  juge la convention « endpoints `*/summary` agrégés Épic 6 » digne d'être fixée, un court ADR
  pourra la documenter — à confirmer (Open Questions).
- **BACKLOG.md** — marquer #39 livré le cas échéant (géré hors phase de code par le pipeline).

## Risks and Open Questions

1. **Périmètre : backend + web, ou backend seul ?** Les livraisons récentes (#36/#37) ont été
   « backend-first », la tranche web restant optionnelle. Recommandation : livrer **backend +
   la tuile web** (l'AC parle explicitement du « dashboard »), mais confirmer si la tranche web
   est attendue dans cette même issue ou différée.
2. **Alternative web-only (sans nouvel endpoint) :** consommer `GET …/appointments?
   date_from=today&date_to=today` et compter côté serveur Next.js. **Écartée** ici (rapatrie de
   la PII `client_note` et déplace la règle métier hors backend), mais à **confirmer** si l'on
   veut éviter toute nouvelle surface backend pour un effort **S**.
3. **`PENDING` (« en attente ») dans l'UI :** l'AC liste **Total, Confirmés, Annulés, Terminés,
   Absents** — `PENDING` n'y figure pas. L'API le renvoie (complétude), mais faut-il **aussi**
   afficher une tuile « En attente » sur le dashboard ? À confirmer (défaut proposé : ne pas
   l'afficher, pour coller à l'AC).
4. **Sens de « Total » :** total = **tous** les RDV du jour (y compris `PENDING`), donc
   `total ≥ Confirmés + Annulés + Terminés + Absents`. Confirmer que c'est bien l'attendu (vs
   « total des seuls statuts affichés »). Recommandation : **tous statuts** (plus honnête).
5. **Fuseau « aujourd'hui » :** figé à `Africa/Abidjan` (UTC+0, convention #21). Un salon hors
   de ce fuseau verrait une frontière de jour décalée — hors périmètre MVP (convention globale).
6. **Collision de route :** vérifier que la route littérale `daily-summary` n'est pas captée par
   une route paramétrée `{appointment_id}` du même préfixe ; monter la route littérale en
   premier au besoin (test de non-régression sur le routage).
7. **Statuts terminaux du jour :** un RDV pris un autre jour mais passé `COMPLETED`/`CANCELLED`
   aujourd'hui reste compté **sur son `appointment_date`**, pas sur la date de transition (le
   décompte est « RDV **planifiés** ce jour, par statut courant »). Confirmer cette sémantique
   (recommandée : elle correspond au « planning du jour »).

## Implementation Checklist

**Backend**
1. `domain/appointment.py` : ajouter `DailyAppointmentSummary` (`date`, `total`, `by_status`) +
   `build_daily_summary(day, counts)` (pur, complète les statuts à 0 via
   `enums.values(AppointmentStatus)`, calcule `total`) ; étendre `__all__`.
2. `application/ports/appointment_repository.py` : ajouter
   `count_by_status_for_day(salon_id, day) -> Mapping[str, int]` au `Protocol` (docstring
   isolation §11.2 + « statuts absents ⇒ non listés »).
3. `application/appointments.py` : ajouter `SummarizeDailyAppointments` (délègue au port +
   `build_daily_summary`, aucune écriture/audit) ; étendre `__all__`.
4. `adapters/outbound/persistence/appointment_repository.py` : implémenter
   `count_by_status_for_day` (`select(status, func.count()).where(salon_id, appointment_date)
   .group_by(status)`).
5. `adapters/inbound/appointments.py` : ajouter le schéma `DailyAppointmentsSummaryResponse`,
   un helper « jour courant `Africa/Abidjan` », et la route
   `GET /salons/{salon_id}/appointments/daily-summary` (gardes `require_salon_scope` +
   `require_permission(STATS_READ_SALON)`, `date` optionnel, OpenAPI documenté). Vérifier le
   non-conflit de routage avec `{appointment_id}`.
6. Tests domaine + application + inbound (200/401/403/422, isolation, non-PII, défaut `date`).
7. Suite e2e PostgreSQL réelle du chemin `GROUP BY` (cf. Testing Plan).
8. Lint/format et gate de tests du repo (backend) au vert.

**Web**
9. Ajouter le type `DailyAppointmentSummary` (`src/domain/appointment/`) et l'appel
   `dailySummary(salonId, dateIso)` au gateway (jeton serveur, jamais exposé).
10. Convertir `app/(gerant)/gerant/page.tsx` en Server Component : résoudre le salon,
    charger le décompte (`todayIso()`), rendre les tuiles **Total/Confirmés/Annulés/Terminés/
    Absents** (`src/adapters/ui/daily-summary-tiles.tsx`) ; gérer « aucun salon » et « 0 RDV ».
11. Tests Vitest (page + gateway).

**Documentation**
12. Mettre à jour `backend/README.md`, `web-dashboard/README.md`, `README.md` racine
    (avancement Épic 6 / US-6.1). Aucun ADR sauf décision explicite (Open Questions).
