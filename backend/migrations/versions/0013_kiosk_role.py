"""rôle KIOSK — régénération des CHECK role (users & salon_members) (US-8.1 #155)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-10

Reflet versionné de l'ajout de `Role.KIOSK` (`coiflink_api/domain/enums.py`) — le
cinquième membre de l'énumération fermée `Role`, identité d'une **borne kiosque**
(compte de service scopé à un salon, jalon M7). Voir
`docs/adr/0041-authentification-borne-kiosque.md`.

Aucune borne n'a de compte personnel : elle vit comme une ligne `users`
(`role = 'KIOSK'`) + un rattachement `salon_members` (`role = 'KIOSK'`). Les deux
`CHECK` `role` (dérivés de l'énumération via `models.py::enum_check`, figés en base
au déploiement) sont **régénérés** pour accepter `'KIOSK'` — **exactement** le
patron du `CHECK` `type` régénéré par `0007` pour `NEW_BOOKING`.

**Aucune nouvelle table, aucune nouvelle colonne** : c'est l'argument de poids de
l'option retenue (ADR-0041) — la borne réutilise toute la chaîne `Principal`
existante. Aucun backfill : les lignes existantes portent des valeurs déjà autorisées.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.

- `upgrade()`   : régénère `ck_users_role` et `ck_salon_members_role` (drop +
                  recreate **avec** `'KIOSK'`).
- `downgrade()` : symétrique (recreate **sans** `'KIOSK'`) — round-trip exigé par la
                  CI. Le downgrade échouerait si des lignes `KIOSK` existent
                  (sémantique standard du retrait d'une valeur d'enum utilisée).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Identifiants de révision Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Valeurs autorisées **après** ajout de KIOSK (miroir de `enums.Role`).
_ROLES_WITH_KIOSK = "'CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN', 'KIOSK'"
# Valeurs autorisées **avant** l'ajout (état 0001–0012).
_ROLES_WITHOUT_KIOSK = "'CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN'"


def _regenerate_role_checks(allowed: str) -> None:
    """Régénère les `CHECK` `role` de `users` et `salon_members` (drop + recreate).

    Noms courts "role" → `ck_users_role` / `ck_salon_members_role` via la convention
    de nommage (`base.py::NAMING_CONVENTION`).
    """

    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint("role", "users", f"role IN ({allowed})")

    op.drop_constraint(op.f("ck_salon_members_role"), "salon_members", type_="check")
    op.create_check_constraint("role", "salon_members", f"role IN ({allowed})")


def upgrade() -> None:
    _regenerate_role_checks(_ROLES_WITH_KIOSK)


def downgrade() -> None:
    _regenerate_role_checks(_ROLES_WITHOUT_KIOSK)
