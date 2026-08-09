"""File d'attente du salon — pointage réel + statut dérivé (domaine pur, #150).

Domaine **pur** (aucune I/O, ni FastAPI ni SQLAlchemy — ADR-0008) de la file
d'attente du Dashboard Manager. Il lève les ambiguïtés de la fonctionnalité en
**définitions dérivées de faits réels**, dans l'esprit du Dashboard Manager
(#148, `domain/dashboard.py`) :

- **« En attente » / « En cours »** sont **dérivés** de la présence de
  `started_at` (colonne `appointments.started_at`, migration 0011) — aucune
  valeur `IN_PROGRESS` n'étend `AppointmentStatus` (`domain/appointment.py`).
  `arrived_at` est **informatif** (affiché, jamais lui-même une étape
  distincte) : la file ne comporte que deux « avant complétion » (attente,
  en cours), conformément à la décision produit retenue.
- **« Terminée » / « Payée »** sont **dérivées** du couple `(status, paiement
  validé)` : un RDV `COMPLETED` sans paiement validé est « Terminée », avec un
  paiement validé (encaissement existant, #33/#34) il est « Payée ». Aucun
  drapeau `paid` nouveau n'est stocké : le paiement validé **est** la source de
  vérité (réutilise le flux d'encaissement existant, patron « dérivé-plutôt-
  que-stocké » d'ADR-0039).

`QueueEntry` est l'objet-valeur de lecture : il émet **uniquement** des noms
d'affichage (`client_name`/`service_names`/`hairdresser_name` = `users.
full_name`/`services.name`, patron #43/#36) — jamais de contact ni
d'identifiant client. `appointment_id`/`hairdresser_id` restent exposés (UUID
**opaques**, non-PII) : le gérant en a besoin pour agir (pointer, assigner,
encaisser) — à la différence des lectures *counts-only* (§11.3, ADR-0026).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Literal

from coiflink_api.domain.enums import AppointmentStatus

# Statut dérivé exposé par la file d'attente (jamais stocké — voir docstring
# module). Ordre déclaré = ordre du cycle de vie attendu par le gérant.
QueueStatus = Literal["waiting", "in_progress", "completed", "paid"]

QUEUE_STATUSES: tuple[QueueStatus, ...] = ("waiting", "in_progress", "completed", "paid")

# Statuts de RDV retenus par la file d'attente (§ décision produit « RDV
# existants uniquement ») : les RDV confirmés du jour (à pointer) **et** les
# RDV réalisés du jour (Terminée/Payée) — jamais `PENDING` (non confirmé),
# `CANCELLED` ni `NO_SHOW` (n'occupent plus la file).
QUEUE_APPOINTMENT_STATUSES: tuple[str, ...] = (
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.COMPLETED.value,
)


def derive_queue_status(
    status: str, *, started_at: datetime.datetime | None, is_paid: bool
) -> QueueStatus:
    """Dérive le statut de file d'un RDV `CONFIRMED`/`COMPLETED` (fonction pure).

    Un RDV `COMPLETED` est « payée » si un paiement **validé** lui est déjà lié,
    sinon « terminée » — la distinction ne dépend que du paiement, jamais d'un
    champ propre au RDV. Un RDV encore `CONFIRMED` est « en cours » dès que
    `started_at` est posé (pointage manuel du gérant), sinon « en attente ».
    Un `status` hors `QUEUE_APPOINTMENT_STATUSES` n'est pas un cas valide de ce
    domaine (la lecture ne les sélectionne jamais) ; retombe sur « en attente »
    plutôt que de lever, cette fonction n'ayant pas à revalider l'appelant.
    """

    if status == AppointmentStatus.COMPLETED.value:
        return "paid" if is_paid else "completed"
    if started_at is not None:
        return "in_progress"
    return "waiting"


@dataclass(frozen=True)
class QueueAppointmentRow:
    """Ligne **brute** renvoyée par `AppointmentRepository.list_queue_details` (#150).

    Porte tout ce que le dépôt de rendez-vous sait résoudre seul (identités,
    horaires, pointage) — **sans** `queue_status` : le statut « payée » dépend
    d'un paiement, résolu séparément par `PaymentRepository`. C'est le cas
    d'usage (`ListSalonQueue`) qui combine les deux lectures et appelle
    `derive_queue_status` pour produire un `QueueEntry`.
    """

    appointment_id: uuid.UUID
    client_name: str | None
    service_names: tuple[str, ...]
    hairdresser_id: uuid.UUID | None
    hairdresser_name: str | None
    start_time: datetime.time
    end_time: datetime.time
    status: str
    arrived_at: datetime.datetime | None
    started_at: datetime.datetime | None


@dataclass(frozen=True)
class QueueEntry:
    """Une ligne **finalisée** de la file d'attente du salon (#150).

    `hairdresser_id` (opaque, non-PII) est exposé — à la différence des
    lectures *counts-only* — car le gérant agit directement sur la ligne
    (assigner une coiffeuse disponible) ; `hairdresser_name` porte le nom
    d'affichage pour la lecture humaine (patron #43/#36). `queue_status` est
    **dérivé** (`derive_queue_status`), jamais stocké.
    """

    appointment_id: uuid.UUID
    client_name: str | None
    service_names: tuple[str, ...]
    hairdresser_id: uuid.UUID | None
    hairdresser_name: str | None
    start_time: datetime.time
    end_time: datetime.time
    status: str
    queue_status: QueueStatus
    arrived_at: datetime.datetime | None
    started_at: datetime.datetime | None


def finalize_queue_entry(row: QueueAppointmentRow, *, is_paid: bool) -> QueueEntry:
    """Combine une ligne brute + le fait payé/non-payé en `QueueEntry` (pur)."""

    return QueueEntry(
        appointment_id=row.appointment_id,
        client_name=row.client_name,
        service_names=row.service_names,
        hairdresser_id=row.hairdresser_id,
        hairdresser_name=row.hairdresser_name,
        start_time=row.start_time,
        end_time=row.end_time,
        status=row.status,
        queue_status=derive_queue_status(
            row.status, started_at=row.started_at, is_paid=is_paid
        ),
        arrived_at=row.arrived_at,
        started_at=row.started_at,
    )


__all__ = [
    "QueueStatus",
    "QUEUE_STATUSES",
    "QUEUE_APPOINTMENT_STATUSES",
    "derive_queue_status",
    "QueueAppointmentRow",
    "QueueEntry",
    "finalize_queue_entry",
]
