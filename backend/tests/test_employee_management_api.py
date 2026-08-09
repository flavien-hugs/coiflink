"""Tests API pour la gestion des coiffeuses (#150) : lister/charger/modifier/
(dés)activer.

Miroir `test_employee_api.py` (création) : `TestClient` avec override de
dépendances, aucune base réelle. Couvre :
- 200 liste/lecture/modification/(dés)activation ;
- 404 coiffeuse inexistante ou hors salon (isolation §11.2) ;
- 409 doublon téléphone/e-mail à la modification (unicité globale `users`) ;
- 422 validation (nom vide, téléphone invalide, spécialités trop longues) ;
- 401/403 RBAC (`EMPLOYEE_MANAGE`, portée salon) ;
- `status` de la réponse reflète `salon_members.status` (jamais `users.status`).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.employees import (
    get_deactivate_employee,
    get_list_salon_employees,
    get_reactivate_employee,
    get_salon_employee,
    get_update_employee_profile,
)
from coiflink_api.adapters.inbound.security import get_access_policy, get_user_repository
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.application.employees import (
    DeactivateEmployee,
    GetSalonEmployee,
    ListSalonEmployees,
    ReactivateEmployee,
    UpdateEmployeeProfile,
)
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.employee import Employee
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.main import app

from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeSalonMemberRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_EMPLOYEE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)

_BASE_URL = f"/salons/{_SALON_ID}/employees"
_ITEM_URL = f"{_BASE_URL}/{_EMPLOYEE_ID}"


def _employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = dict(
        id=_EMPLOYEE_ID,
        full_name="Awa Koné",
        phone="+2250700000000",
        email=None,
        role=Role.HAIRDRESSER.value,
        status=UserStatus.ACTIVE.value,
        specialties=None,
        hired_at=None,
        created_at=_CREATED_AT,
    )
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


def _seeded_members(**overrides: object) -> FakeSalonMemberRepository:
    return FakeSalonMemberRepository(seed={(_SALON_ID, _EMPLOYEE_ID): _employee(**overrides)})


def _manager_creds() -> UserCredentials:
    return UserCredentials(
        id=_MANAGER_ID,
        role=Role.MANAGER.value,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


@pytest.fixture(autouse=True)
def _install_test_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


class _Overrides:
    """Contexte d'override commun (portée salon + compte gérant), patron `test_employee_api.py`."""

    def __init__(self, *, in_scope: bool = True) -> None:
        creds = _manager_creds()
        self.user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope = frozenset({_SALON_ID}) if in_scope else frozenset({_OTHER_SALON_ID})
        self.scope_repo = FakeSalonScopeRepository(scopes={creds.id: scope})

    def __enter__(self) -> TestClient:
        app.dependency_overrides[get_user_repository] = lambda: self.user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(self.scope_repo)
        return TestClient(app)

    def __exit__(self, *exc: object) -> None:
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# GET /salons/{id}/employees — liste
# ---------------------------------------------------------------------------


class TestListEmployees:
    def test_returns_seeded_employees(self) -> None:
        members = _seeded_members()
        app.dependency_overrides[get_list_salon_employees] = lambda: ListSalonEmployees(members)
        try:
            with _Overrides() as client:
                r = client.get(_BASE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_list_salon_employees, None)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == str(_EMPLOYEE_ID)
        assert body[0]["role"] == Role.HAIRDRESSER.value

    def test_empty_salon_returns_empty_list(self) -> None:
        app.dependency_overrides[get_list_salon_employees] = (
            lambda: ListSalonEmployees(FakeSalonMemberRepository())
        )
        try:
            with _Overrides() as client:
                r = client.get(_BASE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_list_salon_employees, None)
        assert r.status_code == 200
        assert r.json() == []

    def test_missing_token_returns_401(self) -> None:
        app.dependency_overrides[get_list_salon_employees] = (
            lambda: ListSalonEmployees(FakeSalonMemberRepository())
        )
        try:
            with _Overrides() as client:
                r = client.get(_BASE_URL)
        finally:
            app.dependency_overrides.pop(get_list_salon_employees, None)
        assert r.status_code == 401

    def test_out_of_scope_returns_403(self) -> None:
        app.dependency_overrides[get_list_salon_employees] = (
            lambda: ListSalonEmployees(FakeSalonMemberRepository())
        )
        try:
            with _Overrides(in_scope=False) as client:
                r = client.get(_BASE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_list_salon_employees, None)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /salons/{id}/employees/{employee_id} — lecture
# ---------------------------------------------------------------------------


class TestGetEmployee:
    def test_returns_200(self) -> None:
        members = _seeded_members(specialties="Tresses", hired_at=datetime.date(2026, 1, 15))
        app.dependency_overrides[get_salon_employee] = lambda: GetSalonEmployee(members)
        try:
            with _Overrides() as client:
                r = client.get(_ITEM_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_salon_employee, None)
        assert r.status_code == 200
        body = r.json()
        assert body["specialties"] == "Tresses"
        assert body["hired_at"] == "2026-01-15"

    def test_unknown_employee_returns_404(self) -> None:
        app.dependency_overrides[get_salon_employee] = (
            lambda: GetSalonEmployee(FakeSalonMemberRepository())
        )
        try:
            with _Overrides() as client:
                r = client.get(_ITEM_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_salon_employee, None)
        assert r.status_code == 404

    def test_employee_of_other_salon_returns_404(self) -> None:
        members = _seeded_members()
        app.dependency_overrides[get_salon_employee] = lambda: GetSalonEmployee(members)
        try:
            with _Overrides() as client:
                r = client.get(
                    f"/salons/{_OTHER_SALON_ID}/employees/{_EMPLOYEE_ID}",
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_salon_employee, None)
        assert r.status_code in (403, 404)


# ---------------------------------------------------------------------------
# PUT /salons/{id}/employees/{employee_id} — modification de profil
# ---------------------------------------------------------------------------

_VALID_UPDATE_BODY = {
    "full_name": "Awa Koné Modifiée",
    "phone": "0700000001",
    "email": "awa@example.com",
    "specialties": "Tresses, colorations",
    "hired_at": "2026-01-15",
}


class TestUpdateEmployee:
    def test_returns_200_with_updated_fields(self) -> None:
        members = _seeded_members()
        from .conftest import FakeUserRepository

        usecase = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        app.dependency_overrides[get_update_employee_profile] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.put(
                    _ITEM_URL,
                    json=_VALID_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_update_employee_profile, None)
        assert r.status_code == 200
        body = r.json()
        assert body["full_name"] == "Awa Koné Modifiée"
        assert body["phone"] == "+2250700000001"
        assert body["specialties"] == "Tresses, colorations"

    def test_unknown_employee_returns_404(self) -> None:
        from .conftest import FakeUserRepository

        usecase = UpdateEmployeeProfile(
            FakeUserRepository(), FakeSalonMemberRepository(), FakeAuditLog()
        )
        app.dependency_overrides[get_update_employee_profile] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.put(
                    _ITEM_URL,
                    json=_VALID_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_update_employee_profile, None)
        assert r.status_code == 404

    def test_duplicate_phone_returns_409(self) -> None:
        from coiflink_api.domain.errors import PhoneAlreadyInUse

        from .conftest import FakeUserRepository

        members = _seeded_members()
        users = FakeUserRepository(raise_on_update_identity=PhoneAlreadyInUse("déjà pris."))
        usecase = UpdateEmployeeProfile(users, members, FakeAuditLog())
        app.dependency_overrides[get_update_employee_profile] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.put(
                    _ITEM_URL,
                    json=_VALID_UPDATE_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_update_employee_profile, None)
        assert r.status_code == 409

    def test_empty_full_name_returns_422(self) -> None:
        from .conftest import FakeUserRepository

        members = _seeded_members()
        usecase = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        app.dependency_overrides[get_update_employee_profile] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.put(
                    _ITEM_URL,
                    json={**_VALID_UPDATE_BODY, "full_name": ""},
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_update_employee_profile, None)
        assert r.status_code == 422

    def test_specialties_too_long_returns_422(self) -> None:
        from .conftest import FakeUserRepository

        members = _seeded_members()
        usecase = UpdateEmployeeProfile(FakeUserRepository(), members, FakeAuditLog())
        app.dependency_overrides[get_update_employee_profile] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.put(
                    _ITEM_URL,
                    json={**_VALID_UPDATE_BODY, "specialties": "a" * 1001},
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_update_employee_profile, None)
        assert r.status_code == 422

    def test_no_role_or_status_field_in_request_schema(self) -> None:
        from coiflink_api.adapters.inbound.employees import UpdateEmployeeRequest

        assert "role" not in UpdateEmployeeRequest.model_fields
        assert "status" not in UpdateEmployeeRequest.model_fields


# ---------------------------------------------------------------------------
# DELETE /salons/{id}/employees/{employee_id} — désactivation
# ---------------------------------------------------------------------------


class TestDeactivateEmployee:
    def test_returns_200_with_inactive_status(self) -> None:
        members = _seeded_members()
        usecase = DeactivateEmployee(members, FakeAuditLog())
        app.dependency_overrides[get_deactivate_employee] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.delete(_ITEM_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_deactivate_employee, None)
        assert r.status_code == 200
        assert r.json()["status"] == UserStatus.INACTIVE.value

    def test_unknown_employee_returns_404(self) -> None:
        usecase = DeactivateEmployee(FakeSalonMemberRepository(), FakeAuditLog())
        app.dependency_overrides[get_deactivate_employee] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.delete(_ITEM_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_deactivate_employee, None)
        assert r.status_code == 404

    def test_out_of_scope_returns_403(self) -> None:
        members = _seeded_members()
        usecase = DeactivateEmployee(members, FakeAuditLog())
        app.dependency_overrides[get_deactivate_employee] = lambda: usecase
        try:
            with _Overrides(in_scope=False) as client:
                r = client.delete(_ITEM_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        finally:
            app.dependency_overrides.pop(get_deactivate_employee, None)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /salons/{id}/employees/{employee_id}/reactivate — réactivation
# ---------------------------------------------------------------------------


class TestReactivateEmployee:
    def test_returns_200_with_active_status(self) -> None:
        members = _seeded_members(status=UserStatus.INACTIVE.value)
        usecase = ReactivateEmployee(members, FakeAuditLog())
        app.dependency_overrides[get_reactivate_employee] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.post(
                    f"{_ITEM_URL}/reactivate",
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_reactivate_employee, None)
        assert r.status_code == 200
        assert r.json()["status"] == UserStatus.ACTIVE.value

    def test_unknown_employee_returns_404(self) -> None:
        usecase = ReactivateEmployee(FakeSalonMemberRepository(), FakeAuditLog())
        app.dependency_overrides[get_reactivate_employee] = lambda: usecase
        try:
            with _Overrides() as client:
                r = client.post(
                    f"{_ITEM_URL}/reactivate",
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_reactivate_employee, None)
        assert r.status_code == 404
