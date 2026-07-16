"""Port d'écriture du **journal d'audit** §11.4 (`Protocol`, US-2.3, #17).

Le cas d'usage `application/services.py` journalise ses mutations via ce port ;
l'implémentation SQLAlchemy (`SqlAuditLog`) vit dans
`adapters/outbound/persistence/audit_log_repository.py`. Le domaine
(`domain/audit.py`) définit *ce qui* est journalisable (`AuditEntry`,
`AuditAction`) ; ce port définit *qu'on écrit*, sans dire *comment*.

**Atomicité** : l'implémentation écrit dans la **même unité de travail** (même
`Session`) que l'action métier — l'entrée d'audit et l'écriture sont committées
(ou rollbackées) **ensemble**. Pas d'audit « fantôme » sur un métier rollbacké,
ni de mutation sans trace.
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.audit import AuditEntry


class AuditLog(Protocol):
    """Contrat d'écriture du journal §11.4."""

    def record(self, entry: AuditEntry) -> None:
        """Écrit une entrée du journal §11.4 dans la même unité de travail.

        Ne lève pas pour un contenu neutre bien formé ; ne journalise **jamais** de
        secret ni de PII (invariant du dépôt, PRD §11.3/§11.4).
        """
        ...


__all__ = ["AuditLog"]
