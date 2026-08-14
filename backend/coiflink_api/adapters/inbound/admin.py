"""Adapter entrant (driving) : router HTTP **supervision plateforme** (admin, US-5.6/6.6).

Expose, sous `/admin/…` (router **plateforme**, non salon-scopé) :

- **`GET /admin/transactions/summary`** — supervision agrégée des transactions
  (US-5.6, #37), garde `STATS_READ_PLATFORM`. Renvoie, **par salon**, des
  **agrégats** de transactions (nombre de paiements, nombre de corrections, montant
  **net** encaissé, devise) et l'**identité métier** du salon (id + nom) — **sans
  aucune PII de paiement** (§11.3).
- **`GET /admin/kpis`** — KPI globaux de la plateforme (US-6.6, #44), garde
  `STATS_READ_PLATFORM` (**deuxième** consommateur). Renvoie un **instantané unique**
  (non paginé) de **scalaires globaux** consolidés sur toute la plateforme : salons
  inscrits (`salons_total`) et actifs (`salons_active`), clients inscrits
  (`clients_total`), tickets walk-in (`tickets_total` + `tickets_this_month`,
  rebranché sur `queue_tickets` avec le pivot walk-in exclusif #148) et **revenus
  plateforme** (`revenue_total` + `revenue_this_month`, net via `cash_journal`, même
  source de vérité que #37/#40). **Aucune** identité d'entité n'est émise (§11.3,
  plus fort que #37). Le KPI « abonnements » du backlog est **volontairement
  absent** : aucun modèle d'abonnement n'existe (voir `domain/platform_kpis.py`,
  ADR-0032).

**Vue plateforme, pas exploitation d'un salon.** À la différence des lectures caisse
salon-scopées (#34/#35/#36, montées sous `/salons/{salon_id}/…`, gardées par
`CASH_JOURNAL_READ` du seul `MANAGER` + `require_salon_scope`), il s'agit de lectures
**inter-salons** réservées à l'`ADMIN`. La garde `require_permission(
STATS_READ_PLATFORM)` **suffit** : l'admin voit tous les salons (lecture plateforme
légitime, `AccessPolicy.scope_of` lui accorde déjà `SalonScope.platform()`), on
**n'utilise pas** `require_salon_scope` (il n'a pas de salon dans sa portée
« propriété » et les routes ne sont pas sous `/salons/{salon_id}`). L'`ADMIN` est le
**seul** rôle porteur de `STATS_READ_PLATFORM` (matrice fermée §4.1, non modifiée) →
`403` générique pour tout autre rôle, `401` sans jeton.

**Aucun** verbe destructif ni aucune écriture : lecture pure, **sans** audit §11.4
(parité #34/#35/#36/#39–#43). **Aucun** chemin n'entre dans `PUBLIC_ROUTE_PATHS` : la
garde `require_permission` satisfait l'invariant deny-by-default (vérifié par
`unprotected_routes`).

Le router traduit HTTP → cas d'usage applicatif, assemble par injection de
dépendances, puis retraduit `InvalidPlatformSummaryFilter → 422` (message neutre).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import require_permission
from coiflink_api.adapters.outbound.persistence.platform_kpi_repository import (
    SqlPlatformKpiRepository,
)
from coiflink_api.adapters.outbound.persistence.platform_transaction_repository import (
    SqlPlatformTransactionRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.platform_kpis import ComputePlatformKpis
from coiflink_api.application.platform_transactions import SummarizeSalonTransactions
from coiflink_api.application.ports.platform_kpi_repository import (
    PlatformKpiRepository,
)
from coiflink_api.application.ports.platform_transaction_repository import (
    PLATFORM_SUMMARY_LIMIT_DEFAULT,
    PLATFORM_SUMMARY_LIMIT_MAX,
    PLATFORM_SUMMARY_LIMIT_MIN,
    PlatformTransactionRepository,
)
from coiflink_api.domain.errors import InvalidPlatformSummaryFilter
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.platform_kpis import PlatformKpiSnapshot
from coiflink_api.domain.platform_transactions import (
    SalonTransactionSummary,
    validate_platform_summary_filter,
)
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.time_window import SALON_TIMEZONE

router = APIRouter(prefix="/admin", tags=["admin"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `payments.py`).
#
# Champs **explicites** (jamais `orm_mode`/`extra`) : la forme de la réponse est
# figée par un test qui échoue si un champ PII interdit apparaît (§11.3).
# --------------------------------------------------------------------------- #
class SalonTransactionSummaryResponse(BaseModel):
    """Agrégat des transactions **d'un** salon (US-5.6, #37) — **sans PII de paiement**.

    Ne porte **que** des compteurs, un montant net et l'**identité métier** du salon.
    `total_amount` est la **somme signée** des lignes `cash_journal` (net des
    corrections), sérialisé en chaîne décimale (`NUMERIC(12,2)`, jamais de flottant).
    **Jamais** de `client_id`, nom de client, `reference`, `recorded_by`, `owner_id`,
    ni ligne de paiement individuelle.
    """

    salon_id: uuid.UUID
    salon_name: str
    payment_count: int
    adjustment_count: int
    total_amount: decimal.Decimal = Field(examples=["615000.00"])
    currency: str = Field(examples=["XOF"])


class SalonTransactionSummaryPageResponse(BaseModel):
    """Réponse paginée de `GET /admin/transactions/summary` : items + total + bornes."""

    items: list[SalonTransactionSummaryResponse]
    total: int
    limit: int
    offset: int


class PlatformKpiResponse(BaseModel):
    """Instantané consolidé des **KPI globaux** de la plateforme (US-6.6, #44).

    Miroir **non-PII** de `SalonTransactionSummaryResponse`, mais **plus fort** : ne
    porte **que** des scalaires globaux (compteurs, montants, dates, devise) —
    **aucune** identité d'entité (ni `salon_id`, `salon_name`, `client_id`, `owner_id`,
    ni ligne quelconque). Champs **explicites** (jamais `orm_mode`/`extra`) ; un test
    d'API **fige** la forme (échec si un champ interdit apparaît).

    `revenue_total`/`revenue_this_month` sont la **somme signée** des lignes
    `cash_journal` (net des corrections #34, **même source de vérité** que #37/#40),
    sérialisés en chaîne décimale (`NUMERIC(12,2)`, jamais un flottant) ; ils **peuvent
    être négatifs**. `tickets_total` compte **tous** les tickets walk-in émis (volume
    plateforme, tous statuts, rebranché sur `queue_tickets` avec le pivot #148).
    **Aucun** champ `subscriptions` : aucun modèle d'abonnement n'existe (voir
    `domain/platform_kpis.py`, ADR-0032) — « revenus plateforme » (flux net encaissé)
    ≠ « revenus d'abonnement » (facturation SaaS inexistante).
    """

    salons_total: int = Field(examples=[128])
    salons_active: int = Field(examples=[97])
    clients_total: int = Field(examples=[5421])
    tickets_total: int = Field(examples=[18342])
    tickets_this_month: int = Field(examples=[1204])
    revenue_total: decimal.Decimal = Field(examples=["12500000.00"])
    revenue_this_month: decimal.Decimal = Field(examples=["980000.00"])
    currency: str = Field(examples=["XOF"])
    reference_date: datetime.date = Field(examples=["2026-08-03"])
    month_from: datetime.date = Field(examples=["2026-08-01"])
    month_to: datetime.date = Field(examples=["2026-08-31"])


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_platform_transaction_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PlatformTransactionRepository:
    """Dépôt d'agrégation plateforme adossé à la session de la requête (lecture seule)."""

    return SqlPlatformTransactionRepository(session)


def get_platform_kpi_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PlatformKpiRepository:
    """Dépôt de KPI globaux plateforme adossé à la session de la requête (lecture seule).

    Surchargeable indépendamment en test via `app.dependency_overrides` (patron de
    `get_platform_transaction_repository`).
    """

    return SqlPlatformKpiRepository(session)


def _today() -> datetime.date:
    """Jour civil courant dans le fuseau de la plateforme (Africa/Abidjan, convention #21)."""

    return datetime.datetime.now(SALON_TIMEZONE).date()


def _summary_response(
    summary: SalonTransactionSummary,
) -> SalonTransactionSummaryResponse:
    return SalonTransactionSummaryResponse(
        salon_id=summary.salon_id,
        salon_name=summary.salon_name,
        payment_count=summary.payment_count,
        adjustment_count=summary.adjustment_count,
        total_amount=summary.total_amount,
        currency=summary.currency,
    )


def _kpi_response(snapshot: PlatformKpiSnapshot) -> PlatformKpiResponse:
    return PlatformKpiResponse(
        salons_total=snapshot.salons_total,
        salons_active=snapshot.salons_active,
        clients_total=snapshot.clients_total,
        tickets_total=snapshot.tickets_total,
        tickets_this_month=snapshot.tickets_this_month,
        revenue_total=snapshot.revenue_total,
        revenue_this_month=snapshot.revenue_this_month,
        currency=snapshot.currency,
        reference_date=snapshot.reference_date,
        month_from=snapshot.month_from,
        month_to=snapshot.month_to,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    "/transactions/summary",
    response_model=SalonTransactionSummaryPageResponse,
    summary="Supervision agrégée des transactions par salon (admin, paginé, sans PII)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (générique) ou compte désactivé"},
        422: {"description": "Filtre de dates incohérent (plage `date_from > date_to`)"},
    },
)
def summarize_salon_transactions(
    platform_repo: Annotated[
        PlatformTransactionRepository, Depends(get_platform_transaction_repository)
    ],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_PLATFORM))
    ],
    date_from: Annotated[datetime.date | None, Query()] = None,
    date_to: Annotated[datetime.date | None, Query()] = None,
    limit: Annotated[
        int,
        Query(ge=PLATFORM_SUMMARY_LIMIT_MIN, le=PLATFORM_SUMMARY_LIMIT_MAX),
    ] = PLATFORM_SUMMARY_LIMIT_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SalonTransactionSummaryPageResponse:
    """Agrège les transactions **par salon** sur toute la plateforme (US-5.6, #37).

    Réservé à l'`ADMIN` (`STATS_READ_PLATFORM`) — supervision **inter-salons**, pas
    exploitation d'un salon. Chaque item porte, pour **un** salon avec activité, le
    nombre de paiements, le nombre de corrections et le **montant net** encaissé
    (somme signée des lignes `cash_journal`, source de vérité #34 : un paiement
    corrigé fait baisser le net et incrémente `adjustment_count`). Bornes de dates
    **optionnelles** (`date_from`/`date_to`, jour civil `Africa/Abidjan`, comparées à
    `created_at`) ; une plage incohérente → `422` (`InvalidPlatformSummaryFilter`),
    message métier neutre. Tri déterministe `salon_name ASC`, bornes en SQL (garde de
    coût §12.1). Lecture seule : **aucune** écriture, **aucun** audit, **aucune** PII
    de paiement (§11.3).
    """

    try:
        summary_filter = validate_platform_summary_filter(
            date_from=date_from, date_to=date_to
        )
    except InvalidPlatformSummaryFilter as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    page, total = SummarizeSalonTransactions(platform_repo).execute(
        filter=summary_filter, limit=limit, offset=offset
    )
    return SalonTransactionSummaryPageResponse(
        items=[_summary_response(summary) for summary in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/kpis",
    response_model=PlatformKpiResponse,
    summary="KPI globaux de la plateforme (admin, instantané consolidé, sans PII)",
    responses={
        200: {"description": "Instantané consolidé des KPI globaux de la plateforme"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (générique) ou compte désactivé"},
        422: {"description": "Paramètre `reference_date` mal formé"},
    },
)
def get_platform_kpis(
    kpi_repo: Annotated[
        PlatformKpiRepository, Depends(get_platform_kpi_repository)
    ],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.STATS_READ_PLATFORM))
    ],
    reference_date: Annotated[
        datetime.date | None,
        Query(description="Date de référence (AAAA-MM-JJ) ; absent = aujourd'hui"),
    ] = None,
) -> PlatformKpiResponse:
    """KPI **globaux** consolidés de la plateforme (dashboard admin, US-6.6, #44).

    Réservé à l'`ADMIN` (`STATS_READ_PLATFORM`, **deuxième** consommateur après #37) —
    lecture **plateforme** (inter-entités), pas exploitation d'un salon : la garde de
    permission **suffit** (l'admin voit toute la plateforme), pas de
    `require_salon_scope`. Tout autre rôle → `403` générique (aucun oracle), sans jeton
    → `401`, admin non `ACTIVE` → `403` « Compte désactivé. ».

    Renvoie un **instantané unique** (non paginé) de scalaires globaux : salons
    inscrits (`salons_total`) et actifs (`salons_active`), clients inscrits
    (`clients_total`), tickets walk-in (`tickets_total` = **volume émis, tous
    statuts** ; `tickets_this_month` = tickets du mois civil courant comparés sur
    `issued_date`) et **revenus plateforme** (`revenue_total`/`revenue_this_month`
    = **somme signée** des lignes `cash_journal`, net des corrections #34, **même
    source de vérité** que #37/#40 ; « revenus plateforme » = flux net encaissé, **pas**
    un revenu d'abonnement — aucun modèle SaaS n'existe, cf. ADR-0032). Le paramètre
    `reference_date` est **optionnel** : absent, il vaut le jour civil courant
    (`Africa/Abidjan`, convention #21) et cadre la fenêtre mensuelle ; mal formé, il
    donne un `422` (validation Query FastAPI).

    Calcul **en base** (`COUNT`/`SUM`, garde de coût §12.1) : la réponse ne porte que
    des scalaires globaux (§11.3) — **aucune** identité d'entité, **aucune** ligne. Une
    plateforme **vide** → compteurs à `0`, revenus `"0.00"` (état vide légitime, ≠
    erreur). Lecture pure : aucune écriture, aucun audit (§11.4).
    """

    snapshot = ComputePlatformKpis(kpi_repo).execute(
        reference_date=reference_date if reference_date is not None else _today()
    )
    return _kpi_response(snapshot)


__all__ = ["router"]
