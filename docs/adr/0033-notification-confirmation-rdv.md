# ADR-0033 : Notification de confirmation de RDV — ligne `notifications` persistée atomiquement (émission/trace §8.4/§11.4), canal pur PUSH→SMS→IN_APP, remise proactive différée M5

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideurs** : équipe CoifLink
- **Issue** : #45 (US-7.1 — Notification de confirmation de RDV)
- **Référence PRD** : §6 Épic 7 (US-7.1), §8.4 (notifications, traçage des notifications critiques), §9.8 (types/canaux de notification), §11.3 (non-fuite PII), §11.4 (journalisation des actions importantes), §12.1 (garde de latence)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0006](./0006-notifications-fcm-sms.md) (notifications FCM/SMS, remise asynchrone différée M5, WhatsApp V2),
  [ADR-0023](./0023-moteur-disponibilite-anti-double-reservation.md) / [ADR-0024](./0024-reservation-cote-client.md) (réservation `PENDING`, unité de travail),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (patron port + trace dans la même `Session`) et
  [ADR-0030](./0030-recu-numerique-remise-differee.md) (précédent « généré/récupérable, remise différée M5 »)

## Contexte et problème

Le PRD (§6 Épic 7, US-7.1) pose : « en tant que client, je veux recevoir une confirmation après avoir réservé, pour être rassuré que mon rendez-vous est bien pris » — le backlog précise « Push, SMS ou WhatsApp selon disponibilité ; envoyée après chaque réservation ». Le critère d'acceptation de #45 est : **« Une confirmation part à la création du RDV ; notification critique tracée (§8.4/§11.4). »**

Trois constats structurent la décision :

1. **La réservation est livrée** (#21/#22) : `POST /salons/{salon_id}/appointments` crée un `Appointment` **`PENDING`** dans **une** unité de travail (la session de la requête, committée par `get_session`). **Aucune notification n'était émise ni tracée** à la création.
2. **Le socle de notification existe déjà au schéma.** La table `notifications` (migration `0001`) et les valeurs d'enum `NotificationType.CONFIRMATION` / `NotificationChannel.{PUSH,SMS,IN_APP,…}` / `NotificationStatus.PENDING` sont **présentes** — écrire une confirmation **n'exige aucune migration** (différence majeure avec le reçu #38, cf. ADR-0030). Mais **rien n'écrivait** dans cette table : ni domaine, ni port, ni adapter de notification.
3. **La remise réelle (push FCM / SMS via file Redis) est différée M5** (ADR-0006). Le seul adapter livré est un **stub no-op** ; aucun worker de remise, aucun fournisseur SMS, **aucun registre de jetons d'appareil** (un `PUSH` ne peut donc être ciblé aujourd'hui).

Le critère parle d'une confirmation qui **« part »** et qui est **« tracée »**. Comme la remise dépend d'une infra non construite, l'interprétation MVP fidèle et livrable — cohérente avec le précédent #38/ADR-0030 — est : **émettre la confirmation en la persistant** (elle est enregistrée dans la transaction de réservation, et la ligne persistée **est** la trace), sans inventer de canal de remise non implémenté.

## Décision

À la création d'un RDV, **persister exactement une** ligne `notifications` (`type = CONFIRMATION`, `status = PENDING`, rattachée au client/salon/RDV) **dans la même unité de travail** que l'INSERT du RDV. Aucune migration, aucun endpoint de lecture, aucune route publique, aucune remise réelle.

### 1. L'émission est une **règle métier** portée par `BookAppointment`

« À la réservation, une confirmation est émise » est une règle métier, placée dans le cas d'usage (testable sans HTTP), pas dans l'adapter entrant. Après l'INSERT réussi (`appointment = repository.create(...)`), `BookAppointment` résout le canal puis **émet** via un port : `notifications.enqueue(build_confirmation_notification(...))`. La signature de `BookAppointment` gagne une dépendance `NotificationRepository` — le call site adapter et les fixtures de test sont mis à jour en conséquence. **Aucune** émission dans `ModifyAppointment`/`CancelAppointment`/`SetAppointmentStatus`/`AssignHairdresser` (périmètre #46/#48).

### 2. Domaine pur (`domain/notification.py`) — neutre, sans PII

`NotificationToCreate` (`dataclass` **gelée**) porte les champs à insérer (miroir de `models.Notification`) ; `status` vaut `PENDING` par défaut. `resolve_confirmation_channel(ChannelAvailability)` est une **fonction pure** : priorité **PUSH → SMS → IN_APP**, `WHATSAPP` **exclu** (V2). `build_confirmation_notification(...)` assemble une notification **neutre** : `title`/`message` **templatés** (aucune PII), identifiants **opaques** (`user_id`/`salon_id`/`appointment_id`). `ChannelAvailability` ne porte que des **booléens** de disponibilité (`has_push_token`, `has_phone`) — jamais le jeton ni le numéro. Gabarit : `domain/audit.py`.

### 3. Port `NotificationRepository` (écriture) + adapter SQLAlchemy, écriture **atomique**

Le port expose **une seule** méthode d'écriture — `enqueue(notification)` — nommée ainsi (et non `send`) pour marquer que **rien n'est acheminé** : la ligne `PENDING` **est la file** que consommera le worker de remise. `SqlNotificationRepository` insère un `models.Notification` et `flush` **sans commit**, sur la **même `Session`** que le RDV (fournie par `get_session`, mise en cache par requête) — patron `AuditLog` (#20/#23). La confirmation est donc committée **avec** le RDV, ou rollbackée **avec** lui : pas de confirmation « fantôme » sur une réservation échouée (`SlotAlreadyBooked`/`SlotUnavailable`), pas de RDV sans sa confirmation. **Aucune** méthode de lecture (pas d'endpoint client au périmètre #45).

### 4. Canal « selon disponibilité » — SMS au MVP, PUSH prêt mais inactif

Faute de **registre de jetons d'appareil** (device token FCM), `PUSH` n'est pas ciblable : au MVP, `ChannelAvailability(has_push_token=False, has_phone=True)` → **SMS** (le client s'inscrit par téléphone, #8 ; garantie **supposée vraie** sans accès base supplémentaire). `IN_APP` reste le repli garanti. La branche `PUSH` de `resolve_confirmation_channel` est prête pour l'activation d'un registre de jetons — **story distincte**.

### 5. Non-remise assumée, statut `PENDING` (honnête)

#45 **émet/trace** la confirmation ; il n'**envoie** rien. `status` reste `PENDING`, `sent_at` reste `NULL` — le worker M5+ passera `SENT` + `sent_at` à la remise réelle (ADR-0006). Marquer `SENT` au MVP serait mensonger. Aucun appel réseau externe n'entre dans le chemin de requête (budget de latence §12.1) ; le stub OTP existant n'est ni remplacé ni sollicité ; clés FCM / identifiants SMS restent hors dépôt (#5).

### 6. La ligne `notifications` **est** la trace §8.4/§11.4 — pas de double trace `audit_logs`

Le critère « notification critique **tracée** » est satisfait par la **ligne persistée** (type, canal, statut, `created_at`, `sent_at` ultérieur). La table `notifications` est le registre **dédié** des notifications ; dupliquer dans `audit_logs` n'apporte rien (et la trace §11.4 « Création rendez-vous » relèverait plutôt de #21). Aucune action n'est ajoutée à `AuditAction`.

### 7. Non-fuite de PII (§11.3, ADR-0006)

La ligne ne stocke **que** des identifiants **opaques** et un `title`/`message` **templaté neutre** — **jamais** le téléphone ni le nom du client. Ni `SqlNotificationRepository` ni `BookAppointment` ne journalisent le destinataire, le canal ou le corps du message. Le worker de remise (futur) résoudra `user_id → users.phone` **à l'envoi** : le numéro n'est **jamais** copié dans `notifications`. Aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS` : une notification n'est jamais publique.

## Conséquences

- **Positif.** La confirmation **part à la création du RDV** (émise/enregistrée dans la transaction de réservation) et **est tracée** (ligne persistée avec statut et horodatage), **sans** migration (l'enum `CONFIRMATION` existe), **sans** route publique et **sans** appel réseau externe. La table `notifications` reçoit sa **première** écriture ; le trio domaine/port/adapter est réutilisable par #46 (rappels) / #47 (salon) / #48 (annulation). L'atomicité conjointe est vérifiée par les tests (succès = 1 confirmation ; échec = 0).
- **Compromis.** La confirmation n'est **pas remise** au MVP : elle est **persistée**, pas poussée. Le `message` est **minimal** (« Votre rendez-vous a bien été enregistré. ») ; la composition riche (date/heure/salon — données que le client possède déjà) est laissée au worker de remise pour minimiser le stockage. Le RDV étant créé `PENDING` (« En attente », #22), le libellé confirme la **prise en compte de la demande**, non une validation par le salon.
- **Non-remise.** La remise proactive (push FCM / SMS via file Redis, WhatsApp V2) relève du **worker M5+** (Épic 7, ADR-0006), avec le fournisseur SMS concret (#5) et un **registre de jetons d'appareil** (story distincte, qui activera `PUSH`).
- **Périmètre.** #45 notifie **le client**, **à la création** uniquement. La notification au salon (US-7.3, #47), les rappels (US-7.2, #46) et les notifications d'annulation/modification (US-7.4, #48) sont hors périmètre.
- **Mobile.** Aucun changement requis : la confirmation n'étant pas remise, le tunnel #22 continue d'afficher « En attente » depuis la réponse du `POST`. Un écran « Notifications » (lecture IN_APP, `GET /me/notifications`) reste une évolution ultérieure (ne pas exposer de PII tierce, patron d'appartenance §11.2).
- **Suivi.** Un test e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouille le parcours : réservation → **une** ligne `notifications` `CONFIRMATION` `PENDING` liée au client et au RDV, `sent_at IS NULL`, **sans** téléphone stocké ; conflit de créneau (`409`) → **aucune** notification (rollback conjoint).
