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
    ListAssignedAppointments,
    ListMyAppointments,
    ListSalonAppointments,
    ModifyAppointment,
    ModifyAppointmentCommand,
    SetAppointmentStatus,
    SummarizeDailyAppointments,
)
from coiflink_api.domain.appointment import Appointment, BookedService
from coiflink_api.domain.audit import AuditAction, ENTITY_TYPE_APPOINTMENT
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    Role,
)
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
    FakeNotificationRepository,
    FakeSalonCatalogRepository,
    FakeSalonRepository,
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
_OWNER_ID = uuid.UUID("66666666-0000-0000-0000-000000000006")
_DATE = datetime.date(2026, 8, 3)  # lundi
_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

_OPENING_HOURS_DICT = to_jsonb(
    parse_opening_hours({"weekly": {"mon": [{"start": "09:00", "end": "17:00"}]}})
)


def _make_salon(
    *,
    status: str = "ACTIVE",
    opening_hours: dict | None = _OPENING_HOURS_DICT,
    owner_id: uuid.UUID = _OWNER_ID,
) -> Salon:
    return Salon(
        id=_SALON_ID,
        owner_id=owner_id,
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


def _salon_repository_with_owner(
    *, salon_id: uuid.UUID = _SALON_ID, owner_id: uuid.UUID = _OWNER_ID
) -> FakeSalonRepository:
    """`FakeSalonRepository` pré-alimenté : `find_by_id(salon_id)` renvoie un salon
    dont l'`owner_id` est connu (US-7.4, #48 — notification d'annulation au salon)."""
    repo = FakeSalonRepository()
    repo._salons[salon_id] = _make_salon(owner_id=owner_id)
    return repo


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
        notifications: FakeNotificationRepository | None = None,
    ) -> BookAppointment:
        return BookAppointment(
            catalog,
            appts or FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
            notifications or FakeNotificationRepository(),
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
            BookAppointment(
                catalog,
                FakeAppointmentRepository(),
                _scope(),
                FakeNotificationRepository(),
            ).execute(_SALON_ID, _CLIENT_ID, cmd, now=now)

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
# BookAppointment — notification de confirmation (US-7.1, #45)
# ---------------------------------------------------------------------------


class TestBookAppointmentNotification:
    """Vérifie qu'une confirmation est émise (tracée) à la réservation et jamais
    en cas d'échec — invariant d'atomicité (§8.4/§11.4, ADR-0006)."""

    def _uc(
        self,
        catalog: FakeSalonCatalogRepository,
        appts: FakeAppointmentRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
        notifications: FakeNotificationRepository | None = None,
    ) -> BookAppointment:
        return BookAppointment(
            catalog,
            appts or FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
            notifications or FakeNotificationRepository(),
        )

    # --- Émission sur réservation valide -----------------------------------

    def test_valid_booking_enqueues_confirmation_plus_reminders(self) -> None:
        # Sans `now` explicite, `BookAppointment` traite l'absence de référence
        # temporelle comme « aucun filtrage par le passé » (parité `is_offered`) :
        # les 3 rappels (`REMINDER_OFFSETS`) sont donc tous planifiés, en plus de
        # la confirmation (#45) et de la notification au salon (#47) — soit 5
        # notifications au total.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert len(notifs.enqueued) == 5

    def test_valid_booking_enqueues_exactly_one_confirmation(self) -> None:
        from coiflink_api.domain.enums import NotificationType

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        confirmations = [
            n for n in notifs.enqueued if n.type == NotificationType.CONFIRMATION.value
        ]
        assert len(confirmations) == 1

    def test_notification_type_is_confirmation(self) -> None:
        from coiflink_api.domain.enums import NotificationType

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].type == NotificationType.CONFIRMATION.value

    def test_notification_status_is_pending(self) -> None:
        from coiflink_api.domain.enums import NotificationStatus

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].status == NotificationStatus.PENDING.value

    def test_notification_user_id_is_client_id(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].user_id == _CLIENT_ID

    def test_notification_salon_id_is_correct(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].salon_id == _SALON_ID

    def test_notification_appointment_id_matches_created_appointment(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        notifs = FakeNotificationRepository()
        result = self._uc(catalog, appts, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        # La notification est rattachée au RDV créé, pas à un ID arbitraire.
        assert notifs.enqueued[0].appointment_id == result.id

    def test_notification_channel_is_sms_at_mvp(self) -> None:
        # Au MVP, faute de registre de jetons d'appareil, `has_push_token` est
        # toujours faux → canal effectif = SMS (client inscrit par téléphone #8).
        from coiflink_api.domain.enums import NotificationChannel

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].channel == NotificationChannel.SMS.value

    def test_notification_title_is_templated(self) -> None:
        from coiflink_api.domain.notification import CONFIRMATION_TITLE

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].title == CONFIRMATION_TITLE

    def test_notification_message_is_templated(self) -> None:
        from coiflink_api.domain.notification import CONFIRMATION_MESSAGE

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[0].message == CONFIRMATION_MESSAGE

    # --- Absence de PII dans la notification (§11.3) -----------------------

    def test_notification_title_contains_no_phone_number(self) -> None:
        # Le titre ne doit pas inclure de numéro de téléphone (§11.3).
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        title = notifs.enqueued[0].title
        assert "+" not in title
        assert not any(c.isdigit() for c in title)

    def test_notification_message_contains_no_phone_number(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert "+" not in notifs.enqueued[0].message

    def test_notification_carries_no_price_value(self) -> None:
        # Le prix figé à la réservation ne doit pas fuiter dans la notification.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        n = notifs.enqueued[0]
        for text_field in (n.title, n.message):
            assert "5000" not in text_field

    # --- Atomicité : pas de notification sur échec (§8.4) ------------------

    def test_race_condition_no_notification_enqueued(self) -> None:
        # Course concurrente (INSERT conflit) → rollback complet : RDV + notification.
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(raise_conflict=True)
        notifs = FakeNotificationRepository()
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog, appts, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert notifs.enqueued == []

    def test_slot_unavailable_no_notification_enqueued(self) -> None:
        # Le créneau hors offre est rejeté *avant* l'INSERT : aucune notification.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        cmd = _valid_command(start_time=datetime.time(23, 0))
        with pytest.raises(SlotUnavailable):
            self._uc(catalog, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, cmd
            )
        assert notifs.enqueued == []

    def test_unknown_service_no_notification_enqueued(self) -> None:
        # Prestation inconnue → erreur avant le RDV : aucune notification.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        cmd = _valid_command(service_ids=(_OTHER_SERVICE_ID,))
        with pytest.raises(ServiceNotFound):
            self._uc(catalog, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, cmd
            )
        assert notifs.enqueued == []

    def test_unknown_salon_no_notification_enqueued(self) -> None:
        catalog = FakeSalonCatalogRepository()
        notifs = FakeNotificationRepository()
        with pytest.raises(SalonNotFound):
            self._uc(catalog, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert notifs.enqueued == []

    def test_hairdresser_not_in_salon_no_notification_enqueued(self) -> None:
        catalog = _bookable_catalog()
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        scope = _scope({_HAIRDRESSER_ID: frozenset({other_salon})})
        notifs = FakeNotificationRepository()
        with pytest.raises(HairdresserNotInSalon):
            self._uc(catalog, scope=scope, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert notifs.enqueued == []


# ---------------------------------------------------------------------------
# BookAppointment — rappels planifiés (US-7.2, #46)
# ---------------------------------------------------------------------------


class TestBookAppointmentReminder:
    """Vérifie que des rappels `REMINDER` sont planifiés à la réservation, un par
    échéance encore future, et **aucun** en cas d'échec (§8.4, atomicité)."""

    _APPOINTMENT_START = datetime.datetime(2026, 8, 3, 9, 0)  # _DATE + 09:00

    def _uc(
        self,
        catalog: FakeSalonCatalogRepository,
        appts: FakeAppointmentRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
        notifications: FakeNotificationRepository | None = None,
    ) -> BookAppointment:
        return BookAppointment(
            catalog,
            appts or FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
            notifications or FakeNotificationRepository(),
        )

    def _reminders(self, notifs: FakeNotificationRepository) -> list:
        from coiflink_api.domain.enums import NotificationType

        return [n for n in notifs.enqueued if n.type == NotificationType.REMINDER.value]

    def test_far_future_booking_plans_three_reminders(self) -> None:
        # RDV réservé bien plus de 24h à l'avance : les 3 offsets sont futurs.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(days=2)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        assert len(self._reminders(notifs)) == 3

    def test_reminder_status_is_pending(self) -> None:
        from coiflink_api.domain.enums import NotificationStatus

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(days=2)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        assert all(
            r.status == NotificationStatus.PENDING.value for r in self._reminders(notifs)
        )

    def test_reminder_scheduled_for_matches_offsets(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(days=2)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        due_dates = sorted(r.scheduled_for for r in self._reminders(notifs))
        expected = sorted(
            [
                self._APPOINTMENT_START - datetime.timedelta(hours=24),
                self._APPOINTMENT_START - datetime.timedelta(hours=2),
                self._APPOINTMENT_START - datetime.timedelta(minutes=30),
            ]
        )
        assert due_dates == expected

    def test_reminder_linked_to_client_salon_and_appointment(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(days=2)
        result = self._uc(catalog, appts, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        for reminder in self._reminders(notifs):
            assert reminder.user_id == _CLIENT_ID
            assert reminder.salon_id == _SALON_ID
            assert reminder.appointment_id == result.id

    def test_reminder_channel_matches_confirmation_channel(self) -> None:
        from coiflink_api.domain.enums import NotificationChannel

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(days=2)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        assert all(
            r.channel == NotificationChannel.SMS.value for r in self._reminders(notifs)
        )

    def test_reminder_title_and_message_are_templated_no_pii(self) -> None:
        from coiflink_api.domain.notification import REMINDER_MESSAGE, REMINDER_TITLE

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(days=2)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        for reminder in self._reminders(notifs):
            assert reminder.title == REMINDER_TITLE
            assert reminder.message == REMINDER_MESSAGE
            assert "+" not in reminder.title
            assert "+" not in reminder.message

    def test_booking_close_to_slot_plans_fewer_reminders(self) -> None:
        # Réservé 90 min à l'avance : seul l'offset `30 min` est encore futur.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(minutes=90)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        reminders = self._reminders(notifs)
        assert len(reminders) == 1
        assert reminders[0].scheduled_for == self._APPOINTMENT_START - datetime.timedelta(
            minutes=30
        )

    def test_booking_immediately_before_slot_plans_no_reminder(self) -> None:
        # Réservé 10 min à l'avance : aucun offset (24h/2h/30min) n'est encore futur.
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        now = self._APPOINTMENT_START - datetime.timedelta(minutes=10)
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command(), now=now
        )
        assert self._reminders(notifs) == []
        # La confirmation (#45) et la notification au salon (#47) partent toujours,
        # indépendamment des échéances de rappel — soit 2 notifications.
        assert len(notifs.enqueued) == 2

    # --- Atomicité : pas de rappel sur échec (§8.4) -------------------------

    def test_race_condition_no_reminder_enqueued(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(raise_conflict=True)
        notifs = FakeNotificationRepository()
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog, appts, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert notifs.enqueued == []


# ---------------------------------------------------------------------------
# BookAppointment — notification au salon (US-7.3, #47)
# ---------------------------------------------------------------------------


class TestBookAppointmentSalonNotification:
    """Vérifie qu'une notification `NEW_BOOKING` est émise au gérant à la réservation
    et **jamais** en cas d'échec — invariant d'atomicité, canal `IN_APP`, ciblage
    `salon.owner_id` (§8.4/§11.4, ADR-0006)."""

    def _uc(
        self,
        catalog: FakeSalonCatalogRepository,
        appts: FakeAppointmentRepository | None = None,
        scope: FakeSalonScopeRepository | None = None,
        notifications: FakeNotificationRepository | None = None,
    ) -> BookAppointment:
        return BookAppointment(
            catalog,
            appts or FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
            notifications or FakeNotificationRepository(),
        )

    def _new_booking_notifs(self, notifs: FakeNotificationRepository) -> list:
        from coiflink_api.domain.enums import NotificationType

        return [n for n in notifs.enqueued if n.type == NotificationType.NEW_BOOKING.value]

    # --- Émission sur réservation valide ------------------------------------

    def test_valid_booking_emits_exactly_one_new_booking(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert len(self._new_booking_notifs(notifs)) == 1

    def test_new_booking_targets_owner_not_client(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.user_id == _OWNER_ID
        assert nb.user_id != _CLIENT_ID

    def test_new_booking_channel_is_in_app(self) -> None:
        from coiflink_api.domain.enums import NotificationChannel

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.channel == NotificationChannel.IN_APP.value

    def test_new_booking_channel_is_not_sms(self) -> None:
        # Le canal salon est `IN_APP` (dashboard), jamais SMS (§B de la spec).
        from coiflink_api.domain.enums import NotificationChannel

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.channel != NotificationChannel.SMS.value

    def test_new_booking_salon_id_is_correct(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.salon_id == _SALON_ID

    def test_new_booking_appointment_id_matches_created(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository()
        notifs = FakeNotificationRepository()
        result = self._uc(catalog, appts, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.appointment_id == result.id

    def test_new_booking_scheduled_for_is_none(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.scheduled_for is None

    def test_new_booking_status_is_pending(self) -> None:
        from coiflink_api.domain.enums import NotificationStatus

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.status == NotificationStatus.PENDING.value

    def test_new_booking_title_is_new_booking_template(self) -> None:
        from coiflink_api.domain.notification import NEW_BOOKING_TITLE

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.title == NEW_BOOKING_TITLE

    def test_new_booking_message_is_new_booking_template(self) -> None:
        from coiflink_api.domain.notification import NEW_BOOKING_MESSAGE

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.message == NEW_BOOKING_MESSAGE

    def test_new_booking_title_contains_no_phone_pii(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert "+" not in nb.title
        assert not any(c.isdigit() for c in nb.title)

    def test_new_booking_message_contains_no_phone_pii(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert "+" not in nb.message

    def test_new_booking_emitted_last_after_confirmation_and_reminders(self) -> None:
        # L'ordre dans `enqueued` : [CONFIRMATION, ...REMINDER..., NEW_BOOKING].
        # Le salon est notifié **après** le client (confirmation + rappels).
        from coiflink_api.domain.enums import NotificationType

        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        assert notifs.enqueued[-1].type == NotificationType.NEW_BOOKING.value
        assert notifs.enqueued[0].type == NotificationType.CONFIRMATION.value

    def test_new_booking_uses_owner_id_from_loaded_salon(self) -> None:
        # Un autre salon avec un autre gérant génère une notification ciblant ce gérant.
        other_owner = uuid.UUID("77777777-0000-0000-0000-000000000007")
        catalog = _bookable_catalog(salon=_make_salon(owner_id=other_owner))
        notifs = FakeNotificationRepository()
        self._uc(catalog, notifications=notifs).execute(
            _SALON_ID, _CLIENT_ID, _valid_command()
        )
        nb = self._new_booking_notifs(notifs)[0]
        assert nb.user_id == other_owner
        assert nb.user_id != _OWNER_ID

    # --- Atomicité : pas de notification salon sur échec --------------------

    def test_slot_unavailable_no_new_booking_enqueued(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        cmd = _valid_command(start_time=datetime.time(23, 0))
        with pytest.raises(SlotUnavailable):
            self._uc(catalog, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, cmd
            )
        assert self._new_booking_notifs(notifs) == []

    def test_race_condition_no_new_booking_enqueued(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(raise_conflict=True)
        notifs = FakeNotificationRepository()
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog, appts, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert self._new_booking_notifs(notifs) == []

    def test_unknown_service_no_new_booking_enqueued(self) -> None:
        catalog = _bookable_catalog()
        notifs = FakeNotificationRepository()
        cmd = _valid_command(service_ids=(_OTHER_SERVICE_ID,))
        with pytest.raises(ServiceNotFound):
            self._uc(catalog, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, cmd
            )
        assert self._new_booking_notifs(notifs) == []

    def test_unknown_salon_no_new_booking_enqueued(self) -> None:
        catalog = FakeSalonCatalogRepository()
        notifs = FakeNotificationRepository()
        with pytest.raises(SalonNotFound):
            self._uc(catalog, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert self._new_booking_notifs(notifs) == []

    def test_hairdresser_not_in_salon_no_new_booking_enqueued(self) -> None:
        catalog = _bookable_catalog()
        other_salon = uuid.UUID("99999999-0000-0000-0000-000000000099")
        scope = _scope({_HAIRDRESSER_ID: frozenset({other_salon})})
        notifs = FakeNotificationRepository()
        with pytest.raises(HairdresserNotInSalon):
            self._uc(catalog, scope=scope, notifications=notifs).execute(
                _SALON_ID, _CLIENT_ID, _valid_command()
            )
        assert self._new_booking_notifs(notifs) == []


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
        notifications: FakeNotificationRepository | None = None,
    ) -> ModifyAppointment:
        return ModifyAppointment(
            catalog if catalog is not None else _bookable_catalog(),
            appts if appts is not None else FakeAppointmentRepository(),
            scope if scope is not None else _scope(),
            audit_log if audit_log is not None else FakeAuditLog(),
            notifications if notifications is not None else FakeNotificationRepository(),
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

    # --- Rappels re-planifiés sur modification (US-7.2, #46) ----------------

    def test_modify_cancels_pending_reminders_exactly_once(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command(start_time=datetime.time(11, 0))
        )
        assert notifs.cancel_calls == [_APPT_ID]

    def test_modify_reschedules_reminders_to_new_slot(self) -> None:
        from coiflink_api.domain.enums import NotificationType

        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        now = datetime.datetime(2026, 8, 1, 0, 0)  # bien avant le nouveau créneau
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID,
            _CLIENT_ID,
            _valid_modify_command(start_time=datetime.time(11, 0)),
            now=now,
        )
        new_start = datetime.datetime(2026, 8, 3, 11, 0)
        reminders = [
            n for n in notifs.enqueued if n.type == NotificationType.REMINDER.value
        ]
        assert len(reminders) == 3
        assert sorted(r.scheduled_for for r in reminders) == sorted(
            new_start - offset
            for offset in (
                datetime.timedelta(hours=24),
                datetime.timedelta(hours=2),
                datetime.timedelta(minutes=30),
            )
        )

    def test_modify_close_to_new_slot_plans_fewer_reminders(self) -> None:
        from coiflink_api.domain.enums import NotificationType

        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        new_start = datetime.datetime(2026, 8, 3, 11, 0)
        now = new_start - datetime.timedelta(minutes=90)
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID,
            _CLIENT_ID,
            _valid_modify_command(start_time=datetime.time(11, 0)),
            now=now,
        )
        reminders = [
            n for n in notifs.enqueued if n.type == NotificationType.REMINDER.value
        ]
        assert len(reminders) == 1
        assert reminders[0].scheduled_for == new_start - datetime.timedelta(minutes=30)

    # --- Notification au salon de la modification (US-7.4, #48) -------------

    def test_modify_emits_one_appointment_update_to_salon(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        updates = [
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        ]
        assert len(updates) == 1
        assert updates[0].user_id == _OWNER_ID

    def test_modify_salon_notification_channel_is_in_app(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        update = next(
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        )
        assert update.channel == NotificationChannel.IN_APP.value

    def test_modify_notification_status_is_pending(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        update = next(
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        )
        assert update.status == NotificationStatus.PENDING.value

    def test_modify_does_not_notify_client(self) -> None:
        # Le client est l'auteur de la modification ; il n'est pas re-notifié (#48).
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        updates = [
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        ]
        assert all(n.user_id != _CLIENT_ID for n in updates)

    def test_race_condition_emits_no_notification(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity()],
            raise_conflict=True,
        )
        notifs = FakeNotificationRepository()
        with pytest.raises(SlotAlreadyBooked):
            self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )
        assert notifs.enqueued == []

    def test_not_modifiable_emits_no_notification(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        notifs = FakeNotificationRepository()
        with pytest.raises(AppointmentNotModifiable):
            self._uc(catalog=catalog, appts=appts, notifications=notifs).execute(
                _APPT_ID, _CLIENT_ID, _valid_modify_command()
            )
        assert notifs.enqueued == []


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
        notifications: FakeNotificationRepository | None = None,
        salons: FakeSalonRepository | None = None,
    ) -> CancelAppointment:
        return CancelAppointment(
            appts if appts is not None else FakeAppointmentRepository(),
            audit_log if audit_log is not None else FakeAuditLog(),
            notifications if notifications is not None else FakeNotificationRepository(),
            salons,
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

    # --- Annulation des rappels (US-7.2, #46, AC) ---------------------------

    def test_cancel_calls_cancel_pending_for_appointment_exactly_once(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(_APPT_ID, _CLIENT_ID)
        assert notifs.cancel_calls == [_APPT_ID]

    def test_cancel_marks_pending_reminders_cancelled(self) -> None:
        from coiflink_api.domain.enums import NotificationStatus, NotificationType
        from coiflink_api.domain.notification import NotificationToCreate

        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        notifs.enqueued.append(
            NotificationToCreate(
                type=NotificationType.REMINDER.value,
                channel="SMS",
                title="Rappel de rendez-vous",
                message="Vous avez un rendez-vous à venir.",
                user_id=_CLIENT_ID,
                salon_id=_SALON_ID,
                appointment_id=_APPT_ID,
                scheduled_for=datetime.datetime(2026, 8, 2, 9, 0),
            )
        )
        self._uc(appts=appts, notifications=notifs).execute(_APPT_ID, _CLIENT_ID)
        assert notifs.enqueued[0].status == NotificationStatus.CANCELLED.value

    def test_not_owned_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        notifs = FakeNotificationRepository()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, notifications=notifs).execute(
                _APPT_ID, _OTHER_CLIENT_ID
            )
        assert notifs.cancel_calls == []

    def test_not_cancellable_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        notifs = FakeNotificationRepository()
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts, notifications=notifs).execute(_APPT_ID, _CLIENT_ID)
        assert notifs.cancel_calls == []

    # --- Notifications d'annulation aux deux parties (US-7.4, #48, §8.4) ----

    def test_cancel_emits_two_cancellation_notifications(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _CLIENT_ID
        )
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert len(cancellations) == 2

    def test_cancel_notifies_client_and_salon_owner(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _CLIENT_ID
        )
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert {n.user_id for n in cancellations} == {_CLIENT_ID, _OWNER_ID}

    def test_cancel_client_notification_channel_is_resolved(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _CLIENT_ID
        )
        client_notif = next(
            n
            for n in notifs.enqueued
            if n.type == NotificationType.CANCELLATION.value and n.user_id == _CLIENT_ID
        )
        assert client_notif.channel == NotificationChannel.SMS.value

    def test_cancel_salon_notification_channel_is_in_app(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _CLIENT_ID
        )
        salon_notif = next(
            n
            for n in notifs.enqueued
            if n.type == NotificationType.CANCELLATION.value and n.user_id == _OWNER_ID
        )
        assert salon_notif.channel == NotificationChannel.IN_APP.value

    def test_cancel_notifications_status_is_pending(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _CLIENT_ID
        )
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert all(n.status == NotificationStatus.PENDING.value for n in cancellations)

    def test_cancel_without_salon_repository_notifies_client_only(self) -> None:
        # Câblage de test qui n'injecte pas de `SalonRepository` (défaut `None`) :
        # l'annulation n'échoue pas, seule la notification salon est omise.
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(_APPT_ID, _CLIENT_ID)
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert len(cancellations) == 1
        assert cancellations[0].user_id == _CLIENT_ID

    def test_cancel_unresolvable_salon_notifies_client_only(self) -> None:
        # `find_by_id` renvoie `None` (salon non amorcé) : théoriquement impossible
        # (FK RESTRICT) mais ne doit pas faire échouer l'annulation.
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        salons = FakeSalonRepository()  # vide : find_by_id(_SALON_ID) -> None
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _CLIENT_ID
        )
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert len(cancellations) == 1
        assert cancellations[0].user_id == _CLIENT_ID

    def test_not_cancellable_emits_no_cancellation_notification(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="COMPLETED")]
        )
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        with pytest.raises(AppointmentNotCancellable):
            self._uc(appts=appts, notifications=notifs, salons=salons).execute(
                _APPT_ID, _CLIENT_ID
            )
        assert notifs.enqueued == []

    def test_not_owned_emits_no_cancellation_notification(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(client_id=_CLIENT_ID)]
        )
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, notifications=notifs, salons=salons).execute(
                _APPT_ID, _OTHER_CLIENT_ID
            )
        assert notifs.enqueued == []


# ---------------------------------------------------------------------------
# SetAppointmentStatus (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestSetAppointmentStatus:
    """Cycle de statuts gérant : portée → machine à états → TOCTOU → audit (§11.4, #25)."""

    def _uc(
        self,
        appts: FakeAppointmentRepository | None = None,
        audit_log: FakeAuditLog | None = None,
        notifications: FakeNotificationRepository | None = None,
        salons: FakeSalonRepository | None = None,
    ) -> SetAppointmentStatus:
        return SetAppointmentStatus(
            appts if appts is not None else FakeAppointmentRepository(),
            audit_log if audit_log is not None else FakeAuditLog(),
            notifications if notifications is not None else FakeNotificationRepository(),
            salons,
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

    # --- Annulation des rappels — uniquement sur → CANCELLED (US-7.2, #46) --

    def test_refusal_cancels_pending_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED"
        )
        assert notifs.cancel_calls == [_APPT_ID]

    def test_confirmation_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert notifs.cancel_calls == []

    # --- Notifications de changement de statut (US-7.4, #48) ----------------

    def test_refusal_emits_two_cancellation_notifications(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED"
        )
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert len(cancellations) == 2
        assert {n.user_id for n in cancellations} == {_CLIENT_ID, _OWNER_ID}

    def test_refusal_salon_notification_channel_is_in_app(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        self._uc(appts=appts, notifications=notifs, salons=salons).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED"
        )
        salon_notif = next(
            n
            for n in notifs.enqueued
            if n.type == NotificationType.CANCELLATION.value and n.user_id == _OWNER_ID
        )
        assert salon_notif.channel == NotificationChannel.IN_APP.value

    def test_refusal_without_salon_repository_notifies_client_only(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED"
        )
        cancellations = [
            n for n in notifs.enqueued if n.type == NotificationType.CANCELLATION.value
        ]
        assert len(cancellations) == 1
        assert cancellations[0].user_id == _CLIENT_ID

    def test_confirmation_emits_one_appointment_update_to_client(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        updates = [
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        ]
        assert len(updates) == 1
        assert updates[0].user_id == _CLIENT_ID
        assert notifs.enqueued == updates  # aucune CANCELLATION mélangée

    def test_completion_emits_one_appointment_update_to_client(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "COMPLETED"
        )
        updates = [
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        ]
        assert len(updates) == 1
        assert updates[0].user_id == _CLIENT_ID

    def test_no_show_emits_one_appointment_update_to_client(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "NO_SHOW"
        )
        updates = [
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        ]
        assert len(updates) == 1
        assert updates[0].user_id == _CLIENT_ID

    def test_status_update_channel_is_resolved(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        update = next(
            n for n in notifs.enqueued if n.type == NotificationType.APPOINTMENT_UPDATE.value
        )
        assert update.channel == NotificationChannel.SMS.value

    def test_invalid_transition_emits_no_notification(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        notifs = FakeNotificationRepository()
        salons = _salon_repository_with_owner()
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts, notifications=notifs, salons=salons).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
            )
        assert notifs.enqueued == []

    def test_not_found_emits_no_notification(self) -> None:
        appts = FakeAppointmentRepository()
        notifs = FakeNotificationRepository()
        with pytest.raises(AppointmentNotFound):
            self._uc(appts=appts, notifications=notifs).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
            )
        assert notifs.enqueued == []

    def test_completed_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "COMPLETED"
        )
        assert notifs.cancel_calls == []

    def test_no_show_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        notifs = FakeNotificationRepository()
        self._uc(appts=appts, notifications=notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "NO_SHOW"
        )
        assert notifs.cancel_calls == []

    def test_invalid_transition_does_not_cancel_reminders(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CANCELLED")]
        )
        notifs = FakeNotificationRepository()
        with pytest.raises(InvalidAppointmentTransition):
            self._uc(appts=appts, notifications=notifs).execute(
                _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
            )
        assert notifs.cancel_calls == []


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


# ---------------------------------------------------------------------------
# ListSalonAppointments (US-3.5, #26)
# ---------------------------------------------------------------------------

_APPT_ID_3 = uuid.UUID("aaaaaa00-0000-0000-0000-000000000003")
_OTHER_SALON_ID = uuid.UUID("88888888-0000-0000-0000-000000000088")
_DATE_BEFORE = datetime.date(2026, 8, 1)
_DATE_AFTER = datetime.date(2026, 8, 10)


def _make_salon_appointment(
    *,
    appt_id: uuid.UUID = _APPT_ID,
    salon_id: uuid.UUID = _SALON_ID,
    status: str = "PENDING",
    date: datetime.date = _DATE,
    start_time: datetime.time = datetime.time(9, 0),
) -> Appointment:
    return Appointment(
        id=appt_id,
        salon_id=salon_id,
        client_id=_CLIENT_ID,
        hairdresser_id=None,
        date=date,
        start_time=start_time,
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT_DT,
        services=(
            BookedService(service_id=_SERVICE_ID, price_at_booking=decimal.Decimal("5000.00")),
        ),
    )


class TestListSalonAppointments:
    """Cas d'usage de lecture planning salon : plage, filtre statut, isolation (§11.2, #26)."""

    def _uc(self, appts: FakeAppointmentRepository) -> ListSalonAppointments:
        return ListSalonAppointments(appts)

    # --- Résultats de base ---------------------------------------------------

    def test_returns_appointment_in_range(self) -> None:
        appt = _make_salon_appointment()
        appts = FakeAppointmentRepository(appointments=[appt])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert len(result) == 1
        assert result[0].id == _APPT_ID

    def test_empty_repo_returns_empty_tuple(self) -> None:
        appts = FakeAppointmentRepository()
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert result == ()

    def test_appointment_before_range_excluded(self) -> None:
        before = _make_salon_appointment(appt_id=_APPT_ID, date=_DATE_BEFORE)
        appts = FakeAppointmentRepository(appointments=[before])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert result == ()

    def test_appointment_after_range_excluded(self) -> None:
        after = _make_salon_appointment(appt_id=_APPT_ID, date=_DATE_AFTER)
        appts = FakeAppointmentRepository(appointments=[after])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert result == ()

    def test_range_is_inclusive_on_first_day(self) -> None:
        first = _make_salon_appointment(appt_id=_APPT_ID, date=_DATE_BEFORE)
        appts = FakeAppointmentRepository(appointments=[first])
        result = self._uc(appts).execute(_SALON_ID, _DATE_BEFORE, _DATE_AFTER)
        assert len(result) == 1

    def test_range_is_inclusive_on_last_day(self) -> None:
        last = _make_salon_appointment(appt_id=_APPT_ID, date=_DATE_AFTER)
        appts = FakeAppointmentRepository(appointments=[last])
        result = self._uc(appts).execute(_SALON_ID, _DATE_BEFORE, _DATE_AFTER)
        assert len(result) == 1

    # --- Isolation salon (§11.2) -------------------------------------------

    def test_never_returns_appointment_of_other_salon(self) -> None:
        other = _make_salon_appointment(appt_id=_APPT_ID, salon_id=_OTHER_SALON_ID)
        appts = FakeAppointmentRepository(appointments=[other])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert result == ()

    def test_returns_only_own_salon_when_both_salons_present(self) -> None:
        own = _make_salon_appointment(appt_id=_APPT_ID, salon_id=_SALON_ID)
        other = _make_salon_appointment(appt_id=_APPT_ID_2, salon_id=_OTHER_SALON_ID)
        appts = FakeAppointmentRepository(appointments=[own, other])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert len(result) == 1
        assert result[0].salon_id == _SALON_ID

    # --- Filtre par statut --------------------------------------------------

    def test_status_filter_returns_only_matching(self) -> None:
        pending = _make_salon_appointment(appt_id=_APPT_ID, status="PENDING")
        confirmed = _make_salon_appointment(appt_id=_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        result = self._uc(appts).execute(
            _SALON_ID, _DATE, _DATE, statuses=("CONFIRMED",)
        )
        assert len(result) == 1
        assert result[0].status == "CONFIRMED"

    def test_no_status_filter_returns_all_statuses(self) -> None:
        pending = _make_salon_appointment(appt_id=_APPT_ID, status="PENDING")
        completed = _make_salon_appointment(appt_id=_APPT_ID_2, status="COMPLETED")
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE, statuses=None)
        assert len(result) == 2

    def test_multi_status_filter(self) -> None:
        pending = _make_salon_appointment(appt_id=_APPT_ID, status="PENDING")
        confirmed = _make_salon_appointment(appt_id=_APPT_ID_2, status="CONFIRMED")
        cancelled = _make_salon_appointment(appt_id=_APPT_ID_3, status="CANCELLED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed, cancelled])
        result = self._uc(appts).execute(
            _SALON_ID, _DATE, _DATE, statuses=("PENDING", "CONFIRMED")
        )
        assert len(result) == 2
        returned_statuses = {r.status for r in result}
        assert "PENDING" in returned_statuses
        assert "CONFIRMED" in returned_statuses
        assert "CANCELLED" not in returned_statuses

    def test_terminal_statuses_included_when_no_filter(self) -> None:
        cancelled = _make_salon_appointment(appt_id=_APPT_ID, status="CANCELLED")
        completed = _make_salon_appointment(appt_id=_APPT_ID_2, status="COMPLETED")
        no_show = _make_salon_appointment(appt_id=_APPT_ID_3, status="NO_SHOW")
        appts = FakeAppointmentRepository(appointments=[cancelled, completed, no_show])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE, statuses=None)
        assert len(result) == 3

    # --- Tri chronologique --------------------------------------------------

    def test_sorted_by_start_time_within_same_day(self) -> None:
        later = _make_salon_appointment(
            appt_id=_APPT_ID, date=_DATE, start_time=datetime.time(11, 0)
        )
        earlier = _make_salon_appointment(
            appt_id=_APPT_ID_2, date=_DATE, start_time=datetime.time(9, 0)
        )
        appts = FakeAppointmentRepository(appointments=[later, earlier])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert result[0].start_time <= result[1].start_time

    def test_sorted_by_date_across_days(self) -> None:
        day2 = _make_salon_appointment(appt_id=_APPT_ID, date=_DATE_AFTER)
        day1 = _make_salon_appointment(appt_id=_APPT_ID_2, date=_DATE_BEFORE)
        appts = FakeAppointmentRepository(appointments=[day2, day1])
        result = self._uc(appts).execute(_SALON_ID, _DATE_BEFORE, _DATE_AFTER)
        assert result[0].date < result[1].date

    def test_result_is_a_tuple(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_salon_appointment()])
        result = self._uc(appts).execute(_SALON_ID, _DATE, _DATE)
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# ListAssignedAppointments (US-3.6, #27)
# ---------------------------------------------------------------------------

_OTHER_HAIRDRESSER_ID = uuid.UUID("99999999-0000-0000-0000-000000000099")


def _make_assigned_appointment(
    *,
    appt_id: uuid.UUID = _APPT_ID,
    hairdresser_id: uuid.UUID | None = _HAIRDRESSER_ID,
    status: str = "PENDING",
    date: datetime.date = _DATE,
    start_time: datetime.time = datetime.time(9, 0),
) -> Appointment:
    return Appointment(
        id=appt_id,
        salon_id=_SALON_ID,
        client_id=_CLIENT_ID,
        hairdresser_id=hairdresser_id,
        date=date,
        start_time=start_time,
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT_DT,
        services=(
            BookedService(service_id=_SERVICE_ID, price_at_booking=decimal.Decimal("5000.00")),
        ),
    )


class TestListAssignedAppointments:
    """Planning coiffeur : isolation assignment-scopée, plage, filtre statut (§11.2, #27)."""

    def _uc(self, appts: FakeAppointmentRepository) -> ListAssignedAppointments:
        return ListAssignedAppointments(appts)

    # --- Résultats de base ---------------------------------------------------

    def test_returns_assigned_appointment_in_range(self) -> None:
        appt = _make_assigned_appointment()
        appts = FakeAppointmentRepository(appointments=[appt])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert len(result) == 1
        assert result[0].id == _APPT_ID

    def test_empty_repo_returns_empty_tuple(self) -> None:
        result = self._uc(FakeAppointmentRepository()).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert result == ()

    # --- Isolation §11.2 : un coiffeur ne voit jamais un RDV d'un collègue ---

    def test_other_hairdresser_appointments_excluded(self) -> None:
        other_appt = _make_assigned_appointment(
            appt_id=_APPT_ID, hairdresser_id=_OTHER_HAIRDRESSER_ID
        )
        appts = FakeAppointmentRepository(appointments=[other_appt])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert result == ()

    def test_unassigned_appointments_excluded(self) -> None:
        unassigned = _make_assigned_appointment(appt_id=_APPT_ID, hairdresser_id=None)
        appts = FakeAppointmentRepository(appointments=[unassigned])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert result == ()

    def test_own_and_other_hairdresser_mixed_only_own_returned(self) -> None:
        own = _make_assigned_appointment(appt_id=_APPT_ID, hairdresser_id=_HAIRDRESSER_ID)
        other = _make_assigned_appointment(
            appt_id=_APPT_ID_2, hairdresser_id=_OTHER_HAIRDRESSER_ID
        )
        appts = FakeAppointmentRepository(appointments=[own, other])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert len(result) == 1
        assert result[0].id == _APPT_ID

    # --- Plage de dates -------------------------------------------------------

    def test_appointment_before_range_excluded(self) -> None:
        before = _make_assigned_appointment(appt_id=_APPT_ID, date=_DATE_BEFORE)
        appts = FakeAppointmentRepository(appointments=[before])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert result == ()

    def test_appointment_after_range_excluded(self) -> None:
        after = _make_assigned_appointment(appt_id=_APPT_ID, date=_DATE_AFTER)
        appts = FakeAppointmentRepository(appointments=[after])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert result == ()

    def test_range_inclusive_first_day(self) -> None:
        on_start = _make_assigned_appointment(appt_id=_APPT_ID, date=_DATE_BEFORE)
        appts = FakeAppointmentRepository(appointments=[on_start])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE_BEFORE, _DATE_AFTER)
        assert len(result) == 1

    def test_range_inclusive_last_day(self) -> None:
        on_end = _make_assigned_appointment(appt_id=_APPT_ID, date=_DATE_AFTER)
        appts = FakeAppointmentRepository(appointments=[on_end])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE_BEFORE, _DATE_AFTER)
        assert len(result) == 1

    # --- Filtre statut --------------------------------------------------------

    def test_status_filter_single(self) -> None:
        pending = _make_assigned_appointment(appt_id=_APPT_ID, status="PENDING")
        confirmed = _make_assigned_appointment(appt_id=_APPT_ID_2, status="CONFIRMED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE, statuses=("CONFIRMED",))
        assert len(result) == 1
        assert result[0].status == "CONFIRMED"

    def test_status_filter_multi(self) -> None:
        pending = _make_assigned_appointment(appt_id=_APPT_ID, status="PENDING")
        confirmed = _make_assigned_appointment(appt_id=_APPT_ID_2, status="CONFIRMED")
        cancelled = _make_assigned_appointment(appt_id=_APPT_ID_3, status="CANCELLED")
        appts = FakeAppointmentRepository(appointments=[pending, confirmed, cancelled])
        result = self._uc(appts).execute(
            _HAIRDRESSER_ID, _DATE, _DATE, statuses=("PENDING", "CONFIRMED")
        )
        assert len(result) == 2
        returned = {r.status for r in result}
        assert "PENDING" in returned
        assert "CONFIRMED" in returned

    def test_no_status_filter_returns_all_statuses(self) -> None:
        pending = _make_assigned_appointment(appt_id=_APPT_ID, status="PENDING")
        completed = _make_assigned_appointment(appt_id=_APPT_ID_2, status="COMPLETED")
        appts = FakeAppointmentRepository(appointments=[pending, completed])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE, statuses=None)
        assert len(result) == 2

    # --- Tri chronologique ---------------------------------------------------

    def test_sorted_by_start_time_within_same_day(self) -> None:
        later = _make_assigned_appointment(
            appt_id=_APPT_ID, date=_DATE, start_time=datetime.time(11, 0)
        )
        earlier = _make_assigned_appointment(
            appt_id=_APPT_ID_2, date=_DATE, start_time=datetime.time(9, 0)
        )
        appts = FakeAppointmentRepository(appointments=[later, earlier])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert result[0].start_time <= result[1].start_time

    def test_sorted_by_date_across_days(self) -> None:
        day2 = _make_assigned_appointment(appt_id=_APPT_ID, date=_DATE_AFTER)
        day1 = _make_assigned_appointment(appt_id=_APPT_ID_2, date=_DATE_BEFORE)
        appts = FakeAppointmentRepository(appointments=[day2, day1])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE_BEFORE, _DATE_AFTER)
        assert result[0].date < result[1].date

    def test_result_is_a_tuple(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_assigned_appointment()])
        result = self._uc(appts).execute(_HAIRDRESSER_ID, _DATE, _DATE)
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# SummarizeDailyAppointments — décompte du jour (US-6.1, #39)
# ---------------------------------------------------------------------------

_SUMMARY_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_SUMMARY_DAY = datetime.date(2026, 7, 31)
_ALL_APPOINTMENT_STATUSES = {"PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"}


def _make_day_appointment(
    *,
    salon_id: uuid.UUID = _SUMMARY_SALON_ID,
    status: str = "PENDING",
    date: datetime.date = _SUMMARY_DAY,
) -> Appointment:
    return Appointment(
        id=uuid.uuid4(),
        salon_id=salon_id,
        client_id=uuid.uuid4(),
        hairdresser_id=None,
        date=date,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status=status,
        client_note=None,
        created_at=_CREATED_AT,
    )


class TestSummarizeDailyAppointments:
    """Cas d'usage lecture pure : délègue au port et complète via `build_daily_summary`."""

    def _uc(self, repo: FakeAppointmentRepository) -> SummarizeDailyAppointments:
        return SummarizeDailyAppointments(repo)

    def test_empty_day_total_zero(self) -> None:
        repo = FakeAppointmentRepository()
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.total == 0

    def test_empty_day_all_statuses_zero(self) -> None:
        repo = FakeAppointmentRepository()
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert all(v == 0 for v in result.by_status.values())

    def test_all_statuses_present_in_result(self) -> None:
        repo = FakeAppointmentRepository()
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert set(result.by_status.keys()) == _ALL_APPOINTMENT_STATUSES

    def test_date_matches_requested_day(self) -> None:
        repo = FakeAppointmentRepository()
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.date == _SUMMARY_DAY

    def test_single_confirmed_appointment_counted(self) -> None:
        appt = _make_day_appointment(status="CONFIRMED")
        repo = FakeAppointmentRepository(appointments=[appt])
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.by_status["CONFIRMED"] == 1
        assert result.total == 1

    def test_multi_status_appointments_counted_correctly(self) -> None:
        appts = [
            _make_day_appointment(status="PENDING"),
            _make_day_appointment(status="PENDING"),
            _make_day_appointment(status="CONFIRMED"),
            _make_day_appointment(status="CANCELLED"),
            _make_day_appointment(status="COMPLETED"),
            _make_day_appointment(status="COMPLETED"),
            _make_day_appointment(status="NO_SHOW"),
        ]
        repo = FakeAppointmentRepository(appointments=appts)
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.by_status["PENDING"] == 2
        assert result.by_status["CONFIRMED"] == 1
        assert result.by_status["CANCELLED"] == 1
        assert result.by_status["COMPLETED"] == 2
        assert result.by_status["NO_SHOW"] == 1
        assert result.total == 7

    def test_total_equals_sum_of_by_status(self) -> None:
        appts = [_make_day_appointment(status=s) for s in ("PENDING", "CONFIRMED", "NO_SHOW")]
        repo = FakeAppointmentRepository(appointments=appts)
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.total == sum(result.by_status.values())

    def test_isolation_other_salon_not_counted(self) -> None:
        # Isolation §11.2 : un RDV d'un autre salon au même jour est exclu
        other_salon = uuid.uuid4()
        own_appt = _make_day_appointment(salon_id=_SUMMARY_SALON_ID, status="CONFIRMED")
        other_appt = _make_day_appointment(salon_id=other_salon, status="CONFIRMED")
        repo = FakeAppointmentRepository(appointments=[own_appt, other_appt])
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.by_status["CONFIRMED"] == 1
        assert result.total == 1

    def test_isolation_other_day_not_counted(self) -> None:
        # Un RDV du même salon mais un autre jour n'est pas compté
        other_day = datetime.date(2026, 7, 30)
        today_appt = _make_day_appointment(date=_SUMMARY_DAY, status="CONFIRMED")
        other_appt = _make_day_appointment(date=other_day, status="CONFIRMED")
        repo = FakeAppointmentRepository(appointments=[today_appt, other_appt])
        result = self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert result.by_status["CONFIRMED"] == 1
        assert result.total == 1

    def test_no_write_side_effects(self) -> None:
        # Lecture pure : aucun audit, aucun enregistrement
        repo = FakeAppointmentRepository()
        self._uc(repo).execute(_SUMMARY_SALON_ID, _SUMMARY_DAY)
        assert repo.created == []
        assert repo.updated == []
        assert repo.cancelled == []
        assert repo.status_changes == []
        assert repo.assignments == []


# ---------------------------------------------------------------------------
# Périmètre de la notification salon (US-7.3, #47) — Cancel / SetStatus /
# ModifyAppointment n'émettent pas de NEW_BOOKING
# ---------------------------------------------------------------------------


class TestNoNewBookingOnOtherUsecases:
    """Régression de périmètre : seul `BookAppointment` émet `NEW_BOOKING`.

    `CancelAppointment`, `SetAppointmentStatus` et `ModifyAppointment`
    n'émettent **aucune** notification `NEW_BOOKING` — l'annulation/la
    modification du RDV relèvent de #48 (US-7.4), hors périmètre de #47.
    """

    def _new_booking_notifs(self, notifs: FakeNotificationRepository) -> list:
        from coiflink_api.domain.enums import NotificationType

        return [n for n in notifs.enqueued if n.type == NotificationType.NEW_BOOKING.value]

    def test_cancel_does_not_emit_new_booking(self) -> None:
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        CancelAppointment(appts, FakeAuditLog(), notifs).execute(_APPT_ID, _CLIENT_ID)
        assert self._new_booking_notifs(notifs) == []

    def test_set_status_confirmed_does_not_emit_new_booking(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        SetAppointmentStatus(appts, FakeAuditLog(), notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CONFIRMED"
        )
        assert self._new_booking_notifs(notifs) == []

    def test_set_status_cancelled_does_not_emit_new_booking(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="PENDING")]
        )
        notifs = FakeNotificationRepository()
        SetAppointmentStatus(appts, FakeAuditLog(), notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "CANCELLED"
        )
        assert self._new_booking_notifs(notifs) == []

    def test_set_status_completed_does_not_emit_new_booking(self) -> None:
        appts = FakeAppointmentRepository(
            appointments=[_make_appointment_entity(status="CONFIRMED")]
        )
        notifs = FakeNotificationRepository()
        SetAppointmentStatus(appts, FakeAuditLog(), notifs).execute(
            _APPT_ID, _SALON_ID, _MANAGER_ID, "COMPLETED"
        )
        assert self._new_booking_notifs(notifs) == []

    def test_modify_does_not_emit_new_booking(self) -> None:
        catalog = _bookable_catalog()
        appts = FakeAppointmentRepository(appointments=[_make_appointment_entity()])
        notifs = FakeNotificationRepository()
        ModifyAppointment(catalog, appts, _scope(), FakeAuditLog(), notifs).execute(
            _APPT_ID, _CLIENT_ID, _valid_modify_command()
        )
        assert self._new_booking_notifs(notifs) == []
