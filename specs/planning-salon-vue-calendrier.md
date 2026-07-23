# Planning du salon — vue calendrier (jour/semaine/mois) (US-3.5)

> Spécification de planification pour l'issue GitHub **#26 — US-3.5 : Planning du salon (vue
> calendrier)** (`feature` · `ux` · Must · Effort M · PRD §6 Épic 3 / §5.2). **Dépend de #25**
> (cycle de statuts gérant) et s'appuie sur le chemin rendez-vous livré par #21/#22/#23/#24/#25.
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, enums SQL) inchangés. **Aucune
> signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 3, US-3.5) pose le besoin : **« en tant que gérant, je veux voir le planning du
jour »**, avec pour spécification fonctionnelle une **vue calendrier jour/semaine/mois**. Le parcours
gérant §5.2 le détaille : *« il consulte le planning du jour ; il voit les rendez-vous confirmés, en
attente, annulés ou terminés »* — préalable direct aux étapes suivantes (assigner un coiffeur,
confirmer l'arrivée, marquer réalisé, encaisser). Le critère d'acceptation de l'issue #26 est :

- **Le planning affiche les RDV du jour par statut** et **se met à jour après changement de statut**.

C'est la **première surface de visualisation gérant** des rendez-vous. Là où #25 a livré la
**capacité serveur** de piloter le statut d'un RDV (`POST /salons/{salon_id}/appointments/{id}/status`)
et d'assigner un coiffeur (`PUT .../hairdresser`), **aucune interface ne permet encore au gérant de
lister les RDV de son salon** — ni de choisir lequel piloter. #26 comble ce vide côté **web gérant**.

État actuel du dépôt (après #21→#25) :

- **Il n'existe aucune lecture salon-scopée des rendez-vous.** Les seules routes de lecture sont
  `GET /catalog/salons/{salon_id}/availability` (**publique**, ne renvoie que les créneaux *libres*,
  jamais les RDV) et `GET /appointments` (RDV **actifs du client** authentifié). La permission
  **`APPOINTMENT_READ_SALON`** existe dans la matrice §4.1 (`domain/permissions.py`, détenue par le
  `MANAGER`) mais **n'est câblée sur aucune route**. Le port `AppointmentRepository` n'a **aucune**
  méthode de liste salon-scopée (il porte `booked_slots`, `create`, `get_owned`, `update`, `cancel`,
  `get_in_salon`, `set_status`, `assign_hairdresser`, `list_for_client` — mais rien pour « lister les
  RDV d'un salon sur une période »). **#26 doit livrer ce chemin de lecture.**
- **La capacité de changement de statut existe (côté serveur, #25) mais sans UI.** Le gérant peut,
  via l'API, confirmer/refuser/terminer/marquer-absent (`POST .../status`) et (dés)assigner un
  coiffeur (`PUT .../hairdresser`). Aucune page web ne consomme ces routes aujourd'hui.
- **Côté web (Next.js), la section « Planning » est `coming-soon`** : `web-dashboard/src/domain/
  navigation/sections.ts` déclare l'entrée `planning` (`href: "/gerant/planning"`,
  `status: "coming-soon"`, catégorie `operations`), **sans page** sous `app/(gerant)/gerant/`.
  Aucune vue ne liste ni n'affiche de rendez-vous.
- **Le socle web est mûr et éprouvé.** Les patrons *Server Component → gateway HTTP (jeton lu du
  cookie httpOnly, jamais exposé) → BFF Route Handler → mutation client + `router.refresh()`* sont
  établis par #15/#16/#17/#20 (voir `prestations/page.tsx`, `http-service-gateway.ts`, `service-list.
  tsx`, `app/api/salons/[id]/services/...`). Des **calculs de calendrier purs** existent déjà
  (`domain/salon/month-calendar.ts` : grille mensuelle lundi→dimanche, réutilisable pour la vue mois).
- **Le schéma suffit.** La table `appointments` (statuts, dates, `hairdresser_id`, `client_id`) et
  l'index `ix_appointments_salon_id (salon_id, appointment_date)` (schéma #3) couvrent une lecture
  salon-scopée par plage de dates. **Aucune migration n'est nécessaire.**

Le gap que #26 comble : **(1)** un **endpoint de lecture salon-scopé** `GET /salons/{salon_id}/
appointments` (câblant `APPOINTMENT_READ_SALON` + `require_salon_scope`) filtrable par **plage de
dates** et, optionnellement, par **statut** ; **(2)** une **page web gérant `/gerant/planning`** avec
**vues jour / semaine / mois**, affichant les RDV **groupés par statut**, et permettant de **piloter
le statut** d'un RDV (réutilisant les routes #25) avec **mise à jour immédiate** de la vue.

## Goals

- **Lecture salon-scopée des rendez-vous (backend).** `GET /salons/{salon_id}/appointments` renvoie
  les RDV du salon sur une **plage de dates** (`date_from`/`date_to` inclusifs), triés
  chronologiquement, **tous statuts** par défaut, avec un **filtre optionnel par statut**. Câble la
  permission **`APPOINTMENT_READ_SALON`** (jamais câblée jusqu'ici) **+** `require_salon_scope`
  (isolation §11.2). Aucun nouveau schéma.
- **Isolation par salon (§11.2).** La route est **salon-scopée** (`require_salon_scope`, `403`
  générique hors périmètre) **et** le dépôt refiltre `salon_id` en SQL (défense en profondeur). Un
  gérant ne lit **que** les RDV de son salon ; un salon hors périmètre est un `403` indiscernable
  (aucun oracle).
- **Vue calendrier jour / semaine / mois (web gérant).** La page `/gerant/planning` propose les
  **trois échelles** (PRD §5.2), la **vue jour** étant le cœur qui satisfait l'acceptation (« les RDV
  du jour par statut »). Semaine et mois offrent une **vue d'ensemble** (agenda hebdomadaire, grille
  mensuelle avec compteurs par statut).
- **Affichage par statut.** Les RDV sont **groupés/colorés par statut** (`PENDING`, `CONFIRMED`,
  `CANCELLED`, `COMPLETED`, `NO_SHOW`) avec une **légende** et un **filtre** (afficher/masquer un
  statut). Le vocabulaire de statut affiché est **francisé** (en attente, confirmé, annulé, terminé,
  absent).
- **Mise à jour après changement de statut.** Depuis le planning, le gérant **confirme / refuse /
  termine / marque-absent** un RDV (réutilisant `POST /salons/{salon_id}/appointments/{id}/status`,
  #25) ; la vue **se rafraîchit** immédiatement (`router.refresh()` du Server Component, relecture de
  la source de vérité backend). C'est le second volet de l'acceptation.
- **Respect de la machine à états (#25).** L'UI **n'invente aucune transition** : elle ne propose que
  les actions autorisées par l'état courant (p. ex. *Confirmer*/*Refuser* sur `PENDING` ;
  *Terminer*/*Absent* sur `CONFIRMED` ; **aucune** action sur un RDV terminal) — le backend reste
  l'**arbitre** (deny-by-default, `409` sur transition interdite, traduite en message neutre côté UI).
- **Jeton jamais exposé (#14).** Toute lecture/écriture backend passe **côté serveur Next** (Server
  Component + Route Handlers BFF) avec le jeton lu du cookie `httpOnly` — **jamais** transmis au
  navigateur, **jamais** journalisé (invariant #14, §11.3).
- **Couverture de tests.** Backend (port/adapter de lecture, cas d'usage, HTTP : portée, filtre,
  deny-by-default, `403` hors salon) ; web (gateway HTTP, BFF, calculs de calendrier purs, groupement
  par statut, garde de session).

## Non-Goals

- **Modifier le cycle de statuts / la machine à états (#25).** #26 **consomme** les routes de #25
  (`POST .../status`, `PUT .../hairdresser`) ; il ne redéfinit **aucune** transition, n'ajoute
  **aucune** action d'audit ni règle de domaine côté statut. La seule évolution backend de #26 est la
  **lecture** salon-scopée.
- **Assignation d'un coiffeur depuis le planning (UI).** *Recommandation : hors périmètre #26.* Un
  sélecteur « assigner un coiffeur » exigerait de **lister les coiffeurs du salon**, or **aucun
  endpoint de liste des employés/`salon_members` n'existe** (seul `POST /salons/{salon_id}/employees`,
  #13, est livré). L'endpoint `PUT .../hairdresser` (#25) reste consommable ultérieurement (US-3.6
  #27 ou un suivi) une fois la liste des coiffeurs disponible. **À confirmer** (voir Open Questions).
- **Planning personnel du coiffeur (US-3.6, #27).** La vue restreinte « un coiffeur ne voit que **ses**
  RDV assignés » (`APPOINTMENT_READ_ASSIGNED`) relève de #27, qui **dépend de #26**. #26 livre la vue
  **gérant** (tout le salon).
- **Réservation « walk-in » par le gérant** (créer un RDV depuis le planning) : hors périmètre (le
  gérant **pilote/visualise** ; la création reste le tunnel client #22).
- **Notifications (§8.4, Épic 7).** Aucune notification n'est émise à l'affichage ni au changement de
  statut (déjà hors périmètre en #25 ; câblage Épic 7).
- **Fiches / historique client enrichis (US-4.x, #28+).** Le planning affiche les RDV du salon ;
  l'enrichissement **nom/téléphone du client** (jointure `users`) relève de la gestion clients — voir
  Open Questions sur l'affichage minimal (identifiant/prestation/créneau) au MVP.
- **Calcul de chiffre d'affaires / encaissement (M4/M5).** Le planning n'agrège **aucun** montant ni
  CA. Les `price_at_booking` portés par la réponse restent indicatifs (déjà présents dans
  `AppointmentResponse`) ; aucun total n'est calculé.
- **Interface mobile (Flutter).** US-3.5 est un parcours **gérant** (web). Le paquet `app-mobile/`
  n'est **pas** touché.
- **Nouvelle table, migration, colonne ou contrainte** : le schéma #3 suffit (lecture seule côté
  écriture métier ; les écritures de statut restent celles de #25).
- **Temps réel / websockets.** La « mise à jour » est un **rafraîchissement** déclenché par l'action
  du gérant (relecture serveur), pas un flux poussé. Le rafraîchissement automatique périodique est
  hors périmètre (voir Open Questions).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

- **Backend** : FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0 + Alembic +
  psycopg 3 (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) — `domain/` et
  `application/` n'importent **jamais** FastAPI ni SQLAlchemy ; RBAC **deny-by-default** (ADR-0015).
  Tests `pytest` (`backend/pyproject.toml`, `testpaths=["tests"]`).
- **Web gérant** : Next.js 16 / React 19 / TypeScript (ADR-0002), **App Router**, Tailwind v4. Zone
  protégée `/gerant` (cookie `httpOnly` + BFF + garde serveur `GET /auth/me` via
  `requireManagerSession`). Tests **Vitest** (`web-dashboard/package.json`, `vitest run`).
- **Test gate** agrégé (#6) : `scripts/test-gate.sh` enchaîne `pytest` / `npm test` / `flutter test`.
- **Fuseau horaire** : `Africa/Abidjan` (UTC+0), datetimes **naïfs** côté backend (`_now()` renvoie
  l'UTC naïf) — le « jour courant » du planning doit être calculé dans ce repère (voir Proposed
  Implementation / Open Questions).

### Backend rendez-vous déjà livré (#21→#25 — à réutiliser/étendre)

- `coiflink_api/domain/enums.py` — `AppointmentStatus` (`PENDING|CONFIRMED|CANCELLED|COMPLETED|
  NO_SHOW`, hérite de `str`).
- `coiflink_api/domain/appointment.py` — entité `Appointment` (+ `BookedService`), machine à états
  gérant (`ALLOWED_STATUS_TRANSITIONS`, `TERMINAL_STATUSES`, `is_valid_transition`, #25), prédicats
  client (`is_client_modifiable`/`is_client_cancellable`), invariant CA (`counts_towards_revenue`).
- `coiflink_api/domain/permissions.py` — `MANAGER` détient **`APPOINTMENT_READ_SALON`** (à câbler),
  `APPOINTMENT_MANAGE`, `APPOINTMENT_UPDATE_STATUS` ; `HAIRDRESSER` détient
  `APPOINTMENT_READ_ASSIGNED` (pour #27). **`APPOINTMENT_READ_SALON` n'est câblée nulle part.**
- `coiflink_api/application/appointments.py` — cas d'usage `BookAppointment`, `CheckAvailability`,
  `ListMyAppointments`, `ModifyAppointment`, `CancelAppointment`, `SetAppointmentStatus`,
  `AssignHairdresser`. **#26 y ajoute `ListSalonAppointments`** (miroir salon-scopé de
  `ListMyAppointments`).
- `coiflink_api/application/ports/appointment_repository.py` — port `AppointmentRepository`.
  `list_for_client(client_id, statuses?)` trie par `(appointment_date, start_time)`. **#26 y ajoute
  `list_for_salon(salon_id, date_from, date_to, statuses?)`.**
- `coiflink_api/adapters/outbound/persistence/appointment_repository.py` — `SqlAppointmentRepository`
  (`_to_domain`, `_load_services`, patrons `select(...).where(...).order_by(...)`). **#26 y implémente
  `list_for_salon`.**
- `coiflink_api/adapters/inbound/appointments.py` — router : DI surchargeables
  (`get_appointment_repository`, `get_catalog_repository`, `get_audit_log`,
  `get_salon_scope_repository`), `_now()` UTC+0, `_appointment_response(...)` (réponse commune
  `AppointmentResponse` — porte `id`, `salon_id`, `client_id`, `hairdresser_id`, `date`, `start_time`,
  `end_time`, `status`, `client_note`, `services`). Les routes gérant #25 (`POST .../status`,
  `PUT .../hairdresser`) y sont montées. **#26 y ajoute la route de lecture.**
- `coiflink_api/adapters/inbound/security.py` — **`require_salon_scope`** (isolation §11.2 ; lit
  `salon_id` du chemin, charge la portée en base ; `403` générique hors périmètre),
  `require_permission`, `PUBLIC_ROUTE_PATHS` (n'y **rien** ajouter — la lecture gérant est
  **protégée**), invariant `unprotected_routes(app)`.
- `coiflink_api/adapters/inbound/services.py` — **patron de référence** d'une route salon-scopée de
  **lecture** (`GET /salons/{salon_id}/services`, `SERVICE_READ` + `require_salon_scope`) : le plus
  proche de la route à ajouter.

### Modèle de données pertinent (schéma #3, `models.py`)

- `Appointment` : `id`, `salon_id`, `client_id`, `hairdresser_id NULL`, `appointment_date`,
  `start_time`, `end_time`, `status` (`CHECK` dérivé de `AppointmentStatus`), `cancellation_reason
  NULL`, `client_note NULL`, `slot tsrange` (généré), `created_at`, `updated_at`. Index
  **`ix_appointments_salon_id (salon_id, appointment_date)`** — couvre la lecture salon-scopée par
  plage de dates de #26. `AppointmentService` (jonctions + `price_at_booking`).

### Web gérant déjà livré (#14→#20 — patrons à réutiliser)

- **Navigation** : `src/domain/navigation/sections.ts` — entrée `planning` (`coming-soon`) à passer
  `available`. Test `test/navigation-sections.test.ts`.
- **Page Server Component** : `app/(gerant)/gerant/prestations/page.tsx` — lit le jeton du cookie
  (`createCookieSessionStore().read()`), charge le salon (`createHttpSalonGateway({accessToken})
  .list()`), gère les états *pas de salon* / *erreur* / *ok*. **Patron direct** de
  `planning/page.tsx`.
- **Layout gérant** : `app/(gerant)/layout.tsx` — applique `requireManagerSession` (garde
  deny-by-default) et le `DashboardShell`.
- **Gateway HTTP sortant** : `src/adapters/api/http-service-gateway.ts` (+ port
  `src/application/ports/service-gateway.ts`) — `fetch` côté serveur, `Authorization: Bearer` depuis
  le cookie, mappage `200/401/403/404/422/503` → résultats de domaine, `cache: "no-store"`, **jamais**
  de log du jeton. **Patron de `http-appointment-gateway.ts`.**
- **Route Handler BFF (mutation)** : `app/api/salons/[id]/services/[serviceId]/route.ts` — lit le
  cookie côté serveur, proxifie via le gateway, renvoie un corps sans secret. **Patron des BFF
  d'action de statut.**
- **Composant client + mutation + refresh** : `src/adapters/ui/service-list.tsx` — `"use client"`,
  `useRouter().refresh()` après une mutation BFF, gestion d'erreurs neutres, drawer. **Patron du
  tableau/agenda de planning.**
- **Calcul de calendrier pur** : `src/domain/salon/month-calendar.ts` (`buildMonthGrid`, `shiftMonth`,
  `monthLabel`, `isoDate`, `WEEKDAY_LABELS_FR`) — **réutilisable tel quel** pour la vue mois. Test
  `test/month-calendar.test.ts`.

## Proposed Implementation

Périmètre : **(A)** une **route backend de lecture** salon-scopée (seul ajout serveur) ; **(B)** la
**page web gérant `/gerant/planning`** (vues jour/semaine/mois, groupement par statut, actions de
statut réutilisant #25). Aucune modification de schéma ni de la machine à états.

### (A) Backend — lecture salon-scopée des rendez-vous

#### 1. Port (`application/ports/appointment_repository.py`)

Ajouter (miroir salon-scopé de `list_for_client`) :

```
def list_for_salon(
    self,
    salon_id: uuid.UUID,
    date_from: datetime.date,
    date_to: datetime.date,
    statuses: tuple[str, ...] | None = None,
) -> tuple[Appointment, ...]:
    ...
```

Sémantique (docstring) : renvoie les RDV **du salon** (`salon_id`) dont `appointment_date` est dans
`[date_from, date_to]` (**inclusif**), avec leurs `BookedService`, triés `(appointment_date,
start_time)`. `statuses=None` ne filtre pas sur le statut (tous statuts) ; une liste restreint.
**Ne renvoie jamais** un RDV d'un autre salon (isolation §11.2 imposée en SQL).

#### 2. Adapter (`adapters/outbound/persistence/appointment_repository.py`)

Implémenter `list_for_salon` en réutilisant `_to_domain` / `_load_services` et le patron de
`list_for_client` :

```
stmt = select(models.Appointment).where(
    models.Appointment.salon_id == salon_id,
    models.Appointment.appointment_date >= date_from,
    models.Appointment.appointment_date <= date_to,
)
if statuses is not None:
    stmt = stmt.where(models.Appointment.status.in_(statuses))
stmt = stmt.order_by(
    models.Appointment.appointment_date.asc(),
    models.Appointment.start_time.asc(),
)
```

L'index `ix_appointments_salon_id (salon_id, appointment_date)` couvre le filtre.

#### 3. Application (`application/appointments.py`)

Cas d'usage **de lecture pure** (aucune écriture, aucun audit) :

```
class ListSalonAppointments:
    def __init__(self, appointment_repository: AppointmentRepository) -> None: ...
    def execute(
        self,
        salon_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        return self._repo.list_for_salon(salon_id, date_from, date_to, statuses)
```

Ajouter à `__all__`. (La **portée salon** est assurée par la garde HTTP `require_salon_scope`, comme
pour `services.py` ; le cas d'usage reste une lecture simple, à l'image de `ListMyAppointments`.)

#### 4. Adapter entrant (HTTP) — `adapters/inbound/appointments.py`

Ajouter **une** route de lecture salon-scopée **protégée** :

- `GET /salons/{salon_id}/appointments` — **gérant** (`require_permission(APPOINTMENT_READ_SALON)`
  **+** `require_salon_scope`). Paramètres de requête :
  - `date_from: datetime.date` (**requis**), `date_to: datetime.date` (**requis**) — plage inclusive
    couvrant la période visible (jour = `date_from == date_to` ; semaine = lundi→dimanche ; mois =
    plage de la grille). **Borner** l'amplitude (`date_to - date_from <= 42 jours` — la grille
    mensuelle fait au plus 6×7 cellules) → `422` au-delà (garde de coût, cf. §12).
  - `status: list[AppointmentStatus] | None = None` (**optionnel, répétable**) — filtre par statut
    (valeur hors énumération → `422` Pydantic). `None` = tous statuts.
  - DI : `get_appointment_repository`. Réponse `200` `list[AppointmentResponse]` (schéma existant,
    réutilisant `_appointment_response`). Erreurs : `401` (jeton) ; `403` (rôle insuffisant **ou**
    salon hors périmètre — identiques, aucun oracle) ; `422` (dates invalides / plage trop large /
    statut hors énumération). Docstring + `responses` OpenAPI (patron `services.py`).
- **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`** (route **protégée**). Vérifier que
  `unprotected_routes(app)` reste vide (test existant).

> **Note de portée & tri.** Le serveur renvoie une **liste plate triée chronologiquement**, tous
> statuts confondus (sauf filtre) ; le **groupement par statut** et la **découpe jour/semaine/mois**
> sont un **concern d'affichage** porté par le web (calculs purs testables). Cela garde la route
> générique et réutilisable (#27 pourra dériver une variante « assignés »).

### (B) Web gérant — page `/gerant/planning`

#### 1. Domaine (TypeScript pur, `src/domain/appointment/`)

- `appointment.ts` : type `Appointment` (camelCase : `id`, `salonId`, `clientId`, `hairdresserId`,
  `date`, `startTime`, `endTime`, `status`, `clientNote`, `services`), l'**union de statut**
  (`AppointmentStatus`), les **libellés FR** (`en attente|confirmé|annulé|terminé|absent`), une
  **classe de couleur** par statut (jetons Tailwind cohérents avec l'existant : p. ex. `palm` pour
  confirmé, `danger` pour annulé/absent, `accent`/muted pour en attente/terminé), et des **prédicats
  d'action UI** dérivés de la machine à états #25 (`canConfirm`, `canRefuse`, `canComplete`,
  `canMarkNoShow`, `isTerminal`) — **miroir** de `ALLOWED_STATUS_TRANSITIONS` (le backend reste
  l'arbitre ; ces prédicats ne font que **cacher** les boutons non pertinents).
- `planning-view.ts` : calculs **purs** de plages et de groupement, sans DOM/React :
  - `dayRange(iso)`, `weekRange(iso)` (lundi→dimanche), `monthRange(monthKey)` → `{ from, to }` ISO
    (alimente `date_from`/`date_to` de l'API) ;
  - `groupByStatus(appointments)` → RDV regroupés par statut (ordre stable) et **compteurs** par
    statut ;
  - `groupByDay(appointments)` / helpers d'agenda (regroupement par jour puis tri par `startTime`).
  - **Réutiliser** `domain/salon/month-calendar.ts` (`buildMonthGrid`, `shiftMonth`, `monthLabel`)
    pour la vue mois ; y **mapper** les compteurs par jour.
- **Fuseau** : le « jour courant » et les bornes sont calculés en **UTC+0** (Africa/Abidjan) pour
  s'aligner sur le backend (les dates de RDV sont des `date` naïves). Centraliser l'obtention de
  « aujourd'hui » (helper pur recevant une date injectable → testable, pas de `new Date()` caché).

#### 2. Port & adapter (lecture + actions)

- **Port** `src/application/ports/appointment-gateway.ts` (patron `service-gateway.ts`) :
  - `listForSalon(salonId, { from, to, statuses? }) -> ListAppointmentsResult`
    (`{ ok: true; appointments } | { ok: false; reason: "forbidden"|"unauthenticated"|"invalid"|
    "unavailable" }`) ;
  - `setStatus(salonId, appointmentId, status, reason?) -> MutateAppointmentResult`
    (`{ ok:true; appointment } | { ok:false; reason: "forbidden"|"unauthenticated"|"not-found"|
    "conflict"|"invalid"|"unavailable" }`) — `conflict` traduit le `409` (transition interdite #25).
- **Adapter** `src/adapters/api/http-appointment-gateway.ts` (patron `http-service-gateway.ts`) :
  `fetch` **côté serveur Next**, `Authorization: Bearer` depuis le cookie, `cache: "no-store"`,
  mappage des statuts HTTP (`200/401/403/404/409/422/503`) → résultats de domaine, projection
  snake_case → camelCase (`toAppointment`). **Jamais** de log du jeton (§11.3).

#### 3. Composition root (page + BFF)

- **Page** `app/(gerant)/gerant/planning/page.tsx` (**Server Component**, patron `prestations/page.
  tsx`) :
  1. Lit le jeton (`createCookieSessionStore().read()`), charge le salon (`http-salon-gateway.list()`)
     — états *pas de salon* (invite à créer le salon d'abord) / *erreur* / *ok*.
  2. Détermine la **période** depuis les *searchParams* (`view=day|week|month`, `date=YYYY-MM-DD`,
     `status=...` optionnels ; défaut `view=day`, `date=aujourd'hui` UTC+0), calcule `from`/`to`
     (domaine pur), appelle `http-appointment-gateway.listForSalon(salon.id, { from, to, statuses })`
     **côté serveur**.
  3. Rend `<PlanningBoard>` (composant client) avec les RDV, la vue, la date et le `salonId`.
  - La **navigation période/vue** met à jour les *searchParams* (liens/`router.push`) → nouveau rendu
    serveur (source de vérité relue). Le **changement de statut** appelle un BFF puis
    `router.refresh()`.
- **BFF Route Handler** `app/api/salons/[id]/appointments/[appointmentId]/status/route.ts` (`POST`,
  patron `services/[serviceId]/route.ts`) : lit le cookie côté serveur, proxifie
  `appointmentGateway.setStatus(...)`, renvoie un corps sans secret ; mappe `403/404/409/422/503`.
  *(Le corps ne porte que `status` (+ `reason?`) ; `salon_id`/`client_id` jamais.)*
  - *(Optionnel)* un BFF `GET app/api/salons/[id]/appointments/route.ts` **n'est requis que** si une
    relecture **client** (hors `router.refresh()`) est retenue — *recommandation : s'appuyer sur
    `router.refresh()` (relecture serveur) et **ne pas** ajouter ce GET BFF au MVP.*

#### 4. UI (`src/adapters/ui/planning-board.tsx` + sous-composants)

- `"use client"`. Barre d'outils : **sélecteur de vue** (Jour/Semaine/Mois), **navigation** période
  (précédent / aujourd'hui / suivant), **légende + filtre par statut** (chips), tous pilotant les
  *searchParams* (via `next/navigation`).
- **Vue Jour** (cœur de l'acceptation) : liste des RDV du jour **groupés par statut** (sections
  colorées + compteurs), chaque carte affichant **heure** (`start_time`–`end_time`), **statut**,
  **prestation(s)** et un identifiant client neutre (voir Open Questions), avec des **boutons
  d'action** contextuels (*Confirmer*/*Refuser*/*Terminer*/*Absent*) selon les prédicats de domaine.
  Une action → `fetch` BFF → succès `router.refresh()` ; erreur → message **neutre**
  (`409` = « Action impossible dans l'état actuel du rendez-vous. »).
- **Vue Semaine** : agenda 7 colonnes (lundi→dimanche) listant par jour les RDV (pastilles colorées
  par statut).
- **Vue Mois** : `buildMonthGrid` (réutilisé) avec, par cellule, des **compteurs/pastilles par
  statut** ; cliquer un jour bascule en **vue Jour** sur cette date.
- États : **vide** (« Aucun rendez-vous pour cette période »), **erreur** (panneau neutre),
  **chargement** (l'action en cours désactive le bouton). Accessibilité : `role="alert"` pour les
  erreurs, libellés `aria`, focus géré (patron existant).

#### 5. Navigation

- `src/domain/navigation/sections.ts` : passer l'entrée `planning` de `coming-soon` à `available`.
  Mettre à jour `test/navigation-sections.test.ts`.

### Documentation & ADR

- **ADR — Planning gérant & lecture salon-scopée des rendez-vous** (numéro libre suivant :
  `docs/adr/` s'arrête à **0025** ; le prochain est vraisemblablement **0026** — **vérifier** au step
  `document`). Acte : endpoint `GET /salons/{salon_id}/appointments` (`APPOINTMENT_READ_SALON` +
  `require_salon_scope`, liste plate triée, filtre statut, plage bornée) ; **groupement/vues** portés
  par le web (domaine pur) ; **réutilisation** des routes de statut #25 avec **refresh serveur** ;
  UI d'assignation coiffeur **différée** (pas de liste employés) ; planning coiffeur #27 en aval ;
  aucun nouveau schéma. Indexer dans `docs/adr/README.md`.
- **`backend/README.md`** : section « Lecture du planning salon (gérant) ».
- **`web-dashboard/README.md`** : section « Planning (vue calendrier) ».
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison
  (ne pas anticiper de comportement non implémenté — pas de temps réel, pas de notification, pas
  d'assignation UI si non livrée).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).

## Affected Files / Packages / Modules

**Backend — à modifier :**
- `backend/coiflink_api/application/ports/appointment_repository.py` — `list_for_salon` (Protocol).
- `backend/coiflink_api/adapters/outbound/persistence/appointment_repository.py` — implémentation
  `list_for_salon`.
- `backend/coiflink_api/application/appointments.py` — `ListSalonAppointments` (+ `__all__`).
- `backend/coiflink_api/adapters/inbound/appointments.py` — route `GET /salons/{salon_id}/
  appointments`, schéma de requête (query params `date_from`/`date_to`/`status`), DI, garde de plage,
  docstring/`responses`.
- `backend/tests/conftest.py` — étendre `FakeAppointmentRepository` (`list_for_salon` : mémorisation
  de la plage/statuts, jeu de RDV multi-statuts, refiltre `salon_id`).

**Backend — à lire (contexte) :** `adapters/inbound/services.py` (patron route salon-scopée de
**lecture**) ; `adapters/inbound/appointments.py` (`_appointment_response`, DI, `_now`) ;
`adapters/inbound/security.py` (`require_salon_scope`, `PUBLIC_ROUTE_PATHS`, `unprotected_routes`) ;
`application/appointments.py::ListMyAppointments` (patron lecture) ; `adapters/outbound/persistence/
appointment_repository.py::list_for_client` (patron `select/where/order_by`) ; `domain/permissions.py`
(`APPOINTMENT_READ_SALON`) ; `models.py` (`Appointment`, index `ix_appointments_salon_id`).

**Web — à créer :**
- `web-dashboard/app/(gerant)/gerant/planning/page.tsx` — Server Component (composition root).
- `web-dashboard/app/api/salons/[id]/appointments/[appointmentId]/status/route.ts` — BFF `POST`
  (action de statut). *(GET BFF optionnel — voir Proposed Implementation.)*
- `web-dashboard/src/application/ports/appointment-gateway.ts` — port.
- `web-dashboard/src/adapters/api/http-appointment-gateway.ts` — adapter HTTP.
- `web-dashboard/src/domain/appointment/appointment.ts` — type, statut, libellés/couleurs, prédicats
  d'action.
- `web-dashboard/src/domain/appointment/planning-view.ts` — plages (jour/semaine/mois), groupement
  par statut/jour, compteurs.
- `web-dashboard/src/adapters/ui/planning-board.tsx` (+ éventuels sous-composants : légende, carte de
  RDV, agenda semaine, grille mois).

**Web — à modifier :**
- `web-dashboard/src/domain/navigation/sections.ts` — `planning` → `available`.

**Web — à lire (contexte) :** `app/(gerant)/gerant/prestations/page.tsx`, `app/(gerant)/layout.tsx`,
`src/application/use-cases/require-manager-session.ts`, `src/adapters/api/http-service-gateway.ts`,
`src/adapters/api/cookie-session-store.ts`, `src/adapters/api/config.ts`,
`src/adapters/ui/service-list.tsx`, `src/domain/salon/month-calendar.ts`.

**Docs :** `docs/adr/00XX-*.md` (numéro à confirmer) + `docs/adr/README.md`, `backend/README.md`,
`web-dashboard/README.md`. **`prd-coiflink.md` : ne pas modifier.** Récit `README.md` §6 : compléter
au step `document`.

**Non touchés :** `app-mobile/` (feature gérant), la **machine à états #25** et les routes d'écriture
de statut (réutilisées telles quelles).

## API / Interface Changes

**Nouvelle route backend** (protégée, jamais publique, **salon-scopée**) :

- `GET /salons/{salon_id}/appointments` — **gérant** (`APPOINTMENT_READ_SALON` + portée salon).
  Query : `date_from=YYYY-MM-DD` (**requis**), `date_to=YYYY-MM-DD` (**requis**, plage inclusive,
  amplitude bornée ≤ 42 j), `status=CONFIRMED&status=PENDING&…` (**optionnel, répétable** ; valeur
  hors énumération → `422`). Réponse `200` : `list[AppointmentResponse]` (schéma existant, triée par
  `date` puis `start_time`). Réponses : `200` ; `401` (jeton absent/expiré) ; `403` (rôle insuffisant
  **ou** salon hors périmètre — identiques, aucun oracle) ; `422` (dates absentes/invalides, plage
  trop large, statut hors énumération). Documentation OpenAPI (docstring + `responses`).

**Réutilisé tel quel :** `AppointmentResponse` ; les routes d'écriture de statut #25 (`POST
/salons/{salon_id}/appointments/{id}/status`, `PUT .../hairdresser`). **Aucune** modification des
routes existantes (client ou gérant).

**Surface web (BFF, interne au dashboard) :**
- `POST /api/salons/{id}/appointments/{appointmentId}/status` — Route Handler BFF proxifiant l'action
  de statut #25 (corps `{ status, reason? }` ; `salon_id`/`client_id` **jamais**). *(GET BFF de liste
  optionnel — non retenu au MVP si `router.refresh()` suffit.)*

## Data Model / Protocol Changes

**Aucune.** La lecture salon-scopée s'appuie sur les colonnes `salon_id`, `appointment_date`,
`start_time`, `status` (schéma #3) et l'index `ix_appointments_salon_id (salon_id, appointment_date)`.
Aucune table, migration, colonne ni contrainte. Le contrat de fil (`AppointmentResponse`) est
**inchangé** ; seuls **de nouveaux paramètres de requête** (`date_from`/`date_to`/`status`) sont
introduits. Les écritures de statut restent celles de #25 (aucune nouvelle mutation).

## Security & Privacy Considerations

- **Isolation par salon (§11.2)** : la route de lecture est **salon-scopée** (`require_salon_scope`,
  `403` générique hors périmètre) **et** le dépôt refiltre `salon_id` en SQL (`list_for_salon`) —
  défense en profondeur. Un gérant ne lit **que** les RDV de **son** salon ; le `salon_id` vient
  **du chemin**. Un salon hors périmètre est un `403` **indiscernable** (aucun oracle d'existence).
- **Deny-by-default (ADR-0015)** : la route exige `APPOINTMENT_READ_SALON` (un `CLIENT`/`HAIRDRESSER`
  ne l'a pas → `403`). **Aucun** ajout à `PUBLIC_ROUTE_PATHS` ; `unprotected_routes(app)` **reste
  vide** (invariant testé). La lecture ne s'appuie sur **aucun** champ soumis pour autoriser.
- **Respect de la machine à états (#25)** : l'UI **n'autorise pas** de transition ; elle **cache** les
  boutons non pertinents (prédicats miroir) mais **le backend reste l'arbitre** — une transition
  interdite (double-clic, course avec l'annulation client #24) renvoie un `409` traduit en message
  **neutre**. Aucun `status` n'est « forcé » côté client.
- **Jeton jamais exposé (#14, §11.3)** : toute lecture/écriture backend passe **côté serveur Next**
  (Server Component + Route Handlers BFF) avec le jeton lu du cookie `httpOnly` — **jamais** transmis
  au navigateur, **jamais** journalisé. Les gateways ne loggent ni `Authorization` ni PII.
- **Confidentialité de l'affichage (§11.3)** : la réponse `AppointmentResponse` porte des UUID
  (`client_id`, `hairdresser_id`) et des données du **propre** salon du gérant — jamais l'identité
  d'un tiers hors salon. L'enrichissement **nom/téléphone client** (jointure `users`) est **hors
  périmètre** (Open Questions) : au MVP, afficher un **libellé neutre** (créneau + prestation +
  identifiant court) évite d'introduire de la PII non maîtrisée dans l'UI/les logs.
- **Budget de coût (§12)** : la plage est **bornée** (≤ 42 jours) et l'index
  `ix_appointments_salon_id (salon_id, appointment_date)` couvre le filtre — lecture bien en deçà du
  budget API (< 3 s). Pas de N+1 non maîtrisé (chargement des prestations par RDV : borné par la
  plage ; à surveiller — voir Open Questions sur un chargement groupé).
- **Résidence/hébergement** : inchangés (ADR-0011). Aucun secret manipulé ni journalisé.
- **Erreurs neutres** : les motifs d'échec (front) restent génériques (`forbidden`/`unavailable`/
  `conflict`/`invalid`) ; les refus RBAC restent les `401`/`403` **constants** de `security.py`.

## Testing Plan

Test gate : `pytest` (backend) + `vitest run` (web). Convention backend : tests **Postgres** *skip
proprement* sans `DATABASE_URL` ; en unitaire, **fakes** injectés via `app.dependency_overrides`.
Les tests existants restent **verts** (extensions **additives**).

**Backend :**
- **Unit — cas d'usage (fakes)** `tests/test_appointment_usecases.py` (étendre) : `ListSalonAppointments`
  renvoie les RDV du salon dans la plage, triés `(date, start_time)` ; applique le filtre `statuses`
  (sous-ensemble) ; renvoie **vide** hors plage ; ne renvoie **jamais** un RDV d'un autre salon
  (le fake refiltre `salon_id`).
- **Intégration/HTTP** `tests/test_appointment_api.py` (étendre, `TestClient` + fakes) :
  `GET /salons/{id}/appointments` : `200` liste triée pour une plage ; filtre `status` (répété)
  reflété ; `422` si `date_from`/`date_to` absents/mal formés, plage > 42 j, ou `status` hors
  énumération ; `403` **rôle non habilité** (`CLIENT`) **et** **gérant d'un autre salon** (messages
  identiques) ; `401` sans jeton. **Invariant deny-by-default** : `unprotected_routes(app)` reste
  **vide** (sans ajouter le chemin à `PUBLIC_ROUTE_PATHS`).
- **Intégration Postgres** `tests/test_planning_read_e2e.py` (nouveau, skip sans `DATABASE_URL`) :
  insérer des RDV multi-statuts/dates pour deux salons ; vérifier que la lecture **ne renvoie que**
  ceux du salon scopé, dans la plage et l'ordre attendus, filtre statut inclus. *(Facultatif :
  vérifier que la vue **reflète** un changement de statut #25 — relecture après `set_status`.)*
- **Matrice RBAC** `tests/test_permissions.py` : `MANAGER` détient `APPOINTMENT_READ_SALON`, `CLIENT`
  non (déjà couvert par la matrice ; ré-affirmer si touché — **aucune** nouvelle permission requise).

**Web (Vitest) :**
- **Domaine pur** `test/planning-view.test.ts` (nouveau) : `dayRange`/`weekRange` (lundi→dimanche)/
  `monthRange` (bornes ISO correctes, y compris passage de mois/année) ; `groupByStatus` (regroupement
  + compteurs, ordre stable, statut vide géré) ; `groupByDay` ; calcul « aujourd'hui » UTC+0 (date
  injectée).
- **Domaine statut** `test/appointment-domain.test.ts` (nouveau) : libellés FR par statut ; prédicats
  d'action (`canConfirm`/`canRefuse`/`canComplete`/`canMarkNoShow`/`isTerminal`) **cohérents** avec la
  machine à états #25 (terminaux → aucune action).
- **Gateway HTTP** `test/http-appointment-gateway.test.ts` (nouveau, `fetch` mocké) : `listForSalon`
  mappe `200`→liste, `401/403/422/503`→motifs ; construit l'URL avec `date_from`/`date_to`/`status`
  (encodage) ; **ne loggue jamais** le jeton. `setStatus` mappe `200/403/404/409/422/503` (dont
  `409`→`conflict`) ; corps `{status, reason?}` **sans** `salon_id`/`client_id`.
- **BFF** `test/bff-routes.test.ts` (étendre) ou nouveau : `POST /api/salons/[id]/appointments/
  [appointmentId]/status` — `401` sans cookie ; proxifie et mappe `403/404/409/422/503` ; corps sans
  secret ; **jamais** de log du jeton.
- **Navigation** `test/navigation-sections.test.ts` (étendre) : `planning` est désormais `available`
  (et sa page existe — cohérence de l'invariant du test).

**Documentation** : revue que `backend/README.md` et `web-dashboard/README.md` décrivent la lecture
salon-scopée, les vues, le groupement par statut, le refresh après action, et la frontière avec #25
(écriture) / #27 (coiffeur).

## Documentation Updates

- **`docs/adr/00XX-*.md`** (nouveau — **confirmer le numéro** au step `document` ; `docs/adr/`
  s'arrête à `0025`) + entrée **`docs/adr/README.md`** : lecture salon-scopée (`APPOINTMENT_READ_SALON`
  câblée pour la première fois), route bornée par plage + filtre statut, **vues & groupement portés
  par le web** (domaine pur), réutilisation des routes de statut #25 + refresh serveur, assignation UI
  différée (pas de liste employés), frontière avec #27, backend sans nouveau schéma.
- **`backend/README.md`** : section « Lecture du planning salon (gérant) » (route, paramètres, portée,
  filtre, ordre, prérequis Postgres des e2e).
- **`web-dashboard/README.md`** : section « Planning (vue calendrier) » (vues jour/semaine/mois,
  groupement par statut, actions de statut via BFF + refresh, jeton non exposé).
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison —
  **ne pas anticiper** de comportement non implémenté (pas de temps réel, pas de notification, pas
  d'assignation UI si non livrée).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstring + `responses` sur la nouvelle route (généré par FastAPI).

## Risks and Open Questions

- **Assignation d'un coiffeur depuis le planning.** Bloquée par l'**absence d'endpoint de liste des
  employés/`salon_members`** (seul `POST .../employees` existe). *Recommandation : hors périmètre #26*
  — livrer d'abord la visualisation + le cycle de statuts ; l'assignation UI (consommant `PUT
  .../hairdresser` #25) attendra une liste des coiffeurs (suivi ou #27). **À confirmer.**
- **Enrichissement de l'identité client.** `AppointmentResponse` ne porte que `client_id` (UUID). Un
  planning lisible voudrait **nom/téléphone**. *Recommandation MVP : afficher un **libellé neutre**
  (créneau + prestation + identifiant court), et différer l'enrichissement à la gestion clients
  (#28+)* pour éviter d'introduire de la PII non maîtrisée. Alternative : étendre la réponse gérant
  avec un `client_display_name` (jointure `users`) — plus utile mais élargit le périmètre et la
  surface PII. **À confirmer.**
- **Contrat de la plage de dates.** `date_from`/`date_to` (recommandé — générique, couvre les trois
  vues) vs `date` + `view=day|week|month` (le serveur déduit la plage). *Recommandation :
  `date_from`/`date_to` bornés (≤ 42 j), la déduction de plage restant côté web (domaine pur,
  testable).* **À confirmer** (borne exacte, inclusivité).
- **Groupement/vues côté serveur vs côté client.** *Recommandation : liste plate triée renvoyée par
  l'API ; groupement par statut & découpe jour/semaine/mois **portés par le web**.* Alternative :
  renvoyer des compteurs par statut/jour (agrégat serveur) — utile aux gros volumes, mais prématuré
  au MVP. **À confirmer.**
- **Portée d'affichage des statuts.** La vue jour affiche-t-elle **tous** les statuts (dont
  `CANCELLED`/`NO_SHOW`) ou seulement les actifs par défaut, avec bascule ? §5.2 mentionne « confirmés,
  en attente, annulés, terminés ». *Recommandation : afficher tous les statuts avec un **filtre**
  (chips), les annulés/absents visibles mais **discrets**.* **À confirmer.**
- **Mécanisme de « mise à jour ».** *Recommandation : rafraîchissement **déclenché** par l'action
  (relecture serveur via `router.refresh()`), pas de temps réel.* Un rafraîchissement **périodique**
  (polling léger) ou un flux poussé sont **hors périmètre** MVP. **À confirmer** que l'acceptation
  (« se met à jour après changement de statut ») est satisfaite par le refresh post-action.
- **Fuseau horaire du « jour courant ».** Le backend raisonne en **UTC+0 (Africa/Abidjan)** sur des
  `date` naïves. *Recommandation : calculer « aujourd'hui » et les bornes en UTC+0 (helper pur, date
  injectable)* pour éviter un décalage selon le fuseau du navigateur du gérant. **À confirmer** (pas
  de gestion multi-fuseau au MVP).
- **Chargement des prestations par RDV (N+1).** `list_for_client` charge les `BookedService` par RDV
  (`_load_services` en boucle). Sur une plage large, envisager un **chargement groupé** (un `select …
  in_(appointment_ids)`), ou l'accepter au MVP (plage bornée). *Recommandation : mesurer ; refactor
  additif si nécessaire.* **À noter.**
- **Pagination.** La plage bornée (≤ 42 j) suffit vraisemblablement au MVP ; une **pagination** (gros
  salons) est différée. **À noter.**
- **Numéro d'ADR.** `docs/adr/` s'arrête à `0025` — le prochain libre est **0026** (le cycle de
  statuts #25 n'a **pas** ajouté d'ADR distinct) ; **vérifier** au step `document`.
- **Dépendance #27 (planning coiffeur).** #27 dépend de #26 et réutilisera l'essentiel (vues,
  groupement) avec une lecture restreinte « assignés » (`APPOINTMENT_READ_ASSIGNED`). Concevoir le
  domaine web (vues/groupement) **réutilisable** (paramétré par la source de RDV), sans le
  sur-spécifier pour #26. **À noter.**

## Implementation Checklist

1. **Lire** : `adapters/inbound/services.py` (route salon-scopée de lecture) ; `adapters/inbound/
   appointments.py` (`_appointment_response`, DI, `_now`, routes #25) ; `adapters/inbound/security.py`
   (`require_salon_scope`, `PUBLIC_ROUTE_PATHS`, `unprotected_routes`) ; `application/appointments.py`
   (`ListMyAppointments`) ; `adapters/outbound/persistence/appointment_repository.py`
   (`list_for_client`) ; `domain/permissions.py`, `models.py`. Côté web : `prestations/page.tsx`,
   `layout.tsx`, `require-manager-session.ts`, `http-service-gateway.ts`, `service-list.tsx`,
   `app/api/salons/[id]/services/[serviceId]/route.ts`, `domain/salon/month-calendar.ts`,
   `domain/navigation/sections.ts`.
2. **Trancher les Open Questions structurantes** (assignation UI hors/dans périmètre, identité client,
   contrat de plage, groupement serveur/client, mécanisme de refresh, fuseau) et les acter dans l'ADR
   (+ `docs/adr/README.md`).
3. **Backend — port** (`application/ports/appointment_repository.py`) : `list_for_salon(salon_id,
   date_from, date_to, statuses?)`.
4. **Backend — adapter** (`SqlAppointmentRepository.list_for_salon`) : `select/where(salon_id, plage,
   statuts?)/order_by(date, start_time)` réutilisant `_to_domain`/`_load_services`.
5. **Backend — cas d'usage** (`application/appointments.py`) : `ListSalonAppointments` (lecture pure)
   + `__all__`.
6. **Backend — route** (`adapters/inbound/appointments.py`) : `GET /salons/{salon_id}/appointments`
   (`APPOINTMENT_READ_SALON` + `require_salon_scope`), query `date_from`/`date_to` (requis, plage
   bornée ≤ 42 j → `422`) + `status` (répété, optionnel), DI, docstring/`responses`. **Ne rien ajouter
   à `PUBLIC_ROUTE_PATHS`.**
7. **Backend — fakes** : étendre `FakeAppointmentRepository.list_for_salon` (refiltre `salon_id`,
   plage, statuts ; jeu multi-statuts) dans `conftest.py`.
8. **Backend — tests** : cas d'usage (fakes), API (`TestClient` : portée, filtre, `403` hors salon,
   `422`, deny-by-default), Postgres e2e (lecture salon-scopée triée, isolation deux salons) — **skip**
   sans `DATABASE_URL`.
9. **Web — domaine** : `src/domain/appointment/appointment.ts` (type, statut, libellés/couleurs,
   prédicats d'action miroir #25) ; `src/domain/appointment/planning-view.ts` (plages jour/semaine/
   mois, `groupByStatus`/compteurs, `groupByDay`, « aujourd'hui » UTC+0). Réutiliser `month-calendar.
   ts`.
10. **Web — port & adapter** : `src/application/ports/appointment-gateway.ts` ; `src/adapters/api/
    http-appointment-gateway.ts` (`listForSalon`, `setStatus`, mappage HTTP, **jeton non loggé**).
11. **Web — composition root** : `app/(gerant)/gerant/planning/page.tsx` (Server Component : session →
    salon → période depuis searchParams → `listForSalon`) ; BFF `app/api/salons/[id]/appointments/
    [appointmentId]/status/route.ts` (`POST`).
12. **Web — UI** : `src/adapters/ui/planning-board.tsx` (+ sous-composants) : sélecteur de vue,
    navigation période, légende/filtre statut, vue jour (groupée + actions contextuelles → BFF →
    `router.refresh()`), vue semaine, vue mois (grille + compteurs), états vide/erreur/chargement,
    erreurs **neutres**.
13. **Web — navigation** : `sections.ts` `planning` → `available` ; ajuster
    `test/navigation-sections.test.ts`.
14. **Web — tests** : `planning-view.test.ts`, `appointment-domain.test.ts`,
    `http-appointment-gateway.test.ts`, BFF (status), navigation.
15. **Documentation** : ADR (numéro à confirmer) + `docs/adr/README.md` + sections `backend/README.md`
    et `web-dashboard/README.md`.
16. **Garde-fous** : `pytest` **et** `vitest run` (test gate agrégé) au vert ; aucun secret/PII
    journalisé ; jeton **jamais** exposé au navigateur (Server Component + BFF) ; corps d'action sans
    `salon_id`/`client_id` ; lecture **salon-scopée** (garde + refiltre SQL) ; plage **bornée** ;
    `unprotected_routes(app)` **vide** ; **aucune** transition inventée côté client (backend arbitre,
    `409` neutre) ; **aucune** notification ni CA fabriqués ; **aucune** signature IA dans le code/
    commits/PR.
