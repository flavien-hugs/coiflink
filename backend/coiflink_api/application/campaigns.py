"""Cas d'usage : **campagnes/messages aux clients d'un salon** (US-7.5, #49).

Tranche applicative hexagonale calquée sur #28 : ces cas d'usage ne dépendent que
de **ports** (`CampaignRepository`, `CustomerRepository`, `AuditLog`) — aucune
dépendance FastAPI/SQLAlchemy. Ils orchestrent le domaine (`domain/campaign.py`,
`domain/notification.py`, `domain/audit.py`) et laissent l'adapter entrant traduire
les erreurs en HTTP.

Invariants structurants (miroir de `CreateCustomer`) :

- **`salon_id` imposé par la portée** : le salon vient toujours de la portée validée
  (`require_salon_scope`), passé en argument d'`execute` ; il n'est **jamais** lu du
  corps de requête (garde-fou anti-élévation). L'**auteur** (`created_by`) est le
  `Principal` (`actor_user_id`), jamais lu du corps.
- **Segment et effectif salon-scopés** : l'effectif (`recipient_count`) est un `COUNT`
  salon-scopé sur `customer_profiles` (#28), restreint au segment **et** aux fiches
  **joignables** (SMS → `phone IS NOT NULL`). **Un seul** `COUNT` — jamais une
  matérialisation par destinataire (garde de coût §12.1).
- **Émission/trace atomique (§11.4)** : la persistance de la campagne (`PENDING`) et
  l'entrée d'audit `CAMPAIGN_CREATED` passent par la **même `Session`** — commit/
  rollback conjoint (pas de campagne « fantôme », pas de campagne sans trace).
- **Aucune PII / aucun contenu journalisé** (§11.3, ADR-0006) : le `metadata` d'audit
  ne porte que type + segment + effectif (entier) — **jamais** le message, **jamais**
  un téléphone ou un nom. La **remise réelle** (fan-out SMS) reste différée M5+ : rien
  n'est envoyé, `sent_at` reste `NULL`.

Validation **avant** toute écriture : un `type`/`segment`/`title`/`message` invalide
lève (aucun `COUNT`, aucune campagne, aucun audit).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.campaign_repository import CampaignRepository
from coiflink_api.application.ports.customer_repository import CustomerRepository
from coiflink_api.domain.audit import ENTITY_TYPE_CAMPAIGN, AuditAction, AuditEntry
from coiflink_api.domain.campaign import (
    Campaign,
    build_campaign,
    normalize_campaign_segment,
    normalize_campaign_type,
    segment_to_customer_filter,
    validate_campaign_message,
    validate_campaign_title,
)
from coiflink_api.domain.notification import (
    ChannelAvailability,
    resolve_notification_channel,
)


@dataclass(frozen=True)
class CampaignCommand:
    """Champs saisissables d'une campagne (US-7.5 : type, segment, titre, message).

    Ni `salon_id` (portée), ni `created_by` (principal), ni `status`/`channel`/
    `recipient_count` (imposés/résolus serveur) : le corps de requête ne porte que le
    contenu **composé par le gérant** et le ciblage.
    """

    type: str
    segment: str
    title: str
    message: str


class CreateCampaign:
    """Crée (émet/trace) une campagne pour le salon de la portée et journalise (§11.4)."""

    def __init__(
        self,
        campaign_repository: CampaignRepository,
        customer_repository: CustomerRepository,
        audit_log: AuditLog,
    ) -> None:
        self._campaigns = campaign_repository
        self._customers = customer_repository
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        command: CampaignCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> Campaign:
        """Valide → résout le canal (SMS) et l'effectif → persiste `PENDING` → journalise.

        Toutes les écritures partagent la **même `Session`** que l'audit : une
        validation échouée ne persiste **rien** ; une erreur du dépôt rollback la
        campagne **et** l'audit conjointement. La résolution de l'effectif est un
        `COUNT` salon-scopé (segment + joignabilité SMS) — jamais un fan-out.
        """

        # 1. Validation domaine AVANT toute lecture/écriture (ordre stable pour des
        #    messages d'erreur déterministes ; aucun `COUNT` si un champ est invalide).
        type_ = normalize_campaign_type(command.type)
        segment = normalize_campaign_segment(command.segment)
        title = validate_campaign_title(command.title)
        message = validate_campaign_message(command.message)

        # 2. Canal : SMS au MVP (population walk-in #28, sans jeton push) — un seul
        #    point de résolution de canal, réutilisé des notifications de RDV.
        channel = resolve_notification_channel(
            ChannelAvailability(has_push_token=False, has_phone=True)
        )

        # 3. Effectif : COUNT salon-scopé du segment (fiches joignables uniquement).
        recipient_count = self._customers.count_for_salon(
            salon_id, filter=segment_to_customer_filter(segment)
        )

        # 4. Persiste la campagne (`status = PENDING`, `created_by = actor_user_id`).
        campaign = self._campaigns.create(
            build_campaign(
                salon_id=salon_id,
                created_by=actor_user_id,
                type=type_,
                segment=segment,
                channel=channel,
                title=title,
                message=message,
                recipient_count=recipient_count,
            )
        )

        # 5. Journalise l'action manuelle du gérant (§11.4) — `metadata` **non-PII** :
        #    type + segment + effectif, jamais le message ni un destinataire.
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.CAMPAIGN_CREATED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_CAMPAIGN,
                entity_id=campaign.id,
                metadata={
                    "type": campaign.type,
                    "segment": campaign.segment,
                    "recipient_count": campaign.recipient_count,
                },
            )
        )
        return campaign


class ListSalonCampaigns:
    """Liste paginée des campagnes d'un salon (lecture — pas d'audit)."""

    def __init__(self, repository: CampaignRepository) -> None:
        self._repository = repository

    def execute(
        self,
        salon_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[tuple[Campaign, ...], int]:
        """Retourne `(page, total)` — les plus récentes d'abord.

        Le total accompagne la page pour permettre une pagination correcte côté
        interface sans seconde requête.
        """

        page = self._repository.list_for_salon(salon_id, limit=limit, offset=offset)
        total = self._repository.count_for_salon(salon_id)
        return page, total


__all__ = [
    "CampaignCommand",
    "CreateCampaign",
    "ListSalonCampaigns",
]
