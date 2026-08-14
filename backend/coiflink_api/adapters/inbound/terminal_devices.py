"""Adapter entrant (driving) : router HTTP de provisioning des bornes terminal (US-8.1, #155).

Expose la **gestion des bornes terminal** par un gérant (patron `employees.py`) :
- `POST /salons/{salon_id}/terminal-devices` — provisionner une borne (**code
  d'activation à 6 chiffres** rendu **une seule fois**, jamais relisible) ;
- `GET /salons/{salon_id}/terminal-devices` — lister les bornes du salon (sans secret) ;
- `DELETE /salons/{salon_id}/terminal-devices/{device_id}` — révoquer une borne
  (suspension logique, jamais une suppression physique — traçabilité §11.4).

Chaque route traduit la requête HTTP en commande applicative, assemble le cas
d'usage via l'injection de dépendances FastAPI, puis retraduit les erreurs de
domaine en codes HTTP :
- `InvalidTerminalDeviceLabel` → **422 Unprocessable Entity** ;
- `TerminalDeviceNotFound` → **404 Not Found** (après portée, aucun oracle §11.2).

Sécurité (RBAC #12, ADR-0015/0041) : toutes les routes sont **protégées** par la
permission `TERMINAL_PROVISION` (matrice §4.1 — seul le `MANAGER` la possède) **et**
par la portée salon (`require_salon_scope`) — un gérant ne provisionne de bornes
que sur **son** salon ; un accès hors périmètre renvoie le `403` générique (aucun
oracle d'existence). **Aucun** chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : une
borne terminal n'est jamais provisionnable/listable publiquement.

Invariant de non-fuite (§11.3) : le **code d'activation** n'apparaît que dans la
réponse `201` (`ProvisionTerminalDeviceResponse`) ; le **secret réel** n'existe qu'une
fois, dans la réponse de `POST /auth/terminal/activate` (généré à l'activation, jamais
au provisioning). Ni `GET` ni `DELETE` ne renvoient de code, de secret ni de
condensat (les champs n'existent pas dans `TerminalDeviceResponse`).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.auth import get_password_hasher
from coiflink_api.adapters.inbound.employees import get_audit_log
from coiflink_api.adapters.inbound.security import require_permission, require_salon_scope
from coiflink_api.adapters.outbound.persistence.terminal_device_repository import (
    SqlTerminalDeviceRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.security.terminal_activation_in_memory import (
    InMemoryTerminalActivationRepository,
)
from coiflink_api.application.terminal_devices import (
    ListTerminalDevices,
    ProvisionTerminalDevice,
    ProvisionTerminalDeviceCommand,
    RevokeTerminalDevice,
)
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.terminal_activation_repository import (
    TerminalActivationRepository,
)
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import InvalidTerminalDeviceLabel, TerminalDeviceNotFound
from coiflink_api.domain.terminal_device import TerminalDevice
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["terminal-devices"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic.
# --------------------------------------------------------------------------- #
class ProvisionTerminalDeviceRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/terminal-devices`.

    **Aucun** champ `salon_id` (lu du chemin, cible de portée), ni `role`/`status`
    (compte de service `TERMINAL` fixé côté serveur, anti-élévation de privilège). Le
    secret est **généré** serveur — jamais fourni par le client.
    """

    label: str = Field(min_length=1, max_length=255, examples=["Borne entrée"])


class TerminalDeviceResponse(BaseModel):
    """Représentation publique d'une borne — **sans** aucun secret ni condensat."""

    id: uuid.UUID
    salon_id: uuid.UUID
    label: str
    status: str
    created_at: datetime.datetime


class ProvisionTerminalDeviceResponse(TerminalDeviceResponse):
    """Réponse `201` — **le code d'activation à 6 chiffres n'est renvoyé qu'ici, une fois**.

    La borne l'échange contre son secret réel via `POST /auth/terminal/activate` : le
    gérant saisit 6 chiffres sur l'écran tactile au lieu de recopier un credential de
    ~43 caractères. Le code n'est **jamais** relisible (aucune autre route ne le
    renvoie) et n'est **jamais** journalisé ; le secret longue durée, lui, n'existe
    qu'à l'activation — il n'apparaît **jamais** dans cette réponse.
    """

    activation_code: str


def _device_response(device: TerminalDevice) -> TerminalDeviceResponse:
    return TerminalDeviceResponse(
        id=device.id,
        salon_id=device.salon_id,
        label=device.label,
        status=device.status,
        created_at=device.created_at,
    )


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_terminal_device_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlTerminalDeviceRepository:
    """Dépôt de bornes terminal adossé à la session de la requête."""

    return SqlTerminalDeviceRepository(session)


def _get_terminal_activation_repository(request: Request) -> TerminalActivationRepository:
    """Dépôt de défis d'activation (singleton `app.state`), partagé avec `auth.py`.

    Le provisioning (ce router) **écrit** le défi ; l'activation
    (`POST /auth/terminal/activate`, router `auth.py`) le **relit**. Les deux getters
    portent volontairement le même attribut `app.state.terminal_activation_repository` :
    `app.state` est partagé par toute l'application, quel que soit le router qui
    l'initialise — un code émis au provisioning est donc retrouvé à l'activation.
    Repli sûr si l'état n'est pas câblé.
    """

    repo = getattr(request.app.state, "terminal_activation_repository", None)
    if repo is None:
        repo = InMemoryTerminalActivationRepository()
        request.app.state.terminal_activation_repository = repo
    return repo


def get_provision_terminal_device(
    request: Request,
    repository: Annotated[
        SqlTerminalDeviceRepository, Depends(get_terminal_device_repository)
    ],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> ProvisionTerminalDevice:
    return ProvisionTerminalDevice(
        repository,
        hasher,
        audit_log,
        _get_terminal_activation_repository(request),
    )


def get_list_terminal_devices(
    repository: Annotated[
        SqlTerminalDeviceRepository, Depends(get_terminal_device_repository)
    ],
) -> ListTerminalDevices:
    return ListTerminalDevices(repository)


def get_revoke_terminal_device(
    repository: Annotated[
        SqlTerminalDeviceRepository, Depends(get_terminal_device_repository)
    ],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> RevokeTerminalDevice:
    return RevokeTerminalDevice(repository, audit_log)


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/terminal-devices",
    response_model=ProvisionTerminalDeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provisionner une borne terminal (gérant) — code d'activation rendu une seule fois",
    responses={
        201: {
            "description": (
                "Borne créée — le code d'activation n'est présent que dans cette réponse"
            )
        },
        401: {"description": "Jeton absent, invalide, expiré, ou refresh présenté en accès"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        422: {"description": "Libellé de borne invalide"},
        503: {"description": "JWT_SECRET non configuré"},
    },
)
def provision_terminal_device(
    salon_id: uuid.UUID,
    payload: ProvisionTerminalDeviceRequest,
    usecase: Annotated[ProvisionTerminalDevice, Depends(get_provision_terminal_device)],
    # Gardes RBAC (#12) : permission §4.1 **et** portée salon §11.2. `salon_id` est
    # lu du chemin par `require_salon_scope` ; les deux dépendances résolvent le même
    # `Principal` (via `get_current_principal`) — pas de double lecture de compte.
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.TERMINAL_PROVISION))
    ],
) -> ProvisionTerminalDeviceResponse:
    """Crée une borne (`role=TERMINAL`, `status=ACTIVE`) rattachée à `salon_id`.

    Retourne l'entité **et** le **code d'activation à 6 chiffres** — **une seule
    fois**. Le gérant saisit ces 6 chiffres sur la borne, qui les échange contre son
    secret longue durée via `POST /auth/terminal/activate` ; elle utilise ensuite
    `(id, secret)` sur `POST /auth/terminal/login` pour toutes ses sessions. Tant qu'elle
    n'est pas activée, la borne ne peut pas se connecter. Provisioning journalisé
    (`TERMINAL_DEVICE_PROVISIONED`, `metadata` vide) dans la même unité de travail que
    la création.
    """

    command = ProvisionTerminalDeviceCommand(label=payload.label)
    try:
        device, activation_code = usecase.execute(
            salon_id, command, actor_user_id=principal.id
        )
    except InvalidTerminalDeviceLabel as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return ProvisionTerminalDeviceResponse(
        id=device.id,
        salon_id=device.salon_id,
        label=device.label,
        status=device.status,
        created_at=device.created_at,
        activation_code=activation_code,
    )


@router.get(
    "/{salon_id}/terminal-devices",
    response_model=list[TerminalDeviceResponse],
    summary="Lister les bornes terminal du salon (gérant)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
    },
)
def list_terminal_devices(
    salon_id: uuid.UUID,
    usecase: Annotated[ListTerminalDevices, Depends(get_list_terminal_devices)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.TERMINAL_PROVISION))
    ],
) -> list[TerminalDeviceResponse]:
    """Liste les bornes **du salon** (actives et révoquées), **sans** aucun secret."""

    devices = usecase.execute(salon_id)
    return [_device_response(device) for device in devices]


@router.delete(
    "/{salon_id}/terminal-devices/{device_id}",
    response_model=TerminalDeviceResponse,
    summary="Révoquer une borne terminal (suspension logique, §11.4)",
    responses={
        200: {"description": "Borne révoquée (compte suspendu, appartenance inactive)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Borne inexistante ou hors salon (après portée)"},
    },
)
def revoke_terminal_device(
    salon_id: uuid.UUID,
    device_id: uuid.UUID,
    usecase: Annotated[RevokeTerminalDevice, Depends(get_revoke_terminal_device)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.TERMINAL_PROVISION))
    ],
) -> TerminalDeviceResponse:
    """Révoque la borne (effet **immédiat** : la requête suivante du device est refusée).

    Révocation **logique** — jamais une suppression (traçabilité §11.4). Journalisée
    (`TERMINAL_DEVICE_REVOKED`, `metadata` vide). `404` si la borne n'existe pas dans ce
    salon (après validation de portée).
    """

    try:
        device = usecase.execute(salon_id, device_id, actor_user_id=principal.id)
    except TerminalDeviceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _device_response(device)


__all__ = [
    "router",
    "ProvisionTerminalDeviceRequest",
    "TerminalDeviceResponse",
    "ProvisionTerminalDeviceResponse",
]
