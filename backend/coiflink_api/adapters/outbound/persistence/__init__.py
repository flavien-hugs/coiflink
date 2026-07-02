"""Persistance PostgreSQL (adapter sortant — ADR-0008).

Importer ce paquet enregistre tous les modèles ORM dans `Base.metadata`, ce qui
permet à Alembic (`migrations/env.py`) et aux tests d'invariants de schéma de
disposer de la `metadata` complète sans connaître chaque module.
"""

from __future__ import annotations

from coiflink_api.adapters.outbound.persistence import models  # noqa: F401
from coiflink_api.adapters.outbound.persistence.base import Base

__all__ = ["Base", "models"]
