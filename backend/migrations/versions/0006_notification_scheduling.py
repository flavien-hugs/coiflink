"""rappel automatique avant RDV — échéance & statut annulé (US-7.2 #46)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-04

Reflet versionné du modèle ORM `Notification`
(`coiflink_api/adapters/outbound/persistence/models.py`).

Un **rappel** (`type = REMINDER`) diffère d'une confirmation (#45) sur deux points
que le schéma actuel ne porte pas :

1. **Une échéance future** (« à envoyer à partir de »). La table `notifications`
   (migration `0001`) n'a aucune colonne d'horodatage d'envoi prévu ; on ajoute
   `scheduled_for TIMESTAMPTZ NULL` — `NULL` = confirmation (à remettre au plus
   tôt, sémantique #45 inchangée), non-`NULL` = rappel daté.
2. **Une annulation traçable.** `NotificationStatus` ne porte pas `CANCELLED` :
   un rappel dont le RDV est annulé doit pouvoir être marqué `CANCELLED` (plutôt
   que supprimé) pour préserver la trace exigée par le PRD §8.4/§11.4. Le `CHECK`
   `status` (dérivé de l'énumération, `models.py::enum_check`) est **régénéré**
   pour accepter la nouvelle valeur.

Un index partiel `ix_notifications_due` (sur `scheduled_for`, filtré aux lignes
`PENDING`) prépare la requête « rappels dus » du futur worker de remise (M5+,
ADR-0006) — aucun consommateur au périmètre #46, ajout bon marché.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `ADD COLUMN scheduled_for` → régénère le `CHECK` `status`
                  (drop + recreate avec `CANCELLED`) → index partiel.
- `downgrade()` : symétrique (index → `CHECK` d'origine → colonne), round-trip
                  exigé par la CI.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifiants de révision Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )

    # Régénération du CHECK `status` (nom court "status" -> `ck_notifications_status`
    # via la convention de nommage, cf. `base.py::NAMING_CONVENTION`) pour accepter
    # `CANCELLED` (rappel annulé avec le RDV, §8.4 — AC #46).
    op.drop_constraint(
        op.f("ck_notifications_status"), "notifications", type_="check"
    )
    op.create_check_constraint(
        "status",
        "notifications",
        "status IN ('PENDING', 'SENT', 'FAILED', 'READ', 'CANCELLED')",
    )

    # Index partiel : accélère la future requête « rappels dus » du worker M5+
    # (`scheduled_for <= now() AND status = 'PENDING'`) — aucun consommateur au
    # périmètre #46, ajout bon marché qui documente l'intention.
    op.create_index(
        "ix_notifications_due",
        "notifications",
        ["scheduled_for"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_due", table_name="notifications")
    op.drop_constraint(op.f("ck_notifications_status"), "notifications", type_="check")
    op.create_check_constraint(
        "status",
        "notifications",
        "status IN ('PENDING', 'SENT', 'FAILED', 'READ')",
    )
    op.drop_column("notifications", "scheduled_for")
