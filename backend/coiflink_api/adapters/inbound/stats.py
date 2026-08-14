"""Adapter entrant (driving) : router HTTP **statistiques salon** (dashboard gérant, US-6.2/6.3).

Expose, sous `/salons/{salon_id}/…` (imbriqué pour hériter de `require_salon_scope`,
isolation §11.2) :

- **`GET /salons/{salon_id}/revenue/summary`** — chiffre d'affaires du salon
  (US-6.2, #40), garde `STATS_READ_SALON`. Renvoie, pour une **date de référence**
  (jour civil `Africa/Abidjan`, défaut = aujourd'hui), le CA du salon sur **trois
  périodes** : le **jour**, la **semaine** (lundi→dimanche) et le **mois** civils qui
  la contiennent. Chaque période porte ses bornes, un **total** net et la devise.
- **`GET /salons/{salon_id}/service-demand`** — prestations les plus demandées
  (US-6.3, #41), garde `STATS_READ_SALON`. Renvoie, pour une **période** optionnelle
  (`date_from`/`date_to`, absents = toute l'histoire), les prestations du salon
  classées **par volume** et **par revenu** (deux ordres, mêmes entrées). Volume =
  occurrences des tickets `done` ; revenu = somme des `services.price` **courants**
  (résolution en direct, #148) — grandeur **distincte** du CA (#40), voir
  `application/service_demand.py`.

- **`GET /salons/{salon_id}/hairdresser-performance`** — performance des coiffeurs
  (US-6.5, #43), garde `STATS_READ_SALON`. Renvoie, pour une **période** optionnelle
  (`date_from`/`date_to`, absents = mois civil courant), **une ligne par coiffeur**
  assigné à ≥ 1 ticket du salon sur la période : **prestations réalisées**
  (occurrences des tickets `done`), **CA généré** (net `cash_journal` **attribué**
  via `payments → queue_tickets.hairdresser_id`, cohérent avec la caisse) et **taux
  d'annulation** (tickets `expired` / tickets assignés — équivalent walk-in).
  Prestations & taux dérivent **de la file d'attente**, le CA **de la caisse** — voir
  `application/hairdresser_performance.py`. **Seul** endpoint stats **nominatif** : il
  émet le `hairdresser_id` + le **nom d'affichage** de l'employé (`users.full_name`,
  convention #34), jamais son contact.

- **`GET /salons/{salon_id}/dashboard/…`** — **Dashboard Manager · activité du salon**
  (§7.2, #148), garde `STATS_READ_SALON`. Consolide, au-dessus du socle #39–#43, un
  écran d'activité « temps réel » sur données **réelles** (aucun mock) : `dashboard/kpis`
  (4 KPI + évolution), `dashboard/revenue-series` / `dashboard/attendance-series` (deux
  graphiques), `dashboard/in-progress` (tickets en cours, noms d'affichage),
  `dashboard/activity` (timeline des faits horodatés) et `dashboard/alerts` (alertes
  dérivées). Filtre de période unifié (`today`/`week`/`month`/`custom`) résolu **côté
  serveur** ; « en cours » = décompte direct des tickets `in_progress`, « en attente » =
  tickets `waiting` — rebranché sur `queue_tickets` avec le pivot walk-in exclusif
  (#148, ancien socle RDV).

**Router `stats` dédié (spec §Open Questions 6).** Cette surface porte la permission
`STATS_READ_SALON` (statistiques du salon), distincte de la caisse
(`PAYMENT_RECORD`/`CASH_JOURNAL_READ`, servie par `payments.py`). `STATS_READ_SALON` a
désormais **cinq** consommateurs : CA (#40), prestations les plus demandées (#41),
performance des coiffeurs (#43) et le tableau de bord d'activité (#148, six routes
`dashboard/*`).

**Non-PII (§11.3), lecture pure.** Les réponses ne portent **que** des montants
(`Decimal` en chaîne), des compteurs, des libellés de prestation, des dates et une
devise : **aucun** `client_id`, `queue_ticket_id`, `reference`, `recorded_by`, ni ligne
de ticket/paiement. Les agrégats sont calculés **en base** (`SUM`/`GROUP BY`), pas en
rapatriant les lignes. Aucune écriture, **aucun** audit §11.4. **Aucun** chemin n'entre
dans `PUBLIC_ROUTE_PATHS` : une donnée d'exploitation salon n'est jamais publique.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.inbound.queue_tickets import get_queue_ticket_repository
from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
    SqlCashJournalEntryRepository,
)
from coiflink_api.adapters.outbound.persistence.payment_repository import (
    SqlPaymentRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.application.ports.queue_ticket_repository import (
    QueueTicketRepository,
)
from coiflink_api.application.dashboard import (
    ACTIVITY_LIMIT_DEFAULT,
    ACTIVITY_LIMIT_MAX,
    ACTIVITY_LIMIT_MIN,
    ListDashboardAlerts,
    ListInProgressServices,
    ListRecentActivity,
    SummarizeAttendanceSeries,
    SummarizeDashboardKpis,
    SummarizeRevenueSeries,
)
from coiflink_api.application.hairdresser_performance import (
    SummarizeHairdresserPerformance,
)
from coiflink_api.application.revenue import SummarizeRevenue
from coiflink_api.application.service_demand import SummarizeServiceDemand
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.dashboard import (
    ActivityEvent,
    Alert,
    DashboardKpis,
    Evolution,
    InProgressService,
    SeriesBucket,
    resolve_period,
)
from coiflink_api.domain.errors import InvalidDashboardPeriod
from coiflink_api.domain.hairdresser_performance import (
    HairdresserPerformance,
    HairdresserPerformanceReport,
)
from coiflink_api.domain.payment import DEFAULT_CURRENCY
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.revenue import (
    RevenuePeriodTotal,
    RevenueSummary,
    month_bounds,
)
from coiflink_api.domain.service_demand import ServiceDemand, ServiceDemandRanking
from coiflink_api.domain.time_window import SALON_TIMEZONE

router = APIRouter(prefix="/salons", tags=["stats"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `admin.py`).
#
# Champs **explicites** (jamais `orm_mode`/`extra`) : la forme de la réponse est
# figée par un test qui échoue si un champ PII interdit apparaît (§11.3). `total`
# est un `Decimal` sérialisé en **chaîne** (`NUMERIC(12,2)`, jamais un flottant).
# --------------------------------------------------------------------------- #
class RevenuePeriodResponse(BaseModel):
    """CA d'**une** période (jour/semaine/mois) : bornes + total net + devise.

    `date_from`/`date_to` sont les bornes de **jour civil** inclusives de la période.
    `total` est la **somme signée** des lignes `cash_journal` `PAYMENT`/`ADJUSTMENT`
    (net des corrections), sérialisé en chaîne décimale ; il **peut être négatif** si
    les corrections excèdent les paiements sur la période. **Aucune PII.**
    """

    date_from: datetime.date = Field(examples=["2026-08-02"])
    date_to: datetime.date = Field(examples=["2026-08-02"])
    total: decimal.Decimal = Field(examples=["35000.00"])


class RevenueSummaryResponse(BaseModel):
    """CA du salon sur trois périodes pour une date de référence (US-6.2, #40).

    Ne porte **que** des dates, des montants et une devise (§11.3) : la date de
    référence, la devise, et les trois totaux `day` / `week` / `month`. **Jamais** de
    `client_id`, `reference`, `recorded_by`, ni ligne de paiement individuelle.
    """

    reference_date: datetime.date = Field(examples=["2026-08-02"])
    currency: str = Field(examples=["XOF"])
    day: RevenuePeriodResponse
    week: RevenuePeriodResponse
    month: RevenuePeriodResponse


class ServiceDemandItemResponse(BaseModel):
    """Une prestation dans le classement du salon (US-6.3, #41) : volume + revenu.

    `volume` = nombre d'occurrences **réalisées** (tickets `done`) ; `revenue` =
    somme des `services.price` **courants** (résolution en direct, #148,
    `NUMERIC(12,2)`, sérialisé en **chaîne** décimale, jamais un flottant). `name` =
    libellé courant (`services.name`), résoluble même si la prestation est
    désactivée. **Aucune PII** (pas de `client_id`/`queue_ticket_id`).
    """

    service_id: uuid.UUID = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    name: str = Field(examples=["Coupe homme"])
    volume: int = Field(examples=[42])
    revenue: decimal.Decimal = Field(examples=["210000.00"])


class ServiceDemandResponse(BaseModel):
    """Prestations les plus demandées du salon (US-6.3, #41) : deux classements.

    `by_volume` et `by_revenue` portent **les mêmes** prestations, dans deux ordres
    (volume décroissant, revenu décroissant) — le front bascule sans re-trier
    (autorité serveur). `date_from`/`date_to` échoient la période demandée (`null` =
    toute l'histoire). Ne porte **que** des libellés, compteurs, montants, dates et
    devise (§11.3) : **jamais** de `client_id`, `queue_ticket_id`, ni ligne de
    ticket/paiement. Classements **vides** si aucun ticket `done` (état normal).
    """

    currency: str = Field(examples=["XOF"])
    date_from: datetime.date | None = Field(default=None, examples=[None])
    date_to: datetime.date | None = Field(default=None, examples=[None])
    by_volume: list[ServiceDemandItemResponse]
    by_revenue: list[ServiceDemandItemResponse]


class HairdresserPerformanceItemResponse(BaseModel):
    """Performance d'**un** coiffeur du salon sur la période (US-6.5, #43).

    `hairdresser_id` + `hairdresser_name` = identité **d'affichage** de l'employé
    (`users.full_name`, convention #34) — **seul** champ nominatif autorisé, jamais son
    contact (`phone`/`email`/`role`). `services_completed` = occurrences de prestations
    réalisées (tickets `done`) ; `revenue` = CA net **attribué** (net `cash_journal`
    via `payments → queue_tickets.hairdresser_id`), `Decimal` sérialisé en **chaîne**
    (`NUMERIC(12,2)`, jamais un flottant) ; `cancelled_count` / `total_count` = tickets
    `expired` / total assignés ; `cancellation_rate` = `cancelled_count / total_count`,
    `Decimal` en **chaîne** ∈ `[0, 1]` (`"0.0000"` si `total_count == 0`). **Aucune
    PII client** (pas de `client_id`/`queue_ticket_id`).
    """

    hairdresser_id: uuid.UUID = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    hairdresser_name: str = Field(examples=["Awa Koné"])
    services_completed: int = Field(examples=[58])
    revenue: decimal.Decimal = Field(examples=["290000.00"])
    cancelled_count: int = Field(examples=[3])
    total_count: int = Field(examples=[64])
    cancellation_rate: decimal.Decimal = Field(examples=["0.0469"])


class HairdresserPerformanceResponse(BaseModel):
    """Performance des coiffeurs du salon sur une période (US-6.5, #43).

    `hairdressers` = **une entrée par coiffeur** assigné à ≥ 1 ticket du salon sur la
    période, triée par ordre **déterministe** (CA décroissant, puis prestations, puis
    nom — autorité serveur). `date_from`/`date_to` échoient la période résolue ;
    `currency` la devise (XOF). Ne porte **que** des identifiants/nom d'affichage
    d'employé, des compteurs, des montants (chaînes décimales), un taux (chaîne
    décimale) et des dates (§11.3) : **jamais** de PII client ni de contact employé.
    Liste **vide** si aucun coiffeur assigné sur la période (état normal, pas une
    erreur).
    """

    currency: str = Field(examples=["XOF"])
    date_from: datetime.date = Field(examples=["2026-08-01"])
    date_to: datetime.date = Field(examples=["2026-08-31"])
    hairdressers: list[HairdresserPerformanceItemResponse]


# --------------------------------------------------------------------------- #
# Schémas Pydantic — **Dashboard Manager · activité du salon** (#148).
#
# Toutes les réponses `dashboard/*` sont **explicites** (jamais `orm_mode`/`extra`).
# Les endpoints de compteurs/montants/séries (`kpis`, `revenue-series`,
# `attendance-series`) ne portent **aucune** PII ; les vues opérationnelles
# (`in-progress`, `activity`, `alerts`) n'émettent que des **noms d'affichage**
# maîtrisés (`users.full_name`/`services.name`, patron #43/#36) — jamais `client_id`,
# contact, ni ligne de ticket/paiement. Montants en `Decimal` (chaîne, `NUMERIC(12,2)`).
# --------------------------------------------------------------------------- #
class DashboardPeriodResponse(BaseModel):
    """Période **résolue** du tableau de bord : genre + bornes de jour civil (#148).

    `kind` échoie le genre demandé (`today`/`week`/`month`/`custom`) ;
    `date_from`/`date_to` sont les bornes **inclusives** résolues côté serveur
    (`Africa/Abidjan`, UTC+0). **Aucune PII.**
    """

    kind: str = Field(examples=["today"])
    date_from: datetime.date = Field(examples=["2026-08-07"])
    date_to: datetime.date = Field(examples=["2026-08-07"])


class EvolutionCountResponse(BaseModel):
    """Évolution d'un **compteur** (KPI) vs période précédente de même longueur (#148).

    `current`/`previous` sont des entiers ; `delta = current - previous` ; `direction`
    vaut `up`/`down`/`flat` (autorité serveur — le front n'a rien à recalculer).
    **Aucune PII** (compteurs seuls).
    """

    current: int = Field(examples=[3])
    previous: int = Field(examples=[5])
    delta: int = Field(examples=[-2])
    direction: str = Field(examples=["down"])


class InProgressCountResponse(BaseModel):
    """Compteur **instantané** des prestations en cours **maintenant** (#148).

    Pas d'évolution (l'issue ne liste que « nombre actuel ») : la valeur est un
    « maintenant » dérivé (`CONFIRMED` ∩ créneau contenant l'instant présent).
    """

    current: int = Field(examples=[2])


class EvolutionMoneyResponse(BaseModel):
    """Évolution d'un **montant** (chiffre d'affaires) vs période précédente (#148).

    `current`/`previous`/`delta` sont des `Decimal` sérialisés en **chaîne**
    (`NUMERIC(12,2)`, jamais un flottant) ; ils **peuvent être négatifs** (corrections
    #34). `direction` vaut `up`/`down`/`flat`. `currency` = devise unique (XOF).
    **Aucune PII.**
    """

    current: decimal.Decimal = Field(examples=["125000.00"])
    previous: decimal.Decimal = Field(examples=["98000.00"])
    delta: decimal.Decimal = Field(examples=["27000.00"])
    direction: str = Field(examples=["up"])
    currency: str = Field(examples=["XOF"])


class DashboardKpisResponse(BaseModel):
    """Les **4 cartes KPI** du tableau de bord d'activité (#148) — counts-only.

    `waiting_clients` (tickets `waiting` sur la période), `revenue` (net
    `cash_journal`) et `clients_count` (fiches distinctes `done`) portent leur
    **évolution** vs la période précédente ; `in_progress` est un **instantané**
    (sans évolution). `attendance_today`/`revenue_this_week` sont des évolutions à
    **bornes fixes** (jour/semaine glissants), indépendantes de `period` — cartes
    « À surveiller » du tableau de bord. Ne porte que des compteurs, un montant,
    une devise et des dates (§11.3) : **jamais** de `client_id`, nom, téléphone, ni
    ligne de ticket/paiement.
    """

    period: DashboardPeriodResponse
    waiting_clients: EvolutionCountResponse
    in_progress: InProgressCountResponse
    revenue: EvolutionMoneyResponse
    clients_count: EvolutionCountResponse
    attendance_today: EvolutionCountResponse
    revenue_this_week: EvolutionMoneyResponse


class RevenueSeriesBucketResponse(BaseModel):
    """Un point de la série d'**évolution du CA** : bornes de jour + net (#148).

    `total` est le net `cash_journal` (`PAYMENT`/`ADJUSTMENT`) du jour, `Decimal` en
    **chaîne** ; les jours vides valent `"0.00"` (axe continu). **Aucune PII.**
    """

    bucket_start: datetime.date = Field(examples=["2026-08-07"])
    bucket_end: datetime.date = Field(examples=["2026-08-07"])
    total: decimal.Decimal = Field(examples=["35000.00"])


class RevenueSeriesResponse(BaseModel):
    """Série temporelle du **chiffre d'affaires** du salon (graphique, #148).

    `buckets` = un point par **jour civil** de la période (jours vides à `"0.00"`),
    pour un axe continu. Ne porte que des dates, des montants (chaînes décimales) et la
    devise (§11.3) : **aucune PII**.
    """

    currency: str = Field(examples=["XOF"])
    date_from: datetime.date = Field(examples=["2026-08-01"])
    date_to: datetime.date = Field(examples=["2026-08-07"])
    buckets: list[RevenueSeriesBucketResponse]


class AttendanceSeriesBucketResponse(BaseModel):
    """Un point de la série de **fréquentation** : bornes de jour + nombre de tickets (#148).

    `count` = nombre de tickets du salon (tous statuts) du jour ; les jours vides
    valent `0` (axe continu). **Aucune PII** (compteur seul).
    """

    bucket_start: datetime.date = Field(examples=["2026-08-07"])
    bucket_end: datetime.date = Field(examples=["2026-08-07"])
    count: int = Field(examples=[12])


class AttendanceSeriesResponse(BaseModel):
    """Série temporelle de la **fréquentation** du salon (graphique, #148).

    `buckets` = un point par **jour civil** de la période (jours vides à `0`). Ne porte
    que des dates et des compteurs (§11.3) : **aucune PII**.
    """

    date_from: datetime.date = Field(examples=["2026-08-01"])
    date_to: datetime.date = Field(examples=["2026-08-07"])
    buckets: list[AttendanceSeriesBucketResponse]


class InProgressItemResponse(BaseModel):
    """Un ticket **en cours maintenant** (liste opérationnelle, #148).

    Émet **uniquement** des **noms d'affichage** (`client_name`, `service_names`,
    `hairdresser_name` = `customer_profiles.full_name`/`services.name`/`users
    .full_name`, patron #43/#36) — **jamais** `customer_profile_id`/`hairdresser_id`
    ni contact. `status` vaut toujours `in_progress` (statut **stocké** du ticket,
    contrairement à l'ancien RDV où « en cours » était dérivé d'un créneau), renvoyé
    pour transparence.
    """

    queue_ticket_id: str = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    client_name: str | None = Field(default=None, examples=["Awa Koné"])
    service_names: list[str] = Field(examples=[["Coupe femme", "Coloration"]])
    hairdresser_name: str | None = Field(default=None, examples=["Fatou D."])
    started_at: datetime.datetime = Field(examples=["2026-08-07T14:00:00+00:00"])
    status: str = Field(examples=["in_progress"])


class InProgressResponse(BaseModel):
    """Liste des tickets **en cours maintenant** du salon (#148).

    `as_of` = instant de la lecture (`Africa/Abidjan`) ; `items` = les tickets
    `in_progress` (décompte direct, aucune arithmétique de créneau), triés par
    heure de prise en charge. N'émet que des **noms d'affichage** maîtrisés —
    jamais `customer_profile_id`/contact (§11.3). Liste **vide** si aucun ticket en
    cours (état légitime).
    """

    as_of: datetime.datetime = Field(examples=["2026-08-07T14:32:00+00:00"])
    items: list[InProgressItemResponse]


class ActivityItemResponse(BaseModel):
    """Un évènement de la timeline « Transactions récentes » (§7.2), horodaté (#148).

    Borné aux **paiements** — seul fait **réellement horodaté** depuis le pivot
    walk-in exclusif (les notifications ont disparu, plus rien à notifier pour un
    client déjà sur place). `amount`/`client_name`/`currency` sont toujours portés
    (nom d'affichage maîtrisé, patron #36). « Arrivée cliente / début / fin de
    prestation » **ne figurent pas** (aucune source, §148 Non-Goals).
    """

    occurred_at: datetime.datetime = Field(examples=["2026-08-07T14:05:00+00:00"])
    kind: str = Field(examples=["payment"])
    label: str = Field(examples=["Paiement enregistré"])
    amount: decimal.Decimal | None = Field(default=None, examples=["15000.00"])
    client_name: str | None = Field(default=None, examples=["Awa Koné"])
    currency: str | None = Field(default=None, examples=["XOF"])


class ActivityResponse(BaseModel):
    """Timeline « Transactions récentes » (§7.2) — faits horodatés, top-N (#148).

    `items` = les **paiements**, triés par horodatage décroissant et bornés (top-N).
    N'émet que des libellés neutres et un montant + un nom d'affichage (§11.3).
    Liste **vide** si aucune activité récente (état légitime).
    """

    items: list[ActivityItemResponse]


class AlertItemResponse(BaseModel):
    """Une alerte importante (§7.2) **dérivée** de faits réels, counts-first (#148).

    `kind` : `payment_anomaly` (écart de caisse #36) ou `prolonged_wait` (tickets
    `waiting` dont l'attente réelle dépasse l'estimation figée). L'ancienne alerte
    `late` (RDV en retard) n'a pas d'équivalent walk-in et a disparu avec le pivot.
    `severity` = `info`/`warning`/`critical` ; `count` = effectif concerné (> 0 par
    construction). **Aucune PII** (counts-only).
    """

    kind: str = Field(examples=["payment_anomaly"])
    severity: str = Field(examples=["warning"])
    count: int = Field(examples=[3])


class AlertsResponse(BaseModel):
    """Alertes importantes du salon (§7.2), dérivées de faits réels (#148).

    `items` = les alertes dont l'effectif est **> 0** (une alerte à `0` n'est pas
    « importante »), dans un ordre d'affichage stable (autorité serveur). Counts-only,
    **aucune PII**. Liste **vide** si aucune alerte (état légitime).
    """

    items: list[AlertItemResponse]


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_cash_journal_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CashJournalRepository:
    """Dépôt du journal de caisse adossé à la session de la requête (lecture seule)."""

    return SqlCashJournalEntryRepository(session)


def get_payment_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PaymentRepository:
    """Dépôt des paiements adossé à la session de la requête (lecture seule, #148).

    Alimente la timeline d'activité (`list_for_salon`) et l'alerte « anomalie de
    paiement » (`count_completed_without_payment`, #36). Local au router `stats` pour
    rester surchargeable indépendamment en test via `app.dependency_overrides`.
    """

    return SqlPaymentRepository(session)


def _today() -> datetime.date:
    """Jour civil courant dans le fuseau du salon (Africa/Abidjan, convention #21)."""

    return datetime.datetime.now(SALON_TIMEZONE).date()


def _now_salon() -> datetime.datetime:
    """Instant présent **aware** dans le fuseau du salon (Africa/Abidjan, UTC+0, #148).

    Sa version naïve (`.replace(tzinfo=None)`) alimente `count_waiting_beyond_estimate`
    (comparaison à `created_at`, colonne naïve) ; la version *aware* sert d'`as_of`
    pour `dashboard/in-progress`. « En cours » n'a plus besoin de cet instant — c'est
    un décompte direct des tickets `in_progress` (aucune arithmétique de créneau,
    contrairement à l'ancien RDV).
    """

    return datetime.datetime.now(SALON_TIMEZONE)


def _resolve_dashboard_period(
    period: str,
    *,
    reference: datetime.date | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> tuple[datetime.date, datetime.date]:
    """Résout le filtre de période unifié en bornes de jour civil, ou `422` (#148).

    Délègue à `domain/dashboard.py::resolve_period` (`today`/`week`/`month`/`custom`),
    avec `reference` par défaut = jour courant du salon. Traduit
    `InvalidDashboardPeriod` (genre inconnu, `custom` sans bornes, `date_to <
    date_from`) en `422` **neutre** (message métier sans PII ni valeur saisie).
    """

    resolved_reference = reference if reference is not None else _today()
    try:
        return resolve_period(
            period,
            reference=resolved_reference,
            date_from=date_from,
            date_to=date_to,
        )
    except InvalidDashboardPeriod as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _period_response(period: RevenuePeriodTotal) -> RevenuePeriodResponse:
    return RevenuePeriodResponse(
        date_from=period.date_from,
        date_to=period.date_to,
        total=period.total,
    )


def _summary_response(summary: RevenueSummary) -> RevenueSummaryResponse:
    return RevenueSummaryResponse(
        reference_date=summary.reference_date,
        currency=summary.currency,
        day=_period_response(summary.day),
        week=_period_response(summary.week),
        month=_period_response(summary.month),
    )


def _demand_item(entry: ServiceDemand) -> ServiceDemandItemResponse:
    return ServiceDemandItemResponse(
        service_id=entry.service_id,
        name=entry.name,
        volume=entry.volume,
        revenue=entry.revenue,
    )


def _service_demand_response(
    ranking: ServiceDemandRanking,
) -> ServiceDemandResponse:
    return ServiceDemandResponse(
        currency=ranking.currency,
        date_from=ranking.date_from,
        date_to=ranking.date_to,
        by_volume=[_demand_item(entry) for entry in ranking.by_volume],
        by_revenue=[_demand_item(entry) for entry in ranking.by_revenue],
    )


def _hairdresser_performance_item(
    entry: HairdresserPerformance,
) -> HairdresserPerformanceItemResponse:
    return HairdresserPerformanceItemResponse(
        hairdresser_id=entry.hairdresser_id,
        hairdresser_name=entry.name,
        services_completed=entry.services_completed,
        revenue=entry.revenue,
        cancelled_count=entry.cancelled_count,
        total_count=entry.total_count,
        cancellation_rate=entry.cancellation_rate,
    )


def _hairdresser_performance_response(
    report: HairdresserPerformanceReport,
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> HairdresserPerformanceResponse:
    # Les bornes échoient la période **résolue** par la route (défaut mois courant).
    return HairdresserPerformanceResponse(
        currency=report.currency,
        date_from=date_from,
        date_to=date_to,
        hairdressers=[
            _hairdresser_performance_item(entry) for entry in report.entries
        ],
    )


def _evolution_count(evolution: Evolution) -> EvolutionCountResponse:
    """Projette une `Evolution` de **compteur** (KPI entier) en réponse (#148)."""

    return EvolutionCountResponse(
        current=int(evolution.current),
        previous=int(evolution.previous),
        delta=int(evolution.delta),
        direction=evolution.direction,
    )


def _evolution_money(evolution: Evolution, currency: str) -> EvolutionMoneyResponse:
    """Projette une `Evolution` de **montant** (CA `Decimal`) en réponse (#148)."""

    return EvolutionMoneyResponse(
        current=decimal.Decimal(evolution.current),
        previous=decimal.Decimal(evolution.previous),
        delta=decimal.Decimal(evolution.delta),
        direction=evolution.direction,
        currency=currency,
    )


def _kpis_response(kpis: DashboardKpis, *, kind: str) -> DashboardKpisResponse:
    """Assemble la réponse des **4 KPI** + évolution (autorité serveur, #148)."""

    return DashboardKpisResponse(
        period=DashboardPeriodResponse(
            kind=kind, date_from=kpis.date_from, date_to=kpis.date_to
        ),
        waiting_clients=_evolution_count(kpis.waiting_clients),
        in_progress=InProgressCountResponse(current=kpis.in_progress),
        revenue=_evolution_money(kpis.revenue, kpis.currency),
        clients_count=_evolution_count(kpis.clients_count),
        attendance_today=_evolution_count(kpis.attendance_today),
        revenue_this_week=_evolution_money(kpis.revenue_this_week, kpis.currency),
    )


def _revenue_series_response(
    buckets: tuple[SeriesBucket, ...],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str,
) -> RevenueSeriesResponse:
    """Assemble la série du CA (montants `Decimal`, jours vides à `0.00`, #148)."""

    return RevenueSeriesResponse(
        currency=currency,
        date_from=date_from,
        date_to=date_to,
        buckets=[
            RevenueSeriesBucketResponse(
                bucket_start=bucket.bucket_start,
                bucket_end=bucket.bucket_end,
                total=decimal.Decimal(bucket.value),
            )
            for bucket in buckets
        ],
    )


def _attendance_series_response(
    buckets: tuple[SeriesBucket, ...],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> AttendanceSeriesResponse:
    """Assemble la série de fréquentation (compteurs, jours vides à `0`, #148)."""

    return AttendanceSeriesResponse(
        date_from=date_from,
        date_to=date_to,
        buckets=[
            AttendanceSeriesBucketResponse(
                bucket_start=bucket.bucket_start,
                bucket_end=bucket.bucket_end,
                count=int(bucket.value),
            )
            for bucket in buckets
        ],
    )


def _in_progress_item(item: InProgressService) -> InProgressItemResponse:
    """Projette une prestation en cours (noms d'affichage seuls, #148)."""

    return InProgressItemResponse(
        queue_ticket_id=item.queue_ticket_id,
        client_name=item.client_name,
        service_names=list(item.service_names),
        hairdresser_name=item.hairdresser_name,
        started_at=item.started_at,
        status=item.status,
    )


def _in_progress_response(
    items: tuple[InProgressService, ...], *, as_of: datetime.datetime
) -> InProgressResponse:
    """Assemble la liste des tickets en cours + l'instant de lecture (#148)."""

    return InProgressResponse(
        as_of=as_of, items=[_in_progress_item(item) for item in items]
    )


def _activity_item(event: ActivityEvent) -> ActivityItemResponse:
    """Projette un évènement de timeline (montant/nom seuls sur paiement, #148)."""

    has_amount = event.amount is not None
    return ActivityItemResponse(
        occurred_at=event.occurred_at,
        kind=event.kind,
        label=event.label,
        amount=event.amount,
        client_name=event.client_name,
        currency=event.currency if has_amount else None,
    )


def _alert_item(alert: Alert) -> AlertItemResponse:
    """Projette une alerte dérivée (counts-only, #148)."""

    return AlertItemResponse(
        kind=alert.kind, severity=alert.severity, count=alert.count
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    "/{salon_id}/revenue/summary",
    response_model=RevenueSummaryResponse,
    summary="Chiffre d'affaires jour/semaine/mois du salon (dashboard gérant, US-6.2 §6)",
    responses={
        200: {"description": "CA du salon sur les trois périodes (jour, semaine, mois)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Paramètre `date` mal formé"},
    },
)
def get_revenue_summary(
    salon_id: uuid.UUID,
    cash_journal_repo: Annotated[
        CashJournalRepository, Depends(get_cash_journal_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    date: Annotated[
        datetime.date | None,
        Query(description="Date de référence (AAAA-MM-JJ) ; absent = aujourd'hui"),
    ] = None,
) -> RevenueSummaryResponse:
    """CA du salon **du jour / de la semaine / du mois** (dashboard gérant, #40).

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, **deuxième**
    consommateur de cette permission `MANAGER` après #39) : le `salon_id` vient du
    chemin, et le dépôt refiltre `salon_id` en SQL (défense en profondeur §11.2). Un
    salon hors périmètre est un `403` **indiscernable** (aucun oracle). Le paramètre
    `date` est **optionnel** : absent, il vaut le jour civil courant (`Africa/Abidjan`,
    convention #21) ; mal formé, il donne un `422`. Les **trois périodes** (jour,
    semaine lundi→dimanche, mois civil) sont **dérivées côté serveur** de cette date —
    l'appelant n'expose aucune plage arbitraire. Le CA de chaque période est la
    **somme signée** des lignes `cash_journal` `PAYMENT`/`ADJUSTMENT` (net des
    corrections #34), calculée **en base** : la réponse ne porte que des montants, des
    dates et la devise (§11.3), aucune PII ni ligne de paiement. Un salon **sans
    activité** → totaux à `0.00` (état vide légitime, ≠ erreur). Lecture pure : aucune
    écriture, aucun audit.
    """

    reference_date = date if date is not None else _today()
    summary = SummarizeRevenue(cash_journal_repo).execute(salon_id, reference_date)
    return _summary_response(summary)


@router.get(
    "/{salon_id}/service-demand",
    response_model=ServiceDemandResponse,
    summary="Prestations les plus demandées du salon (volume & revenu, US-6.3 §6)",
    responses={
        200: {"description": "Prestations du salon classées par volume et par revenu"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`date_from`/`date_to` mal formé ou incohérent"},
    },
)
def get_service_demand(
    salon_id: uuid.UUID,
    queue_ticket_repo: Annotated[
        QueueTicketRepository, Depends(get_queue_ticket_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    date_from: Annotated[
        datetime.date | None,
        Query(description="Premier jour inclus (AAAA-MM-JJ) ; absent = toute l'histoire"),
    ] = None,
    date_to: Annotated[
        datetime.date | None,
        Query(description="Dernier jour inclus (AAAA-MM-JJ) ; absent = toute l'histoire"),
    ] = None,
) -> ServiceDemandResponse:
    """Prestations les plus demandées du salon, **par volume et par revenu** (#41).

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, **troisième**
    consommateur de cette permission `MANAGER` après #39/#40) : le `salon_id` vient du
    chemin, et le dépôt refiltre `salon_id` en SQL (défense en profondeur §11.2). Un
    salon hors périmètre est un `403` **indiscernable** (aucun oracle). Le segment
    `service-demand` est **distinct** de `/{salon_id}/services/{service_id}`
    (`services.py`) : aucun littéral n'est parsé comme un `service_id`.

    Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`, convention #21) sont
    **optionnelles** : absentes = **toute l'histoire** ; une seule fournie laisse
    l'autre borne ouverte ; `date_to < date_from` → `422` (garde explicite) ; une date
    mal formée → `422` (FastAPI). Le classement ne compte que les tickets `done`
    (imposé serveur, « réalisées uniquement ») ; le revenu est la somme des `services
    .price` **courants** (résolution en direct, décision #148). L'agrégat est calculé
    **en base** (`GROUP BY service_id`) : la réponse ne porte que des libellés, des
    compteurs, des montants, la période et la devise (§11.3), aucune PII. Un salon
    **sans ticket réalisé** → classements vides (état vide légitime, ≠ erreur). Lecture
    pure : aucune écriture, aucun audit.
    """

    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    ranking = SummarizeServiceDemand(queue_ticket_repo).execute(
        salon_id,
        date_from=date_from,
        date_to=date_to,
    )
    return _service_demand_response(ranking)


@router.get(
    "/{salon_id}/hairdresser-performance",
    response_model=HairdresserPerformanceResponse,
    summary="Performance des coiffeurs du salon : prestations, CA, taux d'annulation (US-6.5 §6)",
    responses={
        200: {"description": "Performance par coiffeur du salon sur la période"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`date_from`/`date_to` mal formé ou incohérent"},
    },
)
def get_hairdresser_performance(
    salon_id: uuid.UUID,
    queue_ticket_repo: Annotated[
        QueueTicketRepository, Depends(get_queue_ticket_repository)
    ],
    cash_journal_repo: Annotated[
        CashJournalRepository, Depends(get_cash_journal_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    date_from: Annotated[
        datetime.date | None,
        Query(description="Premier jour inclus (AAAA-MM-JJ) ; absent = mois courant"),
    ] = None,
    date_to: Annotated[
        datetime.date | None,
        Query(description="Dernier jour inclus (AAAA-MM-JJ) ; absent = mois courant"),
    ] = None,
) -> HairdresserPerformanceResponse:
    """Performance des coiffeurs du salon : prestations, CA, taux d'annulation (#43).

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, **quatrième**
    consommateur de cette permission `MANAGER` après #39/#40/#41) : le `salon_id`
    vient du chemin, et les dépôts refiltrent `salon_id` en SQL (défense en profondeur
    §11.2). Un salon hors périmètre est un `403` **indiscernable** (aucun oracle). Le
    segment `hairdresser-performance` est **distinct** des autres routes
    `/{salon_id}/…` (`employees`, `customers`, `services/{service_id}`, `payments`,
    `revenue/summary`, `service-demand`) : aucun littéral n'est parsé comme un UUID.

    Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`, convention #21) sont
    **optionnelles** : absentes (ou une seule fournie), la période est **résolue** au
    **mois civil courant** (`month_bounds(_today())`, symétrie #40) ; `date_to <
    date_from` → `422` (garde explicite, patron `get_service_demand`) ; une date mal
    formée → `422` (FastAPI). Pour chaque coiffeur assigné à ≥ 1 ticket du salon sur la
    période, la réponse porte les **prestations réalisées** (occurrences des tickets
    `done`, imposé serveur §8.1), le **CA généré** (net `cash_journal` **attribué**
    via `payments → queue_tickets.hairdresser_id`, net des corrections #34) et le
    **taux d'annulation** (tickets `expired` / tickets assignés — équivalent walk-in)
    — prestations & taux depuis la **file d'attente**, CA depuis la **caisse**. Les
    agrégats sont calculés **en base** (`GROUP BY hairdresser_id`) : la réponse ne
    porte que l'identité **d'affichage** de l'employé (`hairdresser_id` + nom, jamais
    son contact), des compteurs, des montants, un taux et des dates (§11.3), aucune
    PII client. Un salon **sans coiffeur assigné** → liste vide (état vide légitime,
    ≠ erreur). Lecture pure : aucune écriture, aucun audit.
    """

    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    if date_from is None or date_to is None:
        # Défaut = mois civil courant (les deux bornes ensemble), symétrie #40.
        date_from, date_to = month_bounds(_today())
    report = SummarizeHairdresserPerformance(
        queue_ticket_repo, cash_journal_repo
    ).execute(
        salon_id,
        date_from=date_from,
        date_to=date_to,
    )
    return _hairdresser_performance_response(
        report, date_from=date_from, date_to=date_to
    )


# --------------------------------------------------------------------------- #
# Routes — **Dashboard Manager · activité du salon** (#148).
#
# Sixième+ consommateur de `STATS_READ_SALON` (MANAGER seul) + `require_salon_scope`
# (isolation §11.2). Toutes sous le préfixe `/salons/{salon_id}/dashboard/` (segment
# **distinct** de `customers`/`services`/`payments`/`queue`). Deny-by-default :
# rien n'entre dans `PUBLIC_ROUTE_PATHS`. Lecture pure — aucune écriture, aucun audit.
# --------------------------------------------------------------------------- #
@router.get(
    "/{salon_id}/dashboard/kpis",
    response_model=DashboardKpisResponse,
    summary="Dashboard Manager — 4 KPI d'activité du salon + évolution (§7.2, #148)",
    responses={
        200: {"description": "Les 4 KPI du salon (+ évolution) sur la période"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`period`/`date_from`/`date_to` mal formé ou incohérent"},
    },
)
def get_dashboard_kpis(
    salon_id: uuid.UUID,
    queue_ticket_repo: Annotated[
        QueueTicketRepository, Depends(get_queue_ticket_repository)
    ],
    cash_journal_repo: Annotated[
        CashJournalRepository, Depends(get_cash_journal_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    period: Annotated[
        str,
        Query(description="Filtre : today | week | month | custom (défaut today)"),
    ] = "today",
    date_from: Annotated[
        datetime.date | None,
        Query(description="Premier jour inclus (requis si period=custom)"),
    ] = None,
    date_to: Annotated[
        datetime.date | None,
        Query(description="Dernier jour inclus (requis si period=custom)"),
    ] = None,
    reference: Annotated[
        datetime.date | None,
        Query(description="Date de référence des périodes relatives ; absent = aujourd'hui"),
    ] = None,
) -> DashboardKpisResponse:
    """Les **4 cartes KPI** du tableau de bord d'activité + évolution (§7.2, #148).

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, **sixième**
    consommateur de cette permission `MANAGER` après #39–#43) : le `salon_id` vient du
    chemin, et les dépôts refiltrent `salon_id` en SQL (défense en profondeur §11.2). Un
    salon hors périmètre est un `403` **indiscernable** (aucun oracle). Le segment
    `dashboard` est **distinct** des routes `revenue/summary`/`service-demand`/…

    Le **filtre de période** (`today`/`week`/`month`/`custom`, défaut `today`) est
    résolu **côté serveur** en bornes de jour civil (`Africa/Abidjan`, convention #21) ;
    `custom` exige ses deux bornes et `date_to ≥ date_from` (sinon `422`). Les KPI
    « clients en attente » (tickets `waiting`), « chiffre d'affaires » (net
    `cash_journal`) et « nombre de clientes » (fiches distinctes `done`) portent leur
    **évolution** vs la **période précédente de même longueur** ; « prestations en
    cours » est un **instantané** (décompte direct des tickets `in_progress`) — sans
    évolution. Les statuts sont **imposés serveur**. Agrégats calculés **en base** : la
    réponse ne porte que des compteurs, un montant, une devise et des dates (§11.3),
    **aucune PII**. Un salon **sans activité** → KPI à `0` (état vide légitime, ≠
    erreur). Lecture pure.
    """

    date_from_resolved, date_to_resolved = _resolve_dashboard_period(
        period, reference=reference, date_from=date_from, date_to=date_to
    )
    kpis = SummarizeDashboardKpis(queue_ticket_repo, cash_journal_repo).execute(
        salon_id,
        date_from=date_from_resolved,
        date_to=date_to_resolved,
        now=_now_salon().replace(tzinfo=None),
    )
    return _kpis_response(kpis, kind=period)


@router.get(
    "/{salon_id}/dashboard/revenue-series",
    response_model=RevenueSeriesResponse,
    summary="Dashboard Manager — série d'évolution du chiffre d'affaires (§7.2, #148)",
    responses={
        200: {"description": "Série du CA net du salon par jour civil de la période"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`period`/`date_from`/`date_to` mal formé ou incohérent"},
    },
)
def get_dashboard_revenue_series(
    salon_id: uuid.UUID,
    cash_journal_repo: Annotated[
        CashJournalRepository, Depends(get_cash_journal_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    period: Annotated[
        str,
        Query(description="Filtre : today | week | month | custom (défaut today)"),
    ] = "today",
    date_from: Annotated[datetime.date | None, Query()] = None,
    date_to: Annotated[datetime.date | None, Query()] = None,
    reference: Annotated[datetime.date | None, Query()] = None,
) -> RevenueSeriesResponse:
    """Série temporelle du **chiffre d'affaires** du salon (graphique d'évolution, #148).

    Route **salon-scopée** (`STATS_READ_SALON` + `require_salon_scope`). Le net
    `cash_journal` (`PAYMENT`/`ADJUSTMENT`, #34) est agrégé **en base** par **jour
    civil** de la période résolue ; les jours vides valent `0.00` (axe continu). La
    réponse ne porte que des dates, des montants (chaînes décimales) et la devise
    (§11.3), **aucune PII**. Filtre de période & `422` identiques à `dashboard/kpis`.
    """

    date_from_resolved, date_to_resolved = _resolve_dashboard_period(
        period, reference=reference, date_from=date_from, date_to=date_to
    )
    buckets = SummarizeRevenueSeries(cash_journal_repo).execute(
        salon_id, date_from=date_from_resolved, date_to=date_to_resolved
    )
    return _revenue_series_response(
        buckets,
        date_from=date_from_resolved,
        date_to=date_to_resolved,
        currency=DEFAULT_CURRENCY,
    )


@router.get(
    "/{salon_id}/dashboard/attendance-series",
    response_model=AttendanceSeriesResponse,
    summary="Dashboard Manager — série de fréquentation du salon (§7.2, #148)",
    responses={
        200: {"description": "Série du nombre de tickets du salon par jour de la période"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`period`/`date_from`/`date_to` mal formé ou incohérent"},
    },
)
def get_dashboard_attendance_series(
    salon_id: uuid.UUID,
    queue_ticket_repo: Annotated[
        QueueTicketRepository, Depends(get_queue_ticket_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    period: Annotated[
        str,
        Query(description="Filtre : today | week | month | custom (défaut today)"),
    ] = "today",
    date_from: Annotated[datetime.date | None, Query()] = None,
    date_to: Annotated[datetime.date | None, Query()] = None,
    reference: Annotated[datetime.date | None, Query()] = None,
) -> AttendanceSeriesResponse:
    """Série temporelle de la **fréquentation** du salon (graphique, #148).

    Route **salon-scopée** (`STATS_READ_SALON` + `require_salon_scope`). Le nombre de
    tickets du salon (tous statuts) est agrégé **en base** par **jour civil** de la
    période résolue ; les jours vides valent `0` (axe continu). La réponse ne porte que
    des dates et des compteurs (§11.3), **aucune PII**. Filtre de période & `422`
    identiques à `dashboard/kpis`.
    """

    date_from_resolved, date_to_resolved = _resolve_dashboard_period(
        period, reference=reference, date_from=date_from, date_to=date_to
    )
    buckets = SummarizeAttendanceSeries(queue_ticket_repo).execute(
        salon_id, date_from=date_from_resolved, date_to=date_to_resolved
    )
    return _attendance_series_response(
        buckets, date_from=date_from_resolved, date_to=date_to_resolved
    )


@router.get(
    "/{salon_id}/dashboard/in-progress",
    response_model=InProgressResponse,
    summary="Dashboard Manager — prestations en cours maintenant (§7.2, #148)",
    responses={
        200: {"description": "Tickets in_progress (noms d'affichage), triés par heure"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def get_dashboard_in_progress(
    salon_id: uuid.UUID,
    queue_ticket_repo: Annotated[
        QueueTicketRepository, Depends(get_queue_ticket_repository)
    ],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
) -> InProgressResponse:
    """Liste des **tickets en cours maintenant** du salon, avec noms (§7.2, #148).

    Route **salon-scopée** (`STATS_READ_SALON` + `require_salon_scope`). Renvoie les
    tickets `in_progress` (décompte direct, aucune arithmétique de créneau —
    contrairement à l'ancien RDV), enrichis des **noms d'affichage** (cliente
    `customer_profiles.full_name`, prestation(s) `services.name`, professionnelle
    `users.full_name`, patron #43/#36) — **jamais** `customer_profile_id`/contact.
    Instantané (`as_of`), indépendant du filtre de période. Liste **vide** si aucun
    ticket en cours (état légitime). Lecture pure.
    """

    now_aware = _now_salon()
    items = ListInProgressServices(queue_ticket_repo).execute(salon_id)
    return _in_progress_response(items, as_of=now_aware)


@router.get(
    "/{salon_id}/dashboard/activity",
    response_model=ActivityResponse,
    summary="Dashboard Manager — timeline des dernières activités (§7.2, #148)",
    responses={
        200: {"description": "Flux fusionné des faits horodatés, trié décroissant (top-N)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`limit` hors bornes"},
    },
)
def get_dashboard_activity(
    salon_id: uuid.UUID,
    payment_repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
    limit: Annotated[
        int,
        Query(
            ge=ACTIVITY_LIMIT_MIN,
            le=ACTIVITY_LIMIT_MAX,
            description="Nombre maximal d'évènements (top-N)",
        ),
    ] = ACTIVITY_LIMIT_DEFAULT,
) -> ActivityResponse:
    """Timeline « Transactions récentes » (§7.2) — faits **réellement horodatés** (#148).

    Route **salon-scopée** (`STATS_READ_SALON` + `require_salon_scope`). Renvoie les
    **paiements** (montant + nom d'affichage, patron #36), triés par horodatage
    **décroissant** et bornés (top-N). Les notifications salon ont disparu avec le
    pivot walk-in exclusif (un client déjà sur place n'a plus de rappel/confirmation à
    recevoir). « Arrivée cliente / début / fin de prestation » **ne figurent pas**
    (aucune source horodatée, §148 Non-Goals). Liste **vide** si aucune activité (état
    légitime). Lecture pure.
    """

    events = ListRecentActivity(payment_repo).execute(salon_id, limit=limit)
    return ActivityResponse(items=[_activity_item(event) for event in events])


@router.get(
    "/{salon_id}/dashboard/alerts",
    response_model=AlertsResponse,
    summary="Dashboard Manager — alertes importantes du salon (§7.2, #148)",
    responses={
        200: {"description": "Alertes dérivées de faits réels (count > 0), ordre stable"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def get_dashboard_alerts(
    salon_id: uuid.UUID,
    queue_ticket_repo: Annotated[
        QueueTicketRepository, Depends(get_queue_ticket_repository)
    ],
    payment_repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    _salon_scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_SALON))
    ],
) -> AlertsResponse:
    """Alertes importantes (§7.2) **dérivées** de faits réels, counts-first (#148).

    Route **salon-scopée** (`STATS_READ_SALON` + `require_salon_scope`). Dérive deux
    alertes : **`payment_anomaly`** (écarts de caisse #36 — tickets `done` sans
    paiement) et **`prolonged_wait`** (tickets `waiting` dont l'attente réelle dépasse
    l'estimation figée). L'ancienne alerte `late` n'a pas d'équivalent walk-in (un
    ticket n'a pas de créneau) et a été retirée. Ne renvoie que les alertes dont
    l'effectif est **> 0**, dans un ordre d'affichage stable. Counts-only, **aucune
    PII**. L'alerte « anomalie de paiement » réutilise le dépôt paiements (#36) — le
    `MANAGER` détient `STATS_READ_SALON` **et** `CASH_JOURNAL_READ` ; l'écran
    d'activité reste sous une permission unique (cohérence). Lecture pure.
    """

    alerts = ListDashboardAlerts(queue_ticket_repo, payment_repo).execute(
        salon_id, now=_now_salon().replace(tzinfo=None)
    )
    return AlertsResponse(items=[_alert_item(alert) for alert in alerts])


__all__ = ["router"]
