"""Cas d'usage : **journal d'audit filtrable** (page gérante « Journal d'audit »).

Tranche applicative hexagonale : ce cas d'usage ne dépend que du port `AuditLog`
(`application/ports/audit_log.py`) — aucune dépendance FastAPI/SQLAlchemy.
`ListAuditLogs` est une **lecture pure** : elle liste, du plus récent au plus
ancien, les entrées d'audit d'un salon sous un `AuditLogFilter` validé (plage de
dates + catégorie, combinés en **ET**), paginée. Consulter le journal n'est pas
une action journalisée §11.4 — même patron que `ListTransactions`/`ListCashJournal`.
"""

from __future__ import annotations

import uuid

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.domain.audit import AuditLogEntry, AuditLogFilter


class ListAuditLogs:
    """Liste paginée et **filtrée** du journal d'audit d'un salon (lecture — pas d'audit).

    Retourne `(page, total)` : la page d'entrées (plus récentes d'abord) et le
    total **sous le même filtre** (pagination correcte). Lecture pure : aucune
    écriture, aucun audit.
    """

    def __init__(self, audit_log: AuditLog) -> None:
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        filter: AuditLogFilter,
        limit: int,
        offset: int,
    ) -> tuple[tuple[AuditLogEntry, ...], int]:
        """Retourne `(page, total)` — entrées filtrées, plus récentes d'abord."""

        page = self._audit_log.list_for_salon(
            salon_id,
            date_from=filter.date_from,
            date_to=filter.date_to,
            category=filter.category,
            limit=limit,
            offset=offset,
        )
        total = self._audit_log.count_for_salon(
            salon_id,
            date_from=filter.date_from,
            date_to=filter.date_to,
            category=filter.category,
        )
        return page, total


__all__ = ["ListAuditLogs"]
