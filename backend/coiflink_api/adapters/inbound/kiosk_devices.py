"""Adapter entrant (driving) : router HTTP de provisioning des bornes kiosque (US-8.1, #155).

Expose la **gestion des bornes kiosque** par un gérant (patron `employees.py`) :
- `POST /salons/{salon_id}/kiosk-devices` — provisionner une borne (secret rendu
  **une seule fois**, jamais relisible) ;
- `GET /salons/{salon_id}/kiosk-devices` — lister les bornes du salon (sans secret) ;
- `DELETE /salons/{salon_id}/kiosk-devices/{device_id}` — révoquer une borne
  (suspension logique, jamais une suppression physique — traçabilité §11.4).

Chaque route traduit la requête HTTP en commande applicative, assemble le cas
d'usage via l'injection de dépendances FastAPI, puis retraduit les erreurs de
domaine en codes HTTP :
- `InvalidKioskDeviceLabel` → **422 Unprocessable Entity** ;
- `KioskDeviceNotFound` → **404 Not Found** (après portée, aucun oracle §11.2).

Sécurité (RBAC #12, ADR-0015/0041) : toutes les routes sont **protégées** par la
permission `KIOSK_PROVISION` (matrice §4.1 — seul le `MANAGER` la possède) **et**
par la portée salon (`require_salon_scope`) — un gérant ne provisionne de bornes
que sur **son** salon ; un accès hors périmètre renvoie le `403` générique (aucun
oracle d'existence). **Aucun** chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : une
borne kiosque n'est jamais provisionnable/listable publiquement.

Invariant de non-fuite (§11.3) : le **secret** n'apparaît que dans la réponse `201`
(`ProvisionKioskDeviceResponse`) ; ni `GET` ni `DELETE` ne renvoient de secret ni de
condensat (le champ n'existe pas dans `KioskDeviceResponse`).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.auth import get_password_hasher
from coiflink_api.adapters.inbound.employees import get_audit_log
from coiflink_api.adapters.inbound.security import require_permission, require_salon_scope
from coiflink_api.adapters.outbound.persistence.kiosk_device_repository import (
    SqlKioskDeviceRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.kiosk_devices import (
    ListKioskDevices,
    ProvisionKioskDevice,
    ProvisionKioskDeviceCommand,
    RevokeKioskDevice,
)
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import InvalidKioskDeviceLabel, KioskDeviceNotFound
from coiflink_api.domain.kiosk_device import KioskDevice
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["kiosk-devices"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic.
# --------------------------------------------------------------------------- #
class ProvisionKioskDeviceRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/kiosk-devices`.

    **Aucun** champ `salon_id` (lu du chemin, cible de portée), ni `role`/`status`
    (compte de service `KIOSK` fixé côté serveur, anti-élévation de privilège). Le
    secret est **généré** serveur — jamais fourni par le client.
    """

    label: str = Field(min_length=1, max_length=255, examples=["Borne entrée"])


class KioskDeviceResponse(BaseModel):
    """Représentation publique d'une borne — **sans** aucun secret ni condensat."""

    id: uuid.UUID
    salon_id: uuid.UUID
    label: str
    status: str
    created_at: datetime.datetime


class ProvisionKioskDeviceResponse(KioskDeviceResponse):
    """Réponse `201` du provisioning — **le secret n'est renvoyé qu'ici, une fois**.

    Le `secret` est le credential de device longue durée à saisir sur la borne : il
    n'est **jamais** stocké en clair, **jamais** journalisé et **jamais** relisible
    (aucune autre route ne le renvoie).
    """

    secret: str


def _device_response(device: KioskDevice) -> KioskDeviceResponse:
    return KioskDeviceResponse(
        id=device.id,
        salon_id=device.salon_id,
        label=device.label,
        status=device.status,
        created_at=device.created_at,
    )


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_kiosk_device_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlKioskDeviceRepository:
    """Dépôt de bornes kiosque adossé à la session de la requête."""

    return SqlKioskDeviceRepository(session)


def get_provision_kiosk_device(
    repository: Annotated[
        SqlKioskDeviceRepository, Depends(get_kiosk_device_repository)
    ],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> ProvisionKioskDevice:
    return ProvisionKioskDevice(repository, hasher, audit_log)


def get_list_kiosk_devices(
    repository: Annotated[
        SqlKioskDeviceRepository, Depends(get_kiosk_device_repository)
    ],
) -> ListKioskDevices:
    return ListKioskDevices(repository)


def get_revoke_kiosk_device(
    repository: Annotated[
        SqlKioskDeviceRepository, Depends(get_kiosk_device_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> RevokeKioskDevice:
    return RevokeKioskDevice(repository, audit_log)


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/kiosk-devices",
    response_model=ProvisionKioskDeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provisionner une borne kiosque (gérant) — secret rendu une seule fois",
    responses={
        201: {"description": "Borne créée — le secret n'est présent que dans cette réponse"},
        401: {"description": "Jeton absent, invalide, expiré, ou refresh présenté en accès"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        422: {"description": "Libellé de borne invalide"},
        503: {"description": "JWT_SECRET non configuré"},
    },
)
def provision_kiosk_device(
    salon_id: uuid.UUID,
    payload: ProvisionKioskDeviceRequest,
    usecase: Annotated[ProvisionKioskDevice, Depends(get_provision_kiosk_device)],
    # Gardes RBAC (#12) : permission §4.1 **et** portée salon §11.2. `salon_id` est
    # lu du chemin par `require_salon_scope` ; les deux dépendances résolvent le même
    # `Principal` (via `get_current_principal`) — pas de double lecture de compte.
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.KIOSK_PROVISION))
    ],
) -> ProvisionKioskDeviceResponse:
    """Crée une borne (`role=KIOSK`, `status=ACTIVE`) rattachée à `salon_id`.

    Retourne l'entité **et** le secret de device en clair — **une seule fois**. La
    borne échangera ensuite `(id, secret)` contre une paire JWT via
    `POST /auth/kiosk/login`. Provisioning journalisé (`KIOSK_DEVICE_PROVISIONED`,
    `metadata` vide) dans la même unité de travail que la création.
    """

    command = ProvisionKioskDeviceCommand(label=payload.label)
    try:
        device, secret = usecase.execute(
            salon_id, command, actor_user_id=principal.id
        )
    except InvalidKioskDeviceLabel as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return ProvisionKioskDeviceResponse(
        id=device.id,
        salon_id=device.salon_id,
        label=device.label,
        status=device.status,
        created_at=device.created_at,
        secret=secret,
    )


@router.get(
    "/{salon_id}/kiosk-devices",
    response_model=list[KioskDeviceResponse],
    summary="Lister les bornes kiosque du salon (gérant)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
    },
)
def list_kiosk_devices(
    salon_id: uuid.UUID,
    usecase: Annotated[ListKioskDevices, Depends(get_list_kiosk_devices)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.KIOSK_PROVISION))
    ],
) -> list[KioskDeviceResponse]:
    """Liste les bornes **du salon** (actives et révoquées), **sans** aucun secret."""

    devices = usecase.execute(salon_id)
    return [_device_response(device) for device in devices]


@router.delete(
    "/{salon_id}/kiosk-devices/{device_id}",
    response_model=KioskDeviceResponse,
    summary="Révoquer une borne kiosque (suspension logique, §11.4)",
    responses={
        200: {"description": "Borne révoquée (compte suspendu, appartenance inactive)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Borne inexistante ou hors salon (après portée)"},
    },
)
def revoke_kiosk_device(
    salon_id: uuid.UUID,
    device_id: uuid.UUID,
    usecase: Annotated[RevokeKioskDevice, Depends(get_revoke_kiosk_device)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.KIOSK_PROVISION))
    ],
) -> KioskDeviceResponse:
    """Révoque la borne (effet **immédiat** : la requête suivante du device est refusée).

    Révocation **logique** — jamais une suppression (traçabilité §11.4). Journalisée
    (`KIOSK_DEVICE_REVOKED`, `metadata` vide). `404` si la borne n'existe pas dans ce
    salon (après validation de portée).
    """

    try:
        device = usecase.execute(salon_id, device_id, actor_user_id=principal.id)
    except KioskDeviceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _device_response(device)


__all__ = [
    "router",
    "ProvisionKioskDeviceRequest",
    "KioskDeviceResponse",
    "ProvisionKioskDeviceResponse",
]
