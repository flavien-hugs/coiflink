"""Port de persistance de la **supervision agrégée** des transactions (US-5.6, #37).

Le cas d'usage (`application/platform_transactions.py`) déclare ici son besoin :
agréger les transactions **par salon** sur toute la plateforme. L'implémentation
SQLAlchemy vit dans
`adapters/outbound/persistence/platform_transaction_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Port dédié (et non `PaymentRepository`/`CashJournalRepository`).** Les méthodes de
ces ports sont **inconditionnellement** salon-scopées (isolation §11.2) ; l'agrégat
plateforme groupe **sur tous les salons** — il ne leur appartient pas. Un port séparé
garde cette lecture inter-salons explicite et auditable.

**Lecture pure.** Aucune méthode d'écriture (`create`/`update`/`delete`) : la
supervision ne mute rien (§8.2).
"""

from __future__ import annotations

from typing import Protocol

from coiflink_api.domain.platform_transactions import (
    PlatformSummaryFilter,
    SalonTransactionSummary,
)

# Bornes de pagination de la supervision agrégée (US-5.6, #37 — garde de coût
# §12.1). Alignées sur les autres surfaces « caisse » (journal #34, historique #35,
# écarts #36 : 50/1/200) pour la cohérence des lectures financières.
PLATFORM_SUMMARY_LIMIT_DEFAULT = 50
PLATFORM_SUMMARY_LIMIT_MIN = 1
PLATFORM_SUMMARY_LIMIT_MAX = 200


class PlatformTransactionRepository(Protocol):
    """Contrat d'agrégation des transactions par salon (lecture seule, inter-salons)."""

    def summary_by_salon(
        self, *, filter: PlatformSummaryFilter, limit: int, offset: int
    ) -> tuple[SalonTransactionSummary, ...]:
        """Page d'agrégats **par salon** (US-5.6, #37) — lecture seule.

        Agrège `cash_journal` **`GROUP BY salon_id`** (jointure `salons` pour le nom),
        avec `payment_count = COUNT(*) FILTER (WHERE operation_type = 'PAYMENT')`,
        `adjustment_count = COUNT(*) FILTER (WHERE operation_type = 'ADJUSTMENT')` et
        `total_amount = SUM(amount)` (net signé). Les bornes de dates du `filter` sont
        appliquées **conditionnellement en SQL** sur `created_at`. Seuls les salons
        **ayant de l'activité** (au moins une ligne de journal sous le filtre)
        apparaissent. Tri **déterministe** `salon_name ASC, salon_id ASC`, bornes
        `limit`/`offset` en SQL (jamais en mémoire). **Aucune** PII de paiement,
        **aucune** écriture.
        """
        ...

    def count_salons(self, *, filter: PlatformSummaryFilter) -> int:
        """Nombre de salons **distincts** apparaissant sous le même filtre (pagination).

        Applique **exactement** les mêmes clauses que `summary_by_salon` (bornes de
        dates conditionnelles) pour un `total` cohérent avec la page.
        """
        ...


__all__ = [
    "PlatformTransactionRepository",
    "PLATFORM_SUMMARY_LIMIT_DEFAULT",
    "PLATFORM_SUMMARY_LIMIT_MIN",
    "PLATFORM_SUMMARY_LIMIT_MAX",
]
