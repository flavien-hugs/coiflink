"""Tests unitaires — matrice de permissions (domain/permissions.py, issue #12).

Couvre :
- deny-by-default : rôle inconnu/forgé → frozenset vide, pas d'accès par défaut ;
- exhaustivité : chaque rôle connu a **exactement** ses permissions attendues ;
- `ADMIN` n'est pas un joker implicite (ses droits sont listés, pas hérités) ;
- permissions inter-rôles : CLIENT/HAIRDRESSER n'ont pas de droits de gestion,
  ADMIN n'a pas de droits d'exploitation salon.
"""

from __future__ import annotations

import pytest

from coiflink_api.domain.enums import Role
from coiflink_api.domain.permissions import ROLE_PERMISSIONS, Permission, permissions_for


# ---------------------------------------------------------------------------
# Deny-by-default : rôles inconnus / forgés
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_role", [
    "",
    "UNKNOWN",
    "admin",   # casse incorrecte
    "client",
    "SUPERADMIN",
    "MANAGER_ASSISTANT",
])
def test_permissions_for_unknown_role_returns_empty(bad_role: str) -> None:
    assert permissions_for(bad_role) == frozenset()


def test_role_permissions_covers_all_known_roles() -> None:
    for role in Role:
        assert role in ROLE_PERMISSIONS, f"Role {role!r} absent de ROLE_PERMISSIONS"


# ---------------------------------------------------------------------------
# CLIENT
# ---------------------------------------------------------------------------

_CLIENT_EXPECTED = frozenset({
    Permission.SALON_READ_ANY,
    Permission.SERVICE_READ,
    Permission.PAYMENT_READ_OWN,
})

def test_client_has_exactly_its_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.CLIENT] == _CLIENT_EXPECTED


def test_client_cannot_manage_salon() -> None:
    perms = ROLE_PERMISSIONS[Role.CLIENT]
    assert Permission.SALON_CREATE not in perms
    assert Permission.SALON_UPDATE not in perms
    assert Permission.SALON_SET_STATUS not in perms


def test_client_cannot_manage_employees_or_cash() -> None:
    perms = ROLE_PERMISSIONS[Role.CLIENT]
    assert Permission.EMPLOYEE_MANAGE not in perms
    assert Permission.PAYMENT_RECORD not in perms
    assert Permission.CASH_JOURNAL_READ not in perms
    assert Permission.CUSTOMER_MANAGE not in perms


# ---------------------------------------------------------------------------
# PAYMENT_READ_OWN — CLIENT uniquement (US-5.5, #38)
# ---------------------------------------------------------------------------

def test_payment_read_own_in_client_only() -> None:
    """PAYMENT_READ_OWN appartient au seul rôle CLIENT (reçu numérique §11.2)."""
    assert Permission.PAYMENT_READ_OWN in ROLE_PERMISSIONS[Role.CLIENT]


def test_payment_read_own_not_in_manager() -> None:
    assert Permission.PAYMENT_READ_OWN not in ROLE_PERMISSIONS[Role.MANAGER]


def test_payment_read_own_not_in_hairdresser() -> None:
    assert Permission.PAYMENT_READ_OWN not in ROLE_PERMISSIONS[Role.HAIRDRESSER]


def test_payment_read_own_not_in_admin() -> None:
    assert Permission.PAYMENT_READ_OWN not in ROLE_PERMISSIONS[Role.ADMIN]


# ---------------------------------------------------------------------------
# HAIRDRESSER
# ---------------------------------------------------------------------------

_HAIRDRESSER_EXPECTED = frozenset({
    Permission.SALON_READ_OWN,
    Permission.SERVICE_READ,
    Permission.QUEUE_TICKET_UPDATE_STATUS,
    Permission.QUEUE_TICKET_READ_SALON,
})

def test_hairdresser_has_exactly_its_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.HAIRDRESSER] == _HAIRDRESSER_EXPECTED


def test_hairdresser_cannot_access_cash_or_employees() -> None:
    perms = ROLE_PERMISSIONS[Role.HAIRDRESSER]
    assert Permission.PAYMENT_RECORD not in perms
    assert Permission.CASH_JOURNAL_READ not in perms
    assert Permission.EMPLOYEE_MANAGE not in perms


# ---------------------------------------------------------------------------
# MANAGER
# ---------------------------------------------------------------------------

_MANAGER_EXPECTED = frozenset({
    Permission.SALON_CREATE,
    Permission.SALON_UPDATE,
    Permission.SALON_READ_OWN,
    Permission.SERVICE_MANAGE,
    Permission.SERVICE_READ,
    Permission.QUEUE_TICKET_UPDATE_STATUS,
    Permission.QUEUE_TICKET_READ_SALON,
    Permission.EMPLOYEE_MANAGE,
    Permission.CUSTOMER_MANAGE,
    Permission.PAYMENT_RECORD,
    Permission.CASH_JOURNAL_READ,
    Permission.STATS_READ_SALON,
    # Provisioning des bornes terminal de son salon (US-8.1, #155) — seul ajout.
    Permission.TERMINAL_PROVISION,
    # Journal d'audit de son salon — page « Journal d'audit ».
    Permission.AUDIT_LOG_READ,
})

def test_manager_has_exactly_its_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.MANAGER] == _MANAGER_EXPECTED


def test_manager_cannot_platform_supervise() -> None:
    perms = ROLE_PERMISSIONS[Role.MANAGER]
    assert Permission.SALON_SET_STATUS not in perms
    assert Permission.USER_MANAGE not in perms
    assert Permission.STATS_READ_PLATFORM not in perms
    assert Permission.SALON_READ_ANY not in perms


def test_manager_has_terminal_provision_only_among_terminal_permissions() -> None:
    """Le gérant provisionne les bornes (`TERMINAL_PROVISION`) mais n'est pas une borne.

    Il ne détient **aucune** des trois permissions **opérationnelles** de la borne
    (`CUSTOMER_LOOKUP_TERMINAL`/`CUSTOMER_CREATE_WALKIN`/`QUEUE_TICKET_CREATE`) : ce
    sont des droits du terminal, pas du gérant (US-8.1, #155).
    """
    perms = ROLE_PERMISSIONS[Role.MANAGER]
    assert Permission.TERMINAL_PROVISION in perms
    assert Permission.CUSTOMER_LOOKUP_TERMINAL not in perms
    assert Permission.CUSTOMER_CREATE_WALKIN not in perms
    assert Permission.QUEUE_TICKET_CREATE not in perms


# ---------------------------------------------------------------------------
# TERMINAL (borne terminal — US-8.1, #155)
# ---------------------------------------------------------------------------

_TERMINAL_EXPECTED = frozenset({
    Permission.CUSTOMER_LOOKUP_TERMINAL,
    Permission.CUSTOMER_CREATE_WALKIN,
    Permission.QUEUE_TICKET_CREATE,
})

def test_terminal_has_exactly_its_permissions() -> None:
    """La borne détient **exactement** ses trois permissions dédiées, ni plus ni moins."""
    assert ROLE_PERMISSIONS[Role.TERMINAL] == _TERMINAL_EXPECTED


def test_terminal_cannot_manage_customers() -> None:
    """Cœur du critère d'acceptation négatif : pas de `CUSTOMER_MANAGE`.

    Une borne (terminal public partagé) ne peut **pas** lire les fiches complètes /
    notes privées (`CUSTOMER_MANAGE`) — moindre privilège strict (ADR-0041).
    """
    perms = ROLE_PERMISSIONS[Role.TERMINAL]
    assert Permission.CUSTOMER_MANAGE not in perms


def test_terminal_cannot_provision_or_supervise() -> None:
    """La borne ne provisionne pas d'autres bornes ni n'accède à la caisse/stats/employés."""
    perms = ROLE_PERMISSIONS[Role.TERMINAL]
    assert Permission.TERMINAL_PROVISION not in perms
    assert Permission.PAYMENT_RECORD not in perms
    assert Permission.CASH_JOURNAL_READ not in perms
    assert Permission.STATS_READ_SALON not in perms
    assert Permission.EMPLOYEE_MANAGE not in perms
    assert Permission.SERVICE_READ not in perms


@pytest.mark.parametrize(
    "permission",
    [
        Permission.CUSTOMER_LOOKUP_TERMINAL,
        Permission.CUSTOMER_CREATE_WALKIN,
        Permission.QUEUE_TICKET_CREATE,
    ],
)
def test_terminal_permissions_are_terminal_only(permission: Permission) -> None:
    """Les trois permissions opérationnelles de borne n'appartiennent **qu'à** `TERMINAL`."""
    holders = {role for role, perms in ROLE_PERMISSIONS.items() if permission in perms}
    assert holders == {Role.TERMINAL}


# ---------------------------------------------------------------------------
# ADMIN
# ---------------------------------------------------------------------------

_ADMIN_EXPECTED = frozenset({
    Permission.SALON_READ_ANY,
    Permission.SALON_SET_STATUS,
    Permission.USER_MANAGE,
    Permission.STATS_READ_PLATFORM,
})

def test_admin_has_exactly_its_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.ADMIN] == _ADMIN_EXPECTED


def test_admin_cannot_exploit_salon_operations() -> None:
    """ADMIN supervise la plateforme, n'exploite pas un salon."""
    perms = ROLE_PERMISSIONS[Role.ADMIN]
    # Exploitation salon
    assert Permission.SALON_CREATE not in perms
    assert Permission.SALON_UPDATE not in perms
    assert Permission.SERVICE_MANAGE not in perms
    assert Permission.EMPLOYEE_MANAGE not in perms
    assert Permission.CUSTOMER_MANAGE not in perms
    assert Permission.PAYMENT_RECORD not in perms
    assert Permission.CASH_JOURNAL_READ not in perms
    assert Permission.STATS_READ_SALON not in perms


# ---------------------------------------------------------------------------
# permissions_for() — cohérence avec ROLE_PERMISSIONS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", list(Role))
def test_permissions_for_known_role_matches_table(role: Role) -> None:
    assert permissions_for(role.value) == ROLE_PERMISSIONS[role]


def test_role_permissions_table_is_closed_no_extra_keys() -> None:
    """Aucune clé autre que les 4 rôles connus dans la table."""
    assert set(ROLE_PERMISSIONS.keys()) == set(Role)
