"""Cas d'usage : **Dashboard Manager — activité du salon** (lecture pure, #148).

Tranche applicative hexagonale (ADR-0008) : ces cas d'usage ne dépendent que de
**ports** (`QueueTicketRepository`, `CashJournalRepository`, `PaymentRepository`)
— aucune dépendance FastAPI/SQLAlchemy. Ils **consolident** au-dessus du socle KPI
existant (#39–#43/#36) l'écran d'activité de l'issue #148, rebranché sur les tickets
walk-in (pivot exclusif, jalon M7) :

- `SummarizeDashboardKpis` — les **4 cartes KPI** (clients en attente, prestations en
  cours, chiffre d'affaires, nombre de clientes) avec **évolution** vs période
  précédente ; statuts **imposés serveur**. Calcule aussi `attendance_today`/
  `revenue_this_week` — bornes **fixes** (jour/semaine glissants), pour les cartes
  « À surveiller » du tableau de bord, indépendantes du filtre de période.
- `ListInProgressServices` — la **liste des tickets en cours** (noms d'affichage).
- `SummarizeRevenueSeries` / `SummarizeAttendanceSeries` — les deux **séries
  temporelles** des graphiques (CA net, fréquentation), buckets complétés à `0`.
- `ListRecentActivity` — la **timeline** « Transactions récentes » (§7.2), bornée aux
  paiements **réellement horodatés** (les notifications, 100% RDV, ont disparu avec
  le pivot walk-in — plus rien à notifier pour un client déjà sur place).
- `ListDashboardAlerts` — les **alertes** dérivées (anomalie de paiement, attente
  prolongée). L'ancienne alerte « retard » (RDV confirmé dont le créneau planifié
  est dépassé) n'a **pas d'équivalent** walk-in — un ticket n'a pas de créneau, elle
  est donc retirée plutôt que redéfinie arbitrairement.

Comme les autres lectures du tableau de bord (#39–#43), **aucune** écriture ni audit
§11.4 : consulter un KPI/une activité n'est pas une action journalisée. Les statuts
(`waiting`/`in_progress`/`done`) sont **décidés ici**, jamais soumis par l'appelant.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.application.ports.queue_ticket_repository import (
    QueueTicketRepository,
)
from coiflink_api.domain.dashboard import (
    ActivityEvent,
    Alert,
    DashboardKpis,
    InProgressService,
    SeriesBucket,
    build_series,
    compute_evolution,
    previous_period,
)
from coiflink_api.domain.discrepancy import DiscrepancyFilter
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.revenue import week_bounds
from coiflink_api.domain.time_window import day_end_utc, day_start_utc
from coiflink_api.domain.transaction import Transaction, TransactionFilter

# Statut « en attente » = ticket **pas encore pris en charge** (miroir walk-in du
# concept « demande non confirmée », #148).
_WAITING_STATUSES: tuple[str, ...] = ("waiting",)

# Bornes de la timeline (top-N, garde de coût §12.1 — même esprit que #34/#35).
ACTIVITY_LIMIT_DEFAULT = 20
ACTIVITY_LIMIT_MIN = 1
ACTIVITY_LIMIT_MAX = 100

# Sévérité par genre d'alerte (constantes de domaine documentées, ajustables — #148).
_ALERT_SEVERITY: dict[str, str] = {
    "payment_anomaly": "warning",
    "prolonged_wait": "info",
}
# Ordre d'affichage stable des alertes (autorité serveur).
_ALERT_ORDER: tuple[str, ...] = ("payment_anomaly", "prolonged_wait")

_ZERO_MONEY = decimal.Decimal("0.00")


class SummarizeDashboardKpis:
    """Assemble les **4 cartes KPI** + évolution du tableau de bord d'activité (#148).

    `execute(salon_id, *, date_from, date_to, now)` calcule, sur la période résolue
    `[date_from, date_to]` **et** sa période précédente de même longueur
    (`previous_period`) : « clients en attente » (tickets `waiting`), « chiffre
    d'affaires » (net `cash_journal`) et « nombre de clientes » (fiches distinctes
    `done`), avec leur **évolution**. « Prestations en cours » est un **instantané**
    du décompte direct des tickets `in_progress` — indépendant du filtre de période
    et, contrairement à l'ancien RDV, sans arithmétique de créneau (un ticket porte
    directement ce statut). Les statuts sont **imposés serveur**. Lecture pure :
    aucune écriture, aucun audit (§11.4).
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
        now: datetime.datetime,
    ) -> DashboardKpis:
        prev_from, prev_to = previous_period(date_from, date_to)

        waiting_current = self._count_status(salon_id, date_from, date_to)
        waiting_previous = self._count_status(salon_id, prev_from, prev_to)

        revenue_current = self._net_revenue(salon_id, date_from, date_to)
        revenue_previous = self._net_revenue(salon_id, prev_from, prev_to)

        clients_current = self._tickets.count_distinct_completed_clients(
            salon_id,
            date_from=date_from,
            date_to=date_to,
        )
        clients_previous = self._tickets.count_distinct_completed_clients(
            salon_id,
            date_from=prev_from,
            date_to=prev_to,
        )

        # Bornes **fixes** (jour/semaine glissants sur `now`), volontairement
        # indépendantes de `date_from`/`date_to` — cf. docstring de `DashboardKpis`.
        today = now.date()
        yesterday = today - datetime.timedelta(days=1)
        attendance_today = self._attendance_count(salon_id, today, today)
        attendance_yesterday = self._attendance_count(salon_id, yesterday, yesterday)

        week_from, week_to = week_bounds(today)
        prev_week_from, prev_week_to = previous_period(week_from, week_to)
        revenue_this_week = self._net_revenue(salon_id, week_from, week_to)
        revenue_last_week = self._net_revenue(salon_id, prev_week_from, prev_week_to)

        return DashboardKpis(
            date_from=date_from,
            date_to=date_to,
            waiting_clients=compute_evolution(waiting_current, waiting_previous),
            in_progress=self._tickets.count_in_progress(salon_id),
            revenue=compute_evolution(revenue_current, revenue_previous),
            clients_count=compute_evolution(clients_current, clients_previous),
            attendance_today=compute_evolution(attendance_today, attendance_yesterday),
            revenue_this_week=compute_evolution(revenue_this_week, revenue_last_week),
            currency=DEFAULT_CURRENCY,
        )

    def _count_status(
        self, salon_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> int:
        counts = self._tickets.count_by_status_in_range(
            salon_id,
            statuses=_WAITING_STATUSES,
            date_from=date_from,
            date_to=date_to,
        )
        return int(counts.get("waiting", 0))

    def _net_revenue(
        self, salon_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> decimal.Decimal:
        return self._cash_journal.net_revenue_between(
            salon_id,
            created_at_from=day_start_utc(date_from),
            created_at_to=day_end_utc(date_to),
        )

    def _attendance_count(
        self, salon_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> int:
        values = dict(
            self._tickets.attendance_series(
                salon_id, date_from=date_from, date_to=date_to
            )
        )
        return sum(values.values())


class ListInProgressServices:
    """Liste les **tickets en cours maintenant**, avec noms d'affichage (#148).

    `execute(salon_id)` délègue au port `list_in_progress_details` (décompte direct
    `status = 'in_progress'`, résolution des noms **en base**). Émet **uniquement**
    des noms d'affichage (jamais `customer_profile_id`/contact). Lecture pure.
    """

    def __init__(self, queue_ticket_repository: QueueTicketRepository) -> None:
        self._tickets = queue_ticket_repository

    def execute(self, salon_id: uuid.UUID) -> tuple[InProgressService, ...]:
        return self._tickets.list_in_progress_details(salon_id)


class SummarizeRevenueSeries:
    """Série temporelle du **CA net par jour** (graphique d'évolution, #148).

    `execute(salon_id, *, date_from, date_to)` agrège le net `cash_journal` par jour
    civil (port `net_revenue_series`) puis **complète les jours vides à `0.00`**
    (`build_series`) pour un axe continu. Lecture pure ; montants `Decimal`, aucune PII.
    """

    def __init__(self, cash_journal_repository: CashJournalRepository) -> None:
        self._cash_journal = cash_journal_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> tuple[SeriesBucket, ...]:
        values = dict(
            self._cash_journal.net_revenue_series(
                salon_id, date_from=date_from, date_to=date_to
            )
        )
        return build_series(date_from, date_to, values, zero=_ZERO_MONEY)


class SummarizeAttendanceSeries:
    """Série temporelle de la **fréquentation par jour** (graphique de fréquentation).

    `execute(salon_id, *, date_from, date_to)` agrège le nombre de tickets par jour
    (port `attendance_series`) puis **complète les jours vides à `0`** (`build_series`).
    Lecture pure ; compteurs entiers, aucune PII.
    """

    def __init__(self, queue_ticket_repository: QueueTicketRepository) -> None:
        self._tickets = queue_ticket_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> tuple[SeriesBucket, ...]:
        values = dict(
            self._tickets.attendance_series(
                salon_id, date_from=date_from, date_to=date_to
            )
        )
        return build_series(date_from, date_to, values, zero=0)


class ListRecentActivity:
    """Timeline « Transactions récentes » (§7.2) — faits **réellement horodatés** (#148).

    `execute(salon_id, *, limit)` renvoie les **paiements** (avec montant + nom
    d'affichage, patron #36), triés par horodatage **décroissant** et bornés (top-N).
    Les notifications salon ont disparu avec le pivot walk-in exclusif (un client déjà
    sur place n'a plus de rappel/confirmation à recevoir). « Arrivée cliente / début /
    fin de prestation » ne figurent **pas** (aucune source horodatée, #148 Non-Goals).
    Lecture pure.
    """

    def __init__(self, payment_repository: PaymentRepository) -> None:
        self._payments = payment_repository

    def execute(
        self, salon_id: uuid.UUID, *, limit: int
    ) -> tuple[ActivityEvent, ...]:
        events = self._payment_events(salon_id, limit)
        events.sort(key=lambda event: event.occurred_at, reverse=True)
        return tuple(events[:limit])

    def _payment_events(
        self, salon_id: uuid.UUID, limit: int
    ) -> list[ActivityEvent]:
        transactions = self._payments.list_for_salon(
            salon_id, filter=TransactionFilter(), limit=limit, offset=0
        )
        return [self._payment_event(transaction) for transaction in transactions]

    @staticmethod
    def _payment_event(transaction: Transaction) -> ActivityEvent:
        payment = transaction.payment
        return ActivityEvent(
            occurred_at=payment.created_at,
            kind="payment",
            label="Paiement enregistré",
            amount=payment.amount,
            client_name=transaction.client_name,
            currency=payment.currency,
        )


class ListDashboardAlerts:
    """Alertes importantes (§7.2) **dérivées** de faits réels, counts-first (#148).

    `execute(salon_id, *, now)` dérive deux alertes :

    - **`payment_anomaly`** — écarts de caisse (#36) : tickets `done` sans paiement
      (`payment_repo.count_completed_without_payment`, tous, filtre vide) ;
    - **`prolonged_wait`** — tickets `waiting` dont l'attente **réelle** dépasse
      l'estimation figée (`queue_ticket_repo.count_waiting_beyond_estimate`).

    L'ancienne alerte `late` (RDV `CONFIRMED` dont le créneau est dépassé sans clôture)
    n'a **pas d'équivalent walk-in** — un ticket n'a pas de créneau horaire fixe contre
    lequel être « en retard » — et disparaît donc plutôt que d'être arbitrairement
    redéfinie. Ne renvoie que les alertes dont l'effectif est **> 0** (une alerte à `0`
    n'est pas « importante »). Counts-only, aucune PII. Lecture pure.
    """

    def __init__(
        self,
        queue_ticket_repository: QueueTicketRepository,
        payment_repository: PaymentRepository,
    ) -> None:
        self._tickets = queue_ticket_repository
        self._payments = payment_repository

    def execute(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> tuple[Alert, ...]:
        prolonged_wait = self._tickets.count_waiting_beyond_estimate(
            salon_id, now=now
        )
        payment_anomaly = self._payments.count_completed_without_payment(
            salon_id, filter=DiscrepancyFilter()
        )

        counts: dict[str, int] = {
            "payment_anomaly": int(payment_anomaly),
            "prolonged_wait": int(prolonged_wait),
        }
        return tuple(
            Alert(
                kind=kind,  # type: ignore[arg-type]
                severity=_ALERT_SEVERITY[kind],  # type: ignore[arg-type]
                count=counts[kind],
            )
            for kind in _ALERT_ORDER
            if counts[kind] > 0
        )


__all__ = [
    "SummarizeDashboardKpis",
    "ListInProgressServices",
    "SummarizeRevenueSeries",
    "SummarizeAttendanceSeries",
    "ListRecentActivity",
    "ListDashboardAlerts",
    "ACTIVITY_LIMIT_DEFAULT",
    "ACTIVITY_LIMIT_MIN",
    "ACTIVITY_LIMIT_MAX",
]
