"""Politique d'autorisation — couche application (ADR-0008, ADR-0015, issue #12).

`AccessPolicy` est le point d'entrée **unique** des décisions d'accès. Il ne
connaît **ni HTTP ni SQL** : il orchestre le domaine (matrice §4.1 de
`domain/permissions.py`, règles de portée §11.2 de `domain/access.py`) en chargeant
la portée via le port `SalonScopeRepository`. Il lève `PermissionDenied` — c'est
l'adapter entrant qui traduit ce refus en `403`.

Répartition des responsabilités (à ne pas contourner) :

- *décider* → `domain/` (fonctions pures) ;
- *orchestrer + charger la portée* → ce module ;
- *traduire HTTP → domaine et refus → statut* → `adapters/inbound/security.py`.

Une route métier ne réimplémente donc **jamais** un contrôle d'accès : elle
déclare une garde, qui appelle cette politique.
"""

from __future__ import annotations

import uuid

from coiflink_api.application.ports.salon_scope_repository import SalonScopeRepository
from coiflink_api.domain.access import SalonScope, can_access_salon
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import PermissionDenied
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

# Messages **génériques et constants** : un refus ne nomme jamais le rôle attendu,
# la permission manquante ni le salon visé (aucun oracle sur ce qui existe).
_DENIED = "Accès refusé."


class AccessPolicy:
    """Applique les permissions (PRD §4.1) et la portée salon (PRD §11.2)."""

    def __init__(self, scope_repository: SalonScopeRepository) -> None:
        self._scope_repository = scope_repository

    def require_roles(self, principal: Principal, *roles: Role) -> None:
        """Exige que le compte porte l'un des rôles listés ; lève `PermissionDenied` sinon."""

        if not principal.has_role(*roles):
            raise PermissionDenied(_DENIED)

    def require_permission(self, principal: Principal, permission: Permission) -> None:
        """Exige la permission (PRD §4.1) ; lève `PermissionDenied` sinon."""

        if not principal.has_permission(permission):
            raise PermissionDenied(_DENIED)

    def scope_of(self, principal: Principal) -> SalonScope:
        """Charge la portée salon du compte (PRD §11.2).

        L'`ADMIN` **court-circuite le port** : sa portée est la plateforme entière,
        aucune requête n'est nécessaire. Un compte non `ACTIVE` a une portée vide.
        """

        if not principal.is_active:
            return SalonScope.empty()
        if principal.role == Role.ADMIN.value:
            return SalonScope.platform()
        return SalonScope.of(
            self._scope_repository.salon_ids_for(principal.id, principal.role)
        )

    def require_salon(self, principal: Principal, salon_id: uuid.UUID) -> SalonScope:
        """**Point unique** de blocage de l'accès inter-salons (PRD §11.2).

        Charge la portée du compte, délègue la décision à `can_access_salon`, et
        lève `PermissionDenied` si le salon visé n'y figure pas. Retourne la portée
        chargée pour que l'appelant la réutilise (aucune seconde requête).
        """

        scope = self.scope_of(principal)
        if not can_access_salon(principal, salon_id, scope):
            raise PermissionDenied(_DENIED)
        return scope


__all__ = ["AccessPolicy"]
