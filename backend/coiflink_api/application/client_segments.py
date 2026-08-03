"""Cas d'usage : **segmentation des clients** d'un salon sur une période (US-6.4, #42).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`AppointmentRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il matérialise le
critère d'acceptation #42 :

> Segmentation des clients sur une période donnée (§6 US-6.4).

`SummarizeActiveClients` est une **lecture pure** (calquée sur `SummarizeServiceDemand`
#41, `SummarizeRevenue` #40 et `SummarizeDailyAppointments` #39) : il délègue
l'**agrégat en base** (`GROUP BY client_id`, `MIN(appointment_date)` + deux comptes
filtrés) au port `segment_active_clients`, puis classe le résultat via la fonction de
domaine pure `classify_client_segments` (trois segments mutuellement exclusifs). Comme
les autres lectures du tableau de bord (#39/#40/#41) et financières (#34/#35/#37), il
**ne journalise aucune action** §11.4 — la consultation d'un KPI reste bornée par la
permission `STATS_READ_SALON` (le `MANAGER` seul).

**« Réalisées uniquement » par construction (§8.1).** Le filtre de statut est **décidé
serveur** (`HISTORY_STATUSES == (COMPLETED,)`, la « visite » de #29) et jamais soumis
par l'appelant : un RDV `CANCELLED`/`NO_SHOW`/`PENDING`/`CONFIRMED` ne compte pas comme
une visite. La période `[date_from, date_to]` est **résolue** (deux dates non nulles)
par l'adapter entrant (défaut = mois civil courant), comme #40 résout `date`.
"""

from __future__ import annotations

import datetime
import uuid

from coiflink_api.application.ports.appointment_repository import (
    AppointmentRepository,
)
from coiflink_api.domain.client_segments import (
    ClientSegments,
    classify_client_segments,
)
from coiflink_api.domain.visit import HISTORY_STATUSES


class SummarizeActiveClients:
    """Segmentation des clients d'un salon sur une période (lecture — pas d'audit, #42).

    `execute(salon_id, *, date_from, date_to)` délègue l'agrégat `GROUP BY client_id`
    au port (`segment_active_clients`, isolation §11.2 ré-affirmée en SQL) en
    **imposant** `HISTORY_STATUSES` (RDV `COMPLETED` — « réalisées uniquement », jamais
    un statut soumis par l'appelant), puis classe le résultat en **trois segments**
    (`classify_client_segments`). La **portée salon** est assurée par la garde HTTP
    `require_salon_scope`, en défense en profondeur du filtre SQL. Lecture pure : aucune
    écriture, aucun audit (§11.4). Aucune ligne ni PII rapatriée — le port renvoie
    seulement des profils **agrégés et anonymes** (sans `client_id`).
    """

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> ClientSegments:
        profiles = self._appointments.segment_active_clients(
            salon_id,
            statuses=HISTORY_STATUSES,  # (COMPLETED,) — une « visite » réalisée (#29/§8.1)
            date_from=date_from,
            date_to=date_to,
        )
        return classify_client_segments(
            profiles,
            date_from=date_from,
            date_to=date_to,
        )


__all__ = ["SummarizeActiveClients"]
