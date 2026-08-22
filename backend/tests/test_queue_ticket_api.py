"""Tests API — router walk-in `/salons/{id}/queue/tickets[...]` (US-8.3, #157).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_queue_ticket_repository` → `FakeQueueTicketRepository` ;
- `get_catalog_repository`      → `FakeSalonCatalogRepository` ;
- `get_audit_log`               → `FakeAuditLog` ;
- `get_salon_scope_repository`  → `FakeSalonScopeRepository` (portée coiffeuse) ;
- `get_user_repository`         → `FakeAuthUserRepository` (multi-rôles) ;
- `get_access_policy`           → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- `GET /salons/{id}/queue/tickets` :
  - `200` gérant/coiffeuse — tickets actifs du jour, triés `ticket_number` ;
  - `401` sans jeton ;
  - `403` `CLIENT` (pas de `QUEUE_TICKET_READ_SALON`) ;
  - `403` salon hors périmètre (générique) ;
  - liste **vide** légitime si aucun ticket actif ; défaut « aujourd'hui » sans `day`.
- `POST /salons/{id}/queue/tickets` :
  - `201` jeton `TERMINAL` — corps minimal, `ticket_number` présent ;
  - `401` sans jeton ;
  - `403` jeton `CLIENT` / `MANAGER` / `HAIRDRESSER` (permission `QUEUE_TICKET_CREATE`
    détenue par `TERMINAL` uniquement) ;
  - `403` device d'un autre salon (portée cross-salon) ;
  - `404` `customer_profile_id` hors salon (indiscernable, §11.2) ;
  - `422` `service_ids` vide (validation Pydantic, `min_length=1`) ;
  - `422` prestation inactive/hors salon (levée applicative).
- `POST .../start` :
  - `200` succès — corps contient `status=in_progress`, `hairdresser_id` ;
  - `401` sans jeton ;
  - `403` `CLIENT` (pas de `QUEUE_TICKET_UPDATE_STATUS`) ;
  - `404` ticket hors salon/inexistant ;
  - `404` coiffeuse hors salon (`HairdresserNotInSalon`) ;
  - `409` ticket déjà `in_progress` (transition invalide) ;
  - `409` ticket `done` (transition invalide) ;
  - `409` coiffeuse déjà `in_progress` sur un autre ticket (`HairdresserAlreadyBusy`, #173).
- `POST .../complete` :
  - `200` succès — corps contient `status=done`, `completed_at` présent ;
  - `401` sans jeton ;
  - `403` `CLIENT` ;
  - `404` ticket hors salon/inexistant ;
  - `409` ticket encore `waiting` (pas encore démarré) ;
  - `409` ticket déjà `done`.
- `POST .../cancel` :
  - `200` `MANAGER`/`HAIRDRESSER` — corps contient `status=expired` et le motif soumis ;
  - `401` sans jeton ; `403` `CLIENT` ;
  - `404` ticket hors salon/inexistant (isolation) ;
  - `409` ticket déjà `in_progress` (règle métier centrale) ; `409` ticket `done` ;
  - `422` `reason` absent, vide, ou blanc (min_length Pydantic **et** garde domaine).
- `PUT .../services` (#161) :
  - `200` succès sur `waiting` **et** `in_progress` — corps contient les nouveaux
    `service_ids` ;
  - `401` sans jeton ; `403` `CLIENT` ;
  - `404` ticket hors salon/inexistant ;
  - `409` ticket `done`/`expired` (plus éditable) ;
  - `422` `service_ids` vide, inactive ou hors salon.
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
_CUSTOMER_PROFILE_ID = uuid.UUID("cf000000-0000-0000-0000-000000000001")
_DAY = datetime.date(2026, 8, 11)

_TERMINAL_TOKEN = make_access_token(_DEVICE_ID, Role.TERMINAL.value)
_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

_LIST_URL = f"/salons/{_SALON_ID}/queue/tickets"
_JOIN_URL = f"/salons/{_SALON_ID}/queue/tickets"
_START_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/start"
_COMPLETE_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/complete"
_CANCEL_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/cancel"
_SERVICES_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/services"
_CUSTOMER_URL = f"/salons/{_SALON_ID}/queue/tickets/{_TICKET_ID}/customer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_repo() -> FakeAuthUserRepository:
    """Credentials pour tous les rôles testés."""

    creds = {
        str(_DEVICE_ID): UserCredentials(
            id=_DEVICE_ID,
            role=Role.TERMINAL.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        ),
        str(_MANAGER_ID): UserCredentials(
            id=_MANAGER_ID,
            role=Role.MANAGER.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
        ),
        str(_CLIENT_ID): UserCredentials(
            id=_CLIENT_ID, role=Role.CLIENT.value, status=UserStatus.ACTIVE.value, password_hash="x"
        ),
        str(_HAIRDRESSER_ID): UserCredentials(
            id=_HAIRDRESSER_ID,
            role=Role.HAIRDRESSER.value,
            status=UserStatus.ACTIVE.value,
            password_hash="x",
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
    customer_profile_id: uuid.UUID | None = None,
) -> QueueTicket:
    return QueueTicket(
        id=id_,
        salon_id=_SALON_ID,
        ticket_number=1,
        issued_date=_DAY,
        customer_profile_id=customer_profile_id,
        service_ids=(_SERVICE_ID,),
        status=status,
        hairdresser_id=hairdresser_id,
        estimated_wait_minutes=10,
        created_at=_CREATED_AT,
        called_at=None,
        started_at=_CREATED_AT if status in ("in_progress", "done") else None,
        completed_at=_CREATED_AT if status == "done" else None,
        cancellation_reason="Cliente absente" if status == "expired" else None,
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
    # Portée globale (gérant / borne) — inclut device TERMINAL + manager sur _SALON_ID.
    global_scope = scope or FakeSalonScopeRepository(
        {
            _DEVICE_ID: frozenset({_SALON_ID}),
            _MANAGER_ID: frozenset({_SALON_ID}),
            _HAIRDRESSER_ID: frozenset({_SALON_ID}),
        }
    )
    # Portée coiffeuse pour `StartQueueTicket._require_salon_hairdresser`.
    hd_scope = hairdresser_scope or FakeSalonScopeRepository(
        {
            _HAIRDRESSER_ID: frozenset({_SALON_ID}),
        }
    )

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
# GET /salons/{id}/queue/tickets  (lister la file, #148)
# ---------------------------------------------------------------------------


class TestListSalonQueueTicketsAPI:
    def _url(self, day: str | None = None) -> str:
        return f"{_LIST_URL}?day={day}" if day else _LIST_URL

    def test_no_token_returns_401(self) -> None:
        resp = _build_client().get(self._url(day=_DAY.isoformat()))
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        resp = _build_client().get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_manager_returns_200_empty_list(self) -> None:
        resp = _build_client().get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"day": _DAY.isoformat(), "items": []}

    def test_hairdresser_role_returns_200(self) -> None:
        """La coiffeuse lit aussi la file (future page « Mes tickets », #148)."""
        resp = _build_client().get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_active_ticket_returned(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(status="in_progress", hairdresser_id=_HAIRDRESSER_ID),
            customer_first_name="Awa",
            service_names=("Tresses",),
            hairdresser_name="Fatou",
        )
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["ticket_number"] == 1
        assert item["customer_first_name"] == "Awa"
        assert item["service_names"] == ["Tresses"]
        assert item["status"] == "in_progress"

    def test_payment_id_present_when_ticket_paid(self) -> None:
        """`payment_id` remonte le paiement `VALIDATED`/`ADJUSTED` rattaché au ticket."""
        payment_id = uuid.uuid4()
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="done"))
        tickets.set_display(_TICKET_ID, payment_id=payment_id)
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"][0]["payment_id"] == str(payment_id)

    def test_payment_id_null_when_ticket_unpaid(self) -> None:
        """État par défaut : ticket non encaissé → `payment_id` `null`."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="done"))
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"][0]["payment_id"] is None

    def test_expired_ticket_stays_visible_with_reason(self) -> None:
        """Élargissement délibéré (annulation manuelle) : un ticket `expired`
        reste dans la file du jour, motif inclus — jamais retiré de la liste."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="expired"))
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["status"] == "expired"
        assert body["items"][0]["cancellation_reason"] == "Cliente absente"

    def test_out_of_scope_salon_returns_403(self) -> None:
        scope = FakeSalonScopeRepository({_MANAGER_ID: frozenset({_OTHER_SALON_ID})})
        resp = _build_client(scope=scope).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_missing_day_defaults_to_today_without_422(self) -> None:
        resp = _build_client().get(_LIST_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"})
        assert resp.status_code == 200

    def test_invalid_day_returns_422(self) -> None:
        resp = _build_client().get(
            self._url(day="not-a-date"),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_customer_profile_id_exposed_as_opaque_id_for_ticket_detail(self) -> None:
        """`customer_profile_id` est bien renvoyé (opaque) — active le détail du ticket."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(status="waiting", customer_profile_id=_CUSTOMER_PROFILE_ID),
            customer_first_name="Awa",
        )
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.json()["items"][0]["customer_profile_id"] == str(_CUSTOMER_PROFILE_ID)

    def test_customer_profile_id_null_for_anonymous_ticket(self) -> None:
        """Un ticket sans fiche rattachée renvoie `customer_profile_id: null` (état légitime)."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting", customer_profile_id=None))
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.json()["items"][0]["customer_profile_id"] is None

    def test_no_full_name_or_phone_leaked_in_response(self) -> None:
        """Anti-fuite PII : jamais le nom complet ni le téléphone — seulement le prénom (§11.3)."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(status="waiting", customer_profile_id=_CUSTOMER_PROFILE_ID),
            customer_first_name="Awa",
        )
        resp = _build_client(tickets=tickets).get(
            self._url(day=_DAY.isoformat()),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "full_name" not in resp.text
        assert "phone" not in resp.text


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

    def test_terminal_wrong_salon_returns_403(self) -> None:
        # Device du salon_id figé sur _SALON_ID mais tente d'accéder à _OTHER_SALON_ID.
        other_url = f"/salons/{_OTHER_SALON_ID}/queue/tickets"
        resp = _build_client().post(
            other_url, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_terminal_valid_returns_201(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert resp.status_code == 201

    def test_response_contains_ticket_number(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert resp.status_code == 201
        assert "ticket_number" in resp.json()

    def test_response_contains_estimated_wait_minutes(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert "estimated_wait_minutes" in resp.json()

    def test_response_contains_people_ahead_count_as_integer(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        body = resp.json()
        assert "people_ahead_count" in body
        assert isinstance(body["people_ahead_count"], int)

    def test_response_contains_status_waiting(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert resp.json()["status"] == "waiting"

    def test_response_contains_created_at(self) -> None:
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert "created_at" in resp.json()

    def test_empty_service_ids_returns_422(self) -> None:
        # Validation Pydantic (min_length=1).
        resp = _build_client().post(
            _JOIN_URL,
            json={"service_ids": []},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_inactive_service_returns_422(self) -> None:
        # Prestation inactive dans le catalogue → `InvalidQueueTicketServices` → 422.
        cat = _catalog(services=[_service_obj(is_active=False)])
        resp = _build_client(catalog=cat).post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert resp.status_code == 422

    def test_unknown_service_returns_422(self) -> None:
        unknown_id = uuid.uuid4()
        resp = _build_client().post(
            _JOIN_URL,
            json={"service_ids": [str(unknown_id)]},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_customer_profile_from_other_salon_returns_404(self) -> None:
        # `customer_profile_id` inexistant pour ce salon → 404 indiscernable (§11.2).
        other_profile_id = uuid.uuid4()
        body = {"service_ids": [str(_SERVICE_ID)], "customer_profile_id": str(other_profile_id)}
        resp = _build_client().post(
            _JOIN_URL, json=body, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_duplicate_service_ids_returns_422(self) -> None:
        """Régression : un doublon violerait la PK composite `queue_ticket_services`
        (`IntegrityError` non interceptée, `500`) si le domaine ne le rejetait pas
        avant l'écriture — cf. `validate_service_ids`."""
        resp = _build_client().post(
            _JOIN_URL,
            json={"service_ids": [str(_SERVICE_ID), str(_SERVICE_ID)]},
            headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_sequential_ticket_numbers_on_successive_calls(self) -> None:
        client = _build_client()
        r1 = client.post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        r2 = client.post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r2.json()["ticket_number"] == r1.json()["ticket_number"] + 1

    def test_people_ahead_count_increments_across_successive_calls(self) -> None:
        # Même token/salon, deux tickets créés à la suite : le premier n'a personne
        # devant lui (0), le second trouve le premier toujours `waiting` (1).
        client = _build_client()
        r1 = client.post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        r2 = client.post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["people_ahead_count"] == 0
        assert r2.json()["people_ahead_count"] == 1

    def test_anonymous_ticket_customer_profile_id_absent_from_response(self) -> None:
        # La réponse `QueueTicketResponse` n'expose pas `customer_profile_id`.
        resp = _build_client().post(
            _JOIN_URL, json=self._BODY, headers={"Authorization": f"Bearer {_TERMINAL_TOKEN}"}
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

    def test_hairdresser_already_busy_returns_409(self) -> None:
        """#173 : la coiffeuse a déjà un ticket `in_progress` (un autre ticket)."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(id_=uuid.uuid4(), status="in_progress", hairdresser_id=_HAIRDRESSER_ID)
        )
        tickets.seed(_make_ticket(status="waiting"))
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
# POST .../cancel  (annulation manuelle, no-show, motif obligatoire)
# ---------------------------------------------------------------------------


class TestCancelQueueTicketAPI:
    _BODY = {"reason": "Cliente absente"}

    def test_no_token_returns_401(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(_CANCEL_URL, json=self._BODY)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_manager_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_hairdresser_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_response_status_is_expired(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.json()["status"] == "expired"

    def test_response_contains_submitted_reason(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.json()["cancellation_reason"] == "Cliente absente"

    def test_success_from_called_ticket(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="called"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

    def test_unknown_ticket_returns_404(self) -> None:
        resp = _build_client().post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 404

    def test_ticket_from_other_salon_returns_404(self) -> None:
        """Isolation §11.2 : un ticket d'un autre salon est indiscernable d'un inexistant."""
        tickets = FakeQueueTicketRepository()
        import dataclasses as _dc

        t = _dc.replace(_make_ticket(status="waiting"), salon_id=_OTHER_SALON_ID)
        tickets._tickets[t.id] = t
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 404

    def test_in_progress_ticket_returns_409(self) -> None:
        """Cœur de la règle métier : un ticket déjà pris en charge n'est plus annulable."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 409

    def test_done_ticket_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="done"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 409

    def test_missing_reason_field_returns_422(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json={},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_empty_reason_returns_422(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json={"reason": ""},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_whitespace_only_reason_returns_422(self) -> None:
        """`min_length=1` de Pydantic compte les espaces comme une longueur valide —
        c'est la revalidation domaine (`validate_cancellation_reason`) qui rejette
        un motif blanc après `strip()` (défense en profondeur)."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).post(
            _CANCEL_URL,
            json={"reason": "   "},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT .../services  (édition des prestations, #161)
# ---------------------------------------------------------------------------


class TestUpdateQueueTicketServicesAPI:
    _BODY = {"service_ids": [str(_SERVICE_ID)]}

    def test_no_token_returns_401(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(_SERVICES_URL, json=self._BODY)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_manager_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 200

    def test_hairdresser_returns_200(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL,
            json=self._BODY,
            headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_response_contains_updated_service_ids(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.json()["service_ids"] == [str(_SERVICE_ID)]

    def test_success_on_in_progress_ticket(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 200

    def test_unknown_ticket_returns_404(self) -> None:
        resp = _build_client().put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_ticket_from_other_salon_returns_404(self) -> None:
        tickets = FakeQueueTicketRepository()
        import dataclasses as _dc

        t = _dc.replace(_make_ticket(status="waiting"), salon_id=_OTHER_SALON_ID)
        tickets._tickets[t.id] = t
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_done_ticket_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="done"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 409

    def test_expired_ticket_returns_409(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="expired"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL, json=self._BODY, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 409

    def test_empty_service_ids_returns_422(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL,
            json={"service_ids": []},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_inactive_service_returns_422(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        inactive = _service_obj(id_=uuid.uuid4(), is_active=False)
        catalog = _catalog(services=[_service_obj(), inactive])
        resp = _build_client(tickets=tickets, catalog=catalog).put(
            _SERVICES_URL,
            json={"service_ids": [str(inactive.id)]},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_service_from_other_salon_returns_422(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        other_service_id = uuid.uuid4()
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL,
            json={"service_ids": [str(other_service_id)]},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_duplicate_service_ids_returns_422(self) -> None:
        """Régression : un doublon violerait la PK composite `queue_ticket_services`
        (`IntegrityError` non interceptée, `500`) si le domaine ne le rejetait pas
        avant l'écriture — cf. `validate_service_ids`."""
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="waiting"))
        resp = _build_client(tickets=tickets).put(
            _SERVICES_URL,
            json={"service_ids": [str(_SERVICE_ID), str(_SERVICE_ID)]},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET .../customer  (nom complet, zone coiffeur « Mes tickets »)
# ---------------------------------------------------------------------------


def _seed_customer(customers: FakeCustomerRepository, *, salon_id=_SALON_ID, full_name="Awa Koné"):  # type: ignore[no-untyped-def]
    return customers.create(
        type(
            "C",
            (),
            {
                "salon_id": salon_id,
                "full_name": full_name,
                "phone": None,
                "gender": None,
                "notes": None,
            },
        )()
    )


class TestGetAssignedTicketCustomerAPI:
    def test_no_token_returns_401(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress", hairdresser_id=_HAIRDRESSER_ID))
        resp = _build_client(tickets=tickets).get(_CUSTOMER_URL)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(_make_ticket(status="in_progress", hairdresser_id=_HAIRDRESSER_ID))
        resp = _build_client(tickets=tickets).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"}
        )
        assert resp.status_code == 403

    def test_assigned_hairdresser_returns_200_with_full_name(self) -> None:
        customers = FakeCustomerRepository()
        customer = _seed_customer(customers, full_name="Awa Koné")
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(
                status="in_progress",
                hairdresser_id=_HAIRDRESSER_ID,
                customer_profile_id=customer.id,
            )
        )
        resp = _build_client(tickets=tickets, customers=customers).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Awa Koné"

    def test_manager_returns_404(self) -> None:
        """Le gérant n'est jamais `hairdresser_id` d'un ticket : voie d'accès distincte
        (`GET /customers/{id}`, `CUSTOMER_MANAGE`), pas celle-ci."""
        customers = FakeCustomerRepository()
        customer = _seed_customer(customers)
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(
                status="in_progress",
                hairdresser_id=_HAIRDRESSER_ID,
                customer_profile_id=customer.id,
            )
        )
        resp = _build_client(tickets=tickets, customers=customers).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_unknown_ticket_returns_404(self) -> None:
        resp = _build_client().get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_ticket_from_other_salon_returns_404(self) -> None:
        customers = FakeCustomerRepository()
        customer = _seed_customer(customers, salon_id=_OTHER_SALON_ID)
        tickets = FakeQueueTicketRepository()
        import dataclasses as _dc

        t = _dc.replace(
            _make_ticket(
                status="in_progress",
                hairdresser_id=_HAIRDRESSER_ID,
                customer_profile_id=customer.id,
            ),
            salon_id=_OTHER_SALON_ID,
        )
        tickets._tickets[t.id] = t
        resp = _build_client(tickets=tickets, customers=customers).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_other_hairdresser_ticket_returns_404(self) -> None:
        other_hairdresser_id = uuid.uuid4()
        customers = FakeCustomerRepository()
        customer = _seed_customer(customers)
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(
                status="in_progress",
                hairdresser_id=other_hairdresser_id,
                customer_profile_id=customer.id,
            )
        )
        resp = _build_client(tickets=tickets, customers=customers).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_waiting_ticket_returns_404(self) -> None:
        """Pas encore pris en charge → la file reste au prénom seul (#156/§11.3)."""
        customers = FakeCustomerRepository()
        customer = _seed_customer(customers)
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(
                status="waiting",
                hairdresser_id=_HAIRDRESSER_ID,
                customer_profile_id=customer.id,
            )
        )
        resp = _build_client(tickets=tickets, customers=customers).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_anonymous_ticket_returns_404(self) -> None:
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(
                status="in_progress", hairdresser_id=_HAIRDRESSER_ID, customer_profile_id=None
            )
        )
        resp = _build_client(tickets=tickets).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 404

    def test_response_never_leaks_phone_or_notes(self) -> None:
        customers = FakeCustomerRepository()
        customer = customers.create(
            type(
                "C",
                (),
                {
                    "salon_id": _SALON_ID,
                    "full_name": "Awa Koné",
                    "phone": "+2250700000000",
                    "gender": None,
                    "notes": "Allergique au henné",
                },
            )()
        )
        tickets = FakeQueueTicketRepository()
        tickets.seed(
            _make_ticket(
                status="in_progress",
                hairdresser_id=_HAIRDRESSER_ID,
                customer_profile_id=customer.id,
            )
        )
        resp = _build_client(tickets=tickets, customers=customers).get(
            _CUSTOMER_URL, headers={"Authorization": f"Bearer {_HAIRDRESSER_TOKEN}"}
        )
        assert resp.status_code == 200
        assert set(resp.json().keys()) == {"full_name"}
        assert "+2250700000000" not in resp.text
        assert "henné" not in resp.text


# ---------------------------------------------------------------------------
# Invariant de sécurité : aucune route walk-in dans PUBLIC_ROUTE_PATHS
# ---------------------------------------------------------------------------


class TestQueueTicketRoutesSecurity:
    def test_join_queue_not_in_public_route_paths(self) -> None:
        """POST /salons/{id}/queue/tickets ne doit pas être public (deny-by-default)."""

        assert not any("queue/tickets" in path for path in PUBLIC_ROUTE_PATHS), (
            "Une route walk-in est listée dans PUBLIC_ROUTE_PATHS — deny-by-default violé"
        )

    def test_start_not_in_public_route_paths(self) -> None:
        assert not any("queue/tickets" in path for path in PUBLIC_ROUTE_PATHS)
