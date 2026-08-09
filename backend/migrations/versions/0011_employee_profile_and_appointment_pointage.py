"""coiffeuses — champs professionnels + rendez-vous — pointage réel (#150)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-09

Reflet versionné des modèles ORM `SalonMember` et `Appointment`
(`coiflink_api/adapters/outbound/persistence/models.py`).

Ajoute deux colonnes **nullables** à `salon_members` :
- `specialties` (`TEXT`) : prestations maîtrisées par la coiffeuse, texte libre
  composé par le gérant (aucune contrainte fermée au MVP) ;
- `hired_at` (`DATE`) : date d'embauche, informative.

Ajoute deux colonnes **nullables** à `appointments`, pour le **pointage réel**
de la file d'attente (gérant) — Dashboard Manager, Gestion de la file
d'attente :
- `arrived_at` (`TIMESTAMPTZ`) : horodatage de l'arrivée de la cliente ;
- `started_at` (`TIMESTAMPTZ`) : horodatage du début de la prestation.

Ces deux horodatages sont **distincts** du statut `AppointmentStatus` (qui reste
inchangé) : « En attente »/« En cours » sont **dérivés** de leur présence côté
domaine (`domain/queue.py`), évitant d'étendre la machine à états existante
d'une valeur `IN_PROGRESS`. Un rendez-vous sans pointage reste un état normal
(les rendez-vous existants ont `arrived_at = NULL` et `started_at = NULL`).

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `ADD COLUMN` sur `salon_members` puis `appointments`.
- `downgrade()` : `DROP COLUMN` symétrique (réversion complète, round-trip
                  Alembic de la CI).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifiants de révision Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "salon_members",
        sa.Column("specialties", sa.Text(), nullable=True),
    )
    op.add_column(
        "salon_members",
        sa.Column("hired_at", sa.Date(), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "started_at")
    op.drop_column("appointments", "arrived_at")
    op.drop_column("salon_members", "hired_at")
    op.drop_column("salon_members", "specialties")
