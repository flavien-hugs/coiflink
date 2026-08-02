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

**Router `stats` dédié (spec §Open Questions 6).** Cette surface porte la permission
`STATS_READ_SALON` (statistiques du salon), distincte de la caisse
(`PAYMENT_RECORD`/`CASH_JOURNAL_READ`, servie par `payments.py`) : les séparer prépare
l'Épic 6 (performance des coiffeurs #43…). `STATS_READ_SALON` a désormais **trois**
consommateurs : RDV du jour (#39), CA (#40) et prestations les plus demandées (#41).

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
from coiflink_api.application.revenue import SummarizeRevenue
from coiflink_api.application.service_demand import SummarizeServiceDemand
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.revenue import RevenuePeriodTotal, RevenueSummary
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


__all__ = ["router"]
