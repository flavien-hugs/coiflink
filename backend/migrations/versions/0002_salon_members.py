"""table salon_members (appartenance employe<->salon, US-1.4 #13)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-12

Ajoute la table d'**appartenance employé↔salon** (`salon_members`), source
d'autorité de la portée d'un coiffeur (PRD §11.2, ADR-0016). Reflet versionné du
modèle ORM `SalonMember` (`coiflink_api/adapters/outbound/persistence/models.py`)
— mêmes colonnes, contraintes et index. Les `CHECK` reprennent exactement les
valeurs des énumérations du domaine (`Role`, `UserStatus`).

- `upgrade()`   : `CREATE TABLE salon_members` (FK RESTRICT, unicité composite,
                  index de lecture).
- `downgrade()` : `DROP TABLE salon_members` (réversion complète).

Aucun secret ni aucune donnée (PII) n'est présent ici.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "salon_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_salon_members"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_salon_members_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_salon_members_user_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("salon_id", "user_id", name="uq_salon_members_salon_user"),
        sa.UniqueConstraint("salon_id", "id", name="uq_salon_members_salon_id"),
        # Noms de CHECK « courts » : la convention de nommage (env.py) les expanse
        # en `ck_salon_members_<nom>`. Valeurs dérivées du domaine (Role/UserStatus).
        sa.CheckConstraint(
            "role IN ('CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN')", name="role"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')", name="status"
        ),
    )
    op.create_index("ix_salon_members_user_id", "salon_members", ["user_id"])
    op.create_index("ix_salon_members_salon_id", "salon_members", ["salon_id"])


def downgrade() -> None:
    # Les index et contraintes tombent avec la table.
    op.drop_table("salon_members")
