"""Entités et règles de domaine « rendez-vous » (domaine pur, US-3.7, #21).

Ces `dataclass` gelées et fonctions découplent l'application du modèle ORM
SQLAlchemy (`adapters/outbound/persistence/models.py::Appointment` /
`AppointmentService`) : conformément à l'hexagonal (ADR-0008), ni `domain/` ni
`application/` n'importent FastAPI ni SQLAlchemy.

Invariants portés ici (PRD §8.1) :

- **≥ 1 prestation** par rendez-vous (`require_services`) — matérialisé au niveau
  base par l'insertion transactionnelle du RDV **et** de ses lignes
  `appointment_services` dans la même unité de travail ;
- **fenêtre horaire cohérente** (`end_time > start_time`, miroir du `CHECK
  time_order` du schéma) ;
- **prix figé à la réservation** : chaque `BookedService` porte `price_at_booking`
  (un changement de tarif ne réécrit pas l'historique).

La garantie **anti double-réservation** n'est **pas** une règle de ce module :
elle est portée par la contrainte d'exclusion PostgreSQL (schéma #3). Le chemin
d'écriture se contente de la traduire (`SlotAlreadyBooked`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.availability import add_minutes
from coiflink_api.domain.enums import AppointmentStatus
from coiflink_api.domain.errors import AppointmentServiceRequired, SlotUnavailable


@dataclass(frozen=True)
class BookedService:
    """Prestation réservée dans un rendez-vous, avec son **prix figé**.

    `price_at_booking` est capturé au moment de la réservation depuis le tarif
    courant de la prestation (§ `AppointmentService`) : un changement de prix
    ultérieur ne modifie pas les RDV déjà pris.
    """

    service_id: uuid.UUID
    price_at_booking: decimal.Decimal


@dataclass(frozen=True)
class AppointmentToCreate:
    """Intention de création d'un rendez-vous (`salon_id`/`client_id` imposés serveur).

    `salon_id` provient de la portée/chemin et `client_id` du `Principal`
    authentifié — **jamais** du corps de requête (anti-élévation §11.2, miroir de
    `owner_id` #15 et `salon_id` #17). `status` force `PENDING` à la création.
    `services` porte **au moins une** `BookedService` (validé avant écriture).
    """

    salon_id: uuid.UUID
    client_id: uuid.UUID
    hairdresser_id: uuid.UUID | None
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    services: tuple[BookedService, ...]
    client_note: str | None = None
    status: str = AppointmentStatus.PENDING.value


@dataclass(frozen=True)
class Appointment:
    """Rendez-vous persisté (entité de lecture, PRD §9.4)."""

    id: uuid.UUID
    salon_id: uuid.UUID
    client_id: uuid.UUID
    hairdresser_id: uuid.UUID | None
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    status: str
    client_note: str | None
    created_at: datetime.datetime
    services: tuple[BookedService, ...] = ()


def require_services(services: tuple[BookedService, ...]) -> None:
    """Impose la règle §8.1 « ≥ 1 prestation » ; lève `AppointmentServiceRequired`.

    Le rendez-vous sans prestation n'a pas de sens métier (rien à réaliser, rien à
    facturer). La cardinalité est aussi garantie au niveau base par l'insertion
    conjointe RDV + jonctions, mais on la refuse **avant** toute écriture.
    """

    if not services:
        raise AppointmentServiceRequired(
            "Un rendez-vous doit comporter au moins une prestation."
        )


def validate_booking_window(
    start_time: datetime.time, end_time: datetime.time
) -> None:
    """Vérifie `end_time > start_time` (miroir du `CHECK time_order` du schéma).

    La fenêtre est normalement calculée côté serveur (`compute_end_time`) et donc
    toujours valide ; ce garde-fou refuse une fenêtre incohérente (`SlotUnavailable`)
    avant l'écriture plutôt que de laisser échouer le `CHECK` base.
    """

    if end_time <= start_time:
        raise SlotUnavailable("Le créneau demandé est invalide.")


def compute_end_time(start_time: datetime.time, total_minutes: int) -> datetime.time:
    """Heure de fin d'un RDV = `start_time + total_minutes` (somme des durées).

    Une réservation multi-prestations occupe un créneau continu dont la longueur
    est la **somme** des durées (§ Open Questions du spec). Lève `SlotUnavailable`
    si le créneau franchirait minuit (non modélisable par le schéma intra-journée).
    """

    end_time = add_minutes(start_time, total_minutes)
    if end_time is None:
        raise SlotUnavailable("Le créneau demandé dépasse la journée d'ouverture.")
    return end_time


__all__ = [
    "BookedService",
    "AppointmentToCreate",
    "Appointment",
    "require_services",
    "validate_booking_window",
    "compute_end_time",
]
