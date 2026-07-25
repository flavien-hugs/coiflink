"""fiche client — genre optionnel & unicité du téléphone par salon (US-4.1 #28)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24

Reflet versionné du modèle ORM `CustomerProfile`
(`coiflink_api/adapters/outbound/persistence/models.py`).

La table `customer_profiles` existe depuis la migration initiale (`0001`, PRD
§9.5) mais **n'a jamais été écrite** : #28 est le premier writer. Deux ajouts
sont nécessaires pour porter la spécification US-4.1 (« nom, téléphone, genre
optionnel, notes internes ») :

1. la colonne **`gender`** — absente du schéma initial ; nullable (`NULL` = non
   renseigné), avec un `CHECK` **dérivé de l'énumération de domaine**
   `domain.enums.Gender` (conventions `models.py` : jamais de type `ENUM`
   PostgreSQL, évolutif sans `ALTER TYPE`) ;
2. l'index unique **partiel** `uq_customer_profiles_salon_phone` — garantie
   **base** du refus de doublon de téléphone **dans un salon** (le pré-contrôle
   applicatif seul serait sujet à une course concurrente). Partiel car le
   téléphone est optionnel (clients walk-in) ; porté par `(salon_id, phone)` car
   les fiches sont **cloisonnées par salon** (§11.2) — deux salons peuvent ficher
   le même numéro. Miroir exact de `uq_customer_profiles_salon_user` (`0001`).

L'ajout d'une colonne *nullable* et d'un index unique partiel est **sans risque
de rupture** : aucune ligne n'existe en pratique (aucun writer avant #28).

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : `ADD COLUMN gender` → `CHECK` → index unique partiel.
- `downgrade()` : index → `CHECK` (nom complet `ck_customer_profiles_gender`,
                  tel que stocké en base après expansion par la convention) →
                  colonne (réversion complète, exigée par le round-trip Alembic
                  de la CI). `op.drop_constraint` n'applique pas la convention
                  de nommage : le nom fourni doit être le nom réel en base.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifiants de révision Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_profiles",
        sa.Column("gender", sa.String(length=16), nullable=True),
    )
    # Nom de CHECK volontairement « court » : la convention de nommage portée par
    # la metadata cible (env.py) l'expanse en `ck_customer_profiles_gender`.
    # Valeurs alignées sur `domain.enums.Gender` ; `NULL` reste autorisé.
    op.create_check_constraint(
        "gender",
        "customer_profiles",
        "gender IN ('FEMALE', 'MALE', 'OTHER')",
    )
    op.create_index(
        "uq_customer_profiles_salon_phone",
        "customer_profiles",
        ["salon_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_customer_profiles_salon_phone", table_name="customer_profiles")
    op.drop_constraint("ck_customer_profiles_gender", "customer_profiles", type_="check")
    op.drop_column("customer_profiles", "gender")
