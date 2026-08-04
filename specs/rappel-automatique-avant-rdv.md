# Rappel automatique avant RDV (US-7.2)

> Spécification de planification pour l'issue GitHub **#46 — US-7.2 : Rappel automatique avant RDV**
> (`feature` `notifications` · **Must** · Effort **M** · PRD §6 Épic 7 / §8.4 « Notifications » /
> §9.8 « Notification » / §11.3 « Données personnelles » / §11.4 « Journalisation » / §12.1 « Latence »).
> **Dépend de #22** (tunnel de réservation client, livré — consomme
> `POST /salons/{salon_id}/appointments` de #21). S'appuie directement sur le socle de notification
> livré par **#45** (US-7.1). **Cette spec ne produit pas de code** : elle décrit l'approche à
> implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 7, US-7.2 ; §8.4) pose le besoin : **« en tant que client, je veux recevoir un rappel
avant mon rendez-vous »**. Le libellé du backlog (#46) précise : *« Rappel configurable 24h / 2h /
30 min via jobs asynchrones »*, et le critère d'acceptation de l'issue est :

- **Rappel planifié et envoyé à l'échéance ; l'annulation du RDV annule le rappel.**

### État actuel du dépôt (vérifié pour cette spec)

Le **socle de notification est livré par #45** (US-7.1, `feat/45`) et directement réutilisable :

1. **Le trio domaine / port / adapter existe** :
   - `domain/notification.py` — `NotificationToCreate` (dataclass `frozen`, miroir des colonnes de
     `models.Notification`), `ChannelAvailability`, `resolve_confirmation_channel` (fonction pure
     **PUSH → SMS → IN_APP**, WhatsApp exclu V2), `build_confirmation_notification`, et les libellés
     templatés `CONFIRMATION_TITLE`/`CONFIRMATION_MESSAGE`.
   - `application/ports/notification_repository.py` — `NotificationRepository(Protocol)` avec **une**
     méthode d'écriture `enqueue(notification) -> None` (nom délibéré : rien n'est acheminé, la ligne
     `PENDING` **est la file**).
   - `adapters/outbound/persistence/notification_repository.py` — `SqlNotificationRepository.enqueue`
     (`session.add(...)` + `flush()`, **sans commit** : atomicité conjointe avec l'écriture métier via
     `get_session`, patron `AuditLog` #20).
2. **`BookAppointment` émet déjà une confirmation** à la création du RDV (`application/appointments.py`),
   dans la même unité de travail, canal résolu « selon disponibilité » (au MVP : **SMS**).
   `CancelAppointment` (#24) et `SetAppointmentStatus` (#25) **n'émettent aucune notification**
   aujourd'hui (commentaires explicites « Aucune notification n'est émise (§8.4 → Épic 7) »).
3. **La table `notifications` et l'enum `NotificationType.REMINDER` existent** (migration `0001`,
   `domain/enums.py`). Écrire une notification de type `REMINDER` **n'exige aucune migration de type**.
4. **La remise réelle reste différée M5+** (ADR-0006) : le PRD prévoit **FCM (push) + SMS via file
   Redis** (§10.2, §12.7 : « Jobs asynchrones pour notifications », « Redis »). **Aucun worker de
   remise, aucune file Redis câblée, aucun fournisseur SMS concret, aucun ordonnanceur (scheduler)**
   n'existe dans le backend. Le seul adapter de notification « d'envoi » livré est le **stub no-op**
   d'OTP (`adapters/outbound/notifications/otp_sender_stub.py`), qui **ne journalise jamais**
   destinataire ni contenu. **Aucun registre de jetons d'appareil** (device token FCM) — `PUSH` n'est
   pas ciblable au MVP.

### Le gap structurant que #46 comble (et ce qui manque au schéma)

Un **rappel** diffère d'une confirmation sur deux points décisifs, qui appellent chacun une extension :

1. **Un rappel a une échéance future** (`24h` / `2h` / `30 min` **avant** l'heure du RDV). La table
   `notifications` **ne porte aucune colonne d'échéance** : ses colonnes sont `id`, `user_id`,
   `salon_id`, `appointment_id`, `type`, `channel`, `title`, `message`, `status`
   (`PENDING`/`SENT`/`FAILED`/`READ`), `sent_at`, `created_at`. Il **manque un horodatage « à envoyer
   à »**. C'est la différence majeure avec #45 (qui écrivait sans migration) : **#46 nécessite une
   migration** ajoutant une colonne d'échéance (recommandé : `scheduled_for TIMESTAMPTZ NULL`).
2. **Un rappel doit pouvoir être annulé** quand le RDV est annulé (AC explicite). L'enum
   `NotificationStatus` **ne porte pas de valeur `CANCELLED`** : pour tracer honnêtement un rappel qui
   ne partira jamais (sans le supprimer), il faut **soit** élargir l'enum (recommandé : ajouter
   `CANCELLED`), **soit** supprimer les lignes de rappel `PENDING` à l'annulation (voir *Open
   Questions* §3).

Comme pour #45/#38 (ADR-0030), la **remise réelle** dépend d'une infra **non construite** (ordonnanceur
+ worker Redis + fournisseur SMS). L'interprétation MVP fidèle et livrable est donc :

> **Planifier les rappels en les persistant** : à la création du RDV, écrire (en plus de la
> confirmation #45) **une ligne `notifications` par échéance encore future** (`type = REMINDER`,
> `status = PENDING`, `scheduled_for = début_du_RDV − offset`, rattachée au client/salon/RDV) **dans la
> même unité de travail** que l'INSERT du RDV. Ces lignes **sont** les jobs planifiés (§8.4 : « rappel
> planifié ») et **la file** que consommera le worker de remise M5+ (ADR-0006). **À l'annulation** du
> RDV (client #24 ou refus gérant #25), **annuler** les rappels `PENDING` de ce RDV **dans la même
> transaction** (AC : « l'annulation du RDV annule le rappel »). L'**envoi effectif à l'échéance**
> (« envoyé à l'échéance ») relève du **worker M5+** — #46 **planifie/annule**, il n'**envoie** rien
> (`sent_at` reste `NULL`).

Ainsi le rappel est **« planifié »** (ligne `PENDING` datée) et son **annulation est câblée** au cycle
de vie du RDV, **sans** inventer un ordonnanceur/worker non implémenté, et en assumant explicitement —
comme #45 — que la **remise proactive reste différée**.

## Goals

- **Planifier les rappels à la création du RDV, atomiquement.** Dans `BookAppointment`, après l'INSERT
  réussi du RDV et l'émission de la confirmation (#45), **persister une ligne `notifications`
  `type = REMINDER` par échéance encore future** (parmi `24h` / `2h` / `30 min` avant le début du RDV),
  via le port d'écriture, dans **la même** `Session` — donc committées avec le RDV, ou rollbackées avec
  lui. Une échéance déjà passée au moment de la réservation (p. ex. le rappel `24h` d'un RDV réservé
  2 h à l'avance) **n'est pas planifiée** (aucune ligne « en retard » à la création).
- **Annuler les rappels quand le RDV est annulé (AC).** Dans `CancelAppointment` (#24) et dans
  `SetAppointmentStatus` sur transition `→ CANCELLED` (refus gérant, #25), **annuler** (marquer
  `CANCELLED`, ou supprimer — cf. *Open Questions* §3) **tous** les rappels `PENDING` du RDV concerné,
  **dans la même unité de travail** que le changement de statut. Un RDV annulé ne laisse **aucun**
  rappel `PENDING` derrière lui.
- **Rappel planifié = trace (§8.4/§11.4).** La ligne persistée (type, canal, `status`, `scheduled_for`,
  `created_at`, `sent_at` ultérieur) **constitue** la trace de la notification critique. Elle est
  **neutre** : **aucune PII** (ni téléphone, ni nom) — seulement des identifiants opaques (`user_id`,
  `salon_id`, `appointment_id`), un horodatage d'échéance et un contenu **templaté**.
- **Sélection de canal « selon disponibilité », réutilisée du domaine #45.** Réutiliser la fonction pure
  de résolution de canal **PUSH → SMS → IN_APP** (WhatsApp exclu, V2). Au MVP, faute de registre de
  jetons, le canal effectif est **SMS**. Ne pas dupliquer la logique : généraliser ou réutiliser
  `resolve_confirmation_channel` (voir *Proposed Implementation*).
- **Remise différée, assumée et documentée (cohérence #45/#38).** Aucun envoi réel (FCM/SMS) et **aucun
  ordonnanceur** n'est construit par #46 : les rappels restent `PENDING`, `sent_at` reste `NULL`.
  L'**« envoi à l'échéance »** relève du **worker M5+** (ADR-0006) qui interrogera les lignes `REMINDER`
  `PENDING` dont `scheduled_for <= now`. Aucun appel réseau externe dans le chemin de requête (budget de
  latence §12.1).
- **Cohérence des rappels sur modification du RDV.** Si un RDV est **re-planifié** (#23, la date/heure
  change), ses rappels `PENDING` doivent être **re-datés** (annuler puis re-planifier) afin de ne pas
  laisser de rappels périmés pointant l'ancien créneau (voir *Open Questions* §5 — recommandation :
  gérer la re-planification dans `ModifyAppointment`).
- **Périmètre strict : rappels client uniquement.** #46 ne planifie/annule que **les rappels du
  client**. La notification **au salon** (US-7.3, #47) et les notifications d'**annulation/modification**
  poussées au client (US-7.4, #48) restent hors périmètre.
- **Couverture de tests.** Domaine (calcul des échéances, filtre des offsets déjà passés, construction
  d'un rappel neutre), cas d'usage (`BookAppointment` planifie le bon nombre de rappels ; `Cancel`/refus
  gérant annulent les rappels ; atomicité), API (contrats HTTP inchangés), e2e PostgreSQL (réservation →
  lignes `REMINDER` `PENDING` datées ; annulation → rappels `CANCELLED`/supprimés).

## Non-Goals

- **Construire l'ordonnanceur et l'infra de remise (scheduler, worker Redis, FCM push, SMS via
  agrégateur).** L'**envoi effectif à l'échéance** dépend d'un **ordonnanceur** (cron/beat) et d'un
  **worker** consommant la file Redis (ADR-0006) + du fournisseur SMS concret (#5), **différés M5+**.
  #46 **planifie/annule** les rappels (lignes `PENDING` datées) ; il n'implémente **aucun** envoi réel,
  **aucune** boucle d'ordonnancement, **aucune** file Redis. Le stub OTP n'est ni remplacé ni sollicité.
- **Introduire un registre de jetons d'appareil (device token FCM).** Toujours absent → `PUSH` non
  ciblable ; canal effectif = SMS. Story distincte (voir #45, *Open Questions*).
- **Modéliser des préférences de rappel « configurables » par client/salon.** Le libellé « configurable
  24h / 2h / 30 min » est interprété au MVP comme un **jeu d'offsets par défaut** (constante du domaine).
  **Aucune** table/colonne de préférence (activer/désactiver un offset, choisir ses canaux) n'est
  introduite : une vraie configuration par utilisateur/salon est une évolution ultérieure (voir *Open
  Questions* §2).
- **Notifier le salon** (US-7.3, #47) ni **pousser au client** l'annulation/la modification (US-7.4,
  #48). En particulier, l'annulation d'un RDV **annule** ses rappels (#46) mais **n'émet pas** de
  notification « votre RDV a été annulé » (c'est #48).
- **Exposer une lecture des notifications/rappels au client** (`GET /me/notifications`, écran « boîte de
  réception »). Hors critère de #46 (rien n'est remis) — recommandé backend-only.
- **Écran mobile spécifique.** Le rappel n'étant pas remis au MVP, il n'y a **rien de visible** à
  afficher côté mobile.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Notifications | **FCM + SMS via file Redis**, WhatsApp V2, **remise asynchrone différée** ; stub no-op au MVP | [0006](../docs/adr/0006-notifications-fcm-sms.md) |
| Confirmation de RDV (#45) | ligne `notifications` `CONFIRMATION` persistée atomiquement, remise différée | [0033](../docs/adr/0033-notification-confirmation-rdv.md) |
| Réservation / annulation | `POST /salons/{id}/appointments` (`PENDING`) ; annulation client / cycle gérant | [0023](../docs/adr/0023-moteur-disponibilite-anti-double-reservation.md) / [0024](../docs/adr/0024-reservation-cote-client.md) / [0025](../docs/adr/0025-annulation-rendez-vous-client.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0033** (notification de confirmation, #45). L'ajout d'une
colonne d'échéance + la planification/annulation des rappels justifie un **court ADR-0034**
« Rappel automatique — planification/trace persistée, annulation liée au cycle de vie du RDV, remise
différée M5 » (voir *Documentation Updates*).

### Patrons à réutiliser tels quels

- **Trio domaine / port / adapter de notification (#45)** — gabarit direct pour étendre le domaine
  (`build_reminder_notifications`), le port (`cancel_pending_for_appointment`) et l'adapter.
- **Écriture métier + effet transverse dans la même `Session`** — `BookAppointment` (émission
  confirmation #45), `ModifyAppointment`/`CancelAppointment`/`SetAppointmentStatus` (audit §11.4 via
  `AuditLog` #20/#23/#24). **Modèle direct** pour brancher la planification/annulation des rappels dans
  ces cas d'usage sur la **même** `Session`.
- **UPDATE conditionnel avec ré-affirmation du verrou** — `SqlAppointmentRepository.cancel` /
  `set_status` (`WHERE status IN (actifs)` / `WHERE salon_id = … AND status = expected`). Gabarit pour
  `cancel_pending_for_appointment` (UPDATE ciblé `WHERE appointment_id = … AND type = 'REMINDER' AND
  status = 'PENDING'`).
- **Migration Alembic chaînée** — dernière révision livrée `0005_customer_gender`
  (`down_revision = "0004"`) ; #46 ajoute `0006_notification_scheduling` (`down_revision = "0005"`).
  Contraintes `CHECK` dérivées du domaine (`enum_check(...)` dans `models.py`) — élargir `CANCELLED`
  suppose de **régénérer** la contrainte `CHECK` de `status` dans la migration.
- **Injection surchargeable en test** — providers `get_*_repository(session)` +
  `app.dependency_overrides` ; `FakeNotificationRepository` (mémoire) déjà présent dans
  `tests/conftest.py` (accumule `enqueued`) — à **étendre** (offsets/`scheduled_for`, méthode
  d'annulation). E2e adossés à un vrai PostgreSQL, sautés si `DATABASE_URL` absent ; garde
  deny-by-default (`tests/test_security_guards.py::unprotected_routes`).

### Schéma déjà en place (source de vérité : `models.py`, migration `0001`)

- `notifications` : `user_id`/`salon_id`/`appointment_id` **nullable** (FK `RESTRICT`), `type`
  (`CHECK` = `NotificationType` — **`REMINDER` déjà présent**), `channel` (`CHECK`), `title`
  (**NOT NULL**), `message` (**NOT NULL**), `status` (défaut `PENDING`, `CHECK` = `NotificationStatus`
  — **pas de `CANCELLED`**), `sent_at` (nullable), `created_at`. **Pas de colonne d'échéance.** Index
  `ix_notifications_user_id`, `ix_notifications_salon_id (salon_id, created_at)`.
- `appointments` : `client_id`, `salon_id`, `hairdresser_id`, `appointment_date` (`Date`), `start_time`
  (`Time`), `end_time`, `status`. L'instant de début du RDV se compose de `appointment_date` +
  `start_time`, **naïf dans le fuseau Africa/Abidjan (UTC+0)** — convention établie (#21, `SALON_TIMEZONE`).
- `users` : `phone` (client inscrit par téléphone, #8) — **jamais** copié dans `notifications` ; le
  worker de remise le résoudra à l'envoi (le lien reste `user_id`).

### Contraintes transverses documentées

- **PRD §8.4** : un **rappel doit être envoyé avant le rendez-vous** ; les **notifications critiques
  doivent être tracées**.
- **PRD §11.4** : journalisation des actions importantes ; **§11.3** : collecte minimale, non-fuite de
  PII, pas de log de PII.
- **ADR-0006** : canaux FCM + SMS, WhatsApp V2, **remise asynchrone (Redis)** ; **ne jamais
  journaliser** le corps des messages, les numéros/identifiants ; **clés FCM / identifiants SMS hors
  dépôt** (#5) ; journalisation limitée aux métadonnées non sensibles.
- **PRD §12.1** : réponse API < 3 s → la remise réelle (et l'ordonnancement) doivent rester **hors** du
  chemin requête. #46 n'ajoute que des INSERT/UPDATE locaux.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test).

## Proposed Implementation

Approche recommandée : **les rappels sont des lignes `notifications` `REMINDER` datées, planifiées à la
création du RDV dans la même unité de travail, et annulées au cycle de vie du RDV ; canal résolu par la
fonction pure #45 ; remise réelle différée (aucun envoi, aucun ordonnanceur).** Une **migration** ajoute
l'échéance (et, recommandé, le statut `CANCELLED`). Aucun endpoint public, aucune route de lecture.

### (A) Data model — migration `0006_notification_scheduling` (nouveau)

- **Colonne d'échéance** : ajouter `notifications.scheduled_for TIMESTAMPTZ NULL`. Sémantique :
  `NULL` = à remettre **au plus tôt** (confirmation #45, inchangée) ; **non-`NULL`** = à remettre **à
  partir de** `scheduled_for` (rappel). Nullable → **aucun backfill** ; les lignes `CONFIRMATION` de #45
  restent valides avec `scheduled_for = NULL`. Refléter la colonne dans `models.Notification`.
- **Statut `CANCELLED`** (recommandé, cf. *Open Questions* §3) : ajouter
  `NotificationStatus.CANCELLED = "CANCELLED"` (`domain/enums.py`) et **régénérer** la contrainte
  `CHECK` de `status` dans la migration (drop + recreate depuis `values(NotificationStatus)`).
- **Index pour le futur worker** (optionnel, cf. *Open Questions* §7) : un index partiel
  `ix_notifications_due (scheduled_for) WHERE status = 'PENDING'` accélérera la requête « rappels dus »
  du worker M5+. Bon marché et documente l'intention ; à trancher (aucun consommateur au périmètre #46).
- `up()` : `op.add_column(...)` + (recommandé) reconstruction du `CHECK` `status` ; `down()` symétrique.

### (B) Backend — domaine : rappels purs (`domain/notification.py`, étendre)

- **`NotificationToCreate`** : ajouter le champ `scheduled_for: datetime.datetime | None = None`
  (miroir de la nouvelle colonne). Champ **neutre** (un horodatage, pas une PII).
- **Constante `REMINDER_OFFSETS`** : tuple ordonné des avances de rappel, p. ex.
  `(timedelta(hours=24), timedelta(hours=2), timedelta(minutes=30))`. C'est la matérialisation de
  « configurable 24h / 2h / 30 min » (jeu par défaut, sans modèle de préférence au MVP). Libellés
  templatés neutres `REMINDER_TITLE` / `REMINDER_MESSAGE` (aucune PII : « Rappel de rendez-vous » /
  « Vous avez un rendez-vous à venir. » — la composition riche date/heure/salon est laissée au worker).
- **`compute_reminder_schedules(appointment_start, *, now, offsets=REMINDER_OFFSETS) -> tuple[datetime,
  ...]`** : fonction **pure** qui renvoie, pour chaque offset, `appointment_start − offset` **filtré aux
  échéances strictement futures** (`> now`) — déterministe, sans I/O. Un RDV trop proche ne produit que
  les rappels encore atteignables (voire aucun).
- **`build_reminder_notifications(*, client_id, salon_id, appointment_id, appointment_start, channel,
  now) -> tuple[NotificationToCreate, ...]`** : assemble une `NotificationToCreate`
  (`type = REMINDER`, `status = PENDING`, `scheduled_for = échéance`, contenu templaté neutre) **par
  échéance future**. Aucun `raise` (données déjà validées par la réservation).
- **Canal** : réutiliser la résolution de canal #45. Recommandation : **renommer**
  `resolve_confirmation_channel → resolve_notification_channel` (générique, réutilisé par confirmation
  **et** rappel) en conservant un alias rétrocompatible, **ou** appeler la fonction existante telle
  quelle. Ne pas dupliquer la logique PUSH→SMS→IN_APP.

### (C) Backend — port d'écriture (`application/ports/notification_repository.py`, étendre)

- Conserver `enqueue(notification)` (utilisé pour la confirmation **et** chaque rappel — le champ
  `scheduled_for` porte la date).
- Ajouter **une** méthode d'annulation :
  `cancel_pending_for_appointment(appointment_id: uuid.UUID) -> None` — annule (marque `CANCELLED`, ou
  supprime, cf. §3) **tous** les rappels `PENDING` (`type = REMINDER`) rattachés au RDV, dans la même
  unité de travail (`flush`, **sans commit**). **Aucune** méthode de lecture au périmètre #46 (la
  requête « rappels dus » du worker relève de M5+).

### (D) Backend — adapter sortant (`adapters/outbound/persistence/notification_repository.py`, étendre)

- `enqueue` : recopier `notification.scheduled_for` dans `models.Notification(...)` (le reste inchangé,
  toujours sans log de contenu/destinataire, ADR-0006).
- `cancel_pending_for_appointment` : `UPDATE notifications SET status = 'CANCELLED' WHERE appointment_id
  = :aid AND type = 'REMINDER' AND status = 'PENDING'` (ou `DELETE` équivalent selon §3), via
  `session.execute(update(...))` + `flush()`, **sans commit**. Idempotent (aucune ligne à annuler → no-op).

### (E) Backend — cas d'usage

- **`BookAppointment`** (`application/appointments.py`) : après l'émission de la confirmation (#45),
  **planifier les rappels** :
  ```python
  appointment_start = datetime.datetime.combine(command.date, command.start_time)
  for reminder in build_reminder_notifications(
      client_id=client_id,
      salon_id=salon_id,
      appointment_id=appointment.id,
      appointment_start=appointment_start,
      channel=channel,          # même canal que la confirmation (résolu une fois)
      now=now,
  ):
      self._notifications.enqueue(reminder)
  return appointment
  ```
  `now` est déjà propagé au cas d'usage (`execute(..., now=...)`). Aucune nouvelle dépendance :
  `BookAppointment` possède déjà `notification_repository`.
- **`CancelAppointment`** (#24) : recevoir une **nouvelle dépendance** `NotificationRepository` ; après
  le `cancel` réussi (RDV → `CANCELLED`), appeler `self._notifications.cancel_pending_for_appointment(
  appointment_id)` **dans la même transaction** (avant/après l'audit `APPOINTMENT_CANCELLED`, même
  `Session`). Un RDV déjà terminal (`AppointmentNotCancellable`) n'atteint pas ce point → pas
  d'annulation parasite.
- **`SetAppointmentStatus`** (#25) : recevoir `NotificationRepository` ; **uniquement** quand
  `target_status == CANCELLED` (refus gérant), appeler `cancel_pending_for_appointment(appointment_id)`
  après le `set_status` réussi, même `Session`. Les autres transitions (`CONFIRMED`, `COMPLETED`,
  `NO_SHOW`) **n'annulent pas** de rappel ici (cf. *Open Questions* §4 : les rappels d'un RDV `COMPLETED`/
  `NO_SHOW` ont une échéance déjà passée ; le worker M5+ ne remet pas un rappel en retard).
- **`ModifyAppointment`** (#23, recommandé — cf. *Open Questions* §5) : recevoir `NotificationRepository` ;
  après l'`update` réussi, **annuler puis re-planifier** les rappels sur la nouvelle date/heure
  (`cancel_pending_for_appointment` puis `build_reminder_notifications(... appointment_start=nouveau ...)`),
  même `Session`. Évite les rappels périmés pointant l'ancien créneau. **À trancher** (l'alternative :
  déférer à #48).

### (F) Backend — câblage de l'adapter entrant (`adapters/inbound/appointments.py`)

- Injecter `get_notification_repository(session)` (déjà défini pour la réservation #45) dans
  `cancel_appointment`, `set_appointment_status` (et `modify_appointment` si §5 retenu), et le passer
  aux cas d'usage correspondants (signatures mises à jour).
- **Mettre à jour les docstrings** : supprimer/rectifier les mentions « **Aucune notification n'est
  émise (§8.4 → Épic 7)** » de `cancel_appointment` et `set_appointment_status` — elles indiquent
  désormais « l'annulation **annule les rappels** planifiés (§8.4, US-7.2 #46), même unité de travail ;
  aucune notification poussée (US-7.4 #48) ».
- **Aucune** route ajoutée, **aucun** ajout à `security.PUBLIC_ROUTE_PATHS` : les contrats HTTP de
  `POST /salons/{id}/appointments`, `POST /appointments/{id}/cancellation` et
  `POST /salons/{id}/appointments/{id}/status` **ne changent pas** (statuts, corps, réponses inchangés).

### (G) Backend — (différé, hors périmètre) worker de remise / ordonnanceur

Le **worker M5+** (Épic 7, ADR-0006) interrogera périodiquement les lignes `REMINDER` `PENDING` avec
`scheduled_for <= now` **et** un RDV encore actif (défense : re-vérifier le statut du RDV à l'envoi),
puis passera `SENT` + `sent_at` après remise FCM/SMS via la file Redis. **#46 ne le construit pas** (ni
port `NotificationSender`, ni scheduler, ni consommateur de file) — cohérent avec le report de
`NotificationSender` en #45. Ajouter un tel point d'accroche maintenant = code mort/non testé
(recommandation : s'abstenir ; consigner dans l'ADR).

### (H) Trace §11.4 — la ligne `notifications` est la trace

Comme #45, la **ligne persistée** (type, canal, statut, `scheduled_for`, `created_at`, `sent_at`
ultérieur) **est** la trace exigée par §8.4/§11.4. **Recommandation** : ne pas ajouter de double trace
`audit_logs` pour la planification/annulation de rappels — la table `notifications` est le registre
dédié. (L'audit du **RDV** lui-même — création/annulation — reste porté par #21/#24/#25, inchangé.)

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/adapters/outbound/persistence/migrations/versions/0006_notification_scheduling.py` | **nouveau** — `add_column scheduled_for` (+ recréation `CHECK` `status` si `CANCELLED`, + index partiel optionnel) |
| `coiflink_api/adapters/outbound/persistence/models.py` | **modifier** — colonne `scheduled_for` sur `Notification` (+ `CHECK` `status` régénéré si `CANCELLED`) |
| `coiflink_api/domain/enums.py` | **modifier** (si retenu §3) — `NotificationStatus.CANCELLED` |
| `coiflink_api/domain/notification.py` | **modifier** — champ `scheduled_for`, `REMINDER_OFFSETS`, `REMINDER_TITLE`/`REMINDER_MESSAGE`, `compute_reminder_schedules`, `build_reminder_notifications` ; canal généralisé (`resolve_notification_channel`) |
| `coiflink_api/application/ports/notification_repository.py` | **modifier** — `cancel_pending_for_appointment(appointment_id)` |
| `coiflink_api/adapters/outbound/persistence/notification_repository.py` | **modifier** — persister `scheduled_for` ; implémenter `cancel_pending_for_appointment` (UPDATE/DELETE ciblé, `flush`) |
| `coiflink_api/application/appointments.py` | **modifier** — `BookAppointment` planifie les rappels ; `CancelAppointment` + `SetAppointmentStatus` (→`CANCELLED`) reçoivent `NotificationRepository` et annulent les rappels ; `ModifyAppointment` re-planifie (si §5) |
| `coiflink_api/adapters/inbound/appointments.py` | **modifier** — injecter `get_notification_repository` dans `cancel`/`set_status`/(`modify`) ; docstrings « aucune notification » rectifiées |
| `backend/README.md` | section « Notifications (rappels avant RDV) » : planification à la réservation, annulation liée au cycle de vie, non-remise (M5) |

### Backend — tests

| Fichier | Contenu |
| --- | --- |
| `tests/test_domain_notification.py` | **étendre** — `compute_reminder_schedules` (échéances = début − offset ; offsets passés **exclus** ; déterminisme) ; `build_reminder_notifications` **neutre** (aucune PII, `type=REMINDER`, `status=PENDING`, `scheduled_for` correct, canal passé) |
| `tests/test_appointment_usecases.py` | **étendre** — `BookAppointment` planifie **N** rappels (N = offsets futurs) **+ 1** confirmation ; RDV trop proche → moins/aucun rappel ; **aucun** sur réservation échouée ; `CancelAppointment` appelle `cancel_pending_for_appointment` (une fois) ; `SetAppointmentStatus` annule **uniquement** sur `→ CANCELLED` ; `ModifyAppointment` re-planifie (si §5) ; atomicité (même `Session`) |
| `tests/test_appointment_api.py` | **étendre** — `POST` renvoie `201` inchangé (rappels planifiés) ; `POST .../cancellation` et `POST .../status` (→CANCELLED) renvoient inchangé (rappels annulés) ; contrats de réponse inchangés |
| `tests/test_security_guards.py` | **vérifier** — aucune route ajoutée ; rien dans `PUBLIC_ROUTE_PATHS` |
| `tests/test_appointment_notification_e2e.py` | **étendre** — PostgreSQL réel : réservation → lignes `REMINDER` `PENDING` datées (`scheduled_for = début − offset`), liées, `sent_at IS NULL`, sans téléphone ; annulation client → rappels `CANCELLED` (ou supprimés), 0 `PENDING` restant ; refus gérant → idem ; (si §5) modification → rappels re-datés |
| `tests/conftest.py` | **étendre** `FakeNotificationRepository` — enregistrer `scheduled_for` ; implémenter `cancel_pending_for_appointment` (mémoire) ; brancher dans les fixtures de `CancelAppointment`/`SetAppointmentStatus`/(`ModifyAppointment`) |

### Backend — à lire (sans modifier)

`adapters/outbound/persistence/appointment_repository.py` (`create`/`cancel`/`set_status`, atomicité,
UPDATE conditionnel), `adapters/outbound/persistence/session.py` (`get_session`, commit par requête),
`adapters/outbound/persistence/audit_log_repository.py` (gabarit port/adapter), `domain/time_window.py`
(`SALON_TIMEZONE`, fuseau du RDV), migration `0005_customer_gender` (dernière révision, gabarit de
chaînage), `otp_sender_stub.py` (non-journalisation).

### Documentation (racine)

`README.md` (§6 : statut « M5 : rappel automatique avant RDV (US-7.2, #46) »), nouvel ADR
`docs/adr/0034-rappel-automatique-avant-rdv.md` + index `docs/adr/README.md`.

### Mobile (`app-mobile/`)

**Aucun** changement requis au MVP (le rappel n'est pas remis).

## API / Interface Changes

**Aucun nouvel endpoint, aucun changement de contrat HTTP.** #46 enrichit le **comportement interne** de
trois routes existantes **sans** modifier entrée/sortie :

- `POST /salons/{salon_id}/appointments` — planifie désormais aussi des rappels `REMINDER` (en plus de
  la confirmation #45) ; réponse `201 AppointmentResponse` **inchangée**.
- `POST /appointments/{appointment_id}/cancellation` (#24) — annule désormais les rappels `PENDING` du
  RDV ; réponse `200 AppointmentResponse` **inchangée**.
- `POST /salons/{salon_id}/appointments/{appointment_id}/status` (#25) — sur `→ CANCELLED`, annule les
  rappels ; réponse **inchangée**.
- (si §5) `PATCH /appointments/{appointment_id}` (#23) — re-planifie les rappels ; réponse **inchangée**.

Aucune route de lecture des notifications, aucun ajout à `PUBLIC_ROUTE_PATHS`, aucune modification de
CLI. **Nouvelle variable d'environnement** : aucune au MVP (la remise réelle et l'ordonnanceur, avec
leurs secrets FCM/SMS, en auront — différés M5+, #5). **Interfaces web/mobile** : aucune.

## Data Model / Protocol Changes

**Migration `0006_notification_scheduling` requise** (contrairement à #45, qui n'en exigeait aucune) :

- **Nouvelle colonne** `notifications.scheduled_for TIMESTAMPTZ NULL` (nullable → aucun backfill ; les
  lignes `CONFIRMATION` de #45 restent valides avec `scheduled_for = NULL`).
- **Élargissement d'enum (recommandé, §3)** : `NotificationStatus.CANCELLED` → **régénération** de la
  contrainte `CHECK` de `status` (drop + recreate depuis `values(NotificationStatus)`).
- **Index partiel optionnel** `ix_notifications_due (scheduled_for) WHERE status = 'PENDING'` (pour la
  future requête « rappels dus » du worker M5+ ; aucun consommateur au périmètre #46 — à trancher).
- `NotificationType.REMINDER` **existe déjà** (aucune migration de `type`).
- Round-trip Alembic (`upgrade`/`downgrade`) vérifié en CI (`backend` job, PostgreSQL 16).

> Sérialisation : `scheduled_for` est un `datetime` (timestamptz) ; **aucun montant** n'est stocké. Les
> horodatages naïfs des RDV (`appointment_date` + `start_time`, Africa/Abidjan UTC+0) sont composés
> **côté cas d'usage** avant écriture — cohérence de fuseau à respecter (§*Risks*).

## Security & Privacy Considerations

- **Non-fuite de PII (§11.3, ADR-0006).** Les lignes `REMINDER` ne stockent **que** des identifiants
  opaques (`user_id`, `salon_id`, `appointment_id`), un `scheduled_for` (horodatage, non-PII) et un
  `title`/`message` **templaté neutre** — **jamais** le téléphone, le nom, ni un secret. Le worker de
  remise résoudra `user_id → users.phone` **à l'envoi** ; le numéro n'est **jamais** copié.
- **Non-journalisation du contenu (ADR-0006).** L'adapter et les cas d'usage n'émettent **aucun**
  `logger`/`print` du destinataire, du canal, du corps ni de l'échéance. Le stub OTP (référence de
  non-journalisation) n'est pas sollicité.
- **Remise différée = aucune exposition externe.** Aucun appel FCM/SMS, aucun ordonnanceur : rien n'est
  transmis à un tiers. **Clés FCM / identifiants SMS restent hors dépôt** (#5) — #46 n'en introduit ni
  n'en committe aucun.
- **Atomicité (§11.4).** Planification (à la réservation) et annulation (à l'annulation du RDV) se font
  dans **la même** `Session` que l'écriture métier (`get_session`, commit/rollback conjoint) : pas de
  RDV sans ses rappels, pas de rappel `PENDING` survivant à un RDV annulé, aucun rappel « fantôme » sur
  une réservation échouée.
- **Isolation & autorisation inchangées (§11.2/ADR-0015).** Aucune route ajoutée → aucune surface
  d'autorisation nouvelle ; deny-by-default intact. `user_id` **imposé serveur** (`client_id =
  principal.id`), jamais soumis ; l'annulation d'un RDV ne touche que **ses** rappels (filtre
  `appointment_id`).
- **Budget de latence (§12.1).** La planification ajoute jusqu'à 3 INSERT locaux (offsets futurs) ;
  l'annulation, un UPDATE ciblé — **aucun** I/O réseau externe. Les routes restent bien sous 3 s.

Le dépôt **documente** ces contraintes (PRD §8.4/§11.3/§11.4/§12.1, ADR-0006/0033) : #46 les respecte
sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires domaine (`pytest`, sans I/O)

- **`tests/test_domain_notification.py`** (étendre) :
  - `compute_reminder_schedules` : pour un début `T`, renvoie `{T−24h, T−2h, T−30min}` **∩ futur** ;
    exclut les offsets déjà passés au regard de `now` (RDV réservé 90 min à l'avance → seul `30 min` ou
    rien) ; ordre déterministe ; RDV très proche → tuple vide.
  - `build_reminder_notifications` : `type == REMINDER`, `status == PENDING`, `scheduled_for` = échéance
    attendue, `user_id`/`salon_id`/`appointment_id` rattachés, `title`/`message` **non vides, sans PII**,
    canal = celui passé ; **une** notification par échéance future.
  - canal : `resolve_notification_channel` conserve **PUSH → SMS → IN_APP**, `WHATSAPP` exclu (parité #45).

### Backend — cas d'usage (`pytest`, fakes de `conftest.py`)

- **`tests/test_appointment_usecases.py`** (étendre), fake `NotificationRepository` :
  - **réservation (succès)** : `BookAppointment` **enqueue** 1 `CONFIRMATION` + **N** `REMINDER`
    (N = nombre d'offsets encore futurs), `appointment_id`/`user_id` liés, `scheduled_for` cohérents ;
    RDV trop proche → moins de rappels (voire aucun), mais **toujours** la confirmation.
  - **réservation (échec)** : `SlotUnavailable`/`SlotAlreadyBooked`/… → **aucune** notification
    (confirmation **ni** rappel).
  - **annulation client** : `CancelAppointment` appelle `cancel_pending_for_appointment(appointment_id)`
    **exactement une fois** dans la même transaction (vérifié via le fake) ; un RDV non annulable
    (`AppointmentNotCancellable`) **n'annule aucun** rappel.
  - **refus gérant** : `SetAppointmentStatus` annule les rappels **uniquement** sur `→ CANCELLED` ;
    `→ CONFIRMED`/`COMPLETED`/`NO_SHOW` **n'annulent pas**.
  - **(si §5) modification** : `ModifyAppointment` annule puis re-planifie sur la nouvelle date/heure.
  - **atomicité** : planification/annulation passent par la **même** `Session` (ordre/appels via le fake).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_appointment_api.py`** (étendre) : `POST .../appointments` → `201` inchangé + rappels
  enregistrés (assertion sur le fake) ; `POST .../cancellation` et `POST .../status` (→CANCELLED) →
  réponses inchangées + annulation enregistrée ; un échec (`409`/`404`/`422`) n'enregistre **aucun**
  rappel / n'annule rien indûment.
- **`tests/test_security_guards.py`** : `unprotected_routes(app)` **inchangé** ; **aucun** chemin
  notification dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_appointment_notification_e2e.py`** (étendre, patron existant #45 — plage de numéros
  réservée, nettoyage avant/après ; `notifications` supprimé **avant** `appointments`/`users`/`salons`
  — mémoire `notifications-fk-restrict-cleanup`) :
  1. réservation d'un RDV **suffisamment lointain** → **3** lignes `type=REMINDER` `status=PENDING`,
     `scheduled_for` = `début − {24h,2h,30min}`, `sent_at IS NULL`, liées au client/salon/RDV, **sans**
     téléphone ; + la ligne `CONFIRMATION` de #45 (contenu #45 inchangé).
  2. **annulation client** (`POST .../cancellation`) → **0** rappel `PENDING` restant pour ce RDV
     (marqués `CANCELLED`, ou supprimés selon §3) ; la contrainte `CHECK` réelle accepte `CANCELLED`.
  3. **refus gérant** (`POST .../status` `CANCELLED`) → idem.
  4. **(si §5)** modification (`PATCH`) déplaçant le RDV → rappels re-datés sur le nouveau créneau.
  5. la planification/annulation respecte les contraintes réelles (FK `RESTRICT`, `CHECK`
     `type`/`channel`/`status`).

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test **web inchangé** + flutter test **mobile inchangé**) au vert ;
`ruff check` propre ; **round-trip Alembic** (`upgrade`/`downgrade` `0006`) vert ; aucune régression sur
la réservation (#21/#22/#45), l'annulation (#24) ni le cycle gérant (#25) — signatures de
`CancelAppointment`/`SetAppointmentStatus`/(`ModifyAppointment`) mises à jour partout (call sites +
fixtures).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Notifications (rappels avant RDV) » : à la réservation,
  jusqu'à **3** rappels `REMINDER` `PENDING` sont **planifiés** (`scheduled_for = début − 24h/2h/30min`,
  offsets encore futurs uniquement) dans la même transaction que le RDV ; à l'**annulation** (client
  #24 ou refus gérant #25), les rappels `PENDING` du RDV sont **annulés** (`CANCELLED`) dans la même
  transaction ; la **remise réelle à l'échéance** (FCM/SMS via file Redis + ordonnanceur) est **différée
  M5+** (ADR-0006) — rien n'est envoyé, `sent_at` reste `NULL`. Préciser : **migration `0006`** (colonne
  `scheduled_for`, statut `CANCELLED`), canal effectif MVP = SMS.
- **`README.md`** (racine) — §6 : phrase de statut « **M5** : rappel automatique avant RDV (US-7.2,
  #46) — à la création d'un RDV, des rappels `REMINDER` sont **planifiés/tracés** (`scheduled_for`,
  24h/2h/30min) dans `notifications`, même unité de travail que la réservation ; l'**annulation du RDV
  annule les rappels** (§8.4/§11.4) ; **remise proactive** (push/SMS) et **ordonnanceur** différés
  (ADR-0006) », dans le style existant.
- **`docs/adr/0034-rappel-automatique-avant-rdv.md`** (**nouvel ADR**) : figer (a) le rappel comme
  **ligne `notifications` `REMINDER` datée** (`scheduled_for`) persistée à la réservation ; (b) la
  **migration `0006`** (colonne d'échéance + statut `CANCELLED`, index optionnel) ; (c) le jeu d'offsets
  **24h/2h/30min** par défaut (pas de modèle de préférence au MVP) et le **filtre des offsets passés** ;
  (d) l'**annulation liée au cycle de vie du RDV** (client #24 + refus gérant #25) via
  `cancel_pending_for_appointment`, atomique ; (e) la **non-remise** (worker + ordonnanceur différés
  M5+, ADR-0006) ; (f) le **périmètre** strict (client, planification/annulation) vs #47/#48. Mettre à
  jour `docs/adr/README.md`.
- **OpenAPI** — docstrings de `book_appointment` (mention de la planification des rappels),
  `cancel_appointment` et `set_appointment_status` (mention de l'annulation des rappels) mises à jour ;
  **retirer/rectifier** les « Aucune notification n'est émise (§8.4 → Épic 7) » de `cancel`/`set_status`
  là où elles concernent l'annulation des rappels (la **poussée** d'annulation au client reste #48).

## Risks and Open Questions

1. **« Planifié + envoyé à l'échéance » = persisté-daté (recommandé) vs remise réelle.** *Recommandation :
   persister les rappels (`REMINDER` `PENDING` datés) atomiquement — c'est la planification + la trace —
   et **différer** l'envoi effectif (ordonnanceur + worker Redis + FCM/SMS) à M5+ (ADR-0006), comme #45/
   #38 ont différé la remise.* Sans worker, le rappel n'est **jamais réellement envoyé** au MVP ; l'AC
   « envoyé à l'échéance » est **honnêtement partiel** — à **assumer et documenter** dans l'ADR (ne pas
   laisser croire qu'un envoi a lieu). **À trancher / consigner.**
2. **« Configurable » sans modèle de préférence.** Aucune table/colonne ne permet aujourd'hui d'activer/
   désactiver un offset ou de choisir des canaux par client/salon. *Recommandation : au MVP, un **jeu
   d'offsets par défaut** (`24h/2h/30min`, constante `REMINDER_OFFSETS`) — « configurable » au sens du
   PRD, sans surface de configuration.* Une vraie configuration (préférences persistées) est une story
   ultérieure. **À confirmer.**
3. **Annuler = marquer `CANCELLED` (recommandé) vs supprimer.** Ajouter `NotificationStatus.CANCELLED`
   **préserve la trace** (§8.4 : « notifications critiques tracées ») d'un rappel qui ne partira jamais,
   au prix d'un **élargissement d'enum + migration `CHECK`**. La suppression évite la migration d'enum
   mais **perd la trace** et efface le lien `appointment_id`. *Recommandation : marquer `CANCELLED`.*
   **À trancher dans l'ADR.**
4. **Quelles transitions annulent les rappels ?** L'AC vise l'**annulation** (`→ CANCELLED`, client #24 +
   refus gérant #25). Faut-il aussi annuler sur `COMPLETED`/`NO_SHOW` ? *Recommandation : non —* leurs
   rappels ont une échéance **déjà passée** et le **worker M5+ ne remet pas un rappel en retard**
   (`scheduled_for <= now` **et** RDV encore actif). Annuler uniquement sur `→ CANCELLED` garde le
   périmètre net. **À confirmer.**
5. **Re-planification sur modification (#23).** Un RDV déplacé (#23) laisse, sans action, des rappels
   pointant l'ancien créneau. *Recommandation : gérer la re-planification dans `ModifyAppointment`
   (annuler + re-planifier), peu coûteux et cohérent.* Alternative : déférer la synchronisation des
   rappels à #48. **À trancher** (impacte la signature de `ModifyAppointment`).
6. **Rappel d'un RDV encore `PENDING` (non confirmé).** Faut-il rappeler un RDV pas encore confirmé par
   le salon ? *Recommandation : planifier dès la réservation (comme la confirmation #45) et laisser le
   **worker M5+ re-vérifier le statut du RDV à l'envoi*** (ne pas rappeler un RDV devenu terminal). Au
   MVP (pas d'envoi), aucune conséquence ; c'est une consigne pour le futur worker. **À confirmer.**
7. **Index « rappels dus ».** Un index partiel `(scheduled_for) WHERE status='PENDING'` aidera la
   requête du worker M5+, mais **aucun consommateur** n'existe au périmètre #46. *Recommandation : ajout
   modéré (bon marché, documente l'intention) ou report jusqu'au worker.* **À trancher.**
8. **Fuseau horaire de `scheduled_for`.** Les RDV sont **naïfs Africa/Abidjan (UTC+0)** (`appointment_date`
   + `start_time`) ; la colonne est `TIMESTAMPTZ`. *Recommandation : composer l'instant de début dans le
   fuseau du salon (convention `SALON_TIMEZONE`, cohérente avec `_now()`/`_today()` de l'adapter) et
   soustraire l'offset — vérifier la parité avec la manière dont #21 borne « passé/futur ».* **À valider
   par test.**
9. **Idempotence / doublons de rappels.** Chaque réservation planifie **son** jeu de rappels ; une
   modification les re-planifie (si §5). Aucune contrainte d'unicité `notifications` n'existe/n'est
   requise. *À confirmer* qu'aucun chemin ne double les rappels d'un même RDV (la re-planification
   **annule d'abord** les `PENDING` existants).
10. **Statut initial `PENDING` (honnête).** Comme #45, `PENDING` + `sent_at = NULL` ; le worker M5+
    passera `SENT`. Ne **pas** marquer `SENT` au MVP (mensonger). **À confirmer.**
11. **Généraliser vs dupliquer la résolution de canal.** *Recommandation : renommer
    `resolve_confirmation_channel → resolve_notification_channel` (alias rétrocompatible) et le réutiliser
    pour le rappel*, plutôt que dupliquer. Impact minime sur les imports #45. **À confirmer.**
12. **ADR dédié.** *Recommandation : oui* — court **ADR-0034** figeant planification/trace + annulation +
    migration + non-remise M5 + périmètre. **À confirmer.**

## Implementation Checklist

1. **Vérifier l'état livré & trancher.** Relire le trio #45 (`domain/notification.py`,
   `application/ports/notification_repository.py`,
   `adapters/outbound/persistence/notification_repository.py`), `BookAppointment`/`CancelAppointment`/
   `SetAppointmentStatus`/`ModifyAppointment` et leurs call sites (`adapters/inbound/appointments.py`),
   `SqlAppointmentRepository.cancel`/`set_status`, `models.Notification`, `domain/enums.py`
   (`NotificationType.REMINDER` **présent**, `NotificationStatus` **sans** `CANCELLED`), la dernière
   migration `0005`. **Trancher** les questions ouvertes 1–12 ; consigner dans un **ADR-0034**.
2. **Migration** : créer `0006_notification_scheduling` (`down_revision = "0005"`) — `add_column
   scheduled_for TIMESTAMPTZ NULL` ; (si §3) `NotificationStatus.CANCELLED` + régénération du `CHECK`
   `status` ; (si §7) index partiel `ix_notifications_due`. Refléter dans `models.py` (+ `enums.py`).
   Vérifier le **round-trip** `upgrade`/`downgrade` sur PostgreSQL 16.
3. **Domaine** : étendre `domain/notification.py` — champ `scheduled_for`, `REMINDER_OFFSETS`,
   `REMINDER_TITLE`/`REMINDER_MESSAGE`, `compute_reminder_schedules`, `build_reminder_notifications`
   (purs, sans PII) ; canal généralisé `resolve_notification_channel`. Étendre
   `tests/test_domain_notification.py`.
4. **Port** : `application/ports/notification_repository.py` — ajouter
   `cancel_pending_for_appointment(appointment_id)`.
5. **Persistance** : `notification_repository.py` — persister `scheduled_for` dans `enqueue` ;
   implémenter `cancel_pending_for_appointment` (UPDATE/DELETE ciblé `appointment_id` + `type='REMINDER'`
   + `status='PENDING'`, `flush`, **sans** log de contenu/destinataire).
6. **Cas d'usage** : `BookAppointment` planifie les rappels (offsets futurs, même `Session`) ;
   `CancelAppointment` et `SetAppointmentStatus` (→`CANCELLED`) reçoivent `NotificationRepository` et
   annulent les rappels ; (si §5) `ModifyAppointment` re-planifie. Étendre `FakeNotificationRepository`
   (`conftest.py`) et `tests/test_appointment_usecases.py` (comptes de rappels, annulation, atomicité,
   non-régression des transitions non concernées).
7. **Adapter entrant** : injecter `get_notification_repository` dans `cancel_appointment`/
   `set_appointment_status`/(`modify_appointment`) ; **aucune** route ajoutée, **rien** dans
   `PUBLIC_ROUTE_PATHS` ; rectifier les docstrings « Aucune notification n'est émise » ; étendre
   `tests/test_appointment_api.py` et vérifier `tests/test_security_guards.py`.
8. **e2e** : étendre `tests/test_appointment_notification_e2e.py` (réservation → 3 rappels `REMINDER`
   `PENDING` datés, liés, sans téléphone ; annulation client / refus gérant → 0 `PENDING` restant ;
   (si §5) modification → rappels re-datés). Exécuter `pytest` (+ `DATABASE_URL`, `alembic upgrade head`)
   et `ruff check`.
9. **Documentation** : section `backend/README.md` ; phrase de statut `README.md` racine (M5) ;
   `docs/adr/0034-rappel-automatique-avant-rdv.md` + index `docs/adr/README.md` ; docstrings OpenAPI
   (`book`/`cancel`/`set_status`) mises à jour.
10. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test **web inchangé** +
    flutter test **mobile inchangé**), `ruff check`, round-trip Alembic vert ; relire la PR pour garantir
    qu'**aucun** numéro, nom, secret ni contenu de message n'apparaît dans les logs ; que les rappels sont
    **planifiés dans la même transaction** que le RDV et **annulés dans la même transaction** que
    l'annulation ; qu'**aucun** rappel n'est planifié pour une échéance déjà passée ; qu'un RDV annulé ne
    laisse **aucun** rappel `PENDING` ; que **rien n'est réellement « envoyé »** (non-remise assumée,
    `PENDING`, `sent_at NULL`, ADR-0006) ; qu'**aucune** route n'a été ajoutée ; et qu'**aucune signature
    IA** n'a été introduite.
