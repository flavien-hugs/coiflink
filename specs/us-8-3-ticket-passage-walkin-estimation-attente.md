# Ticket de passage walk-in & estimation d'attente (US-8.3, #157)

> Spécification de planification pour l'issue GitHub **#157 — US-8.3 : Ticket de passage walk-in &
> estimation d'attente** (`feature` · Must · Effort L · jalon **M7 — Borne client (terminal
> libre-service)**, Épic 8 · PRD §17 « Borne Intelligente d'Accueil »). **Dépend de : #155
> (rôle/auth `TERMINAL`), #156 (identification téléphone / création walk-in).**
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> **Rafraîchissement de la spec canonique.** Une première spec de planification existe déjà sous
> [`specs/borne-ticket-file-attente-walkin.md`](./borne-ticket-file-attente-walkin.md) (référencée
> par le corps de l'issue). Elle a été rédigée **avant** le merge de #155/#156 et hédge donc sur
> plusieurs points désormais tranchés dans le code (`b9c5388` #155, `4320171` #156). Ce document en
> reprend la conception — encore valide — mais **verrouille** les hypothèses vérifiées par lecture
> directe du dépôt à l'état du commit `4320171` : nom canonique de la permission, numéro de
> migration réel, forme exacte de la garde `TERMINAL`, projection PII de #156. En cas de divergence,
> **ce document fait foi** pour l'implémentation de #157 ; l'ancien reste la référence historique.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon M7 promeut le parcours « client sans rendez-vous » du PRD §17 au rang de fonctionnalité
livrable, limité volontairement au walk-in (cf. bloc M7 de `BACKLOG.md`). Les deux briques amont sont
livrées :

- **#155** dote la borne d'une identité de terminal (rôle `TERMINAL`, compte de service scopé à un
  salon, JWT courts via `POST /auth/terminal/login`) et de ses permissions **minimales**, dont
  `QUEUE_TICKET_CREATE` déjà déclarée dans la matrice `ROLE_PERMISSIONS` (vérifié :
  `coiflink_api/domain/permissions.py:79` et `:154`).
- **#156** donne à la borne le moyen de savoir **qui** se présente : `POST
  /salons/{salon_id}/terminal/customers/lookup` (recherche par téléphone) et `POST
  /salons/{salon_id}/terminal/customers` (création walk-in), tous deux ne renvoyant qu'une projection
  minimale `{customer_id, first_name}` (vérifié : `coiflink_api/adapters/inbound/terminal_customers.py`).

Il manque encore la **pièce centrale** du parcours : **quoi faire** de ce client une fois identifié —
lui délivrer un **numéro de passage**, une **estimation d'attente**, et le faire apparaître dans la
file du personnel pour qu'il soit pris en charge. C'est l'objet de #157.

État du dépôt vérifié par lecture directe (commit `4320171`) :

- **Aucune notion de « file d'attente walk-in » n'existe.** La seule « file d'attente » livrée
  (#150/#152) est un **outil de pointage sur rendez-vous déjà planifiés** :
  `coiflink_api/domain/queue.py` ne dérive un statut (`waiting`/`in_progress`/`completed`/`paid`) que
  pour des `Appointment` déjà `CONFIRMED`/`COMPLETED` — jamais `PENDING`, jamais un client sans RDV.
  Recherche exhaustive négative sur `ticket`, `estimated_wait`, `queue_number` : aucune table,
  colonne ni calcul d'attente n'existe.
- **`Appointment.client_id` est `NOT NULL` (FK `users`).** Un walk-in identifié par #156 obtient une
  `CustomerProfile` avec `user_id = NULL` **dans le cas général** (pas de compte, pas de mot de
  passe) ; l'entité de domaine `Customer` **n'expose même pas** `user_id` (anti-oracle ADR-0026). Un
  ticket walk-in ne peut donc **pas**, dans le cas général, devenir une ligne `appointments` sans
  soit exiger un compte (contradiction avec le principe du walk-in), soit assouplir `client_id` en
  base (changement de schéma hors périmètre). C'est le fait le plus structurant : il détermine la
  forme du « pont » vers la file gérant.
- **Le seul générateur de compteur séquentiel-par-salon du dépôt est le `receipt_number` des
  paiements** (#154, ADR-0040), directement réutilisable comme patron : `SqlPaymentRepository.create`
  (`coiflink_api/adapters/outbound/persistence/payment_repository.py:67-89`) exécute
  `SELECT pg_advisory_xact_lock(hashtext(:salon_id))` puis `SELECT COALESCE(MAX(receipt_number),0)+1`
  dans la **même** transaction que l'`INSERT` — « pas de nouvelle table de compteur, pas de nouvelle
  frontière de transaction ». #157 décline ce patron avec une clé de verrou plus fine (salon **et**
  jour).
- **`Payment` sait déjà exister sans `Appointment`** (`payments.appointment_id`/`client_id`
  nullables) : encaisser une prestation walk-in servie ne nécessite **aucune** ligne `appointments`
  ni aucun code d'encaissement nouveau. Ce n'est **pas** un livrable de #157 (aucun `ticket_id` sur
  `Payment`), mais cela retire une inquiétude : le jalon n'a pas besoin de résoudre la facturation
  walk-in pour être cohérent.
- **`GET /salons/{salon_id}/queue`** (`coiflink_api/adapters/inbound/appointments.py:1235-1272`,
  gardé `require_salon_scope` + `require_permission(APPOINTMENT_READ_SALON)`) rend aujourd'hui
  **exclusivement** `list[QueueEntryResponse]` issu de `ListSalonQueue(appointments, payments)`.
  C'est le seul écran « file d'attente » du dépôt
  (`web-dashboard/app/(gerant)/gerant/file-attente/page.tsx` + `queue-board.tsx`) — celui que le
  critère d'acceptation « il apparaît dans la file gérant existante » vise.

## Goals

- **Domaine `QueueTicket` indépendant, migration additive dédiée.** Nouvelle entité de domaine +
  nouvelle table `queue_tickets` (+ jonction `queue_ticket_services`), **sans aucune** modification
  de `appointments`/`services`/`customer_profiles`.
- **Numérotation séquentielle par salon et par jour civil, sûre en concurrence.** `ticket_number`
  redémarre à 1 chaque jour civil du salon (fuseau `Africa/Abidjan`), garanti unique par un index
  base **et** protégé d'une course par verrou consultatif transactionnel (patron ADR-0040, clé
  salon+jour).
- **Endpoint « rejoindre la file »**, réservé au rôle `TERMINAL` (#155) : crée un ticket `waiting`,
  retourne `ticket_number`, `estimated_wait_minutes`, l'heure d'émission — la borne peut imprimer
  immédiatement (préalable direct de #160).
- **Formule V1 d'ETA explicite et bornée**, assumée heuristique perfectible : position dans la file
  des tickets `waiting` × durée moyenne des prestations demandées par les tickets actifs
  (`waiting` + `in_progress`) ÷ nombre de coiffeuses `ACTIVE` du salon — avec filets pour les cas
  dégénérés (aucune coiffeuse active, file vide, aucune donnée de durée).
- **Prise en charge par une coiffeuse / le gérant** : cas d'usage qui assigne une coiffeuse à un
  ticket `waiting` et le fait passer `in_progress`, en miroir des préconditions déjà établies par
  #150 (coiffeuse requise avant démarrage) — sans dupliquer la persistance `appointments`.
- **Visibilité gérant sans écriture dans `appointments`.** La réponse de `GET
  /salons/{salon_id}/queue` **évolue** vers un objet à deux clés `{appointments, walk_in_tickets}`,
  satisfaisant « apparaît dans la file gérant existante une fois pris en charge » **sans jamais**
  créer de ligne `appointments` fictive.
- **Aucune régression sur la file des rendez-vous planifiés** : les entrées `QueueEntryResponse`
  existantes sont reprises **champ à champ** sous la clé `appointments` ; le passage de `list[...]`
  à l'objet à deux clés est une rupture de forme mineure et assumée, le consommateur unique
  (`queue-board.tsx`) étant mis à jour dans la même PR.
- **Cycle de vie complet du ticket** : `waiting → called → in_progress → done`, plus `expired`
  (jamais pris en charge) — statuts fermés, dérivés d'aucune autre table.

## Non-Goals

Rappel du périmètre M7 (cf. `BACKLOG.md`) — restent **hors scope de tout M7**, pas seulement de #157 :
check-in d'un RDV existant depuis la borne, identification par QR code / code de réservation,
affichage temps réel des coiffeurs disponibles **avant** affectation, paiement autonome sur la borne.

Spécifiquement hors scope de **#157** :

- **Le rôle `TERMINAL`, son credential, sa garde de portée.** #157 **consomme** ce qui est livré par
  #155 (`require_salon_scope` + `require_permission(Permission.QUEUE_TICKET_CREATE)`) ; il ne le
  redéfinit pas.
- **L'identification téléphone / création de fiche walk-in.** #157 **consomme** le `customer_id`
  déjà résolu par #156 (porté par `customer_profile_id`, nullable) ; il n'ajoute ni ne modifie
  `lookup`/`create` walk-in.
- **Toute UI.** Écrans borne (#159) et impression thermique (#160) sont des **consommateurs** de
  l'endpoint « rejoindre la file » et du cycle de statuts définis ici ; aucun widget Flutter n'est
  livré par #157.
- **Facturation liée au ticket.** Aucun champ `ticket_id` sur `Payment` ; l'encaissement d'une
  prestation walk-in servie reste un encaissement `service_id`-only classique (déjà possible
  aujourd'hui). Un lien explicite paiement ↔ ticket est un suivi potentiel, pas un livrable.
- **Notifications au client walk-in** (SMS/WhatsApp). M7 assume un ticket **papier** (#160) — cohérent
  avec l'ADR-0006 (fan-out différé).
- **Historique / statistiques des tickets** (attente réelle vs estimée, taux d'abandon). La table
  persistée le permettra plus tard ; aucun écran ni agrégat n'est livré ici.
- **Affinage de l'ETA au-delà de la V1** (données historiques, durée par coiffeuse, pondération par
  prestation) — explicitement heuristique V1 assumée perfectible.
- **Modification de `ROLE_PERMISSIONS` pour `CLIENT`/`HAIRDRESSER`/`MANAGER`/`ADMIN`.** La permission
  `TERMINAL` (`QUEUE_TICKET_CREATE`) **existe déjà** (#155). Pour la prise en charge (start/complete),
  la réutilisation de `APPOINTMENT_UPDATE_STATUS` (déjà détenue par `MANAGER`, et par le coiffeur sur
  son planning) est proposée — aucun nouveau droit à créer (voir *Risks*).
- **Expiration automatique planifiée** (job cron) : le dépôt n'a aucun ordonnanceur ; l'`expired` est
  un statut cible **atteignable** mais non déclenché automatiquement par #157 (voir *Risks*).

## Relevant Repository Context

### Stack & architecture (figées par les ADR, inchangées par #157)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Journal d'audit | Table `audit_logs` + port `AuditLog`, entrées **neutres** | [0019](../docs/adr/0019-journalisation-audit-et-prestations.md) |
| Numérotation séquentielle par salon | verrou consultatif transactionnel + `MAX+1`, sans table de compteur | [0040](../docs/adr/0040-impression-recu-encaissement-gerant.md) |
| Authentification borne terminal | rôle `TERMINAL`, device credential, JWT courts, révocation à la requête suivante | [0041](../docs/adr/0041-authentification-borne-kiosque.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0041** (livrée avec #155). #157 introduit **ADR-0042**
(`docs/adr/0042-file-attente-walkin-queue-ticket.md`), committée avec son implémentation — cette spec
en constitue la matière première. #161 (US-8.7) vérifie la présence des deux ADR et met à jour l'index
`docs/adr/README.md` en fin de jalon.

### Faits verrouillés par le merge de #155/#156 (ne plus hédger)

| Point | Ancienne hypothèse | État vérifié (commit `4320171`) |
| --- | --- | --- |
| Permission terminal « rejoindre la file » | nom à confirmer | **`Permission.QUEUE_TICKET_CREATE`** existe (`domain/permissions.py:79`), détenue **exactement** par `Role.TERMINAL` (`:150-155`) |
| Garde d'une route terminal salon-scopée | forme à confirmer | `require_salon_scope` (portée device→salon, `salon_id` lu du **chemin**) **+** `require_permission(...)`, deux dépendances résolvant le **même** `Principal` (patron `terminal_customers.py:247-250`, `308-311`) |
| Dernière migration | inconnue | **`0013_kiosk_role.py`** est la tête → nouvelle migration **`0014`**, `down_revision = "0013"` |
| Projection PII walk-in de #156 | à aligner | `lookup`/`create` renvoient **`{customer_id, first_name}`** uniquement (`terminal_customers.py`) — le prénom seul est la PII autorisée à l'écran ; `walk_in_tickets` s'y aligne |
| `GET .../queue` actuel | `list[QueueEntryResponse]` | confirmé (`appointments.py:1236`, `1271-1272` : `ListSalonQueue(appointments, payments).execute(...)`) |

### File d'attente existante (#150/#152) — à ne pas confondre

- `coiflink_api/domain/queue.py` : `QueueStatus` (`waiting`/`in_progress`/`completed`/`paid`),
  `QUEUE_APPOINTMENT_STATUSES = (CONFIRMED, COMPLETED)`, `derive_queue_status` — dérive **toujours**
  d'un `Appointment` réel ; rien ne connaît de numéro de passage.
- `coiflink_api/application/queue.py` : `MarkAppointmentArrived`, `StartAppointmentService`
  (préconditions `arrived_at`/`hairdresser_id`, erreurs
  `AppointmentArrivalRequired`/`AppointmentHairdresserRequired`), `ListSalonQueue` (compose
  `AppointmentRepository.list_queue_details` + `PaymentRepository.list_paid_appointment_ids`).
- `coiflink_api/adapters/inbound/appointments.py:289-304` : `QueueEntryResponse` (`appointment_id`,
  `client_name`, `service_names`, `hairdresser_id`/`name`, `start_time`/`end_time`, `status`,
  `queue_status`, `arrived_at`, `started_at`) — **aucun** champ numéro/position/ETA.
- `coiflink_api/adapters/inbound/appointments.py:1235-1272` : route `GET /salons/{salon_id}/queue`,
  paramètre `day` optionnel (défaut `_today()`, fuseau `Africa/Abidjan`).
- `web-dashboard/src/adapters/ui/queue-board.tsx` : consommateur **unique** du contrat.

### Modèle Appointment/Payment pertinent pour le « pont »

- `coiflink_api/adapters/outbound/persistence/models.py` (`Appointment`) : `client_id` **`NOT NULL`**
  (FK `users`, `RESTRICT`), `hairdresser_id` **nullable**,
  `appointment_date`/`start_time`/`end_time` **requis** (colonne générée `slot` — exclusion
  anti-double-réservation). `hairdresser_id` référence **`users.id`** (identifiant de **compte**,
  appartenance salon vérifiée **applicativement**, jamais par la FK).
- `Payment` : `appointment_id`/`client_id` **nullables** — encaissement comptoir sans RDV ni compte
  déjà exploitable.
- `mark_arrived`/`mark_started` : `UPDATE ... WHERE status = 'CONFIRMED'` — condition qui n'existera
  **jamais** pour un ticket walk-in (aucune ligne `appointments` à mettre à jour).

### Dénominateurs de l'ETA (déjà présents)

- `coiflink_api/domain/service.py` (`Service.duration_minutes`, > 0, ≤ 24 h) — source de la « durée
  moyenne des prestations demandées ».
- `coiflink_api/adapters/outbound/persistence/salon_catalog_repository.py` :
  `list_active_hairdressers(salon_id)` (filtre `salon_members.role = HAIRDRESSER AND status =
  ACTIVE`), déjà consommé par le catalogue #150. Réutilisable **tel quel** comme dénominateur
  « nombre de coiffeuses actives » — aucun nouveau calcul d'effectif.

### CustomerProfile (consommé, jamais modifié)

- `models.py` (`CustomerProfile`) : `id`, `salon_id`, `user_id` (nullable), `full_name`, `phone`
  (nullable), unicité **partielle par salon** `(salon_id, phone) WHERE phone IS NOT NULL`.
- `coiflink_api/domain/customer.py` (`Customer`) : **n'expose pas** `user_id` (anti-oracle ADR-0026).
  `QueueTicket.customer_profile_id` référence la **fiche**, jamais un compte. #157 ne dépend que de
  `find_by_id` (existant) ; il ne touche pas `find_by_phone`/`create` (propriété de #156).

## Proposed Implementation

### (A) Domaine `QueueTicket` — entité, validation

**Nouveau fichier `backend/coiflink_api/domain/queue_ticket.py`** (pur, aucune I/O) :

```python
QueueTicketStatus = Literal["waiting", "called", "in_progress", "done", "expired"]
QUEUE_TICKET_STATUSES: tuple[QueueTicketStatus, ...] = (
    "waiting", "called", "in_progress", "done", "expired",
)
# Transitions fermées (miroir du style AppointmentStatus) :
#   waiting -> called -> in_progress -> done
#   waiting -> expired   (jamais pris en charge, purge de fin de journée)
#   called  -> expired   (appelé mais jamais présenté)

@dataclass(frozen=True)
class QueueTicketToCreate:
    salon_id: uuid.UUID
    customer_profile_id: uuid.UUID | None   # None = ticket anonyme (voir Open Questions)
    service_ids: tuple[uuid.UUID, ...]      # >= 1, validé avant écriture

@dataclass(frozen=True)
class QueueTicket:
    id: uuid.UUID
    salon_id: uuid.UUID
    ticket_number: int
    issued_date: datetime.date              # jour civil salon (SALON_TIMEZONE), scope du compteur
    customer_profile_id: uuid.UUID | None
    service_ids: tuple[uuid.UUID, ...]
    status: QueueTicketStatus
    hairdresser_id: uuid.UUID | None        # posé uniquement à la prise en charge
    estimated_wait_minutes: int             # figé à l'émission, jamais recalculé a posteriori
    created_at: datetime.datetime
    called_at: datetime.datetime | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
```

- `service_ids` : au moins une prestation requise (`InvalidQueueTicketServices` sinon), miroir de
  `AppointmentServiceRequired`.
- `estimated_wait_minutes` est **calculé une fois à l'émission** (par le cas d'usage, §D) et stocké
  tel quel — **pas** de recalcul dynamique en lecture : le ticket affiche une estimation **stable**,
  cohérente avec ce qui a été imprimé (#160), même si la file évolue ensuite.
- `called_at`/`started_at`/`completed_at` sont des horodatages **distincts** du `status` (esprit
  `arrived_at`/`started_at` d'`Appointment`), volontairement **non partagés** avec cette table (§C).

**Machine à états — fonction pure de transition** : une table de vérité fermée (miroir du test de
`AppointmentStatus`) ; toute transition hors table lève `InvalidQueueTicketTransition`.

**Nouvelles erreurs (`domain/errors.py`)**, groupées à la suite de `AppointmentHairdresserRequired` :

- `InvalidQueueTicketServices` — `service_ids` vide, ou contient une prestation inactive/hors salon.
- `QueueTicketNotFound` — ticket inexistant **ou** hors salon (indiscernables, §11.2, miroir
  `AppointmentNotFound`).
- `InvalidQueueTicketTransition` — transition hors machine à états (couvre aussi la prise en charge
  d'un ticket déjà `in_progress`/`done`/`expired` : garde TOCTOU sur double-clic concurrent).
- `QueueTicketHairdresserRequired` — passage `in_progress` sans `hairdresser_id` (miroir exact de
  `AppointmentHairdresserRequired`).

### (B) Numérotation séquentielle — verrou par salon **et** jour civil

Déclinaison directe du patron ADR-0040 (`payment_repository.py:67-89`), avec une clé de verrou
combinant `salon_id` et le jour civil (`SALON_TIMEZONE`) pour que le compteur reparte à 1 chaque jour
**sans** dépendre d'un job de purge :

```python
def create(self, ticket: QueueTicketToCreate, *, issued_date: date) -> QueueTicket:
    lock_key = f"{ticket.salon_id}:{issued_date.isoformat()}"
    self._session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": lock_key},
    )
    next_number = self._session.execute(
        select(func.coalesce(func.max(models.QueueTicket.ticket_number), 0) + 1).where(
            models.QueueTicket.salon_id == ticket.salon_id,
            models.QueueTicket.issued_date == issued_date,
        )
    ).scalar_one()
    # ... INSERT (ticket_number=next_number) ; flush() sans commit ; refresh()
```

- `hashtext(text)` retourne un entier 32 bits stable : concaténer `salon_id` et `issued_date` en
  **une seule** clé reproduit exactement la forme déjà en production pour `receipt_number`. Le risque
  de collision de hachage est **théorique** et sans conséquence fonctionnelle (elle ne ferait que
  sérialiser à tort deux verrous indépendants — jamais de corruption ; la vraie garantie vient de la
  contrainte `UNIQUE`).
- Le verrou est **transactionnel** (`_xact_lock`), relâché au commit/rollback piloté par
  `get_session` — aucune nouvelle gestion de connexion, aucun verrou orphelin en cas de crash.
- `issued_date` est passé explicitement par le cas d'usage (horloge injectée, testable), jamais
  recalculé par le dépôt.
- Filet de dernier recours : `uq_queue_tickets_salon_day_number` (contrainte `UNIQUE`) — transforme
  une éventuelle course en `IntegrityError` retraduite en erreur de domaine, jamais en corruption
  silencieuse (miroir `CustomerAlreadyExists`).

**Alternative écartée** : une **séquence PostgreSQL nommée par salon** redémarrée par cron. Écartée
car elle introduirait de la **DDL dynamique par salon** (potentiellement des milliers de séquences),
un job de reset fiable en heure locale, et une dépendance opérationnelle (cron) absente ailleurs — le
patron verrou+`MAX+1` déjà en production pour les reçus est strictement plus simple à opérer et tester.

### (C) Indépendance vis-à-vis d'`Appointment` et forme du « pont »

**Pourquoi `QueueTicket` ne réutilise pas `appointments`** :

1. **Contrainte bloquante** : `Appointment.client_id` est `NOT NULL` (FK `users`) ; un walk-in a, en
   général, `CustomerProfile.user_id = NULL`. Exiger un compte pour délivrer un ticket contredirait
   l'objectif du parcours walk-in.
2. **Aucun créneau réel** : `appointment_date`/`start_time`/`end_time` sont requis et alimentent la
   colonne générée `slot` (exclusion base). Un walk-in n'a ni date ni heure prévue — seulement une
   estimation dérivable.
3. **Cycle de vie différent** : un `Appointment` porte une réservation à l'avance (annulable,
   modifiable, avec rappels) ; un `QueueTicket` porte une présence physique immédiate de quelques
   dizaines de minutes.

**Forme du pont retenue : fusion en lecture, jamais en écriture.** `GET /salons/{salon_id}/queue`
compose une **troisième source** en plus des deux existantes (RDV + paiements) :
`QueueTicketRepository.list_active_for_salon(salon_id, issued_date)` (tickets du jour aux statuts
`waiting`/`called`/`in_progress`/`done`, **hors** `expired`), **sans jamais** créer, mettre à jour ni
référencer une ligne `appointments`. Chaque ticket est projeté en une entrée dédiée sous la clé
`walk_in_tickets` (schéma en *API*), plutôt qu'en pseudo-entrée RDV avec un `appointment_id` fictif.

Justification « fusion en lecture » plutôt que « en écriture » :

- Le critère d'acceptation exige une **visibilité unifiée**, pas une **persistance unifiée** — la
  contrainte `client_id NOT NULL` rend cette dernière impraticable sans un changement de schéma qui
  déborderait l'effort L et fragiliserait un chemin d'écriture éprouvé (réservation #21/#22).
- Une fusion **en écriture** obligerait à un pseudo-`client_id` (compte technique « walk-in » ?) —
  rejeté : il polluerait toutes les lectures « mes rendez-vous » et casserait l'hypothèse implicite
  `client_id → un seul client réel` exploitée par les stats/notifications/historique.
- Une fusion **en lecture** n'exige aucune modification de `AppointmentRepository`/`PaymentRepository`
  (elle ajoute une source) ; seuls la forme de la réponse HTTP et `tests/test_queue_api.py` évoluent.

**Réutilisation au niveau du patron (pas du code)** — comment réutiliser `MarkAppointmentArrived` et
le cycle `arrived_at`/`started_at` sans dupliquer la logique :

- **Nom et ordre des préconditions** : `StartQueueTicket` (§D) vérifie `hairdresser_id is not None`
  comme `StartAppointmentService`, avec la **même** forme d'erreur (`QueueTicketHairdresserRequired`).
- **Écriture idempotente et conditionnelle** : `mark_started` fait `UPDATE ... WHERE status =
  'CONFIRMED'` puis ne pose l'horodatage que s'il est encore `None` — `SqlQueueTicketRepository.start`
  reproduit cette forme (`UPDATE ... WHERE status = 'waiting'`) pour la même garde TOCTOU.
- **Audit neutre** : `AuditAction.APPOINTMENT_STARTED` a pour miroir `AuditAction.QUEUE_TICKET_STARTED`
  avec `metadata={}` (aucune PII).

Aucune fonction n'est partagée bit à bit : les deux chemins opèrent sur des tables différentes avec
des `WHERE` différents. La réutilisation porte sur la **conception**, pas l'implémentation — niveau
honnête compte tenu de la contrainte `client_id NOT NULL`.

### (D) Cas d'usage (`application/queue_ticket.py`, nouveau fichier)

Dépend uniquement des ports `QueueTicketRepository` (nouveau), `CustomerRepository` (lecture,
existant), un port de lecture salon exposant `list_active_hairdressers` (déjà implémenté côté
`salon_catalog_repository.py` ; réutiliser le port existant qui l'expose, sinon en ajouter un dédié —
à trancher selon le découpage réel), `AuditLog`.

- **`JoinQueue.execute(salon_id, command, *, clock) -> QueueTicket`** (endpoint « rejoindre la
  file ») :
  1. valide `service_ids` (non vide ; chaque `Service` actif **et** du salon —
     `InvalidQueueTicketServices` sinon) ;
  2. si `customer_profile_id` fourni, vérifie son appartenance au salon
     (`CustomerRepository.find_by_id(salon_id, id)` ; sinon `QueueTicketNotFound`, indiscernable
     d'une fiche d'un autre salon, §11.2) ;
  3. calcule `estimated_wait_minutes` (formule ci-dessous), à partir de l'état de la file **avant**
     insertion ;
  4. `repository.create(QueueTicketToCreate(...), issued_date=today)` — alloue `ticket_number` sous
     verrou (§B) ;
  5. **pas d'audit** pour la création (un ticket walk-in n'est pas une action de gestion sensible
     §11.4, il ne porte aucune PII propre) — **à confirmer**, voir *Risks*.
- **Formule d'ETA (V1, fonction pure `estimate_wait_minutes`)** :

  ```python
  def estimate_wait_minutes(
      *,
      position: int,                    # tickets `waiting` déjà devant (0-indexé)
      average_service_minutes: float,   # moyenne des durées des prestations des tickets actifs
      active_hairdresser_count: int,
  ) -> int:
      if active_hairdresser_count <= 0:
          return DEFAULT_WAIT_MINUTES_NO_STAFF   # constante documentée (ex. 30) — filet dégénéré
      raw = (position * average_service_minutes) / active_hairdresser_count
      return max(0, round(raw))
  ```

  - `position` = nombre de tickets `waiting` **déjà** présents avant l'insertion (le nouveau
    n'attend pas derrière lui-même).
  - `average_service_minutes` = moyenne des `duration_minutes` des prestations liées aux tickets
    `waiting` **et** `in_progress` du salon (file réellement à écouler) ; si aucun ticket actif
    n'existe encore, repli sur la moyenne des `duration_minutes` des **prestations demandées par ce
    ticket lui-même** — jamais une constante arbitraire ni la moyenne de tout le catalogue.
  - `active_hairdresser_count` = `len(list_active_hairdressers(salon_id))` ; filet explicite si `0`
    (constante documentée, **pas** une division par zéro masquée).
  - **Limites explicites, assumées V1** : ne tient pas compte de la progression réelle des
    prestations `in_progress`, ne distingue pas les coiffeuses par spécialité, ne s'appuie sur
    **aucune** donnée historique — cohérent avec la décision produit du jalon.
- **`StartQueueTicket.execute(salon_id, ticket_id, hairdresser_id, actor_id, *, clock) ->
  QueueTicket`** : charge `(salon_id, ticket_id)` (`QueueTicketNotFound` sinon), exige `status ==
  "waiting"` (sinon `InvalidQueueTicketTransition`), valide `hairdresser_id` **membre `ACTIVE` du
  salon** (miroir `HairdresserNotInSalon`), passe `in_progress`, pose `started_at`, journalise
  `QUEUE_TICKET_STARTED` (`metadata={}`). Combine en un seul geste métier ce qui serait, côté RDV,
  deux étapes (assignation + démarrage) : un ticket walk-in n'a jamais de coiffeuse pré-assignée.
- **`CompleteQueueTicket.execute(salon_id, ticket_id, actor_id, *, clock) -> QueueTicket`** : exige
  `status == "in_progress"`, passe `done`, pose `completed_at`, journalise `QUEUE_TICKET_COMPLETED`.
- **`ListSalonQueueTickets.execute(salon_id, issued_date) -> tuple[QueueTicket, ...]`** : lecture
  pure, triée `ticket_number ASC`, pour l'extension de `ListSalonQueue` (§C) et l'écran born e #159.
- **Expiration** (`waiting`/`called` → `expired`) : **non livrée** comme automatisme planifié (pas de
  cron dans ce dépôt) ; documentée comme limite V1 (voir *Risks*).

### (E) Port & adapter de persistance

**`application/ports/queue_ticket_repository.py`** (nouveau, `Protocol`) :

```python
class QueueTicketRepository(Protocol):
    def create(self, ticket: QueueTicketToCreate, *, issued_date: date) -> QueueTicket: ...
    def get(self, salon_id: uuid.UUID, ticket_id: uuid.UUID) -> QueueTicket | None: ...
    def count_waiting(self, salon_id: uuid.UUID, *, issued_date: date) -> int: ...
    def list_active_for_salon(
        self, salon_id: uuid.UUID, *, issued_date: date
    ) -> tuple[QueueTicket, ...]: ...  # waiting/called/in_progress/done du jour (hors expired), triés ticket_number
    def average_requested_duration_minutes(
        self, salon_id: uuid.UUID, *, issued_date: date
    ) -> float | None: ...  # None si aucun ticket actif — bascule sur le repli du cas d'usage
    def start(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID, hairdresser_id: uuid.UUID, *, now: datetime
    ) -> QueueTicket: ...
    def complete(
        self, salon_id: uuid.UUID, ticket_id: uuid.UUID, *, now: datetime
    ) -> QueueTicket: ...
```

Toutes les méthodes filtrent `salon_id` en SQL (isolation §11.2, miroir `SqlCustomerRepository`).
**`adapters/outbound/persistence/queue_ticket_repository.py`** (`SqlQueueTicketRepository`) suit le
patron `flush()` sans `commit()` (atomicité pilotée par `get_session`).
`average_requested_duration_minutes` s'implémente en **un** `SELECT AVG(services.duration_minutes)`
joignant `queue_ticket_services → services`, filtré sur les tickets `waiting`/`in_progress` du jour —
une seule requête agrégée, pas de calcul en mémoire.

### (F) Adapter entrant (HTTP)

**`adapters/inbound/queue_tickets.py`** (nouveau routeur, `prefix="/salons"`, tag `queue-tickets`),
monté dans `main.py` avec un commentaire de câblage dans le style existant (permission, portée,
absence de `PUBLIC_ROUTE_PATHS`). Gardes exactes reproduisant `terminal_customers.py` : `require_salon_scope`
+ `require_permission(...)`. Détail des routes en *API / Interface Changes*.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/domain/queue_ticket.py` | entités pures, machine à états, `estimate_wait_minutes` |
| `coiflink_api/application/ports/queue_ticket_repository.py` | port `Protocol` |
| `coiflink_api/application/queue_ticket.py` | `JoinQueue`, `StartQueueTicket`, `CompleteQueueTicket`, `ListSalonQueueTickets` |
| `coiflink_api/adapters/outbound/persistence/queue_ticket_repository.py` | `SqlQueueTicketRepository` |
| `coiflink_api/adapters/inbound/queue_tickets.py` | router `/salons/{salon_id}/queue/tickets` (TERMINAL + gérant/coiffeuse) |
| `migrations/versions/0014_queue_tickets.py` | tables `queue_tickets` + `queue_ticket_services` |
| `tests/test_domain_queue_ticket.py`, `tests/test_queue_ticket_usecases.py`, `tests/test_queue_ticket_api.py`, `tests/test_queue_ticket_e2e.py` | tests |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/errors.py` | `InvalidQueueTicketServices`, `QueueTicketNotFound`, `InvalidQueueTicketTransition`, `QueueTicketHairdresserRequired` |
| `coiflink_api/domain/audit.py` | `ENTITY_TYPE_QUEUE_TICKET`, `AuditAction.QUEUE_TICKET_STARTED`/`QUEUE_TICKET_COMPLETED` |
| `coiflink_api/adapters/outbound/persistence/models.py` | classes ORM `QueueTicket`/`QueueTicketService`, reflet de `0014` |
| `coiflink_api/application/queue.py` | `ListSalonQueue` étendu pour composer une 3ᵉ source (tickets du jour) — voir §C |
| `coiflink_api/adapters/inbound/appointments.py` | réponse `GET .../queue` restructurée en objet `{appointments, walk_in_tickets}` |
| `coiflink_api/main.py` | `include_router(queue_tickets_router)` + commentaire de câblage |
| `backend/README.md` | section « File d'attente walk-in — tickets de passage (US-8.3, #157) » |
| `tests/conftest.py` | `FakeQueueTicketRepository` + fixture |
| `tests/test_domain_audit.py` | nouvelles actions/entité couvertes |
| `tests/test_queue_api.py` | non-régression du contenu RDV (clé `appointments`) + nouvelle clé `walk_in_tickets` |

### Web (`web-dashboard/`) — dépendance directe de la même PR

| Fichier | Modification |
| --- | --- |
| `web-dashboard/src/adapters/ui/queue-board.tsx` | consommer le nouveau contrat `{appointments, walk_in_tickets}` (rendu des tickets walk-in) |
| `web-dashboard/README.md` | note sur le nouveau contrat de `GET /salons/{salon_id}/queue` |

### Documentation (racine)

`docs/adr/0042-file-attente-walkin-queue-ticket.md` (nouvelle ADR) + entrée dans
`docs/adr/README.md` ; `README.md` (statut M7 : #157 livré).

### À lire (sans modifier) pour rester fidèle aux patrons

`application/queue.py`, `domain/queue.py`, `adapters/outbound/persistence/appointment_repository.py`
(`mark_arrived`/`mark_started`), `adapters/outbound/persistence/payment_repository.py:67-89`,
`adapters/outbound/persistence/salon_catalog_repository.py` (`list_active_hairdressers`),
`adapters/inbound/terminal_customers.py` (garde TERMINAL), `domain/errors.py`,
`docs/adr/0040-impression-recu-encaissement-gerant.md`.

## API / Interface Changes

### Nouveau — rejoindre la file (walk-in)

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/queue/tickets` | `require_salon_scope` (portée device→salon) **+** `require_permission(Permission.QUEUE_TICKET_CREATE)` — détenue par `Role.TERMINAL` (#155) | `201` ticket · `401` (jeton absent/invalide) · `403` (rôle/permission insuffisant, salon hors périmètre) · `404` fiche client hors salon · `422` prestation(s) invalide(s) |

```jsonc
// POST /salons/{salon_id}/queue/tickets — corps
{
  "customer_profile_id": "…uuid…",   // optionnel : null = ticket anonyme (voir Open Questions)
  "service_ids": ["…uuid…"]          // >= 1, prestations actives du salon
}

// 201 — réponse
{
  "id": "…uuid…",
  "ticket_number": 7,
  "issued_date": "2026-08-11",
  "status": "waiting",
  "estimated_wait_minutes": 18,
  "created_at": "2026-08-11T09:12:00Z",
  "service_ids": ["…uuid…"]
}
```

`ticket_number` est exposé comme **entier brut** (API et domaine) : le formatage d'affichage (« N°
014 », zéro-padding) est la responsabilité exclusive du formatter ESC/POS de #160 (sur le modèle de
`format_receipt_number`, `domain/receipt.py`) — jamais une chaîne pré-formatée par #157.

Cette route n'est **pas** ajoutée à `PUBLIC_ROUTE_PATHS` : « public/terminal » qualifie l'usage (un
terminal en salle d'accueil), pas le régime d'authentification (deny-by-default inchangé). Le
`salon_id` du chemin doit correspondre au salon figé du device (§11.2, borne mono-salon) : toute
divergence renvoie le `403` générique, jamais un `404` qui confirmerait l'existence du salon visé.

### Nouveau — prise en charge / clôture (gérant, coiffeuse)

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/queue/tickets/{ticket_id}/start` | `require_salon_scope` + `require_permission(Permission.APPOINTMENT_UPDATE_STATUS)` *(réutilisation proposée — mêmes acteurs que le démarrage d'un RDV : coiffeuse et gérant ; voir Open Questions)* | `200` ticket · `401`/`403` · `404` · `409` (transition invalide) |
| `POST` | `/salons/{salon_id}/queue/tickets/{ticket_id}/complete` | idem | `200` ticket · `401`/`403` · `404` · `409` |

```jsonc
// POST .../start — corps
{ "hairdresser_id": "…uuid…" }   // requis, doit être un membre ACTIVE du salon

// 200 — réponse (start et complete)
{
  "id": "…uuid…",
  "ticket_number": 7,
  "status": "in_progress",
  "hairdresser_id": "…uuid…",
  "started_at": "2026-08-11T09:20:00Z",
  "completed_at": null
}
```

### Modifié — `GET /salons/{salon_id}/queue` (rupture de forme mineure et assumée)

La réponse actuelle (`list[QueueEntryResponse]`, `appointments.py:1236`) est **remplacée** par un
objet englobant à deux clés :

```jsonc
// 200 — GET /salons/{salon_id}/queue?day=2026-08-11
{
  "appointments": [ /* QueueEntryResponse existants, structure inchangée champ à champ */ ],
  "walk_in_tickets": [
    {
      "ticket_id": "…uuid…",
      "ticket_number": 7,
      "customer_first_name": "Awa",      // prénom seul, aligné sur la projection #156 ; jamais le nom complet ni le téléphone
      "service_names": ["Tresses"],
      "hairdresser_id": "…uuid…",
      "hairdresser_name": "…",
      "status": "in_progress",           // tickets du jour waiting/called/in_progress/done (hors expired)
      "started_at": "2026-08-11T09:20:00Z",
      "completed_at": null
    }
  ]
}
```

**Décision tranchée : deux tableaux distincts dans la même réponse, jamais fusionnés en une liste
unique.** Justification :

- Un `QueueEntryResponse` porte `appointment_id`, `start_time`, `end_time` — sans sens pour un
  walk-in (pas de créneau planifié). Les forcer dans un seul type de ligne exigerait de les rendre
  nullables (fuite de complexité walk-in) ou un type union côté web (plus dur à consommer).
- Le tri naturel diffère : RDV par `start_time`, tickets par `ticket_number` (ordre d'arrivée).
- Le critère d'acceptation est satisfait : les deux tableaux vivent dans la **même** réponse HTTP du
  **même** endpoint, sur le **même** écran (`queue-board.tsx`).

Le changement casse en théorie tout client désérialisant strictement l'ancienne forme. Impact réel :
seul `queue-board.tsx` (dépôt) consomme ce contrat — mis à jour dans la **même** PR. Alternative
écartée : un endpoint séparé `GET .../queue/tickets` (deux appels/écrans ne satisferaient pas
littéralement « apparaît dans la file gérant existante », sans bénéfice de compatibilité réel).
**Point à confirmer** avec le porteur produit/équipe web, voir *Risks*.

## Data Model / Protocol Changes

**Oui** — migration Alembic **`0014_queue_tickets.py`** (`revision = "0014"`, `down_revision =
"0013"` — la tête vérifiée est `0013_kiosk_role.py`), reflet du modèle ORM, créant **deux** tables :

1. **`queue_tickets`** : `id` (PK, `gen_random_uuid()`), `salon_id` (FK `salons`, `RESTRICT`),
   `ticket_number` (`INTEGER NOT NULL`), `issued_date` (`DATE NOT NULL`), `customer_profile_id` (FK
   `customer_profiles`, nullable, `RESTRICT`), `hairdresser_id` (FK **`users`**, nullable, `RESTRICT`
   — miroir exact d'`Appointment.hairdresser_id` : identifiant de **compte**, appartenance salon
   vérifiée **applicativement**), `status` (`VARCHAR(32)` + `CHECK IN
   ('waiting','called','in_progress','done','expired')`), `estimated_wait_minutes` (`INTEGER NOT
   NULL`), `created_at` (`TIMESTAMPTZ NOT NULL DEFAULT now()`), `called_at`/`started_at`/`completed_at`
   (`TIMESTAMPTZ` nullable). Contrainte **`UNIQUE (salon_id, issued_date, ticket_number)`** (garantie
   base du compteur) ; index **`(salon_id, status)`** (lectures filtrées par statut).
2. **`queue_ticket_services`** : jonction `(queue_ticket_id, service_id)` (PK composite), `salon_id`
   dupliqué pour la FK composite **`(salon_id, service_id) → services(salon_id, id)`** (force
   l'appartenance salon, miroir `appointment_services`), `ondelete="CASCADE"` sur `queue_ticket_id`
   (jonction pure-dépendante).
3. **Aucune** colonne existante (`appointments`, `payments`, `customer_profiles`, `services`)
   modifiée — migration strictement **additive**.
4. `downgrade()` : `drop_table("queue_ticket_services")` puis `drop_table("queue_tickets")` (ordre
   inverse de création — exigé par le round-trip Alembic de la CI ; les FK disparaissent avec les
   tables).

**Décision explicite non retenue** : ajouter un `appointment_id` nullable sur `queue_tickets` en
prévision d'un futur pont en écriture — un champ nullable jamais rempli en V1 serait une dette de
schéma silencieuse ; si le pont en écriture devient un besoin réel, la colonne s'ajoutera alors par
une migration dédiée avec sa propre justification.

**Mise à jour miroir de `models.py`** (source de vérité versionnée) : classes ORM
`QueueTicket`/`QueueTicketService`, strictement reflet de `0014` — toute divergence casse le
round-trip Alembic de la CI.

## Security & Privacy Considerations

- **Aucune route publique.** Les trois routes restent **protégées** (credential `TERMINAL` de #155 pour
  la création ; `APPOINTMENT_UPDATE_STATUS` + portée salon pour start/complete) — jamais ajoutées à
  `PUBLIC_ROUTE_PATHS`. Invariant deny-by-default inchangé ; l'invariant de test
  `unprotected_routes(app) == []` (tests de sécurité #51) couvre automatiquement les nouvelles routes.
- **Isolation par salon (§11.2), en profondeur.** Toutes les méthodes du port filtrent `salon_id` en
  SQL ; un `customer_profile_id` d'un autre salon est refusé avec la **même** erreur
  (`QueueTicketNotFound`) qu'un id inexistant — aucun oracle d'existence. Le device `TERMINAL` ne peut
  de toute façon soumettre que le `salon_id` de son provisioning (`require_salon_scope`, #155).
- **Minimisation de la PII à l'écran gérant partagé.** `GET .../queue` n'expose que
  `customer_first_name` pour un ticket walk-in — jamais le nom complet ni le téléphone —, aligné sur
  la projection `{customer_id, first_name}` déjà retenue par #156 (`terminal_customers.py`). L'écran
  borne (#159) n'affiche jamais l'identité d'un autre client que celui en interaction.
- **`customer_profile_id` nullable — ticket anonyme possible.** Un client qui refuse de laisser son
  identité doit tout de même pouvoir obtenir un ticket : `customer_profile_id = null` reste valide
  côté domaine. Conséquence : le ticket n'alimente **aucun** historique de visite
  (`CustomerProfile.total_visits`/`last_visit_at` ne sont **jamais** touchés par #157). **À
  confirmer** avec le produit (l'UX exacte est propriété de #159).
- **Aucune donnée financière ni de santé sur un `QueueTicket`** : seulement des identifiants opaques,
  une liste de prestations et des horodatages — surface de risque minimale.
- **Journalisation §11.4 ciblée sur les actions de gestion, pas l'émission.**
  `QUEUE_TICKET_STARTED`/`QUEUE_TICKET_COMPLETED` sont journalisées avec `metadata={}` (aucune PII,
  miroir `APPOINTMENT_STARTED`) ; la **création** d'un ticket par le device n'est **pas** journalisée
  dans le journal d'audit **gérant** (aucune action humaine du personnel) — **à confirmer** (une
  trace d'accès device relèverait d'un futur journal d'activité borne, #155/#161).
- **Abus du terminal partagé.** Rien dans #157 n'empêche la création de tickets en boucle ; un
  **débit maximal par device/minute** est une mitigation naturelle mais relève de la garde `TERMINAL`
  (#155, qui pose déjà un rate-limiter sur `lookup`) ou d'un middleware transverse — **hors périmètre
  de #157**, signalé comme dépendance amont à vérifier avant mise en production du jalon.
- **Intégrité concurrente du numéro de ticket.** Le verrou consultatif sérialise les créations
  concurrentes du même salon+jour ; la contrainte `UNIQUE` base est le filet ultime — une violation
  improbable est retraduite en erreur de domaine, jamais en `IntegrityError` brute exposée au client.
- **Aucun secret journalisé.** Le device credential (#155) n'apparaît jamais dans les logs ni les
  réponses de #157 ; les réponses ne portent que numéro, prénom, prestations et horodatages.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_domain_queue_ticket.py`** :
  - `estimate_wait_minutes` : position `0` → attente minimale ; position croissante → attente
    croissante ; `active_hairdresser_count = 0` → constante de repli (jamais de `ZeroDivisionError`) ;
    arrondi cohérent (`round`, jamais de troncature qui sous-estime).
  - transitions valides/invalides de `QueueTicketStatus` (table de vérité complète : 5 statuts ×
    transitions autorisées, miroir du test d'état d'`AppointmentStatus`).
  - `service_ids` vide → `InvalidQueueTicketServices`.
- **`tests/test_queue_ticket_usecases.py`** (fakes `conftest.py`) :
  - `JoinQueue` : `ticket_number` incrémente par salon+jour distinct (deux salons/jours ne se
    marchent jamais dessus) ; `customer_profile_id` d'un autre salon → `QueueTicketNotFound`,
    **aucune** écriture ; `customer_profile_id = None` accepté ; `estimated_wait_minutes` cohérent
    (file vide, file non vide, 0 coiffeuse active).
  - `StartQueueTicket` : refuse un ticket déjà `in_progress`/`done` (`InvalidQueueTicketTransition`) ;
    refuse une coiffeuse hors salon (`HairdresserNotInSalon`) ; audit `QUEUE_TICKET_STARTED` **une
    seule fois**, `metadata == {}`.
  - `CompleteQueueTicket` : refuse un ticket encore `waiting` (jamais démarré).
  - `ListSalonQueueTickets` : ne renvoie que les tickets du salon/jour demandés, triés
    `ticket_number`.
- **`tests/test_domain_audit.py`** : nouvelles actions/entité présentes et cohérentes.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_queue_ticket_api.py`** :
  - `POST .../queue/tickets` : `201` avec `ticket_number` séquentiel croissant sur appels successifs
    du même salon/jour ; `422` prestation vide/inactive/hors salon ; `404` `customer_profile_id`
    d'un autre salon ; `403` si le principal n'a pas la permission `QUEUE_TICKET_CREATE` (ex. un
    `CLIENT`/`MANAGER` sur cette route terminal) ; `401` sans jeton.
  - `POST .../start` / `.../complete` : `200` nominal ; `409` transition invalide (déjà démarré / pas
    encore démarré) ; `404` ticket d'un autre salon ; `403` rôle insuffisant ; `401` sans jeton.
  - `tests/test_queue_api.py` (existant, à étendre) : le corps de `GET .../queue` porte désormais
    `appointments`/`walk_in_tickets` ; `appointments` reproduit **exactement** l'ancien contenu
    (non-régression du contrat RDV) ; `walk_in_tickets` contient les tickets du jour
    `waiting`/`called`/`in_progress`/`done` (jamais `expired`).
- **`tests/test_security_guards.py` / matrice authz** : vérifier qu'aucun chemin `queue/tickets`
  n'entre dans `PUBLIC_ROUTE_PATHS` et que la matrice rôle × route couvre les trois nouvelles routes.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_queue_ticket_e2e.py`** (patron des e2e terminal #155/#156) :
  1. parcours complet : device `TERMINAL` provisionné (#155) → identification/omission client (#156) →
     `POST .../queue/tickets` → le ticket apparaît dans `ListSalonQueueTickets` → `POST .../start`
     (coiffeuse du salon) → apparaît dans `GET .../queue` (`walk_in_tickets`) → `POST .../complete`.
  2. **concurrence réelle** : deux créations quasi-simultanées (threads/connexions séparées) sur le
     même salon/jour → deux `ticket_number` **distincts et consécutifs** (preuve du verrou + de la
     contrainte `UNIQUE`).
  3. **isolation par jour** : deux tickets à un jour d'intervalle (horloge injectée) → chacun
     redémarre à partir de son propre `MAX` (le compteur de la veille n'influence pas le nouveau).
  4. **isolation inter-salons** : un device du salon A ne peut ni créer ni voir un ticket du salon B.
  5. deny-by-default : sans credential valide → `401`/`403` sur les trois routes.
- **Migration** : round-trip Alembic (`upgrade head → downgrade -1 → upgrade head`) couvre `0014`.

## Documentation Updates

- **`backend/README.md`** : section « File d'attente walk-in — tickets de passage (US-8.3, #157) »
  avec le tableau routes/permission/réponses, la formule d'ETA en clair, et un rappel « `QueueTicket`
  est indépendant d'`Appointment` — voir ADR-0042 ».
- **`docs/adr/0042-file-attente-walkin-queue-ticket.md`** (nouvelle ADR, committée avec #157) +
  entrée dans **`docs/adr/README.md`**.
- **OpenAPI** : `summary`/`responses`/docstrings des nouvelles routes (dont `409`/`422`), visibles sur
  `/docs`.
- **`web-dashboard/README.md`** : note sur le nouveau contrat de `GET /salons/{salon_id}/queue`
  (`appointments`/`walk_in_tickets`) une fois `queue-board.tsx` mis à jour.
- **`README.md`** (racine) : ligne de statut M7 mentionnant #157 livré (file walk-in), à la suite de
  #155/#156.

## Risks and Open Questions

Choix à valider par le porteur produit **avant** l'implémentation (déterminent des décisions de
schéma ou de contrat difficiles à revenir en arrière) :

1. **Fusion en *lecture* vs *écriture* (indépendance `QueueTicket`/`Appointment`).** Justifiée par
   `Appointment.client_id NOT NULL` (§C). **À valider** : si le produit veut un jour que le walk-in
   pèse dans les statistiques de revenu/fréquentation (qui s'appuient aujourd'hui sur
   `Appointment`/`Payment.appointment_id`), il faudra soit accepter que ces stats ignorent le walk-in
   en V1 (implicite ici), soit lancer un travail de schéma dédié plus tard — **pas dans #157**.
2. **Formule V1 d'ETA** — implémentée telle quelle avec deux replis (aucune coiffeuse active ; aucun
   ticket actif). **À valider** : le repli « moyenne des prestations du ticket lui-même » en
   l'absence de tout autre ticket est une convention parmi d'autres (une constante fixe serait plus
   simple mais moins représentative) — impact limité au tout premier ticket de la journée.
3. **Réutilisation de `APPOINTMENT_UPDATE_STATUS` pour start/complete** — proposée par cohérence
   (mêmes acteurs — coiffeuse et gérant — que le démarrage d'un RDV) plutôt que créer une permission
   dédiée `QUEUE_TICKET_MANAGE`. **À confirmer** : bon marché à changer maintenant, coûteux après
   coup (matrice de permissions). Si le produit veut un jour dissocier ces droits, une permission
   dédiée serait alors justifiée.
4. **Forme de réponse de `GET /salons/{salon_id}/queue` (`list` → objet à deux clés)** — rupture de
   contrat mineure assumée d'un endpoint interne (consommateur unique connu : `queue-board.tsx`,
   mis à jour dans la même PR). **À confirmer** avec l'équipe web ; l'alternative (endpoint séparé)
   est documentée et écartée mais pas définitivement exclue.
5. **Journalisation ou non de la création d'un ticket** — cette spec propose de **ne pas**
   journaliser `JoinQueue` (pas une action humaine de gestion) mais de journaliser `start`/`complete`
   (actions humaines). **À confirmer** — un rejet n'aurait qu'un coût d'implémentation marginal (le
   socle `AuditLog` est déjà injectable).
6. **Expiration automatique** — non livrée (pas de cron dans le dépôt). Un ticket `waiting` oublié
   reste `waiting` indéfiniment jusqu'à une action explicite. **À confirmer** : acceptable pour un
   MVP piloté sur 2-3 salons, à traiter avant généralisation.
7. **Ticket anonyme (`customer_profile_id = null`)** — le domaine l'autorise ; l'UX (#159) ne le
   tranche pas ici. **À confirmer** avec #156/#159 : la borne doit-elle offrir un chemin « continuer
   sans donner mon nom » ?
8. **Rate-limiting de la création de tickets** — non livré par #157 (dépendance à la garde `TERMINAL`
   #155 ou à un middleware transverse). À vérifier avant mise en production du jalon.
9. **`down_revision` de la migration** — `0013` est la tête vérifiée aujourd'hui, mais si une autre
   issue du jalon (ex. #158+) merge une migration avant #157, **renuméroter** ; ne jamais laisser
   deux migrations partager la même révision.

## Implementation Checklist

1. **Lire** `application/queue.py`, `domain/queue.py`, `appointment_repository.py`
   (`mark_arrived`/`mark_started`), `payment_repository.py:67-89`,
   `salon_catalog_repository.py` (`list_active_hairdressers`), `terminal_customers.py` (garde TERMINAL),
   `docs/adr/0040-…` — s'imprégner des patrons de verrouillage, de préconditions et d'audit.
2. **Trancher** avec le porteur produit les questions ouvertes 1, 2, 3, 4, 5, 6, 7 (elles déterminent
   des choix de schéma/contrat difficiles à revenir en arrière).
3. **Domaine** : créer `domain/queue_ticket.py` (statuts, `QueueTicketToCreate`/`QueueTicket`,
   machine à états, `estimate_wait_minutes` avec ses replis documentés) ; ajouter les 4 erreurs à
   `domain/errors.py`.
4. **Audit** : ajouter `ENTITY_TYPE_QUEUE_TICKET`, `AuditAction.QUEUE_TICKET_STARTED`/
   `QUEUE_TICKET_COMPLETED` à `domain/audit.py`.
5. **Tests de domaine** : écrire `tests/test_domain_queue_ticket.py` (ETA, machine à états) **avant**
   la persistance.
6. **Schéma** : ajouter les classes ORM `QueueTicket`/`QueueTicketService` à `models.py` ; écrire
   `migrations/versions/0014_queue_tickets.py` (`down_revision = "0013"`, revalidé selon l'ordre de
   merge réel) avec un `downgrade()` complet ; vérifier le round-trip Alembic sur PostgreSQL 16.
7. **Port** : créer `application/ports/queue_ticket_repository.py`.
8. **Cas d'usage** : créer `application/queue_ticket.py` (`JoinQueue`, `StartQueueTicket`,
   `CompleteQueueTicket`, `ListSalonQueueTickets`), en réutilisant les patrons de préconditions et
   d'écriture idempotente identifiés à l'étape 1.
9. **Fakes & tests applicatifs** : `FakeQueueTicketRepository` + fixture dans `tests/conftest.py` ;
   écrire `tests/test_queue_ticket_usecases.py`.
10. **Adapter sortant** : créer `adapters/outbound/persistence/queue_ticket_repository.py` (verrou
    consultatif salon+jour, `flush()` sans `commit()`, filtres `(salon_id, id)`,
    `average_requested_duration_minutes` en une requête agrégée).
11. **Adapter entrant** : créer `adapters/inbound/queue_tickets.py` (schémas Pydantic ; gardes
    `require_salon_scope` + `require_permission(...)` selon la table §API ; mapping `404`/`409`/`422`) ;
    **ne pas** toucher `PUBLIC_ROUTE_PATHS`.
12. **Extension de la file existante** : modifier `application/queue.py::ListSalonQueue` (3ᵉ source)
    et `adapters/inbound/appointments.py` (réponse `GET .../queue` à deux clés) ; mettre à jour
    `tests/test_queue_api.py` (non-régression RDV **et** nouvelle clé `walk_in_tickets`).
13. **Câblage** : `app.include_router(queue_tickets_router)` dans `main.py` avec commentaire de
    câblage dans le style existant.
14. **Web** : adapter `web-dashboard/src/adapters/ui/queue-board.tsx` au nouveau contrat (même PR).
15. **Tests API & e2e** : `tests/test_queue_ticket_api.py` puis `tests/test_queue_ticket_e2e.py`
    (concurrence réelle, isolation par jour, isolation inter-salons, deny-by-default) ; exécuter
    `pytest` (+ `DATABASE_URL`) et `ruff check`.
16. **Documentation** : section dédiée dans `backend/README.md` ; rédaction de
    `docs/adr/0042-file-attente-walkin-queue-ticket.md` + entrée dans `docs/adr/README.md` ; note de
    contrat dans `web-dashboard/README.md` ; ligne de statut M7 dans `README.md`.
17. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test),
    `ruff check` ; relire la PR pour s'assurer qu'**aucune PII** n'apparaît dans l'audit ou les
    réponses au-delà du prénom autorisé, et qu'**aucune signature IA** n'a été introduite.
