"""table salon_photos + renommage salons.logo_url -> logo_object_key (US-2.1 #15)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13

Reflet versionné des évolutions du modèle ORM pour la **création d'un salon**
(`coiflink_api/adapters/outbound/persistence/models.py`) :

1. **Renommage** `salons.logo_url` → `salons.logo_object_key`. La colonne stocke
   désormais une **clé d'objet** S3-compatible (`salons/{id}/logo/{uuid}.png`),
   pas une URL : l'URL signée est calculée à la lecture (ADR-0005). La table est
   vide (aucun salon n'existe encore), le renommage est donc sans risque et un nom
   qui ment est une dette évitée (spec §Data Model, décision 1).

2. **Nouvelle table** `salon_photos` : comble l'absence de « photos » (pluriel) du
   §9.2, demandées par US-2.1 / §7.2. Reflet exact du modèle ORM `SalonPhoto`.
   Chaque ligne référence une **clé d'objet** (jamais une URL publique).

   `ON DELETE CASCADE` (par exception à la convention `RESTRICT` du module) : une
   photo est **purement dépendante** de son salon — elle n'a aucun sens seule
   (même logique que `appointment_services`). Supprimer un salon (cas plateforme
   futur) emporte donc ses photos.

- `upgrade()`   : rename de colonne + `CREATE TABLE salon_photos` (FK CASCADE,
                  unicités composites, `CHECK position >= 0`, index de lecture).
- `downgrade()` : `DROP TABLE salon_photos` + rename inverse (réversion complète).

Aucun secret ni aucune donnée (PII) n'est présent ici : les clés d'objet sont des
UUID opaques (contrainte ADR-0005).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Renommage sémantique : la colonne stocke une clé d'objet, pas une URL.
    op.alter_column("salons", "logo_url", new_column_name="logo_object_key")

    # 2. Table des photos (pluriel) — reflet du modèle ORM `SalonPhoto`.
    op.create_table(
        "salon_photos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_salon_photos"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_salon_photos_salon_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("salon_id", "id", name="uq_salon_photos_salon_id"),
        sa.UniqueConstraint(
            "salon_id", "object_key", name="uq_salon_photos_salon_object_key"
        ),
        # Nom de CHECK « court » : la convention de nommage (env.py) l'expanse en
        # `ck_salon_photos_position_positive`.
        sa.CheckConstraint("position >= 0", name="position_positive"),
    )
    op.create_index(
        "ix_salon_photos_salon_id", "salon_photos", ["salon_id", "position"]
    )


def downgrade() -> None:
    # Les index et contraintes tombent avec la table.
    op.drop_table("salon_photos")
    # Réversion du renommage de colonne.
    op.alter_column("salons", "logo_object_key", new_column_name="logo_url")
