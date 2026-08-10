# Ticket de passage walk-in & estimation d'attente (US-8.3)

> Spécification de planification pour l'issue GitHub **#157 — US-8.3 : Ticket de passage
> walk-in & estimation d'attente** (`feature` · Must · Effort L · PRD §17 « Borne Intelligente
> d'Accueil », promu au jalon **M7 — Borne client (kiosque libre-service)**, Épic 8).
> **Dépend de : #155, #156.** **Cette spec ne produit pas de code** : elle décrit l'approche à
> implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon M7 promeut le parcours « client sans rendez-vous » du PRD §17 (« Borne Intelligente
d'Accueil ») au rang de fonctionnalité livrable, en le limitant volontairement au walk-in
(cf. bloc M7 de `BACKLOG.md`). #155 (rôle `KIOSK`) pose l'identité du terminal ; #156 (identification
téléphone / création walk-in) donne à la borne un moyen de savoir **qui** se présente. Il manque
encore la pièce centrale du parcours : **quoi faire** de ce client une fois identifié — lui délivrer
un numéro de passage, une estimation d'attente, et le faire apparaître quelque part pour que le
personnel puisse le prendre en charge. C'est l'objet de #157.

Exploration du dépôt (vérifiée par lecture directe, code à l'état du dernier commit
`f5374b2`) :

- **Aucune notion de « file d'attente walk-in » n'existe.** La seule « file d'attente » livrée à ce
  jour (#150/#152, PR #153) est un **outil de pointage sur rendez-vous déjà planifiés** :
  `domain/queue.py` ne dérive un statut (`waiting`/`in_progress`/`completed`/`paid`) que pour des
  `Appointment` dont le statut est déjà `CONFIRMED` ou `COMPLETED`
  (`QUEUE_APPOINTMENT_STATUSES`, `coiflink_api/domain/queue.py:48-51`) — **jamais** `PENDING`, et
  **jamais** un client sans RDV du tout. Le commentaire de `application/dashboard.py:61` est
  explicite : *« aucune salle d'attente walk-in, §17 »*. Il n'existe **aucune table**, **aucune
  colonne** `ticket_number`/`queue_number`, **aucun** calcul de temps d'attente nulle part dans le
  dépôt (recherche exhaustive négative sur `ticket`, `estimated_wait`, `queue_number`).
- **`Appointment.client_id` est une FK `NOT NULL` vers `users`.** Vérifié sur le modèle ORM
  (`coiflink_api/adapters/outbound/persistence/models.py:305` : `client_id: Mapped[uuid.UUID] =
  _fk_uuid(nullable=False)`) et sur l'entité de domaine (`coiflink_api/domain/appointment.py:60-61` :
  `client_id: uuid.UUID` non optionnel dans `AppointmentToCreate`). Un rendez-vous suppose donc
  toujours un **compte utilisateur** authentifié. Or un client walk-in identifié par #156 obtient
  une `CustomerProfile` avec `user_id = NULL` **dans le cas général** (c'est précisément le point du
  walk-in : pas de mot de passe, pas de compte) — et l'entité de domaine `Customer` **n'expose même
  pas** `user_id` (`coiflink_api/domain/customer.py:164-170`, anti-oracle ADR-0026). **Un ticket
  walk-in ne peut donc pas, dans le cas général, devenir une ligne `appointments`** sans soit exiger
  un compte (contradiction avec le principe même du walk-in), soit assouplir `client_id` en base (un
  changement de schéma qui déborderait très largement le périmètre de #157 — voir *Proposed
  Implementation §C*). C'est le fait le plus structurant de cette spec : il détermine la forme du
  « pont » vers #152 demandé par le jalon.
- **Le seul générateur de compteur séquentiel-par-salon du dépôt est le `receipt_number` des
  paiements (#154, ADR-0040)**, directement réutilisable comme patron pour `ticket_number` :
  `coiflink_api/adapters/outbound/persistence/payment_repository.py:57-89` verrouille
  (`pg_advisory_xact_lock(hashtext(:salon_id))`) avant de lire `MAX(receipt_number) + 1`, dans la
  **même transaction** que l'insertion — « pas de nouvelle table de compteur, pas de nouvelle
  frontière de transaction » (commentaire ligne 61-63). `docs/adr/0040-impression-recu-encaissement-gerant.md:34-43`
  documente le choix. #157 doit simplement décliner ce patron avec une clé de verrou plus fine
  (salon **et** jour, cf. *Proposed Implementation §A*).
- **`Payment` sait déjà exister sans `Appointment`.** `payments.appointment_id` et `payments.client_id`
  sont tous deux **nullables** (`models.py:477-480`), le PRD §8.2 étant explicitement « lié à une
  prestation **ou** un rendez-vous ». `RecordPayment` (`application/payments.py:74-91`) résout le
  montant attendu depuis `Service.price` quand seul `service_id` est fourni. Conséquence directe pour
  #157 : **encaisser une prestation walk-in ne nécessite aucune ligne `appointments`** — le gérant
  peut déjà enregistrer un paiement `service_id`-only pour un ticket servi, sans qu'aucun code
  d'encaissement ne bouge. Ce point n'est pas un livrable de #157 (aucun champ `ticket_id` sur
  `Payment` n'est ajouté ici, voir *Non-Goals*) mais il retire une inquiétude : le jalon n'a pas
  besoin de résoudre la facturation walk-in pour être cohérent.
- **`list_active_hairdressers(salon_id)` existe déjà** (`adapters/outbound/persistence/
  salon_catalog_repository.py:105-118`, filtre `role = HAIRDRESSER AND status = ACTIVE` sur
  `salon_members`), déjà consommé par le catalogue public pour #150 (choix de coiffeuse à la
  réservation). C'est directement le dénominateur « nombre de coiffeuses actives » de la formule
  d'ETA — aucun nouveau calcul d'effectif à inventer.
- **`MarkAppointmentArrived`/`StartAppointmentService` (`application/queue.py:52-139`) sont câblés à
  du texte SQL conditionnel `WHERE status = 'CONFIRMED'`**
  (`adapters/outbound/persistence/appointment_repository.py:369-416`) : ils ne peuvent physiquement
  s'exécuter que sur une ligne `appointments` déjà existante et confirmée. Aucune fonction commune
  n'est extractible telle quelle vers un ticket qui n'a jamais existé dans `appointments` — la
  réutilisation possible est **le patron** (préconditions vérifiées dans le cas d'usage, écriture
  conditionnelle idempotente, audit neutre), pas l'appel de méthode lui-même.
- **`GET /salons/{salon_id}/queue`** (`adapters/inbound/appointments.py:1234-1272`, gardé
  `APPOINTMENT_READ_SALON` + `require_salon_scope`) rend aujourd'hui exclusivement des
  `QueueEntryResponse` issues de `ListSalonQueue` (`application/queue.py:142-174`), composées à
  partir de `AppointmentRepository.list_queue_details` + `PaymentRepository.
  list_paid_appointment_ids`. Cette route est le seul écran gérant de « file d'attente » qui existe
  (`web-dashboard/app/(gerant)/gerant/file-attente/page.tsx`) : c'est l'écran que le critère
  d'acceptation de #157 (« il apparaît dans la file gérant existante ») vise.

## Goals

- **Domaine `QueueTicket` indépendant, avec migration dédiée.** Nouvelle entité de domaine et
  nouvelle table `queue_tickets` (+ table de jonction `queue_ticket_services`), sans aucune
  modification de `appointments`/`services`/`customer_profiles` (additif pur).
- **Numérotation séquentielle par salon et par jour, sûre en concurrence.** `ticket_number`
  redémarre à 1 chaque jour civil du salon (fuseau `Africa/Abidjan`, `domain/time_window.py`),
  garanti unique par un index base **et** protégé d'une course par verrou consultatif
  transactionnel (patron ADR-0040, décliné avec une clé salon+jour).
- **Endpoint « rejoindre la file »**, réservé au rôle `KIOSK` de #155 : crée un ticket `waiting`,
  retourne `ticket_number`, `estimated_wait_minutes`, l'heure d'émission — la borne peut imprimer
  immédiatement (préalable direct de #160).
- **Formule V1 d'ETA explicite et bornée**, assumée comme heuristique perfectible : position dans
  la file des tickets `waiting` × durée moyenne des prestations demandées par les tickets actifs ÷
  nombre de coiffeuses `ACTIVE` du salon — avec des filets pour les cas dégénérés (aucune coiffeuse
  active, file vide, aucune donnée de durée).
- **Prise en charge par une coiffeuse/le gérant** : un nouveau cas d'usage assigne une coiffeuse à un
  ticket `waiting` et le fait passer `in_progress`, en miroir des préconditions déjà établies par
  #150 pour un rendez-vous (coiffeuse requise avant démarrage) — sans dupliquer la persistance
  `appointments`.
- **Visibilité gérant sans écriture dans `appointments`.** La réponse de `GET /salons/{salon_id}/queue`
  **évolue** vers un objet à deux clés `{appointments, walk_in_tickets}` pour inclure les tickets
  walk-in du jour (`waiting`/`called`/`in_progress`/`done`, hors `expired`), satisfaisant le critère
  d'acceptation « apparaît dans la file gérant existante une fois pris en charge » sans jamais créer
  de ligne `appointments` fictive (voir *Proposed Implementation §C* pour la justification détaillée
  du choix « fusion en lecture »).
- **Aucune régression sur la file des rendez-vous planifiés** : les entrées `QueueEntryResponse`
  existantes sont reprises champ à champ sous la clé `appointments` ; le passage de `list[...]` à un
  objet à deux clés `{appointments, walk_in_tickets}` est une rupture de forme mineure et assumée,
  le consommateur unique `queue-board.tsx` étant mis à jour dans la même PR.
- **Cycle de vie complet du ticket** : `waiting → called → in_progress → done`, plus `expired`
  (ticket jamais pris en charge, nettoyé en fin de journée) — statuts fermés, dérivés d'aucune autre
  table.

## Non-Goals

Rappel du périmètre du jalon M7 dans son ensemble (cf. `BACKLOG.md`, bloc M7) — ce qui suit reste
**hors scope de tout M7**, pas seulement de #157 : le **check-in d'un rendez-vous existant** depuis
la borne, l'**identification par QR code ou code de réservation**, l'**affichage temps réel des
coiffeurs disponibles avant affectation** (la borne ne demande jamais « quelle coiffeuse »), et le
**paiement autonome sur la borne**. Ces quatre points restent différés au-delà de M7.

Spécifiquement hors scope de #157 :

- **Le rôle `KIOSK`, son credential et sa garde de portée.** #157 **consomme** la garde posée par
  #155 (`require_permission`/portée salon d'un device) ; il ne la définit pas. La spec suppose son
  existence à l'implémentation et devra être ajustée si la forme exacte diffère.
- **L'identification téléphone / création de fiche walk-in.** #157 **consomme** `CustomerProfile`
  (via `customer_profile_id`, nullable) produit par #156 ; il n'ajoute ni ne modifie
  `find_by_phone`/`create`.
- **Toute UI.** Écrans borne (#159) et impression thermique (#160) sont des consommateurs de
  l'endpoint « rejoindre la file » et du cycle de statuts définis ici ; aucun widget Flutter n'est
  livré par #157.
- **Facturation liée au ticket.** Aucun champ `ticket_id` n'est ajouté à `Payment` ; l'encaissement
  d'une prestation walk-in servie reste, en V1, un encaissement `service_id`-only classique (déjà
  possible aujourd'hui, cf. *Problem Statement*). Un lien explicite paiement ↔ ticket est un suivi
  potentiel, pas un livrable (voir *Risks and Open Questions*).
- **Notifications au client walk-in** (SMS/WhatsApp annonçant son tour). Le PRD §17.3 l'évoquait pour
  la version « ticket numérique » ; M7 assume un ticket **papier** (#160) — aucune notification
  proactive n'est ajoutée, cohérent avec l'ADR-0006 (fan-out différé).
- **Historique/statistiques des tickets walk-in** (temps d'attente réel vs estimé, taux d'abandon).
  Une table `queue_tickets` persistée permet cette analyse plus tard, mais aucun écran ni agrégat
  n'est livré par #157.
- **Affinage de la formule d'ETA au-delà de la V1** (données historiques, durée par coiffeuse,
  pondération par prestation) — explicitement une **heuristique V1 assumée perfectible**.
- **Modification de la matrice `ROLE_PERMISSIONS` pour `CLIENT`/`HAIRDRESSER`/`MANAGER`/`ADMIN`.**
  Les permissions existantes (`APPOINTMENT_UPDATE_STATUS` notamment, réutilisée pour la prise en
  charge — voir *Proposed Implementation §D*) ne sont pas élargies ; seule une permission **nouvelle
  et minimale** est nécessaire côté `KIOSK` (propriété de #155, simplement nommée ici).

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

`docs/adr/` s'arrête aujourd'hui à **ADR-0040** ; les deux numéros suivants sont pris par le jalon,
à raison d'une décision par ADR (pratique du dépôt : l'ADR atterrit avec la PR de la fonctionnalité,
cf. ADR-0039 avec #148 et ADR-0040 avec #154) : **ADR-0041**
(`docs/adr/0041-authentification-borne-kiosque.md`, committée avec l'implémentation de #155) et
**ADR-0042** (`docs/adr/0042-file-attente-walkin-queue-ticket.md`, committée avec l'implémentation
de #157 — cette spec en constitue la matière première). #161 (US-8.7) n'écrit pas d'ADR consolidée :
il vérifie la présence des deux ADR et met à jour l'index `docs/adr/README.md` en fin de jalon.

### File d'attente existante (#150/#152, PR #153) — à ne pas confondre

- `coiflink_api/domain/queue.py:40-72` : `QueueStatus` (`waiting`/`in_progress`/`completed`/`paid`),
  `QUEUE_APPOINTMENT_STATUSES = (CONFIRMED, COMPLETED)`, `derive_queue_status` — dérive **toujours**
  d'un `Appointment` réel. Rien ici ne connaît de numéro de passage.
- `coiflink_api/application/queue.py:52-180` : `MarkAppointmentArrived`, `StartAppointmentService`
  (préconditions `arrived_at`/`hairdresser_id` avant `started_at`, erreurs
  `AppointmentArrivalRequired`/`AppointmentHairdresserRequired`, `domain/errors.py:290-308`),
  `ListSalonQueue` (compose `AppointmentRepository.list_queue_details` +
  `PaymentRepository.list_paid_appointment_ids`).
- `coiflink_api/adapters/inbound/appointments.py:289-307` : `QueueEntryResponse` (`appointment_id`,
  `client_name`, `service_names`, `hairdresser_id`/`name`, `start_time`/`end_time`, `status`,
  `queue_status`, `arrived_at`, `started_at`) — **aucun** champ numéro/position/ETA.
- `coiflink_api/adapters/inbound/appointments.py:1234-1272` : route `GET /salons/{salon_id}/queue`,
  gardée `require_salon_scope` + `require_permission(Permission.APPOINTMENT_READ_SALON)`, paramètre
  `day` optionnel (défaut `_today()`, `appointments.py:413-416`, fuseau `Africa/Abidjan`).
- Migration `0011` (`backend/migrations/versions/0011_employee_profile_and_appointment_pointage.py`)
  a ajouté `appointments.arrived_at`/`started_at` — colonnes **nullables**, **aucun** compteur.
- Web : `web-dashboard/app/(gerant)/gerant/file-attente/page.tsx` +
  `web-dashboard/src/adapters/ui/queue-board.tsx` consomment `GET /salons/{salon_id}/queue` ; c'est
  le seul écran que le critère d'acceptation de #157 vise en écrivant « la file gérant existante ».

### Modèle Appointment/Payment pertinent pour le « pont »

- `coiflink_api/adapters/outbound/persistence/models.py:298-372` (`Appointment`) : `client_id`
  **`NOT NULL`** (FK `users`, `ondelete="RESTRICT"`), `hairdresser_id` nullable,
  `appointment_date`/`start_time`/`end_time` **requis** (composent la colonne générée `slot`,
  support de l'exclusion anti-double-réservation). Un ticket walk-in n'a, par construction, ni
  `client_id` (compte) ni créneau réel connu à l'avance — les deux raisons pour lesquelles
  `AppointmentToCreate` ne peut pas représenter un walk-in.
- `coiflink_api/adapters/outbound/persistence/models.py:470-528` (`Payment`) : `appointment_id` et
  `client_id` **nullables**, seul `salon_id`/`amount`/`payment_method`/`recorded_by` sont requis —
  déjà exploitable pour un encaissement comptoir sans RDV ni compte client (cf. *Problem Statement*).
- `coiflink_api/application/ports/appointment_repository.py:412-448` /
  `coiflink_api/adapters/outbound/persistence/appointment_repository.py:369-416` : `mark_arrived`/
  `mark_started`, écriture `UPDATE ... WHERE status = 'CONFIRMED'` — condition qui n'existera jamais
  pour un ticket walk-in (il n'y a pas de ligne `appointments` à mettre à jour).

### Catalogue / prestations / coiffeuses actives (dénominateurs de l'ETA)

- `coiflink_api/domain/service.py:193-215` (`Service`) : `duration_minutes: int` (> 0, ≤ 24 h,
  `validate_duration`, `service.py:102-120`) — source de la « durée moyenne des prestations
  demandées ».
- `coiflink_api/adapters/outbound/persistence/salon_catalog_repository.py:105-118` :
  `list_active_hairdressers(salon_id)` — filtre `salon_members.role = HAIRDRESSER AND status =
  ACTIVE`, déjà utilisé par le catalogue public (#150). Réutilisable **tel quel** comme dénominateur
  de l'ETA (aucun nouveau dépôt à écrire pour ce chiffre).
- `coiflink_api/adapters/outbound/persistence/models.py:264-296` (`Service`) : `is_active` (colonne
  `Boolean`), pas de champ « durée moyenne » précalculé — la moyenne est calculée à la volée par le
  cas d'usage (voir *Proposed Implementation §D*).

### CustomerProfile (consommé, pas modifié)

- `coiflink_api/adapters/outbound/persistence/models.py:414-465` : `id`, `salon_id`, `user_id`
  (nullable), `full_name`, `phone` (nullable), `gender`, `notes`, `last_visit_at`, `total_visits`.
  Unicité **partielle par salon** `(salon_id, phone) WHERE phone IS NOT NULL`
  (`models.py:459-465`).
- `coiflink_api/domain/customer.py:164-179` (`Customer`) : **n'expose pas** `user_id` (anti-oracle,
  ADR-0026) — `QueueTicket.customer_profile_id` référence la fiche, jamais un compte.
- Le port `CustomerRepository` actuel (`application/ports/customer_repository.py:29-172`) n'a pas
  encore de `find_by_phone` (c'est le livrable de #156) ; #157 ne dépend que de `find_by_id`/`create`
  déjà présents, plus le futur `find_by_phone` de #156 en amont du flux (côté borne, pas côté
  `QueueTicket` lui-même : le ticket ne fait que porter un `customer_profile_id` déjà résolu).

### Numérotation séquentielle par salon — patron à décliner (#154, ADR-0040)

- `coiflink_api/adapters/outbound/persistence/payment_repository.py:57-89` (`SqlPaymentRepository.
  create`) : `SELECT pg_advisory_xact_lock(hashtext(:salon_id))` puis
  `SELECT COALESCE(MAX(receipt_number), 0) + 1 WHERE salon_id = :salon_id`, dans la **même**
  transaction que l'`INSERT` — le verrou est relâché au commit/rollback piloté par `get_session`.
  Migration `0012` (`migrations/versions/0012_payment_receipt_number.py`) ajoute la colonne et la
  contrainte `UNIQUE (salon_id, receipt_number)` comme filet base.
- `docs/adr/0040-impression-recu-encaissement-gerant.md:34-43` documente le compromis : « pas de
  nouvelle table de compteur, pas de nouvelle frontière de transaction ».
- Différence pour #157 : la portée du compteur est **salon + jour civil**, pas seulement salon
  (`ticket_number` redémarre chaque jour). La clé de verrou doit donc encoder les deux (voir
  *Proposed Implementation §A*).

### Fuseau / jour civil du salon

- `coiflink_api/domain/time_window.py:22` : `SALON_TIMEZONE = ZoneInfo("Africa/Abidjan")` (UTC+0,
  sans heure d'été). `day_start_utc`/`day_end_utc` (`time_window.py:24-37`) convertissent un jour
  civil salon en bornes UTC. `adapters/inbound/appointments.py:413-416` (`_today()`) l'utilise déjà
  pour le paramètre `day` de `GET /salons/{salon_id}/queue`.

## Proposed Implementation

### (A) Domaine `QueueTicket` — entité, validation, migration

**Nouveau fichier `backend/coiflink_api/domain/queue_ticket.py`** (pur, aucune I/O) :

```python
QueueTicketStatus = Literal["waiting", "called", "in_progress", "done", "expired"]
QUEUE_TICKET_STATUSES: tuple[QueueTicketStatus, ...] = (
    "waiting", "called", "in_progress", "done", "expired",
)
# Transitions fermées, miroir du style AppointmentStatus :
# waiting -> called -> in_progress -> done
# waiting -> expired (jamais pris en charge, purge de fin de journée)
# called  -> expired (appelé mais jamais présenté, purge de fin de journée)

@dataclass(frozen=True)
class QueueTicketToCreate:
    salon_id: uuid.UUID
    customer_profile_id: uuid.UUID | None   # None = client refuse de laisser un nom (voir Open Q.)
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

`service_ids` : au moins une prestation requise (`InvalidQueueTicketServices` si vide), miroir de
`AppointmentServiceRequired` (`domain/errors.py:234-241`). `estimated_wait_minutes` est **calculé une
fois à l'émission** (par le cas d'usage, cf. §D) et stocké tel quel — pas de recalcul dynamique en
lecture : un ticket affiche une estimation stable, cohérente avec ce qui a été imprimé (#160), même
si la file évolue ensuite. `called_at`/`started_at`/`completed_at` sont des horodatages **distincts**
du `status`, dans le même esprit que `arrived_at`/`started_at` sur `Appointment`
(`domain/queue.py`) — mais volontairement **non partagés** avec cette table (voir §C pour la
justification : pas de ligne `appointments` sous-jacente).

**Nouvelles erreurs (`domain/errors.py`)**, à la suite de `AppointmentHairdresserRequired`
(ligne 300) pour rester groupées par thème :

- `InvalidQueueTicketServices` — `service_ids` vide ou contient une prestation inactive/hors salon.
- `QueueTicketNotFound` — ticket inexistant **ou** hors salon (indiscernables, §11.2, miroir
  `AppointmentNotFound`).
- `InvalidQueueTicketTransition` — transition hors machine à états (miroir
  `InvalidAppointmentTransition`), couvre aussi la prise en charge d'un ticket déjà `in_progress`/
  `done`/`expired` (garde TOCTOU sur double-clic concurrent).
- `QueueTicketHairdresserRequired` — tentative de passage `in_progress` sans `hairdresser_id` (miroir
  exact de `AppointmentHairdresserRequired`, même message d'intention : « une prestation en cours
  sans coiffeuse n'a pas de sens métier »).

**Migration `backend/migrations/versions/0014_queue_tickets.py`** (`revision = "0014"`,
`down_revision = "0013"` — la migration `0013_kiosk_role.py` appartient à #155, dont #157 dépend ;
**à revalider à l'implémentation** selon l'ordre réel de merge des migrations du jalon, coordination
à faire en amont de l'implémentation, cf. *Risks and Open Questions*) :

```python
op.create_table(
    "queue_tickets",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
              server_default=sa.text("gen_random_uuid()")),
    sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("ticket_number", sa.Integer(), nullable=False),
    sa.Column("issued_date", sa.Date(), nullable=False),
    sa.Column("customer_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("hairdresser_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("status", sa.String(length=32), nullable=False,
              server_default=sa.text("'waiting'")),
    sa.Column("estimated_wait_minutes", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
              server_default=sa.text("now()")),
    sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
)
op.create_foreign_key(
    "fk_queue_tickets_salon_id", "queue_tickets", "salons",
    ["salon_id"], ["id"], ondelete="RESTRICT",
)
op.create_foreign_key(
    "fk_queue_tickets_customer_profile_id", "queue_tickets", "customer_profiles",
    ["customer_profile_id"], ["id"], ondelete="RESTRICT",
)
op.create_foreign_key(
    "fk_queue_tickets_hairdresser_id", "queue_tickets", "users",
    ["hairdresser_id"], ["id"], ondelete="RESTRICT",
)
# Filet base : le compteur ne se chevauche jamais, même en cas de bug applicatif.
op.create_unique_constraint(
    "uq_queue_tickets_salon_day_number", "queue_tickets",
    ["salon_id", "issued_date", "ticket_number"],
)
op.create_check_constraint(
    "ck_queue_tickets_status", "queue_tickets",
    "status IN ('waiting','called','in_progress','done','expired')",
)
op.create_index("ix_queue_tickets_salon_id_status", "queue_tickets", ["salon_id", "status"])

op.create_table(
    "queue_ticket_services",
    sa.Column("queue_ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.PrimaryKeyConstraint("queue_ticket_id", "service_id",
                             name="pk_queue_ticket_services"),
)
op.create_foreign_key(
    "fk_queue_ticket_services_ticket", "queue_ticket_services", "queue_tickets",
    ["queue_ticket_id"], ["id"], ondelete="CASCADE",   # jonction pure-dépendante, miroir appointment_services
)
op.create_foreign_key(
    "fk_queue_ticket_services_salon_service", "queue_ticket_services", "services",
    ["salon_id", "service_id"], ["salon_id", "id"], ondelete="RESTRICT",
)
```

`hairdresser_id` référence `users.id` — **miroir exact** d'`Appointment.hairdresser_id`
(`models.py:298-372`, `ForeignKeyConstraint(["hairdresser_id"], ["users.id"], ondelete="RESTRICT")`) :
vérifié par lecture directe du modèle, un rendez-vous **ne** référence **jamais** `salon_members.id`
pour sa coiffeuse — c'est un identifiant de **compte**, dont l'appartenance au salon est vérifiée
**applicativement**, jamais par la FK elle-même. `list_active_hairdressers` (§ ci-dessus) le confirme
côté lecture : `Employee.id` **est explicitement documenté** comme « l'`id` du compte `users` »
(`domain/employee.py:55-56`), pas un identifiant `salon_members`. `QueueTicket.hairdresser_id` suit
donc la **même** convention, pour rester directement assignable depuis le même
`list_active_hairdressers(salon_id)` sans traduction d'identifiant, et pour que
`StartQueueTicket` (§D) réutilise **au mot près** le contrôle d'appartenance déjà écrit
(`_require_salon_hairdresser`/`SalonScopeRepository.salon_ids_for(hairdresser_id, Role.HAIRDRESSER)`,
`application/appointments.py:142-159` — lit `salon_members WHERE user_id = … AND status = 'ACTIVE'`,
sans jamais faire de `salon_members.id` une clé étrangère) plutôt que d'inventer une deuxième forme de
contrôle d'appartenance propre au ticket. `queue_ticket_services` reprend le patron
`appointment_services` (`models.py:373-411`, FK composite `(salon_id, service_id)` forçant
l'appartenance salon, `ondelete="CASCADE"` car purement dépendante de son ticket).
`downgrade()` : `drop_table("queue_ticket_services")` puis `drop_table("queue_tickets")` (les FK
disparaissent avec les tables ; ordre inverse de création pour respecter les dépendances).

**Mise à jour miroir de `models.py`** : nouvelles classes ORM `QueueTicket`/`QueueTicketService`,
strictement reflet de la migration (convention du dépôt : `models.py` = source de vérité versionnée,
toute divergence casse le round-trip Alembic de la CI).

### (B) Numérotation séquentielle — verrou par salon **et** jour civil

Déclinaison directe du patron ADR-0040, avec une clé de verrou combinant `salon_id` et le jour civil
(`SALON_TIMEZONE`) pour que le compteur reparte à 1 chaque jour sans dépendre d'un job de purge :

```python
def create(self, ticket: QueueTicketToCreate, *, issued_date: datetime.date) -> QueueTicket:
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
    ...
```

- `hashtext(text)` retourne un entier 32 bits stable pour une même chaîne : concaténer `salon_id` et
  `issued_date` dans **une seule** clé (plutôt que deux entiers avec la forme à deux arguments de
  `pg_advisory_xact_lock`) reproduit exactement la forme déjà en production pour `receipt_number`,
  au prix d'un risque de collision de hachage **théorique** entre deux salons/jours différents — ce
  risque existe déjà pour `receipt_number` (accepté par ADR-0040) et n'a pas de conséquence
  fonctionnelle ici : une collision ne ferait que sérialiser à tort deux verrous indépendants
  (perte de parallélisme, jamais de corruption de données — la vraie garantie vient de la contrainte
  `UNIQUE` en base).
- Le verrou est **transactionnel** (`_xact_lock`), relâché automatiquement au commit/rollback déjà
  piloté par `get_session` — aucune nouvelle gestion de connexion, aucun risque de verrou orphelin en
  cas de crash applicatif (PostgreSQL le libère à la fin de la session serveur).
- `issued_date` est passé explicitement par le cas d'usage (horloge injectée, testable), jamais
  recalculé par le dépôt — cohérent avec le patron `_utc_now`/`clock` de `application/queue.py:46-49`.
- Filet de dernier recours : `uq_queue_tickets_salon_day_number` (contrainte `UNIQUE` base) — si le
  verrou consultatif était contourné par un futur chemin d'écriture, la contrainte transforme une
  collision en `IntegrityError` retraduite en une erreur de domaine plutôt qu'une corruption
  silencieuse (miroir `CustomerAlreadyExists`/`uq_customer_profiles_salon_phone`).

Alternative écartée : une **séquence PostgreSQL nommée par salon** (`CREATE SEQUENCE
queue_ticket_seq_<salon_id>`) redémarrée chaque jour par un job planifié. Écartée parce qu'elle
introduirait une **DDL dynamique par salon** (une séquence par salon, potentiellement des milliers),
un job de reset à opérer de façon fiable en heure locale du salon, et une dépendance opérationnelle
(cron) que le dépôt n'a nulle part ailleurs — le patron verrou+`MAX+1` déjà en production pour les
reçus est strictement plus simple à opérer et à tester.

### (C) Indépendance vis-à-vis d'`Appointment` et forme du « pont »

**Pourquoi `QueueTicket` ne réutilise pas `appointments` :**

1. **Contrainte bloquante** : `Appointment.client_id` est `NOT NULL` (FK `users`). Un walk-in
   identifié par #156 a, dans le cas général, une `CustomerProfile.user_id = NULL` — il n'existe
   littéralement rien à mettre dans `client_id`. Exiger un compte pour délivrer un ticket
   contredirait l'objectif même du parcours walk-in du jalon M7.
2. **Aucun créneau réel** : `appointment_date`/`start_time`/`end_time` sont requis et alimentent la
   colonne générée `slot` (anti-double-réservation par exclusion base). Un walk-in n'a, par
   définition, ni date ni heure de créneau prévue à l'avance — seulement une estimation qui peut
   dériver.
3. **Cycle de vie différent** : un `Appointment` porte une réservation (client engagé à l'avance,
   annulable, modifiable, avec rappels §Épic 6) ; un `QueueTicket` porte une présence physique
   immédiate et un cycle de vie de quelques dizaines de minutes, sans notion d'annulation/
   modification à distance.

**Forme du pont retenue : fusion en lecture, jamais en écriture.** `GET /salons/{salon_id}/queue`
compose une **troisième source** en plus des deux existantes (RDV + paiements) :
`QueueTicketRepository.list_active_for_salon(salon_id, day)` (tickets du jour aux statuts
`waiting`/`called`/`in_progress`/`done`, hors `expired` — le gérant doit voir les tickets `waiting`
pour pouvoir les appeler, et le critère d'acceptation « apparaît dans la file une fois pris en
charge » est ainsi satisfait a fortiori), sans jamais créer, mettre à jour ni référencer une ligne
`appointments`. Chaque ticket actif est projeté en une entrée dédiée sous la clé `walk_in_tickets`
(voir *API / Interface Changes* pour le schéma exact), plutôt qu'en une pseudo-entrée RDV avec un
`appointment_id` fictif. Justification du choix « fusion en lecture » plutôt que « fusion en
écriture » (répond au point (f) de la mission) :

- Le critère d'acceptation de #157 (« il apparaît dans la file gérant existante une fois pris en
  charge ») exige une **visibilité unifiée**, pas une **persistance unifiée** — la contrainte
  `client_id NOT NULL` (point 1 ci-dessus) rend de toute façon la persistance unifiée impraticable
  sans un changement de schéma qui déborderait très largement l'effort L déjà alloué à #157 et
  fragiliserait un chemin d'écriture éprouvé (réservation client, #21/#22).
- Une fusion **en écriture** obligerait à choisir un pseudo-`client_id` (compte technique
  « walk-in » partagé ?) — solution rejetée : elle polluerait toutes les lectures « mes rendez-vous »
  d'un compte qui n'appartient à personne, et casserait l'hypothèse implicite `client_id → un seul
  client réel` exploitée ailleurs (stats, notifications, historique).
- Une fusion **en lecture** n'exige aucune modification de `AppointmentRepository` ni de
  `PaymentRepository` : elle ajoute une source, sans toucher aux deux existantes
  (`ListSalonQueue.execute` reste appelable seul pour quiconque ne s'intéresse qu'aux RDV
  planifiés) ; seuls `tests/test_queue_api.py` et la forme de la réponse HTTP évoluent avec l'objet
  à deux clés.

**Ce qui **est** réutilisé, au niveau du patron plutôt que du code** (répond explicitement au point
(c) de la mission — « comment réutiliser `MarkAppointmentArrived` et le cycle `arrived_at`/
`started_at` sans dupliquer la logique ») :

- Le **nom des préconditions et leur ordre de vérification** : `StartQueueTicket` (nouveau cas
  d'usage, §D) vérifie `hairdresser_id is not None` exactement comme `StartAppointmentService`
  (`application/queue.py:117-124`) vérifie `arrived_at`/`hairdresser_id`, avec la **même** erreur de
  forme (`QueueTicketHairdresserRequired`, miroir texte de `AppointmentHairdresserRequired`).
- Le **patron d'écriture idempotente et conditionnelle** : `mark_started`
  (`appointment_repository.py:395-416`) fait un `UPDATE ... WHERE status = 'CONFIRMED'` puis ne pose
  l'horodatage que s'il est encore `None` — `SqlQueueTicketRepository.start` reproduit exactement
  cette forme (`UPDATE ... WHERE status = 'waiting'`), pour la même raison (garde TOCTOU contre un
  double-clic ou une prise en charge concurrente par deux coiffeuses).
- Le **patron d'audit neutre** : `AuditAction.APPOINTMENT_STARTED` (`domain/audit.py:137-138`) a pour
  miroir `AuditAction.QUEUE_TICKET_STARTED` avec `metadata={}` (aucune PII), même schéma d'entrée.

Aucune fonction n'est partagée bit à bit entre les deux chemins parce qu'ils opèrent sur des tables
différentes avec des conditions `WHERE` différentes — la réutilisation porte sur la **conception**,
pas sur l'implémentation, ce qui est le niveau de réutilisation honnête compte tenu de la contrainte
`client_id NOT NULL` documentée ci-dessus.

### (D) Cas d'usage (`application/queue_ticket.py`, nouveau fichier)

Dépend uniquement des ports `QueueTicketRepository` (nouveau), `CustomerRepository` (lecture, existant),
`SalonCatalogRepository`-like (`list_active_hairdressers`, déjà existant côté
`salon_catalog_repository.py`, exposé par un port dédié ou réutilisé via un port de lecture salon —
à trancher à l'implémentation selon le découpage exact de #155/#156), `AuditLog`.

- **`JoinQueue.execute(salon_id, command, *, clock) -> QueueTicket`** (le cas d'usage de l'endpoint
  « rejoindre la file », §E) :
  1. valide `service_ids` (non vide, chaque `Service` actif et du salon — `InvalidQueueTicketServices`
     sinon) ;
  2. si `customer_profile_id` est fourni, vérifie son appartenance au salon
     (`CustomerRepository.find_by_id(salon_id, id)`, sinon `QueueTicketNotFound` — indiscernable
     d'une fiche d'un autre salon, §11.2) ;
  3. calcule `estimated_wait_minutes` (formule ci-dessous) ;
  4. `repository.create(QueueTicketToCreate(...), issued_date=today)` — alloue `ticket_number` sous
     verrou (§B) ;
  5. **pas d'audit** pour la création : un ticket walk-in n'est pas une action de gestion sensible au
     sens §11.4 (à la différence de `CUSTOMER_CREATED`, il ne porte aucune PII propre — seulement un
     numéro et une liste de prestations) ; **à confirmer**, voir *Risks and Open Questions*.
- **Formule d'ETA (V1, fonction pure `domain/queue_ticket.py::estimate_wait_minutes`)** :

  ```python
  def estimate_wait_minutes(
      *,
      position: int,                       # tickets `waiting` déjà devant celui-ci (0-indexé)
      average_service_minutes: float,       # moyenne des durées des prestations des tickets actifs
      active_hairdresser_count: int,
  ) -> int:
      if active_hairdresser_count <= 0:
          return DEFAULT_WAIT_MINUTES_NO_STAFF   # constante documentée, ex. 30 — filet dégénéré
      raw = (position * average_service_minutes) / active_hairdresser_count
      return max(0, round(raw))
  ```

  - `position` = nombre de tickets `waiting` déjà présents dans la file **avant** l'insertion du
    nouveau ticket (le nouveau ticket lui-même n'attend pas derrière lui-même).
  - `average_service_minutes` = moyenne des `duration_minutes` des prestations liées aux tickets
    actuellement `waiting` **et** `in_progress` du salon (file réellement à écouler) ; si aucun ticket
    actif n'existe encore (le nouveau est le premier de la journée), repli sur la moyenne des
    `duration_minutes` des **prestations demandées par ce ticket lui-même** — jamais une constante
    arbitraire ni la moyenne de tout le catalogue (qui inclurait des prestations jamais demandées ce
    jour-là).
  - `active_hairdresser_count` = `len(list_active_hairdressers(salon_id))`. Filet explicite si `0`
    (salon sans coiffeuse active pointée — configuration incomplète mais pas à faire planter la
    borne) : une constante de repli documentée, **pas** une division par zéro masquée.
  - **Limites explicites, assumées V1** : ne tient pas compte de la progression réelle des
    prestations `in_progress` (une coiffeuse à 2 minutes de finir compte comme une à 30), ne
    distingue pas les coiffeuses par spécialité/prestation demandée, ne s'appuie sur **aucune**
    donnée historique (temps réel observé vs estimé) — cohérent avec la décision produit du jalon
    (« heuristique simple assumée comme perfectible »).
- **`StartQueueTicket.execute(salon_id, ticket_id, hairdresser_id, actor_id, *, clock) ->
  QueueTicket`** : charge le ticket `(salon_id, ticket_id)` (`QueueTicketNotFound` sinon), exige
  `status == "waiting"` (sinon `InvalidQueueTicketTransition`), assigne `hairdresser_id` (validé
  membre `ACTIVE` du salon — miroir `HairdresserNotInSalon`), passe `in_progress`, pose
  `started_at`, journalise `QUEUE_TICKET_STARTED` (`metadata={}`). Combine en une seule opération ce
  qui serait, côté RDV, deux étapes (`AssignHairdresser` + `StartAppointmentService`) : un ticket
  walk-in n'a jamais de coiffeuse pré-assignée (hors scope M7, cf. *Non-Goals* du jalon), l'assignation
  et le démarrage ne font donc qu'un seul geste métier pour la coiffeuse qui « prend » le client.
- **`CompleteQueueTicket.execute(salon_id, ticket_id, actor_id, *, clock) -> QueueTicket`** : exige
  `status == "in_progress"`, passe `done`, pose `completed_at`, journalise `QUEUE_TICKET_COMPLETED`.
- **`ListSalonQueueTickets.execute(salon_id, day) -> tuple[QueueTicket, ...]`** : lecture pure,
  triée `ticket_number ASC`, pour l'écran borne « votre position » (si #159 en a besoin) et pour
  l'extension de `ListSalonQueue` (§C).
- **Expiration** (`waiting`/`called` → `expired`) : **non livrée par #157** en tant qu'automatisme
  planifié (pas de job cron dans ce dépôt) ; un ticket non pris en charge en fin de journée reste
  visible avec son `status` d'origine jusqu'à ce qu'une action explicite (manuelle, ou un futur
  endpoint) le marque `expired`. Documenté comme limite V1, voir *Risks and Open Questions*.

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
patron `flush()` sans `commit()` des autres dépôts (atomicité pilotée par `get_session`).
`average_requested_duration_minutes` s'implémente en un `SELECT AVG(services.duration_minutes)` via
un jointure `queue_ticket_services → services`, filtré sur les tickets `waiting`/`in_progress` du
jour — une seule requête agrégée, pas de calcul en mémoire sur N lignes.

### (F) Adapter entrant (HTTP) — endpoint « rejoindre la file »

**`adapters/inbound/queue_tickets.py`** (nouveau routeur, `prefix="/salons"`, tag `queue-tickets`),
monté dans `main.py` avec un commentaire de câblage dans le style existant (permission, portée,
absence de `PUBLIC_ROUTE_PATHS`). Détail de la route dans *API / Interface Changes*.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer

| Fichier | Rôle |
| --- | --- |
| `coiflink_api/domain/queue_ticket.py` | entités pures, machine à états, `estimate_wait_minutes` |
| `coiflink_api/application/ports/queue_ticket_repository.py` | port `Protocol` |
| `coiflink_api/application/queue_ticket.py` | `JoinQueue`, `StartQueueTicket`, `CompleteQueueTicket`, `ListSalonQueueTickets` |
| `coiflink_api/adapters/outbound/persistence/queue_ticket_repository.py` | `SqlQueueTicketRepository` |
| `coiflink_api/adapters/inbound/queue_tickets.py` | router `/salons/{salon_id}/queue/tickets` (KIOSK + gérant/coiffeuse) |
| `migrations/versions/0014_queue_tickets.py` | tables `queue_tickets` + `queue_ticket_services` |
| `tests/test_domain_queue_ticket.py`, `tests/test_queue_ticket_usecases.py`, `tests/test_queue_ticket_api.py`, `tests/test_queue_ticket_e2e.py` | tests |

### Backend — à modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/errors.py` | `InvalidQueueTicketServices`, `QueueTicketNotFound`, `InvalidQueueTicketTransition`, `QueueTicketHairdresserRequired` |
| `coiflink_api/domain/audit.py` | `ENTITY_TYPE_QUEUE_TICKET`, `AuditAction.QUEUE_TICKET_STARTED`/`QUEUE_TICKET_COMPLETED` |
| `coiflink_api/adapters/outbound/persistence/models.py` | classes ORM `QueueTicket`/`QueueTicketService`, reflet de `0014` |
| `coiflink_api/application/queue.py` | `ListSalonQueue` étendu pour composer une 3ᵉ source (tickets du jour `waiting`/`called`/`in_progress`/`done`), voir §C |
| `coiflink_api/adapters/inbound/appointments.py` | réponse `GET .../queue` restructurée en objet à deux clés `appointments`/`walk_in_tickets` (cf. *API*) |
| `coiflink_api/main.py` | `include_router(queue_tickets_router)` + commentaire de câblage |
| `backend/README.md` | section « File d'attente walk-in (US-8.3, #157) » |
| `tests/conftest.py` | `FakeQueueTicketRepository` + fixture |
| `tests/test_domain_audit.py` | nouvelles actions/entité couvertes |
| `tests/test_queue_api.py` | vérifie la non-régression du contenu RDV (clé `appointments`) + la nouvelle clé `walk_in_tickets` |

### Documentation (racine)

`docs/adr/0042-file-attente-walkin-queue-ticket.md` (nouvelle ADR, committée avec l'implémentation
de #157) + `docs/adr/README.md` (entrée correspondante),
`README.md` (statut M7 amorcé, une fois #155/#156 livrées).

### À lire (sans modifier) pour rester fidèle aux patrons

`application/queue.py`, `domain/queue.py`, `adapters/outbound/persistence/appointment_repository.py`
(lignes 369-416, 695-730), `adapters/outbound/persistence/payment_repository.py` (lignes 57-89),
`adapters/outbound/persistence/salon_catalog_repository.py` (lignes 90-118), `domain/errors.py`
(lignes 234-308), `docs/adr/0040-impression-recu-encaissement-gerant.md`.

## API / Interface Changes

### Nouveau — rejoindre la file (walk-in)

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/queue/tickets` | rôle `KIOSK` (#155) + portée device→salon + `Permission.QUEUE_TICKET_CREATE` (nom canonique fixé par #155, déclarée dans sa matrice ; seul l'ordre de merge reste à coordonner) | `201` ticket · `401`/`403` (device invalide/hors salon) · `404` fiche client hors salon · `422` prestation(s) invalide(s) |

```jsonc
// POST /salons/{salon_id}/queue/tickets — corps
{
  "customer_profile_id": "…uuid…",   // optionnel : null = client anonyme (voir Open Questions)
  "service_ids": ["…uuid…"]          // >= 1, prestations actives du salon
}

// 201 — réponse
{
  "id": "…uuid…",
  "ticket_number": 7,
  "issued_date": "2026-08-10",
  "status": "waiting",
  "estimated_wait_minutes": 18,
  "created_at": "2026-08-10T09:12:00Z",
  "service_ids": ["…uuid…"]
}
```

`ticket_number` est exposé comme un **entier brut**, dans l'API comme dans le domaine : le formatage
d'affichage (« N° 014 », zéro-padding) est la responsabilité exclusive du formatter ESC/POS de #160
(sur le modèle de `format_receipt_number`, `backend/coiflink_api/domain/receipt.py:95-107`) — jamais
une chaîne pré-formatée par #157.

Cette route n'est **pas** ajoutée à `PUBLIC_ROUTE_PATHS` : « public/kiosk » signifie *atteignable
depuis un terminal en salle d'accueil*, pas *sans authentification* — le device s'identifie avec le
credential posé par #155 (deny-by-default inchangé). Le `salon_id` du chemin doit correspondre au
salon figé du device (§11.2, décision M7 #8 « borne mono-salon ») : toute divergence renvoie le
`403` générique existant, jamais un `404` qui confirmerait l'existence du salon visé.

### Nouveau — prise en charge / clôture (gérant, coiffeuse)

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/queue/tickets/{ticket_id}/start` | `require_salon_scope` + `require_permission(Permission.APPOINTMENT_UPDATE_STATUS)` *(réutilisation proposée — même acteurs que le démarrage d'un RDV : coiffeuse et gérant, voir Open Questions)* | `200` ticket · `401`/`403` · `404` · `409` (déjà pris en charge / transition invalide) |
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
  "started_at": "2026-08-10T09:20:00Z",
  "completed_at": null
}
```

### Modifié — `GET /salons/{salon_id}/queue` (rupture de forme mineure et assumée)

La réponse actuelle (`list[QueueEntryResponse]`) est **remplacée** par un objet
englobant pour porter les deux sources sans ambiguïté (changement de forme du corps réponse,
documenté comme **rupture mineure et assumée** de ce seul endpoint — voir justification ci-dessous) :

```jsonc
// 200 — GET /salons/{salon_id}/queue?day=2026-08-10
{
  "appointments": [ /* QueueEntryResponse existants, structure inchangée champ à champ */ ],
  "walk_in_tickets": [
    {
      "ticket_id": "…uuid…",
      "ticket_number": 7,
      "customer_first_name": "Awa",      // jamais le nom complet (miroir décision #156)
      "service_names": ["Tresses"],
      "hairdresser_id": "…uuid…",
      "hairdresser_name": "…",
      "status": "in_progress",           // tickets du jour waiting/called/in_progress/done (hors expired)
      "started_at": "2026-08-10T09:20:00Z",
      "completed_at": null
    }
  ]
}
```

**Décision tranchée (point (f) de la mission) : les deux files restent des tableaux distincts dans
la même réponse, jamais fusionnées en une liste unique.** Justification :

- Un `QueueEntryResponse` (RDV) porte `appointment_id`, `start_time`, `end_time` — des champs qui
  n'ont pas de sens pour un ticket walk-in (pas de créneau planifié). Forcer les deux formes dans un
  seul type de ligne obligerait soit à rendre ces champs nullables sur le type existant (fuite de
  complexité walk-in vers un contrat qui n'en avait pas besoin), soit à un type union côté web —
  plus complexe à consommer que deux tableaux nommés.
- Le tri naturel diffère : les RDV se trient par `start_time` (heure planifiée), les tickets par
  `ticket_number` (ordre d'arrivée) — les mélanger dans une seule liste triée exigerait une clé de tri
  artificielle sans signification métier claire pour le gérant.
- Le critère d'acceptation (« apparaît dans la file gérant existante ») est satisfait : les deux
  tableaux vivent dans la **même réponse HTTP** du **même endpoint**, affichés sur le **même écran**
  (`queue-board.tsx` à adapter côté web, hors périmètre backend de #157) — sans qu'une fusion
  structurelle soit nécessaire pour cela.
- Les tickets **du jour** aux statuts `waiting`/`called`/`in_progress`/`done` (hors `expired`)
  apparaissent ici — le gérant doit voir les tickets `waiting` pour pouvoir les appeler, et le
  critère d'acceptation (« apparaît dans la file une fois pris en charge ») est ainsi satisfait
  a fortiori.

Le changement de forme de la réponse (`list[...]` → objet à deux clés) casse, en théorie, tout client
HTTP qui désérialiserait strictement l'ancienne forme. Impact réel : le seul consommateur du dépôt est
`web-dashboard/src/adapters/ui/queue-board.tsx`, à mettre à jour dans la **même** PR (hors backend,
mais dépendance directe non contournable). Alternative moins intrusive envisagée et écartée : un
endpoint séparé `GET /salons/{salon_id}/queue/tickets` en plus de l'existant — écartée parce qu'elle
ne satisferait pas littéralement « apparaît dans la file gérant existante » (deux écrans/appels au
lieu d'un) sans bénéfice de compatibilité réel (le seul consommateur est modifié dans tous les cas).
**Point à confirmer par le porteur produit avant implémentation**, voir *Risks and Open Questions*.

## Data Model / Protocol Changes

**Oui** — une migration Alembic (`0014`, `down_revision = 0013` — la migration `0013_kiosk_role.py`
de #155 — à revalider selon l'ordre de merge avec #155/#156) créant deux tables, reflet du modèle
ORM :

1. `queue_tickets` : `id` (PK), `salon_id` (FK `salons`, `RESTRICT`), `ticket_number` (`INTEGER NOT
   NULL`), `issued_date` (`DATE NOT NULL`), `customer_profile_id` (FK `customer_profiles`, nullable,
   `RESTRICT`), `hairdresser_id` (FK `users`, nullable, `RESTRICT` — miroir exact
   d'`Appointment.hairdresser_id`, appartenance au salon vérifiée applicativement, jamais par la FK),
   `status` (`VARCHAR(32)` + `CHECK` dérivé de `QueueTicketStatus`), `estimated_wait_minutes`
   (`INTEGER NOT NULL`),
   `created_at`, `called_at`/`started_at`/`completed_at` (`TIMESTAMPTZ` nullable). Contrainte
   `UNIQUE (salon_id, issued_date, ticket_number)` — garantie base du compteur ; index
   `(salon_id, status)` pour les lectures filtrées par statut (file active).
2. `queue_ticket_services` : jonction `(queue_ticket_id, service_id)`, `salon_id` dupliqué pour la FK
   composite `(salon_id, service_id) → services(salon_id, id)` (force l'appartenance salon, miroir
   `appointment_services`), `ondelete="CASCADE"` sur `queue_ticket_id` (jonction pure-dépendante).
3. Aucune colonne existante (`appointments`, `payments`, `customer_profiles`, `services`) n'est
   modifiée — migration strictement additive.
4. `downgrade()` : `drop_table` des deux tables dans l'ordre inverse de création (exigé par le
   round-trip Alembic de la CI).

**Décision explicite non retenue** : ajouter un `appointment_id` nullable sur `queue_tickets` en
prévision d'un futur pont en écriture. Écartée pour ce jalon — un champ nullable jamais rempli en V1
serait une dette de schéma silencieuse ; si le pont en écriture devient un besoin réel plus tard
(ex. walk-in avec compte), la colonne s'ajoute alors par une migration dédiée, avec sa propre
justification.

## Security & Privacy Considerations

- **Aucune route publique.** `POST /salons/{salon_id}/queue/tickets` reste **protégée** par le
  credential `KIOSK` de #155 — jamais ajoutée à `PUBLIC_ROUTE_PATHS`. « Public/kiosk » qualifie
  l'usage (un terminal en salle d'accueil), pas le régime d'authentification (invariant deny-by-default
  inchangé).
- **Isolation par salon (§11.2), en profondeur.** Toutes les méthodes du port
  `QueueTicketRepository` filtrent `salon_id` en SQL ; un `customer_profile_id` d'un autre salon est
  refusé avec la **même** erreur (`QueueTicketNotFound`) qu'un id inexistant — aucun oracle
  d'existence inter-salons. Le device `KIOSK` ne peut de toute façon soumettre que le `salon_id`
  auquel il est provisionné (garde posée par #155) : une tentative de forger un autre `salon_id` dans
  le chemin est déjà interceptée avant d'atteindre ce cas d'usage.
- **Minimisation de la PII exposée à un écran public partagé.** `GET .../queue` (écran gérant, pas
  la borne) n'expose que `customer_first_name` pour un ticket walk-in — jamais le nom complet ni le
  téléphone —, cohérent avec la décision déjà prise pour l'identification (#156). L'écran borne
  lui-même (#159) n'affiche jamais d'identité d'un autre client que celui en cours d'interaction.
- **`customer_profile_id` nullable — ticket anonyme possible.** Un client qui refuse de laisser son
  identité (ou qui n'a pas de téléphone joignable au moment précis) doit pouvoir tout de même obtenir
  un ticket : `customer_profile_id = null` reste un cas valide côté domaine. Conséquence : le ticket
  n'alimente alors aucun historique de visite (`CustomerProfile.total_visits`/`last_visit_at` ne sont
  **pas** touchés par #157 dans tous les cas — ce n'est pas son rôle, voir *Non-Goals*). **Point à
  confirmer** avec le produit : la borne (#159) doit-elle réellement permettre de continuer sans
  identification, ou #156 rend-elle l'identification obligatoire avant `service_ids` ? Cette spec
  laisse la porte ouverte côté domaine sans trancher l'UX (propriété de #159).
- **Aucune donnée financière ni de santé sur un `QueueTicket`.** Contrairement à `CustomerProfile`
  (notes potentiellement sensibles, cf. spec #28) ou `Payment` (montants), un ticket ne porte que
  des identifiants opaques, une liste de prestations et des horodatages — surface de risque minimale.
- **Journalisation §11.4 ciblée sur les actions de gestion, pas sur l'émission.** `QUEUE_TICKET_STARTED`/
  `QUEUE_TICKET_COMPLETED` sont journalisées avec `metadata={}` (aucune PII, miroir
  `APPOINTMENT_ARRIVED`/`APPOINTMENT_STARTED`) ; la simple **création** d'un ticket par le device
  `KIOSK` n'est **pas** journalisée dans le journal d'audit **gérant** (elle ne correspond à aucune
  action humaine du personnel) — à confirmer, voir *Risks and Open Questions* (une trace d'accès
  device pourrait relever d'un futur journal d'activité borne, propriété de #155/#161, pas de #157).
- **Résistance à l'abus du terminal partagé.** Rien dans #157 n'empêche un utilisateur malveillant de
  la borne de créer des tickets en boucle (`service_ids` arbitraires) : un **débit maximal par
  device/minute** est une mitigation naturelle, mais relève de la garde `KIOSK` (#155) ou d'un
  middleware de rate-limiting transverse — **hors périmètre de #157**, signalé ici comme dépendance
  amont à vérifier avant mise en production du jalon.
- **Intégrité concurrente du numéro de ticket.** Comme pour `receipt_number`, le verrou consultatif
  sérialise les créations concurrentes du même salon+jour ; la contrainte `UNIQUE` base est le filet
  ultime — une violation improbable est retraduite en erreur de domaine, jamais en `IntegrityError`
  brute exposée au client.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O)

- **`tests/test_domain_queue_ticket.py`** :
  - `estimate_wait_minutes` : position `0` → attente minimale (`0` ou proche) ; position croissante
    → attente croissante ; `active_hairdresser_count = 0` → constante de repli documentée (jamais de
    `ZeroDivisionError`) ; arrondi cohérent (`round`, jamais de troncature silencieuse qui sous-estime
    l'attente) ;
  - transitions valides/invalides de `QueueTicketStatus` (table de vérité complète : les 5 statuts ×
    les transitions autorisées, miroir du test de machine à états d'`AppointmentStatus`) ;
  - `service_ids` vide → `InvalidQueueTicketServices` (fonction de validation pure).
- **`tests/test_queue_ticket_usecases.py`** (fakes `conftest.py`) :
  - `JoinQueue` : `ticket_number` alloué par le fake incrémente correctement par salon+jour distinct
    (deux salons ou deux jours ne se marchent jamais dessus) ; `customer_profile_id` d'un autre salon
    → `QueueTicketNotFound`, **aucune** écriture ; `customer_profile_id = None` accepté ;
    `estimated_wait_minutes` cohérent avec la formule (cas file vide, cas file non vide, cas 0
    coiffeuse active) ;
  - `StartQueueTicket` : refuse un ticket déjà `in_progress`/`done` (`InvalidQueueTicketTransition`)
    ; refuse une coiffeuse hors salon (`HairdresserNotInSalon`, réutilisation directe de l'erreur
    existante) ; audit `QUEUE_TICKET_STARTED` une seule fois, `metadata == {}` ;
  - `CompleteQueueTicket` : refuse un ticket encore `waiting` (jamais démarré) ;
  - `ListSalonQueueTickets` : ne renvoie que les tickets du salon/jour demandés, triés par
    `ticket_number`.
- **`tests/test_domain_audit.py`** : nouvelles actions/entité présentes et cohérentes.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_queue_ticket_api.py`** :
  - `POST .../queue/tickets` : `201` avec `ticket_number` séquentiel croissant sur appels successifs
    du même salon/jour ; `422` prestation vide/inactive/hors salon ; `404` `customer_profile_id`
    d'un autre salon ; `403` si le principal n'a pas le rôle/permission `KIOSK` attendu (dépend de la
    forme exacte livrée par #155 — test à ajuster à l'implémentation) ; `401` sans credential.
  - `POST .../start` / `.../complete` : `200` nominal ; `409` transition invalide (déjà démarré, pas
    encore démarré) ; `404` ticket d'un autre salon ; `403` rôle insuffisant ; `401` sans jeton.
  - `tests/test_queue_api.py` (existant, à étendre) : le corps de `GET .../queue` porte désormais
    `appointments`/`walk_in_tickets` ; vérifier que `appointments` reproduit **exactement** l'ancien
    contenu (non-régression du contrat RDV) et que `walk_in_tickets` contient les tickets du jour
    aux statuts `waiting`/`called`/`in_progress`/`done` (jamais `expired`).
- **`tests/test_security_guards.py`** : l'invariant `unprotected_routes(app) == []` couvre
  automatiquement les nouvelles routes ; vérifier explicitement qu'aucun chemin `queue/tickets`
  n'entre dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_queue_ticket_e2e.py`** (patron `test_employee_and_queue_e2e.py`) :
  1. parcours complet : device `KIOSK` provisionné (dépendance #155) → identification/omission client
     (#156) → `POST .../queue/tickets` → le ticket apparaît dans `ListSalonQueueTickets` →
     `POST .../start` (coiffeuse du salon) → apparaît dans `GET .../queue` (`walk_in_tickets`) →
     `POST .../complete` ;
  2. **concurrence réelle** : deux créations quasi-simultanées (threads/connexions séparées) sur le
     même salon/jour → deux `ticket_number` **distincts et consécutifs**, jamais de doublon (preuve
     du verrou consultatif + de la contrainte `UNIQUE`) ;
  3. **isolation par jour** : deux tickets créés à un jour d'intervalle (horloge injectée) sur le même
     salon → chacun redémarre bien à partir de son propre `MAX` (le compteur du jour précédent
     n'influence pas le nouveau) ;
  4. **isolation inter-salons** : même schéma que #150/#152 — un device du salon A ne peut ni créer
     ni voir un ticket du salon B ;
  5. deny-by-default : sans credential valide → `401`/`403` sur les trois nouvelles routes.
- **Migration** : round-trip Alembic (`upgrade head → downgrade -1 → upgrade head`) couvre `0014`.

## Documentation Updates

- **`backend/README.md`** : nouvelle section « File d'attente walk-in — tickets de passage (US-8.3,
  #157) » avec le tableau routes/permission/réponses, la formule d'ETA documentée en clair, et un
  rappel explicite « `QueueTicket` est indépendant d'`Appointment` — voir ADR-0042 » (ADR committée
  avec l'implémentation de #157, cette spec en constitue la matière première).
- **`docs/adr/0042-file-attente-walkin-queue-ticket.md`** + entrée dans **`docs/adr/README.md`** :
  l'architecture `QueueTicket` a sa propre ADR, committée avec #157 (l'ADR-0041, committée avec
  #155, couvre l'authentification borne ; #161 vérifie l'index des deux en fin de jalon).
- **OpenAPI** : `summary`/`responses`/docstrings des nouvelles routes, y compris les codes
  `409`/`422`, visibles sur `/docs`.
- **`web-dashboard/README.md`** : note sur le nouveau contrat de `GET /salons/{salon_id}/queue`
  (`appointments`/`walk_in_tickets`) une fois `queue-board.tsx` mis à jour (hors périmètre backend de
  #157, mais dépendance directe à signaler dans la PR).

## Risks and Open Questions

Les points suivants reprennent uniquement les décisions de la liste de décisions M7 qui concernent
directement #157, présentées comme des choix à valider par le porteur produit avant l'implémentation
réelle :

1. **Décision 2 (« `QueueTicket` indépendant, pontable vers `Appointment` seulement au démarrage »)
   — le pont proposé ici est une fusion en *lecture*, pas en *écriture*.** Justification technique
   détaillée en *Proposed Implementation §C* : `Appointment.client_id` est `NOT NULL`, ce qu'un
   walk-in sans compte ne peut pas satisfaire. **À valider** : si le produit considère qu'un walk-in
   doit un jour apparaître dans les statistiques de revenu/fréquentation qui s'appuient aujourd'hui
   exclusivement sur `Appointment`/`Payment.appointment_id`, il faudra soit accepter que ces
   statistiques ignorent le walk-in en V1 (implicite si cette spec est retenue telle quelle), soit
   lancer un travail de schéma dédié plus tard — **pas dans #157**.
2. **Décision 5 (formule V1 d'ETA « position × durée moyenne ÷ coiffeuses actives »)** — implémentée
   telle quelle avec deux replis explicites documentés (aucune coiffeuse active ; aucun ticket actif
   pour calculer une moyenne). **À valider** : le repli « moyenne des prestations du ticket lui-même »
   en l'absence de tout autre ticket actif est une convention parmi d'autres possibles (une constante
   fixe serait plus simple mais moins représentative) — à confirmer avant l'implémentation, l'impact
   étant limité au tout premier ticket de la journée.
3. **Décision 6 (« portée téléphone limitée au salon de la borne »)** — n'affecte #157 qu'indirectement
   (le ticket porte un `customer_profile_id` déjà résolu par #156 dans le bon salon) ; **aucune
   validation supplémentaire** n'est nécessaire côté `QueueTicket` au-delà de la vérification
   d'appartenance déjà prévue (§D point 2) — signalé ici pour mémoire, pas une question ouverte
   propre à #157.
4. **Numéro de migration `0014` et clé de verrou** — dépend de l'ordre de merge réel avec #155/#156
   (#155 introduit `0013_kiosk_role.py`, sur laquelle le `down_revision = 0013` s'appuie). **À
   revalider explicitement à l'implémentation** : renuméroter si nécessaire, jamais laisser deux
   migrations partager la même révision.
5. **Réutilisation de `Permission.APPOINTMENT_UPDATE_STATUS` pour « prendre en charge »/« clôturer »
   un ticket** — proposée par cohérence (mêmes acteurs — coiffeuse et gérant — que le démarrage d'un
   RDV) plutôt que de créer une permission dédiée `QUEUE_TICKET_MANAGE`. **À confirmer** : si le
   produit souhaite pouvoir un jour autoriser la prise en charge de tickets walk-in à un rôle qui n'a
   pas `APPOINTMENT_UPDATE_STATUS` (peu probable au MVP), une permission dédiée serait alors
   justifiée — décision à trancher avant l'implémentation, car elle est bon marché à changer
   maintenant et coûteuse à changer après coup (migration de données de permissions).
6. **Permission `Permission.QUEUE_TICKET_CREATE`** — nom canonique **fixé par #155**
   (`specs/borne-role-authentification-kiosque.md`, qui pose le rôle et sa matrice minimale) ; #157
   la consomme telle quelle. Le nommage est tranché ; seul l'**ordre de merge** entre les deux
   implémentations reste à coordonner (la matrice de #155 doit atterrir avant ou avec #157).
7. **Forme de réponse de `GET /salons/{salon_id}/queue` (`list` → objet à deux clés)** — rupture de
   contrat mineure assumée d'un seul endpoint interne (consommateur unique et connu :
   `queue-board.tsx`). **À confirmer** avec le porteur produit/équipe web avant implémentation,
   l'alternative (endpoint séparé) étant documentée et écartée en *API / Interface Changes* mais pas
   à exclure définitivement si une contrainte de compatibilité apparaît que cette spec ignore.
8. **Journalisation ou non de la création d'un ticket** (§D point 5, §Security) — cette spec propose
   de **ne pas** journaliser `JoinQueue` dans `audit_logs` (pas une action humaine de gestion) mais
   de journaliser `start`/`complete` (actions humaines). **À confirmer** — un rejet de cette
   proposition n'aurait qu'un coût d'implémentation marginal (le socle `AuditLog` est déjà injectable
   dans `JoinQueue`).
9. **Expiration automatique des tickets non pris en charge** — non livrée par #157 (pas de job cron
   dans ce dépôt à ce jour). **À confirmer** : un ticket `waiting` oublié en fin de journée reste
   `waiting` indéfiniment jusqu'à ce qu'une action explicite le clôture — acceptable pour un MVP
   piloté sur 2-3 salons (cf. Risque 5 du PRD, rappelé par le contexte du jalon M7), mais à traiter
   avant une généralisation.
10. **Ticket anonyme (`customer_profile_id = null`)** — le domaine l'autorise (§Security), l'UX
    (#159) ne le tranche pas ici. **À confirmer** avec #156/#159 : la borne doit-elle réellement
    offrir un chemin « continuer sans donner mon nom » ?

## Implementation Checklist

1. **Lire** `application/queue.py`, `domain/queue.py`, `adapters/outbound/persistence/
   appointment_repository.py` (369-416, 695-730), `adapters/outbound/persistence/
   payment_repository.py` (57-89), `adapters/outbound/persistence/salon_catalog_repository.py`
   (90-118), `docs/adr/0040-impression-recu-encaissement-gerant.md` — s'imprégner des patrons de
   verrouillage, de préconditions et d'audit à décliner.
2. **Coordonner** avec #155/#156 : numéro de migration réel, nom de la permission `KIOSK` consommée
   par l'endpoint « rejoindre la file », forme exacte de la garde de portée device→salon.
3. **Trancher** les questions ouvertes 1, 5, 7, 8, 9, 10 avec le porteur produit avant d'écrire du
   code (elles déterminent des choix de schéma ou de contrat difficiles à revenir en arrière).
4. **Domaine** : créer `domain/queue_ticket.py` (statuts, `QueueTicketToCreate`/`QueueTicket`,
   `estimate_wait_minutes` avec ses replis documentés) ; ajouter les quatre nouvelles erreurs à
   `domain/errors.py`.
5. **Audit** : ajouter `ENTITY_TYPE_QUEUE_TICKET`, `AuditAction.QUEUE_TICKET_STARTED`/
   `QUEUE_TICKET_COMPLETED` à `domain/audit.py`.
6. **Tests de domaine** : écrire `tests/test_domain_queue_ticket.py` (formule d'ETA, machine à
   états) **avant** la persistance.
7. **Schéma** : ajouter les classes ORM `QueueTicket`/`QueueTicketService` à `models.py` ; écrire
   `migrations/versions/0014_queue_tickets.py` (`down_revision` revalidé à l'étape 2) avec un
   `downgrade()` complet ; vérifier le round-trip Alembic sur PostgreSQL 16.
8. **Port** : créer `application/ports/queue_ticket_repository.py`.
9. **Cas d'usage** : créer `application/queue_ticket.py` (`JoinQueue`, `StartQueueTicket`,
   `CompleteQueueTicket`, `ListSalonQueueTickets`), en réutilisant les patrons de préconditions et
   d'écriture idempotente identifiés à l'étape 1.
10. **Fakes & tests applicatifs** : `FakeQueueTicketRepository` + fixture dans `tests/conftest.py` ;
    écrire `tests/test_queue_ticket_usecases.py`.
11. **Adapter sortant** : créer `adapters/outbound/persistence/queue_ticket_repository.py` (verrou
    consultatif salon+jour, `flush()` sans `commit()`, filtres `(salon_id, id)`).
12. **Adapter entrant** : créer `adapters/inbound/queue_tickets.py` (schémas Pydantic, gardes
    KIOSK/gérant selon la table de §API, mapping `404`/`409`/`422`) ; **ne pas** toucher
    `PUBLIC_ROUTE_PATHS`.
13. **Extension de la file existante** : modifier `application/queue.py::ListSalonQueue` (3ᵉ source)
    et `adapters/inbound/appointments.py` (réponse `GET .../queue` à deux clés) ; mettre à jour
    `tests/test_queue_api.py` pour couvrir la non-régression **et** la nouvelle clé `walk_in_tickets`.
14. **Câblage** : `app.include_router(queue_tickets_router)` dans `main.py` avec commentaire de
    câblage dans le style existant.
15. **Tests API & e2e** : `tests/test_queue_ticket_api.py` puis `tests/test_queue_ticket_e2e.py`
    (concurrence réelle sur le compteur, isolation par jour, isolation inter-salons,
    deny-by-default) ; exécuter `pytest` (+ `DATABASE_URL`) et `ruff check`.
16. **Documentation** : section dédiée dans `backend/README.md` ; rédaction de
    `docs/adr/0042-file-attente-walkin-queue-ticket.md` et entrée correspondante dans
    `docs/adr/README.md` (ADR committée avec la PR de #157) ; note de contrat dans
    `web-dashboard/README.md`.
17. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test),
    `ruff check` ; relire la PR pour s'assurer qu'**aucune PII** n'apparaît dans l'audit ou les
    réponses au-delà du prénom déjà autorisé, et qu'**aucune signature IA** n'a été introduite.
