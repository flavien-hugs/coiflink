"""Projection de lecture « reçu numérique de paiement » (domaine pur, US-5.5, #38).

Ces `dataclass` gelées et fonctions découplent l'application du modèle ORM
SQLAlchemy (`adapters/outbound/persistence/models.py`) : conformément à
l'hexagonal (ADR-0008), ni `domain/` ni `application/` n'importent FastAPI ni
SQLAlchemy.

Un **reçu** est une **projection en lecture seule** dérivée d'un paiement déjà
persisté (#33) : montant, devise, mode, statut, référence et horodatage viennent
tels quels du `payment` (source de vérité), l'identité **publique** du salon
(`salons.name`) est résolue depuis `payment.salon_id`, et les **lignes** sont les
prestations réglées — pour un paiement lié à un **RDV**, les `appointment_services`
(nom courant + `price_at_booking` **figé**) ; pour un paiement lié à une
**prestation seule**, la prestation (`services.name` + `Service.price`). Aucune
écriture, aucun recalcul « à la main » côté client.

Points de sécurité/qualité de donnée (PRD §11.2/§11.3) :

- montants `NUMERIC(12,2)` portés en `Decimal` (jamais un flottant) ; le **total
  affiché reste `payment.amount`** (source de vérité), les lignes étant
  informatives (cohérence somme des lignes = `amount` garantie par #33) ;
- **aucune PII tierce** : le reçu ne contient que des données que le client
  possède déjà (son propre paiement, l'identité **publique** du salon, les
  prestations qu'il a réglées) — jamais `recorded_by`, ni un autre client, ni une
  donnée de gestion.

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
    """Ligne de prestation d'un reçu : libellé + montant figé (US-5.5, #38).

    Le **nom** est le libellé *courant* de la prestation (`services.name`), le
    **montant** est le prix **figé** au moment de la réservation
    (`price_at_booking`) pour un RDV, ou `Service.price` pour une prestation seule.
    Une prestation soft-deletée (`is_active = false`) reste en table (FK
    `RESTRICT`), donc son nom reste résoluble pour le reçu.
    """

    service_name: str
    amount: decimal.Decimal


@dataclass(frozen=True)
class Receipt:
    """Reçu numérique d'un paiement, vu par le client (projection en lecture seule).

    Assemblage de données **déjà validées** (aucun `raise` métier ici) : le
    `payment` reste la source de vérité (`amount`/`status`/`reference`/`paid_at`),
    l'identité du salon est **publique** (`salon_name`), et les `lines` sont
    informatives. `appointment_id` est renseigné pour un paiement lié à un RDV,
    `None` pour une prestation seule.
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
    appointment_id: uuid.UUID | None
    lines: tuple[ReceiptLine, ...] = ()


def format_receipt_number(payment_id: uuid.UUID) -> str:
    """Numéro de reçu **stable et déterministe** dérivé de l'identifiant de paiement.

    Fonction **pure** (sans I/O, sans compteur base) : le `payment.id` canonique
    est l'identifiant stable du reçu — deux appels pour le même paiement donnent
    **toujours** la même valeur, sans nouvelle colonne ni écriture (voir spec
    *Open Questions* §3). Centralisée ici pour qu'un éventuel libellé cosmétique
    `REC-…` ne se décide qu'à **un** endroit.
    """

    return str(payment_id)


__all__ = [
    "DEFAULT_CURRENCY",
    "ReceiptLine",
    "Receipt",
    "format_receipt_number",
]
