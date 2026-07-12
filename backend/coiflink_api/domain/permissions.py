"""Matrice de permissions par rôle (PRD §4.1) — domaine pur (ADR-0008, ADR-0015).

Ce module est **l'unique source de vérité des droits** de CoifLink : il traduit le
tableau des permissions du PRD §4.1 en valeurs Python, sans aucune dépendance
framework/I/O. L'application (`application/authorization.py`) et les adapters
entrants (`adapters/inbound/security.py`) s'y adossent ; ils n'en réimplémentent
aucune règle.

Deux invariants portés par ce module (issue #12) :

- **Deny-by-default jusque dans le domaine** : `ROLE_PERMISSIONS` est **fermé**.
  Un rôle absent de la table (rôle retiré, claim forgé, valeur inconnue) n'a
  **aucune** permission — jamais un accès par défaut.
- **`ADMIN` n'est pas un joker implicite** : ses permissions de supervision
  plateforme sont **listées** comme celles des autres rôles, ce qui rend le
  privilège lisible et auditable (et non dérivé d'un `if role == ADMIN: True`
  disséminé dans le code).

La **portée** (quel salon, quel rendez-vous) est un contrôle **distinct**, traité
par `domain/access.py` (PRD §11.2) : une permission dit *ce que* le rôle a le
droit de faire, la portée dit *sur quelles données*.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import unique

from coiflink_api.domain.enums import Role, _StrEnum


@unique
class Permission(_StrEnum):
    """Verbes métier autorisables, dérivés du PRD §4.1.

    Nommage : `<RESSOURCE>_<ACTION>`. Le suffixe précise la **portée attendue**
    quand elle discrimine le droit (`_OWN` : ses propres données ; `_ANY` : toutes
    celles de la plateforme ; `_ASSIGNED` : celles qui lui sont assignées ;
    `_SALON` : celles du salon de son périmètre).
    """

    # Salons (PRD §4.1 — gérant : créer/modifier son salon ; admin : superviser).
    SALON_CREATE = "SALON_CREATE"
    SALON_UPDATE = "SALON_UPDATE"
    SALON_READ_OWN = "SALON_READ_OWN"
    SALON_READ_ANY = "SALON_READ_ANY"
    SALON_SET_STATUS = "SALON_SET_STATUS"

    # Prestations.
    SERVICE_MANAGE = "SERVICE_MANAGE"
    SERVICE_READ = "SERVICE_READ"

    # Rendez-vous.
    APPOINTMENT_BOOK = "APPOINTMENT_BOOK"
    APPOINTMENT_READ_OWN = "APPOINTMENT_READ_OWN"
    APPOINTMENT_READ_ASSIGNED = "APPOINTMENT_READ_ASSIGNED"
    APPOINTMENT_READ_SALON = "APPOINTMENT_READ_SALON"
    APPOINTMENT_MANAGE = "APPOINTMENT_MANAGE"
    APPOINTMENT_UPDATE_STATUS = "APPOINTMENT_UPDATE_STATUS"

    # Employés.
    EMPLOYEE_MANAGE = "EMPLOYEE_MANAGE"

    # Fiches clients.
    CUSTOMER_MANAGE = "CUSTOMER_MANAGE"

    # Caisse.
    PAYMENT_RECORD = "PAYMENT_RECORD"
    CASH_JOURNAL_READ = "CASH_JOURNAL_READ"

    # Statistiques.
    STATS_READ_SALON = "STATS_READ_SALON"
    STATS_READ_PLATFORM = "STATS_READ_PLATFORM"

    # Comptes utilisateurs (supervision plateforme).
    USER_MANAGE = "USER_MANAGE"


# Tableau du PRD §4.1, **exhaustif et fermé**. Toute évolution des droits passe
# par ce dictionnaire (et par les tests de matrice qui le figent), jamais par un
# contrôle ad hoc dans une route.
ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    # Client : consulte les salons et prestations, réserve/modifie/annule **ses**
    # rendez-vous, consulte **son** historique. Aucun droit de gestion.
    Role.CLIENT: frozenset(
        {
            Permission.SALON_READ_ANY,
            Permission.SERVICE_READ,
            Permission.APPOINTMENT_BOOK,
            Permission.APPOINTMENT_READ_OWN,
        }
    ),
    # Coiffeur : voit **son** planning et les RDV qui lui sont assignés, met à
    # jour leur statut (réalisé, absent, retard). Ni caisse ni employés.
    Role.HAIRDRESSER: frozenset(
        {
            Permission.SALON_READ_OWN,
            Permission.SERVICE_READ,
            Permission.APPOINTMENT_READ_ASSIGNED,
            Permission.APPOINTMENT_UPDATE_STATUS,
        }
    ),
    # Gérant : gestion complète de **son** salon (la portée est appliquée à part,
    # cf. `domain/access.py`) — salon, prestations, employés, RDV, fiches clients,
    # caisse, statistiques du salon.
    Role.MANAGER: frozenset(
        {
            Permission.SALON_CREATE,
            Permission.SALON_UPDATE,
            Permission.SALON_READ_OWN,
            Permission.SERVICE_MANAGE,
            Permission.SERVICE_READ,
            Permission.APPOINTMENT_MANAGE,
            Permission.APPOINTMENT_READ_SALON,
            Permission.APPOINTMENT_UPDATE_STATUS,
            Permission.EMPLOYEE_MANAGE,
            Permission.CUSTOMER_MANAGE,
            Permission.PAYMENT_RECORD,
            Permission.CASH_JOURNAL_READ,
            Permission.STATS_READ_SALON,
        }
    ),
    # Admin CoifLink : **supervision plateforme** (voir tous les salons, les
    # activer/désactiver, gérer les comptes, lire les KPI globaux). Il n'hérite
    # **pas** des droits d'exploitation d'un salon (caisse, prestations…) : la
    # supervision n'est pas l'exploitation.
    Role.ADMIN: frozenset(
        {
            Permission.SALON_READ_ANY,
            Permission.SALON_SET_STATUS,
            Permission.USER_MANAGE,
            Permission.STATS_READ_PLATFORM,
        }
    ),
}


def permissions_for(role: str) -> frozenset[Permission]:
    """Permissions du rôle donné ; `frozenset()` si le rôle est inconnu.

    Tolérant par construction : un `role` illisible (jeton forgé, rôle supprimé
    du domaine) ne lève pas — il n'ouvre simplement **aucun** droit.
    """

    try:
        known_role = Role(role)
    except ValueError:
        return frozenset()
    return ROLE_PERMISSIONS.get(known_role, frozenset())


__all__ = ["Permission", "ROLE_PERMISSIONS", "permissions_for"]
