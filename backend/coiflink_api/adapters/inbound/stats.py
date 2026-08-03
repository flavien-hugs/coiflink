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
  occurrences des RDV `COMPLETED` ; revenu = somme des `price_at_booking` (prix figés,
  XOF) — grandeur **distincte** du CA (#40), voir `application/service_demand.py`.

- **`GET /salons/{salon_id}/active-clients`** — segmentation des clients du salon
  (US-6.4, #42), garde `STATS_READ_SALON`. Renvoie, pour une **période** optionnelle
  (`date_from`/`date_to`, absents = mois civil courant), la répartition des clients du
  salon (comptes ayant des RDV `COMPLETED`) en **trois compteurs** : **nouveaux**
  (première visite dans la période), **récurrents** (vus dans la période **et** avant)
  et **inactifs** (vus avant, silencieux sur la période) — voir
  `application/client_segments.py`.

- **`GET /salons/{salon_id}/hairdresser-performance`** — performance des coiffeurs
  (US-6.5, #43), garde `STATS_READ_SALON`. Renvoie, pour une **période** optionnelle
  (`date_from`/`date_to`, absents = mois civil courant), **une ligne par coiffeur**
  assigné à ≥ 1 RDV du salon sur la période : **prestations réalisées** (occurrences
  des RDV `COMPLETED`), **CA généré** (net `cash_journal` **attribué** via `payments →
  appointments.hairdresser_id`, cohérent avec la caisse) et **taux d'annulation** (RDV
  `CANCELLED` / RDV assignés). Prestations & taux dérivent **du planning**, le CA **de
  la caisse** — voir `application/hairdresser_performance.py`. **Seul** endpoint stats
  **nominatif** : il émet le `hairdresser_id` + le **nom d'affichage** de l'employé
  (`users.full_name`, convention #34), jamais son contact.

**Router `stats` dédié (spec §Open Questions 6).** Cette surface porte la permission
`STATS_READ_SALON` (statistiques du salon), distincte de la caisse
(`PAYMENT_RECORD`/`CASH_JOURNAL_READ`, servie par `payments.py`). `STATS_READ_SALON` a
désormais **cinq** consommateurs : RDV du jour (#39), CA (#40), prestations les plus
demandées (#41), clients actifs (#42) et performance des coiffeurs (#43).

**Non-PII (§11.3), lecture pure.** Les réponses ne portent **que** des montants
(`Decimal` en chaîne), des compteurs, des libellés de prestation, des dates et une
devise : **aucun** `client_id`, `appointment_id`, `reference`, `recorded_by`, ni ligne
de RDV/paiement. Les agrégats sont calculés **en base** (`SUM`/`GROUP BY`), pas en
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
from coiflink_api.adapters.outbound.persistence.appointment_repository import (
    SqlAppointmentRepository,
)
from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
    SqlCashJournalEntryRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.appointment_repository import (
    AppointmentRepository,
)
from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.application.client_segments import SummarizeActiveClients
from coiflink_api.application.hairdresser_performance import (
    SummarizeHairdresserPerformance,
)
from coiflink_api.application.revenue import SummarizeRevenue
from coiflink_api.application.service_demand import SummarizeServiceDemand
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.client_segments import ClientSegments
from coiflink_api.domain.hairdresser_performance import (
    HairdresserPerformance,
    HairdresserPerformanceReport,
)
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

    `volume` = nombre d'occurrences **réalisées** (RDV `COMPLETED`) ; `revenue` =
    somme des `price_at_booking` (prix **figés**, `NUMERIC(12,2)`, sérialisé en
    **chaîne** décimale, jamais un flottant). `name` = libellé courant
    (`services.name`), résoluble même si la prestation est désactivée. **Aucune PII**
    (pas de `client_id`/`appointment_id`).
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
    devise (§11.3) : **jamais** de `client_id`, `appointment_id`, ni ligne de
    RDV/paiement. Classements **vides** si aucun RDV `COMPLETED` (état normal).
    """

    currency: str = Field(examples=["XOF"])
    date_from: datetime.date | None = Field(default=None, examples=[None])
    date_to: datetime.date | None = Field(default=None, examples=[None])
    by_volume: list[ServiceDemandItemResponse]
    by_revenue: list[ServiceDemandItemResponse]


class ClientSegmentsResponse(BaseModel):
    """Segmentation des clients du salon sur une période (US-6.4, #42).

    `new` / `recurring` / `inactive` = effectifs (entiers ≥ 0) des **trois segments
    mutuellement exclusifs** relatifs à la période `[date_from, date_to]` : nouveaux
    (première visite `COMPLETED` dans la période), récurrents (vus dans la période
    **et** avant) et inactifs (vus avant, silencieux sur la période). `active = new +
    recurring` est exposé pour éviter un recalcul côté front. Ne porte **que** des
    compteurs et des dates (§11.3) : **jamais** de `client_id`, `appointment_id`, nom,
    téléphone, ni ligne de RDV. Tous les compteurs à `0` (salon sans RDV `COMPLETED`
    sur la période) est un état **vide légitime**, pas une erreur.
    """

    date_from: datetime.date = Field(examples=["2026-08-01"])
    date_to: datetime.date = Field(examples=["2026-08-31"])
    new: int = Field(examples=[12])
    recurring: int = Field(examples=[27])
    inactive: int = Field(examples=[8])
    active: int = Field(examples=[39])


class HairdresserPerformanceItemResponse(BaseModel):
    """Performance d'**un** coiffeur du salon sur la période (US-6.5, #43).

    `hairdresser_id` + `hairdresser_name` = identité **d'affichage** de l'employé
    (`users.full_name`, convention #34) — **seul** champ nominatif autorisé, jamais son
    contact (`phone`/`email`/`role`). `services_completed` = occurrences de prestations
    réalisées (RDV `COMPLETED`) ; `revenue` = CA net **attribué** (net `cash_journal`
    via `payments → appointments.hairdresser_id`), `Decimal` sérialisé en **chaîne**
    (`NUMERIC(12,2)`, jamais un flottant) ; `cancelled_count` / `total_count` = RDV
    annulés / total assignés ; `cancellation_rate` = `cancelled_count / total_count`,
    `Decimal` en **chaîne** ∈ `[0, 1]` (`"0.0000"` si `total_count == 0`). **Aucune
    PII client** (pas de `client_id`/`appointment_id`).
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

    `hairdressers` = **une entrée par coiffeur** assigné à ≥ 1 RDV du salon sur la
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
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_cash_journal_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CashJournalRepository:
    """Dépôt du journal de caisse adossé à la session de la requête (lecture seule)."""

    return SqlCashJournalEntryRepository(session)


def get_appointment_repository(
    session: Annotated[Session, Depends(get_session)],
) -> AppointmentRepository:
    """Dépôt de rendez-vous adossé à la session de la requête (lecture seule, #41).

    Local au router `stats` (comme `get_cash_journal_repository`) pour rester
    surchargeable indépendamment en test via `app.dependency_overrides`.
    """

    return SqlAppointmentRepository(session)


def _today() -> datetime.date:
    """Jour civil courant dans le fuseau du salon (Africa/Abidjan, convention #21)."""

    return datetime.datetime.now(SALON_TIMEZONE).date()


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


def _active_clients_response(
    segments: ClientSegments,
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> ClientSegmentsResponse:
    # Les bornes échoient la période **résolue** par la route (défaut mois courant) :
    # `segments.date_from`/`date_to` les portent déjà, on les passe explicitement pour
    # garantir une réponse non nulle même si le domaine évoluait.
    return ClientSegmentsResponse(
        date_from=date_from,
        date_to=date_to,
        new=segments.new,
        recurring=segments.recurring,
        inactive=segments.inactive,
        active=segments.active,
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
    # Les bornes échoient la période **résolue** par la route (défaut mois courant) —
    # on les passe explicitement (symétrie `_active_clients_response`).
    return HairdresserPerformanceResponse(
        currency=report.currency,
        date_from=date_from,
        date_to=date_to,
        hairdressers=[
            _hairdresser_performance_item(entry) for entry in report.entries
        ],
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
    appointment_repo: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
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
    l'autre borne ouverte ; `date_to < date_from` → `422` (garde explicite, patron
    `list_salon_appointments`) ; une date mal formée → `422` (FastAPI). Le classement
    ne compte que les RDV `COMPLETED` (imposé serveur, « réalisées uniquement ») ; le
    revenu est la somme des `price_at_booking` (prix figés, XOF). L'agrégat est calculé
    **en base** (`GROUP BY service_id`) : la réponse ne porte que des libellés, des
    compteurs, des montants, la période et la devise (§11.3), aucune PII. Un salon
    **sans RDV réalisé** → classements vides (état vide légitime, ≠ erreur). Lecture
    pure : aucune écriture, aucun audit.
    """

    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    ranking = SummarizeServiceDemand(appointment_repo).execute(
        salon_id,
        date_from=date_from,
        date_to=date_to,
    )
    return _service_demand_response(ranking)


@router.get(
    "/{salon_id}/active-clients",
    response_model=ClientSegmentsResponse,
    summary="Clients actifs du salon : nouveaux / récurrents / inactifs (US-6.4 §6)",
    responses={
        200: {"description": "Segmentation des clients du salon sur la période"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "`date_from`/`date_to` mal formé ou incohérent"},
    },
)
def get_active_clients(
    salon_id: uuid.UUID,
    appointment_repo: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
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
) -> ClientSegmentsResponse:
    """Segmentation des clients du salon (nouveaux / récurrents / inactifs, #42).

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, **quatrième**
    consommateur de cette permission `MANAGER` après #39/#40/#41) : le `salon_id` vient
    du chemin, et le dépôt refiltre `salon_id` en SQL (défense en profondeur §11.2). Un
    salon hors périmètre est un `403` **indiscernable** (aucun oracle). Le segment
    `active-clients` est **distinct** de `/{salon_id}/customers/…` (`customers.py`,
    permission `CUSTOMER_MANAGE`, fiche-scopé) : il reste sous `STATS_READ_SALON`.

    Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`, convention #21) sont
    **optionnelles** : absentes (ou une seule fournie), la période est **résolue** au
    **mois civil courant** (`month_bounds(_today())`, symétrie #40) — le dashboard
    affiche une valeur immédiate sans saisie ; `date_to < date_from` → `422` (garde
    explicite, patron `get_service_demand`) ; une date mal formée → `422` (FastAPI). La
    segmentation ne compte que les RDV `COMPLETED` (imposé serveur, « réalisées
    uniquement » §8.1) : un client est **nouveau** si sa première visite tombe dans la
    période, **récurrent** s'il a été vu dans la période **et** avant, **inactif** s'il
    a été vu avant mais pas dans la période. L'agrégat est calculé **en base**
    (`GROUP BY client_id`, `client_id` jamais émis) : la réponse ne porte que des
    compteurs et des dates (§11.3), aucune PII. Un salon **sans RDV réalisé** →
    compteurs à `0` (état vide légitime, ≠ erreur). Lecture pure : aucune écriture,
    aucun audit.
    """

    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    if date_from is None or date_to is None:
        # Défaut = mois civil courant (les deux bornes ensemble) : une seule borne
        # fournie ne suffit pas à cadrer la segmentation, on retombe sur le mois.
        date_from, date_to = month_bounds(_today())
    segments = SummarizeActiveClients(appointment_repo).execute(
        salon_id,
        date_from=date_from,
        date_to=date_to,
    )
    return _active_clients_response(
        segments, date_from=date_from, date_to=date_to
    )


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
    appointment_repo: Annotated[
        AppointmentRepository, Depends(get_appointment_repository)
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

    Route **salon-scopée** (`require_salon_scope` + `STATS_READ_SALON`, **cinquième**
    consommateur de cette permission `MANAGER` après #39/#40/#41/#42) : le `salon_id`
    vient du chemin, et les dépôts refiltrent `salon_id` en SQL (défense en profondeur
    §11.2). Un salon hors périmètre est un `403` **indiscernable** (aucun oracle). Le
    segment `hairdresser-performance` est **distinct** des autres routes
    `/{salon_id}/…` (`employees`, `customers`, `services/{service_id}`, `payments`,
    `revenue/summary`, `service-demand`, `active-clients`) : aucun littéral n'est parsé
    comme un UUID.

    Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`, convention #21) sont
    **optionnelles** : absentes (ou une seule fournie), la période est **résolue** au
    **mois civil courant** (`month_bounds(_today())`, symétrie #42) ; `date_to <
    date_from` → `422` (garde explicite, patron `get_active_clients`) ; une date mal
    formée → `422` (FastAPI). Pour chaque coiffeur assigné à ≥ 1 RDV du salon sur la
    période, la réponse porte les **prestations réalisées** (occurrences des RDV
    `COMPLETED`, imposé serveur §8.1), le **CA généré** (net `cash_journal` **attribué**
    via `payments → appointments.hairdresser_id`, net des corrections #34) et le **taux
    d'annulation** (RDV `CANCELLED` / RDV assignés) — prestations & taux depuis le
    **planning**, CA depuis la **caisse**. Les agrégats sont calculés **en base**
    (`GROUP BY hairdresser_id`) : la réponse ne porte que l'identité **d'affichage** de
    l'employé (`hairdresser_id` + nom, jamais son contact), des compteurs, des montants,
    un taux et des dates (§11.3), aucune PII client. Un salon **sans coiffeur assigné**
    → liste vide (état vide légitime, ≠ erreur). Lecture pure : aucune écriture, aucun
    audit.
    """

    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La date de fin précède la date de début.",
        )
    if date_from is None or date_to is None:
        # Défaut = mois civil courant (les deux bornes ensemble), symétrie #42.
        date_from, date_to = month_bounds(_today())
    report = SummarizeHairdresserPerformance(
        appointment_repo, cash_journal_repo
    ).execute(
        salon_id,
        date_from=date_from,
        date_to=date_to,
    )
    return _hairdresser_performance_response(
        report, date_from=date_from, date_to=date_to
    )


__all__ = ["router"]
