# Notification au salon à la réservation (US-7.3)

> Spécification de planification pour l'issue GitHub **#47 — US-7.3 : Notification au salon à la
> réservation** (`feature` `notifications` · **Must** · Effort **S** · PRD §6 Épic 7 / §8.4
> « Notifications » / §9.8 « Notification » / §11.2 « Isolation par salon » / §11.3 « Données
> personnelles » / §11.4 « Journalisation » / §12.1 « Latence »).
> **Dépend de #22** (tunnel de réservation client, livré — consomme
> `POST /salons/{salon_id}/appointments` de #21). S'appuie **directement** sur le socle de
> notification livré par **#45** (US-7.1, confirmation client) et **#46** (US-7.2, rappels).
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 7, US-7.3 ; §8.4) et le backlog (#47) posent le besoin : **« en tant que salon, je veux
être notifié à chaque nouvelle réservation »**. Le libellé du backlog précise : *« Notification
dashboard + option email/SMS »*, et le critère d'acceptation de l'issue est :

- **Le salon est notifié à chaque nouvelle réservation.**

### État actuel du dépôt (vérifié pour cette spec)

Le **socle de notification est livré et directement réutilisable** (#45 puis #46) :

1. **Le trio domaine / port / adapter existe** et écrit déjà dans la table `notifications` :
   - `domain/notification.py` — `NotificationToCreate` (dataclass `frozen`, miroir des colonnes de
     `models.Notification`, avec le champ `scheduled_for` ajouté par #46), `ChannelAvailability`,
     `resolve_notification_channel` (fonction pure **PUSH → SMS → IN_APP**, `WHATSAPP` exclu V2, alias
     rétrocompatible `resolve_confirmation_channel`), `build_confirmation_notification`,
     `build_reminder_notifications`, et les libellés templatés neutres
     `CONFIRMATION_TITLE`/`CONFIRMATION_MESSAGE`/`REMINDER_TITLE`/`REMINDER_MESSAGE`.
   - `application/ports/notification_repository.py` — `NotificationRepository(Protocol)` avec
     `enqueue(notification) -> None` (écriture) et `cancel_pending_for_appointment(appointment_id) ->
     None` (annulation des rappels, #46).
   - `adapters/outbound/persistence/notification_repository.py` — `SqlNotificationRepository`
     (`session.add(...)` + `flush()`, **sans commit** : atomicité conjointe avec l'écriture métier via
     `get_session`, patron `AuditLog` #20 ; recopie le contenu **déjà neutre**, ne journalise **jamais**
     destinataire ni contenu, ADR-0006).
2. **`BookAppointment` émet déjà, dans la même unité de travail que l'INSERT du RDV** : une
   `CONFIRMATION` **au client** (#45) puis jusqu'à 3 `REMINDER` datés **au client** (#46). Le `Salon`
   chargé par `_load_bookable_salon(...)` au début de `execute(...)` **porte déjà `owner_id`** (voir
   `domain/salon.py::Salon.owner_id`) : **le gérant à notifier est résoluble sans aucun accès base
   supplémentaire**. **Aucune** notification n'est aujourd'hui émise **vers le salon**.
3. **La table `notifications` porte `user_id`/`salon_id`/`appointment_id`** (tous nullable, FK
   `RESTRICT`), `type`/`channel`/`title`/`message`/`status`/`sent_at`/`scheduled_for`/`created_at`
   (migrations `0001` + `0006`). L'enum `NotificationType` (`domain/enums.py`) porte **`CONFIRMATION`,
   `REMINDER`, `CANCELLATION`** — **aucune valeur ne désigne une notification destinée au salon à la
   réservation**. La contrainte `CHECK` de `type` est **dérivée de l'enum** (`models.py::enum_check(
   "type", enums.NotificationType, name="type")` → `ck_notifications_type`).
4. **La remise réelle reste différée M5+** (ADR-0006, ADR-0033, ADR-0034) : **aucun worker de remise,
   aucune file Redis câblée, aucun fournisseur SMS/email concret, aucun ordonnanceur** n'existe. Le seul
   adapter « d'envoi » livré est le **stub no-op** d'OTP
   (`adapters/outbound/notifications/otp_sender_stub.py`), qui ne journalise jamais destinataire ni
   contenu. Le canal effectif d'une notification poussée est **SMS** au MVP (faute de registre de jetons
   d'appareil, `PUSH` n'est pas ciblable).

### Le gap structurant que #47 comble

À la création d'un RDV, **le client** reçoit sa confirmation/ses rappels (#45/#46), mais **le salon
n'apprend rien** de la nouvelle réservation. #47 ajoute **une** notification **destinée au salon** (au
gérant, `user_id = salon.owner_id`) **à chaque réservation réussie**, dans la **même unité de travail**
que le RDV. Deux points la distinguent des notifications client existantes :

1. **Un destinataire différent : le salon (le gérant), pas le client.** La ligne rattache
   `user_id = salon.owner_id`, `salon_id`, `appointment_id`. Aucun modèle existant ne capture cette
   sémantique « nouvelle réservation reçue par le salon » : l'enum `NotificationType` **n'a pas** de
   valeur adaptée. **#47 nécessite une migration** ajoutant une valeur d'enum (recommandé :
   `NEW_BOOKING`) et **régénérant la contrainte `CHECK` de `type`** — exactement le patron par lequel
   #46 a régénéré le `CHECK` de `status` pour `CANCELLED` (migration `0006`).
2. **Un canal « dashboard » : `IN_APP`.** Le backlog dit « Notification **dashboard** + **option**
   email/SMS ». La notification que le salon consulte dans son tableau de bord est **`IN_APP`** ;
   l'email/SMS est une **option** de remise proactive, qui relève — comme le push/SMS client de #45/#46
   — du **worker M5+** (ADR-0006) et **n'est pas construite ici**.

Comme pour #45/#46/#38 (ADR-0030), la **remise proactive** dépend d'une infra **non construite**.
L'interprétation MVP fidèle et livrable, cohérente avec les précédents, est :

> **Notifier le salon en persistant** une ligne `notifications` (`type = NEW_BOOKING`, `channel =
> IN_APP`, `status = PENDING`, `scheduled_for = NULL`, rattachée au **gérant**/salon/RDV) **dans la même
> unité de travail** que l'INSERT du RDV. Cette ligne **est** la notification « dashboard » du salon
> (§8.4/§11.4 : notification critique tracée) et **la file** que consommera le futur worker pour la
> remise **optionnelle** email/SMS. L'**émission** satisfait l'AC « le salon est notifié à chaque
> nouvelle réservation » ; la **remise proactive** email/SMS reste **différée M5+**.

**Décision de périmètre à trancher (voir *Risks & Open Questions* §1) : faut-il aussi livrer un endpoint
de lecture salon-scopé (`GET /salons/{salon_id}/notifications`) pour que le tableau de bord *affiche*
réellement ces notifications ?** Le backlog dit explicitement « **dashboard** » (contrairement à #45,
dont l'ADR-0033 a *reporté* la lecture `GET /me/notifications`). Ce document **recommande d'inclure ce
endpoint de lecture** (léger, isolation §11.2, sans PII tierce) afin que « le salon est notifié » soit
vrai **au sens visible**, pas seulement au sens de la trace — tout en documentant l'alternative
« backend-only émission/trace » (stricte parité #45/#46) comme repli acceptable si l'effort **S** doit
rester minimal.

## Goals

- **Notifier le salon à chaque réservation réussie, atomiquement.** Dans `BookAppointment`, après
  l'INSERT réussi du RDV et l'émission des notifications client (#45/#46), **persister exactement une**
  ligne `notifications` `type = NEW_BOOKING`, `channel = IN_APP`, `status = PENDING`,
  `scheduled_for = NULL`, rattachée au **gérant** (`user_id = salon.owner_id`, déjà chargé), au salon et
  au RDV, via le port `enqueue`, dans **la même** `Session` — donc committée avec le RDV, ou rollbackée
  avec lui. **Une** réservation → **une** notification salon.
- **Notification salon = trace (§8.4/§11.4).** La ligne persistée (type, canal, `status`, `created_at`,
  `sent_at` ultérieur) **constitue** la trace de la notification critique « nouvelle réservation ». Elle
  est **neutre** : **aucune PII** (ni nom, ni téléphone du client) — seulement des identifiants opaques
  (`user_id = owner`, `salon_id`, `appointment_id`) et un `title`/`message` **templaté**.
- **Canal « dashboard » = `IN_APP` ; email/SMS = option différée.** La notification que le salon
  consulte est `IN_APP`. Ne **pas** router vers SMS/email au MVP : la remise proactive optionnelle
  relève du worker M5+ (ADR-0006). `status` reste `PENDING`, `sent_at` reste `NULL` — honnête (rien
  n'est envoyé).
- **(Recommandé — voir §1) Rendre la notification lisible par le salon.** Livrer un endpoint de lecture
  **salon-scopé** `GET /salons/{salon_id}/notifications` (liste read-only des notifications `NEW_BOOKING`
  du salon, plus récentes d'abord, paginée), **deny-by-default** + **isolation par salon** (§11.2), pour
  matérialiser le « dashboard ». Optionnellement, une **surface `/gerant`** minimale (indicateur/liste).
  *Alternative documentée : différer la lecture (backend-only), comme #45.*
- **Périmètre strict : notification à la création uniquement.** #47 notifie le salon **à la
  réservation** (`BookAppointment`). Les notifications d'**annulation/modification** au client **et** au
  salon relèvent de **#48 (US-7.4)** : ni `CancelAppointment`, ni `SetAppointmentStatus`, ni
  `ModifyAppointment` n'émettent de notification salon dans #47.
- **Remise différée, assumée et documentée (cohérence #45/#46/#38).** Aucun envoi réel (email/SMS/push)
  et **aucun ordonnanceur** n'est construit. Aucun appel réseau externe dans le chemin de requête
  (budget de latence §12.1). **Aucun** secret (identifiants email/SMS/FCM) n'entre au dépôt (#5).
- **Couverture de tests.** Domaine (constructeur de notification salon neutre, sans PII, `type`/`channel`
  corrects), cas d'usage (`BookAppointment` émet **1** notification salon en plus de la confirmation et
  des rappels ; **aucune** sur réservation échouée ; ciblage `owner_id` ; atomicité), API (contrat
  `POST` inchangé ; endpoint de lecture salon-scopé si retenu), e2e PostgreSQL (réservation → ligne
  `NEW_BOOKING` `PENDING` `IN_APP` liée au gérant/salon/RDV, `sent_at IS NULL`, sans PII).

## Non-Goals

- **Construire l'infra de remise (worker Redis, ordonnanceur, email/SMS/FCM).** La remise **optionnelle**
  email/SMS dépend d'un worker consommant la file (ADR-0006) + d'un fournisseur concret (#5), **différés
  M5+**. #47 **émet/trace** la notification salon ; il n'implémente **aucun** envoi réel, **aucune** file
  Redis, **aucun** ordonnanceur. Le stub OTP n'est ni remplacé ni sollicité.
- **Notifier le salon (ou le client) d'une annulation/modification** — c'est **#48 (US-7.4)**. #47 ne
  touche **que** `BookAppointment` (création). En particulier, une modification (#23) ne **re-notifie
  pas** le salon dans #47.
- **Modéliser des préférences de notification salon** (activer/désactiver `IN_APP`/email/SMS,
  destinataires multiples, notifier les coiffeurs). Le canal `IN_APP` par défaut suffit au MVP ; les
  préférences sont une évolution ultérieure.
- **Enrichir la ligne persistée de détails du RDV** (date/heure/prestation/nom du client). Comme #45/#46,
  le `title`/`message` reste **minimal et neutre** ; la composition riche (et l'éventuelle jointure vers
  les détails du RDV — que le salon a le droit de voir) se fait **à la lecture** (endpoint §1) ou dans le
  futur worker de remise, **jamais** copiée dans `notifications`.
- **Registre de jetons d'appareil (device token FCM).** Toujours absent ; sans objet pour une
  notification salon dont le canal « dashboard » est `IN_APP`.
- **Écran mobile.** Le salon utilise le **web** (`/gerant`) ; aucun changement `app-mobile/`.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, **portée salon §11.2** | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Notifications | **FCM + SMS via file Redis**, WhatsApp V2, **remise asynchrone différée** ; stub no-op au MVP | [0006](../docs/adr/0006-notifications-fcm-sms.md) |
| Confirmation de RDV (#45) | ligne `notifications` `CONFIRMATION` persistée atomiquement, remise différée | [0033](../docs/adr/0033-notification-confirmation-rdv.md) |
| Rappels (#46) | rappels `REMINDER` datés (`scheduled_for`), statut `CANCELLED`, remise différée | [0034](../docs/adr/0034-rappel-automatique-avant-rdv.md) |
| Réservation | `POST /salons/{id}/appointments` (`PENDING`), unité de travail | [0023](../docs/adr/0023-moteur-disponibilite-anti-double-reservation.md) / [0024](../docs/adr/0024-reservation-cote-client.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0034** (rappels, #46). L'ajout d'un type de notification salon +
son émission (et l'éventuel endpoint de lecture salon-scopé) justifie un **court ADR-0035**
« Notification au salon à la réservation — ligne `NEW_BOOKING`/`IN_APP` persistée atomiquement, lecture
salon-scopée (deny-by-default, isolation §11.2), remise email/SMS différée M5 » (voir *Documentation
Updates*).

### Patrons à réutiliser tels quels

- **Trio domaine / port / adapter de notification (#45/#46)** — gabarit direct pour ajouter le
  constructeur de notification salon (`build_salon_new_booking_notification`) ; le port `enqueue` et
  l'adapter `SqlNotificationRepository.enqueue` **suffisent tels quels** (aucune nouvelle méthode
  d'écriture requise — la ligne salon est une `NotificationToCreate` de plus).
- **Écriture métier + effet transverse dans la même `Session`** — `BookAppointment` émet déjà
  confirmation (#45) et rappels (#46) sur la **même** `Session`. **Modèle direct** : ajouter l'émission
  salon au même endroit, avec le `owner_id` déjà disponible sur le `Salon` chargé.
- **Migration Alembic chaînée + `CHECK` dérivé de l'enum** — dernière révision livrée
  `0006_notification_scheduling` (`down_revision = "0005"`) ; #47 ajoute
  `0007_notification_new_booking_type` (`down_revision = "0006"`). Ajouter une valeur à
  `NotificationType` suppose de **régénérer** la contrainte `CHECK` de `type` (`ck_notifications_type`,
  drop + recreate) — **exactement** le patron du `CHECK` `status` régénéré par `0006` pour `CANCELLED`.
- **(Si endpoint de lecture retenu) Route salon-scopée deny-by-default** — patron
  `GET /salons/{salon_id}/services` (#17), `GET /salons/{salon_id}/appointments` (#26),
  `GET /salons/{salon_id}/payments` (#35) : garde `require_salon_scope` + permission dédiée, **filtre
  `salon_id` ré-affirmé en SQL** (défense en profondeur §11.2), lecture **read-only** paginée sans PII.
- **Injection surchargeable en test** — providers `get_*_repository(session)` +
  `app.dependency_overrides` ; `FakeNotificationRepository` (mémoire, `tests/conftest.py`) accumule
  `enqueued` — à **réutiliser tel quel** pour vérifier l'émission salon (une `NotificationToCreate`
  `NEW_BOOKING` supplémentaire) ; e2e adossés à un vrai PostgreSQL, sautés si `DATABASE_URL` absent ;
  garde deny-by-default (`tests/test_security_guards.py::unprotected_routes`).

### Schéma déjà en place (source de vérité : `models.py`, migrations `0001` + `0006`)

- `notifications` : `user_id`/`salon_id`/`appointment_id` **nullable** (FK `RESTRICT`), `type`
  (`CHECK` = `NotificationType` — **pas de valeur salon**), `channel` (`CHECK` = `NotificationChannel`,
  **`IN_APP` présent**), `title` (**NOT NULL**), `message` (**NOT NULL**), `status` (défaut `PENDING`,
  `CHECK` = `NotificationStatus`), `sent_at` (nullable), `scheduled_for` (nullable, #46), `created_at`.
  Index `ix_notifications_user_id`, `ix_notifications_salon_id (salon_id, created_at)` — **ce dernier
  sert directement** un tri salon-scopé « plus récentes d'abord » (endpoint §1).
- `salons` : `owner_id` (FK `users.id`) — **le gérant du salon**. Exposé sur le read-model
  `domain/salon.py::Salon.owner_id`, déjà chargé par `_load_bookable_salon(...)` dans `BookAppointment`.
- `appointments` : `client_id`, `salon_id`, `hairdresser_id`, `appointment_date`, `start_time`, etc. —
  le RDV que le salon a le droit de consulter (jointure possible à la **lecture**, pas au stockage).

### Contraintes transverses documentées

- **PRD §8.4** : une **annulation doit notifier le client et le salon** ; **une confirmation après
  chaque réservation** ; les **notifications critiques doivent être tracées**. (#47 matérialise le volet
  « le salon apprend la réservation » ; le volet annulation → #48.)
- **PRD §11.2** : **isolation par salon** — un gérant ne voit **que** son salon (endpoint de lecture §1 :
  garde `require_salon_scope` + filtre SQL).
- **PRD §11.3 / §11.4 / ADR-0006** : collecte minimale, **non-fuite de PII**, **ne jamais journaliser**
  corps de message / numéros / identifiants ; **clés email/SMS/FCM hors dépôt** (#5) ; trace des actions
  critiques.
- **PRD §12.1** : réponse API < 3 s → la remise réelle (et l'ordonnancement) restent **hors** chemin
  requête. #47 n'ajoute qu'**un** INSERT local (et une lecture indexée pour l'endpoint §1).
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test).

## Proposed Implementation

Approche recommandée en **trois volets** : **(A/B/C/D) émission/trace atomique** de la notification
salon (cœur de l'AC, requis) ; **(E, recommandé)** endpoint de lecture salon-scopé + surface `/gerant`
pour matérialiser le « dashboard » ; **(F, différé)** remise proactive email/SMS (worker M5+, **hors
périmètre**). Aucun envoi réel, aucun ordonnanceur, aucun secret.

### (A) Data model — migration `0007_notification_new_booking_type` (nouveau)

- **Valeur d'enum** : ajouter `NotificationType.NEW_BOOKING = "NEW_BOOKING"` (`domain/enums.py`). Le
  modèle `models.Notification` dérive automatiquement son `CHECK` de l'enum
  (`enum_check("type", enums.NotificationType, name="type")`) — **aucune** modification de `models.py`
  autre que ce reflet automatique.
- **Régénération du `CHECK` `type`** dans la migration (le `CHECK` en base est figé au déploiement, pas
  dérivé à chaud) : `op.drop_constraint(op.f("ck_notifications_type"), "notifications", type_="check")`
  puis `op.create_check_constraint("type", "notifications", "type IN ('CONFIRMATION', 'REMINDER',
  'CANCELLATION', 'NEW_BOOKING')")`. `downgrade()` symétrique (recreate sans `NEW_BOOKING`). **Aucun
  backfill** : les lignes existantes portent des valeurs déjà autorisées. Le libellé `"NEW_BOOKING"`
  (11 caractères) tient dans `type String(32)`.
- **Aucune** nouvelle colonne, **aucun** nouvel index requis (le tri salon-scopé réutilise
  `ix_notifications_salon_id (salon_id, created_at)`).
- Round-trip Alembic (`upgrade`/`downgrade` `0007`) vérifié en CI (`backend` job, PostgreSQL 16).

> **Nommage à confirmer (mineur)** : `NEW_BOOKING` (recommandé) vs `SALON_NEW_BOOKING` /
> `BOOKING_RECEIVED`. `NEW_BOOKING` est concis et clair ; la valeur est un identifiant technique figé une
> fois choisie.

### (B) Backend — domaine : notification salon pure (`domain/notification.py`, étendre)

- **Libellés templatés neutres** : `NEW_BOOKING_TITLE` / `NEW_BOOKING_MESSAGE`, p. ex.
  `"Nouvelle réservation"` / `"Un nouveau rendez-vous a été réservé dans votre salon."` — **aucune PII**
  (ni nom, ni téléphone, ni date/heure du client ; ces détails, que le salon a le droit de voir, sont
  résolus **à la lecture** via `appointment_id`, pas stockés).
- **`build_salon_new_booking_notification(*, owner_id, salon_id, appointment_id, channel) ->
  NotificationToCreate`** : assemble une `NotificationToCreate` (`type = NEW_BOOKING`, `status =
  PENDING`, `scheduled_for = None`, `title`/`message` templatés), avec **`user_id = owner_id`** (le
  gérant), `salon_id`, `appointment_id`. Aucun `raise` (données déjà validées par la réservation).
  Gabarit direct : `build_confirmation_notification`.
- **Canal** : le canal « dashboard » est **`IN_APP`**. Deux options d'implémentation, à trancher (voir
  §6 des *Open Questions*) :
  - **Recommandée (explicite)** : passer `channel = NotificationChannel.IN_APP.value` — le canal salon
    n'est **pas** « selon disponibilité » (téléphone/push), c'est le canal du tableau de bord.
  - **Alternative (réutiliser la résolution)** : `resolve_notification_channel(ChannelAvailability(
    has_push_token=False, has_phone=False))` retourne `IN_APP` — mais sémantiquement moins clair (le
    gérant *a* un téléphone) ; à éviter, car cela ferait basculer vers SMS si l'on renseignait
    `has_phone=True` par erreur.

### (C) Backend — port & adapter (aucune nouvelle méthode d'écriture)

- Le port `NotificationRepository.enqueue(notification)` et
  `SqlNotificationRepository.enqueue(...)` **couvrent déjà** l'insertion : la notification salon est une
  `NotificationToCreate` de plus (avec `scheduled_for = None`). **Aucune** modification du port ni de
  l'adapter d'écriture. `cancel_pending_for_appointment` (#46) n'est **pas** concerné (il cible
  `type = REMINDER`, jamais `NEW_BOOKING`).

### (D) Backend — cas d'usage `BookAppointment` (`application/appointments.py`, étendre)

- Après l'INSERT réussi du RDV, l'émission de la confirmation (#45) et la planification des rappels
  (#46), **émettre la notification salon** dans la **même** `Session` :
  ```python
  self._notifications.enqueue(
      build_salon_new_booking_notification(
          owner_id=salon.owner_id,          # `salon` est déjà chargé (aucun accès base en plus)
          salon_id=salon_id,
          appointment_id=appointment.id,
          channel=NotificationChannel.IN_APP.value,
      )
  )
  return appointment
  ```
  - `salon` est le `Salon` retourné par `_load_bookable_salon(self._catalog, salon_id)` en début de
    `execute(...)` — `salon.owner_id` est disponible **sans** dépendance ni requête supplémentaire.
  - **Aucune** nouvelle dépendance de `BookAppointment` (`notification_repository` existe déjà).
  - **Une** réservation → **une** notification salon (pas une par prestation ni par échéance). En cas de
    réservation échouée (`SlotUnavailable`/`SlotAlreadyBooked`/…), le point n'est jamais atteint / la
    transaction est rollbackée → **aucune** notification salon (parité confirmation/rappels).
- **Ne pas** émettre de notification salon dans `ModifyAppointment`/`CancelAppointment`/
  `SetAppointmentStatus`/`AssignHairdresser` (périmètre #48). Les docstrings de ces cas d'usage restent
  inchangées quant à l'absence de notification **salon** ; leur commentaire actuel « annulation des
  rappels (#46) » reste valide.

### (E) Backend — (recommandé) endpoint de lecture salon-scopé « dashboard »

*But : matérialiser « Notification dashboard » — le salon **lit** ses notifications de nouvelle
réservation. À trancher (voir §1) ; sinon, s'abstenir et livrer A–D seulement (backend-only émission,
comme #45).*

- **Permission** : ajouter `Permission.NOTIFICATION_READ_SALON = "NOTIFICATION_READ_SALON"`
  (`domain/permissions.py`) et l'accorder au **`MANAGER`** dans `ROLE_PERMISSIONS` (suffixe `_SALON` =
  portée salon, convention existante). Mettre à jour les **tests de matrice RBAC** qui figent
  `ROLE_PERMISSIONS`.
- **Cas d'usage lecture** : `ListSalonNotifications` (lecture pure, **aucun** audit — consulter un
  tableau de bord n'est pas journalisé §11.4) → port `NotificationReadRepository.list_for_salon(salon_id,
  *, types=(NEW_BOOKING,), limit, offset)` (filtre `salon_id` **et** `type` en SQL, tri
  `created_at DESC` via `ix_notifications_salon_id`). Domaine de lecture neutre
  `SalonNotificationView` (id, type, channel, title, message, status, created_at, `appointment_id`) —
  **sans PII** ; l'enrichissement RDV (date/heure/prestation) est laissé au web (jointure séparée) ou
  déféré.
- **Route** : `GET /salons/{salon_id}/notifications` — garde
  `require_permission(Permission.NOTIFICATION_READ_SALON)` + `require_salon_scope` (isolation §11.2,
  patron `GET /salons/{salon_id}/payments` #35). Réponse paginée `200`, `403` hors portée, **jamais**
  publique (pas dans `PUBLIC_ROUTE_PATHS`). **Documenter** la route (OpenAPI) — nouvelle API publique.
- **Web `/gerant` (léger, optionnel)** : indicateur/liste des nouvelles réservations dans le shell
  gérant, consommant la route via le BFF existant. Peut être **minimal** (compteur + liste read-only) ou
  déféré à une story UI dédiée si l'effort **S** doit rester backend.

### (F) Backend — (différé, hors périmètre) remise email/SMS « option »

Le **worker M5+** (Épic 7, ADR-0006) interrogera les lignes `NEW_BOOKING` `PENDING` et remettra, **en
option**, un email/SMS au gérant (résolution `owner_id → users.email/phone` **à l'envoi** ; jamais copiée
dans `notifications`), puis passera `SENT` + `sent_at`. **#47 ne le construit pas** (ni port
`NotificationSender`, ni scheduler, ni fournisseur email/SMS) — cohérent avec #45/#46. Ajouter un point
d'accroche maintenant = code mort/non testé (recommandation : s'abstenir ; consigner dans l'ADR).

### (G) Trace §8.4/§11.4 — la ligne `notifications` est la trace

Comme #45/#46, la **ligne persistée** (`type = NEW_BOOKING`, canal, statut, `created_at`, `sent_at`
ultérieur) **est** la trace exigée. **Recommandation** : ne pas ajouter de double trace `audit_logs`
(l'audit du **RDV** créé, s'il existe, relève de #21) — la table `notifications` est le registre dédié.
Aucune action ajoutée à `AuditAction`.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `migrations/versions/0007_notification_new_booking_type.py` | **nouveau** — `NotificationType.NEW_BOOKING` : drop + recreate du `CHECK` `ck_notifications_type` (up/down symétriques) |
| `coiflink_api/domain/enums.py` | **modifier** — `NotificationType.NEW_BOOKING` |
| `coiflink_api/domain/notification.py` | **modifier** — `NEW_BOOKING_TITLE`/`NEW_BOOKING_MESSAGE`, `build_salon_new_booking_notification(...)` ; export dans `__all__` |
| `coiflink_api/application/appointments.py` | **modifier** — `BookAppointment.execute` émet la notification salon (`owner_id = salon.owner_id`, `channel = IN_APP`) dans la même `Session` ; docstring de `BookAppointment` mise à jour |
| `coiflink_api/adapters/inbound/appointments.py` | **modifier** — docstring OpenAPI de `book_appointment` (mention « le salon est notifié ») ; **(si §E)** provider + route `GET /salons/{salon_id}/notifications` |
| `coiflink_api/domain/permissions.py` | **(si §E) modifier** — `NOTIFICATION_READ_SALON` + `ROLE_PERMISSIONS[MANAGER]` |
| `coiflink_api/application/ports/notification_repository.py` | **(si §E) modifier** — port de lecture `list_for_salon(...)` (ou nouveau port `NotificationReadRepository`) |
| `coiflink_api/adapters/outbound/persistence/notification_repository.py` | **(si §E) modifier** — implémenter la lecture salon-scopée (filtre `salon_id` + `type`, tri `created_at DESC`) |
| `backend/README.md` | section « Notifications (au salon à la réservation) » : émission `NEW_BOOKING`/`IN_APP` atomique, non-remise (option email/SMS M5), **(si §E)** endpoint de lecture salon-scopé |

### Backend — tests

| Fichier | Contenu |
| --- | --- |
| `tests/test_notification_domain.py` | **étendre** — `build_salon_new_booking_notification` : `type == NEW_BOOKING`, `channel == IN_APP`, `status == PENDING`, `scheduled_for is None`, `user_id == owner_id`, `salon_id`/`appointment_id` liés, `title`/`message` **non vides, sans PII** |
| `tests/test_appointment_usecases.py` | **étendre** — `BookAppointment` émet **1** `NEW_BOOKING` ciblant `salon.owner_id` **en plus** de la confirmation (#45) et des rappels (#46) ; **aucune** notification salon sur réservation échouée ; atomicité (même `Session`, via le fake) ; les autres cas d'usage (`Cancel`/`SetStatus`/`Modify`) **n'émettent pas** de `NEW_BOOKING` |
| `tests/test_appointment_api.py` | **étendre** — `POST .../appointments` → `201` **inchangé** + notification salon enregistrée (assertion sur le fake) ; un échec (`404`/`409`/`422`) n'enregistre **aucune** notification salon |
| `tests/test_security_guards.py` | **vérifier** — `POST` inchangé ; **(si §E)** `GET /salons/{salon_id}/notifications` **protégé** (absent de `PUBLIC_ROUTE_PATHS`) ; matrice RBAC figée |
| `tests/test_appointment_notification_e2e.py` | **étendre** (PostgreSQL réel) — réservation → **1** ligne `type=NEW_BOOKING` `status=PENDING` `channel=IN_APP`, `user_id = owner`, `salon_id`/`appointment_id` liés, `sent_at IS NULL`, **sans** PII ; conflit de créneau (`409`) → **aucune** notification (rollback conjoint) ; nettoyage : supprimer `notifications` **avant** `appointments`/`users`/`salons` (FK `RESTRICT`) |
| `tests/test_notification_read_api.py` *(si §E)* | **nouveau** — `GET /salons/{salon_id}/notifications` : `200` liste read-only du bon salon (plus récentes d'abord), `403` hors portée (isolation §11.2), aucune PII |
| `tests/conftest.py` | **réutiliser** `FakeNotificationRepository` (`enqueued`) pour l'émission ; **(si §E)** fake de lecture salon-scopée |

### Backend — à lire (sans modifier)

`adapters/outbound/persistence/appointment_repository.py` (`create`, atomicité),
`adapters/outbound/persistence/session.py` (`get_session`, commit par requête), `domain/salon.py`
(`Salon.owner_id`), `adapters/inbound/salon_scope.py`/garde `require_salon_scope` (patron #35, si §E),
`domain/permissions.py` + tests de matrice RBAC (si §E), migration `0006_notification_scheduling`
(gabarit de régénération de `CHECK`), `otp_sender_stub.py` (non-journalisation).

### Documentation (racine)

`README.md` (§6 : phrase de statut « M5 : notification au salon à la réservation (US-7.3, #47) »),
nouvel ADR `docs/adr/0035-notification-salon-a-la-reservation.md` + index `docs/adr/README.md`.

### Mobile (`app-mobile/`)

**Aucun** changement (le salon utilise le web `/gerant`).

## API / Interface Changes

- **`POST /salons/{salon_id}/appointments`** (#21/#22) — enrichit son **comportement interne** : émet
  désormais aussi **une** notification salon `NEW_BOOKING` (en plus de la confirmation #45 et des rappels
  #46). **Contrat inchangé** : réponse `201 AppointmentResponse`, mêmes statuts d'erreur.
- **`GET /salons/{salon_id}/notifications`** — **nouvelle route** *(si §E retenu)* : lecture salon-scopée
  read-only des notifications `NEW_BOOKING` du salon (paginée, plus récentes d'abord), garde
  `NOTIFICATION_READ_SALON` + `require_salon_scope`. **API publique à documenter** (OpenAPI, README).
  `403` hors portée, jamais dans `PUBLIC_ROUTE_PATHS`. **Si §E est différé : aucun nouvel endpoint.**
- **CLI / interfaces web/mobile** : aucun changement CLI. Web `/gerant` : ajout optionnel/léger (si §E).
- **Nouvelle variable d'environnement** : **aucune** au MVP (la remise email/SMS et l'ordonnanceur, avec
  leurs secrets, en auront — différés M5+, #5).

## Data Model / Protocol Changes

**Migration `0007_notification_new_booking_type` requise** :

- **Nouvelle valeur d'enum** `NotificationType.NEW_BOOKING` → **régénération** de la contrainte `CHECK`
  `ck_notifications_type` (`drop_constraint` + `create_check_constraint` avec la liste incluant
  `NEW_BOOKING`). **Aucun backfill** (les lignes existantes portent des valeurs déjà valides).
- **Aucune** nouvelle colonne, **aucun** nouvel index (le tri salon-scopé réutilise
  `ix_notifications_salon_id (salon_id, created_at)`).
- `NotificationChannel.IN_APP` et `NotificationStatus.PENDING` **existent déjà** (aucun changement).
- Round-trip Alembic (`upgrade`/`downgrade` `0007`) vérifié en CI (`backend` job, PostgreSQL 16).

> Sérialisation : la notification salon ne stocke **aucun montant**, **aucun** horodatage d'échéance
> (`scheduled_for = NULL`), **aucune** PII — seulement des identifiants opaques et un `title`/`message`
> templaté. Le `user_id` de la ligne est celui du **gérant** (`salon.owner_id`), pas du client.

## Security & Privacy Considerations

- **Non-fuite de PII (§11.3, ADR-0006).** La ligne `NEW_BOOKING` ne stocke **que** des identifiants
  opaques (`user_id = owner`, `salon_id`, `appointment_id`) et un `title`/`message` **templaté neutre** —
  **jamais** le nom/téléphone du client, ni un secret. Le worker de remise (futur) résoudra
  `owner_id → users.email/phone` **à l'envoi** ; ces valeurs ne sont **jamais** copiées.
- **Non-journalisation du contenu (ADR-0006).** L'adapter d'écriture (`enqueue`) et `BookAppointment`
  n'émettent **aucun** `logger`/`print` du destinataire, du canal ni du corps. Le stub OTP (référence de
  non-journalisation) n'est pas sollicité.
- **Isolation par salon (§11.2, ADR-0015).** Le `user_id` de la notification est **imposé serveur**
  (`salon.owner_id`, jamais soumis). **(Si §E)** l'endpoint de lecture applique `require_salon_scope`
  **et** ré-affirme le filtre `salon_id` en SQL (défense en profondeur) : un gérant ne lit **que** les
  notifications de **son** salon ; deny-by-default intact (nouvelle permission `NOTIFICATION_READ_SALON`,
  figée par la matrice RBAC).
- **Atomicité (§11.4).** L'émission se fait dans la **même** `Session` que l'INSERT du RDV
  (`get_session`, commit/rollback conjoint) : pas de notification salon « fantôme » sur une réservation
  échouée, pas de RDV créé sans sa notification salon.
- **Remise différée = aucune exposition externe.** Aucun appel email/SMS/FCM, aucun ordonnanceur : rien
  n'est transmis à un tiers. **Clés/identifiants email/SMS/FCM restent hors dépôt** (#5) — #47 n'en
  introduit ni n'en committe aucun.
- **Budget de latence (§12.1).** L'émission ajoute **un** INSERT local ; **(si §E)** la lecture est une
  requête indexée paginée — **aucun** I/O réseau externe. Les routes restent bien sous 3 s.

Le dépôt **documente** ces contraintes (PRD §8.4/§11.2/§11.3/§11.4/§12.1, ADR-0006/0033/0034) : #47 les
respecte sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires domaine (`pytest`, sans I/O)

- **`tests/test_notification_domain.py`** (étendre) : `build_salon_new_booking_notification` →
  `type == "NEW_BOOKING"`, `channel == "IN_APP"`, `status == "PENDING"`, `scheduled_for is None`,
  `user_id == owner_id`, `salon_id`/`appointment_id` rattachés, `title`/`message` **non vides et sans
  PII** (assertions négatives : la sortie ne contient ni numéro, ni nom fournis en entrée — elle
  n'accepte d'ailleurs aucune de ces données).

### Backend — cas d'usage (`pytest`, fakes de `conftest.py`)

- **`tests/test_appointment_usecases.py`** (étendre), `FakeNotificationRepository` :
  - **réservation (succès)** : `enqueued` contient **1** `CONFIRMATION` (#45) + **N** `REMINDER` (#46) +
    **1** `NEW_BOOKING` dont `user_id == salon.owner_id`, `salon_id`/`appointment_id` corrects.
  - **réservation (échec)** : `SlotUnavailable`/`SlotAlreadyBooked`/… → **aucune** notification (ni
    client, ni salon).
  - **atomicité** : l'émission salon passe par la **même** `Session`/le même port que le RDV (ordre/
    appels via le fake).
  - **périmètre** : `Cancel`/`SetStatus`/`Modify` n'ajoutent **aucune** ligne `NEW_BOOKING`.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_appointment_api.py`** (étendre) : `POST .../appointments` → `201` **inchangé** +
  notification salon enregistrée (assertion fake) ; un échec (`404`/`409`/`422`) n'enregistre **aucune**
  notification salon.
- **`tests/test_security_guards.py`** : `POST` inchangé ; **(si §E)** `GET
  /salons/{salon_id}/notifications` **absent** de `PUBLIC_ROUTE_PATHS` ; matrice RBAC (`MANAGER` ⊇
  `NOTIFICATION_READ_SALON`, autres rôles exclus) figée.
- **`tests/test_notification_read_api.py`** *(si §E)* : `200` liste du bon salon (plus récentes d'abord,
  pagination) ; `403` pour un gérant d'un autre salon (isolation §11.2) ; réponse sans PII.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_appointment_notification_e2e.py`** (étendre, patron existant #45/#46 — plage de numéros
  réservée, nettoyage avant/après ; `notifications` supprimé **avant** `appointments`/`users`/`salons`,
  FK `RESTRICT`) :
  1. réservation → **1** ligne `type=NEW_BOOKING` `status=PENDING` `channel=IN_APP`, `user_id = owner`,
     `salon_id`/`appointment_id` liés, `scheduled_for IS NULL`, `sent_at IS NULL`, **sans** PII ; +
     les lignes `CONFIRMATION` (#45) et `REMINDER` (#46) inchangées.
  2. conflit de créneau (`409`) → **aucune** notification (rollback conjoint).
  3. la ligne respecte les contraintes réelles (FK `RESTRICT`, `CHECK` `type` **incluant** `NEW_BOOKING`,
     `CHECK` `channel`/`status`).
  4. **(si §E)** `GET /salons/{salon_id}/notifications` renvoie la notification pour le gérant du salon,
     `403` pour un autre gérant.

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test **web** + flutter test **mobile inchangé**) au vert ;
`ruff check` propre ; **round-trip Alembic** (`upgrade`/`downgrade` `0007`) vert ; aucune régression sur
la réservation (#21/#22), la confirmation (#45) ni les rappels (#46).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Notifications (au salon à la réservation) » : à la
  réservation, **une** notification `NEW_BOOKING` `IN_APP` `PENDING` est **émise/tracée** vers le
  **gérant** (`salon.owner_id`) dans la même transaction que le RDV ; la **remise proactive** email/SMS
  (« option ») est **différée M5+** (ADR-0006) — rien n'est envoyé, `sent_at` reste `NULL`. Préciser :
  **migration `0007`** (valeur d'enum `NEW_BOOKING`), canal « dashboard » = `IN_APP`, **(si §E)**
  endpoint de lecture salon-scopé + permission `NOTIFICATION_READ_SALON`.
- **`README.md`** (racine) — §6 : phrase de statut « **M5** : notification au salon à la réservation
  (US-7.3, #47) — à la création d'un RDV, une notification `NEW_BOOKING`/`IN_APP` est **émise/tracée**
  dans `notifications` vers le gérant (`salon.owner_id`), même unité de travail que la réservation ;
  **option email/SMS** de remise proactive différée (ADR-0006) », dans le style existant.
- **`docs/adr/0035-notification-salon-a-la-reservation.md`** (**nouvel ADR**) : figer (a) la
  notification salon comme **ligne `notifications` `NEW_BOOKING`/`IN_APP` persistée atomiquement** à la
  réservation, ciblant `salon.owner_id` ; (b) la **migration `0007`** (valeur d'enum + régénération du
  `CHECK` `type`) ; (c) le canal « dashboard » `IN_APP` vs remise **optionnelle** email/SMS différée
  M5+ ; (d) **le périmètre strict** (création uniquement — annulation/modification = #48) ; (e) la
  décision **lecture salon-scopée** (endpoint `GET /salons/{salon_id}/notifications` + permission
  `NOTIFICATION_READ_SALON`, isolation §11.2) **ou** son report. Mettre à jour `docs/adr/README.md`.
- **OpenAPI** — docstring de `book_appointment` (mention « le salon est notifié à la réservation ») ;
  **(si §E)** documenter la nouvelle route de lecture (résumé, réponses `200/403`).

## Risks and Open Questions

1. **Portée « dashboard » : émission seule (backend-only) vs émission + endpoint de lecture salon-scopé.**
   Le backlog dit « Notification **dashboard** » ; l'AC est « le salon est **notifié** ». Persister une
   ligne sans lecture satisfait l'AC **au sens de la trace** (parité #45, dont ADR-0033 a *reporté*
   `GET /me/notifications`), mais le salon ne **voit** rien. *Recommandation : livrer A–D (émission/trace,
   requis) **et** l'endpoint de lecture salon-scopé §E (léger, isolation §11.2), car « dashboard » est
   explicite et différencie #47 de #45.* Repli acceptable si l'effort **S** doit rester minimal :
   backend-only émission, endpoint de lecture déféré. **À trancher et consigner dans l'ADR-0035.**
2. **Type dédié `NEW_BOOKING` (recommandé) vs réutiliser `CONFIRMATION`.** Réutiliser `CONFIRMATION` avec
   `user_id = owner` **évite la migration** mais mélange les sémantiques (confirmation *client* vs
   *nouvelle réservation reçue par le salon*), casse le filtrage par type du dashboard et l'invariant
   « une ligne `CONFIRMATION` = la confirmation du client ». *Recommandation : ajouter `NEW_BOOKING`
   (migration `0007`, régénération du `CHECK` `type`) — patron déjà éprouvé par `0006`.* **À trancher.**
3. **Destinataire = gérant (`salon.owner_id`).** La notification salon cible le **propriétaire** du
   salon. Faut-il aussi notifier les **coiffeurs** (le coiffeur assigné, s'il y en a un) ? *Recommandation :
   non au MVP — une notification au gérant (`owner_id`) suffit à l'AC « le salon est notifié » ; notifier
   des destinataires multiples est une évolution (préférences).* **À confirmer.**
4. **Canal `IN_APP` explicite vs résolution.** *Recommandation : passer `channel = IN_APP` explicitement*
   (la notification salon est « dashboard », pas « selon disponibilité » téléphone/push), plutôt que de
   détourner `resolve_notification_channel`. **À confirmer.**
5. **Nom de la valeur d'enum.** `NEW_BOOKING` (recommandé) vs `SALON_NEW_BOOKING`/`BOOKING_RECEIVED`.
   Identifiant technique figé une fois choisi. **À confirmer (mineur).**
6. **Nom / octroi de la permission (si §E).** `NOTIFICATION_READ_SALON` pour le `MANAGER` (suffixe
   `_SALON`, convention existante). Impacte la **matrice RBAC** (tests figés). **À confirmer.**
7. **Enrichissement à la lecture (si §E).** La ligne stocke des ids opaques + texte neutre ; le
   dashboard voudra afficher date/heure/prestation. *Recommandation : jointure `appointment_id → RDV`
   **à la lecture** (le salon a le droit de voir ses propres RDV — ce n'est pas de la PII tierce de son
   point de vue), **sans** copier ces données dans `notifications`.* **À confirmer.**
8. **Statut initial `PENDING` (honnête).** Comme #45/#46, `PENDING` + `sent_at = NULL` ; le worker M5+
   passera `SENT` lors de la remise **optionnelle** email/SMS. Ne **pas** marquer `SENT` au MVP
   (mensonger). **À confirmer.**
9. **Une notification par réservation.** L'AC vise « à chaque nouvelle réservation » → **une** ligne par
   `BookAppointment` réussi (pas une par prestation ni par rappel). *À vérifier par test* qu'aucun chemin
   ne double la notification salon.
10. **ADR dédié.** *Recommandation : oui* — court **ADR-0035** figeant émission/trace + type/canal +
    périmètre (création uniquement) + décision lecture + non-remise M5. **À confirmer.**

## Implementation Checklist

1. **Vérifier l'état livré & trancher.** Relire le trio notification (#45/#46 :
   `domain/notification.py`, `application/ports/notification_repository.py`,
   `adapters/outbound/persistence/notification_repository.py`), `BookAppointment` (émission confirmation
   #45 + rappels #46, `salon.owner_id` disponible), `domain/enums.py` (`NotificationType` **sans** valeur
   salon), la dernière migration `0006` (patron de régénération du `CHECK`), `domain/salon.py`
   (`Salon.owner_id`). **Trancher** les questions ouvertes 1–10 ; consigner dans un **ADR-0035**.
2. **Migration** : créer `0007_notification_new_booking_type` (`down_revision = "0006"`) — ajouter
   `NotificationType.NEW_BOOKING` (`domain/enums.py`), **régénérer** le `CHECK` `ck_notifications_type`
   (drop + recreate incluant `NEW_BOOKING`) ; `downgrade` symétrique. Vérifier le **round-trip**
   `upgrade`/`downgrade` sur PostgreSQL 16.
3. **Domaine** : étendre `domain/notification.py` — `NEW_BOOKING_TITLE`/`NEW_BOOKING_MESSAGE`,
   `build_salon_new_booking_notification(*, owner_id, salon_id, appointment_id, channel)` (pur, sans PII,
   `type=NEW_BOOKING`, `channel=IN_APP`, `status=PENDING`, `scheduled_for=None`) ; export `__all__`.
   Étendre `tests/test_notification_domain.py`.
4. **Cas d'usage** : dans `BookAppointment.execute`, après la confirmation/les rappels, émettre **une**
   notification salon (`owner_id = salon.owner_id`, `channel = IN_APP`) via `enqueue`, même `Session` ;
   mettre à jour la docstring. Étendre `tests/test_appointment_usecases.py` (1 `NEW_BOOKING` ciblant
   `owner_id` en plus ; aucune sur échec ; atomicité ; autres cas d'usage inchangés).
5. **Adapter entrant** : mettre à jour la docstring OpenAPI de `book_appointment` ; **aucune** route
   ajoutée pour le cœur A–D. Étendre `tests/test_appointment_api.py`.
6. **(Si §E) Lecture salon-scopée** : ajouter `NOTIFICATION_READ_SALON` (`domain/permissions.py` +
   `ROLE_PERMISSIONS[MANAGER]` + tests de matrice) ; port/adapter de lecture (`list_for_salon`, filtre
   `salon_id`+`type`, tri `created_at DESC`) ; cas d'usage `ListSalonNotifications` ; route
   `GET /salons/{salon_id}/notifications` (garde permission + `require_salon_scope`, **hors**
   `PUBLIC_ROUTE_PATHS`) ; `tests/test_notification_read_api.py` + `tests/test_security_guards.py`.
7. **e2e** : étendre `tests/test_appointment_notification_e2e.py` (réservation → 1 `NEW_BOOKING`
   `PENDING` `IN_APP` liée au gérant/salon/RDV, `sent_at IS NULL`, sans PII ; conflit `409` → aucune
   notification ; **(si §E)** lecture salon-scopée + `403` hors portée). Exécuter `pytest`
   (+ `DATABASE_URL`, `alembic upgrade head`) et `ruff check`.
8. **Documentation** : section `backend/README.md` ; phrase de statut `README.md` racine (M5) ;
   `docs/adr/0035-notification-salon-a-la-reservation.md` + index `docs/adr/README.md` ; docstrings
   OpenAPI (`book_appointment`, **et** la route de lecture si §E).
9. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test **web** + flutter test
   **mobile inchangé**), `ruff check`, round-trip Alembic vert ; relire la PR pour garantir qu'**aucun**
   numéro, nom, secret ni contenu de message n'apparaît dans les logs ; que la notification salon est
   **émise dans la même transaction** que le RDV et **ciblée sur `salon.owner_id`** ; qu'**une seule**
   notification salon part par réservation ; qu'une réservation échouée n'en laisse **aucune** ; que
   **rien n'est réellement « envoyé »** (non-remise assumée, `PENDING`, `sent_at NULL`, ADR-0006) ; que
   le **périmètre** reste la **création** (annulation/modification = #48) ; et qu'**aucune signature IA**
   n'a été introduite.
