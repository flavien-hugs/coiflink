"""Projection de lecture « reçu numérique de paiement » (domaine pur, US-5.5, #38).

Ces `dataclass` gelées et fonctions découplent l'application du modèle ORM
SQLAlchemy (`adapters/outbound/persistence/models.py`) : conformément à
l'hexagonal (ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni
SQLAlchemy.

Un **reçu** est une **projection en lecture seule** dérivée d'un paiement déjà
persisté (#33) : montant, devise, mode, statut, référence et horodatage viennent
tels quels du `payment` (source de vérité), l'identité **publique** du salon
(`salons.name`) est résolue depuis `payment.salon_id`, et les **lignes** sont les
prestations réglées — pour un paiement lié à un **ticket walk-in**, les
prestations du ticket (nom courant + `Service.price` actuel) ; pour un paiement
lié à une **prestation seule**, la prestation (`services.name` + `Service.price`).
Aucune écriture, aucun recalcul « à la main » côté client.

Points de sécurité/qualité de donnée (PRD §11.2/§11.3) :

- montants `NUMERIC(12,2)` portés en `Decimal` (jamais un flottant) ; le **total
  affiché reste `payment.amount`** (source de vérité), les lignes étant
  informatives (cohérence somme des lignes = `amount` garantie par #33) ;
- **aucune PII tierce** : le reçu ne contient que des données que le client
  possède déjà (son propre paiement, l'identité **publique** du salon, les
  prestations qu'il a réglées) — jamais `recorded_by`, ni un autre client, ni une
  donnée de gestion.

Depuis l'impression du reçu côté gérant (ADR-0040), la **même** projection sert
deux lectures distinctes : `get_receipt_for_client` (client, appartenance) et
`get_receipt_for_salon` (gérant, portée salon — voir
`application/ports/receipt_repository.py`). `client_name`/`client_phone` ne sont
peuplés que par la lecture gérante (le client connaît déjà sa propre identité) ;
c'est à l'adapter entrant client (`adapters/inbound/receipts.py`) de ne **jamais**
les exposer même s'ils étaient renseignés.

Aucune de ces règles ne connaît HTTP : l'adapter entrant traduit la projection en
schéma de réponse (cf. `adapters/inbound/receipts.py`).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from dataclasses import dataclass

# Devise unique au MVP (§9.6). Aucun multi-devises n'est modélisé.
DEFAULT_CURRENCY = "XOF"


@dataclass(frozen=True)
class ReceiptLine:
    """Ligne de prestation d'un reçu : libellé + montant (US-5.5, #38).

    Le **nom** est le libellé *courant* de la prestation (`services.name`), le
    **montant** est `Service.price`. Une prestation soft-deletée (`is_active =
    false`) reste en table (FK `RESTRICT`), donc son nom reste résoluble pour le
    reçu.
    """

    service_name: str
    amount: decimal.Decimal


@dataclass(frozen=True)
class Receipt:
    """Reçu numérique d'un paiement, vu par le client (projection en lecture seule).

    Assemblage de données **déjà validées** (aucun `raise` métier ici) : le
    `payment` reste la source de vérité (`amount`/`status`/`reference`/`paid_at`),
    l'identité du salon est **publique** (`salon_name`), et les `lines` sont
    informatives.
    """

    receipt_number: str
    payment_id: uuid.UUID
    salon_id: uuid.UUID
    salon_name: str
    amount: decimal.Decimal
    currency: str
    payment_method: str
    status: str
    reference: str | None
    paid_at: datetime.datetime
    lines: tuple[ReceiptLine, ...] = ()
    # Numéro du ticket walk-in réglé (`queue_tickets.ticket_number`), `None` pour
    # un paiement lié à une prestation seule (`service_id`) — pas de ticket à
    # référencer. Entier **brut** (le zéro-padding « N° 004 » relève de
    # l'affichage, miroir `QueueTicket.ticket_number`).
    ticket_number: int | None = None
    # Renseignés **uniquement** par la lecture gérante (`get_receipt_for_salon`,
    # ADR-0040) — un client connaît déjà sa propre identité, la lecture
    # d'appartenance (`get_receipt_for_client`) les laisse toujours à `None`.
    client_name: str | None = None
    client_phone: str | None = None


def format_receipt_number(receipt_number: int) -> str:
    """Numéro de reçu **présentable**, dérivé du compteur séquentiel par salon.

    Fonction **pure** (sans I/O) : `receipt_number` est déjà alloué de façon
    atomique à la création du paiement (`SqlPaymentRepository.create`, verrou
    consultatif par salon) ; ici on ne fait que le **formater** en un libellé
    stable (`REC-000042`), centralisé pour qu'un futur changement de gabarit ne se
    décide qu'à **un** endroit. Remplace l'ancien identifiant dérivé de l'UUID du
    paiement (ADR-0030 §Open Question 3) — décision assumée dans ADR-0040 : un
    reçu imprimé et remis en main a besoin d'un numéro court et présentable.
    """

    return f"REC-{receipt_number:06d}"


__all__ = [
    "DEFAULT_CURRENCY",
    "ReceiptLine",
    "Receipt",
    "format_receipt_number",
]
