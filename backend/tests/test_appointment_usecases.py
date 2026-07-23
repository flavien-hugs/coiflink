"""Tests unitaires — cas d'usage `CheckAvailability`, `BookAppointment`,
`ModifyAppointment` et `ListMyAppointments` (US-3.7, #21 / US-3.2, #23).

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
- `ModifyAppointment` (#23) : RDV non possédé → `AppointmentNotFound` ; RDV terminé →
  `AppointmentNotModifiable` ; salon non réservable → `SalonNotBookable` ; prestation
  inactive → `ServiceNotFound` ; créneau hors offre → `SlotUnavailable` ; course
  perdue → `SlotAlreadyBooked` (rien persisté) ; modification valide → `Appointment`
  retourné ; `exclude_appointment_id` passé à `booked_slots` ; entrée d'audit neutre
  (`APPOINTMENT_UPDATED`, noms de champs uniquement) dans la même unité de travail.
- `ListMyAppointments` (#23) : liste filtrée par `client_id` et `statuses`.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.application.appointments import (
    AssignHairdresser,
    BookAppointment,
    BookingCommand,
    CancelAppointment,
    CheckAvailability,
    ListMyAppointments,
    ModifyAppointment,
    ModifyAppointmentCommand,
    SetAppointmentStatus,
)
from coiflink_api.domain.appointment import Appointment, BookedService
from coiflink_api.domain.audit import AuditAction, ENTITY_TYPE_APPOINTMENT
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    AppointmentNotCancellable,
    AppointmentNotFound,
    AppointmentNotModifiable,
    HairdresserNotInSalon,
    InvalidAppointmentTransition,
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
    FakeAuditLog,
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


# ---------------------------------------------------------------------------
# ModifyAppointment (US-3.2, #23)
# ---------------------------------------------------------------------------

_APPT_ID = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_APPT_ID_2 = uuid.UUID("aaaaaa00-0000-0000-0000-000000000002")
_OTHER_CLIENT_ID = uuid.UUID("99999999-0000-0000-0000-000000000099")
_MANAGER_ID = uuid.UUID("55555555-0000-0000-0000-000000000005")
_CREATED_AT_DT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _make_appointment_entity(
    *,
    appt_id: uuid.UUID = _APPT_ID,
    client_id: uuid.UUID = _CLIENT_ID,
    status: str = "PENDING",
    date: datetime.date = _DATE,
    start_time: datetime.time = datetime.time(9, 0),
    end_time: datetime.time = datetime.time(10, 0),
    hairdresser_id: uuid.UUID | None = _HAIRDRESSER_ID,
    client_note: str | None = None,
) -> Appointment:
    """Crée une entité `Appointment` pré-chargée pour les tests de modification."""
    return Appointment(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=client_id,
        hairdresser_id=hairdresser_id,
        date=date,
        start_time=start_time,
        end_time=end_time,
        status=status,
        client_note=client_note,
        created_at=_CREATED_AT_DT,
        services=(
            BookedService(service_id=_SERVICE_ID, price_at_booking=decimal.Decimal("5000.00")),
        ),
    )


def _valid_modify_command(
    *,
    service_ids: tuple[uuid.UUID, ...] = (_SERVICE_ID,),
    start_time: datetime.time = datetime.time(9, 0),
    client_note: str | None = None,
) -> ModifyAppointmentCommand:
    return ModifyAppointmentCommand(
        date=_DATE,
        start_time=start_time,
        service_ids=service_ids,
        hairdresser_id=_HAIRDRESSER_ID,
        client_note=client_note,
        granularity_minutes=15,
    )


class TestModifyAppointment:
    def _uc(
        self,
        catalog: FakeSalonCatalogRepository | None = None,
        appts: FakeAppointmentRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
        audit_log: FakeAuditLog | None = None,
    ) -> ModifyAppointment:
        return ModifyAppointment(
            catalog if catalog is not None else _bookable_catalog(),
            appts if appts is not None else FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
            audit_log if audit_log is not None else FakeAuditLog(),
        )

    # --- Propriété / appartenance ----------------------------------------

    def test_not_owned_raises_appointment_not_found(self) -> None:
        # RDV existe mais appartient à un autre client : indiscernable d'un RDV inexistant.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(
                _APPT_ID, _OTHER_CLIENT_ID, _valid_modify_command()
            )

    def test_unknown_appointment_id_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository()  # aucun RDV pré-chargé
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )

    def test_not_owned_nothing_updated(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(
                _APPT_ID, _OTHER_CLIENT_ID, _valid_modify_command()
            )
        assert appts.updated == []

    def test_not_owned_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        audit = FakeAuditLog()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, audit_log=audit).execute(
                _APPT_ID, _OTHER_CLIENT_ID, _valid_modify_command()
            )
        assert audit.recorded == []

    # --- Verrou d'état (§8.1) --------------------------------------------

    def test_completed_appointment_raises_not_modifiable(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        with pytest.raises(AppointmentNotModifiable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, _valid_modify_command())

    def test_cancelled_appointment_raises_not_modifiable(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        with pytest.raises(AppointmentNotModifiable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, _valid_modify_command())

    def test_no_show_appointment_raises_not_modifiable(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="NO_SHOW")]
        )
        with pytest.raises(AppointmentNotModifiable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, _valid_modify_command())

    def test_terminated_nothing_updated(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        with pytest.raises(AppointmentNotModifiable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, _valid_modify_command())
        assert appts.updated == []

    def test_terminated_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        audit = FakeAuditLog()
        with pytest.raises(AppointmentNotModifiable):
            self._uc(appts=appts, audit_log=audit).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )
        assert audit.recorded == []

    # --- Validation du salon / prestation / coiffeur ----------------------

    def test_salon_not_bookable_raises_error(self) -> None:
        catalog = _bookable_catalog(salon=_make_salon(opening_hours=None))
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        with pytest.raises(SalonNotBookable):
            self._uc(catalog=catalog, appts=appts).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )

    def test_service_not_found_raises_error(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        cmd = _valid_modify_command(service_ids=(_OTHER_SERVICE_ID,))
        with pytest.raises(ServiceNotFound):
            self._uc(catalog=catalog, appts=appts).execute(_APPT_ID, _CLIENT_ID, cmd)

    def test_slot_outside_hours_raises_slot_unavailable(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        cmd = _valid_modify_command(start_time=datetime.time(23, 0))
        with pytest.raises(SlotUnavailable):
            self._uc(catalog=catalog, appts=appts).execute(_APPT_ID, _CLIENT_ID, cmd)

    def test_hairdresser_not_in_salon_raises_error(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        scope = _scope({_HAIRDRESSER_ID: frozenset({other_salon})})
        with pytest.raises(HairdresserNotInSalon):
            self._uc(catalog=catalog, appts=appts, scope=scope).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )

    # --- Course concurrente (contrainte d'exclusion base sur UPDATE) --------

    def test_race_condition_raises_slot_already_booked(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()],
            raise_conflict=True,
        )
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog=catalog, appts=appts).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )

    def test_race_condition_nothing_persisted(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()],
            raise_conflict=True,
        )
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog=catalog, appts=appts).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )
        assert appts.updated == []

    # --- Cas valide : re-planification réussie ----------------------------

    def test_valid_modification_returns_appointment(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        result = self._uc(catalog=catalog, appts=appts).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert isinstance(result, Appointment)

    def test_valid_modification_updates_repository(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        self._uc(catalog=catalog, appts=appts).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert len(appts.updated) == 1
        assert appts.updated[0][0] == _APPT_ID

    def test_client_id_from_argument_not_command(self) -> None:
        # `client_id` vient de l'argument `execute`, jamais d'une propriété du command.
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        result = self._uc(catalog=catalog, appts=appts).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert result.client_id == _CLIENT_ID

    def test_salon_id_from_loaded_appointment(self) -> None:
        # `salon_id` vient du RDV chargé, jamais du command (route d'appartenance).
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        result = self._uc(catalog=catalog, appts=appts).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert result.salon_id == _SALON_ID

    # --- Exclusion du RDV lui-même du calcul de disponibilité (#23) ------

    def test_booked_slots_called_with_exclude_appointment_id(self) -> None:
        # L'appel à `booked_slots` doit passer `exclude_appointment_id=appointment_id` :
        # sans cela, le propre créneau du RDV apparaîtrait occupé (faux rejet).
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        self._uc(catalog=catalog, appts=appts).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert any(
            call.get("exclude_appointment_id") == _APPT_ID
            for call in appts.booked_slots_calls
        )

    # --- Journal d'audit §11.4 -------------------------------------------

    def test_audit_log_recorded_once(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert len(audit.recorded) == 1

    def test_audit_action_is_appointment_updated(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert audit.recorded[0].action == AuditAction.APPOINTMENT_UPDATED.value

    def test_audit_actor_is_client_id(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert audit.recorded[0].actor_user_id == _CLIENT_ID

    def test_audit_entity_type_is_appointment(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert audit.recorded[0].entity_type == ENTITY_TYPE_APPOINTMENT

    def test_audit_entity_id_is_appointment_id(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert audit.recorded[0].entity_id == _APPT_ID

    def test_audit_salon_id_from_appointment(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert audit.recorded[0].salon_id == _SALON_ID

    def test_audit_metadata_changed_contains_field_names_only(self) -> None:
        # §11.4 diff neutre : `metadata.changed` porte des **noms** de champs, jamais des valeurs.
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_note="Ancienne note")]
        )
        audit = FakeAuditLog()
        cmd = _valid_modify_command(client_note="Nouvelle note")
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, cmd
        )
        changed = audit.recorded[0].metadata["changed"]
        assert "client_note" in changed
        # Les valeurs (texte de la note) ne doivent pas apparaître dans les noms.
        for field_name in changed:
            assert isinstance(field_name, str)
            assert "Ancienne" not in field_name
            assert "Nouvelle" not in field_name

    def test_audit_metadata_no_change_if_nothing_changed(self) -> None:
        # Si aucune valeur ne change, `metadata.changed` est vide.
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_note=None)]
        )
        audit = FakeAuditLog()
        # Même date/start_time/hairdresser_id/client_note, même prestation.
        cmd = _valid_modify_command(client_note=None)
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, cmd
        )
        changed = audit.recorded[0].metadata["changed"]
        assert "date" not in changed
        assert "start_time" not in changed
        assert "hairdresser_id" not in changed
        assert "client_note" not in changed

    def test_audit_metadata_services_listed_when_changed(self) -> None:
        catalog = _bookable_catalog(
            services=[_make_service(), _make_service(service_id=_OTHER_SERVICE_ID)]
        )
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        # Changer les service_ids → "services" doit apparaître dans changed.
        cmd = _valid_modify_command(service_ids=(_OTHER_SERVICE_ID,))
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, cmd
        )
        changed = audit.recorded[0].metadata["changed"]
        assert "services" in changed

    def test_audit_metadata_values_never_include_prices(self) -> None:
        # Les valeurs de prix ne doivent jamais figurer dans le diff d'audit.
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(catalog=catalog, appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        changed = audit.recorded[0].metadata["changed"]
        for name in changed:
            assert "5000" not in name
            assert "price" not in name.lower()

    # --- TOCTOU guard : update conditionnel sur statut --------------------

    def test_toctou_guard_raises_not_modifiable(self) -> None:
        # Simule un changement de statut concurrent entre la lecture et l'écriture.
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()],
            raise_not_modifiable=True,
        )
        with pytest.raises(AppointmentNotModifiable):
            self._uc(catalog=catalog, appts=appts).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )


# ---------------------------------------------------------------------------
# ListMyAppointments (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestListMyAppointments:
    def _uc(self, appts: FakeAppointmentRepository) -> ListMyAppointments:
        return ListMyAppointments(appts)

    def test_returns_only_client_appointments(self) -> None:
        own = _make_appointment_entity(appt_id=_APPT_ID, client_id=_CLIENT_ID)
        other = _make_appointment_entity(appt_id=_APPT_ID_2, client_id=_OTHER_CLIENT_ID)
        appts = FakeAppointmentRepository(appointments=[own, other])
        result = self._uc(appts).execute(_CLIENT_ID)
        assert len(result) == 1
        assert result[0].client_id == _CLIENT_ID

    def test_empty_repo_returns_empty_tuple(self) -> None:
        appts = FakeAppointmentRepository()
        result = self._uc(appts).execute(_CLIENT_ID)
        assert result == ()

    def test_filters_by_statuses_pending_only(self) -> None:
        pending = _make_appointment_entity(appt_id=_APPT_ID, status="PENDING")
        completed = _make_appointment_entity(appt_id=_APPT_ID_2, status="COMPLETED")
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        result = self._uc(appts).execute(_CLIENT_ID, statuses=("PENDING",))
        assert len(result) == 1
        assert result[0].status == "PENDING"

    def test_no_statuses_filter_returns_all_own(self) -> None:
        pending = _make_appointment_entity(appt_id=_APPT_ID, status="PENDING")
        completed = _make_appointment_entity(appt_id=_APPT_ID_2, status="COMPLETED")
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        result = self._uc(appts).execute(_CLIENT_ID, statuses=None)
        assert len(result) == 2

    def test_no_own_appointments_returns_empty(self) -> None:
        other = _make_appointment_entity(appt_id=_APPT_ID, client_id=_OTHER_CLIENT_ID)
        appts = FakeAppointmentRepository(appointments=[other])
        result = self._uc(appts).execute(_CLIENT_ID)
        assert result == ()


# ---------------------------------------------------------------------------
# CancelAppointment (US-3.3, #24)
# ---------------------------------------------------------------------------


class TestCancelAppointment:
    """Cas d'usage d'annulation : ownership → verrou d'état → cancel → audit."""

    def _uc(
        self,
        appts: FakeAppointmentRepository | None = None,
        audit_log: FakeAuditLog | None = None,
    ) -> CancelAppointment:
        return CancelAppointment(
            appts if appts is not None else FakeAppointmentRepository(),
            audit_log if audit_log is not None else FakeAuditLog(),
        )

    # --- Propriété / appartenance ------------------------------------------

    def test_not_owned_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, _OTHER_CLIENT_ID)

    def test_unknown_appointment_id_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)

    def test_not_owned_nothing_cancelled(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, _OTHER_CLIENT_ID)
        assert appts.cancelled == []

    def test_not_owned_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        audit = FakeAuditLog()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _OTHER_CLIENT_ID)
        assert audit.recorded == []

    # --- Verrou d'état (§8.1) ---------------------------------------------

    def test_completed_appointment_raises_not_cancellable(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)

    def test_cancelled_appointment_raises_not_cancellable(self) -> None:
        # Double annulation → 409 : une annulation est terminale (pas d'idempotence).
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)

    def test_no_show_appointment_raises_not_cancellable(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="NO_SHOW")]
        )
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)

    def test_terminated_nothing_cancelled(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)
        assert appts.cancelled == []

    def test_terminated_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        audit = FakeAuditLog()
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded == []

    # --- Annulation valide ------------------------------------------------

    def test_pending_appointment_cancelled_successfully(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        result = self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)
        assert result.status == "CANCELLED"

    def test_confirmed_appointment_cancelled_successfully(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        result = self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)
        assert result.status == "CANCELLED"

    def test_cancel_recorded_in_repository(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()]
        )
        self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)
        assert len(appts.cancelled) == 1
        assert appts.cancelled[0][0] == _APPT_ID

    def test_reason_transmitted_to_repository(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()]
        )
        self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, reason="Empêchement.")
        assert appts.cancelled[0][1] == "Empêchement."

    def test_reason_none_transmitted_as_none(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()]
        )
        self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, reason=None)
        assert appts.cancelled[0][1] is None

    def test_whitespace_reason_normalized_to_none(self) -> None:
        # `normalize_cancellation_reason` trime + vide → None avant d'appeler cancel.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()]
        )
        self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, reason="   ")
        assert appts.cancelled[0][1] is None

    def test_reason_trimmed_before_transmission(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()]
        )
        self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID, reason="  motif  ")
        assert appts.cancelled[0][1] == "motif"

    # --- Journal d'audit §11.4 -------------------------------------------

    def test_audit_log_recorded_once(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert len(audit.recorded) == 1

    def test_audit_action_is_appointment_cancelled(self) -> None:
        from coiflink_api.domain.audit import AuditAction

        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded[0].action == AuditAction.APPOINTMENT_CANCELLED.value

    def test_audit_actor_is_client_id(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded[0].actor_user_id == _CLIENT_ID

    def test_audit_entity_type_is_appointment(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded[0].entity_type == ENTITY_TYPE_APPOINTMENT

    def test_audit_entity_id_is_appointment_id(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded[0].entity_id == _APPT_ID

    def test_audit_salon_id_from_appointment(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded[0].salon_id == _SALON_ID

    def test_audit_metadata_reason_not_present(self) -> None:
        # §11.3 : le texte du motif ne doit jamais figurer dans les métadonnées d'audit.
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, reason="Motif confidentiel"
        )
        metadata = audit.recorded[0].metadata
        for value in metadata.values():
            assert "Motif confidentiel" not in str(value)

    def test_audit_metadata_reason_provided_true_when_reason_given(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _CLIENT_ID, reason="motif"
        )
        assert audit.recorded[0].metadata.get("reason_provided") is True

    def test_audit_metadata_reason_provided_false_when_no_reason(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(_APPT_ID, _CLIENT_ID)
        assert audit.recorded[0].metadata.get("reason_provided") is False

    # --- Garde TOCTOU : UPDATE conditionnel sur statut ---------------------

    def test_toctou_guard_raises_not_cancellable(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()],
            raise_not_cancellable=True,
        )
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts).execute(_APPT_ID, _CLIENT_ID)


# ---------------------------------------------------------------------------
# SetAppointmentStatus (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestSetAppointmentStatus:
    """Cycle de statuts gérant : portée → machine à états → TOCTOU → audit (§11.4, #25)."""

    def _uc(
        self,
        appts: FakeAppointmentRepository | None = None,
        audit_log: FakeAuditLog | None = None,
    ) -> SetAppointmentStatus:
        return SetAppointmentStatus(
            appts if appts is not None else FakeAppointmentRepository(),
            audit_log if audit_log is not None else FakeAuditLog(),
        )

    # --- RDV introuvable / hors salon (§11.2) --------------------------------

    def test_unknown_appointment_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")

    def test_appointment_in_other_salon_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(appt_id=_APPT_ID)]
        )
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, other_salon, _MANAGER_ID, "CONFIRMED")

    def test_not_found_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository()
        audit = FakeAuditLog()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, audit_log=audit).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
            )
        assert audit.recorded == []

    # --- Machine à états : transitions invalides -----------------------------

    def test_terminal_status_raises_invalid_appointment_transition(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")

    def test_identity_transition_raises_invalid_appointment_transition(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "PENDING")

    def test_forbidden_transition_raises_invalid_appointment_transition(self) -> None:
        # PENDING → COMPLETED n'est pas dans la table (PENDING → CONFIRMED → COMPLETED).
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "COMPLETED")

    def test_invalid_transition_nothing_persisted(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")
        assert appts.status_changes == []

    def test_invalid_transition_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        audit = FakeAuditLog()
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts, audit_log=audit).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
            )
        assert audit.recorded == []

    # --- Garde TOCTOU (§8.1) -----------------------------------------------

    def test_toctou_guard_raises_invalid_appointment_transition(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")],
            raise_invalid_transition=True,
        )
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")

    # --- Transitions valides -------------------------------------------------

    def test_pending_to_confirmed_returns_appointment(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        result = self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")
        assert isinstance(result, Appointment)

    def test_valid_transition_recorded_in_repository(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")
        assert len(appts.status_changes) == 1
        appt_id, from_status, to_status, _reason = appts.status_changes[0]
        assert appt_id == _APPT_ID
        assert from_status == "PENDING"
        assert to_status == "CONFIRMED"

    def test_valid_transition_updates_status(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        result = self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED")
        assert result.status == "CONFIRMED"

    def test_confirmed_to_completed_valid(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        result = self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, "COMPLETED")
        assert result.status == "COMPLETED"

    # --- Motif d'annulation (§11.3) ----------------------------------------

    def test_reason_transmitted_for_cancelled_transition(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED", reason="Fermé ce jour."
        )
        assert appts.status_changes[0][3] == "Fermé ce jour."

    def test_reason_not_transmitted_for_non_cancelled_transition(self) -> None:
        # Pour une transition autre que → CANCELLED, le motif n'est pas transmis.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED", reason="info non pertinente"
        )
        assert appts.status_changes[0][3] is None

    def test_whitespace_reason_normalized_to_none_on_cancelled(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED", reason="   "
        )
        assert appts.status_changes[0][3] is None

    def test_reason_trimmed_on_cancelled(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED", reason="  motif  "
        )
        assert appts.status_changes[0][3] == "motif"

    # --- Journal d'audit §11.4 -------------------------------------------

    def test_audit_log_recorded_once(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert len(audit.recorded) == 1

    def test_audit_action_is_appointment_status_changed(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].action == AuditAction.APPOINTMENT_STATUS_CHANGED.value

    def test_audit_actor_is_manager_id(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].actor_user_id == _MANAGER_ID

    def test_audit_entity_type_is_appointment(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].entity_type == ENTITY_TYPE_APPOINTMENT

    def test_audit_entity_id_is_appointment_id(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].entity_id == _APPT_ID

    def test_audit_salon_id_from_execution(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].salon_id == _SALON_ID

    def test_audit_metadata_from_is_previous_status(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].metadata["from"] == "PENDING"

    def test_audit_metadata_to_is_target_status(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert audit.recorded[0].metadata["to"] == "CONFIRMED"

    def test_audit_metadata_never_contains_reason_text(self) -> None:
        # §11.3 : le texte du motif ne doit jamais figurer dans le journal d'audit.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED", reason="Motif confidentiel"
        )
        metadata = audit.recorded[0].metadata
        for value in metadata.values():
            assert "Motif confidentiel" not in str(value)


# ---------------------------------------------------------------------------
# AssignHairdresser (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestAssignHairdresser:
    """Assignation coiffeur : portée → appartenance → TOCTOU → audit (§11.4, #25)."""

    def _uc(
        self,
        appts: FakeAppointmentRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
        audit_log: FakeAuditLog | None = None,
    ) -> AssignHairdresser:
        sc = scope if scope is not None else _scope()
        return AssignHairdresser(
            appts if appts is not None else FakeAppointmentRepository(),
            sc,
            audit_log if audit_log is not None else FakeAuditLog(),
        )

    # --- RDV introuvable / hors salon (§11.2) --------------------------------

    def test_unknown_appointment_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID)

    def test_appointment_in_other_salon_raises_appointment_not_found(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(appt_id=_APPT_ID)]
        )
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts).execute(_APPT_ID, other_salon, _MANAGER_ID, _HAIRDRESSER_ID)

    def test_not_found_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository()
        audit = FakeAuditLog()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, audit_log=audit).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
            )
        assert audit.recorded == []

    # --- Appartenance du coiffeur au salon (§11.2) -------------------------

    def test_hairdresser_not_in_salon_raises_error(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        scope = _scope({_HAIRDRESSER_ID: frozenset({other_salon})})
        with pytest.raises(HairdresserNotInSalon):
            self._uc(appts=appts, scope=scope).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
            )

    def test_unknown_hairdresser_raises_not_in_salon(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        with pytest.raises(HairdresserNotInSalon):
            self._uc(appts=appts, scope=_scope({})).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
            )

    def test_deassign_skips_membership_check(self) -> None:
        # hairdresser_id=None → la vérification de portée ne doit pas être sollicitée.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        scope = _scope({})  # portée vide → HairdresserNotInSalon si sollicitée
        self._uc(appts=appts, scope=scope).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, None)
        assert scope.calls == []

    # --- Verrou d'état : RDV terminal (CLIENT_MODIFIABLE_STATUSES) ----------

    def test_terminal_appointment_raises_invalid_appointment_transition(self) -> None:
        # assign_hairdresser refuse les RDV hors CLIENT_MODIFIABLE_STATUSES.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, None)

    # --- Conflit d'agenda (exclusion base) ---------------------------------

    def test_slot_conflict_raises_slot_already_booked(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")],
            raise_conflict=True,
        )
        with pytest.raises(SlotAlreadyBooked):
            self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID)

    def test_slot_conflict_nothing_audited(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")],
            raise_conflict=True,
        )
        audit = FakeAuditLog()
        with pytest.raises(SlotAlreadyBooked):
            self._uc(appts=appts, audit_log=audit).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
            )
        assert audit.recorded == []

    # --- Assignation valide -----------------------------------------------

    def test_valid_assignment_recorded_in_repository(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID)
        assert len(appts.assignments) == 1
        assert appts.assignments[0] == (_APPT_ID, _HAIRDRESSER_ID)

    def test_valid_deassignment_recorded_in_repository(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        self._uc(appts=appts).execute(_APPT_ID, _SALON_ID, _MANAGER_ID, None)
        assert len(appts.assignments) == 1
        assert appts.assignments[0] == (_APPT_ID, None)

    def test_assignment_returns_updated_appointment(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING", hairdresser_id=None)]
        )
        result = self._uc(appts=appts).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert result.hairdresser_id == _HAIRDRESSER_ID

    # --- Journal d'audit §11.4 -------------------------------------------

    def test_audit_log_recorded_once(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert len(audit.recorded) == 1

    def test_audit_action_is_hairdresser_assigned(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].action == AuditAction.APPOINTMENT_HAIRDRESSER_ASSIGNED.value

    def test_audit_actor_is_manager_id(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].actor_user_id == _MANAGER_ID

    def test_audit_entity_type_is_appointment(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].entity_type == ENTITY_TYPE_APPOINTMENT

    def test_audit_entity_id_is_appointment_id(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].entity_id == _APPT_ID

    def test_audit_salon_id_from_execution(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].salon_id == _SALON_ID

    def test_audit_metadata_changed_contains_hairdresser_id_field(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].metadata["changed"] == ["hairdresser_id"]

    def test_audit_metadata_assigned_true_when_hairdresser_set(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        assert audit.recorded[0].metadata["assigned"] is True

    def test_audit_metadata_assigned_false_when_deassigning(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, None
        )
        assert audit.recorded[0].metadata["assigned"] is False

    def test_audit_metadata_never_contains_hairdresser_uuid(self) -> None:
        # §11.4 : l'UUID du coiffeur (opaque) ne doit jamais figurer dans le journal.
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        audit = FakeAuditLog()
        self._uc(appts=appts, audit_log=audit).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, _HAIRDRESSER_ID
        )
        metadata = audit.recorded[0].metadata
        for value in metadata.values():
            assert str(_HAIRDRESSER_ID) not in str(value)
