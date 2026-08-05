"""notification au salon à la réservation — type NEW_BOOKING (US-7.3 #47)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-04

Reflet versionné du modèle ORM `Notification`
(`coiflink_api/adapters/outbound/persistence/models.py`).

La notification destinée au **salon** à chaque nouvelle réservation (#47) a une
sémantique propre — « nouvelle réservation reçue par le salon » — qu'aucune valeur
de `NotificationType` ne portait : `CONFIRMATION`/`REMINDER` visent le **client**,
`CANCELLATION` une annulation. On ajoute `NotificationType.NEW_BOOKING`
(`domain/enums.py`) ; le `CHECK` `type` (dérivé de l'énumération,
`models.py::enum_check`, figé en base au déploiement) est **régénéré** pour
l'accepter — **exactement** le patron du `CHECK` `status` régénéré par `0006` pour
`CANCELLED`.

Aucune nouvelle colonne, aucun nouvel index : la ligne salon est une ligne
`notifications` de plus (canal `IN_APP`, `status = PENDING`, `scheduled_for = NULL`),
et le tri salon-scopé réutilise `ix_notifications_salon_id (salon_id, created_at)`.
Aucun backfill : les lignes existantes portent des valeurs déjà autorisées.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : régénère le `CHECK` `type` (drop + recreate avec `NEW_BOOKING`).
- `downgrade()` : symétrique (recreate sans `NEW_BOOKING`), round-trip exigé par la CI.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Identifiants de révision Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Régénération du CHECK `type` (nom court "type" -> `ck_notifications_type` via
    # la convention de nommage, cf. `base.py::NAMING_CONVENTION`) pour accepter
    # `NEW_BOOKING` (notification au salon à la réservation, §8.4 — AC #47).
    op.drop_constraint(op.f("ck_notifications_type"), "notifications", type_="check")
    op.create_check_constraint(
        "type",
        "notifications",
        "type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION', 'NEW_BOOKING')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_type"), "notifications", type_="check")
    op.create_check_constraint(
        "type",
        "notifications",
        "type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION')",
    )
