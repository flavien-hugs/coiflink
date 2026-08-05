"""table campaigns — campagnes/messages aux clients (US-7.5 #49)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-05

Reflet versionné du modèle ORM `Campaign`
(`coiflink_api/adapters/outbound/persistence/models.py`).

#49 introduit le concept de **campagne** : une action manuelle du gérant
(composer un message et le diffuser à un segment de son fichier clients #28).
Aucune table existante ne le porte — `notifications` (#45–#48) est centré sur le
RDV (`appointment_id`, libellés fixes). Cette migration crée la table dédiée
`campaigns`, base de l'émission/trace atomique et de la file que consommera le
worker de remise (M5+, ADR-0006).

Chaque ligne porte le salon (`salon_id`), l'auteur gérant (`created_by`), le
`type` (rappel/promotion/fermeture exceptionnelle), le `segment` ciblé, le
`channel` (SMS au MVP), le `title`/`message` **composés par le gérant**, un
**effectif** (`recipient_count`, entier non-PII) snapshot du segment, un `status`
(`PENDING` à la création) et un `sent_at` (`NULL` tant que rien n'est remis).

**Non-fuite de PII (§11.3)** : aucune colonne ne stocke de téléphone, nom ni
identité de destinataire — le fan-out (numéros) est résolu **à l'envoi** par le
worker, jamais copié ici. Aucune table `campaign_recipients` (fan-out différé).

**FK `ON DELETE RESTRICT`** sur `salon_id` et `created_by` : une campagne garde
sa trace même si le salon/l'auteur change d'état (convention `RESTRICT` du
module, cohérente avec `audit_logs`/`notifications`).

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `CREATE TABLE campaigns` (FK RESTRICT, `CHECK` dérivés de
                  `CampaignType`/`CampaignSegment`/`NotificationChannel`/
                  `CampaignStatus`, index `ix_campaigns_salon_id`).
- `downgrade()` : `DROP TABLE campaigns` (réversion complète — table neuve, aucune
                  donnée existante à préserver). Round-trip exigé par la CI.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("segment", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
        sa.ForeignKeyConstraint(
            ["salon_id"],
            ["salons.id"],
            name="fk_campaigns_salon_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_campaigns_created_by",
            ondelete="RESTRICT",
        ),
        # `CHECK` dérivés du domaine (`domain/enums.py`) — les valeurs SQL ne
        # divergent jamais des énumérations Python (patron `notifications`).
        sa.CheckConstraint(
            "type IN ('REMINDER', 'PROMOTION', 'EXCEPTIONAL_CLOSURE')", name="type"
        ),
        sa.CheckConstraint(
            "segment IN ('ALL', 'FEMALE', 'MALE', 'OTHER')", name="segment"
        ),
        sa.CheckConstraint(
            "channel IN ('PUSH', 'SMS', 'EMAIL', 'WHATSAPP', 'IN_APP')",
            name="channel",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')", name="status"
        ),
        sa.CheckConstraint("recipient_count >= 0", name="recipient_count_positive"),
    )
    # Liste des campagnes du salon, la plus récente d'abord (isolation §11.2).
    op.create_index("ix_campaigns_salon_id", "campaigns", ["salon_id", "created_at"])


def downgrade() -> None:
    # L'index et les contraintes tombent avec la table.
    op.drop_table("campaigns")
