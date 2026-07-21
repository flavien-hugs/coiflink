# Moteur de disponibilité & anti double-réservation (US-3.7)

> Spécification de planification pour l'issue GitHub **#21 — US-3.7 : Moteur de disponibilité &
> anti double-réservation** (`feature` · Must · Effort M · PRD §6 Épic 3, §8.1). **Dépend de #16**
> (horaires d'ouverture) **et de #17** (prestations). **Cette spec ne produit pas de code** : elle
> décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, docstrings, commentaires),
> en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants techniques (noms de
> tables/colonnes, SQL, enums, symboles Python) inchangés. **Aucune signature IA** dans le code, les
> commits ou la PR.

## Problem Statement

Le PRD §8.1 pose une règle d'intégrité **critique** : « un créneau ne peut pas être réservé deux fois
pour le même coiffeur ». US-3.7 (§6 Épic 3) la formule côté produit — « en tant que gérant, je veux
éviter les doubles réservations » — avec pour spécification « vérification automatique des créneaux
disponibles ». Les critères d'acceptation de l'issue #21 sont explicitement **de concurrence** :

- deux réservations concurrentes sur le **même créneau / même coiffeur** ⇒ **une seule acceptée** ;
- des **tests de concurrence** le démontrent.

État actuel du dépôt :

- **Le socle base de données existe déjà** (issue #3, migration `0001_schema_initial`) : les tables
  `appointments` et `appointment_services` sont au schéma, la colonne générée `slot tsrange`
  (`tsrange(appointment_date + start_time, appointment_date + end_time)`) est calculée, l'extension
  `btree_gist` est créée, et la **contrainte d'exclusion** anti double-réservation est posée :
  `EXCLUDE USING gist (hairdresser_id WITH =, slot WITH &&) WHERE (hairdresser_id IS NOT NULL AND
  status IN ('PENDING','CONFIRMED'))` (`ex_appointments_hairdresser_slot`, cf.
  `adapters/outbound/persistence/models.py` et `migrations/versions/0001_schema_initial.py`).
- **Aucune couche applicative de rendez-vous n'existe** : il n'y a ni `domain/appointment.py`, ni
  `domain/availability.py`, ni port `AppointmentRepository`, ni adapter SQL de rendez-vous, ni route
  HTTP de réservation ou de disponibilité (vérifié : `appointment` n'apparaît que dans `models.py`).
- Les briques amont sont livrées : les **horaires d'ouverture** (`domain/opening_hours.py`, contrat
  JSONB `salons.opening_hours`, #16), les **prestations** (`domain/service.py`,
  `application/services.py`, #17), la règle §8.3 `is_bookable(status, opening_hours)`
  (`domain/salon.py`, #15), et la matrice RBAC des rendez-vous (`domain/permissions.py` :
  `APPOINTMENT_BOOK`, `APPOINTMENT_MANAGE`, `APPOINTMENT_READ_*`, `APPOINTMENT_UPDATE_STATUS`).

Le gap que #21 comble : **la logique applicative qui exploite ce socle** — (1) un **moteur de
disponibilité** pur qui calcule les créneaux libres d'un salon/coiffeur à partir des horaires, de la
durée de prestation et des rendez-vous déjà pris ; (2) un **chemin d'écriture de réservation
transactionnel** qui s'appuie sur la contrainte d'exclusion PostgreSQL pour garantir qu'entre deux
insertions concurrentes du même créneau/coiffeur, **une seule aboutit**, la seconde étant rejetée
proprement (traduite en `409 Conflict`).

## Goals

- **Moteur de disponibilité pur** (domaine, sans I/O) : à partir des `OpeningHours` (#16), de la durée
  d'une (ou plusieurs) prestation(s) (#17) et des créneaux déjà réservés, calculer la liste
  **déterministe** des créneaux libres pour une date et un coiffeur donnés (jours fermés, pauses,
  jours exceptionnels, créneaux passés et créneaux en conflit exclus).
- **Garantie anti double-réservation à la concurrence** : deux réservations simultanées sur le même
  créneau et le même coiffeur ⇒ **exactement une acceptée**, l'autre rejetée. La garantie repose sur
  la **contrainte d'exclusion base** (`ex_appointments_hairdresser_slot`) déjà posée par #3 —
  l'arbitrage est atomique et immunisé contre le TOCTOU (la vérification applicative n'est
  qu'une aide UX, pas le juge de dernier ressort).
- **Chemin d'écriture de réservation** : un cas d'usage `BookAppointment` qui, dans **une seule
  transaction**, crée le `Appointment` **et** ≥ 1 ligne `appointment_services` (invariant §8.1
  « ≥ 1 prestation »), attrape la violation d'exclusion et la traduit en erreur de domaine dédiée.
- **Vérification automatique des créneaux** exposée : un point de lecture de disponibilité et le
  contrôle de disponibilité au moment de la réservation (défense en profondeur avant l'arbitrage base).
- **Respect des invariants §8.3 et §11.2** : un salon non réservable (inactif ou sans horaire) refuse
  toute réservation ; l'isolation par salon et l'anti-élévation (`client_id`/`salon_id` imposés par le
  serveur) sont préservés.
- **Tests de concurrence** reproductibles démontrant l'unicité (critère d'acceptation dur).

## Non-Goals

- **Parcours client complet de réservation US-3.1** (choix guidé salon → prestation → date → heure →
  commentaire, confirmations/rappels §8.4/§7.1). #21 fournit le **moteur** et le chemin d'écriture
  minimal qui porte la règle anti-doublon ; l'ergonomie et le tunnel client de US-3.1 se **superposent**
  en réutilisant le cas d'usage (voir *Risks and Open Questions* pour la frontière exacte à confirmer).
- **Modification / annulation / confirmation-refus de rendez-vous** (US-3.2, US-3.3, US-3.4) et les
  transitions de statut associées.
- **Plannings** (vue jour/semaine/mois gérant US-3.5, planning coiffeur US-3.6).
- **Notifications** de confirmation/annulation (§8.4, Épic 7) — hors périmètre ; aucun envoi n'est
  ajouté par #21.
- **Nouvelle table / nouvelle migration de schéma** : le socle `appointments` /
  `appointment_services` / `slot` / `EXCLUDE` / `btree_gist` **existe déjà** (#3). #21 n'introduit
  **aucune** modification de schéma sauf, en option, un index d'accélération (voir *Data Model*).
- **Capacité de salon sans coiffeur assigné** : la règle §8.1 est explicitement « pour le même
  coiffeur ». La gestion d'une capacité globale d'un salon qui n'assigne pas de coiffeur relève d'une
  décision produit distincte (voir *Open Questions*).
- **Modélisation des congés/absences du coiffeur** au-delà des jours exceptionnels du salon (#16).

## Relevant Repository Context

- **Stack figée (ADR)** : backend FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0
  + Alembic + psycopg 3 (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) — le
  domaine et l'application n'importent **jamais** FastAPI ni SQLAlchemy ; RBAC **deny-by-default**
  (ADR-0015). Tests : `pytest` (ADR-0003, `backend/pyproject.toml`).
- **Socle base déjà en place (issue #3)** — `adapters/outbound/persistence/models.py` :
  - `Appointment` : `salon_id`, `client_id`, `hairdresser_id NULL`, `appointment_date`, `start_time`,
    `end_time`, `status` (défaut `PENDING`), `slot tsrange` **générée**
    (`Computed(..., persisted=True)`), `CHECK end_time > start_time`, `UniqueConstraint(salon_id, id)`,
    FK composites `(salon_id, hairdresser_id)`, et **`ExcludeConstraint`** anti double-réservation
    ci-dessus. Index `ix_appointments_salon_id (salon_id, appointment_date)` et
    `ix_appointments_client_id`.
  - `AppointmentService` : PK `(appointment_id, service_id)`, `salon_id`, `price_at_booking`, FK
    composites `(salon_id, appointment_id)` **CASCADE** et `(salon_id, service_id)` **RESTRICT** —
    forcent au niveau base que RDV et prestation appartiennent au **même salon**.
  - Fuseau : le §9 / `opening_hours` utilisent **Africa/Abidjan = UTC+0**, d'où le choix `tsrange`
    (non-`tstzrange`) du schéma. Le moteur de disponibilité doit rester cohérent avec ce fuseau.
- **Enums** (`domain/enums.py`) : `AppointmentStatus` = `PENDING | CONFIRMED | CANCELLED | COMPLETED |
  NO_SHOW`. Les RDV « actifs » au sens de l'exclusion sont `PENDING` et `CONFIRMED`.
- **Horaires (#16)** — `domain/opening_hours.py` : structure canonique `OpeningHours(version, timezone,
  weekly: tuple[DaySchedule], exceptions: tuple[ExceptionalDay])`, jours `mon..sun`, intervalles
  `HH:MM` triés non chevauchants, exceptions datées (`closed` ou horaires exceptionnels). Le JSONB en
  base est cette forme normalisée (`to_jsonb`). Le moteur de disponibilité **consomme** cette structure
  (idéalement en la re-parsant via `parse_opening_hours` pour bénéficier des invariants).
- **Prestations (#17)** — `domain/service.py` : `Service(id, salon_id, name, price, duration_minutes,
  category, is_active, ...)`. La **durée** (`duration_minutes`) est la longueur du créneau à réserver.
- **Règle §8.3 (#15)** — `domain/salon.py::is_bookable(status, opening_hours)` : `ACTIVE` **et**
  horaires présents. Réutilisée telle quelle pour refuser toute réservation sur un salon non réservable.
- **RBAC (#12)** — `domain/permissions.py` : `CLIENT` détient `APPOINTMENT_BOOK` +
  `APPOINTMENT_READ_OWN` + `SALON_READ_ANY` + `SERVICE_READ` ; `MANAGER` détient `APPOINTMENT_MANAGE` +
  `APPOINTMENT_READ_SALON`. Gardes disponibles : `require_permission`, `require_any_permission`,
  `require_salon_scope` (`adapters/inbound/security.py`). **Attention** : un `CLIENT` **n'a aucune
  portée salon** (`require_salon_scope` lui renvoie `403`) — une route de réservation/disponibilité
  destinée au client **ne doit pas** utiliser `require_salon_scope` (cf. le catalogue public #18/#19,
  ajouté à `PUBLIC_ROUTE_PATHS`).
- **Patrons applicatifs de référence** (à calquer) : `application/services.py` +
  `adapters/inbound/services.py` + `adapters/outbound/persistence/service_repository.py` (CRUD par
  port, DI FastAPI surchargeable en test) ; unité de travail transactionnelle pilotée par
  `get_session` (`adapters/outbound/persistence/session.py` : commit si succès, rollback si exception ;
  les dépôts `flush` sans committer). Les erreurs de domaine sont **neutres** (`domain/errors.py`) et
  traduites en HTTP par l'adapter entrant.
- **Composition root** : `coiflink_api/main.py` monte les routers ; un nouveau router doit y être
  inclus (et son chemin ajouté à `PUBLIC_ROUTE_PATHS` **uniquement** si public — décision de sécurité).
- **Décisions non finalisées côté produit** susceptibles d'affecter le moteur : granularité des
  créneaux, comportement sans coiffeur assigné, surface exacte des routes (voir *Open Questions*).

## Proposed Implementation

Tout est **au-dessus du schéma existant** ; la garantie de concurrence est **déjà** portée par la base.
Le rôle de #21 est d'ajouter la couche domaine/application/adapters qui l'exploite proprement.

### 1. Domaine pur

**`domain/availability.py` (nouveau) — le moteur.** Fonctions **pures**, aucune dépendance
framework/I/O (ADR-0008), fuseau Africa/Abidjan (UTC+0, cohérent avec `tsrange` du schéma) :

- Value objects : `SlotRange(date: datetime.date, start: datetime.time, end: datetime.time)` (créneau
  fermé-ouvert `[start, end)`), et `TimeSpan`/helpers de minutes.
- `overlaps(a: SlotRange, b: SlotRange) -> bool` : chevauchement strict `a.start < b.end and
  b.start < a.end` (l'adjacence `end == start` **n'est pas** un conflit — cohérent avec la sémantique
  `&&` de `tsrange` et avec l'adjacence tolérée des intervalles d'horaires #16).
- `intervals_for_date(hours: OpeningHours, date) -> tuple[TimeInterval, ...]` : résout les intervalles
  d'ouverture **effectifs** d'une date — une **exception datée** (fermée ⇒ `()` ; ouverte ⇒ ses
  intervalles) **prime** sur le programme hebdomadaire du jour de la semaine ; sinon le `DaySchedule`
  du jour (`DAY_KEYS[date.weekday()]`), ou `()` si le jour est fermé/absent.
- `free_slots(hours, date, duration_minutes, booked, *, granularity_minutes, now=None,
  min_lead_minutes=0) -> tuple[SlotRange, ...]` : pour chaque intervalle d'ouverture effectif, génère
  les créneaux candidats de longueur `duration_minutes` par pas de `granularity_minutes`, ne conserve
  que ceux **entièrement contenus** dans l'intervalle (une prestation qui ne « rentre » pas est
  écartée), exclut ceux qui **chevauchent** un `booked` (`overlaps`), et exclut les créneaux
  **passés** (candidat dont le début est < `now + min_lead_minutes`, quand `now` est fourni). Résultat
  trié, sans doublon.
- `is_offered(hours, slot, duration_minutes, booked, *, granularity_minutes, now=None) -> bool` :
  prédicat utilisé par `BookAppointment` pour rejeter en amont un créneau qui n'est pas dans l'offre
  (hors horaires, mal aligné, passé, ou déjà occupé) — **avant** l'arbitrage base.

**`domain/appointment.py` (nouveau) — entités & règles.** `dataclass` gelées, pas d'ORM :

- `AppointmentToCreate(salon_id, client_id, hairdresser_id | None, date, start_time, end_time,
  status=PENDING, client_note | None, services: tuple[BookedService, ...])` où
  `BookedService(service_id, price_at_booking)` porte le prix figé (§ `AppointmentService`). **≥ 1**
  service requis (validé avant écriture).
- `Appointment(id, salon_id, client_id, hairdresser_id, date, start_time, end_time, status,
  client_note, created_at, ...)` (entité de lecture).
- Règles pures : `validate_booking_window(start, end)` (`end > start`, cohérent avec le `CHECK`
  base) ; `require_services(services)` (`≥ 1`, sinon `AppointmentServiceRequired`) ; calcul optionnel
  `end_time = start_time + somme(durées)` pour une réservation multi-prestations (voir Open Questions).

**`domain/errors.py` (modifier)** — nouvelles erreurs **neutres** (ni PII ni détail SQL) :

- `SlotAlreadyBooked(DomainError)` : le créneau/coiffeur est déjà pris — **inclut le perdant d'une
  course concurrente** (traduction de la violation d'exclusion base). → `409 Conflict`.
- `SlotUnavailable(DomainError)` : le créneau demandé n'est pas dans l'offre (hors horaires, mal
  aligné, passé). → `409` (ou `422` — à trancher, voir Open Questions).
- `SalonNotBookable(DomainError)` : salon inactif ou sans horaire (§8.3). → `409` (ou `422`).
- `AppointmentServiceRequired(DomainError)` : réservation sans prestation (§8.1). → `422`.
- (Réutiliser `ServiceNotFound` / `SalonNotFound` pour prestation/salon inconnus dans la portée.)
  Mettre à jour `__all__`.

### 2. Application (cas d'usage)

**`application/ports/appointment_repository.py` (nouveau)** — protocole (typing.Protocol ou ABC, au
choix du patron existant) :

- `booked_slots(salon_id, hairdresser_id, date) -> tuple[SlotRange, ...]` : créneaux **actifs**
  (`status IN (PENDING, CONFIRMED)`) d'un coiffeur pour une date (alimente le moteur).
- `create(appointment: AppointmentToCreate) -> Appointment` : insère le RDV **et** ses lignes
  `appointment_services` dans la **même** unité de travail ; **doit** lever `SlotAlreadyBooked` si la
  contrainte d'exclusion est violée (course concurrente), en distinguant cette violation des autres.

**`application/appointments.py` (nouveau)** :

- `CheckAvailability` : `execute(salon_id, date, service_id, hairdresser_id | None, *, granularity) ->
  tuple[SlotRange, ...]`. Charge le salon (via un port de lecture — réutiliser le dépôt salon ou le
  dépôt catalogue selon la surface retenue), refuse si **non réservable** (`is_bookable`, §8.3) →
  `SalonNotBookable` ; charge la prestation (active, même salon) sinon `ServiceNotFound` ; lit
  `booked_slots(...)` ; retourne `free_slots(...)`.
- `BookAppointment` : `execute(salon_id, client_id, command) -> Appointment`. Séquence :
  1. valider `≥ 1` prestation (`require_services`) et la fenêtre horaire ;
  2. refuser si salon non réservable (§8.3) et si prestation inactive/hors salon ;
  3. **défense en profondeur** : `is_offered(...)` (créneau dans l'offre) sinon `SlotUnavailable` ;
  4. `repository.create(AppointmentToCreate(...))` — **une transaction** ; en cas de course, l'INSERT
     perd sur la contrainte d'exclusion ⇒ le dépôt lève `SlotAlreadyBooked` ⇒ **rollback** de toute
     l'unité de travail (RDV + jonctions).
  - `client_id` et `salon_id` proviennent **du serveur/portée**, jamais du corps (anti-élévation,
    miroir de `owner_id` #15 et `salon_id` #17).

> **Cœur de la garantie (à documenter dans les docstrings)** : entre l'étape 3 (contrôle applicatif) et
> l'étape 4 (INSERT) subsiste un TOCTOU. Il est **fermé par la base** : sous `READ COMMITTED` (défaut
> SQLAlchemy), deux INSERT concurrents de créneaux qui se chevauchent pour le même `hairdresser_id`
> déclenchent l'attente puis l'**échec** du second sur `ex_appointments_hairdresser_slot`. L'application
> ne « gagne » jamais la course à la place de la base ; elle se contente de **traduire** l'échec.

### 3. Adapter sortant (persistance)

**`adapters/outbound/persistence/appointment_repository.py` (nouveau)** — `SqlAppointmentRepository`
sur `Session` SQLAlchemy, calqué sur `SqlServiceRepository` :

- `booked_slots(...)` : `SELECT` sur `Appointment` filtré `salon_id`, `hairdresser_id`,
  `appointment_date == date`, `status IN (PENDING, CONFIRMED)` → `SlotRange`.
- `create(...)` : `session.add(Appointment(...))` + `session.add(AppointmentService(...))` pour chaque
  prestation, puis `session.flush()` (déclenche INSERT et contraintes **sans committer** — le commit
  est piloté par `get_session`). **Attraper `sqlalchemy.exc.IntegrityError`** et, si la contrainte
  fautive est `ex_appointments_hairdresser_slot` (inspecter `error.orig` / le nom de contrainte
  psycopg — code SQLSTATE `23P01` *exclusion_violation*), **lever `SlotAlreadyBooked`** ; toute autre
  `IntegrityError` est relevée telle quelle (ne jamais masquer une FK/CHECK inattendue). **Ne jamais**
  journaliser le contenu de l'erreur brute (peut porter des identifiants) — message neutre.
- Mapper les modèles ORM ↔ entités de domaine (`_to_domain`), sans fuite de détail SQLAlchemy.

### 4. Adapter entrant (HTTP)

**`adapters/inbound/appointments.py` (nouveau)** — router assemblé par DI (dépendances
surchargeables en test), schémas Pydantic documentés (OpenAPI). Deux surfaces (surface exacte **à
confirmer**, voir Open Questions) :

- **Lecture de disponibilité** — `GET .../availability?date=&service_id=&hairdresser_id=` : renvoie la
  liste des créneaux **libres** (jamais l'identité de qui occupe les créneaux pris — cf. Privacy).
  Destinée au **client** (avant réservation) : soit publique sous `/catalog/salons/{salon_id}/
  availability` (patron #18/#19, ajout à `PUBLIC_ROUTE_PATHS`), soit authentifiée
  `require_permission(SERVICE_READ)`/`SALON_READ_ANY` **sans** `require_salon_scope`.
- **Réservation** — `POST .../appointments` : crée le RDV. Le corps porte `date`, `start_time`,
  `service_id(s)`, `hairdresser_id?`, `client_note?` — **jamais** `client_id`/`salon_id`/`status`.
  Traductions d'erreurs : `SlotAlreadyBooked` → **409** ; `SlotUnavailable`/`SalonNotBookable` → **409**
  (ou 422) ; `AppointmentServiceRequired`/fenêtre invalide → **422** ; `ServiceNotFound`/`SalonNotFound`
  → **404** *après* portée. Deux acteurs possibles selon la surface : **client**
  (`APPOINTMENT_BOOK`, `client_id = principal.id`, pas de `require_salon_scope`) et/ou **gérant**
  (`APPOINTMENT_MANAGE` + `require_salon_scope`, réservation walk-in) — **à confirmer** (US-3.1 vs
  US-3.4). Recommandation MVP : livrer **au moins** le chemin qui rend l'acceptation testable (client
  `APPOINTMENT_BOOK`), tout en gardant le cas d'usage réutilisable par le gérant.

**`coiflink_api/main.py` (modifier)** : `app.include_router(appointments_router)` ; ajouter le chemin de
disponibilité à `PUBLIC_ROUTE_PATHS` **seulement** s'il est décidé public (décision de sécurité, ADR).

### 5. Documentation & ADR

Rédiger **ADR-0023** (Moteur de disponibilité & anti double-réservation) actant : garantie portée par
la contrainte d'exclusion base (source de vérité), moteur pur au-dessus, granularité et fuseau retenus,
surface des routes et acteur(s), sémantique de chevauchement (fermé-ouvert, adjacence tolérée). Indexer
dans `docs/adr/README.md`. Mettre à jour `backend/README.md` (section rendez-vous/disponibilité).

## Affected Files / Packages / Modules

**À créer :**
- `backend/coiflink_api/domain/availability.py` — moteur pur (créneaux libres, chevauchement).
- `backend/coiflink_api/domain/appointment.py` — entités & règles de rendez-vous.
- `backend/coiflink_api/application/ports/appointment_repository.py` — port.
- `backend/coiflink_api/application/appointments.py` — cas d'usage `CheckAvailability`, `BookAppointment`.
- `backend/coiflink_api/adapters/outbound/persistence/appointment_repository.py` — `SqlAppointmentRepository`.
- `backend/coiflink_api/adapters/inbound/appointments.py` — router HTTP (disponibilité + réservation).
- `docs/adr/0023-moteur-disponibilite-anti-double-reservation.md` (+ entrée `docs/adr/README.md`).
- Tests (voir *Testing Plan*).

**À modifier :**
- `backend/coiflink_api/domain/errors.py` — nouvelles erreurs + `__all__`.
- `backend/coiflink_api/main.py` — inclusion du router (+ `PUBLIC_ROUTE_PATHS` si public).
- `backend/tests/conftest.py` — `FakeAppointmentRepository` (dont un mode « lève `SlotAlreadyBooked` »
  pour simuler la course, sur le patron de `FakeUserRepositoryRaisingDuplicate` /
  `FakeSalonMemberRepository(raise_duplicate=True)`), fixture associée.
- `backend/README.md` — section rendez-vous/disponibilité + commande des tests de concurrence.
- (Optionnel) `backend/migrations/versions/0005_*.py` — index d'accélération (voir *Data Model*).

**À lire (contexte) :** `adapters/outbound/persistence/models.py` (Appointment/AppointmentService/
EXCLUDE), `migrations/versions/0001_schema_initial.py`, `domain/opening_hours.py`, `domain/service.py`,
`domain/salon.py` (`is_bookable`), `domain/permissions.py`, `adapters/inbound/security.py`,
`adapters/inbound/services.py`, `adapters/inbound/catalog.py` (surface publique),
`adapters/outbound/persistence/session.py`, `tests/test_service_e2e.py` (patron e2e Postgres + skip).

## API / Interface Changes

**Nouvelles routes HTTP** (surface exacte à confirmer — Open Questions) :

- `GET` disponibilité — p. ex. `GET /catalog/salons/{salon_id}/availability?date=YYYY-MM-DD&
  service_id=...&hairdresser_id=...` → `200` liste de créneaux libres `[{date, start, end}]` ; `404`
  salon inconnu/non actif ; `409`/`422` salon non réservable ou paramètres invalides.
- `POST` réservation — p. ex. `POST /salons/{salon_id}/appointments` ou `POST /appointments` → `201`
  `{id, salon_id, hairdresser_id, date, start_time, end_time, status, services:[...]}` ; `409` créneau
  déjà pris (course perdue) ; `422` sans prestation / fenêtre invalide ; `403` rôle/portée ; `404`
  salon/prestation hors portée.

Corps de réservation : **aucun** `client_id`/`salon_id`/`status` accepté (imposés serveur ;
`extra="ignore"` comme `CreateServiceRequest`). Documentation OpenAPI fournie (docstrings + `responses`).

Aucune modification d'API existante. Aucune interface CLI nouvelle.

## Data Model / Protocol Changes

**Aucune modification de schéma requise.** Les tables `appointments` / `appointment_services`, la
colonne générée `slot tsrange`, l'extension `btree_gist` et la contrainte d'exclusion
`ex_appointments_hairdresser_slot` **existent déjà** (issue #3, migration `0001_schema_initial`). #21
n'écrit et ne lit que via ce schéma.

**Option (non requise)** : une migration additive `0005_*` créant un index
`(salon_id, hairdresser_id, appointment_date)` pour accélérer `booked_slots` si les mesures le
justifient (l'index existant `ix_appointments_salon_id (salon_id, appointment_date)` couvre déjà en
grande partie ce besoin). À décider au vu du budget latence §12 — par défaut : **ne pas** ajouter
d'index tant qu'aucun besoin n'est démontré.

## Security & Privacy Considerations

- **Anti double-réservation = intégrité de données** : la garantie est portée par la **base**
  (contrainte d'exclusion), pas par un verrou applicatif faillible. L'implémentation ne doit **jamais**
  contourner ni désactiver cette contrainte, ni tenter un « check-then-insert » applicatif comme unique
  rempart. Point de vigilance : la contrainte ne s'applique **qu'aux RDV avec `hairdresser_id NOT NULL`
  et `status IN (PENDING, CONFIRMED)`** — voir *Open Questions* sur les réservations sans coiffeur.
- **Isolation par salon §11.2 / anti-élévation** : `salon_id` vient du chemin/portée, `client_id` vient
  du `Principal` (client) — jamais du corps. Les FK composites `(salon_id, service_id)` /
  `(salon_id, appointment_id)` empêchent au niveau base de mêler des entités de salons différents.
  Un `CLIENT` ne réserve que pour **lui-même** ; un refus de portée renvoie le **`403` générique**
  (aucun oracle d'existence).
- **PII (§11.3) dans la disponibilité** : une réponse de disponibilité ne doit exposer **que des
  créneaux libres** — **jamais** l'identité (`client_id`, nom, téléphone) de qui occupe les créneaux
  pris, ni même nécessairement les créneaux occupés. Collecte/exposition minimale.
- **Messages d'erreur & logs neutres** : `SlotAlreadyBooked`/`SlotUnavailable`/`SalonNotBookable`
  portent des messages génériques (ni PII ni détail SQL). L'`IntegrityError` psycopg brute **n'est
  jamais journalisée** telle quelle (elle peut contenir des identifiants de ligne) : on inspecte le
  nom de contrainte / le SQLSTATE puis on lève une erreur de domaine neutre. Aucun secret manipulé.
- **§8.3 respecté** : aucune réservation sur un salon non `ACTIVE` ou sans horaire.
- **Budgets §12** : la vérification de disponibilité et la réservation doivent rester bien en deçà du
  budget API (< 3 s) ; les index existants sur `appointments` soutiennent la requête `booked_slots`.
- **Résidence/hébergement** : inchangé (ADR-0011) ; aucune donnée nouvelle exfiltrée.

## Testing Plan

Le test gate est `pytest` (`backend/pyproject.toml`, `testpaths=["tests"]`). Les tests existants
doivent rester verts. Convention du dépôt : les tests **Postgres** *skip proprement* si
`DATABASE_URL` est absent (patron `test_service_e2e.py` : `pytest.skip` / `@pytest.mark.skipif`).

- **Unit — moteur pur (sans base, rapides)** `tests/test_domain_availability.py` :
  - jour fermé (absent / `[]`) → aucun créneau ;
  - exception datée **fermée** prime sur un jour hebdo ouvert → aucun créneau ; exception **ouverte**
    prime et impose ses intervalles ;
  - **pauses** (deux intervalles) : aucun créneau ne chevauche le trou ;
  - une prestation **plus longue** que tout intervalle → aucun créneau ;
  - **adjacence** `end == start` tolérée (deux créneaux dos-à-dos ne sont pas en conflit) ;
    chevauchement d'une minute → conflit ;
  - créneaux **passés** exclus quand `now` fourni ; granularité respectée ; tri/déduplication.
- **Unit — règles rendez-vous** `tests/test_domain_appointment.py` : `end > start`, `≥ 1` prestation
  (`AppointmentServiceRequired`), calcul `end_time` multi-prestations (si retenu).
- **Unit — application avec fakes** `tests/test_appointment_usecases.py` :
  - `CheckAvailability` refuse un salon non réservable (§8.3) et une prestation inactive/hors salon ;
    renvoie les créneaux du moteur pour un salon réservable ;
  - `BookAppointment` : `client_id`/`salon_id` **jamais** issus du corps ; refuse `SlotUnavailable`
    (défense en profondeur) ; **propage `SlotAlreadyBooked`** quand le `FakeAppointmentRepository`
    simule la violation d'exclusion (mode `raise_conflict=True`) — et **rien n'est persisté**.
- **Intégration Postgres** `tests/test_appointment_api.py` / `tests/test_appointment_e2e.py`
  (skip si pas de `DATABASE_URL`) :
  - insertion réelle : un second RDV **actif** chevauchant, même coiffeur → rejeté (409) ; un RDV
    `CANCELLED`/`NO_SHOW` chevauchant → **accepté** (hors clause `WHERE` de l'exclusion) ;
  - RDV sans `hairdresser_id` (NULL) : documenter/asserter le comportement retenu (voir Open Questions) ;
  - isolation inter-salons (403 générique) ; RDV sans prestation refusé (422) ; disponibilité ne
    fuit aucune PII.
- **Concurrence (critère d'acceptation dur)** `tests/test_appointment_concurrency.py` (Postgres, skip
  sinon) :
  - **deux transactions concurrentes** (deux connexions/sessions réelles + `threading.Barrier` pour
    maximiser la contention, via `ThreadPoolExecutor`) insèrent le **même créneau/coiffeur** puis
    committent → **exactement un succès** et une `IntegrityError`/`SlotAlreadyBooked` (SQLSTATE
    `23P01`). Répéter N fois pour la robustesse.
  - variante **HTTP** : deux `TestClient` (threads) sur `POST .../appointments` sur le même
    créneau/coiffeur → exactement **un `201`** et **un `409`**.
  - *Note d'outillage* : la fonctionnalité est **spécifique PostgreSQL** (`btree_gist` + `EXCLUDE`) ;
    ces tests ne peuvent pas s'exécuter sur SQLite et **doivent** skip sans `DATABASE_URL`. Le
    fournisseur de Postgres (testcontainers vs service CI #4 vs DSN local) reste une **décision
    d'outillage à confirmer** — aligner sur le choix déjà retenu par les e2e existants.
- **Documentation** : vérifier (revue) que `backend/README.md` documente la commande des tests de
  concurrence et le prérequis Postgres.

## Documentation Updates

- **`docs/adr/0023-moteur-disponibilite-anti-double-reservation.md`** (nouveau) : garantie portée par
  l'`EXCLUDE` base, moteur pur au-dessus, granularité/fuseau, sémantique de chevauchement, surface des
  routes et acteur(s), comportement sans coiffeur. Ajouter l'entrée dans **`docs/adr/README.md`**.
- **`backend/README.md`** : section « Rendez-vous : disponibilité & anti double-réservation » — moteur
  de créneaux, règle §8.1, prérequis Postgres, commande des tests de concurrence, rappel « la garantie
  vient de la contrainte d'exclusion ».
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstrings + `responses` sur les nouvelles routes (généré automatiquement par FastAPI).

## Risks and Open Questions

- **Frontière avec US-3.1 (réservation client) et US-3.4 (confirmer/refuser)** : #21 doit-il livrer le
  **tunnel client complet** et le chemin gérant, ou seulement le **moteur + un chemin de réservation
  minimal** qui rend l'anti-doublon testable ? *Recommandation : le second* (moteur + cas d'usage
  réutilisable + au moins une route de réservation), la richesse UX/US-3.1 se superposant ensuite.
  **À confirmer.**
- **Réservations sans coiffeur assigné (`hairdresser_id NULL`)** : la contrainte d'exclusion **ne
  s'applique pas** (clause `WHERE hairdresser_id IS NOT NULL`) — conforme au §8.1 (« pour le même
  coiffeur »), mais laisse ouverte la question d'une **capacité de salon** sans coiffeur. Options :
  (a) exiger un coiffeur pour que la règle s'applique ; (b) traiter le salon comme une ressource
  unique implicite ; (c) laisser sans limite au MVP. *Recommandation : documenter (c) au MVP et exiger
  un coiffeur pour bénéficier de la garantie.* **À confirmer (décision produit).**
- **Granularité des créneaux** : grille fixe (15/30 min) vs pas = durée de la prestation vs créneaux
  alignés sur le début des intervalles d'ouverture. Impacte l'UX et les tests. **À confirmer** ; défaut
  proposé : pas paramétrable, valeur MVP 15 min.
- **Réservation multi-prestations** : `end_time = start + somme(durées)` (le schéma autorise plusieurs
  lignes `appointment_services`) ou une prestation unique au MVP ? **À confirmer** ; défaut proposé :
  supporter ≥ 1 prestation, `end_time` = somme des durées.
- **Codes HTTP** : `SlotUnavailable`/`SalonNotBookable` en **409** (état/ressource) ou **422**
  (requête) ? `SlotAlreadyBooked` est clairement **409**. **À confirmer** ; défaut proposé : 409 pour
  les conflits d'état, 422 pour les entrées invalides (fenêtre, `≥ 1` prestation).
- **Surface & visibilité de la disponibilité** : route **publique** (catalogue #18/#19, ajout à
  `PUBLIC_ROUTE_PATHS`) ou **authentifiée** ? Faut-il exposer les créneaux **occupés** (busy) ou
  seulement les **libres** ? *Recommandation : n'exposer que les libres ; décider la visibilité
  publique via l'ADR.* **À confirmer (décision de sécurité).**
- **Fuseau horaire** : Africa/Abidjan = UTC+0 (cohérent avec `tsrange` et le défaut #16). Si un fuseau
  à décalage était introduit plus tard, le choix `tsrange`/`timestamp` du schéma devrait être revu. Le
  moteur doit rester explicite sur l'hypothèse UTC+0.
- **Sessions sync vs async pour la concurrence** : `get_session` est **synchrone** (threadpool
  FastAPI). Le test de concurrence doit utiliser **deux connexions distinctes** (le pooling + le
  threadpool le permettent) ; une async engine n'est pas requise. **À confirmer** au moment de
  l'implémentation du test.
- **Outillage Postgres en test** (testcontainers vs service CI #4 vs DSN local) : non tranché à
  l'échelle du dépôt ; s'aligner sur les e2e existants (skip conditionnel sur `DATABASE_URL`).
- **Isolation du niveau de transaction** : sous `READ COMMITTED` (défaut), l'exclusion suffit à
  garantir l'unicité (le second INSERT attend puis échoue). Aucune élévation à `SERIALIZABLE` n'est
  nécessaire ; le noter pour éviter une sur-ingénierie.

## Implementation Checklist

1. **Lire le socle** : `models.py` (Appointment/AppointmentService/EXCLUDE), migration `0001`,
   `opening_hours.py`, `service.py`, `salon.py::is_bookable`, `permissions.py`, `security.py`,
   patrons `services.py` (in/out) et `session.py`.
2. **Trancher les Open Questions structurantes** avec le porteur produit (frontière US-3.1, coiffeur
   obligatoire ou non, granularité, multi-prestations, surface/visibilité disponibilité, codes HTTP) et
   les acter dans **ADR-0023** (+ `docs/adr/README.md`).
3. **Domaine — moteur** : créer `domain/availability.py` (`SlotRange`, `overlaps`,
   `intervals_for_date`, `free_slots`, `is_offered`) — pur, fuseau UTC+0, chevauchement fermé-ouvert.
4. **Domaine — rendez-vous** : créer `domain/appointment.py` (`AppointmentToCreate`, `BookedService`,
   `Appointment`, `require_services`, `validate_booking_window`, calcul `end_time`).
5. **Erreurs** : ajouter `SlotAlreadyBooked`, `SlotUnavailable`, `SalonNotBookable`,
   `AppointmentServiceRequired` à `domain/errors.py` (+ `__all__`), messages **neutres**.
6. **Port** : créer `application/ports/appointment_repository.py` (`booked_slots`, `create` levant
   `SlotAlreadyBooked` sur violation d'exclusion).
7. **Cas d'usage** : créer `application/appointments.py` (`CheckAvailability`, `BookAppointment`) —
   §8.3, prestation active/du salon, défense en profondeur `is_offered`, `client_id`/`salon_id`
   imposés serveur, écriture transactionnelle unique.
8. **Adapter sortant** : créer `SqlAppointmentRepository` — requête `booked_slots` (`status IN
   (PENDING,CONFIRMED)`), `create` (add RDV + jonctions, `flush`), traduction `IntegrityError`
   (SQLSTATE `23P01` / contrainte `ex_appointments_hairdresser_slot`) → `SlotAlreadyBooked`, **sans
   journaliser l'erreur brute**.
9. **Adapter entrant** : créer `adapters/inbound/appointments.py` (route disponibilité + route
   réservation), schémas Pydantic (`extra="ignore"`, pas de `client_id`/`salon_id`/`status`),
   gardes RBAC selon la surface retenue, traductions d'erreurs → codes HTTP.
10. **Composition root** : `app.include_router(...)` dans `main.py` (+ `PUBLIC_ROUTE_PATHS` si public).
11. **Fakes de test** : `FakeAppointmentRepository` (+ mode `raise_conflict`) et fixture dans
    `conftest.py`.
12. **Tests** : moteur pur, règles RDV, cas d'usage (fakes), intégration Postgres, et **concurrence**
    (deux transactions/HTTP concurrents → exactement une réussite) — tous les tests Postgres **skip**
    sans `DATABASE_URL`.
13. **Documentation** : ADR-0023 + `docs/adr/README.md` + section `backend/README.md` (commande des
    tests de concurrence, prérequis Postgres, rappel « garantie = contrainte d'exclusion »).
14. **Garde-fous** : `pytest` vert (tests sans base au minimum ; Postgres si DSN dispo) ; aucun secret
    ni PII journalisé ; aucune signature IA dans le code/commits/PR ; contrainte d'exclusion **jamais**
    contournée.
