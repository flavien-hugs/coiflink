"""Adapter sortant : lecture des **reçus numériques** (SQLAlchemy, US-5.5, #38).

Implémente le port `ReceiptRepository` sur une `Session` SQLAlchemy 2.0 et les
modèles ORM `Payment`/`Salon`/`AppointmentService`/`Service` (schéma `0001`). Seul
cet adapter connaît SQLAlchemy ; il mappe les lignes ↔ projections de domaine.

**Lecture seule.** Aucune méthode n'écrit : le reçu est **dérivé** de tables
existantes, jamais persisté. Aucune migration côté paiement.

**Appartenance §11.2 au niveau du dépôt** : `payments.client_id = client_id` est
un filtre **inconditionnel** de toutes les requêtes — un paiement d'un autre client
(ou sans `client_id`) est indiscernable d'un paiement inexistant (non-oracle §11.3).

Les **lignes** de prestation sont résolues par paiement :

- paiement lié à un **RDV** (`appointment_id`) → `appointment_services` jointes à
  `services` pour le libellé courant + `price_at_booking` **figé** ;
- paiement lié à une **prestation seule** (`service_id`) → `services.name` +
  `Service.price`.

Le nombre de reçus d'une page étant borné (`RECEIPTS_LIMIT_MAX`), la résolution des
lignes par paiement reste bornée ; seule `salons.name` est jointe pour l'identité
publique (jamais `owner_id` ni PII de gestion, §11.3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.receipt import Receipt, ReceiptLine, format_receipt_number


class SqlReceiptRepository:
    """Dépôt de lecture des reçus adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_receipts_for_client(
        self,
        client_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Receipt, ...]:
        """Page des reçus du client, plus récents d'abord — filtre d'appartenance §11.2."""

        stmt = (
            select(models.Payment, models.Salon.name)
            .join(models.Salon, models.Salon.id == models.Payment.salon_id)
            .where(models.Payment.client_id == client_id)
            .order_by(models.Payment.created_at.desc(), models.Payment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.execute(stmt).all()
        return tuple(
            self._to_receipt(payment, salon_name) for payment, salon_name in rows
        )

    def count_receipts_for_client(self, client_id: uuid.UUID) -> int:
        """Nombre total de reçus du client (pagination), même filtre d'appartenance."""

        stmt = (
            select(func.count())
            .select_from(models.Payment)
            .where(models.Payment.client_id == client_id)
        )
        return int(self._session.scalar(stmt) or 0)

    def get_receipt_for_client(
        self, client_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Receipt | None:
        """Reçu `(client_id, payment_id)` ou `None` (non-oracle §11.3)."""

        stmt = (
            select(models.Payment, models.Salon.name)
            .join(models.Salon, models.Salon.id == models.Payment.salon_id)
            .where(
                models.Payment.client_id == client_id,
                models.Payment.id == payment_id,
            )
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        payment, salon_name = row
        return self._to_receipt(payment, salon_name)

    def get_receipt_for_salon(
        self, salon_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Receipt | None:
        """Reçu `(salon_id, payment_id)` ou `None` (impression gérant, ADR-0040).

        Portée **salon**, pas `client_id` : inclut les paiements comptoir sans
        client (`outerjoin` sur `User`, jamais `join` — un `client_id` `NULL` ne
        doit pas exclure la ligne). Peuple `client_name`/`client_phone` — seule
        cette lecture les renseigne (§11.3 : le client n'a pas besoin qu'on lui
        rappelle sa propre identité).
        """

        stmt = (
            select(models.Payment, models.Salon.name, models.User.full_name, models.User.phone)
            .join(models.Salon, models.Salon.id == models.Payment.salon_id)
            .outerjoin(models.User, models.User.id == models.Payment.client_id)
            .where(
                models.Payment.salon_id == salon_id,
                models.Payment.id == payment_id,
            )
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        payment, salon_name, client_name, client_phone = row
        return self._to_receipt(
            payment, salon_name, client_name=client_name, client_phone=client_phone
        )

    def _to_receipt(
        self,
        payment: models.Payment,
        salon_name: str,
        *,
        client_name: str | None = None,
        client_phone: str | None = None,
    ) -> Receipt:
        return Receipt(
            receipt_number=format_receipt_number(payment.receipt_number),
            payment_id=payment.id,
            salon_id=payment.salon_id,
            salon_name=salon_name,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=payment.payment_method,
            status=payment.status,
            reference=payment.reference,
            paid_at=payment.created_at,
            appointment_id=payment.appointment_id,
            lines=self._lines_for_payment(payment),
            client_name=client_name,
            client_phone=client_phone,
        )

    def _lines_for_payment(
        self, payment: models.Payment
    ) -> tuple[ReceiptLine, ...]:
        """Lignes de prestation d'un reçu : RDV (`price_at_booking`) ou prestation seule."""

        if payment.appointment_id is not None:
            stmt = (
                select(
                    models.Service.name,
                    models.AppointmentService.price_at_booking,
                )
                .join(
                    models.Service,
                    (models.Service.salon_id == models.AppointmentService.salon_id)
                    & (models.Service.id == models.AppointmentService.service_id),
                )
                .where(
                    models.AppointmentService.salon_id == payment.salon_id,
                    models.AppointmentService.appointment_id == payment.appointment_id,
                )
                .order_by(models.Service.name)
            )
            return tuple(
                ReceiptLine(service_name=name, amount=price)
                for name, price in self._session.execute(stmt).all()
            )

        if payment.service_id is not None:
            stmt = select(models.Service.name, models.Service.price).where(
                models.Service.salon_id == payment.salon_id,
                models.Service.id == payment.service_id,
            )
            row = self._session.execute(stmt).first()
            if row is None:
                return ()
            name, price = row
            return (ReceiptLine(service_name=name, amount=price),)

        return ()


__all__ = ["SqlReceiptRepository"]
