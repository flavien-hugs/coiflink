"""tickets de passage — motif d'annulation manuelle (no-show)

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-13

Ajoute `queue_tickets.cancellation_reason` (US-8.3) : le gérant / la coiffeuse
peut désormais annuler un ticket `waiting`/`called` quand le client ne se
présente pas, avec un **motif obligatoire** (validé côté domaine,
`CANCELLATION_REASON_MAX_LENGTH`). Le ticket bascule alors sur le statut
`expired` déjà existant (jamais un nouveau statut) ; ce motif y est stocké.

Migration **purement additive** : colonne `TEXT` **nullable** (aucune valeur
par défaut requise, tous les tickets existants restent valides). Aucune perte
de données au downgrade — la colonne n'est jamais peuplée avant cette migration.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Identifiants de révision Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "queue_tickets", sa.Column("cancellation_reason", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("queue_tickets", "cancellation_reason")
