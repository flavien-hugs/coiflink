"""Dashboard Manager — **activité du salon** : période, évolution, « en cours » (#148).

Domaine **pur** (aucune I/O, ni FastAPI ni SQLAlchemy — ADR-0008) du tableau de bord
d'activité gérant. Il lève les ambiguïtés de l'issue #148 en **définitions dérivées de
faits réels** (aucun statut nouveau, aucune migration) :

- **Filtre de période** (`DashboardPeriodKind` = `today|week|month|custom`) résolu en
  bornes de **jour civil** `[date_from, date_to]` via `resolve_period`, en réutilisant
  les bornes de `domain/revenue.py` (`day_bounds`/`week_bounds`/`month_bounds`). La
  **période précédente de même longueur** (`previous_period`) est la base de
  l'**évolution** (`Evolution`/`compute_evolution`) — calculée **côté serveur**
  (autorité), jamais recomposée par le front.
- **« Prestations en cours »** = RDV `CONFIRMED` dont le créneau
  `[appointment_date+start_time, appointment_date+end_time)` **contient l'instant
  présent** (`is_in_progress`, fuseau salon `Africa/Abidjan` = UTC+0, naïf). Aucun
  statut `IN_PROGRESS`, aucune colonne d'horodatage : la dérivation est **pure** et
  testable sans base. Un vrai suivi arrivée/début/fin (pointage, borne §17) est hors
  MVP (§21).

Les objets-valeur de lecture (`SeriesBucket`, `InProgressService`, `ActivityEvent`,
`Alert`) et les helpers purs de complétion (`build_series`) vivent ici : ils ne
portent **aucune PII** au-delà d'un **nom d'affichage maîtrisé** (`InProgressService`/
`ActivityEvent`, patron #43/#36), jamais de contact ni d'identifiant client.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from typing import Literal

from coiflink_api.domain.errors import InvalidDashboardPeriod
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.revenue import day_bounds, month_bounds, week_bounds

# Genres de période du filtre unifié « Aujourd'hui | Semaine | Mois | Personnalisée ».
DashboardPeriodKind = Literal["today", "week", "month", "custom"]

PERIOD_KINDS: tuple[DashboardPeriodKind, ...] = ("today", "week", "month", "custom")

# Sens d'une évolution period-sur-period (dérivé du signe du delta).
EvolutionDirection = Literal["up", "down", "flat"]

# Genres d'alerte dérivés de faits réels (§7.2 « Alertes importantes »).
AlertKind = Literal["payment_anomaly", "late", "prolonged_wait"]
AlertSeverity = Literal["info", "warning", "critical"]

# Genres d'évènement de la timeline « Transactions récentes » (§7.2), bornés aux faits
# **réellement horodatés** (paiement, nouvelle réservation, annulation/modification).
ActivityKind = Literal["payment", "new_booking", "cancellation", "appointment_update"]


def resolve_period(
    kind: str,
    *,
    reference: datetime.date,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    """Résout un genre de période en bornes de **jour civil** inclusives (#148).

    `today` → `day_bounds(reference)` ; `week` → `week_bounds(reference)`
    (lundi→dimanche) ; `month` → `month_bounds(reference)` ; `custom` → les bornes
    fournies (**les deux requises**). Réutilise `domain/revenue.py` pour une sémantique
    de période **identique** au CA (#40). Lève `InvalidDashboardPeriod` (→ `422`) si le
    genre est inconnu, si `custom` n'a pas ses deux bornes, ou si `date_to < date_from`.
    Fonction **pure** (aucune I/O).
    """

    if kind == "today":
        return day_bounds(reference)
    if kind == "week":
        return week_bounds(reference)
    if kind == "month":
        return month_bounds(reference)
    if kind == "custom":
        if date_from is None or date_to is None:
            raise InvalidDashboardPeriod("Période personnalisée incomplète.")
        if date_to < date_from:
            raise InvalidDashboardPeriod("La date de fin précède la date de début.")
        return date_from, date_to
    raise InvalidDashboardPeriod("Genre de période inconnu.")


def previous_period(
    date_from: datetime.date, date_to: datetime.date
) -> tuple[datetime.date, datetime.date]:
    """Période **immédiatement précédente de même longueur** (base de l'évolution).

    `length = date_to - date_from + 1` jours ; `prev_to = date_from - 1j` ;
    `prev_from = prev_to - (length - 1)j`. La période précédente est **contiguë** (elle
    se termine la veille de `date_from`) et de **même durée** — comparaison à durée
    constante. Fonction **pure**.
    """

    length = (date_to - date_from).days + 1
    prev_to = date_from - datetime.timedelta(days=1)
    prev_from = prev_to - datetime.timedelta(days=length - 1)
    return prev_from, prev_to


@dataclass(frozen=True)
class Evolution:
    """Évolution d'un KPI entre la période courante et la précédente (autorité serveur).

    `current`/`previous` sont un entier (compteur) **ou** un `Decimal` (montant, jamais
    un flottant). `delta` et `direction` sont **dérivés** (le front n'a rien à
    recalculer). `direction` vaut `up`/`down`/`flat` selon le signe du delta — robuste à
    `previous == 0` (pas de ratio, donc pas de division par zéro).
    """

    current: int | decimal.Decimal
    previous: int | decimal.Decimal

    @property
    def delta(self) -> int | decimal.Decimal:
        return self.current - self.previous

    @property
    def direction(self) -> EvolutionDirection:
        delta = self.delta
        if delta > 0:
            return "up"
        if delta < 0:
            return "down"
        return "flat"


def compute_evolution(
    current: int | decimal.Decimal, previous: int | decimal.Decimal
) -> Evolution:
    """Assemble une `Evolution` (helper pur — délégation à la dataclass gelée)."""

    return Evolution(current=current, previous=previous)


def is_in_progress(
    now: datetime.datetime,
    appointment_date: datetime.date,
    start_time: datetime.time,
    end_time: datetime.time,
) -> bool:
    """Vrai si le créneau du RDV **contient l'instant présent** (dérivation « en cours »).

    Créneau `[appointment_date+start_time, appointment_date+end_time)` : borne basse
    **inclusive**, borne haute **exclusive** (à la fin exacte, le RDV n'est plus en
    cours). `now` est un `datetime` **naïf** dans le repère du salon (`Africa/Abidjan` =
    UTC+0, convention #21), cohérent avec la colonne générée `slot` (TSRANGE naïf).
    Fonction **pure** — la définition « en cours » est décidée ici, sans base ni statut
    nouveau (#148, Non-Goals).
    """

    start = datetime.datetime.combine(appointment_date, start_time)
    end = datetime.datetime.combine(appointment_date, end_time)
    return start <= now < end


def has_started(
    now: datetime.datetime,
    appointment_date: datetime.date,
    start_time: datetime.time,
) -> bool:
    """Vrai si l'heure de début du RDV est **dépassée** (`start <= now`) — pur (#148).

    Base des alertes « retard » (RDV `CONFIRMED` dont le créneau a commencé mais n'est
    plus en cours — donc terminé sans clôture) et « attente prolongée » (RDV `PENDING`
    dont le début est dépassé sans confirmation).
    """

    return datetime.datetime.combine(appointment_date, start_time) <= now


@dataclass(frozen=True)
class DashboardKpis:
    """Les **4 cartes KPI** du tableau de bord d'activité (#148) — sans PII.

    `waiting_clients` (RDV `PENDING` sur la période), `revenue` (net `cash_journal` sur
    la période) et `clients_count` (comptes distincts avec un RDV `COMPLETED`) portent
    leur **évolution** vs la période précédente. `in_progress` est un **instantané**
    (nombre de prestations en cours **maintenant**) — sans évolution (l'issue ne liste
    que « nombre actuel »). Uniquement des compteurs, un montant et une devise (§11.3).

    `attendance_today`/`revenue_this_week` alimentent les cartes « À surveiller »
    (réorganisation du tableau de bord) — **bornes fixes**, volontairement
    **indépendantes** du filtre de période (`date_from`/`date_to` ci-dessus) : le CA
    du jour et la fréquentation du jour sont déjà visibles ailleurs (tuile CA, ce
    même KPI d'ici) — ces deux champs répondent à une question différente,
    toujours la même (« vs hier », « vs la semaine dernière »), pour ne jamais
    dépendre de ce que le gérant a sélectionné dans le filtre.
    """

    date_from: datetime.date
    date_to: datetime.date
    waiting_clients: Evolution
    in_progress: int
    revenue: Evolution
    clients_count: Evolution
    attendance_today: Evolution
    revenue_this_week: Evolution
    currency: str = DEFAULT_CURRENCY


@dataclass(frozen=True)
class SeriesBucket:
    """Un point d'une série temporelle (graphique) : bornes de jour civil + valeur.

    `value` est un entier (fréquentation) **ou** un `Decimal` (CA net). Les buckets
    **vides valent `0`** (jamais absents) pour un axe temporel continu — garanti par
    `build_series`. Aucune PII (dates + valeur).
    """

    bucket_start: datetime.date
    bucket_end: datetime.date
    value: int | decimal.Decimal


def build_series(
    date_from: datetime.date,
    date_to: datetime.date,
    values: dict[datetime.date, int | decimal.Decimal],
    *,
    zero: int | decimal.Decimal,
) -> tuple[SeriesBucket, ...]:
    """Complète une série **jour par jour** sur `[date_from, date_to]` (pur, patron #39).

    Un bucket par **jour civil** de la plage (inclusive) ; la valeur est
    `values.get(day, zero)` — les jours sans donnée valent `zero` (axe continu). Borné
    par la longueur de la période (petit au MVP salon). Fonction **pure** (aucune I/O).
    """

    buckets: list[SeriesBucket] = []
    day = date_from
    while day <= date_to:
        buckets.append(
            SeriesBucket(bucket_start=day, bucket_end=day, value=values.get(day, zero))
        )
        day += datetime.timedelta(days=1)
    return tuple(buckets)


@dataclass(frozen=True)
class InProgressService:
    """Un ticket walk-in **en cours maintenant** (liste opérationnelle §148, avec noms).

    Émet **uniquement** des **noms d'affichage** (`client_name`, `service_names`,
    `hairdresser_name` = `customer_profiles.full_name`/`services.name`/`users.full_name`,
    patron #43/#36) — **jamais** `customer_profile_id`/`hairdresser_id` ni contact.
    `status` vaut toujours `in_progress` (statut **stocké** du ticket, contrairement à
    l'ancien RDV où « en cours » était dérivé d'un créneau) ; il est renvoyé pour
    transparence. `started_at` remplace l'ancien couple `start_time`/`end_time` — un
    ticket walk-in n'a pas de créneau planifié, seulement l'instant où la prise en
    charge a commencé.
    """

    queue_ticket_id: str
    client_name: str | None
    service_names: tuple[str, ...]
    hairdresser_name: str | None
    started_at: datetime.datetime
    status: str


@dataclass(frozen=True)
class ActivityEvent:
    """Un évènement de la timeline « Transactions récentes » (§7.2), horodaté (#148).

    Borné aux faits **réellement horodatés** (`payment`/`new_booking`/`cancellation`/
    `appointment_update`). `amount`/`client_name` ne sont portés que par les paiements
    (nom d'affichage maîtrisé, patron #36) ; les autres genres portent un `label`
    **neutre** (message templaté sans PII, ADR-0006). « Arrivée cliente / début / fin
    de prestation » ne sont **pas** représentés (aucune source, §148 Non-Goals).
    """

    occurred_at: datetime.datetime
    kind: ActivityKind
    label: str
    amount: decimal.Decimal | None = None
    client_name: str | None = None
    currency: str = DEFAULT_CURRENCY


@dataclass(frozen=True)
class Alert:
    """Une alerte **dérivée** de faits réels (§7.2 « Alertes importantes »), counts-first.

    `kind` : `payment_anomaly` (écart de caisse #36), `late` (RDV `CONFIRMED` dont le
    créneau est passé sans clôture) ou `prolonged_wait` (RDV `PENDING` du jour dont le
    début est dépassé sans confirmation). `count` = effectif concerné (> 0 par
    construction : une alerte à `0` n'est pas émise). Aucune PII (counts-only).
    """

    kind: AlertKind
    severity: AlertSeverity
    count: int


__all__ = [
    "DashboardPeriodKind",
    "PERIOD_KINDS",
    "EvolutionDirection",
    "AlertKind",
    "AlertSeverity",
    "ActivityKind",
    "resolve_period",
    "previous_period",
    "Evolution",
    "compute_evolution",
    "is_in_progress",
    "has_started",
    "DashboardKpis",
    "SeriesBucket",
    "build_series",
    "InProgressService",
    "ActivityEvent",
    "Alert",
]
