"""Cas d'usage : **performance des coiffeurs** d'un salon sur une période (US-6.5, #43).

Tranche applicative hexagonale : ce cas d'usage ne dépend que de **deux ports**
(`QueueTicketRepository` **et** `CashJournalRepository`) — aucune dépendance
FastAPI/SQLAlchemy. Il matérialise le critère d'acceptation #43 :

> Indicateurs par coiffeur cohérents avec la file d'attente et la caisse (§6 US-6.5).

`SummarizeHairdresserPerformance` est une **lecture pure** (calquée sur
`SummarizeServiceDemand` #41) : il délègue les
**agrégats en base** (`GROUP BY hairdresser_id`) aux dépôts, **fusionne** les deux
sources par `hairdresser_id`, puis applique la fonction de domaine pure
`rank_hairdresser_performance` (calcul du taux + ordre déterministe). Comme les
autres lectures du tableau de bord (#39/#40/#41/#42), il **ne journalise aucune
action** §11.4 — la consultation d'un KPI reste bornée par la permission
`STATS_READ_SALON` (le `MANAGER` seul).

**Chaque indicateur cohérent avec son autorité** (cœur de l'AC). Prestations
réalisées et taux d'annulation dérivent **de la file d'attente** (`queue_tickets`
assignés, via `performance_by_hairdresser`) ; le CA dérive **de la caisse** (net
`cash_journal` attribué par ticket, via `net_revenue_by_hairdresser`).

**« Réalisé » & « annulé » imposés serveur (§8.1).** Les statuts sont **décidés
côté serveur** (`_COMPLETED_STATUSES == ("done",)` pour le réalisé,
`_CANCELLED_STATUSES == ("expired",)` pour l'équivalent walk-in de l'annulation — un
ticket `expired` est un ticket auquel le client n'a jamais donné suite) et jamais
soumis par l'appelant. La période `[date_from, date_to]` est **résolue** (deux dates
non nulles) par l'adapter entrant (défaut = mois civil courant), comme #42.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.application.ports.queue_ticket_repository import (
    QueueTicketRepository,
)
from coiflink_api.domain.hairdresser_performance import (
    HairdresserActivity,
    HairdresserPerformanceReport,
    rank_hairdresser_performance,
)

_COMPLETED_STATUSES: tuple[str, ...] = ("done",)
_CANCELLED_STATUSES: tuple[str, ...] = ("expired",)


class SummarizeHairdresserPerformance:
    """Performance des coiffeurs d'un salon sur une période (lecture — pas d'audit, #43).

    `execute(salon_id, *, date_from, date_to)` délègue l'agrégat file d'attente
    `GROUP BY hairdresser_id` au port `performance_by_hairdresser` (isolation §11.2
    ré-affirmée en SQL) en **imposant** les tickets `done` (prestations réalisées) et
    `expired` (numérateur du taux — équivalent walk-in de l'annulation), puis
    **greffe** le CA net attribué par la caisse (`net_revenue_by_hairdresser`),
    **fusionné par `hairdresser_id`** (`0.00` si le coiffeur n'a aucun paiement
    attribué). La liste des coiffeurs vient **de la file d'attente** : un coiffeur
    avec du CA mais aucun ticket assigné dans la fenêtre n'apparaît pas (cohérence
    « liste = coiffeurs actifs », spec §Open Questions 10). Le calcul du taux et
    l'ordre du classement sont délégués au domaine (`rank_hairdresser_performance`).
    Lecture pure : aucune écriture, aucun audit (§11.4). Aucune PII **client** ni
    contact employé n'est rapatriée — seulement des compteurs, des montants et le nom
    d'affichage de l'employé.
    """

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        cash_journal_repository: CashJournalRepository,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._cash_journal = cash_journal_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> HairdresserPerformanceReport:
        counts = self._tickets.performance_by_hairdresser(
            salon_id,
            date_from=date_from,
            date_to=date_to,
            completed_statuses=_COMPLETED_STATUSES,  # ("done",) — §8.1, réalisé
            cancelled_statuses=_CANCELLED_STATUSES,  # ("expired",) — décidé serveur
        )
        net_by_hairdresser = self._cash_journal.net_revenue_by_hairdresser(
            salon_id,
            date_from=date_from,
            date_to=date_to,
        )
        activities = tuple(
            HairdresserActivity(
                hairdresser_id=row.hairdresser_id,
                name=row.name,
                services_completed=row.services_completed,
                # CA net attribué (caisse) fusionné par `hairdresser_id` ; `0.00` si
                # le coiffeur n'a aucun paiement attribué sur la période.
                revenue=net_by_hairdresser.get(
                    row.hairdresser_id, decimal.Decimal("0.00")
                ),
                cancelled_count=row.cancelled_count,
                total_count=row.total_count,
            )
            for row in counts
        )
        return rank_hairdresser_performance(
            activities,
            date_from=date_from,
            date_to=date_to,
        )


__all__ = ["SummarizeHairdresserPerformance"]
