"""Port de persistance des **paiements** (`Protocol`, US-5.1/5.3, #33/#34).

Le cas d'usage (`application/payments.py`, `application/cash_journal.py`) déclare
ici ses besoins ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/payment_repository.py`. Conformément à l'hexagonal
(ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Invariant append-only / non-suppression (§8.2).** Ce port n'expose **aucune**
méthode `delete` : un paiement validé n'est **jamais** supprimé. La seule mutation
autorisée est `mark_adjusted` — un passage de statut `VALIDATED → ADJUSTED` (la
ligne et son montant d'origine subsistent). L'absence de verbe destructif **dans le
port** est un choix de conception, vérifié par les tests de sécurité.

**Isolation §11.2 au niveau du dépôt** : toutes les méthodes portant sur un
paiement existant prennent `salon_id` **en plus** de l'identifiant et filtrent sur
le couple `(salon_id, id)`. Un paiement d'un autre salon est **indiscernable d'un
paiement inexistant** — impossible de le lire/corriger même si l'`id` est deviné.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.payment import Payment, PaymentToCreate


class PaymentRepository(Protocol):
    """Contrat de persistance des paiements d'un salon (append + statut, jamais delete)."""

    def create(self, payment: PaymentToCreate) -> Payment:
        """Insère et retourne le paiement enregistré (statut `VALIDATED`, US-5.1).

        Le `salon_id` et l'auteur (`recorded_by`) proviennent de la portée validée
        et du principal — jamais du corps. `created_at` est généré côté serveur
        (horodatage non falsifiable §8.2).
        """
        ...

    def get(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        """Retourne le paiement `(salon_id, payment_id)` ; lève `PaymentNotFound`.

        Le filtre porte sur `salon_id` **et** `id` (isolation §11.2) : un paiement
        d'un autre salon est indiscernable d'un paiement inexistant (aucun oracle).
        """
        ...

    def mark_adjusted(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        """Passe le paiement `(salon_id, payment_id)` à `status = ADJUSTED` (US-5.3).

        **Jamais** une suppression : une mutation de **statut** bornée
        (`VALIDATED → ADJUSTED`). Le filtre `(salon_id, id)` (isolation §11.2) et la
        garde de transition (seul un `VALIDATED` est corrigible) évitent d'altérer
        un paiement hors salon ou dans un état non corrigible — lève
        `PaymentNotFound` (hors salon/inconnu) ou `PaymentNotAdjustable` (état
        incompatible). `flush()` sans `commit()` (atomicité avec le journal/l'audit).
        """
        ...


__all__ = ["PaymentRepository"]
