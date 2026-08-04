"""Domaine pur des **notifications applicatives** (US-7.1, #45).

Le domaine définit *ce qu'est* une notification à créer et *comment se choisit son
canal* — sans rien savoir de la persistance (table SQL) ni de l'acheminement réel
(FCM/SMS). L'écriture est un port (`application/ports/notification_repository.py`) ;
l'implémentation vit dans `adapters/outbound/persistence/notification_repository.py`.
Gabarit direct : `domain/audit.py` (`AuditEntry` `frozen`, sans I/O).

#45 est la **première** issue qui écrit dans la table `notifications` : à la création
d'un RDV, une **confirmation** est **émise/tracée** (ligne `CONFIRMATION` `PENDING`)
dans la même unité de travail que la réservation. La **remise réelle** (push FCM / SMS
via file Redis) reste **différée M5+** (ADR-0006) — rien n'est envoyé ici : la ligne
`PENDING` **est la file** et **la trace** de la notification critique (§8.4/§11.4).

Invariant de non-fuite (PRD §11.3/§11.4, ADR-0006) : une `NotificationToCreate` est
**neutre** — elle ne porte **jamais** de PII (ni téléphone, ni nom) ni de secret. Seuls
des identifiants **opaques** (`user_id`/`salon_id`/`appointment_id`) et un `title`/
`message` **templaté** y figurent. Le worker de remise (futur) résoudra
`user_id → users.phone` **à l'envoi** — le numéro n'est **jamais** copié dans la ligne.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class NotificationToCreate:
    """Champs à insérer dans `notifications` — pur, neutre (sans PII ni secret).

    Miroir des colonnes du modèle ORM `models.Notification`. `status` vaut `PENDING`
    par défaut : #45 **émet** (persiste) la notification sans l'**acheminer** — le
    worker M5+ passera `SENT` + `sent_at` à la remise réelle (ADR-0006).
    """

    type: str
    channel: str
    title: str
    message: str
    user_id: uuid.UUID | None = None
    salon_id: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None
    status: str = NotificationStatus.PENDING.value


@dataclass(frozen=True)
class ChannelAvailability:
    """Signaux **non-PII** de disponibilité de canal (des booléens, jamais la valeur).

    Ne porte **jamais** le jeton d'appareil ni le numéro eux-mêmes : seulement le
    *fait* qu'ils soient connus (`has_push_token`/`has_phone`). Cela garde
    `resolve_confirmation_channel` pur et testable, sans PII.
    """

    has_push_token: bool = False
    has_phone: bool = False


def resolve_confirmation_channel(availability: ChannelAvailability) -> str:
    """Choisit le canal de confirmation « selon disponibilité » (fonction **pure**).

    Priorité **PUSH → SMS → IN_APP**. `WHATSAPP` est **exclu** (V2, ADR-0006) et
    `EMAIL` n'entre pas dans la confirmation de RDV. Déterministe, sans I/O.

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
    `status` reste `PENDING` (non remis, ADR-0006). Le `channel` est celui résolu par
    `resolve_confirmation_channel`. Aucun `raise` : les données sont déjà validées par
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


__all__ = [
    "CONFIRMATION_TITLE",
    "CONFIRMATION_MESSAGE",
    "NotificationToCreate",
    "ChannelAvailability",
    "resolve_confirmation_channel",
    "build_confirmation_notification",
]
