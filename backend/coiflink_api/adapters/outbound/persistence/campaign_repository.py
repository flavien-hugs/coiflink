"""Adapter sortant : persistance des **campagnes/messages aux clients** (SQLAlchemy, #49).

Implémente le port `CampaignRepository` sur une `Session` SQLAlchemy 2.0 et le
modèle ORM `models.Campaign` (table `campaigns`, migration `0009`). Seul cet adapter
connaît SQLAlchemy ; il mappe les entités de domaine ↔ modèles ORM. Gabarit direct :
`SqlCustomerRepository`.

**Atomicité** : l'écriture partage la **même `Session`** que l'entrée d'audit
(injectée via `get_session`) et est `flush`ée **sans commit** — campagne et audit
sont committés (ou rollbackés) **ensemble** : pas de campagne « fantôme » sur une
erreur, pas de campagne sans sa trace (§11.4).

**Non-remise & non-fuite** (ADR-0006, §11.3) : cet adapter **n'achemine rien** (aucun
appel SMS/FCM) et ne **journalise jamais** le message ni un destinataire. Il recopie
tel quel le contenu **déjà validé et neutre** de `CampaignToCreate` (`status` reste
`PENDING`, `sent_at` `NULL`).

**Isolation §11.2 au niveau du dépôt** : la lecture filtre **inconditionnellement**
sur `salon_id` — une campagne d'un autre salon est indiscernable d'une campagne
inexistante (défense en profondeur derrière `require_salon_scope`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.campaign import Campaign, CampaignToCreate


class SqlCampaignRepository:
    """Dépôt de campagnes adossé à une `Session` SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, campaign: CampaignToCreate) -> Campaign:
        """Insère la campagne (`status = PENDING`, `sent_at = NULL` — non remise)."""

        row = models.Campaign(
            salon_id=campaign.salon_id,
            created_by=campaign.created_by,
            type=campaign.type,
            segment=campaign.segment,
            channel=campaign.channel,
            title=campaign.title,
            message=campaign.message,
            recipient_count=campaign.recipient_count,
            status=campaign.status,
        )
        self._session.add(row)
        # `flush` déclenche l'INSERT (et les contraintes) sans committer.
        self._session.flush()
        # Recharge les valeurs générées côté serveur (id, status, created_at).
        self._session.refresh(row)
        return _to_domain(row)

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Campaign, ...]:
        """Page des campagnes du salon, les plus récentes d'abord (SQL, §11.2)."""

        stmt = (
            select(models.Campaign)
            .where(models.Campaign.salon_id == salon_id)
            .order_by(
                models.Campaign.created_at.desc(),
                models.Campaign.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(_to_domain(row) for row in self._session.scalars(stmt).all())

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        """Nombre total de campagnes du salon (pagination cohérente avec la page)."""

        stmt = (
            select(func.count())
            .select_from(models.Campaign)
            .where(models.Campaign.salon_id == salon_id)
        )
        return int(self._session.scalar(stmt) or 0)


def _to_domain(row: models.Campaign) -> Campaign:
    return Campaign(
        id=row.id,
        salon_id=row.salon_id,
        created_by=row.created_by,
        type=row.type,
        segment=row.segment,
        channel=row.channel,
        title=row.title,
        message=row.message,
        recipient_count=row.recipient_count,
        status=row.status,
        sent_at=row.sent_at,
        created_at=row.created_at,
    )


__all__ = ["SqlCampaignRepository"]
