"""prestations — clé d'objet image optionnelle (illustration de la prestation)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-09

Reflet versionné du modèle ORM `Service`
(`coiflink_api/adapters/outbound/persistence/models.py`).

Ajoute la colonne **`image_object_key`** à `services` : la clé d'objet
S3-compatible de l'illustration de la prestation (ADR-0005/ADR-0017), jamais
une URL — l'URL signée est calculée à la lecture, comme `salons.logo_object_key`
(`0001`). Le binaire transite directement navigateur → stockage objet ; l'API
ne reçoit que la clé (fabriquée serveur, sans PII).

Colonne **nullable** : une prestation sans image reste un état normal (pas
d'illustration requise au MVP), et l'ajout est sans risque de rupture — les
prestations existantes ont `image_object_key = NULL`.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `ADD COLUMN image_object_key`.
- `downgrade()` : `DROP COLUMN image_object_key` (réversion complète, round-trip
                  Alembic de la CI).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifiants de révision Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column("image_object_key", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("services", "image_object_key")
