"""Cas d'usage : **Dashboard Manager — activité du salon** (lecture pure, #148).

Tranche applicative hexagonale (ADR-0008) : ces cas d'usage ne dépendent que de
**ports** (`AppointmentRepository`, `CashJournalRepository`, `PaymentRepository`,
`NotificationRepository`) — aucune dépendance FastAPI/SQLAlchemy. Ils **consolident**
au-dessus du socle KPI existant (#39–#43/#36) l'écran d'activité de l'issue #148 :

- `SummarizeDashboardKpis` — les **4 cartes KPI** (clients en attente, prestations en
  cours, chiffre d'affaires, nombre de clientes) avec **évolution** vs période
  précédente ; statuts **imposés serveur**.
- `ListInProgressServices` — la **liste des prestations en cours** (noms d'affichage).
- `SummarizeRevenueSeries` / `SummarizeAttendanceSeries` — les deux **séries
  temporelles** des graphiques (CA net, fréquentation), buckets complétés à `0`.
- `ListRecentActivity` — la **timeline** « Transactions récentes » (§7.2), bornée aux
  faits **réellement horodatés** (paiements + notifications salon).
- `ListDashboardAlerts` — les **alertes** dérivées (anomalie de paiement, retard,
  attente prolongée).

Comme les autres lectures du tableau de bord (#39–#43), **aucune** écriture ni audit
§11.4 : consulter un KPI/une activité n'est pas une action journalisée. Les statuts
(`PENDING`/`CONFIRMED`/`COMPLETED`) sont **décidés ici**, jamais soumis par l'appelant.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.ports.appointment_repository import (
    AppointmentRepository,
)
from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.application.ports.notification_repository import (
    NotificationRepository,
)
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.domain.appointment import REVENUE_STATUSES
from coiflink_api.domain.dashboard import (
    ActivityEvent,
    Alert,
    DashboardKpis,
    InProgressService,
    SeriesBucket,
    build_series,
    compute_evolution,
    has_started,
    is_in_progress,
    previous_period,
)
from coiflink_api.domain.discrepancy import DiscrepancyFilter
from coiflink_api.domain.enums import AppointmentStatus, NotificationType
from coiflink_api.domain.notification import SalonNotification
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.time_window import day_end_utc, day_start_utc
from coiflink_api.domain.transaction import Transaction, TransactionFilter

# Statut « en attente » = demande **non encore confirmée** par le gérant (#148, la
# source « queue » la plus proche existante — aucune salle d'attente walk-in, §17).
_WAITING_STATUSES: tuple[str, ...] = (AppointmentStatus.PENDING.value,)

# Statut « réalisé » = une **visite** (§8.1) — base du KPI « nombre de clientes ».
_COMPLETED_STATUSES: tuple[str, ...] = REVENUE_STATUSES  # (COMPLETED,)

# Genres de notification **salon** repris dans la timeline d'activité (§7.2) : nouvelle
# réservation (#47), annulation & modification (#48). Les confirmations/rappels
# **client** (`CONFIRMATION`/`REMINDER`) ne sont pas de l'activité salon.
_ACTIVITY_NOTIFICATION_KINDS: dict[str, str] = {
    NotificationType.NEW_BOOKING.value: "new_booking",
    NotificationType.CANCELLATION.value: "cancellation",
    NotificationType.APPOINTMENT_UPDATE.value: "appointment_update",
}

# Bornes de la timeline (top-N, garde de coût §12.1 — même esprit que #34/#35).
ACTIVITY_LIMIT_DEFAULT = 20
ACTIVITY_LIMIT_MIN = 1
ACTIVITY_LIMIT_MAX = 100

# Sévérité par genre d'alerte (constantes de domaine documentées, ajustables — #148).
_ALERT_SEVERITY: dict[str, str] = {
    "payment_anomaly": "warning",
    "late": "warning",
    "prolonged_wait": "info",
}
# Ordre d'affichage stable des alertes (autorité serveur).
_ALERT_ORDER: tuple[str, ...] = ("payment_anomaly", "late", "prolonged_wait")

_ZERO_MONEY = decimal.Decimal("0.00")


class SummarizeDashboardKpis:
    """Assemble les **4 cartes KPI** + évolution du tableau de bord d'activité (#148).

    `execute(salon_id, *, date_from, date_to, now)` calcule, sur la période résolue
    `[date_from, date_to]` **et** sa période précédente de même longueur
    (`previous_period`) : « clients en attente » (RDV `PENDING`), « chiffre d'affaires »
    (net `cash_journal`) et « nombre de clientes » (comptes distincts `COMPLETED`), avec
    leur **évolution**. « Prestations en cours » est un **instantané** dérivé
    (`CONFIRMED` ∩ `is_in_progress(now)`), indépendant du filtre de période. Les statuts
    sont **imposés serveur**. Lecture pure : aucune écriture, aucun audit (§11.4).
    """

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        cash_journal_repository: CashJournalRepository,
    ) -> None:
        self._appointments = appointment_repository
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

        clients_current = self._appointments.count_distinct_completed_clients(
            salon_id,
            statuses=_COMPLETED_STATUSES,
            date_from=date_from,
            date_to=date_to,
        )
        clients_previous = self._appointments.count_distinct_completed_clients(
            salon_id,
            statuses=_COMPLETED_STATUSES,
            date_from=prev_from,
            date_to=prev_to,
        )

        return DashboardKpis(
            date_from=date_from,
            date_to=date_to,
            waiting_clients=compute_evolution(waiting_current, waiting_previous),
            in_progress=self._count_in_progress(salon_id, now),
            revenue=compute_evolution(revenue_current, revenue_previous),
            clients_count=compute_evolution(clients_current, clients_previous),
            currency=DEFAULT_CURRENCY,
        )

    def _count_status(
        self, salon_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> int:
        counts = self._appointments.count_by_status_in_range(
            salon_id,
            statuses=_WAITING_STATUSES,
            date_from=date_from,
            date_to=date_to,
        )
        return int(counts.get(AppointmentStatus.PENDING.value, 0))

    def _net_revenue(
        self, salon_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> decimal.Decimal:
        return self._cash_journal.net_revenue_between(
            salon_id,
            created_at_from=day_start_utc(date_from),
            created_at_to=day_end_utc(date_to),
        )

    def _count_in_progress(
        self, salon_id: uuid.UUID, now: datetime.datetime
    ) -> int:
        """Instantané « en cours » = RDV `CONFIRMED` du jour ∩ `is_in_progress(now)`.

        Charge les RDV `CONFIRMED` du **jour courant** (`now.date()`, patron « charger
        puis filtrer » de la spec §B) et compte ceux dont le créneau contient `now`. La
        dérivation vit dans le domaine (`is_in_progress`), pas en base : aucun statut ni
        horodatage nouveau.
        """

        today = now.date()
        confirmed = self._appointments.list_for_salon(
            salon_id,
            today,
            today,
            statuses=(AppointmentStatus.CONFIRMED.value,),
        )
        return sum(
            1
            for appt in confirmed
            if is_in_progress(now, appt.date, appt.start_time, appt.end_time)
        )


class ListInProgressServices:
    """Liste les **prestations en cours maintenant**, avec noms d'affichage (#148).

    `execute(salon_id, *, now)` délègue au port `list_in_progress_details` (dérivation
    `CONFIRMED` ∩ créneau contenant `now`, résolution des noms **en base**). Émet
    **uniquement** des noms d'affichage (jamais `client_id`/contact). Lecture pure.
    """

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> tuple[InProgressService, ...]:
        return self._appointments.list_in_progress_details(salon_id, now=now)


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

    `execute(salon_id, *, date_from, date_to)` agrège le nombre de RDV par jour (port
    `attendance_series`) puis **complète les jours vides à `0`** (`build_series`).
    Lecture pure ; compteurs entiers, aucune PII.
    """

    def __init__(self, appointment_repository: AppointmentRepository) -> None:
        self._appointments = appointment_repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> tuple[SeriesBucket, ...]:
        values = dict(
            self._appointments.attendance_series(
                salon_id, date_from=date_from, date_to=date_to
            )
        )
        return build_series(date_from, date_to, values, zero=0)


class ListRecentActivity:
    """Timeline « Transactions récentes » (§7.2) — faits **réellement horodatés** (#148).

    `execute(salon_id, *, limit)` fusionne, triés par horodatage **décroissant** et
    bornés (top-N) : les **paiements** (avec montant + nom d'affichage, patron #36) et
    les **notifications salon** `NEW_BOOKING`/`CANCELLATION`/`APPOINTMENT_UPDATE` (#47/
    #48, libellé **neutre**). Une paire client+salon d'une même notification (`type`,
    `appointment_id`) est **dédupliquée** (un seul évènement métier). « Arrivée cliente
    / début / fin de prestation » ne figurent **pas** (aucune source horodatée, #148
    Non-Goals). Lecture pure.
    """

    def __init__(
        self,
        payment_repository: PaymentRepository,
        notification_repository: NotificationRepository,
    ) -> None:
        self._payments = payment_repository
        self._notifications = notification_repository

    def execute(
        self, salon_id: uuid.UUID, *, limit: int
    ) -> tuple[ActivityEvent, ...]:
        events: list[ActivityEvent] = []
        events.extend(self._payment_events(salon_id, limit))
        events.extend(self._notification_events(salon_id, limit))
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

    def _notification_events(
        self, salon_id: uuid.UUID, limit: int
    ) -> list[ActivityEvent]:
        rows = self._notifications.list_for_salon(salon_id, limit=limit)
        seen: set[tuple[str, uuid.UUID | None]] = set()
        events: list[ActivityEvent] = []
        for row in rows:
            kind = _ACTIVITY_NOTIFICATION_KINDS.get(row.type)
            if kind is None:
                continue
            key = (row.type, row.appointment_id)
            if key in seen:
                continue
            seen.add(key)
            events.append(self._notification_event(row, kind))
        return events

    @staticmethod
    def _notification_event(row: SalonNotification, kind: str) -> ActivityEvent:
        return ActivityEvent(
            occurred_at=row.created_at,
            kind=kind,  # type: ignore[arg-type]
            label=row.title,
        )


class ListDashboardAlerts:
    """Alertes importantes (§7.2) **dérivées** de faits réels, counts-first (#148).

    `execute(salon_id, *, now)` dérive trois alertes :

    - **`payment_anomaly`** — écarts de caisse (#36) : RDV `COMPLETED` sans paiement
      (`payment_repo.count_completed_without_payment`, tous, filtre vide) ;
    - **`late`** — RDV `CONFIRMED` du jour dont le créneau est **passé** sans clôture
      (`has_started(now)` **et non** `is_in_progress(now)`) ;
    - **`prolonged_wait`** — RDV `PENDING` du jour dont le début est **dépassé** sans
      confirmation (`has_started(now)`).

    Les RDV du jour sont chargés **une seule fois** (`list_for_salon(today, today)`) et
    les deux alertes de planning en dérivent (aucune requête superflue). Ne renvoie que
    les alertes dont l'effectif est **> 0** (une alerte à `0` n'est pas « importante »).
    Counts-only, aucune PII. Lecture pure.
    """

    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        payment_repository: PaymentRepository,
    ) -> None:
        self._appointments = appointment_repository
        self._payments = payment_repository

    def execute(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> tuple[Alert, ...]:
        today = now.date()
        appointments = self._appointments.list_for_salon(salon_id, today, today)

        late = sum(
            1
            for appt in appointments
            if appt.status == AppointmentStatus.CONFIRMED.value
            and has_started(now, appt.date, appt.start_time)
            and not is_in_progress(now, appt.date, appt.start_time, appt.end_time)
        )
        prolonged_wait = sum(
            1
            for appt in appointments
            if appt.status == AppointmentStatus.PENDING.value
            and has_started(now, appt.date, appt.start_time)
        )
        payment_anomaly = self._payments.count_completed_without_payment(
            salon_id, filter=DiscrepancyFilter()
        )

        counts: dict[str, int] = {
            "payment_anomaly": int(payment_anomaly),
            "late": late,
            "prolonged_wait": prolonged_wait,
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
