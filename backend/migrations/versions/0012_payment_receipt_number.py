"""paiements — numéro de reçu séquentiel par salon (impression gérant)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-10

Reflet versionné du modèle ORM `Payment`
(`coiflink_api/adapters/outbound/persistence/models.py`).

Ajoute `payments.receipt_number` (`INTEGER`, **`NOT NULL`** après backfill),
avec une contrainte `UNIQUE (salon_id, receipt_number)` — un numéro de reçu
présentable (impression gérant, remise physique à la cliente), séquentiel par
salon, distinct de l'UUID `id` du paiement. Alloué atomiquement à la création
(`SqlPaymentRepository.create`, verrou consultatif transactionnel par salon) ;
cette migration ne fait qu'ajouter la colonne et numéroter les paiements déjà
enregistrés.

Backfill des paiements existants : numérotation par salon, `ROW_NUMBER()`
ordonné par `created_at, id` (ordre de création), avant de rendre la colonne
`NOT NULL` et d'ajouter la contrainte d'unicité.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `ADD COLUMN` nullable, backfill SQL, `ALTER COLUMN ... SET
                  NOT NULL`, `ADD CONSTRAINT` unique.
- `downgrade()` : `DROP CONSTRAINT` puis `DROP COLUMN` (réversion complète,
                  round-trip Alembic de la CI).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifiants de révision Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("receipt_number", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE payments
        SET receipt_number = numbered.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY salon_id ORDER BY created_at, id
            ) AS rn
            FROM payments
        ) AS numbered
        WHERE payments.id = numbered.id
        """
    )
    op.alter_column("payments", "receipt_number", nullable=False)
    op.create_unique_constraint(
        "uq_payments_salon_receipt_number", "payments", ["salon_id", "receipt_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_payments_salon_receipt_number", "payments", type_="unique")
    op.drop_column("payments", "receipt_number")
