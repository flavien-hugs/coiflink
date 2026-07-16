"""Adapter sortant : écriture du **journal d'audit** §11.4 (SQLAlchemy, US-2.3, #17).

Implémente le port `AuditLog` en insérant une ligne dans la table `audit_logs`
(modèle ORM `models.AuditLog`). Seul cet adapter connaît SQLAlchemy.

**Atomicité** : l'insertion partage la **même `Session`** que la mutation métier
(injectée via `get_session`) et est `flush`ée **sans commit** — l'entrée d'audit
et l'action métier sont committées (ou rollbackées) **ensemble** : pas de trace
« fantôme » sur un métier rollbacké, ni de mutation sans trace.

**Invariant de non-fuite** : cet adapter recopie tel quel le contenu **déjà
neutre** de l'`AuditEntry` (le domaine garantit l'absence de secret/PII) ; il
n'ajoute aucune donnée sensible.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.audit import AuditEntry


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


__all__ = ["SqlAuditLog"]
