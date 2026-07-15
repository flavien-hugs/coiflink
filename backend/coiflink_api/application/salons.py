"""Cas d'usage : **création et consultation d'un salon** par un gérant (US-2.1, #15).

Tranche applicative hexagonale calquée sur #13 : ces cas d'usage ne dépendent que
de **ports** (`SalonRepository`, `MediaStorage`) — aucune dépendance
FastAPI/SQLAlchemy/boto3. Ils orchestrent le domaine (`domain/salon.py`,
`domain/phone.py`) et laissent l'adapter entrant traduire les erreurs en HTTP.

Invariant central (§Security du spec) : l'`owner_id` d'un salon est **imposé par
le serveur** depuis le `Principal` authentifié (argument d'`execute`), jamais lu
d'une commande venant du client — miroir exact du `role` fixé au câblage de
`CreateEmployee` (#13). Un champ `owner_id` dans le corps de requête n'existe pas.

Médias (logo/photos) — décision de conception (ADR-0005, ADR-0017) :
- le binaire **ne transite jamais** par l'API : le navigateur téléverse
  directement vers le stockage objet via une **URL signée** (`IssueMediaUploadUrl`) ;
- la **clé d'objet est fabriquée par le serveur** à partir d'UUID opaques, donc
  **sans PII** ni nom de fichier client (`_build_object_key`) ;
- la clé soumise à l'attachement est **revalidée** contre le préfixe du salon
  (`_ensure_key_prefix`) — sans quoi l'isolation §11.2 serait contournable *par
  les médias* (un gérant référence l'objet d'un autre salon).
"""

from __future__ import annotations

import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.media_storage import MediaStorage, PresignedUpload
from coiflink_api.application.ports.salon_repository import SalonRepository
from coiflink_api.domain.errors import (
    MediaKeyMismatch,
    PhotoLimitExceeded,
    SalonNotFound,
)
from coiflink_api.domain.opening_hours import parse_opening_hours, to_jsonb
from coiflink_api.domain.phone import normalize_phone
from coiflink_api.domain.salon import (
    Salon,
    SalonPhoto,
    SalonToCreate,
    validate_content_type,
    validate_coordinates,
    validate_salon_name,
)

# Segments de chemin d'objet par nature de média (le pluriel « photos » suit la
# convention de bucket ; « logo » reste singulier — un seul logo par salon).
_KIND_SEGMENTS: dict[str, str] = {"logo": "logo", "photo": "photos"}

DEFAULT_MAX_PHOTOS = 10


# --------------------------------------------------------------------------- #
# Vues de lecture — le salon enrichi de ses **URLs signées** (jamais de clé brute).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SalonPhotoView:
    """Photo résolue : la clé d'objet est remplacée par une **URL signée** (ou None)."""

    id: uuid.UUID
    url: str | None


@dataclass(frozen=True)
class SalonView:
    """Salon prêt à sérialiser : logo/photos en **URLs signées**, `is_bookable` §8.3.

    Le client ne voit **jamais** une clé d'objet brute ni une URL de bucket non
    signée. `logo_url` / `photos[].url` valent `None` si le stockage objet n'est
    pas configuré (les lectures restent servies, sans média).
    """

    salon: Salon
    logo_url: str | None
    photos: tuple[SalonPhotoView, ...]

    @property
    def is_bookable(self) -> bool:
        return self.salon.is_bookable


# --------------------------------------------------------------------------- #
# Fabrique / validation de clé d'objet (contraintes dures ADR-0005).
# --------------------------------------------------------------------------- #
def _build_object_key(salon_id: uuid.UUID, kind: str, extension: str) -> str:
    """Fabrique une clé d'objet **sans PII** : `salons/{salon_id}/{seg}/{uuid4}.{ext}`.

    `salon_id` et l'`uuid4` sont opaques : jamais le nom du salon, le téléphone,
    l'adresse ni un nom de fichier client. L'extension vient du **MIME validé**.
    """

    segment = _KIND_SEGMENTS[kind]
    return f"salons/{salon_id}/{segment}/{uuid.uuid4()}.{extension}"


def _ensure_key_prefix(salon_id: uuid.UUID, kind: str, object_key: str) -> str:
    """Revalide que `object_key` appartient bien au préfixe **de ce salon**.

    Règle de sécurité obligatoire (§11.2) : sans cette vérification, un gérant
    pourrait faire référencer par son salon une clé appartenant à un autre salon.
    Lève `MediaKeyMismatch` (→ 422) si le préfixe ne correspond pas.
    """

    segment = _KIND_SEGMENTS[kind]
    expected_prefix = f"salons/{salon_id}/{segment}/"
    if not isinstance(object_key, str) or not object_key.startswith(expected_prefix):
        raise MediaKeyMismatch("La clé d'objet ne correspond pas à ce salon.")
    return object_key


# --------------------------------------------------------------------------- #
# Création.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CreateSalonCommand:
    """Données d'entrée de création — **sans** `owner_id`, `status` ni `opening_hours`.

    L'`owner_id` est un argument d'`execute` fourni par la garde (le `Principal`),
    jamais un champ de commande venant du client.
    """

    name: str
    description: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    commune: str | None = None
    latitude: decimal.Decimal | None = None
    longitude: decimal.Decimal | None = None


class CreateSalon:
    """Crée un salon rattaché au gérant authentifié (`owner_id` imposé serveur)."""

    def __init__(self, repository: SalonRepository) -> None:
        self._repository = repository

    def execute(self, command: CreateSalonCommand, *, owner_id: uuid.UUID) -> Salon:
        """Valide puis persiste le salon (`status=ACTIVE`, `opening_hours=NULL`).

        Séquence : `validate_salon_name` → `validate_coordinates` →
        `normalize_phone` si fourni → `repository.create(...)`. La validation
        précède toute écriture (aucun appel au dépôt si le nom est invalide).
        """

        name = validate_salon_name(command.name)
        latitude, longitude = validate_coordinates(command.latitude, command.longitude)
        phone = normalize_phone(command.phone) if command.phone else None

        return self._repository.create(
            SalonToCreate(
                owner_id=owner_id,
                name=name,
                description=command.description or None,
                phone=phone,
                address=command.address or None,
                city=command.city or None,
                commune=command.commune or None,
                latitude=latitude,
                longitude=longitude,
            )
        )


# --------------------------------------------------------------------------- #
# Configuration des horaires d'ouverture (US-2.2, #16).
# --------------------------------------------------------------------------- #
class SetOpeningHours:
    """Valide (domaine pur) puis persiste les horaires d'un salon (§8.3, #16).

    Sémantique **replace** : le JSONB normalisé remplace intégralement les horaires
    existants. La **validation précède l'écriture** (aucun appel au dépôt si la
    structure est invalide), et `find_by_id` distingue `404` (salon absent, portée
    déjà validée) d'un `422` (structure invalide) — miroir d'`AttachSalonLogo`.
    """

    def __init__(self, repository: SalonRepository) -> None:
        self._repository = repository

    def execute(self, salon_id: uuid.UUID, payload: dict) -> Salon:
        hours = parse_opening_hours(payload)
        if self._repository.find_by_id(salon_id) is None:
            raise SalonNotFound("Salon introuvable.")
        return self._repository.set_opening_hours(salon_id, to_jsonb(hours))


# --------------------------------------------------------------------------- #
# Lectures (résolution des URLs signées).
# --------------------------------------------------------------------------- #
class _SalonReader:
    """Base des lectures : résout logo/photos en URLs signées via `MediaStorage`."""

    def __init__(
        self,
        repository: SalonRepository,
        media_storage: MediaStorage | None = None,
    ) -> None:
        self._repository = repository
        self._media_storage = media_storage

    def _view(self, salon: Salon) -> SalonView:
        photos = self._repository.list_photos(salon.id)
        return SalonView(
            salon=salon,
            logo_url=self._sign(salon.logo_object_key),
            photos=tuple(
                SalonPhotoView(id=photo.id, url=self._sign(photo.object_key))
                for photo in photos
            ),
        )

    def _sign(self, object_key: str | None) -> str | None:
        """URL signée de lecture, ou `None` si pas de clé / stockage non configuré."""

        if object_key is None or self._media_storage is None:
            return None
        return self._media_storage.presign_download(object_key)


class GetSalon(_SalonReader):
    """Lit un salon (portée déjà validée par la garde) et le résout en `SalonView`."""

    def execute(self, salon_id: uuid.UUID) -> SalonView:
        salon = self._repository.find_by_id(salon_id)
        if salon is None:
            raise SalonNotFound("Salon introuvable.")
        return self._view(salon)


class ListOwnSalons(_SalonReader):
    """Liste les salons du gérant authentifié, chacun résolu en `SalonView`."""

    def execute(self, owner_id: uuid.UUID) -> tuple[SalonView, ...]:
        return tuple(
            self._view(salon) for salon in self._repository.list_for_owner(owner_id)
        )


# --------------------------------------------------------------------------- #
# Médias : émission d'URL, attachement du logo, ajout/retrait de photo.
# --------------------------------------------------------------------------- #
class IssueMediaUploadUrl:
    """Fabrique la clé d'objet (sans PII) et délègue au stockage l'URL signée `PUT`."""

    def __init__(self, media_storage: MediaStorage) -> None:
        self._media_storage = media_storage

    def execute(
        self, salon_id: uuid.UUID, kind: str, content_type: str
    ) -> PresignedUpload:
        if kind not in _KIND_SEGMENTS:
            # Garde-fou : l'adapter contraint déjà `kind` à {logo, photo}.
            raise MediaKeyMismatch("Nature de média inconnue.")
        extension = validate_content_type(content_type)
        object_key = _build_object_key(salon_id, kind, extension)
        return self._media_storage.presign_upload(object_key, content_type)


class AttachSalonLogo:
    """Attache une clé d'objet **revalidée** comme logo du salon (remplace l'ancien)."""

    def __init__(
        self,
        repository: SalonRepository,
        media_storage: MediaStorage | None = None,
    ) -> None:
        self._repository = repository
        self._media_storage = media_storage

    def execute(self, salon_id: uuid.UUID, object_key: str) -> Salon:
        key = _ensure_key_prefix(salon_id, "logo", object_key)
        previous = self._repository.find_by_id(salon_id)
        if previous is None:
            raise SalonNotFound("Salon introuvable.")
        salon = self._repository.set_logo(salon_id, key)
        # Nettoyage best-effort de l'ancien objet remplacé (jamais bloquant).
        if (
            previous.logo_object_key
            and previous.logo_object_key != key
            and self._media_storage is not None
        ):
            self._media_storage.delete(previous.logo_object_key)
        return salon


class AddSalonPhoto:
    """Ajoute une photo (clé revalidée) sous la limite `MEDIA_MAX_PHOTOS` (§#15)."""

    def __init__(
        self, repository: SalonRepository, *, max_photos: int = DEFAULT_MAX_PHOTOS
    ) -> None:
        self._repository = repository
        self._max_photos = max_photos

    def execute(self, salon_id: uuid.UUID, object_key: str) -> SalonPhoto:
        key = _ensure_key_prefix(salon_id, "photo", object_key)
        if self._repository.find_by_id(salon_id) is None:
            raise SalonNotFound("Salon introuvable.")
        if self._repository.count_photos(salon_id) >= self._max_photos:
            raise PhotoLimitExceeded(
                "Le nombre maximal de photos pour ce salon est atteint."
            )
        return self._repository.add_photo(salon_id, key)


class RemoveSalonPhoto:
    """Retire une photo du salon et supprime l'objet correspondant (best-effort)."""

    def __init__(
        self,
        repository: SalonRepository,
        media_storage: MediaStorage | None = None,
    ) -> None:
        self._repository = repository
        self._media_storage = media_storage

    def execute(self, salon_id: uuid.UUID, photo_id: uuid.UUID) -> None:
        object_key = self._repository.delete_photo(salon_id, photo_id)
        if object_key is None:
            raise SalonNotFound("Photo introuvable.")
        if self._media_storage is not None:
            self._media_storage.delete(object_key)


__all__ = [
    "DEFAULT_MAX_PHOTOS",
    "SalonPhotoView",
    "SalonView",
    "CreateSalonCommand",
    "CreateSalon",
    "SetOpeningHours",
    "GetSalon",
    "ListOwnSalons",
    "IssueMediaUploadUrl",
    "AttachSalonLogo",
    "AddSalonPhoto",
    "RemoveSalonPhoto",
]
