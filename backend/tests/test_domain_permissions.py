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
    Permission.APPOINTMENT_BOOK,
    Permission.APPOINTMENT_READ_OWN,
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


def test_client_cannot_read_any_appointment_other_than_own() -> None:
    perms = ROLE_PERMISSIONS[Role.CLIENT]
    assert Permission.APPOINTMENT_READ_ASSIGNED not in perms
    assert Permission.APPOINTMENT_READ_SALON not in perms
    assert Permission.APPOINTMENT_MANAGE not in perms


# ---------------------------------------------------------------------------
# HAIRDRESSER
# ---------------------------------------------------------------------------

_HAIRDRESSER_EXPECTED = frozenset({
    Permission.SALON_READ_OWN,
    Permission.SERVICE_READ,
    Permission.APPOINTMENT_READ_ASSIGNED,
    Permission.APPOINTMENT_UPDATE_STATUS,
})

def test_hairdresser_has_exactly_its_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.HAIRDRESSER] == _HAIRDRESSER_EXPECTED


def test_hairdresser_cannot_book_or_read_all_appointments() -> None:
    perms = ROLE_PERMISSIONS[Role.HAIRDRESSER]
    assert Permission.APPOINTMENT_BOOK not in perms
    assert Permission.APPOINTMENT_READ_OWN not in perms
    assert Permission.APPOINTMENT_READ_SALON not in perms
    assert Permission.APPOINTMENT_MANAGE not in perms


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
    Permission.APPOINTMENT_MANAGE,
    Permission.APPOINTMENT_READ_SALON,
    Permission.APPOINTMENT_UPDATE_STATUS,
    Permission.EMPLOYEE_MANAGE,
    Permission.CUSTOMER_MANAGE,
    Permission.PAYMENT_RECORD,
    Permission.CASH_JOURNAL_READ,
    Permission.STATS_READ_SALON,
})

def test_manager_has_exactly_its_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.MANAGER] == _MANAGER_EXPECTED


def test_manager_cannot_platform_supervise() -> None:
    perms = ROLE_PERMISSIONS[Role.MANAGER]
    assert Permission.SALON_SET_STATUS not in perms
    assert Permission.USER_MANAGE not in perms
    assert Permission.STATS_READ_PLATFORM not in perms
    assert Permission.SALON_READ_ANY not in perms


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
    assert Permission.APPOINTMENT_MANAGE not in perms
    assert Permission.APPOINTMENT_BOOK not in perms
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
