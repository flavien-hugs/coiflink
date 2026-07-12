"""Identité autorisée d'une requête — domaine pur (ADR-0008, ADR-0015, issue #12).

Le `Principal` est l'utilisateur **authentifié** d'une requête, tel que résolu par
l'adapter entrant (`adapters/inbound/security.py`) : identifiant, rôle et statut
**relus en base** — jamais dérivés du seul claim `role` du JWT (une rétrogradation
ou une suspension prend ainsi effet immédiatement, sans attendre l'expiration du
jeton d'accès).

Invariant (PRD §11.3, ADR-0013) : le `Principal` ne transporte **aucune PII** —
ni nom, ni téléphone, ni e-mail. Il traverse toute la couche d'autorisation et
peut se retrouver dans une trace ou un log de refus : il ne doit rien contenir
qui identifie directement une personne.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.permissions import Permission, permissions_for


@dataclass(frozen=True)
class Principal:
    """Utilisateur authentifié d'une requête (sans aucune PII)."""

    id: uuid.UUID
    role: str
    status: str

    @property
    def is_active(self) -> bool:
        """Vrai si le compte est `ACTIVE` (seul état autorisé à agir)."""

        return self.status == UserStatus.ACTIVE.value

    @property
    def permissions(self) -> frozenset[Permission]:
        """Permissions du rôle (PRD §4.1) ; vide si le rôle est inconnu."""

        return permissions_for(self.role)

    def has_permission(self, permission: Permission) -> bool:
        """Vrai si le rôle **et** le statut du compte autorisent ce verbe métier."""

        return self.is_active and permission in self.permissions

    def has_role(self, *roles: Role) -> bool:
        """Vrai si le compte est actif et porte l'un des rôles listés."""

        return self.is_active and any(self.role == role.value for role in roles)


__all__ = ["Principal"]
