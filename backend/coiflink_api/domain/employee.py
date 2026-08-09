"""Entité de domaine « coiffeuse » (lecture) + validation des champs pro (#150).

`Employee` est l'objet-valeur de lecture combinant l'**identité** (`users`) et
l'**appartenance salon** (`salon_members`, US-1.4 #13) : un gérant gère ses
coiffeuses via cette vue unifiée plutôt qu'en composant lui-même `User` +
`SalonMembershipToCreate` (qui reste le seul type d'**écriture** de
l'appartenance). `status` ici est celui de `salon_members` — la source
d'autorité de la **disponibilité aux affectations** (PRD §11.2) — et non
`users.status` (compte global, hors périmètre de l'activation/désactivation
« coiffeuse » : désactiver une coiffeuse ne bloque pas sa connexion, seulement
son éligibilité aux nouvelles affectations de ce salon).

`specialties`/`hired_at` sont les champs professionnels facultatifs (migration
0011) : texte libre composé par le gérant, aucune contrainte fermée au MVP.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.domain.errors import InvalidEmployeeSpecialties

# Borne applicative (colonne `TEXT`) — miroir `InvalidCustomerNotes`.
SPECIALTIES_MAX_LENGTH = 1000


def normalize_specialties(raw: str | None) -> str | None:
    """Normalise (trim) les spécialités facultatives ; lève si trop longues.

    `None`/chaîne vide/blanche devient `None` (« non renseigné »), comme les
    autres champs texte optionnels du domaine (`normalize_cancellation_reason`,
    notes client). Ne **tronque jamais** silencieusement — un texte hors bornes
    est un refus explicite (`422`), le gérant compose ce champ lui-même et peut
    le raccourcir.
    """

    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    if len(trimmed) > SPECIALTIES_MAX_LENGTH:
        raise InvalidEmployeeSpecialties(
            f"Les spécialités ne doivent pas dépasser {SPECIALTIES_MAX_LENGTH} caractères."
        )
    return trimmed


@dataclass(frozen=True)
class Employee:
    """Une coiffeuse du salon (identité + appartenance), sans secret.

    `id` est l'`id` du compte `users` (le même que celui renvoyé par
    `POST /salons/{id}/employees`, `UserResponse.id`) — utilisé comme
    identifiant de ressource par les routes de gestion (`GET`/`PUT`/`DELETE`
    `.../employees/{id}`). `status` reflète `salon_members.status`
    (`ACTIVE`/`INACTIVE`), pas `users.status`.
    """

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    role: str
    status: str
    specialties: str | None
    hired_at: datetime.date | None
    created_at: datetime.datetime


__all__ = [
    "SPECIALTIES_MAX_LENGTH",
    "normalize_specialties",
    "Employee",
]
