"""Domaine pur des **notifications applicatives** (US-7.1 #45, US-7.2 #46, US-7.3 #47).

Le domaine définit *ce qu'est* une notification à créer et *comment se choisit son
canal* — sans rien savoir de la persistance (table SQL) ni de l'acheminement réel
(FCM/SMS). L'écriture est un port (`application/ports/notification_repository.py`) ;
l'implémentation vit dans `adapters/outbound/persistence/notification_repository.py`.
Gabarit direct : `domain/audit.py` (`AuditEntry` `frozen`, sans I/O).

#45 est la **première** issue qui écrit dans la table `notifications` : à la création
d'un RDV, une **confirmation** est **émise/tracée** (ligne `CONFIRMATION` `PENDING`)
dans la même unité de travail que la réservation. #46 étend le domaine pour les
**rappels** (`REMINDER`) : une notification **datée** (`scheduled_for`), planifiée à
la réservation pour chaque échéance encore future (`24h`/`2h`/`30min` avant le début
du RDV) et annulée si le RDV l'est. Dans les deux cas, la **remise réelle** (push FCM
/ SMS via file Redis) reste **différée M5+** (ADR-0006) — rien n'est envoyé ici : la
ligne `PENDING` **est la file** et **la trace** de la notification critique (§8.4/§11.4).

#47 ajoute la notification destinée au **salon** (au gérant) à chaque nouvelle
réservation : `build_salon_new_booking_notification` assemble une ligne `NEW_BOOKING`
`IN_APP` `PENDING` rattachée à `salon.owner_id` (le gérant), au salon et au RDV — le
canal « dashboard » est `IN_APP`, la remise proactive **optionnelle** email/SMS reste
différée M5+ (ADR-0006). Un **destinataire différent** (le gérant, pas le client) est
la seule vraie différence avec la confirmation client.

Invariant de non-fuite (PRD §11.3/§11.4, ADR-0006) : une `NotificationToCreate` est
**neutre** — elle ne porte **jamais** de PII (ni téléphone, ni nom) ni de secret. Seuls
des identifiants **opaques** (`user_id`/`salon_id`/`appointment_id`), un `title`/
`message` **templaté** et, pour un rappel, un horodatage d'échéance (`scheduled_for`,
non-PII) y figurent. Le worker de remise (futur) résoudra `user_id → users.phone`
**à l'envoi** — le numéro n'est **jamais** copié dans la ligne.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

# Titre/corps **templatés et neutres** de la confirmation (§11.3 : aucune PII). Le RDV
# est créé au statut `PENDING` (« En attente », #22) : le message confirme que la
# **demande a bien été enregistrée**, sans affirmer que le salon l'a déjà validée. La
# composition riche (date/heure/salon — données que le client possède déjà) est laissée
# au worker de remise (M5+), pour minimiser ce qui est stocké dans `notifications`.
CONFIRMATION_TITLE = "Réservation enregistrée"
CONFIRMATION_MESSAGE = "Votre rendez-vous a bien été enregistré."

# Titre/corps **templatés et neutres** du rappel (§11.3 : aucune PII — pas de date,
# d'heure ni de nom de salon, données que le worker de remise composera à l'envoi).
REMINDER_TITLE = "Rappel de rendez-vous"
REMINDER_MESSAGE = "Vous avez un rendez-vous à venir."

# Titre/corps **templatés et neutres** de la notification **au salon** (US-7.3, #47 —
# §11.3 : aucune PII). Le salon apprend qu'**une** nouvelle réservation est arrivée ;
# les détails du RDV (date/heure/prestation/client — que le salon a le droit de voir)
# sont résolus **à la lecture** via `appointment_id`, jamais stockés dans la ligne.
NEW_BOOKING_TITLE = "Nouvelle réservation"
NEW_BOOKING_MESSAGE = "Un nouveau rendez-vous a été réservé dans votre salon."

# Titre/corps **templatés et neutres** des notifications d'**annulation** (US-7.4, #48 —
# §11.3 : aucune PII, jamais le **motif** — persisté sur le RDV, jamais recopié ici).
# Deux destinataires distincts, deux libellés : le **client** (« votre rendez-vous »)
# et le **salon** (« un rendez-vous de votre salon »).
CANCELLATION_TITLE = "Rendez-vous annulé"
CANCELLATION_MESSAGE = "Votre rendez-vous a été annulé."
SALON_CANCELLATION_TITLE = "Rendez-vous annulé"
SALON_CANCELLATION_MESSAGE = "Un rendez-vous de votre salon a été annulé."

# Titre/corps **templatés et neutres** des notifications de **changement de statut /
# modification** (US-7.4, #48 — §11.3 : aucune PII, ni ancien/nouveau statut ni
# ancien/nouveau créneau). `STATUS_UPDATE_*` va au **client** (le gérant a confirmé /
# clôturé / marqué absent son RDV) ; `SALON_MODIFICATION_*` va au **salon** (le client
# a modifié un RDV). Le détail (from/to, diff) vit dans `audit_logs`/sur le RDV, résolu
# à la lecture/remise — jamais copié dans la ligne `notifications`.
STATUS_UPDATE_TITLE = "Rendez-vous mis à jour"
STATUS_UPDATE_MESSAGE = "Le statut de votre rendez-vous a été mis à jour."
SALON_MODIFICATION_TITLE = "Rendez-vous modifié"
SALON_MODIFICATION_MESSAGE = "Un rendez-vous de votre salon a été modifié."

# Avances de rappel par défaut (« configurable 24h / 2h / 30 min », backlog #46) —
# jeu **fixe** au MVP, aucune préférence par client/salon (cf. spec, Open Questions §2).
REMINDER_OFFSETS: tuple[datetime.timedelta, ...] = (
    datetime.timedelta(hours=24),
    datetime.timedelta(hours=2),
    datetime.timedelta(minutes=30),
)


@dataclass(frozen=True)
class NotificationToCreate:
    """Champs à insérer dans `notifications` — pur, neutre (sans PII ni secret).

    Miroir des colonnes du modèle ORM `models.Notification`. `status` vaut `PENDING`
    par défaut : on **émet** (persiste) la notification sans l'**acheminer** — le
    worker M5+ passera `SENT` + `sent_at` à la remise réelle (ADR-0006).
    `scheduled_for` reste `None` pour une confirmation (à remettre au plus tôt) ;
    un rappel (US-7.2, #46) porte l'échéance à laquelle il devient remettable.
    """

    type: str
    channel: str
    title: str
    message: str
    user_id: uuid.UUID | None = None
    salon_id: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None
    status: str = NotificationStatus.PENDING.value
    scheduled_for: datetime.datetime | None = None


@dataclass(frozen=True)
class ChannelAvailability:
    """Signaux **non-PII** de disponibilité de canal (des booléens, jamais la valeur).

    Ne porte **jamais** le jeton d'appareil ni le numéro eux-mêmes : seulement le
    *fait* qu'ils soient connus (`has_push_token`/`has_phone`). Cela garde
    `resolve_notification_channel` pur et testable, sans PII.
    """

    has_push_token: bool = False
    has_phone: bool = False


def resolve_notification_channel(availability: ChannelAvailability) -> str:
    """Choisit le canal de notification « selon disponibilité » (fonction **pure**).

    Priorité **PUSH → SMS → IN_APP**. `WHATSAPP` est **exclu** (V2, ADR-0006) et
    `EMAIL` n'entre pas dans la confirmation/le rappel de RDV. Déterministe, sans I/O.
    Réutilisée telle quelle pour la confirmation (#45) **et** le rappel (#46) — un
    seul point de résolution de canal, pas de logique dupliquée.

    Au MVP, faute de **registre de jetons d'appareil**, `has_push_token` est toujours
    faux : le canal effectif est **SMS** (le client s'inscrit par téléphone, #8), avec
    `IN_APP` comme **repli garanti**. La branche PUSH reste prête pour l'activation
    d'un registre de jetons (story distincte).
    """

    if availability.has_push_token:
        return NotificationChannel.PUSH.value
    if availability.has_phone:
        return NotificationChannel.SMS.value
    return NotificationChannel.IN_APP.value


# Alias rétrocompatible (#45) : `resolve_confirmation_channel` est le nom d'origine,
# conservé pour ne pas casser les imports existants (usecases, tests). Généralisé en
# `resolve_notification_channel` par #46 (réutilisé par le rappel).
resolve_confirmation_channel = resolve_notification_channel


def build_confirmation_notification(
    *,
    client_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    channel: str,
) -> NotificationToCreate:
    """Assemble la confirmation **neutre** d'un RDV créé (`type = CONFIRMATION`).

    Rattache la notification au **client** (`user_id = client_id`), au salon et au RDV
    par identifiants **opaques** ; `title`/`message` sont **templatés** (aucune PII).
    `status` reste `PENDING` (non remis, ADR-0006), `scheduled_for` reste `None` (à
    remettre au plus tôt). Le `channel` est celui résolu par
    `resolve_notification_channel`. Aucun `raise` : les données sont déjà validées par
    la réservation.
    """

    return NotificationToCreate(
        type=NotificationType.CONFIRMATION.value,
        channel=channel,
        title=CONFIRMATION_TITLE,
        message=CONFIRMATION_MESSAGE,
        user_id=client_id,
        salon_id=salon_id,
        appointment_id=appointment_id,
    )


def build_salon_new_booking_notification(
    *,
    owner_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    channel: str,
) -> NotificationToCreate:
    """Assemble la notification **au salon** d'une nouvelle réservation (`NEW_BOOKING`).

    Rattache la notification au **gérant** (`user_id = owner_id`, jamais au client),
    au salon et au RDV par identifiants **opaques** ; `title`/`message` sont
    **templatés** (aucune PII — ni nom ni téléphone du client). `status` reste
    `PENDING` (non remis, ADR-0006), `scheduled_for` reste `None` (à remettre au plus
    tôt). Le `channel` est celui du **tableau de bord** (`IN_APP`) : la notification
    salon n'est pas « selon disponibilité » (le canal est fourni explicitement par
    l'appelant, cf. `application/appointments.py`). Aucun `raise` : les données sont
    déjà validées par la réservation. Gabarit direct : `build_confirmation_notification`.
    """

    return NotificationToCreate(
        type=NotificationType.NEW_BOOKING.value,
        channel=channel,
        title=NEW_BOOKING_TITLE,
        message=NEW_BOOKING_MESSAGE,
        user_id=owner_id,
        salon_id=salon_id,
        appointment_id=appointment_id,
    )


def build_client_cancellation_notification(
    *,
    client_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    channel: str,
) -> NotificationToCreate:
    """Assemble la notification d'annulation **au client** (`type = CANCELLATION`, #48).

    Sur **toute** transition `→ CANCELLED` (annulation client #24 **ou** refus gérant
    #25), le §8.4 impose de notifier le client. Rattache la notification au **client**
    (`user_id = client_id`), au salon et au RDV par identifiants **opaques** ;
    `title`/`message` sont **templatés** (aucune PII, jamais le motif). `status` reste
    `PENDING` (non remis, ADR-0006), `scheduled_for` reste `None`. Le `channel` est
    résolu « selon disponibilité » (SMS au MVP). Aucun `raise` : les données sont déjà
    validées par le changement de statut. Gabarit : `build_confirmation_notification`.
    """

    return NotificationToCreate(
        type=NotificationType.CANCELLATION.value,
        channel=channel,
        title=CANCELLATION_TITLE,
        message=CANCELLATION_MESSAGE,
        user_id=client_id,
        salon_id=salon_id,
        appointment_id=appointment_id,
    )


def build_salon_cancellation_notification(
    *,
    owner_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    channel: str,
) -> NotificationToCreate:
    """Assemble la notification d'annulation **au salon** (`type = CANCELLATION`, #48).

    Deuxième volet de la règle §8.4 (« une annulation notifie le client **et** le
    salon ») : rattache la notification au **gérant** (`user_id = owner_id`, jamais au
    client), au salon et au RDV par identifiants **opaques** ; `title`/`message` sont
    **templatés** (aucune PII, jamais le motif). `status` reste `PENDING`,
    `scheduled_for` reste `None`. Le `channel` « dashboard » est `IN_APP` (explicite,
    fourni par l'appelant, comme #47). Aucun `raise`. Gabarit :
    `build_salon_new_booking_notification`.
    """

    return NotificationToCreate(
        type=NotificationType.CANCELLATION.value,
        channel=channel,
        title=SALON_CANCELLATION_TITLE,
        message=SALON_CANCELLATION_MESSAGE,
        user_id=owner_id,
        salon_id=salon_id,
        appointment_id=appointment_id,
    )


def build_client_status_update_notification(
    *,
    client_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    channel: str,
) -> NotificationToCreate:
    """Assemble la notification de changement de statut **au client** (US-7.4, #48).

    Couvre les transitions gérant **autres** que l'annulation (`CONFIRMED`,
    `COMPLETED`, `NO_SHOW`) : « un changement de statut déclenche la notification à la
    partie concernée » (AC #48). Type dédié `APPOINTMENT_UPDATE` (migration `0008`) —
    distinct de `CONFIRMATION` (réservation #45). Rattache la notification au
    **client** (`user_id = client_id`), au salon et au RDV par identifiants
    **opaques** ; `title`/`message` sont **templatés** (aucune PII, ni ancien/nouveau
    statut). `status` reste `PENDING`, `scheduled_for` reste `None`. Le `channel` est
    résolu « selon disponibilité » (SMS au MVP). Aucun `raise`.
    """

    return NotificationToCreate(
        type=NotificationType.APPOINTMENT_UPDATE.value,
        channel=channel,
        title=STATUS_UPDATE_TITLE,
        message=STATUS_UPDATE_MESSAGE,
        user_id=client_id,
        salon_id=salon_id,
        appointment_id=appointment_id,
    )


def build_salon_modification_notification(
    *,
    owner_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    channel: str,
) -> NotificationToCreate:
    """Assemble la notification de **modification au salon** (US-7.4, #48).

    Quand un client **modifie** son RDV (#23), le salon est notifié (« annulation/
    **modification** », titre #48). Type dédié `APPOINTMENT_UPDATE` (migration
    `0008`). Rattache la notification au **gérant** (`user_id = owner_id`), au salon et
    au RDV par identifiants **opaques** ; `title`/`message` sont **templatés** (aucune
    PII, ni ancien/nouveau créneau). `status` reste `PENDING`, `scheduled_for` reste
    `None`. Le `channel` « dashboard » est `IN_APP` (explicite, comme #47). Aucun
    `raise`.
    """

    return NotificationToCreate(
        type=NotificationType.APPOINTMENT_UPDATE.value,
        channel=channel,
        title=SALON_MODIFICATION_TITLE,
        message=SALON_MODIFICATION_MESSAGE,
        user_id=owner_id,
        salon_id=salon_id,
        appointment_id=appointment_id,
    )


def compute_reminder_schedules(
    appointment_start: datetime.datetime,
    *,
    now: datetime.datetime,
    offsets: tuple[datetime.timedelta, ...] = REMINDER_OFFSETS,
) -> tuple[datetime.datetime, ...]:
    """Échéances de rappel **strictement futures** pour un début de RDV (fonction pure).

    Pour chaque `offset`, l'échéance vaut `appointment_start - offset` ; seules les
    échéances `> now` sont conservées (une échéance déjà passée au moment de la
    réservation — p. ex. le rappel `24h` d'un RDV pris 2 h à l'avance — n'est **pas**
    planifiée : aucune ligne « en retard » à la création, cf. spec §Goals). Un RDV très
    proche peut ne produire **aucune** échéance. Déterministe, sans I/O ; l'ordre suit
    `offsets` (donc du plus lointain au plus proche avec `REMINDER_OFFSETS`).
    """

    return tuple(
        due
        for offset in offsets
        if (due := appointment_start - offset) > now
    )


def build_reminder_notifications(
    *,
    client_id: uuid.UUID,
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    appointment_start: datetime.datetime,
    channel: str,
    now: datetime.datetime,
    offsets: tuple[datetime.timedelta, ...] = REMINDER_OFFSETS,
) -> tuple[NotificationToCreate, ...]:
    """Assemble les rappels **neutres** d'un RDV, un par échéance encore future.

    Une `NotificationToCreate` (`type = REMINDER`, `status = PENDING`) par échéance
    renvoyée par `compute_reminder_schedules` ; `scheduled_for` porte l'échéance,
    `title`/`message` sont **templatés** (aucune PII — pas de date/heure/salon, laissés
    au worker de remise). Aucun `raise` : les données sont déjà validées par la
    réservation. Peut renvoyer un tuple **vide** (RDV trop proche).
    """

    return tuple(
        NotificationToCreate(
            type=NotificationType.REMINDER.value,
            channel=channel,
            title=REMINDER_TITLE,
            message=REMINDER_MESSAGE,
            user_id=client_id,
            salon_id=salon_id,
            appointment_id=appointment_id,
            scheduled_for=due,
        )
        for due in compute_reminder_schedules(appointment_start, now=now, offsets=offsets)
    )


__all__ = [
    "CONFIRMATION_TITLE",
    "CONFIRMATION_MESSAGE",
    "REMINDER_TITLE",
    "REMINDER_MESSAGE",
    "REMINDER_OFFSETS",
    "NEW_BOOKING_TITLE",
    "NEW_BOOKING_MESSAGE",
    "CANCELLATION_TITLE",
    "CANCELLATION_MESSAGE",
    "SALON_CANCELLATION_TITLE",
    "SALON_CANCELLATION_MESSAGE",
    "STATUS_UPDATE_TITLE",
    "STATUS_UPDATE_MESSAGE",
    "SALON_MODIFICATION_TITLE",
    "SALON_MODIFICATION_MESSAGE",
    "NotificationToCreate",
    "ChannelAvailability",
    "resolve_notification_channel",
    "resolve_confirmation_channel",
    "build_confirmation_notification",
    "build_salon_new_booking_notification",
    "build_client_cancellation_notification",
    "build_salon_cancellation_notification",
    "build_client_status_update_notification",
    "build_salon_modification_notification",
    "compute_reminder_schedules",
    "build_reminder_notifications",
]
