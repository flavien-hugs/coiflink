"""rôle `TERMINAL` — renomme le compte de service borne (`KIOSK` → `TERMINAL`)

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-12

Renomme la valeur du rôle borne libre-service : `KIOSK` (introduit par `0013`,
US-8.1 #155) devient `TERMINAL` — aligne toute la terminologie du jalon M7 (code,
routes, permissions) sur « borne/terminal » plutôt que l'emprunt anglais « kiosk ».
Aucun changement de sémantique : même compte de service, mêmes permissions
(`CUSTOMER_LOOKUP_TERMINAL`, `CUSTOMER_CREATE_WALKIN`, `QUEUE_TICKET_CREATE`), même
rattachement `salon_members` (voir ADR-0041).

La migration `0013` (déjà mergée sur `main`) reste **intacte** — l'historique n'est
jamais réécrit. Ce fichier assure la transition, y compris pour les lignes déjà en
base :

- `upgrade()`   : élargit d'abord les `CHECK` `role` pour accepter `'TERMINAL'` en
                  plus de `'KIOSK'` (une valeur ne peut migrer sans que les deux
                  soient temporairement autorisées, sous peine de violer le `CHECK`
                  pendant l'`UPDATE`), bascule les lignes existantes
                  (`role = 'KIOSK'` → `role = 'TERMINAL'`) sur `users` **et**
                  `salon_members`, puis régénère les `CHECK` dans leur forme finale
                  (`'KIOSK'` retiré).
- `downgrade()` : symétrique — élargit, rebascule les lignes `'TERMINAL'` vers
                  `'KIOSK'`, puis régénère les `CHECK` sans `'TERMINAL'`.

Aucun secret ni aucune donnée personnelle (PII) n'apparaît dans ce fichier.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Identifiants de révision Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# État de départ (post-`0013`) : `KIOSK` présent, `TERMINAL` absent.
_ROLES_WITH_KIOSK = "'CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN', 'KIOSK'"
# Superset transitoire : les deux valeurs coexistent le temps de l'`UPDATE`.
_ROLES_TRANSITIONAL = "'CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN', 'KIOSK', 'TERMINAL'"
# État final : `TERMINAL` présent, `KIOSK` retiré.
_ROLES_WITH_TERMINAL = "'CLIENT', 'HAIRDRESSER', 'MANAGER', 'ADMIN', 'TERMINAL'"


def _regenerate_role_checks(allowed: str) -> None:
    """Régénère les `CHECK` `role` de `users` et `salon_members` (drop + recreate).

    Noms courts "role" → `ck_users_role` / `ck_salon_members_role` via la convention
    de nommage (`base.py::NAMING_CONVENTION`) — patron identique à `0013`.
    """

    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint("role", "users", f"role IN ({allowed})")

    op.drop_constraint(op.f("ck_salon_members_role"), "salon_members", type_="check")
    op.create_check_constraint("role", "salon_members", f"role IN ({allowed})")


def upgrade() -> None:
    _regenerate_role_checks(_ROLES_TRANSITIONAL)
    op.execute("UPDATE users SET role = 'TERMINAL' WHERE role = 'KIOSK'")
    op.execute("UPDATE salon_members SET role = 'TERMINAL' WHERE role = 'KIOSK'")
    _regenerate_role_checks(_ROLES_WITH_TERMINAL)


def downgrade() -> None:
    _regenerate_role_checks(_ROLES_TRANSITIONAL)
    op.execute("UPDATE users SET role = 'KIOSK' WHERE role = 'TERMINAL'")
    op.execute("UPDATE salon_members SET role = 'KIOSK' WHERE role = 'TERMINAL'")
    _regenerate_role_checks(_ROLES_WITH_KIOSK)
