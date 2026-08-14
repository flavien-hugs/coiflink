"""retrait définitif du module Rendez-vous et des notifications de RDV (pivot walk-in, jalon M7)

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-13

Suite logique de la migration additive `0016` : le code applicatif est
désormais **entièrement rebranché** sur la file d'attente walk-in
(`queue_tickets`/`queue_ticket_services`) et ne référence plus aucun module
Rendez-vous ni Notification (domaine, application, adapters supprimés en
amont de cette migration). Cette migration matérialise en base le retrait
correspondant, dans l'ordre imposé par les dépendances FK :

1. `notifications` — porte une FK vers `appointments` (`fk_notifications_appointment_id`) ;
   supprimée en premier.
2. `payments` — retire le rattachement `appointment_id` devenu obsolète
   (troisième rattachement possible, `queue_ticket_id`, ajouté par `0016`) :
   FK composite `fk_payments_appointment`, index `ix_payments_appointment_id`,
   colonne `appointment_id`, et régénère le `CHECK` `ref_present` en 2 clauses
   (`service_id`/`queue_ticket_id`) — **exactement** la contrainte déjà portée
   par le mapping ORM (`coiflink_api/adapters/outbound/persistence/models.py::Payment`).
3. `appointment_services` — jonction RDV ↔ prestation, désormais orpheline.
4. `appointments` — emporte avec elle, à la suppression de la table,
   l'`EXCLUDE` anti double-réservation (`ex_appointments_hairdresser_slot`) et
   la colonne générée `slot`.
5. Extension `btree_gist` — n'était requise que par cette contrainte `EXCLUDE`
   (vérifié : aucune autre contrainte du schéma ne l'utilise).

**Irréversible pour les données** : `upgrade()` supprime physiquement les
lignes existantes de `appointments`, `appointment_services` et
`notifications` (et la valeur de `payments.appointment_id`) — suppression
volontaire et assumée (pivot walk-in exclusif), aucune tentative de
sauvegarde/restauration. `downgrade()` ne restitue que la **structure**
(tables vides, contraintes, index), telle qu'elle existait juste avant cette
migration — pas les données perdues.

Reflet versionné du mapping ORM
(`coiflink_api/adapters/outbound/persistence/models.py`), qui ne porte plus
les classes `Appointment`/`AppointmentService`/`Notification` depuis le
nettoyage applicatif préalable à cette migration.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : drop `notifications` → altère `payments` (FK, `CHECK`,
                  index, colonne) → drop `appointment_services` → drop
                  `appointments` → drop extension `btree_gist`.
- `downgrade()` : miroir structurel complet (extension → `appointments` →
                  `appointment_services` → `payments` → `notifications`),
                  intégrant tous les ALTER accumulés de `0001` à `0016` sur
                  ces tables (pointage `0011`, régénérations de `CHECK`
                  `0006`/`0007`/`0008`) — round-trip DDL exigé par la CI,
                  sans prétention à restaurer les données.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifiants de révision Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `ck_payments_ref_present` : état juste avant cette migration (identique à
# `_REF_PRESENT_AFTER` de `0016`, trois rattachements possibles) et état
# résultant (deux rattachements, `appointment_id` retiré) — patron identique
# aux constantes `_REF_PRESENT_BEFORE`/`_REF_PRESENT_AFTER` de `0016`.
_REF_PRESENT_BEFORE = (
    "appointment_id IS NOT NULL OR service_id IS NOT NULL "
    "OR queue_ticket_id IS NOT NULL"
)
_REF_PRESENT_AFTER = "service_id IS NOT NULL OR queue_ticket_id IS NOT NULL"


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


def upgrade() -> None:
    # --- notifications (FK vers appointments : doit partir en premier) ------ #
    op.drop_table("notifications")

    # --- payments : retire le rattachement appointment_id ------------------- #
    op.drop_constraint("fk_payments_appointment", "payments", type_="foreignkey")
    op.drop_constraint(op.f("ck_payments_ref_present"), "payments", type_="check")
    op.create_check_constraint("ref_present", "payments", _REF_PRESENT_AFTER)
    op.drop_index("ix_payments_appointment_id", table_name="payments")
    op.drop_column("payments", "appointment_id")

    # --- appointment_services (jonction RDV ↔ prestation) ------------------- #
    op.drop_table("appointment_services")

    # --- appointments (emporte l'EXCLUDE et la colonne générée `slot`) ------ #
    op.drop_table("appointments")

    # --- extension btree_gist (n'était requise que par l'EXCLUDE ci-dessus) - #
    op.execute("DROP EXTENSION IF EXISTS btree_gist")


def downgrade() -> None:
    # --- extension btree_gist ------------------------------------------------ #
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # --- appointments (schéma final : 0001 + pointage 0011) ----------------- #
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
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
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

    # --- appointment_services (jonction RDV ↔ prestation, 0001) ------------- #
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

    # --- payments : restitue le rattachement appointment_id (état de 0016) - #
    op.add_column("payments", sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_payments_appointment",
        "payments",
        "appointments",
        ["salon_id", "appointment_id"],
        ["salon_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"])
    op.drop_constraint(op.f("ck_payments_ref_present"), "payments", type_="check")
    op.create_check_constraint("ref_present", "payments", _REF_PRESENT_BEFORE)

    # --- notifications (schéma final : 0001 + 0006 + 0007 + 0008) ----------- #
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
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
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
            "type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION', 'NEW_BOOKING', "
            "'APPOINTMENT_UPDATE')",
            name="type",
        ),
        sa.CheckConstraint(
            "channel IN ('PUSH', 'SMS', 'EMAIL', 'WHATSAPP', 'IN_APP')",
            name="channel",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'READ', 'CANCELLED')", name="status"
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_salon_id", "notifications", ["salon_id", "created_at"])
    op.create_index(
        "ix_notifications_due",
        "notifications",
        ["scheduled_for"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )
