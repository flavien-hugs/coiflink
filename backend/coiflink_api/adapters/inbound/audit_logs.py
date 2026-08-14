"""Adapter entrant (driving) : router HTTP **journal d'audit** (page gérante « Journal d'audit »).

Expose, sous `/salons/{salon_id}/…` (imbriqué pour hériter de `require_salon_scope`,
isolation §11.2) :

- **`GET /salons/{salon_id}/audit-logs`** — liste **paginée** et **filtrable**
  (plage de dates + catégorie d'action) du journal d'audit du salon, garde
  `AUDIT_LOG_READ` (MANAGER uniquement). Chaque entrée porte l'auteur résolu en
  **nom d'affichage** (`users.full_name`, pas un secret), jamais `event_metadata`
  (toujours vide en pratique, aucune valeur à exposer, §11.3/§11.4).

Réorganisation du tableau de bord (« Journal d'audit » promu en page sidebar,
catégorie « Salon ») : la donnée `audit_logs` existait déjà en base (écrite par
chaque action §11.4 des autres routers), mais n'avait **aucune** lecture
manager-facing avant cette page — ce router est la **première** exposition en
lecture du journal.

**Aucun** verbe destructif n'est exposé : le journal d'audit est **append-only**
(écrit uniquement par les autres routers via `AuditLog.record`, jamais ici).
**Aucun** chemin n'entre dans `PUBLIC_ROUTE_PATHS` : un journal d'audit n'est
**jamais** public.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from coiflink_api.adapters.inbound.payments import get_audit_log
from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.application.audit_log import ListAuditLogs
from coiflink_api.application.ports.audit_log import (
    AUDIT_LOG_LIMIT_DEFAULT,
    AUDIT_LOG_LIMIT_MAX,
    AUDIT_LOG_LIMIT_MIN,
    AuditLog,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.audit import AuditLogEntry, validate_audit_log_filter
from coiflink_api.domain.errors import InvalidAuditLogFilter
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["audit-logs"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `payments.py`).
# --------------------------------------------------------------------------- #
class AuditLogEntryResponse(BaseModel):
    """Une entrée du journal d'audit, vue par le gérant.

    `action` est la valeur brute d'`AuditAction` (le front porte les libellés
    FR) ; `category` est l'une des 7 valeurs fermées d'`AUDIT_CATEGORIES`.
    `actor_name` est un nom d'affichage (pas un secret). **Aucune** `metadata` :
    toujours vide en pratique (§11.3/§11.4), aucune valeur à exposer.
    """

    id: uuid.UUID
    action: str
    category: str
    entity_type: str
    entity_id: uuid.UUID
    actor_name: str
    created_at: datetime.datetime


class AuditLogPageResponse(BaseModel):
    """Réponse paginée de `GET /salons/{salon_id}/audit-logs` : items + total + bornes."""

    items: list[AuditLogEntryResponse]
    total: int
    limit: int
    offset: int


def _audit_log_response(entry: AuditLogEntry) -> AuditLogEntryResponse:
    return AuditLogEntryResponse(
        id=entry.id,
        action=entry.action,
        category=entry.category,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        actor_name=entry.actor_name,
        created_at=entry.created_at,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    "/{salon_id}/audit-logs",
    response_model=AuditLogPageResponse,
    summary="Journal d'audit du salon, paginé et filtrable (plus récent d'abord)",
    responses={
        200: {"description": "Page du journal d'audit du salon"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {
            "description": (
                "Filtre invalide : plage de dates incohérente ou catégorie hors "
                "énumération"
            )
        },
    },
)
def list_audit_logs(
    salon_id: uuid.UUID,
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.AUDIT_LOG_READ))
    ],
    date_from: Annotated[datetime.date | None, Query()] = None,
    date_to: Annotated[datetime.date | None, Query()] = None,
    category: Annotated[
        str | None,
        Query(description="Catégorie fermée (prestations, salon, clients, …)"),
    ] = None,
    limit: Annotated[
        int, Query(ge=AUDIT_LOG_LIMIT_MIN, le=AUDIT_LOG_LIMIT_MAX)
    ] = AUDIT_LOG_LIMIT_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogPageResponse:
    """Liste **filtrable** du journal d'audit du salon de la portée.

    Filtres **optionnels** combinés en **ET** : plage de dates inclusive
    (`date_from`/`date_to`, jour civil `Africa/Abidjan`), `category` (énumération
    fermée). Un filtre invalide → `422` (`InvalidAuditLogFilter`), message métier
    neutre. Isolation §11.2 en profondeur : jamais d'entrée d'un autre salon.
    Lecture seule : aucune écriture, aucun audit (consulter le journal n'est pas
    une action journalisée).
    """

    try:
        audit_log_filter = validate_audit_log_filter(
            date_from=date_from, date_to=date_to, category=category
        )
    except InvalidAuditLogFilter as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    page, total = ListAuditLogs(audit_log).execute(
        salon_id, filter=audit_log_filter, limit=limit, offset=offset
    )
    return AuditLogPageResponse(
        items=[_audit_log_response(entry) for entry in page],
        total=total,
        limit=limit,
        offset=offset,
    )


__all__ = ["router"]
