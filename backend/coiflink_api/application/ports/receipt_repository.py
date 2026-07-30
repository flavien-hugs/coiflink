"""Port de lecture des **reçus numériques** (`Protocol`, US-5.5, #38).

Le cas d'usage (`application/receipts.py`) déclare ici ses besoins ;
l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/receipt_repository.py`. Conformément à l'hexagonal
(ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Port dédié (lecture seule).** Le reçu est une **projection en lecture** dérivée
de `payments` × `appointment_services`/`services` × `salons` : ce port est séparé
de `PaymentRepository` (écriture + historique gérant #35) pour garder chacun
focalisé (voir spec *Open Questions* §2). Il n'expose **aucune** écriture.

**Appartenance stricte (§11.2), imposée au niveau du dépôt.** Toutes les méthodes
prennent `client_id` et filtrent **inconditionnellement** `payments.client_id =
client_id`. Un paiement d'un autre client (ou sans `client_id`) est **indiscernable
d'un paiement inexistant** — impossible de le lire même si l'`id` est deviné
(non-oracle §11.3).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from coiflink_api.domain.receipt import Receipt

# Bornes de pagination de la liste des reçus (US-5.5, #38 — garde de coût §12.1).
# `20` par défaut (page cliente compacte), plafond `100`.
RECEIPTS_LIMIT_DEFAULT = 20
RECEIPTS_LIMIT_MIN = 1
RECEIPTS_LIMIT_MAX = 100


class ReceiptRepository(Protocol):
    """Contrat de lecture des reçus d'un **client** (appartenance forcée, jamais d'écriture)."""

    def list_receipts_for_client(
        self,
        client_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Receipt, ...]:
        """Page des reçus du client, **du plus récent au plus ancien** — lecture seule.

        Applique **inconditionnellement** le filtre `payments.client_id = client_id`
        (appartenance §11.2 : jamais le reçu d'un tiers, quel que soit l'appelant),
        résout `salon_id → salons.name` (identité **publique**, §11.3) et compose les
        **lignes** de prestation (RDV → `appointment_services.price_at_booking` figé ;
        prestation seule → `services.price`). Tri déterministe `created_at DESC,
        id DESC`, bornes `limit`/`offset` appliquées **en SQL**. **Aucune** écriture.
        """
        ...

    def count_receipts_for_client(self, client_id: uuid.UUID) -> int:
        """Nombre total de reçus du client (pagination), même filtre d'appartenance."""
        ...

    def get_receipt_for_client(
        self, client_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Receipt | None:
        """Retourne le reçu `(client_id, payment_id)` ou `None` (non-oracle §11.3).

        `None` que le paiement **n'existe pas** **ou** n'appartienne pas au client —
        les deux cas sont **indiscernables** (l'adapter les traduit tous deux en `404`
        neutre). Le filtre porte sur `client_id` **et** `id`. **Aucune** écriture.
        """
        ...


__all__ = [
    "ReceiptRepository",
    "RECEIPTS_LIMIT_DEFAULT",
    "RECEIPTS_LIMIT_MIN",
    "RECEIPTS_LIMIT_MAX",
]
