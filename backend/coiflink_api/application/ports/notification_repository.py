"""Port d'écriture des **notifications** (`Protocol`, US-7.1, #45).

Le cas d'usage `application/appointments.py::BookAppointment` **émet** une confirmation
via ce port ; l'implémentation SQLAlchemy (`SqlNotificationRepository`) vit dans
`adapters/outbound/persistence/notification_repository.py`. Le domaine
(`domain/notification.py`) définit *ce qui* est émis (`NotificationToCreate`) ; ce port
définit *qu'on écrit*, sans dire *comment*. Gabarit : `application/ports/audit_log.py`.

Le nom **`enqueue`** (et non `send`) est délibéré : #45 **n'achemine rien**. La ligne
`notifications` `PENDING` **est la file** que consommera le worker de remise (M5+,
ADR-0006) et **la trace** de la notification critique (§8.4/§11.4). Aucune méthode de
lecture n'est exposée (pas d'endpoint client au périmètre #45).

**Atomicité** : l'implémentation écrit dans la **même unité de travail** (même
`Session`) que la création du RDV — la confirmation et le RDV sont committés (ou
rollbackés) **ensemble**. Pas de confirmation « fantôme » sur une réservation échouée,
ni de RDV sans sa confirmation.
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.notification import NotificationToCreate


class NotificationRepository(Protocol):
    """Contrat d'écriture des notifications."""

    def enqueue(self, notification: NotificationToCreate) -> None:
        """Persiste une notification dans la même unité de travail (sans acheminer).

        Insère la ligne (`flush`, **sans commit** : l'unité de travail est pilotée par
        `get_session`). Ne journalise **jamais** le destinataire ni le contenu
        (invariant du dépôt, PRD §11.3 / ADR-0006).
        """
        ...


__all__ = ["NotificationRepository"]
