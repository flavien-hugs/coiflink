"""Adapter sortant : **KPI globaux** de la plateforme (SQLAlchemy, US-6.6, #44).

Implémente le port `PlatformKpiRepository` sur une `Session` SQLAlchemy 2.0 et les
modèles ORM `models.Salon` / `models.User` / `models.Appointment` /
`models.CashJournal`. Seul cet adapter connaît SQLAlchemy ; il calcule **en base**
une poignée de scalaires globaux et les projette en `PlatformKpiCounts` (domaine pur,
sans PII).

**Tout en SQL (garde de coût §12.1).** Chaque KPI est un `SELECT` scalaire
**indépendant** (lisible, chacun couvert par un index existant) : `COUNT` pour les
compteurs, `SUM` net signé pour le revenu. **Rien n'est rapatrié ni compté en
mémoire.** Aucune écriture, aucun `flush`, aucun commit.

**Source de vérité du revenu : le journal de caisse (#34).** `revenue_total` /
`revenue_this_month` = **somme signée** des `cash_journal.amount` (`PAYMENT` positif,
`ADJUSTMENT` signé), sur **tous** les salons : un paiement corrigé fait **baisser** le
net (parité #37/#40). C'est le flux net encaissé par les salons, **pas** un revenu de
facturation SaaS (qui n'existe pas — cf. `domain/platform_kpis.py`, ADR-0032).

**Interprétation temporelle.** Les rendez-vous du mois se comparent **directement** à
`appointment_date` (déjà un jour civil `Africa/Abidjan`) sur les bornes de
`month_bounds`. Le revenu du mois se compare à `created_at` (timezone-aware) sur les
bornes de mois **déjà converties en UTC** par le cas d'usage.

**Non-PII (§11.3).** La projection ne sélectionne **que** des agrégats globaux —
**aucune** identité d'entité (ni `salon_id`, ni `client_id`, ni `owner_id`, ni ligne
individuelle).

**Index.** `ix_salons_status` couvre `salons_active` ; `ix_appointments_salon_id
(salon_id, appointment_date)` couvre partiellement le filtre de mois ;
`ix_cash_journal_salon_id (salon_id, created_at)` couvre le filtre de revenu. Les
`COUNT(*)` globaux non filtrés font un balayage borné acceptable au MVP (volumétrie
pilote, PRD §14) — aucun nouvel index requis.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence import models
from coiflink_api.domain.enums import Role, SalonStatus
from coiflink_api.domain.platform_kpis import PlatformKpiCounts

# Précision de quantification des montants agrégés : le centime (miroir de
# `NUMERIC(12,2)`), pour rester en `Decimal` (jamais un flottant) — parité #37.
_AMOUNT_QUANTUM = decimal.Decimal("0.01")

# Valeurs textuelles filtrées (miroir des `CHECK` du schéma, source de vérité domaine).
_CLIENT_ROLE = Role.CLIENT.value
_SALON_ACTIVE = SalonStatus.ACTIVE.value


class SqlPlatformKpiRepository:
    """Dépôt de calcul des KPI globaux plateforme adossé à une `Session` (lecture seule)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def compute_snapshot(
        self,
        *,
        month_from: datetime.date,
        month_to: datetime.date,
        revenue_from_utc: datetime.datetime,
        revenue_to_utc: datetime.datetime,
    ) -> PlatformKpiCounts:
        """Calcule les scalaires globaux **en SQL** (US-6.6, #44) — lecture seule.

        Sept `SELECT` scalaires indépendants (compteurs `COUNT`, sommes `SUM` nettes) ;
        chacun est borné et couvert par un index existant. Le revenu est quantifié au
        centime en `Decimal`. Aucune écriture, aucune PII.
        """

        return PlatformKpiCounts(
            salons_total=self._count(select(func.count()).select_from(models.Salon)),
            salons_active=self._count(
                select(func.count())
                .select_from(models.Salon)
                .where(models.Salon.status == _SALON_ACTIVE)
            ),
            clients_total=self._count(
                select(func.count())
                .select_from(models.User)
                .where(models.User.role == _CLIENT_ROLE)
            ),
            appointments_total=self._count(
                select(func.count()).select_from(models.Appointment)
            ),
            appointments_this_month=self._count(
                select(func.count())
                .select_from(models.Appointment)
                .where(
                    models.Appointment.appointment_date >= month_from,
                    models.Appointment.appointment_date <= month_to,
                )
            ),
            revenue_total=self._net_revenue(
                select(func.coalesce(func.sum(models.CashJournal.amount), 0))
            ),
            revenue_this_month=self._net_revenue(
                select(func.coalesce(func.sum(models.CashJournal.amount), 0)).where(
                    models.CashJournal.created_at >= revenue_from_utc,
                    models.CashJournal.created_at <= revenue_to_utc,
                )
            ),
        )

    def _count(self, stmt) -> int:
        """Exécute un `SELECT COUNT(...)` scalaire et renvoie un `int` (jamais `None`)."""

        return int(self._session.scalar(stmt) or 0)

    def _net_revenue(self, stmt) -> decimal.Decimal:
        """Exécute un `SELECT COALESCE(SUM(amount), 0)` et quantifie au centime.

        Le résultat **peut être négatif** (corrections #34 > paiements) ; on garde le
        signe et on quantifie à `0.01` en `Decimal` (jamais un flottant).
        """

        return decimal.Decimal(self._session.scalar(stmt) or 0).quantize(_AMOUNT_QUANTUM)


__all__ = ["SqlPlatformKpiRepository"]
