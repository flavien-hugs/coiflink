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
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import unique

from coiflink_api.domain.enums import _StrEnum

# Type d'entité journalisée pour les prestations (extensible aux futures §11.4).
ENTITY_TYPE_SERVICE = "service"

# Type d'entité journalisée pour les salons (extensible aux futures §11.4).
ENTITY_TYPE_SALON = "salon"

# Type d'entité journalisée pour les rendez-vous (§11.4 « Modification rendez-vous »).
ENTITY_TYPE_APPOINTMENT = "appointment"

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

# Type d'entité journalisée pour les bornes kiosque (provisioning §11.4) — #155.
ENTITY_TYPE_KIOSK_DEVICE = "kiosk_device"

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

    # Rendez-vous (§11.4 « Modification rendez-vous ») — #23 (modification client).
    APPOINTMENT_UPDATED = "APPOINTMENT_UPDATED"

    # Rendez-vous (§11.4 « Annulation rendez-vous ») — #24 (annulation client).
    APPOINTMENT_CANCELLED = "APPOINTMENT_CANCELLED"

    # Rendez-vous (§11.4 « Cycle de statuts ») — #25 (gestion gérant) : changement
    # de statut (confirmation/refus/réalisé/absent) et (dés)assignation d'un coiffeur.
    APPOINTMENT_STATUS_CHANGED = "APPOINTMENT_STATUS_CHANGED"
    APPOINTMENT_HAIRDRESSER_ASSIGNED = "APPOINTMENT_HAIRDRESSER_ASSIGNED"

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

    # File d'attente — pointage réel (§11.4) — #150. Arrivée/début de prestation
    # sont des actions manuelles du gérant sur un RDV **existant**, distinctes du
    # cycle `APPOINTMENT_STATUS_CHANGED` (#25) : elles posent `arrived_at`/
    # `started_at`, jamais `status`.
    APPOINTMENT_ARRIVED = "APPOINTMENT_ARRIVED"
    APPOINTMENT_STARTED = "APPOINTMENT_STARTED"

    # Borne kiosque — provisioning §11.4 — #155 (US-8.1). Provisionner ou révoquer
    # une borne est un **acte sensible du gérant** (`KIOSK_PROVISION`) : il crée /
    # suspend un compte de service durable, il mérite donc sa trace. L'entrée reste
    # **neutre** — `metadata` est vide : ni le secret, ni son condensat, ni le
    # libellé de la borne n'entrent au journal (§11.3/§11.4).
    KIOSK_DEVICE_PROVISIONED = "KIOSK_DEVICE_PROVISIONED"
    KIOSK_DEVICE_REVOKED = "KIOSK_DEVICE_REVOKED"

    # File d'attente walk-in — prise en charge §11.4 — #157 (US-8.3). Démarrer /
    # clôturer un ticket de passage sont des **actions manuelles** de la coiffeuse
    # ou du gérant (`APPOINTMENT_UPDATE_STATUS`), miroir d'`APPOINTMENT_STARTED`.
    # L'**émission** d'un ticket par la borne (`JoinQueue`) n'est **pas**
    # journalisée (aucune action humaine de gestion, aucune PII propre au ticket).
    # Les entrées restent **neutres** — `metadata` est vide : ni prénom, ni
    # prestation, ni estimation d'attente n'entre au journal (§11.3/§11.4).
    QUEUE_TICKET_STARTED = "QUEUE_TICKET_STARTED"
    QUEUE_TICKET_COMPLETED = "QUEUE_TICKET_COMPLETED"


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


__all__ = [
    "ENTITY_TYPE_SERVICE",
    "ENTITY_TYPE_SALON",
    "ENTITY_TYPE_APPOINTMENT",
    "ENTITY_TYPE_CUSTOMER",
    "ENTITY_TYPE_PAYMENT",
    "ENTITY_TYPE_CASH_JOURNAL",
    "ENTITY_TYPE_CAMPAIGN",
    "ENTITY_TYPE_SALON_MEMBER",
    "ENTITY_TYPE_KIOSK_DEVICE",
    "ENTITY_TYPE_QUEUE_TICKET",
    "AuditAction",
    "AuditEntry",
]
