# Planning personnel du coiffeur (US-3.6)

> Spécification de planification pour l'issue GitHub **#27 — US-3.6 : Planning personnel du
> coiffeur** (`feature` · Should · Effort M · PRD §6 Épic 3 / §11.2). **Dépend de #13**
> (comptes employés & appartenance `salon_members`) et **#26** (planning salon — lecture
> salon-scopée, domaine web du planning). **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, enums SQL) inchangés. **Aucune
> signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 3, US-3.6) pose le besoin : **« en tant que coiffeur, je veux consulter les
rendez-vous qui me sont assignés »**, avec pour spécification fonctionnelle un **planning personnel
du coiffeur**. Le rôle coiffeur est **facultatif au MVP** (PRD §2.3) : activable pour les salons
structurés à plusieurs employés. Ses fonctions (PRD §5, §4.1) : *voir son planning*, *confirmer une
prestation*, *mettre à jour un statut*. L'invariant d'isolation §11.2 est explicite :

- **« Un coiffeur ne peut voir que son planning ou les rendez-vous qui lui sont assignés. »**

Le critère d'acceptation de l'issue #27 le reprend :

- **Un coiffeur voit uniquement son planning ; aucun accès aux RDV non assignés.**

C'est **avant tout une garantie d'autorisation** (lecture assignment-scopée) : le cœur de #27 est
qu'un coiffeur authentifié ne puisse lire **que** les RDV dont il est le coiffeur assigné
(`hairdresser_id = son identifiant`), jamais ceux d'un collègue, jamais les RDV non assignés, jamais
ceux d'un autre salon.

État actuel du dépôt (après #21→#26) — ce qui existe déjà et ce qui manque :

- **Les droits & la portée du coiffeur sont déjà modélisés, mais aucune route ne les câble en
  lecture.** La matrice §4.1 (`domain/permissions.py`) attribue au `HAIRDRESSER` la permission
  **`APPOINTMENT_READ_ASSIGNED`** (« voit son planning / les RDV qui lui sont assignés ») **et**
  `APPOINTMENT_UPDATE_STATUS`. La règle de portée `domain/access.can_access_appointment` restreint
  déjà un `HAIRDRESSER` à un RDV **assigné** (`appointment.hairdresser_id == principal.id`). Mais
  **`APPOINTMENT_READ_ASSIGNED` n'est câblée sur aucune route** : il n'existe aucun endpoint qu'un
  coiffeur puisse appeler pour lire son planning.
- **La lecture salon-scopée livrée par #26 est réservée au gérant.**
  `GET /salons/{salon_id}/appointments` exige `APPOINTMENT_READ_SALON` — permission que le
  `HAIRDRESSER` **ne possède pas**. Un coiffeur y obtient donc un `403` : l'isolation est **déjà
  respectée** (un coiffeur ne peut pas lire tout le salon), mais il **n'a pas de vue du tout**. #27
  doit livrer **sa** vue, restreinte à ses assignations.
- **Le port `AppointmentRepository` sait lister par client (#23) et par salon (#26), pas par
  coiffeur.** Il porte `list_for_client(client_id, statuses?)` et
  `list_for_salon(salon_id, date_from, date_to, statuses?)`, mais **aucune** méthode « lister les RDV
  assignés à un coiffeur sur une période ». **#27 doit livrer ce chemin de lecture.**
- **La portée d'un coiffeur fait déjà autorité (via #13/ADR-0016).**
  `SqlSalonScopeRepository.salon_ids_for(id, HAIRDRESSER)` lit `salon_members WHERE user_id = … AND
  status = 'ACTIVE'` : un coiffeur « voit » son salon dès sa création. Un membre `INACTIVE` perd sa
  portée. (Ce port reste inchangé par #27 — voir Non-Goals.)
- **Il n'existe aucune surface où un coiffeur se connecte.** Le web (`web-dashboard/`) n'expose que
  la **zone gérant** `/gerant` (garde `canAccessGerant` → **rôle `MANAGER` uniquement**) et la zone
  admin ; l'application mobile (`app-mobile/`) est **cliente**. Un `HAIRDRESSER` peut s'authentifier
  (`POST /auth/login`, #10/ADR-0016) mais **aucune interface ne l'accueille**. Le PRD ne prévoit
  **pas** d'interface coiffeur dédiée au MVP (les interfaces §7 sont : mobile client, web gérant, web
  admin ; « Application coiffeur dédiée » est une évolution **V2**, PRD §21). **La surface de
  consultation du coiffeur est donc la décision structurante de #27** (voir Proposed Implementation
  §B et Open Questions).
- **Le domaine web du planning (#26) est déjà pur et réutilisable.**
  `web-dashboard/src/domain/appointment/appointment.ts` (statuts, libellés FR, couleurs, prédicats
  d'action) et `…/planning-view.ts` (plages jour/semaine/mois, groupement par statut/jour,
  compteurs, `todayIso` UTC+0) ne dépendent d'aucune source de données particulière : ils s'appliquent
  tels quels à une liste de RDV **assignés**.

Le gap que #27 comble : **(A)** un **endpoint de lecture assignment-scopé**
`GET /appointments/assigned` (câblant `APPOINTMENT_READ_ASSIGNED`, filtrant `hairdresser_id =
principal.id` **imposé serveur**) filtrable par **plage de dates** et, optionnellement, par
**statut** ; **(B)** une **surface de consultation** du planning personnel du coiffeur (décision de
périmètre : voir Proposed Implementation §B), réutilisant le domaine de planning livré par #26.

## Goals

- **Lecture assignment-scopée des rendez-vous (backend).** `GET /appointments/assigned` renvoie les
  RDV **assignés au coiffeur authentifié** (`hairdresser_id = principal.id`) sur une **plage de
  dates** (`date_from`/`date_to` inclusifs, bornée), triés chronologiquement, **tous statuts** par
  défaut, avec un **filtre optionnel par statut**. Câble la permission **`APPOINTMENT_READ_ASSIGNED`**
  (jamais câblée jusqu'ici). Aucun nouveau schéma requis pour l'AC.
- **Isolation « il ne voit que les siens » (§11.2).** Route d'**appartenance** (pas de `salon_id`
  dans le chemin) : le `hairdresser_id` vient **du `Principal`**, jamais d'un champ soumis, et le
  dépôt refiltre `hairdresser_id` en SQL (défense en profondeur). Un coiffeur ne lit **jamais** un
  RDV d'un collègue, un RDV non assigné (`hairdresser_id IS NULL`), ni un RDV d'un autre salon.
  C'est le **cœur de l'AC**.
- **Deny-by-default (ADR-0015).** La route exige `APPOINTMENT_READ_ASSIGNED` : un `CLIENT`, un
  `MANAGER` et un `ADMIN` ne la détiennent pas → `403`. **Rien** n'est ajouté à
  `PUBLIC_ROUTE_PATHS` ; `unprotected_routes(app)` **reste vide** (invariant testé).
- **Séparation nette gérant / coiffeur.** #27 **n'élargit pas** la route gérant #26
  (`GET /salons/{salon_id}/appointments` reste `APPOINTMENT_READ_SALON`) et **ne redéfinit aucune**
  règle de portée : il ajoute un **chemin de lecture parallèle**, propre au coiffeur.
- **Consultation du planning personnel (surface coiffeur).** Le coiffeur **consulte** son planning
  (au minimum la vue jour, idéalement jour/semaine/mois par réutilisation du domaine #26), RDV
  affichés/groupés par statut avec libellés FR. La surface exacte est une décision de périmètre
  (voir §B / Open Questions).
- **Réutilisation du domaine de planning #26.** Le domaine web pur (`appointment.ts`,
  `planning-view.ts`) est **réutilisé tel quel** ; la présentation (`planning-board.tsx`) est rendue
  **réutilisable** (paramétrée par la source de RDV, variante lecture) plutôt que dupliquée.
- **Jeton jamais exposé (#14).** Si une surface web est retenue, toute lecture backend passe **côté
  serveur Next** avec le jeton lu du cookie `httpOnly` — **jamais** transmis au navigateur, **jamais**
  journalisé (invariant #14, §11.3).
- **Couverture de tests.** Backend (port/adapter de lecture assignment-scopée, cas d'usage, HTTP :
  portée par `hairdresser_id`, filtre, plage bornée, deny-by-default, `403` pour `CLIENT`/`MANAGER`,
  isolation inter-coiffeurs/inter-salons) ; front selon la surface retenue (domaine réutilisé,
  gateway HTTP, garde de session coiffeur).

## Non-Goals

- **Modifier la matrice de permissions (§4.1) ou les règles de portée.** `APPOINTMENT_READ_ASSIGNED`
  existe déjà ; `can_access_appointment` restreint déjà le coiffeur. #27 **câble** ces droits, il n'en
  crée aucun et n'en élargit aucun. Le port `SalonScopeRepository` reste inchangé (#13/ADR-0016).
- **Écriture de statut par le coiffeur** (« confirmer une prestation / mettre à jour un statut »,
  PRD §5). *Recommandation : hors périmètre de #27* — l'AC de #27 est strictement une **lecture**
  isolée. ⚠ **Point de sécurité à ne pas ignorer** : la route de statut #25
  (`POST /salons/{salon_id}/appointments/{id}/status`) est **salon-scopée**
  (`APPOINTMENT_UPDATE_STATUS` + `require_salon_scope`), or un `HAIRDRESSER` détient
  `APPOINTMENT_UPDATE_STATUS` **et** une portée salon (via `salon_members`). En l'état, un coiffeur
  pourrait donc piloter le statut d'un RDV **non assigné** de son salon. Tant que #27 se limite à la
  **lecture assignment-scopée**, l'AC (« aucun accès aux RDV non assignés ») porte sur la lecture et
  est satisfaite. **Ne pas** exposer d'actions de statut au coiffeur dans #27 **sans** d'abord
  resserrer la route #25 côté écriture (contrôle d'assignation quand l'acteur est un `HAIRDRESSER`) —
  sujet d'un suivi (voir Risks & Open Questions).
- **Assignation d'un coiffeur** (`PUT .../hairdresser`, #25) et **liste des employés/coiffeurs** :
  hors périmètre (le coiffeur ne gère rien ; il consulte). Aucun endpoint de liste des employés
  n'existe (seul `POST /salons/{salon_id}/employees`, #13) — sans conséquence sur #27, qui n'en a pas
  besoin.
- **Nouvelle table, migration métier, contrainte.** Le schéma #3 (table `appointments`, colonne
  `hairdresser_id`) suffit à l'AC. Un **index de performance** sur `hairdresser_id` est une
  **optimisation optionnelle** discutée en Open Questions (additive, non requise par l'AC).
- **Enrichissement de l'identité client** (nom/téléphone). `AppointmentResponse` ne porte que des
  UUID ; l'enrichissement (jointure `users`) relève de la gestion clients (#28+). Au MVP : libellé
  neutre (créneau + prestation), pas de PII non maîtrisée (§11.3).
- **Notifications** (§8.4, Épic 7). Aucune notification n'est émise.
- **Chiffre d'affaires / encaissement** (M4/M5). Aucun montant n'est agrégé ; `price_at_booking`
  reste indicatif (déjà porté par `AppointmentResponse`).
- **Application coiffeur mobile dédiée** (PRD §21, V2). #27 ne crée pas d'app mobile coiffeur ; la
  surface éventuelle est web (voir §B).
- **Temps réel / websockets / rafraîchissement périodique.** Hors périmètre (comme #26).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

- **Backend** : FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0 + Alembic +
  psycopg 3 (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) — `domain/` et
  `application/` n'importent **jamais** FastAPI ni SQLAlchemy ; RBAC **deny-by-default** (ADR-0015).
  Tests `pytest` (`backend/pyproject.toml`, `testpaths=["tests"]`).
- **Web** : Next.js 16 / React 19 / TypeScript (ADR-0002), **App Router**, Tailwind v4. Zone gérant
  `/gerant` protégée (cookie `httpOnly` + BFF + garde serveur `GET /auth/me` via
  `requireManagerSession`). Tests **Vitest** (`web-dashboard/package.json`, `vitest run`).
- **Mobile** : Flutter (ADR-0001), paquet **client** — pas de flux coiffeur.
- **Test gate** agrégé (#6) : `scripts/test-gate.sh` enchaîne `pytest` / `npm test` / `flutter test`.
- **Fuseau horaire** : `Africa/Abidjan` (UTC+0), datetimes **naïfs** côté backend (`_now()` renvoie
  l'UTC naïf) — le « jour courant » du planning se calcule dans ce repère (helper pur `todayIso`,
  déjà livré par #26).

### Backend — droits, portée & rendez-vous déjà livrés (à réutiliser/câbler)

- `coiflink_api/domain/permissions.py` — `HAIRDRESSER` détient **`APPOINTMENT_READ_ASSIGNED`** (à
  câbler) et `APPOINTMENT_UPDATE_STATUS`. `MANAGER` détient `APPOINTMENT_READ_SALON` (route #26).
  **Aucune nouvelle permission** n'est requise.
- `coiflink_api/domain/access.py` — `can_access_appointment(principal, appointment, scope)` :
  `HAIRDRESSER` ⇒ vrai **ssi** `appointment.hairdresser_id == principal.id` (« son planning »). Règle
  déjà écrite ; #27 la matérialise en **filtre de lecture SQL**.
- `coiflink_api/domain/enums.py` — `AppointmentStatus`
  (`PENDING|CONFIRMED|CANCELLED|COMPLETED|NO_SHOW`).
- `coiflink_api/application/appointments.py` — cas d'usage existants dont **`ListMyAppointments`**
  (lecture par `client_id`) et **`ListSalonAppointments`** (lecture par `salon_id` + plage, #26).
  **#27 y ajoute `ListAssignedAppointments`** (miroir par `hairdresser_id` + plage).
- `coiflink_api/application/ports/appointment_repository.py` — port `AppointmentRepository` :
  `list_for_client(...)` (#23), `list_for_salon(...)` (#26). **#27 y ajoute
  `list_for_hairdresser(hairdresser_id, date_from, date_to, statuses?)`.**
- `coiflink_api/adapters/outbound/persistence/appointment_repository.py` —
  `SqlAppointmentRepository` (`_to_domain`, `_load_services`, patrons
  `select(...).where(...).order_by(...)` de `list_for_client`/`list_for_salon`). **#27 y implémente
  `list_for_hairdresser`.**
- `coiflink_api/adapters/inbound/appointments.py` — router : DI surchargeables
  (`get_appointment_repository`), `_now()` UTC+0, `_appointment_response(...)` (schéma commun
  `AppointmentResponse`), `MAX_PLANNING_RANGE_DAYS = 42` (garde de coût, réutilisable), route client
  d'**appartenance** `GET /appointments` (patron direct de la route coiffeur), route gérant #26
  `GET /salons/{salon_id}/appointments` (patron de la plage/statut). **#27 y ajoute la route
  coiffeur.**
- `coiflink_api/adapters/inbound/security.py` — `require_permission`, `PUBLIC_ROUTE_PATHS` (n'y
  **rien** ajouter), invariant `unprotected_routes(app)`. La route coiffeur est une route
  d'**appartenance** (pas de `require_salon_scope`, comme `GET /appointments` client — le filtre vient
  du `Principal`).
- `backend/tests/conftest.py` — `FakeAppointmentRepository` (fake du port ; `appointments` préchargés
  pour `list_for_client`/`list_for_salon`). **#27 y ajoute `list_for_hairdresser`** (refiltre
  `hairdresser_id`, plage, statuts).

### Modèle de données pertinent (schéma #3, `models.py`)

- `Appointment` : `id`, `salon_id`, `client_id`, **`hairdresser_id NULL`**, `appointment_date`,
  `start_time`, `end_time`, `status`, `client_note NULL`, `slot tsrange` (généré), `created_at`,
  `updated_at`. Index `ix_appointments_salon_id (salon_id, appointment_date)` (couvre #26). Contrainte
  d'exclusion `ex_appointments_hairdresser_slot` (GiST) — **ne couvre pas** un `hairdresser_id =` en
  lecture btree (voir Open Questions sur un index dédié optionnel). `AppointmentService` (jonctions +
  `price_at_booking`).

### Web — domaine de planning & patrons de session (à réutiliser)

- **Domaine pur (réutilisable tel quel)** : `src/domain/appointment/appointment.ts` (statuts,
  `STATUS_LABELS_FR`, `STATUS_STYLES`, `isTerminal`, prédicats/`availableActions` miroir #25) ;
  `src/domain/appointment/planning-view.ts` (`rangeForView`, `dayRange`/`weekRange`/`monthRange`,
  `groupByStatus`/`countByStatus`/`groupByDay`, `todayIso`/`shiftDate`, tout en **UTC+0**).
- **Présentation** : `src/adapters/ui/planning-board.tsx` (+ `weekly-agenda.tsx`,
  `exceptions-calendar.tsx`) — barre d'outils, vues jour/semaine/mois, groupement par statut. À
  rendre **réutilisable** (variante lecture / source de RDV paramétrable).
- **Port & adapter de lecture** : `src/application/ports/appointment-gateway.ts` (`listForSalon`,
  `setStatus`) ; `src/adapters/api/http-appointment-gateway.ts` (`fetch` **côté serveur**,
  `Authorization: Bearer` du cookie, `cache: "no-store"`, mappage `200/401/403/404/409/422/503`,
  `toAppointment` snake→camel, **jamais** de log du jeton). **#27 y ajoute `listAssigned`** (ou un
  gateway dédié).
- **Garde de session** : `src/domain/auth/session.ts` (`canAccessGerant` = `MANAGER` + `ACTIVE`) ;
  `src/domain/auth/role.ts` (`ROLES` inclut `HAIRDRESSER`, libellé **« Employé »**) ;
  `src/application/use-cases/require-manager-session.ts` (patron d'une **garde de session coiffeur**) ;
  `app/(gerant)/layout.tsx` (composition root de zone protégée) ; `app/(gerant)/gerant/planning/
  page.tsx` (patron de page planning : session → salon → période → lecture → board).

## Proposed Implementation

Périmètre : **(A)** une **route backend de lecture assignment-scopée** — **cœur de l'AC**, seul
ajout serveur indispensable ; **(B)** une **surface de consultation** du planning personnel du
coiffeur (décision de périmètre). Aucune modification de schéma requise par l'AC ; aucune évolution de
la matrice de permissions ni des règles de portée.

### (A) Backend — lecture assignment-scopée des rendez-vous du coiffeur

#### 1. Port (`application/ports/appointment_repository.py`)

Ajouter (miroir de `list_for_salon`, filtrant `hairdresser_id`) :

```
def list_for_hairdresser(
    self,
    hairdresser_id: uuid.UUID,
    date_from: datetime.date,
    date_to: datetime.date,
    statuses: tuple[str, ...] | None = None,
) -> tuple[Appointment, ...]:
    ...
```

Sémantique (docstring) : renvoie les RDV dont `hairdresser_id == :hairdresser_id` et dont
`appointment_date` est dans `[date_from, date_to]` (**inclusif**), avec leurs `BookedService`, triés
`(appointment_date, start_time)`. `statuses=None` ne filtre pas sur le statut (tous statuts) ; une
liste restreint. **Ne renvoie jamais** un RDV assigné à un autre coiffeur, un RDV non assigné
(`hairdresser_id IS NULL`), ni un RDV d'un autre salon — l'isolation « son planning » (§11.2) est
imposée **en SQL** (`WHERE hairdresser_id = :hairdresser_id`), en défense en profondeur du filtre
serveur.

#### 2. Adapter (`adapters/outbound/persistence/appointment_repository.py`)

Implémenter `list_for_hairdresser` en réutilisant `_to_domain`/`_load_services` et le patron de
`list_for_salon` :

```
stmt = select(models.Appointment).where(
    models.Appointment.hairdresser_id == hairdresser_id,
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

Note performance : aucun index dédié `hairdresser_id` n'existe (voir Open Questions) ; la lecture est
**bornée** (≤ 42 jours, un seul coiffeur) → volume faible au MVP. Un index additif est une
optimisation ultérieure éventuelle, non requise par l'AC.

#### 3. Application (`application/appointments.py`)

Cas d'usage **de lecture pure** (aucune écriture, aucun audit), miroir de `ListSalonAppointments` :

```
class ListAssignedAppointments:
    def __init__(self, appointment_repository: AppointmentRepository) -> None: ...
    def execute(
        self,
        hairdresser_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        return self._appointments.list_for_hairdresser(
            hairdresser_id, date_from, date_to, statuses
        )
```

Ajouter à `__all__`. (Le `hairdresser_id` est **imposé par l'adapter entrant** depuis le `Principal`,
jamais lu du corps ni du chemin — comme `client_id` pour `ListMyAppointments`.)

#### 4. Adapter entrant (HTTP) — `adapters/inbound/appointments.py`

Ajouter **une** route de lecture d'**appartenance** **protégée** :

- `GET /appointments/assigned` — **coiffeur** (`require_permission(APPOINTMENT_READ_ASSIGNED)`).
  **Pas** de `salon_id` dans le chemin, **pas** de `require_salon_scope` : c'est une route
  d'appartenance (patron `GET /appointments` client). Le `hairdresser_id` est **le `principal.id`**,
  jamais un champ soumis. Paramètres de requête :
  - `date_from: datetime.date` (**requis**), `date_to: datetime.date` (**requis**) — plage inclusive
    couvrant la période visible. **Borner** l'amplitude via `MAX_PLANNING_RANGE_DAYS` (42) → `422`
    au-delà (réutiliser la garde et le message de #26 ; `date_to < date_from` → `422`).
  - `status: list[AppointmentStatus] | None = None` (**optionnel, répétable**, alias `status`) —
    filtre par statut (valeur hors énumération → `422` Pydantic). `None` = tous statuts.
  - DI : `get_appointment_repository`. Réponse `200` `list[AppointmentResponse]` (schéma existant,
    réutilisant `_appointment_response`). Erreurs : `401` (jeton) ; `403` (rôle sans
    `APPOINTMENT_READ_ASSIGNED` — `CLIENT`, `MANAGER`, `ADMIN`) ; `422` (dates invalides / plage trop
    large / statut hors énumération). Docstring + `responses` OpenAPI (patron `GET /appointments` &
    route #26).
- **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`** (route **protégée**). Vérifier que
  `unprotected_routes(app)` reste vide (test existant). **Ordre des routes** : `/appointments/assigned`
  est un chemin **statique** distinct de `GET /appointments` et de `PATCH /appointments/{id}` — pas
  de collision de résolution.

> **Note de portée & tri.** Le serveur renvoie une **liste plate triée chronologiquement**, tous
> statuts confondus (sauf filtre) ; le **groupement par statut** et la **découpe jour/semaine/mois**
> restent un **concern d'affichage** porté par le front (domaine #26 réutilisé). La route reste
> générique et symétrique de la route gérant #26.

### (B) Surface de consultation du planning coiffeur — **décision de périmètre**

Le coiffeur n'a **aucune surface** aujourd'hui (le web est gérant/admin, le mobile est client). Trois
options ; **recommandation : Option 1** (à confirmer au step `plan`/`document`, cf. Open Questions).

#### Option 1 (recommandée) — nouvelle zone web `/coiffeur`

Ajouter une zone protégée dédiée au rôle `HAIRDRESSER`, réutilisant au maximum les patrons #14 et le
domaine de planning #26 :

1. **Règle de domaine** — `src/domain/auth/session.ts` : ajouter `canAccessCoiffeur(user)` (rôle
   `HAIRDRESSER` **et** statut `ACTIVE`), miroir de `canAccessGerant`. Test `auth-session.test.ts`.
2. **Cas d'usage de session** — `src/application/use-cases/require-hairdresser-session.ts` (patron
   `require-manager-session.ts`) : `getCurrentUser()` (→ `/auth/me`) puis `canAccessCoiffeur`.
   `SessionDecision` identique (`allow` | `unauthenticated` | `wrong-role` | `unavailable`). Test
   dédié.
3. **Layout / composition root** — `app/(coiffeur)/layout.tsx` (patron `app/(gerant)/layout.tsx`) :
   lit le cookie, exécute `requireHairdresserSession`, `redirect("/login")` si refus (motif non
   divulgué), rend un shell (réutiliser/paramétrer `DashboardShell`, navigation réduite : « Mon
   planning »).
4. **Page planning** — `app/(coiffeur)/coiffeur/planning/page.tsx` (Server Component, patron
   `gerant/planning/page.tsx`, **sans** l'étape « charger le salon » — le coiffeur n'a pas de salon à
   choisir) : période depuis `searchParams` (`view`, `date`, `status` ; défaut `view=day`,
   `date=todayIso()`), calcul `from`/`to` (domaine #26), appel **côté serveur**
   `appointmentGateway.listAssigned({ from, to, statuses })`, rendu du board.
5. **Gateway** — étendre `AppointmentGateway`/`http-appointment-gateway.ts` d'une méthode
   `listAssigned(query) -> ListAppointmentsResult` (patron `listForSalon`, URL `/appointments/
   assigned`, mêmes `params`/mappage HTTP, **jeton non loggé**). *(Alternative : un
   `hairdresser-appointment-gateway.ts` dédié — recommandé d'étendre l'existant pour éviter la
   duplication.)*
6. **UI** — réutiliser le **domaine** #26 tel quel ; rendre `planning-board.tsx` réutilisable en
   **variante lecture** (source de RDV en prop ; masquer les actions de statut — voir Non-Goals sur
   l'écriture coiffeur) plutôt que de dupliquer. Vue jour au minimum (cœur de la consultation),
   semaine/mois si le board est réutilisé.
7. **Redirection de connexion & racine** — ajuster `app/login` / `app/page.tsx` pour router un
   `HAIRDRESSER` authentifié vers `/coiffeur/planning` (et un `MANAGER` vers `/gerant`), sans « flash »
   de contenu privé.

> Coût : une **nouvelle zone authentifiée** (session, layout, page, gateway, redirection). Substantiel
> mais cohérent avec la livraison **backend + web** de #26 et le seul moyen de rendre « le coiffeur
> **consulte** » réellement visible.

#### Option 2 — backend seul (différer la surface)

Livrer uniquement **(A)** (endpoint + tests). L'AC d'**isolation** est techniquement satisfaite
(garantie d'autorisation vérifiable par tests), mais « le coiffeur consulte » n'est pas visible faute
de surface. Honnête et minimal ; à retenir seulement si l'effort de la zone web est jugé hors budget
de #27.

#### Option 3 — surface mobile

Non retenue : `app-mobile/` est **client** (pas de connexion coiffeur câblée, pas de zone employé) ;
le PRD réserve une « application coiffeur dédiée » à la **V2** (§21).

### Documentation & ADR

- **ADR — Planning personnel du coiffeur & lecture assignment-scopée** (numéro libre suivant :
  `docs/adr/` s'arrête à **0025** ; #26 n'a **pas** ajouté d'ADR → le prochain est **0026** —
  **vérifier** au step `document`). Acte : endpoint d'**appartenance** `GET /appointments/assigned`
  (`APPOINTMENT_READ_ASSIGNED` câblée pour la première fois, `hairdresser_id` imposé serveur, plage
  bornée, filtre statut) ; **séparation** gérant #26 / coiffeur #27 (routes distinctes, permissions
  distinctes) ; **surface coiffeur** retenue (Option 1/2) ; réutilisation du domaine de planning #26 ;
  **caveat écriture** (route de statut #25 salon-scopée → resserrement d'assignation requis avant
  toute action coiffeur) ; aucun nouveau schéma. Indexer dans `docs/adr/README.md`.
- **`backend/README.md`** : section « Planning personnel du coiffeur (lecture assignée) ».
- **`web-dashboard/README.md`** (si Option 1) : section « Zone coiffeur — Mon planning ».
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison
  (ne pas anticiper de comportement non implémenté — pas d'action de statut coiffeur, pas de temps
  réel, pas d'app mobile coiffeur).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).

## Affected Files / Packages / Modules

**Backend — à modifier :**
- `backend/coiflink_api/application/ports/appointment_repository.py` — `list_for_hairdresser`
  (Protocol).
- `backend/coiflink_api/adapters/outbound/persistence/appointment_repository.py` — implémentation
  `list_for_hairdresser`.
- `backend/coiflink_api/application/appointments.py` — `ListAssignedAppointments` (+ `__all__`).
- `backend/coiflink_api/adapters/inbound/appointments.py` — route `GET /appointments/assigned`
  (query `date_from`/`date_to`/`status`, garde de plage réutilisant `MAX_PLANNING_RANGE_DAYS`, DI,
  `require_permission(APPOINTMENT_READ_ASSIGNED)`, docstring/`responses`).
- `backend/tests/conftest.py` — étendre `FakeAppointmentRepository` (`list_for_hairdresser` : refiltre
  `hairdresser_id`, plage, statuts).

**Backend — à lire (contexte) :** `adapters/inbound/appointments.py`
(`GET /appointments` client & `GET /salons/{salon_id}/appointments` #26 : patrons directs,
`_appointment_response`, `_now`, `MAX_PLANNING_RANGE_DAYS`) ; `adapters/inbound/security.py`
(`require_permission`, `PUBLIC_ROUTE_PATHS`, `unprotected_routes`) ;
`application/appointments.py::ListSalonAppointments`/`ListMyAppointments` (patrons lecture) ;
`adapters/outbound/persistence/appointment_repository.py::list_for_salon`/`list_for_client` (patrons
SQL) ; `domain/permissions.py` (`APPOINTMENT_READ_ASSIGNED`) ; `domain/access.py`
(`can_access_appointment` — règle coiffeur) ; `models.py` (`Appointment.hairdresser_id`).

**Web — à créer (si Option 1) :**
- `web-dashboard/app/(coiffeur)/layout.tsx` — composition root de la zone coiffeur.
- `web-dashboard/app/(coiffeur)/coiffeur/planning/page.tsx` — Server Component (session → période →
  lecture → board).
- `web-dashboard/src/application/use-cases/require-hairdresser-session.ts` — garde de session
  coiffeur.

**Web — à modifier (si Option 1) :**
- `web-dashboard/src/domain/auth/session.ts` — `canAccessCoiffeur`.
- `web-dashboard/src/application/ports/appointment-gateway.ts` — `listAssigned`.
- `web-dashboard/src/adapters/api/http-appointment-gateway.ts` — implémentation `listAssigned`.
- `web-dashboard/src/adapters/ui/planning-board.tsx` — rendre réutilisable (source de RDV en prop,
  variante lecture).
- `web-dashboard/app/login/page.tsx` / `web-dashboard/app/page.tsx` — routage par rôle après
  connexion (`HAIRDRESSER` → `/coiffeur/planning`).

**Web — à lire (contexte) :** `app/(gerant)/layout.tsx`, `app/(gerant)/gerant/planning/page.tsx`,
`src/application/use-cases/require-manager-session.ts`, `src/domain/auth/session.ts`,
`src/domain/auth/role.ts`, `src/adapters/api/cookie-session-store.ts`,
`src/adapters/api/http-appointment-gateway.ts`, `src/domain/appointment/appointment.ts`,
`src/domain/appointment/planning-view.ts`, `src/adapters/ui/dashboard-shell.tsx`.

**Docs :** `docs/adr/00XX-*.md` (numéro à confirmer — vraisemblablement **0026**) +
`docs/adr/README.md`, `backend/README.md`, `web-dashboard/README.md` (si Option 1). **`prd-coiflink.md`
: ne pas modifier.** Récit `README.md` §6 : compléter au step `document`.

**Non touchés :** la matrice `domain/permissions.py` et les règles `domain/access.py` (déjà
suffisantes) ; le port `SalonScopeRepository` (#13/ADR-0016) ; la **machine à états** et les routes
d'écriture de statut #25 ; la route gérant #26 (non élargie) ; `app-mobile/`.

## API / Interface Changes

**Nouvelle route backend** (protégée, jamais publique, route d'**appartenance** coiffeur) :

- `GET /appointments/assigned` — **coiffeur** (`APPOINTMENT_READ_ASSIGNED`). Le `hairdresser_id` est
  **imposé serveur** (`principal.id`) — jamais un paramètre. Query : `date_from=YYYY-MM-DD`
  (**requis**), `date_to=YYYY-MM-DD` (**requis**, plage inclusive, amplitude bornée ≤ 42 j),
  `status=CONFIRMED&status=PENDING&…` (**optionnel, répétable** ; valeur hors énumération → `422`).
  Réponse `200` : `list[AppointmentResponse]` (schéma existant, triée par `date` puis `start_time`).
  Réponses : `200` ; `401` (jeton absent/expiré) ; `403` (rôle sans `APPOINTMENT_READ_ASSIGNED` —
  `CLIENT`/`MANAGER`/`ADMIN`) ; `422` (dates absentes/invalides, plage trop large, statut hors
  énumération). Documentation OpenAPI (docstring + `responses`).

**Réutilisé tel quel :** `AppointmentResponse`. **Aucune** modification des routes existantes (client
#21/#23/#24, gérant #25/#26). En particulier, `GET /salons/{salon_id}/appointments` (#26) **n'est pas
élargi** au coiffeur.

**Surface web (si Option 1)** : nouvelle zone `/coiffeur/planning` (Server Component + gateway
sortant `listAssigned` **interne**, côté serveur Next). Aucun nouvel endpoint BFF requis si la lecture
reste en Server Component (pas d'action de statut coiffeur dans #27 — voir Non-Goals).

## Data Model / Protocol Changes

**Aucune (requise par l'AC).** La lecture assignment-scopée s'appuie sur les colonnes
`hairdresser_id`, `appointment_date`, `start_time`, `status` (schéma #3). Aucune table, migration,
colonne ni contrainte n'est nécessaire. Le contrat de fil (`AppointmentResponse`) est **inchangé** ;
seuls de **nouveaux paramètres de requête** (`date_from`/`date_to`/`status`) sont introduits sur une
route nouvelle.

**Optionnel (optimisation, non requis)** : un index btree `ix_appointments_hairdresser_id
(hairdresser_id, appointment_date)` accélérerait la lecture à gros volume (la contrainte GiST
`ex_appointments_hairdresser_slot` ne couvre pas un `hairdresser_id =` btree). Additif ; à mesurer et
décider (Open Questions). S'il est retenu, il devient une **migration Alembic** (round-trip CI, #3).

## Security & Privacy Considerations

- **Isolation « il ne voit que les siens » (§11.2)** — cœur de l'AC. La route est une route
  d'**appartenance** : le `hairdresser_id` vient **du `Principal`** (`principal.id`), **jamais** d'un
  champ soumis ni du chemin (anti-élévation §11.2) ; le dépôt refiltre `hairdresser_id` en SQL
  (`list_for_hairdresser`) — défense en profondeur. Un coiffeur ne lit **jamais** un RDV d'un
  collègue, un RDV non assigné (`hairdresser_id IS NULL`) ni un RDV d'un autre salon. Aucun oracle
  d'existence : la réponse est simplement la liste de **ses** RDV (vide si aucun).
- **Deny-by-default (ADR-0015)** : la route exige `APPOINTMENT_READ_ASSIGNED` (détenue par le seul
  `HAIRDRESSER`). Un `CLIENT`, un `MANAGER` et un `ADMIN` reçoivent un `403` **générique**. **Aucun**
  ajout à `PUBLIC_ROUTE_PATHS` ; `unprotected_routes(app)` **reste vide** (invariant testé). La
  lecture ne s'appuie sur **aucun** champ soumis pour autoriser.
- **⚠ Frontière lecture/écriture (à ne pas franchir dans #27)** : la route de statut #25
  (`POST /salons/{salon_id}/appointments/{id}/status`) est **salon-scopée**, or un `HAIRDRESSER`
  détient `APPOINTMENT_UPDATE_STATUS` **et** une portée salon → il pourrait piloter le statut d'un RDV
  **non assigné**. L'AC de #27 portant sur la **lecture**, elle est satisfaite ; mais **ne pas**
  exposer d'action de statut au coiffeur tant que #25 n'impose pas, côté écriture, `hairdresser_id ==
  principal.id` quand l'acteur est un coiffeur (suivi — voir Open Questions). Ne pas **impliquer** que
  cette isolation d'écriture existe.
- **Jeton jamais exposé (#14, §11.3)** : si une surface web est livrée (Option 1), toute lecture
  backend passe **côté serveur Next** avec le jeton lu du cookie `httpOnly` — **jamais** transmis au
  navigateur, **jamais** journalisé. Le gateway ne loggue ni `Authorization` ni PII.
- **Confidentialité de l'affichage (§11.3)** : `AppointmentResponse` porte des UUID (`client_id`) et
  des données des **propres** RDV du coiffeur. L'enrichissement nom/téléphone client est **hors
  périmètre** (#28+) ; au MVP, libellé neutre (créneau + prestation), pas de PII non maîtrisée dans
  l'UI/les logs.
- **Budget de coût (§12)** : la plage est **bornée** (≤ 42 j, réutilisant `MAX_PLANNING_RANGE_DAYS`)
  et la lecture porte sur un **seul** coiffeur — volume faible. Chargement des prestations par RDV
  (`_load_services` en boucle) borné par la plage ; index dédié optionnel (Open Questions). Lecture
  bien en deçà du budget API (< 3 s).
- **Résidence/hébergement** : inchangés (ADR-0011). Aucun secret manipulé ni journalisé.
- **Erreurs neutres** : les refus RBAC restent les `401`/`403` **constants** de `security.py` ; côté
  front, motifs génériques (`forbidden`/`unauthenticated`/`invalid`/`unavailable`).

## Testing Plan

Test gate : `pytest` (backend) + `vitest run` (web, si Option 1). Convention backend : tests
**Postgres** *skip proprement* sans `DATABASE_URL` ; en unitaire, **fakes** injectés via
`app.dependency_overrides`. Les tests existants restent **verts** (extensions **additives**).

**Backend :**
- **Unit — cas d'usage (fakes)** `tests/test_appointment_usecases.py` (étendre) :
  `ListAssignedAppointments` renvoie les RDV **du coiffeur** dans la plage, triés
  `(date, start_time)` ; applique le filtre `statuses` (sous-ensemble) ; renvoie **vide** hors plage ;
  ne renvoie **jamais** un RDV d'un autre coiffeur, ni un RDV non assigné (le fake refiltre
  `hairdresser_id`).
- **Intégration/HTTP** `tests/test_appointment_api.py` (étendre, `TestClient` + fakes) :
  `GET /appointments/assigned` : `200` liste triée pour une plage ; filtre `status` (répété) reflété ;
  `hairdresser_id` **jamais** lu d'un paramètre (le résultat reste celui du `Principal`) ; `422` si
  `date_from`/`date_to` absents/mal formés, plage > 42 j, `date_to < date_from`, ou `status` hors
  énumération ; `403` pour **`CLIENT`** et **`MANAGER`** (sans `APPOINTMENT_READ_ASSIGNED`) ; `401`
  sans jeton. **Invariant deny-by-default** : `unprotected_routes(app)` reste **vide** (sans ajouter
  le chemin à `PUBLIC_ROUTE_PATHS`).
- **Intégration Postgres** `tests/test_hairdresser_planning_e2e.py` (nouveau, skip sans
  `DATABASE_URL`) : insérer des RDV multi-coiffeurs / multi-salons / multi-statuts, dont des RDV **non
  assignés** (`hairdresser_id IS NULL`) ; vérifier que la lecture d'un coiffeur **ne renvoie que**
  ses RDV assignés, dans la plage et l'ordre attendus, filtre statut inclus — **jamais** ceux d'un
  autre coiffeur, d'un autre salon, ou non assignés.
- **Matrice RBAC** `tests/test_permissions.py` : `HAIRDRESSER` détient `APPOINTMENT_READ_ASSIGNED`,
  les autres non (déjà couvert par la matrice ; ré-affirmer si touché — **aucune** nouvelle permission
  requise).

**Web (Vitest — si Option 1) :**
- **Domaine session** `test/auth-session.test.ts` (étendre) : `canAccessCoiffeur` (vrai pour
  `HAIRDRESSER`+`ACTIVE` ; faux pour tout autre rôle ou statut non `ACTIVE`).
- **Garde de session** `test/require-hairdresser-session.test.ts` (nouveau, patron
  `require-manager-session.test.ts`) : `allow`/`unauthenticated`/`wrong-role`/`unavailable`.
- **Gateway HTTP** `test/http-appointment-gateway.test.ts` (étendre) : `listAssigned` mappe
  `200`→liste, `401/403/422/503`→motifs ; construit l'URL `/appointments/assigned` avec
  `date_from`/`date_to`/`status` (encodage) ; **ne loggue jamais** le jeton.
- **Réutilisation domaine** : `test/planning-view.test.ts` / `test/appointment-domain.test.ts`
  restent **verts** (domaine #26 réutilisé sans modification ; ajouter au besoin un cas source
  « assignés »).
- **Board réutilisable** : si `planning-board.tsx` est refactoré en variante lecture, ajouter/adapter
  les tests de rendu (groupement par statut, absence d'actions de statut coiffeur, états
  vide/erreur).

**Documentation** : revue que `backend/README.md` (et `web-dashboard/README.md` si Option 1) décrivent
la lecture assignment-scopée, la frontière avec #26 (gérant) et le caveat écriture #25.

## Documentation Updates

- **`docs/adr/00XX-*.md`** (nouveau — **confirmer le numéro** au step `document` ; `docs/adr/`
  s'arrête à `0025`, #26 n'a pas ajouté d'ADR → prochain **0026**) + entrée **`docs/adr/README.md`** :
  route d'appartenance `GET /appointments/assigned` (`APPOINTMENT_READ_ASSIGNED` câblée pour la
  première fois, `hairdresser_id` imposé serveur, plage bornée + filtre statut), séparation
  gérant #26 / coiffeur #27, surface coiffeur retenue (Option 1/2), réutilisation du domaine de
  planning #26, **caveat** écriture #25 (resserrement d'assignation à faire avant toute action
  coiffeur), backend sans nouveau schéma (index optionnel documenté).
- **`backend/README.md`** : section « Planning personnel du coiffeur (lecture assignée) » (route,
  paramètres, portée par `hairdresser_id`, filtre, ordre, prérequis Postgres des e2e).
- **`web-dashboard/README.md`** (si Option 1) : section « Zone coiffeur — Mon planning » (garde de
  session, vues réutilisées, jeton non exposé).
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison —
  **ne pas anticiper** de comportement non implémenté (pas d'action de statut coiffeur, pas de temps
  réel, pas d'app mobile coiffeur).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstring + `responses` sur la nouvelle route (généré par FastAPI).

## Risks and Open Questions

- **Surface de consultation du coiffeur (décision structurante).** Aucune surface coiffeur n'existe
  (web = gérant/admin, mobile = client) et le PRD ne prévoit pas d'interface coiffeur au MVP (§7 ;
  app coiffeur = V2 §21). *Recommandation : **Option 1** — nouvelle zone web `/coiffeur` réutilisant
  le domaine de planning #26.* Alternatives : **Option 2** (backend seul, différer la surface) si le
  budget de #27 (Should/M) ne couvre pas une zone authentifiée ; **Option 3** (mobile) écartée.
  **À confirmer** au step `plan`.
- **Écriture de statut par le coiffeur (frontière de sécurité).** PRD §5 liste « confirmer une
  prestation / mettre à jour un statut » côté coiffeur, mais la route #25 est **salon-scopée** (un
  coiffeur pourrait écrire sur un RDV non assigné). *Recommandation : **hors périmètre #27** (AC =
  lecture) ; ne pas exposer d'action de statut coiffeur tant que #25 n'impose pas
  `hairdresser_id == principal.id` pour un acteur `HAIRDRESSER`.* Suivi à créer si l'écriture coiffeur
  est souhaitée. **À noter / confirmer.**
- **Contrat de la route : d'appartenance vs salon-scopée.** *Recommandation : route d'**appartenance**
  `GET /appointments/assigned` (patron `GET /appointments` client ; `hairdresser_id` imposé serveur —
  isolation maximale, le coiffeur ne peut même pas nommer un salon).* Alternative : élargir la route
  #26 via `require_any_permission(APPOINTMENT_READ_SALON, APPOINTMENT_READ_ASSIGNED)` +
  `require_salon_scope` puis re-filtrer `hairdresser_id` selon le rôle dans le handler — **plus
  complexe**, conflate deux rôles, et fait dépendre la forme des données du rôle. **Non recommandée.**
  **À confirmer** (nom du chemin : `/appointments/assigned`).
- **Contrat de la plage de dates.** *Recommandation : `date_from`/`date_to` bornés (≤ 42 j) réutilisant
  `MAX_PLANNING_RANGE_DAYS` (#26), déduction de plage jour/semaine/mois côté front (domaine #26).*
  Cohérent avec la route gérant. **À confirmer** (bornes, inclusivité).
- **Multi-salon d'un coiffeur.** Un compte peut être membre de plusieurs salons (`salon_members`) et
  se voir assigner des RDV dans chacun. La route d'appartenance (`hairdresser_id = principal.id`)
  renvoie **tous** ses RDV assignés, tous salons confondus — conforme à « il ne voit que les siens ».
  Si un jour un cloisonnement par salon est voulu, un `salon_id` **optionnel** en query pourra être
  ajouté (additif). **À noter** (non requis au MVP).
- **Index de performance `hairdresser_id`.** Absent aujourd'hui ; la lecture est bornée et
  mono-coiffeur (volume faible au MVP). *Recommandation : mesurer ; index additif (migration) si
  nécessaire, hors AC.* **À noter.**
- **Réutilisation vs duplication du board.** *Recommandation : rendre `planning-board.tsx`
  réutilisable (source de RDV en prop, variante lecture) plutôt que dupliquer.* Risque de régression
  sur la vue gérant #26 : couvrir par tests. **À noter.**
- **Fuseau horaire du « jour courant ».** Réutiliser `todayIso()` / l'arithmétique UTC+0 du domaine
  #26 (pas de `new Date()` caché). **À noter** (pas de multi-fuseau au MVP).
- **Numéro d'ADR.** `docs/adr/` s'arrête à `0025` ; #26 n'a pas ajouté d'ADR distinct → le prochain
  libre est **0026** — **vérifier** au step `document`.

## Implementation Checklist

1. **Lire** : côté backend — `adapters/inbound/appointments.py` (`GET /appointments` client &
   `GET /salons/{salon_id}/appointments` #26, `_appointment_response`, `_now`,
   `MAX_PLANNING_RANGE_DAYS`) ; `adapters/inbound/security.py` (`require_permission`,
   `PUBLIC_ROUTE_PATHS`, `unprotected_routes`) ; `application/appointments.py`
   (`ListSalonAppointments`/`ListMyAppointments`) ;
   `adapters/outbound/persistence/appointment_repository.py` (`list_for_salon`/`list_for_client`) ;
   `domain/permissions.py`, `domain/access.py`, `models.py`. Côté web —
   `app/(gerant)/layout.tsx`, `app/(gerant)/gerant/planning/page.tsx`,
   `require-manager-session.ts`, `domain/auth/session.ts`, `domain/auth/role.ts`,
   `http-appointment-gateway.ts`, `domain/appointment/*`.
2. **Trancher les Open Questions structurantes** — surface coiffeur (Option 1/2), contrat de route
   (appartenance), plage, écriture coiffeur hors périmètre — et les acter dans l'ADR
   (+ `docs/adr/README.md`).
3. **Backend — port** (`application/ports/appointment_repository.py`) :
   `list_for_hairdresser(hairdresser_id, date_from, date_to, statuses?)`.
4. **Backend — adapter** (`SqlAppointmentRepository.list_for_hairdresser`) :
   `select/where(hairdresser_id, plage, statuts?)/order_by(date, start_time)` réutilisant
   `_to_domain`/`_load_services`.
5. **Backend — cas d'usage** (`application/appointments.py`) : `ListAssignedAppointments` (lecture
   pure) + `__all__`.
6. **Backend — route** (`adapters/inbound/appointments.py`) : `GET /appointments/assigned`
   (`require_permission(APPOINTMENT_READ_ASSIGNED)`, `hairdresser_id = principal.id`, query
   `date_from`/`date_to` requis + plage bornée ≤ 42 j → `422`, `status` répété optionnel, DI,
   docstring/`responses`). **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`.**
7. **Backend — fakes** : étendre `FakeAppointmentRepository.list_for_hairdresser` (refiltre
   `hairdresser_id`, plage, statuts) dans `conftest.py`.
8. **Backend — tests** : cas d'usage (fakes), API (`TestClient` : portée par `hairdresser_id`, filtre,
   `403` pour `CLIENT`/`MANAGER`, `422`, deny-by-default), Postgres e2e (isolation
   inter-coiffeurs/inter-salons, RDV non assignés exclus) — **skip** sans `DATABASE_URL`.
9. **Web (si Option 1) — session** : `canAccessCoiffeur` (`session.ts`) ;
   `require-hairdresser-session.ts` ; tests associés.
10. **Web (si Option 1) — gateway** : `listAssigned` (`appointment-gateway.ts` +
    `http-appointment-gateway.ts`, URL `/appointments/assigned`, mappage HTTP, **jeton non loggé**).
11. **Web (si Option 1) — composition root** : `app/(coiffeur)/layout.tsx` (garde coiffeur) ;
    `app/(coiffeur)/coiffeur/planning/page.tsx` (session → période depuis searchParams →
    `listAssigned` → board) ; routage par rôle après connexion (`HAIRDRESSER` → `/coiffeur/planning`).
12. **Web (si Option 1) — UI** : réutiliser le domaine #26 ; rendre `planning-board.tsx` réutilisable
    (variante lecture, sans actions de statut coiffeur) ; vue jour au minimum, semaine/mois par
    réutilisation ; états vide/erreur.
13. **Web (si Option 1) — tests** : `auth-session`, `require-hairdresser-session`,
    `http-appointment-gateway` (`listAssigned`), rendu du board réutilisé.
14. **Documentation** : ADR (numéro à confirmer, ~0026) + `docs/adr/README.md` ; section
    `backend/README.md` (et `web-dashboard/README.md` si Option 1).
15. **Garde-fous** : `pytest` **et** `vitest run` (test gate agrégé) au vert ; aucun secret/PII
    journalisé ; jeton **jamais** exposé au navigateur (Server Component + cookie httpOnly) ; lecture
    **assignment-scopée** (`hairdresser_id` du `Principal` + refiltre SQL) ; plage **bornée** ;
    `unprotected_routes(app)` **vide** ; route gérant #26 **non élargie** ; **aucune** action de statut
    coiffeur exposée (frontière écriture #25) ; **aucune** notification ni CA fabriqués ; **aucune**
    signature IA dans le code/commits/PR.
