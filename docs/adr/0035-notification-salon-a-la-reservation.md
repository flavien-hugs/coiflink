# ADR-0035 : Notification au salon à la réservation — ligne `notifications` `NEW_BOOKING`/`IN_APP` persistée atomiquement (émission/trace §8.4/§11.4), destinataire = gérant (`salon.owner_id`), lecture salon-scopée différée, remise email/SMS différée M5

- **Statut** : Accepté
- **Date** : 2026-08-05
- **Décideurs** : équipe CoifLink
- **Issue** : #47 (US-7.3 — Notification au salon à la réservation)
- **Référence PRD** : §6 Épic 7 (US-7.3), §8.4 (notifications, traçage des notifications critiques), §9.8 (types/canaux de notification), §11.2 (isolation par salon), §11.3 (non-fuite PII), §11.4 (journalisation des actions importantes), §12.1 (garde de latence)
- **S'appuie sur** : [ADR-0033](./0033-notification-confirmation-rdv.md) (trio domaine/port/adapter de notification, écriture atomique — socle direct de #47),
  [ADR-0034](./0034-rappel-automatique-avant-rdv.md) (rappels datés, régénération d'un `CHECK` dérivé de l'enum — patron de migration réutilisé),
  [ADR-0006](./0006-notifications-fcm-sms.md) (notifications FCM/SMS, remise asynchrone différée M5, WhatsApp V2),
  [ADR-0023](./0023-moteur-disponibilite-anti-double-reservation.md) / [ADR-0024](./0024-reservation-cote-client.md) (réservation, unité de travail),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, isolation par salon §11.2)

## Contexte et problème

Le PRD (§6 Épic 7, US-7.3 ; §8.4) pose : « en tant que salon, je veux être notifié à chaque nouvelle réservation ». Le backlog (#47) précise : *« Notification dashboard + option email/SMS »*, et le critère d'acceptation est : **« Le salon est notifié à chaque nouvelle réservation. »**

Trois constats structurent la décision :

1. **Le socle de notification est livré (#45/#46).** Le trio domaine (`domain/notification.py`) / port (`NotificationRepository`) / adapter (`SqlNotificationRepository`) écrit déjà une ligne `notifications` dans la **même** unité de travail que la réservation ; `BookAppointment` émet la confirmation (#45) puis planifie les rappels (#46) — tous deux destinés au **client**. Le `Salon` chargé au début de `execute(...)` **porte déjà `owner_id`** (`domain/salon.py::Salon.owner_id`) : le gérant à notifier est résoluble **sans aucun accès base supplémentaire**.
2. **La notification au salon diffère des notifications client sur un point que le schéma ne porte pas.** Son **destinataire** est le **gérant** (`user_id = salon.owner_id`), pas le client — mais surtout sa **sémantique** (« nouvelle réservation reçue par le salon ») n'est portée par **aucune** valeur de `NotificationType` : `CONFIRMATION`/`REMINDER` visent le client, `CANCELLATION` une annulation. Réutiliser `CONFIRMATION` avec `user_id = owner` mélangerait les sémantiques et casserait l'invariant « une ligne `CONFIRMATION` = la confirmation du client ».
3. **La remise réelle (email/SMS/push) reste différée M5** (ADR-0006), comme pour #45/#46/#38 : aucun ordonnanceur, aucun worker, aucun fournisseur email/SMS concret. L'« option email/SMS » du backlog ne peut donc pas être satisfaite par un envoi réel au MVP.

L'interprétation MVP fidèle et livrable, cohérente avec #45/#46, est : **notifier le salon en persistant** une ligne `notifications` (`type = NEW_BOOKING`, `channel = IN_APP`, `status = PENDING`) rattachée au **gérant**/salon/RDV, dans la **même** unité de travail que le RDV. Cette ligne **est** la notification « dashboard » du salon (§8.4/§11.4) et **la file** que consommera le futur worker pour la remise **optionnelle** email/SMS.

## Décision

Une **migration** (`0007_notification_new_booking_type`) ajoute la valeur d'enum `NotificationType.NEW_BOOKING` et **régénère** le `CHECK` `type`. À la création d'un RDV, après la confirmation (#45) et les rappels (#46), **émettre exactement une** ligne `notifications` `NEW_BOOKING`/`IN_APP`/`PENDING` pour le **gérant** (`user_id = salon.owner_id`), dans la **même** unité de travail que le RDV. Aucun envoi réel, **aucune** route ajoutée (lecture salon-scopée différée), aucune route publique.

### 1. Migration `0007` — valeur d'enum `NEW_BOOKING` + régénération du `CHECK` `type`

`NotificationType.NEW_BOOKING = "NEW_BOOKING"` est ajouté (`domain/enums.py`) ; le modèle `models.Notification` **dérive** son `CHECK` `type` de l'enum (`enum_check("type", enums.NotificationType, name="type")`), mais le `CHECK` en base est figé au déploiement. La migration `0007` (`down_revision = "0006"`) le **régénère** : `drop_constraint(ck_notifications_type)` puis `create_check_constraint` avec la liste incluant `NEW_BOOKING` — **exactement** le patron du `CHECK` `status` régénéré par `0006` pour `CANCELLED`. `downgrade()` symétrique (recreate sans `NEW_BOOKING`), round-trip exigé par la CI. **Aucun backfill** (les lignes existantes portent des valeurs déjà autorisées), **aucune** nouvelle colonne, **aucun** nouvel index.

### 2. Domaine pur (`domain/notification.py`, étendu) — un constructeur de notification salon neutre

`build_salon_new_booking_notification(*, owner_id, salon_id, appointment_id, channel)` assemble une `NotificationToCreate` neutre (`type = NEW_BOOKING`, `status = PENDING`, `scheduled_for = None`, `title`/`message` templatés `NEW_BOOKING_TITLE`/`NEW_BOOKING_MESSAGE`) avec `user_id = owner_id` (le **gérant**, jamais le client). Aucun `raise` (données déjà validées par la réservation). Gabarit direct : `build_confirmation_notification`. Le **canal** est fourni **explicitement** par l'appelant (`IN_APP`, cf. §4) plutôt que par `resolve_notification_channel` : la notification salon est « dashboard », pas « selon disponibilité » téléphone/push.

### 3. Port + adapter — aucune nouvelle méthode d'écriture

La notification salon est une `NotificationToCreate` de plus : le port `NotificationRepository.enqueue(...)` et `SqlNotificationRepository.enqueue(...)` (livrés par #45) **suffisent tels quels**. `cancel_pending_for_appointment` (#46) n'est **pas** concerné (il cible `type = REMINDER`, jamais `NEW_BOOKING`).

### 4. Cas d'usage — une notification salon par réservation réussie, canal `IN_APP` explicite

`BookAppointment.execute` émet la notification salon après la confirmation et les rappels, dans la **même** `Session` : `enqueue(build_salon_new_booking_notification(owner_id=salon.owner_id, salon_id=salon_id, appointment_id=appointment.id, channel=NotificationChannel.IN_APP.value))`. `salon` est déjà chargé par `_load_bookable_salon(...)` — aucune dépendance ni requête ajoutée. **Une** réservation → **une** notification salon ; une réservation échouée (`SlotUnavailable`/`SlotAlreadyBooked`/…) n'atteint jamais ce point et la transaction est rollbackée → **aucune** notification salon fantôme. `ModifyAppointment`/`CancelAppointment`/`SetAppointmentStatus`/`AssignHairdresser` n'émettent **aucune** `NEW_BOOKING` (périmètre #48).

### 5. Non-remise assumée, statut `PENDING` (honnête)

#47 **émet/trace** la notification salon ; il n'**envoie** rien. `status` reste `PENDING`, `sent_at` reste `NULL` — le worker M5+ passera `SENT` + `sent_at` à la remise **optionnelle** email/SMS (résolution `owner_id → users.email/phone` **à l'envoi**, jamais copiée dans `notifications`). Aucun appel réseau externe n'entre dans le chemin de requête (§12.1) ; ni ordonnanceur, ni worker Redis, ni fournisseur email/SMS ne sont construits ici (aucun secret n'entre au dépôt, #5).

### 6. La ligne `notifications` **est** la trace §8.4/§11.4 — pas de double trace `audit_logs`

Comme #45/#46, la ligne persistée (type, canal, statut, `created_at`, `sent_at` ultérieur) **est** la trace de la notification critique « nouvelle réservation reçue par le salon ». Aucune action n'est ajoutée à `AuditAction`.

### 7. Non-fuite de PII (§11.3, ADR-0006) & isolation par salon (§11.2)

La ligne `NEW_BOOKING` ne stocke **que** des identifiants **opaques** (`user_id = owner`, `salon_id`, `appointment_id`) et un `title`/`message` **templaté neutre** (« Nouvelle réservation » / « Un nouveau rendez-vous a été réservé dans votre salon. ») — **jamais** le nom ni le téléphone du client. Les détails du RDV (date/heure/prestation/client), que le salon a le droit de voir, sont résolus **à la lecture** via `appointment_id`, jamais copiés. Le `user_id` de la ligne est **imposé serveur** (`salon.owner_id`, jamais soumis). Ni `SqlNotificationRepository` ni `BookAppointment` ne journalisent destinataire, canal ou corps.

### 8. Lecture salon-scopée « dashboard » — différée (parité #45)

Le backlog dit « Notification **dashboard** ». Persister une ligne satisfait l'AC « le salon est **notifié** » **au sens de la trace** ; l'endpoint de **lecture** salon-scopé (`GET /salons/{salon_id}/notifications`, permission `NOTIFICATION_READ_SALON`, `require_salon_scope` + filtre `salon_id` en SQL §11.2) qui matérialiserait l'affichage est **différé** — exactement comme #45, dont l'ADR-0033 a *reporté* `GET /me/notifications`. Repli assumé pour tenir l'effort **S** : émission/trace backend-only, lecture reportée à une story dédiée (qui pourra réutiliser l'index `ix_notifications_salon_id (salon_id, created_at)` pour le tri « plus récentes d'abord »). **Contrat HTTP inchangé** : `POST /salons/{salon_id}/appointments` reste `201 AppointmentResponse` ; aucune route ajoutée, rien dans `PUBLIC_ROUTE_PATHS`.

## Conséquences

- **Positif.** À chaque réservation réussie, **une** notification salon (ligne `NEW_BOOKING`/`IN_APP`/`PENDING` liée au gérant/salon/RDV) est **émise/tracée** dans la même transaction que le RDV, ciblée sur `salon.owner_id` sans accès base supplémentaire. Une réservation échouée n'en laisse **aucune** (rollback conjoint). Aucune route publique, aucun appel réseau externe.
- **Compromis.** L'AC « le salon est notifié » est satisfait **au sens de la trace/émission**, pas de l'affichage : sans l'endpoint de lecture (différé), le salon ne **voit** pas encore ces notifications dans un tableau de bord. Le message reste minimal et neutre ; la composition riche (date/heure/prestation) est laissée à la lecture (future) ou au worker de remise.
- **Non-remise.** L'**option** email/SMS (remise proactive au gérant) et l'**ordonnanceur** relèvent du **worker M5+** (Épic 7, ADR-0006), avec un fournisseur concret (#5). Aucun point d'accroche mort n'est ajouté ici.
- **Périmètre.** #47 notifie le salon **à la création** uniquement. Les notifications d'**annulation/modification** (au client comme au salon) relèvent de **#48 (US-7.4)** : une modification (#23) ne **re-notifie pas** le salon dans #47. Les préférences de notification salon (activer/désactiver, destinataires multiples, notifier les coiffeurs) sont une évolution ultérieure.
- **Suivi.** Un test e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouille le parcours : réservation → **1** ligne `NEW_BOOKING`/`PENDING`/`IN_APP` (`user_id = owner`, `salon_id`/`appointment_id` liés, `scheduled_for IS NULL`, `sent_at IS NULL`, sans PII), en plus des lignes `CONFIRMATION` (#45) et `REMINDER` (#46) inchangées ; conflit de créneau (`409`) → **aucune** notification (rollback conjoint) ; nettoyage : `notifications` supprimé **avant** `appointments`/`users`/`salons` (FK `RESTRICT`).
