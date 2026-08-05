"""notification d'annulation/modification — type APPOINTMENT_UPDATE (US-7.4 #48)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-05

Reflet versionné du modèle ORM `Notification`
(`coiflink_api/adapters/outbound/persistence/models.py`).

Sur **toute** transition `→ CANCELLED` (annulation client #24 ou refus gérant #25),
la notification aux parties concernées réutilise `CANCELLATION` — **aucune** valeur
d'enum nouvelle, donc aucune migration pour ce cœur (§8.4). En revanche, « un
changement de statut déclenche la notification » (AC #48) est **plus large** que
l'annulation : la **confirmation/clôture/absence** notifiée au **client** et la
**modification** (#23) notifiée au **salon** ont une sémantique propre qu'aucune
valeur existante ne porte (`CONFIRMATION`/`REMINDER` visent une réservation client,
`NEW_BOOKING` le salon, `CANCELLATION` une annulation). On ajoute
`NotificationType.APPOINTMENT_UPDATE` (`domain/enums.py`) ; le `CHECK` `type` (dérivé
de l'énumération, `models.py::enum_check`, figé en base au déploiement) est
**régénéré** pour l'accepter — **exactement** le patron du `CHECK` `type` régénéré par
`0007` pour `NEW_BOOKING`.

Aucune nouvelle colonne, aucun nouvel index : une notification de changement de
statut est une ligne `notifications` de plus (`status = PENDING`,
`scheduled_for = NULL`). Aucun backfill : les lignes existantes portent des valeurs
déjà autorisées. La chaîne `"APPOINTMENT_UPDATE"` (18 car.) tient dans
`type String(32)`.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : régénère le `CHECK` `type` (drop + recreate avec `APPOINTMENT_UPDATE`).
- `downgrade()` : symétrique (recreate sans `APPOINTMENT_UPDATE`), round-trip exigé par la CI.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Identifiants de révision Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Régénération du CHECK `type` (nom court "type" -> `ck_notifications_type` via
    # la convention de nommage, cf. `base.py::NAMING_CONVENTION`) pour accepter
    # `APPOINTMENT_UPDATE` (changement de statut / modification, AC #48).
    op.drop_constraint(op.f("ck_notifications_type"), "notifications", type_="check")
    op.create_check_constraint(
        "type",
        "notifications",
        "type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION', 'NEW_BOOKING', "
        "'APPOINTMENT_UPDATE')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_type"), "notifications", type_="check")
    op.create_check_constraint(
        "type",
        "notifications",
        "type IN ('CONFIRMATION', 'REMINDER', 'CANCELLATION', 'NEW_BOOKING')",
    )
