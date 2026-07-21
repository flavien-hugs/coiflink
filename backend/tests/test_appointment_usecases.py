"""Tests unitaires — cas d'usage `CheckAvailability` et `BookAppointment` (US-3.7, #21).

Tous les ports sont remplacés par des fakes (conftest.py) : aucune base ni réseau.

Couvre :
- `CheckAvailability` : salon inconnu → `SalonNotFound` ; salon non réservable
  (`is_bookable` échoue) → `SalonNotBookable` ; prestation inactive/hors salon →
  `ServiceNotFound` ; salon réservable → retourne les créneaux du moteur ;
- `BookAppointment` : `client_id`/`salon_id` jamais issus du corps ; prestation
  inconnue → `ServiceNotFound` ; salon non réservable → `SalonNotBookable` ; créneau
  hors offre → `SlotUnavailable` ; course concurrente simulée (FakeAppointmentRepository
  `raise_conflict=True`) → `SlotAlreadyBooked` et rien persisté ;
  réservation valide → `Appointment` créé avec les bons champs.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.application.appointments import BookAppointment, BookingCommand, CheckAvailability
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    HairdresserNotInSalon,
    SalonNotBookable,
    SalonNotFound,
    ServiceNotFound,
    SlotAlreadyBooked,
    SlotUnavailable,
)
from coiflink_api.domain.opening_hours import to_jsonb, parse_opening_hours
from coiflink_api.domain.salon import Salon
from coiflink_api.domain.service import Service

from .conftest import (
    FakeAppointmentRepository,
    FakeSalonCatalogRepository,
    FakeSalonScopeRepository,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_SERVICE_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_OTHER_SERVICE_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")
_DATE = datetime.date(2026, 8, 3)  # lundi
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

_OPENING_HOURS_DICT = to_jsonb(
    parse_opening_hours({"weekly": {"mon": [{"start": "09:00", "end": "17:00"}]}})
)


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
    duration_minutes: int = 60,
    is_active: bool = True,
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


def _bookable_catalog(
    *,
    salon: Salon | None = None,
    services: list[Service] | None = None,
) -> FakeSalonCatalogRepository:
    s = salon if salon is not None else _make_salon()
    svcs = services if services is not None else [_make_service()]
    return FakeSalonCatalogRepository(
        salons=[s],
        services={_SALON_ID: svcs},
    )


# ---------------------------------------------------------------------------
# CheckAvailability
# ---------------------------------------------------------------------------


class TestCheckAvailability:
    def _uc(
        self,
        catalog: FakeSalonCatalogRepository,
        appts: FakeAppointmentRepository | None = None,
    ) -> CheckAvailability:
        return CheckAvailability(catalog, appts or FakeAppointmentRepository())

    def test_unknown_salon_raises_salon_not_found(self) -> None:
        catalog = FakeSalonCatalogRepository()  # aucun salon
        with pytest.raises(SalonNotFound):
            self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID)

    def test_inactive_salon_raises_salon_not_found(self) -> None:
        catalog = _bookable_catalog(salon=_make_salon(status="INACTIVE"))
        # `get_active` filtre → None → SalonNotFound
        with pytest.raises(SalonNotFound):
            self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID)

    def test_salon_without_hours_raises_salon_not_bookable(self) -> None:
        catalog = _bookable_catalog(salon=_make_salon(opening_hours=None))
        with pytest.raises(SalonNotBookable):
            self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID)

    def test_inactive_service_raises_service_not_found(self) -> None:
        catalog = _bookable_catalog(services=[_make_service(is_active=False)])
        with pytest.raises(ServiceNotFound):
            self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID)

    def test_unknown_service_raises_service_not_found(self) -> None:
        catalog = _bookable_catalog()
        with pytest.raises(ServiceNotFound):
            self._uc(catalog).execute(_SALON_ID, _DATE, _OTHER_SERVICE_ID)

    def test_bookable_salon_returns_slots(self) -> None:
        catalog = _bookable_catalog()
        result = self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID)
        assert isinstance(result, tuple)
        assert len(result) > 0
        assert all(isinstance(s, SlotRange) for s in result)
        assert all(s.date == _DATE for s in result)

    def test_booked_slot_excluded_from_results(self) -> None:
        booked_slot = SlotRange(
            date=_DATE,
            start=datetime.time(9, 0),
            end=datetime.time(10, 0),
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, _HAIRDRESSER_ID, _DATE): [booked_slot]}
        )
        catalog = _bookable_catalog()
        result = CheckAvailability(catalog, appts).execute(
            _SALON_ID, _DATE, _SERVICE_ID, _HAIRDRESSER_ID
        )
        from coiflink_api.domain.availability import overlaps

        for slot in result:
            assert not overlaps(slot, booked_slot)

    def test_slots_only_contain_free_times_no_pii(self) -> None:
        catalog = _bookable_catalog()
        result = self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID)
        # La réponse ne porte que date/start/end — pas d'identifiant client (§11.3).
        for slot in result:
            assert hasattr(slot, "date")
            assert hasattr(slot, "start")
            assert hasattr(slot, "end")
            assert not hasattr(slot, "client_id")


# ---------------------------------------------------------------------------
# BookAppointment
# ---------------------------------------------------------------------------


def _valid_command(
    *,
    hairdresser_id: uuid.UUID | None = _HAIRDRESSER_ID,
    service_ids: tuple[uuid.UUID, ...] = (_SERVICE_ID,),
    start_time: datetime.time = datetime.time(9, 0),
) -> BookingCommand:
    return BookingCommand(
        date=_DATE,
        start_time=start_time,
        service_ids=service_ids,
        hairdresser_id=hairdresser_id,
        granularity_minutes=15,
    )


def _scope(
    scopes: dict[uuid.UUID, frozenset[uuid.UUID]] | None = None,
) -> FakeSalonScopeRepository:
    """Portée employé : par défaut `_HAIRDRESSER_ID` est membre ACTIVE de `_SALON_ID`."""

    if scopes is None:
        scopes = {_HAIRDRESSER_ID: frozenset({_SALON_ID})}
    return FakeSalonScopeRepository(scopes)


class TestBookAppointment:
    def _uc(
        self,
        catalog: FakeSalonCatalogRepository,
        appts: FakeAppointmentRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
    ) -> BookAppointment:
        return BookAppointment(
            catalog,
            appts or FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
        )

    def test_client_id_from_argument_not_body(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        result = self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())
        # `client_id` doit être celui passé en argument, jamais celui du corps
        assert result.client_id == _CLIENT_ID

    def test_salon_id_from_argument_not_body(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        result = self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())
        assert result.salon_id == _SALON_ID

    def test_unknown_salon_raises_salon_not_found(self) -> None:
        catalog = FakeSalonCatalogRepository()
        with pytest.raises(SalonNotFound):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, _valid_command())

    def test_inactive_salon_raises_salon_not_found(self) -> None:
        catalog = _bookable_catalog(salon=_make_salon(status="INACTIVE"))
        with pytest.raises(SalonNotFound):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, _valid_command())

    def test_salon_without_hours_raises_salon_not_bookable(self) -> None:
        catalog = _bookable_catalog(salon=_make_salon(opening_hours=None))
        with pytest.raises(SalonNotBookable):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, _valid_command())

    def test_unknown_service_raises_service_not_found(self) -> None:
        catalog = _bookable_catalog()
        cmd = _valid_command(service_ids=(_OTHER_SERVICE_ID,))
        with pytest.raises(ServiceNotFound):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, cmd)

    def test_slot_outside_hours_raises_slot_unavailable(self) -> None:
        catalog = _bookable_catalog()
        # 23:00 → hors horaires d'ouverture
        cmd = _valid_command(start_time=datetime.time(23, 0))
        with pytest.raises(SlotUnavailable):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, cmd)

    def test_race_condition_raises_slot_already_booked(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(raise_conflict=True)
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())

    def test_race_condition_nothing_persisted(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(raise_conflict=True)
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())
        # Le dépôt ne doit avoir persisté aucun rendez-vous
        assert appts.created == []

    def test_valid_booking_creates_appointment(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        result = self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())
        assert len(appts.created) == 1
        assert result.date == _DATE
        assert result.start_time == datetime.time(9, 0)
        assert result.end_time == datetime.time(10, 0)  # 60 min
        assert result.status == "PENDING"

    def test_valid_booking_sets_services_with_price(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        result = self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())
        assert len(result.services) == 1
        assert result.services[0].service_id == _SERVICE_ID
        assert result.services[0].price_at_booking == decimal.Decimal("5000.00")

    def test_multi_service_end_time_is_sum(self) -> None:
        svc2 = _make_service(service_id=_OTHER_SERVICE_ID, duration_minutes=30)
        catalog = _bookable_catalog(services=[_make_service(), svc2])
        appts = FakeAppointmentRepository()
        cmd = _valid_command(service_ids=(_SERVICE_ID, _OTHER_SERVICE_ID))
        result = self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, cmd)
        # 60 + 30 = 90 min → end_time = 10:30
        assert result.end_time == datetime.time(10, 30)

    def test_past_slot_raises_slot_unavailable(self) -> None:
        # Simulé via now = 10:00 alors que le créneau demandé est 09:00
        catalog = _bookable_catalog()
        now = datetime.datetime(_DATE.year, _DATE.month, _DATE.day, 10, 0)
        cmd = _valid_command(start_time=datetime.time(9, 0))
        with pytest.raises(SlotUnavailable):
            BookAppointment(catalog, FakeAppointmentRepository(), _scope()).execute(
                _SALON_ID, _CLIENT_ID, cmd, now=now
            )

    def test_no_services_raises_appointment_service_required(self) -> None:
        # Cas dégénéré : service_ids vide — la validation `require_services` doit
        # s'activer avant toute I/O (le cas d'usage charge d'abord le salon,
        # puis itère les service_ids → tuple vide → require_services lève).
        from coiflink_api.domain.errors import AppointmentServiceRequired

        catalog = _bookable_catalog()
        cmd = BookingCommand(
            date=_DATE,
            start_time=datetime.time(9, 0),
            service_ids=(),
        )
        with pytest.raises(AppointmentServiceRequired):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, cmd)

    # --- Rattachement du coiffeur au salon (§11.2) -------------------------
    # L'exclusion base `ex_appointments_hairdresser_slot` porte sur
    # `(hairdresser_id, slot)` **sans** `salon_id` : sans ce contrôle applicatif,
    # un client pourrait occuper l'agenda d'un coiffeur d'un autre salon.

    def test_hairdresser_of_another_salon_is_rejected(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        scope = _scope({_HAIRDRESSER_ID: frozenset({other_salon})})
        with pytest.raises(HairdresserNotInSalon):
            self._uc(catalog, appts, scope).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        # Rien n'a été écrit : le refus intervient avant l'INSERT.
        assert appts.created == []

    def test_unknown_hairdresser_id_is_rejected(self) -> None:
        # Portée vide : UUID inconnu, ou compte CLIENT passé comme coiffeur —
        # indiscernables (aucun oracle d'existence).
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        with pytest.raises(HairdresserNotInSalon):
            self._uc(catalog, appts, _scope({})).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert appts.created == []

    def test_membership_is_read_from_scope_with_hairdresser_role(self) -> None:
        # La question posée au port d'autorité est bien « ce compte est-il
        # membre ACTIVE ? » — branche HAIRDRESSER de `salon_ids_for`.
        catalog = _bookable_catalog()
        scope = _scope()
        self._uc(catalog, FakeAppointmentRepository(), scope).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert scope.calls == [(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)]

    def test_booking_without_hairdresser_skips_membership_check(self) -> None:
        # Sans coiffeur assigné il n'y a pas de rattachement à valider : le port
        # de portée ne doit pas être sollicité.
        catalog = _bookable_catalog()
        scope = _scope()
        self._uc(catalog, FakeAppointmentRepository(), scope).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(hairdresser_id=None)
        )
        assert scope.calls == []

    def test_booking_without_hairdresser_succeeds(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        result = self._uc(catalog, appts).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(hairdresser_id=None)
        )
        assert result.hairdresser_id is None
        assert len(appts.created) == 1

    def test_adjacent_booked_slot_does_not_block(self) -> None:
        # [10:00, 11:00) adjacent à [09:00, 10:00) → pas de chevauchement : réservation OK.
        adjacent = SlotRange(
            date=_DATE, start=datetime.time(10, 0), end=datetime.time(11, 0)
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, _HAIRDRESSER_ID, _DATE): [adjacent]}
        )
        catalog = _bookable_catalog()
        result = self._uc(catalog, appts).execute(_SALON_ID, _CLIENT_ID, _valid_command())
        assert result.start_time == datetime.time(9, 0)
        assert result.end_time == datetime.time(10, 0)

    def test_inactive_service_raises_service_not_found(self) -> None:
        # Une prestation désactivée est indiscernable d'une inexistante (§11.2).
        catalog = _bookable_catalog(services=[_make_service(is_active=False)])
        with pytest.raises(ServiceNotFound):
            self._uc(catalog).execute(_SALON_ID, _CLIENT_ID, _valid_command())


# ---------------------------------------------------------------------------
# CheckAvailability — cas supplémentaires
# ---------------------------------------------------------------------------


class TestCheckAvailabilityExtra:
    def _uc(
        self,
        catalog: FakeSalonCatalogRepository,
        appts: FakeAppointmentRepository | None = None,
    ) -> CheckAvailability:
        return CheckAvailability(catalog, appts or FakeAppointmentRepository())

    def test_availability_without_hairdresser_returns_slots(self) -> None:
        # hairdresser_id=None : le moteur interroge les créneaux sans coiffeur assigné.
        catalog = _bookable_catalog()
        result = self._uc(catalog).execute(_SALON_ID, _DATE, _SERVICE_ID, None)
        assert isinstance(result, tuple)
        assert len(result) > 0

    def test_booked_slot_without_hairdresser_excluded(self) -> None:
        # Un créneau réservé sans coiffeur doit être exclu de la disponibilité sans coiffeur.
        booked_slot = SlotRange(
            date=_DATE, start=datetime.time(9, 0), end=datetime.time(10, 0)
        )
        appts = FakeAppointmentRepository(
            booked={(_SALON_ID, None, _DATE): [booked_slot]}
        )
        catalog = _bookable_catalog()
        result = CheckAvailability(catalog, appts).execute(
            _SALON_ID, _DATE, _SERVICE_ID, None
        )
        from coiflink_api.domain.availability import overlaps

        for slot in result:
            assert not overlaps(slot, booked_slot)
