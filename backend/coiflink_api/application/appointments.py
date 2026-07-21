"""Cas d'usage : **disponibilité & réservation** de rendez-vous (US-3.7, #21).

Tranche applicative hexagonale (ADR-0008) : ces cas d'usage ne dépendent que de
**ports** (`AppointmentRepository`, `SalonCatalogRepository`) et du domaine pur
(`domain/availability.py`, `domain/appointment.py`) — aucune dépendance
FastAPI/SQLAlchemy. Ils laissent l'adapter entrant traduire les erreurs en HTTP.

Deux invariants structurants :

- **`salon_id`/`client_id` imposés serveur** : jamais lus du corps de requête
  (anti-élévation §11.2). Le `salon_id` vient du chemin, le `client_id` du
  `Principal` client authentifié.
- **La garantie anti double-réservation vient de la base**, pas d'ici : le contrôle
  `is_offered` de `BookAppointment` est une **défense en profondeur** (aide UX) ;
  entre ce contrôle et l'INSERT subsiste un TOCTOU **fermé par la contrainte
  d'exclusion** `ex_appointments_hairdresser_slot`. Sous `READ COMMITTED` (défaut),
  deux INSERT concurrents de créneaux qui se chevauchent pour le même coiffeur
  déclenchent l'attente puis l'échec du second, traduit en `SlotAlreadyBooked`.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.appointment_repository import AppointmentRepository
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
)
from coiflink_api.domain.appointment import (
    Appointment,
    AppointmentToCreate,
    BookedService,
    compute_end_time,
    require_services,
    validate_booking_window,
)
from coiflink_api.domain.availability import (
    DEFAULT_GRANULARITY_MINUTES,
    SlotRange,
    free_slots,
    is_offered,
)
from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    HairdresserNotInSalon,
    SalonNotBookable,
    SalonNotFound,
    ServiceNotFound,
    SlotUnavailable,
)
from coiflink_api.domain.opening_hours import parse_opening_hours
from coiflink_api.domain.salon import Salon, is_bookable
from coiflink_api.domain.service import Service


@dataclass(frozen=True)
class BookingCommand:
    """Champs saisissables d'une réservation (jamais `salon_id`/`client_id`/`status`).

    `service_ids` porte **au moins une** prestation (validé avant écriture) ;
    `hairdresser_id` est optionnel — la garantie anti double-réservation ne
    s'applique **qu'avec** un coiffeur assigné (clause `WHERE hairdresser_id IS NOT
    NULL` de l'exclusion, cohérent avec le §8.1 « pour le même coiffeur »).
    """

    date: datetime.date
    start_time: datetime.time
    service_ids: tuple[uuid.UUID, ...]
    hairdresser_id: uuid.UUID | None = None
    client_note: str | None = None
    granularity_minutes: int = DEFAULT_GRANULARITY_MINUTES


def _load_bookable_salon(
    repository: SalonCatalogRepository, salon_id: uuid.UUID
) -> Salon:
    """Charge un salon `ACTIVE` **réservable** (§8.3), sinon lève l'erreur adaptée.

    `get_active` filtre `status = ACTIVE` en SQL : un salon inconnu ou non actif est
    indiscernable (`SalonNotFound` → `404`, pas d'oracle). Un salon actif mais sans
    horaire n'est pas réservable (`SalonNotBookable` → `409`, §8.3).
    """

    salon = repository.get_active(salon_id)
    if salon is None:
        raise SalonNotFound("Salon introuvable.")
    if not is_bookable(salon.status, salon.opening_hours):
        raise SalonNotBookable("Ce salon n'accepte pas encore de réservation.")
    return salon


def _active_service(
    repository: SalonCatalogRepository, salon_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    """Charge une prestation **active du salon**, sinon `ServiceNotFound`.

    Réutilise `list_active_services` (filtre `is_active = true` en SQL) : une
    prestation d'un autre salon ou désactivée est indiscernable d'une inexistante.
    """

    for service in repository.list_active_services(salon_id):
        if service.id == service_id:
            return service
    raise ServiceNotFound("Prestation introuvable.")


def _require_salon_hairdresser(
    repository: SalonScopeRepository, salon_id: uuid.UUID, hairdresser_id: uuid.UUID
) -> None:
    """Refuse un `hairdresser_id` qui n'est pas membre `ACTIVE` du salon ciblé (§11.2).

    Réutilise le port d'autorité de la portée employé : `salon_ids_for(id,
    HAIRDRESSER)` lit `salon_members WHERE user_id = … AND status = 'ACTIVE'` — donc
    un membre `INACTIVE`, un coiffeur d'un autre salon, un client ou un UUID inconnu
    donnent tous une portée qui ne contient pas `salon_id`, et sont refusés de façon
    indiscernable (`HairdresserNotInSalon` → `404`, aucun oracle).

    Contrôle **indispensable** : l'exclusion base `ex_appointments_hairdresser_slot`
    ne porte pas `salon_id`, elle ne peut donc pas rattraper un coiffeur hors salon.
    """

    scope = repository.salon_ids_for(hairdresser_id, Role.HAIRDRESSER.value)
    if salon_id not in scope:
        raise HairdresserNotInSalon("Coiffeur introuvable pour ce salon.")


class CheckAvailability:
    """Calcule les créneaux **libres** d'un salon/coiffeur pour une prestation (§8.3).

    Refuse un salon non réservable (`SalonNotBookable`) et une prestation
    inactive/hors salon (`ServiceNotFound`) **avant** tout calcul. La liste renvoyée
    ne contient que des créneaux libres — jamais l'identité de qui occupe les
    créneaux pris (§11.3).
    """

    def __init__(
        self,
        catalog_repository: SalonCatalogRepository,
        appointment_repository: AppointmentRepository,
    ) -> None:
        self._catalog = catalog_repository
        self._appointments = appointment_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        date: datetime.date,
        service_id: uuid.UUID,
        hairdresser_id: uuid.UUID | None = None,
        *,
        granularity_minutes: int = DEFAULT_GRANULARITY_MINUTES,
        now: datetime.datetime | None = None,
    ) -> tuple[SlotRange, ...]:
        salon = _load_bookable_salon(self._catalog, salon_id)
        service = _active_service(self._catalog, salon_id, service_id)
        hours = parse_opening_hours(salon.opening_hours)
        booked = self._appointments.booked_slots(salon_id, hairdresser_id, date)
        return free_slots(
            hours,
            date,
            service.duration_minutes,
            booked,
            granularity_minutes=granularity_minutes,
            now=now,
        )


class BookAppointment:
    """Crée un rendez-vous en **une** transaction, anti double-réservation garantie base.

    Séquence : valider `≥ 1` prestation → refuser un salon non réservable → charger
    les prestations actives (durée + prix figé) → calculer la fenêtre horaire →
    défense en profondeur `is_offered` → `repository.create(...)`. En cas de course
    concurrente, l'INSERT perd sur la contrainte d'exclusion et le dépôt lève
    `SlotAlreadyBooked` (rollback complet — RDV + jonctions).
    """

    def __init__(
        self,
        catalog_repository: SalonCatalogRepository,
        appointment_repository: AppointmentRepository,
        scope_repository: SalonScopeRepository,
    ) -> None:
        self._catalog = catalog_repository
        self._appointments = appointment_repository
        self._scope = scope_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        client_id: uuid.UUID,
        command: BookingCommand,
        *,
        now: datetime.datetime | None = None,
    ) -> Appointment:
        salon = _load_bookable_salon(self._catalog, salon_id)

        # Le coiffeur demandé doit appartenir au salon réservé : l'exclusion base
        # est globale (sans `salon_id`) et ne peut pas arbitrer ce cas (§11.2).
        if command.hairdresser_id is not None:
            _require_salon_hairdresser(self._scope, salon_id, command.hairdresser_id)

        # Prestations actives du salon (durée pour la fenêtre, prix figé à la
        # réservation). L'ordre suit `command.service_ids` (déterminisme).
        active = {s.id: s for s in self._catalog.list_active_services(salon_id)}
        booked_services: list[BookedService] = []
        total_minutes = 0
        for service_id in command.service_ids:
            service = active.get(service_id)
            if service is None:
                raise ServiceNotFound("Prestation introuvable.")
            total_minutes += service.duration_minutes
            booked_services.append(
                BookedService(service_id=service.id, price_at_booking=service.price)
            )
        require_services(tuple(booked_services))

        end_time = compute_end_time(command.start_time, total_minutes)
        validate_booking_window(command.start_time, end_time)

        hours = parse_opening_hours(salon.opening_hours)
        booked = self._appointments.booked_slots(
            salon_id, command.hairdresser_id, command.date
        )
        slot = SlotRange(date=command.date, start=command.start_time, end=end_time)
        if not is_offered(
            hours,
            slot,
            total_minutes,
            booked,
            granularity_minutes=command.granularity_minutes,
            now=now,
        ):
            raise SlotUnavailable("Le créneau demandé n'est pas disponible.")

        return self._appointments.create(
            AppointmentToCreate(
                salon_id=salon_id,
                client_id=client_id,
                hairdresser_id=command.hairdresser_id,
                date=command.date,
                start_time=command.start_time,
                end_time=end_time,
                services=tuple(booked_services),
                client_note=command.client_note,
            )
        )


__all__ = ["BookingCommand", "CheckAvailability", "BookAppointment"]
