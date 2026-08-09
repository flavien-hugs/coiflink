"""Adapter entrant (driving) : router HTTP **disponibilité & réservation** (US-3.7, #21).

Expose deux surfaces au-dessus du moteur de disponibilité et du chemin d'écriture
transactionnel (la garantie anti double-réservation venant de la contrainte
d'exclusion base) :

- **Lecture de disponibilité** — `GET /catalog/salons/{salon_id}/availability` :
  créneaux **libres** d'un salon `ACTIVE` pour une prestation (et un coiffeur
  optionnel). **Publique** (ajoutée à `PUBLIC_ROUTE_PATHS`, patron catalogue
  #18/#19) : un client browse et compare avant même de se connecter. La réponse ne
  révèle **jamais** l'identité de qui occupe les créneaux pris (§11.3) — seulement
  les créneaux libres.
- **Réservation** — `POST /salons/{salon_id}/appointments` : crée le RDV pour le
  **client authentifié** (`APPOINTMENT_BOOK`). `client_id = principal.id`, `salon_id`
  du chemin — **jamais** du corps (anti-élévation §11.2). Un `CLIENT` n'ayant **aucune
  portée salon**, cette route **n'utilise pas** `require_salon_scope` (il renverrait
  un `403`) : la validation « salon réservable » est faite par le cas d'usage.
- **Lecture « mes rendez-vous »** — `GET /appointments` : liste les RDV **actifs** du
  **client authentifié** (`APPOINTMENT_READ_OWN`) ; prérequis du flux de modification
  mobile. Ne renvoie **que** les données du client (§11.2/§11.3).
- **Modification** — `PATCH /appointments/{appointment_id}` : re-planifie **le** RDV
  du **client authentifié** (`APPOINTMENT_BOOK`, appartenance vérifiée serveur, §8.1).
  Route d'**appartenance** (pas de portée salon, pas de `salon_id` dans le chemin) :
  le `salon_id` vient du RDV chargé. Un RDV terminé (`COMPLETED`/terminal) est
  **verrouillé côté client** (`409`). La modification est journalisée (§11.4).
- **Cycle de statuts (gérant)** — `POST /salons/{salon_id}/appointments/{id}/status` :
  confirme/refuse/termine/marque-absent un RDV **du salon** (`APPOINTMENT_UPDATE_STATUS`
  **+** `require_salon_scope`, US-3.4 #25). Le `status` cible est **doublement
  contraint** (énumération Pydantic → `422` ; machine à états du domaine → `409`) — le
  juge est le domaine, pas un champ soumis. Journalisé `APPOINTMENT_STATUS_CHANGED`.
- **Assignation (gérant)** — `PUT /salons/{salon_id}/appointments/{id}/hairdresser` :
  (dés)assigne un coiffeur à un RDV **actif du salon** (`APPOINTMENT_MANAGE` **+**
  `require_salon_scope`). Le coiffeur est validé contre l'appartenance salon ; le
  conflit d'agenda est arbitré par l'exclusion base (`SlotAlreadyBooked`). Journalisé
  `APPOINTMENT_HAIRDRESSER_ASSIGNED`.

Traductions d'erreurs de domaine → HTTP : `SlotAlreadyBooked` (course perdue) /
`SlotUnavailable` / `SalonNotBookable` / `AppointmentNotModifiable` (verrou terminé) /
`InvalidAppointmentTransition` (transition interdite/terminale, gérant) → **409** ;
`AppointmentServiceRequired` → **422** ; `ServiceNotFound` / `SalonNotFound` /
`HairdresserNotInSalon` / `AppointmentNotFound` (inexistant ou hors
appartenance/salon) → **404** *(après portée/appartenance)*.

Un `hairdresser_id` soumis dans le corps est **validé contre `salon_members`** avant
écriture (§11.2) : l'exclusion base ne porte pas `salon_id`, sans ce contrôle un
client pourrait occuper l'agenda d'un coiffeur d'un autre salon.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    get_salon_scope_repository,
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.appointment_repository import (
    SqlAppointmentRepository,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.notification_repository import (
    SqlNotificationRepository,
)
from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    SqlSalonCatalogRepository,
)
from coiflink_api.adapters.outbound.persistence.payment_repository import (
    SqlPaymentRepository,
)
from coiflink_api.adapters.outbound.persistence.salon_repository import (
    SqlSalonRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
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
from coiflink_api.application.ports.appointment_repository import AppointmentRepository
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.notification_repository import (
    NotificationRepository,
)
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
)
from coiflink_api.application.ports.salon_repository import SalonRepository
from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.application.queue import (
    ListSalonQueue,
    MarkAppointmentArrived,
    StartAppointmentService,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.appointment import (
    Appointment,
    CLIENT_HISTORY_STATUSES,
    CLIENT_MODIFIABLE_STATUSES,
    DailyAppointmentSummary,
)
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import (
    AppointmentArrivalRequired,
    AppointmentHairdresserRequired,
    AppointmentNotCancellable,
    AppointmentNotFound,
    AppointmentNotModifiable,
    AppointmentServiceRequired,
    HairdresserNotInSalon,
    InvalidAppointmentTransition,
    SalonNotBookable,
    SalonNotFound,
    ServiceNotFound,
    SlotAlreadyBooked,
    SlotUnavailable,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.queue import QueueEntry
from coiflink_api.domain.time_window import SALON_TIMEZONE

router = APIRouter(tags=["appointments"])

# Chemin **public** de la disponibilité (ajouté à `security.PUBLIC_ROUTE_PATHS`).
# Exposé ici pour rester la source unique du littéral (router + composition root).
AVAILABILITY_PATH = "/catalog/salons/{salon_id}/availability"

# Amplitude maximale de la plage de lecture du planning (garde de coût §12) : la
# grille mensuelle du web fait au plus 6×7 = 42 cellules. Une plage plus large est
# refusée (`422`), l'index `ix_appointments_salon_id` couvrant les lectures bornées.
MAX_PLANNING_RANGE_DAYS = 42


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `services.py`).
# --------------------------------------------------------------------------- #
class SlotResponse(BaseModel):
    """Créneau **libre** renvoyé par la disponibilité : `date`, `start`, `end`."""

    date: datetime.date
    start: datetime.time
    end: datetime.time


class AvailabilityResponse(BaseModel):
    """Réponse de `GET .../availability` : la liste ordonnée des créneaux libres."""

    slots: list[SlotResponse]


class BookAppointmentRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/appointments`.

    **Aucun** `salon_id`/`client_id`/`status` : le `salon_id` vient du chemin, le
    `client_id` du `Principal`, `status` force `PENDING`. Un champ privilégié présent
    est **ignoré** (`extra="ignore"`). `service_ids` porte **au moins une** prestation.
    """

    model_config = ConfigDict(extra="ignore")

    date: datetime.date = Field(examples=["2026-08-01"])
    start_time: datetime.time = Field(examples=["09:00"])
    service_ids: list[uuid.UUID] = Field(min_length=1)
    hairdresser_id: uuid.UUID | None = Field(default=None)
    client_note: str | None = Field(default=None, examples=["Je préfère court."])


class ModifyAppointmentRequest(BaseModel):
    """Corps de `PATCH /appointments/{appointment_id}` (sémantique *replace*, #23).

    Mêmes champs saisissables qu'une réservation ; **aucun** `salon_id`/`client_id`/
    `status` : le `salon_id` vient du RDV chargé, `client_id` du `Principal`, `status`
    reste inchangé. Un champ privilégié présent est **ignoré** (`extra="ignore"`).
    `service_ids` porte **au moins une** prestation.
    """

    model_config = ConfigDict(extra="ignore")

    date: datetime.date = Field(examples=["2026-08-01"])
    start_time: datetime.time = Field(examples=["09:00"])
    service_ids: list[uuid.UUID] = Field(min_length=1)
    hairdresser_id: uuid.UUID | None = Field(default=None)
    client_note: str | None = Field(default=None, examples=["Je préfère court."])


class CancelAppointmentRequest(BaseModel):
    """Corps de `POST /appointments/{appointment_id}/cancellation` (US-3.3, #24).

    Porte **uniquement** un `reason` optionnel : le `status = CANCELLED` est **forcé
    serveur** (c'est *la route* qui décide de la transition, jamais un champ soumis) ;
    le `client_id` vient du `Principal`, le `salon_id` du RDV chargé. Un champ
    privilégié présent (`salon_id`/`client_id`/`status`) est **ignoré**
    (`extra="ignore"`) — anti-élévation §11.2. Le motif est **persisté** sur la ligne
    du RDV mais **jamais** journalisé (§11.3).
    """

    model_config = ConfigDict(extra="ignore")

    reason: str | None = Field(
        default=None, examples=["Empêchement de dernière minute."]
    )


class SetStatusRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/appointments/{appointment_id}/status` (#25).

    Le gérant **choisit légitimement la cible** : `status` est une **valeur
    d'énumération** (`AppointmentStatus`) — une valeur hors énumération est un `422`
    Pydantic — puis la **machine à états du domaine** (deny-by-default) arbitre la
    transition (`409` si interdite). C'est le domaine, jamais un champ soumis, qui
    est le juge. Un `reason` optionnel n'est **persisté** que sur un refus/annulation
    (`→ CANCELLED`) et **jamais** journalisé. **Aucun** `salon_id`/`client_id` : le
    `salon_id` vient du chemin (portée). Champ privilégié présent → **ignoré**
    (`extra="ignore"`, anti-élévation §11.2).
    """

    model_config = ConfigDict(extra="ignore")

    status: AppointmentStatus = Field(examples=["CONFIRMED"])
    reason: str | None = Field(
        default=None, examples=["Créneau non honoré par le client."]
    )


class AssignHairdresserRequest(BaseModel):
    """Corps de `PUT /salons/{salon_id}/appointments/{appointment_id}/hairdresser` (#25).

    Porte **uniquement** `hairdresser_id` : un UUID pour **assigner/réassigner**, ou
    `null` pour **désassigner** (présence **requise** — intention explicite). Le
    coiffeur est validé contre l'appartenance salon (`salon_members`) avant écriture
    (§11.2). **Aucun** `salon_id`/`client_id`/`status` : le `salon_id` vient du chemin.
    Champ privilégié présent → **ignoré** (`extra="ignore"`).
    """

    model_config = ConfigDict(extra="ignore")

    hairdresser_id: uuid.UUID | None = Field(
        description="Coiffeur à assigner (UUID) ou null pour désassigner."
    )


class BookedServiceResponse(BaseModel):
    """Prestation réservée : identifiant + prix figé à la réservation."""

    service_id: uuid.UUID
    price_at_booking: decimal.Decimal


class AppointmentResponse(BaseModel):
    """Rendez-vous créé, renvoyé par l'API (statut `PENDING` à la création).

    `arrived_at`/`started_at` (#150) portent le **pointage réel** de la file
    d'attente — distinct de `status` (`domain/queue.py`) ; `None` = non pointé.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    client_id: uuid.UUID
    hairdresser_id: uuid.UUID | None
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    status: str
    client_note: str | None
    services: list[BookedServiceResponse]
    arrived_at: datetime.datetime | None = None
    started_at: datetime.datetime | None = None


class QueueEntryResponse(BaseModel):
    """Une ligne de la file d'attente du salon (#150) — sans PII au-delà des noms.

    `queue_status` est **dérivé** (`en_attente`/`en_cours`/`terminee`/`payee`
    côté domaine `waiting`/`in_progress`/`completed`/`paid`), jamais stocké.
    """

    appointment_id: uuid.UUID
    client_name: str | None
    service_names: list[str]
    hairdresser_id: uuid.UUID | None
    hairdresser_name: str | None
    start_time: datetime.time
    end_time: datetime.time
    status: str
    queue_status: str
    arrived_at: datetime.datetime | None
    started_at: datetime.datetime | None


class DailyAppointmentsSummaryResponse(BaseModel):
    """Décompte du jour par statut renvoyé par `GET .../appointments/daily-summary`.

    Réponse **sans PII** (§11.3) : uniquement la `date` du jour civil et des
    compteurs entiers. `by_status` porte **toutes** les valeurs de `AppointmentStatus`
    (statuts sans RDV = `0`), et `total` en est la **somme** (tous statuts, y compris
    `PENDING`). Aucun `client_id`/`client_note`/`hairdresser_id` ni ligne de RDV.
    """

    date: datetime.date = Field(examples=["2026-07-31"])
    total: int = Field(examples=[12])
    by_status: dict[str, int] = Field(
        examples=[
            {
                "PENDING": 2,
                "CONFIRMED": 5,
                "CANCELLED": 1,
                "COMPLETED": 3,
                "NO_SHOW": 1,
            }
        ]
    )


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_appointment_repository(
    session: Annotated[Session, Depends(get_session)],
) -> AppointmentRepository:
    """Dépôt de rendez-vous adossé à la session de la requête."""

    return SqlAppointmentRepository(session)


def get_catalog_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SalonCatalogRepository:
    """Dépôt de lecture publique du catalogue (salon actif + prestations actives)."""

    return SqlSalonCatalogRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité, patron #20).

    FastAPI met en cache `get_session` par requête : le dépôt de rendez-vous et le
    journal d'audit partagent donc la **même** `Session`, d'où le commit/rollback
    conjoint de la modification métier et de sa trace (§11.4).
    """

    return SqlAuditLog(session)


def get_notification_repository(
    session: Annotated[Session, Depends(get_session)],
) -> NotificationRepository:
    """Écriture des notifications adossée à la **même** session (atomicité, #45).

    FastAPI met en cache `get_session` par requête : le dépôt de rendez-vous et le
    dépôt de notifications partagent donc la **même** `Session`, d'où le commit/
    rollback conjoint de la création du RDV et de sa confirmation (US-7.1, §8.4/§11.4,
    patron `get_audit_log`).
    """

    return SqlNotificationRepository(session)


def get_salon_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SalonRepository:
    """Dépôt de salons adossé à la **même** session (atomicité, US-7.4 #48).

    Sert à résoudre le **gérant** du salon (`salon.owner_id`) pour la notification
    d'annulation destinée au salon (§8.4). `find_by_id` est un `get` par clé primaire
    **indépendant du statut** : une annulation reste possible même sur un salon devenu
    inactif (§8.3). FastAPI met en cache `get_session` par requête → même `Session` que
    le dépôt de RDV et de notifications, d'où le commit/rollback conjoint (patron
    `get_notification_repository`).
    """

    return SqlSalonRepository(session)


def get_payment_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PaymentRepository:
    """Dépôt de paiements adossé à la **même** session (lecture, file d'attente #150).

    Sert **uniquement** à résoudre les RDV `COMPLETED` couverts par un paiement
    validé (`list_paid_appointment_ids`) — lecture pure, pas d'écriture.
    """

    return SqlPaymentRepository(session)


def _now() -> datetime.datetime:
    """Instant courant **naïf** dans le repère Africa/Abidjan (UTC+0, cf. schéma)."""

    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _today() -> datetime.date:
    """Jour civil courant dans le fuseau du salon (Africa/Abidjan, convention #21)."""

    return datetime.datetime.now(SALON_TIMEZONE).date()


def _slot_response(slot: SlotRange) -> SlotResponse:
    return SlotResponse(date=slot.date, start=slot.start, end=slot.end)


def _appointment_response(appointment: Appointment) -> AppointmentResponse:
    return AppointmentResponse(
        id=appointment.id,
        salon_id=appointment.salon_id,
        client_id=appointment.client_id,
        hairdresser_id=appointment.hairdresser_id,
        date=appointment.date,
        start_time=appointment.start_time,
        end_time=appointment.end_time,
        status=appointment.status,
        client_note=appointment.client_note,
        services=[
            BookedServiceResponse(
                service_id=service.service_id,
                price_at_booking=service.price_at_booking,
            )
            for service in appointment.services
        ],
        arrived_at=appointment.arrived_at,
        started_at=appointment.started_at,
    )


def _queue_entry_response(entry: QueueEntry) -> QueueEntryResponse:
    return QueueEntryResponse(
        appointment_id=entry.appointment_id,
        client_name=entry.client_name,
        service_names=list(entry.service_names),
        hairdresser_id=entry.hairdresser_id,
        hairdresser_name=entry.hairdresser_name,
        start_time=entry.start_time,
        end_time=entry.end_time,
        status=entry.status,
        queue_status=entry.queue_status,
        arrived_at=entry.arrived_at,
        started_at=entry.started_at,
    )


def _daily_summary_response(
    summary: DailyAppointmentSummary,
) -> DailyAppointmentsSummaryResponse:
    return DailyAppointmentsSummaryResponse(
        date=summary.date,
        total=summary.total,
        by_status=dict(summary.by_status),
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    AVAILABILITY_PATH,
    response_model=AvailabilityResponse,
    summary="Lister les créneaux libres d'un salon (disponibilité, §8.1/§8.3)",
    responses={
        200: {"description": "Créneaux libres pour la date/prestation demandées"},
        404: {"description": "Salon inexistant ou non actif / prestation introuvable"},
        409: {"description": "Salon non réservable (inactif ou sans horaire)"},
        422: {"description": "Paramètres de requête invalides"},
    },
)
def get_availability(
    salon_id: uuid.UUID,
    catalog: Annotated[SalonCatalogRepository, Depends(get_catalog_repository)],
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    date: Annotated[datetime.date, Query(description="Jour ciblé (AAAA-MM-JJ)")],
    service_id: Annotated[uuid.UUID, Query(description="Prestation à réserver")],
    hairdresser_id: Annotated[
        uuid.UUID | None, Query(description="Coiffeur ciblé (optionnel)")
    ] = None,
) -> AvailabilityResponse:
    """Créneaux **libres** d'un salon `ACTIVE` pour une prestation (et un coiffeur).

    Refuse un salon non réservable (§8.3, `409`) et une prestation inactive/hors
    salon (`404`). La réponse n'expose que les créneaux libres — jamais l'identité de
    qui occupe les créneaux pris (§11.3). Les créneaux passés sont exclus.
    """

    try:
        slots = CheckAvailability(catalog, appointments).execute(
            salon_id,
            date,
            service_id,
            hairdresser_id,
            now=_now(),
        )
    except SalonNotBookable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (SalonNotFound, ServiceNotFound) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AvailabilityResponse(slots=[_slot_response(slot) for slot in slots])


@router.post(
    "/salons/{salon_id}/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Réserver un créneau (anti double-réservation garantie base, §8.1)",
    responses={
        201: {"description": "Rendez-vous créé (statut PENDING)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (réservation réservée au client)"},
        404: {"description": "Salon inexistant/non actif ou prestation introuvable"},
        409: {"description": "Créneau déjà pris (course perdue) ou salon non réservable"},
        422: {"description": "Sans prestation ou paramètres invalides"},
    },
)
def book_appointment(
    salon_id: uuid.UUID,
    payload: BookAppointmentRequest,
    catalog: Annotated[SalonCatalogRepository, Depends(get_catalog_repository)],
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    scope: Annotated[SalonScopeRepository, Depends(get_salon_scope_repository)],
    notifications: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_BOOK))
    ],
) -> AppointmentResponse:
    """Réserve un créneau pour le **client authentifié** (`client_id = principal.id`).

    Le `salon_id` vient du chemin, le `client_id` du `Principal` — jamais du corps.
    En cas de course concurrente sur le même créneau/coiffeur, la contrainte
    d'exclusion base tranche : **une seule** insertion aboutit, l'autre reçoit un
    `409` (`SlotAlreadyBooked`). À la création, une confirmation `CONFIRMATION` est
    **émise/tracée** dans la table `notifications` (§8.4/§11.4, US-7.1 #45), des
    **rappels** `REMINDER` sont **planifiés** pour chaque échéance encore future
    (`24h`/`2h`/`30min` avant le RDV, US-7.2 #46), et **le salon est notifié** par une
    ligne `NEW_BOOKING`/`IN_APP` destinée au gérant (`salon.owner_id`, US-7.3 #47) —
    **même** unité de travail que le RDV ; la **remise réelle** (push/SMS/email) reste
    différée M5+ (ADR-0006) — rien n'est envoyé, le contrat de réponse (`201`) est
    inchangé.
    """

    command = BookingCommand(
        date=payload.date,
        start_time=payload.start_time,
        service_ids=tuple(payload.service_ids),
        hairdresser_id=payload.hairdresser_id,
        client_note=payload.client_note,
    )
    try:
        appointment = BookAppointment(
            catalog, appointments, scope, notifications
        ).execute(salon_id, principal.id, command, now=_now())
    except AppointmentServiceRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (SlotAlreadyBooked, SlotUnavailable, SalonNotBookable) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (SalonNotFound, ServiceNotFound, HairdresserNotInSalon) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.get(
    "/appointments",
    response_model=list[AppointmentResponse],
    summary="Lister ses rendez-vous actifs (client, §7.1)",
    responses={
        200: {"description": "Rendez-vous actifs du client (à venir)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (lecture réservée au client)"},
    },
)
def list_my_appointments(
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_READ_OWN))
    ],
) -> list[AppointmentResponse]:
    """Liste les RDV **actifs** (`PENDING`/`CONFIRMED`) du **client authentifié**.

    Route d'**appartenance** (pas de portée salon) : le filtre `client_id =
    principal.id` est imposé serveur. Ne renvoie **que** les RDV du client demandeur
    — jamais l'identité d'un tiers (§11.3). Alimente le flux de modification (#23) ;
    l'historique complet (RDV terminés + montants) relève de US-4.4 (#30).
    """

    result = ListMyAppointments(appointments).execute(
        principal.id, statuses=CLIENT_MODIFIABLE_STATUSES
    )
    return [_appointment_response(appointment) for appointment in result]


@router.get(
    "/appointments/history",
    response_model=list[AppointmentResponse],
    summary="Consulter son historique de prestations (client, US-4.4)",
    responses={
        200: {
            "description": (
                "RDV terminés (COMPLETED) du client, du plus récent au plus ancien"
            )
        },
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (lecture réservée au client)"},
    },
)
def list_my_appointment_history(
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_READ_OWN))
    ],
) -> list[AppointmentResponse]:
    """Liste les RDV **terminés** (`COMPLETED`) du **client authentifié** (US-4.4, #30).

    Route d'**appartenance** (pas de portée salon, `APPOINTMENT_READ_OWN`) : le filtre
    `client_id = principal.id` est imposé serveur — un client ne voit **que ses
    propres** RDV, tous salons confondus, jamais ceux d'un tiers (§11.2/§11.3). Le
    statut `COMPLETED` est **décidé serveur** (`CLIENT_HISTORY_STATUSES`) : le client
    ne soumet **aucun** statut, l'acceptation « son historique de RDV terminés et rien
    d'autre » est donc garantie **par construction**. Chaque RDV porte ses prestations
    et leurs montants **figés** (`price_at_booking`). Lecture seule (RDV terminal
    §8.1) — aucune action de modification/annulation. Ordre **du plus récent au plus
    ancien**. `401`/`403` **génériques** (aucun oracle). L'écran est **vide** (≠ erreur)
    tant qu'aucun RDV n'a été passé à `COMPLETED` par le gérant (#25).
    """

    result = ListMyAppointments(appointments).execute(
        principal.id, statuses=CLIENT_HISTORY_STATUSES, newest_first=True
    )
    return [_appointment_response(appointment) for appointment in result]


@router.get(
    "/appointments/assigned",
    response_model=list[AppointmentResponse],
    summary="Lister ses RDV assignés sur une plage (planning coiffeur, §11.2)",
    responses={
        200: {
            "description": (
                "RDV assignés au coiffeur dans la plage (triés par date puis heure)"
            )
        },
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (lecture réservée au coiffeur assigné)"},
        422: {
            "description": (
                "Dates absentes/mal formées, plage trop large (> 42 j) ou statut hors "
                "énumération"
            )
        },
    },
)
def list_assigned_appointments(
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.APPOINTMENT_READ_ASSIGNED)),
    ],
    date_from: Annotated[
        datetime.date, Query(description="Premier jour inclus (AAAA-MM-JJ)")
    ],
    date_to: Annotated[
        datetime.date, Query(description="Dernier jour inclus (AAAA-MM-JJ)")
    ],
    status_filter: Annotated[
        list[AppointmentStatus] | None,
        Query(
            alias="status",
            description="Filtrer par statut (répétable) ; absent = tous statuts",
        ),
    ] = None,
) -> list[AppointmentResponse]:
    """Liste les RDV **assignés au coiffeur authentifié** sur `[date_from, date_to]`.

    Route d'**appartenance** (`require_permission(APPOINTMENT_READ_ASSIGNED)`, câblée
    ici pour la première fois) : **pas** de `salon_id` dans le chemin, **pas** de
    `require_salon_scope` — le `hairdresser_id` est **imposé serveur** (`principal.id`),
    jamais un champ soumis (anti-élévation §11.2), et le dépôt refiltre `hairdresser_id`
    en SQL (défense en profondeur). Un coiffeur ne lit **jamais** un RDV d'un collègue,
    un RDV non assigné (`hairdresser_id IS NULL`) ni un RDV d'un autre salon — c'est le
    cœur de l'AC « il ne voit que les siens ». Aucun oracle d'existence : la réponse est
    simplement la liste de **ses** RDV (vide si aucun). La plage est **inclusive** et
    **bornée** (≤ 42 j, garde de coût §12 réutilisant `MAX_PLANNING_RANGE_DAYS`) — au-delà,
    `422`, comme une date mal formée ou un `status` hors énumération. La réponse est une
    **liste plate triée** chronologiquement (tous statuts sauf filtre) ; le groupement
    par statut et la découpe jour/semaine/mois sont portés par le web (domaine #26).
    Un `CLIENT`/`MANAGER`/`ADMIN` (sans `APPOINTMENT_READ_ASSIGNED`) reçoit un `403`.
    """

    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    if (date_to - date_from).days > MAX_PLANNING_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La plage de dates demandée est trop large.",
        )

    statuses = (
        tuple(item.value for item in status_filter) if status_filter else None
    )
    result = ListAssignedAppointments(appointments).execute(
        principal.id, date_from, date_to, statuses=statuses
    )
    return [_appointment_response(appointment) for appointment in result]


@router.patch(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Modifier son rendez-vous (verrou si terminé, journalisé §11.4)",
    responses={
        200: {"description": "Rendez-vous modifié"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (modification réservée au client)"},
        404: {"description": "RDV inexistant/hors appartenance ou prestation introuvable"},
        409: {
            "description": (
                "RDV non modifiable (terminé), créneau déjà pris ou salon non réservable"
            )
        },
        422: {"description": "Sans prestation ou paramètres invalides"},
    },
)
def modify_appointment(
    appointment_id: uuid.UUID,
    payload: ModifyAppointmentRequest,
    catalog: Annotated[SalonCatalogRepository, Depends(get_catalog_repository)],
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    scope: Annotated[SalonScopeRepository, Depends(get_salon_scope_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    notifications: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_BOOK))
    ],
) -> AppointmentResponse:
    """Re-planifie **le** RDV du **client authentifié** (`client_id = principal.id`).

    Route d'appartenance : le `salon_id` vient du RDV chargé, jamais du chemin ni du
    corps (§11.2). Un RDV inexistant ou d'autrui est un `404` **indiscernable** (aucun
    oracle). Un RDV terminé est **verrouillé côté client** (`409`). En cas de course
    concurrente sur le créneau/coiffeur, la contrainte d'exclusion base tranche
    (`409`). La modification **re-planifie les rappels** sur le nouveau créneau
    (§8.4, US-7.2 #46), **notifie le salon** (une ligne `APPOINTMENT_UPDATE`/`IN_APP`
    destinée au gérant, US-7.4 #48 — remise différée M5+) et est journalisée
    `APPOINTMENT_UPDATED` (§11.4).
    """

    command = ModifyAppointmentCommand(
        date=payload.date,
        start_time=payload.start_time,
        service_ids=tuple(payload.service_ids),
        hairdresser_id=payload.hairdresser_id,
        client_note=payload.client_note,
    )
    try:
        appointment = ModifyAppointment(
            catalog, appointments, scope, audit_log, notifications
        ).execute(appointment_id, principal.id, command, now=_now())
    except AppointmentServiceRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (
        SlotAlreadyBooked,
        SlotUnavailable,
        SalonNotBookable,
        AppointmentNotModifiable,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (
        AppointmentNotFound,
        SalonNotFound,
        ServiceNotFound,
        HairdresserNotInSalon,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.post(
    "/appointments/{appointment_id}/cancellation",
    response_model=AppointmentResponse,
    summary="Annuler son rendez-vous (verrou si terminé, journalisé §11.4)",
    responses={
        200: {"description": "Rendez-vous annulé (statut CANCELLED)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (annulation réservée au client)"},
        404: {"description": "RDV inexistant ou hors appartenance"},
        409: {"description": "RDV non annulable (terminé, déjà annulé, absent)"},
    },
)
def cancel_appointment(
    appointment_id: uuid.UUID,
    payload: CancelAppointmentRequest,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    notifications: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
    salons: Annotated[SalonRepository, Depends(get_salon_repository)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_BOOK))
    ],
) -> AppointmentResponse:
    """Annule **le** RDV du **client authentifié** (`client_id = principal.id`).

    Sous-ressource d'**action** : c'est la route qui décide de la transition vers
    `CANCELLED` — le corps ne porte **jamais** `status`/`client_id`/`salon_id` (§11.2),
    seul un **motif optionnel** est saisissable (persisté, jamais journalisé). Route
    d'appartenance : le `salon_id` vient du RDV chargé. Un RDV inexistant ou d'autrui
    est un `404` **indiscernable** (aucun oracle). Un RDV terminé/terminal (déjà annulé,
    `COMPLETED`, `NO_SHOW`) est **verrouillé côté client** (`409`). L'annulation
    **libère** le créneau (le RDV quitte l'ensemble actif), **annule les rappels**
    planifiés (§8.4, US-7.2 #46) et est journalisée `APPOINTMENT_CANCELLED` (§11.4). Le
    **client et le salon** sont notifiés de l'annulation (deux lignes `CANCELLATION`
    **émises/tracées** dans `notifications`, §8.4, US-7.4 #48) — **même** unité de
    travail ; la **remise réelle** reste différée M5+ (ADR-0006), le contrat de réponse
    (`200`) est inchangé.
    """

    try:
        appointment = CancelAppointment(
            appointments, audit_log, notifications, salons
        ).execute(appointment_id, principal.id, payload.reason, now=_now())
    except AppointmentNotCancellable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except AppointmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.get(
    "/salons/{salon_id}/appointments",
    response_model=list[AppointmentResponse],
    summary="Lister les RDV d'un salon sur une plage (planning gérant, §5.2)",
    responses={
        200: {"description": "RDV du salon dans la plage (triés par date puis heure)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {
            "description": (
                "Dates absentes/mal formées, plage trop large (> 42 j) ou statut hors "
                "énumération"
            )
        },
    },
)
def list_salon_appointments(
    salon_id: uuid.UUID,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_READ_SALON))
    ],
    date_from: Annotated[
        datetime.date, Query(description="Premier jour inclus (AAAA-MM-JJ)")
    ],
    date_to: Annotated[
        datetime.date, Query(description="Dernier jour inclus (AAAA-MM-JJ)")
    ],
    status_filter: Annotated[
        list[AppointmentStatus] | None,
        Query(
            alias="status",
            description="Filtrer par statut (répétable) ; absent = tous statuts",
        ),
    ] = None,
) -> list[AppointmentResponse]:
    """Liste les RDV **du salon** sur `[date_from, date_to]` (planning gérant, #26).

    Route **salon-scopée** (`require_salon_scope` + `APPOINTMENT_READ_SALON`, câblée
    ici pour la première fois) : le `salon_id` vient du chemin, et le dépôt refiltre
    `salon_id` en SQL (défense en profondeur §11.2). Un salon hors périmètre est un
    `403` **indiscernable** (aucun oracle). La plage est **inclusive** et **bornée**
    (≤ 42 j, garde de coût §12) — au-delà, `422`, comme une date mal formée ou un
    `status` hors énumération. La réponse est une **liste plate triée**
    chronologiquement (tous statuts sauf filtre) ; le **groupement par statut** et la
    découpe jour/semaine/mois sont portés par le web.
    """

    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    if (date_to - date_from).days > MAX_PLANNING_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La plage de dates demandée est trop large.",
        )

    statuses = (
        tuple(item.value for item in status_filter) if status_filter else None
    )
    result = ListSalonAppointments(appointments).execute(
        salon_id, date_from, date_to, statuses=statuses
    )
    return [_appointment_response(appointment) for appointment in result]


@router.get(
    "/salons/{salon_id}/appointments/daily-summary",
    response_model=DailyAppointmentsSummaryResponse,
    summary="Décompte du jour par statut (dashboard gérant, US-6.1 §6)",
    responses={
        200: {"description": "Décompte du jour par statut (tous statuts présents)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Paramètre `date` mal formé"},
    },
)
def get_daily_appointments_summary(
    salon_id: uuid.UUID,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    date: Annotated[
        datetime.date | None,
        Query(description="Jour ciblé (AAAA-MM-JJ) ; absent = aujourd'hui"),
    ] = None,
) -> DailyAppointmentsSummaryResponse:
    """Décompte des RDV **du salon** pour un jour, par statut (dashboard gérant, #39).

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, câblée ici pour
    la **première fois** — premier consommateur de cette permission `MANAGER`) : le
    `salon_id` vient du chemin, et le dépôt refiltre `salon_id` en SQL (défense en
    profondeur §11.2). Un salon hors périmètre est un `403` **indiscernable** (aucun
    oracle). Le paramètre `date` est **optionnel** : absent, il vaut le jour civil
    courant (`Africa/Abidjan`, convention #21) ; mal formé, il donne un `422`. La
    réponse ne porte **que** des compteurs entiers et la date (§11.3) : le décompte est
    calculé **en base** (`GROUP BY status`), sans rapatrier de ligne de RDV ni de PII.
    `by_status` liste **tous** les statuts (statuts sans RDV = `0`) et `total` en est la
    somme (tous statuts, y compris `PENDING` non affiché dans les tuiles de l'AC).
    """

    day = date if date is not None else _today()
    summary = SummarizeDailyAppointments(appointments).execute(salon_id, day)
    return _daily_summary_response(summary)


@router.post(
    "/salons/{salon_id}/appointments/{appointment_id}/status",
    response_model=AppointmentResponse,
    summary="Piloter le statut d'un RDV du salon (gérant, verrou terminal, §11.4)",
    responses={
        200: {"description": "Statut mis à jour (transition validée)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "RDV inexistant ou hors salon (après portée)"},
        409: {
            "description": (
                "Transition interdite/terminale (ou statut changé sous garde TOCTOU)"
            )
        },
        422: {"description": "Valeur de statut hors énumération"},
    },
)
def set_appointment_status(
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    payload: SetStatusRequest,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    notifications: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
    salons: Annotated[SalonRepository, Depends(get_salon_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.APPOINTMENT_UPDATE_STATUS)),
    ],
) -> AppointmentResponse:
    """Fait passer un RDV **du salon** vers un statut cible (confirmer/refuser/…).

    Route **salon-scopée** (`require_salon_scope` + `APPOINTMENT_UPDATE_STATUS`) : le
    `salon_id` vient du chemin, l'acteur du `Principal`. Le `status` soumis est
    **doublement contraint** (énumération Pydantic → `422` ; machine à états du
    domaine → `409`) — le juge est le domaine, jamais un champ soumis (§11.2). Un RDV
    hors salon/inexistant est un `404` **indiscernable** (aucun oracle). Un RDV
    terminal (`COMPLETED`/`CANCELLED`/`NO_SHOW`) est **verrouillé** (`409`). Un refus
    gérant (`→ CANCELLED`) **annule les rappels** planifiés (§8.4, US-7.2 #46). Chaque
    changement est journalisé `APPOINTMENT_STATUS_CHANGED` (§11.4). **Chaque changement
    de statut notifie la partie concernée** (US-7.4 #48) : `→ CANCELLED` émet **deux**
    `CANCELLATION` (client + salon, §8.4) ; les autres transitions émettent **une**
    `APPOINTMENT_UPDATE` au **client** — dans la **même** unité de travail, remise
    différée M5+ (ADR-0006), contrat de réponse (`200`) inchangé.
    """

    try:
        appointment = SetAppointmentStatus(
            appointments, audit_log, notifications, salons
        ).execute(
            appointment_id,
            salon_id,
            principal.id,
            payload.status.value,
            reason=payload.reason,
        )
    except InvalidAppointmentTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except AppointmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.put(
    "/salons/{salon_id}/appointments/{appointment_id}/hairdresser",
    response_model=AppointmentResponse,
    summary="Assigner/désassigner un coiffeur à un RDV du salon (gérant, §11.4)",
    responses={
        200: {"description": "Coiffeur (dés)assigné"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {
            "description": "RDV hors salon **ou** coiffeur hors salon (indiscernables)"
        },
        409: {"description": "Conflit d'agenda (créneau pris) ou RDV terminal"},
        422: {"description": "Corps invalide"},
    },
)
def assign_appointment_hairdresser(
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    payload: AssignHairdresserRequest,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    scope_repository: Annotated[
        SalonScopeRepository, Depends(get_salon_scope_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_MANAGE))
    ],
) -> AppointmentResponse:
    """(Dés)assigne un coiffeur à un RDV **actif du salon** (gérant, `APPOINTMENT_MANAGE`).

    Route **salon-scopée** : le `salon_id` vient du chemin. Le `hairdresser_id` soumis
    est **validé contre `salon_members`** (§11.2) — sans quoi un gérant occuperait
    l'agenda d'un coiffeur d'un autre salon (l'exclusion base ne porte pas `salon_id`).
    Un RDV hors salon ou un coiffeur hors salon sont des `404` **indiscernables**. Un
    conflit d'agenda (coiffeur déjà pris) est un `409` (`SlotAlreadyBooked`, arbitré
    par l'exclusion base) ; un RDV terminal (créneau libéré) est un `409`. L'action
    est journalisée `APPOINTMENT_HAIRDRESSER_ASSIGNED` (§11.4).
    """

    try:
        appointment = AssignHairdresser(
            appointments, scope_repository, audit_log
        ).execute(appointment_id, salon_id, principal.id, payload.hairdresser_id)
    except (SlotAlreadyBooked, InvalidAppointmentTransition) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (AppointmentNotFound, HairdresserNotInSalon) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.post(
    "/salons/{salon_id}/appointments/{appointment_id}/arrival",
    response_model=AppointmentResponse,
    summary="Pointer l'arrivée d'une cliente sur un RDV du salon (gérant, §11.4, #150)",
    responses={
        200: {"description": "Arrivée pointée (idempotent)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "RDV inexistant ou hors salon (après portée)"},
        409: {"description": "RDV non confirmé (pas encore/plus dans un état pointable)"},
    },
)
def mark_appointment_arrived(
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.APPOINTMENT_UPDATE_STATUS)),
    ],
) -> AppointmentResponse:
    """Pose `arrived_at` sur un RDV `CONFIRMED` **du salon** — idempotent.

    Un double appel n'écrase **pas** l'horodatage déjà posé (pas de second clic
    accidentel qui décalerait l'heure d'arrivée). Un RDV hors salon/inexistant
    est un `404` indiscernable ; un RDV non `CONFIRMED` (pas encore confirmé,
    déjà réalisé/annulé) est un `409`. Journalisé `APPOINTMENT_ARRIVED`.
    """

    try:
        appointment = MarkAppointmentArrived(appointments, audit_log).execute(
            appointment_id, salon_id, principal.id
        )
    except InvalidAppointmentTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except AppointmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.post(
    "/salons/{salon_id}/appointments/{appointment_id}/start",
    response_model=AppointmentResponse,
    summary="Démarrer la prestation d'un RDV du salon (gérant, §11.4, #150)",
    responses={
        200: {"description": "Prestation démarrée (idempotent)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "RDV inexistant ou hors salon (après portée)"},
        409: {
            "description": (
                "RDV non confirmé, arrivée non pointée, ou aucune coiffeuse assignée"
            )
        },
    },
)
def start_appointment_service(
    salon_id: uuid.UUID,
    appointment_id: uuid.UUID,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.APPOINTMENT_UPDATE_STATUS)),
    ],
) -> AppointmentResponse:
    """Pose `started_at` sur un RDV `CONFIRMED` **du salon** — idempotent.

    Exige l'arrivée déjà pointée **et** une coiffeuse déjà assignée (`409`
    sinon) — une prestation « en cours » sans arrivée ni coiffeuse n'a pas de
    sens métier. Un RDV hors salon/inexistant est un `404` indiscernable.
    Journalisé `APPOINTMENT_STARTED`.
    """

    try:
        appointment = StartAppointmentService(appointments, audit_log).execute(
            appointment_id, salon_id, principal.id
        )
    except (
        AppointmentArrivalRequired,
        AppointmentHairdresserRequired,
        InvalidAppointmentTransition,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except AppointmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _appointment_response(appointment)


@router.get(
    "/salons/{salon_id}/queue",
    response_model=list[QueueEntryResponse],
    summary="Lister la file d'attente du salon pour un jour donné (gérant, #150)",
    responses={
        200: {"description": "File d'attente du jour, triée par heure de RDV"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Paramètre de date invalide"},
    },
)
def list_salon_queue(
    salon_id: uuid.UUID,
    appointments: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
    ],
    payments: Annotated[PaymentRepository, Depends(get_payment_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_READ_SALON))
    ],
    day: Annotated[
        datetime.date | None,
        Query(description="Jour ciblé (AAAA-MM-JJ) ; défaut aujourd'hui"),
    ] = None,
) -> list[QueueEntryResponse]:
    """Liste les RDV `CONFIRMED`/`COMPLETED` **du salon** pour `day` (défaut aujourd'hui).

    Portée « RDV existants uniquement » (§ décision produit) : ni `PENDING` non
    confirmé, ni `CANCELLED`/`NO_SHOW`. `queue_status` est **dérivé**
    (`waiting`/`in_progress`/`completed`/`paid`) — « payée » reflète un paiement
    **réellement validé** (réutilise le flux d'encaissement #33/#34), jamais un
    drapeau propre au RDV. Lecture pure, aucun audit (cohérent avec le
    Dashboard #148).
    """

    target_day = day if day is not None else _today()
    entries = ListSalonQueue(appointments, payments).execute(salon_id, target_day)
    return [_queue_entry_response(entry) for entry in entries]


__all__ = ["router", "AVAILABILITY_PATH"]
