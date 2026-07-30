"""Adapter entrant (driving) : router HTTP **reçu numérique de paiement** (US-5.5, #38).

Expose deux lectures d'**appartenance** au client authentifié (patron #30
« Mon historique ») :

- **`GET /me/receipts`** — page des reçus du client (plus récent d'abord), garde
  `PAYMENT_READ_OWN`. **Pas** de `require_salon_scope` : un client n'a **aucune**
  portée salon (il paie potentiellement dans plusieurs salons), et le filtre
  `client_id = principal.id` est **imposé serveur** (jamais soumis) ;
- **`GET /me/receipts/{payment_id}`** — un reçu précis, même garde ; `404` **neutre**
  si le paiement n'existe pas **ou** appartient à un autre client (non-oracle §11.3).

Le reçu est une **projection en lecture** dérivée du paiement (#33) : montant, mode,
statut, référence, horodatage, identité **publique** du salon et lignes de
prestation figées. Il ne contient **aucune** PII tierce (jamais `recorded_by`, ni
un autre client, ni donnée de gestion). Montants sérialisés en **chaîne décimale**
(`NUMERIC(12,2)`, jamais de flottant), cohérents avec #34/#35.

**Aucun** verbe destructif ; **aucun** chemin n'entre dans `PUBLIC_ROUTE_PATHS` :
un reçu financier n'est **jamais** public. **Aucune** remise (push/SMS) n'est
effectuée — elle relève de M5 (Épic 7, ADR-0006) ; #38 **génère** un reçu
**récupérable**, il n'**envoie** rien.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import require_permission
from coiflink_api.adapters.outbound.persistence.receipt_repository import (
    SqlReceiptRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.ports.receipt_repository import (
    RECEIPTS_LIMIT_DEFAULT,
    RECEIPTS_LIMIT_MAX,
    RECEIPTS_LIMIT_MIN,
    ReceiptRepository,
)
from coiflink_api.application.receipts import GetMyReceipt, ListMyReceipts
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal
from coiflink_api.domain.receipt import Receipt

router = APIRouter(tags=["receipts"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `payments.py`).
# --------------------------------------------------------------------------- #
class ReceiptLineResponse(BaseModel):
    """Ligne de prestation d'un reçu : libellé + montant figé (chaîne décimale)."""

    service_name: str
    amount: decimal.Decimal


class ReceiptResponse(BaseModel):
    """Reçu numérique d'un paiement, renvoyé au client (US-5.5, #38).

    Montants en **chaîne décimale** (`NUMERIC(12,2)`, jamais de flottant). Le
    **total** de référence est `amount` (le paiement tel qu'enregistré) ; les
    `lines` sont informatives. `reference`/`appointment_id` peuvent être `null`.
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
    lines: list[ReceiptLineResponse]


class ReceiptPageResponse(BaseModel):
    """Réponse paginée de `GET /me/receipts` : items + total + bornes."""

    items: list[ReceiptResponse]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_receipt_repository(
    session: Annotated[Session, Depends(get_session)],
) -> ReceiptRepository:
    """Dépôt de lecture des reçus adossé à la session de la requête."""

    return SqlReceiptRepository(session)


def _receipt_response(receipt: Receipt) -> ReceiptResponse:
    return ReceiptResponse(
        receipt_number=receipt.receipt_number,
        payment_id=receipt.payment_id,
        salon_id=receipt.salon_id,
        salon_name=receipt.salon_name,
        amount=receipt.amount,
        currency=receipt.currency,
        payment_method=receipt.payment_method,
        status=receipt.status,
        reference=receipt.reference,
        paid_at=receipt.paid_at,
        appointment_id=receipt.appointment_id,
        lines=[
            ReceiptLineResponse(service_name=line.service_name, amount=line.amount)
            for line in receipt.lines
        ],
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    "/me/receipts",
    response_model=ReceiptPageResponse,
    summary="Lister ses reçus de paiement (client, plus récent d'abord, US-5.5)",
    responses={
        200: {"description": "Reçus du client, du plus récent au plus ancien"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (lecture réservée au client)"},
    },
)
def list_my_receipts(
    receipts: Annotated[ReceiptRepository, Depends(get_receipt_repository)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.PAYMENT_READ_OWN))
    ],
    limit: Annotated[
        int, Query(ge=RECEIPTS_LIMIT_MIN, le=RECEIPTS_LIMIT_MAX)
    ] = RECEIPTS_LIMIT_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReceiptPageResponse:
    """Liste les reçus du **client authentifié** (`client_id = principal.id`).

    Route d'**appartenance** (pas de portée salon, `PAYMENT_READ_OWN`) : le filtre
    `client_id = principal.id` est **imposé serveur** — un client ne voit **que ses
    propres** reçus, tous salons confondus, jamais ceux d'un tiers (§11.2/§11.3).
    Chaque reçu porte l'identité **publique** du salon et ses lignes de prestation
    figées. Lecture seule (aucune écriture/audit). Ordre **du plus récent au plus
    ancien**. `401`/`403` **génériques**. La liste est **vide** (≠ erreur) tant
    qu'aucun paiement n'a été rattaché au client (#33).
    """

    page, total = ListMyReceipts(receipts).execute(
        principal.id, limit=limit, offset=offset
    )
    return ReceiptPageResponse(
        items=[_receipt_response(receipt) for receipt in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/me/receipts/{payment_id}",
    response_model=ReceiptResponse,
    summary="Consulter un reçu de paiement (client, 404 neutre si tiers/inexistant)",
    responses={
        200: {"description": "Reçu du client"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant (lecture réservée au client)"},
        404: {"description": "Reçu inexistant ou hors appartenance (neutre)"},
    },
)
def get_my_receipt(
    payment_id: uuid.UUID,
    receipts: Annotated[ReceiptRepository, Depends(get_receipt_repository)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.PAYMENT_READ_OWN))
    ],
) -> ReceiptResponse:
    """Retourne le reçu `(principal.id, payment_id)` — `404` **neutre** sinon.

    Route d'**appartenance** : le `client_id` vient du `Principal`, jamais du chemin
    ni du corps. Un `payment_id` d'un autre client **ou** inexistant est un `404`
    **indiscernable** (aucun oracle d'existence, §11.3). Lecture seule.
    """

    receipt = GetMyReceipt(receipts).execute(principal.id, payment_id)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reçu introuvable."
        )
    return _receipt_response(receipt)


__all__ = ["router"]
