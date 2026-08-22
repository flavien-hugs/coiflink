"""ticket de passage — une coiffeuse ne sert qu'un seul ticket en cours à la fois (#173)

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-24

Rien n'empêchait jusqu'ici d'affecter la même coiffeuse (`hairdresser_id`) à
deux tickets `in_progress` simultanément — ni côté application, ni côté base.
Cette migration pose le filet de dernier recours : un index unique **partiel**
sur `queue_tickets(hairdresser_id) WHERE status = 'in_progress'`. Un ticket
`in_progress` porte toujours un `hairdresser_id` non nul (posé uniquement à la
prise en charge, `domain/queue_ticket.py`) : aucune ambiguïté sur les lignes
`NULL`, qu'un index partiel ignore de toute façon.

Portée **volontairement globale** (pas de `salon_id` dans l'index), dérogation
délibérée à l'isolation stricte par salon (§11.2) suivie ailleurs dans ce
schéma : une personne ne peut physiquement servir qu'un seul client à la fois,
quel que soit le salon où elle est staff — la contrainte doit donc porter sur
`hairdresser_id` seul.

`SqlQueueTicketRepository.start()` retraduit la violation de cet index en
`domain.errors.HairdresserAlreadyBusy` (`409`), même patron que
`uq_customer_profiles_salon_phone` (`0005`) → `CustomerAlreadyExists`.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_queue_tickets_hairdresser_in_progress",
        "queue_tickets",
        ["hairdresser_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )


def downgrade() -> None:
    op.drop_index("uq_queue_tickets_hairdresser_in_progress", table_name="queue_tickets")
