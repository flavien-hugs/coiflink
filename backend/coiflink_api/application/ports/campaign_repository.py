"""Port de persistance des **campagnes/messages aux clients** (`Protocol`, US-7.5, #49).

Le cas d'usage `application/campaigns.py` déclare ici ses besoins d'écriture et de
lecture ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/campaign_repository.py`. Conformément à l'hexagonal
(ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM. Gabarit
direct : `application/ports/customer_repository.py`.

**Isolation §11.2 au niveau du dépôt** : la lecture prend `salon_id` et filtre
**inconditionnellement** dessus — une campagne d'un autre salon est indiscernable
d'une campagne inexistante. C'est la défense en profondeur derrière
`require_salon_scope`.

**Émission/trace, pas remise** (ADR-0006, §11.3) : `create` **persiste** la campagne
(`flush`, sans `commit` : l'unité de travail est pilotée par `get_session`, pour un
commit atomique avec l'audit) ; elle n'achemine **rien** et ne journalise **jamais**
le message ni un destinataire. Aucune méthode ne matérialise une ligne par
destinataire (fan-out différé au worker M5+).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.campaign import Campaign, CampaignToCreate

# Bornes de pagination de la liste (garde de coût §12.1 — patron fiches #28).
CAMPAIGN_LIMIT_DEFAULT = 50
CAMPAIGN_LIMIT_MIN = 1
CAMPAIGN_LIMIT_MAX = 200


class CampaignRepository(Protocol):
    """Contrat de persistance des campagnes d'un salon."""

    def create(self, campaign: CampaignToCreate) -> Campaign:
        """Persiste et retourne la campagne créée (`status = PENDING`, `sent_at = NULL`).

        `flush` **sans commit** : la ligne est matérialisée (contraintes FK/CHECK
        vérifiées) mais committée **avec** l'entrée d'audit par `get_session`
        (atomicité §11.4). Ne journalise **jamais** le message ni un destinataire
        (ADR-0006).
        """
        ...

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Campaign, ...]:
        """Page des campagnes du salon, les plus récentes d'abord.

        Filtre `salon_id` **inconditionnel** (isolation §11.2), tri
        `created_at DESC, id DESC`, bornes en SQL (garde de coût §12.1).
        """
        ...

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        """Nombre total de campagnes du salon (pagination cohérente avec la page)."""
        ...


__all__ = [
    "CampaignRepository",
    "CAMPAIGN_LIMIT_DEFAULT",
    "CAMPAIGN_LIMIT_MIN",
    "CAMPAIGN_LIMIT_MAX",
]
