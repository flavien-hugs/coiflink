"""paiements — fournisseurs Mobile Money nommés (#179)

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-23

Remplace le mode générique `MOBILE_MONEY_MANUAL` par quatre fournisseurs
nommés, réellement utilisés en Côte d'Ivoire (§9.6 mis à jour) :
`ORANGE_MONEY_MANUAL`, `MTN_MONEY_MANUAL`, `MOOV_MONEY_MANUAL`,
`WAVE_MANUAL`. Élargit uniquement l'ensemble autorisé par le `CHECK`
`payment_method` (posé par la migration initiale `0001`, jamais retouché
depuis) — aucune colonne, aucun index, aucune perte de données.

**`MOBILE_MONEY_MANUAL` reste une valeur autorisée par la contrainte** —
décision délibérée, pas un oubli, exactement le même raisonnement que la
migration `0019` (qui explique pourquoi `mobile_money_phone` n'a **jamais**
reçu son propre `CHECK`) : un `CHECK` s'évalue sur **toute** ligne touchée
par un `UPDATE`, y compris une correction (`mark_adjusted`, US-5.3/#34,
`application/cash_journal.py`) qui ne modifie que `status`. Un paiement
`MOBILE_MONEY_MANUAL` antérieur à cette migration ne peut être
**rétroactivement** rattaché à l'un des quatre fournisseurs (l'information
n'a jamais été capturée) : retirer la valeur de la contrainte romprait toute
correction future de ces paiements, potentiellement des mois après cette
migration. La validation applicative
(`domain/payment.py::PAYMENT_METHOD_CREATE_VALUES`,
`application/payments.py::RecordPayment.execute`) est l'unique garde qui
empêche de **choisir** ce mode pour un NOUVEAU paiement — la contrainte base
reste volontairement plus permissive, pour la même raison que `0019`.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Identifiants de révision Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PAYMENT_METHOD_BEFORE = "payment_method IN ('CASH', 'MOBILE_MONEY_MANUAL', 'CARD_MANUAL', 'OTHER')"
_PAYMENT_METHOD_AFTER = (
    "payment_method IN ('CASH', 'MOBILE_MONEY_MANUAL', 'ORANGE_MONEY_MANUAL', "
    "'MTN_MONEY_MANUAL', 'MOOV_MONEY_MANUAL', 'WAVE_MANUAL', 'CARD_MANUAL', 'OTHER')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_payments_payment_method"), "payments", type_="check")
    op.create_check_constraint("payment_method", "payments", _PAYMENT_METHOD_AFTER)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_payments_payment_method"), "payments", type_="check")
    op.create_check_constraint("payment_method", "payments", _PAYMENT_METHOD_BEFORE)
