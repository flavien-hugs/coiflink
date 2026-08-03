"""Adapter sortant : persistance du **journal de caisse** (SQLAlchemy, US-5.3, #34).

Implémente le port `CashJournalRepository` sur une `Session` SQLAlchemy 2.0 et le
modèle ORM `models.CashJournal` (table `cash_journal` du schéma `0001`). Seul cet
adapter connaît SQLAlchemy ; il mappe les entités de domaine ↔ modèles ORM.

**Invariant append-only (§8.2), porté par le code lui-même.** Cet adapter n'expose
**que** `append` (un `INSERT`) et deux lectures. Il ne fournit **aucune** méthode
`update`/`delete` : l'immuabilité du journal est **structurelle** (on ne peut pas
appeler ce qui n'existe pas). Une correction est une **nouvelle** ligne
`ADJUSTMENT`, jamais une réécriture. Comme les autres dépôts, `append` `flush`e
**sans commit** : le commit (ou rollback) est piloté par `get_session`, ce qui
rend l'écriture atomique avec la mutation du paiement et l'entrée d'audit (§11.4).

**Isolation §11.2 au niveau du dépôt** : les lectures prennent `salon_id` et
refiltrent systématiquement dessus ; l'écriture porte le `salon_id` de la portée
validée (et la FK composite `(salon_id, transaction_id) → payments` garantit en
base que la transaction liée appartient au même salon).

**Nom d'auteur en lecture (§11.3)** : la projection joint `users` pour résoudre le
**seul** `full_name` de l'auteur (staff du salon, non sensible dans ce périmètre) —
jamais son téléphone, son e-mail ni son condensat.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.cash_journal import CashJournalEntry, CashJournalToAppend
from coiflink_api.domain.enums import CashOperationType
from coiflink_api.domain.payment import DEFAULT_CURRENCY

# Précision de quantification du CA agrégé : le centime (miroir de `NUMERIC(12,2)`),
# pour rester en `Decimal` (jamais un flottant), comme `SqlPlatformTransactionRepository`.
_AMOUNT_QUANTUM = decimal.Decimal("0.01")

# Types d'opération qui **sont** du chiffre d'affaires : un paiement (`PAYMENT`) et
# sa correction éventuelle (`ADJUSTMENT`, delta signé). Le CA est ainsi **net des
# corrections** (#34), en cohérence avec le « montant net » de #37. Les autres types
# (`REFUND`/`CASH_OPENING`/`CASH_CLOSING`) ne sont pas du CA — et n'existent pas au MVP.
_REVENUE_OPERATION_TYPES = (
    CashOperationType.PAYMENT.value,
    CashOperationType.ADJUSTMENT.value,
)


class SqlCashJournalEntryRepository:
    """Dépôt du journal de caisse adossé à une `Session` SQLAlchemy (append + lectures)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, entry: CashJournalToAppend) -> CashJournalEntry:
        """Insère **une** ligne de journal (`INSERT` seul — append-only, §8.2)."""

        row = models.CashJournal(
            salon_id=entry.salon_id,
            transaction_id=entry.transaction_id,
            operation_type=entry.operation_type,
            amount=entry.amount,
            performed_by=entry.performed_by,
            description=entry.description,
        )
        self._session.add(row)
        # `flush` déclenche l'INSERT (et les contraintes FK) sans committer.
        self._session.flush()
        # Recharge les valeurs générées côté serveur (id, created_at).
        self._session.refresh(row)
        return _to_domain(row, self._full_name(entry.performed_by))

    def list_for_salon(
        self, salon_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[CashJournalEntry, ...]:
        """Page d'opérations du salon, **de la plus récente à la plus ancienne**.

        Tri `created_at DESC, id DESC` (déterministe). La projection **résout le
        nom d'affichage de l'auteur** (`performed_by → users.full_name`) via une
        jointure restreinte à cette seule colonne. Bornes appliquées en SQL.
        """

        stmt = (
            select(models.CashJournal, models.User.full_name)
            .join(models.User, models.User.id == models.CashJournal.performed_by)
            .where(models.CashJournal.salon_id == salon_id)
            .order_by(
                models.CashJournal.created_at.desc(),
                models.CashJournal.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(
            _to_domain(row, full_name) for row, full_name in self._session.execute(stmt).all()
        )

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        """Nombre total d'opérations du salon (total de pagination)."""

        stmt = (
            select(func.count())
            .select_from(models.CashJournal)
            .where(models.CashJournal.salon_id == salon_id)
        )
        return int(self._session.scalar(stmt) or 0)

    def net_revenue_between(
        self,
        salon_id: uuid.UUID,
        *,
        created_at_from: datetime.datetime,
        created_at_to: datetime.datetime,
    ) -> decimal.Decimal:
        """Somme **signée** du CA du salon sur `[created_at_from, created_at_to]` (US-6.2, #40).

        Somme `cash_journal.amount` des lignes `PAYMENT`/`ADJUSTMENT` du salon dont
        `created_at` est dans l'intervalle **inclus** — CA **net des corrections**
        (#34), miroir de `SqlPlatformTransactionRepository`. Isolation §11.2
        **réaffirmée en SQL** (`WHERE salon_id`). L'agrégat est calculé **en base**
        (`SUM`, jamais en mémoire), couvert par l'index
        `ix_cash_journal_salon_id (salon_id, created_at)`. Lecture pure : aucun
        `flush`. `Decimal("0.00")` si aucune ligne.
        """

        stmt = select(func.coalesce(func.sum(models.CashJournal.amount), 0)).where(
            models.CashJournal.salon_id == salon_id,
            models.CashJournal.created_at >= created_at_from,
            models.CashJournal.created_at <= created_at_to,
            models.CashJournal.operation_type.in_(_REVENUE_OPERATION_TYPES),
        )
        total = self._session.scalar(stmt) or 0
        return decimal.Decimal(total).quantize(_AMOUNT_QUANTUM)

    def net_revenue_by_hairdresser(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[uuid.UUID, decimal.Decimal]:
        """CA net **attribué par coiffeur** du salon sur une période (US-6.5, #43).

        Variante attribuée de `net_revenue_between` : somme **signée** des lignes
        `cash_journal` `PAYMENT`/`ADJUSTMENT` du salon, jointes au `payment`
        (`transaction_id → payments.id`) puis au RDV (`payments.appointment_id →
        appointments.id`), filtrées `appointments.hairdresser_id IS NOT NULL` et
        `appointments.appointment_date ∈ [date_from, date_to]` **inclus**,
        `GROUP BY appointments.hairdresser_id`. CA **net des corrections** (#34) : un
        `ADJUSTMENT` fait baisser le total du coiffeur.

        L'**attribution par le RDV** (join `payments.appointment_id`) porte le
        `hairdresser_id` **et** la borne `appointment_date` (axe **planning**, pas
        `cash_journal.created_at`) : le CA partage la période des prestations/annulations.
        Les lignes **sans `transaction_id`** ou dont le paiement n'a **pas** de RDV
        assigné (prestation directe, `appointment_id IS NULL`) sont **exclues** par les
        joins (inattribuables). Isolation §11.2 **réaffirmée en SQL**
        (`WHERE cash_journal.salon_id`), couverte par `ix_cash_journal_salon_id`.
        Lecture pure (aucun `flush`) ; renvoie `{hairdresser_id: Decimal}` quantifié au
        centime — **aucune** PII (ni `client_id`, ni `reference`, ni `recorded_by`).
        """

        stmt = (
            select(
                models.Appointment.hairdresser_id,
                func.coalesce(func.sum(models.CashJournal.amount), 0).label("net"),
            )
            .join(
                models.Payment,
                models.Payment.id == models.CashJournal.transaction_id,
            )
            .join(
                models.Appointment,
                models.Appointment.id == models.Payment.appointment_id,
            )
            .where(
                models.CashJournal.salon_id == salon_id,
                models.CashJournal.operation_type.in_(_REVENUE_OPERATION_TYPES),
                models.Appointment.hairdresser_id.is_not(None),
                models.Appointment.appointment_date.between(date_from, date_to),
            )
            .group_by(models.Appointment.hairdresser_id)
        )
        return {
            row.hairdresser_id: decimal.Decimal(row.net or 0).quantize(_AMOUNT_QUANTUM)
            for row in self._session.execute(stmt).all()
        }

    def _full_name(self, user_id: uuid.UUID) -> str | None:
        """Résout le seul `full_name` de l'auteur (jamais d'autre donnée §11.3)."""

        return self._session.scalar(select(models.User.full_name).where(models.User.id == user_id))


def _to_domain(row: models.CashJournal, performed_by_name: str | None) -> CashJournalEntry:
    return CashJournalEntry(
        id=row.id,
        salon_id=row.salon_id,
        operation_type=row.operation_type,
        amount=row.amount,
        # `cash_journal` ne porte pas de colonne devise : le MVP est mono-devise
        # (XOF/FCFA, §9.6). La devise affichée est la devise unique du système.
        currency=DEFAULT_CURRENCY,
        performed_by=row.performed_by,
        performed_by_name=performed_by_name,
        transaction_id=row.transaction_id,
        description=row.description,
        created_at=row.created_at,
    )


__all__ = ["SqlCashJournalEntryRepository"]
