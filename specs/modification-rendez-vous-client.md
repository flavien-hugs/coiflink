# Modification d'un rendez-vous côté client (US-3.2)

> Spécification de planification pour l'issue GitHub **#23 — US-3.2 : Modification d'un rendez-vous
> (client)** (`feature` · Must · Effort S · PRD §6 Épic 3, §7.1, §8.1, §11.4). **Dépend de #22**
> (réservation d'un rendez-vous côté client). **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires Dart/Python),
> en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants techniques (noms de
> routes, champs JSON, symboles, enums SQL) inchangés. **Aucune signature IA** dans le code, les
> commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 3, US-3.2) pose le besoin : **« en tant que client, je veux modifier mon rendez-vous
si j'ai un empêchement »**, avec pour règle métier (§8.1) : *« un rendez-vous terminé ne peut plus être
modifié, sauf par le gérant »*. Les critères d'acceptation de l'issue #23 sont : *modification d'un RDV
non terminé ; RDV terminé **verrouillé côté client***. La modification est de plus une **action
importante** que le §11.4 impose de **journaliser** (« Modification rendez-vous »).

État actuel du dépôt :

- **Le socle base et le chemin d'écriture de réservation existent** (issues #3 puis #21). La table
  `appointments` porte déjà toutes les colonnes nécessaires à une modification : `appointment_date`,
  `start_time`, `end_time`, `status`, `client_note`, `cancellation_reason`, la colonne **générée**
  `slot tsrange` (recalculée automatiquement à chaque changement de date/heure) et `updated_at`
  (**rafraîchie automatiquement** à chaque flush ORM, centralisée par #20). La contrainte d'exclusion
  anti double-réservation `ex_appointments_hairdresser_slot` (`WHERE hairdresser_id IS NOT NULL AND
  status IN ('PENDING','CONFIRMED')`) protège aussi les **mises à jour** : déplacer un RDV actif vers
  un créneau déjà occupé par **un autre** RDV actif du même coiffeur échoue au niveau base.
- **Le chemin applicatif de réservation existe** (#21) : `CheckAvailability`, `BookAppointment`
  (`application/appointments.py`), le port `AppointmentRepository` (`booked_slots`, `create`), l'adapter
  SQL `SqlAppointmentRepository`, et le router `POST /salons/{salon_id}/appointments`.
- **Aucun chemin de modification n'existe** : il n'y a ni cas d'usage `ModifyAppointment`, ni méthode
  `update`/lecture d'un RDV par le client dans le port, ni route `PATCH`/`PUT` de modification. Il
  n'existe pas non plus de **lecture « mes rendez-vous »** côté client (aucune route ne consomme la
  permission `APPOINTMENT_READ_OWN`, pourtant déjà détenue par le rôle `CLIENT` dans la matrice
  §4.1) : le seul RDV qu'un client « connaît » aujourd'hui est celui renvoyé par la réponse du `POST`.
- **Côté mobile (#22)** : le paquet Flutter dispose du domaine rendez-vous (`Appointment`,
  `AppointmentStatus` — dont `completed → « Terminé »`), du port `AppointmentGateway`
  (`availableSlots`, `book`), de l'adapter `HttpAppointmentGateway`, d'une session cliente minimale
  (`AuthSession` + `TokenStore` en mémoire) et du **tunnel de réservation** (`booking_flow_screen`,
  `booking_confirmation_screen`, `booking_labels`). Il n'existe **ni écran « Mes rendez-vous », ni flux
  de modification, ni verrouillage d'un RDV terminé**.

Le gap que #23 comble : **(1)** un **chemin de modification serveur** pour le RDV du client authentifié
— re-planification (prestation, date, créneau, commentaire) d'un RDV **non terminé**, **verrou** d'un
RDV terminé (`COMPLETED`, et par extension les états terminaux), ré-application du moteur de
disponibilité et de la garantie anti double-réservation, et **journalisation §11.4** ; **(2)** côté
mobile, un **point d'entrée « Mes rendez-vous »** minimal permettant au client de retrouver son RDV et
de le modifier, avec l'affordance de modification **désactivée** quand le RDV est terminé.

## Goals

- **Modifier un RDV non terminé (client)** : un client authentifié modifie **son** rendez-vous
  (`client_id == principal.id`) tant qu'il est dans un état modifiable — re-planification (nouvelle
  date/créneau), changement de prestation(s) et de commentaire — en réutilisant le moteur de
  disponibilité (#21) et la garantie anti double-réservation portée par la base.
- **Verrouiller un RDV terminé côté client** : un RDV `COMPLETED` (et, par extension recommandée, tout
  état terminal : `CANCELLED`, `NO_SHOW`) **n'est plus modifiable par le client** — la route renvoie un
  refus **neutre** (§8.1 « ne peut plus être modifié, sauf par le gérant » ; l'exception « gérant »
  relève d'une issue de gestion, hors périmètre, voir *Non-Goals*).
- **Journaliser la modification (§11.4)** : chaque modification écrit une entrée d'audit
  `APPOINTMENT_UPDATED` **neutre** (acteur = `client_id`, portée = `salon_id` du RDV, `metadata.changed`
  = **noms de champs** modifiés uniquement — jamais de valeur), dans la **même unité de travail** que
  l'écriture métier (patron #17/#20).
- **Préserver l'anti double-réservation et §8.3** : une modification vers un créneau déjà pris (autre
  RDV actif du même coiffeur) est rejetée (`SlotAlreadyBooked` → `409`) ; un salon devenu non réservable
  (§8.3) ou un créneau hors offre est refusé. La garantie reste portée par la **contrainte d'exclusion
  base**, jamais par un verrou applicatif.
- **Préserver l'anti-élévation & la confidentialité (§11.2/§11.3)** : le corps ne porte **jamais**
  `client_id`/`salon_id`/`status` ; le client ne peut modifier que **ses** RDV (un RDV d'autrui est
  **indiscernable** d'un identifiant inexistant → `404` générique, aucun oracle) ; aucune identité d'un
  tiers n'est exposée.
- **Point d'entrée mobile « Mes rendez-vous » minimal** : le client retrouve ses RDV (à venir),
  déclenche la modification via le tunnel réutilisé et voit l'affordance **désactivée** pour un RDV
  terminé (libellé « Terminé » déjà disponible côté domaine mobile).
- **Couverture de tests** : règles de domaine (état modifiable), cas d'usage (ownership, verrou,
  ré-planification, exclusion de soi du calcul de disponibilité), intégration/HTTP, et — côté mobile —
  passerelle + widget du flux de modification et du verrou.

## Non-Goals

- **Exception « modification par le gérant » d'un RDV terminé** (§8.1 « sauf par le gérant ») : la
  capacité **gérant** de modifier/faire évoluer un RDV (y compris terminé) et le **cycle de statuts**
  (confirmer/refuser/terminer/absent) relèvent de **US-3.4 (#25)**. #23 se limite au **chemin client**
  et n'implémente **que le verrou côté client**. Aucun droit gérant nouveau n'est ajouté ici.
- **Annulation d'un RDV** (US-3.3 #24) : distincte de la modification (transition vers `CANCELLED` +
  `cancellation_reason` + non-comptabilisation au CA). #23 ne touche pas au statut d'annulation.
- **Historique complet « Mes rendez-vous »** (RDV terminés + prestations + montants, US-4.4 #30 —
  dépend de #25) : #23 ne livre qu'une **lecture minimale** des RDV du client suffisante pour atteindre
  le flux de modification (voir *Open Questions* sur le périmètre exact de cette lecture).
- **Notification de modification** (§7.4 US-7.4 « être notifié en cas de modification », Épic 7) :
  aucun envoi n'est ajouté ; l'audit §11.4 est une **trace interne**, pas une notification client. Le
  câblage notifications viendra avec l'Épic 7 (#43+).
- **Nouvelle table, migration, colonne ou contrainte** : le schéma `appointments` /
  `appointment_services` / `slot` / `EXCLUDE` existe depuis #3 et suffit. #23 n'ajoute **aucun** DDL.
- **Sélection/réassignation d'un coiffeur par le client** : cohérent avec #22, le MVP travaille au
  **niveau salon** (`hairdresser_id` nul). La réassignation d'un coiffeur relève du gérant (#25).
- **Interface web (Next.js)** : US-3.2 est un parcours **client** (mobile). Le `web-dashboard/` n'est
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

### Backend rendez-vous déjà livré (#21 — à réutiliser/étendre)

- `coiflink_api/domain/appointment.py` — `Appointment`, `AppointmentToCreate`, `BookedService`,
  `require_services`, `validate_booking_window`, `compute_end_time`.
- `coiflink_api/domain/availability.py` — `SlotRange`, `free_slots`, `is_offered`, `overlaps`,
  `add_minutes`, `DEFAULT_GRANULARITY_MINUTES` (moteur pur, fuseau Africa/Abidjan UTC+0).
- `coiflink_api/domain/enums.py` — `AppointmentStatus` = `PENDING | CONFIRMED | CANCELLED | COMPLETED |
  NO_SHOW`. Les états « actifs » (occupant un créneau) sont `PENDING`/`CONFIRMED`.
- `coiflink_api/application/appointments.py` — `BookingCommand`, `CheckAvailability`,
  `BookAppointment` (helpers `_load_bookable_salon`, `_active_service`, `_require_salon_hairdresser`,
  imposition serveur de `salon_id`/`client_id`, défense en profondeur `is_offered`).
- `coiflink_api/application/ports/appointment_repository.py` — `AppointmentRepository`
  (`booked_slots`, `create`).
- `coiflink_api/adapters/outbound/persistence/appointment_repository.py` — `SqlAppointmentRepository`
  (traduction de l'`IntegrityError` SQLSTATE `23P01` / contrainte `ex_appointments_hairdresser_slot`
  → `SlotAlreadyBooked`, **sans journaliser l'erreur brute** ; `_to_domain`).
- `coiflink_api/adapters/inbound/appointments.py` — router `GET .../availability` (public) + `POST
  /salons/{salon_id}/appointments` (client `APPOINTMENT_BOOK`) ; schémas Pydantic `extra="ignore"` ;
  DI surchargeable (`get_appointment_repository`, `get_catalog_repository`) ; `_now()` UTC+0.
- `coiflink_api/domain/errors.py` — `SlotAlreadyBooked`, `SlotUnavailable`, `SalonNotBookable`,
  `HairdresserNotInSalon`, `AppointmentServiceRequired`, `ServiceNotFound`, `SalonNotFound` (toutes
  **neutres**).

### Modèle de données pertinent (schéma #3, `models.py`)

- `Appointment` : `id`, `salon_id`, `client_id`, `hairdresser_id NULL`, `appointment_date`,
  `start_time`, `end_time`, `status` (défaut `PENDING`), `cancellation_reason NULL`, `client_note
  NULL`, `slot tsrange` **`Computed(persisted=True)`**, `created_at`, `updated_at`
  (`onupdate=func.now()`), `CHECK end_time > start_time`, `UniqueConstraint(salon_id, id)`, exclusion
  `ex_appointments_hairdresser_slot`, index `ix_appointments_client_id` (utile à la lecture « mes
  RDV ») et `ix_appointments_salon_id (salon_id, appointment_date)`.
- `AppointmentService` : PK `(appointment_id, service_id)`, `salon_id`, `price_at_booking`, FK
  composites `(salon_id, appointment_id)` **CASCADE** et `(salon_id, service_id)` **RESTRICT**.

### RBAC & portée (ADR-0015, #12)

- `domain/permissions.py` : le rôle **`CLIENT`** détient `SALON_READ_ANY`, `SERVICE_READ`,
  **`APPOINTMENT_BOOK`** et **`APPOINTMENT_READ_OWN`**. Le commentaire de la matrice décrit
  explicitement le client comme *« réserve/**modifie**/annule ses rendez-vous, consulte son
  historique »* — la **modification client est donc couverte par `APPOINTMENT_BOOK`** (aucune
  permission `APPOINTMENT_MODIFY_*` distincte n'existe ; voir *Open Questions*).
- `adapters/inbound/security.py` : gardes `require_permission`, `require_any_permission`,
  `require_salon_scope` (marquées `_mark_principal_guard`, donc satisfont l'invariant deny-by-default).
  **Point clé** : un `CLIENT` **n'a aucune portée salon** (`require_salon_scope` lui renvoie `403`) —
  une route client d'appartenance **ne doit pas** utiliser `require_salon_scope` ; l'appartenance du RDV
  au client est validée **dans le cas d'usage** (`client_id == principal.id`), comme la réservation #21.
  Une route protégée (non listée dans `PUBLIC_ROUTE_PATHS`) est fermée par défaut.

### Journalisation d'audit §11.4 (#17/#20 — patron à réutiliser)

- `domain/audit.py` : `AuditAction` (fermé — `SERVICE_*`, `SALON_UPDATED`), `AuditEntry`
  (`action`, `actor_user_id`, `entity_type`, `entity_id`, `salon_id?`, `metadata`), `ENTITY_TYPE_*`.
- `application/ports/audit_log.py` : `AuditLog.record(entry)` — **même session** que la mutation
  (atomicité). `adapters/outbound/persistence/audit_log_repository.py` : `SqlAuditLog`.
- Patron d'usage (#20, `application/salons.py::UpdateSalon`) : diff **neutre** `_changed_fields`
  (noms de champs seulement) → `repository.update(...)` → `audit_log.record(AuditEntry(...,
  metadata={"changed": [...]}))`. DI `get_audit_log(session)` déjà exposée
  (`adapters/inbound/salons.py`) et à répliquer dans le router rendez-vous.

### Mobile déjà livré (#18/#19/#22 — patrons à calquer)

- `lib/domain/appointment/{appointment,appointment_status,availability_slot}.dart` — value objects +
  `AppointmentStatus.fromApi` / `.label` (dont `completed → « Terminé »`, `cancelled → « Annulé »`,
  `noShow → « Absent »`, valeur inconnue tolérée).
- `lib/application/ports/appointment_gateway.dart` — `AppointmentGateway` (`availableSlots`, `book`),
  `BookingDraft`, exceptions **neutres** (`AppointmentGatewayException`, `SlotTakenException`,
  `NotBookableException`, `UnauthorizedException`).
- `lib/application/auth_session.dart` + `lib/application/ports/token_store.dart` — session cliente
  (jeton **jamais journalisé**, `InMemoryTokenStore` au MVP).
- `lib/adapters/data/http_appointment_gateway.dart` — mapping JSON ↔ domaine, en-tête
  `Authorization: Bearer`, codes `201/401/409/404`, **aucune journalisation** d'URL/jeton/PII.
- `lib/adapters/ui/booking/{booking_flow_screen,booking_confirmation_screen,booking_labels}.dart` — le
  tunnel guidé (prestation → date → créneau → note → confirmation) à **réutiliser** pour la
  ré-planification.
- `lib/adapters/ui/{app,salon_detail_screen}.dart`, `lib/main.dart` — composition (gateways, session,
  routes).

## Proposed Implementation

Périmètre recommandé : **étendre** le chemin rendez-vous #21 par une **capacité de modification client**
au-dessus du **schéma inchangé**, puis livrer côté mobile un **point d'entrée « Mes rendez-vous »
minimal** et le **flux de modification** réutilisant le tunnel #22. La garantie anti double-réservation
reste portée par la base (l'exclusion s'applique aussi aux `UPDATE`).

### Backend

#### 1. Domaine (`domain/appointment.py`, `domain/errors.py`)

- **Règle d'état modifiable (pure)** dans `domain/appointment.py` :
  - Constante `CLIENT_MODIFIABLE_STATUSES = (AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value)` et fonction `is_client_modifiable(status: str) -> bool`.
  - Justification : le PRD §8.1 verrouille explicitement le RDV **terminé** (`COMPLETED`) côté client ;
    un RDV **annulé** (`CANCELLED`) ou **absent** (`NO_SHOW`) est également terminal et n'a pas de sens à
    modifier. *Recommandation : n'autoriser la modification que sur `PENDING`/`CONFIRMED`* et documenter
    ce choix dans l'ADR (voir *Open Questions* pour `CANCELLED`/`NO_SHOW`).
- **Nouvelles erreurs neutres** dans `domain/errors.py` (mettre à jour `__all__`) :
  - `AppointmentNotFound(DomainError)` : le RDV n'existe pas **ou** n'appartient pas au client
    demandeur — **indiscernables** (aucun oracle, §11.2). → `404`.
  - `AppointmentNotModifiable(DomainError)` : le RDV est dans un état non modifiable par le client
    (terminé/terminal). Message neutre (« Ce rendez-vous n'est plus modifiable. »). → **`409 Conflict`**
    *(état de la ressource, cohérent avec `SlotAlreadyBooked` ; voir Open Questions pour 403/423)*.

#### 2. Application (`application/appointments.py`)

- **Commande** `@dataclass(frozen=True) ModifyAppointmentCommand` : mêmes champs saisissables qu'une
  réservation — `date`, `start_time`, `service_ids: tuple[UUID, ...]` (**≥ 1**), `hairdresser_id | None`,
  `client_note | None`, `granularity_minutes = DEFAULT_GRANULARITY_MINUTES`. **Jamais**
  `salon_id`/`client_id`/`status`. Sémantique **replace** des champs modifiables (ré-planification
  complète, comme le corps de réservation).
- **Cas d'usage** `class ModifyAppointment` (constructeur : `catalog_repository`,
  `appointment_repository`, `scope_repository`, `audit_log`) ; `execute(appointment_id, client_id,
  command, *, now=None) -> Appointment` :
  1. **Charger le RDV du client** : `current = appointment_repository.get_owned(appointment_id,
     client_id)` ; `None` → `AppointmentNotFound` (couvre RDV inexistant **et** RDV d'autrui — la
     requête filtre `client_id`, donc aucun oracle).
  2. **Verrou d'état** : `if not is_client_modifiable(current.status): raise
     AppointmentNotModifiable(...)`.
  3. **Re-valider la cible** (miroir `BookAppointment`) : `_load_bookable_salon(catalog,
     current.salon_id)` (§8.3) ; `_require_salon_hairdresser(...)` si `command.hairdresser_id` fourni ;
     charger les prestations actives du salon → `BookedService` (durée pour la fenêtre, **prix figé
     recapturé** au tarif courant), `require_services(...)`, `compute_end_time`, `validate_booking_window`.
     Le `salon_id` provient **du RDV chargé** (jamais du corps).
  4. **Défense en profondeur `is_offered` en excluant le RDV lui-même** : lire les créneaux occupés via
     `appointment_repository.booked_slots(current.salon_id, command.hairdresser_id, command.date,
     exclude_appointment_id=appointment_id)` — **sans cette exclusion**, le propre créneau actuel du RDV
     (même date/coiffeur) apparaîtrait comme « occupé » et un déplacement légitime (y compris un
     simple changement de note à date/heure inchangées) serait **faussement rejeté**. Puis `is_offered(
     hours, SlotRange(date, start, end), total_minutes, booked, granularity_minutes=..., now=now)`
     sinon `SlotUnavailable`.
  5. **Écriture transactionnelle** : `appointment_repository.update(appointment_id, changes)` — met à
     jour `appointment_date`/`start_time`/`end_time`/`hairdresser_id`/`client_note` **et remplace** les
     lignes `appointment_services` (durée/prix recapturés) dans **une** unité de travail. La colonne
     générée `slot` se recalcule ; l'exclusion base arbitre toute course/collision (→ `SlotAlreadyBooked`).
  6. **Audit §11.4** : `audit_log.record(AuditEntry(action=AuditAction.APPOINTMENT_UPDATED.value,
     actor_user_id=client_id, salon_id=current.salon_id, entity_type=ENTITY_TYPE_APPOINTMENT,
     entity_id=appointment_id, metadata={"changed": [...noms de champs...]}))` — **noms de champs
     uniquement** (diff neutre calculé entre `current` et la cible : `date`, `start_time`,
     `hairdresser_id`, `client_note`, `services`), **jamais** de valeur (dates/heures comprises, par
     cohérence avec le patron #20).
- **Garantie transactionnelle contre une course de statut (TOCTOU load→update)** : entre l'étape 1 et
  l'étape 5, un changement de statut concurrent (p. ex. un gérant qui « termine » le RDV — capacité
  #25, non encore livrée) pourrait invalider le verrou. *Recommandation :* l'`update` du dépôt applique
  un **UPDATE conditionnel** (`WHERE id = … AND status IN ('PENDING','CONFIRMED')`) et lève
  `AppointmentNotModifiable` si `rowcount == 0` — le verrou est ainsi ré-affirmé **au moment de
  l'écriture**. À défaut (aucun endpoint de changement de statut n'existe encore), le risque est faible
  au MVP mais le garde-fou est peu coûteux (voir *Open Questions*).

#### 3. Port & adapter (persistance)

- **Port** `application/ports/appointment_repository.py` — ajouter :
  - `get_owned(appointment_id: UUID, client_id: UUID) -> Appointment | None` : charge le RDV **et** ses
    `BookedService` **si et seulement si** `client_id` correspond (isolation §11.2 en SQL).
  - `booked_slots(..., exclude_appointment_id: UUID | None = None)` : paramètre **optionnel additif**
    (rétro-compatible avec les appels #21) excluant un RDV du calcul (`AND id <> :exclude`).
  - `update(appointment_id: UUID, changes: AppointmentUpdate) -> Appointment` : met à jour la ligne +
    remplace les jonctions dans une transaction ; **doit** lever `SlotAlreadyBooked` sur violation
    d'exclusion (course/collision) et `AppointmentNotModifiable` si l'UPDATE conditionnel n'affecte
    aucune ligne (voir §2.6). Introduire un petit VO `AppointmentUpdate` (dataclass gelée : `date`,
    `start_time`, `end_time`, `hairdresser_id`, `client_note`, `services: tuple[BookedService, ...]`)
    dans `domain/appointment.py`.
- **Adapter** `adapters/outbound/persistence/appointment_repository.py` — `SqlAppointmentRepository` :
  - `get_owned(...)` : `SELECT` sur `Appointment` filtré `id == appointment_id AND client_id ==
    client_id`, joint/relit ses `AppointmentService` → `_to_domain(row, services)`.
  - `booked_slots(...)` : ajouter la clause `id != exclude_appointment_id` quand fourni.
  - `update(...)` : recharger la ligne (ou `UPDATE … WHERE id AND status IN (actifs)`), affecter les
    champs, **supprimer** les `AppointmentService` existants du RDV puis **ré-insérer** ceux de
    `changes.services`, `flush()`. Réutiliser `_is_exclusion_violation` (SQLSTATE `23P01` /
    `ex_appointments_hairdresser_slot`) → `rollback` + `SlotAlreadyBooked` (message **neutre**, l'erreur
    brute **jamais journalisée**). Toute autre `IntegrityError` **relevée telle quelle**.
  - **Aucune** modification de schéma : la colonne générée `slot` et `updated_at` (`onupdate`) se
    mettent à jour automatiquement au flush.

#### 4. Adapter entrant (HTTP)

- **Router** `adapters/inbound/appointments.py` — ajouter :
  - `PATCH /appointments/{appointment_id}` (**client**, `require_permission(APPOINTMENT_BOOK)`, **pas**
    de `require_salon_scope` — appartenance validée dans le cas d'usage). Corps
    `ModifyAppointmentRequest` (Pydantic `extra="ignore"`) : `date`, `start_time`, `service_ids
    (min_length=1)`, `hairdresser_id?`, `client_note?` — **jamais** `salon_id`/`client_id`/`status`. Le
    `salon_id` n'est **pas** dans le chemin : il vient du RDV chargé (route d'**appartenance** client,
    pas de portée salon). DI : réutiliser `get_appointment_repository`, `get_catalog_repository`,
    `get_salon_scope_repository`, et ajouter `get_audit_log` (mêmes patrons que `salons.py`).
    Traductions : `AppointmentNotFound` → **404** ; `AppointmentNotModifiable` → **409** ;
    `SlotAlreadyBooked`/`SlotUnavailable`/`SalonNotBookable` → **409** ;
    `AppointmentServiceRequired` → **422** ; `ServiceNotFound`/`SalonNotFound`/`HairdresserNotInSalon`
    → **404**. Réponse `200` `AppointmentResponse` (schéma existant, réutilisé).
  - **Lecture « mes rendez-vous » (recommandée, prérequis du flux mobile)** :
    `GET /appointments` (**client**, `require_permission(APPOINTMENT_READ_OWN)`) → liste **des RDV du
    client** (`client_id == principal.id`), filtrable au minimum sur les états **à venir/actifs**
    (`PENDING`/`CONFIRMED`) pour alimenter la modification. Projeter `AppointmentResponse` (les données
    du **seul** client — jamais d'identité tierce, §11.3). *Voir Open Questions sur le périmètre exact
    (liste seule vs `GET /appointments/{id}`, filtre par statut).* Ajouter la méthode de lecture
    correspondante au port/adapter (`list_for_client(client_id, statuses?)`).
- **Composition root** `coiflink_api/main.py` : le router rendez-vous est **déjà monté** ; les nouvelles
  routes en héritent. **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`** : la modification et la lecture « mes
  RDV » sont **protégées** (jamais publiques). Vérifier que l'invariant `unprotected_routes(app)` reste
  vide (test existant).

### Mobile (Flutter)

Réutilisation maximale du tunnel #22 ; découpage hexagonal respecté.

1. **Domaine** — `Appointment`/`AppointmentStatus` existants suffisent (statuts + libellés déjà
   présents, dont « Terminé »). Ajouter un prédicat d'affichage `bool get isClientModifiable =>
   status == AppointmentStatus.pending || status == AppointmentStatus.confirmed` (miroir mobile de la
   règle serveur — **aide UX** ; le serveur reste juge).
2. **Port** `application/ports/appointment_gateway.dart` — ajouter :
   - `Future<Appointment> modify({required String appointmentId, required BookingDraft draft, required
     String accessToken});`
   - *(si lecture livrée)* `Future<List<Appointment>> myAppointments({required String accessToken});`.
   - Nouvelles exceptions **neutres** : `NotModifiableException extends AppointmentGatewayException`
     (`409` verrou terminé — rien à re-choisir) et `AppointmentNotFoundException` (`404`).
     `UnauthorizedException` (`401`) et `SlotTakenException` (`409`) existants réutilisés.
3. **Use cases** `application/use_cases/modify_appointment.dart` (+ `list_my_appointments.dart` si
   lecture) : validations amont légères (≥ 1 prestation, date non passée, **RDV modifiable** — refuser
   en amont si non modifiable), délégation au port.
4. **Adapter data** `adapters/data/http_appointment_gateway.dart` — ajouter `modify(...)` →
   `PATCH /appointments/{appointmentId}` (en-tête `Authorization: Bearer`, corps sans
   `client_id`/`salon_id`/`status`) et `myAppointments(...)` → `GET /appointments` ; mapping des codes
   (`200`/`401`/`404`/`409` → exceptions ci-dessus, `409` distingué verrou vs créneau pris selon le
   contexte de l'appel), **aucune journalisation** d'URL/jeton/PII.
5. **UI** — `adapters/ui/appointments/my_appointments_screen.dart` : liste des RDV du client (statut +
   libellé, date/heure) ; bouton **« Modifier »** par RDV, **désactivé** quand `!appointment
   .isClientModifiable` (RDV terminé/terminal), avec une mention explicite (« Rendez-vous terminé »).
   Le bouton ouvre le **tunnel #22 pré-rempli** (prestation/date/créneau/note du RDV) en mode
   *modification* (confirmation appelant `modify(...)` au lieu de `book(...)`). Gérer `409` verrou
   (message + rafraîchir), `409` créneau pris (retour au choix de créneau), `401` (→ Connexion).
   Câbler l'entrée « Mes rendez-vous » dans `app.dart`/`main.dart` (et éventuellement un lien depuis la
   confirmation de réservation #22).

### Documentation & ADR

- **ADR-0025 — Modification d'un rendez-vous côté client** actant : verrou d'état côté client
  (`PENDING`/`CONFIRMED` modifiables ; `COMPLETED`/terminaux verrouillés ; exception gérant → #25),
  route d'**appartenance** `PATCH /appointments/{id}` (pas de portée salon), réutilisation du moteur
  #21 et de l'exclusion base pour les `UPDATE`, exclusion du RDV lui-même du calcul de disponibilité,
  journalisation `APPOINTMENT_UPDATED` (§11.4), périmètre mobile (« Mes rendez-vous » minimal), codes
  HTTP retenus, et backend **sans nouveau schéma**. Indexer dans `docs/adr/README.md`.
- **`backend/README.md`** : section « Modification d'un rendez-vous (client) ».
- **`app-mobile/README.md`** : section « Mes rendez-vous & modification ».

## Affected Files / Packages / Modules

**Backend — à modifier :**
- `backend/coiflink_api/domain/appointment.py` — `is_client_modifiable`, `CLIENT_MODIFIABLE_STATUSES`,
  VO `AppointmentUpdate`.
- `backend/coiflink_api/domain/errors.py` — `AppointmentNotFound`, `AppointmentNotModifiable` (+ `__all__`).
- `backend/coiflink_api/domain/audit.py` — `AuditAction.APPOINTMENT_UPDATED`, `ENTITY_TYPE_APPOINTMENT`.
- `backend/coiflink_api/application/appointments.py` — `ModifyAppointmentCommand`, `ModifyAppointment`.
- `backend/coiflink_api/application/ports/appointment_repository.py` — `get_owned`,
  `update`, `list_for_client` (si lecture), `booked_slots(exclude_appointment_id=…)`.
- `backend/coiflink_api/adapters/outbound/persistence/appointment_repository.py` — implémentations.
- `backend/coiflink_api/adapters/inbound/appointments.py` — `PATCH /appointments/{id}`,
  `GET /appointments`, schémas, DI `get_audit_log`, traductions d'erreurs.
- `backend/tests/conftest.py` — étendre `FakeAppointmentRepository` (RDV en mémoire : `get_owned`,
  `update` avec mode `raise_conflict`/`not_modifiable`, `list_for_client`, `booked_slots` exclusif) et
  réutiliser le `FakeAuditLog` (patron #17/#20).

**Backend — à lire (contexte) :** `application/salons.py::UpdateSalon` (patron update+audit),
`adapters/inbound/salons.py` (DI `get_audit_log`, route `PUT`), `adapters/inbound/security.py`
(gardes, deny-by-default), `application/appointments.py` (helpers réutilisés), `models.py`
(Appointment/AppointmentService/EXCLUDE/`updated_at`), `tests/test_appointment_*` + `tests/test_service_e2e.py`
(patron e2e Postgres + skip).

**Mobile — à créer :**
- `app-mobile/lib/application/use_cases/modify_appointment.dart` (+ `list_my_appointments.dart`).
- `app-mobile/lib/adapters/ui/appointments/my_appointments_screen.dart` (+ widgets éventuels).
- Tests (voir *Testing Plan*).

**Mobile — à modifier :**
- `app-mobile/lib/application/ports/appointment_gateway.dart` — `modify`/`myAppointments` + exceptions.
- `app-mobile/lib/adapters/data/http_appointment_gateway.dart` — `PATCH`/`GET`.
- `app-mobile/lib/domain/appointment/appointment.dart` — `isClientModifiable`.
- `app-mobile/lib/adapters/ui/booking/booking_flow_screen.dart` — mode « modification » (pré-remplissage
  + confirmation via `modify`), `booking_labels.dart` (libellés de modification).
- `app-mobile/lib/adapters/ui/app.dart`, `lib/main.dart` — route/navigation « Mes rendez-vous ».
- `app-mobile/README.md`.

**Docs :** `docs/adr/0025-modification-rendez-vous-client.md` (+ `docs/adr/README.md`),
`backend/README.md`. **`prd-coiflink.md` : ne pas modifier** (source de vérité produit). Récit
`README.md` §6 (« M3 en cours ») : à compléter au step `document` **une fois livré**.

## API / Interface Changes

**Nouvelles routes backend** (protégées, jamais publiques) :

- `PATCH /appointments/{appointment_id}` — **client** (`APPOINTMENT_BOOK`, appartenance vérifiée
  serveur). Corps `{date, start_time, service_ids:[≥1], hairdresser_id?, client_note?}` (**sans**
  `client_id`/`salon_id`/`status`, `extra="ignore"`). Réponses : `200` `AppointmentResponse` ; `401`
  jeton absent/expiré ; `403` rôle insuffisant ; `404` RDV inexistant/hors appartenance ou
  prestation/salon introuvable ; `409` RDV non modifiable (terminé) / créneau déjà pris / salon non
  réservable ; `422` sans prestation ou paramètres invalides. Documentation OpenAPI (docstrings +
  `responses`).
- `GET /appointments` *(recommandé — prérequis du flux mobile)* — **client**
  (`APPOINTMENT_READ_OWN`) → `200` liste des RDV **du client** (états à venir/actifs par défaut). Ne
  renvoie **que** les données du client (§11.2/§11.3). *Surface exacte à confirmer (Open Questions).*

**Interfaces internes mobiles nouvelles** (paquet-privées) : `AppointmentGateway.modify` (+
`myAppointments`), use cases `ModifyAppointment`/`ListMyAppointments`, exceptions
`NotModifiableException`/`AppointmentNotFoundException`. Documentées par docstrings Dart.

**Aucune modification** des routes `GET .../availability` et `POST /salons/{id}/appointments`
existantes. `AppointmentResponse` est **réutilisé tel quel** (contrat JSON inchangé).

## Data Model / Protocol Changes

**Aucune.** Les tables `appointments` / `appointment_services`, la colonne générée `slot tsrange`,
`updated_at` (`onupdate`), `cancellation_reason`, `client_note`, l'extension `btree_gist` et la
contrainte d'exclusion `ex_appointments_hairdresser_slot` **existent depuis #3**. La modification
n'introduit **ni table, ni migration, ni colonne, ni contrainte** : elle écrit et relit via ce schéma.
La contrainte d'exclusion s'applique **aussi aux `UPDATE`** (PostgreSQL vérifie l'exclusion sur INSERT
et UPDATE, en comparant la ligne mise à jour aux **autres** lignes actives), ce qui étend
mécaniquement la garantie anti double-réservation à la re-planification, sans DDL. Le contrat de fil
(`AppointmentResponse`) est inchangé ; le mobile n'ajoute que de la désérialisation côté client.

## Security & Privacy Considerations

- **Isolation par salon / anti-élévation (§11.2)** : la modification est **scopée par appartenance**
  (`client_id == principal.id`), imposée **serveur** — le corps ne porte jamais `client_id`, `salon_id`
  ni `status`. Le `salon_id` provient du RDV chargé, jamais du chemin/corps. Un RDV d'autrui (ou
  inexistant) donne un **`404` générique indiscernable** (aucun oracle d'existence). Un
  `hairdresser_id` soumis est revalidé contre `salon_members` (`_require_salon_hairdresser`, §11.2).
- **Anti double-réservation = intégrité base (§8.1)** : préservée pour les `UPDATE` par la contrainte
  d'exclusion ; **jamais** contournée ni désactivée. La vérification applicative `is_offered` (avec
  **exclusion du RDV lui-même**) reste une **aide UX** (défense en profondeur), la base tranchant les
  courses (`SlotAlreadyBooked` → `409`). Rappel : pour un RDV **sans coiffeur** (`hairdresser_id` nul,
  MVP salon-level), l'exclusion base ne s'applique pas (clause `WHERE hairdresser_id IS NOT NULL`) —
  comportement identique à la réservation #22 (documenté ADR-0023/0024).
- **§8.3 respecté** : aucune modification vers un salon devenu non `ACTIVE` ou sans horaire
  (`SalonNotBookable` → `409`).
- **Verrou d'état (§8.1)** : un RDV terminé (`COMPLETED`, et terminaux) est **verrouillé côté client**
  au niveau du cas d'usage **et** (recommandé) ré-affirmé par un UPDATE conditionnel — l'UI mobile
  n'est qu'un confort ; le serveur est juge.
- **Journalisation §11.3/§11.4 sans fuite** : l'entrée d'audit `APPOINTMENT_UPDATED` est **neutre** —
  `actor_user_id` UUID **opaque**, `metadata.changed` = **noms de champs** uniquement (jamais de valeur,
  y compris dates/heures/note, par cohérence avec le diff neutre #20). L'`IntegrityError` psycopg brute
  **n'est jamais journalisée** (peut porter des identifiants) : on inspecte SQLSTATE/nom de contrainte
  puis on lève une erreur de domaine neutre. **Aucun secret ni jeton** manipulé/journalisé.
- **Messages neutres** : `AppointmentNotFound`/`AppointmentNotModifiable`/`SlotAlreadyBooked`/… portent
  des messages génériques ; les refus RBAC restent les `401`/`403` **constants** de `security.py`
  (jamais `str(exc)`, jamais l'identifiant visé). Côté mobile, les exceptions ne portent **ni** URL, **ni**
  jeton, **ni** corps, **ni** PII.
- **Confidentialité (§11.3)** : `GET /appointments` ne renvoie **que** les RDV du client demandeur.
- **Budgets §12** : lecture et modification restent bien en deçà du budget API (< 3 s) ; les index
  `ix_appointments_client_id` et `ix_appointments_salon_id (salon_id, appointment_date)` soutiennent la
  lecture « mes RDV » et le calcul de disponibilité.
- **Résidence/hébergement** : inchangés (ADR-0011) ; aucune donnée nouvelle exfiltrée ; le jeton mobile
  reste dans le `TokenStore` (en mémoire au MVP, #22) et **jamais journalisé** (§11.1).

## Testing Plan

Test gate : `pytest` (backend) et `flutter test` (mobile). Convention du dépôt : tests **Postgres**
*skip proprement* sans `DATABASE_URL` (patron `test_service_e2e.py` / `test_appointment_*`) ; côté
mobile, fakes injectés, **aucun** appel réseau réel. Les tests existants doivent rester **verts** et
ne pas être modifiés.

- **Unit — règle de domaine** `tests/test_domain_appointment.py` (étendre) : `is_client_modifiable`
  → `True` pour `PENDING`/`CONFIRMED`, `False` pour `COMPLETED`/`CANCELLED`/`NO_SHOW` et valeur inconnue.
- **Unit — application (fakes)** `tests/test_appointment_usecases.py` (étendre) :
  - `ModifyAppointment` : refuse un RDV **non possédé** (`AppointmentNotFound`), un RDV **terminé**
    (`AppointmentNotModifiable`), un salon non réservable (§8.3), une prestation inactive/hors salon ;
  - **exclut le RDV lui-même** du calcul de disponibilité (un simple changement de note, ou un
    déplacement chevauchant **son propre** créneau actuel, **n'est pas** faussement rejeté) ;
  - **propage `SlotAlreadyBooked`** quand le fake simule la violation d'exclusion sur `update` (course
    perdue / collision avec un autre RDV actif) — et **rien n'est modifié** ;
  - `client_id`/`salon_id` **jamais** issus du corps ; `metadata.changed` ne contient que des **noms**
    de champs (aucune valeur) et l'entrée d'audit est écrite dans la **même** unité de travail.
- **Intégration/HTTP** `tests/test_appointment_api.py` (étendre, `TestClient` + fakes ou Postgres) :
  - `PATCH /appointments/{id}` : `200` sur RDV `PENDING`/`CONFIRMED` possédé ; `409` sur RDV
    `COMPLETED` ; `404` sur RDV d'un autre client ; `422` sans prestation ; corps portant
    `client_id`/`salon_id`/`status` → **ignorés** (anti-élévation vérifiée) ; `403` pour un rôle non
    `CLIENT` ; `401` sans jeton.
  - `GET /appointments` (si livré) : ne renvoie que les RDV du client ; isolation vérifiée.
  - **Invariant deny-by-default** : `unprotected_routes(app)` reste **vide** (les nouvelles routes sont
    protégées ; test existant `test_security_guards`/`test_rbac_e2e` à faire passer sans y ajouter les
    chemins à `PUBLIC_ROUTE_PATHS`).
- **Intégration Postgres** `tests/test_appointment_e2e.py` ou nouveau `tests/test_appointment_modify_e2e.py`
  (skip sans `DATABASE_URL`) :
  - déplacement réel vers un créneau libre → `200`, `slot`/`updated_at` mis à jour, jonctions
    `appointment_services` remplacées ;
  - déplacement vers un créneau occupé par **un autre** RDV actif du même coiffeur → `409`
    (`SlotAlreadyBooked`, SQLSTATE `23P01`) — la garantie s'applique bien aux `UPDATE` ;
  - RDV inséré directement en `COMPLETED` (pas d'endpoint de transition au MVP) → `PATCH` = `409`
    (verrou) ;
  - une entrée `audit_logs` `APPOINTMENT_UPDATED` **neutre** est écrite (métadonnées = noms de champs).
- **Mobile — passerelle** `test/http_appointment_gateway_test.dart` (étendre, `MockClient`) : `modify`
  envoie l'en-tête `Authorization`, **omet** `client_id`/`salon_id`/`status`, mappe `200 → Appointment`,
  `409 → NotModifiable`/`SlotTaken` (selon le contexte), `404 → AppointmentNotFound`, `401 →
  Unauthorized` ; `myAppointments` mappe la liste ; **aucun** message ne contient jeton/URL/PII.
- **Mobile — use cases & widget** `test/modify_appointment_test.dart`, `test/my_appointments_screen_test.dart` :
  refus amont d'un RDV non modifiable ; le bouton « Modifier » est **désactivé** pour un RDV `completed`
  (« Terminé ») ; parcours nominal de modification (pré-rempli → confirmation) ; `409` verrou → message ;
  `409` créneau pris → retour choix créneau ; `401` → Connexion. **Le jeton n'apparaît dans aucun log.**
- **Documentation** : revue que `backend/README.md` et `app-mobile/README.md` documentent la
  modification, le verrou et le prérequis d'auth.

## Documentation Updates

- **`docs/adr/0025-modification-rendez-vous-client.md`** (nouveau) + entrée **`docs/adr/README.md`** :
  verrou d'état client, route d'appartenance, réutilisation du moteur #21 et de l'exclusion base pour
  les `UPDATE`, exclusion du RDV lui-même, journalisation §11.4, périmètre mobile, codes HTTP, backend
  sans nouveau schéma, frontière avec #24 (annulation) et #25 (gérant/cycle de statuts).
- **`backend/README.md`** : section « Modification d'un rendez-vous (client) » (route `PATCH`, verrou
  terminé, anti double-réservation sur `UPDATE`, journalisation, prérequis Postgres des tests e2e).
- **`app-mobile/README.md`** : section « Mes rendez-vous & modification » (flux, verrou UI, prérequis
  session, garde-fous de non-journalisation).
- **`README.md`** (récit §6, « M3 en cours ») : compléter au step `document` **après** livraison —
  **ne pas anticiper** de comportement non implémenté.
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstrings + `responses` sur les nouvelles routes (généré par FastAPI).

## Risks and Open Questions

- **États « modifiables » côté client** : le PRD §8.1 ne verrouille explicitement que le RDV **terminé**
  (`COMPLETED`). *Recommandation : n'autoriser la modification que sur `PENDING`/`CONFIRMED`* et
  verrouiller aussi `CANCELLED`/`NO_SHOW` (terminaux, sans sens à modifier). **À confirmer** — si l'on
  s'en tient à la lettre, seul `COMPLETED` serait verrouillé (mais modifier un RDV annulé n'a pas de
  sens produit).
- **« Selon les règles du salon »** (§8.1) : aucune **règle de délai/fenêtre de modification**
  configurable n'existe dans le schéma ni le PRD (au-delà des horaires/disponibilité). *Recommandation :
  au MVP, une modification est permise tant que (a) le RDV est non terminal et (b) le nouveau créneau est
  **offert** (salon réservable + dans les horaires + libre) ;* pas de « cutoff » temporel dédié. **À
  confirmer** — si une échéance (p. ex. « pas de modification < 2 h avant ») est voulue, elle nécessite
  une décision produit et un champ de configuration (hors périmètre S).
- **Forme de la route** : `PATCH /appointments/{id}` (route d'**appartenance**, pas de portée salon —
  *recommandée*) vs `PATCH /salons/{salon_id}/appointments/{id}` (le `salon_id` du chemin serait
  purement informatif pour un `CLIENT` sans portée salon, et devrait égaler celui du RDV). **À
  confirmer.**
- **Permission** : réutiliser **`APPOINTMENT_BOOK`** pour la modification (matrice §4.1 **inchangée**,
  cohérent avec le commentaire « réserve/modifie/annule ses RDV » ; ownership vérifiée dans le cas
  d'usage) — *recommandé* — vs introduire `APPOINTMENT_MODIFY_OWN` (matrice + tests de matrice à faire
  évoluer). **À confirmer.**
- **Code HTTP du verrou terminé** : `409 Conflict` (état de la ressource — *recommandé*, cohérent avec
  `SlotAlreadyBooked`) vs `403 Forbidden` (dimension « sauf par le gérant ») vs `423 Locked`. **À
  confirmer.**
- **Périmètre de la lecture « mes rendez-vous »** : #23 doit-il livrer `GET /appointments` (+ écran
  liste) — nécessaire pour **atteindre** le flux de modification — ou seulement le `PATCH` (le mobile
  récupérant l'id depuis la confirmation #22) ? *Recommandation : livrer une **lecture minimale** des
  RDV actifs du client dans #23* (partagée avec #24), l'historique complet (terminés + montants)
  restant à #30. **À confirmer** (impacte l'effort S).
- **Sémantique de modification** : *replace* des champs modifiables (ré-planification complète —
  *recommandé*, miroir du corps de réservation) vs `PATCH` partiel champ-à-champ. Autoriser le
  changement de **prestation(s)** (re-capture durée/prix) et de **note** en plus de la date/créneau. **À
  confirmer** (notamment si le prix figé doit être re-capturé au tarif courant lors d'un changement de
  prestation — *recommandé* — ou conservé).
- **TOCTOU statut load→update** : un changement de statut concurrent (gérant, capacité #25 non encore
  livrée) pourrait invalider le verrou entre la lecture et l'écriture. *Recommandation : UPDATE
  conditionnel (`WHERE status IN ('PENDING','CONFIRMED')`) ré-affirmant le verrou.* Risque faible au MVP
  (aucun endpoint de transition), garde-fou peu coûteux. **À confirmer.**
- **Notification de modification (§7.4)** : hors périmètre (Épic 7). Confirmer qu'aucune notification
  n'est attendue dans #23 (seulement la trace d'audit interne §11.4).
- **Persistance de session mobile** : le `TokenStore` est **en mémoire** (#22) — la session est perdue
  au redémarrage, la modification exige une reconnexion. Cohérent avec ADR-0024 ; le passage à un
  magasin sécurisé reste un simple remplacement d'implémentation (différé). **À noter.**
- **Fuseau horaire** : Africa/Abidjan = **UTC+0** (schéma `tsrange`, #16/#21). Le mobile doit construire
  dates/heures dans ce repère (comme #22) pour rester cohérent avec la disponibilité. **À expliciter.**
- **Outillage Postgres en test** (testcontainers vs service CI vs DSN local) : non tranché à l'échelle
  du dépôt ; s'aligner sur les e2e existants (skip conditionnel sur `DATABASE_URL`).

## Implementation Checklist

1. **Lire** : `application/appointments.py` (helpers réutilisés), `application/salons.py::UpdateSalon`
   + `adapters/inbound/salons.py` (patron update+audit, DI `get_audit_log`), `adapters/inbound/appointments.py`,
   `adapters/outbound/persistence/appointment_repository.py`, `domain/appointment.py`, `domain/errors.py`,
   `domain/audit.py`, `adapters/inbound/security.py`, `models.py` (Appointment/EXCLUDE/`updated_at`) ;
   mobile : `application/ports/appointment_gateway.dart`, `adapters/data/http_appointment_gateway.dart`,
   `adapters/ui/booking/*`, `domain/appointment/*`.
2. **Trancher les Open Questions structurantes** (états modifiables, règles salon/délai, forme de route,
   permission, code HTTP du verrou, périmètre de la lecture « mes RDV », sémantique de modification,
   UPDATE conditionnel) et les acter dans **ADR-0025** (+ `docs/adr/README.md`).
3. **Domaine** : `is_client_modifiable`/`CLIENT_MODIFIABLE_STATUSES` + VO `AppointmentUpdate`
   (`domain/appointment.py`) ; erreurs `AppointmentNotFound`/`AppointmentNotModifiable`
   (`domain/errors.py`, `__all__`) ; `AuditAction.APPOINTMENT_UPDATED` + `ENTITY_TYPE_APPOINTMENT`
   (`domain/audit.py`).
4. **Port** (`application/ports/appointment_repository.py`) : `get_owned`, `update`,
   `booked_slots(exclude_appointment_id=…)`, et `list_for_client` (si lecture retenue).
5. **Cas d'usage** (`application/appointments.py`) : `ModifyAppointmentCommand` + `ModifyAppointment`
   (ownership → verrou → re-validation §8.3/prestation/coiffeur → `is_offered` **excluant le RDV** →
   `update` transactionnel → audit `APPOINTMENT_UPDATED` métadonnées **neutres**).
6. **Adapter sortant** (`SqlAppointmentRepository`) : `get_owned`, `update` (champs + remplacement des
   jonctions, UPDATE conditionnel sur statut, traduction exclusion `23P01` → `SlotAlreadyBooked` **sans
   journaliser l'erreur brute**), `booked_slots` exclusif, `list_for_client`.
7. **Adapter entrant** (`adapters/inbound/appointments.py`) : `PATCH /appointments/{id}` (client
   `APPOINTMENT_BOOK`, **pas** de `require_salon_scope`, DI `get_audit_log`), `GET /appointments`
   (client `APPOINTMENT_READ_OWN`) si retenu ; schémas `extra="ignore"` sans champs privilégiés ;
   traductions d'erreurs → codes HTTP. **Ne rien ajouter à `PUBLIC_ROUTE_PATHS`.**
8. **Fakes de test** : étendre `FakeAppointmentRepository` (RDV en mémoire, modes `raise_conflict` /
   `not_modifiable`) et réutiliser `FakeAuditLog` dans `conftest.py`.
9. **Tests backend** : domaine, cas d'usage (fakes), API (`TestClient`, anti-élévation + deny-by-default),
   Postgres e2e (déplacement, collision `UPDATE`, verrou terminé, audit) — **skip** sans `DATABASE_URL`.
10. **Mobile** : `AppointmentGateway.modify` (+ `myAppointments`) + exceptions ; `HttpAppointmentGateway`
    (`PATCH`/`GET`) ; use cases ; `isClientModifiable` ; écran « Mes rendez-vous » + tunnel réutilisé en
    mode modification (verrou UI, `409`/`401` gérés) ; câblage `app.dart`/`main.dart`.
11. **Tests mobile** : passerelle (mock), use cases (fakes), widget (liste + verrou + flux) ; asserter
    **anti-élévation** (corps sans champs privilégiés) et **non-journalisation** du jeton/PII.
12. **Documentation** : ADR-0025 + `docs/adr/README.md` + sections `backend/README.md` /
    `app-mobile/README.md`.
13. **Garde-fous** : `pytest` et `flutter test` (et test gate agrégé) au vert ; aucun secret/jeton/PII
    journalisé ; corps de modification sans `client_id`/`salon_id`/`status` ; contrainte d'exclusion base
    **jamais** contournée (y compris sur `UPDATE`) ; `unprotected_routes(app)` **vide** ; **aucune**
    signature IA dans le code/commits/PR.
