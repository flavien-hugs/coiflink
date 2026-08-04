"""Domaine pur des **notifications applicatives** (US-7.1 #45, US-7.2 #46).

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
    "NotificationToCreate",
    "ChannelAvailability",
    "resolve_notification_channel",
    "resolve_confirmation_channel",
    "build_confirmation_notification",
    "compute_reminder_schedules",
    "build_reminder_notifications",
]
