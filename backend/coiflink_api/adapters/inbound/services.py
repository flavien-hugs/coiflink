"""Adapter entrant (driving) : router HTTP de gestion des prestations (US-2.3, #17).

Expose le **CRUD des prestations d'un salon** — création, liste, consultation,
modification (sémantique *replace*) et « suppression » (désactivation) — sous
`/salons/{salon_id}/services`, imbriqué sous le salon pour hériter de
`require_salon_scope` (le `salon_id` est dans le chemin, isolation §11.2).

Le router traduit HTTP → commande applicative, assemble les cas d'usage par
injection de dépendances FastAPI, puis retraduit les erreurs de domaine :

- `InvalidServiceName` / `InvalidServicePrice` / `InvalidServiceDuration` /
  `InvalidServiceCategory` → **422** ;
- `ServiceNotFound` → **404** *(uniquement après validation de portée)*.

Sécurité (RBAC #12, ADR-0015) :
- **mutations** (`POST`/`PUT`/`DELETE`) : `require_permission(SERVICE_MANAGE)` —
  seul le `MANAGER` la détient — **et** `require_salon_scope` (son salon) ;
- **lectures** (`GET`) : `require_permission(SERVICE_READ)` **et**
  `require_salon_scope`. Bien que le `CLIENT` détienne `SERVICE_READ`, il n'a
  **aucune portée** sur un salon dont il n'est ni gérant ni employé →
  `require_salon_scope` lui renvoie le `403` générique. La lecture *publique*
  client (catalogue §8.3) relève de #18/#19, avec sa propre route ;
- l'**acteur** journalisé est le `Principal` (`principal.id`), jamais lu du corps.

Journalisation §11.4 : chaque mutation enregistre une `AuditEntry` dans la **même
Session** que l'écriture (atomicité). Aucun chemin n'est ajouté à
`PUBLIC_ROUTE_PATHS` : les prestations ne sont pas publiques dans cette issue.
"""

from __future__ import annotations

import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.service_repository import (
    SqlServiceRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.service_repository import ServiceRepository
from coiflink_api.application.services import (
    CreateService,
    DeactivateService,
    GetService,
    ListSalonServices,
    ServiceCommand,
    UpdateService,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import (
    InvalidServiceCategory,
    InvalidServiceDuration,
    InvalidServiceName,
    InvalidServicePrice,
    ServiceNotFound,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.service import Service

router = APIRouter(prefix="/salons", tags=["services"])

# Erreurs de validation du domaine → 422 (jamais `str(exc)` sur un refus RBAC).
_VALIDATION_ERRORS = (
    InvalidServiceName,
    InvalidServicePrice,
    InvalidServiceDuration,
    InvalidServiceCategory,
)


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `salons.py`).
# --------------------------------------------------------------------------- #
class CreateServiceRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/services`.

    **Aucun** `salon_id`/`id`/`is_active` dans le corps : le `salon_id` vient de
    la portée validée, `is_active` se pilote via `DELETE`. Un champ privilégié
    présent est **ignoré** (`extra="ignore"`).
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=255, examples=["Coupe homme"])
    price: decimal.Decimal = Field(examples=["5000.00"])  # requis, >= 0
    duration_minutes: int = Field(examples=[30])  # requis, > 0
    description: str | None = Field(default=None, examples=["Coupe aux ciseaux."])
    category: str | None = Field(default=None, examples=["Coupe"])


class UpdateServiceRequest(CreateServiceRequest):
    """Corps de `PUT /salons/{salon_id}/services/{service_id}` (sémantique *replace*).

    Mêmes champs que la création : prix et durée restent **obligatoires**.
    """


class ServiceResponse(BaseModel):
    """Représentation d'une prestation renvoyée par l'API."""

    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    description: str | None
    price: decimal.Decimal
    duration_minutes: int
    category: str | None
    is_active: bool
    created_at: object
    updated_at: object


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_service_repository(
    session: Annotated[Session, Depends(get_session)],
) -> ServiceRepository:
    """Dépôt de prestations adossé à la session de la requête."""

    return SqlServiceRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité, §11.4).

    FastAPI met en cache la dépendance `get_session` par requête : le dépôt de
    prestations et le journal d'audit partagent donc la **même** `Session`, d'où
    le commit/rollback conjoint de la mutation et de sa trace.
    """

    return SqlAuditLog(session)


def _service_response(service: Service) -> ServiceResponse:
    return ServiceResponse(
        id=service.id,
        salon_id=service.salon_id,
        name=service.name,
        description=service.description,
        price=service.price,
        duration_minutes=service.duration_minutes,
        category=service.category,
        is_active=service.is_active,
        created_at=service.created_at,
        updated_at=service.updated_at,
    )


def _command(payload: CreateServiceRequest) -> ServiceCommand:
    return ServiceCommand(
        name=payload.name,
        price=payload.price,
        duration_minutes=payload.duration_minutes,
        description=payload.description,
        category=payload.category,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/services",
    response_model=ServiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une prestation rattachée au salon",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Nom, prix, durée ou catégorie invalides"},
    },
)
def create_service(
    salon_id: uuid.UUID,
    payload: CreateServiceRequest,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceResponse:
    """Crée une prestation (`is_active=true`) pour le salon de la portée validée.

    Le `salon_id` vient du chemin (portée), jamais du corps. Journalise
    `SERVICE_CREATED` (§11.4) dans la même unité de travail.
    """

    try:
        service = CreateService(repository, audit_log).execute(
            salon_id, _command(payload), actor_user_id=principal.id
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _service_response(service)


@router.get(
    "/{salon_id}/services",
    response_model=list[ServiceResponse],
    summary="Lister les prestations d'un salon (actives et désactivées)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def list_services(
    salon_id: uuid.UUID,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_READ))
    ],
) -> list[ServiceResponse]:
    """Liste les prestations du salon (vue gérant : actives **et** désactivées)."""

    services = ListSalonServices(repository).execute(salon_id, include_inactive=True)
    return [_service_response(service) for service in services]


@router.get(
    "/{salon_id}/services/{service_id}",
    response_model=ServiceResponse,
    summary="Consulter une prestation du salon",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Prestation introuvable (portée déjà validée)"},
    },
)
def get_service(
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_READ))
    ],
) -> ServiceResponse:
    """Consulte la prestation `(salon_id, service_id)` (isolation §11.2)."""

    try:
        service = GetService(repository).execute(salon_id, service_id)
    except ServiceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _service_response(service)


@router.put(
    "/{salon_id}/services/{service_id}",
    response_model=ServiceResponse,
    summary="Modifier une prestation (remplacement, journalisé §11.4)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Prestation introuvable (portée déjà validée)"},
        422: {"description": "Nom, prix, durée ou catégorie invalides"},
    },
)
def update_service(
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    payload: UpdateServiceRequest,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceResponse:
    """Remplace les champs modifiables de la prestation puis journalise.

    Cœur du critère « modification journalisée » : après écriture, une entrée
    `SERVICE_UPDATED` porte la **liste des champs modifiés** (`metadata.changed`).
    """

    try:
        service = UpdateService(repository, audit_log).execute(
            salon_id, service_id, _command(payload), actor_user_id=principal.id
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ServiceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _service_response(service)


@router.delete(
    "/{salon_id}/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Désactiver une prestation (« suppression » = soft-delete, §11.4)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Prestation introuvable (portée déjà validée)"},
    },
)
def delete_service(
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> Response:
    """Désactive la prestation (`is_active=false`) — la « suppression » canonique.

    Soft-delete : la FK `appointment_services → services` est `ON DELETE RESTRICT`
    (une prestation réservée ne peut être supprimée physiquement) et la
    désactivation préserve l'historique. Journalise `SERVICE_DEACTIVATED` (§11.4).
    """

    try:
        DeactivateService(repository, audit_log).execute(
            salon_id, service_id, actor_user_id=principal.id
        )
    except ServiceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
