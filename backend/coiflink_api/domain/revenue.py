"""Chiffre d'affaires **jour / semaine / mois** d'un salon (domaine pur, US-6.2, #40).

Ce module porte les objets-valeur de lecture du CA (`RevenuePeriodTotal`,
`RevenueSummary`) et — surtout — les **fonctions pures de bornes de période**
(`day_bounds` / `week_bounds` / `month_bounds`). Ces bornes **sont** la règle
métier de l'US-6.2 : « CA journalier, hebdomadaire, mensuel » se traduit par la
définition **exacte** du jour, de la semaine et du mois civils qui contiennent une
date de référence. Les isoler ici (sans I/O) les rend testables sans base et
garantit des périodes cohérentes.

Conformément à l'hexagonal (ADR-0008), le module ne connaît ni FastAPI ni
SQLAlchemy : le cas d'usage (`application/revenue.py`) convertit ces bornes de
**jour civil** en bornes UTC via `domain/time_window.py` puis interroge le journal
de caisse ; l'adapter entrant les projette en JSON.

**Sémantique des périodes** (visible par le gérant, cf. spec §Open Questions 4/9) :

- **jour** : la date de référence elle-même (`from == to`) ;
- **semaine** : la semaine civile **lundi → dimanche** qui la contient (usage
  FR/CI, standard ISO du lundi) ;
- **mois** : le mois civil (du 1er au dernier jour, via `calendar.monthrange` —
  gère février bissextile et les mois de 30/31 jours).

Ces bornes vérifient par construction `date_from ≤ date_to`, `semaine ⊇ jour` et
`mois ⊇ jour`. Elles se **chevauchent** (le jour ⊂ la semaine, la semaine croise
parfois deux mois) : le cas d'usage ne combine donc pas les sommes — il calcule
**trois** totaux indépendants.
"""

from __future__ import annotations

import calendar
import datetime
import decimal
from dataclasses import dataclass

from coiflink_api.domain.payment import DEFAULT_CURRENCY


@dataclass(frozen=True)
class RevenuePeriodTotal:
    """CA d'**une** période (jour, semaine ou mois) — projection de lecture immuable.

    Porte ses **bornes de jour civil** inclusives (`date_from`/`date_to`), le
    **total** encaissé net (`Decimal` quantifié au centime, `NUMERIC(12,2)`, jamais
    un flottant) et la **devise** (mono-devise XOF au MVP, §9.6). `total` **peut être
    négatif** si les corrections (#34) excèdent les paiements sur la période. Sans
    PII : uniquement des dates, un montant et une devise (§11.3).
    """

    date_from: datetime.date
    date_to: datetime.date
    total: decimal.Decimal
    currency: str = DEFAULT_CURRENCY


@dataclass(frozen=True)
class RevenueSummary:
    """CA d'un salon sur **trois périodes** pour une date de référence (US-6.2, #40).

    Assemble les totaux du **jour**, de la **semaine** (lundi→dimanche) et du **mois**
    civils contenant `reference_date`. Objet-valeur **immuable** et **sans PII**
    (§11.3) : seulement des dates, des montants et une devise. Construit par
    `application/revenue.py::SummarizeRevenue`.
    """

    reference_date: datetime.date
    day: RevenuePeriodTotal
    week: RevenuePeriodTotal
    month: RevenuePeriodTotal
    currency: str = DEFAULT_CURRENCY


def day_bounds(reference: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Bornes du **jour** civil : la date de référence elle-même (`(d, d)`)."""

    return reference, reference


def week_bounds(reference: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Bornes de la **semaine** civile **lundi → dimanche** contenant `reference`.

    `weekday()` vaut `0` le lundi et `6` le dimanche : reculer de `weekday()` jours
    donne le lundi, avancer de 6 jours depuis ce lundi donne le dimanche. Un lundi
    est donc sa propre borne basse ; un dimanche, sa propre borne haute.
    """

    monday = reference - datetime.timedelta(days=reference.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def month_bounds(reference: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Bornes du **mois** civil : du 1er au dernier jour du mois de `reference`.

    Le dernier jour est fourni par `calendar.monthrange` (stdlib, aucune dépendance
    nouvelle) : il gère correctement février (28/29 jours) et les mois de 30/31 jours.
    """

    first = reference.replace(day=1)
    last_day = calendar.monthrange(reference.year, reference.month)[1]
    last = reference.replace(day=last_day)
    return first, last


__all__ = [
    "RevenuePeriodTotal",
    "RevenueSummary",
    "day_bounds",
    "week_bounds",
    "month_bounds",
]
