"""Adapter entrant (driving) : router HTTP **supervision plateforme** (admin, US-5.6, #37).

Expose, sous `/admin/…` (router **plateforme**, non salon-scopé) :

- **`GET /admin/transactions/summary`** — supervision agrégée des transactions
  (US-5.6, #37), garde `STATS_READ_PLATFORM`. Renvoie, **par salon**, des
  **agrégats** de transactions (nombre de paiements, nombre de corrections, montant
  **net** encaissé, devise) et l'**identité métier** du salon (id + nom) — **sans
  aucune PII de paiement** (§11.3).

**Vue plateforme, pas exploitation d'un salon.** À la différence des lectures caisse
salon-scopées (#34/#35/#36, montées sous `/salons/{salon_id}/…`, gardées par
`CASH_JOURNAL_READ` du seul `MANAGER` + `require_salon_scope`), il s'agit d'une
supervision **inter-salons** réservée à l'`ADMIN`. La garde `require_permission(
STATS_READ_PLATFORM)` **suffit** : l'admin voit tous les salons (lecture plateforme
légitime, `AccessPolicy.scope_of` lui accorde déjà `SalonScope.platform()`), on
**n'utilise pas** `require_salon_scope` (il n'a pas de salon dans sa portée
« propriété » et la route n'est pas sous `/salons/{salon_id}`). L'`ADMIN` est le
**seul** rôle porteur de `STATS_READ_PLATFORM` (matrice fermée §4.1, non modifiée) →
`403` générique pour tout autre rôle, `401` sans jeton.

**Aucun** verbe destructif ni aucune écriture : lecture pure, **sans** audit §11.4
(parité #34/#35/#36). **Aucun** chemin n'entre dans `PUBLIC_ROUTE_PATHS` : la garde
`require_permission` satisfait l'invariant deny-by-default (vérifié par
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
from coiflink_api.adapters.outbound.persistence.platform_transaction_repository import (
    SqlPlatformTransactionRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.platform_transactions import SummarizeSalonTransactions
from coiflink_api.application.ports.platform_transaction_repository import (
    PLATFORM_SUMMARY_LIMIT_DEFAULT,
    PLATFORM_SUMMARY_LIMIT_MAX,
    PLATFORM_SUMMARY_LIMIT_MIN,
    PlatformTransactionRepository,
)
from coiflink_api.domain.errors import InvalidPlatformSummaryFilter
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.platform_transactions import (
    SalonTransactionSummary,
    validate_platform_summary_filter,
)
from coiflink_api.domain.principal import Principal

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


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_platform_transaction_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PlatformTransactionRepository:
    """Dépôt d'agrégation plateforme adossé à la session de la requête (lecture seule)."""

    return SqlPlatformTransactionRepository(session)


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


__all__ = ["router"]
