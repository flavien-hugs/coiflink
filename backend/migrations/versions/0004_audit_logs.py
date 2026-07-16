"""table audit_logs — journal d'audit §11.4 (US-2.3 #17)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15

Reflet versionné du modèle ORM `AuditLog`
(`coiflink_api/adapters/outbound/persistence/models.py`).

#17 est la **première** issue dont un critère d'acceptation exige la
journalisation §11.4 (« modification prestation journalisée »). Aucune infra
d'audit n'existait : cette migration crée la table `audit_logs`, durable et
requêtable, base de la supervision §11.3 et des actions §11.4 suivantes (RDV,
paiement, caisse, désactivation salon) qui réutiliseront le même socle.

Chaque ligne trace *qui* (`actor_user_id`) a fait *quelle* action (`action`) sur
*quelle* entité (`entity_type`/`entity_id`) de *quel* salon (`salon_id`), *quand*
(`created_at`), avec un contexte **neutre** (`metadata`).

**`ON DELETE RESTRICT`** sur `actor_user_id` et `salon_id` : un journal d'audit
ne doit **pas** perdre ses lignes quand un compte ou un salon est supprimé — la
traçabilité prime (convention `RESTRICT` par défaut du module). `salon_id` est
**nullable** (une action §11.4 future peut être hors portée salon).

**Invariant de non-fuite** : aucune colonne ne porte de secret ni de PII —
`actor_user_id` est un UUID opaque, `metadata` ne contient que des noms de champs
modifiés et des valeurs non sensibles.

- `upgrade()`   : `CREATE TABLE audit_logs` (FK RESTRICT, `metadata` JSONB défaut
                  `{}`, index de lecture chronologique / par entité / par acteur).
- `downgrade()` : `DROP TABLE audit_logs` (réversion complète — table neuve, aucune
                  donnée existante à préserver).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_logs_actor_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["salon_id"],
            ["salons.id"],
            name="fk_audit_logs_salon_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_audit_logs_salon_id_created_at",
        "audit_logs",
        ["salon_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"]
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_user_id"])


def downgrade() -> None:
    # Les index tombent avec la table.
    op.drop_table("audit_logs")
