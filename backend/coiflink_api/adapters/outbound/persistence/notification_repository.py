"""Adapter sortant : écriture des **notifications** (SQLAlchemy, US-7.1, #45).

Implémente le port `NotificationRepository` en insérant une ligne dans la table
`notifications` (modèle ORM `models.Notification`, migration `0001`). Seul cet adapter
connaît SQLAlchemy. Gabarit : `audit_log_repository.py::SqlAuditLog`.

**Atomicité** : l'insertion partage la **même `Session`** que la création du RDV
(injectée via `get_session`) et est `flush`ée **sans commit** — la confirmation et le
RDV sont committés (ou rollbackés) **ensemble** : pas de confirmation « fantôme » sur
une réservation échouée, ni de RDV sans sa confirmation.

**Non-remise & non-fuite** (ADR-0006, §11.3) : cet adapter **n'achemine rien** (aucun
appel FCM/SMS) et ne **journalise jamais** le destinataire, le canal ni le corps du
message. Il recopie tel quel le contenu **déjà neutre** de `NotificationToCreate` (le
domaine garantit l'absence de PII/secret) ; `status` reste `PENDING`, `sent_at` `NULL`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.notification import NotificationToCreate


class SqlNotificationRepository:
    """Écriture des notifications adossée à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, notification: NotificationToCreate) -> None:
        """Insère une notification dans la même unité de travail que le RDV.

        `flush()` sans `commit()` : la ligne est matérialisée (contraintes FK/CHECK
        vérifiées) mais committée **avec** la création du RDV par `get_session`. Aucun
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
        )
        self._session.add(row)
        self._session.flush()


__all__ = ["SqlNotificationRepository"]
