"""Tests API — router disponibilité & réservation (US-3.7, #21).

Utilise FastAPI `TestClient` avec override de dépendances (aucune base ni réseau) :
- `get_appointment_repository` → `FakeAppointmentRepository`
- `get_catalog_repository` → `FakeSalonCatalogRepository`
- `get_user_repository` → `FakeAuthUserRepository` (multi-rôles)
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository())`
- `app.state.token_service` → `JwtTokenService(TEST_JWT_SECRET)` (autouse)

Couvre :
- `GET /catalog/salons/{salon_id}/availability` : route **publique** (sans jeton) ;
  200 avec créneaux ; 404 salon inconnu ; 409 salon non réservable ; 422 paramètres
  invalides ; la réponse ne divulgue aucune PII (§11.3) ;
- `POST /salons/{salon_id}/appointments` : 401 sans jeton ; 403 mauvais rôle ; 201
  avec RDV valide ; 409 course concurrente (`SlotAlreadyBooked`), 409 créneau
  indisponible (`SlotUnavailable`), 409 salon non réservable (`SalonNotBookable`) ;
  404 prestation inconnue ; 422 sans prestation (corps invalide) ;
- anti-élévation : `client_id` et `salon_id` ignorés s'ils figurent dans le corps.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.appointments import (
    get_appointment_repository,
    get_audit_log,
    get_catalog_repository,
)
from coiflink_api.domain.appointment import (
    Appointment as AppointmentEntity,
    BookedService as BookedServiceEntity,
)
from coiflink_api.adapters.inbound.security import (
    get_access_policy,
    get_salon_scope_repository,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.opening_hours import to_jsonb, parse_opening_hours
from coiflink_api.domain.salon import Salon
from coiflink_api.domain.service import Service
from coiflink_api.main import app

from .conftest import (
    FakeAppointmentRepository,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeSalonCatalogRepository,
    FakeSalonScopeRepository,
    TEST_JWT_SECRET,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
# Identifiants de comptes distincts par rôle (le claim `sub` du JWT doit correspondre
# à un compte relu en base → `get_current_principal` → `principal.role`).
_MANAGER_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")
_ADMIN_ID = uuid.UUID("66666666-0000-0000-0000-000000000006")
_HAIRDRESSER_USER_ID = uuid.UUID("77777777-0000-0000-0000-000000000007")
_ROLE_USER_IDS: dict[str, uuid.UUID] = {
    "CLIENT": _CLIENT_ID,
    "MANAGER": _MANAGER_ID,
    "ADMIN": _ADMIN_ID,
    "HAIRDRESSER": _HAIRDRESSER_USER_ID,
}
_SERVICE_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")

_OPENING_HOURS_DICT = to_jsonb(
    parse_opening_hours({"weekly": {"mon": [{"start": "09:00", "end": "17:00"}]}})
)
_DATE = "2026-08-03"  # lundi
_AVAIL_URL = f"/catalog/salons/{_SALON_ID}/availability"
_BOOK_URL = f"/salons/{_SALON_ID}/appointments"
_MODIFY_APPT_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_OTHER_CLIENT_ID_API = uuid.UUID("99999999-0000-0000-0000-000000000099")


def _make_salon(
    *,
    status: str = "ACTIVE",
    opening_hours: dict | None = _OPENING_HOURS_DICT,
) -> Salon:
    return Salon(
        id=_SALON_ID,
        owner_id=uuid.uuid4(),
        name="Salon Test",
        description=None,
        phone=None,
        address="Rue des Jardins",
        city="Abidjan",
        commune="Cocody",
        latitude=decimal.Decimal("5.36"),
        longitude=decimal.Decimal("-3.99"),
        logo_object_key=None,
        status=status,
        opening_hours=opening_hours,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _make_service(
    *,
    service_id: uuid.UUID = _SERVICE_ID,
    is_active: bool = True,
    duration_minutes: int = 60,
) -> Service:
    return Service(
        id=service_id,
        salon_id=_SALON_ID,
        name="Coupe homme",
        description=None,
        price=decimal.Decimal("5000.00"),
        duration_minutes=duration_minutes,
        category="Coupe",
        is_active=is_active,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _catalog(
    *,
    salon: Salon | None = None,
    services: list[Service] | None = None,
) -> FakeSalonCatalogRepository:
    s = salon if salon is not None else _make_salon()
    svcs = services if services is not None else [_make_service()]
    return FakeSalonCatalogRepository(salons=[s], services={_SALON_ID: svcs})


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    """Installe le service JWT (TEST_JWT_SECRET) sur `app.state` pour la durée du test."""
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.pop(get_appointment_repository, None)
    app.dependency_overrides.pop(get_catalog_repository, None)
    app.dependency_overrides.pop(get_audit_log, None)
    app.dependency_overrides.pop(get_user_repository, None)
    app.dependency_overrides.pop(get_access_policy, None)
    app.dependency_overrides.pop(get_salon_scope_repository, None)


def _user_repo_for_all_roles() -> FakeAuthUserRepository:
    """Dépôt en mémoire avec un compte ACTIVE pour chaque rôle testé."""
    creds = {
        str(uid): UserCredentials(
            id=uid, role=role, status=UserStatus.ACTIVE.value, password_hash="x"
        )
        for role, uid in _ROLE_USER_IDS.items()
    }
    return FakeAuthUserRepository(credentials_by_id=creds)


def _client(
    catalog: FakeSalonCatalogRepository | None = None,
    appts: FakeAppointmentRepository | None = None,
    scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    cat = catalog if catalog is not None else _catalog()
    ap = appts if appts is not None else FakeAppointmentRepository()
    # Par défaut `_HAIRDRESSER_ID` est membre ACTIVE de `_SALON_ID` (§11.2).
    sc = (
        scope
        if scope is not None
        else FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_catalog_repository] = lambda: cat
    app.dependency_overrides[get_appointment_repository] = lambda: ap
    app.dependency_overrides[get_salon_scope_repository] = lambda: sc
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(FakeSalonScopeRepository())
    return TestClient(app)


def _auth_header(role: str = "CLIENT") -> dict[str, str]:
    """Jeton d'accès signé avec le secret de test, `sub` = identifiant du compte du rôle."""
    user_id = _ROLE_USER_IDS.get(role, uuid.uuid4())
    token = make_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /catalog/salons/{salon_id}/availability — route publique
# ---------------------------------------------------------------------------


class TestGetAvailability:
    def _url(self, *, date: str = _DATE) -> str:
        return f"{_AVAIL_URL}?date={date}&service_id={_SERVICE_ID}"

    def test_public_no_token_returns_200(self) -> None:
        resp = _client().get(self._url())
        assert resp.status_code == 200

    def test_returns_slots_list(self) -> None:
        resp = _client().get(self._url())
        data = resp.json()
        assert "slots" in data
        assert isinstance(data["slots"], list)

    def test_slots_have_date_start_end(self) -> None:
        resp = _client().get(self._url())
        slots = resp.json()["slots"]
        assert len(slots) > 0
        for slot in slots:
            assert "date" in slot
            assert "start" in slot
            assert "end" in slot

    def test_slots_contain_no_client_pii(self) -> None:
        resp = _client().get(self._url())
        slots = resp.json()["slots"]
        for slot in slots:
            assert "client_id" not in slot
            assert "hairdresser_id" not in slot

    def test_unknown_salon_returns_404(self) -> None:
        catalog = FakeSalonCatalogRepository()  # aucun salon
        resp = _client(catalog=catalog).get(self._url())
        assert resp.status_code == 404

    def test_inactive_salon_returns_404(self) -> None:
        catalog = _catalog(salon=_make_salon(status="INACTIVE"))
        resp = _client(catalog=catalog).get(self._url())
        assert resp.status_code == 404

    def test_salon_without_hours_returns_409(self) -> None:
        catalog = _catalog(salon=_make_salon(opening_hours=None))
        resp = _client(catalog=catalog).get(self._url())
        assert resp.status_code == 409

    def test_unknown_service_returns_404(self) -> None:
        unknown = uuid.uuid4()
        resp = _client().get(f"{_AVAIL_URL}?date={_DATE}&service_id={unknown}")
        assert resp.status_code == 404

    def test_invalid_date_format_returns_422(self) -> None:
        resp = _client().get(f"{_AVAIL_URL}?date=not-a-date&service_id={_SERVICE_ID}")
        assert resp.status_code == 422

    def test_missing_date_param_returns_422(self) -> None:
        resp = _client().get(f"{_AVAIL_URL}?service_id={_SERVICE_ID}")
        assert resp.status_code == 422

    def test_missing_service_id_param_returns_422(self) -> None:
        resp = _client().get(f"{_AVAIL_URL}?date={_DATE}")
        assert resp.status_code == 422

    def test_booked_slot_absent_from_response(self) -> None:
        booked_slot = SlotRange(
            date=datetime.date(2026, 8, 3),
            start=datetime.time(9, 0),
            end=datetime.time(10, 0),
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, None, datetime.date(2026, 8, 3)): [booked_slot]}
        )
        resp = _client(appts=appts).get(self._url())
        slots = resp.json()["slots"]
        booked_starts = {slot["start"] for slot in slots if slot["start"] == "09:00:00"}
        assert not booked_starts


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/appointments — réservation
# ---------------------------------------------------------------------------


def _valid_body(**extra) -> dict:  # type: ignore[no-untyped-def]
    base = {
        "date": _DATE,
        "start_time": "09:00",
        "service_ids": [str(_SERVICE_ID)],
        "hairdresser_id": str(_HAIRDRESSER_ID),
    }
    base.update(extra)
    return base


class TestBookAppointment:
    def test_hairdresser_of_another_salon_returns_404(self) -> None:
        # Isolation §11.2 : l'exclusion base ne porte pas `salon_id` — sans le
        # contrôle applicatif, un CLIENT pourrait occuper l'agenda d'un coiffeur
        # d'un autre salon. Refus générique (404), et rien n'est persisté.
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        appts = FakeAppointmentRepository()
        scope = FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({other_salon})})
        resp = _client(appts=appts, scope=scope).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 404
        assert appts.created == []

    def test_arbitrary_hairdresser_id_returns_404(self) -> None:
        # UUID sans aucune appartenance (compte inexistant, ou CLIENT passé comme
        # coiffeur) : indiscernable du cas précédent, aucun oracle d'existence.
        appts = FakeAppointmentRepository()
        resp = _client(appts=appts, scope=FakeSalonScopeRepository({})).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 404
        assert appts.created == []

    def test_no_token_returns_401(self) -> None:
        resp = _client().post(_BOOK_URL, json=_valid_body())
        assert resp.status_code == 401

    def test_manager_role_returns_403(self) -> None:
        resp = _client().post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 403

    def test_valid_booking_returns_201(self) -> None:
        resp = _client().post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 201

    def test_response_contains_appointment_fields(self) -> None:
        resp = _client().post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        data = resp.json()
        assert "id" in data
        assert "salon_id" in data
        assert "client_id" in data
        assert "start_time" in data
        assert "end_time" in data
        assert "status" in data
        assert data["status"] == "PENDING"

    def test_client_id_set_from_principal_not_body(self) -> None:
        # Un `client_id` dans le corps doit être ignoré (`extra="ignore"`)
        injected_id = str(uuid.uuid4())
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"client_id": injected_id}),
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        data = resp.json()
        # Le client_id vient du token (= _CLIENT_ID), pas du corps
        assert data["client_id"] == str(_CLIENT_ID)

    def test_status_field_in_body_ignored(self) -> None:
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"status": "CONFIRMED"}),
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "PENDING"

    def test_race_condition_returns_409(self) -> None:
        appts = FakeAppointmentRepository(raise_conflict=True)
        resp = _client(appts=appts).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 409

    def test_slot_outside_hours_returns_409(self) -> None:
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"start_time": "23:00"}),
            headers=_auth_header(),
        )
        assert resp.status_code == 409

    def test_salon_without_hours_returns_409(self) -> None:
        catalog = _catalog(salon=_make_salon(opening_hours=None))
        resp = _client(catalog=catalog).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 409

    def test_unknown_salon_returns_404(self) -> None:
        catalog = FakeSalonCatalogRepository()
        resp = _client(catalog=catalog).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 404

    def test_unknown_service_returns_404(self) -> None:
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"service_ids": [str(uuid.uuid4())]}),
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_empty_service_ids_returns_422(self) -> None:
        # Pydantic rejette `service_ids=[]` (min_length=1 sur le champ)
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"service_ids": []}),
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_missing_date_returns_422(self) -> None:
        body = {k: v for k, v in _valid_body().items() if k != "date"}
        resp = _client().post(_BOOK_URL, json=body, headers=_auth_header())
        assert resp.status_code == 422

    def test_missing_start_time_returns_422(self) -> None:
        body = {k: v for k, v in _valid_body().items() if k != "start_time"}
        resp = _client().post(_BOOK_URL, json=body, headers=_auth_header())
        assert resp.status_code == 422

    def test_client_note_optional_accepted(self) -> None:
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"client_note": "Je préfère court."}),
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["client_note"] == "Je préfère court."

    def test_without_hairdresser_id_accepted(self) -> None:
        resp = _client().post(
            _BOOK_URL,
            json={
                "date": _DATE,
                "start_time": "09:00",
                "service_ids": [str(_SERVICE_ID)],
            },
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["hairdresser_id"] is None

    def test_services_price_fixed_at_booking(self) -> None:
        resp = _client().post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        data = resp.json()
        assert len(data["services"]) == 1
        assert "price_at_booking" in data["services"][0]
        assert data["services"][0]["price_at_booking"] == "5000.00"

    def test_admin_role_returns_403(self) -> None:
        resp = _client().post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header(role="ADMIN")
        )
        assert resp.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        resp = _client().post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header(role="HAIRDRESSER")
        )
        assert resp.status_code == 403

    def test_salon_id_in_body_is_ignored(self) -> None:
        # `extra="ignore"` : un `salon_id` dans le corps ne doit pas remplacer celui
        # du chemin (anti-élévation §11.2).
        injected = str(uuid.uuid4())
        resp = _client().post(
            _BOOK_URL,
            json=_valid_body(**{"salon_id": injected}),
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["salon_id"] == str(_SALON_ID)

    def test_multi_service_booking_correct_end_time(self) -> None:
        svc2_id = uuid.UUID("66666666-0000-0000-0000-000000000006")
        catalog = _catalog(
            services=[_make_service(), _make_service(service_id=svc2_id, duration_minutes=30)]
        )
        resp = _client(catalog=catalog).post(
            _BOOK_URL,
            json=_valid_body(**{"service_ids": [str(_SERVICE_ID), str(svc2_id)]}),
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        # 60 + 30 = 90 min → end_time = 10:30:00
        assert resp.json()["end_time"] == "10:30:00"

    def test_race_condition_response_body_is_neutral(self) -> None:
        # La réponse 409 ne divulgue ni PII ni détail SQL (§11.3).
        appts = FakeAppointmentRepository(raise_conflict=True)
        resp = _client(appts=appts).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 409
        detail = resp.json().get("detail", "")
        assert "client" not in detail.lower()
        assert "sql" not in detail.lower()
        assert "postgres" not in detail.lower()


# ---------------------------------------------------------------------------
# GET /catalog/salons/{salon_id}/availability — cas supplémentaires
# ---------------------------------------------------------------------------


class TestGetAvailabilityExtra:
    def test_closed_day_returns_200_empty_slots(self) -> None:
        # Mardi — hors des horaires (lundi uniquement) : réponse 200 + liste vide,
        # pas 404 ni 409.
        tuesday = "2026-08-04"
        resp = _client().get(f"{_AVAIL_URL}?date={tuesday}&service_id={_SERVICE_ID}")
        assert resp.status_code == 200
        assert resp.json()["slots"] == []

    def test_availability_with_hairdresser_id_returns_200(self) -> None:
        url = f"{_AVAIL_URL}?date={_DATE}&service_id={_SERVICE_ID}&hairdresser_id={_HAIRDRESSER_ID}"
        resp = _client().get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert "slots" in data
        assert len(data["slots"]) > 0

    def test_hairdresser_id_isolates_availability(self) -> None:
        # Un créneau réservé pour le coiffeur A ne doit pas apparaître comme occupé
        # dans la disponibilité du coiffeur B.
        other_hairdresser = uuid.UUID("88888888-0000-0000-0000-000000000008")
        booked = SlotRange(
            date=datetime.date(2026, 8, 3),
            start=datetime.time(9, 0),
            end=datetime.time(10, 0),
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, _HAIRDRESSER_ID, datetime.date(2026, 8, 3)): [booked]}
        )
        url = (
            f"{_AVAIL_URL}?date={_DATE}&service_id={_SERVICE_ID}"
            f"&hairdresser_id={other_hairdresser}"
        )
        resp = _client(appts=appts).get(url)
        assert resp.status_code == 200
        starts = {s["start"] for s in resp.json()["slots"]}
        # Le créneau 09:00 doit être disponible pour l'autre coiffeur
        assert "09:00:00" in starts


# ---------------------------------------------------------------------------
# _is_exclusion_violation — détection de la violation de contrainte d'exclusion
# ---------------------------------------------------------------------------


class _MockOrig:
    """Simule un `orig` psycopg : expose `sqlstate`, `diag.constraint_name`, `__str__`."""

    def __init__(
        self,
        sqlstate: str | None = None,
        constraint_name: str | None = None,
        in_str: bool = False,
    ) -> None:
        self.sqlstate = sqlstate
        self.diag = (
            type("_Diag", (), {"constraint_name": constraint_name})()
            if constraint_name is not None
            else None
        )
        self._in_str = in_str

    def __str__(self) -> str:
        if self._in_str:
            return "ERROR: ex_appointments_hairdresser_slot conflict detected"
        return "ERROR: foreign_key_violation"


class _MockIntegrityError:
    """Simule une `sqlalchemy.exc.IntegrityError` avec `.orig` configurable."""

    def __init__(self, orig: object | None) -> None:
        self.orig = orig


def _make_appointment_entity(
    *,
    appt_id: uuid.UUID = _MODIFY_APPT_ID,
    client_id: uuid.UUID = _CLIENT_ID,
    status: str = "PENDING",
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=client_id,
        hairdresser_id=_HAIRDRESSER_ID,
        date=datetime.date(2026, 8, 3),
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT,
        services=(
            BookedServiceEntity(
                service_id=_SERVICE_ID,
                price_at_booking=decimal.Decimal("5000.00"),
            ),
        ),
    )


def _valid_modify_body(**extra) -> dict:  # type: ignore[no-untyped-def]
    base = {
        "date": _DATE,
        "start_time": "09:00",
        "service_ids": [str(_SERVICE_ID)],
        "hairdresser_id": str(_HAIRDRESSER_ID),
    }
    base.update(extra)
    return base


def _modify_client(
    catalog: FakeSalonCatalogRepository | None = None,
    appts: FakeAppointmentRepository | None = None,
    scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """Comme `_client` mais installe aussi `get_audit_log` (requis par PATCH /appointments)."""
    tc = _client(catalog=catalog, appts=appts, scope=scope)
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    return tc


# ---------------------------------------------------------------------------
# GET /appointments — liste des rendez-vous actifs du client (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestListMyAppointmentsAPI:
    _URL = "/appointments"

    def test_returns_200_with_active_appointments(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        resp = _client(appts=appts).get(self._URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == str(_MODIFY_APPT_ID)

    def test_returns_only_active_statuses(self) -> None:
        pending = _make_appointment_entity(appt_id=_MODIFY_APPT_ID, status="PENDING")
        completed = _make_appointment_entity(
            appt_id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"),
            status="COMPLETED",
        )
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        resp = _client(appts=appts).get(self._URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "PENDING"

    def test_no_token_returns_401(self) -> None:
        resp = _client().get(self._URL)
        assert resp.status_code == 401

    def test_manager_role_returns_403(self) -> None:
        resp = _client().get(self._URL, headers=_auth_header(role="MANAGER"))
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _client().get(self._URL, headers=_auth_header(role="ADMIN"))
        assert resp.status_code == 403

    def test_returns_only_own_appointments(self) -> None:
        own = _make_appointment_entity(appt_id=_MODIFY_APPT_ID, client_id=_CLIENT_ID)
        other = _make_appointment_entity(
            appt_id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000099"),
            client_id=_OTHER_CLIENT_ID_API,
        )
        appts = FakeAppointmentRepository(appointments=[own, other])
        resp = _client(appts=appts).get(self._URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["client_id"] == str(_CLIENT_ID)

    def test_empty_repo_returns_empty_list(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _client(appts=appts).get(self._URL, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_response_contains_appointment_fields(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        resp = _client(appts=appts).get(self._URL, headers=_auth_header())
        assert resp.status_code == 200
        item = resp.json()[0]
        assert "id" in item
        assert "salon_id" in item
        assert "client_id" in item
        assert "status" in item
        assert "services" in item


# ---------------------------------------------------------------------------
# PATCH /appointments/{appointment_id} — modification client (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestModifyAppointmentAPI:
    def _url(self, appt_id: uuid.UUID = _MODIFY_APPT_ID) -> str:
        return f"/appointments/{appt_id}"

    def test_pending_appointment_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 200

    def test_confirmed_appointment_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 200

    def test_completed_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 409

    def test_other_client_appointment_returns_404(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_OTHER_CLIENT_ID_API)]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 404

    def test_unknown_appointment_returns_404(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 404

    def test_empty_service_ids_returns_422(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(),
            json=_valid_modify_body(**{"service_ids": []}),
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_no_token_returns_401(self) -> None:
        resp = _modify_client().patch(self._url(), json=_valid_modify_body())
        assert resp.status_code == 401

    def test_manager_role_returns_403(self) -> None:
        resp = _modify_client().patch(
            self._url(),
            json=_valid_modify_body(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _modify_client().patch(
            self._url(),
            json=_valid_modify_body(),
            headers=_auth_header(role="ADMIN"),
        )
        assert resp.status_code == 403

    def test_client_id_in_body_is_ignored(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        injected = str(uuid.uuid4())
        resp = _modify_client(appts=appts).patch(
            self._url(),
            json=_valid_modify_body(**{"client_id": injected}),
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["client_id"] == str(_CLIENT_ID)

    def test_salon_id_in_body_is_ignored(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        injected = str(uuid.uuid4())
        resp = _modify_client(appts=appts).patch(
            self._url(),
            json=_valid_modify_body(**{"salon_id": injected}),
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["salon_id"] == str(_SALON_ID)

    def test_status_in_body_is_ignored(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(),
            json=_valid_modify_body(**{"status": "CONFIRMED"}),
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"

    def test_race_condition_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()],
            raise_conflict=True,
        )
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 409

    def test_response_contains_appointment_fields(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        resp = _modify_client(appts=appts).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "salon_id" in data
        assert "client_id" in data
        assert "status" in data
        assert "services" in data


# ---------------------------------------------------------------------------
# _is_exclusion_violation — détection de la violation de contrainte d'exclusion
# ---------------------------------------------------------------------------


class TestIsExclusionViolation:
    """Tests unitaires de `_is_exclusion_violation` (adapter persistence).

    Cette fonction est le point critique qui distingue une course concurrente
    (→ `SlotAlreadyBooked`) d'une autre erreur d'intégrité (→ relevée telle quelle).
    Elle est testée ici sans I/O réelle via des mocks simples.
    """

    @staticmethod
    def _fn(exc: object) -> bool:
        from coiflink_api.adapters.outbound.persistence.appointment_repository import (
            _is_exclusion_violation,
        )

        return _is_exclusion_violation(exc)  # type: ignore[arg-type]

    def test_no_orig_returns_false(self) -> None:
        assert not self._fn(_MockIntegrityError(None))

    def test_sqlstate_23p01_returns_true(self) -> None:
        orig = _MockOrig(sqlstate="23P01")
        assert self._fn(_MockIntegrityError(orig))

    def test_diag_constraint_name_returns_true(self) -> None:
        orig = _MockOrig(sqlstate="23000", constraint_name="ex_appointments_hairdresser_slot")
        assert self._fn(_MockIntegrityError(orig))

    def test_constraint_name_in_str_returns_true(self) -> None:
        # Fallback : certaines versions de psycopg exposent le nom uniquement via __str__.
        orig = _MockOrig(sqlstate="23000", in_str=True)
        assert self._fn(_MockIntegrityError(orig))

    def test_other_sqlstate_fk_violation_returns_false(self) -> None:
        # SQLSTATE 23503 = foreign_key_violation — ne doit pas être masquée.
        orig = _MockOrig(sqlstate="23503")
        assert not self._fn(_MockIntegrityError(orig))

    def test_unrelated_constraint_in_diag_returns_false(self) -> None:
        orig = _MockOrig(sqlstate="23000", constraint_name="uq_some_other_constraint")
        assert not self._fn(_MockIntegrityError(orig))


# ---------------------------------------------------------------------------
# POST /appointments/{appointment_id}/cancellation — annulation client (US-3.3, #24)
# ---------------------------------------------------------------------------

_CANCEL_APPT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_SET_STATUS_APPT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_ASSIGN_APPT_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")


def _manager_client(
    appts: FakeAppointmentRepository | None = None,
    scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient configuré pour MANAGER avec `_SALON_ID` dans sa portée (#25)."""
    ap = appts if appts is not None else FakeAppointmentRepository()
    manager_scope = FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    hairdresser_scope = (
        scope
        if scope is not None
        else FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_appointment_repository] = lambda: ap
    app.dependency_overrides[get_catalog_repository] = lambda: _catalog()
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(manager_scope)
    app.dependency_overrides[get_salon_scope_repository] = lambda: hairdresser_scope
    return TestClient(app)


def _make_status_entity(
    *,
    appt_id: uuid.UUID = _SET_STATUS_APPT_ID,
    status: str = "PENDING",
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=_HAIRDRESSER_ID,
        date=datetime.date(2026, 8, 3),
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT,
        services=(
            BookedServiceEntity(
                service_id=_SERVICE_ID,
                price_at_booking=decimal.Decimal("5000.00"),
            ),
        ),
    )


def _make_assign_entity(
    *,
    appt_id: uuid.UUID = _ASSIGN_APPT_ID,
    status: str = "PENDING",
    hairdresser_id: uuid.UUID | None = None,
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=hairdresser_id,
        date=datetime.date(2026, 8, 3),
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT,
        services=(
            BookedServiceEntity(
                service_id=_SERVICE_ID,
                price_at_booking=decimal.Decimal("5000.00"),
            ),
        ),
    )


def _cancel_client(
    appts: FakeAppointmentRepository | None = None,
) -> TestClient:
    """Comme `_client` mais installe aussi `get_audit_log` (requis par l'annulation)."""
    tc = _client(appts=appts)
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    return tc


def _make_cancel_entity(
    *,
    appt_id: uuid.UUID = _CANCEL_APPT_ID,
    client_id: uuid.UUID = _CLIENT_ID,
    status: str = "PENDING",
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=client_id,
        hairdresser_id=None,
        date=datetime.date(2026, 8, 3),
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT,
        services=(
            BookedServiceEntity(
                service_id=_SERVICE_ID,
                price_at_booking=decimal.Decimal("5000.00"),
            ),
        ),
    )


class TestCancelAppointmentAPI:
    def _url(self, appt_id: uuid.UUID = _CANCEL_APPT_ID) -> str:
        return f"/appointments/{appt_id}/cancellation"

    # --- Authentification / autorisation ----------------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _cancel_client().post(self._url(), json={})
        assert resp.status_code == 401

    def test_manager_role_returns_403(self) -> None:
        resp = _cancel_client().post(
            self._url(), json={}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _cancel_client().post(
            self._url(), json={}, headers=_auth_header(role="ADMIN")
        )
        assert resp.status_code == 403

    # --- Appartenance (§11.2) ----------------------------------------

    def test_other_client_appointment_returns_404(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(client_id=_OTHER_CLIENT_ID_API)]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 404

    def test_unknown_appointment_returns_404(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 404

    # --- Verrou d'état (§8.1) ----------------------------------------

    def test_completed_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="COMPLETED")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 409

    def test_already_cancelled_appointment_returns_409(self) -> None:
        # Double annulation = 409 (idempotence refusée).
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="CANCELLED")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 409

    def test_no_show_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="NO_SHOW")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 409

    # --- Cas valides ------------------------------------------------

    def test_pending_appointment_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 200

    def test_confirmed_appointment_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="CONFIRMED")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 200

    def test_response_status_is_cancelled(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.json()["status"] == "CANCELLED"

    def test_cancel_with_reason_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(),
            json={"reason": "Empêchement de dernière minute."},
            headers=_auth_header(),
        )
        assert resp.status_code == 200

    def test_cancel_without_reason_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 200

    # --- Anti-élévation §11.2 : champs privilégiés ignorés ---------------

    def test_client_id_in_body_is_ignored(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        injected = str(uuid.uuid4())
        resp = _cancel_client(appts=appts).post(
            self._url(),
            json={"client_id": injected},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["client_id"] == str(_CLIENT_ID)

    def test_salon_id_in_body_is_ignored(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        injected = str(uuid.uuid4())
        resp = _cancel_client(appts=appts).post(
            self._url(),
            json={"salon_id": injected},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["salon_id"] == str(_SALON_ID)

    def test_status_in_body_is_ignored(self) -> None:
        # Le body peut tenter de fixer `status` — doit être ignoré (`extra="ignore"`).
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(),
            json={"status": "PENDING"},
            headers=_auth_header(),
        )
        # La route décide : le statut résultant est CANCELLED (pas PENDING du corps).
        assert resp.status_code == 200
        assert resp.json()["status"] == "CANCELLED"

    def test_response_contains_expected_fields(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        data = resp.json()
        assert "id" in data
        assert "salon_id" in data
        assert "client_id" in data
        assert "status" in data
        assert "services" in data

    def test_409_response_body_is_neutral(self) -> None:
        # §11.3 : la réponse 409 ne divulgue ni PII ni détail SQL.
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="COMPLETED")]
        )
        resp = _cancel_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 409
        detail = resp.json().get("detail", "")
        assert "client" not in detail.lower()
        assert "sql" not in detail.lower()
        assert "postgres" not in detail.lower()


# ---------------------------------------------------------------------------
# POST /salons/{salon_id}/appointments/{appointment_id}/status (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestSetAppointmentStatusAPI:
    """Cycle de statuts gérant via HTTP : portée → machine à états → HTTP (§11.4, #25)."""

    def _url(self, appt_id: uuid.UUID = _SET_STATUS_APPT_ID) -> str:
        return f"/salons/{_SALON_ID}/appointments/{appt_id}/status"

    # --- Authentification / autorisation ------------------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _manager_client().post(self._url(), json={"status": "CONFIRMED"})
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_status_entity()])
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="CLIENT")
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_status_entity()])
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="ADMIN")
        )
        assert resp.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        # Gérant sans portée sur _SALON_ID → require_salon_scope → 403.
        appts = FakeAppointmentRepository(appointments=[_make_status_entity()])
        app.dependency_overrides[get_appointment_repository] = lambda: appts
        app.dependency_overrides[get_catalog_repository] = lambda: _catalog()
        app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
        app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
            FakeSalonScopeRepository()
        )
        app.dependency_overrides[get_salon_scope_repository] = lambda: FakeSalonScopeRepository()
        tc = TestClient(app)
        resp = tc.post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 403

    # --- Validation Pydantic (422) -----------------------------------------

    def test_invalid_status_value_returns_422(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_status_entity()])
        resp = _manager_client(appts=appts).post(
            self._url(),
            json={"status": "INVALID_STATUS"},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    def test_missing_status_field_returns_422(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_status_entity()])
        resp = _manager_client(appts=appts).post(
            self._url(), json={}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 422

    # --- Cas valides ---------------------------------------------------------

    def test_pending_to_confirmed_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200

    def test_pending_to_cancelled_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CANCELLED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200

    def test_confirmed_to_completed_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="CONFIRMED")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "COMPLETED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200

    def test_response_status_updated(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.json()["status"] == "CONFIRMED"

    def test_response_contains_appointment_fields(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        data = resp.json()
        assert "id" in data
        assert "salon_id" in data
        assert "client_id" in data
        assert "status" in data

    # --- Transitions interdites (409) ----------------------------------------

    def test_terminal_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="CANCELLED")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409

    def test_forbidden_transition_returns_409(self) -> None:
        # PENDING → COMPLETED est interdit par la machine à états (deny-by-default).
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "COMPLETED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409

    def test_toctou_guard_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")],
            raise_invalid_transition=True,
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409

    # --- RDV introuvable (404) -----------------------------------------------

    def test_unknown_appointment_returns_404(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 404

    # --- Anti-élévation §11.2 -----------------------------------------------

    def test_extra_body_fields_ignored(self) -> None:
        # `extra="ignore"` : `client_id`/`salon_id` dans le corps doivent être ignorés.
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        injected_client = str(uuid.uuid4())
        resp = _manager_client(appts=appts).post(
            self._url(),
            json={"status": "CONFIRMED", "client_id": injected_client},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json()["client_id"] == str(_CLIENT_ID)

    # --- Motif (§11.3) -------------------------------------------------------

    def test_reason_accepted_on_cancelled_transition(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(),
            json={"status": "CANCELLED", "reason": "Salon fermé exceptionnellement."},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200

    def test_409_response_is_neutral(self) -> None:
        # §11.3 : la réponse 409 ne divulgue ni PII ni détail SQL.
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="CANCELLED")]
        )
        resp = _manager_client(appts=appts).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 409
        detail = resp.json().get("detail", "")
        assert "sql" not in detail.lower()
        assert "postgres" not in detail.lower()


# ---------------------------------------------------------------------------
# PUT /salons/{salon_id}/appointments/{appointment_id}/hairdresser (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestAssignHairdresserAPI:
    """Assignation coiffeur via HTTP : portée → appartenance → conflit → HTTP (#25)."""

    def _url(self, appt_id: uuid.UUID = _ASSIGN_APPT_ID) -> str:
        return f"/salons/{_SALON_ID}/appointments/{appt_id}/hairdresser"

    # --- Authentification / autorisation ------------------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _manager_client().put(
            self._url(), json={"hairdresser_id": str(_HAIRDRESSER_ID)}
        )
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_assign_entity()])
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="CLIENT"),
        )
        assert resp.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        # HAIRDRESSER n'a pas APPOINTMENT_MANAGE.
        appts = FakeAppointmentRepository(appointments=[_make_assign_entity()])
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_assign_entity()])
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="ADMIN"),
        )
        assert resp.status_code == 403

    # --- Cas valides ---------------------------------------------------------

    def test_assign_hairdresser_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200

    def test_deassign_hairdresser_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING", hairdresser_id=_HAIRDRESSER_ID)]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": None},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200

    def test_response_hairdresser_id_updated(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.json()["hairdresser_id"] == str(_HAIRDRESSER_ID)

    def test_response_hairdresser_id_null_after_deassign(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING", hairdresser_id=_HAIRDRESSER_ID)]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": None},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.json()["hairdresser_id"] is None

    def test_confirmed_appointment_assign_returns_200(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="CONFIRMED")]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200

    # --- Erreurs métier -------------------------------------------------------

    def test_unknown_appointment_returns_404(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 404

    def test_hairdresser_not_in_salon_returns_404(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING")]
        )
        other_hairdresser = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
        # Portée vide → le coiffeur demandé n'est pas membre du salon.
        scope = FakeSalonScopeRepository()
        resp = _manager_client(appts=appts, scope=scope).put(
            self._url(),
            json={"hairdresser_id": str(other_hairdresser)},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 404

    def test_terminal_appointment_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="CANCELLED")]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": None},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 409

    def test_slot_conflict_returns_409(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING")],
            raise_conflict=True,
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={"hairdresser_id": str(_HAIRDRESSER_ID)},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 409

    # --- Corps invalide (422) ------------------------------------------------

    def test_missing_hairdresser_field_returns_422(self) -> None:
        # `hairdresser_id` est **requis** (null accepté mais absence rejetée).
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).put(
            self._url(), json={}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 422

    # --- Anti-élévation §11.2 ------------------------------------------------

    def test_extra_body_fields_ignored(self) -> None:
        # `extra="ignore"` : `status` et `salon_id` dans le corps doivent être ignorés.
        appts = FakeAppointmentRepository(
            appointments=[_make_assign_entity(status="PENDING")]
        )
        resp = _manager_client(appts=appts).put(
            self._url(),
            json={
                "hairdresser_id": str(_HAIRDRESSER_ID),
                "status": "CANCELLED",
                "salon_id": str(uuid.uuid4()),
            },
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"
