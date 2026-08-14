"""Tests unitaires — règles de portée salon (domain/access.py, issue #12).

Couvre :
- `SalonScope` : constructeurs, `covers()` (vide, salon listé, platform_wide) ;
- `can_access_salon` : chaque rôle, compte inactif bloqué, isolation inter-salons.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.domain.access import SalonScope, can_access_salon
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.principal import Principal

# IDs synthétiques (aucune PII, aucun secret)
_SALON_A = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_SALON_B = uuid.UUID("bbbbbb00-0000-0000-0000-000000000002")
_USER_1  = uuid.UUID("11111100-0000-0000-0000-000000000001")


def _p(role: str, uid: uuid.UUID = _USER_1, status: str = UserStatus.ACTIVE.value) -> Principal:
    return Principal(id=uid, role=role, status=status)


# ---------------------------------------------------------------------------
# SalonScope
# ---------------------------------------------------------------------------

def test_scope_empty_covers_nothing() -> None:
    scope = SalonScope.empty()
    assert scope.covers(_SALON_A) is False
    assert scope.covers(_SALON_B) is False
    assert scope.platform_wide is False


def test_scope_of_covers_listed_salon() -> None:
    scope = SalonScope.of([_SALON_A])
    assert scope.covers(_SALON_A) is True
    assert scope.covers(_SALON_B) is False


def test_scope_of_multiple_salons() -> None:
    scope = SalonScope.of([_SALON_A, _SALON_B])
    assert scope.covers(_SALON_A) is True
    assert scope.covers(_SALON_B) is True


def test_scope_platform_covers_any_salon() -> None:
    scope = SalonScope.platform()
    assert scope.platform_wide is True
    assert scope.covers(_SALON_A) is True
    assert scope.covers(_SALON_B) is True
    assert scope.covers(uuid.uuid4()) is True


def test_scope_empty_is_not_platform_wide() -> None:
    assert SalonScope.empty().platform_wide is False


def test_scope_of_is_not_platform_wide() -> None:
    assert SalonScope.of([_SALON_A]).platform_wide is False


def test_scope_is_frozen() -> None:
    scope = SalonScope.of([_SALON_A])
    with pytest.raises((TypeError, AttributeError)):
        scope.platform_wide = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# can_access_salon
# ---------------------------------------------------------------------------

class TestCanAccessSalon:
    def test_admin_always_true(self) -> None:
        p = _p(Role.ADMIN.value)
        assert can_access_salon(p, _SALON_A, SalonScope.empty()) is True
        assert can_access_salon(p, _SALON_B, SalonScope.empty()) is True

    def test_manager_in_scope_true(self) -> None:
        p = _p(Role.MANAGER.value)
        scope = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_A, scope) is True

    def test_manager_outside_scope_false(self) -> None:
        p = _p(Role.MANAGER.value)
        scope = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_B, scope) is False

    def test_hairdresser_in_scope_true(self) -> None:
        p = _p(Role.HAIRDRESSER.value)
        scope = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_A, scope) is True

    def test_hairdresser_outside_scope_false(self) -> None:
        p = _p(Role.HAIRDRESSER.value)
        scope = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_B, scope) is False

    def test_client_never_has_salon_access(self) -> None:
        p = _p(Role.CLIENT.value)
        # Même avec une portée généreuse, CLIENT n'a pas accès aux données d'un salon
        assert can_access_salon(p, _SALON_A, SalonScope.platform()) is False

    @pytest.mark.parametrize("role", [Role.CLIENT, Role.HAIRDRESSER, Role.MANAGER, Role.ADMIN, Role.TERMINAL])
    def test_inactive_account_denied_for_all_roles(self, role: Role) -> None:
        p = _p(role.value, status=UserStatus.INACTIVE.value)
        assert can_access_salon(p, _SALON_A, SalonScope.platform()) is False

    @pytest.mark.parametrize("role", [Role.CLIENT, Role.HAIRDRESSER, Role.MANAGER, Role.ADMIN, Role.TERMINAL])
    def test_suspended_account_denied_for_all_roles(self, role: Role) -> None:
        p = _p(role.value, status=UserStatus.SUSPENDED.value)
        assert can_access_salon(p, _SALON_A, SalonScope.platform()) is False

    def test_cross_salon_isolation_manager(self) -> None:
        """Un gérant du salon A ne peut pas accéder au salon B."""
        manager_a = _p(Role.MANAGER.value, uid=_USER_1)
        scope_a = SalonScope.of([_SALON_A])
        assert can_access_salon(manager_a, _SALON_B, scope_a) is False

    def test_unknown_role_denied(self) -> None:
        p = _p("GHOST_ROLE")
        assert can_access_salon(p, _SALON_A, SalonScope.platform()) is False

    # --- TERMINAL (borne terminal, US-8.1, #155) ---

    def test_terminal_in_scope_true(self) -> None:
        """La borne accède à son salon de rattachement (portée mono-salon, §11.2)."""
        p = _p(Role.TERMINAL.value)
        scope = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_A, scope) is True

    def test_terminal_outside_scope_false(self) -> None:
        """La borne est refusée sur un salon hors sa portée (isolation §11.2)."""
        p = _p(Role.TERMINAL.value)
        scope = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_B, scope) is False

    def test_terminal_empty_scope_false(self) -> None:
        p = _p(Role.TERMINAL.value)
        assert can_access_salon(p, _SALON_A, SalonScope.empty()) is False

    def test_terminal_cross_salon_isolation(self) -> None:
        """Une borne du salon A ne peut pas accéder au salon B (isolation inter-salons)."""
        p = _p(Role.TERMINAL.value)
        scope_a = SalonScope.of([_SALON_A])
        assert can_access_salon(p, _SALON_B, scope_a) is False
