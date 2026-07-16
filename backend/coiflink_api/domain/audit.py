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
    "AuditAction",
    "AuditEntry",
]
