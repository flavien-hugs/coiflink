"""Port de persistance des **KPI globaux** de la plateforme (US-6.6, #44).

Le cas d'usage (`application/platform_kpis.py`) déclare ici son besoin : calculer,
**en base**, un instantané de compteurs et de totaux à l'échelle de la plateforme
entière. L'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/platform_kpi_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Port dédié (et non `PaymentRepository`/`CashJournalRepository`/… salon-scopés).**
Les méthodes de ces ports sont **inconditionnellement** salon-scopées (isolation
§11.2) ; les compteurs/sommes de #44 portent sur **toutes** les entités de la
plateforme (tous salons, tous clients, tous tickets walk-in) — ils ne leur
appartiennent pas. Un port séparé garde cette lecture inter-entités explicite et
auditable (raison identique au port dédié de #37).

**Instantané unique, pas de pagination.** La lecture renvoie une poignée de scalaires
globaux (aucune ligne matérialisée) : pas de `limit`/`offset`, pas de constante
`LIMIT_*`.

**Lecture pure.** Aucune méthode d'écriture : consulter les KPI ne mute rien (§8.2).
"""

from __future__ import annotations

import datetime
from typing import Protocol

from coiflink_api.domain.platform_kpis import PlatformKpiCounts


class PlatformKpiRepository(Protocol):
    """Contrat de calcul des KPI globaux de la plateforme (lecture seule, inter-entités)."""

    def compute_snapshot(
        self,
        *,
        month_from: datetime.date,
        month_to: datetime.date,
        revenue_from_utc: datetime.datetime,
        revenue_to_utc: datetime.datetime,
    ) -> PlatformKpiCounts:
        """Calcule les scalaires globaux **en SQL** (US-6.6, #44) — lecture seule.

        Renvoie un `PlatformKpiCounts` portant :

        - `salons_total = COUNT(*)` sur `salons` ; `salons_active = COUNT(*) WHERE
          status = 'ACTIVE'` ;
        - `clients_total = COUNT(*)` sur `users` `WHERE role = 'CLIENT'` (exclut
          `HAIRDRESSER`/`MANAGER`/`ADMIN`) ;
        - `tickets_total = COUNT(*)` sur `queue_tickets` (**tous statuts**, volume
          émis) ; `tickets_this_month = COUNT(*) WHERE issued_date BETWEEN month_from
          AND month_to` (comparaison **date** — `issued_date` est déjà un jour civil
          `Africa/Abidjan`, **sans** conversion de fuseau) ;
        - `revenue_total = SUM(amount)` (net signé) sur **toute** la table
          `cash_journal` ; `revenue_this_month = SUM(amount) WHERE created_at BETWEEN
          revenue_from_utc AND revenue_to_utc` (bornes du mois civil **converties en
          UTC** en amont, car `created_at` est timezone-aware).

        Toute l'agrégation est **en SQL** (`COUNT`/`SUM`, jamais en mémoire — garde de
        coût §12.1). **Aucune** écriture, **aucune** PII : le résultat ne porte que des
        scalaires globaux.
        """
        ...


__all__ = ["PlatformKpiRepository"]
