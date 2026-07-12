"""Tests unitaires — AccessPolicy (application/authorization.py, issue #12).

Couvre :
- `require_roles` : rôle correct, rôle incorrect, compte inactif ;
- `require_permission` : permission accordée, permission refusée, compte inactif ;
- `scope_of` : ADMIN court-circuite le dépôt (portée plateforme sans I/O),
               compte inactif → portée vide (deny-by-default),
               compte actif non-ADMIN → dépôt sollicité ;
- `require_salon` : salon dans la portée autorisé, salon hors portée levé PermissionDenied,
                    isolation CLIENT (jamais de portée salon), isolation inter-salons.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import PermissionDenied
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

from .conftest import FakeSalonScopeRepository

_ID1 = uuid.UUID("11111100-0000-0000-0000-000000000001")
_ID2 = uuid.UUID("22222200-0000-0000-0000-000000000002")
_SALON_A = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_SALON_B = uuid.UUID("bbbbbb00-0000-0000-0000-000000000002")


def _p(role: str, uid: uuid.UUID = _ID1, status: str = UserStatus.ACTIVE.value) -> Principal:
    return Principal(id=uid, role=role, status=status)


def _policy(scopes: dict[uuid.UUID, frozenset[uuid.UUID]] | None = None) -> AccessPolicy:
    return AccessPolicy(FakeSalonScopeRepository(scopes=scopes))


# ---------------------------------------------------------------------------
# require_roles
# ---------------------------------------------------------------------------

class TestRequireRoles:
    def test_matching_role_passes(self) -> None:
        policy = _policy()
        p = _p(Role.MANAGER.value)
        policy.require_roles(p, Role.MANAGER)  # should not raise

    def test_non_matching_role_raises(self) -> None:
        policy = _policy()
        p = _p(Role.CLIENT.value)
        with pytest.raises(PermissionDenied):
            policy.require_roles(p, Role.MANAGER)

    def test_one_of_multiple_roles_passes(self) -> None:
        policy = _policy()
        p = _p(Role.HAIRDRESSER.value)
        policy.require_roles(p, Role.MANAGER, Role.HAIRDRESSER)  # should not raise

    def test_inactive_account_denied_even_matching_role(self) -> None:
        policy = _policy()
        p = _p(Role.ADMIN.value, status=UserStatus.INACTIVE.value)
        with pytest.raises(PermissionDenied):
            policy.require_roles(p, Role.ADMIN)


# ---------------------------------------------------------------------------
# require_permission
# ---------------------------------------------------------------------------

class TestRequirePermission:
    def test_granted_permission_passes(self) -> None:
        policy = _policy()
        p = _p(Role.MANAGER.value)
        policy.require_permission(p, Permission.SALON_CREATE)  # should not raise

    def test_denied_permission_raises(self) -> None:
        policy = _policy()
        p = _p(Role.CLIENT.value)
        with pytest.raises(PermissionDenied):
            policy.require_permission(p, Permission.SALON_CREATE)

    def test_inactive_account_denied_even_with_right_role(self) -> None:
        policy = _policy()
        p = _p(Role.MANAGER.value, status=UserStatus.SUSPENDED.value)
        with pytest.raises(PermissionDenied):
            policy.require_permission(p, Permission.SALON_CREATE)

    def test_admin_denied_salon_exploitation_permission(self) -> None:
        policy = _policy()
        p = _p(Role.ADMIN.value)
        with pytest.raises(PermissionDenied):
            policy.require_permission(p, Permission.PAYMENT_RECORD)


# ---------------------------------------------------------------------------
# scope_of
# ---------------------------------------------------------------------------

class TestScopeOf:
    def test_admin_gets_platform_scope_without_calling_repo(self) -> None:
        repo = FakeSalonScopeRepository()
        policy = AccessPolicy(repo)
        p = _p(Role.ADMIN.value)
        scope = policy.scope_of(p)
        assert scope.platform_wide is True
        assert repo.calls == [], "ADMIN ne doit pas solliciter le dépôt"

    def test_inactive_account_gets_empty_scope(self) -> None:
        repo = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A})})
        policy = AccessPolicy(repo)
        p = _p(Role.MANAGER.value, status=UserStatus.INACTIVE.value)
        scope = policy.scope_of(p)
        assert scope == SalonScope.empty()
        # Le dépôt ne doit pas non plus être sollicité pour un compte inactif
        assert repo.calls == []

    def test_manager_scope_from_repo(self) -> None:
        repo = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A})})
        policy = AccessPolicy(repo)
        p = _p(Role.MANAGER.value, uid=_ID1)
        scope = policy.scope_of(p)
        assert scope.covers(_SALON_A) is True
        assert scope.covers(_SALON_B) is False
        assert len(repo.calls) == 1
        assert repo.calls[0] == (_ID1, Role.MANAGER.value)

    def test_client_scope_from_repo_returns_empty(self) -> None:
        # FakeSalonScopeRepository retourne frozenset() pour les IDs inconnus
        repo = FakeSalonScopeRepository()
        policy = AccessPolicy(repo)
        p = _p(Role.CLIENT.value, uid=_ID1)
        scope = policy.scope_of(p)
        assert scope == SalonScope.empty()

    def test_hairdresser_scope_from_repo(self) -> None:
        repo = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A, _SALON_B})})
        policy = AccessPolicy(repo)
        p = _p(Role.HAIRDRESSER.value, uid=_ID1)
        scope = policy.scope_of(p)
        assert scope.covers(_SALON_A) is True
        assert scope.covers(_SALON_B) is True


# ---------------------------------------------------------------------------
# require_salon
# ---------------------------------------------------------------------------

class TestRequireSalon:
    def test_manager_in_scope_passes_and_returns_scope(self) -> None:
        repo = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A})})
        policy = AccessPolicy(repo)
        p = _p(Role.MANAGER.value, uid=_ID1)
        scope = policy.require_salon(p, _SALON_A)
        assert scope.covers(_SALON_A) is True

    def test_manager_out_of_scope_raises(self) -> None:
        repo = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A})})
        policy = AccessPolicy(repo)
        p = _p(Role.MANAGER.value, uid=_ID1)
        with pytest.raises(PermissionDenied):
            policy.require_salon(p, _SALON_B)

    def test_cross_salon_blocked(self) -> None:
        """Gérant du salon A bloqué sur le salon B (isolation inter-salons)."""
        repo_a = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A})})
        policy = AccessPolicy(repo_a)
        manager_a = _p(Role.MANAGER.value, uid=_ID1)
        with pytest.raises(PermissionDenied):
            policy.require_salon(manager_a, _SALON_B)

    def test_client_always_denied_salon_access(self) -> None:
        """CLIENT n'a jamais de portée salon, même avec un scope riche."""
        repo = FakeSalonScopeRepository()
        policy = AccessPolicy(repo)
        p = _p(Role.CLIENT.value, uid=_ID1)
        with pytest.raises(PermissionDenied):
            policy.require_salon(p, _SALON_A)

    def test_admin_always_granted(self) -> None:
        repo = FakeSalonScopeRepository()
        policy = AccessPolicy(repo)
        p = _p(Role.ADMIN.value)
        scope = policy.require_salon(p, _SALON_A)
        assert scope.platform_wide is True

    def test_inactive_manager_denied(self) -> None:
        repo = FakeSalonScopeRepository(scopes={_ID1: frozenset({_SALON_A})})
        policy = AccessPolicy(repo)
        p = _p(Role.MANAGER.value, uid=_ID1, status=UserStatus.INACTIVE.value)
        with pytest.raises(PermissionDenied):
            policy.require_salon(p, _SALON_A)

    def test_permission_denied_message_is_generic(self) -> None:
        """Le message du refus est générique : aucun oracle sur ce qui existe."""
        repo = FakeSalonScopeRepository()
        policy = AccessPolicy(repo)
        p = _p(Role.CLIENT.value, uid=_ID1)
        try:
            policy.require_salon(p, _SALON_A)
        except PermissionDenied as exc:
            assert str(exc) == "Accès refusé.", f"Message non générique : {exc!r}"
        else:
            pytest.fail("PermissionDenied attendue")
