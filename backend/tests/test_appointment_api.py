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
    get_notification_repository,
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
from coiflink_api.domain.time_window import SALON_TIMEZONE
from coiflink_api.main import app

from .conftest import (
    FakeAppointmentRepository,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeNotificationRepository,
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
_DATE = "2026-08-10"  # lundi
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
    app.dependency_overrides.pop(get_notification_repository, None)
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
    notifications: FakeNotificationRepository | None = None,
) -> TestClient:
    cat = catalog if catalog is not None else _catalog()
    ap = appts if appts is not None else FakeAppointmentRepository()
    # Par défaut `_HAIRDRESSER_ID` est membre ACTIVE de `_SALON_ID` (§11.2).
    sc = (
        scope
        if scope is not None
        else FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({_SALON_ID})})
    )
    # Confirmation de RDV (#45) : dépôt de notifications en mémoire (aucune I/O). Sans
    # cette surcharge, la réservation résoudrait le vrai `SqlNotificationRepository`
    # (session réelle) — le fake garde le chemin `POST` hors base.
    notif = notifications if notifications is not None else FakeNotificationRepository()
    app.dependency_overrides[get_catalog_repository] = lambda: cat
    app.dependency_overrides[get_appointment_repository] = lambda: ap
    app.dependency_overrides[get_salon_scope_repository] = lambda: sc
    app.dependency_overrides[get_notification_repository] = lambda: notif
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
            date=datetime.date(2026, 8, 10),
            start=datetime.time(9, 0),
            end=datetime.time(10, 0),
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, None, datetime.date(2026, 8, 10)): [booked_slot]}
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

    def test_valid_booking_enqueues_one_confirmation_notification(self) -> None:
        # US-7.1 (#45) : une réservation réussie émet **une** confirmation
        # `CONFIRMATION`/`PENDING`, rattachée au RDV créé — couvert en détail par
        # `TestBookAppointmentNotification` (cas d'usage), affirmé ici au niveau API
        # pour fermer l'écart relevé par la revue de la PR #132.
        notif = FakeNotificationRepository()
        resp = _client(notifications=notif).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 201
        appointment_id = resp.json()["id"]
        confirmations = [n for n in notif.enqueued if n.type == "CONFIRMATION"]
        assert len(confirmations) == 1
        notification = confirmations[0]
        assert notification.status == "PENDING"
        assert str(notification.appointment_id) == appointment_id
        assert str(notification.user_id) == str(_CLIENT_ID)

    def test_valid_booking_plans_reminders(self) -> None:
        # US-7.2 (#46) : la réservation planifie aussi des rappels `REMINDER`
        # `PENDING`, datés, rattachés au RDV créé (le RDV est réservé loin dans le
        # futur — `_DATE` — donc les 3 offsets sont encore futurs).
        notif = FakeNotificationRepository()
        resp = _client(notifications=notif).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 201
        appointment_id = resp.json()["id"]
        reminders = [n for n in notif.enqueued if n.type == "REMINDER"]
        assert len(reminders) == 3
        for reminder in reminders:
            assert reminder.status == "PENDING"
            assert str(reminder.appointment_id) == appointment_id
            assert reminder.scheduled_for is not None

    def test_booking_response_never_exposes_reminder_content(self) -> None:
        notif = FakeNotificationRepository()
        resp = _client(notifications=notif).post(
            _BOOK_URL, json=_valid_body(), headers=_auth_header()
        )
        assert resp.status_code == 201
        assert "REMINDER" not in resp.text
        assert "scheduled_for" not in resp.text

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
        tuesday = "2026-08-11"
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
            date=datetime.date(2026, 8, 10),
            start=datetime.time(9, 0),
            end=datetime.time(10, 0),
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, _HAIRDRESSER_ID, datetime.date(2026, 8, 10)): [booked]}
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
    notifications: FakeNotificationRepository | None = None,
) -> TestClient:
    """Comme `_client` mais installe aussi `get_audit_log` (requis par PATCH /appointments)."""
    tc = _client(catalog=catalog, appts=appts, scope=scope, notifications=notifications)
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

    # --- Re-planification des rappels (US-7.2, #46) -------------------------

    def test_modify_reschedules_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notif = FakeNotificationRepository()
        resp = _modify_client(appts=appts, notifications=notif).patch(
            self._url(), json=_valid_modify_body(), headers=_auth_header()
        )
        assert resp.status_code == 200
        assert notif.cancel_calls == [_MODIFY_APPT_ID]
        reminders = [n for n in notif.enqueued if n.type == "REMINDER"]
        assert len(reminders) == 3


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
    notifications: FakeNotificationRepository | None = None,
) -> TestClient:
    """TestClient configuré pour MANAGER avec `_SALON_ID` dans sa portée (#25)."""
    ap = appts if appts is not None else FakeAppointmentRepository()
    manager_scope = FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    hairdresser_scope = (
        scope
        if scope is not None
        else FakeSalonScopeRepository({_HAIRDRESSER_ID: frozenset({_SALON_ID})})
    )
    notif = notifications if notifications is not None else FakeNotificationRepository()
    app.dependency_overrides[get_appointment_repository] = lambda: ap
    app.dependency_overrides[get_catalog_repository] = lambda: _catalog()
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    app.dependency_overrides[get_notification_repository] = lambda: notif
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
    notifications: FakeNotificationRepository | None = None,
) -> TestClient:
    """Comme `_client` mais installe aussi `get_audit_log` (requis par l'annulation)."""
    tc = _client(appts=appts, notifications=notifications)
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

    # --- Annulation des rappels (US-7.2, #46, AC) ---------------------------

    def test_cancel_cancels_pending_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_cancel_entity(status="PENDING")]
        )
        notif = FakeNotificationRepository()
        resp = _cancel_client(appts=appts, notifications=notif).post(
            self._url(), json={}, headers=_auth_header()
        )
        assert resp.status_code == 200
        assert notif.cancel_calls == [_CANCEL_APPT_ID]


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
        app.dependency_overrides[get_notification_repository] = lambda: FakeNotificationRepository()
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

    # --- Annulation des rappels — refus gérant uniquement (US-7.2, #46) -----

    def test_refusal_cancels_pending_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        notif = FakeNotificationRepository()
        resp = _manager_client(appts=appts, notifications=notif).post(
            self._url(), json={"status": "CANCELLED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200
        assert notif.cancel_calls == [_SET_STATUS_APPT_ID]

    def test_confirmation_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_status_entity(status="PENDING")]
        )
        notif = FakeNotificationRepository()
        resp = _manager_client(appts=appts, notifications=notif).post(
            self._url(), json={"status": "CONFIRMED"}, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 200
        assert notif.cancel_calls == []


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


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/appointments — planning vue calendrier (US-3.5, #26)
# ---------------------------------------------------------------------------

_PLANNING_APPT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_PLANNING_APPT_ID_2 = uuid.UUID("cccccccc-0000-0000-0000-000000000002")


def _make_planning_entity(
    *,
    appt_id: uuid.UUID = _PLANNING_APPT_ID,
    status: str = "PENDING",
    date: datetime.date = datetime.date(2026, 8, 3),
    start_time: datetime.time = datetime.time(9, 0),
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=None,
        date=date,
        start_time=start_time,
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


class TestListSalonAppointmentsAPI:
    """Tests HTTP pour GET /salons/{salon_id}/appointments (US-3.5, #26).

    Couvre : 200 liste vide et peuplée ; filtre statut simple et multiple ;
    401 sans jeton ; 403 mauvais rôle et gérant hors périmètre ;
    422 param manquant, plage inversée, plage > 42 jours ;
    200 à exactement 42 jours (borne incluse) ; tri chronologique.
    """

    def _url(self) -> str:
        return _BOOK_URL  # GET sur la même URL de base

    def _params(
        self, *, date_from: str = "2026-08-01", date_to: str = "2026-08-07"
    ) -> dict:
        return {"date_from": date_from, "date_to": date_to}

    # --- Résultats 200 -------------------------------------------------------

    def test_empty_returns_200_empty_list(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_list_with_appointment(self) -> None:
        appt = _make_planning_entity()
        appts = FakeAppointmentRepository(appointments=[appt])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == str(_PLANNING_APPT_ID)

    def test_response_fields_match_schema(self) -> None:
        appt = _make_planning_entity()
        appts = FakeAppointmentRepository(appointments=[appt])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        item = resp.json()[0]
        for field in ("id", "salon_id", "client_id", "status", "date", "start_time", "end_time", "services"):
            assert field in item, f"Champ manquant : {field}"

    def test_salon_id_in_response_matches_requested_salon(self) -> None:
        appt = _make_planning_entity()
        appts = FakeAppointmentRepository(appointments=[appt])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json()[0]["salon_id"] == str(_SALON_ID)

    def test_single_day_range_returns_200(self) -> None:
        appt = _make_planning_entity(date=datetime.date(2026, 8, 3))
        appts = FakeAppointmentRepository(appointments=[appt])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=self._params(date_from="2026-08-03", date_to="2026-08-03"),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    # --- Filtre par statut ---------------------------------------------------

    def test_status_filter_single_returns_only_matching(self) -> None:
        pending = _make_planning_entity(appt_id=_PLANNING_APPT_ID, status="PENDING")
        confirmed = _make_planning_entity(appt_id=_PLANNING_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params={**self._params(), "status": "CONFIRMED"},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "CONFIRMED"

    def test_status_filter_multi_repeatable_param(self) -> None:
        pending = _make_planning_entity(appt_id=_PLANNING_APPT_ID, status="PENDING")
        confirmed = _make_planning_entity(appt_id=_PLANNING_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=[
                ("date_from", "2026-08-01"),
                ("date_to", "2026-08-07"),
                ("status", "PENDING"),
                ("status", "CONFIRMED"),
            ],
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_no_status_filter_returns_all_statuses(self) -> None:
        pending = _make_planning_entity(appt_id=_PLANNING_APPT_ID, status="PENDING")
        confirmed = _make_planning_entity(appt_id=_PLANNING_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    # --- Sécurité / RBAC deny-by-default (ADR-0015) -------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _manager_client().get(self._url(), params=self._params())
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="CLIENT"),
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="ADMIN"),
        )
        assert resp.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 403

    def test_manager_out_of_scope_returns_403(self) -> None:
        # Gérant sans portée sur _SALON_ID → require_salon_scope → 403 (§11.2).
        app.dependency_overrides[get_appointment_repository] = lambda: FakeAppointmentRepository()
        app.dependency_overrides[get_catalog_repository] = lambda: _catalog()
        app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
        app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
            FakeSalonScopeRepository()
        )
        app.dependency_overrides[get_salon_scope_repository] = lambda: FakeSalonScopeRepository()
        tc = TestClient(app)
        resp = tc.get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 403

    # --- Validation 422 (plage, params) -------------------------------------

    def test_missing_date_from_returns_422(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params={"date_to": "2026-08-07"},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    def test_missing_date_to_returns_422(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params={"date_from": "2026-08-01"},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    def test_date_to_before_date_from_returns_422(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params=self._params(date_from="2026-08-07", date_to="2026-08-01"),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    def test_range_exactly_42_days_allowed(self) -> None:
        # (2026-02-12 - 2026-01-01).days == 42 → égal à la limite → 200.
        resp = _manager_client().get(
            self._url(),
            params=self._params(date_from="2026-01-01", date_to="2026-02-12"),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200

    def test_range_over_42_days_returns_422(self) -> None:
        # (2026-02-13 - 2026-01-01).days == 43 → dépasse la limite → 422.
        resp = _manager_client().get(
            self._url(),
            params=self._params(date_from="2026-01-01", date_to="2026-02-13"),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    def test_invalid_date_format_returns_422(self) -> None:
        resp = _manager_client().get(
            self._url(),
            params=self._params(date_from="not-a-date"),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    # --- Tri chronologique --------------------------------------------------

    def test_results_sorted_by_start_time(self) -> None:
        later = _make_planning_entity(
            appt_id=_PLANNING_APPT_ID,
            date=datetime.date(2026, 8, 3),
            start_time=datetime.time(11, 0),
        )
        earlier = _make_planning_entity(
            appt_id=_PLANNING_APPT_ID_2,
            date=datetime.date(2026, 8, 3),
            start_time=datetime.time(9, 0),
        )
        appts = FakeAppointmentRepository(appointments=[later, earlier])
        resp = _manager_client(appts=appts).get(
            self._url(),
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["start_time"] <= data[1]["start_time"]


# ---------------------------------------------------------------------------
# GET /appointments/assigned — planning coiffeur (US-3.6, #27)
# ---------------------------------------------------------------------------

_ASSIGNED_APPT_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
_ASSIGNED_APPT_ID_2 = uuid.UUID("ffffffff-0000-0000-0000-000000000002")
_OTHER_HAIRDRESSER_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _make_assigned_entity(
    *,
    appt_id: uuid.UUID = _ASSIGNED_APPT_ID,
    hairdresser_id: uuid.UUID | None = _HAIRDRESSER_USER_ID,
    status: str = "PENDING",
    date: datetime.date = datetime.date(2026, 8, 3),
    start_time: datetime.time = datetime.time(9, 0),
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=hairdresser_id,
        date=date,
        start_time=start_time,
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


class TestListAssignedAppointmentsAPI:
    """Tests HTTP pour GET /appointments/assigned (US-3.6, #27).

    Couvre : 200 liste vide et peuplée ; isolation (hairdresser_id depuis principal, §11.2) ;
    filtre statut simple et multiple ; 401 sans jeton ; 403 CLIENT/MANAGER/ADMIN ;
    422 param manquant, plage inversée, plage > 42 jours, statut invalide ;
    200 à exactement 42 jours (borne incluse) ; tri chronologique ;
    invariant deny-by-default (route absente de PUBLIC_ROUTE_PATHS).
    """

    _URL = "/appointments/assigned"

    def _params(
        self, *, date_from: str = "2026-08-01", date_to: str = "2026-08-07"
    ) -> dict:
        return {"date_from": date_from, "date_to": date_to}

    # --- Résultats 200 -------------------------------------------------------

    def test_empty_returns_200_empty_list(self) -> None:
        resp = _client().get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_assigned_appointments(self) -> None:
        appt = _make_assigned_entity()
        appts = FakeAppointmentRepository(appointments=[appt])
        resp = _client(appts=appts).get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == str(_ASSIGNED_APPT_ID)

    # --- Isolation §11.2 : hairdresser_id imposé par principal.id -----------

    def test_other_hairdresser_appointments_excluded(self) -> None:
        other_appt = _make_assigned_entity(
            appt_id=_ASSIGNED_APPT_ID,
            hairdresser_id=_OTHER_HAIRDRESSER_USER_ID,
        )
        appts = FakeAppointmentRepository(appointments=[other_appt])
        resp = _client(appts=appts).get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_unassigned_appointments_excluded(self) -> None:
        unassigned = _make_assigned_entity(
            appt_id=_ASSIGNED_APPT_ID, hairdresser_id=None
        )
        appts = FakeAppointmentRepository(appointments=[unassigned])
        resp = _client(appts=appts).get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    # --- Filtre statut -------------------------------------------------------

    def test_status_filter_single_returns_only_matching(self) -> None:
        pending = _make_assigned_entity(appt_id=_ASSIGNED_APPT_ID, status="PENDING")
        confirmed = _make_assigned_entity(appt_id=_ASSIGNED_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        resp = _client(appts=appts).get(
            self._URL,
            params={**self._params(), "status": "CONFIRMED"},
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "CONFIRMED"

    def test_status_filter_multi_repeatable_param(self) -> None:
        pending = _make_assigned_entity(appt_id=_ASSIGNED_APPT_ID, status="PENDING")
        confirmed = _make_assigned_entity(appt_id=_ASSIGNED_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        resp = _client(appts=appts).get(
            self._URL,
            params=[
                ("date_from", "2026-08-01"),
                ("date_to", "2026-08-07"),
                ("status", "PENDING"),
                ("status", "CONFIRMED"),
            ],
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_no_status_filter_returns_all_statuses(self) -> None:
        pending = _make_assigned_entity(appt_id=_ASSIGNED_APPT_ID, status="PENDING")
        confirmed = _make_assigned_entity(appt_id=_ASSIGNED_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        resp = _client(appts=appts).get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    # --- Auth / RBAC ---------------------------------------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _client().get(self._URL, params=self._params())
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        resp = _client().get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="CLIENT"),
        )
        assert resp.status_code == 403

    def test_manager_role_returns_403(self) -> None:
        resp = _client().get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _client().get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="ADMIN"),
        )
        assert resp.status_code == 403

    # --- Validation 422 ------------------------------------------------------

    def test_missing_date_from_returns_422(self) -> None:
        resp = _client().get(
            self._URL,
            params={"date_to": "2026-08-07"},
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 422

    def test_missing_date_to_returns_422(self) -> None:
        resp = _client().get(
            self._URL,
            params={"date_from": "2026-08-01"},
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 422

    def test_date_to_before_date_from_returns_422(self) -> None:
        resp = _client().get(
            self._URL,
            params=self._params(date_from="2026-08-07", date_to="2026-08-01"),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 422

    def test_range_exactly_42_days_returns_200(self) -> None:
        # (2026-02-12 - 2026-01-01).days == 42 → borne incluse → 200.
        resp = _client().get(
            self._URL,
            params=self._params(date_from="2026-01-01", date_to="2026-02-12"),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200

    def test_range_over_42_days_returns_422(self) -> None:
        # (2026-02-13 - 2026-01-01).days == 43 → dépasse la limite → 422.
        resp = _client().get(
            self._URL,
            params=self._params(date_from="2026-01-01", date_to="2026-02-13"),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 422

    def test_invalid_date_format_returns_422(self) -> None:
        resp = _client().get(
            self._URL,
            params=self._params(date_from="not-a-date"),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 422

    def test_invalid_status_value_returns_422(self) -> None:
        resp = _client().get(
            self._URL,
            params={**self._params(), "status": "INVALID_STATUS"},
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 422

    # --- Forme de la réponse -------------------------------------------------

    def test_response_fields_match_schema(self) -> None:
        appt = _make_assigned_entity()
        appts = FakeAppointmentRepository(appointments=[appt])
        resp = _client(appts=appts).get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        item = resp.json()[0]
        for field in (
            "id", "salon_id", "client_id", "hairdresser_id",
            "status", "date", "start_time", "end_time", "services",
        ):
            assert field in item

    def test_results_sorted_by_start_time(self) -> None:
        later = _make_assigned_entity(
            appt_id=_ASSIGNED_APPT_ID,
            date=datetime.date(2026, 8, 3),
            start_time=datetime.time(11, 0),
        )
        earlier = _make_assigned_entity(
            appt_id=_ASSIGNED_APPT_ID_2,
            date=datetime.date(2026, 8, 3),
            start_time=datetime.time(9, 0),
        )
        appts = FakeAppointmentRepository(appointments=[later, earlier])
        resp = _client(appts=appts).get(
            self._URL,
            params=self._params(),
            headers=_auth_header(role="HAIRDRESSER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["start_time"] <= data[1]["start_time"]

    # --- Invariant deny-by-default -------------------------------------------

    def test_assigned_route_absent_from_public_route_paths(self) -> None:
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS
        assert "/appointments/assigned" not in PUBLIC_ROUTE_PATHS


# ---------------------------------------------------------------------------
# GET /appointments/history — historique client (US-4.4, #30)
# ---------------------------------------------------------------------------

_HISTORY_APPT_ID_1 = uuid.UUID("eeeeeeee-0000-0000-0001-000000000001")
_HISTORY_APPT_ID_2 = uuid.UUID("eeeeeeee-0000-0000-0001-000000000002")
_OTHER_CLIENT_HISTORY = uuid.UUID("99999999-0000-0001-0000-000000000099")

_HISTORY_URL = "/appointments/history"


def _make_history_entity(
    *,
    appt_id: uuid.UUID = _HISTORY_APPT_ID_1,
    client_id: uuid.UUID = _CLIENT_ID,
    status: str = "COMPLETED",
    date: datetime.date = datetime.date(2026, 6, 1),
    start_time: datetime.time = datetime.time(9, 0),
) -> AppointmentEntity:
    return AppointmentEntity(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=client_id,
        hairdresser_id=None,
        date=date,
        start_time=start_time,
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


class TestListMyAppointmentHistoryAPI:
    """Tests HTTP pour GET /appointments/history (US-4.4, #30).

    Couvre : filtre COMPLETED serveur (rien d'autre) ; appartenance (§11.2) ;
    RBAC deny-by-default (401/403) ; réponse avec prestations et price_at_booking ;
    état vide ; route absente de PUBLIC_ROUTE_PATHS ; non-régression GET /appointments.
    """

    # --- Filtre COMPLETED serveur (acceptation « rien d'autre ») -------------

    def test_returns_200_with_completed_appointments(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_history_entity(status="COMPLETED")]
        )
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["status"] == "COMPLETED"

    def test_pending_appointment_not_in_history(self) -> None:
        pending = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, status="PENDING"
        )
        completed = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_2, status="COMPLETED"
        )
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "COMPLETED"

    def test_confirmed_appointment_not_in_history(self) -> None:
        confirmed = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, status="CONFIRMED"
        )
        appts = FakeAppointmentRepository(appointments=[confirmed])
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cancelled_appointment_not_in_history(self) -> None:
        cancelled = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, status="CANCELLED"
        )
        appts = FakeAppointmentRepository(appointments=[cancelled])
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_no_show_appointment_not_in_history(self) -> None:
        no_show = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, status="NO_SHOW"
        )
        appts = FakeAppointmentRepository(appointments=[no_show])
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_empty_history_returns_200_empty_list(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    # --- Appartenance §11.2 : seuls les RDV du client demandeur ---------------

    def test_returns_only_own_appointments(self) -> None:
        own = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, client_id=_CLIENT_ID, status="COMPLETED"
        )
        other = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_2,
            client_id=_OTHER_CLIENT_HISTORY,
            status="COMPLETED",
        )
        appts = FakeAppointmentRepository(appointments=[own, other])
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["client_id"] == str(_CLIENT_ID)

    # --- Réponse : champs et prestations --------------------------------------

    def test_response_contains_expected_fields(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_history_entity()]
        )
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        item = resp.json()[0]
        for field in ("id", "salon_id", "client_id", "status", "date",
                      "start_time", "end_time", "services"):
            assert field in item

    def test_response_services_carry_price_at_booking(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_history_entity()]
        )
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        services = resp.json()[0]["services"]
        assert len(services) == 1
        assert "price_at_booking" in services[0]
        assert services[0]["price_at_booking"] == "5000.00"

    def test_response_status_is_completed(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_history_entity()]
        )
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()[0]["status"] == "COMPLETED"

    # --- RBAC deny-by-default (ADR-0015) -------------------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _client().get(_HISTORY_URL)
        assert resp.status_code == 401

    def test_manager_role_returns_403(self) -> None:
        resp = _client().get(_HISTORY_URL, headers=_auth_header(role="MANAGER"))
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _client().get(_HISTORY_URL, headers=_auth_header(role="ADMIN"))
        assert resp.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        resp = _client().get(
            _HISTORY_URL, headers=_auth_header(role="HAIRDRESSER")
        )
        assert resp.status_code == 403

    # --- Invariant deny-by-default : route protégée --------------------------

    def test_history_route_absent_from_public_route_paths(self) -> None:
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS

        assert "/appointments/history" not in PUBLIC_ROUTE_PATHS

    def test_unprotected_routes_remains_empty(self) -> None:
        from coiflink_api.adapters.inbound.security import unprotected_routes

        assert unprotected_routes(app) == []

    # --- Non-régression : GET /appointments ne renvoie que les actifs --------

    def test_get_appointments_still_excludes_completed(self) -> None:
        pending = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, status="PENDING"
        )
        completed = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_2, status="COMPLETED"
        )
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        resp = _client(appts=appts).get("/appointments", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        statuses = {item["status"] for item in data}
        assert "COMPLETED" not in statuses

    def test_get_appointments_still_returns_pending(self) -> None:
        pending = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1, status="PENDING"
        )
        appts = FakeAppointmentRepository(appointments=[pending])
        resp = _client(appts=appts).get("/appointments", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "PENDING"

    # --- Ordre descendant (plus récent d'abord) --------------------------------

    def test_history_ordered_newest_first(self) -> None:
        older = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_1,
            status="COMPLETED",
            date=datetime.date(2026, 5, 1),
            start_time=datetime.time(9, 0),
        )
        newer = _make_history_entity(
            appt_id=_HISTORY_APPT_ID_2,
            status="COMPLETED",
            date=datetime.date(2026, 6, 1),
            start_time=datetime.time(9, 0),
        )
        appts = FakeAppointmentRepository(appointments=[older, newer])
        resp = _client(appts=appts).get(_HISTORY_URL, headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Plus récent (2026-06-01) doit apparaître en premier.
        assert data[0]["date"] >= data[1]["date"]


# ---------------------------------------------------------------------------
# GET /salons/{salon_id}/appointments/daily-summary — décompte du jour (US-6.1, #39)
# ---------------------------------------------------------------------------

_DAILY_SUMMARY_URL = f"/salons/{_SALON_ID}/appointments/daily-summary"
_SUMMARY_DAY = datetime.date(2026, 7, 31)
_SUMMARY_DAY_STR = "2026-07-31"


def _make_summary_entity(
    *,
    salon_id: uuid.UUID = _SALON_ID,
    status: str = "PENDING",
    date: datetime.date = _SUMMARY_DAY,
) -> AppointmentEntity:
    return AppointmentEntity(
        id=uuid.uuid4(),
        salon_id=salon_id,
        client_id=_CLIENT_ID,
        hairdresser_id=None,
        date=date,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT,
    )


def _daily_summary_client(
    appts: FakeAppointmentRepository | None = None,
    manager_scope: FakeSalonScopeRepository | None = None,
) -> TestClient:
    """TestClient MANAGER avec `_SALON_ID` dans sa portée (US-6.1, #39)."""
    ap = appts if appts is not None else FakeAppointmentRepository()
    scope = (
        manager_scope
        if manager_scope is not None
        else FakeSalonScopeRepository({_MANAGER_ID: frozenset({_SALON_ID})})
    )
    app.dependency_overrides[get_appointment_repository] = lambda: ap
    app.dependency_overrides[get_catalog_repository] = lambda: _catalog()
    app.dependency_overrides[get_audit_log] = lambda: FakeAuditLog()
    app.dependency_overrides[get_user_repository] = lambda: _user_repo_for_all_roles()
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope)
    app.dependency_overrides[get_salon_scope_repository] = lambda: FakeSalonScopeRepository()
    return TestClient(app)


class TestDailySummaryAPI:
    """Tests HTTP pour GET /salons/{id}/appointments/daily-summary (US-6.1, #39).

    Couvre : 200 réponse complète (toutes clés présentes, total == somme) ;
    401 sans jeton ; 403 mauvais rôle et MANAGER hors périmètre ;
    422 `date` mal formée ; isolation salon et isolation jour ;
    non-PII (pas de client_id, client_note, hairdresser_id) ;
    `date` par défaut = aujourd'hui (Africa/Abidjan).
    """

    # --- 401 / 403 : accès refusé -----------------------------------------

    def test_no_token_returns_401(self) -> None:
        resp = _daily_summary_client().get(_DAILY_SUMMARY_URL)
        assert resp.status_code == 401

    def test_client_role_returns_403(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL, headers=_auth_header(role="CLIENT")
        )
        assert resp.status_code == 403

    def test_hairdresser_role_returns_403(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL, headers=_auth_header(role="HAIRDRESSER")
        )
        assert resp.status_code == 403

    def test_admin_role_returns_403(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL, headers=_auth_header(role="ADMIN")
        )
        assert resp.status_code == 403

    def test_manager_wrong_salon_returns_403(self) -> None:
        # MANAGER authentifié mais portée ≠ _SALON_ID → 403 générique (aucun oracle)
        other_salon = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
        out_of_scope = FakeSalonScopeRepository({_MANAGER_ID: frozenset({other_salon})})
        resp = _daily_summary_client(manager_scope=out_of_scope).get(
            _DAILY_SUMMARY_URL, headers=_auth_header(role="MANAGER")
        )
        assert resp.status_code == 403

    # --- 200 : réponse valide -----------------------------------------------

    def test_manager_of_salon_returns_200(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200

    def test_response_contains_required_fields(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        data = resp.json()
        assert "date" in data
        assert "total" in data
        assert "by_status" in data

    def test_all_five_statuses_in_by_status(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        by_status = resp.json()["by_status"]
        for status in ("PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"):
            assert status in by_status, f"Statut manquant dans by_status : {status}"

    def test_total_equals_sum_of_by_status(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[
                _make_summary_entity(status="CONFIRMED"),
                _make_summary_entity(status="PENDING"),
            ]
        )
        resp = _daily_summary_client(appts=appts).get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        data = resp.json()
        assert data["total"] == sum(data["by_status"].values())

    def test_correct_counts_returned(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[
                _make_summary_entity(status="CONFIRMED"),
                _make_summary_entity(status="CONFIRMED"),
                _make_summary_entity(status="NO_SHOW"),
            ]
        )
        resp = _daily_summary_client(appts=appts).get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        data = resp.json()
        assert data["by_status"]["CONFIRMED"] == 2
        assert data["by_status"]["NO_SHOW"] == 1
        assert data["total"] == 3

    def test_empty_salon_all_counts_zero(self) -> None:
        appts = FakeAppointmentRepository()
        resp = _daily_summary_client(appts=appts).get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert all(v == 0 for v in data["by_status"].values())

    # --- Paramètre `date` ---------------------------------------------------

    def test_explicit_date_reflected_in_response(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json()["date"] == _SUMMARY_DAY_STR

    def test_no_date_param_uses_today(self) -> None:
        today = datetime.datetime.now(SALON_TIMEZONE).date().isoformat()
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json()["date"] == today

    def test_malformed_date_returns_422(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": "not-a-date"},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 422

    # --- Isolation §11.2 : salon et jour ------------------------------------

    def test_other_salon_appointments_not_counted(self) -> None:
        other_salon = uuid.UUID("dddddddd-0000-0000-0000-000000000099")
        appts = FakeAppointmentRepository(
            appointments=[_make_summary_entity(salon_id=other_salon, status="CONFIRMED")]
        )
        resp = _daily_summary_client(appts=appts).get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_appointments_on_different_day_not_counted(self) -> None:
        yesterday = datetime.date(2026, 7, 30)
        appts = FakeAppointmentRepository(
            appointments=[_make_summary_entity(date=yesterday, status="CONFIRMED")]
        )
        resp = _daily_summary_client(appts=appts).get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    # --- Non-PII §11.3 -------------------------------------------------------

    def test_response_contains_no_client_id(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        data = resp.json()
        assert "client_id" not in data

    def test_response_contains_no_client_note(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        data = resp.json()
        assert "client_note" not in data

    def test_response_contains_no_hairdresser_id(self) -> None:
        resp = _daily_summary_client().get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        data = resp.json()
        assert "hairdresser_id" not in data

    def test_by_status_values_are_integers(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_summary_entity(status="CONFIRMED")]
        )
        resp = _daily_summary_client(appts=appts).get(
            _DAILY_SUMMARY_URL,
            params={"date": _SUMMARY_DAY_STR},
            headers=_auth_header(role="MANAGER"),
        )
        for v in resp.json()["by_status"].values():
            assert isinstance(v, int)
