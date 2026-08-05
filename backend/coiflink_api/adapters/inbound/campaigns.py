"""Adapter entrant (driving) : router HTTP des **campagnes/messages aux clients** (#49).

Expose la **création d'une campagne** (critère d'acceptation « le gérant envoie un
message à un segment de clients ») et une **lecture minimale** qui la rend
observable — liste paginée du salon — sous `/salons/{salon_id}/campaigns`, imbriqué
sous le salon pour hériter de `require_salon_scope` (le `salon_id` est dans le
chemin, isolation §11.2). Gabarit direct : `adapters/inbound/customers.py`.

Le router traduit HTTP → commande applicative, assemble le cas d'usage par injection
de dépendances FastAPI, puis retraduit les erreurs de domaine :

- `InvalidCampaignTitle` / `InvalidCampaignMessage` / `InvalidCampaignType` /
  `InvalidCampaignSegment` → **422**.

Sécurité (RBAC #12, ADR-0015 ; ADR-0026) :
- **toutes** les routes déclarent `require_permission(CUSTOMER_MANAGE)` **et**
  `require_salon_scope` — **seul le `MANAGER`** (ni `CLIENT`, ni `HAIRDRESSER`, ni
  `ADMIN`). La matrice `ROLE_PERMISSIONS` n'est **pas** modifiée (réutilisation de
  `CUSTOMER_MANAGE`, déjà détenue par le gérant qui gère son fichier clients) ;
- l'**auteur** (`created_by`) est le `Principal` (`principal.id`), jamais lu du corps ;
- **aucun chemin n'est ajouté à `PUBLIC_ROUTE_PATHS`** : une campagne n'est jamais
  lisible sans jeton.

Non-remise & non-fuite (ADR-0006, §11.3) : la création **émet/trace** la campagne
(`status = PENDING`, `sent_at = NULL`) — **rien n'est envoyé** (fan-out SMS différé
M5+). Ni les messages d'erreur, ni les logs applicatifs ne portent le corps du
message, un téléphone ou un nom. La liste ne renvoie **aucun** destinataire ; elle
projette un effectif (entier) non-PII.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.campaign_repository import (
    SqlCampaignRepository,
)
from coiflink_api.adapters.outbound.persistence.customer_repository import (
    SqlCustomerRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.campaigns import (
    CampaignCommand,
    CreateCampaign,
    ListSalonCampaigns,
)
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.campaign_repository import (
    CAMPAIGN_LIMIT_DEFAULT,
    CAMPAIGN_LIMIT_MAX,
    CAMPAIGN_LIMIT_MIN,
    CampaignRepository,
)
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.campaign import (
    CAMPAIGN_MESSAGE_MAX_LENGTH,
    CAMPAIGN_SEGMENT_VALUES,
    CAMPAIGN_TITLE_MAX_LENGTH,
    CAMPAIGN_TYPE_VALUES,
    Campaign,
)
from coiflink_api.domain.errors import (
    InvalidCampaignMessage,
    InvalidCampaignSegment,
    InvalidCampaignTitle,
    InvalidCampaignType,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["campaigns"])

# Erreurs de validation du domaine → 422 (jamais `str(exc)` sur un refus RBAC).
_VALIDATION_ERRORS = (
    InvalidCampaignType,
    InvalidCampaignSegment,
    InvalidCampaignTitle,
    InvalidCampaignMessage,
)


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `customers.py`).
# --------------------------------------------------------------------------- #
class CreateCampaignRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/campaigns`.

    **Aucun** champ privilégié dans le corps : le `salon_id` vient de la portée
    validée ; `created_by`, `channel`, `status`, `recipient_count`, `id` et `sent_at`
    sont imposés/résolus/générés serveur. Un champ privilégié présent est **ignoré**
    (`extra="ignore"`).

    Le gérant compose un `title` et un `message` (**texte libre** borné) et choisit
    un `type` (`REMINDER` | `PROMOTION` | `EXCEPTIONAL_CLOSURE`) et un `segment`
    (`ALL` | `FEMALE` | `MALE` | `OTHER`) — un prédicat salon-scopé sur son fichier
    clients (#28). Le message ne doit contenir **aucune** PII d'un client précis : il
    est diffusé à l'identique à tout le segment (le système n'y injecte rien).
    """

    model_config = ConfigDict(extra="ignore")

    type: str = Field(examples=[CAMPAIGN_TYPE_VALUES[0]])
    segment: str = Field(examples=[CAMPAIGN_SEGMENT_VALUES[0]])
    title: str = Field(
        min_length=1,
        max_length=CAMPAIGN_TITLE_MAX_LENGTH,
        examples=["Promotion de la rentrée"],
    )
    message: str = Field(
        min_length=1,
        max_length=CAMPAIGN_MESSAGE_MAX_LENGTH,
        examples=["-20% sur toutes les coupes cette semaine."],
    )


class CampaignResponse(BaseModel):
    """Représentation d'une campagne renvoyée à la création (POST).

    **Aucune** identité de destinataire : la campagne porte un `recipient_count`
    (effectif, entier), jamais une liste de fiches ni un téléphone. `status` vaut
    `PENDING` et `sent_at` `null` au MVP (non remise, ADR-0006).
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    type: str
    segment: str
    channel: str
    title: str
    message: str
    recipient_count: int
    status: str
    sent_at: datetime.datetime | None
    created_at: datetime.datetime


class CampaignSummaryResponse(BaseModel):
    """Ligne de la liste des campagnes du salon (GET) — **non-PII**, sans message.

    Rend la création observable (parité #28) sans exposer ni le corps du message ni
    un destinataire : type, segment, titre, effectif, statut, date. Le corps composé
    n'est renvoyé qu'à la création (POST), jamais dans la liste.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    type: str
    segment: str
    channel: str
    title: str
    recipient_count: int
    status: str
    sent_at: datetime.datetime | None
    created_at: datetime.datetime


class CampaignPageResponse(BaseModel):
    """Réponse paginée de `GET /salons/{salon_id}/campaigns` : items + total + bornes."""

    items: list[CampaignSummaryResponse]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_campaign_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CampaignRepository:
    """Dépôt de campagnes adossé à la session de la requête."""

    return SqlCampaignRepository(session)


def get_customer_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CustomerRepository:
    """Dépôt de fiches clients (résolution de l'effectif) sur la **même** session."""

    return SqlCustomerRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité).

    FastAPI met en cache la dépendance `get_session` par requête : le dépôt de
    campagnes, le dépôt de fiches et le journal d'audit partagent donc la **même**
    `Session`, d'où le commit/rollback conjoint de la création et de sa trace.
    """

    return SqlAuditLog(session)


def _campaign_response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=campaign.id,
        salon_id=campaign.salon_id,
        type=campaign.type,
        segment=campaign.segment,
        channel=campaign.channel,
        title=campaign.title,
        message=campaign.message,
        recipient_count=campaign.recipient_count,
        status=campaign.status,
        sent_at=campaign.sent_at,
        created_at=campaign.created_at,
    )


def _campaign_summary(campaign: Campaign) -> CampaignSummaryResponse:
    return CampaignSummaryResponse(
        id=campaign.id,
        salon_id=campaign.salon_id,
        type=campaign.type,
        segment=campaign.segment,
        channel=campaign.channel,
        title=campaign.title,
        recipient_count=campaign.recipient_count,
        status=campaign.status,
        sent_at=campaign.sent_at,
        created_at=campaign.created_at,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/campaigns",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer (émettre/tracer) une campagne vers un segment de clients du salon",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Type, segment, titre ou message invalides"},
    },
)
def create_campaign(
    salon_id: uuid.UUID,
    payload: CreateCampaignRequest,
    campaign_repository: Annotated[CampaignRepository, Depends(get_campaign_repository)],
    customer_repository: Annotated[CustomerRepository, Depends(get_customer_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
) -> CampaignResponse:
    """Émet/trace une campagne pour le salon de la portée (US-7.5, #49).

    Le `salon_id` vient du chemin (portée), l'auteur du principal — jamais du corps.
    Le serveur valide, résout le canal (SMS) et l'effectif du segment (un `COUNT`
    salon-scopé des fiches joignables), persiste la campagne (`status = PENDING`) et
    journalise `CAMPAIGN_CREATED` (§11.4) dans la **même** unité de travail, avec un
    `metadata` **non-PII** (type + segment + effectif). **Rien n'est envoyé** : la
    remise proactive (fan-out SMS) est différée M5+ (ADR-0006).
    """

    try:
        campaign = CreateCampaign(
            campaign_repository, customer_repository, audit_log
        ).execute(
            salon_id,
            CampaignCommand(
                type=payload.type,
                segment=payload.segment,
                title=payload.title,
                message=payload.message,
            ),
            actor_user_id=principal.id,
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _campaign_response(campaign)


@router.get(
    "/{salon_id}/campaigns",
    response_model=CampaignPageResponse,
    summary="Lister les campagnes du salon (paginé, plus récentes d'abord, non-PII)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def list_campaigns(
    salon_id: uuid.UUID,
    repository: Annotated[CampaignRepository, Depends(get_campaign_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.CUSTOMER_MANAGE))
    ],
    limit: int = Query(
        default=CAMPAIGN_LIMIT_DEFAULT, ge=CAMPAIGN_LIMIT_MIN, le=CAMPAIGN_LIMIT_MAX
    ),
    offset: int = Query(default=0, ge=0),
) -> CampaignPageResponse:
    """Liste des campagnes du salon de la portée (isolation §11.2, lecture pure).

    Projection **non-PII** : ni destinataire, ni corps de message. Bornes de
    pagination en SQL (garde de coût §12.1) ; aucune écriture, aucun audit.
    """

    page, total = ListSalonCampaigns(repository).execute(
        salon_id, limit=limit, offset=offset
    )
    return CampaignPageResponse(
        items=[_campaign_summary(campaign) for campaign in page],
        total=total,
        limit=limit,
        offset=offset,
    )


__all__ = ["router"]
