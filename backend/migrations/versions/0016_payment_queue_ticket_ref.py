"""paiements — ajoute un rattachement optionnel à un ticket walk-in

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-12

Prépare le retrait de la fonctionnalité Rendez-vous (pivot walk-in exclusif,
jalon M7) : ajoute `payments.queue_ticket_id`, troisième rattachement possible
en plus de `appointment_id`/`service_id` — un paiement pourra bientôt être lié
à un `QueueTicket` (US-8.3, #157) plutôt qu'à un rendez-vous planifié.

Migration **additive uniquement** : `appointment_id` reste présent et le `CHECK`
`ref_present` reste satisfaisable par n'importe laquelle des trois références.
Le retrait effectif d'`appointment_id`/`appointments` est délégué à la migration
suivante (`0017`), une fois le code applicatif entièrement rebranché sur
`queue_ticket_id` — permet de garder la suite de tests verte à chaque étape
plutôt qu'une coupure nette.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Identifiants de révision Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REF_PRESENT_BEFORE = "appointment_id IS NOT NULL OR service_id IS NOT NULL"
_REF_PRESENT_AFTER = (
    "appointment_id IS NOT NULL OR service_id IS NOT NULL "
    "OR queue_ticket_id IS NOT NULL"
)


def upgrade() -> None:
    op.add_column("payments", sa.Column("queue_ticket_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_payments_queue_ticket",
        "payments",
        "queue_tickets",
        ["salon_id", "queue_ticket_id"],
        ["salon_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_payments_queue_ticket_id", "payments", ["queue_ticket_id"]
    )

    op.drop_constraint(op.f("ck_payments_ref_present"), "payments", type_="check")
    op.create_check_constraint("ref_present", "payments", _REF_PRESENT_AFTER)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_payments_ref_present"), "payments", type_="check")
    op.create_check_constraint("ref_present", "payments", _REF_PRESENT_BEFORE)

    op.drop_index("ix_payments_queue_ticket_id", table_name="payments")
    op.drop_constraint("fk_payments_queue_ticket", "payments", type_="foreignkey")
    op.drop_column("payments", "queue_ticket_id")
