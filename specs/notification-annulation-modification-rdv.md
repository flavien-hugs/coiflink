# Notification d'annulation / modification (US-7.4)

> Spécification de planification pour l'issue GitHub **#48 — US-7.4 : Notification d'annulation /
> modification** (`feature` `notifications` · **Must** · Effort **S** · PRD §6 Épic 7 / §8.4
> « Notifications » / §9.8 « Notification » / §11.2 « Isolation par salon » / §11.3 « Données
> personnelles » / §11.4 « Journalisation » / §12.1 « Latence »).
> **Dépend de #23** (modification RDV client, livré), **#24** (annulation RDV client, livré) et
> **#25** (cycle de statuts gérant, livré). S'appuie **directement** sur le socle de notification
> livré par **#45** (US-7.1, confirmation client), **#46** (US-7.2, rappels) et **#47** (US-7.3,
> notification au salon à la réservation). **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 7, US-7.4 ; §8.4) pose le besoin : **« en tant que client, je veux être notifié en
cas d'annulation ou de modification »**. Le libellé du backlog (#48) précise : *« Notification
automatique après changement de statut ; annulation notifie client + salon (§8.4) »*, et le critère
d'acceptation de l'issue est :

- **Un changement de statut déclenche la notification aux parties concernées.**

Le PRD §8.4 ajoute la règle métier concrète qui structure ce lot : **« Une annulation doit notifier le
client et le salon. »**

### État actuel du dépôt (vérifié pour cette spec)

Le **socle de notification est livré et directement réutilisable** (#45 → #46 → #47) :

1. **Le trio domaine / port / adapter existe** et écrit déjà dans la table `notifications` :
   - `domain/notification.py` — `NotificationToCreate` (dataclass `frozen`, miroir des colonnes de
     `models.Notification`, champ `scheduled_for` inclus), `ChannelAvailability`,
     `resolve_notification_channel` (fonction pure **PUSH → SMS → IN_APP**, `WHATSAPP` exclu V2, alias
     rétrocompatible `resolve_confirmation_channel`), `build_confirmation_notification` (#45),
     `build_reminder_notifications` (#46), `build_salon_new_booking_notification` (#47) et les libellés
     templatés neutres correspondants.
   - `application/ports/notification_repository.py` — `NotificationRepository(Protocol)` avec
     `enqueue(notification) -> None` (écriture) et `cancel_pending_for_appointment(appointment_id) ->
     None` (annulation des rappels, #46).
   - `adapters/outbound/persistence/notification_repository.py` — `SqlNotificationRepository`
     (`session.add(...)` + `flush()`, **sans commit** : atomicité conjointe avec l'écriture métier via
     `get_session`, patron `AuditLog` #20 ; recopie le contenu **déjà neutre**, ne journalise **jamais**
     destinataire ni contenu, ADR-0006).
2. **Les trois cas d'usage concernés portent déjà un `NotificationRepository`** (injecté par #46 pour
   l'annulation des rappels) :
   - `CancelAppointment` (#24) : après le `cancel` réussi, appelle
     `cancel_pending_for_appointment(appointment_id)` (annule les rappels) puis journalise
     `APPOINTMENT_CANCELLED`. **N'émet aucune notification** vers le client ni le salon (docstring
     explicite : « Aucune notification poussée au client n'est émise ici … = US-7.4, #48 »).
   - `SetAppointmentStatus` (#25) : sur `→ CANCELLED` (refus gérant) uniquement, appelle
     `cancel_pending_for_appointment(appointment_id)` ; journalise `APPOINTMENT_STATUS_CHANGED`
     (`{from, to}`). **N'émet aucune notification** aux parties.
   - `ModifyAppointment` (#23) : après l'`update` réussi, **re-planifie** les rappels (annule + recrée)
     et journalise `APPOINTMENT_UPDATED`. Charge déjà le `Salon` via `_load_bookable_salon(...)` —
     **`salon.owner_id` est donc disponible sans accès base supplémentaire**. **N'émet aucune
     notification** vers le salon.
3. **La table `notifications` et l'enum `NotificationType.CANCELLATION` existent déjà.** L'enum
   (`domain/enums.py::NotificationType`) porte **`CONFIRMATION`, `REMINDER`, `CANCELLATION`,
   `NEW_BOOKING`** ; la contrainte `CHECK` de `type` (`ck_notifications_type`, dérivée de l'enum via
   `models.py::enum_check`) inclut **déjà `CANCELLATION`** depuis la migration `0007` (livrée avec #47 :
   `type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION', 'NEW_BOOKING')`). **Écrire une notification
   `CANCELLATION` n'exige donc aucune migration.**
4. **La remise réelle reste différée M5+** (ADR-0006/0030/0033/0034/0035) : **aucun worker de remise,
   aucune file Redis câblée, aucun fournisseur SMS/email concret, aucun ordonnanceur, aucun registre de
   jetons d'appareil.** Le seul adapter « d'envoi » livré est le **stub no-op** d'OTP
   (`otp_sender_stub.py`), qui ne journalise jamais destinataire ni contenu. Le canal effectif d'une
   notification poussée est **SMS** au MVP (faute de registre de jetons, `PUSH` n'est pas ciblable) ; le
   canal « dashboard » du salon est `IN_APP` (#47).

### Le gap structurant que #48 comble

Aujourd'hui, un **changement de statut** de RDV (annulation client #24, refus/confirmation/clôture
gérant #25) et une **modification** (#23) **annulent/re-planifient les rappels** (#46) mais **ne
notifient personne** de l'événement. #48 ajoute la **notification aux parties concernées** au moment du
changement, dans la **même unité de travail** que l'écriture du statut — sans construire aucune remise
réelle (comme #45/#46/#47). Deux constats cadrent la décision :

1. **L'annulation est la seule règle chiffrée du PRD (§8.4).** « Une annulation doit notifier le client
   **et** le salon » : sur **toute** transition `→ CANCELLED` (client #24 **ou** refus gérant #25), il
   faut émettre **deux** notifications — une au **client** (`user_id = appointment.client_id`) et une au
   **salon** (au gérant, `user_id = salon.owner_id`). Le type `CANCELLATION` **existe déjà** (enum +
   `CHECK`, migration `0007`) → **aucune migration** pour ce cœur.
2. **« Un changement de statut déclenche la notification » est plus large que l'annulation.** L'AC vise
   *tout* changement de statut. Au-delà de l'annulation, cela recouvre : le **gérant confirme**
   (`PENDING → CONFIRMED`), **clôture** (`CONFIRMED → COMPLETED`) ou marque **absent** (`… → NO_SHOW`) —
   la partie concernée est alors le **client** ; et la **modification** (#23) par le client — la partie
   concernée est alors le **salon** (l'issue s'intitule « annulation/**modification** »). Ces cas
   n'ont **aucune** valeur de `NotificationType` adaptée : `CONFIRMATION` (#45) est la confirmation de
   *réservation* du client, `NEW_BOOKING` (#47) la *nouvelle réservation* reçue par le salon. Les
   couvrir suppose **une** nouvelle valeur d'enum (recommandé : `APPOINTMENT_UPDATE`) + une migration
   régénérant le `CHECK` `type` — exactement le patron de `0006` (`CANCELLED`) et `0007` (`NEW_BOOKING`).

Comme #45/#46/#47, la **remise proactive** (push/SMS/email) dépend d'une infra **non construite**.
L'interprétation MVP fidèle et livrable, cohérente avec les précédents, est :

> **Notifier les parties concernées en persistant** une ligne `notifications` par destinataire
> (`status = PENDING`, `scheduled_for = NULL`, rattachée au destinataire/salon/RDV) **dans la même unité
> de travail** que le changement de statut. Ces lignes **sont** la trace des notifications critiques
> (§8.4/§11.4) et **la file** que consommera le futur worker pour la remise. L'**émission** satisfait
> l'AC « un changement de statut déclenche la notification aux parties concernées » ; la **remise
> proactive** reste **différée M5+**.

### Découpage recommandé : cœur sans migration + extension avec migration `0008`

Cette spec recommande de livrer les **deux** volets pour honorer pleinement l'AC (« *un* changement de
statut ») et le titre de l'issue (« annulation/**modification** »), tout en isolant clairement un cœur
sans migration :

- **Volet A — cœur, sans migration (règle §8.4 explicite).** Sur toute transition `→ CANCELLED` (client
  #24 + refus gérant #25), émettre **deux** notifications `CANCELLATION` : **client** + **salon**.
- **Volet B — extension, migration `0008` (reste de l'AC).** Sur les **autres** transitions de statut
  gérant (`CONFIRMED`/`COMPLETED`/`NO_SHOW`) notifier le **client** ; sur une **modification** (#23)
  notifier le **salon**. Type dédié `APPOINTMENT_UPDATE`.

*Repli documenté (si l'effort **S** doit rester minimal) : livrer **A seul** (annulation → client +
salon, aucune migration). A satisfait la clause §8.4 nommée mais **pas** la lettre de l'AC (« un
changement de statut », donc aussi confirmation/clôture/modification). À trancher dans l'ADR (voir
Risks §1).*

## Goals

- **Notifier les deux parties à l'annulation, atomiquement (Volet A, §8.4).** Sur toute transition
  `→ CANCELLED` — `CancelAppointment` (#24) et `SetAppointmentStatus` avec `target == CANCELLED` (#25) —
  persister, **après** l'écriture réussie du statut et dans la **même** `Session`, **exactement deux**
  lignes `notifications` `type = CANCELLATION` `status = PENDING` : (a) au **client**
  (`user_id = appointment.client_id`, canal résolu « selon disponibilité » → SMS au MVP) et (b) au
  **salon** (`user_id = salon.owner_id`, `channel = IN_APP`). **Aucune** migration (le type existe).
- **Notifier la partie concernée sur les autres changements de statut & la modification (Volet B).**
  `SetAppointmentStatus` sur `CONFIRMED`/`COMPLETED`/`NO_SHOW` → **une** notification `APPOINTMENT_UPDATE`
  au **client** ; `ModifyAppointment` (#23) → **une** notification `APPOINTMENT_UPDATE` au **salon**
  (`owner_id` déjà chargé). Migration `0008` (valeur d'enum + régénération du `CHECK` `type`).
- **Notification = trace (§8.4/§11.4).** Chaque ligne persistée (type, canal, `status`, `created_at`,
  `sent_at` ultérieur) **constitue** la trace de la notification critique. Elle est **neutre** :
  **aucune PII** (ni nom, ni téléphone) — seulement des identifiants opaques (`user_id`, `salon_id`,
  `appointment_id`) et un `title`/`message` **templaté**. Le motif d'annulation (persisté sur le RDV,
  #24/#25) n'est **jamais** recopié dans la notification.
- **Canaux fidèles aux précédents.** Client : `resolve_notification_channel` (PUSH → SMS → IN_APP ; SMS
  au MVP). Salon : `IN_APP` explicite (canal « dashboard », comme #47) — pas « selon disponibilité ».
- **Atomicité conjointe.** L'émission passe par le port `enqueue` sur la **même** `Session` que
  l'écriture du statut du RDV (`get_session`, commit/rollback conjoint) : un changement de statut
  échoué (verrou terminal, TOCTOU, RDV d'autrui) ne laisse **aucune** notification ; un changement
  réussi ne peut pas exister sans ses notifications.
- **Coexistence avec l'annulation des rappels (#46).** Sur `→ CANCELLED`, `cancel_pending_for_appointment`
  (annulation des rappels `REMINDER`, #46) **et** l'émission des `CANCELLATION` cohabitent : la
  première fait un `UPDATE` ciblé (`type = REMINDER`), la seconde des `INSERT` (`type = CANCELLATION`) —
  aucun recouvrement. Idem sur modification : re-planification des rappels **et** notification salon.
- **Remise différée, assumée et documentée (cohérence #45/#46/#47/#38).** Aucun envoi réel
  (email/SMS/push), **aucun** ordonnanceur. `status = PENDING`, `sent_at = NULL`. Aucun appel réseau
  externe dans le chemin de requête (budget de latence §12.1). **Aucun** secret n'entre au dépôt (#5).
- **Couverture de tests.** Domaine (constructeurs neutres, `type`/`channel`/`status` corrects),
  cas d'usage (nombre & ciblage des notifications par transition ; **aucune** sur écriture échouée ;
  atomicité ; transitions non concernées silencieuses), API (contrats HTTP inchangés), e2e PostgreSQL
  (lignes réelles, contraintes FK `RESTRICT`/`CHECK`, ordre de nettoyage).

## Non-Goals

- **Construire l'infra de remise (worker Redis, ordonnanceur, email/SMS/FCM, registre de jetons).** La
  remise **proactive** dépend d'un worker consommant la file (ADR-0006) + fournisseurs concrets (#5),
  **différés M5+**. #48 **émet/trace** les notifications ; il n'implémente **aucun** envoi réel.
- **Endpoint de lecture des notifications** (`GET /me/notifications` côté client,
  `GET /salons/{salon_id}/notifications` côté salon). Différé — parité #45/#47 (ADR-0033/0035 ont
  reporté la lecture). Le web `/gerant` et le mobile ne sont **pas** modifiés ici.
- **Modéliser des préférences de notification** (activer/désactiver un canal, choisir les destinataires,
  notifier les coiffeurs assignés). Une notification au client + au gérant suffit au MVP.
- **Notifier sur l'(dés)assignation d'un coiffeur (`AssignHairdresser`, #25).** Ce n'est **pas** un
  changement de statut au sens de l'AC ; hors périmètre (évolution ultérieure éventuelle).
- **Enrichir la ligne persistée de détails du RDV** (date/heure/prestation, ancien vs nouveau créneau,
  ancien vs nouveau statut, motif). Comme #45/#46/#47, `title`/`message` restent **minimaux et
  neutres** ; la composition riche est laissée à la **lecture** (future) ou au worker de remise, qui
  peut joindre `appointment_id`/`audit_logs` — **jamais** copiée dans `notifications`.
- **Écran mobile / web spécifique.** Rien n'étant remis au MVP, il n'y a **rien de visible** à afficher.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, **portée salon §11.2** | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Notifications | **FCM + SMS via file Redis**, WhatsApp V2, **remise asynchrone différée** ; stub no-op au MVP | [0006](../docs/adr/0006-notifications-fcm-sms.md) |
| Confirmation (#45) | ligne `notifications` `CONFIRMATION` persistée atomiquement, remise différée | [0033](../docs/adr/0033-notification-confirmation-rdv.md) |
| Rappels (#46) | rappels `REMINDER` datés, statut `CANCELLED`, annulation liée au cycle de vie | [0034](../docs/adr/0034-rappel-automatique-avant-rdv.md) |
| Notification salon (#47) | ligne `NEW_BOOKING`/`IN_APP` au gérant à la réservation, migration `0007` (`CHECK` `type`) | [0035](../docs/adr/0035-notification-salon-a-la-reservation.md) |
| Annulation client (#24) | transition d'état soft, motif optionnel non journalisé | [0025](../docs/adr/0025-annulation-rendez-vous-client.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0035** (#47). L'ajout des notifications d'annulation/
modification (émission + éventuelle valeur d'enum `APPOINTMENT_UPDATE`) justifie un **court ADR-0036**
« Notification d'annulation/modification — émission atomique aux parties concernées, `CANCELLATION`
réutilisé (client + salon), type `APPOINTMENT_UPDATE` pour les autres changements de statut & la
modification, remise différée M5 » (voir *Documentation Updates*).

### Patrons à réutiliser tels quels

- **Trio domaine / port / adapter de notification (#45/#46/#47)** — gabarit direct pour les nouveaux
  constructeurs (`build_client_cancellation_notification`, `build_salon_cancellation_notification`, et,
  Volet B, `build_client_status_update_notification` / `build_salon_modification_notification`). Le port
  `enqueue` et l'adapter `SqlNotificationRepository.enqueue` **suffisent tels quels** : chaque
  notification est une `NotificationToCreate` de plus. **Aucune** nouvelle méthode d'écriture.
- **Écriture métier + effet transverse dans la même `Session`** — les trois cas d'usage émettent déjà
  des effets transverses sur la **même** `Session` (audit §11.4, annulation/planification des rappels
  #46). **Modèle direct** : ajouter l'émission des notifications au même endroit, après l'écriture du
  statut, avant/après l'audit.
- **Résolution du gérant (`salon.owner_id`)** — `ModifyAppointment` charge déjà le `Salon`
  (`_load_bookable_salon`), donc `owner_id` est **gratuit**. `CancelAppointment` et
  `SetAppointmentStatus` ne chargent **pas** le salon : ils doivent résoudre `owner_id` via le **port**
  `SalonRepository.find_by_id(salon_id) -> Salon | None`
  (`application/ports/salon_repository.py`, implémenté par `SqlSalonRepository.find_by_id` — un `get`
  par clé primaire **indépendant du statut**, indispensable car une annulation reste possible même sur
  un salon devenu inactif, §8.3). C'est le point d'attention d'implémentation principal (voir Risks §3).
- **Migration Alembic chaînée + `CHECK` dérivé de l'enum (Volet B)** — dernière révision livrée
  `0007_notification_new_booking_type` (`down_revision = "0006"`) ; #48 ajoute (Volet B seulement)
  `0008_notification_appointment_update_type` (`down_revision = "0007"`). Ajouter
  `NotificationType.APPOINTMENT_UPDATE` suppose de **régénérer** `ck_notifications_type` (drop + recreate
  incluant les 5 valeurs) — **exactement** le patron de `0006`/`0007`.
- **Injection surchargeable en test** — providers `get_*_repository(session)` +
  `app.dependency_overrides` ; `FakeNotificationRepository` (`tests/conftest.py`) accumule `enqueued`
  (liste de `NotificationToCreate`) et enregistre `cancel_calls` — à **réutiliser tel quel** pour
  vérifier l'émission (filtrer `enqueued` par `type`) ; e2e adossés à un vrai PostgreSQL, sautés si
  `DATABASE_URL` absent ; garde deny-by-default (`tests/test_security_guards.py::unprotected_routes`).

### Schéma déjà en place (source de vérité : `models.py`, migrations `0001` + `0006` + `0007`)

- `notifications` : `user_id`/`salon_id`/`appointment_id` **nullable** (FK `RESTRICT`), `type`
  (`CHECK` = `NotificationType` — **`CANCELLATION` présent** ; `APPOINTMENT_UPDATE` **absent**),
  `channel` (`CHECK` = `NotificationChannel`, **`SMS`/`IN_APP` présents**), `title`/`message`
  (**NOT NULL**), `status` (défaut `PENDING`, `CHECK` = `NotificationStatus`), `sent_at` (nullable),
  `scheduled_for` (nullable, #46), `created_at`. Index `ix_notifications_user_id`,
  `ix_notifications_salon_id (salon_id, created_at)`.
- `appointments` : `client_id`, `salon_id`, `hairdresser_id`, `appointment_date`, `start_time`,
  `status`, `cancellation_reason` (#24/#25). Le read-model `domain/appointment.py::Appointment` porte
  `client_id` et `salon_id` — le **client** à notifier est donc résoluble sans accès base.
- `salons` : `owner_id` (FK `users.id`, non nullable) — **le gérant du salon** ; exposé sur
  `domain/salon.py::Salon.owner_id`, chargé par `ModifyAppointment` (gratuit) et résoluble par
  `SalonRepository.find_by_id` (Cancel/SetStatus).

### Contraintes transverses documentées

- **PRD §8.4** : une **annulation doit notifier le client et le salon** ; **notifications critiques
  tracées**. (#48 le matérialise pour l'annulation ; l'AC élargit à tout changement de statut.)
- **PRD §11.3 / §11.4 / ADR-0006** : collecte minimale, **non-fuite de PII**, **ne jamais journaliser**
  corps de message / numéros / motif ; **clés email/SMS/FCM hors dépôt** (#5) ; trace des actions
  critiques.
- **PRD §11.2 / ADR-0015** : isolation par salon — le `user_id` du destinataire est **imposé serveur**
  (`appointment.client_id` / `salon.owner_id`), jamais soumis.
- **PRD §12.1** : réponse API < 3 s → la remise réelle (et l'ordonnancement) restent **hors** chemin
  requête. #48 n'ajoute qu'un petit nombre d'`INSERT` locaux (+ **un** `get` par clé primaire du salon
  pour Cancel/SetStatus).
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test).

## Proposed Implementation

Approche recommandée : **les notifications d'annulation/modification sont des lignes `notifications`
émises dans la même unité de travail que le changement de statut, aux parties concernées ; canal client
résolu (SMS), canal salon `IN_APP` ; remise réelle différée (aucun envoi, aucun ordonnanceur).** Le
Volet A (annulation) ne requiert **aucune** migration ; le Volet B (autres changements + modification)
ajoute la migration `0008`.

### (A) Data model — migration `0008_notification_appointment_update_type` (Volet B uniquement)

*Le Volet A (annulation) n'exige **aucune** migration : `NotificationType.CANCELLATION` et son `CHECK`
existent depuis `0007`.* La migration `0008` n'est nécessaire **que** si le Volet B est retenu.

- **Valeur d'enum** : ajouter `NotificationType.APPOINTMENT_UPDATE = "APPOINTMENT_UPDATE"`
  (`domain/enums.py`). Le modèle `models.Notification` dérive son `CHECK` de l'enum
  (`enum_check("type", enums.NotificationType, name="type")`) — aucune autre modification de `models.py`.
- **Régénération du `CHECK` `type`** dans la migration :
  `op.drop_constraint(op.f("ck_notifications_type"), "notifications", type_="check")` puis
  `op.create_check_constraint("type", "notifications", "type IN ('CONFIRMATION', 'REMINDER',
  'CANCELLATION', 'NEW_BOOKING', 'APPOINTMENT_UPDATE')")`. `downgrade()` symétrique (recreate sans
  `APPOINTMENT_UPDATE`). **Aucun backfill** ; `"APPOINTMENT_UPDATE"` (18 car.) tient dans
  `type String(32)`. **Aucune** nouvelle colonne, **aucun** nouvel index.
- Round-trip Alembic (`upgrade`/`downgrade` `0008`) vérifié en CI (`backend` job, PostgreSQL 16).

> **Nommage à confirmer (mineur)** : `APPOINTMENT_UPDATE` (recommandé, générique — couvre confirmation/
> clôture/absence côté client **et** modification côté salon) vs deux valeurs distinctes
> `STATUS_CHANGED` + `MODIFICATION`. Le générique tient l'effort **S** (une seule migration) et reste
> honnête (le détail from/to n'est **pas** stocké §11.3 — il vit dans `audit_logs` et sur le RDV,
> résolus à la lecture/remise). **À trancher** (voir Risks §2).

### (B) Backend — domaine : constructeurs neutres (`domain/notification.py`, étendre)

- **Libellés templatés neutres (aucune PII)** :
  - `CANCELLATION_TITLE` / `CANCELLATION_MESSAGE` (client), p. ex. `"Rendez-vous annulé"` /
    `"Votre rendez-vous a été annulé."`
  - `SALON_CANCELLATION_TITLE` / `SALON_CANCELLATION_MESSAGE` (salon), p. ex. `"Rendez-vous annulé"` /
    `"Un rendez-vous de votre salon a été annulé."`
  - *(Volet B)* `STATUS_UPDATE_TITLE` / `STATUS_UPDATE_MESSAGE` (client), p. ex.
    `"Rendez-vous mis à jour"` / `"Le statut de votre rendez-vous a été mis à jour."` ;
    `SALON_MODIFICATION_TITLE` / `SALON_MODIFICATION_MESSAGE` (salon), p. ex.
    `"Rendez-vous modifié"` / `"Un rendez-vous de votre salon a été modifié."`
  - **Aucune** de ces chaînes ne porte de date/heure/prestation/nom/téléphone ni le **motif**.
- **Constructeurs** (gabarit direct : `build_confirmation_notification` /
  `build_salon_new_booking_notification`) :
  - `build_client_cancellation_notification(*, client_id, salon_id, appointment_id, channel) ->
    NotificationToCreate` — `type = CANCELLATION`, `user_id = client_id`, `status = PENDING`,
    `scheduled_for = None`.
  - `build_salon_cancellation_notification(*, owner_id, salon_id, appointment_id, channel) ->
    NotificationToCreate` — `type = CANCELLATION`, `user_id = owner_id`.
  - *(Volet B)* `build_client_status_update_notification(*, client_id, salon_id, appointment_id,
    channel)` — `type = APPOINTMENT_UPDATE`, `user_id = client_id`.
  - *(Volet B)* `build_salon_modification_notification(*, owner_id, salon_id, appointment_id, channel)` —
    `type = APPOINTMENT_UPDATE`, `user_id = owner_id`.
  - Aucun `raise` (données déjà validées par le changement de statut). Exporter dans `__all__`.
- **Canal** : le canal **client** est celui résolu par `resolve_notification_channel`
  (`ChannelAvailability(has_push_token=False, has_phone=True)` → SMS au MVP, comme #45/#46). Le canal
  **salon** est `NotificationChannel.IN_APP.value` (explicite, comme #47).

### (C) Backend — port & adapter (aucune nouvelle méthode)

- Le port `NotificationRepository.enqueue(notification)` et `SqlNotificationRepository.enqueue(...)`
  **couvrent déjà** l'insertion : chaque notification d'annulation/modification est une
  `NotificationToCreate` de plus. **Aucune** modification du port ni de l'adapter d'écriture.
- `cancel_pending_for_appointment` (#46) reste inchangé (il cible `type = REMINDER`, jamais
  `CANCELLATION`/`APPOINTMENT_UPDATE`).

### (D) Backend — cas d'usage

#### `CancelAppointment` (#24) — Volet A

- **Nouvelle dépendance** : `SalonRepository` (port `application/ports/salon_repository.py`) pour
  résoudre `salon.owner_id` (le salon n'est pas chargé aujourd'hui). Charger le salon **après** le
  `cancel` réussi via `find_by_id(current.salon_id)` — il **existe toujours** (FK RESTRICT ; un RDV
  référence un salon), indépendamment de son statut (§8.3). Si, par prudence, `find_by_id` renvoie
  `None`, **ne pas** faire échouer l'annulation : ne pas émettre la notification salon (cas
  théoriquement impossible — à décider, Risks §3).
- Après `cancel(...)`, l'appel existant `cancel_pending_for_appointment(...)` (rappels #46) et **avant/
  après** l'audit, émettre **deux** notifications dans la **même** `Session` :
  ```python
  channel = resolve_notification_channel(
      ChannelAvailability(has_push_token=False, has_phone=True)
  )
  self._notifications.enqueue(
      build_client_cancellation_notification(
          client_id=client_id,
          salon_id=current.salon_id,
          appointment_id=appointment_id,
          channel=channel,
      )
  )
  self._notifications.enqueue(
      build_salon_cancellation_notification(
          owner_id=salon.owner_id,
          salon_id=current.salon_id,
          appointment_id=appointment_id,
          channel=NotificationChannel.IN_APP.value,
      )
  )
  ```
- Un RDV non annulable (`AppointmentNotCancellable`) n'atteint jamais ce point → **aucune** notification.

#### `SetAppointmentStatus` (#25) — Volets A & B

- **Nouvelle dépendance** : `SalonRepository` (résolution `owner_id`, comme Cancel).
- Après `set_status(...)` réussi :
  - Si `target_status == CANCELLED` (**Volet A**, refus gérant) : comme Cancel — émettre **deux**
    `CANCELLATION` (client + salon). L'appel existant `cancel_pending_for_appointment(...)` (rappels
    #46) reste.
  - Sinon (**Volet B** : `CONFIRMED`/`COMPLETED`/`NO_SHOW`) : émettre **une**
    `APPOINTMENT_UPDATE` au **client** (`build_client_status_update_notification`). *(Recommandation :
    couvrir les trois ; a minima `CONFIRMED`. À trancher, Risks §4.)*
- Résoudre `owner_id` via `find_by_id(salon_id)` **uniquement** dans les branches qui notifient le salon
  (annulation) — inutile pour les transitions notifiant seulement le client.

#### `ModifyAppointment` (#23) — Volet B

- **Aucune** nouvelle dépendance : le `Salon` est déjà chargé (`salon.owner_id` disponible). Après
  l'`update` réussi et la re-planification des rappels (#46), émettre **une** `APPOINTMENT_UPDATE` au
  **salon** (`build_salon_modification_notification(owner_id=salon.owner_id, ...)`, `channel = IN_APP`),
  même `Session`. *(Recommandation : ne notifier que le salon — le client est l'auteur et connaît déjà
  le changement. Notifier aussi le client en accusé est une option, Risks §5.)*

#### `AssignHairdresser` (#25)

- **Aucune** notification (hors périmètre — pas un changement de statut).

### (E) Backend — câblage de l'adapter entrant (`adapters/inbound/appointments.py`)

- **`cancel_appointment`** et **`set_appointment_status`** : injecter le provider
  `get_salon_repository(session)` (à ajouter s'il n'existe pas — il renvoie `SqlSalonRepository(session)`
  sur la **même** `Session`, patron `get_notification_repository`) et le passer aux cas d'usage
  correspondants (signatures mises à jour).
- **`modify_appointment`** : aucune dépendance ajoutée (le catalogue fournit déjà le salon via le cas
  d'usage).
- **Mettre à jour les docstrings OpenAPI** : rectifier la mention actuelle de `cancel_appointment`
  (« Aucune notification poussée au client n'est émise ici … = US-7.4, #48 ») en « le client **et** le
  salon sont notifiés de l'annulation (émission/trace §8.4, US-7.4 #48) » ; ajouter à
  `set_appointment_status` (« chaque changement de statut notifie la partie concernée ») et à
  `modify_appointment` (« le salon est notifié de la modification »). **Aucun** contrat HTTP ne change.
- **Aucune** route ajoutée, **rien** dans `PUBLIC_ROUTE_PATHS`.

### (F) Backend — (différé, hors périmètre) remise proactive & lecture

Le **worker M5+** (Épic 7, ADR-0006) interrogera les lignes `CANCELLATION`/`APPOINTMENT_UPDATE`
`PENDING` et remettra push/SMS (client) / email/SMS (salon), puis passera `SENT` + `sent_at`. Les
**endpoints de lecture** (`GET /me/notifications`, `GET /salons/{salon_id}/notifications`) restent
différés (parité #45/#47). **#48 ne construit ni l'un ni l'autre** — cohérent avec les précédents ;
aucun point d'accroche mort n'est ajouté.

### (G) Trace §8.4/§11.4 — la ligne `notifications` est la trace

Comme #45/#46/#47, la **ligne persistée** (type, canal, statut, `created_at`, `sent_at` ultérieur)
**est** la trace exigée. **Recommandation** : ne pas ajouter de double trace `audit_logs` — l'audit du
**changement de statut** (`APPOINTMENT_CANCELLED`/`APPOINTMENT_STATUS_CHANGED`/`APPOINTMENT_UPDATED`)
existe déjà (#24/#25/#23) et porte le `{from, to}`/diff neutre. Aucune action ajoutée à `AuditAction`.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `migrations/versions/0008_notification_appointment_update_type.py` | **nouveau (Volet B)** — `NotificationType.APPOINTMENT_UPDATE` : drop + recreate du `CHECK` `ck_notifications_type` (up/down symétriques) |
| `coiflink_api/domain/enums.py` | **(Volet B) modifier** — `NotificationType.APPOINTMENT_UPDATE` |
| `coiflink_api/domain/notification.py` | **modifier** — libellés `CANCELLATION_*`/`SALON_CANCELLATION_*` (Volet A) et `STATUS_UPDATE_*`/`SALON_MODIFICATION_*` (Volet B) ; `build_client_cancellation_notification`, `build_salon_cancellation_notification` (A) + `build_client_status_update_notification`, `build_salon_modification_notification` (B) ; export `__all__` |
| `coiflink_api/application/appointments.py` | **modifier** — `CancelAppointment` (dépendance `SalonRepository` + 2 `CANCELLATION`) ; `SetAppointmentStatus` (dépendance `SalonRepository` + notifications par transition) ; `ModifyAppointment` (1 `APPOINTMENT_UPDATE` salon) ; docstrings mises à jour |
| `coiflink_api/adapters/inbound/appointments.py` | **modifier** — provider `get_salon_repository` (si absent) ; injection dans `cancel_appointment`/`set_appointment_status` ; docstrings OpenAPI rectifiées (`cancel`/`set_status`/`modify`) |
| `coiflink_api/application/ports/salon_repository.py` | **lire** — `find_by_id` déjà présent (aucune modification attendue) |
| `backend/README.md` | section « Notifications (annulation/modification de RDV) » : émission atomique aux parties concernées, canaux, non-remise (M5), migration `0008` (Volet B) |

### Backend — tests

| Fichier | Contenu |
| --- | --- |
| `tests/test_notification_domain.py` | **étendre** — chaque constructeur : `type`/`channel`/`status`/`scheduled_for` corrects, `user_id` = bon destinataire, `salon_id`/`appointment_id` liés, `title`/`message` **non vides & sans PII** (n'accepte aucune donnée PII en entrée) |
| `tests/test_appointment_usecases.py` | **étendre** — `CancelAppointment` émet **2** `CANCELLATION` (client `client_id` + salon `owner_id`) **en plus** de l'annulation des rappels (#46) ; RDV non annulable → **0** ; `SetAppointmentStatus` → **2** `CANCELLATION` sur `→ CANCELLED`, **1** `APPOINTMENT_UPDATE` client sur `CONFIRMED`/`COMPLETED`/`NO_SHOW` ; `ModifyAppointment` → **1** `APPOINTMENT_UPDATE` salon ; atomicité (même `Session`/fake) ; écriture échouée → **0** notification |
| `tests/test_appointment_api.py` | **étendre** — `POST .../cancellation`, `POST .../status`, `PATCH /appointments/{id}` → réponses **inchangées** + notifications enregistrées (assertion fake) ; un échec (`404`/`409`/`422`) n'enregistre **aucune** notification |
| `tests/test_security_guards.py` | **vérifier** — aucune route ajoutée, `PUBLIC_ROUTE_PATHS` inchangé, matrice RBAC inchangée |
| `tests/test_appointment_notification_e2e.py` | **étendre** (PostgreSQL réel) — annulation client / refus gérant → **2** lignes `type=CANCELLATION` `status=PENDING` (`user_id` client + owner, `channel` SMS/IN_APP), `sent_at IS NULL`, **sans** PII, en plus des rappels `CANCELLED` ; confirmation/clôture → **1** `APPOINTMENT_UPDATE` client ; modification → **1** `APPOINTMENT_UPDATE` salon ; écriture échouée → **0** ; nettoyage `notifications` **avant** `appointments`/`users`/`salons` (FK `RESTRICT`) |
| `tests/conftest.py` | **réutiliser** `FakeNotificationRepository` (`enqueued`) ; ajouter un **fake `SalonRepository`** (ou réutiliser un existant) renvoyant un `Salon` avec `owner_id` connu, et le brancher dans les fixtures de `CancelAppointment`/`SetAppointmentStatus` |

### Backend — à lire (sans modifier)

`adapters/outbound/persistence/appointment_repository.py` (`cancel`/`set_status`, atomicité),
`adapters/outbound/persistence/salon_repository.py` (`find_by_id`, indépendant du statut),
`adapters/outbound/persistence/session.py` (`get_session`, commit par requête),
`adapters/outbound/persistence/notification_repository.py` (adapter `enqueue`),
`domain/salon.py` (`Salon.owner_id`), `domain/appointment.py` (`Appointment.client_id`/`salon_id`),
migration `0007` (gabarit de régénération de `CHECK`), `otp_sender_stub.py` (non-journalisation).

### Documentation (racine)

`README.md` (§6 : phrase de statut « M5 : notification d'annulation/modification (US-7.4, #48) »),
nouvel ADR `docs/adr/0036-notification-annulation-modification.md` + index `docs/adr/README.md`.

### Mobile (`app-mobile/`)

**Aucun** changement (rien n'est remis ni lu au MVP).

## API / Interface Changes

- **`POST /appointments/{appointment_id}/cancellation`** (#24) — enrichit son **comportement interne** :
  émet désormais **deux** notifications `CANCELLATION` (client + salon). **Contrat inchangé** :
  `200 AppointmentResponse`, mêmes statuts d'erreur.
- **`POST /salons/{salon_id}/appointments/{appointment_id}/status`** (#25) — émet désormais des
  notifications (2 `CANCELLATION` sur `→ CANCELLED` ; 1 `APPOINTMENT_UPDATE` client sinon).
  **Contrat inchangé** : `200 AppointmentResponse`.
- **`PATCH /appointments/{appointment_id}`** (#23) — émet désormais **une** notification
  `APPOINTMENT_UPDATE` au salon. **Contrat inchangé** : `200 AppointmentResponse`.
- **CLI / interfaces web/mobile** : aucun changement.
- **Nouvelle variable d'environnement** : **aucune** au MVP (la remise email/SMS/push et l'ordonnanceur,
  avec leurs secrets, en auront — différés M5+, #5).
- **Nouvel endpoint** : **aucun** (lecture différée, parité #45/#47).

## Data Model / Protocol Changes

- **Volet A (annulation) : aucune migration.** `NotificationType.CANCELLATION` et son `CHECK`
  (`ck_notifications_type`) existent depuis `0007` ; `NotificationChannel.SMS`/`IN_APP` et
  `NotificationStatus.PENDING` existent. Écrire des lignes `CANCELLATION` n'exige aucun changement de
  schéma.
- **Volet B (autres changements + modification) : migration `0008_notification_appointment_update_type`.**
  Nouvelle valeur d'enum `NotificationType.APPOINTMENT_UPDATE` → **régénération** de `ck_notifications_type`
  (`drop_constraint` + `create_check_constraint` avec les 5 valeurs). **Aucun backfill**, **aucune**
  nouvelle colonne, **aucun** nouvel index. Round-trip Alembic (`upgrade`/`downgrade`) vérifié en CI.
- **Sérialisation** : chaque notification ne stocke **aucun montant**, **aucun** motif, **aucune** PII
  ni `scheduled_for` (`NULL`) — seulement des identifiants opaques et un `title`/`message` templaté. Le
  `user_id` est celui du **destinataire** (client **ou** gérant).

## Security & Privacy Considerations

- **Non-fuite de PII (§11.3, ADR-0006).** Chaque ligne ne stocke **que** des identifiants opaques
  (`user_id`, `salon_id`, `appointment_id`) et un `title`/`message` **templaté neutre** — **jamais** le
  nom/téléphone d'une partie, ni le **motif** d'annulation (persisté sur le RDV #24/#25, **jamais**
  recopié). Le worker de remise (futur) résoudra `user_id → users.email/phone` **à l'envoi** ; ces
  valeurs ne sont **jamais** copiées.
- **Non-journalisation du contenu (ADR-0006).** L'adapter `enqueue` et les cas d'usage n'émettent
  **aucun** `logger`/`print` du destinataire, du canal ni du corps. Le stub OTP n'est pas sollicité.
- **Isolation par salon (§11.2, ADR-0015).** Le `user_id` de chaque notification est **imposé serveur**
  (`appointment.client_id` / `salon.owner_id`, jamais soumis). Le `salon_id` vient du RDV chargé (Cancel)
  ou du chemin (SetStatus, portée validée) ; `owner_id` est résolu par `find_by_id` sur ce `salon_id`.
  Aucune route ajoutée → deny-by-default intact, matrice RBAC inchangée.
- **Atomicité (§11.4).** L'émission se fait dans la **même** `Session` que l'écriture du statut
  (`get_session`, commit/rollback conjoint) : pas de notification « fantôme » sur un changement échoué
  (verrou terminal, TOCTOU, RDV d'autrui), pas de changement de statut sans ses notifications.
- **Remise différée = aucune exposition externe.** Aucun appel email/SMS/FCM, aucun ordonnanceur : rien
  n'est transmis à un tiers. **Clés/identifiants restent hors dépôt** (#5) — #48 n'en introduit aucun.
- **Budget de latence (§12.1).** L'émission ajoute quelques `INSERT` locaux (+ **un** `get` par clé
  primaire du salon pour Cancel/SetStatus) — **aucun** I/O réseau externe. Les routes restent bien sous
  3 s.

Le dépôt **documente** ces contraintes (PRD §8.4/§11.2/§11.3/§11.4/§12.1, ADR-0006/0025/0033/0034/0035) :
#48 les respecte sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires domaine (`pytest`, sans I/O)

- **`tests/test_notification_domain.py`** (étendre) : pour chaque constructeur
  (`build_client_cancellation_notification`, `build_salon_cancellation_notification`, et, Volet B,
  `build_client_status_update_notification`, `build_salon_modification_notification`) →
  `type`/`channel`/`status == PENDING`, `scheduled_for is None`, `user_id` = bon destinataire,
  `salon_id`/`appointment_id` rattachés, `title`/`message` **non vides & sans PII** (aucun numéro ni
  nom — les constructeurs n'acceptent d'ailleurs aucune de ces données).

### Backend — cas d'usage (`pytest`, fakes de `conftest.py`)

- **`tests/test_appointment_usecases.py`** (étendre), `FakeNotificationRepository` + fake
  `SalonRepository` :
  - **annulation client (succès)** : `enqueued` contient **2** `CANCELLATION` (`user_id` = `client_id`
    puis `owner_id`), en plus de l'`UPDATE` des rappels (`cancel_calls` = 1, #46).
  - **annulation impossible** (`AppointmentNotCancellable`) → **aucune** notification, aucun
    `cancel_calls`.
  - **refus gérant** (`SetAppointmentStatus` `→ CANCELLED`) → **2** `CANCELLATION` (client + salon).
  - **confirmation/clôture/absence** (`→ CONFIRMED`/`COMPLETED`/`NO_SHOW`) → **1** `APPOINTMENT_UPDATE`
    client ; **aucune** `CANCELLATION`, **aucun** `cancel_calls`.
  - **modification** (`ModifyAppointment`) → **1** `APPOINTMENT_UPDATE` salon (`user_id = owner_id`).
  - **atomicité** : toutes les émissions passent par le **même** port/`Session` (via le fake) ; une
    écriture de statut échouée (`InvalidAppointmentTransition`, `AppointmentNotFound`) → **0** émission.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_appointment_api.py`** (étendre) : `POST .../cancellation`, `POST .../status`,
  `PATCH /appointments/{id}` → réponses `200` **inchangées** + notifications enregistrées (assertions
  fake) ; un échec (`404`/`409`/`422`) n'enregistre **aucune** notification.
- **`tests/test_security_guards.py`** : `unprotected_routes(app)` **inchangé** ; aucun chemin
  notification dans `PUBLIC_ROUTE_PATHS` ; matrice RBAC figée.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_appointment_notification_e2e.py`** (étendre, patron existant #45/#46/#47 — plage de
  numéros réservée, nettoyage avant/après ; `notifications` supprimé **avant**
  `appointments`/`users`/`salons`, FK `RESTRICT`) :
  1. **annulation client** (`POST .../cancellation`) → **2** lignes `type=CANCELLATION` `status=PENDING`,
     l'une `user_id = client`/`channel = SMS`, l'autre `user_id = owner`/`channel = IN_APP`,
     `sent_at IS NULL`, `scheduled_for IS NULL`, **sans** PII ; les rappels `REMINDER` passent
     `CANCELLED` (#46, inchangé).
  2. **refus gérant** (`POST .../status` `CANCELLED`) → idem (2 `CANCELLATION`).
  3. **confirmation gérant** (`POST .../status` `CONFIRMED`) → **1** `APPOINTMENT_UPDATE` client,
     `sent_at IS NULL` (Volet B).
  4. **modification** (`PATCH /appointments/{id}`) → **1** `APPOINTMENT_UPDATE` salon (`user_id = owner`,
     `channel = IN_APP`) en plus des rappels re-datés (Volet B).
  5. un changement **refusé** (transition interdite `409`, RDV d'autrui `404`) → **aucune** notification
     (rollback conjoint).
  6. les lignes respectent les contraintes réelles (FK `RESTRICT`, `CHECK` `type` **incluant**
     `CANCELLATION` et, Volet B, `APPOINTMENT_UPDATE`, `CHECK` `channel`/`status`).

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test **web inchangé** + flutter test **mobile inchangé**) au vert ;
`ruff check` propre ; **round-trip Alembic** (`0008` si Volet B) vert ; aucune régression sur l'annulation
(#24), le cycle gérant (#25), la modification (#23), la confirmation (#45), les rappels (#46) ni la
notification salon (#47). Les changements de signature de `CancelAppointment`/`SetAppointmentStatus`
(dépendance `SalonRepository`) sont répercutés partout (call sites `adapters/inbound/appointments.py` +
fixtures `conftest.py`).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Notifications (annulation/modification de RDV) » : sur
  **toute** annulation (client #24 ou refus gérant #25), **deux** notifications `CANCELLATION` sont
  **émises/tracées** (client + gérant `salon.owner_id`) dans la même transaction que le changement de
  statut ; les autres changements de statut (`CONFIRMED`/`COMPLETED`/`NO_SHOW`) notifient le **client**,
  et une **modification** (#23) notifie le **salon**, via `APPOINTMENT_UPDATE` (migration `0008`) ; la
  **remise proactive** (push/SMS/email) reste **différée M5+** (ADR-0006) — rien n'est envoyé, `sent_at`
  reste `NULL`. Préciser : canal client SMS, canal salon `IN_APP`.
- **`README.md`** (racine) — §6 : phrase de statut « **M5** : notification d'annulation/modification
  (US-7.4, #48) — un changement de statut émet/trace des notifications aux parties concernées
  (annulation → client + salon, `CANCELLATION` ; autres changements & modification → `APPOINTMENT_UPDATE`)
  dans `notifications`, même unité de travail que le changement ; **remise proactive différée**
  (ADR-0006) », dans le style existant.
- **`docs/adr/0036-notification-annulation-modification.md`** (**nouvel ADR**) : figer (a) l'émission
  atomique aux parties concernées ; (b) **`CANCELLATION` réutilisé** (client + salon) → **aucune**
  migration pour l'annulation ; (c) le type **`APPOINTMENT_UPDATE`** (migration `0008`) pour les autres
  changements de statut & la modification, **ou** son report (repli Volet A seul) ; (d) la résolution du
  gérant via `SalonRepository.find_by_id` (indépendante du statut) ; (e) le périmètre (pas
  d'`AssignHairdresser`, pas de lecture, remise différée). Mettre à jour `docs/adr/README.md`.
- **OpenAPI** — docstrings de `cancel_appointment` (rectifier la mention « aucune notification … #48 »),
  `set_appointment_status` et `modify_appointment` (mention des notifications émises).

## Risks and Open Questions

1. **Portée : Volet A seul (annulation, sans migration) vs A + B (tout changement de statut +
   modification, migration `0008`).** L'AC dit « **un** changement de statut déclenche la notification » ;
   §8.4 ne chiffre que l'annulation. *Recommandation : livrer A + B* pour honorer la lettre de l'AC et le
   titre « annulation/**modification** », en isolant A (sans migration) comme cœur. Repli acceptable si
   l'effort **S** doit rester minimal : **A seul** (annulation → client + salon), en documentant que
   confirmation/clôture/modification sont différées. **À trancher et consigner dans l'ADR-0036.**
2. **Taxonomie du type (Volet B) : générique `APPOINTMENT_UPDATE` vs `STATUS_CHANGED` + `MODIFICATION`.**
   *Recommandation : un seul type générique `APPOINTMENT_UPDATE`* (une migration, effort **S**) — le
   détail from/to n'est pas stocké (§11.3), il vit dans `audit_logs`/sur le RDV. Alternative plus fine
   (deux valeurs) si l'on veut distinguer côté remise sans jointure. **À confirmer.**
3. **Résolution du gérant (`owner_id`) dans Cancel/SetStatus.** Ces cas d'usage ne chargent pas le
   salon ; #48 ajoute une dépendance `SalonRepository.find_by_id(salon_id)` (un `get` par clé primaire,
   **indépendant du statut** — indispensable car l'annulation reste possible sur un salon inactif §8.3).
   *Recommandation : cibler `user_id = salon.owner_id` (parité #47).* Alternative envisagée et **écartée**
   : `user_id = NULL` + `salon_id` seul (notification salon-scopée sans destinataire) — diverge de #47 et
   complique la future remise. Décider le comportement si `find_by_id` renvoie `None` (théoriquement
   impossible) : **ne pas** faire échouer l'annulation. **À confirmer.**
4. **Quelles transitions gérant notifient le client (Volet B) ?** `CONFIRMED` est clairement utile
   (« votre RDV est confirmé »). `COMPLETED`/`NO_SHOW` le sont moins (RDV déjà passé). *Recommandation :
   notifier sur les trois pour une règle uniforme « tout changement de statut notifie » ; a minima
   `CONFIRMED`.* **À confirmer.**
5. **Modification (#23) : notifier le salon seul (recommandé) ou aussi le client ?** Le client est
   l'auteur et connaît déjà le changement. *Recommandation : salon seul.* Notifier aussi le client en
   accusé de réception est une option (2 lignes au lieu d'1). **À confirmer.**
6. **Notifier l'initiateur d'une annulation ?** §8.4 dit « client **et** salon », sans exception pour
   l'initiateur. Sur une annulation client, le client reçoit donc un **accusé** ; sur un refus gérant, le
   salon (owner) reçoit une ligne pour un acte qu'il a initié (potentiellement redondant, mais fidèle à
   §8.4). *Recommandation : suivre §8.4 (les deux), sans cas particulier.* **À confirmer (mineur).**
7. **Statut initial `PENDING` (honnête).** Comme #45/#46/#47, `PENDING` + `sent_at = NULL` ; le worker
   M5+ passera `SENT`. Ne **pas** marquer `SENT` au MVP (mensonger). **À confirmer.**
8. **Une notification par partie par événement.** Vérifier par test qu'aucun chemin ne double une
   notification (p. ex. Cancel émet exactement 2 lignes, pas 2 par prestation ni par rappel).
9. **ADR dédié.** *Recommandation : oui* — court **ADR-0036** figeant émission/trace + réutilisation
   `CANCELLATION` + type `APPOINTMENT_UPDATE` (ou report) + résolution `owner_id` + périmètre + non-remise.
   **À confirmer.**

## Implementation Checklist

1. **Vérifier l'état livré & trancher.** Relire le trio notification (#45/#46/#47 :
   `domain/notification.py`, `application/ports/notification_repository.py`,
   `adapters/outbound/persistence/notification_repository.py`), les cas d'usage `CancelAppointment` /
   `SetAppointmentStatus` / `ModifyAppointment` et leurs call sites
   (`adapters/inbound/appointments.py`), `domain/enums.py` (`NotificationType.CANCELLATION` **présent**,
   `CHECK` `type` incluant déjà `CANCELLATION` via `0007`), `application/ports/salon_repository.py`
   (`find_by_id`), `domain/salon.py` (`Salon.owner_id`), la migration `0007` (patron `CHECK`). **Trancher**
   les questions 1–9 ; consigner dans un **ADR-0036**.
2. **(Volet B) Migration** : créer `0008_notification_appointment_update_type` (`down_revision = "0007"`)
   — ajouter `NotificationType.APPOINTMENT_UPDATE` (`domain/enums.py`), **régénérer** le `CHECK`
   `ck_notifications_type` (drop + recreate incluant les 5 valeurs) ; `downgrade` symétrique. Vérifier le
   **round-trip** sur PostgreSQL 16.
3. **Domaine** : étendre `domain/notification.py` — libellés neutres + constructeurs
   `build_client_cancellation_notification`, `build_salon_cancellation_notification` (A) et
   `build_client_status_update_notification`, `build_salon_modification_notification` (B) ; export
   `__all__`. Étendre `tests/test_notification_domain.py`.
4. **Cas d'usage** :
   - `CancelAppointment` : dépendance `SalonRepository` ; après le `cancel` (et l'annulation des rappels
     #46), émettre **2** `CANCELLATION` (client + salon via `find_by_id`), même `Session` ; docstring.
   - `SetAppointmentStatus` : dépendance `SalonRepository` ; sur `→ CANCELLED`, **2** `CANCELLATION` ;
     sinon **1** `APPOINTMENT_UPDATE` client (Volet B) ; docstring.
   - `ModifyAppointment` : **1** `APPOINTMENT_UPDATE` salon (`salon.owner_id` déjà chargé) ; docstring.
   Étendre `FakeNotificationRepository`/fake `SalonRepository` (`conftest.py`) et
   `tests/test_appointment_usecases.py` (comptes/ciblage par transition, atomicité, non-émission sur échec).
5. **Adapter entrant** : provider `get_salon_repository` (si absent, même `Session`) ; injection dans
   `cancel_appointment`/`set_appointment_status` ; **aucune** route ajoutée ; docstrings OpenAPI
   (`cancel`/`set_status`/`modify`) rectifiées. Étendre `tests/test_appointment_api.py` ; vérifier
   `tests/test_security_guards.py`.
6. **e2e** : étendre `tests/test_appointment_notification_e2e.py` (annulation → 2 `CANCELLATION` liées &
   sans PII ; confirmation/clôture → 1 `APPOINTMENT_UPDATE` client ; modification → 1 `APPOINTMENT_UPDATE`
   salon ; échec → 0 ; nettoyage `notifications` avant `appointments`/`users`/`salons`). Exécuter `pytest`
   (+ `DATABASE_URL`, `alembic upgrade head`) et `ruff check`.
7. **Documentation** : section `backend/README.md` ; phrase de statut `README.md` racine (M5) ;
   `docs/adr/0036-notification-annulation-modification.md` + index `docs/adr/README.md` ; docstrings
   OpenAPI.
8. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test **web inchangé** +
   flutter test **mobile inchangé**), `ruff check`, round-trip Alembic (`0008` si Volet B) vert ; relire
   la PR pour garantir qu'**aucun** numéro, nom, motif, secret ni contenu de message n'apparaît dans les
   logs ; que les notifications sont **émises dans la même transaction** que le changement de statut et
   **ciblées** sur `client_id` / `salon.owner_id` ; qu'une **annulation notifie bien client + salon**
   (§8.4) ; qu'un changement échoué n'émet **aucune** notification ; que **rien n'est réellement
   « envoyé »** (non-remise assumée, `PENDING`, `sent_at NULL`, ADR-0006) ; que le **périmètre** exclut
   `AssignHairdresser` et la lecture ; et qu'**aucune signature IA** n'a été introduite.
