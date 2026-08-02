"""Cas d'usage : **prestations les plus demandées** d'un salon (US-6.3, #41).

Tranche applicative hexagonale : ce cas d'usage ne dépend que d'un **port**
(`AppointmentRepository`) — aucune dépendance FastAPI/SQLAlchemy. Il matérialise le
critère d'acceptation #41 :

> Top prestations **par volume et par revenu** généré (§6 US-6.3).

`SummarizeServiceDemand` est une **lecture pure** (calquée sur `SummarizeRevenue`
#40 et `SummarizeDailyAppointments` #39) : il délègue l'**agrégat en base**
(`GROUP BY service_id`, `COUNT` volume + `SUM(price_at_booking)` revenu) au port
`demand_by_service`, puis ordonne le résultat via la fonction de domaine pure
`rank_service_demand` (deux classements déterministes). Comme les autres lectures
du tableau de bord (#39/#40) et financières (#34/#35/#37), il **ne journalise
aucune action** §11.4 — la consultation d'un KPI reste bornée par la permission
`STATS_READ_SALON` (le `MANAGER` seul).

**« Réalisées uniquement » par construction (§8.1, spec §Open Questions 2).** Le
filtre de statut est **décidé serveur** (`REVENUE_STATUSES == (COMPLETED,)`) et
jamais soumis par l'appelant : un RDV `CANCELLED`/`NO_SHOW`/`PENDING`/`CONFIRMED`
ne pèse ni en volume ni en revenu. Volume et revenu partagent ainsi la **même
population** (un classement cohérent), aligné §8.1 et #31.
"""

from __future__ import annotations

import datetime
import uuid

from coiflink_api.application.ports.appointment_repository import (
    AppointmentRepository,
)
from coiflink_api.domain.appointment import REVENUE_STATUSES
from coiflink_api.domain.service_demand import (
    ServiceDemandRanking,
    rank_service_demand,
)


class SummarizeServiceDemand:
    """Classement des prestations d'un salon par volume et revenu (lecture — pas d'audit).

    `execute(salon_id, date_from=?, date_to=?)` délègue l'agrégat `GROUP BY
    service_id` au port (`demand_by_service`, isolation §11.2 ré-affirmée en SQL) en
    **imposant** `REVENUE_STATUSES` (RDV `COMPLETED` — « réalisées uniquement »,
    jamais un statut soumis par l'appelant), puis ordonne le résultat en **deux
    classements** déterministes (`rank_service_demand`). La **portée salon** est
    assurée par la garde HTTP `require_salon_scope`, en défense en profondeur du
    filtre SQL. Lecture pure : aucune écriture, aucun audit (§11.4). Aucune ligne ni
    PII rapatriée — le port renvoie seulement des prestations agrégées.
    """

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> ServiceDemandRanking:
        rows = self._appointments.demand_by_service(
            salon_id,
            statuses=REVENUE_STATUSES,
            date_from=date_from,
            date_to=date_to,
        )
        return rank_service_demand(
            rows,
            date_from=date_from,
            date_to=date_to,
        )


__all__ = ["SummarizeServiceDemand"]
