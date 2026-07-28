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

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.cash_journal import CashJournalEntry, CashJournalToAppend
from coiflink_api.domain.payment import DEFAULT_CURRENCY


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
