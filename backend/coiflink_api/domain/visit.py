"""Read models « historique des visites d'un client » (domaine pur, US-4.2, #29).

Ces `dataclass` gelées et fonctions découplent l'application du modèle ORM
SQLAlchemy (`adapters/outbound/persistence/models.py`) : conformément à
l'hexagonal (ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni
SQLAlchemy.

Une **visite** est un rendez-vous **réalisé** (`COMPLETED`) : elle porte ses
prestations **nommées** (libellé + prix figé) et un **montant total** = somme des
`price_at_booking` (prix figé à la réservation, jamais le tarif courant — un
changement de tarif ne réécrit pas l'historique, invariant #21). Devise **XOF**
(unique au MVP, §9.6) ; montants `NUMERIC(12,2)` sérialisés en décimal, **jamais**
de flottant.

Le résumé (`VisitHistory`) est **dérivé en lecture** : `total_visits`,
`last_visit_at` et `total_amount` sont calculés à la volée, **sans** écrire les
colonnes homonymes de `customer_profiles` (voir la spec US-4.2 § *Open Questions*).

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit le read model en
schéma de réponse (cf. `adapters/inbound/customers.py`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass, field

from coiflink_api.domain.enums import AppointmentStatus

# Définition de « RDV terminés » de #29 (critère d'acceptation), **nommée
# distinctement** de `domain.appointment.REVENUE_STATUSES` : même valeur
# aujourd'hui (`COMPLETED`), mais deux décisions métier séparées, susceptibles de
# diverger (patron `CLIENT_CANCELLABLE_STATUSES`). Une visite = une prestation
# **réalisée** ; un `NO_SHOW`/`CANCELLED` n'est pas une visite.
HISTORY_STATUSES: tuple[str, ...] = (AppointmentStatus.COMPLETED.value,)

# Devise unique au MVP (§9.6). Aucun multi-devises n'est modélisé.
DEFAULT_CURRENCY = "XOF"


@dataclass(frozen=True)
class VisitService:
    """Prestation d'une visite terminée : libellé + prix figé (US-4.2, #29).

    Le **nom** est le libellé *courant* de la prestation (`services.name`) : il
    n'est pas figé, seul le **prix** l'est (`price_at_booking`). Une prestation
    soft-deletée (`is_active = false`) reste en table (FK `RESTRICT`), donc son
    nom reste résoluble pour l'historique.
    """

    service_id: uuid.UUID
    name: str
    price_at_booking: decimal.Decimal


@dataclass(frozen=True)
class CustomerVisit:
    """RDV terminé d'un client, vue « historique » (prestations nommées + montant).

    `status` vaut toujours `COMPLETED` dans ce périmètre. `total_amount` est la
    somme des `price_at_booking` des prestations (`visit_total`). Ni `client_id`,
    ni `user_id` ne sont portés : le lien fiche ↔ compte reste encapsulé dans le
    dépôt (anti-oracle §11.1/§11.3, ADR-0026).
    """

    appointment_id: uuid.UUID
    date: datetime.date
    start_time: datetime.time
    end_time: datetime.time
    status: str
    services: tuple[VisitService, ...]
    total_amount: decimal.Decimal


@dataclass(frozen=True)
class VisitHistory:
    """Historique agrégé d'une fiche : visites + résumé dérivé (jamais dénormalisé).

    Le résumé reflète **toujours** la vérité des RDV `COMPLETED` : il n'est pas
    persisté (les colonnes `customer_profiles.last_visit_at`/`total_visits`
    restent à leurs défauts). Une fiche walk-in ou sans visite réalisée donne un
    historique **vide** (comportement normal, pas une erreur).
    """

    visits: tuple[CustomerVisit, ...] = ()
    total_visits: int = 0
    last_visit_at: datetime.datetime | None = None
    total_amount: decimal.Decimal = field(default_factory=lambda: decimal.Decimal("0"))
    currency: str = DEFAULT_CURRENCY


def visit_total(services: tuple[VisitService, ...]) -> decimal.Decimal:
    """Montant d'une visite = **somme des `price_at_booking`** (fonction pure).

    Testable sans I/O. Une visite **sans** prestation ne devrait pas exister
    (invariant §8.1 « ≥ 1 prestation »), mais la somme d'un tuple vide vaut
    `Decimal("0")` (robustesse, sans erreur). `Decimal` de bout en bout : **jamais**
    de flottant (perte de précision monétaire).
    """

    total = decimal.Decimal("0")
    for service in services:
        total += service.price_at_booking
    return total


@dataclass(frozen=True)
class CustomerPayment:
    """Un paiement du compte lié à une fiche, vue « historique » (fiche client).

    `status` reflète l'état réel du paiement (`PENDING`/`VALIDATED`/`CANCELLED`/
    `ADJUSTED`, §9.6) — contrairement aux visites (toujours `COMPLETED`), un
    paiement affiché ici peut être dans n'importe quel état : c'est justement
    l'utilité de la colonne « statut ». Ni `client_id`, ni `user_id`, ni
    `recorded_by`/`reference` ne sont portés : le lien fiche ↔ compte reste
    encapsulé dans le dépôt (anti-oracle §11.1/§11.3, ADR-0026, patron
    `CustomerVisit`).
    """

    payment_id: uuid.UUID
    created_at: datetime.datetime
    amount: decimal.Decimal
    currency: str
    status: str


@dataclass(frozen=True)
class ServiceFrequency:
    """Une prestation dans le classement des préférences d'un client (US-4.3, #31).

    `count` = nombre d'occurrences **réalisées** (une ligne `appointment_services`
    par occurrence, dans les RDV `COMPLETED`) ; `total_amount` = somme des
    `price_at_booking` de cette prestation (prix **figés** à la réservation, XOF,
    jamais le tarif courant). `name` est le libellé **courant** (`services.name`),
    résoluble même si la prestation est soft-deletée (`is_active = false`, FK
    `RESTRICT`). La clé d'agrégation est **toujours** `service_id` (deux prestations
    distinctes partageant un libellé ne sont pas fusionnées). `Decimal` de bout en
    bout, **jamais** de flottant.
    """

    service_id: uuid.UUID
    name: str
    count: int
    total_amount: decimal.Decimal


@dataclass(frozen=True)
class CustomerServiceStats:
    """Statistiques « prestations préférées » d'une fiche : classement + totaux dérivés.

    `services` est trié de la **plus fréquente à la moins fréquente** (ordre
    déterministe, voir `favourite_services`). `total_visits` = nombre de visites
    `COMPLETED` considérées ; `total_services` = nombre total d'occurrences de
    prestations agrégées. Une fiche walk-in ou sans visite réalisée donne un
    classement **vide** (comportement normal, pas une erreur). Rien n'est
    persisté : tout est **dérivé en lecture** des visites déjà exposées par #29.
    """

    services: tuple[ServiceFrequency, ...] = ()
    total_visits: int = 0
    total_services: int = 0
    currency: str = DEFAULT_CURRENCY


def favourite_services(
    visits: tuple[CustomerVisit, ...],
    *,
    currency: str = DEFAULT_CURRENCY,
) -> CustomerServiceStats:
    """Classe les prestations d'un client par fréquence (fonction **pure**).

    Parcourt les visites (attendues `COMPLETED`, invariant §8.1 « ≥ 1 prestation »),
    agrège par `service_id` (`count += 1`, `total_amount += price_at_booking`),
    puis trie **fréquence décroissante**, en départageant par `total_amount`
    décroissant, puis `name` croissant, puis `service_id` (chaîne) croissant —
    ordre **déterministe** et stable (utile aux tests, indépendant de l'ordre
    d'itération d'un dict). Une entrée vide (aucune visite) donne un classement
    vide. `Decimal` de bout en bout : **jamais** de flottant.

    Le lien `user_id`/`client_id` n'est **jamais** vu ici (encapsulé côté dépôt,
    anti-oracle ADR-0026) : l'agrégation ne connaît que des prestations nommées.
    """

    # Agrégation par `service_id` — l'insertion préserve le premier libellé vu ;
    # `services.name` étant stable par `service_id`, ce choix est sans effet en
    # pratique (voir spec § *Open Questions* — clé = `service_id`, jamais le nom).
    totals: dict[uuid.UUID, ServiceFrequency] = {}
    total_services = 0
    for visit in visits:
        for service in visit.services:
            total_services += 1
            existing = totals.get(service.service_id)
            if existing is None:
                totals[service.service_id] = ServiceFrequency(
                    service_id=service.service_id,
                    name=service.name,
                    count=1,
                    total_amount=service.price_at_booking,
                )
            else:
                totals[service.service_id] = ServiceFrequency(
                    service_id=existing.service_id,
                    name=existing.name,
                    count=existing.count + 1,
                    total_amount=existing.total_amount + service.price_at_booking,
                )

    ranked = tuple(
        sorted(
            totals.values(),
            key=lambda entry: (
                -entry.count,
                -entry.total_amount,
                entry.name,
                str(entry.service_id),
            ),
        )
    )

    return CustomerServiceStats(
        services=ranked,
        total_visits=len(visits),
        total_services=total_services,
        currency=currency,
    )


def build_history(
    visits: tuple[CustomerVisit, ...],
    *,
    currency: str = DEFAULT_CURRENCY,
) -> VisitHistory:
    """Construit le résumé dérivé d'un historique (fonction **pure**).

    `total_visits = len(visits)` ; `last_visit_at` = date+heure de la visite la
    plus récente ; `total_amount` = somme des montants de visite. Le tri « plus
    récent d'abord » est appliqué par le dépôt (SQL) : `build_history` ne suppose
    que cet ordre et prend `visits[0]` pour `last_visit_at`, ou `None` si vide.
    """

    if not visits:
        return VisitHistory(currency=currency)

    most_recent = visits[0]
    last_visit_at = datetime.datetime.combine(
        most_recent.date, most_recent.start_time
    )
    total_amount = decimal.Decimal("0")
    for visit in visits:
        total_amount += visit.total_amount

    return VisitHistory(
        visits=visits,
        total_visits=len(visits),
        last_visit_at=last_visit_at,
        total_amount=total_amount,
        currency=currency,
    )


__all__ = [
    "HISTORY_STATUSES",
    "DEFAULT_CURRENCY",
    "VisitService",
    "CustomerVisit",
    "VisitHistory",
    "CustomerPayment",
    "ServiceFrequency",
    "CustomerServiceStats",
    "visit_total",
    "build_history",
    "favourite_services",
]
