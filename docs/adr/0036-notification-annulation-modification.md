# ADR-0036 : Notification d'annulation/modification de RDV — émission atomique aux parties concernées, `CANCELLATION` réutilisé (client + salon), type `APPOINTMENT_UPDATE` pour les autres changements de statut & la modification, remise différée M5

- **Statut** : Accepté
- **Date** : 2026-08-05
- **Décideurs** : équipe CoifLink
- **Issue** : #48 (US-7.4 — Notification d'annulation/modification)
- **Référence PRD** : §6 Épic 7 (US-7.4), §8.4 (« une annulation doit notifier le client et le salon », traçage des notifications critiques), §9.8 (types/canaux de notification), §11.2 (isolation par salon), §11.3 (non-fuite PII), §11.4 (journalisation des actions importantes), §12.1 (garde de latence)
- **S'appuie sur** : [ADR-0033](./0033-notification-confirmation-rdv.md) (trio domaine/port/adapter de notification, écriture atomique),
  [ADR-0034](./0034-rappel-automatique-avant-rdv.md) (annulation liée au cycle de vie, régénération d'un `CHECK` dérivé de l'enum — patron de migration),
  [ADR-0035](./0035-notification-salon-a-la-reservation.md) (destinataire = gérant `salon.owner_id`, canal `IN_APP`, migration `NEW_BOOKING`),
  [ADR-0006](./0006-notifications-fcm-sms.md) (FCM/SMS, remise asynchrone différée M5, WhatsApp V2),
  [ADR-0025](./0025-annulation-rendez-vous-client.md) (annulation client, motif optionnel non journalisé),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, isolation par salon §11.2)

## Contexte et problème

Le PRD (§6 Épic 7, US-7.4 ; §8.4) pose : « en tant que client, je veux être notifié en cas d'annulation ou de modification ». Le backlog (#48) précise : *« Notification automatique après changement de statut ; une annulation notifie client + salon (§8.4) »*, et le critère d'acceptation est : **« Un changement de statut déclenche la notification aux parties concernées. »**

Trois constats structurent la décision :

1. **Le socle de notification est livré (#45/#46/#47) et directement réutilisable.** Le trio domaine (`domain/notification.py`) / port (`NotificationRepository.enqueue`) / adapter (`SqlNotificationRepository`) écrit déjà une ligne `notifications` dans la **même** unité de travail que l'écriture métier. Les trois cas d'usage concernés (`CancelAppointment` #24, `SetAppointmentStatus` #25, `ModifyAppointment` #23) portent déjà un `NotificationRepository` (injecté par #46 pour l'annulation/re-planification des rappels) — mais **n'émettaient aucune notification** de l'événement aux parties.
2. **L'annulation est la seule règle chiffrée (§8.4) ; l'AC est plus large.** « Une annulation notifie le client **et** le salon » → sur **toute** transition `→ CANCELLED` (annulation client #24 **ou** refus gérant #25), **deux** notifications. Le type `CANCELLATION` **existe déjà** (enum + `CHECK`, migration `0007`) → **aucune migration** pour ce cœur. Mais l'AC vise *tout* changement de statut : la **confirmation/clôture/absence** gérant (côté **client**) et la **modification** #23 (côté **salon**) n'ont **aucune** valeur d'enum adaptée (`CONFIRMATION` #45 = réservation client, `NEW_BOOKING` #47 = réservation reçue par le salon).
3. **La remise réelle (email/SMS/push) reste différée M5** (ADR-0006), comme #45/#46/#47 : aucun worker, aucun ordonnanceur, aucun fournisseur concret. #48 **émet/trace**, il n'**achemine** rien.

L'interprétation MVP fidèle et livrable, cohérente avec les précédents, est : **notifier les parties concernées en persistant** une ligne `notifications` par destinataire (`status = PENDING`, `scheduled_for = NULL`) dans la **même** unité de travail que le changement de statut. Ces lignes **sont** la trace des notifications critiques (§8.4/§11.4) et **la file** du futur worker de remise.

## Décision

Livrer les **deux** volets. **Volet A (annulation, sans migration)** : sur toute transition `→ CANCELLED`, émettre **deux** notifications `CANCELLATION` — client + salon. **Volet B (reste de l'AC, migration `0008`)** : sur les autres transitions gérant (`CONFIRMED`/`COMPLETED`/`NO_SHOW`) notifier le **client** ; sur une **modification** (#23) notifier le **salon** — type dédié `APPOINTMENT_UPDATE`. Toutes les émissions passent par le port `enqueue` sur la **même** `Session` que l'écriture du statut. Aucun envoi réel, **aucune** route ajoutée.

### 1. Migration `0008` — valeur d'enum `APPOINTMENT_UPDATE` (Volet B uniquement)

Le Volet A n'exige **aucune** migration (`CANCELLATION` et son `CHECK` existent depuis `0007`). `NotificationType.APPOINTMENT_UPDATE = "APPOINTMENT_UPDATE"` est ajouté (`domain/enums.py`) ; le modèle `models.Notification` dérive son `CHECK` `type` de l'enum (`enum_check(...)`), mais le `CHECK` en base est figé au déploiement. La migration `0008` (`down_revision = "0007"`) le **régénère** : `drop_constraint(ck_notifications_type)` puis `create_check_constraint` incluant les **5** valeurs — **exactement** le patron de `0006`/`0007`. `downgrade()` symétrique (recreate sans `APPOINTMENT_UPDATE`), round-trip vérifié en CI (PostgreSQL 16). **Aucun backfill**, **aucune** nouvelle colonne, **aucun** nouvel index ; `"APPOINTMENT_UPDATE"` (18 car.) tient dans `type String(32)`. Taxonomie : un **seul** type générique (le détail `from`/`to` n'est pas stocké §11.3 — il vit dans `audit_logs` et sur le RDV, résolu à la lecture/remise).

### 2. Domaine pur (`domain/notification.py`, étendu) — quatre constructeurs neutres

`build_client_cancellation_notification` / `build_salon_cancellation_notification` (`type = CANCELLATION`) et `build_client_status_update_notification` / `build_salon_modification_notification` (`type = APPOINTMENT_UPDATE`) assemblent une `NotificationToCreate` neutre (`status = PENDING`, `scheduled_for = None`, `title`/`message` **templatés**). Gabarits directs : `build_confirmation_notification` (client) et `build_salon_new_booking_notification` (salon). Aucun `raise` (données déjà validées par le changement de statut). Le **canal client** est résolu « selon disponibilité » (`resolve_notification_channel` → SMS au MVP) ; le **canal salon** est `IN_APP` explicite (comme #47).

### 3. Port + adapter — aucune nouvelle méthode d'écriture

Chaque notification est une `NotificationToCreate` de plus : le port `enqueue` et `SqlNotificationRepository.enqueue` **suffisent tels quels**. `cancel_pending_for_appointment` (#46) reste inchangé (il cible `type = REMINDER`, jamais `CANCELLATION`/`APPOINTMENT_UPDATE`) : sur `→ CANCELLED`, l'annulation des rappels (`UPDATE type = REMINDER`) et l'émission des `CANCELLATION` (`INSERT`) **cohabitent sans recouvrement**.

### 4. Résolution du gérant (`salon.owner_id`) via `SalonRepository.find_by_id`

`ModifyAppointment` charge déjà le `Salon` (`_load_bookable_salon`) — `owner_id` est **gratuit**. `CancelAppointment`/`SetAppointmentStatus` ne chargent pas le salon : ils reçoivent une **dépendance optionnelle** `SalonRepository` (défaut `None`) et résolvent `owner_id` via `find_by_id(salon_id)` — un `get` par clé primaire **indépendant du statut** (indispensable : une annulation reste possible sur un salon devenu inactif §8.3). Le câblage de production (`adapters/inbound/appointments.py::get_salon_repository`, **même** `Session`) l'injecte **toujours** → §8.4 (client **et** salon) honoré. En son absence (tests unitaires ciblant un autre concern) ou si `find_by_id` renvoie `None` (théoriquement impossible — FK `RESTRICT`), l'annulation **n'échoue pas** : seule la notification salon est omise. Alternative écartée : `user_id = NULL` + `salon_id` seul (diverge de #47, complique la future remise).

### 5. Cas d'usage — nombre & ciblage par transition, même unité de travail

- **`CancelAppointment` (#24)** : après le `cancel` réussi et l'annulation des rappels, émettre **2** `CANCELLATION` (client `client_id` + salon `owner_id`).
- **`SetAppointmentStatus` (#25)** : sur `→ CANCELLED` (refus gérant), comme Cancel — **2** `CANCELLATION` (+ annulation des rappels existante) ; sinon (`CONFIRMED`/`COMPLETED`/`NO_SHOW`) — **1** `APPOINTMENT_UPDATE` au **client** (`current.client_id`).
- **`ModifyAppointment` (#23)** : après l'`update` et la re-planification des rappels, **1** `APPOINTMENT_UPDATE` au **salon** (`salon.owner_id`) — le client est l'auteur et connaît déjà le changement ; on ne le re-notifie pas.
- **`AssignHairdresser` (#25)** : **aucune** notification (hors périmètre — pas un changement de statut au sens de l'AC).

Toutes les émissions passent par le port `enqueue` sur la **même** `Session` que l'écriture du statut : un changement échoué (verrou terminal, TOCTOU, RDV d'autrui) ne laisse **aucune** notification (rollback conjoint) ; un changement réussi ne peut exister sans ses notifications.

### 6. Non-remise assumée, statut `PENDING` (honnête)

#48 **émet/trace** ; il n'**envoie** rien. `status` reste `PENDING`, `sent_at` reste `NULL` — le worker M5+ passera `SENT` + `sent_at` à la remise réelle (résolution `user_id → users.email/phone` **à l'envoi**, jamais copiée dans `notifications`). Aucun appel réseau externe n'entre dans le chemin de requête (§12.1) ; l'émission n'ajoute que quelques `INSERT` locaux (+ **un** `get` par clé primaire du salon pour Cancel/SetStatus). Aucun secret n'entre au dépôt (#5).

### 7. La ligne `notifications` **est** la trace §8.4/§11.4 — pas de double trace `audit_logs`

Comme #45/#46/#47, la ligne persistée (type, canal, statut, `created_at`, `sent_at` ultérieur) **est** la trace exigée. L'audit du **changement de statut** (`APPOINTMENT_CANCELLED`/`APPOINTMENT_STATUS_CHANGED`/`APPOINTMENT_UPDATED`, avec le `{from, to}`/diff neutre) existe déjà (#24/#25/#23). Aucune action n'est ajoutée à `AuditAction`.

### 8. Non-fuite de PII (§11.3, ADR-0006) & isolation par salon (§11.2)

Chaque ligne ne stocke **que** des identifiants **opaques** (`user_id`, `salon_id`, `appointment_id`) et un `title`/`message` **templaté neutre** — **jamais** le nom/téléphone d'une partie, ni le **motif** d'annulation (persisté sur le RDV #24/#25, jamais recopié). Le `user_id` du destinataire est **imposé serveur** (`appointment.client_id` / `salon.owner_id`, jamais soumis). Aucune route ajoutée → deny-by-default intact, matrice RBAC inchangée. Ni l'adapter `enqueue` ni les cas d'usage ne journalisent destinataire, canal ou corps.

### 9. Lecture des notifications — différée (parité #45/#47)

Les endpoints de lecture (`GET /me/notifications` côté client, `GET /salons/{salon_id}/notifications` côté salon) restent **différés** — exactement comme #45/#47 (ADR-0033/0035 ont reporté la lecture). #48 livre l'**émission/trace** ; **contrats HTTP inchangés** (`cancel`/`status`/`modify` renvoient toujours `200 AppointmentResponse`).

## Conséquences

- **Positif.** Un changement de statut de RDV **émet/trace** désormais des notifications aux parties concernées dans la **même** transaction que l'écriture : annulation → **2** `CANCELLATION` (client + salon, §8.4) ; confirmation/clôture/absence → **1** `APPOINTMENT_UPDATE` client ; modification → **1** `APPOINTMENT_UPDATE` salon. Un changement échoué n'en laisse **aucune** (rollback conjoint). Aucune route publique, aucun appel réseau externe.
- **Compromis.** L'AC est satisfait **au sens de la trace/émission**, pas de l'affichage : sans les endpoints de lecture (différés), client et salon ne **voient** pas encore ces notifications. Le message reste minimal et neutre (le détail `from`/`to`, la date/heure et le motif ne sont **pas** stockés) ; la composition riche est laissée à la lecture (future) ou au worker de remise via `appointment_id`/`audit_logs`.
- **Non-remise.** La remise proactive (push/SMS/email) et l'ordonnanceur relèvent du **worker M5+** (Épic 7, ADR-0006), avec des fournisseurs concrets (#5). Aucun point d'accroche mort n'est ajouté ici.
- **Périmètre.** Hors champ : `AssignHairdresser` (pas un changement de statut), préférences de notification (activer/désactiver, destinataires multiples, notifier les coiffeurs assignés), accusé de réception au client sur sa propre modification, écrans web/mobile (rien n'est remis ni lu au MVP).
- **Suivi.** Des tests e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouilleront le parcours : annulation client / refus gérant → **2** lignes `CANCELLATION`/`PENDING` (`user_id` client + owner, `channel` SMS/IN_APP, `sent_at IS NULL`, sans PII), en plus des rappels `CANCELLED` (#46) ; confirmation/clôture → **1** `APPOINTMENT_UPDATE` client ; modification → **1** `APPOINTMENT_UPDATE` salon ; changement refusé (`409`/`404`) → **0** ; nettoyage : `notifications` supprimé **avant** `appointments`/`users`/`salons` (FK `RESTRICT`).
