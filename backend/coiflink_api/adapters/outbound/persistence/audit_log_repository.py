"""Adapter sortant : écriture **et lecture** du **journal d'audit** §11.4 (SQLAlchemy, US-2.3, #17).

Implémente le port `AuditLog` : `record()` insère une ligne dans la table
`audit_logs` (modèle ORM `models.AuditLog`) ; `list_for_salon`/`count_for_salon`
la relisent pour la page gérante « Journal d'audit » (réorganisation du tableau
de bord). Seul cet adapter connaît SQLAlchemy.

**Atomicité (écriture)** : l'insertion partage la **même `Session`** que la
mutation métier (injectée via `get_session`) et est `flush`ée **sans commit** —
l'entrée d'audit et l'action métier sont committées (ou rollbackées) **ensemble**
: pas de trace « fantôme » sur un métier rollbacké, ni de mutation sans trace.

**Invariant de non-fuite** : cet adapter recopie tel quel le contenu **déjà
neutre** de l'`AuditEntry` (le domaine garantit l'absence de secret/PII) ; il
n'ajoute aucune donnée sensible. La lecture résout `actor_user_id →
users.full_name` (`join`, un nom n'est pas un secret) mais n'expose
**jamais** `event_metadata` (toujours vide en pratique, aucune valeur à exposer).

**Appartenance §11.2 au niveau du dépôt** : `audit_logs.salon_id = salon_id` est
un filtre **inconditionnel** de la lecture — une entrée d'un autre salon (ou hors
portée salon) est indiscernable d'une entrée inexistante (non-oracle §11.3).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.audit import (
    ACTIONS_BY_CATEGORY,
    AUDIT_ACTION_CATEGORY,
    AuditCategory,
    AuditEntry,
    AuditLogEntry,
)
from coiflink_api.domain.time_window import day_end_utc, day_start_utc


class SqlAuditLog:
    """Journal d'audit §11.4 adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, entry: AuditEntry) -> None:
        """Insère une ligne d'audit dans la même unité de travail que la mutation.

        `flush()` sans `commit()` : la ligne est matérialisée (contraintes FK
        vérifiées) mais committée **avec** l'action métier par `get_session`.
        """

        row = models.AuditLog(
            action=entry.action,
            actor_user_id=entry.actor_user_id,
            salon_id=entry.salon_id,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            event_metadata=dict(entry.metadata),
        )
        self._session.add(row)
        self._session.flush()

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> tuple[AuditLogEntry, ...]:
        """Page des entrées du salon, plus récentes d'abord — lecture seule."""

        stmt = (
            select(models.AuditLog, models.User.full_name)
            # `join` (pas `outerjoin`) : `actor_user_id` est `NOT NULL` avec une FK
            # `ON DELETE RESTRICT` vers `users.id` — un acteur d'audit existe
            # toujours, contrairement à `Payment.client_id` (nullable ailleurs).
            .join(models.User, models.User.id == models.AuditLog.actor_user_id)
            .where(*self._filter_clauses(salon_id, date_from, date_to, category))
            .order_by(models.AuditLog.created_at.desc(), models.AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self._session.execute(stmt).all()
        return tuple(self._to_entry(row, full_name) for row, full_name in rows)

    def count_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        category: str | None,
    ) -> int:
        """Nombre total d'entrées du salon **sous le même filtre** (pagination)."""

        stmt = (
            select(func.count())
            .select_from(models.AuditLog)
            .where(*self._filter_clauses(salon_id, date_from, date_to, category))
        )
        return int(self._session.scalar(stmt) or 0)

    @staticmethod
    def _filter_clauses(
        salon_id: uuid.UUID,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        category: str | None,
    ) -> list:
        clauses: list = [models.AuditLog.salon_id == salon_id]
        if date_from is not None:
            clauses.append(models.AuditLog.created_at >= day_start_utc(date_from))
        if date_to is not None:
            clauses.append(models.AuditLog.created_at <= day_end_utc(date_to))
        if category is not None:
            clauses.append(
                models.AuditLog.action.in_(
                    ACTIONS_BY_CATEGORY.get(category, ())  # type: ignore[arg-type]
                )
            )
        return clauses

    @staticmethod
    def _to_entry(row: models.AuditLog, actor_name: str) -> AuditLogEntry:
        # `.get(row.action, "salon")`, pas une indexation directe : l'exhaustivité
        # de `AUDIT_ACTION_CATEGORY` sur l'énumération **actuelle** est garantie au
        # moment des tests (`TestAuditActionCategoryExhaustiveness`) — c'est là
        # qu'une catégorie manquante est « une régression, jamais un défaut
        # silencieux ». Ça ne dit rien des lignes **historiques** : `audit_logs`
        # est un journal append-only (§11.4, conservé indéfiniment) et une action
        # retirée d'une fonctionnalité supprimée (ex. les anciens RDV) doit rester
        # lisible pour toujours, pas faire planter la page pour tout salon qui a
        # de l'ancien historique.
        category: AuditCategory = AUDIT_ACTION_CATEGORY.get(row.action, "salon")
        return AuditLogEntry(
            id=row.id,
            action=row.action,
            category=category,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            actor_name=actor_name,
            created_at=row.created_at,
        )


__all__ = ["SqlAuditLog"]
