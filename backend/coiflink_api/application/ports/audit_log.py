"""Port d'écriture **et de lecture** du **journal d'audit** §11.4 (`Protocol`, US-2.3, #17).

Le cas d'usage `application/services.py` journalise ses mutations via
`record()` ; la page gérante « Journal d'audit » les relit via
`list_for_salon`/`count_for_salon` (réorganisation du tableau de bord).
L'implémentation SQLAlchemy (`SqlAuditLog`) vit dans
`adapters/outbound/persistence/audit_log_repository.py`. Le domaine
(`domain/audit.py`) définit *ce qui* est journalisable (`AuditEntry`,
`AuditAction`) et *ce que la lecture renvoie* (`AuditLogEntry`) ; ce port définit
*qu'on écrit/lit*, sans dire *comment*.

**Atomicité** (écriture) : l'implémentation écrit dans la **même unité de
travail** (même `Session`) que l'action métier — l'entrée d'audit et l'écriture
sont committées (ou rollbackées) **ensemble**. Pas d'audit « fantôme » sur un
métier rollbacké, ni de mutation sans trace.

**Lecture** : pure, paginée, filtrable (plage de dates + catégorie), triée
`created_at DESC, id DESC` (même patron que `PaymentRepository.list_for_salon`).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Protocol

from coiflink_api.domain.audit import AuditEntry, AuditLogEntry

# Bornes de pagination du journal d'audit (même patron que `PAYMENTS_LIMIT_*`).
AUDIT_LOG_LIMIT_DEFAULT = 50
AUDIT_LOG_LIMIT_MIN = 1
AUDIT_LOG_LIMIT_MAX = 200


class AuditLog(Protocol):
    """Contrat d'écriture/lecture du journal §11.4."""

    def record(self, entry: AuditEntry) -> None:
        """Écrit une entrée du journal §11.4 dans la même unité de travail.

        Ne lève pas pour un contenu neutre bien formé ; ne journalise **jamais** de
        secret ni de PII (invariant du dépôt, PRD §11.3/§11.4).
        """
        ...

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
        """Page des entrées du salon, plus récentes d'abord — filtre d'appartenance §11.2."""
        ...

    def count_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        category: str | None,
    ) -> int:
        """Nombre total d'entrées du salon **sous le même filtre** (pagination)."""
        ...


__all__ = [
    "AuditLog",
    "AUDIT_LOG_LIMIT_DEFAULT",
    "AUDIT_LOG_LIMIT_MIN",
    "AUDIT_LOG_LIMIT_MAX",
]
