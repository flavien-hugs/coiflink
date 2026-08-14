"""paiements — colonne du téléphone Mobile Money (US-5.1)

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-14

Ajoute `payments.mobile_money_phone` : quand `payment_method =
MOBILE_MONEY_MANUAL`, le gérant doit désormais renseigner le numéro de
téléphone utilisé pour la transaction (par défaut celui du client, ajustable
côté formulaire) **et** un numéro de transaction (`reference`, déjà existante
— devient obligatoire pour ce mode). Migration **purement additive** :
colonne `VARCHAR(32)` **nullable** (même borne que `users.phone`/
`customer_profiles.phone`).

**Pas de `CHECK` en base pour cette exigence** (à la différence de
`ref_present`) — décision délibérée, pas un oubli. Un `CHECK` s'applique à
**toute** écriture qui touche la ligne, y compris un `UPDATE` qui ne modifie
qu'une colonne sans rapport : `SqlPaymentRepository.mark_adjusted` (correction
d'un paiement, US-5.3/#34) fait exactement cela (`UPDATE payments SET
status = 'ADJUSTED' ...`). Un paiement `MOBILE_MONEY_MANUAL` antérieur à cette
exigence a nécessairement `mobile_money_phone IS NULL` (colonne inexistante
avant cette migration, aucun backfill possible a posteriori) : un `CHECK`
rejetterait alors **toute correction future** de ce paiement, y compris des
mois après cette migration — `NOT VALID` ne protège que le scan initial de
l'`ALTER TABLE`, pas les écritures suivantes sur les lignes déjà en base
(vérifié empiriquement). La validation applicative
(`domain/payment.py::validate_mobile_money_phone`/
`require_mobile_money_reference`, appelée par `RecordPayment.execute` **avant
toute écriture**) reste l'unique garde, cohérente avec le fait que **toutes**
les écritures de ce projet passent par l'API — aucun accès direct à la base.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Identifiants de révision Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments", sa.Column("mobile_money_phone", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("payments", "mobile_money_phone")
