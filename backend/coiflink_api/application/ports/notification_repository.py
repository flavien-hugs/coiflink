"""Port d'écriture des **notifications** (`Protocol`, US-7.1 #45, US-7.2 #46).

Les cas d'usage `application/appointments.py::BookAppointment`/`CancelAppointment`/
`SetAppointmentStatus`/`ModifyAppointment` **émettent**/**annulent** des notifications
via ce port ; l'implémentation SQLAlchemy (`SqlNotificationRepository`) vit dans
`adapters/outbound/persistence/notification_repository.py`. Le domaine
(`domain/notification.py`) définit *ce qui* est émis (`NotificationToCreate`) ; ce port
définit *qu'on écrit*/*qu'on annule*, sans dire *comment*. Gabarit : `application/ports/audit_log.py`.

Le nom **`enqueue`** (et non `send`) est délibéré : rien n'est acheminé ici. La ligne
`notifications` `PENDING` **est la file** que consommera le worker de remise (M5+,
ADR-0006) et **la trace** de la notification critique (§8.4/§11.4). Aucune méthode de
lecture n'est exposée (pas d'endpoint client au périmètre #45/#46).

**`cancel_pending_for_appointment`** (#46) annule (marque `CANCELLED`) tous les
rappels `PENDING` d'un RDV — appelée quand le RDV est annulé (client ou refus gérant),
pour satisfaire l'AC « l'annulation du RDV annule le rappel » (§8.4).

**Atomicité** : l'implémentation écrit/annule dans la **même unité de travail** (même
`Session`) que l'écriture métier du RDV — committées (ou rollbackées) **ensemble**.
Pas de confirmation/rappel « fantôme » sur une réservation échouée, ni de RDV annulé
laissant un rappel `PENDING` derrière lui.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.notification import NotificationToCreate, SalonNotification


class NotificationRepository(Protocol):
    """Contrat d'écriture (et d'annulation) des notifications."""

    def list_for_salon(
        self, salon_id: uuid.UUID, *, limit: int
    ) -> tuple[SalonNotification, ...]:
        """Dernières notifications **du salon**, de la plus récente à la plus ancienne (#148).

        Lecture **bornée** (`limit`, top-N) des lignes `notifications` dont
        `salon_id = :salon_id`, triées `created_at DESC, id DESC` (déterministe).
        Projette **uniquement** `(created_at, type, title, message, appointment_id)` —
        contenu **déjà neutre** (ADR-0006), **jamais** `user_id`, canal ni destinataire.
        Alimente la timeline d'activité (§7.2) ; **matérialise** la lecture salon
        différée par #47/#48 (parité, **sans** remise). L'isolation §11.2 est imposée
        **en SQL** (`WHERE salon_id`), couverte par `ix_notifications_salon_id
        (salon_id, created_at)`. Lecture pure (aucun `flush`).
        """
        ...

    def enqueue(self, notification: NotificationToCreate) -> None:
        """Persiste une notification dans la même unité de travail (sans acheminer).

        Insère la ligne (`flush`, **sans commit** : l'unité de travail est pilotée par
        `get_session`). Ne journalise **jamais** le destinataire ni le contenu
        (invariant du dépôt, PRD §11.3 / ADR-0006).
        """
        ...

    def cancel_pending_for_appointment(self, appointment_id: uuid.UUID) -> None:
        """Annule (marque `CANCELLED`) les rappels `PENDING` d'un RDV (US-7.2, #46).

        Ne touche que les lignes `type = REMINDER` `status = PENDING` rattachées à
        `appointment_id` — jamais la confirmation (#45), déjà émise et non annulable.
        `flush`, **sans commit** : même unité de travail que l'écriture du statut du
        RDV. Idempotent (aucune ligne à annuler → no-op).
        """
        ...


__all__ = ["NotificationRepository"]
