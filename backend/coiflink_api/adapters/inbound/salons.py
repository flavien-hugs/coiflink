"""Adapter entrant (driving) : router HTTP de gestion des salons (US-2.1, #15).

Expose la **création d'un salon** par un gérant (`POST /salons`), sa
**consultation** (`GET /salons`, `GET /salons/{salon_id}`) et la gestion de ses
**médias** (logo/photos via URLs signées). Le router traduit HTTP → commande
applicative, assemble les cas d'usage par injection de dépendances FastAPI, puis
retraduit les erreurs de domaine en codes HTTP :

- `InvalidSalonName` / `InvalidLocation` / `InvalidPhone` / `InvalidMediaType` /
  `MediaKeyMismatch` → **422** ;
- `PhotoLimitExceeded` → **409** ;
- `SalonNotFound` → **404** *(uniquement après validation de portée)* ;
- stockage objet non configuré → **503** (mêmes règles que `JWT_SECRET`).

Sécurité (RBAC #12, ADR-0015) :
- `POST /salons` ne peut pas utiliser `require_salon_scope` (le salon n'existe pas
  encore) : la protection repose sur `require_permission(SALON_CREATE)` (seul le
  `MANAGER` la détient) **et** sur `owner_id = principal.id`. **Aucun** champ
  `owner_id` n'est déclaré dans la requête — invariant anti-élévation de privilège
  (miroir du `role` absent de `CreateEmployeeRequest`, #13) ;
- toutes les routes `/salons/{salon_id}/…` portent `require_salon_scope`
  (isolation §11.2) ; un accès hors périmètre renvoie le `403` générique ;
- la clé d'objet soumise (logo/photo) est **revalidée** contre le préfixe du salon
  (cas d'usage) — sans quoi l'isolation serait contournable par les médias.

Aucun chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : les salons ne sont pas publics
dans cette issue (la visibilité client `ACTIVE`-seulement relève de #18/#19).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_any_permission,
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.salon_repository import SqlSalonRepository
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.media_storage import MediaStorage
from coiflink_api.application.ports.salon_repository import SalonRepository
from coiflink_api.application.salons import (
    AddSalonPhoto,
    AttachSalonLogo,
    CreateSalon,
    CreateSalonCommand,
    GetSalon,
    IssueMediaUploadUrl,
    ListOwnSalons,
    RemoveSalonPhoto,
    SalonView,
    SetOpeningHours,
    UpdateSalon,
    UpdateSalonCommand,
)
from coiflink_api.config import DEFAULT_MEDIA_MAX_PHOTOS
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import (
    InvalidLocation,
    InvalidMediaType,
    InvalidOpeningHours,
    InvalidPhone,
    InvalidSalonName,
    MediaKeyMismatch,
    PhotoLimitExceeded,
    SalonNotFound,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["salons"])

_MEDIA_UNAVAILABLE_DETAIL = "Service de stockage objet indisponible (non configuré)."


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `employees.py`).
# --------------------------------------------------------------------------- #
class CreateSalonRequest(BaseModel):
    """Corps de `POST /salons`. **Aucun** `owner_id`/`status`/`opening_hours`.

    Un `owner_id` présent dans le corps est **ignoré** (Pydantic `extra=ignore`) :
    l'`owner_id` réel est toujours le `Principal` authentifié.
    """

    name: str = Field(min_length=1, max_length=255, examples=["Salon Élégance"])
    description: str | None = Field(default=None, examples=["Coiffure afro et tresses."])
    phone: str | None = Field(default=None, examples=["0700000000"])
    address: str | None = Field(default=None, examples=["Rue des Jardins, Cocody"])
    city: str | None = Field(default=None, examples=["Abidjan"])
    commune: str | None = Field(default=None, examples=["Cocody"])
    latitude: float | None = Field(default=None, examples=[5.359952])
    longitude: float | None = Field(default=None, examples=[-3.996643])


class UpdateSalonRequest(BaseModel):
    """Corps de `PUT /salons/{salon_id}`. **Aucun** `owner_id`/`status`/`opening_hours`.

    Mêmes champs que `CreateSalonRequest` : sémantique *replace*, `name` requis.
    """

    name: str = Field(min_length=1, max_length=255, examples=["Salon Élégance"])
    description: str | None = Field(default=None, examples=["Coiffure afro et tresses."])
    phone: str | None = Field(default=None, examples=["0700000000"])
    address: str | None = Field(default=None, examples=["Rue des Jardins, Cocody"])
    city: str | None = Field(default=None, examples=["Abidjan"])
    commune: str | None = Field(default=None, examples=["Cocody"])
    latitude: float | None = Field(default=None, examples=[5.359952])
    longitude: float | None = Field(default=None, examples=[-3.996643])


class SalonPhotoResponse(BaseModel):
    """Photo d'un salon : `url` est une **URL signée** (jamais une clé d'objet)."""

    id: uuid.UUID
    url: str | None = None


class SalonResponse(BaseModel):
    """Représentation publique d'un salon. `logo_url` : URL **signée** ou `null`."""

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    phone: str | None
    address: str | None
    city: str | None
    commune: str | None
    latitude: float | None
    longitude: float | None
    logo_url: str | None
    photos: list[SalonPhotoResponse]
    status: str
    opening_hours: dict | None
    is_bookable: bool
    created_at: object
    updated_at: object


class UploadUrlRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/media/upload-url`."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["logo", "photo"] = Field(examples=["logo"])
    content_type: str = Field(examples=["image/png"])


class UploadUrlResponse(BaseModel):
    """URL signée de téléversement direct navigateur → stockage objet (#15)."""

    url: str
    method: str
    headers: dict[str, str]
    object_key: str
    expires_in: int


class AttachMediaRequest(BaseModel):
    """Corps de `PUT /salons/{salon_id}/logo` et `POST /salons/{salon_id}/photos`."""

    object_key: str = Field(examples=["salons/<uuid>/logo/<uuid>.png"])


class TimeIntervalModel(BaseModel):
    """Intervalle d'ouverture `HH:MM`–`HH:MM` (validé par le domaine, #16)."""

    model_config = ConfigDict(extra="forbid")

    start: str = Field(examples=["08:00"])
    end: str = Field(examples=["12:00"])


class ExceptionalDayModel(BaseModel):
    """Jour exceptionnel daté : fermeture ou horaires exceptionnels (#16)."""

    model_config = ConfigDict(extra="forbid")

    date: datetime.date = Field(examples=["2026-08-07"])
    closed: bool = Field(default=False)
    intervals: list[TimeIntervalModel] = Field(default_factory=list)


class OpeningHoursRequest(BaseModel):
    """Corps de `PUT /salons/{salon_id}/opening-hours` (sémantique *replace*, #16).

    `weekly` : dict jour → intervalles (jours absents = fermés). `timezone` est
    optionnel — le défaut serveur `Africa/Abidjan` s'applique (non éditable UI MVP).
    La structure est **revalidée par le domaine** (`parse_opening_hours`), autorité
    des règles métier.
    """

    model_config = ConfigDict(extra="ignore")

    weekly: dict[str, list[TimeIntervalModel]] = Field(default_factory=dict)
    exceptions: list[ExceptionalDayModel] = Field(default_factory=list)
    timezone: str | None = Field(default=None, examples=["Africa/Abidjan"])


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_salon_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SalonRepository:
    """Dépôt de salons adossé à la session de la requête."""

    return SqlSalonRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité, §11.4).

    FastAPI met en cache la dépendance `get_session` par requête : le dépôt de
    salons et le journal d'audit partagent donc la **même** `Session`, d'où le
    commit/rollback conjoint de la mutation et de sa trace.
    """

    return SqlAuditLog(session)


def get_optional_media_storage(request: Request) -> MediaStorage | None:
    """Stockage objet déposé sur `app.state` (peut être `None` si non configuré).

    Les **lectures** tolèrent l'absence de stockage (URLs médias résolues à
    `null`) ; seules les routes d'écriture de médias exigent un stockage (503).
    """

    return getattr(request.app.state, "media_storage", None)


def require_media_storage(
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
) -> MediaStorage:
    """Exige un stockage objet configuré ; `503` sinon (cf. `JWT_SECRET` absent)."""

    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_MEDIA_UNAVAILABLE_DETAIL,
        )
    return storage


def _max_photos(request: Request) -> int:
    """Plafond de photos par salon (config média), défaut `MEDIA_MAX_PHOTOS`."""

    config = getattr(request.app.state, "media_config", None)
    return getattr(config, "max_photos", DEFAULT_MEDIA_MAX_PHOTOS)


def _salon_response(view: SalonView) -> SalonResponse:
    """Mappe une `SalonView` (URLs signées résolues) vers la réponse HTTP."""

    salon = view.salon
    return SalonResponse(
        id=salon.id,
        owner_id=salon.owner_id,
        name=salon.name,
        description=salon.description,
        phone=salon.phone,
        address=salon.address,
        city=salon.city,
        commune=salon.commune,
        latitude=float(salon.latitude) if salon.latitude is not None else None,
        longitude=float(salon.longitude) if salon.longitude is not None else None,
        logo_url=view.logo_url,
        photos=[SalonPhotoResponse(id=p.id, url=p.url) for p in view.photos],
        status=salon.status,
        opening_hours=salon.opening_hours,
        is_bookable=view.is_bookable,
        created_at=salon.created_at,
        updated_at=salon.updated_at,
    )


def _to_decimal(value: float | None) -> decimal.Decimal | None:
    return decimal.Decimal(str(value)) if value is not None else None


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "",
    response_model=SalonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un salon rattaché au gérant authentifié",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (seul le gérant crée un salon)"},
        422: {"description": "Nom, téléphone ou coordonnées invalides"},
        503: {"description": "JWT_SECRET non configuré"},
    },
)
def create_salon(
    payload: CreateSalonRequest,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_CREATE))
    ],
) -> SalonResponse:
    """Crée un salon (`status=ACTIVE`, `opening_hours=NULL`) pour le gérant courant.

    L'`owner_id` est **imposé** depuis le `Principal` (jamais lu du corps). Le
    salon créé n'est **pas encore réservable** (`is_bookable=false`) tant qu'aucun
    horaire n'est configuré (§8.3, #16).
    """

    command = CreateSalonCommand(
        name=payload.name,
        description=payload.description,
        phone=payload.phone,
        address=payload.address,
        city=payload.city,
        commune=payload.commune,
        latitude=_to_decimal(payload.latitude),
        longitude=_to_decimal(payload.longitude),
    )
    try:
        salon = CreateSalon(repository).execute(command, owner_id=principal.id)
    except (InvalidSalonName, InvalidLocation, InvalidPhone) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Un salon fraîchement créé n'a ni logo ni photo : vue triviale (aucune I/O
    # de signature), inutile de repasser par le stockage objet.
    return _salon_response(SalonView(salon=salon, logo_url=None, photos=()))


@router.get(
    "",
    response_model=list[SalonResponse],
    summary="Lister les salons du gérant authentifié",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant"},
    },
)
def list_salons(
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_READ_OWN))
    ],
) -> list[SalonResponse]:
    """Retourne les salons rattachés au principal (portée implicite : ses salons)."""

    views = ListOwnSalons(repository, storage).execute(principal.id)
    return [_salon_response(view) for view in views]


@router.get(
    "/{salon_id}",
    response_model=SalonResponse,
    summary="Consulter un salon (gérant/coiffeur : le sien ; admin : tous)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Salon introuvable (portée déjà validée)"},
    },
)
def get_salon(
    salon_id: uuid.UUID,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal,
        Depends(
            require_any_permission(
                Permission.SALON_READ_OWN, Permission.SALON_READ_ANY
            )
        ),
    ],
) -> SalonResponse:
    """Consulte un salon dans le périmètre du principal (isolation §11.2)."""

    try:
        view = GetSalon(repository, storage).execute(salon_id)
    except SalonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _salon_response(view)


@router.put(
    "/{salon_id}",
    response_model=SalonResponse,
    summary="Modifier les informations générales du salon (journalisé §11.4)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Salon introuvable (portée déjà validée)"},
        422: {"description": "Nom, téléphone ou coordonnées invalides"},
    },
)
def update_salon(
    salon_id: uuid.UUID,
    payload: UpdateSalonRequest,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_UPDATE))
    ],
) -> SalonResponse:
    """Remplace les informations générales du salon puis journalise `SALON_UPDATED`.

    `owner_id`, `status` et `opening_hours` ne sont pas modifiables par cette route.
    """

    command = UpdateSalonCommand(
        name=payload.name,
        description=payload.description,
        phone=payload.phone,
        address=payload.address,
        city=payload.city,
        commune=payload.commune,
        latitude=_to_decimal(payload.latitude),
        longitude=_to_decimal(payload.longitude),
    )
    try:
        UpdateSalon(repository, audit_log).execute(
            salon_id, command, actor_user_id=principal.id
        )
        view = GetSalon(repository, storage).execute(salon_id)
    except (InvalidSalonName, InvalidLocation, InvalidPhone) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except SalonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _salon_response(view)


@router.post(
    "/{salon_id}/media/upload-url",
    response_model=UploadUrlResponse,
    summary="Émettre une URL signée de téléversement de média (logo/photo)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Type MIME hors liste blanche"},
        503: {"description": "Stockage objet non configuré"},
    },
)
def issue_upload_url(
    salon_id: uuid.UUID,
    payload: UploadUrlRequest,
    storage: Annotated[MediaStorage, Depends(require_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_UPDATE))
    ],
) -> UploadUrlResponse:
    """Fabrique la clé d'objet (sans PII) et renvoie l'URL signée `PUT`."""

    try:
        presigned = IssueMediaUploadUrl(storage).execute(
            salon_id, payload.kind, payload.content_type
        )
    except InvalidMediaType as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return UploadUrlResponse(
        url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        object_key=presigned.object_key,
        expires_in=presigned.expires_in,
    )


@router.put(
    "/{salon_id}/logo",
    response_model=SalonResponse,
    summary="Attacher un logo (clé d'objet préalablement téléversée)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Salon introuvable (portée déjà validée)"},
        422: {"description": "Clé d'objet hors du préfixe de ce salon"},
    },
)
def set_logo(
    salon_id: uuid.UUID,
    payload: AttachMediaRequest,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_UPDATE))
    ],
) -> SalonResponse:
    """Revalide le préfixe de la clé puis l'écrit comme logo du salon."""

    try:
        AttachSalonLogo(repository, storage).execute(salon_id, payload.object_key)
        view = GetSalon(repository, storage).execute(salon_id)
    except MediaKeyMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except SalonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _salon_response(view)


@router.put(
    "/{salon_id}/opening-hours",
    response_model=SalonResponse,
    summary="Configurer les horaires d'ouverture (rend le salon réservable, §8.3)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Salon introuvable (portée déjà validée)"},
        422: {"description": "Structure d'horaires invalide"},
    },
)
def set_opening_hours(
    salon_id: uuid.UUID,
    payload: OpeningHoursRequest,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_UPDATE))
    ],
) -> SalonResponse:
    """Remplace les horaires du salon puis renvoie le `SalonResponse` complet.

    La structure est validée/normalisée par le domaine avant écriture ; après
    enregistrement d'horaires valides, `is_bookable` passe à `true` (§8.3, #16).
    Sémantique *replace* (idempotente) : un `PUT` remplace intégralement l'existant.
    """

    try:
        SetOpeningHours(repository).execute(salon_id, payload.model_dump())
        view = GetSalon(repository, storage).execute(salon_id)
    except InvalidOpeningHours as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except SalonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _salon_response(view)


@router.post(
    "/{salon_id}/photos",
    response_model=SalonPhotoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une photo (clé d'objet préalablement téléversée)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Salon introuvable (portée déjà validée)"},
        409: {"description": "Nombre maximal de photos atteint"},
        422: {"description": "Clé d'objet hors du préfixe de ce salon"},
    },
)
def add_photo(
    request: Request,
    salon_id: uuid.UUID,
    payload: AttachMediaRequest,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_UPDATE))
    ],
) -> SalonPhotoResponse:
    """Revalide le préfixe de la clé puis ajoute la photo (sous `MEDIA_MAX_PHOTOS`)."""

    try:
        photo = AddSalonPhoto(
            repository, max_photos=_max_photos(request)
        ).execute(salon_id, payload.object_key)
    except MediaKeyMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except PhotoLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except SalonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    url = storage.presign_download(photo.object_key) if storage is not None else None
    return SalonPhotoResponse(id=photo.id, url=url)


@router.delete(
    "/{salon_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer une photo du salon",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Photo introuvable pour ce salon"},
    },
)
def delete_photo(
    salon_id: uuid.UUID,
    photo_id: uuid.UUID,
    repository: Annotated[SalonRepository, Depends(get_salon_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SALON_UPDATE))
    ],
) -> Response:
    """Retire la photo `(salon_id, photo_id)` et supprime l'objet (best-effort)."""

    try:
        RemoveSalonPhoto(repository, storage).execute(salon_id, photo_id)
    except SalonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
