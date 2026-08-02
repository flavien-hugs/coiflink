"""Adapter entrant (driving) : router HTTP **statistiques salon** (dashboard gérant, US-6.2, #40).

Expose, sous `/salons/{salon_id}/…` (imbriqué pour hériter de `require_salon_scope`,
isolation §11.2) :

- **`GET /salons/{salon_id}/revenue/summary`** — chiffre d'affaires du salon
  (US-6.2, #40), garde `STATS_READ_SALON`. Renvoie, pour une **date de référence**
  (jour civil `Africa/Abidjan`, défaut = aujourd'hui), le CA du salon sur **trois
  périodes** : le **jour**, la **semaine** (lundi→dimanche) et le **mois** civils qui
  la contiennent. Chaque période porte ses bornes, un **total** net et la devise.

**Router `stats` dédié (spec §Open Questions 6).** Cette surface porte la permission
`STATS_READ_SALON` (statistiques du salon), distincte de la caisse
(`PAYMENT_RECORD`/`CASH_JOURNAL_READ`, servie par `payments.py`) : les séparer prépare
l'Épic 6 (prestations les plus demandées #41, performance des coiffeurs #43…). C'est
le **deuxième** consommateur de `STATS_READ_SALON` après la tranche RDV du jour (#39).

**Source de vérité : le journal de caisse (#34).** Le CA dérive de la **somme signée**
des lignes `cash_journal` `PAYMENT`/`ADJUSTMENT` — donc **net des corrections**, comme
le « montant net » de #37. Un **RDV annulé** (`CANCELLED`) n'a pas de paiement, donc
pas de ligne, donc **aucune** contribution au CA : « annulés exclus » (AC #40, §8.1)
est vrai **par construction**.

**Non-PII (§11.3), lecture pure.** La réponse ne porte **que** des montants (`Decimal`
en chaîne), des dates et une devise : **aucun** `client_id`, `reference`,
`recorded_by`, ni ligne de paiement. Le CA est calculé **en base** (`SUM`), pas en
rapatriant les lignes. Aucune écriture, **aucun** audit §11.4. **Aucun** chemin n'entre
dans `PUBLIC_ROUTE_PATHS` : une donnée financière n'est jamais publique.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
    SqlCashJournalEntryRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.cash_journal_repository import (
    CashJournalRepository,
)
from coiflink_api.application.revenue import SummarizeRevenue
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.revenue import RevenuePeriodTotal, RevenueSummary
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


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_cash_journal_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CashJournalRepository:
    """Dépôt du journal de caisse adossé à la session de la requête (lecture seule)."""

    return SqlCashJournalEntryRepository(session)


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


__all__ = ["router"]
