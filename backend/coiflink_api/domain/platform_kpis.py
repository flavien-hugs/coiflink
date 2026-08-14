"""KPI **globaux** de la plateforme (domaine pur, US-6.6, #44).

Ce module porte l'objet-valeur de lecture `PlatformKpiSnapshot` — l'**instantané
consolidé** de la plateforme entière (compteurs et totaux à l'échelle globale) —
et le petit VO de transport `PlatformKpiCounts` (scalaires bruts calculés en base).
Conformément à l'hexagonal (ADR-0008), il ne connaît ni FastAPI ni SQLAlchemy :
l'adapter entrant le projette en JSON, le cas d'usage l'assemble à partir des
compteurs et des bornes de période.

**Vue plateforme consolidée, pas exploitation d'un salon.** À la différence des
lectures statistiques salon-scopées (Épic 6, #39–#43, gardées par `STATS_READ_SALON`
du seul `MANAGER` et montées sous `/salons/{salon_id}/…`), il s'agit d'un agrégat
**inter-entités** réservé à l'`ADMIN` (`STATS_READ_PLATFORM`) : combien de salons sont
inscrits, combien de tickets walk-in ont été pris, quel revenu transite par CoifLink.
C'est aussi une vue **plus globale** que la supervision #37 (`GET
/admin/transactions/summary`, qui liste des agrégats **par salon**) : #44 ne renvoie
**que des scalaires globaux**, aucune ligne par entité.

**Non-PII (§11.3), plus forte que #37.** L'instantané ne porte **que** des scalaires
globaux (compteurs, montants, dates, devise). **Aucune** identité d'entité n'est émise
— ni `salon_id`/`salon_name`, ni `client_id`, ni `owner_id`, ni `reference`, ni
`recorded_by`, ni aucune ligne individuelle.

**Sort du KPI « abonnements » (décision produit centrale).** Le critère d'acceptation
du backlog liste « abonnements » parmi les KPIs, mais **aucun modèle de données
d'abonnement / facturation n'existe** dans le backend (ni table, ni domaine, ni enum).
Ce module **n'émet donc pas** de champ `subscriptions` : on ne fabrique pas un nombre
d'abonnements à partir de données inexistantes (la mise en place d'un système
d'abonnement est un épic distinct). Le KPI **« salons inscrits / actifs »** couvre le
besoin de pilotage adossé à des données réelles ; l'UI admin peut **libeller**
`salons_active` « salons abonnés (actifs) ». Voir ADR-0032.

**« Revenus plateforme » ≠ « revenus d'abonnement ».** `revenue_total` /
`revenue_this_month` sont le **flux net encaissé par les salons** (somme signée des
lignes `cash_journal`, **même source de vérité** que #34/#37/#40 : un paiement corrigé
fait baisser le net), **pas** un revenu de facturation SaaS (qui n'existe pas). Cette
distinction est explicite dans les libellés pour ne pas induire en erreur.

**Interprétation temporelle.** La fenêtre mensuelle réutilise
`domain/revenue.py::month_bounds` (1er → dernier jour du mois civil `Africa/Abidjan`,
convention #21) — aucune duplication calendaire. Le cas d'usage convertit ces bornes
de **jour civil** en bornes UTC (via `domain/time_window.py`) **uniquement** pour le
revenu (colonne `cash_journal.created_at` timezone-aware) ; les tickets se comparent
**directement** sur `issued_date` (déjà un jour civil).
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from coiflink_api.domain.payment import DEFAULT_CURRENCY


@dataclass(frozen=True)
class PlatformKpiCounts:
    """Scalaires bruts d'un instantané plateforme (transport port → cas d'usage).

    Petit VO **interne** renvoyé par `PlatformKpiRepository.compute_snapshot` : il ne
    porte **que** les compteurs et sommes calculés en base, sans la devise ni les
    bornes de période (assemblées par le cas d'usage, qui garde le domaine pur des
    détails de fenêtre). Montants en `Decimal` quantifié au centime (`NUMERIC(12,2)`,
    jamais un flottant) ; ils **peuvent être négatifs** si les corrections (#34)
    excèdent les paiements. **Aucune** identité d'entité.
    """

    salons_total: int
    salons_active: int
    clients_total: int
    tickets_total: int
    tickets_this_month: int
    revenue_total: decimal.Decimal
    revenue_this_month: decimal.Decimal


@dataclass(frozen=True)
class PlatformKpiSnapshot:
    """Instantané **consolidé** des KPI globaux de la plateforme (US-6.6, #44).

    Objet-valeur de lecture **immuable** et **sans identité d'entité** (§11.3) :

    - **Salons inscrits** — `salons_total` (tous statuts) et `salons_active`
      (statut `ACTIVE`, PRD §7.3 « Salons actifs ») ;
    - **Clients inscrits** — `clients_total` (comptes de rôle `CLIENT` uniquement) ;
    - **Tickets walk-in** — `tickets_total` (**volume émis**, tous statuts, y compris
      `expired` — cf. ADR-0032) et `tickets_this_month` (tickets du **mois civil
      courant**, comparés sur `issued_date`) — rebranché sur `queue_tickets` avec le
      pivot walk-in exclusif (#148) ;
    - **Revenus plateforme** — `revenue_total` (net cumulé) et `revenue_this_month`
      (net du **mois civil courant**), **somme signée** des lignes `cash_journal`
      (net des corrections #34), `Decimal` quantifié au centime — jamais un flottant,
      **peut être négatif** ;
    - `currency` (mono-devise XOF au MVP), `reference_date` (date de référence de la
      fenêtre mensuelle) et `month_from`/`month_to` (bornes du mois civil courant,
      exposées pour la transparence de la période — comme #40).

    **Aucun** champ identifiant une entité (pas de `salon_id`, `salon_name`,
    `client_id`, `owner_id`, ni ligne quelconque). **Aucun** champ `subscriptions` :
    aucun modèle d'abonnement n'existe (cf. docstring du module, ADR-0032).
    """

    salons_total: int
    salons_active: int
    clients_total: int
    tickets_total: int
    tickets_this_month: int
    revenue_total: decimal.Decimal
    revenue_this_month: decimal.Decimal
    reference_date: datetime.date
    month_from: datetime.date
    month_to: datetime.date
    currency: str = DEFAULT_CURRENCY


__all__ = ["PlatformKpiCounts", "PlatformKpiSnapshot"]
