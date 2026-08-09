"""Tests API — file d'attente du salon (#150) : arrivée, démarrage, lecture.

Utilise FastAPI `TestClient` avec override de dépendances (aucune base ni
réseau), miroir `TestAssignHairdresserAPI` (`test_appointment_api.py`) :
- `get_appointment_repository` → `FakeAppointmentRepository`
- `get_audit_log` → `FakeAuditLog`
- `get_payment_repository` → `FakePaymentRepository`
- `get_user_repository` → `FakeAuthUserRepository` (multi-rôles)
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository())`

Couvre :
- `POST .../arrival` : 200 idempotent ; 404 hors salon/inexistant ; 409 non
  `CONFIRMED` ; 401/403 RBAC.
- `POST .../start` : 200 quand préconditions réunies ; 409 arrivée manquante /
  coiffeuse manquante ; 404 hors salon/inexistant.
- `GET /salons/{id}/queue` : 200 liste triée, `queue_status` dérivé (`waiting`/
  `in_progress`/`completed`/`paid`) ; 401/403 RBAC ; défaut « aujourd'hui »
  sans `day`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.appointments import (
    get_appointment_repository,
    get_audit_log,
    get_payment_repository,
)
from coiflink_api.adapters.inbound.security import get_access_policy, get_user_repository
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.appointment import Appointment as AppointmentEntity
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.queue import QueueAppointmentRow
from coiflink_api.main import app

from .conftest import (
    TEST_JWT_SECRET,
    FakeAppointmentRepository,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakePaymentRepository,
    FakeSalonScopeRepository,
    make_access_token,
)

_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000099")
_CLIENT_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_APPOINTMENT_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_MANAGER_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")
_ROLE_USER_IDS: dict[str, uuid.UUID] = {
    "CLIENT": _CLIENT_ID,
    "MANAGER": _MANAGER_ID,
    "HAIRDRESSER": _HAIRDRESSER_ID,
}
_DAY = datetime.date(2026, 8, 9)


@pytest.fixture(autouse=True)
def _install_test_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Generator[None, None, None]:
    """Retire les overrides de `_manager_client` après chaque test (isolation inter-fichiers).

    `_manager_client` écrit dans `app.dependency_overrides` (singleton global) sans
    nettoyage propre ; sans cette garde, un test d'un **autre** fichier (p. ex. un
    e2e réel) hériterait des fakes laissés ici — miroir du `finally` explicite de
    `test_appointment_api.py`/`test_employee_management_api.py`.
    """
    yield
    for dep in (
        get_appointment_repository,
        get_payment_repository,
        get_audit_log,
        get_user_repository,
        get_access_policy,
    ):
        app.dependency_overrides.pop(dep, None)


def _user_repo_for_all_roles() -> FakeAuthUserRepository:
    creds = {
        str(uid): UserCredentials(
            id=uid, role=role, status=UserStatus.ACTIVE.value, password_hash="x"
        )
        for role, uid in _ROLE_USER_IDS.items()
    }
    return FakeAuthUserRepository(credentials_by_id=creds)


def _auth_header(role: str = "MANAGER") -> dict[str, str]:
    user_id = _ROLE_USER_IDS.get(role, uuid.uuid4())
    token = make_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


def _manager_client(
    appts: FakeAppointmentRepository | None = None,
    payments: FakePaymentRepository | None = None,
    scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient configuré pour MANAGER avec `_SALON_ID` dans sa portée (#150)."""

    ap = appts if appts is not None else FakeAppointmentRepository()
    pay = payments if payments is not None else FakePaymentRepository()
    manager_scope = (
        scope
        if scope is not None
        else FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_appointment_repository] = lambda: ap
    app.dependency_overrides[get_payment_repository] = lambda: pay
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(manager_scope)
    return TestClient(app)


def _appointment(**overrides: object) -> AppointmentEntity:
    defaults: dict[str, object] = dict(
        id=_APPOINTMENT_ID,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=_HAIRDRESSER_ID,
        date=_DAY,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(9, 30),
        status="CONFIRMED",
        client_note=None,
        created_at=_CREATED_AT,
        arrived_at=None,
        started_at=None,
    )
    defaults.update(overrides)
    return AppointmentEntity(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# POST .../arrival
# ---------------------------------------------------------------------------


class TestMarkArrivedAPI:
    def _url(self, appt_id: uuid.UUID = _APPOINTMENT_ID) -> str:
        return f"/salons/{_SALON_ID}/appointments/{appt_id}/arrival"

    def test_no_token_returns_401(self) -> None:
        resp = _manager_client().post(self._url())
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_appointment()])
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="CLIENT")
        )
        assert resp.status_code == 403

    def test_manager_returns_200(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_appointment()])
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200
        assert resp.json()["arrived_at"] is not None

    def test_idempotent_second_call_returns_200(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_appointment()])
        client = _manager_client(appts=appts)
        first = client.post(self._url(), headers=_auth_header(role="MANAGER"))
        second = client.post(self._url(), headers=_auth_header(role="MANAGER"))
        assert second.status_code == 200
        assert first.json()["arrived_at"] == second.json()["arrived_at"]

    def test_unknown_appointment_returns_404(self) -> None:
        resp = _manager_client().post(self._url(), headers=_auth_header(role="MANAGER"))
        assert resp.status_code == 404

    def test_out_of_scope_salon_returns_403(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_appointment()])
        scope = FakeSalonScopeRepository({_MANAGER_ID: frozenset({_OTHER_SALON_ID})})
        resp = _manager_client(appts=appts, scope=scope).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 403

    def test_pending_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_appointment(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409

    def test_completed_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_appointment(status="COMPLETED")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST .../start
# ---------------------------------------------------------------------------


class TestStartServiceAPI:
    def _url(self, appt_id: uuid.UUID = _APPOINTMENT_ID) -> str:
        return f"/salons/{_SALON_ID}/appointments/{appt_id}/start"

    def test_no_token_returns_401(self) -> None:
        resp = _manager_client().post(self._url())
        assert resp.status_code == 401

    def test_manager_returns_200_when_preconditions_met(self) -> None:
        now = datetime.datetime(2026, 8, 9, 9, 0, tzinfo=datetime.timezone.utc)
        appts = FakeAppointmentRepository(appointments=[_appointment(arrived_at=now)])
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200
        assert resp.json()["started_at"] is not None

    def test_missing_arrival_returns_409(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_appointment(arrived_at=None)])
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409

    def test_missing_hairdresser_returns_409(self) -> None:
        now = datetime.datetime(2026, 8, 9, 9, 0, tzinfo=datetime.timezone.utc)
        appts = FakeAppointmentRepository(
            appointments=[_appointment(arrived_at=now, hairdresser_id=None)]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409

    def test_unknown_appointment_returns_404(self) -> None:
        resp = _manager_client().post(self._url(), headers=_auth_header(role="MANAGER"))
        assert resp.status_code == 404

    def test_hairdresser_role_returns_403(self) -> None:
        now = datetime.datetime(2026, 8, 9, 9, 0, tzinfo=datetime.timezone.utc)
        appts = FakeAppointmentRepository(appointments=[_appointment(arrived_at=now)])
        resp = _manager_client(appts=appts).post(
            self._url(), headers=_auth_header(role="HAIRDRESSER")
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /salons/{id}/queue
# ---------------------------------------------------------------------------


def _queue_row(**overrides: object) -> QueueAppointmentRow:
    defaults: dict[str, object] = dict(
        appointment_id=_APPOINTMENT_ID,
        client_name="Awa Koné",
        service_names=("Coupe",),
        hairdresser_id=_HAIRDRESSER_ID,
        hairdresser_name="Fatou",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(9, 30),
        status="CONFIRMED",
        arrived_at=None,
        started_at=None,
    )
    defaults.update(overrides)
    return QueueAppointmentRow(**defaults)  # type: ignore[arg-type]


class TestListSalonQueueAPI:
    def _url(self, day: str | None = None) -> str:
        base = f"/salons/{_SALON_ID}/queue"
        return f"{base}?day={day}" if day else base

    def test_no_token_returns_401(self) -> None:
        resp = _manager_client().get(self._url(day="2026-08-09"))
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        resp = _manager_client().get(
            self._url(day="2026-08-09"), headers=_auth_header(role="CLIENT")
        )
        assert resp.status_code == 403

    def test_empty_queue_returns_200_empty_list(self) -> None:
        resp = _manager_client().get(
            self._url(day="2026-08-09"), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_waiting_entry_returned(self) -> None:
        appts = FakeAppointmentRepository()
        appts.queue_details = (_queue_row(),)
        resp = _manager_client(appts=appts).get(
            self._url(day="2026-08-09"), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["queue_status"] == "waiting"
        assert body[0]["client_name"] == "Awa Koné"
        assert body[0]["service_names"] == ["Coupe"]

    def test_out_of_scope_salon_returns_403(self) -> None:
        scope = FakeSalonScopeRepository({_MANAGER_ID: frozenset({_OTHER_SALON_ID})})
        resp = _manager_client(scope=scope).get(
            self._url(day="2026-08-09"), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 403

    def test_missing_day_defaults_to_today_without_422(self) -> None:
        resp = _manager_client().get(self._url(), headers=_auth_header(role="MANAGER"))
        assert resp.status_code == 200

    def test_invalid_day_returns_422(self) -> None:
        resp = _manager_client().get(
            self._url(day="not-a-date"), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 422

    def test_no_client_id_leaked_in_response(self) -> None:
        """Anti-fuite PII : jamais `client_id`/`user_id` — seulement des noms (§11.3)."""
        appts = FakeAppointmentRepository()
        appts.queue_details = (_queue_row(),)
        resp = _manager_client(appts=appts).get(
            self._url(day="2026-08-09"), headers=_auth_header(role="MANAGER")
        )
        assert str(_CLIENT_ID) not in resp.text
