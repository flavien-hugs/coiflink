"""Tests unitaires — Principal (domain/principal.py, issue #12).

Couvre :
- `is_active` pour chaque statut de compte ;
- `has_permission` : compte actif avec/sans la permission, compte inactif bloqué ;
- `has_role` : rôle correct, rôle incorrect, compte inactif bloqué ;
- `permissions` : cohérence avec `permissions_for()` ;
- invariant PII : le Principal ne transporte aucun champ personnel.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

_ID = uuid.UUID("00000000-0000-0000-0000-000000000042")


def _principal(role: str, status: str = UserStatus.ACTIVE.value) -> Principal:
    return Principal(id=_ID, role=role, status=status)


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------

def test_active_account_is_active() -> None:
    assert _principal(Role.CLIENT.value, UserStatus.ACTIVE.value).is_active is True


@pytest.mark.parametrize("status", [UserStatus.INACTIVE.value, UserStatus.SUSPENDED.value])
def test_non_active_account_is_not_active(status: str) -> None:
    assert _principal(Role.CLIENT.value, status).is_active is False


# ---------------------------------------------------------------------------
# has_permission — compte actif
# ---------------------------------------------------------------------------

def test_active_client_has_salon_read_any() -> None:
    p = _principal(Role.CLIENT.value)
    assert p.has_permission(Permission.SALON_READ_ANY) is True


def test_active_client_does_not_have_salon_create() -> None:
    p = _principal(Role.CLIENT.value)
    assert p.has_permission(Permission.SALON_CREATE) is False


def test_active_manager_has_salon_create() -> None:
    p = _principal(Role.MANAGER.value)
    assert p.has_permission(Permission.SALON_CREATE) is True


def test_active_admin_has_user_manage() -> None:
    p = _principal(Role.ADMIN.value)
    assert p.has_permission(Permission.USER_MANAGE) is True


def test_active_admin_does_not_have_payment_record() -> None:
    p = _principal(Role.ADMIN.value)
    assert p.has_permission(Permission.PAYMENT_RECORD) is False


# ---------------------------------------------------------------------------
# has_permission — compte inactif bloqué (défense en profondeur)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [UserStatus.INACTIVE.value, UserStatus.SUSPENDED.value])
def test_inactive_principal_has_no_permission(status: str) -> None:
    p = _principal(Role.MANAGER.value, status)
    for perm in Permission:
        assert p.has_permission(perm) is False, f"MANAGER inactif ne doit pas avoir {perm}"


# ---------------------------------------------------------------------------
# has_permission — rôle inconnu
# ---------------------------------------------------------------------------

def test_unknown_role_active_account_has_no_permission() -> None:
    p = _principal("PHANTOM_ROLE")
    for perm in Permission:
        assert p.has_permission(perm) is False


# ---------------------------------------------------------------------------
# has_role
# ---------------------------------------------------------------------------

def test_has_role_matches_own_role() -> None:
    p = _principal(Role.MANAGER.value)
    assert p.has_role(Role.MANAGER) is True


def test_has_role_does_not_match_other_role() -> None:
    p = _principal(Role.CLIENT.value)
    assert p.has_role(Role.ADMIN) is False


def test_has_role_inactive_always_false() -> None:
    p = _principal(Role.ADMIN.value, UserStatus.INACTIVE.value)
    assert p.has_role(Role.ADMIN) is False


def test_has_role_accepts_multiple_roles_one_matches() -> None:
    p = _principal(Role.HAIRDRESSER.value)
    assert p.has_role(Role.CLIENT, Role.HAIRDRESSER) is True


def test_has_role_accepts_multiple_roles_none_match() -> None:
    p = _principal(Role.CLIENT.value)
    assert p.has_role(Role.MANAGER, Role.ADMIN) is False


# ---------------------------------------------------------------------------
# permissions property
# ---------------------------------------------------------------------------

def test_permissions_property_returns_role_permissions() -> None:
    from coiflink_api.domain.permissions import ROLE_PERMISSIONS
    p = _principal(Role.HAIRDRESSER.value)
    assert p.permissions == ROLE_PERMISSIONS[Role.HAIRDRESSER]


def test_permissions_property_unknown_role_empty() -> None:
    p = _principal("GHOST")
    assert p.permissions == frozenset()


# ---------------------------------------------------------------------------
# Invariant PII : Principal ne contient pas de champs personnels
# ---------------------------------------------------------------------------

def test_principal_fields_are_only_id_role_status() -> None:
    p = _principal(Role.CLIENT.value)
    field_names = {f.name for f in p.__dataclass_fields__.values()}  # type: ignore[union-attr]
    assert field_names == {"id", "role", "status"}
