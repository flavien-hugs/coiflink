# ADR-0034 : Rappel automatique avant RDV — rappels `notifications` datés (`scheduled_for`), annulation liée au cycle de vie du RDV (statut `CANCELLED`), remise proactive différée M5

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideurs** : équipe CoifLink
- **Issue** : #46 (US-7.2 — Rappel automatique avant RDV)
- **Référence PRD** : §6 Épic 7 (US-7.2), §8.4 (notifications, traçage des notifications critiques), §9.8 (types/canaux de notification), §11.3 (non-fuite PII), §11.4 (journalisation des actions importantes), §12.1 (garde de latence)
- **S'appuie sur** : [ADR-0033](./0033-notification-confirmation-rdv.md) (trio domaine/port/adapter de notification, canal pur, écriture atomique — socle direct de #46),
  [ADR-0006](./0006-notifications-fcm-sms.md) (notifications FCM/SMS, remise asynchrone différée M5, WhatsApp V2),
  [ADR-0023](./0023-moteur-disponibilite-anti-double-reservation.md) / [ADR-0024](./0024-reservation-cote-client.md) (réservation, unité de travail),
  [ADR-0025](./0025-annulation-rendez-vous-client.md) (annulation client) et
  [ADR-0030](./0030-recu-numerique-remise-differee.md) (précédent « généré/récupérable, remise différée M5 »)

## Contexte et problème

Le PRD (§6 Épic 7, US-7.2 ; §8.4) pose : « en tant que client, je veux recevoir un rappel avant mon rendez-vous ». Le backlog (#46) précise : *« Rappel configurable 24h / 2h / 30 min via jobs asynchrones »*, et le critère d'acceptation est : **« Rappel planifié et envoyé à l'échéance ; l'annulation du RDV annule le rappel. »**

Trois constats structurent la décision :

1. **Le socle de notification est livré par #45** ([ADR-0033](./0033-notification-confirmation-rdv.md)) : le trio domaine (`domain/notification.py`) / port (`NotificationRepository`) / adapter (`SqlNotificationRepository`) écrit déjà une ligne `notifications` `CONFIRMATION` dans la même unité de travail que la réservation. `NotificationType.REMINDER` **existe déjà** au schéma (migration `0001`) — écrire une notification `REMINDER` n'exige, en soi, aucune migration.
2. **Un rappel diffère d'une confirmation sur deux points que le schéma ne porte pas.** (a) Un rappel a une **échéance future** (`24h`/`2h`/`30min` avant le RDV) — la table `notifications` n'a **aucune** colonne d'horodatage d'envoi. (b) Un rappel doit pouvoir être **annulé** quand le RDV l'est (AC explicite) — `NotificationStatus` ne porte pas de valeur `CANCELLED`.
3. **La remise réelle (push FCM / SMS via file Redis) reste différée M5** (ADR-0006), comme pour #45/#38 : aucun ordonnanceur, aucun worker, aucun fournisseur SMS concret, aucun registre de jetons d'appareil n'existe. L'AC « envoyé à l'échéance » ne peut donc pas être satisfait par un envoi réel au MVP.

L'interprétation MVP fidèle et livrable, cohérente avec #45/#38 : **planifier les rappels en les persistant** (une ligne `notifications` `REMINDER` `PENDING` datée par échéance encore future, dans la même unité de travail que la réservation) et **annuler** ces lignes lorsque le RDV l'est, sans inventer d'ordonnanceur/worker non implémenté.

## Décision

Une **migration** (`0006_notification_scheduling`) ajoute l'échéance et le statut `CANCELLED`. À la création d'un RDV, **planifier** (persister) une ligne `notifications` `REMINDER`/`PENDING` par échéance **encore future**, dans la **même** unité de travail que le RDV. À l'annulation du RDV (client ou refus gérant), **annuler** (marquer `CANCELLED`) les rappels `PENDING` du RDV, dans la **même** unité de travail que le changement de statut. Aucun envoi réel, aucun endpoint de lecture, aucune route publique.

### 1. Migration `0006` — échéance (`scheduled_for`) et statut `CANCELLED`

`notifications.scheduled_for TIMESTAMPTZ NULL` : `NULL` = à remettre au plus tôt (confirmation #45, sémantique inchangée) ; non-`NULL` = à remettre **à partir de** cette date (rappel). Nullable → **aucun backfill**, les lignes `CONFIRMATION` existantes restent valides. `NotificationStatus.CANCELLED` est ajouté (marquer plutôt que supprimer un rappel qui ne partira jamais **préserve la trace** exigée par §8.4/§11.4) ; le `CHECK` `status` est **régénéré** pour l'accepter. Un **index partiel** `ix_notifications_due (scheduled_for) WHERE status = 'PENDING'` prépare — sans le consommer — la future requête « rappels dus » du worker M5+.

### 2. Domaine pur (`domain/notification.py`, étendu) — un jeu d'offsets fixe, un filtre du passé

`REMINDER_OFFSETS = (24h, 2h, 30min)` matérialise le « configurable » du backlog en un **jeu par défaut** : aucune table de préférence par client/salon n'est introduite au MVP (évolution ultérieure distincte). `compute_reminder_schedules(appointment_start, now, offsets)` est une fonction **pure** qui renvoie, pour chaque offset, `appointment_start - offset`, **filtré aux échéances strictement futures** (`> now`) : une échéance déjà passée au moment de la réservation (RDV pris moins de 24h à l'avance, par exemple) n'est **pas** planifiée — aucune ligne « en retard » à la création. `build_reminder_notifications(...)` assemble une `NotificationToCreate` neutre (`type=REMINDER`, `status=PENDING`, `scheduled_for`, `title`/`message` templatés sans PII) par échéance future. La résolution de canal de #45 est **généralisée** (`resolve_confirmation_channel` → `resolve_notification_channel`, alias rétrocompatible conservé) et réutilisée telle quelle (PUSH → SMS → IN_APP, WhatsApp exclu V2) — pas de logique dupliquée.

### 3. Port + adapter — une méthode d'annulation ciblée, idempotente

Le port `NotificationRepository` gagne `cancel_pending_for_appointment(appointment_id)`. `SqlNotificationRepository` l'implémente par un `UPDATE` ciblé (`WHERE appointment_id = … AND type = 'REMINDER' AND status = 'PENDING'`), `flush` **sans commit** — même unité de travail que le changement de statut du RDV (patron `AuditLog` #20, UPDATE conditionnel de `SqlAppointmentRepository.cancel`/`set_status`). L'`UPDATE` ne touche **jamais** la confirmation (#45), déjà émise ; idempotent (aucune ligne à annuler → no-op).

### 4. Cas d'usage — planifier à la réservation, annuler au cycle de vie, re-planifier sur modification

`BookAppointment` planifie les rappels après avoir émis la confirmation, dans la même `Session`. `CancelAppointment` (#24) et `SetAppointmentStatus` (#25, **uniquement** sur `→ CANCELLED`) reçoivent `NotificationRepository` et annulent les rappels `PENDING` du RDV après l'écriture réussie du changement de statut, dans la même `Session` — un RDV annulé ne laisse **aucun** rappel `PENDING` derrière lui (AC). Les transitions `CONFIRMED`/`COMPLETED`/`NO_SHOW` n'annulent **rien** : leurs rappels ont une échéance déjà passée, que le futur worker ne remettra pas (il re-vérifiera le statut du RDV à l'envoi). `ModifyAppointment` (#23) est étendu de la même manière : après un déplacement de créneau réussi, les rappels `PENDING` existants sont **annulés puis re-planifiés** sur la nouvelle date/heure — sans cela, un RDV déplacé laisserait des rappels pointant l'ancien créneau.

### 5. Non-remise assumée, statut `PENDING` (honnête)

#46 **planifie/annule** les rappels ; il n'**envoie** rien. `status` reste `PENDING` à la planification, `sent_at` reste `NULL` — le worker M5+ passera `SENT` + `sent_at` à la remise réelle (ADR-0006), en re-vérifiant que le RDV est toujours actif. L'AC « envoyé à l'échéance » est donc **honnêtement partiel** au MVP : le rappel est *planifié et tracé*, pas *délivré*. Aucun appel réseau externe n'entre dans le chemin de requête (§12.1) ; ni ordonnanceur, ni worker Redis, ni fournisseur SMS ne sont construits ici.

### 6. La ligne `notifications` **est** la trace §8.4/§11.4 — pas de double trace `audit_logs`

Comme #45, la ligne persistée (type, canal, statut, `scheduled_for`, `created_at`, `sent_at` ultérieur) **est** la trace du rappel. Aucune action n'est ajoutée à `AuditAction` pour la planification/annulation des rappels.

### 7. Non-fuite de PII (§11.3, ADR-0006)

Les lignes `REMINDER` ne stockent **que** des identifiants opaques, un `scheduled_for` (horodatage, non-PII) et un `title`/`message` **templaté neutre** (« Rappel de rendez-vous » / « Vous avez un rendez-vous à venir. » — sans date/heure/salon, laissés au futur worker) — jamais le téléphone ni le nom du client.

## Conséquences

- **Positif.** Un rappel **planifié** (ligne `REMINDER`/`PENDING` datée) et **tracé** existe pour chaque échéance encore future à la création du RDV, dans la même transaction que la réservation. L'**annulation du RDV annule ses rappels** (AC), dans la même transaction que l'annulation/le refus. Une **modification** du créneau re-date les rappels au lieu de laisser des lignes périmées. Aucune route publique, aucun appel réseau externe.
- **Compromis.** L'AC « envoyé à l'échéance » n'est **pas** satisfait par un envoi réel au MVP — seule la planification/trace l'est, comme #45/#38 avant. Le message reste minimal et neutre ; la composition riche (date/heure/salon) est laissée au futur worker.
- **Non-remise.** La remise proactive (push FCM / SMS via file Redis) et l'**ordonnanceur** qui interrogera les lignes `REMINDER` `PENDING` dues (`scheduled_for <= now`) relèvent du **worker M5+** (Épic 7, ADR-0006), avec le fournisseur SMS concret (#5) et un registre de jetons d'appareil (activera `PUSH`).
- **Périmètre.** #46 planifie/annule les rappels **du client** uniquement. La notification au salon (US-7.3, #47) et la notification poussée d'annulation/modification au client (US-7.4, #48) restent hors périmètre — annuler un rappel n'est pas notifier le client de l'annulation.
- **Suivi.** Un test e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouille le parcours : réservation lointaine → 3 lignes `REMINDER`/`PENDING` datées (`scheduled_for = début − 24h/2h/30min`), liées au client/salon/RDV, `sent_at IS NULL` ; annulation client / refus gérant → 0 rappel `PENDING` restant (marqués `CANCELLED`) ; modification → anciens rappels `CANCELLED`, nouveaux `PENDING` sur le nouveau créneau.
