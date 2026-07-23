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
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
)
from coiflink_api.domain.appointment import (
    Appointment,
    AppointmentToCreate,
    AppointmentUpdate,
    BookedService,
    compute_end_time,
    is_client_cancellable,
    is_client_modifiable,
    normalize_cancellation_reason,
    require_services,
    validate_booking_window,
)
from coiflink_api.domain.audit import (
    ENTITY_TYPE_APPOINTMENT,
    AuditAction,
    AuditEntry,
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
    AppointmentNotCancellable,
    AppointmentNotFound,
    AppointmentNotModifiable,
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


def _resolve_booked_services(
    repository: SalonCatalogRepository,
    salon_id: uuid.UUID,
    service_ids: tuple[uuid.UUID, ...],
) -> tuple[tuple[BookedService, ...], int]:
    """Résout les prestations **actives** du salon en `BookedService` + durée totale.

    Le **prix figé** est (re)capturé au tarif courant de chaque prestation ; la durée
    totale sert à calculer la fenêtre horaire. L'ordre suit `service_ids`
    (déterminisme). Lève `ServiceNotFound` sur une prestation inactive/hors salon,
    puis `AppointmentServiceRequired` (via `require_services`) si l'ensemble est vide.
    Réutilisé par la réservation (#21) et la modification (#23).
    """

    active = {s.id: s for s in repository.list_active_services(salon_id)}
    booked_services: list[BookedService] = []
    total_minutes = 0
    for service_id in service_ids:
        service = active.get(service_id)
        if service is None:
            raise ServiceNotFound("Prestation introuvable.")
        total_minutes += service.duration_minutes
        booked_services.append(
            BookedService(service_id=service.id, price_at_booking=service.price)
        )
    require_services(tuple(booked_services))
    return tuple(booked_services), total_minutes


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
        booked_services, total_minutes = _resolve_booked_services(
            self._catalog, salon_id, command.service_ids
        )

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
                services=booked_services,
                client_note=command.client_note,
            )
        )


# --------------------------------------------------------------------------- #
# Modification d'un rendez-vous par le client (US-3.2, #23).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModifyAppointmentCommand:
    """Champs re-planifiables d'un RDV — mêmes saisies qu'une réservation.

    Sémantique **replace** (comme le corps de réservation) : la modification remplace
    intégralement date/créneau, prestation(s) et commentaire. Ne porte **jamais**
    `salon_id`/`client_id`/`status` — le `salon_id` vient du RDV chargé, `client_id`
    du `Principal`, `status` reste inchangé (anti-élévation §11.2). `service_ids`
    porte **au moins une** prestation.
    """

    date: datetime.date
    start_time: datetime.time
    service_ids: tuple[uuid.UUID, ...]
    hairdresser_id: uuid.UUID | None = None
    client_note: str | None = None
    granularity_minutes: int = DEFAULT_GRANULARITY_MINUTES


# Champs comparés pour le diff **neutre** de la modification (ordre stable). Seuls
# des **noms de champs** sont journalisés — jamais les valeurs (§11.4, patron #20).
_APPOINTMENT_DIFF_FIELDS: tuple[str, ...] = (
    "date",
    "start_time",
    "hairdresser_id",
    "client_note",
)


def _changed_appointment_fields(
    current: Appointment, changes: AppointmentUpdate
) -> list[str]:
    """Noms des champs re-planifiés dont la valeur change (diff neutre, §11.4).

    Compare les seuls **noms** de champs (jamais les valeurs). L'ensemble des
    prestations est comparé par identifiants (indépendamment de l'ordre) et signalé
    sous le nom générique `"services"` — aucune valeur (prix/durée) ne fuit.
    """

    changed = [
        field
        for field in _APPOINTMENT_DIFF_FIELDS
        if getattr(current, field) != getattr(changes, field)
    ]
    current_services = {s.service_id for s in current.services}
    new_services = {s.service_id for s in changes.services}
    if current_services != new_services:
        changed.append("services")
    return changed


class ModifyAppointment:
    """Re-planifie **le** RDV du client authentifié et journalise (§11.4, #23).

    Séquence : charger le RDV **du client** (`AppointmentNotFound` si inexistant ou
    d'autrui — indiscernables) → **verrou d'état** (`AppointmentNotModifiable` si
    terminé/terminal) → re-valider la cible (salon réservable §8.3, coiffeur du
    salon, prestations actives, fenêtre) → `is_offered` en **excluant le RDV
    lui-même** du calcul → `update` transactionnel (l'exclusion base arbitre les
    courses, l'UPDATE conditionnel ré-affirme le verrou) → audit `APPOINTMENT_UPDATED`
    (métadonnées neutres). Le `salon_id` provient **du RDV chargé**, jamais du corps.
    """

    def __init__(
        self,
        catalog_repository: SalonCatalogRepository,
        appointment_repository: AppointmentRepository,
        scope_repository: SalonScopeRepository,
        audit_log: AuditLog,
    ) -> None:
        self._catalog = catalog_repository
        self._appointments = appointment_repository
        self._scope = scope_repository
        self._audit_log = audit_log

    def execute(
        self,
        appointment_id: uuid.UUID,
        client_id: uuid.UUID,
        command: ModifyAppointmentCommand,
        *,
        now: datetime.datetime | None = None,
    ) -> Appointment:
        current = self._appointments.get_owned(appointment_id, client_id)
        if current is None:
            # RDV inexistant **ou** d'autrui : indiscernables (aucun oracle, §11.2).
            raise AppointmentNotFound("Rendez-vous introuvable.")
        if not is_client_modifiable(current.status):
            raise AppointmentNotModifiable("Ce rendez-vous n'est plus modifiable.")

        # Le `salon_id` vient du RDV chargé (route d'appartenance, jamais du corps).
        salon = _load_bookable_salon(self._catalog, current.salon_id)

        # Un coiffeur demandé doit appartenir au salon du RDV (§11.2) : l'exclusion
        # base est globale (sans `salon_id`) et ne peut pas arbitrer ce cas.
        if command.hairdresser_id is not None:
            _require_salon_hairdresser(
                self._scope, current.salon_id, command.hairdresser_id
            )

        booked_services, total_minutes = _resolve_booked_services(
            self._catalog, current.salon_id, command.service_ids
        )

        end_time = compute_end_time(command.start_time, total_minutes)
        validate_booking_window(command.start_time, end_time)

        hours = parse_opening_hours(salon.opening_hours)
        # Défense en profondeur `is_offered` en **excluant le RDV lui-même** : sinon
        # son propre créneau actuel apparaîtrait occupé (faux rejet d'un déplacement
        # légitime, y compris un simple changement de note à date/heure inchangées).
        booked = self._appointments.booked_slots(
            current.salon_id,
            command.hairdresser_id,
            command.date,
            exclude_appointment_id=appointment_id,
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

        changes = AppointmentUpdate(
            date=command.date,
            start_time=command.start_time,
            end_time=end_time,
            hairdresser_id=command.hairdresser_id,
            client_note=command.client_note,
            services=booked_services,
        )
        changed = _changed_appointment_fields(current, changes)
        updated = self._appointments.update(appointment_id, changes)
        # Audit §11.4 dans la **même** unité de travail que l'écriture (patron #20) :
        # métadonnées **neutres** (noms de champs uniquement, jamais de valeur).
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.APPOINTMENT_UPDATED.value,
                actor_user_id=client_id,
                salon_id=current.salon_id,
                entity_type=ENTITY_TYPE_APPOINTMENT,
                entity_id=appointment_id,
                metadata={"changed": changed},
            )
        )
        return updated


# --------------------------------------------------------------------------- #
# Annulation d'un rendez-vous par le client (US-3.3, #24).
# --------------------------------------------------------------------------- #
class CancelAppointment:
    """Annule **le** RDV du client authentifié et journalise (§11.4, #24).

    Séquence (patron ownership→verrou→écriture conditionnelle→audit, #23) : charger
    le RDV **du client** (`AppointmentNotFound` si inexistant ou d'autrui —
    indiscernables, aucun oracle §11.2) → **verrou d'état** (`AppointmentNotCancellable`
    si terminé/terminal/déjà annulé) → `cancel` transactionnel (UPDATE conditionnel sur
    statut actif, ré-affirme le verrou — garde TOCTOU) → audit `APPOINTMENT_CANCELLED`
    **neutre** dans la **même** unité de travail.

    N'exige **ni** catalogue **ni** portée : l'annulation ne re-valide **pas** la
    disponibilité et **reste possible même si le salon est devenu non réservable/
    inactif** (§8.3) — on n'empêche jamais un client d'annuler son RDV. Par
    construction, l'annulation **libère** le créneau (le RDV quitte l'ensemble actif).

    Le **motif** est optionnel : normalisé (`normalize_cancellation_reason`), il est
    **persisté** sur la ligne du RDV mais **jamais** journalisé — les métadonnées
    d'audit ne portent qu'un booléen neutre `reason_provided` (le *fait* qu'un motif
    ait été fourni n'est pas une PII ; son **contenu**, si — donc jamais tracé).
    """

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        audit_log: AuditLog,
    ) -> None:
        self._appointments = appointment_repository
        self._audit_log = audit_log

    def execute(
        self,
        appointment_id: uuid.UUID,
        client_id: uuid.UUID,
        reason: str | None = None,
        *,
        now: datetime.datetime | None = None,  # noqa: ARG002 (parité de signature)
    ) -> Appointment:
        current = self._appointments.get_owned(appointment_id, client_id)
        if current is None:
            # RDV inexistant **ou** d'autrui : indiscernables (aucun oracle, §11.2).
            raise AppointmentNotFound("Rendez-vous introuvable.")
        if not is_client_cancellable(current.status):
            raise AppointmentNotCancellable(
                "Ce rendez-vous ne peut plus être annulé."
            )

        normalized_reason = normalize_cancellation_reason(reason)
        # UPDATE conditionnel (`WHERE status IN (actifs)`) : ré-affirme le verrou au
        # moment de l'écriture. Le motif normalisé est persisté ; le RDV quitte
        # l'ensemble actif → le créneau se libère (exclusion base + `booked_slots`).
        updated = self._appointments.cancel(
            appointment_id, reason=normalized_reason
        )
        # Audit §11.4 dans la **même** unité de travail que l'écriture (patron #20/#23) :
        # métadonnées **neutres** — jamais le texte du motif ni de PII.
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.APPOINTMENT_CANCELLED.value,
                actor_user_id=client_id,
                salon_id=current.salon_id,
                entity_type=ENTITY_TYPE_APPOINTMENT,
                entity_id=appointment_id,
                metadata={"reason_provided": normalized_reason is not None},
            )
        )
        return updated


class ListMyAppointments:
    """Liste les RDV **du client** authentifié (lecture « Mes rendez-vous », #23).

    Prérequis du flux de modification : le client retrouve ses RDV pour en choisir
    un à modifier. Ne renvoie **que** ses propres RDV (§11.2/§11.3) ; `statuses`
    restreint aux états utiles (par défaut, l'adapter entrant filtre les états
    actifs/modifiables `PENDING`/`CONFIRMED`).
    """

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self,
        client_id: uuid.UUID,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        return self._appointments.list_for_client(client_id, statuses)


__all__ = [
    "BookingCommand",
    "CheckAvailability",
    "BookAppointment",
    "ModifyAppointmentCommand",
    "ModifyAppointment",
    "CancelAppointment",
    "ListMyAppointments",
]
