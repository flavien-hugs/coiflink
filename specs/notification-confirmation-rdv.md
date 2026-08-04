# Notification de confirmation de RDV (US-7.1)

> Spécification de planification pour l'issue GitHub **#45 — US-7.1 : Notification de confirmation de
> RDV** (`feature` `notifications` · **Must** · Effort **M** · PRD §6 Épic 7 / §8.4 « Notifications » /
> §11.4 « Journalisation » / §11.3 « Données personnelles »). **Dépend de #22** (tunnel de réservation
> client, livré — consomme `POST /salons/{salon_id}/appointments` de #21). **Cette spec ne produit pas
> de code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 7, US-7.1 ; §8.4) pose le besoin : **« en tant que client, je veux recevoir une
confirmation après avoir réservé, pour être rassuré que mon rendez-vous est bien pris »**. Le libellé
du backlog précise : *« Push, SMS ou WhatsApp selon disponibilité ; envoyée après chaque
réservation »*. Le critère d'acceptation de l'issue #45 est :

- **Une confirmation part à la création du RDV ; notification critique tracée (§8.4/§11.4).**

### État actuel du dépôt (vérifié pour cette spec)

La **réservation est livrée** (#21/#22) : `POST /salons/{salon_id}/appointments`
(`adapters/inbound/appointments.py::book_appointment` → `application/appointments.py::BookAppointment`)
crée un `Appointment` au statut **`PENDING`** dans **une** unité de travail (la session de la requête,
committée par `get_session`, `adapters/outbound/persistence/session.py`). Le tunnel client #22
consomme cet endpoint **sans** modifier le backend et affiche le statut initial « En attente » depuis
la réponse du `POST`. **Aucune notification n'est aujourd'hui émise ni tracée** à la création du RDV.

Points structurants découverts en lisant la base de code :

1. **La table `notifications` existe déjà** (`adapters/outbound/persistence/models.py::Notification`,
   migration `0001`) : colonnes `id`, `user_id` (FK `users`, nullable), `salon_id` (FK, nullable),
   `appointment_id` (FK, nullable), `type`, `channel`, `title`, `message`, `status` (défaut
   `PENDING`), `sent_at` (nullable), `created_at`, avec contraintes `CHECK` sur `type`/`channel`/
   `status` (dérivées du domaine) et index `ix_notifications_user_id`, `ix_notifications_salon_id`.
2. **Le vocabulaire d'enum est déjà au domaine** (`domain/enums.py`) : `NotificationType.CONFIRMATION`
   (+ `REMINDER`/`CANCELLATION`), `NotificationChannel.{PUSH,SMS,EMAIL,WHATSAPP,IN_APP}`,
   `NotificationStatus.{PENDING,SENT,FAILED,READ}`. **Aucune migration de contrainte `CHECK` n'est
   requise** pour écrire une confirmation — différence majeure avec le reçu #38 (qui aurait dû
   élargir l'enum, cf. [ADR-0030](../docs/adr/0030-recu-numerique-remise-differee.md)).
3. **L'acheminement réel des notifications reste différé** (ADR-0006) : le PRD prévoit **FCM (push) +
   SMS via file Redis**, WhatsApp en **V2**. Le seul adapter de notification livré est le **stub
   no-op** d'OTP (`adapters/outbound/notifications/otp_sender_stub.py`), qui **ne journalise jamais**
   destinataire ni contenu. **Aucun worker de remise, aucune file Redis câblée, aucun fournisseur SMS
   concret** (décision opérationnelle différée, #5). **Aucun registre de jeton d'appareil** (device
   token FCM) n'existe dans le schéma — un `PUSH` ne peut donc être **ciblé** aujourd'hui.
4. **Pas de domaine ni de port « notification »** : ni `domain/notification.py`, ni
   `application/ports/notification_repository.py`, ni `adapters/outbound/persistence/notification_repository.py`.
   La table existe mais **rien n'y écrit**.
5. **Patron d'atomicité §11.4 établi** : `adapters/inbound/appointments.py::get_audit_log` fournit un
   `SqlAuditLog` adossé à **la même** `Session` que le dépôt de RDV (FastAPI met `get_session` en
   cache par requête) — la trace et l'écriture métier sont committées/rollbackées **ensemble**
   (patron #20/#23/#25). Ce patron est directement réutilisable pour écrire la notification.

### Le gap que #45 comble

Le critère est **« une confirmation part à la création du RDV ; notification critique tracée »**.
Comme la **remise réelle** (push FCM / SMS) dépend d'une infra **non encore construite** (worker
Redis + fournisseur SMS + registre de jetons — tous hors périmètre #45, cf. ADR-0006), l'interprétation
MVP fidèle et livrable — cohérente avec le précédent #38/ADR-0030 (« généré/récupérable, pas
envoyé ») — est :

> **Émettre la confirmation en la persistant** : à la création du RDV, écrire une ligne
> `notifications` (`type = CONFIRMATION`, canal résolu « selon disponibilité », `status = PENDING`,
> rattachée au client et au RDV) **dans la même unité de travail** que l'INSERT du RDV. Cette ligne
> **est la trace** de la notification critique (§8.4/§11.4) et **la file** que consommera le worker de
> remise (M5+, ADR-0006). L'acheminement effectif (FCM/SMS) reste **différé** (aucun envoi réel).

Ainsi la confirmation **« part à la création du RDV »** (elle est émise/enregistrée dans la
transaction de réservation) et **est tracée** (ligne persistée avec statut et horodatage), **sans**
inventer un canal de remise non implémenté et **sans** migration de schéma (l'enum `CONFIRMATION`
existe déjà).

## Goals

- **Émettre une confirmation à la création du RDV, atomiquement.** Dans `BookAppointment`, après
  l'INSERT réussi du RDV, **persister exactement une** ligne `notifications` (`type = CONFIRMATION`,
  `user_id = client_id`, `salon_id`, `appointment_id`, `status = PENDING`) via un **port d'écriture**,
  dans **la même** `Session` — donc committée avec le RDV, ou rollbackée avec lui (aucune notification
  « fantôme » sur une réservation qui échoue, aucun RDV sans sa confirmation).
- **Tracer la notification critique (§8.4/§11.4).** La ligne persistée (avec `status`, `created_at`,
  et `sent_at` renseigné plus tard par le worker) **constitue la trace** exigée par le critère. Elle
  est **neutre** : elle ne porte **aucune PII** (pas de numéro de téléphone, pas de nom) — seuls des
  identifiants opaques (`user_id`, `salon_id`, `appointment_id`) et un contenu **templaté**.
- **Sélection de canal « selon disponibilité », en fonction pure du domaine.** Une fonction pure
  `resolve_confirmation_channel(...)` choisit le canal par priorité **PUSH → SMS → IN_APP**, en
  fonction de signaux de disponibilité (jeton d'appareil connu ? téléphone connu ?). **WhatsApp est
  exclu** (V2, ADR-0006). Au MVP, faute de registre de jetons, `PUSH` n'est jamais disponible : le
  canal effectif est **SMS** (le client s'inscrit par téléphone, #8) avec `IN_APP` comme repli garanti
  (voir *Open Questions*).
- **Remise différée, assumée et documentée.** Aucun envoi réel (FCM/SMS) n'est effectué par #45 :
  `status` reste `PENDING`, `sent_at` reste `NULL`. La remise proactive relève du **worker M5+**
  (ADR-0006). Cohérent avec la non-remise de #38 (ADR-0030) et avec le budget de latence §12.1 (aucun
  appel réseau externe dans le chemin de requête).
- **Périmètre strict : confirmation client uniquement.** #45 ne notifie **que le client** et **que sur
  création**. La notification **au salon** (US-7.3, #47), les **rappels** (US-7.2, #46) et les
  notifications d'**annulation/modification** (US-7.4, #48) sont hors périmètre.
- **Zéro migration de schéma.** La table `notifications` et l'enum `CONFIRMATION` existent (migration
  `0001`) : #45 **écrit** dans l'existant, sans nouvelle table/colonne/contrainte.
- **Couverture de tests.** Domaine (résolution de canal, construction d'une notification neutre), cas
  d'usage (`BookAppointment` émet exactement une confirmation en cas de succès, **aucune** en cas
  d'échec ; atomicité), API (le `POST` renvoie toujours `201` ; une confirmation est enregistrée ;
  aucune route publique ajoutée), e2e PostgreSQL (réservation → ligne `notifications` `CONFIRMATION`
  `PENDING` liée au RDV, **sans** téléphone ; conflit de créneau → aucune notification).

## Non-Goals

- **Construire l'infra de remise (worker Redis, FCM push, SMS via agrégateur).** L'acheminement réel
  d'une confirmation « envoyée » dépend du worker de notifications (file Redis, ADR-0006) et du
  fournisseur SMS concret (décision opérationnelle #5), **différés M5+**. #45 **enregistre/émet** la
  confirmation (ligne `PENDING`) ; il n'implémente **aucun** envoi réel. Le stub OTP existant n'est ni
  remplacé ni sollicité.
- **Enregistrer un registre de jetons d'appareil (device token FCM) ni un flux d'enregistrement de
  token.** Sans lui, `PUSH` ne peut être ciblé ; sa mise en service est une **story distincte** (voir
  *Open Questions* §2). #45 ne l'introduit pas.
- **Notifier le salon à la réservation.** C'est **US-7.3 (#47)** (notification dashboard + option
  email/SMS). #45 émet **une seule** notification, destinée au **client**.
- **Émettre des rappels avant le RDV.** C'est **US-7.2 (#46)** (jobs asynchrones 24 h / 2 h / 30 min).
- **Émettre des notifications d'annulation/modification/changement de statut.** C'est **US-7.4
  (#48)**. En particulier, la **modification** d'un RDV (#23) et le **cycle de statuts gérant** (#25)
  **n'émettent pas** de confirmation via #45.
- **Exposer une lecture des notifications au client** (`GET /me/notifications`, écran « boîte de
  réception » IN_APP). Utile mais hors critère de #45 (voir *Open Questions* §7) ; recommandé
  **backend-only** pour cette issue.
- **Migration de schéma / élargissement d'enum.** Contrairement à #38, aucun changement de la table
  `notifications`, de `NotificationType`/`Channel`/`Status` ni de leurs contraintes `CHECK`.
- **Écran mobile spécifique.** Le tunnel #22 affiche déjà « En attente » depuis la réponse du `POST` ;
  la confirmation étant une notification **non remise** au MVP, il n'y a **rien de visible** à afficher
  côté mobile (voir *Open Questions* §7).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Notifications | **FCM + SMS via file Redis**, WhatsApp V2, **remise asynchrone différée** ; stub no-op au MVP | [0006](../docs/adr/0006-notifications-fcm-sms.md) |
| Réservation | `POST /salons/{id}/appointments` (statut `PENDING`, anti double-réservation base) | [0023](../docs/adr/0023-moteur-disponibilite-anti-double-reservation.md) / [0024](../docs/adr/0024-reservation-cote-client.md) |
| Mobile client | Flutter (Android prioritaire) | [0001](../docs/adr/0001-app-mobile-flutter.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0032** (KPI globaux plateforme). Aucun ADR n'existe pour les
notifications applicatives au-delà du socle ADR-0006 ; la première écriture dans `notifications` + un
port de notification justifie un **court ADR** « Notification de confirmation — persistance/trace,
remise différée M5 » (voir *Documentation Updates*).

### Patrons à réutiliser tels quels

- **Écriture § métier + trace §11.4 dans la même Session** — `adapters/inbound/appointments.py`
  (`get_audit_log` → `SqlAuditLog(session)`, injecté aux cas d'usage `ModifyAppointment`/
  `SetAppointmentStatus`) : la trace est écrite via un **port** dans la **même** `Session` que le RDV,
  commit/rollback conjoint (`get_session`). **Modèle direct** pour brancher un `NotificationRepository`
  sur la même session dans `BookAppointment`.
- **Cas d'usage qui orchestre écriture + effet transverse** — `ModifyAppointment.execute` :
  `repository.update(...)` **puis** `audit_log.record(AuditEntry(...))` dans la même transaction. #45
  fait l'analogue : `appointment = repository.create(...)` **puis**
  `notifications.enqueue(NotificationToCreate(...))`.
- **Port `Protocol` + adapter SQLAlchemy** — `application/ports/audit_log.py` (`AuditLog.record`) /
  `adapters/outbound/persistence/audit_log_repository.py` (`SqlAuditLog`) : gabarit exact pour
  `NotificationRepository.enqueue` / `SqlNotificationRepository`.
- **Domaine pur + valeurs d'enum** — `domain/audit.py` (`AuditEntry` `frozen`, sans I/O) : gabarit pour
  `domain/notification.py` (`NotificationToCreate` `frozen`, `resolve_confirmation_channel`,
  `build_confirmation_notification`). Les enums (`NotificationType`/`Channel`/`Status`) existent déjà.
- **Injection surchargeable en test** — providers `get_*_repository(session)` +
  `app.dependency_overrides` ; fakes en mémoire dans `tests/conftest.py` ; e2e adossés à un vrai
  PostgreSQL sautés si `DATABASE_URL` absent ; garde deny-by-default
  (`tests/test_security_guards.py::unprotected_routes`).

### Schéma déjà en place (source de vérité : `models.py`, migration `0001`)

- `notifications` : `user_id`/`salon_id`/`appointment_id` **nullable** (FK `RESTRICT`), `type`
  (`CHECK` = `NotificationType`), `channel` (`CHECK` = `NotificationChannel`), `title` (`String(255)`,
  **NOT NULL**), `message` (`Text`, **NOT NULL**), `status` (défaut `PENDING`, `CHECK` =
  `NotificationStatus`), `sent_at` (nullable), `created_at` (serveur). Index sur `user_id` et
  `(salon_id, created_at)`.
- `appointments` : porte `client_id`, `salon_id`, `hairdresser_id`, `appointment_date`, `start_time`,
  `end_time`, `status`. `BookAppointment` renvoie une entité `Appointment` **avec son `id`** après
  `flush`.
- `users` : `phone` (client inscrit par téléphone, #8) — **jamais** copié dans `notifications` ; le
  worker de remise le résoudra à l'envoi (le lien reste `user_id`).

### Contraintes transverses documentées

- **PRD §8.4** : une confirmation doit être **envoyée après chaque réservation** ; les **notifications
  critiques doivent être tracées** dans le système.
- **PRD §11.4** : journalisation des actions importantes (dont « Création rendez-vous ») ; **§11.3** :
  collecte minimale, non-fuite de PII, pas de log de PII.
- **ADR-0006** : canaux FCM + SMS, WhatsApp V2, **remise asynchrone (Redis)** ; **ne jamais
  journaliser** le **corps des messages**, les **OTP**, ni les **numéros/identifiants** ; **clés FCM /
  identifiants SMS hors dépôt** (#5), jamais committés ; journalisation limitée aux **métadonnées non
  sensibles** (statut d'envoi, horodatage).
- **PRD §12.1** : réponse API < 3 s → la remise réelle doit rester **hors** du chemin requête
  (asynchrone). #45 n'appelle aucun service externe : il n'écrit qu'une ligne locale.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test).

## Proposed Implementation

Approche recommandée : **la confirmation est une ligne `notifications` persistée à la création du RDV,
dans la même unité de travail ; canal résolu par une fonction pure ; remise réelle différée (aucun
envoi).** Aucune migration, aucun endpoint de lecture, aucune route publique.

### (A) Backend — domaine : notification pure (`domain/notification.py`, nouveau)

- `NotificationToCreate` : dataclass `frozen` **pure** portant les champs à insérer :
  `type: str`, `channel: str`, `user_id: uuid.UUID | None`, `salon_id: uuid.UUID | None`,
  `appointment_id: uuid.UUID | None`, `title: str`, `message: str`,
  `status: str = NotificationStatus.PENDING.value`.
- `ChannelAvailability` : petit dataclass `frozen` de **signaux** de disponibilité
  (`has_push_token: bool`, `has_phone: bool`) — jamais le jeton ni le numéro eux-mêmes, seulement des
  booléens (non-PII).
- `resolve_confirmation_channel(availability: ChannelAvailability) -> str` : fonction **pure**,
  priorité **PUSH → SMS → IN_APP** ; **WhatsApp exclu** (V2). Déterministe, testable, sans I/O.
- `build_confirmation_notification(*, client_id, salon_id, appointment_id, channel) ->
  NotificationToCreate` : assemble une notification **neutre**. `title`/`message` sont **templatés et
  sans PII** (ni téléphone, ni nom). Voir *Open Questions* §3 sur le niveau de détail du `message` (au
  MVP, message minimal type « Votre rendez-vous a bien été enregistré. » — la composition riche
  date/salon peut être laissée au worker de remise).
- Aucun `raise` métier : l'assemblage porte sur des données déjà validées par la réservation.

### (B) Backend — port d'écriture (`application/ports/notification_repository.py`, nouveau)

- `NotificationRepository(Protocol)` avec **une** méthode d'écriture :
  `enqueue(notification: NotificationToCreate) -> None` — insère la ligne (via `flush`, **sans
  commit** : l'unité de travail est pilotée par `get_session`, atomicité conjointe avec le RDV, patron
  `AuditLog`). Nom `enqueue` (et non `send`) pour marquer que **rien n'est acheminé** ici : la ligne
  `PENDING` **est la file**.
- **Aucune** méthode de lecture (pas d'endpoint client au périmètre #45).

### (C) Backend — cas d'usage : brancher l'émission dans `BookAppointment`

- `application/appointments.py::BookAppointment` reçoit une **nouvelle dépendance** injectée :
  `notification_repository: NotificationRepository`. Après l'INSERT réussi
  (`appointment = self._appointments.create(...)`), résoudre le canal puis **émettre** :
  ```python
  channel = resolve_confirmation_channel(availability)
  self._notifications.enqueue(
      build_confirmation_notification(
          client_id=client_id,
          salon_id=salon_id,
          appointment_id=appointment.id,
          channel=channel,
      )
  )
  return appointment
  ```
- **Disponibilité du canal** : au MVP, `availability = ChannelAvailability(has_push_token=False,
  has_phone=True)` (aucun registre de jetons ; le client est inscrit par téléphone). Deux options pour
  `has_phone` (voir *Open Questions* §2) : (i) supposer `True` (garantie #8, aucun accès base
  supplémentaire) ; (ii) lire `users.phone is not None` via un port existant. **Recommandation** :
  (i) au MVP (canal effectif = SMS), en laissant `resolve_confirmation_channel` prêt pour PUSH quand
  le registre de jetons existera.
- **Atomicité** : `enqueue` se fait **avant** le `return`, dans la même `Session`. Si `create` lève
  (`SlotAlreadyBooked`/`SlotUnavailable`), on n'atteint jamais l'`enqueue` (et un rollback global
  s'applique de toute façon) → **aucune** confirmation sur une réservation échouée.
- **Aucune** émission dans `ModifyAppointment`, `CancelAppointment`, `SetAppointmentStatus`,
  `AssignHairdresser` (périmètre #48/#46).

### (D) Backend — adapter sortant (`adapters/outbound/persistence/notification_repository.py`, nouveau)

- `SqlNotificationRepository(session)` implémente `NotificationRepository.enqueue` : construit un
  `models.Notification(...)` depuis `NotificationToCreate` et `session.add(...)` + `flush()` (sans
  commit ; **jamais** de `logger`/`print` du contenu ni d'un destinataire — ADR-0006). Gabarit :
  `SqlAuditLog`.

### (E) Backend — câblage de l'adapter entrant

- `adapters/inbound/appointments.py` : ajouter un provider `get_notification_repository(session)` (comme
  `get_audit_log`, **même** `Session` par requête) et l'injecter dans `book_appointment`, qui construit
  `BookAppointment(catalog, appointments, scope, notifications)`.
- **Aucun** nouveau chemin, **aucun** ajout à `security.PUBLIC_ROUTE_PATHS` : #45 ne crée pas de route
  (il enrichit le `POST` existant). Le contrat HTTP du `POST` (statut `201`, `AppointmentResponse`)
  **ne change pas**.

### (F) Backend — (option, différée) port d'acheminement `NotificationSender`

Si l'orchestrateur veut poser **le point d'accroche** de la remise sans l'implémenter, ajouter un port
`NotificationSender` (`send(notification) -> None`) avec un **stub no-op** (gabarit `StubOtpSender`,
`adapters/outbound/notifications/`), **non invoqué** dans le chemin de requête (la remise reste le job
du worker M5+). **Recommandation** : **différer** — la ligne `notifications` `PENDING` suffit comme file
et comme trace ; ajouter le port maintenant risque du code mort. À trancher dans l'ADR (*Open
Questions* §1).

### (G) Trace §11.4 — la ligne `notifications` est la trace

Le critère « notification critique **tracée** (§8.4/§11.4) » est satisfait par la **ligne persistée**
(type, canal, statut, `created_at`, `sent_at` ultérieur). **Recommandation** : **ne pas** ajouter en
plus une entrée `audit_logs` — la table `notifications` est le registre dédié des notifications, et
dupliquer dans l'audit n'apporte rien (et §11.4 « Création rendez-vous » relèverait plutôt de #21).
Alternative à trancher (*Open Questions* §5) : ajouter une action neutre `APPOINTMENT_CREATED` /
`NOTIFICATION_ENQUEUED` à `AuditAction` si l'on veut aussi une trace côté audit — **métadonnées
neutres** (jamais de PII), même unité de travail.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/notification.py` | **nouveau** — `NotificationToCreate`, `ChannelAvailability`, `resolve_confirmation_channel`, `build_confirmation_notification` (purs) |
| `coiflink_api/application/ports/notification_repository.py` | **nouveau** — `NotificationRepository` (`enqueue`) |
| `coiflink_api/application/appointments.py` | **modifier** — `BookAppointment` reçoit `NotificationRepository` et émet la confirmation après `create` |
| `coiflink_api/adapters/outbound/persistence/notification_repository.py` | **nouveau** — `SqlNotificationRepository.enqueue` (INSERT + `flush`, sans commit) |
| `coiflink_api/adapters/inbound/appointments.py` | **modifier** — provider `get_notification_repository` + injection dans `book_appointment` |
| `coiflink_api/adapters/outbound/notifications/notification_sender_stub.py` | **optionnel/différé** — stub no-op si le port `NotificationSender` est retenu (§F) |
| `backend/README.md` | section « Notification de confirmation » : émission à la réservation, trace, non-remise (M5) |

### Backend — tests

| Fichier | Contenu |
| --- | --- |
| `tests/test_domain_notification.py` | **nouveau** — `resolve_confirmation_channel` (PUSH>SMS>IN_APP, WhatsApp exclu), `build_confirmation_notification` **neutre** (aucune PII, `type=CONFIRMATION`, `status=PENDING`) |
| `tests/test_appointment_usecases.py` | **étendre** — `BookAppointment` émet **exactement une** confirmation en cas de succès (canal attendu, `appointment_id` lié) ; **aucune** sur `SlotUnavailable`/`SlotAlreadyBooked` ; atomicité (fake `NotificationRepository`) |
| `tests/test_appointment_api.py` | **étendre** — `POST` renvoie toujours `201` ; une confirmation est enregistrée (assertion sur le fake) ; contrat de réponse inchangé |
| `tests/test_appointment_concurrency.py` | **étendre/vérifier** — la course perdue (`SlotAlreadyBooked`) ne laisse **aucune** notification |
| `tests/test_security_guards.py` | **vérifier** — aucune route ajoutée ; rien dans `PUBLIC_ROUTE_PATHS` |
| `tests/test_appointment_notification_e2e.py` | **nouveau** — PostgreSQL réel : réservation → 1 ligne `notifications` `CONFIRMATION` `PENDING`, `appointment_id`/`user_id` liés, `sent_at IS NULL`, **aucun** téléphone stocké ; conflit → 0 notification |
| `tests/conftest.py` | fake `NotificationRepository` (mémoire) + branchement dans les fixtures de `BookAppointment` |

### Backend — à lire (sans modifier)

`adapters/outbound/persistence/audit_log_repository.py` (gabarit `SqlAuditLog`),
`application/ports/audit_log.py` + `domain/audit.py` (gabarit port/domaine),
`adapters/outbound/persistence/appointment_repository.py` (`create`, `flush`, atomicité),
`adapters/outbound/persistence/session.py` (`get_session`, commit par requête),
`adapters/outbound/persistence/models.py` (`Notification`), `domain/enums.py`
(`NotificationType`/`Channel`/`Status`), `adapters/outbound/notifications/otp_sender_stub.py`
(gabarit stub, non-journalisation).

### Documentation (racine)

`README.md` (§6 : statut « M5 : notification de confirmation de RDV (US-7.1, #45) »), nouvel ADR
`docs/adr/0033-notification-confirmation-rdv.md` + index `docs/adr/README.md`.

### Mobile (`app-mobile/`)

**Aucun** changement requis au MVP (la confirmation n'est pas remise ; le tunnel #22 affiche déjà « En
attente »). Voir *Open Questions* §7 pour un éventuel écran « Notifications » (hors périmètre).

## API / Interface Changes

**Aucun nouvel endpoint, aucun changement de contrat HTTP.** #45 enrichit le **comportement interne**
de `POST /salons/{salon_id}/appointments` (une confirmation est désormais persistée dans la même
transaction) **sans** modifier son entrée ni sa sortie : mêmes garde (`APPOINTMENT_BOOK`), même corps
`BookAppointmentRequest`, même réponse `201 AppointmentResponse`.

- **Aucune** route de lecture des notifications au périmètre #45 (`GET /me/notifications` = *Open
  Questions* §7).
- **Aucun** ajout à `PUBLIC_ROUTE_PATHS` (une notification n'est jamais publique).
- **Aucune** modification de CLI, de variable d'environnement (au MVP — la remise réelle en aura,
  différée), ni de contrat inter-paquet. **Interface web gérant** : aucune (la confirmation est
  client ; le salon relève de #47). **Interface mobile** : aucune (voir *Non-Goals*).

## Data Model / Protocol Changes

**Aucune.** La table `notifications` et les valeurs d'enum `CONFIRMATION`/`PUSH`/`SMS`/`IN_APP`/
`PENDING` existent depuis la migration `0001` (`models.py`, `domain/enums.py`). #45 **écrit** une ligne
dans l'existant ; il n'ajoute **ni** table, **ni** colonne, **ni** index, **ni** valeur d'enum, **ni**
migration Alembic. C'est la différence structurante avec #38 (qui aurait exigé d'élargir
`NotificationType` + migrer un `CHECK`, cf. ADR-0030).

> Sérialisation : les champs de notification sont des chaînes/UUID/horodatages simples ; **aucun
> montant** n'est stocké (pas de `Decimal` ici).

## Security & Privacy Considerations

- **Non-fuite de PII dans la notification (§11.3, ADR-0006).** La ligne `notifications` ne stocke
  **que** des identifiants opaques (`user_id`, `salon_id`, `appointment_id`) et un `title`/`message`
  **templaté neutre** : **jamais** le numéro de téléphone, le nom du client, ni un secret. Le worker de
  remise (futur) résoudra `user_id → users.phone` **à l'envoi** — le numéro **n'est jamais copié** dans
  `notifications`.
- **Non-journalisation du contenu (ADR-0006).** `SqlNotificationRepository` et `BookAppointment`
  n'émettent **aucun** `logger`/`print` du destinataire, du canal ni du corps du message. Le stub OTP
  existant, référence de non-journalisation, n'est pas sollicité.
- **Remise différée = aucune exposition externe.** Aucun appel FCM/SMS n'est effectué : rien n'est
  transmis à un opérateur tiers, donc **aucune** exposition de PII hors du périmètre authentifié. Les
  **clés FCM / identifiants SMS restent hors dépôt** (#5) — #45 n'en introduit ni n'en committe aucun.
- **Atomicité (§11.4).** La confirmation est persistée dans **la même** `Session` que le RDV
  (`get_session` commit/rollback conjoint) : pas de RDV sans trace de confirmation, pas de trace sur un
  RDV rollbacké. La ligne persistée (statut + horodatage) **est** la trace §8.4/§11.4.
- **Isolation & autorisation inchangées (§11.2/ADR-0015).** #45 n'ajoute aucune route, donc aucune
  surface d'autorisation nouvelle ; deny-by-default reste intact. Le `user_id` est **imposé serveur**
  (`client_id = principal.id`, déjà garanti par la réservation), jamais soumis.
- **Budget de latence (§12.1).** L'émission n'ajoute qu'un INSERT local (aucun I/O réseau externe) : le
  `POST` reste bien sous 3 s.

Le dépôt **documente** ces contraintes (PRD §8.4/§11.3/§11.4, ADR-0006) : #45 les respecte sans en
affaiblir aucune.

## Testing Plan

### Backend — unitaires domaine (`pytest`, sans I/O)

- **`tests/test_domain_notification.py`** (nouveau) :
  - `resolve_confirmation_channel` : `has_push_token=True → PUSH` ; sinon `has_phone=True → SMS` ;
    sinon `IN_APP` ; **jamais** `WHATSAPP` (exclu V2) ; déterminisme.
  - `build_confirmation_notification` : `type == CONFIRMATION`, `status == PENDING`, `user_id`/
    `salon_id`/`appointment_id` correctement rattachés, `title`/`message` **non vides et sans PII**
    (aucun numéro/nom injecté), canal = celui passé.

### Backend — cas d'usage (`pytest`, fakes de `conftest.py`)

- **`tests/test_appointment_usecases.py`** (étendre) : `BookAppointment` avec un fake
  `NotificationRepository` —
  - **succès** : après une réservation valide, **exactement une** notification enqueuée, `type =
    CONFIRMATION`, `appointment_id == appointment.id`, `user_id == client_id`, canal attendu ;
  - **échec** (`SlotUnavailable`, `SlotAlreadyBooked`, `SalonNotBookable`, `ServiceNotFound`,
    `HairdresserNotInSalon`) : **aucune** notification enqueuée ;
  - **atomicité** : l'`enqueue` passe par la même `Session` (vérifiée via le fake / ordre d'appel) ;
  - **non-régression** : `ModifyAppointment`/`CancelAppointment`/`SetAppointmentStatus` n'émettent
    **aucune** confirmation.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_appointment_api.py`** (étendre) : `POST /salons/{id}/appointments` —
  - renvoie toujours `201` + `AppointmentResponse` **inchangé** ;
  - une confirmation est enregistrée (assertion sur le fake `NotificationRepository` surchargé) ;
  - un `409`/`404`/`422` n'enregistre **aucune** confirmation.
- **`tests/test_security_guards.py`** : `unprotected_routes(app)` **inchangé** (aucune route ajoutée) ;
  **aucun** chemin notification dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_appointment_notification_e2e.py`** (nouveau, patron des e2e existants : données
  réservées, nettoyage avant/après) :
  1. gérant → salon réservable → prestation → **client** réserve un créneau →
     `SELECT ... FROM notifications` : **une** ligne `type=CONFIRMATION`, `status=PENDING`,
     `user_id = client`, `appointment_id = RDV`, `sent_at IS NULL`, et **aucune** colonne ne contient
     le téléphone du client ;
  2. **course perdue** (deux réservations concurrentes du même créneau/coiffeur, patron
     `test_appointment_concurrency.py`) : le perdant (`409`) ne laisse **aucune** notification (rollback
     conjoint) ;
  3. la confirmation est committée **avec** le RDV (présente dès que le `POST` a répondu `201`).

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test **web inchangé** + flutter test **mobile inchangé**) au
vert ; `ruff check` propre ; aucune régression sur `POST /salons/{id}/appointments` (#21/#22) ni sur
les cas d'usage RDV existants (signature de `BookAppointment` mise à jour partout : call site adapter +
fixtures de tests).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Notifications (confirmation de RDV) » : à la
  réservation, une notification `CONFIRMATION` est **persistée** (`user_id`, `salon_id`,
  `appointment_id`, canal résolu, `status=PENDING`) dans la même transaction que le RDV ; elle **trace**
  la notification critique (§8.4/§11.4) ; la **remise réelle** (FCM/SMS via file Redis) est **différée
  M5+** (ADR-0006) — rien n'est envoyé, `sent_at` reste `NULL`. Préciser : **aucune migration**, canal
  effectif MVP = SMS (PUSH nécessite un registre de jetons, story distincte).
- **`README.md`** (racine) — §6 : phrase de statut « **M5** : notification de confirmation de RDV
  (US-7.1, #45) — à la création d'un RDV, une confirmation `CONFIRMATION` est **émise/tracée** dans la
  table `notifications` (§8.4/§11.4), même unité de travail que la réservation ; **remise proactive**
  (push/SMS) différée (ADR-0006) », dans le style existant.
- **`docs/adr/0033-notification-confirmation-rdv.md`** (**nouvel ADR**) : figer (a) la confirmation
  comme **ligne `notifications` persistée** à la création du RDV (pas de migration : enum
  `CONFIRMATION` déjà présent) ; (b) le **port `NotificationRepository`** + écriture atomique (patron
  `AuditLog`) ; (c) la **résolution de canal** pure PUSH→SMS→IN_APP, WhatsApp exclu, PUSH indisponible
  au MVP (pas de registre de jetons) ; (d) la **non-remise** (worker/fournisseur SMS différés M5+,
  ADR-0006) ; (e) le **périmètre** strict (client, création) vs #46/#47/#48. Mettre à jour
  `docs/adr/README.md`.
- **OpenAPI** — la docstring de `book_appointment` mentionne désormais l'émission de la confirmation
  (« une confirmation `CONFIRMATION` est tracée à la création, remise différée §8.4/ADR-0006 »),
  remplaçant les commentaires actuels « Aucune notification n'est émise (§8.4 → Épic 7) » **là où ils
  concernent la création** (ceux de `cancel`/`set_status` restent, relevant de #48).

## Risks and Open Questions

1. **« Émise » = persistée (recommandé) vs « envoyée » (remise réelle).** *Recommandation : persister
   la confirmation (`notifications` `PENDING`) atomiquement — c'est l'émission + la trace — et
   **différer** la remise réelle (worker Redis + FCM/SMS) à M5+ (ADR-0006), comme #38/ADR-0030 a
   différé la remise du reçu.* Ajouter dès #45 un port `NotificationSender` + stub no-op (§F) est
   **optionnel** ; recommandation : différer (éviter le code mort). **À trancher / consigner dans
   l'ADR.**
2. **Sélection « selon disponibilité » & absence de registre de jetons.** Aucun device token FCM n'est
   stocké → `PUSH` **ne peut être ciblé** au MVP ; le canal effectif est **SMS** (ou `IN_APP`). *À
   confirmer :* (a) le canal par défaut MVP (SMS recommandé) ; (b) si `has_phone` est **supposé vrai**
   (garantie #8, aucun accès base) ou **lu** via un port ; (c) l'introduction d'un **registre de jetons
   d'appareil** (story distincte) qui activera PUSH. **Recommandation** : SMS par défaut, `has_phone`
   supposé vrai, PUSH prêt côté domaine mais inactif.
3. **Contenu du `message`/`title` vs non-journalisation (ADR-0006).** La colonne `message` est **NOT
   NULL**. *Recommandation : message **templaté minimal et neutre** (aucune PII : ni téléphone, ni
   nom)* ; la composition riche (date/heure/salon) — données que le client possède — peut être **laissée
   au worker de remise** pour minimiser le stockage. **À confirmer** : niveau de détail du message
   persisté.
4. **Notifier aussi le salon ?** **Non** au périmètre #45 — c'est **US-7.3 (#47)**. La ligne unique
   émise cible le **client** (`user_id = client_id`). *À confirmer* que #47 reste séparé.
5. **Double trace (audit §11.4) ?** *Recommandation : la ligne `notifications` suffit comme trace ; ne
   pas dupliquer dans `audit_logs`.* Variante : ajouter `APPOINTMENT_CREATED`/`NOTIFICATION_ENQUEUED` à
   `AuditAction` (métadonnées neutres, même transaction) si une trace côté audit est souhaitée. **À
   trancher dans l'ADR.**
6. **Placement de l'émission : cas d'usage (recommandé) vs adapter.** *Recommandation : dans
   `BookAppointment`* (« à la réservation, une confirmation est émise » est une **règle métier**),
   testable sans HTTP. Impact : signature de `BookAppointment` modifiée → mettre à jour le call site
   adapter et **toutes** les fixtures de test qui l'instancient.
7. **Écran/lecture des notifications côté client (`GET /me/notifications`, IN_APP).** Hors critère de
   #45 (rien n'est remis). *Recommandation : hors périmètre* ; à planifier si une « boîte de réception »
   IN_APP est voulue (ne pas exposer de PII tierce, patron d'appartenance §11.2).
8. **Idempotence / réservations multiples.** Chaque `POST` réussi émet **une** confirmation ; deux
   réservations distinctes → deux confirmations (attendu). La **modification** (#23) n'émet rien (#48).
   *À confirmer* qu'aucune contrainte d'unicité `notifications` n'est requise (aucune au schéma).
9. **Statut initial `PENDING` vs `SENT`.** *Recommandation : `PENDING`* (honnête : rien n'est envoyé) ;
   le worker M5+ passera `SENT` + `sent_at`. Ne **pas** marquer `SENT` au MVP (mensonger). *À
   confirmer.*
10. **ADR dédié.** *Recommandation : oui* — court ADR-0033 figeant persistance/trace + non-remise M5 +
    résolution de canal + périmètre. À confirmer.

## Implementation Checklist

1. **Vérifier l'état livré** : relire `application/appointments.py::BookAppointment` (#21) et son call
   site `adapters/inbound/appointments.py::book_appointment` ; `adapters/outbound/persistence/{audit_log_repository,appointment_repository,session}.py`
   (atomicité, `flush` sans commit) ; `models.py::Notification` ; `domain/enums.py`
   (`NotificationType.CONFIRMATION` **présent**) ; `otp_sender_stub.py` (non-journalisation).
   **Trancher** les questions ouvertes 1–10 ; consigner dans un **ADR-0033**.
2. **Domaine** : créer `domain/notification.py` (`NotificationToCreate`, `ChannelAvailability`,
   `resolve_confirmation_channel`, `build_confirmation_notification` — purs, sans PII) ; écrire
   `tests/test_domain_notification.py`.
3. **Port** : `application/ports/notification_repository.py` (`NotificationRepository.enqueue`).
4. **Cas d'usage** : modifier `BookAppointment` pour recevoir `NotificationRepository` et **émettre**
   la confirmation après `create` (canal résolu, même `Session`) ; ajouter un fake
   `NotificationRepository` à `tests/conftest.py` ; étendre `tests/test_appointment_usecases.py`
   (succès = 1 confirmation, échec = 0, non-régression modif/annulation/statut).
5. **Persistance** : `adapters/outbound/persistence/notification_repository.py`
   (`SqlNotificationRepository.enqueue` : `add` + `flush`, **aucun** log de contenu/destinataire).
6. **Adapter entrant** : provider `get_notification_repository(session)` + injection dans
   `book_appointment` ; **aucune** route ajoutée, **rien** dans `PUBLIC_ROUTE_PATHS` ; étendre
   `tests/test_appointment_api.py` (201 inchangé + confirmation enregistrée) et vérifier
   `tests/test_security_guards.py`.
7. **e2e** : `tests/test_appointment_notification_e2e.py` (réservation → 1 ligne `CONFIRMATION`
   `PENDING` liée, sans téléphone ; conflit → 0). Exécuter `pytest` (+ `DATABASE_URL`) et `ruff check`.
8. **(Optionnel, différé)** si retenu (§F) : port `NotificationSender` + `notification_sender_stub.py`
   no-op **non invoqué** ; sinon s'abstenir (recommandé).
9. **Documentation** : section `backend/README.md` ; phrase de statut `README.md` racine (M5) ;
   `docs/adr/0033-notification-confirmation-rdv.md` + index `docs/adr/README.md` ; docstring
   `book_appointment` mise à jour (émission de la confirmation, remise différée).
10. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test **web inchangé** +
    flutter test **mobile inchangé**), `ruff check` ; relire la PR pour garantir qu'**aucun** numéro,
    nom, secret ni contenu de message n'apparaît dans les logs, que la notification est **persistée
    dans la même transaction** que le RDV, qu'**aucune** confirmation n'est émise sur une réservation
    échouée, que **rien n'est réellement « envoyé »** (non-remise assumée, `PENDING`, ADR-0006),
    qu'**aucune** route/valeur d'enum/migration n'a été ajoutée, et qu'**aucune signature IA** n'a été
    introduite.
