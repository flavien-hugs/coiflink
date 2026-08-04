"""Adapter sortant : écriture des **notifications** (SQLAlchemy, US-7.1 #45, US-7.2 #46).

Implémente le port `NotificationRepository` en insérant/mettant à jour des lignes de la
table `notifications` (modèle ORM `models.Notification`, migration `0001` + `0006`).
Seul cet adapter connaît SQLAlchemy. Gabarit : `audit_log_repository.py::SqlAuditLog`.

**Atomicité** : l'écriture partage la **même `Session`** que l'écriture métier du RDV
(injectée via `get_session`) et est `flush`ée **sans commit** — notification et RDV
sont committés (ou rollbackés) **ensemble** : pas de confirmation/rappel « fantôme »
sur une réservation échouée, pas de RDV annulé laissant un rappel `PENDING`.

**Non-remise & non-fuite** (ADR-0006, §11.3) : cet adapter **n'achemine rien** (aucun
appel FCM/SMS) et ne **journalise jamais** le destinataire, le canal ni le corps du
message. Il recopie tel quel le contenu **déjà neutre** de `NotificationToCreate` (le
domaine garantit l'absence de PII/secret) ; `status` reste `PENDING`, `sent_at` `NULL`.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import NotificationStatus, NotificationType
from coiflink_api.domain.notification import NotificationToCreate


def _as_timestamptz(value: datetime.datetime | None) -> datetime.datetime | None:
    """Attache le fuseau UTC à un `scheduled_for` naïf avant écriture (colonne `TIMESTAMPTZ`).

    Le domaine calcule les échéances en naïf, dans le repère `Africa/Abidjan` (UTC+0,
    convention #21/`_now()`) — équivalent numérique à l'UTC. Attacher `UTC` ici (plutôt
    que de laisser psycopg deviner le fuseau de session) rend l'écriture déterministe.
    """

    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=datetime.timezone.utc)


class SqlNotificationRepository:
    """Écriture (et annulation) des notifications adossée à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, notification: NotificationToCreate) -> None:
        """Insère une notification dans la même unité de travail que le RDV.

        `flush()` sans `commit()` : la ligne est matérialisée (contraintes FK/CHECK
        vérifiées) mais committée **avec** l'écriture métier par `get_session`. Aucun
        `logger`/`print` du contenu ni du destinataire (ADR-0006).
        """

        row = models.Notification(
            user_id=notification.user_id,
            salon_id=notification.salon_id,
            appointment_id=notification.appointment_id,
            type=notification.type,
            channel=notification.channel,
            title=notification.title,
            message=notification.message,
            status=notification.status,
            scheduled_for=_as_timestamptz(notification.scheduled_for),
        )
        self._session.add(row)
        self._session.flush()

    def cancel_pending_for_appointment(self, appointment_id: uuid.UUID) -> None:
        """Annule (marque `CANCELLED`) les rappels `PENDING` d'un RDV (US-7.2, #46).

        `UPDATE` ciblé (`type = REMINDER` **et** `status = PENDING`) : ne touche jamais
        la confirmation (#45), déjà émise. `flush()` sans `commit()` — même unité de
        travail que le changement de statut du RDV. Idempotent (aucune ligne → no-op).
        """

        self._session.execute(
            update(models.Notification)
            .where(models.Notification.appointment_id == appointment_id)
            .where(models.Notification.type == NotificationType.REMINDER.value)
            .where(models.Notification.status == NotificationStatus.PENDING.value)
            .values(status=NotificationStatus.CANCELLED.value)
        )
        self._session.flush()


__all__ = ["SqlNotificationRepository"]
