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


@dataclass(frozen=True)
class AppointmentUpdate:
    """Champs re-planifiés d'un rendez-vous existant (sémantique *replace*, US-3.2, #23).

    Porte la **cible** d'une modification client : nouvelle date/créneau, coiffeur,
    commentaire et **jeu complet** de prestations (durée/prix figé recapturés). Ne
    porte **jamais** `salon_id`/`client_id`/`status` — le `salon_id` provient du RDV
    chargé, `client_id`/`status` restent inchangés (anti-élévation §11.2). `end_time`
    est calculé serveur (`compute_end_time`), jamais lu du corps.
    """

    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    hairdresser_id: uuid.UUID | None
    client_note: str | None
    services: tuple[BookedService, ...]


# Statuts d'un rendez-vous que **le client** peut encore modifier (§8.1, #23). Un
# RDV `COMPLETED` est explicitement verrouillé côté client par le PRD §8.1 (« ne
# peut plus être modifié, sauf par le gérant ») ; par extension, un RDV `CANCELLED`
# ou `NO_SHOW` est **terminal** et n'a pas de sens à modifier. Seuls les états
# **actifs** (occupant un créneau) restent modifiables — miroir de la clause `WHERE`
# de l'exclusion `ex_appointments_hairdresser_slot`. L'exception « gérant » d'un RDV
# terminé relève de US-3.4 (#25), hors périmètre de #23.
CLIENT_MODIFIABLE_STATUSES: tuple[str, ...] = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
)


def is_client_modifiable(status: str) -> bool:
    """Vrai si un RDV de ce `status` est encore modifiable **par le client** (§8.1).

    Fonction **pure** (aucune I/O) : le verrou d'état est décidé ici et ré-affirmé à
    l'écriture (UPDATE conditionnel du dépôt). Un statut inconnu est refusé par
    construction (absent de `CLIENT_MODIFIABLE_STATUSES`) — jamais un accès par défaut.
    """

    return status in CLIENT_MODIFIABLE_STATUSES


# Statuts d'un rendez-vous que **le client** peut encore **annuler** (§8.1, #24). Le
# jeu coïncide aujourd'hui avec `CLIENT_MODIFIABLE_STATUSES` (états actifs occupant un
# créneau), mais on le **nomme distinctement** : la règle d'annulation et la règle de
# modification sont deux décisions métier séparées, susceptibles de diverger (un salon
# pourrait un jour autoriser l'annulation dans des états où la modification est fermée,
# ou l'inverse). Un RDV `COMPLETED`/`CANCELLED`/`NO_SHOW` est terminal et **non
# annulable par le client** (l'exception gérant relève de US-3.4/#25, hors périmètre).
CLIENT_CANCELLABLE_STATUSES: tuple[str, ...] = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
)


def is_client_cancellable(status: str) -> bool:
    """Vrai si un RDV de ce `status` est encore annulable **par le client** (§8.1, #24).

    Fonction **pure** (aucune I/O) : le verrou d'état est décidé ici et ré-affirmé à
    l'écriture (UPDATE conditionnel du dépôt, garde TOCTOU). Un statut inconnu est
    refusé par construction (absent de `CLIENT_CANCELLABLE_STATUSES`).
    """

    return status in CLIENT_CANCELLABLE_STATUSES


# Longueur maximale de robustesse d'un motif d'annulation (texte de confort, jamais
# journalisé). Au-delà, le motif est **tronqué** silencieusement (le motif est un
# confort ; on ne bloque jamais une annulation légitime pour un motif trop long).
MAX_CANCELLATION_REASON_LENGTH = 500


def normalize_cancellation_reason(raw: str | None) -> str | None:
    """Normalise le motif d'annulation optionnel (fonction **pure**, §11.3, #24).

    Retire les espaces de bordure ; `None` ou chaîne vide/blanche devient `None`
    (« pas de motif »). Un motif au-delà de `MAX_CANCELLATION_REASON_LENGTH` est
    **tronqué** (robustesse anti-abus, sans erreur bloquante). Le motif est une
    donnée cliente : il est **persisté** sur la ligne du RDV mais **jamais**
    journalisé (ni `logging`, ni métadonnées d'audit).
    """

    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return trimmed[:MAX_CANCELLATION_REASON_LENGTH]


# Statuts d'un rendez-vous **comptabilisés dans le chiffre d'affaires** (§8.1, #24).
# ⚠️ Aucun calcul de CA n'est livré au MVP courant (encaissement M4 #28–#38, KPI
# gérant M5 US-6.2). Ce prédicat **ne calcule pas** de CA : il **matérialise
# l'invariant** que les futures agrégations (M4/M5) devront honorer — le CA ne compte
# que les RDV **réalisés** (`COMPLETED`, ou plus tard les paiements validés) et
# **jamais** un RDV `CANCELLED`/`NO_SHOW` ni un RDV encore actif non réalisé
# (`PENDING`/`CONFIRMED`). L'annulation (#24) rend donc le RDV mécaniquement exclu du CA.
REVENUE_STATUSES: tuple[str, ...] = (AppointmentStatus.COMPLETED.value,)


def counts_towards_revenue(status: str) -> bool:
    """Vrai si un RDV de ce `status` compte dans le chiffre d'affaires (§8.1, #24).

    **N'implémente aucun calcul de CA** (non livré au MVP) : prédicat de domaine
    **pur** qui documente et verrouille l'invariant « un RDV `CANCELLED` n'est jamais
    comptabilisé » — à réutiliser par les issues d'encaissement/KPI (M4/M5). Retourne
    `False` pour `CANCELLED` (et tout état non réalisé), garantissant par construction
    l'exclusion des RDV annulés dès que le CA sera calculé.
    """

    return status in REVENUE_STATUSES


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
    "AppointmentUpdate",
    "CLIENT_MODIFIABLE_STATUSES",
    "is_client_modifiable",
    "CLIENT_CANCELLABLE_STATUSES",
    "is_client_cancellable",
    "MAX_CANCELLATION_REASON_LENGTH",
    "normalize_cancellation_reason",
    "REVENUE_STATUSES",
    "counts_towards_revenue",
    "require_services",
    "validate_booking_window",
    "compute_end_time",
]
