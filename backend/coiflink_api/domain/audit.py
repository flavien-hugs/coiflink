"""Vocabulaire du **journal d'audit** §11.4 (domaine pur, US-2.3, #17).

Le domaine définit **ce qui est journalisable** — les actions traçables et la
forme d'une entrée — sans rien savoir de la façon dont c'est persisté (table SQL,
log structuré…). L'écriture est un port (`application/ports/audit_log.py`) ;
l'implémentation vit dans `adapters/outbound/persistence/audit_log_repository.py`.

#17 est la **première** issue dont un critère d'acceptation exige la journalisation
§11.4 : ce module établit le socle réutilisable par les actions §11.4 suivantes
(modification RDV, paiement, correction de caisse, désactivation salon). Ces
actions s'ajouteront à `AuditAction` au fil des issues, sans ré-architecturer.

Invariant de non-fuite (PRD §11.3/§11.4) : une `AuditEntry` est **neutre** — elle
ne porte **jamais** de secret (jeton, condensat) ni de PII (téléphone, adresse).
L'`actor_user_id` est un UUID **opaque** ; `metadata` ne contient que des noms de
champs modifiés et des valeurs non sensibles strictement utiles à la traçabilité.

**Lecture gérante** (page « Journal d'audit », réorganisation du tableau de bord) :
`AuditLogEntry` est la projection de **lecture** d'une ligne déjà persistée —
`actor_user_id` y est résolu en **nom d'affichage** (`users.full_name`, patron
#36/#43 : un nom n'est pas un secret, contrairement au reste de l'entrée) et
`action` est classé dans une des 7 **catégories fermées** (`AUDIT_CATEGORIES`)
pour un filtre lisible côté gérant, sans exposer `metadata` (toujours vide en
pratique, cf. commentaires de chaque action ci-dessous — aucune valeur ajoutée à
l'exposer). `AuditLogFilter`/`validate_audit_log_filter` bornent la lecture
(plage de dates, catégorie) — même patron que `domain/transaction.py`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import unique
from typing import Literal

from coiflink_api.domain.enums import _StrEnum
from coiflink_api.domain.errors import InvalidAuditLogFilter

# Type d'entité journalisée pour les prestations (extensible aux futures §11.4).
ENTITY_TYPE_SERVICE = "service"

# Type d'entité journalisée pour les salons (extensible aux futures §11.4).
ENTITY_TYPE_SALON = "salon"

# Type d'entité journalisée pour les fiches clients (§11.3 « accès sensibles »).
ENTITY_TYPE_CUSTOMER = "customer"

# Type d'entité journalisée pour les paiements (§11.4 « Paiement enregistré ») — #34.
ENTITY_TYPE_PAYMENT = "payment"

# Type d'entité journalisée pour le journal de caisse (§11.4 « Correction de caisse ») — #34.
ENTITY_TYPE_CASH_JOURNAL = "cash_journal"

# Type d'entité journalisée pour les campagnes/messages aux clients (§11.4) — #49.
ENTITY_TYPE_CAMPAIGN = "campaign"

# Type d'entité journalisée pour les coiffeuses (appartenance salon, §11.4) — #150.
ENTITY_TYPE_SALON_MEMBER = "salon_member"

# Type d'entité journalisée pour les bornes terminal (provisioning §11.4) — #155.
ENTITY_TYPE_TERMINAL_DEVICE = "terminal_device"

# Type d'entité journalisée pour les tickets de passage walk-in (§11.4) — #157.
ENTITY_TYPE_QUEUE_TICKET = "queue_ticket"


@unique
class AuditAction(_StrEnum):
    """Actions traçables du journal §11.4 (domaine **fermé**).

    Au MVP (#17), seules les mutations de **prestation** sont câblées. Les actions
    §11.4 futures (RDV, paiement, caisse, désactivation salon) viendront ici.
    """

    # Prestations (§11.4 « Modification prestation ») — #17.
    SERVICE_CREATED = "SERVICE_CREATED"
    SERVICE_UPDATED = "SERVICE_UPDATED"
    SERVICE_DEACTIVATED = "SERVICE_DEACTIVATED"
    SERVICE_REACTIVATED = "SERVICE_REACTIVATED"

    # Salon (§11.4 « Modification salon »).
    SALON_UPDATED = "SALON_UPDATED"

    # Fiche client — #28 (US-4.1). Journalisée au titre de §11.3 (« journalisation
    # des accès sensibles ») : créer une fiche est une **collecte de données
    # personnelles**. L'entrée reste **neutre** — `metadata` est vide : ni nom, ni
    # téléphone, ni genre, ni note n'entre au journal.
    CUSTOMER_CREATED = "CUSTOMER_CREATED"

    # Note client privée — #32 (US-4.5). Journalisée au titre de §11.3 (« accès
    # sensibles ») : la note peut contenir des données de santé (allergies). Comme
    # `CUSTOMER_CREATED`, l'entrée reste **neutre** — `metadata` est vide : ni le
    # contenu de la note, ni l'ancienne valeur n'entrent au journal.
    CUSTOMER_NOTE_UPDATED = "CUSTOMER_NOTE_UPDATED"

    # Fiche client — #144 (US-4.6). Modification des champs d'identité (nom,
    # téléphone, genre) d'une fiche existante, journalisée au titre de §11.4
    # (« Modification »). Contrairement à `CUSTOMER_CREATED`/`CUSTOMER_NOTE_UPDATED`
    # (`metadata` vide), l'entrée porte le **diff neutre** `{"changed": [...]}`
    # (patron `SALON_UPDATED`) : seuls les **noms** des champs modifiés — jamais une
    # **valeur** (ni ancien/nouveau nom, ni numéro, ni genre), ce serait de la PII
    # au journal (§11.3/§11.4).
    CUSTOMER_UPDATED = "CUSTOMER_UPDATED"

    # Paiement enregistré — #34 (US-5.3, §11.4 « Paiement enregistré »). Chaque
    # paiement validé porte son auteur (`recorded_by`) et son horodatage. L'entrée
    # reste **neutre** — `metadata` est vide : ni le montant, ni le mode, ni
    # l'identité du client n'entrent au journal d'audit (le détail financier vit
    # dans `payments`/`cash_journal`, accès borné par permission).
    PAYMENT_RECORDED = "PAYMENT_RECORDED"

    # Correction de caisse — #34 (US-5.3, §11.4 « Correction de caisse »). Une
    # correction crée une ligne d'ajustement (`ADJUSTMENT`) sans jamais supprimer le
    # paiement d'origine. Comme les autres actions caisse, l'entrée reste **neutre**
    # — `metadata` est vide : ni le delta, ni le motif de correction n'entrent au
    # journal d'audit.
    CASH_ADJUSTED = "CASH_ADJUSTED"

    # Campagne/message aux clients — #49 (US-7.5, §11.4). Une campagne est une
    # **action manuelle du gérant** (composer + diffuser un message à un segment) :
    # à ce titre elle mérite sa propre trace d'audit, contrairement aux
    # notifications de RDV (#45–#48, effets de bord d'événements déjà audités). Le
    # `metadata` reste **non-PII** : type + segment + effectif (entier) — **jamais**
    # le corps du message, **jamais** un téléphone ou un nom de client (§11.3).
    CAMPAIGN_CREATED = "CAMPAIGN_CREATED"

    # Coiffeuses (§11.4 « Gestion des employés ») — #150. `EMPLOYEE_CREATED`
    # complète #13 (jusqu'ici non journalisé) ; `EMPLOYEE_UPDATED` porte le diff
    # **neutre** (`{"changed": [...]}`, patron `CUSTOMER_UPDATED`) ; l'activation/
    # désactivation pilote `salon_members.status` (disponibilité aux affectations),
    # distinct d'une désactivation de **compte** (`users.status`, hors périmètre).
    EMPLOYEE_CREATED = "EMPLOYEE_CREATED"
    EMPLOYEE_UPDATED = "EMPLOYEE_UPDATED"
    EMPLOYEE_DEACTIVATED = "EMPLOYEE_DEACTIVATED"
    EMPLOYEE_REACTIVATED = "EMPLOYEE_REACTIVATED"

    # Borne terminal — provisioning §11.4 — #155 (US-8.1). Provisionner ou révoquer
    # une borne est un **acte sensible du gérant** (`TERMINAL_PROVISION`) : il crée /
    # suspend un compte de service durable, il mérite donc sa trace. L'entrée reste
    # **neutre** — `metadata` est vide : ni le secret, ni son condensat, ni le
    # libellé de la borne n'entrent au journal (§11.3/§11.4).
    TERMINAL_DEVICE_PROVISIONED = "TERMINAL_DEVICE_PROVISIONED"
    TERMINAL_DEVICE_REVOKED = "TERMINAL_DEVICE_REVOKED"

    # File d'attente walk-in — prise en charge §11.4 — #157 (US-8.3). Démarrer /
    # clôturer un ticket de passage sont des **actions manuelles** de la coiffeuse
    # ou du gérant (`QUEUE_TICKET_UPDATE_STATUS`). L'**émission** d'un ticket par
    # la borne (`JoinQueue`) n'est **pas**
    # journalisée (aucune action humaine de gestion, aucune PII propre au ticket).
    # Les entrées restent **neutres** — `metadata` est vide : ni prénom, ni
    # prestation, ni estimation d'attente n'entre au journal (§11.3/§11.4).
    QUEUE_TICKET_STARTED = "QUEUE_TICKET_STARTED"
    QUEUE_TICKET_COMPLETED = "QUEUE_TICKET_COMPLETED"

    # File d'attente walk-in — édition des prestations d'un ticket déjà émis
    # §11.4 — #161 (US-8.3). Modifier les prestations d'un ticket `waiting`/
    # `in_progress` est une **action manuelle** de la coiffeuse ou du gérant
    # (`QUEUE_TICKET_UPDATE_STATUS`, même acteur que démarrer/clôturer). L'entrée
    # reste **neutre** — `metadata` est vide : ni l'ancienne ni la nouvelle liste
    # de prestations n'entre au journal (§11.3/§11.4).
    QUEUE_TICKET_SERVICES_UPDATED = "QUEUE_TICKET_SERVICES_UPDATED"

    # File d'attente walk-in — annulation manuelle d'un ticket (no-show) §11.4.
    # Annuler un ticket `waiting`/`called` (client absent) est une **action
    # manuelle** de la coiffeuse ou du gérant (même acteur/permission que
    # démarrer/clôturer/éditer). L'entrée reste **neutre** — `metadata` est vide :
    # le motif d'annulation, potentiellement identifiant, n'entre **jamais** au
    # journal (§11.3/§11.4) ; il vit uniquement sur le ticket lui-même.
    QUEUE_TICKET_CANCELLED = "QUEUE_TICKET_CANCELLED"


@dataclass(frozen=True)
class AuditEntry:
    """Une ligne du journal §11.4 — neutre, sans PII ni secret.

    - `action`      : une valeur d'`AuditAction` (le *quoi*) ;
    - `actor_user_id` : le `Principal` authentifié (le *qui*), UUID opaque ;
    - `salon_id`    : la portée (le *où*), `None` si l'action n'est pas à portée salon ;
    - `entity_type` / `entity_id` : la ressource visée (p. ex. `"service"` + son id) ;
    - `metadata`    : contexte **neutre** (p. ex. `{"changed": ["price"]}`), jamais
      de secret ni de PII.
    """

    action: str
    actor_user_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    salon_id: uuid.UUID | None = None
    metadata: dict = field(default_factory=dict)


# Catégories **fermées** du journal d'audit — regroupement lisible des 21 valeurs
# d'`AuditAction` pour le filtre de la page gérante « Journal d'audit ». Un
# regroupement, jamais une nouvelle notion métier : chaque action garde son
# `AuditAction` d'origine, la catégorie n'est qu'une clé de lecture/filtre.
AuditCategory = Literal[
    "prestations",
    "salon",
    "clients",
    "paiements_caisse",
    "employes",
    "bornes",
    "file_attente",
]

AUDIT_CATEGORIES: tuple[AuditCategory, ...] = (
    "prestations",
    "salon",
    "clients",
    "paiements_caisse",
    "employes",
    "bornes",
    "file_attente",
)

# Table **exhaustive** action → catégorie (un test de matrice fige cette
# exhaustivité, miroir `test_domain_permissions.py`) : une action absente de cette
# table est une régression, jamais un défaut silencieux.
AUDIT_ACTION_CATEGORY: Mapping[str, AuditCategory] = {
    AuditAction.SERVICE_CREATED.value: "prestations",
    AuditAction.SERVICE_UPDATED.value: "prestations",
    AuditAction.SERVICE_DEACTIVATED.value: "prestations",
    AuditAction.SERVICE_REACTIVATED.value: "prestations",
    AuditAction.SALON_UPDATED.value: "salon",
    AuditAction.CUSTOMER_CREATED.value: "clients",
    AuditAction.CUSTOMER_NOTE_UPDATED.value: "clients",
    AuditAction.CUSTOMER_UPDATED.value: "clients",
    AuditAction.CAMPAIGN_CREATED.value: "clients",
    AuditAction.PAYMENT_RECORDED.value: "paiements_caisse",
    AuditAction.CASH_ADJUSTED.value: "paiements_caisse",
    AuditAction.EMPLOYEE_CREATED.value: "employes",
    AuditAction.EMPLOYEE_UPDATED.value: "employes",
    AuditAction.EMPLOYEE_DEACTIVATED.value: "employes",
    AuditAction.EMPLOYEE_REACTIVATED.value: "employes",
    AuditAction.TERMINAL_DEVICE_PROVISIONED.value: "bornes",
    AuditAction.TERMINAL_DEVICE_REVOKED.value: "bornes",
    AuditAction.QUEUE_TICKET_STARTED.value: "file_attente",
    AuditAction.QUEUE_TICKET_COMPLETED.value: "file_attente",
    AuditAction.QUEUE_TICKET_SERVICES_UPDATED.value: "file_attente",
    AuditAction.QUEUE_TICKET_CANCELLED.value: "file_attente",
}

# Actions d'une catégorie donnée — dérivé de `AUDIT_ACTION_CATEGORY`, sert le
# filtre `category` du dépôt (traduit en `WHERE action IN (...)`).
ACTIONS_BY_CATEGORY: Mapping[AuditCategory, tuple[str, ...]] = {
    category: tuple(
        action for action, cat in AUDIT_ACTION_CATEGORY.items() if cat == category
    )
    for category in AUDIT_CATEGORIES
}


@dataclass(frozen=True)
class AuditLogEntry:
    """Une ligne du journal d'audit **lue** pour la page gérante (projection de lecture).

    `actor_name` résout `actor_user_id → users.full_name` (nom d'affichage, pas un
    secret) ; `category` est dérivée d'`action` via `AUDIT_ACTION_CATEGORY`.
    `metadata` n'est **jamais** exposée ici (toujours vide en pratique par
    construction de `AuditEntry`, cf. docstrings de chaque `AuditAction`).
    """

    id: uuid.UUID
    action: str
    category: AuditCategory
    entity_type: str
    entity_id: uuid.UUID
    actor_name: str
    created_at: datetime.datetime


@dataclass(frozen=True)
class AuditLogFilter:
    """Critères **validés** de filtrage du journal d'audit — plage de dates + catégorie.

    Produit **uniquement** par `validate_audit_log_filter` : un `AuditLogFilter`
    en circulation est donc toujours cohérent (plage ordonnée, catégorie fermée).
    """

    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    category: AuditCategory | None = None


def validate_audit_log_filter(
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    category: str | None = None,
) -> AuditLogFilter:
    """Valide/normalise les critères de filtre du journal d'audit.

    Règles (toutes → `InvalidAuditLogFilter`, message métier **neutre**) :
    - **plage ordonnée** : `date_from ≤ date_to` ;
    - **catégorie** dans l'énumération fermée `AUDIT_CATEGORIES` ;
    - `None` (ou catégorie vide) = **pas de contrainte**.
    """

    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidAuditLogFilter("Filtre de journal d'audit invalide.")

    cleaned_category: AuditCategory | None = None
    if category is not None:
        stripped = category.strip()
        if stripped:
            if stripped not in AUDIT_CATEGORIES:
                raise InvalidAuditLogFilter("Filtre de journal d'audit invalide.")
            cleaned_category = stripped  # type: ignore[assignment]

    return AuditLogFilter(
        date_from=date_from, date_to=date_to, category=cleaned_category
    )


__all__ = [
    "ENTITY_TYPE_SERVICE",
    "ENTITY_TYPE_SALON",
    "ENTITY_TYPE_CUSTOMER",
    "ENTITY_TYPE_PAYMENT",
    "ENTITY_TYPE_CASH_JOURNAL",
    "ENTITY_TYPE_CAMPAIGN",
    "ENTITY_TYPE_SALON_MEMBER",
    "ENTITY_TYPE_TERMINAL_DEVICE",
    "ENTITY_TYPE_QUEUE_TICKET",
    "AuditAction",
    "AuditEntry",
    "AuditCategory",
    "AUDIT_CATEGORIES",
    "AUDIT_ACTION_CATEGORY",
    "ACTIONS_BY_CATEGORY",
    "AuditLogEntry",
    "AuditLogFilter",
    "validate_audit_log_filter",
]
