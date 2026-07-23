# Confirmer/refuser un RDV & cycle de statuts (gérant) (US-3.4)

> Spécification de planification pour l'issue GitHub **#25 — US-3.4 : Confirmer/refuser un
> rendez-vous & cycle de statuts (gérant)** (`feature` · Must · Effort M · PRD §6 Épic 3, §8.1,
> §11.4, §4.1). **Dépend de #22** (réservation) et s'appuie sur le chemin rendez-vous livré par
> **#21/#23/#24** (moteur, modification, annulation). **Cette spec ne produit pas de code** : elle
> décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python), en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants
> techniques (noms de routes, champs JSON, symboles, enums SQL) inchangés. **Aucune signature IA**
> dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 3, US-3.4) pose le besoin : **« en tant que gérant, je veux confirmer ou refuser un
rendez-vous »**, avec pour spécification fonctionnelle les **statuts** : *en attente, confirmé,
annulé, terminé, absent*. Les critères d'acceptation de l'issue #25 sont :

- **Transitions de statut valides** ; **transitions interdites bloquées** ;
- **Changement journalisé** (§11.4) ;
- **assignation optionnelle d'un coiffeur**.

C'est la **contrepartie gérant** du cycle de vie d'un rendez-vous : là où le client réserve (#21/#22),
modifie (#23) et annule (#24) **son** RDV **actif**, le gérant **pilote le statut** d'un RDV de **son
salon** (confirmer une demande en attente, refuser/annuler, marquer réalisé ou absent) et peut
**assigner/réassigner** un coiffeur. Le PRD §8.1 verrouille explicitement cette asymétrie : *« un
rendez-vous terminé ne peut plus être modifié, sauf par le gérant »* — l'« exception gérant » que
#23/#24 ont laissée à #25.

État actuel du dépôt (après #21/#22/#23/#24) :

- **Le socle base porte déjà tout le nécessaire.** La table `appointments` (schéma #3, migration
  `0001`) a `status` (défaut `PENDING`, `CHECK` enum
  `PENDING|CONFIRMED|CANCELLED|COMPLETED|NO_SHOW`), `hairdresser_id` (**nullable**, FK composite vers
  `salon_members`), `cancellation_reason` (`Text` nullable), la colonne générée `slot tsrange` et
  `updated_at` (`onupdate=func.now()`, centralisée par #20). La contrainte d'exclusion
  `ex_appointments_hairdresser_slot` porte sur `status IN ('PENDING','CONFIRMED')`. **Aucune
  migration, table, colonne ni contrainte n'est nécessaire.**
- **Le vocabulaire des statuts existe déjà** : `domain/enums.py::AppointmentStatus` =
  `PENDING | CONFIRMED | CANCELLED | COMPLETED | NO_SHOW` (source de vérité du `CHECK`).
- **Les permissions du gérant pour les RDV existent déjà mais ne sont câblées sur aucune route** :
  `domain/permissions.py` accorde au rôle **`MANAGER`** les permissions **`APPOINTMENT_MANAGE`**,
  **`APPOINTMENT_READ_SALON`** et **`APPOINTMENT_UPDATE_STATUS`** (et au **`HAIRDRESSER`**
  `APPOINTMENT_READ_ASSIGNED` + `APPOINTMENT_UPDATE_STATUS`). Aucune route ne les consomme
  aujourd'hui — #25 est la **première** issue à câbler la gestion gérant des RDV.
- **Le chemin rendez-vous existe et sait déjà écrire/journaliser** (patron *lecture → verrou d'état →
  UPDATE conditionnel → audit* de #23/#24) : `SqlAppointmentRepository` (adapter sortant) porte
  `create`/`update`/`cancel`/`get_owned`/`booked_slots`/`list_for_client`, la traduction de
  l'exclusion base `23P01` → `SlotAlreadyBooked` (**sans journaliser l'erreur brute**), et
  `_ACTIVE_STATUSES = (PENDING, CONFIRMED)`. Le router `adapters/inbound/appointments.py` monte les
  routes **client** (`GET .../availability` public, `POST /salons/{id}/appointments`,
  `GET /appointments`, `PATCH /appointments/{id}`, `POST /appointments/{id}/cancellation`).
- **Le mécanisme d'audit §11.4 est établi et réutilisable** (#17) : `domain/audit.py` (`AuditAction`
  **enum fermé**, `AuditEntry` neutre, `ENTITY_TYPE_APPOINTMENT`), port `AuditLog.record` écrit dans
  la **même** unité de travail que la mutation. #23 a ajouté `APPOINTMENT_UPDATED`, #24
  `APPOINTMENT_CANCELLED`.
- **Aucune notion de « transition de statut valide » n'existe.** Il n'y a **ni** machine à états (quel
  statut peut succéder à quel autre), **ni** cas d'usage gérant, **ni** méthode de port
  `set_status`/`assign_hairdresser`, **ni** route de gestion gérant, **ni** action d'audit dédiée aux
  changements de statut. La lecture salon-scopée (`GET /salons/{id}/appointments`) n'existe pas
  encore (permission `APPOINTMENT_READ_SALON` non câblée).
- **Côté web (Next.js), la section « Planning » est `coming-soon`** (`web-dashboard/src/domain/
  navigation/sections.ts` : `/gerant/planning`), et aucune vue ne liste les RDV d'un salon. La vue
  calendrier/planning relève d'US-3.5 (#26).

Le gap que #25 comble : **(1)** une **machine à états pure** (transitions valides du gérant ;
transitions interdites/terminales bloquées) ; **(2)** un **chemin de transition de statut serveur**
salon-scopé (`APPOINTMENT_UPDATE_STATUS`) qui confirme/refuse/termine/marque-absent un RDV et le
**journalise** (§11.4) ; **(3)** une **assignation optionnelle de coiffeur** (`APPOINTMENT_MANAGE`),
validée contre l'appartenance salon et arbitrée par l'exclusion base, journalisée ; le tout **sans
nouveau schéma**.

## Goals

- **Machine à états pure (domaine).** Une fonction/table pure décrit les **transitions autorisées**
  du gérant entre statuts et **refuse par construction** toute transition non listée (terminale,
  identité, interdite). Statut inconnu → refus (deny-by-default), jamais un passage par défaut.
- **Confirmer / refuser / terminer / marquer absent (gérant).** Un gérant du salon fait passer un RDV
  de **son salon** vers un statut **cible valide** — refus **neutre** (`InvalidAppointmentTransition`
  → `409`) pour une transition interdite. Le changement force le `status` **côté serveur** via la
  machine à états (jamais un `status` arbitraire accepté sans validation).
- **Isolation par salon (§11.2).** La route est **salon-scopée** (`require_salon_scope`) et le dépôt
  **refiltre** `salon_id` : un RDV d'un autre salon (ou inexistant) est un **`404` indiscernable**
  *après* la portée (aucun oracle). Un gérant ne pilote **que** les RDV de son salon.
- **Assignation optionnelle d'un coiffeur.** Le gérant peut **assigner/réassigner/désassigner** un
  coiffeur à un RDV **actif** ; le coiffeur doit être **membre `ACTIVE` du salon**
  (`HairdresserNotInSalon` → `404`) et l'exclusion base arbitre tout conflit d'agenda
  (`SlotAlreadyBooked` → `409`). L'assignation est journalisée.
- **Verrou d'état ré-affirmé à l'écriture (garde TOCTOU).** L'UPDATE est **conditionné au statut
  courant attendu** (`WHERE id = … AND salon_id = … AND status = :expected`) : si le statut a changé
  entre la lecture et l'écriture, aucune ligne n'est affectée → conflit **neutre** (patron #23/#24).
- **Journaliser chaque changement (§11.4).** Chaque transition de statut et chaque assignation écrit
  une `AuditEntry` **neutre** (acteur = gérant, portée = `salon_id`, entité = l'`appointment`) dans la
  **même** unité de travail que l'écriture métier (patron #17/#20/#23/#24). Métadonnées non-PII (p.
  ex. statuts `from`/`to`, valeurs d'énumération).
- **Aucun nouveau schéma.** Toutes les colonnes existent depuis #3 ; #25 **écrit** `status` /
  `hairdresser_id` (et éventuellement `cancellation_reason`) sur une ligne existante.
- **Anti-élévation & confidentialité (§11.2/§11.3).** Le corps ne porte **jamais** `salon_id`
  (chemin), `client_id` ni un `status` non validé ; les messages d'erreur restent **génériques** ;
  aucune PII ni secret n'est journalisé.
- **Couverture de tests.** Machine à états (transitions valides/interdites/terminales), cas d'usage
  (portée salon, verrou, assignation, audit dans la même unité de travail), intégration/HTTP
  (anti-élévation, deny-by-default, `403` hors salon, `404` indiscernable), Postgres e2e (transition
  réelle, verrou terminal, assignation + conflit d'exclusion, libération de créneau, audit).

## Non-Goals

- **Vue planning / calendrier gérant (US-3.5, #26).** #25 livre la **capacité serveur** de piloter le
  statut et d'assigner un coiffeur ; l'**écran web** (liste du jour, calendrier jour/semaine/mois,
  boutons d'action) relève de #26 — la section `/gerant/planning` reste `coming-soon` à l'issue de
  #25. *(Recommandation : ne pas livrer d'UI web dans #25 ; voir Open Questions sur une éventuelle
  lecture salon-scopée minimale.)*
- **Planning personnel du coiffeur (US-3.6, #27).** La lecture « RDV assignés »
  (`APPOINTMENT_READ_ASSIGNED`) et l'éventuelle restriction *« un coiffeur ne pilote que **ses** RDV
  assignés »* relèvent de #27. #25 câble la gestion **gérant** ; la permission
  `APPOINTMENT_UPDATE_STATUS` (partagée) est discutée en Open Questions.
- **Notifications de confirmation / d'annulation (§8.4, Épic 7 #43+).** Le PRD §8.4 prévoit qu'« une
  confirmation/annulation doit notifier le client et le salon » ; ce câblage relève de l'Épic 7. #25
  n'émet **aucune** notification — l'audit §11.4 est une **trace interne**, pas une notification (même
  posture que #24).
- **Calcul de chiffre d'affaires.** L'invariant « seul un RDV `COMPLETED` compte au CA » est **déjà
  matérialisé** (prédicat pur `counts_towards_revenue`, #24) ; #25 **ne calcule aucun CA** (M4/M5).
  Le passage à `COMPLETED` rend simplement le RDV éligible au futur CA — aucun agrégat n'est livré.
- **Politique d'annulation/refus configurable par le salon** (délai, pénalité, fenêtre) : aucun champ
  au schéma ni au PRD (hors périmètre, cf. #24).
- **Réservation « walk-in » par le gérant** (créer un RDV côté gérant) : hors périmètre #25 (le
  gérant **pilote** des RDV existants ; la création reste le tunnel client #22, réutilisable
  ultérieurement).
- **Interface mobile (Flutter).** US-3.4 est un parcours **gérant** (web). Le paquet `app-mobile/`
  n'est **pas** touché.
- **Nouvelle table, migration, colonne ou contrainte** : le schéma existe depuis #3 et suffit.

## Relevant Repository Context

### Stack & architecture

- **Backend** : FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0 + Alembic +
  psycopg 3 (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) — `domain/` et
  `application/` n'importent **jamais** FastAPI ni SQLAlchemy ; RBAC **deny-by-default** (ADR-0015).
  Tests `pytest` (`backend/pyproject.toml`, `testpaths=["tests"]`).
- **Web gérant** : Next.js / React / TypeScript (ADR-0002), zone protégée `/gerant` (cookie
  `httpOnly` + BFF + `GET /auth/me`). **Non touché par #25** (recommandation, cf. Non-Goals).
- **Test gate** agrégé (#6) : `scripts/test-gate.sh` enchaîne `pytest` / `npm test` / `flutter test`.

### Backend rendez-vous déjà livré (#21/#23/#24 — à réutiliser/étendre)

- `coiflink_api/domain/enums.py` — `AppointmentStatus` (`PENDING|CONFIRMED|CANCELLED|COMPLETED|
  NO_SHOW`, hérite de `str`). Source de vérité du `CHECK` (via `values()`).
- `coiflink_api/domain/appointment.py` — `Appointment`, `AppointmentToCreate`, `AppointmentUpdate`,
  `BookedService` ; règles d'état **client** `is_client_modifiable`/`CLIENT_MODIFIABLE_STATUSES`,
  `is_client_cancellable`/`CLIENT_CANCELLABLE_STATUSES` ; `normalize_cancellation_reason`
  (`MAX_CANCELLATION_REASON_LENGTH`) ; invariant CA `counts_towards_revenue`/`REVENUE_STATUSES` ;
  `require_services`, `validate_booking_window`, `compute_end_time`. **#25 y ajoute la machine à états
  gérant.**
- `coiflink_api/domain/errors.py` — erreurs **neutres** (`__all__` maintenu) :
  `AppointmentNotFound` (404), `AppointmentNotModifiable`/`AppointmentNotCancellable`/
  `SlotAlreadyBooked`/`SlotUnavailable`/`SalonNotBookable` (409), `HairdresserNotInSalon` (404), etc.
- `coiflink_api/domain/audit.py` — `AuditAction` (**enum fermé** : `SERVICE_*`, `SALON_UPDATED`,
  `APPOINTMENT_UPDATED`, `APPOINTMENT_CANCELLED`), `AuditEntry`, `ENTITY_TYPE_APPOINTMENT`.
- `coiflink_api/domain/permissions.py` — matrice §4.1. `MANAGER` : `APPOINTMENT_MANAGE`,
  `APPOINTMENT_READ_SALON`, `APPOINTMENT_UPDATE_STATUS` (+ salon/prestations/employés/caisse/stats).
  `HAIRDRESSER` : `APPOINTMENT_READ_ASSIGNED`, `APPOINTMENT_UPDATE_STATUS`. **Aucune** route ne les
  consomme aujourd'hui.
- `coiflink_api/application/appointments.py` — `BookAppointment`, `ModifyAppointment`,
  `CancelAppointment`, `ListMyAppointments` ; helpers **réutilisables** `_load_bookable_salon`,
  `_resolve_booked_services`, **`_require_salon_hairdresser`** (refuse un coiffeur hors salon via
  `SalonScopeRepository.salon_ids_for(id, HAIRDRESSER)`).
- `coiflink_api/application/ports/appointment_repository.py` — `booked_slots`, `create`, `get_owned`,
  `update`, `cancel`, `list_for_client`. **#25 y ajoute la lecture/écriture salon-scopée.**
- `coiflink_api/adapters/outbound/persistence/appointment_repository.py` —
  `SqlAppointmentRepository` : `_ACTIVE_STATUSES`, `update`/`cancel` avec **UPDATE conditionnel** sur
  statut, `_is_exclusion_violation` (SQLSTATE `23P01` / nom de contrainte, message neutre),
  `_to_domain`, `_load_services`.
- `coiflink_api/adapters/inbound/appointments.py` — router : schémas Pydantic `extra="ignore"`, DI
  surchargeables (`get_appointment_repository`, `get_catalog_repository`, `get_audit_log`,
  `get_salon_scope_repository`), `_now()` UTC+0, `_appointment_response(...)` (réponse commune
  `AppointmentResponse` — porte déjà `status` et `hairdresser_id`).
- `coiflink_api/adapters/inbound/security.py` — **`require_salon_scope`** (isolation §11.2, `403`
  générique hors périmètre ; lit `salon_id` du chemin, charge la portée en base), `require_permission`,
  `PUBLIC_ROUTE_PATHS` (n'y **rien** ajouter), invariant `unprotected_routes(app)`.

### Modèle de données pertinent (schéma #3, `models.py`)

- `Appointment` : `id`, `salon_id`, `client_id`, **`hairdresser_id NULL`** (FK composite vers
  `salon_members(salon_id, user_id)`), `appointment_date`, `start_time`, `end_time`, `status` (défaut
  `PENDING`, `CHECK` dérivé de `AppointmentStatus`), `cancellation_reason NULL`, `client_note NULL`,
  `slot tsrange` **`Computed(persisted=True)`**, `created_at`, `updated_at` (`onupdate=func.now()`),
  `UniqueConstraint(salon_id, id)`, exclusion `ex_appointments_hairdresser_slot`
  (`WHERE hairdresser_id IS NOT NULL AND status IN ('PENDING','CONFIRMED')`), index
  `ix_appointments_salon_id (salon_id, appointment_date)` et `ix_appointments_client_id`.
- `AppointmentService` : PK `(appointment_id, service_id)`, `salon_id`, `price_at_booking`, FK
  composites CASCADE/RESTRICT. **Les transitions de statut et l'assignation ne touchent pas les
  jonctions** (prestations + prix figé conservés — historique/CA futur).
- `AuditLog` (§11.4) : `actor_user_id`, `salon_id`, `entity_type`, `entity_id`, `action`,
  `event_metadata` (colonne SQL `metadata`), FK `ON DELETE RESTRICT`.

### RBAC & portée (ADR-0015, #12)

- **Route salon-scopée** = montée sous `/salons/{salon_id}/…` pour que `require_salon_scope` lise
  `salon_id` du chemin et valide la portée du gérant (propriété via `salons.owner_id`). Contrairement
  au client (aucune portée salon → `require_salon_scope` renverrait `403`), **le gérant a une portée
  salon** : la route gérant **utilise** `require_salon_scope` (patron `services.py` #17).
- Chaîne : `require_authenticated` (globale) → `get_current_principal` (rôle/statut **relus en base**)
  → `require_permission(...)` → `require_salon_scope` → handler. Refus `401`/`403` **constants et
  génériques** (aucun oracle).

### Journalisation d'audit §11.4 (#17/#20/#23/#24 — patron à réutiliser)

- Diff/contexte **neutre** → `repository.<write>(...)` → `audit_log.record(AuditEntry(...,
  metadata={...neutre...}))`, **même** `Session` que la mutation (`get_audit_log(session)` déjà exposé
  dans `adapters/inbound/appointments.py`). Métadonnées : jamais de valeur sensible/PII ; les
  **valeurs d'énumération** de statut (`PENDING`, `CONFIRMED`…) ne sont **pas** des PII et sont
  admissibles.

## Proposed Implementation

Périmètre recommandé : **étendre** le chemin rendez-vous par une **capacité gérant** au-dessus du
schéma inchangé — une **machine à états pure**, un **cas d'usage de transition** et un **cas d'usage
d'assignation**, exposés par des **routes salon-scopées** protégées, chacune **journalisée** (§11.4).
**Backend uniquement** ; l'UI web (planning) est portée par #26 (cf. Non-Goals & Open Questions).

### Backend

#### 1. Domaine (`domain/appointment.py`, `domain/errors.py`, `domain/audit.py`)

- **Machine à états gérant (pure)** dans `domain/appointment.py` :
  - `TERMINAL_STATUSES: frozenset[str] = frozenset({CANCELLED, COMPLETED, NO_SHOW})` (aucune
    transition sortante).
  - **Table de transitions autorisées** (recommandée — voir Open Questions pour les variantes) :
    ```
    ALLOWED_STATUS_TRANSITIONS = {
        PENDING:   {CONFIRMED, CANCELLED, NO_SHOW},
        CONFIRMED: {COMPLETED, CANCELLED, NO_SHOW},
        CANCELLED: {},   # terminal
        COMPLETED: {},   # terminal
        NO_SHOW:   {},   # terminal
    }
    ```
    Sémantique métier : `PENDING → CONFIRMED` = *confirmer* ; `PENDING → CANCELLED` = *refuser* ;
    `CONFIRMED → COMPLETED` = *terminé/réalisé* ; `CONFIRMED → NO_SHOW` = *absent* ;
    `CONFIRMED → CANCELLED` = *annulation gérant*. Les états terminaux sont **verrouillés** (« un RDV
    terminé ne peut plus être modifié », §8.1). L'**identité** (`X → X`) n'est **pas** une transition
    valide (deny-by-default, cohérent avec le refus d'un no-op silencieux — voir Open Questions).
  - `is_valid_transition(current: str, target: str) -> bool` : fonction **pure**, `target in
    ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())`. Un `current`/`target` inconnu → `False`
    (jamais un accès par défaut). Documenter que le verrou est **ré-affirmé** à l'écriture (UPDATE
    conditionnel sur le statut courant attendu, garde TOCTOU).
- **Nouvelle erreur neutre** dans `domain/errors.py` (mettre à jour `__all__`) :
  - `InvalidAppointmentTransition(DomainError)` : la transition demandée n'est pas autorisée (état
    terminal, transition interdite, ou statut courant changé sous la garde TOCTOU). Message neutre
    (« Cette transition de statut n'est pas autorisée. »). → **`409 Conflict`** *(conflit d'état,
    cohérent avec `AppointmentNotModifiable`/`AppointmentNotCancellable` ; voir Open Questions
    409 vs 422)*.
  - *(Réutiliser `AppointmentNotFound` pour inexistant/hors salon **après** portée ;
    `HairdresserNotInSalon` pour un coiffeur hors salon ; `SlotAlreadyBooked` pour un conflit
    d'assignation — tous déjà livrés.)*
- **Nouvelle(s) action(s) d'audit** dans `domain/audit.py` (enum fermé `AuditAction`) :
  - `APPOINTMENT_STATUS_CHANGED = "APPOINTMENT_STATUS_CHANGED"` (§11.4 — changement de statut
    gérant : confirmation/refus/terminé/absent) ;
  - `APPOINTMENT_HAIRDRESSER_ASSIGNED = "APPOINTMENT_HAIRDRESSER_ASSIGNED"` **ou** réutilisation de
    `APPOINTMENT_UPDATED` avec `{"changed": ["hairdresser_id"]}` pour l'assignation (voir Open
    Questions). `ENTITY_TYPE_APPOINTMENT` existe déjà.

#### 2. Port & adapter (persistance)

- **Port** `application/ports/appointment_repository.py` — ajouter :
  - `get_in_salon(appointment_id: UUID, salon_id: UUID) -> Appointment | None` : charge le RDV **et**
    ses `BookedService` **ssi** il appartient à `salon_id` (isolation §11.2 en SQL, filtre
    `id == … AND salon_id == …`). `None` si inexistant **ou** hors salon (indiscernables → `404`
    *après* portée). *(Analogue salon-scopé de `get_owned` #23.)*
  - `set_status(appointment_id: UUID, salon_id: UUID, *, expected_current: str, target: str, reason:
    str | None = None) -> Appointment` : **UPDATE conditionnel**
    `WHERE id = :id AND salon_id = :salon_id AND status = :expected_current` posant `status = :target`
    (et `cancellation_reason = :reason` **uniquement** si `target = CANCELLED` — voir Open Questions).
    Si `rowcount == 0` (RDV disparu, hors salon, ou statut changé sous la garde TOCTOU) → lève
    `InvalidAppointmentTransition`. Retourne l'entité relue (`_to_domain` + `_load_services`).
    *N.B. : une transition de statut ne peut **pas** violer l'exclusion base* — elle ne fait que
    retirer le RDV de l'ensemble actif (`→` terminal) ou le maintenir avec le **même** créneau/
    coiffeur (`PENDING → CONFIRMED`) ; aucune nouvelle occupation concurrente n'est introduite.
  - `assign_hairdresser(appointment_id: UUID, salon_id: UUID, *, hairdresser_id: UUID | None) ->
    Appointment` : **UPDATE conditionnel** sur le **statut actif** (`WHERE id = … AND salon_id = …
    AND status IN (PENDING, CONFIRMED)`) posant `hairdresser_id`. `rowcount == 0` →
    `InvalidAppointmentTransition` (RDV terminal/absent : assignation non pertinente — voir Open
    Questions). **Traduit la violation d'exclusion** `23P01` → `SlotAlreadyBooked` (le coiffeur
    assigné est déjà occupé sur ce créneau ; `_is_exclusion_violation` + rollback + message neutre,
    **sans journaliser l'erreur brute**). Une **désassignation** (`hairdresser_id = None`) ne peut
    jamais violer l'exclusion (retire le RDV de la portée `hairdresser_id IS NOT NULL`).
- **Adapter** `adapters/outbound/persistence/appointment_repository.py` — `SqlAppointmentRepository` :
  implémenter `get_in_salon`, `set_status`, `assign_hairdresser` en réutilisant `_ACTIVE_STATUSES`,
  `_is_exclusion_violation`, `_to_domain`, `_load_services` et le patron `flush()` (commit piloté par
  `get_session`). **Aucune** modification de schéma ; `updated_at` (`onupdate`) se rafraîchit
  automatiquement.

#### 3. Application (`application/appointments.py`)

- **Cas d'usage** `class SetAppointmentStatus` (constructeur : `appointment_repository`, `audit_log`).
  `execute(appointment_id, salon_id, actor_id, target_status, *, reason=None) -> Appointment` :
  1. **Charger le RDV du salon** : `current = repo.get_in_salon(appointment_id, salon_id)` ; `None` →
     `AppointmentNotFound` (couvre inexistant **et** hors salon — aucun oracle).
  2. **Valider la transition** : `if not is_valid_transition(current.status, target_status): raise
     InvalidAppointmentTransition(...)` (transition interdite/terminale).
  3. **Écriture transactionnelle** : `updated = repo.set_status(appointment_id, salon_id,
     expected_current=current.status, target=target_status, reason=normalize_cancellation_reason(
     reason) if target_status == CANCELLED else None)` — UPDATE conditionnel (garde TOCTOU).
  4. **Audit §11.4** : `audit_log.record(AuditEntry(action=APPOINTMENT_STATUS_CHANGED,
     actor_user_id=actor_id, salon_id=salon_id, entity_type=ENTITY_TYPE_APPOINTMENT,
     entity_id=appointment_id, metadata={"from": current.status, "to": target_status}))` — valeurs
     d'énumération **non-PII** ; **jamais** le texte d'un motif ni de PII.
- **Cas d'usage** `class AssignHairdresser` (constructeur : `appointment_repository`,
  `scope_repository`, `audit_log`). `execute(appointment_id, salon_id, actor_id, hairdresser_id) ->
  Appointment` :
  1. `current = repo.get_in_salon(...)` ; `None` → `AppointmentNotFound`.
  2. Si `hairdresser_id is not None` : `_require_salon_hairdresser(scope, salon_id, hairdresser_id)`
     (coiffeur **membre `ACTIVE` du salon**, sinon `HairdresserNotInSalon` → `404`).
  3. `updated = repo.assign_hairdresser(appointment_id, salon_id, hairdresser_id=hairdresser_id)`
     (UPDATE conditionnel actif ; exclusion base → `SlotAlreadyBooked`).
  4. Audit `APPOINTMENT_HAIRDRESSER_ASSIGNED` (ou `APPOINTMENT_UPDATED` `{"changed":
     ["hairdresser_id"]}`), même unité de travail. Métadonnées **neutres** (nom de champ ; l'UUID du
     coiffeur, opaque, peut être omis — voir Open Questions).
- Ajouter `SetAppointmentStatus`, `AssignHairdresser` à `__all__`. Aucun catalogue requis (on ne
  re-valide **pas** l'offre : le gérant pilote un RDV existant ; l'assignation ne dépend que de
  l'appartenance salon du coiffeur et de l'exclusion base).

#### 4. Adapter entrant (HTTP)

- **Router** `adapters/inbound/appointments.py` — ajouter deux routes **salon-scopées** protégées :
  - `POST /salons/{salon_id}/appointments/{appointment_id}/status` — **gérant**
    (`require_permission(APPOINTMENT_UPDATE_STATUS)` **+** `require_salon_scope`). Corps
    `SetStatusRequest` (`extra="ignore"`) : `status: AppointmentStatus` (**énumération** — une valeur
    hors enum est **`422`** par Pydantic) et, optionnellement, `reason: str | None` (persisté
    **seulement** si `status = CANCELLED`). DI : `get_appointment_repository`, `get_audit_log`.
    Traductions : `AppointmentNotFound` → `404` ; `InvalidAppointmentTransition` → `409`. Réponse
    `200` `AppointmentResponse` (schéma existant).
    - **Forme de route & `status` dans le corps — divergence assumée vs le client.** Le client
      annule via une **sous-ressource d'action** (`POST .../cancellation`) *sans* soumettre de
      `status` (anti-élévation). Le gérant, lui, **choisit légitimement la cible** : c'est **la
      machine à états du domaine** (deny-by-default) — pas le client — qui est le juge, et l'acteur
      détient `APPOINTMENT_UPDATE_STATUS` **+** la portée salon. Un `status` **validé par l'enum et la
      table de transitions** est donc admissible ici. Alternatives (sous-ressources
      `/confirmation`/`/refusal`/`/completion`/`/no-show`) en Open Questions ; **recommandation :
      route de transition unique `/status`** (extensible, une seule traduction d'erreurs).
  - `PUT /salons/{salon_id}/appointments/{appointment_id}/hairdresser` — **gérant**
    (`require_permission(APPOINTMENT_MANAGE)` **+** `require_salon_scope`). Corps `AssignHairdresser
    Request` (`extra="ignore"`) : `hairdresser_id: uuid.UUID | None` (**assignation** ou
    **désassignation** explicite). DI : `get_appointment_repository`, `get_salon_scope_repository`,
    `get_audit_log`. Traductions : `AppointmentNotFound`/`HairdresserNotInSalon` → `404` ;
    `SlotAlreadyBooked` → `409` ; `InvalidAppointmentTransition` (RDV terminal) → `409`. Réponse
    `200` `AppointmentResponse`.
  - `actor_id = principal.id` (retourné par la garde de permission). `salon_id` **du chemin**
    (jamais du corps). Réutiliser `_appointment_response(...)` et `_now()`.
- **Composition root** `coiflink_api/main.py` : le router rendez-vous est **déjà monté** ; les
  nouvelles routes en héritent. **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`** (routes **protégées**).
  Vérifier que l'invariant `unprotected_routes(app)` reste vide (test existant).

### Documentation & ADR

- **ADR-0026 — Cycle de statuts & gestion gérant d'un rendez-vous** (numéro libre suivant —
  **vérifier** au step `document` : `docs/adr/` s'arrête à `0025`) actant : **machine à états pure**
  (table de transitions ; états terminaux verrouillés §8.1), routes **salon-scopées**
  (`require_salon_scope`, permission `APPOINTMENT_UPDATE_STATUS` / `APPOINTMENT_MANAGE`), **UPDATE
  conditionnel** sur statut attendu (garde TOCTOU), **assignation optionnelle** (appartenance salon +
  exclusion base → `SlotAlreadyBooked`), journalisation `APPOINTMENT_STATUS_CHANGED` /
  `APPOINTMENT_HAIRDRESSER_ASSIGNED` (§11.4), **`status` dans le corps** admissible côté gérant (juge
  = domaine), backend **sans nouveau schéma**, notification (§8.4) différée à l'Épic 7, UI planning
  différée à #26. Indexer dans `docs/adr/README.md`.
- **`backend/README.md`** : section « Cycle de statuts d'un rendez-vous (gérant) ».
- **`prd-coiflink.md` : ne pas modifier**. Récit `README.md` §6 (« M3 en cours ») : à compléter au
  step `document` **une fois livré**.

## Affected Files / Packages / Modules

**Backend — à modifier :**
- `backend/coiflink_api/domain/appointment.py` — `ALLOWED_STATUS_TRANSITIONS`, `TERMINAL_STATUSES`,
  `is_valid_transition`, `__all__`.
- `backend/coiflink_api/domain/errors.py` — `InvalidAppointmentTransition` (+ `__all__`).
- `backend/coiflink_api/domain/audit.py` — `AuditAction.APPOINTMENT_STATUS_CHANGED` (+
  `APPOINTMENT_HAIRDRESSER_ASSIGNED` ou réutilisation `APPOINTMENT_UPDATED`).
- `backend/coiflink_api/application/appointments.py` — `SetAppointmentStatus`, `AssignHairdresser`
  (+ `__all__`).
- `backend/coiflink_api/application/ports/appointment_repository.py` — `get_in_salon`, `set_status`,
  `assign_hairdresser`.
- `backend/coiflink_api/adapters/outbound/persistence/appointment_repository.py` — implémentations.
- `backend/coiflink_api/adapters/inbound/appointments.py` — routes `POST
  /salons/{salon_id}/appointments/{id}/status` et `PUT /salons/{salon_id}/appointments/{id}/
  hairdresser`, schémas Pydantic, DI, traductions d'erreurs.
- `backend/tests/conftest.py` — étendre `FakeAppointmentRepository` (`get_in_salon`, `set_status`,
  `assign_hairdresser` ; modes `raise_invalid_transition`, `raise_conflict` pour l'assignation ;
  mémorisation `(from, to)` / `hairdresser_id`) et réutiliser `FakeAuditLog`, `FakeSalonScope
  Repository`.

**Backend — à lire (contexte) :** `application/appointments.py::{ModifyAppointment,
CancelAppointment,_require_salon_hairdresser}` (patrons portée→verrou→UPDATE conditionnel→audit +
validation coiffeur) ; `adapters/inbound/appointments.py` (DI `get_audit_log`, réponses, `_now`) ;
`adapters/inbound/security.py` (`require_salon_scope`, deny-by-default) ; `adapters/inbound/
services.py` (patron route salon-scopée `/salons/{salon_id}/…`) ; `adapters/outbound/persistence/
appointment_repository.py` (`update`/`cancel`/`_is_exclusion_violation`/`_to_domain`) ; `models.py`
(`Appointment` : `status`/`hairdresser_id`/`updated_at`/EXCLUDE) ; `tests/test_appointment_*`
(patrons fakes + skip Postgres).

**Docs :** `docs/adr/0026-*.md` (numéro à confirmer) + `docs/adr/README.md`, `backend/README.md`.
**`prd-coiflink.md` : ne pas modifier.** Récit `README.md` §6 : à compléter au step `document` **une
fois livré**.

**Non touchés :** `app-mobile/` (feature gérant, pas cliente), `web-dashboard/` (UI planning → #26 —
sauf décision contraire, voir Open Questions).

## API / Interface Changes

**Nouvelles routes backend** (protégées, jamais publiques, **salon-scopées**) :

- `POST /salons/{salon_id}/appointments/{appointment_id}/status` — **gérant**
  (`APPOINTMENT_UPDATE_STATUS` + portée salon). Corps `{status: "CONFIRMED"|"CANCELLED"|"COMPLETED"|
  "NO_SHOW"|"PENDING", reason?: string}` (`extra="ignore"` ; `salon_id`/`client_id` **jamais** dans
  le corps). Réponses : `200` `AppointmentResponse` (statut cible) ; `401` jeton absent/expiré ;
  `403` rôle insuffisant **ou** salon hors périmètre (identiques, aucun oracle) ; `404` RDV
  inexistant/hors salon (après portée) ; `409` transition interdite/terminale (ou statut changé sous
  garde TOCTOU) ; `422` valeur de `status` hors énumération. Documentation OpenAPI (docstrings +
  `responses`).
- `PUT /salons/{salon_id}/appointments/{appointment_id}/hairdresser` — **gérant** (`APPOINTMENT_MANAGE`
  + portée salon). Corps `{hairdresser_id: string | null}` (`extra="ignore"`). Réponses : `200`
  `AppointmentResponse` ; `401` ; `403` (rôle/salon) ; `404` RDV hors salon **ou** coiffeur hors
  salon (indiscernables) ; `409` conflit d'agenda (`SlotAlreadyBooked`) ou RDV terminal ; `422`
  corps invalide.

**Réutilisé tel quel :** `AppointmentResponse` (porte déjà `status`, `hairdresser_id`). **Aucune
modification** des routes client existantes (`GET .../availability`, `POST /salons/{id}/appointments`,
`GET /appointments`, `PATCH /appointments/{id}`, `POST /appointments/{id}/cancellation`).

## Data Model / Protocol Changes

**Aucune.** Les colonnes `status` (`CHECK` enum), `hairdresser_id` (FK composite `salon_members`),
`cancellation_reason` (`Text` nullable), la colonne générée `slot`, `updated_at` (`onupdate`) et la
contrainte d'exclusion `ex_appointments_hairdresser_slot` **existent depuis #3**. #25 **écrit**
`status` / `hairdresser_id` (et `cancellation_reason` seulement sur `CANCELLED`) sur une ligne
existante — **ni table, ni migration, ni colonne, ni contrainte**. La table `audit_logs` (§11.4)
reçoit une ligne par changement (action ajoutée à l'enum fermé `AuditAction`, **sans** migration —
l'action est une valeur `text`, pas un type SQL). Le contrat de fil (`AppointmentResponse`) est
inchangé.

## Security & Privacy Considerations

- **Isolation par salon (§11.2)** : les routes sont **salon-scopées** (`require_salon_scope`, `403`
  générique hors périmètre) **et** le dépôt refiltre `salon_id` (`get_in_salon`, UPDATE conditionnel
  `AND salon_id = …`) — défense en profondeur. Le `salon_id` vient **du chemin**, jamais du corps ;
  le `client_id` du RDV n'est jamais réécrit. Un RDV d'un autre salon est un **`404` indiscernable**
  *après* la portée (aucun oracle).
- **Anti-élévation (§11.2)** : le corps ne porte **jamais** `salon_id`/`client_id` (`extra="ignore"`).
  Le `status` soumis n'ouvre **aucun** privilège : il est **doublement contraint** (énumération
  Pydantic → `422` ; table de transitions du domaine → `409`) et exige la permission
  `APPOINTMENT_UPDATE_STATUS` + la portée salon. Le juge de la transition est **le domaine**, pas le
  client (deny-by-default).
- **Assignation & exclusion (§11.2)** : un `hairdresser_id` soumis est **validé contre
  `salon_members`** (`_require_salon_hairdresser`) — l'exclusion base ne porte pas `salon_id` et ne
  peut arbitrer un coiffeur hors salon ; sans ce contrôle, un gérant pourrait occuper l'agenda d'un
  coiffeur d'un autre salon. Le conflit d'agenda (coiffeur déjà pris) est arbitré par l'exclusion base
  → `SlotAlreadyBooked` (message **neutre** ; l'`IntegrityError` brute **n'est jamais journalisée**).
- **Verrou d'état / garde TOCTOU (§8.1)** : un RDV terminal (`CANCELLED`/`COMPLETED`/`NO_SHOW`) est
  **verrouillé** (`InvalidAppointmentTransition`) au niveau du domaine **et** ré-affirmé par l'UPDATE
  conditionnel (`status = :expected_current`). Un changement concurrent (double clic, course avec le
  client #24) → `409` cohérent, jamais une transition « fantôme ».
- **Journalisation §11.3/§11.4 sans fuite** : chaque `AuditEntry` (`APPOINTMENT_STATUS_CHANGED` /
  `APPOINTMENT_HAIRDRESSER_ASSIGNED`) est **neutre** — `actor_user_id`/`entity_id` UUID **opaques**,
  `metadata` limitée à des **valeurs d'énumération de statut** (`{"from","to"}`, non-PII) et/ou des
  **noms de champs** (`{"changed": ["hairdresser_id"]}`). **Jamais** de texte de motif, de PII ni de
  secret. Le `cancellation_reason` (si supporté sur `CANCELLED`) est **persisté** mais **jamais**
  journalisé (patron #24).
- **Messages neutres** : `AppointmentNotFound`/`InvalidAppointmentTransition`/`SlotAlreadyBooked`/
  `HairdresserNotInSalon` portent des messages **génériques** ; les refus RBAC restent les `401`/`403`
  **constants** de `security.py`.
- **Budgets §12** : lecture + écriture conditionnelle restent bien en deçà du budget API (< 3 s) ;
  l'index `ix_appointments_salon_id (salon_id, appointment_date)` et la PK couvrent les accès.
- **Résidence/hébergement** : inchangés (ADR-0011). Aucun secret manipulé ni journalisé.

## Testing Plan

Test gate : `pytest` (backend). Convention : tests **Postgres** *skip proprement* sans `DATABASE_URL`
(patron `test_appointment_*` / `test_salon_update_e2e.py`) ; en unitaire, **fakes** injectés via
`app.dependency_overrides`, **aucun** accès base réel. Les tests existants restent **verts** (seule
extension **additive** de `conftest`).

- **Unit — machine à états** `tests/test_domain_appointment.py` (étendre) : `is_valid_transition`
  → `True` pour chaque transition de `ALLOWED_STATUS_TRANSITIONS` ; `False` pour toute transition
  terminale (`CANCELLED/COMPLETED/NO_SHOW → *`), l'identité (`X → X`), une transition interdite
  (p. ex. `COMPLETED → CONFIRMED`, `PENDING → COMPLETED`) et un statut inconnu. `TERMINAL_STATUSES`
  correct.
- **Unit — application (fakes)** `tests/test_appointment_usecases.py` (étendre) :
  - `SetAppointmentStatus` : refuse un RDV **hors salon/inexistant** (`AppointmentNotFound`) ; refuse
    une **transition interdite/terminale** (`InvalidAppointmentTransition`) ; confirme
    (`PENDING → CONFIRMED`), refuse (`PENDING → CANCELLED`), termine (`CONFIRMED → COMPLETED`), marque
    absent (`CONFIRMED → NO_SHOW`) ; l'audit `APPOINTMENT_STATUS_CHANGED` est écrit dans la **même**
    unité de travail avec `metadata={"from","to"}` (valeurs d'énumération, **sans** PII) ; `salon_id`
    du chemin (jamais du corps).
  - `AssignHairdresser` : assigne un coiffeur **du salon** ; **désassigne** (`None`) ; refuse un
    coiffeur **hors salon** (`HairdresserNotInSalon`) ; propage `SlotAlreadyBooked` (conflit
    d'agenda) ; refuse un RDV terminal (`InvalidAppointmentTransition`) ; audit écrit (même unité de
    travail), **sans** PII.
- **Intégration/HTTP** `tests/test_appointment_api.py` (étendre, `TestClient` + fakes) :
  - `POST /salons/{id}/appointments/{aid}/status` : `200` sur transition valide (statut cible reflété)
    ; `409` sur transition interdite/terminale ; `422` sur `status` hors énumération ; `404` sur RDV
    d'un autre salon (après portée) ; `403` **rôle non habilité** et **gérant d'un autre salon**
    (messages identiques) ; `401` sans jeton ; corps portant `salon_id`/`client_id` → **ignorés**
    (anti-élévation).
  - `PUT /salons/{id}/appointments/{aid}/hairdresser` : `200` assignation/désassignation ; `404`
    coiffeur hors salon ; `409` conflit d'agenda ; `403`/`401` idem.
  - **Invariant deny-by-default** : `unprotected_routes(app)` reste **vide** (test existant
    `test_security_guards`/`test_rbac_e2e`), **sans** ajouter les chemins à `PUBLIC_ROUTE_PATHS`.
- **Intégration Postgres** `tests/test_appointment_status_e2e.py` (nouveau, skip sans `DATABASE_URL`) :
  - transitions réelles `PENDING → CONFIRMED → COMPLETED` (statut persisté, `updated_at` rafraîchi) ;
  - **verrou terminal** : `CANCELLED`/`COMPLETED`/`NO_SHOW → *` = `409` ;
  - **garde TOCTOU** : `expected_current` non satisfait (RDV passé terminal) → `409` ;
  - **assignation** : coiffeur du salon assigné → `200` ; conflit d'exclusion (coiffeur déjà pris sur
    le créneau) → `SlotAlreadyBooked`/`409` ; **désassignation** → `200` ;
  - **libération de créneau** : `CONFIRMED → NO_SHOW`/`CANCELLED` sort le RDV de l'ensemble actif — un
    nouveau RDV du **client** sur ce créneau/coiffeur **réussit** (preuve via `booked_slots`/
    `availability`) ;
  - une entrée `audit_logs` `APPOINTMENT_STATUS_CHANGED` / `APPOINTMENT_HAIRDRESSER_ASSIGNED`
    **neutre** est écrite (métadonnées sans PII, `salon_id`/acteur corrects).
- **Matrice RBAC** `tests/test_permissions.py` (si touché) : figer que `MANAGER` détient
  `APPOINTMENT_UPDATE_STATUS`/`APPOINTMENT_MANAGE` et que `CLIENT` ne les a **pas** (déjà couvert par
  la matrice ; ré-affirmer si une permission est ajoutée — **aucune** nouvelle permission n'est
  requise a priori).
- **Documentation** : revue que `backend/README.md` documente les transitions, le verrou terminal,
  l'assignation, l'audit et les prérequis Postgres des e2e.

## Documentation Updates

- **`docs/adr/0026-*.md`** (nouveau — **confirmer le numéro** au step `document`) + entrée
  **`docs/adr/README.md`** : machine à états, routes salon-scopées, UPDATE conditionnel (garde
  TOCTOU), assignation (appartenance salon + exclusion base), journalisation §11.4, `status` admissible
  côté gérant (juge = domaine), backend sans nouveau schéma, frontière avec #23/#24 (client) et
  #26/#27 (planning), notification (§8.4) différée à l'Épic 7.
- **`backend/README.md`** : section « Cycle de statuts d'un rendez-vous (gérant) » (routes,
  transitions valides/interdites, verrou terminal, assignation, conflit d'agenda, audit, prérequis
  Postgres des tests e2e).
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison —
  **ne pas anticiper** de comportement non implémenté (ne pas laisser croire qu'un planning web ou une
  notification existent).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstrings + `responses` sur les deux nouvelles routes (généré par FastAPI).

## Risks and Open Questions

- **Périmètre UI web.** *Recommandation : #25 = **backend seul** (machine à états + routes + audit) ;
  la vue planning (liste/calendrier + boutons d'action) relève d'US-3.5 (#26).* Précédent : ADR-0023
  (#21 a livré le moteur + une route minimale ; le tunnel #22 s'est superposé). **À confirmer.**
- **Lecture salon-scopée (`GET /salons/{salon_id}/appointments`, `APPOINTMENT_READ_SALON`).** Sans
  elle, le gérant n'a pas de liste pour **choisir** le RDV à piloter (les tests créent un RDV
  `PENDING` via le tunnel/insert direct puis le transitionnent). *Recommandation : **différer** cette
  lecture à #26* (elle est le cœur du « planning du jour »). Alternative : livrer une lecture minimale
  dès #25 (faible coût, mais chevauche #26). **À confirmer.**
- **Table de transitions.** Recommandée : `PENDING → {CONFIRMED, CANCELLED, NO_SHOW}` ;
  `CONFIRMED → {COMPLETED, CANCELLED, NO_SHOW}` ; terminaux fermés. **Points à trancher :**
  (a) `PENDING → NO_SHOW` autorisé (client absent alors que le RDV n'a jamais été confirmé) —
  *recommandé oui* ; (b) `PENDING → COMPLETED` — *recommandé **non*** (confirmer d'abord) ;
  (c) identité `X → X` — *recommandé **non*** (pas de no-op silencieux, `409`) ; (d) retours
  (`CONFIRMED → PENDING`, `NO_SHOW → CONFIRMED` pour corriger une erreur) — *recommandé **non** au
  MVP* (terminaux immuables). **À confirmer.**
- **Code HTTP d'une transition connue mais interdite.** `409 Conflict` (*recommandé*, conflit d'état,
  cohérent avec `AppointmentNotModifiable`/`AppointmentNotCancellable`) vs `422` (règle métier). Une
  **valeur de `status` hors énumération** reste `422` (Pydantic). **À confirmer.**
- **`status` dans le corps (gérant) vs sous-ressources d'action.** Route de transition unique
  `POST .../status` avec `{status}` validé par la machine à états (*recommandé* — extensible, une
  traduction d'erreurs) vs sous-ressources (`/confirmation`, `/refusal`, `/completion`, `/no-show`) —
  plus verbeuses mais « sans `status` soumis » comme le client #24. La divergence est **assumée** (le
  juge est le domaine ; l'acteur est habilité + scopé). **À confirmer.**
- **Permission de la route de transition.** `APPOINTMENT_UPDATE_STATUS` (*recommandé* — permission
  sémantiquement dédiée ; détenue par `MANAGER` **et** `HAIRDRESSER`) + `require_salon_scope`.
  **Conséquence** : un `HAIRDRESSER` avec portée salon pourrait déjà transitionner un RDV de son salon
  — la restriction « **assigné** seulement » relève de #27 (US-3.6). Alternative : gater #25 strictement
  gérant (`APPOINTMENT_MANAGE` ou `require_roles(MANAGER)`) et laisser le câblage coiffeur à #27. **À
  confirmer.**
- **Permission de l'assignation.** `APPOINTMENT_MANAGE` (*recommandé* — acte de **gestion**,
  `MANAGER` seul) vs `APPOINTMENT_UPDATE_STATUS`. **À confirmer.**
- **Assignation sur un RDV terminal.** *Recommandé : autorisée **uniquement** sur un RDV actif*
  (`PENDING`/`CONFIRMED`) — l'assignation d'un coiffeur à un RDV `COMPLETED`/`NO_SHOW`/`CANCELLED` n'a
  pas de sens (créneau libéré). Alternative : autoriser l'enregistrement rétroactif du coiffeur ayant
  réalisé un `COMPLETED` (utile aux stats coiffeur M5) — nécessiterait de sortir l'UPDATE de la
  condition « actif ». **À confirmer.**
- **Motif de refus/annulation gérant.** Réutiliser `cancellation_reason` + `normalize_cancellation_
  reason` sur `PENDING/CONFIRMED → CANCELLED` (*recommandé* — cohérent avec #24, persisté, **jamais**
  journalisé) vs ne pas supporter de motif gérant au MVP. **À confirmer.**
- **Action(s) & métadonnées d'audit.** `APPOINTMENT_STATUS_CHANGED` avec `{"from","to"}` (valeurs
  d'énumération non-PII, *recommandé*) — une transition vers `CANCELLED` par le gérant pourrait
  **alternativement** journaliser `APPOINTMENT_CANCELLED` (aligné sur §11.4 « Annulation » et le
  chemin client #24). Assignation : action dédiée `APPOINTMENT_HAIRDRESSER_ASSIGNED` vs réutilisation
  `APPOINTMENT_UPDATED` `{"changed":["hairdresser_id"]}`. Inclure/omettre l'UUID (opaque) du coiffeur
  dans `metadata` (*recommandé : omettre*, nom de champ suffit). **À confirmer.**
- **Notification (§8.4 / US-7.4).** Hors périmètre #25 (Épic 7, #43+). Confirmer qu'aucune
  notification n'est attendue (seule la trace d'audit §11.4) — la table PRD §6 mentionne
  « Notification au salon » pour l'annulation, portée par l'Épic 7. **À noter.**
- **Interaction avec l'annulation client #24.** Un client annule (`→ CANCELLED`) un RDV que le gérant
  s'apprêtait à confirmer : la garde TOCTOU (`expected_current`) fait échouer proprement la transition
  gérant en `409`. Cohérent, à **couvrir par test**. **À noter.**
- **Numéro d'ADR.** `docs/adr/` s'arrête à `0025` ; le prochain libre est **0026** — **vérifier** au
  step `document`.
- **Outillage Postgres en test** : s'aligner sur les e2e existants (skip conditionnel sur
  `DATABASE_URL`) — les transitions elles-mêmes sont testables sur fakes, mais l'exclusion base
  (conflit d'assignation) et la libération de créneau exigent Postgres.

## Implementation Checklist

1. **Lire** : `application/appointments.py::{ModifyAppointment,CancelAppointment,
   _require_salon_hairdresser}` ; `adapters/inbound/appointments.py` (DI, réponses) ;
   `adapters/inbound/security.py` (`require_salon_scope`) ; `adapters/inbound/services.py` (route
   salon-scopée `/salons/{salon_id}/…`) ; `adapters/outbound/persistence/appointment_repository.py`
   (`update`/`cancel`/`_is_exclusion_violation`/`_to_domain`) ; `domain/appointment.py`,
   `domain/errors.py`, `domain/audit.py`, `domain/permissions.py`, `models.py`.
2. **Trancher les Open Questions structurantes** (périmètre UI/lecture, table de transitions, code
   409 vs 422, forme de route & `status` dans le corps, permissions, assignation sur terminal, motif
   gérant, actions/métadonnées d'audit) et les acter dans **ADR-0026** (+ `docs/adr/README.md`).
3. **Domaine** : `ALLOWED_STATUS_TRANSITIONS`/`TERMINAL_STATUSES`/`is_valid_transition`
   (`domain/appointment.py`, `__all__`) ; `InvalidAppointmentTransition` (`domain/errors.py`,
   `__all__`) ; `AuditAction.APPOINTMENT_STATUS_CHANGED` (+ `APPOINTMENT_HAIRDRESSER_ASSIGNED` ou
   réutilisation) (`domain/audit.py`).
4. **Port** (`application/ports/appointment_repository.py`) : `get_in_salon`, `set_status`,
   `assign_hairdresser`.
5. **Cas d'usage** (`application/appointments.py`) : `SetAppointmentStatus` (portée salon → validation
   transition → `set_status` conditionnel → audit `APPOINTMENT_STATUS_CHANGED`) et `AssignHairdresser`
   (portée salon → coiffeur du salon → `assign_hairdresser` (exclusion → `SlotAlreadyBooked`) →
   audit) + `__all__`.
6. **Adapter sortant** (`SqlAppointmentRepository`) : `get_in_salon`, `set_status` (UPDATE conditionnel
   `WHERE id AND salon_id AND status = :expected`, `rowcount==0` → `InvalidAppointmentTransition` ;
   `cancellation_reason` seulement si `CANCELLED`), `assign_hairdresser` (UPDATE conditionnel actif ;
   `_is_exclusion_violation` → rollback + `SlotAlreadyBooked` ; relecture `_to_domain`/`_load_services`).
7. **Adapter entrant** (`adapters/inbound/appointments.py`) : `POST /salons/{salon_id}/appointments/
   {id}/status` (`APPOINTMENT_UPDATE_STATUS` + `require_salon_scope`) et `PUT /salons/{salon_id}/
   appointments/{id}/hairdresser` (`APPOINTMENT_MANAGE` + `require_salon_scope`) ; schémas
   `SetStatusRequest` (`status: AppointmentStatus`, `reason?`) / `AssignHairdresserRequest`
   (`hairdresser_id: uuid|None`) `extra="ignore"` ; traductions d'erreurs → codes HTTP. **Ne rien
   ajouter à `PUBLIC_ROUTE_PATHS`.**
8. **Fakes de test** : étendre `FakeAppointmentRepository` (`get_in_salon`, `set_status`,
   `assign_hairdresser` ; modes `raise_invalid_transition`/`raise_conflict` ; mémorisation
   `(from,to)`/`hairdresser_id`) et réutiliser `FakeAuditLog`/`FakeSalonScopeRepository` dans
   `conftest.py`.
9. **Tests backend** : machine à états (domaine), cas d'usage (fakes), API (`TestClient`,
   anti-élévation + deny-by-default + `403` hors salon + `404` indiscernable), Postgres e2e
   (transitions, verrou terminal, garde TOCTOU, assignation + conflit d'exclusion, **créneau libéré**,
   audit) — **skip** sans `DATABASE_URL`.
10. **Documentation** : ADR-0026 + `docs/adr/README.md` + section `backend/README.md`.
11. **Garde-fous** : `pytest` (et test gate agrégé) au vert ; aucun secret/PII journalisé ; corps sans
    `salon_id`/`client_id` ; `status` doublement contraint (enum + machine à états) ; UPDATE
    conditionnel (garde TOCTOU) ; exclusion base **jamais** contournée (l'assignation la respecte) ;
    `unprotected_routes(app)` **vide** ; **aucune** notification ni calcul de CA fabriqués ; **aucune**
    signature IA dans le code/commits/PR.
```
