"""Prestations les plus demandées d'un salon (domaine pur, US-6.3, #41).

Ce module porte les objets-valeur de lecture du classement (`ServiceDemand`,
`ServiceDemandRanking`) et — surtout — la **fonction pure de tri**
(`rank_service_demand`) qui **est** la règle métier de l'US-6.3 : « classer les
prestations par volume **et** par revenu généré » se traduit par la définition
**exacte** de deux ordres déterministes (par volume décroissant, par revenu
décroissant) sur les mêmes prestations agrégées. L'isoler ici (sans I/O) le rend
testable sans base et garantit un ordre **stable**, indépendant de l'ordre SQL.

Conformément à l'hexagonal (ADR-0008), le module ne connaît ni FastAPI ni
SQLAlchemy : l'adapter sortant (`adapters/outbound/persistence/queue_ticket_repository
.py::demand_by_service`) fait l'**agrégat en base** (`GROUP BY service_id`, `COUNT`
volume, `SUM(services.price)` revenu **courant**) et renvoie des `ServiceDemand`
**non triés** ; le cas d'usage (`application/service_demand.py`) les ordonne via
`rank_service_demand` ; l'adapter entrant (`adapters/inbound/stats.py`) projette le
résultat en JSON.

**Volume & revenu = tickets `done` uniquement** (réalisés), en cohérence avec
l'invariant §8.1. Un ticket `waiting`/`called`/`in_progress`/`expired` ne pèse
**ni** en volume **ni** en revenu — « non réalisés exclus » (§8.1) est vrai **par
construction** du filtre de statut décidé côté serveur.

**Revenu = somme des `services.price` courants** (pivot walk-in : `queue_ticket_
services` ne fige aucun prix, contrairement à l'ancien `appointment_services
.price_at_booking` — décision « résolution en direct » #148), devise **XOF**
(§9.6), `Decimal` de bout en bout (`NUMERIC(12,2)`, sérialisé en **chaîne**
décimale, jamais de flottant). Cette grandeur (valeur des prestations réalisées)
peut **différer** du CA du salon (#40, dérivé du journal de caisse net).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.payment import DEFAULT_CURRENCY


@dataclass(frozen=True)
class ServiceDemand:
    """Une prestation dans le classement du salon (US-6.3, #41).

    `volume` = nombre d'occurrences **réalisées** (une ligne `appointment_services`
    par occurrence, RDV `COMPLETED`) ; `revenue` = somme des `price_at_booking` de
    cette prestation (prix **figés**, XOF, jamais le tarif courant). `name` = libellé
    **courant** (`services.name`), résoluble même si la prestation est soft-deletée
    (`is_active = false`, FK `RESTRICT`). Clé métier = `service_id` (deux prestations
    distinctes partageant un libellé ne sont pas fusionnées). `Decimal` de bout en
    bout, jamais de flottant. Objet-valeur **immuable** et **sans PII** (§11.3) :
    aucun `client_id`, `appointment_id`, ni ligne de RDV/paiement.
    """

    service_id: uuid.UUID
    name: str
    volume: int
    revenue: decimal.Decimal


@dataclass(frozen=True)
class ServiceDemandRanking:
    """Classement des prestations d'un salon : mêmes entrées, deux ordres (US-6.3).

    `by_volume` = tri **volume décroissant** ; `by_revenue` = tri **revenu
    décroissant**. Chaque entrée porte **les deux** métriques (le web affiche « ×N
    fois · M FCFA » quel que soit l'onglet). `date_from`/`date_to` échoient la période
    couverte (`None` si toute l'histoire). Classements **vides** si aucun RDV réalisé
    (état normal, pas une erreur). Immuable et **sans PII** : seulement des
    prestations nommées, des compteurs, des montants, une période et une devise.
    """

    by_volume: tuple[ServiceDemand, ...] = ()
    by_revenue: tuple[ServiceDemand, ...] = ()
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    currency: str = DEFAULT_CURRENCY


def rank_service_demand(
    rows: tuple[ServiceDemand, ...],
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> ServiceDemandRanking:
    """Trie les prestations agrégées en deux classements déterministes (fonction pure).

    `by_volume` : `-volume`, puis `-revenue`, puis `name` croissant, puis
    `str(service_id)` croissant. `by_revenue` : `-revenue`, puis `-volume`, puis
    `name` croissant, puis `str(service_id)` croissant. Les départages sont
    **stables** (indépendants de l'ordre d'itération SQL, utiles aux tests). Les
    `rows` proviennent d'un `GROUP BY service_id` (déjà dédupliquées par prestation) :
    cette fonction **ne ré-agrège pas**, elle **ordonne**. Une entrée vide donne deux
    classements vides. `Decimal` conservé (aucun arrondi, aucun flottant).
    """

    by_volume = tuple(
        sorted(
            rows,
            key=lambda entry: (
                -entry.volume,
                -entry.revenue,
                entry.name,
                str(entry.service_id),
            ),
        )
    )
    by_revenue = tuple(
        sorted(
            rows,
            key=lambda entry: (
                -entry.revenue,
                -entry.volume,
                entry.name,
                str(entry.service_id),
            ),
        )
    )
    return ServiceDemandRanking(
        by_volume=by_volume,
        by_revenue=by_revenue,
        date_from=date_from,
        date_to=date_to,
        currency=currency,
    )


__all__ = [
    "ServiceDemand",
    "ServiceDemandRanking",
    "rank_service_demand",
]
