"""Entités et règles de domaine « salon » (domaine pur, US-2.1, #15).

Ces `dataclass` et fonctions découplent l'application du modèle ORM SQLAlchemy
(`adapters/outbound/persistence/models.py`) : conformément à l'hexagonal
(ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni SQLAlchemy.

Ce module porte trois responsabilités **pures** :

- les entités de lecture/écriture (`SalonToCreate`, `Salon`, `SalonPhoto`) ;
- la **validation** propre au salon (`validate_salon_name`,
  `validate_coordinates`) — distincte de celle d'un compte utilisateur ;
- la **règle §8.3** isolée et testable (`is_bookable`) : un salon n'est
  réservable que s'il est `ACTIVE` **et** possède des horaires. La configuration
  des horaires elle-même relève de #16 : ici la colonne reste `NULL`.

Le stockage des médias (logo/photos) est délégué au port `MediaStorage`
(ADR-0005) ; la validation du **type MIME** et la **fabrique de clé d'objet**
sans PII vivent ici (règles pures) et dans le cas d'usage (`application/salons.py`).
"""

from __future__ import annotations

import decimal
import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import SalonStatus
from coiflink_api.domain.errors import InvalidLocation, InvalidMediaType, InvalidSalonName

# Bornes du nom de salon (distinctes du nom de personne de `domain/user.py`).
SALON_NAME_MAX_LENGTH = 255

# Bornes géographiques (WGS 84) des coordonnées de localisation.
_LAT_MIN, _LAT_MAX = decimal.Decimal("-90"), decimal.Decimal("90")
_LON_MIN, _LON_MAX = decimal.Decimal("-180"), decimal.Decimal("180")

# Types MIME d'image acceptés pour le logo et les photos (liste blanche) et leur
# extension canonique. L'extension de la clé d'objet est **dérivée du MIME
# validé**, jamais du nom de fichier fourni par le client (PII / traversée).
ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def validate_salon_name(name: str) -> str:
    """Valide et normalise (trim) le nom du salon ; lève `InvalidSalonName` sinon.

    Règles : chaîne non vide après `strip()`, longueur ≤ `SALON_NAME_MAX_LENGTH`.
    Volontairement **séparée** de `validate_name` (`domain/user.py`) : ses bornes
    visent un nom de personne et son erreur est déjà mappée à l'inscription.
    """

    if not isinstance(name, str):
        raise InvalidSalonName("Le nom du salon est requis.")
    cleaned = name.strip()
    if not cleaned:
        raise InvalidSalonName("Le nom du salon est requis.")
    if len(cleaned) > SALON_NAME_MAX_LENGTH:
        raise InvalidSalonName(
            f"Le nom du salon ne doit pas dépasser {SALON_NAME_MAX_LENGTH} caractères."
        )
    return cleaned


def validate_coordinates(
    latitude: decimal.Decimal | None, longitude: decimal.Decimal | None
) -> tuple[decimal.Decimal | None, decimal.Decimal | None]:
    """Valide un couple de coordonnées : **les deux ou aucune**, dans les bornes.

    - `(None, None)` → accepté (localisation non géocodée) ;
    - une seule des deux fournie → `InvalidLocation` ;
    - latitude hors `[-90, 90]` ou longitude hors `[-180, 180]` → `InvalidLocation`.
    """

    if latitude is None and longitude is None:
        return None, None
    if latitude is None or longitude is None:
        raise InvalidLocation(
            "La latitude et la longitude doivent être fournies ensemble."
        )
    if not (_LAT_MIN <= latitude <= _LAT_MAX):
        raise InvalidLocation("La latitude est hors des bornes autorisées.")
    if not (_LON_MIN <= longitude <= _LON_MAX):
        raise InvalidLocation("La longitude est hors des bornes autorisées.")
    return latitude, longitude


def validate_content_type(content_type: str) -> str:
    """Retourne l'extension canonique d'un type MIME accepté ; lève `InvalidMediaType`.

    Le type MIME est confronté à la **liste blanche** `ALLOWED_IMAGE_TYPES`.
    L'extension retournée sert à fabriquer la clé d'objet côté serveur ; elle ne
    dépend jamais du nom de fichier client.
    """

    if not isinstance(content_type, str):
        raise InvalidMediaType("Type de média non pris en charge.")
    extension = ALLOWED_IMAGE_TYPES.get(content_type.strip().lower())
    if extension is None:
        raise InvalidMediaType("Type de média non pris en charge.")
    return extension


def is_bookable(status: str, opening_hours: object | None) -> bool:
    """Un salon n'est réservable que s'il est `ACTIVE` **et** a des horaires (§8.3).

    `bool(opening_hours)` traite `None` **et** `{}` comme « pas d'horaire » : un
    JSONB vide écrit plus tard (#16) ne rend pas un salon réservable par accident.
    Ce prédicat est **dérivé, jamais persisté** — l'exposer suffit à matérialiser
    le second critère d'acceptation de #15.
    """

    return status == SalonStatus.ACTIVE.value and bool(opening_hours)


@dataclass(frozen=True)
class SalonToCreate:
    """Intention d'écriture d'un salon (l'`owner_id` est **imposé par le serveur**).

    `owner_id` provient toujours du `Principal` authentifié, jamais du corps de
    requête : garde-fou anti-élévation de privilège (miroir du `role` absent de
    `CreateEmployeeRequest`, #13). `status` et `opening_hours` ne sont pas ici :
    la création force `status=ACTIVE` et `opening_hours=NULL`.
    """

    owner_id: uuid.UUID
    name: str
    description: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    commune: str | None = None
    latitude: decimal.Decimal | None = None
    longitude: decimal.Decimal | None = None


@dataclass(frozen=True)
class SalonPhoto:
    """Photo de salon persistée : référence une **clé d'objet**, jamais une URL.

    L'URL signée de lecture est calculée à la volée (`MediaStorage.presign_download`)
    à chaque lecture — une URL signée expire, la persister serait un bug.
    """

    id: uuid.UUID
    salon_id: uuid.UUID
    object_key: str
    position: int
    created_at: datetime.datetime


@dataclass(frozen=True)
class Salon:
    """Salon persisté. `logo_object_key` est une **clé d'objet** (jamais une URL).

    Les photos sont chargées séparément (`SalonPhoto`) par le cas d'usage de
    lecture, qui résout les URLs signées avant de renvoyer la réponse HTTP.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    phone: str | None
    address: str | None
    city: str | None
    commune: str | None
    latitude: decimal.Decimal | None
    longitude: decimal.Decimal | None
    logo_object_key: str | None
    status: str
    opening_hours: dict | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @property
    def is_bookable(self) -> bool:
        """Reflet §8.3 sur l'entité : `ACTIVE` **et** horaires présents."""

        return is_bookable(self.status, self.opening_hours)


__all__ = [
    "SALON_NAME_MAX_LENGTH",
    "ALLOWED_IMAGE_TYPES",
    "validate_salon_name",
    "validate_coordinates",
    "validate_content_type",
    "is_bookable",
    "SalonToCreate",
    "SalonPhoto",
    "Salon",
]
