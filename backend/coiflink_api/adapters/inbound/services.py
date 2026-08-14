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

import datetime
import decimal
import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.salons import (
    get_optional_media_storage,
    require_media_storage,
)
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
from coiflink_api.config import DEFAULT_MEDIA_MAX_PHOTOS
from coiflink_api.application.ports.media_storage import MediaStorage
from coiflink_api.application.ports.service_repository import ServiceRepository
from coiflink_api.application.services import (
    AddServicePhoto,
    CreateService,
    DeactivateService,
    GetService,
    IssueServiceImageUploadUrl,
    ListSalonServices,
    ReactivateService,
    RemoveServicePhoto,
    ServiceCommand,
    UpdateService,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.errors import (
    InvalidMediaType,
    InvalidServiceCategory,
    InvalidServiceDuration,
    InvalidServiceFilter,
    InvalidServiceName,
    InvalidServicePrice,
    MediaKeyMismatch,
    PhotoLimitExceeded,
    ServiceNotFound,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.service import Service, ServicePhoto, validate_service_filter

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


class ServicePhotoResponse(BaseModel):
    """Photo résolue de la galerie : clé d'objet remplacée par une URL signée."""

    id: uuid.UUID
    url: str | None


class ServiceResponse(BaseModel):
    """Représentation d'une prestation renvoyée par l'API.

    `photos` est la galerie complète, ordonnée (`position` croissante, index 0 =
    couverture) — **jamais** de clé d'objet brute (ADR-0005). `image_url` est un
    champ de **commodité** dérivé de la couverture (`photos[0].url` si non vide,
    sinon `null`) : miroir `SalonResponse.logo_url`, conservé pour les clients qui
    n'ont besoin que d'une vignette (ex. catalogue mobile) sans consommer la
    galerie complète.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    description: str | None
    price: decimal.Decimal
    duration_minutes: int
    category: str | None
    is_active: bool
    image_url: str | None
    photos: list[ServicePhotoResponse]
    created_at: object
    updated_at: object


class ServiceImageUploadUrlRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/services/media/upload-url`."""

    model_config = ConfigDict(extra="ignore")

    content_type: str = Field(examples=["image/png"])


class ServiceImageUploadUrlResponse(BaseModel):
    """URL signée de téléversement direct navigateur → stockage objet (ADR-0005)."""

    url: str
    method: str
    headers: dict[str, str]
    object_key: str
    expires_in: int


class AddServicePhotoRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/services/{service_id}/photos`.

    `object_key` est la clé **préalablement téléversée** (émise par
    `POST .../media/upload-url`). Bornée à la longueur de la colonne
    `service_photos.object_key` (`String(1024)`) : sans cette borne, une clé
    trop longue passerait la validation Pydantic et échouerait à l'écriture
    SQL (`DataError` non intercepté) au lieu d'un `422` propre.
    """

    model_config = ConfigDict(extra="ignore")

    object_key: str = Field(
        max_length=1024, examples=["services/<salon_id>/<uuid>.png"]
    )


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


def _service_response(
    service: Service,
    storage: MediaStorage | None,
    photos: Sequence[ServicePhoto] = (),
) -> ServiceResponse:
    """Mappe une `Service` (+ sa galerie) vers la réponse HTTP.

    `photos` doit être **déjà ordonnée** (`position` croissante, cf.
    `ServiceRepository.list_photos`) : la première entrée sert de couverture
    (`image_url`). `null`/liste vide si la prestation n'a pas de photo **ou** si
    le stockage objet n'est pas configuré (les lectures tolèrent l'absence de
    stockage, miroir `_salon_response`) — jamais la clé d'objet brute.
    """

    photo_responses = [
        ServicePhotoResponse(
            id=photo.id,
            url=storage.presign_download(photo.object_key) if storage is not None else None,
        )
        for photo in photos
    ]
    image_url = photo_responses[0].url if photo_responses else None
    return ServiceResponse(
        id=service.id,
        salon_id=service.salon_id,
        name=service.name,
        description=service.description,
        price=service.price,
        duration_minutes=service.duration_minutes,
        category=service.category,
        is_active=service.is_active,
        image_url=image_url,
        photos=photo_responses,
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


def _max_photos(request: Request) -> int:
    """Plafond de photos par prestation (config média, partagée avec le salon)."""

    config = getattr(request.app.state, "media_config", None)
    return getattr(config, "max_photos", DEFAULT_MEDIA_MAX_PHOTOS)


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
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceResponse:
    """Crée une prestation (`is_active=true`) pour le salon de la portée validée.

    Le `salon_id` vient du chemin (portée), jamais du corps. Journalise
    `SERVICE_CREATED` (§11.4) dans la même unité de travail. La galerie de
    photos n'est **pas** posée ici : les photos s'ajoutent séparément une fois
    la prestation créée (`POST .../services/{service_id}/photos`, miroir #15
    photos/salon).
    """

    try:
        service = CreateService(repository, audit_log).execute(
            salon_id, _command(payload), actor_user_id=principal.id
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _service_response(service, storage)


@router.get(
    "/{salon_id}/services",
    response_model=list[ServiceResponse],
    summary="Lister/filtrer les prestations d'un salon (actives et désactivées)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Filtre invalide : plage de dates incohérente"},
    },
)
def list_services(
    salon_id: uuid.UUID,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_READ))
    ],
    q: Annotated[
        str | None, Query(description="Recherche par nom (sous-chaîne)")
    ] = None,
    category: Annotated[str | None, Query()] = None,
    created_from: Annotated[datetime.date | None, Query()] = None,
    created_to: Annotated[datetime.date | None, Query()] = None,
) -> list[ServiceResponse]:
    """Liste **filtrable** des prestations du salon (vue gérant : actives **et** désactivées).

    Filtres **optionnels** combinés en **ET** : `q` (nom, sous-chaîne insensible à
    la casse), `category` (texte libre, égalité exacte), plage de dates de
    création inclusive (`created_from`/`created_to`, jour civil `Africa/Abidjan`).
    Les critères deviennent des clauses `WHERE` SQL (filtrage **serveur**) ; un
    filtre invalide → `422` (`InvalidServiceFilter`), message neutre. Pas de
    pagination ici (portée volontairement hors périmètre) : la réponse reste une
    liste complète, comme avant l'ajout du filtrage.
    """

    try:
        service_filter = validate_service_filter(
            q=q, category=category, created_from=created_from, created_to=created_to
        )
    except InvalidServiceFilter as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    services = ListSalonServices(repository).execute(
        salon_id, filter=service_filter, include_inactive=True
    )
    return [
        _service_response(service, storage, repository.list_photos(salon_id, service.id))
        for service in services
    ]


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
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
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
    return _service_response(service, storage, repository.list_photos(salon_id, service_id))


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
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceResponse:
    """Remplace les champs modifiables de la prestation puis journalise.

    Cœur du critère « modification journalisée » : après écriture, une entrée
    `SERVICE_UPDATED` porte la **liste des champs modifiés** (`metadata.changed`).
    La galerie de photos n'est **pas** touchée ici (routes dédiées
    `.../photos`).
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
    return _service_response(service, storage, repository.list_photos(salon_id, service_id))


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


@router.post(
    "/{salon_id}/services/{service_id}/reactivate",
    response_model=ServiceResponse,
    summary="Réactiver une prestation désactivée (journalisé §11.4)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Prestation introuvable (portée déjà validée)"},
    },
)
def reactivate_service(
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceResponse:
    """Réactive la prestation (`is_active=true`) — symétrique de la désactivation.

    Journalise `SERVICE_REACTIVATED` (§11.4).
    """

    try:
        service = ReactivateService(repository, audit_log).execute(
            salon_id, service_id, actor_user_id=principal.id
        )
    except ServiceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _service_response(service, storage, repository.list_photos(salon_id, service_id))


@router.post(
    "/{salon_id}/services/media/upload-url",
    response_model=ServiceImageUploadUrlResponse,
    summary="Émettre une URL signée de téléversement de l'image d'une prestation",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Type MIME hors liste blanche"},
        503: {"description": "Stockage objet non configuré"},
    },
)
def issue_service_image_upload_url(
    salon_id: uuid.UUID,
    payload: ServiceImageUploadUrlRequest,
    storage: Annotated[MediaStorage, Depends(require_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceImageUploadUrlResponse:
    """Fabrique la clé d'objet (sans PII) et renvoie l'URL signée `PUT` (ADR-0005).

    Scopée au **salon** (pas encore à une prestation précise) : le binaire est
    téléversé directement navigateur → stockage objet, puis la clé est ajoutée à
    la galerie via `POST .../services/{service_id}/photos` — la prestation peut
    être en cours de création (miroir #15 : le logo s'attache après la création
    du salon).
    """

    try:
        presigned = IssueServiceImageUploadUrl(storage).execute(
            salon_id, payload.content_type
        )
    except InvalidMediaType as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ServiceImageUploadUrlResponse(
        url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        object_key=presigned.object_key,
        expires_in=presigned.expires_in,
    )


@router.post(
    "/{salon_id}/services/{service_id}/photos",
    response_model=ServiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une photo à la galerie d'une prestation",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Prestation introuvable (portée déjà validée)"},
        409: {"description": "Nombre maximal de photos atteint"},
        422: {"description": "Clé d'objet hors du préfixe de ce salon"},
    },
)
def add_service_photo(
    request: Request,
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    payload: AddServicePhotoRequest,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> ServiceResponse:
    """Revalide le préfixe de la clé puis ajoute la photo (sous `MEDIA_MAX_PHOTOS`).

    Journalise `SERVICE_UPDATED` (§11.4). Renvoie la prestation à jour, galerie
    incluse (miroir `create_service`/`update_service`).
    """

    try:
        service = AddServicePhoto(
            repository, audit_log, max_photos=_max_photos(request)
        ).execute(salon_id, service_id, payload.object_key, actor_user_id=principal.id)
    except MediaKeyMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except PhotoLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ServiceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _service_response(service, storage, repository.list_photos(salon_id, service_id))


@router.delete(
    "/{salon_id}/services/{service_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer une photo de la galerie d'une prestation",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Photo introuvable pour cette prestation"},
    },
)
def remove_service_photo(
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    photo_id: uuid.UUID,
    repository: Annotated[ServiceRepository, Depends(get_service_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SERVICE_MANAGE))
    ],
) -> Response:
    """Retire la photo `(salon_id, service_id, photo_id)` et supprime l'objet
    (best-effort) ; journalise `SERVICE_UPDATED` (§11.4)."""

    try:
        RemoveServicePhoto(repository, audit_log, storage).execute(
            salon_id, service_id, photo_id, actor_user_id=principal.id
        )
    except ServiceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
