"""Performance des coiffeurs d'un salon sur une période (domaine pur, US-6.5, #43).

Ce module porte les objets-valeur de lecture de la performance
(`HairdresserActivityCounts`, `HairdresserActivity`, `HairdresserPerformance`,
`HairdresserPerformanceReport`) et — surtout — la **fonction pure de calcul & de
tri** (`rank_hairdresser_performance`) qui **est** la règle métier de l'US-6.5 :
« mesurer, par coiffeur, les prestations réalisées, le CA généré et le taux
d'annulation » se traduit par la définition **exacte** du taux d'annulation
(`cancelled_count / total_count`, division protégée) et d'un ordre **déterministe**
sur les coiffeurs agrégés. L'isoler ici (sans I/O) le rend testable sans base et
garantit un classement **stable**, indépendant de l'ordre SQL.

Conformément à l'hexagonal (ADR-0008), le module ne connaît ni FastAPI ni
SQLAlchemy. Les indicateurs viennent de **deux sources distinctes mais chacune
autoritaire** :

- **la file d'attente** (`queue_tickets` assignés) pour les **prestations
  réalisées** (occurrences des tickets `done`) et le **taux d'annulation** (tickets
  `expired` / tickets assignés — équivalent walk-in de l'ancien RDV `CANCELLED`) :
  l'adapter sortant (`queue_ticket_repository.py::performance_by_hairdresser`) fait
  l'**agrégat en base** (`GROUP BY hairdresser_id`) et renvoie des
  `HairdresserActivityCounts` ;
- **la caisse** (net `cash_journal` — même source que #40/#34) pour le **CA
  généré**, attribué au coiffeur via `payments.queue_ticket_id →
  queue_tickets.hairdresser_id` (`cash_journal_repository.py::
  net_revenue_by_hairdresser`).

Le cas d'usage (`application/hairdresser_performance.py`) **fusionne** les deux
sources par `hairdresser_id` en `HairdresserActivity`, puis applique
`rank_hairdresser_performance` ; l'adapter entrant (`adapters/inbound/stats.py`)
projette le résultat en JSON.

**« Réalisé » = ticket `done`** (prestations & CA), en cohérence avec l'invariant
§8.1. Le **taux d'annulation** compte les tickets `expired` (numérateur) sur le
total assigné (dénominateur) — statuts **décidés côté serveur**, jamais soumis par
l'appelant.

**Décimal, pas de flottant.** Le CA est un `Decimal` quantifié au centime
(`NUMERIC(12,2)`) et le taux un `Decimal` quantifié à quatre décimales, transportés
en **chaîne** ; le web les formate (FCFA / pourcentage) à l'affichage.

**Émission d'identité employé maîtrisée (§11.3).** `hairdresser_id` + `name`
(`users.full_name`) = identité **d'affichage** de l'employé, nécessaire au KPI
(« performance **des coiffeurs** ») et conforme à la convention #34 (résolution
`full_name` pour l'UI). Ni ce module ni la réponse ne portent le **téléphone**,
l'**e-mail**, le **rôle** ni le **statut** de l'employé, ni aucune PII **client**.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.domain.payment import DEFAULT_CURRENCY

# Précision de quantification du **taux d'annulation** : quatre décimales (ex.
# `Decimal("0.0469")`), en `Decimal` — jamais un flottant. Le taux est une part
# ∈ [0, 1] ; le web le formate en pourcentage à l'affichage.
_RATE_QUANTUM = decimal.Decimal("0.0001")

# Précision de quantification du CA attribué : le centime (miroir `NUMERIC(12,2)`).
_AMOUNT_QUANTUM = decimal.Decimal("0.01")


@dataclass(frozen=True)
class HairdresserActivityCounts:
    """Compteurs bruts de **file d'attente** d'un coiffeur au salon (US-6.5, #43).

    Produit par le dépôt (`GROUP BY hairdresser_id` sur `queue_tickets`) : porte
    l'identité **d'affichage** de l'employé (`hairdresser_id` + `name`, jamais
    téléphone/e-mail, §11.3) et les grandeurs **de la file d'attente** —
    `services_completed` = occurrences de prestations réalisées (lignes
    `queue_ticket_services` des tickets `done`) ; `cancelled_count` = tickets
    `expired` du coiffeur sur la période ; `total_count` = **tous** les tickets
    assignés au coiffeur sur la période (tous statuts). **Sans le CA** : le cas
    d'usage y adjoint le CA de la caisse (net `cash_journal` attribué). Objet-valeur
    **immuable** et **sans PII**.
    """

    hairdresser_id: uuid.UUID
    name: str
    services_completed: int
    cancelled_count: int
    total_count: int


@dataclass(frozen=True)
class HairdresserActivity:
    """Agrégats bruts d'un coiffeur au salon sur une période (US-6.5, #43).

    Fusion des deux sources par `hairdresser_id` (file d'attente + caisse) :
    `services_completed` = occurrences de prestations réalisées (tickets `done`) ;
    `revenue` = CA net **attribué** (caisse, `0.00` si le coiffeur n'a aucun paiement
    attribué sur la période) ; `cancelled_count` / `total_count` = tickets `expired` /
    total assignés. `Decimal` de bout en bout pour le montant, jamais de flottant.
    Objet-valeur **immuable** et **sans PII** (nom d'affichage employé seul).
    """

    hairdresser_id: uuid.UUID
    name: str
    services_completed: int
    revenue: decimal.Decimal
    cancelled_count: int
    total_count: int


@dataclass(frozen=True)
class HairdresserPerformance:
    """Performance dérivée d'un coiffeur (US-6.5, #43) : ajoute le taux d'annulation.

    `cancellation_rate` = `cancelled_count / total_count` (`Decimal` quantifié à
    quatre décimales), `Decimal("0.0000")` si `total_count == 0` (garde division par
    zéro). Porte les **compteurs bruts** pour la transparence (le front peut afficher
    « 3/64 »). Objet-valeur **immuable** et **sans PII** (nom d'affichage employé
    seul, jamais de contact ni de PII client).
    """

    hairdresser_id: uuid.UUID
    name: str
    services_completed: int
    revenue: decimal.Decimal
    cancelled_count: int
    total_count: int
    cancellation_rate: decimal.Decimal


@dataclass(frozen=True)
class HairdresserPerformanceReport:
    """Classement des coiffeurs d'un salon sur une période (US-6.5, #43).

    `entries` triées par ordre **déterministe** (voir `rank_hairdresser_performance`).
    `date_from`/`date_to` échoient la période ; `currency` la devise (XOF au MVP).
    `entries` **vide** si aucun coiffeur assigné sur la période (état normal, pas une
    erreur). Objet-valeur **immuable** et **sans PII**.
    """

    entries: tuple[HairdresserPerformance, ...] = ()
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    currency: str = DEFAULT_CURRENCY


def _cancellation_rate(cancelled_count: int, total_count: int) -> decimal.Decimal:
    """Taux d'annulation quantifié (`Decimal`), `0` si `total_count == 0` (pur).

    Division **protégée** : un coiffeur sans aucun ticket assigné (impossible ici —
    la liste dérive de la file d'attente — mais défensif) donne `Decimal("0.0000")`
    plutôt qu'un `ZeroDivisionError`. Le calcul reste en `Decimal` (jamais un
    flottant).
    """

    if total_count <= 0:
        return decimal.Decimal("0").quantize(_RATE_QUANTUM)
    rate = decimal.Decimal(cancelled_count) / decimal.Decimal(total_count)
    return rate.quantize(_RATE_QUANTUM)


def rank_hairdresser_performance(
    rows: tuple[HairdresserActivity, ...],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str = DEFAULT_CURRENCY,
) -> HairdresserPerformanceReport:
    """Calcule le taux d'annulation et ordonne le classement (fonction **pure**).

    Pour chaque activité : `cancellation_rate = cancelled_count / total_count`
    (quantifié à quatre décimales ; `0` si `total_count == 0`, garde division par
    zéro). Ordre par défaut **déterministe** : `-revenue`, puis `-services_completed`,
    puis `name` croissant, puis `str(hairdresser_id)` croissant (départages **stables**
    pour les tests). Cette fonction **ne ré-agrège pas** (les `rows` proviennent déjà
    d'un `GROUP BY hairdresser_id` fusionné avec le CA de la caisse) : elle **calcule**
    (le taux) et **ordonne**. Une entrée vide donne un rapport `entries == ()` (période
    et devise échoées). `Decimal` conservé (aucun flottant).
    """

    performances = tuple(
        HairdresserPerformance(
            hairdresser_id=row.hairdresser_id,
            name=row.name,
            services_completed=row.services_completed,
            revenue=row.revenue.quantize(_AMOUNT_QUANTUM),
            cancelled_count=row.cancelled_count,
            total_count=row.total_count,
            cancellation_rate=_cancellation_rate(
                row.cancelled_count, row.total_count
            ),
        )
        for row in rows
    )
    entries = tuple(
        sorted(
            performances,
            key=lambda entry: (
                -entry.revenue,
                -entry.services_completed,
                entry.name,
                str(entry.hairdresser_id),
            ),
        )
    )
    return HairdresserPerformanceReport(
        entries=entries,
        date_from=date_from,
        date_to=date_to,
        currency=currency,
    )


__all__ = [
    "HairdresserActivityCounts",
    "HairdresserActivity",
    "HairdresserPerformance",
    "HairdresserPerformanceReport",
    "rank_hairdresser_performance",
]
