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

import decimal
import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    escape_like,
)
from coiflink_api.domain.discrepancy import (
    COMPLETED_STATUS,
    PAID_PAYMENT_STATUSES,
    CashDiscrepancy,
    DiscrepancyFilter,
)
from coiflink_api.domain.enums import PaymentStatus
from coiflink_api.domain.errors import PaymentNotAdjustable, PaymentNotFound
from coiflink_api.domain.payment import DEFAULT_CURRENCY, Payment, PaymentToCreate
from coiflink_api.domain.transaction import Transaction, TransactionFilter

# Pas de comparaison de montant : le centime (miroir de `NUMERIC(12,2)`), pour
# quantifier le montant attendu agrégé en `Decimal` (jamais un flottant).
_AMOUNT_QUANTUM = decimal.Decimal("0.01")


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

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        filter: TransactionFilter,
        limit: int,
        offset: int,
    ) -> tuple[Transaction, ...]:
        """Page **filtrée** des transactions du salon (US-5.2, #35) — lecture seule.

        Filtre `salon_id` **inconditionnel** (isolation §11.2) + clauses de filtre
        **conditionnelles** (date/client/montant/mode, combinées en ET), tri
        `created_at DESC, id DESC`, bornes en SQL. Join restreint à
        `users.full_name` (jamais d'autre PII, §11.3) pour l'affichage. **Aucune**
        écriture, aucun `flush`.
        """

        stmt = (
            select(models.Payment, models.User.full_name)
            .outerjoin(models.User, models.User.id == models.Payment.client_id)
            .where(*self._filter_clauses(salon_id, filter))
            .order_by(models.Payment.created_at.desc(), models.Payment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return tuple(
            Transaction(payment=_to_domain(row), client_name=full_name)
            for row, full_name in self._session.execute(stmt).all()
        )

    def count_for_salon(
        self, salon_id: uuid.UUID, *, filter: TransactionFilter
    ) -> int:
        """Nombre total de transactions du salon **sous le même filtre** (pagination)."""

        stmt = (
            select(func.count())
            .select_from(models.Payment)
            .outerjoin(models.User, models.User.id == models.Payment.client_id)
            .where(*self._filter_clauses(salon_id, filter))
        )
        return int(self._session.scalar(stmt) or 0)

    @staticmethod
    def _filter_clauses(
        salon_id: uuid.UUID, filter: TransactionFilter
    ) -> Sequence[ColumnElement[bool]]:
        """Clauses `WHERE` : `salon_id` inconditionnel + critères présents (ET).

        Partagées **à l'identique** par `list_for_salon` et `count_for_salon` pour
        que le `total` corresponde exactement à la page. La clause `q` suppose la
        jointure `models.User` déjà présente dans les deux requêtes appelantes
        (`outerjoin` sur `client_id`, relation 1:1 — ne multiplie jamais les lignes).
        """

        clauses: list[ColumnElement[bool]] = [models.Payment.salon_id == salon_id]
        if filter.created_at_from is not None:
            clauses.append(models.Payment.created_at >= filter.created_at_from)
        if filter.created_at_to is not None:
            clauses.append(models.Payment.created_at <= filter.created_at_to)
        if filter.client_id is not None:
            clauses.append(models.Payment.client_id == filter.client_id)
        if filter.amount_min is not None:
            clauses.append(models.Payment.amount >= filter.amount_min)
        if filter.amount_max is not None:
            clauses.append(models.Payment.amount <= filter.amount_max)
        if filter.payment_method is not None:
            clauses.append(models.Payment.payment_method == filter.payment_method)
        if filter.q is not None:
            clauses.append(
                models.User.full_name.ilike(f"%{escape_like(filter.q)}%", escape="\\")
            )
        return clauses

    def list_completed_without_payment(
        self,
        salon_id: uuid.UUID,
        *,
        filter: DiscrepancyFilter,
        limit: int,
        offset: int,
    ) -> tuple[CashDiscrepancy, ...]:
        """Page des **écarts de caisse** du salon (US-5.4, #36) — lecture seule.

        RDV `COMPLETED` sans paiement `VALIDATED`/`ADJUSTED` rattaché (`NOT EXISTS`
        sur `payments.appointment_id`), filtre `salon_id` **inconditionnel**
        (isolation §11.2) + bornes de dates conditionnelles sur `appointment_date`.
        Le `LEFT JOIN appointment_services` + `GROUP BY` calcule le **montant
        attendu** (somme des `price_at_booking`) ; le join `users` (restreint à
        `full_name`, §11.3) résout le nom du client. Tri déterministe, bornes en SQL.
        **Aucune** écriture, aucun `flush`.
        """

        expected_amount = func.coalesce(
            func.sum(models.AppointmentService.price_at_booking), 0
        )
        stmt = (
            select(
                models.Appointment.id,
                models.Appointment.appointment_date,
                models.Appointment.start_time,
                models.Appointment.client_id,
                models.User.full_name,
                expected_amount,
            )
            .outerjoin(models.User, models.User.id == models.Appointment.client_id)
            .outerjoin(
                models.AppointmentService,
                (models.AppointmentService.salon_id == models.Appointment.salon_id)
                & (models.AppointmentService.appointment_id == models.Appointment.id),
            )
            .where(*self._discrepancy_clauses(salon_id, filter))
            .group_by(
                models.Appointment.id,
                models.Appointment.appointment_date,
                models.Appointment.start_time,
                models.Appointment.client_id,
                models.User.full_name,
            )
            .order_by(
                models.Appointment.appointment_date.desc(),
                models.Appointment.start_time.desc(),
                models.Appointment.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(
            CashDiscrepancy(
                appointment_id=appointment_id,
                salon_id=salon_id,
                appointment_date=appointment_date,
                start_time=start_time,
                client_id=client_id,
                expected_amount=decimal.Decimal(amount).quantize(_AMOUNT_QUANTUM),
                client_name=full_name,
                currency=DEFAULT_CURRENCY,
            )
            for (
                appointment_id,
                appointment_date,
                start_time,
                client_id,
                full_name,
                amount,
            ) in self._session.execute(stmt).all()
        )

    def count_completed_without_payment(
        self, salon_id: uuid.UUID, *, filter: DiscrepancyFilter
    ) -> int:
        """Nombre total d'écarts du salon **sous le même filtre** (pagination).

        Compte les **RDV** (jamais les lignes de prestation : pas de join
        `appointment_services`) sous les **mêmes** clauses `WHERE`/`NOT EXISTS` que
        `list_completed_without_payment`.
        """

        stmt = (
            select(func.count())
            .select_from(models.Appointment)
            .where(*self._discrepancy_clauses(salon_id, filter))
        )
        return int(self._session.scalar(stmt) or 0)

    @staticmethod
    def _discrepancy_clauses(
        salon_id: uuid.UUID, filter: DiscrepancyFilter
    ) -> Sequence[ColumnElement[bool]]:
        """Clauses `WHERE` des écarts : salon + `COMPLETED` + `NOT EXISTS` payé + dates.

        Partagées **à l'identique** par `list_completed_without_payment` et
        `count_completed_without_payment` (total cohérent avec la page). Le filtre
        `salon_id` est **inconditionnel** (isolation §11.2) ; la sous-requête
        `NOT EXISTS` porte elle aussi `salon_id` (un paiement d'un autre salon ne
        couvre jamais un RDV).
        """

        paid_exists = (
            select(models.Payment.id)
            .where(
                models.Payment.salon_id == models.Appointment.salon_id,
                models.Payment.appointment_id == models.Appointment.id,
                models.Payment.status.in_(PAID_PAYMENT_STATUSES),
            )
            .exists()
        )
        clauses: list[ColumnElement[bool]] = [
            models.Appointment.salon_id == salon_id,
            models.Appointment.status == COMPLETED_STATUS,
            ~paid_exists,
        ]
        if filter.date_from is not None:
            clauses.append(models.Appointment.appointment_date >= filter.date_from)
        if filter.date_to is not None:
            clauses.append(models.Appointment.appointment_date <= filter.date_to)
        return clauses

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
