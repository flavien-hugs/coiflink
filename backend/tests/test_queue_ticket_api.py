"""Tests API — router walk-in `/salons/{id}/queue/tickets[...]` (US-8.3, #157).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_queue_ticket_repository` → `FakeQueueTicketRepository` ;
- `get_catalog_repository`      → `FakeSalonCatalogRepository` ;
- `get_audit_log`               → `FakeAuditLog` ;
- `get_salon_scope_repository`  → `FakeSalonScopeRepository` (portée coiffeuse) ;
- `get_user_repository`         → `FakeAuthUserRepository` (multi-rôles) ;
- `get_access_policy`           → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- `POST /salons/{id}/queue/tickets` :
  - `201` jeton `KIOSK` — corps minimal, `ticket_number` présent ;
  - `401` sans jeton ;
  - `403` jeton `CLIENT` / `MANAGER` / `HAIRDRESSER` (permission `QUEUE_TICKET_CREATE`
    détenue par `KIOSK` uniquement) ;
  - `403` device d'un autre salon (portée cross-salon) ;
  - `404` `customer_profile_id` hors salon (indiscernable, §11.2) ;
  - `422` `service_ids` vide (validation Pydantic, `min_length=1`) ;
  - `422` prestation inactive/hors salon (levée applicative).
- `POST .../start` :
  - `200` succès — corps contient `status=in_progress`, `hairdresser_id` ;
  - `401` sans jeton ;
  - `403` `CLIENT` (pas de `APPOINTMENT_UPDATE_STATUS`) ;
  - `404` ticket hors salon/inexistant ;
  - `404` coiffeuse hors salon (`HairdresserNotInSalon`) ;
  - `409` ticket déjà `in_progress` (transition invalide) ;
  - `409` ticket `done` (transition invalide).
- `POST .../complete` :
  - `200` succès — corps contient `status=done`, `completed_at` présent ;
  - `401` sans jeton ;
  - `403` `CLIENT` ;
  - `404` ticket hors salon/inexistant ;
  - `409` ticket encore `waiting` (pas encore démarré) ;
  - `409` ticket déjà `done`.
- Invariant de sécurité : aucune route walk-in dans `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.customers import get_customer_repository
from coiflink_api.adapters.inbound.queue_tickets import (
    get_audit_log,
    get_catalog_repository,
    get_queue_ticket_repository,
)
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.inbound.security import get_salon_scope_repository
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.queue_ticket import QueueTicket
from coiflink_api.main import app

from .conftest import (
    TEST_JWT_SECRET,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeCustomerRepository,
    FakeQueueTicketRepository,
    FakeSalonCatalogRepository,
    FakeSalonScopeRepository,
    _CREATED_AT,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_DEVICE_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_SALON_ID = uuid.UUID("aa000000-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bb000000-0000-0000-0000-000000000002")

_MANAGER_ID = uuid.UUID("ee000000-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("ee000000-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("ee000000-0000-0000-0000-000000000003")
_ADMIN_ID = uuid.UUID("ee000000-0000-0000-0000-000000000004")

_SERVICE_ID = uuid.UUID("5e000000-0000-0000-0000-000000000001")
_TICKET_ID = uuid.UUID("7c000000-0000-0000-0000-000000000001")
_DAY = datetime.date(2026, 8, 11)

_KIOSK_TOKEN = make_access_token(_DEVICE_ID, Role.KIOSK.value)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

_JOIN_URL = f"/salons/{_SALON_ID}/queue/tickets"
_START_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/start"
_COMPLETE_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/complete"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_repo() -> FakeAuthUserRepository:
    """Credentials pour tous les rôles testés."""

    creds = {
        str(_DEVICE_ID): UserCredentials(
            id=_DEVICE_ID, role=Role.KIOSK.value, status=UserStatus.ACTIVE.value, password_hash="x"
        ),
        str(_MANAGER_ID): UserCredentials(
            id=_MANAGER_ID, role=Role.MANAGER.value, status=UserStatus.ACTIVE.value, password_hash="x"
        ),
        str(_CLIENT_ID): UserCredentials(
            id=_CLIENT_ID, role=Role.CLIENT.value, status=UserStatus.ACTIVE.value, password_hash="x"
        ),
        str(_HAIRDRESSER_ID): UserCredentials(
            id=_HAIRDRESSER_ID, role=Role.HAIRDRESSER.value, status=UserStatus.ACTIVE.value, password_hash="x"
        ),
    }
    return FakeAuthUserRepository(credentials_by_id=creds)


def _service_obj(
    *,
    id_: uuid.UUID = _SERVICE_ID,
    salon_id: uuid.UUID = _SALON_ID,
    duration_minutes: int = 30,
    is_active: bool = True,
):  # type: ignore[no-untyped-def]
    """Objet service duck-typed (les fakes n'utilisent pas le vrai domaine Service)."""

    class _Svc:
        def __init__(self):  # type: ignore[no-untyped-def]
            self.id = id_
            self.salon_id = salon_id
            self.duration_minutes = duration_minutes
            self.is_active = is_active
            self.name = "Prestation Test"
            self.price = 5000

    return _Svc()


class _Hairdresser:
    """Coiffeuse duck-typed minimale pour les fakes de catalogue."""

    def __init__(self, id_: uuid.UUID = _HAIRDRESSER_ID) -> None:
        self.id = id_
        self.status = "ACTIVE"
        self.full_name = "Coiffeuse Test"


def _catalog(
    services: list | None = None, hairdressers: list | None = None
) -> FakeSalonCatalogRepository:
    svc_list = services if services is not None else [_service_obj()]
    hd_list = hairdressers if hairdressers is not None else [_Hairdresser()]
    return FakeSalonCatalogRepository(
        services={_SALON_ID: svc_list},
        hairdressers={_SALON_ID: hd_list},
    )


def _make_ticket(
    *,
    id_: uuid.UUID = _TICKET_ID,
    status: str = "waiting",
    hairdresser_id: uuid.UUID | None = None,
) -> QueueTicket:
    return QueueTicket(
        id=id_,
        salon_id=_SALON_ID,
        ticket_number=1,
        issued_date=_DAY,
        customer_profile_id=None,
        service_ids=(_SERVICE_ID,),
        status=status,
        hairdresser_id=hairdresser_id,
        estimated_wait_minutes=10,
        created_at=_CREATED_AT,
        called_at=None,
        started_at=_CREATED_AT if status in ("in_progress", "done") else None,
        completed_at=_CREATED_AT if status == "done" else None,
    )


def _build_client(
    tickets: FakeQueueTicketRepository | None = None,
    catalog: FakeSalonCatalogRepository | None = None,
    scope: FakeSalonScopeRepository | None = None,
    hairdresser_scope: FakeSalonScopeRepository | None = None,
    customers: FakeCustomerRepository | None = None,
) -> TestClient:
    tix = tickets if tickets is not None else FakeQueueTicketRepository()
    cat = catalog if catalog is not None else _catalog()
    cus = customers if customers is not None else FakeCustomerRepository()
    # Portée globale (gérant / borne) — inclut device KIOSK + manager sur _SALON_ID.
    global_scope = scope or FakeSalonScopeRepository({
        _DEVICE_ID: frozenset({_SALON_ID}),
        _MANAGER_ID: frozenset({_SALON_ID}),
        _HAIRDRESSER_ID: frozenset({_SALON_ID}),
    })
    # Portée coiffeuse pour `StartQueueTicket._require_salon_hairdresser`.
    hd_scope = hairdresser_scope or FakeSalonScopeRepository({
        _HAIRDRESSER_ID: frozenset({_SALON_ID}),
    })

    app.dependency_overrides[get_queue_ticket_repository] = lambda: tix
    app.dependency_overrides[get_catalog_repository] = lambda: cat
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    app.dependency_overrides[get_user_repository] = lambda: _user_repo()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(global_scope)
    # `get_salon_scope_repository` est consommé par `StartQueueTicket` (portée coiffeuse).
    app.dependency_overrides[get_salon_scope_repository] = lambda: hd_scope
    # `get_customer_repository` est consommé par `get_join_queue` (fiche client optionnelle).
    app.dependency_overrides[get_customer_repository] = lambda: cus
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_test_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture(autouse=True)
def _clear_overrides() -> Generator[None, None, None]:
    yield
    for dep in (
        get_queue_ticket_repository,
        get_catalog_repository,
        get_audit_log,
        get_user_repository,
        get_access_policy,
        get_salon_scope_repository,
        get_customer_repository,
    ):
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# POST /salons/{id}/queue/tickets  (rejoindre la file)
# ---------------------------------------------------------------------------


class TestJoinQueueAPI:
    _BODY = {"service_ids": [str(_SERVICE_ID)]}

    def test_no_token_returns_401(self) -> None:
        resp = _build_client().post(_JOIN_URL, json=self._BODY)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_manager_role_returns_403(self) -> None:
        # MANAGER ne possède pas QUEUE_TICKET_CREATE.
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        resp = _build_client().post(
            _JOIN_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_kiosk_wrong_salon_returns_403(self) -> None:
        # Device du salon_id figé sur _SALON_ID mais tente d'accéder à _OTHER_SALON_ID.
        other_url = f"/salons/{_OTHER_SALON_ID}/queue/tickets"
        resp = _build_client().post(
            other_url, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_kiosk_valid_returns_201(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert resp.status_code == 201

    def test_response_contains_ticket_number(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert resp.status_code == 201
        assert "ticket_number" in resp.json()

    def test_response_contains_estimated_wait_minutes(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert "estimated_wait_minutes" in resp.json()

    def test_response_contains_status_waiting(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert resp.json()["status"] == "waiting"

    def test_response_contains_created_at(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert "created_at" in resp.json()

    def test_empty_service_ids_returns_422(self) -> None:
        # Validation Pydantic (min_length=1).
        resp = _build_client().post(
            _JOIN_URL,
            json={"service_ids": []},
            headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_inactive_service_returns_422(self) -> None:
        # Prestation inactive dans le catalogue → `InvalidQueueTicketServices` → 422.
        cat = _catalog(services=[_service_obj(is_active=False)])
        resp = _build_client(catalog=cat).post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert resp.status_code == 422

    def test_unknown_service_returns_422(self) -> None:
        unknown_id = uuid.uuid4()
        resp = _build_client().post(
            _JOIN_URL,
            json={"service_ids": [str(unknown_id)]},
            headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_customer_profile_from_other_salon_returns_404(self) -> None:
        # `customer_profile_id` inexistant pour ce salon → 404 indiscernable (§11.2).
        other_profile_id = uuid.uuid4()
        body = {"service_ids": [str(_SERVICE_ID)], "customer_profile_id": str(other_profile_id)}
        resp = _build_client().post(
            _JOIN_URL, json=body, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_sequential_ticket_numbers_on_successive_calls(self) -> None:
        client = _build_client()
        r1 = client.post(_JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"})
        r2 = client.post(_JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"})
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r2.json()["ticket_number"] == r1.json()["ticket_number"] + 1

    def test_anonymous_ticket_customer_profile_id_absent_from_response(self) -> None:
        # La réponse `QueueTicketResponse` n'expose pas `customer_profile_id`.
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_KIOSK_TOKEN}"}
        )
        assert "customer_profile_id" not in resp.json()


# ---------------------------------------------------------------------------
# POST .../start  (prise en charge)
# ---------------------------------------------------------------------------


class TestStartQueueTicketAPI:
    _BODY = {"hairdresser_id": str(_HAIRDRESSER_ID)}

    def test_no_token_returns_401(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(_START_URL, json=self._BODY)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_manager_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 200

    def test_hairdresser_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _START_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_response_status_is_in_progress(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.json()["status"] == "in_progress"

    def test_response_contains_hairdresser_id(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.json()["hairdresser_id"] == str(_HAIRDRESSER_ID)

    def test_unknown_ticket_returns_404(self) -> None:
        resp = _build_client().post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_ticket_from_other_salon_returns_404(self) -> None:
        tickets = FakeQueueTicketRepository()
        # Même id que _TICKET_ID mais appartient au salon B.
        import dataclasses as _dc
        t = _dc.replace(_make_ticket(status="waiting"), salon_id=_OTHER_SALON_ID)
        tickets._tickets[t.id] = t
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_hairdresser_not_in_salon_returns_404(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        # Portée coiffeuse : uniquement sur salon B → refus.
        hd_scope = FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({_OTHER_SALON_ID})})
        resp = _build_client(tickets=tickets, hairdresser_scope=hd_scope).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_already_in_progress_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 409

    def test_done_ticket_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="done"))
        resp = _build_client(tickets=tickets).post(
            _START_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST .../complete  (clôture)
# ---------------------------------------------------------------------------


class TestCompleteQueueTicketAPI:
    def test_no_token_returns_401(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(_COMPLETE_URL)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_manager_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 200

    def test_response_status_is_done(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.json()["status"] == "done"

    def test_response_contains_completed_at(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.json()["completed_at"] is not None

    def test_unknown_ticket_returns_404(self) -> None:
        resp = _build_client().post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_waiting_ticket_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 409

    def test_done_ticket_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="done"))
        resp = _build_client(tickets=tickets).post(
            _COMPLETE_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Invariant de sécurité : aucune route walk-in dans PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestQueueTicketRoutesSecurity:
    def test_join_queue_not_in_public_route_paths(self) -> None:
        """POST /salons/{id}/queue/tickets ne doit pas être public (deny-by-default)."""

        assert not any(
            "queue/tickets" in path for path in PUBLIC_ROUTE_PATHS
        ), "Une route walk-in est listée dans PUBLIC_ROUTE_PATHS — deny-by-default violé"

    def test_start_not_in_public_route_paths(self) -> None:
        assert not any(
            "queue/tickets" in path for path in PUBLIC_ROUTE_PATHS
        )
