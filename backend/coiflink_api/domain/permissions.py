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

    # File d'attente walk-in (US-8.3, #157, pivot walk-in exclusif #148) —
    # `QUEUE_TICKET_UPDATE_STATUS` : démarrer (assigner une coiffeuse + passer
    # `in_progress`) ou clôturer (`done`) un ticket du salon. `QUEUE_TICKET_READ_SALON` :
    # lister les tickets du salon pour un jour (file gérant, future page « Mes
    # tickets » coiffeur). Toutes deux attribuées au `MANAGER` (exploitation de sa
    # file d'attente) et au `HAIRDRESSER` (ses propres prises en charge) — seul
    # modèle de rendez-vous du produit depuis le pivot walk-in exclusif (#148), qui
    # a fait disparaître les anciennes permissions `APPOINTMENT_*`.
    QUEUE_TICKET_UPDATE_STATUS = "QUEUE_TICKET_UPDATE_STATUS"
    QUEUE_TICKET_READ_SALON = "QUEUE_TICKET_READ_SALON"

    # Employés.
    EMPLOYEE_MANAGE = "EMPLOYEE_MANAGE"

    # Fiches clients.
    CUSTOMER_MANAGE = "CUSTOMER_MANAGE"

    # Borne terminal (US-8.1, #155) — permissions **minimales et dédiées** du rôle
    # `TERMINAL`, distinctes de `CUSTOMER_MANAGE` (moindre privilège d'un terminal
    # public partagé, ADR-0041) :
    # - `CUSTOMER_LOOKUP_TERMINAL` : rechercher une fiche `CustomerProfile` par
    #   téléphone, restreinte au salon de la borne, réponse minimale (consommée par #156) ;
    # - `CUSTOMER_CREATE_WALKIN` : créer une fiche walk-in (nom/prénom/téléphone)
    #   **sans** compte ni mot de passe (consommée par #156) ;
    # - `QUEUE_TICKET_CREATE` : créer un ticket de passage walk-in (consommée par #157) ;
    # - `TERMINAL_PROVISION` : provisionner/lister/révoquer les bornes de **son** salon
    #   (consommée par #155, **MANAGER** uniquement).
    CUSTOMER_LOOKUP_TERMINAL = "CUSTOMER_LOOKUP_TERMINAL"
    CUSTOMER_CREATE_WALKIN = "CUSTOMER_CREATE_WALKIN"
    QUEUE_TICKET_CREATE = "QUEUE_TICKET_CREATE"
    TERMINAL_PROVISION = "TERMINAL_PROVISION"

    # Caisse.
    PAYMENT_RECORD = "PAYMENT_RECORD"
    CASH_JOURNAL_READ = "CASH_JOURNAL_READ"
    # Reçu numérique : le client lit **ses** reçus de paiement (US-5.5, #38).
    PAYMENT_READ_OWN = "PAYMENT_READ_OWN"

    # Statistiques.
    STATS_READ_SALON = "STATS_READ_SALON"
    STATS_READ_PLATFORM = "STATS_READ_PLATFORM"

    # Journal d'audit (§11.4) — page gérante « Journal d'audit » (réorganisation du
    # tableau de bord). Distinct de `STATS_READ_SALON` (chiffres d'activité) et de
    # `CASH_JOURNAL_READ` (données financières) : c'est un outil de **preuve**
    # (qui a fait quoi), pas un indicateur de pilotage — MANAGER uniquement, comme
    # tout autre droit de lecture salon-scopé de ce tableau.
    AUDIT_LOG_READ = "AUDIT_LOG_READ"

    # Comptes utilisateurs (supervision plateforme).
    USER_MANAGE = "USER_MANAGE"


# Tableau du PRD §4.1, **exhaustif et fermé**. Toute évolution des droits passe
# par ce dictionnaire (et par les tests de matrice qui le figent), jamais par un
# contrôle ad hoc dans une route.
ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    # Client : consulte les salons et prestations, consulte **son** historique et
    # **ses** reçus de paiement (#38). Aucun droit de gestion.
    Role.CLIENT: frozenset(
        {
            Permission.SALON_READ_ANY,
            Permission.SERVICE_READ,
            Permission.PAYMENT_READ_OWN,
        }
    ),
    # Coiffeur : voit **son** planning. Démarre/termine ses propres tickets de la
    # file d'attente walk-in (#148, #157). Ni caisse ni employés.
    Role.HAIRDRESSER: frozenset(
        {
            Permission.SALON_READ_OWN,
            Permission.SERVICE_READ,
            Permission.QUEUE_TICKET_UPDATE_STATUS,
            Permission.QUEUE_TICKET_READ_SALON,
        }
    ),
    # Gérant : gestion complète de **son** salon (la portée est appliquée à part,
    # cf. `domain/access.py`) — salon, prestations, employés, file d'attente
    # walk-in, fiches clients, caisse, statistiques du salon.
    Role.MANAGER: frozenset(
        {
            Permission.SALON_CREATE,
            Permission.SALON_UPDATE,
            Permission.SALON_READ_OWN,
            Permission.SERVICE_MANAGE,
            Permission.SERVICE_READ,
            Permission.QUEUE_TICKET_UPDATE_STATUS,
            Permission.QUEUE_TICKET_READ_SALON,
            Permission.EMPLOYEE_MANAGE,
            Permission.CUSTOMER_MANAGE,
            Permission.PAYMENT_RECORD,
            Permission.CASH_JOURNAL_READ,
            Permission.STATS_READ_SALON,
            # Provisioning des bornes terminal de son salon (US-8.1, #155) — seul
            # ajout au gérant : aucun retrait, aucun élargissement d'un droit existant.
            Permission.TERMINAL_PROVISION,
            # Journal d'audit de son salon — page « Journal d'audit ».
            Permission.AUDIT_LOG_READ,
        }
    ),
    # Borne terminal (US-8.1, #155) : compte de service d'un **terminal public
    # partagé**, scopé à un salon. Détient **exactement** ces trois permissions
    # dédiées — ni `CUSTOMER_MANAGE` (fiches complètes, notes privées, caisse), ni
    # aucune lecture gérant. C'est le cœur du critère d'acceptation négatif de
    # l'issue (ADR-0041).
    Role.TERMINAL: frozenset(
        {
            Permission.CUSTOMER_LOOKUP_TERMINAL,
            Permission.CUSTOMER_CREATE_WALKIN,
            Permission.QUEUE_TICKET_CREATE,
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
