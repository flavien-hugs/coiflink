"""file d'attente walk-in — tickets de passage & jonction prestations (US-8.3 #157)

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-11

Reflet versionné des modèles ORM `QueueTicket`/`QueueTicketService`
(`coiflink_api/adapters/outbound/persistence/models.py`), matérialisant le domaine
**indépendant d'`Appointment`** du ticket de passage walk-in (ADR-0042).

Migration strictement **additive** : elle crée **deux** tables et **ne modifie
aucune** colonne existante (`appointments`, `payments`, `customer_profiles`,
`services`) — un walk-in n'écrit jamais dans `appointments`.

- `queue_tickets` : numéro séquentiel par salon **et** jour civil
  (`UNIQUE (salon_id, issued_date, ticket_number)` — garantie base du compteur,
  alloué atomiquement par `SqlQueueTicketRepository.create` sous verrou consultatif
  transactionnel, patron ADR-0040), estimation d'attente figée à l'émission, cycle
  de vie fermé (`waiting`/`called`/`in_progress`/`done`/`expired`).
- `queue_ticket_services` : jonction ticket ↔ prestation, FK composites
  `(salon_id, …)` forçant l'appartenance salon (miroir `appointment_services`).

`hairdresser_id` référence **`users.id`** (identifiant de compte, appartenance
salon vérifiée applicativement — miroir `Appointment.hairdresser_id`) ;
`customer_profile_id` est **nullable** (ticket anonyme possible).

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `create_table("queue_tickets")` puis `create_table(
                  "queue_ticket_services")` (ordre des dépendances FK) + index.
- `downgrade()` : drop dans l'ordre **inverse** (jonction d'abord) — round-trip
                  Alembic exigé par la CI ; les FK disparaissent avec les tables.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Statuts fermés du ticket (miroir de `domain/queue_ticket.QUEUE_TICKET_STATUSES`).
_STATUS_VALUES = "'waiting', 'called', 'in_progress', 'done', 'expired'"


def _id_col() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _uuid_col(name: str, *, nullable: bool) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    # --- queue_tickets ------------------------------------------------------ #
    op.create_table(
        "queue_tickets",
        _id_col(),
        _uuid_col("salon_id", nullable=False),
        sa.Column("ticket_number", sa.Integer(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=False),
        _uuid_col("customer_profile_id", nullable=True),
        _uuid_col("hairdresser_id", nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'waiting'"),
        ),
        sa.Column("estimated_wait_minutes", sa.Integer(), nullable=False),
        _created_at(),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_queue_tickets"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_queue_tickets_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["customer_profile_id"],
            ["customer_profiles.id"],
            name="fk_queue_tickets_customer_profile_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hairdresser_id"],
            ["users.id"],
            name="fk_queue_tickets_hairdresser_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("salon_id", "id", name="uq_queue_tickets_salon_id"),
        sa.UniqueConstraint(
            "salon_id",
            "issued_date",
            "ticket_number",
            name="uq_queue_tickets_salon_day_number",
        ),
        sa.CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status"),
        sa.CheckConstraint(
            "estimated_wait_minutes >= 0", name="estimated_wait_positive"
        ),
    )
    op.create_index(
        "ix_queue_tickets_salon_id", "queue_tickets", ["salon_id", "issued_date"]
    )
    op.create_index(
        "ix_queue_tickets_salon_status", "queue_tickets", ["salon_id", "status"]
    )

    # --- queue_ticket_services (jonction ticket ↔ prestation) --------------- #
    op.create_table(
        "queue_ticket_services",
        _uuid_col("queue_ticket_id", nullable=False),
        _uuid_col("service_id", nullable=False),
        _uuid_col("salon_id", nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint(
            "queue_ticket_id", "service_id", name="pk_queue_ticket_services"
        ),
        sa.ForeignKeyConstraint(
            ["salon_id", "queue_ticket_id"],
            ["queue_tickets.salon_id", "queue_tickets.id"],
            name="fk_queue_ticket_services_ticket",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_queue_ticket_services_service",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_queue_ticket_services_service_id",
        "queue_ticket_services",
        ["service_id"],
    )


def downgrade() -> None:
    op.drop_table("queue_ticket_services")
    op.drop_table("queue_tickets")
