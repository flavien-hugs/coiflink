"""prestations — galerie de photos `service_photos` (remplace l'image unique)

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-14

Une prestation ne portait jusqu'ici qu'une seule illustration
(`services.image_object_key`, migration 0010). Cette migration la remplace par
une galerie **ordonnée** de photos, miroir exact de `salon_photos` (0003) : la
photo de `position = 0` sert de couverture pour l'affichage catalogue
(gérant et fiche publique).

FK **composite** `(salon_id, service_id)` vers `services.(salon_id, id)` — et
non une simple FK vers `services.id` — pour rester cohérent avec la convention
d'isolation §11.2 déjà appliquée aux tables qui référencent une entité
déjà scopée-salon (miroir `payments.service_id`, cf. `0001`) ; `salon_photos`,
elle, référence directement `salons.id` car le salon **est** la racine
d'isolation. `services.(salon_id, id)` est déjà unique (`uq_services_salon_id`,
`0001`) : la FK composite ne nécessite aucune migration supplémentaire.

`downgrade()` reconstruit `services.image_object_key` (nullable, round-trip
DDL) sans tenter de restaurer des données — la galerie n'a pas d'équivalent
scalaire univoque (plusieurs photos → un seul champ), comme pour toute
suppression de colonne dans ce projet.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_photos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_service_photos"),
        sa.ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_service_photos_service",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("salon_id", "id", name="uq_service_photos_salon_id"),
        sa.UniqueConstraint(
            "salon_id", "object_key", name="uq_service_photos_salon_object_key"
        ),
        sa.CheckConstraint("position >= 0", name="position_positive"),
    )
    op.create_index(
        "ix_service_photos_salon_id_service_id",
        "service_photos",
        ["salon_id", "service_id", "position"],
    )
    op.drop_column("services", "image_object_key")


def downgrade() -> None:
    op.add_column(
        "services",
        sa.Column("image_object_key", sa.String(length=1024), nullable=True),
    )
    op.drop_table("service_photos")
