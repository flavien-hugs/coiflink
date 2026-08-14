"""Cas d'usage : **gestion des prestations d'un salon** (US-2.3, #17).

Tranche applicative hexagonale calquée sur #15/#16 : ces cas d'usage ne dépendent
que de **ports** (`ServiceRepository`, `AuditLog`) — aucune dépendance
FastAPI/SQLAlchemy. Ils orchestrent le domaine (`domain/service.py`,
`domain/audit.py`) et laissent l'adapter entrant traduire les erreurs en HTTP.

Deux invariants structurants :

- **`salon_id` imposé par la portée** : l'`salon_id` d'une prestation provient
  toujours de la portée validée (`require_salon_scope`), passé en argument
  d'`execute` ; il n'est **jamais** lu du corps de requête (garde-fou
  anti-élévation, miroir du `owner_id` de #15).
- **Journalisation §11.4 dans la même unité de travail** : chaque **mutation**
  (création, modification, désactivation) enregistre une `AuditEntry` via le port
  `AuditLog`, dans la **même `Session`** que l'écriture métier — commit/rollback
  atomique (patron `CreateEmployee` #13). L'**acteur** est le `Principal`
  authentifié (`actor_user_id`), jamais une valeur du corps.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.media_storage import MediaStorage, PresignedUpload
from coiflink_api.application.ports.service_repository import ServiceRepository
from coiflink_api.config import DEFAULT_MEDIA_MAX_PHOTOS
from coiflink_api.domain.audit import ENTITY_TYPE_SERVICE, AuditAction, AuditEntry
from coiflink_api.domain.errors import MediaKeyMismatch, PhotoLimitExceeded, ServiceNotFound
from coiflink_api.domain.salon import validate_content_type
from coiflink_api.domain.service import (
    Service,
    ServiceFilter,
    ServiceToCreate,
    ServiceUpdate,
    normalize_category,
    normalize_description,
    validate_duration,
    validate_price,
    validate_service_name,
)

# Segment de préfixe de la clé d'objet image (ADR-0005) : `services/{salon_id}/…`,
# **distinct** du préfixe `salons/{salon_id}/…` (#15) — une prestation n'est pas
# un salon, même si le port `MediaStorage` (générique) est partagé.
_IMAGE_PREFIX_SEGMENT = "services"


def _build_image_object_key(salon_id: uuid.UUID, extension: str) -> str:
    """Fabrique une clé d'objet **sans PII** : `services/{salon_id}/{uuid4}.{ext}`.

    Miroir `application/salons.py::_build_object_key`. `salon_id` et l'`uuid4`
    sont opaques ; l'extension vient du **MIME validé**. Le `service_id` n'entre
    **pas** dans la clé : à l'émission de l'URL, la prestation n'existe pas
    encore nécessairement (création en cours) — seul le salon est déjà connu.
    """

    return f"{_IMAGE_PREFIX_SEGMENT}/{salon_id}/{uuid.uuid4()}.{extension}"


def _ensure_image_key_prefix(salon_id: uuid.UUID, object_key: str) -> str:
    """Revalide que `object_key` appartient bien au préfixe **de ce salon**.

    Règle de sécurité obligatoire (§11.2, miroir `application/salons.py::
    _ensure_key_prefix`) : sans cette vérification, un gérant pourrait faire
    référencer par une prestation de son salon une clé appartenant à un autre
    salon. Lève `MediaKeyMismatch` (→ 422) si le préfixe ne correspond pas.
    """

    expected_prefix = f"{_IMAGE_PREFIX_SEGMENT}/{salon_id}/"
    if not isinstance(object_key, str) or not object_key.startswith(expected_prefix):
        raise MediaKeyMismatch("La clé d'objet ne correspond pas à ce salon.")
    return object_key

# Champs comparés pour le diff neutre de `UpdateService` (ordre stable). Seuls des
# **noms de champs** sont journalisés — jamais les valeurs (règle de non-fuite).
_DIFF_FIELDS: tuple[str, ...] = (
    "name",
    "price",
    "duration_minutes",
    "description",
    "category",
)


@dataclass(frozen=True)
class ServiceCommand:
    """Champs saisissables d'une prestation (création **ou** modification).

    Ni `salon_id`, ni `id`, ni `is_active` : le `salon_id` vient de la portée,
    `is_active` se pilote via `DeactivateService`. Prix et durée sont
    **obligatoires** (validés dans le domaine avant écriture).
    """

    name: str
    price: object
    duration_minutes: object
    description: str | None = None
    category: str | None = None


def _validate(command: ServiceCommand) -> tuple[str, object, int, str | None, str | None]:
    """Valide la commande (nom → prix → durée → catégorie) ; retourne les champs normalisés.

    La validation précède **toute** écriture (aucun appel au dépôt si un champ est
    invalide). L'ordre est stable pour des messages d'erreur déterministes.
    """

    name = validate_service_name(command.name)
    price = validate_price(command.price)  # type: ignore[arg-type]
    duration = validate_duration(command.duration_minutes)  # type: ignore[arg-type]
    description = normalize_description(command.description)
    category = normalize_category(command.category)
    return name, price, duration, description, category


class CreateService:
    """Crée une prestation rattachée au salon de la portée et journalise (§11.4)."""

    def __init__(self, repository: ServiceRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        command: ServiceCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> Service:
        """Valide puis persiste la prestation (`is_active=True`), puis journalise.

        Séquence : validation domaine → `repository.create(...)` →
        `audit.record(SERVICE_CREATED)`. Le `salon_id` provient de la portée validée.
        """

        name, price, duration, description, category = _validate(command)
        service = self._repository.create(
            ServiceToCreate(
                salon_id=salon_id,
                name=name,
                price=price,  # type: ignore[arg-type]
                duration_minutes=duration,
                description=description,
                category=category,
            )
        )
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.SERVICE_CREATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SERVICE,
                entity_id=service.id,
                metadata={},
            )
        )
        return service


class ListSalonServices:
    """Liste les prestations d'un salon (lecture — pas d'audit)."""

    def __init__(self, repository: ServiceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        filter: ServiceFilter,
        include_inactive: bool = True,
    ) -> tuple[Service, ...]:
        return self._repository.list_for_salon(
            salon_id, filter=filter, include_inactive=include_inactive
        )


class GetService:
    """Consulte une prestation dans le périmètre du salon (lecture — pas d'audit)."""

    def __init__(self, repository: ServiceRepository) -> None:
        self._repository = repository

    def execute(self, salon_id: uuid.UUID, service_id: uuid.UUID) -> Service:
        service = self._repository.find_by_id(salon_id, service_id)
        if service is None:
            raise ServiceNotFound("Prestation introuvable.")
        return service


def _changed_fields(current: Service, changes: ServiceUpdate) -> list[str]:
    """Noms des champs dont la valeur change (diff **neutre**, ordre stable).

    Ne compare que les **noms** de champs modifiés : aucune valeur n'entre dans le
    journal d'audit (règle de non-fuite §11.4).
    """

    return [
        field
        for field in _DIFF_FIELDS
        if getattr(current, field) != getattr(changes, field)
    ]


class UpdateService:
    """Modifie une prestation (sémantique *replace*) et journalise (§11.4).

    Cœur du critère « modification journalisée » : après écriture, une entrée
    `SERVICE_UPDATED` porte la **liste des champs modifiés** (`metadata.changed`).
    La validation précède l'écriture ; `find_by_id` distingue `404` (prestation
    absente, portée déjà validée) d'un `422` (champ invalide) — aucune écriture ni
    audit si la validation échoue.
    """

    def __init__(self, repository: ServiceRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        service_id: uuid.UUID,
        command: ServiceCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> Service:
        name, price, duration, description, category = _validate(command)

        current = self._repository.find_by_id(salon_id, service_id)
        if current is None:
            raise ServiceNotFound("Prestation introuvable.")

        changes = ServiceUpdate(
            name=name,
            price=price,  # type: ignore[arg-type]
            duration_minutes=duration,
            description=description,
            category=category,
        )
        changed = _changed_fields(current, changes)
        service = self._repository.update(salon_id, service_id, changes)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.SERVICE_UPDATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SERVICE,
                entity_id=service_id,
                metadata={"changed": changed},
            )
        )
        return service


class DeactivateService:
    """Désactive une prestation (« suppression » canonique) et journalise (§11.4).

    Décision d'architecture (spec *Open Questions* #2) : la « suppression » de
    l'issue est une **désactivation** (`is_active=False`) — la FK
    `appointment_services → services` est `ON DELETE RESTRICT`, une prestation déjà
    réservée ne peut être supprimée physiquement, et la désactivation préserve
    l'historique (prix figé des RDV passés). `find_by_id` avant écriture distingue
    `404` d'une simple portée validée. Enregistre `SERVICE_DEACTIVATED`.
    """

    def __init__(self, repository: ServiceRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        service_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> Service:
        if self._repository.find_by_id(salon_id, service_id) is None:
            raise ServiceNotFound("Prestation introuvable.")
        service = self._repository.set_active(salon_id, service_id, active=False)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.SERVICE_DEACTIVATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SERVICE,
                entity_id=service_id,
                metadata={},
            )
        )
        return service


class ReactivateService:
    """Réactive une prestation désactivée et journalise (§11.4).

    Symétrique de `DeactivateService` : `find_by_id` avant écriture distingue
    `404` d'une simple portée validée. Enregistre `SERVICE_REACTIVATED`.
    """

    def __init__(self, repository: ServiceRepository, audit_log: AuditLog) -> None:
        self._repository = repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        service_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> Service:
        if self._repository.find_by_id(salon_id, service_id) is None:
            raise ServiceNotFound("Prestation introuvable.")
        service = self._repository.set_active(salon_id, service_id, active=True)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.SERVICE_REACTIVATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SERVICE,
                entity_id=service_id,
                metadata={},
            )
        )
        return service


class IssueServiceImageUploadUrl:
    """Fabrique la clé d'objet (sans PII) et délègue au stockage l'URL signée `PUT`.

    Miroir `application/salons.py::IssueMediaUploadUrl`, simplifié : une seule
    nature de média (« image »), pas de `kind`. Le binaire ne transite **jamais**
    par l'API (ADR-0005) — le navigateur téléverse directement vers le stockage
    objet avec cette URL. Aucune écriture, aucun audit (lecture d'une capacité de
    téléversement, pas une mutation de prestation).
    """

    def __init__(self, media_storage: MediaStorage) -> None:
        self._media_storage = media_storage

    def execute(self, salon_id: uuid.UUID, content_type: str) -> PresignedUpload:
        extension = validate_content_type(content_type)
        object_key = _build_image_object_key(salon_id, extension)
        return self._media_storage.presign_upload(object_key, content_type)


class AddServicePhoto:
    """Ajoute une photo (clé revalidée) sous la limite `MEDIA_MAX_PHOTOS` (galerie).

    Miroir `application/salons.py::AddSalonPhoto`, avec une différence
    délibérée : contrairement à `AddSalonPhoto` (non journalisé), cette action
    journalise `SERVICE_UPDATED` (§11.4) — #17 pose « modification journalisée »
    comme critère d'acceptation pour toute mutation de prestation, photos
    incluses. La clé est revalidée contre le préfixe du salon
    (`_ensure_image_key_prefix`, sinon `MediaKeyMismatch` → 422) avant
    d'atteindre le dépôt — sans quoi l'isolation §11.2 serait contournable *par
    les médias* (référencer l'objet d'un autre salon).
    """

    def __init__(
        self,
        repository: ServiceRepository,
        audit_log: AuditLog,
        *,
        max_photos: int = DEFAULT_MEDIA_MAX_PHOTOS,
    ) -> None:
        self._repository = repository
        self._audit_log = audit_log
        self._max_photos = max_photos

    def execute(
        self,
        salon_id: uuid.UUID,
        service_id: uuid.UUID,
        object_key: str,
        *,
        actor_user_id: uuid.UUID,
    ) -> Service:
        key = _ensure_image_key_prefix(salon_id, object_key)

        service = self._repository.find_by_id(salon_id, service_id)
        if service is None:
            raise ServiceNotFound("Prestation introuvable.")
        if self._repository.count_photos(salon_id, service_id) >= self._max_photos:
            raise PhotoLimitExceeded(
                "Le nombre maximal de photos pour cette prestation est atteint."
            )

        self._repository.add_photo(salon_id, service_id, key)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.SERVICE_UPDATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SERVICE,
                entity_id=service_id,
                metadata={"changed": ["photos"]},
            )
        )
        # La ligne `services` n'a pas changé (seule la galerie a bougé) : `service`,
        # déjà chargé pour la vérification d'existence, reste à jour — évite une
        # seconde lecture.
        return service


class RemoveServicePhoto:
    """Retire une photo de la prestation et supprime l'objet (best-effort).

    Miroir `application/salons.py::RemoveSalonPhoto`, même différence
    d'audit que `AddServicePhoto` (journalise `SERVICE_UPDATED`, contrairement
    à `RemoveSalonPhoto`).
    """

    def __init__(
        self,
        repository: ServiceRepository,
        audit_log: AuditLog,
        media_storage: MediaStorage | None = None,
    ) -> None:
        self._repository = repository
        self._audit_log = audit_log
        self._media_storage = media_storage

    def execute(
        self,
        salon_id: uuid.UUID,
        service_id: uuid.UUID,
        photo_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> None:
        object_key = self._repository.delete_photo(salon_id, service_id, photo_id)
        if object_key is None:
            raise ServiceNotFound("Photo introuvable.")
        if self._media_storage is not None:
            self._media_storage.delete(object_key)

        self._audit_log.record(
            AuditEntry(
                action=AuditAction.SERVICE_UPDATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SERVICE,
                entity_id=service_id,
                metadata={"changed": ["photos"]},
            )
        )


__all__ = [
    "ServiceCommand",
    "CreateService",
    "ListSalonServices",
    "GetService",
    "UpdateService",
    "DeactivateService",
    "ReactivateService",
    "IssueServiceImageUploadUrl",
    "AddServicePhoto",
    "RemoveServicePhoto",
]
