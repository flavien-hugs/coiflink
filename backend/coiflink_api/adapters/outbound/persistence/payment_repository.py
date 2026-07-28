"""Adapter sortant : persistance des **paiements** (SQLAlchemy, US-5.1/5.3, #33/#34).

Implémente le port `PaymentRepository` sur une `Session` SQLAlchemy 2.0 et le
modèle ORM `models.Payment` (table `payments` du schéma `0001`). Seul cet adapter
connaît SQLAlchemy ; il mappe les entités de domaine ↔ modèles ORM.

**Invariant append-only / non-suppression (§8.2).** Cet adapter n'expose **aucune**
méthode `delete` : un paiement validé n'est **jamais** supprimé. La seule mutation
est `mark_adjusted` — un `UPDATE status` borné (`VALIDATED → ADJUSTED`), filtré
`(salon_id, id)`. Comme les autres dépôts, les écritures sont `flush`ées **sans
commit** : le commit (ou rollback) est piloté par `get_session`, ce qui rend la
mutation atomique avec la ligne `cash_journal` et l'entrée d'audit (§11.4).

**Isolation §11.2 au niveau du dépôt** : `get`/`mark_adjusted` filtrent sur le
couple `(salon_id, id)` — impossible de lire/corriger le paiement d'un autre salon
même si l'`id` est deviné (miroir de `SqlCustomerRepository`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import PaymentStatus
from coiflink_api.domain.errors import PaymentNotAdjustable, PaymentNotFound
from coiflink_api.domain.payment import Payment, PaymentToCreate


class SqlPaymentRepository:
    """Dépôt de paiements adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, payment: PaymentToCreate) -> Payment:
        """Insère le paiement (statut `VALIDATED`, US-5.1) — `flush` sans `commit`."""

        row = models.Payment(
            salon_id=payment.salon_id,
            appointment_id=payment.appointment_id,
            service_id=payment.service_id,
            client_id=payment.client_id,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=payment.payment_method,
            status=payment.status,
            recorded_by=payment.recorded_by,
            reference=payment.reference,
        )
        self._session.add(row)
        # `flush` déclenche l'INSERT (et les contraintes) sans committer.
        self._session.flush()
        # Recharge les valeurs générées côté serveur (id, created_at, status défaut).
        self._session.refresh(row)
        return _to_domain(row)

    def get(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        """Charge le paiement `(salon_id, payment_id)` — filtre d'isolation §11.2."""

        row = self._get_row(salon_id, payment_id)
        if row is None:
            raise PaymentNotFound("Paiement introuvable.")
        return _to_domain(row)

    def mark_adjusted(self, salon_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        """Passe le paiement à `status = ADJUSTED` (US-5.3) — **jamais** un delete.

        Filtre `(salon_id, id)` (isolation §11.2) → `PaymentNotFound` si hors
        salon/inconnu ; garde de transition (seul un `VALIDATED` est corrigible) →
        `PaymentNotAdjustable` sinon. Seule la colonne `status` est écrite ; la ligne
        et son montant d'origine subsistent. `flush` sans `commit` (atomicité).
        """

        row = self._get_row(salon_id, payment_id)
        if row is None:
            raise PaymentNotFound("Paiement introuvable.")
        if row.status != PaymentStatus.VALIDATED.value:
            raise PaymentNotAdjustable("Ce paiement ne peut pas être corrigé.")
        row.status = PaymentStatus.ADJUSTED.value
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def _get_row(
        self, salon_id: uuid.UUID, payment_id: uuid.UUID
    ) -> models.Payment | None:
        stmt = select(models.Payment).where(
            models.Payment.salon_id == salon_id,
            models.Payment.id == payment_id,
        )
        return self._session.scalar(stmt)


def _to_domain(row: models.Payment) -> Payment:
    return Payment(
        id=row.id,
        salon_id=row.salon_id,
        amount=row.amount,
        currency=row.currency,
        payment_method=row.payment_method,
        status=row.status,
        recorded_by=row.recorded_by,
        appointment_id=row.appointment_id,
        service_id=row.service_id,
        client_id=row.client_id,
        reference=row.reference,
        created_at=row.created_at,
    )


__all__ = ["SqlPaymentRepository"]
