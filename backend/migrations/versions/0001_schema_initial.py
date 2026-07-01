"""schema initial CoifLink (8 entites du PRD §9 + jonction RDV/prestation)

Revision ID: 0001
Revises:
Create Date: 2026-06-30

Migration initiale **écrite à la main** (les `CHECK`/`EXCLUDE` et la colonne
générée ne sont pas autogénérés par Alembic) : elle matérialise le schéma
relationnel des 8 entités du PRD §9 ainsi que la table de jonction
`appointment_services`, avec les contraintes clés métier (§8.1/§8.2).

- `upgrade()`   : extension `btree_gist` → tables (ordre des dépendances FK) →
                  contraintes composites, `EXCLUDE`, index.
- `downgrade()` : réversion complète vers un schéma vide (drop des tables dans
                  l'ordre inverse, puis de l'extension), de sorte que
                  `alembic downgrade base` n'échoue pas.

Le mapping ORM de référence vit dans
`coiflink_api/adapters/sortant/persistance/modeles.py` ; cette migration en est
le reflet versionné. Aucun secret ni aucune donnée (PII) n'est présent ici.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --------------------------------------------------------------------------- #
# Fabriques de colonnes standard (cohérentes avec modeles.py).
# --------------------------------------------------------------------------- #
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


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


# Tables dans l'ordre de création (= ordre des dépendances FK).
_TABLES_CREATION_ORDER = (
    "users",
    "salons",
    "services",
    "appointments",
    "appointment_services",
    "customer_profiles",
    "payments",
    "cash_journal",
    "notifications",
)


def upgrade() -> None:
    # Requis par la contrainte d'exclusion anti double-réservation (opérateur `=`
    # sur UUID + `&&` sur range dans un même index GiST).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # --- users -------------------------------------------------------------- #
    op.create_table(
        "users",
        _id_col(),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
        # Noms de CHECK volontairement « courts » : la convention de nommage
        # portée par la metadata cible (env.py) les expanse en `ck_<table>_<nom>`.
        sa.CheckConstraint(
            "role IN ('CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN')", name="role"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')", name="status"
        ),
    )
    op.create_index(
        "uq_users_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # --- salons ------------------------------------------------------------- #
    op.create_table(
        "salons",
        _id_col(),
        _uuid_col("owner_id", nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("address", sa.String(length=512), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("commune", sa.String(length=128), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("logo_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("opening_hours", postgresql.JSONB(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name="pk_salons"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_salons_owner_id", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')", name="status"
        ),
    )
    op.create_index("ix_salons_city_commune", "salons", ["city", "commune"])
    op.create_index("ix_salons_status", "salons", ["status"])

    # --- services ----------------------------------------------------------- #
    op.create_table(
        "services",
        _id_col(),
        _uuid_col("salon_id", nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_services_salon_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("salon_id", "id", name="uq_services_salon_id"),
        sa.CheckConstraint("price >= 0", name="price_positive"),
        sa.CheckConstraint("duration_minutes > 0", name="duration_positive"),
    )
    op.create_index("ix_services_salon_id", "services", ["salon_id"])

    # --- appointments ------------------------------------------------------- #
    op.create_table(
        "appointments",
        _id_col(),
        _uuid_col("salon_id", nullable=False),
        _uuid_col("client_id", nullable=False),
        _uuid_col("hairdresser_id", nullable=True),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("end_time", sa.Time(timezone=False), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("client_note", sa.Text(), nullable=True),
        sa.Column(
            "slot",
            postgresql.TSRANGE(),
            sa.Computed(
                "tsrange((appointment_date + start_time), (appointment_date + end_time))",
                persisted=True,
            ),
            nullable=False,
        ),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name="pk_appointments"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_appointments_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name="fk_appointments_client_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["hairdresser_id"],
            ["users.id"],
            name="fk_appointments_hairdresser_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("salon_id", "id", name="uq_appointments_salon_id"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'COMPLETED', 'NO_SHOW')",
            name="status",
        ),
        sa.CheckConstraint("end_time > start_time", name="time_order"),
        postgresql.ExcludeConstraint(
            (sa.column("hairdresser_id"), "="),
            (sa.column("slot"), "&&"),
            using="gist",
            where=sa.text("hairdresser_id IS NOT NULL AND status IN ('PENDING', 'CONFIRMED')"),
            name="ex_appointments_hairdresser_slot",
        ),
    )
    op.create_index("ix_appointments_salon_id", "appointments", ["salon_id", "appointment_date"])
    op.create_index("ix_appointments_client_id", "appointments", ["client_id"])

    # --- appointment_services (jonction RDV ↔ prestation) ------------------- #
    op.create_table(
        "appointment_services",
        _uuid_col("appointment_id", nullable=False),
        _uuid_col("service_id", nullable=False),
        _uuid_col("salon_id", nullable=False),
        sa.Column("price_at_booking", sa.Numeric(precision=12, scale=2), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("appointment_id", "service_id", name="pk_appointment_services"),
        sa.ForeignKeyConstraint(
            ["salon_id", "appointment_id"],
            ["appointments.salon_id", "appointments.id"],
            name="fk_appointment_services_appointment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_appointment_services_service",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("price_at_booking >= 0", name="price_positive"),
    )
    op.create_index(
        "ix_appointment_services_service_id", "appointment_services", ["service_id"]
    )

    # --- customer_profiles -------------------------------------------------- #
    op.create_table(
        "customer_profiles",
        _id_col(),
        _uuid_col("salon_id", nullable=False),
        _uuid_col("user_id", nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_visit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_visits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name="pk_customer_profiles"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_customer_profiles_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_customer_profiles_user_id", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("total_visits >= 0", name="total_visits_positive"),
    )
    op.create_index("ix_customer_profiles_salon_id", "customer_profiles", ["salon_id"])
    op.create_index(
        "uq_customer_profiles_salon_user",
        "customer_profiles",
        ["salon_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # --- payments ----------------------------------------------------------- #
    op.create_table(
        "payments",
        _id_col(),
        _uuid_col("salon_id", nullable=False),
        _uuid_col("appointment_id", nullable=True),
        _uuid_col("service_id", nullable=True),
        _uuid_col("client_id", nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'XOF'")),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING'")),
        _uuid_col("recorded_by", nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_payments_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["salon_id", "appointment_id"],
            ["appointments.salon_id", "appointments.id"],
            name="fk_payments_appointment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["salon_id", "service_id"],
            ["services.salon_id", "services.id"],
            name="fk_payments_service",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name="fk_payments_client_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name="fk_payments_recorded_by", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("salon_id", "id", name="uq_payments_salon_id"),
        sa.CheckConstraint(
            "payment_method IN ('CASH', 'MOBILE_MONEY_MANUAL', 'CARD_MANUAL', 'OTHER')",
            name="payment_method",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'VALIDATED', 'CANCELLED', 'ADJUSTED')",
            name="status",
        ),
        sa.CheckConstraint("amount >= 0", name="amount_positive"),
        sa.CheckConstraint(
            "appointment_id IS NOT NULL OR service_id IS NOT NULL", name="ref_present"
        ),
    )
    op.create_index("ix_payments_salon_id", "payments", ["salon_id", "created_at"])
    op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"])

    # --- cash_journal (append-only) ----------------------------------------- #
    op.create_table(
        "cash_journal",
        _id_col(),
        _uuid_col("salon_id", nullable=False),
        _uuid_col("transaction_id", nullable=True),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        _uuid_col("performed_by", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_cash_journal"),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_cash_journal_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["salon_id", "transaction_id"],
            ["payments.salon_id", "payments.id"],
            name="fk_cash_journal_transaction",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["performed_by"], ["users.id"], name="fk_cash_journal_performed_by", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "operation_type IN ('PAYMENT', 'REFUND', 'ADJUSTMENT', 'CASH_OPENING', 'CASH_CLOSING')",
            name="operation_type",
        ),
    )
    op.create_index("ix_cash_journal_salon_id", "cash_journal", ["salon_id", "created_at"])

    # --- notifications ------------------------------------------------------ #
    op.create_table(
        "notifications",
        _id_col(),
        _uuid_col("user_id", nullable=True),
        _uuid_col("salon_id", nullable=True),
        _uuid_col("appointment_id", nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notifications_user_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["salon_id"], ["salons.id"], name="fk_notifications_salon_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name="fk_notifications_appointment_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION')", name="type"
        ),
        sa.CheckConstraint(
            "channel IN ('PUSH', 'SMS', 'EMAIL', 'WHATSAPP', 'IN_APP')",
            name="channel",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'READ')", name="status"
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_salon_id", "notifications", ["salon_id", "created_at"])


def downgrade() -> None:
    # Drop dans l'ordre inverse des dépendances FK (les index/contraintes des
    # tables, dont l'EXCLUDE et les index partiels, tombent avec leur table).
    for table in reversed(_TABLES_CREATION_ORDER):
        op.drop_table(table)
    # L'extension n'est plus référencée une fois `appointments` supprimée.
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
