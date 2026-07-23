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

Traductions d'erreurs de domaine → HTTP : `SlotAlreadyBooked` (course perdue) /
`SlotUnavailable` / `SalonNotBookable` / `AppointmentNotModifiable` (verrou terminé)
→ **409** ; `AppointmentServiceRequired` → **422** ; `ServiceNotFound` /
`SalonNotFound` / `HairdresserNotInSalon` / `AppointmentNotFound` (inexistant ou hors
appartenance) → **404** *(après portée/appartenance)*.

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
)
from coiflink_api.adapters.outbound.persistence.appointment_repository import (
    SqlAppointmentRepository,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    SqlSalonCatalogRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.appointments import (
    BookAppointment,
    BookingCommand,
    CheckAvailability,
    ListMyAppointments,
    ModifyAppointment,
    ModifyAppointmentCommand,
)
from coiflink_api.application.ports.appointment_repository import AppointmentRepository
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.salon_catalog_repository import (
    SalonCatalogRepository,
)
from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.domain.appointment import (
    Appointment,
    CLIENT_MODIFIABLE_STATUSES,
)
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.errors import (
    AppointmentNotFound,
    AppointmentNotModifiable,
    AppointmentServiceRequired,
    HairdresserNotInSalon,
    SalonNotBookable,
    SalonNotFound,
    ServiceNotFound,
    SlotAlreadyBooked,
    SlotUnavailable,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(tags=["appointments"])

# Chemin **public** de la disponibilité (ajouté à `security.PUBLIC_ROUTE_PATHS`).
# Exposé ici pour rester la source unique du littéral (router + composition root).
AVAILABILITY_PATH = "/catalog/salons/{salon_id}/availability"


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


class BookedServiceResponse(BaseModel):
    """Prestation réservée : identifiant + prix figé à la réservation."""

    service_id: uuid.UUID
    price_at_booking: decimal.Decimal


class AppointmentResponse(BaseModel):
    """Rendez-vous créé, renvoyé par l'API (statut `PENDING` à la création)."""

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


def _now() -> datetime.datetime:
    """Instant courant **naïf** dans le repère Africa/Abidjan (UTC+0, cf. schéma)."""

    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


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
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_BOOK))
    ],
) -> AppointmentResponse:
    """Réserve un créneau pour le **client authentifié** (`client_id = principal.id`).

    Le `salon_id` vient du chemin, le `client_id` du `Principal` — jamais du corps.
    En cas de course concurrente sur le même créneau/coiffeur, la contrainte
    d'exclusion base tranche : **une seule** insertion aboutit, l'autre reçoit un
    `409` (`SlotAlreadyBooked`).
    """

    command = BookingCommand(
        date=payload.date,
        start_time=payload.start_time,
        service_ids=tuple(payload.service_ids),
        hairdresser_id=payload.hairdresser_id,
        client_note=payload.client_note,
    )
    try:
        appointment = BookAppointment(catalog, appointments, scope).execute(
            salon_id, principal.id, command, now=_now()
        )
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
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_BOOK))
    ],
) -> AppointmentResponse:
    """Re-planifie **le** RDV du **client authentifié** (`client_id = principal.id`).

    Route d'appartenance : le `salon_id` vient du RDV chargé, jamais du chemin ni du
    corps (§11.2). Un RDV inexistant ou d'autrui est un `404` **indiscernable** (aucun
    oracle). Un RDV terminé est **verrouillé côté client** (`409`). En cas de course
    concurrente sur le créneau/coiffeur, la contrainte d'exclusion base tranche
    (`409`). La modification est journalisée `APPOINTMENT_UPDATED` (§11.4).
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
            catalog, appointments, scope, audit_log
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


__all__ = ["router", "AVAILABILITY_PATH"]
