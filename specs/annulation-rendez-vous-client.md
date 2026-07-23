# Annulation d'un rendez-vous côté client (US-3.3)

> Spécification de planification pour l'issue GitHub **#24 — US-3.3 : Annulation d'un rendez-vous
> (client)** (`feature` · Must · Effort S · PRD §6 Épic 3, §7.1, §8.1, §11.4). **Dépend de #22**
> (réservation) et s'appuie sur le chemin de modification livré par **#23**. **Cette spec ne produit
> pas de code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires Dart/Python),
> en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants techniques (noms de
> routes, champs JSON, symboles, enums SQL) inchangés. **Aucune signature IA** dans le code, les
> commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 3, US-3.3) pose le besoin : **« en tant que client, je veux annuler mon rendez-vous »**,
avec deux règles métier (§8.1) : *« un client peut annuler selon les règles définies par le salon »* et
*« un rendez-vous annulé ne doit pas être comptabilisé dans le chiffre d'affaires »*. Les critères
d'acceptation de l'issue #24 sont : **annulation avec motif optionnel** ; **RDV annulé exclu du
chiffre d'affaires (CA)**.

État actuel du dépôt (après #21/#22/#23) :

- **Le socle base porte déjà tout le nécessaire.** La table `appointments` (schéma #3, migration
  `0001`) a les colonnes `status` (défaut `PENDING`, `CHECK` enum
  `PENDING|CONFIRMED|CANCELLED|COMPLETED|NO_SHOW`), **`cancellation_reason`** (`Text` **nullable**),
  la colonne générée `slot tsrange` et `updated_at` (`onupdate=func.now()`, rafraîchie
  automatiquement, centralisée par #20). **Aucune migration, table, colonne ni contrainte n'est
  nécessaire.**
- **La contrainte d'exclusion anti double-réservation `ex_appointments_hairdresser_slot`** ne porte
  que sur `status IN ('PENDING','CONFIRMED')` : un RDV **annulé n'occupe plus le créneau**. De même,
  `SqlAppointmentRepository.booked_slots` filtre `status IN (PENDING, CONFIRMED)` (`_ACTIVE_STATUSES`).
  **Conséquence directe : annuler un RDV libère automatiquement son créneau** dans le moteur de
  disponibilité (#21) — sans code supplémentaire.
- **Le chemin rendez-vous existe et sait déjà écrire/journaliser.** #23 a livré le patron
  *lecture possédée → verrou d'état → UPDATE conditionnel → audit* : `get_owned(appointment_id,
  client_id)` (isolation §11.2 en SQL, `None` = inexistant **ou** d'autrui, indiscernables), un
  `update` **conditionné au statut actif** (garde TOCTOU), l'entrée d'audit `APPOINTMENT_UPDATED`
  **neutre** dans la **même** unité de travail (`get_audit_log` partage la `Session`), et les erreurs
  neutres `AppointmentNotFound` (→ 404) / `AppointmentNotModifiable` (→ 409). Le router
  `adapters/inbound/appointments.py` monte déjà `GET /appointments`, `PATCH /appointments/{id}`,
  `POST /salons/{id}/appointments`, `GET .../availability`.
- **La règle d'état côté client existe déjà pour la modification** : `is_client_modifiable` +
  `CLIENT_MODIFIABLE_STATUSES = (PENDING, CONFIRMED)` (`domain/appointment.py`) — un RDV
  `CANCELLED`/`COMPLETED`/`NO_SHOW` est déjà considéré terminal/verrouillé côté client.
- **Aucun chemin d'annulation n'existe** : pas de cas d'usage `CancelAppointment`, pas de méthode
  `cancel` au port/adapter, pas de route d'annulation, pas d'action d'audit `APPOINTMENT_CANCELLED`,
  et **aucune** affordance mobile d'annulation (l'écran « Mes rendez-vous » de #23 n'a qu'un bouton
  « Modifier »).
- **Aucune notion de chiffre d'affaires n'existe encore.** L'encaissement (M4, #28–#38) et le tableau
  de bord/KPI CA (M5, #39+) ne sont **pas** livrés — aucune requête ni agrégat de CA n'existe dans
  `backend/` ni `web-dashboard/`. La règle « RDV annulé exclu du CA » **ne peut donc pas être
  “implémentée”** sous forme de calcul ici ; elle se matérialise par **la transition d'état vers
  `CANCELLED`** (qui rendra le RDV mécaniquement exclu de tout futur calcul de CA restreint aux RDV
  réalisés/`COMPLETED` ou aux paiements validés) et par une **contrainte documentée** pour les issues
  M4/M5. Voir *Risks and Open Questions*.

Le gap que #24 comble : **(1)** un **chemin d'annulation serveur** pour le RDV du client authentifié —
transition d'un RDV **actif** (`PENDING`/`CONFIRMED`) vers **`CANCELLED`** avec **motif optionnel**
persisté dans `cancellation_reason`, verrou d'un RDV terminé/terminal, libération automatique du
créneau, et **journalisation §11.4** (`APPOINTMENT_CANCELLED`) ; **(2)** côté mobile, une **affordance
« Annuler »** dans « Mes rendez-vous » (#23) avec saisie facultative du motif ; **(3)** une **garantie
vérifiée** (test) que le RDV annulé sort de l'offre réservable et des états actifs, plus une
**contrainte documentée** que tout futur calcul de CA (M4/M5) devra exclure `CANCELLED`.

## Goals

- **Annuler un RDV actif (client)** : un client authentifié annule **son** rendez-vous
  (`client_id == principal.id`) tant qu'il est `PENDING`/`CONFIRMED`, en fournissant un **motif
  optionnel**. La transition force `status = CANCELLED` **côté serveur** (jamais lu du corps) et écrit
  `cancellation_reason` s'il est fourni.
- **Verrouiller l'annulation d'un RDV terminé/terminal** : un RDV `COMPLETED`, déjà `CANCELLED` ou
  `NO_SHOW` **n'est pas annulable par le client** — refus **neutre** (`AppointmentNotCancellable` →
  `409`). Le verrou est ré-affirmé à l'écriture par un **UPDATE conditionnel** (garde TOCTOU, patron
  #23).
- **Libérer le créneau** : par construction (clause `WHERE status IN (PENDING,CONFIRMED)` de
  l'exclusion base **et** de `booked_slots`), le créneau d'un RDV annulé **redevient disponible** —
  garantie **vérifiée par test**, pas de code additionnel.
- **Exclure le RDV annulé du CA (invariant, pas un calcul)** : aucun CA n'est calculé au MVP courant ;
  #24 garantit **l'état `CANCELLED`** et **documente** que les futures agrégations de CA (M4/M5) ne
  comptent **que** les RDV réalisés/paiements validés — un RDV `CANCELLED` en est **exclu par
  définition**. Voir *Non-Goals* et *Risks and Open Questions*.
- **Journaliser l'annulation (§11.4)** : chaque annulation écrit une entrée d'audit
  `APPOINTMENT_CANCELLED` **neutre** (acteur = `client_id`, portée = `salon_id` du RDV, entité =
  l'`appointment`, `metadata` **sans** texte de motif ni PII), dans la **même** unité de travail que
  l'écriture métier (patron #17/#20/#23).
- **Préserver l'anti-élévation & la confidentialité (§11.2/§11.3)** : le corps ne porte **jamais**
  `client_id`/`salon_id`/`status` (seul le **motif** est saisissable) ; un RDV d'autrui (ou inexistant)
  est un **`404` indiscernable** (aucun oracle) ; aucune identité tierce n'est exposée. Le
  `cancellation_reason` (texte libre du client) est **stocké mais jamais journalisé**.
- **Affordance mobile « Annuler »** : dans « Mes rendez-vous » (#23), un bouton **« Annuler »**
  (désactivé pour un RDV non annulable) ouvre une **confirmation** avec un champ **motif facultatif** ;
  au succès, la liste se rafraîchit (le RDV annulé quitte la liste des RDV actifs).
- **Couverture de tests** : règle de domaine (état annulable), cas d'usage (ownership, verrou, motif
  optionnel, audit dans la même unité de travail, motif jamais dans l'audit), intégration/HTTP
  (anti-élévation, deny-by-default), Postgres e2e (transition réelle, **créneau libéré**, verrou
  terminé, audit), et — côté mobile — passerelle + use case + widget (confirmation, motif, verrou,
  `409`/`401`).

## Non-Goals

- **Implémenter un calcul de chiffre d'affaires.** Le CA (encaissement M4 #28–#38 ; KPI gérant M5
  US-6.2 #40+) n'existe pas encore. #24 **ne construit aucun agrégat de CA** ; il garantit l'état
  `CANCELLED` et **documente l'invariant d'exclusion** que les issues M4/M5 devront respecter. Ne pas
  laisser entendre qu'un calcul de CA est livré (contrainte : ne pas impliquer de comportement non
  implémenté).
- **Règle d'annulation configurable par le salon (« selon les règles définies par le salon »).**
  Aucun champ de politique d'annulation (délai/cutoff, pénalité, fenêtre) n'existe au schéma ni au
  PRD. Au MVP, l'annulation est permise tant que le RDV est **actif** ; pas de « cutoff » temporel
  dédié. Une politique configurable relèverait d'une décision produit + configuration salon (hors
  périmètre S — voir *Open Questions*).
- **Notification au salon / au client (§8.4, US-7.4).** Le PRD (§8.4, table US-7.4) prévoit qu'« une
  annulation doit notifier le client et le salon » ; ce câblage relève de l'**Épic 7** (notifications,
  #43+). #24 n'envoie **aucune** notification : l'audit §11.4 est une **trace interne**, pas une
  notification. (Les critères d'acceptation *de l'issue #24* ne mentionnent que la règle salon et
  l'exclusion du CA ; la « notification au salon » de la table PRD §6 est portée par l'Épic 7.)
- **Annulation / gestion de statut par le gérant** (confirmer/refuser/terminer/absent, US-3.4 #25) :
  hors périmètre. #24 se limite au **chemin client**. Aucun droit gérant nouveau.
- **Historique complet « Mes rendez-vous »** (RDV annulés/terminés + montants, US-4.4 #30) : la lecture
  `GET /appointments` reste filtrée aux **RDV actifs** (`PENDING`/`CONFIRMED`) ; un RDV annulé en
  **disparaît** (comportement assumé au MVP — la confirmation `200` renseigne le client). L'affichage
  des RDV annulés dans un historique relève de #30.
- **Réactivation / dé-annulation d'un RDV** : une annulation est **terminale** côté client (pas de
  retour à `PENDING`). Reprogrammer = créer un nouveau RDV (tunnel #22).
- **Nouvelle table, migration, colonne ou contrainte** : le schéma existe depuis #3 et suffit.
- **Interface web (Next.js)** : US-3.3 est un parcours **client** (mobile). Le `web-dashboard/` n'est
  pas touché.

## Relevant Repository Context

### Stack & architecture

- **Backend** : FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0 + Alembic +
  psycopg 3 (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) — `domain/` et
  `application/` n'importent **jamais** FastAPI ni SQLAlchemy ; RBAC **deny-by-default** (ADR-0015).
  Tests `pytest` (`backend/pyproject.toml`, `testpaths=["tests"]`).
- **Mobile** : Flutter stable / Dart ^3.12 (ADR-0001, ADR-0007), **même découpage hexagonal** :
  `lib/domain`, `lib/application` (ports + use_cases), `lib/adapters/data` (HTTP), `lib/adapters/ui`.
  Tests `flutter test`.
- **Test gate** agrégé (#6) : `scripts/test-gate.sh` enchaîne `pytest` / `npm test` / `flutter test`.

### Backend rendez-vous déjà livré (#21/#23 — à réutiliser/étendre)

- `coiflink_api/domain/appointment.py` — `Appointment`, `AppointmentToCreate`, `AppointmentUpdate`,
  `BookedService`, `is_client_modifiable` + `CLIENT_MODIFIABLE_STATUSES`, `require_services`,
  `validate_booking_window`, `compute_end_time`.
- `coiflink_api/domain/enums.py` — `AppointmentStatus` = `PENDING | CONFIRMED | CANCELLED | COMPLETED
  | NO_SHOW` (hérite de `str`). Les états « actifs » sont `PENDING`/`CONFIRMED`.
- `coiflink_api/domain/errors.py` — erreurs **neutres** : `AppointmentNotFound` (404),
  `AppointmentNotModifiable` (409), `SlotAlreadyBooked`, `SalonNotBookable`, etc. (`__all__` maintenu).
- `coiflink_api/domain/audit.py` — `AuditAction` (**enum fermé** : `SERVICE_*`, `SALON_UPDATED`,
  `APPOINTMENT_UPDATED`), `AuditEntry` (`action`, `actor_user_id`, `entity_type`, `entity_id`,
  `salon_id?`, `metadata`), `ENTITY_TYPE_APPOINTMENT = "appointment"`.
- `coiflink_api/application/appointments.py` — `BookAppointment`, `ModifyAppointment` (patron
  ownership→verrou→UPDATE conditionnel→audit), `ListMyAppointments`, helpers réutilisables
  (`_load_bookable_salon`, `_resolve_booked_services`, `_require_salon_hairdresser`).
- `coiflink_api/application/ports/appointment_repository.py` — `booked_slots(...,
  exclude_appointment_id=…)`, `create`, `get_owned`, `update`, `list_for_client`.
- `coiflink_api/adapters/outbound/persistence/appointment_repository.py` —
  `SqlAppointmentRepository` : `_ACTIVE_STATUSES = (PENDING, CONFIRMED)`, `update` avec **UPDATE
  conditionnel** sur statut + traduction exclusion `23P01` → `SlotAlreadyBooked` (**sans journaliser
  l'erreur brute**), `_to_domain`, `_load_services`.
- `coiflink_api/adapters/inbound/appointments.py` — router : `GET .../availability` (public), `POST
  /salons/{id}/appointments` (client `APPOINTMENT_BOOK`), `GET /appointments`
  (`APPOINTMENT_READ_OWN`), `PATCH /appointments/{id}` (`APPOINTMENT_BOOK`) ; schémas Pydantic
  `extra="ignore"` ; DI surchargeables (`get_appointment_repository`, `get_catalog_repository`,
  `get_audit_log`, `get_salon_scope_repository`) ; `_now()` UTC+0 ; `AppointmentResponse` (réponse
  commune, **ne porte pas** `cancellation_reason`).

### Modèle de données pertinent (schéma #3, `models.py`)

- `Appointment` : `id`, `salon_id`, `client_id`, `hairdresser_id NULL`, `appointment_date`,
  `start_time`, `end_time`, `status` (défaut `PENDING`), **`cancellation_reason NULL`** (`Text`),
  `client_note NULL`, `slot tsrange` **`Computed(persisted=True)`**, `created_at`, `updated_at`
  (`onupdate=func.now()`), `CHECK end_time > start_time`, `enum_check("status", AppointmentStatus)`,
  `UniqueConstraint(salon_id, id)`, exclusion `ex_appointments_hairdresser_slot`
  (`WHERE hairdresser_id IS NOT NULL AND status IN ('PENDING','CONFIRMED')`), index
  `ix_appointments_client_id` (lecture « mes RDV ») et `ix_appointments_salon_id (salon_id,
  appointment_date)`.
- `AppointmentService` : PK `(appointment_id, service_id)`, `salon_id`, `price_at_booking`, FK
  composites CASCADE/RESTRICT. **L'annulation ne touche pas les jonctions** (le RDV et ses prestations
  restent, avec le prix figé — utile à l'historique/CA futur).

### RBAC & portée (ADR-0015, #12)

- `domain/permissions.py` : le rôle **`CLIENT`** détient `SALON_READ_ANY`, `SERVICE_READ`,
  **`APPOINTMENT_BOOK`** et **`APPOINTMENT_READ_OWN`**. Le commentaire de la matrice décrit le client
  comme *« réserve/modifie/**annule** ses rendez-vous »* — **l'annulation est donc couverte par
  `APPOINTMENT_BOOK`** (aucune permission `APPOINTMENT_CANCEL_*` distincte n'existe ; #23 a déjà
  réutilisé `APPOINTMENT_BOOK` pour la modification).
- `adapters/inbound/security.py` : gardes `require_permission`, `require_any_permission`,
  `require_salon_scope`. **Point clé** : un `CLIENT` **n'a aucune portée salon** (`require_salon_scope`
  → `403`) — la route d'annulation, comme la modification #23, **n'utilise pas** `require_salon_scope` ;
  l'appartenance est validée **dans le cas d'usage** (`client_id == principal.id`). Une route protégée
  (hors `PUBLIC_ROUTE_PATHS`) est fermée par défaut.

### Journalisation d'audit §11.4 (#17/#20/#23 — patron à réutiliser)

- `application/ports/audit_log.py` : `AuditLog.record(entry)` — **même** session que la mutation
  (atomicité). `adapters/outbound/persistence/audit_log_repository.py` : `SqlAuditLog`.
- Patron d'usage (#23, `ModifyAppointment`) : diff **neutre** (noms de champs seulement) →
  `repository.update(...)` → `audit_log.record(AuditEntry(..., metadata={"changed": [...]}))`. DI
  `get_audit_log(session)` déjà exposée dans `adapters/inbound/appointments.py`.

### Mobile déjà livré (#22/#23 — patrons à calquer)

- `lib/domain/appointment/{appointment,appointment_status,availability_slot}.dart` — `Appointment`
  (dont `isClientModifiable`), `AppointmentStatus.fromApi`/`.label` (dont `cancelled → « Annulé »`,
  valeur inconnue tolérée).
- `lib/application/ports/appointment_gateway.dart` — `AppointmentGateway` (`availableSlots`, `book`,
  `myAppointments`, `modify`), `BookingDraft`, exceptions **neutres** (`AppointmentGatewayException`,
  `SlotTakenException`, `NotBookableException`, `UnauthorizedException`, `NotModifiableException`,
  `AppointmentNotFoundException`).
- `lib/application/auth_session.dart` + `lib/application/ports/token_store.dart` — session cliente
  (jeton **jamais journalisé**, `InMemoryTokenStore` au MVP).
- `lib/adapters/data/http_appointment_gateway.dart` — mapping JSON ↔ domaine, en-tête
  `Authorization: Bearer`, codes `200/201/401/404/409`, **aucune journalisation** d'URL/jeton/PII ;
  `_modifyConflictFromBody`/`_conflictFromBody` routent le `409` sans exposer le `detail`.
- `lib/adapters/ui/appointments/my_appointments_screen.dart` — liste des RDV actifs, carte
  `_AppointmentCard` (bouton « Modifier » désactivé si `!isClientModifiable`) ; `AppointmentModifier`
  injecté.
- `lib/adapters/ui/app.dart`, `lib/main.dart` — composition (gateways, session, use cases, lanceurs
  `openBooking`/`openModification`/`openMyAppointments`).
- `lib/adapters/ui/use_cases/{modify_appointment,list_my_appointments}.dart` — patron use case client.

## Proposed Implementation

Périmètre recommandé : **étendre** le chemin rendez-vous #23 par une **capacité d'annulation client**
au-dessus du **schéma inchangé** (transition d'état + motif optionnel + audit), puis livrer côté mobile
l'**affordance « Annuler »** dans « Mes rendez-vous ». La libération du créneau et l'exclusion des
états actifs sont **déjà** garanties par le schéma ; #24 ne fait que déclencher la transition et la
tracer.

### Backend

#### 1. Domaine (`domain/appointment.py`, `domain/errors.py`, `domain/audit.py`)

- **Règle d'état annulable (pure)** dans `domain/appointment.py` :
  - `CLIENT_CANCELLABLE_STATUSES = (AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value)`
    et `is_client_cancellable(status: str) -> bool`. *(Le jeu de statuts coïncide avec
    `CLIENT_MODIFIABLE_STATUSES`, mais on **nomme distinctement** la règle d'annulation pour la
    lisibilité et l'évolutivité — un salon pourrait un jour autoriser l'annulation dans des états où la
    modification est fermée, ou l'inverse. Voir Open Questions.)*
  - Justification : le PRD §8.1 permet au client d'annuler ; un RDV **terminé** (`COMPLETED`), **déjà
    annulé** (`CANCELLED`) ou **absent** (`NO_SHOW`) est terminal et **non annulable par le client**
    (l'exception gérant relève de #25).
- **Nouvelle erreur neutre** dans `domain/errors.py` (mettre à jour `__all__`) :
  - `AppointmentNotCancellable(DomainError)` : le RDV n'est pas dans un état annulable par le client
    (terminé/terminal/déjà annulé). Message neutre (« Ce rendez-vous ne peut plus être annulé. »). →
    **`409 Conflict`** *(état de la ressource, cohérent avec `AppointmentNotModifiable`)*.
  - *(Réutiliser `AppointmentNotFound` pour inexistant/hors appartenance — déjà livré #23.)*
- **Nouvelle action d'audit** dans `domain/audit.py` : `AuditAction.APPOINTMENT_CANCELLED =
  "APPOINTMENT_CANCELLED"` (§11.4 « Annulation rendez-vous »). `ENTITY_TYPE_APPOINTMENT` existe déjà.
- **VO de motif (optionnel)** : plutôt qu'un VO dédié, passer le motif comme `str | None` normalisé.
  Ajouter une petite fonction de normalisation **pure** `normalize_cancellation_reason(raw: str |
  None) -> str | None` (trim ; `None`/chaîne vide → `None` ; **borne de longueur** de robustesse, p.
  ex. `<= 500`, tronquée/refusée — cohérent avec les bornes de robustesse existantes). Documenter le
  choix (troncature silencieuse vs `422`) — recommandation : **tronquer** au MVP (motif = confort),
  aucune erreur bloquante. Voir Open Questions.

#### 2. Application (`application/appointments.py`)

- **Cas d'usage** `class CancelAppointment` (constructeur : `appointment_repository`, `audit_log` —
  **ni** catalog **ni** scope : l'annulation ne re-valide **pas** la disponibilité et **doit rester
  possible même si le salon est devenu non réservable/inactif** — on n'empêche jamais un client
  d'annuler). `execute(appointment_id, client_id, reason, *, now=None) -> Appointment` :
  1. **Charger le RDV du client** : `current = appointment_repository.get_owned(appointment_id,
     client_id)` ; `None` → `AppointmentNotFound` (couvre inexistant **et** d'autrui — aucun oracle).
  2. **Verrou d'état** : `if not is_client_cancellable(current.status): raise
     AppointmentNotCancellable(...)`.
  3. **Écriture transactionnelle** : `updated = appointment_repository.cancel(appointment_id,
     reason=normalize_cancellation_reason(reason))` — **UPDATE conditionnel**
     (`WHERE id = … AND status IN ('PENDING','CONFIRMED')`) posant `status = 'CANCELLED'` et
     `cancellation_reason = :reason`. Si `rowcount == 0` (statut passé terminal entre la lecture et
     l'écriture — garde TOCTOU), lève `AppointmentNotCancellable`. La colonne `updated_at` se
     rafraîchit ; le RDV **quitte** l'ensemble actif → le créneau **se libère** (exclusion base +
     `booked_slots`).
  4. **Audit §11.4** : `audit_log.record(AuditEntry(action=AuditAction.APPOINTMENT_CANCELLED.value,
     actor_user_id=client_id, salon_id=current.salon_id, entity_type=ENTITY_TYPE_APPOINTMENT,
     entity_id=appointment_id, metadata={...neutre...}))` — **jamais** le texte du motif ni de PII.
     Métadonnées recommandées : `{}` **ou** un booléen neutre `{"reason_provided": bool}` (le fait
     qu'un motif ait été fourni n'est pas une PII ; le **contenu**, si). Voir Open Questions.
- Ajouter `CancelAppointment` à `__all__`. Le motif **n'est jamais** journalisé (ni via `logging`, ni
  via l'audit) ; l'`IntegrityError` éventuelle est laissée telle quelle (l'annulation ne viole pas
  l'exclusion — elle **libère** un créneau).

#### 3. Port & adapter (persistance)

- **Port** `application/ports/appointment_repository.py` — ajouter :
  - `cancel(appointment_id: UUID, *, reason: str | None) -> Appointment` : passe le RDV à
    `CANCELLED` et pose `cancellation_reason` via **UPDATE conditionnel** sur le statut actif ; lève
    `domain.errors.AppointmentNotCancellable` si aucune ligne active ne correspond (garde TOCTOU).
    Retourne l'entité relue (`_to_domain` + `_load_services`). Documenter que l'annulation **ne
    supprime pas** les jonctions `appointment_services`.
- **Adapter** `adapters/outbound/persistence/appointment_repository.py` — `SqlAppointmentRepository` :
  - `cancel(...)` : `UPDATE appointments SET status='CANCELLED', cancellation_reason=:reason WHERE id
    = :id AND status IN (_ACTIVE_STATUSES)` (via `update(models.Appointment)...` ORM ou Core), lire le
    `rowcount`/relire la ligne ; `0` → `AppointmentNotCancellable`. `flush()` (commit piloté par
    `get_session`). Réutiliser `_to_domain(row, self._load_services(id))`. **Aucune** modification de
    schéma ; `updated_at` (`onupdate`) et l'exclusion se gèrent automatiquement.
  - *(Alternative d'implémentation : `SELECT ... WHERE status IN (actifs)` puis affectation d'attributs
    comme dans `update`, pour un `rowcount` explicite et un relecture homogène. Choisir la voie
    cohérente avec `update` #23.)*
- **Domaine `Appointment`** : n'a pas besoin d'exposer `cancellation_reason` pour le contrat courant
  (`AppointmentResponse` ne le renvoie pas). *Si* l'on décide d'échoyer le motif (Open Questions),
  ajouter `cancellation_reason: str | None` à l'entité + à la réponse — sinon **laisser inchangé**.

#### 4. Adapter entrant (HTTP)

- **Router** `adapters/inbound/appointments.py` — ajouter :
  - `POST /appointments/{appointment_id}/cancellation` (**client**,
    `require_permission(APPOINTMENT_BOOK)`, **pas** de `require_salon_scope`). Corps
    `CancelAppointmentRequest` (Pydantic `extra="ignore"`) : **uniquement** `reason: str | None =
    None` — **jamais** `salon_id`/`client_id`/`status` (un champ privilégié présent est **ignoré**).
    DI : `get_appointment_repository`, `get_audit_log`. Traductions : `AppointmentNotFound` → **404** ;
    `AppointmentNotCancellable` → **409**. Réponse `200` `AppointmentResponse` (schéma existant,
    `status = CANCELLED`).
  - **Forme de route** : `POST .../cancellation` (sous-ressource « action », préserve l'invariant
    « le corps ne porte jamais `status` » : c'est **la route** qui décide de la transition, pas un
    `status` soumis). Alternatives possibles (`POST .../cancel`, `DELETE /appointments/{id}`,
    `PATCH` avec statut) discutées en *Open Questions* — la **recommandation** est `POST
    .../cancellation` (une annulation est une **transition d'état soft**, pas une suppression : le
    `DELETE` serait trompeur ; on conserve la ligne pour l'audit/historique/CA futur).
- **Composition root** `coiflink_api/main.py` : le router rendez-vous est **déjà monté** ; la nouvelle
  route en hérite. **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`** (annulation **protégée**). Vérifier que
  l'invariant `unprotected_routes(app)` reste vide (test existant).

### Mobile (Flutter)

Réutilisation de l'écran « Mes rendez-vous » (#23) ; découpage hexagonal respecté.

1. **Domaine** — `Appointment` : ajouter `bool get isClientCancellable => status ==
   AppointmentStatus.pending || status == AppointmentStatus.confirmed` (miroir **d'affichage** de la
   règle serveur ; le serveur reste juge). `AppointmentStatus.cancelled → « Annulé »` existe déjà.
2. **Port** `application/ports/appointment_gateway.dart` — ajouter :
   - `Future<Appointment> cancel({required String appointmentId, String? reason, required String
     accessToken});`
   - Nouvelle exception **neutre** : `NotCancellableException extends AppointmentGatewayException`
     (`409`, RDV terminé/terminal — rien à re-choisir). `AppointmentNotFoundException` (`404`) et
     `UnauthorizedException` (`401`) existants réutilisés.
3. **Use case** `application/use_cases/cancel_appointment.dart` : refus **en amont** si
   `!appointment.isClientCancellable` (`NotCancellableException`), délégation au port ; propage les
   exceptions. Le motif est transmis tel quel (trimé, `null` si vide).
4. **Adapter data** `adapters/data/http_appointment_gateway.dart` — ajouter `cancel(...)` →
   `POST /appointments/{appointmentId}/cancellation` (en-tête `Authorization: Bearer`, corps `{if
   reason non vide: 'reason': reason}` — **sans** `client_id`/`salon_id`/`status`) ; mapping des codes
   (`200 → Appointment`, `401 → Unauthorized`, `409 → NotCancellable`, `404 →
   AppointmentNotFound`, autre → `AppointmentGatewayException`). **Aucune journalisation** d'URL/jeton/
   motif/PII (le motif est une donnée cliente — jamais loggé).
5. **UI** — `adapters/ui/appointments/my_appointments_screen.dart` : ajouter un bouton **« Annuler »**
   sur `_AppointmentCard`, **désactivé** quand `!appointment.isClientCancellable`. Au tap : ouvrir une
   **boîte de dialogue de confirmation** (« Annuler ce rendez-vous ? ») avec un `TextField` **motif
   facultatif** (« Motif (facultatif) »). À la confirmation, appeler le use case `CancelAppointment` ;
   au succès `_showMessage('Rendez-vous annulé.')` puis `_load()` (le RDV annulé quitte la liste
   active). Gérer `NotCancellableException`/`409` (message + rafraîchir), `UnauthorizedException`/`401`
   (invalider session → Connexion), autres (message neutre). Câbler un lanceur `onCancel` (typedef
   `AppointmentCanceller`) injecté depuis `app.dart`/`main.dart` (patron `onModify`).

### Documentation & ADR

- **ADR-0025 — Annulation d'un rendez-vous côté client** (numéro libre suivant — **vérifier** au step
  `document` : `docs/adr/` s'arrête à `0024`, aucun `0025` n'existe encore bien que le spec #23 l'ait
  *mentionné*) actant : transition d'état client `PENDING`/`CONFIRMED` → `CANCELLED` (terminaux
  verrouillés ; exception gérant → #25), **motif optionnel** persisté (jamais journalisé), route
  d'**action** `POST /appointments/{id}/cancellation` (pas de portée salon), **libération automatique
  du créneau** par le schéma existant, journalisation `APPOINTMENT_CANCELLED` (§11.4), **invariant
  d'exclusion du CA** (aucun calcul livré ; contrainte pour M4/M5), permission réutilisée
  (`APPOINTMENT_BOOK`), codes HTTP, backend **sans nouveau schéma**, notification (§8.4) différée à
  l'Épic 7. Indexer dans `docs/adr/README.md`.
- **`backend/README.md`** : section « Annulation d'un rendez-vous (client) ».
- **`app-mobile/README.md`** : section « Annulation depuis Mes rendez-vous ».

## Affected Files / Packages / Modules

**Backend — à modifier :**
- `backend/coiflink_api/domain/appointment.py` — `is_client_cancellable`,
  `CLIENT_CANCELLABLE_STATUSES`, `normalize_cancellation_reason`, `__all__`.
- `backend/coiflink_api/domain/errors.py` — `AppointmentNotCancellable` (+ `__all__`).
- `backend/coiflink_api/domain/audit.py` — `AuditAction.APPOINTMENT_CANCELLED`.
- `backend/coiflink_api/application/appointments.py` — `CancelAppointment` (+ `__all__`).
- `backend/coiflink_api/application/ports/appointment_repository.py` — `cancel(...)`.
- `backend/coiflink_api/adapters/outbound/persistence/appointment_repository.py` — implémentation
  `cancel`.
- `backend/coiflink_api/adapters/inbound/appointments.py` — `POST
  /appointments/{id}/cancellation`, schéma `CancelAppointmentRequest`, DI, traductions d'erreurs.
- `backend/tests/conftest.py` — étendre `FakeAppointmentRepository` (mémoire : `cancel` avec modes
  `not_cancellable`, mémorisation du `reason`) et réutiliser le `FakeAuditLog` (patron #23).

**Backend — à lire (contexte) :** `application/appointments.py::ModifyAppointment` (patron
ownership→verrou→UPDATE conditionnel→audit), `adapters/inbound/appointments.py` (DI `get_audit_log`,
route `PATCH`), `adapters/inbound/security.py` (deny-by-default), `adapters/outbound/persistence/
appointment_repository.py` (`update`/`_ACTIVE_STATUSES`/`_to_domain`), `models.py`
(`Appointment.cancellation_reason`/`updated_at`/EXCLUDE), `tests/test_appointment_*` (patrons fakes +
Postgres skip).

**Mobile — à créer :**
- `app-mobile/lib/application/use_cases/cancel_appointment.dart`.
- Tests (voir *Testing Plan*) : `test/cancel_appointment_test.dart`, extension des tests écran/gateway.

**Mobile — à modifier :**
- `app-mobile/lib/application/ports/appointment_gateway.dart` — `cancel` + `NotCancellableException`.
- `app-mobile/lib/adapters/data/http_appointment_gateway.dart` — `POST .../cancellation`.
- `app-mobile/lib/domain/appointment/appointment.dart` — `isClientCancellable`.
- `app-mobile/lib/adapters/ui/appointments/my_appointments_screen.dart` — bouton « Annuler » +
  dialogue de motif, gestion des codes.
- `app-mobile/lib/adapters/ui/app.dart`, `lib/main.dart` — lanceur `onCancel` (composition).
- `app-mobile/README.md`.

**Docs :** `docs/adr/0025-annulation-rendez-vous-client.md` (numéro à confirmer) + `docs/adr/README.md`,
`backend/README.md`. **`prd-coiflink.md` : ne pas modifier**. Récit `README.md` §6 (« M3 en cours ») :
à compléter au step `document` **une fois livré**.

## API / Interface Changes

**Nouvelle route backend** (protégée, jamais publique) :

- `POST /appointments/{appointment_id}/cancellation` — **client** (`APPOINTMENT_BOOK`, appartenance
  vérifiée serveur). Corps `{reason?: string}` (**sans** `client_id`/`salon_id`/`status`,
  `extra="ignore"`). Réponses : `200` `AppointmentResponse` (`status = "CANCELLED"`) ; `401` jeton
  absent/expiré ; `403` rôle insuffisant ; `404` RDV inexistant/hors appartenance ; `409` RDV non
  annulable (terminé/terminal/déjà annulé). Documentation OpenAPI (docstrings + `responses`).

**Interfaces internes mobiles nouvelles** (paquet-privées) : `AppointmentGateway.cancel`, use case
`CancelAppointment`, exception `NotCancellableException`, prédicat d'affichage `isClientCancellable`.
Documentées par docstrings Dart.

**Aucune modification** des routes `GET .../availability`, `POST /salons/{id}/appointments`,
`GET /appointments`, `PATCH /appointments/{id}`. `AppointmentResponse` est **réutilisé tel quel** (le
`status` reflète désormais `CANCELLED` ; `cancellation_reason` **n'est pas** ajouté au contrat, sauf
décision contraire — voir Open Questions).

## Data Model / Protocol Changes

**Aucune.** Les colonnes `status` (`CHECK` enum incluant `CANCELLED`) et **`cancellation_reason`**
(`Text` nullable), la colonne générée `slot`, `updated_at` (`onupdate`) et la contrainte d'exclusion
`ex_appointments_hairdresser_slot` **existent depuis #3**. L'annulation **écrit** `status` et
`cancellation_reason` sur une ligne existante — **ni table, ni migration, ni colonne, ni contrainte**.
La libération du créneau est **mécanique** : la clause `WHERE status IN ('PENDING','CONFIRMED')` de
l'exclusion **et** de `booked_slots` exclut d'office un RDV `CANCELLED`. Le contrat de fil
(`AppointmentResponse`) est inchangé.

## Security & Privacy Considerations

- **Isolation par salon / anti-élévation (§11.2)** : l'annulation est **scopée par appartenance**
  (`client_id == principal.id`), imposée **serveur** — le corps ne porte jamais `client_id`,
  `salon_id` ni `status`. Le `status = CANCELLED` est **forcé serveur** (via la route d'action, pas un
  champ soumis). Le `salon_id` provient du RDV chargé. Un RDV d'autrui (ou inexistant) donne un **`404`
  indiscernable** (aucun oracle).
- **Motif = donnée cliente à protéger (§11.3)** : `cancellation_reason` est un **texte libre** saisi
  par le client. Il est **persisté** sur **sa propre** ligne de RDV (donnée légitime du RDV), mais
  **jamais journalisé** (ni `logging`, ni message d'exception, ni **métadonnées d'audit** — l'audit
  reste **neutre**). Longueur **bornée** (robustesse anti-abus). Côté mobile, le motif ne transite que
  dans le corps `POST` (jamais dans un log/URL).
- **Journalisation §11.3/§11.4 sans fuite** : l'entrée d'audit `APPOINTMENT_CANCELLED` est **neutre** —
  `actor_user_id` UUID **opaque**, `entity_id` UUID, `metadata` **sans** texte de motif ni PII (au plus
  un booléen `reason_provided`). Aucun secret ni jeton manipulé/journalisé.
- **Verrou d'état (§8.1)** : un RDV terminé/terminal (`COMPLETED`/`CANCELLED`/`NO_SHOW`) est **non
  annulable** au niveau du cas d'usage **et** ré-affirmé par l'UPDATE conditionnel (garde TOCTOU) —
  l'UI mobile n'est qu'un confort ; le serveur est juge. L'idempotence d'une double annulation est un
  `409` (voir Open Questions).
- **Disponibilité / anti double-réservation** : l'annulation **libère** un créneau (elle ne peut pas
  violer l'exclusion). Aucune ré-validation de disponibilité n'est requise ni souhaitable : un client
  peut annuler **même** si son salon est devenu non réservable/inactif (§8.3). Rappel : pour un RDV
  **sans coiffeur** (`hairdresser_id` nul, MVP salon-level), l'exclusion base ne s'appliquait déjà pas.
- **CA (§8.1) — invariant, non calcul** : aucun agrégat de CA n'existe encore. #24 garantit l'état
  `CANCELLED` ; l'exclusion du CA sera **assurée par construction** dès que M4/M5 calculeront le CA sur
  les RDV réalisés / paiements validés (jamais sur `CANCELLED`). Un **test** vérifie que l'annulation
  sort le RDV des états actifs/du créneau ; la contrainte pour M4/M5 est **documentée** (ADR-0025).
- **Messages neutres** : `AppointmentNotFound`/`AppointmentNotCancellable` portent des messages
  génériques ; les refus RBAC restent les `401`/`403` **constants** de `security.py`. Côté mobile, les
  exceptions ne portent **ni** URL, **ni** jeton, **ni** corps, **ni** motif, **ni** PII.
- **Budgets §12** : lecture + annulation restent bien en deçà du budget API (< 3 s) ; l'index
  `ix_appointments_client_id` soutient la lecture « mes RDV ».
- **Résidence/hébergement** : inchangés (ADR-0011). Le jeton mobile reste dans le `TokenStore` (en
  mémoire au MVP, #22) et **jamais journalisé** (§11.1).

## Testing Plan

Test gate : `pytest` (backend) et `flutter test` (mobile). Convention du dépôt : tests **Postgres**
*skip proprement* sans `DATABASE_URL` (patron `test_appointment_*` / `test_salon_update_e2e.py`) ;
côté mobile, fakes/`MockClient` injectés, **aucun** appel réseau réel. Les tests existants doivent
rester **verts** et ne pas être modifiés (sauf extension additive de `conftest`).

- **Unit — règle de domaine** `tests/test_domain_appointment.py` (étendre) : `is_client_cancellable`
  → `True` pour `PENDING`/`CONFIRMED`, `False` pour `COMPLETED`/`CANCELLED`/`NO_SHOW` et valeur
  inconnue ; `normalize_cancellation_reason` → `None` pour `None`/vide/espaces, trim, borne de
  longueur.
- **Unit — application (fakes)** `tests/test_appointment_usecases.py` (étendre) :
  - `CancelAppointment` : refuse un RDV **non possédé** (`AppointmentNotFound`) ; refuse un RDV
    **terminé/terminal** (`AppointmentNotCancellable`) ; annule un RDV `PENDING`/`CONFIRMED` possédé
    (statut résultant `CANCELLED`, `cancellation_reason` transmis au dépôt) ; **motif optionnel**
    (`None` accepté) ;
  - l'entrée d'audit `APPOINTMENT_CANCELLED` est écrite dans la **même** unité de travail, `metadata`
    **sans** texte de motif ; `client_id`/`salon_id`/`status` **jamais** issus du corps.
- **Intégration/HTTP** `tests/test_appointment_api.py` (étendre, `TestClient` + fakes ou Postgres) :
  - `POST /appointments/{id}/cancellation` : `200` (`status=CANCELLED`) sur RDV actif possédé, **avec**
    et **sans** motif ; `409` sur RDV `COMPLETED`/déjà `CANCELLED` ; `404` sur RDV d'un autre client ;
    corps portant `client_id`/`salon_id`/`status` → **ignorés** (anti-élévation) ; `403` rôle non
    `CLIENT` ; `401` sans jeton.
  - **Invariant deny-by-default** : `unprotected_routes(app)` reste **vide** (test existant
    `test_security_guards`/`test_rbac_e2e` à faire passer **sans** ajouter le chemin à
    `PUBLIC_ROUTE_PATHS`).
- **Intégration Postgres** `tests/test_appointment_e2e.py` ou nouveau
  `tests/test_appointment_cancel_e2e.py` (skip sans `DATABASE_URL`) :
  - annulation réelle → `200`, `status=CANCELLED`, `cancellation_reason` persisté (ou `NULL` si
    absent), `updated_at` rafraîchi ;
  - **créneau libéré** : après annulation, `GET .../availability` (ou `booked_slots`) **ré-expose** le
    créneau et une **nouvelle réservation** sur ce créneau/coiffeur **réussit** — preuve que le RDV
    annulé n'occupe plus le slot (exclusion base) ;
  - RDV inséré directement en `COMPLETED` → annulation = `409` (verrou) ;
  - une entrée `audit_logs` `APPOINTMENT_CANCELLED` **neutre** est écrite (métadonnées sans motif).
- **Mobile — passerelle** `test/http_appointment_gateway_test.dart` (étendre, `MockClient`) : `cancel`
  envoie l'en-tête `Authorization`, **omet** `client_id`/`salon_id`/`status`, inclut `reason` **seulement**
  s'il est non vide, mappe `200 → Appointment` (statut « Annulé »), `409 → NotCancellable`, `404 →
  AppointmentNotFound`, `401 → Unauthorized` ; **aucun** message ne contient jeton/URL/motif/PII.
- **Mobile — use case & widget** `test/cancel_appointment_test.dart`,
  `test/my_appointments_screen_test.dart` (étendre) : refus amont d'un RDV non annulable ; le bouton
  « Annuler » est **désactivé** pour un RDV `completed`/`cancelled` ; parcours nominal (confirmation +
  motif facultatif → succès → rafraîchissement) ; `409` → message + refresh ; `401` → Connexion. **Le
  jeton et le motif n'apparaissent dans aucun log.**
- **Documentation** : revue que `backend/README.md` et `app-mobile/README.md` documentent
  l'annulation, le motif optionnel, le verrou et l'invariant CA.

## Documentation Updates

- **`docs/adr/0025-annulation-rendez-vous-client.md`** (nouveau — **confirmer le numéro** au step
  `document`) + entrée **`docs/adr/README.md`** : transition d'état client, motif optionnel non
  journalisé, route d'action `POST .../cancellation`, libération automatique du créneau, journalisation
  §11.4, **invariant d'exclusion du CA** (aucun calcul livré ; contrainte M4/M5), permission réutilisée,
  codes HTTP, backend sans nouveau schéma, frontière avec #23 (modification) et #25 (gérant/statuts),
  notification (§8.4) différée à l'Épic 7.
- **`backend/README.md`** : section « Annulation d'un rendez-vous (client) » (route `POST
  .../cancellation`, verrou terminé, motif optionnel, créneau libéré, audit, prérequis Postgres des
  tests e2e).
- **`app-mobile/README.md`** : section « Annulation depuis Mes rendez-vous » (dialogue de motif, verrou
  UI, garde-fous de non-journalisation).
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison —
  **ne pas anticiper** de comportement non implémenté (surtout : ne pas laisser croire qu'un calcul de
  CA existe).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstrings + `responses` sur la nouvelle route (généré par FastAPI).

## Risks and Open Questions

- **« Exclu du CA » alors qu'aucun CA n'existe.** Le calcul de chiffre d'affaires (encaissement M4
  #28–#38, KPI gérant M5 US-6.2) n'est **pas** livré. *Recommandation : #24 se limite à garantir l'état
  `CANCELLED` (+ test que le créneau se libère / le RDV sort des états actifs) et à **documenter**
  l'invariant « le CA n'inclut jamais un RDV `CANCELLED` » que les issues M4/M5 devront honorer.* **Ne
  pas** fabriquer d'agrégat de CA factice. **À confirmer.** (Alternative : ajouter dès maintenant un
  helper de domaine `counts_towards_revenue(status) -> bool` retournant `False` pour `CANCELLED`, à
  réutiliser par M4/M5 — *optionnel, faible coût, améliore la traçabilité de l'invariant*.)
- **« Selon les règles définies par le salon » (§8.1).** Aucune politique d'annulation configurable
  (délai/cutoff, pénalité) n'existe au schéma ni au PRD. *Recommandation : au MVP, tout RDV **actif**
  est annulable, sans cutoff temporel.* **À confirmer** — une fenêtre d'annulation (p. ex. « pas
  d'annulation < 2 h avant ») nécessiterait une décision produit + un champ de configuration salon
  (hors périmètre S).
- **Forme de la route.** `POST /appointments/{id}/cancellation` (sous-ressource action — *recommandé*,
  préserve « le corps ne porte jamais `status` ») vs `POST .../cancel` vs `DELETE /appointments/{id}`
  (trompeur : annulation ≠ suppression ; on conserve la ligne) vs `PATCH /appointments/{id}` avec
  `status` (romprait l'invariant anti-élévation). **À confirmer.**
- **Permission.** Réutiliser **`APPOINTMENT_BOOK`** (matrice §4.1 **inchangée**, cohérent avec le
  commentaire « réserve/modifie/annule ses RDV » et avec la modification #23) — *recommandé* — vs
  introduire `APPOINTMENT_CANCEL_OWN` (matrice + tests de matrice à faire évoluer). **À confirmer.**
- **États annulables.** `PENDING`/`CONFIRMED` (*recommandé*, miroir de l'activité). Nommer une constante
  **distincte** `CLIENT_CANCELLABLE_STATUSES` (même jeu que `CLIENT_MODIFIABLE_STATUSES` aujourd'hui)
  vs **réutiliser** `is_client_modifiable`. *Recommandation : constante distincte* pour découpler les
  deux règles. **À confirmer.**
- **Idempotence d'une double annulation.** Ré-annuler un RDV déjà `CANCELLED` : `409`
  (`AppointmentNotCancellable`, *recommandé* — cohérent avec le verrou) vs `200` idempotent. **À
  confirmer.**
- **Métadonnées d'audit.** `metadata` vide `{}` vs booléen neutre `{"reason_provided": bool}` vs
  `{"previous_status": <enum>}` (valeur d'enum, non-PII). *Recommandation : neutre et minimal —
  **jamais** le texte du motif.* **À confirmer.**
- **Écho du motif dans la réponse.** `AppointmentResponse` **n'ajoute pas** `cancellation_reason`
  (*recommandé*, surface minimale) vs l'échoyer pour que le client relise son motif (nécessite d'ajouter
  le champ à l'entité de domaine + à la réponse). **À confirmer.**
- **Longueur/validation du motif.** Trim + borne de robustesse ; **tronquer** silencieusement
  (*recommandé*, motif = confort) vs `422` au-delà de la borne. **À confirmer.**
- **Disparition du RDV annulé de « Mes rendez-vous ».** `GET /appointments` filtre `PENDING`/`CONFIRMED`
  → un RDV annulé **quitte** la liste (la `200` renseigne le client). L'historique incluant les RDV
  annulés relève de #30. **À noter** (choix assumé au MVP).
- **Notification (§8.4 / US-7.4).** Hors périmètre #24 (Épic 7, #43+). Confirmer qu'aucune notification
  n'est attendue dans #24 (seule la trace d'audit §11.4). **À noter** — la table PRD §6 mentionne
  « Notification au salon », portée par l'Épic 7.
- **TOCTOU statut load→cancel.** Un changement de statut concurrent (gérant, capacité #25 non livrée)
  pourrait invalider le verrou. *Recommandation : UPDATE conditionnel (`WHERE status IN
  ('PENDING','CONFIRMED')`) ré-affirmant le verrou* (patron #23). Risque faible au MVP. **À confirmer.**
- **Numéro d'ADR.** `docs/adr/` s'arrête à `0024` ; **aucun `0025` n'existe** bien que le spec #23 ait
  *évoqué* un « ADR-0025 (modification) » **non créé**. Le prochain numéro libre est **0025** —
  **vérifier** au step `document` pour éviter une collision.
- **Persistance de session mobile.** `TokenStore` **en mémoire** (#22) : l'annulation exige une session
  (reconnexion après redémarrage). Cohérent avec ADR-0024. **À noter.**
- **Outillage Postgres en test** (testcontainers vs service CI vs DSN local) : s'aligner sur les e2e
  existants (skip conditionnel sur `DATABASE_URL`).

## Implementation Checklist

1. **Lire** : `application/appointments.py::ModifyAppointment` (patron ownership→verrou→UPDATE
   conditionnel→audit) + `adapters/inbound/appointments.py` (DI `get_audit_log`, route `PATCH`) ;
   `adapters/outbound/persistence/appointment_repository.py` (`update`/`_ACTIVE_STATUSES`/`_to_domain`)
   ; `domain/appointment.py`, `domain/errors.py`, `domain/audit.py`, `adapters/inbound/security.py`,
   `models.py` (`cancellation_reason`/`updated_at`/EXCLUDE) ; mobile :
   `application/ports/appointment_gateway.dart`, `adapters/data/http_appointment_gateway.dart`,
   `adapters/ui/appointments/my_appointments_screen.dart`, `adapters/ui/app.dart`, `domain/
   appointment/*`.
2. **Trancher les Open Questions structurantes** (CA = invariant vs calcul, règle salon/délai, forme de
   route, permission, états annulables, idempotence, métadonnées d'audit, écho du motif, validation du
   motif) et les acter dans **ADR-0025** (+ `docs/adr/README.md`).
3. **Domaine** : `is_client_cancellable`/`CLIENT_CANCELLABLE_STATUSES` +
   `normalize_cancellation_reason` (`domain/appointment.py`, `__all__`) ; erreur
   `AppointmentNotCancellable` (`domain/errors.py`, `__all__`) ; `AuditAction.APPOINTMENT_CANCELLED`
   (`domain/audit.py`).
4. **Port** (`application/ports/appointment_repository.py`) : `cancel(appointment_id, *, reason)`.
5. **Cas d'usage** (`application/appointments.py`) : `CancelAppointment` (ownership → verrou → `cancel`
   transactionnel (UPDATE conditionnel) → audit `APPOINTMENT_CANCELLED` neutre) + `__all__`.
6. **Adapter sortant** (`SqlAppointmentRepository`) : `cancel` (`UPDATE ... SET status='CANCELLED',
   cancellation_reason=:reason WHERE id AND status IN (actifs)`, `rowcount==0` →
   `AppointmentNotCancellable`, relecture via `_to_domain`/`_load_services` ; **ne supprime pas** les
   jonctions).
7. **Adapter entrant** (`adapters/inbound/appointments.py`) : `POST /appointments/{id}/cancellation`
   (client `APPOINTMENT_BOOK`, **pas** de `require_salon_scope`, DI `get_audit_log`) ; schéma
   `CancelAppointmentRequest` (`extra="ignore"`, **seul** `reason`) ; traductions d'erreurs → codes
   HTTP. **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`.**
8. **Fakes de test** : étendre `FakeAppointmentRepository` (mode `not_cancellable`, mémorisation du
   `reason`, transition `CANCELLED`) et réutiliser `FakeAuditLog` dans `conftest.py`.
9. **Tests backend** : domaine, cas d'usage (fakes), API (`TestClient`, anti-élévation +
   deny-by-default), Postgres e2e (annulation, **créneau libéré**, verrou terminé, audit) — **skip**
   sans `DATABASE_URL`.
10. **Mobile** : `AppointmentGateway.cancel` + `NotCancellableException` ; `HttpAppointmentGateway`
    (`POST .../cancellation`) ; use case `CancelAppointment` ; `isClientCancellable` ; bouton
    « Annuler » + dialogue de motif dans « Mes rendez-vous » (verrou UI, `409`/`401` gérés) ; câblage
    `app.dart`/`main.dart` (`onCancel`).
11. **Tests mobile** : passerelle (mock), use case (fakes), widget (bouton + dialogue + flux) ;
    asserter **anti-élévation** (corps sans champs privilégiés) et **non-journalisation** du
    jeton/motif/PII.
12. **Documentation** : ADR-0025 + `docs/adr/README.md` + sections `backend/README.md` /
    `app-mobile/README.md`.
13. **Garde-fous** : `pytest` et `flutter test` (et test gate agrégé) au vert ; aucun secret/jeton/
    motif/PII journalisé ; corps d'annulation sans `client_id`/`salon_id`/`status` ; contrainte
    d'exclusion base **jamais** contournée (l'annulation **libère** un créneau) ;
    `unprotected_routes(app)` **vide** ; **aucun** calcul de CA fabriqué (invariant documenté
    seulement) ; **aucune** signature IA dans le code/commits/PR.
