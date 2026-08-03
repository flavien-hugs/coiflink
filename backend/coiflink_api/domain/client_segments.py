"""Segmentation des clients d'un salon sur une période (domaine pur, US-6.4, #42).

Ce module porte les objets-valeur de lecture de la segmentation
(`ClientVisitProfile`, `ClientSegments`) et — surtout — la **fonction pure de
classification** (`classify_client_segments`) qui **est** la règle métier de
l'US-6.4 : « segmenter les clients (nouveaux, récurrents, inactifs) sur une
période donnée » se traduit par la définition **exacte** de trois segments
mutuellement exclusifs à partir, pour chaque client, de sa première visite, de son
nombre de visites **dans** la période et de son nombre de visites **avant** la
période. L'isoler ici (sans I/O) le rend testable sans base et garantit une
classification **déterministe**, indépendante de l'ordre SQL.

Conformément à l'hexagonal (ADR-0008), le module ne connaît ni FastAPI ni
SQLAlchemy : l'adapter sortant (`adapters/outbound/persistence/appointment_repository
.py::segment_active_clients`) fait l'**agrégat en base** (`GROUP BY client_id`,
`MIN(appointment_date)`, deux `COUNT`/`SUM` filtrés) et renvoie des
`ClientVisitProfile` **sans `client_id`** ; le cas d'usage
(`application/client_segments.py`) applique `classify_client_segments` ; l'adapter
entrant (`adapters/inbound/stats.py`) projette le résultat en JSON.

**Une « visite » = RDV `COMPLETED` uniquement** (réalisé), en cohérence avec
l'invariant §8.1 (`REVENUE_STATUSES == (COMPLETED,)`) et avec #29/#31
(`HISTORY_STATUSES`). Un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` ne compte
**pas** comme une visite — « annulés exclus » (§8.1) est vrai **par construction**
du filtre de statut, décidé côté serveur (le cas d'usage impose `HISTORY_STATUSES`).

**Anti-oracle & minimisation (§11.1/§11.3, ADR-0026).** Ni ce module ni la réponse
ne portent d'identité de client : `ClientVisitProfile` **ne porte pas** le
`client_id` (groupé mais jamais émis en SQL), et `ClientSegments` ne porte **que**
des compteurs et des dates.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientVisitProfile:
    """Profil de visite **agrégé** d'un client au salon (US-6.4, #42) — sans identité.

    Produit par le dépôt (`GROUP BY client_id`) : il **ne porte pas** le `client_id`
    (anti-oracle §11.1/§11.3) — seulement les grandeurs nécessaires à la
    classification. `first_visit` = date de la première visite `COMPLETED` au salon ;
    `visits_in_period` = nombre de visites dans `[date_from, date_to]` (inclus) ;
    `visits_before` = nombre de visites **strictement avant** `date_from`. Objet-valeur
    **immuable** et **sans PII** : aucun `client_id`, `appointment_id`, ni ligne de RDV.
    """

    first_visit: datetime.date
    visits_in_period: int
    visits_before: int


@dataclass(frozen=True)
class ClientSegments:
    """Répartition des clients d'un salon sur une période (US-6.4, #42).

    `new` / `recurring` / `inactive` = effectifs des trois segments (mutuellement
    exclusifs). `active = new + recurring` (clients vus **sur** la période) est un
    dérivé de commodité, exposé pour éviter un recalcul côté front. `date_from` /
    `date_to` échoient la période demandée. Objet-valeur **immuable** et **sans PII**
    (§11.3) : ne porte **que** des compteurs et des dates, jamais une identité de
    client. Tous les compteurs à `0` (salon sans RDV `COMPLETED`) est un état **vide
    légitime**, pas une erreur.
    """

    new: int = 0
    recurring: int = 0
    inactive: int = 0
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None

    @property
    def active(self) -> int:
        """Clients **vus sur la période** = nouveaux + récurrents (dérivé pur)."""

        return self.new + self.recurring


def classify_client_segments(
    profiles: tuple[ClientVisitProfile, ...],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
) -> ClientSegments:
    """Compte les clients par segment (fonction **pure**, déterministe).

    Pour chaque profil (un client, agrégé `GROUP BY client_id`) :

    - **new**       si `visits_in_period > 0` et `visits_before == 0`
                    (première visite réalisée dans la période) ;
    - **recurring** si `visits_in_period > 0` et `visits_before > 0`
                    (revient après une visite antérieure) ;
    - **inactive**  si `visits_in_period == 0` et `visits_before > 0`
                    (vu avant, silencieux sur la période).

    Un profil sans visite ni **dans** la période ni **avant** (uniquement postérieure
    à `date_to`, cas de bord) n'est compté dans **aucun** segment. Les trois segments
    sont donc **mutuellement exclusifs** et `new + recurring + inactive ≤ len(profiles)`.
    `first_visit` est porté pour la robustesse/les tests, mais la classification
    s'appuie sur les compteurs (cohérence attendue : `visits_before == 0 ⟺ first_visit
    ≥ date_from`). Une entrée vide donne tous les compteurs à `0`. Aucune I/O.
    """

    new = 0
    recurring = 0
    inactive = 0
    for profile in profiles:
        if profile.visits_in_period > 0:
            if profile.visits_before > 0:
                recurring += 1
            else:
                new += 1
        elif profile.visits_before > 0:
            inactive += 1
    return ClientSegments(
        new=new,
        recurring=recurring,
        inactive=inactive,
        date_from=date_from,
        date_to=date_to,
    )


__all__ = [
    "ClientVisitProfile",
    "ClientSegments",
    "classify_client_segments",
]
