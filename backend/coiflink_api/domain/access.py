"""Règles de **portée** (isolation multi-salons) — domaine pur (PRD §11.2, #12).

Là où `domain/permissions.py` répond « ce rôle a-t-il le droit de faire cela ? »,
ce module répond « …**sur ces données-là** ? ». C'est ici que vit littéralement le
PRD §11.2 :

- un **gérant** ne voit que les données de **son** salon ;
- un **coiffeur** ne voit que **son** planning / les RDV qui lui sont **assignés** ;
- un **client** ne voit que **ses propres** rendez-vous ;
- l'**admin** supervise la plateforme.

Ce sont des **fonctions pures** : aucune I/O, aucune base, aucun HTTP. La portée
(`SalonScope`) leur est **fournie** par l'appelant, qui l'a chargée via le port
`SalonScopeRepository` — le domaine ne sait pas *comment* on lit un salon, il sait
seulement *décider*. Elles sont donc testables sans base ni serveur.

Invariant de sûreté : un compte non `ACTIVE` n'accède à **rien** (défense en
profondeur — l'adapter entrant l'a déjà refusé en amont).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from coiflink_api.domain.enums import Role
from coiflink_api.domain.principal import Principal


@dataclass(frozen=True)
class SalonScope:
    """Ensemble des salons sur lesquels un compte a une portée.

    `platform_wide` est le cas de l'`ADMIN` : la supervision ne s'énumère pas
    salon par salon (elle les couvre tous, y compris ceux créés après la requête).
    Pour tous les autres rôles, la portée est l'ensemble **explicite** `salon_ids`,
    vide par défaut — deny-by-default.
    """

    salon_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    platform_wide: bool = False

    @classmethod
    def empty(cls) -> "SalonScope":
        """Portée vide : aucun salon (client, rôle inconnu, coiffeur non rattaché)."""

        return cls()

    @classmethod
    def of(cls, salon_ids: Iterable[uuid.UUID]) -> "SalonScope":
        """Portée limitée aux salons énumérés (gérant, coiffeur)."""

        return cls(salon_ids=frozenset(salon_ids))

    @classmethod
    def platform(cls) -> "SalonScope":
        """Portée de supervision plateforme (`ADMIN`) : tous les salons."""

        return cls(platform_wide=True)

    def covers(self, salon_id: uuid.UUID) -> bool:
        """Vrai si ce salon est dans la portée."""

        return self.platform_wide or salon_id in self.salon_ids


@dataclass(frozen=True)
class AppointmentRef:
    """Référence minimale d'un rendez-vous, suffisante pour **décider** (sans PII).

    Alimentée par les issues RDV (#21+) depuis leur dépôt : la décision d'accès ne
    dépend jamais du contenu du rendez-vous, seulement de son rattachement.
    """

    salon_id: uuid.UUID
    client_id: uuid.UUID
    hairdresser_id: uuid.UUID | None = None


def can_access_salon(
    principal: Principal, salon_id: uuid.UUID, scope: SalonScope
) -> bool:
    """Vrai si ce compte peut accéder aux données de ce salon (PRD §11.2).

    `ADMIN` : toujours (supervision). `MANAGER` / `HAIRDRESSER` : uniquement si le
    salon est dans leur portée. `CLIENT` : jamais — un client n'a pas de portée
    *salon* (il accède à **ses** rendez-vous, pas aux données d'un salon).
    """

    if not principal.is_active:
        return False
    if principal.role == Role.ADMIN.value:
        return True
    if principal.role in (Role.MANAGER.value, Role.HAIRDRESSER.value):
        return scope.covers(salon_id)
    return False


def can_access_appointment(
    principal: Principal, appointment: AppointmentRef, scope: SalonScope
) -> bool:
    """Vrai si ce compte peut accéder à ce rendez-vous (PRD §11.2).

    `CLIENT` : uniquement **son** rendez-vous. `HAIRDRESSER` : uniquement un RDV
    qui lui est **assigné** (« son planning »). `MANAGER` : un RDV d'un salon de sa
    portée. `ADMIN` : toujours.
    """

    if not principal.is_active:
        return False
    if principal.role == Role.ADMIN.value:
        return True
    if principal.role == Role.CLIENT.value:
        return appointment.client_id == principal.id
    if principal.role == Role.HAIRDRESSER.value:
        return (
            appointment.hairdresser_id is not None
            and appointment.hairdresser_id == principal.id
        )
    if principal.role == Role.MANAGER.value:
        return scope.covers(appointment.salon_id)
    return False


__all__ = [
    "SalonScope",
    "AppointmentRef",
    "can_access_salon",
    "can_access_appointment",
]
