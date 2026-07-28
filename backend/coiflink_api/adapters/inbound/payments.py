"""Adapter entrant (driving) : router HTTP **encaissement & journal de caisse** (US-5.1/5.3).

Expose, sous `/salons/{salon_id}/…` (imbriqué pour hériter de `require_salon_scope`,
isolation §11.2) :

- **`POST /salons/{salon_id}/payments`** — enregistrement d'un paiement (US-5.1,
  #33), garde `PAYMENT_RECORD`. Crée un paiement `VALIDATED`, l'inscrit au journal
  (ligne `PAYMENT`) et le journalise (`PAYMENT_RECORDED`) dans la même unité de
  travail ;
- **`GET /salons/{salon_id}/cash-journal`** — journal horodaté (US-5.3, #34), garde
  `CASH_JOURNAL_READ`. Liste paginée des opérations, **de la plus récente à la plus
  ancienne**, chacune portant `created_at` (horodatage) et l'auteur (`performed_by`
  + nom résolu) ;
- **`POST /salons/{salon_id}/payments/{payment_id}/adjustments`** — correction
  (US-5.3, #34), garde `PAYMENT_RECORD`. **Insère** une ligne `ADJUSTMENT` (delta
  signé) rattachée au paiement d'origine et passe ce dernier à `ADJUSTED` — **sans
  jamais** le supprimer ni le réécrire (§8.2).

**Aucun** verbe destructif (`DELETE`/`PUT`/`PATCH`) n'est exposé sur `payments` ou
`cash_journal` : un paiement validé n'est jamais supprimé, une ligne de journal
n'est jamais modifiée (append-only §8.2). **Aucun** chemin n'entre dans
`PUBLIC_ROUTE_PATHS` : le journal de caisse (données financières) n'est jamais
public.

Le router traduit HTTP → commande applicative, assemble les cas d'usage par
injection de dépendances, puis retraduit les erreurs de domaine :

- `InvalidPaymentAmount` / `InvalidPaymentMethod` / `PaymentReferenceRequired` /
  `InvalidAdjustment` → **422** ;
- `PaymentNotAdjustable` (paiement non `VALIDATED`) → **409** ;
- `PaymentNotFound` → **404** *(uniquement après validation de portée)*.

Sécurité (RBAC #12, ADR-0015 ; §8.2/§11.2/§11.3/§11.4) : `PAYMENT_RECORD` et
`CASH_JOURNAL_READ` (§4.1) sont détenues par le **seul** `MANAGER` — la matrice
`ROLE_PERMISSIONS` n'est **pas** modifiée. L'auteur (`recorded_by`/`performed_by`)
vient **toujours** du `Principal`, jamais du corps (non-répudiation). Les entrées
d'audit sont **neutres** (ni montant, ni motif, ni PII).
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.security import (
    require_permission,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.cash_journal_repository import (
    SqlCashJournalEntryRepository,
)
from coiflink_api.adapters.outbound.persistence.payment_repository import (
    SqlPaymentRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.cash_journal import AdjustPayment, ListCashJournal
from coiflink_api.application.payments import PaymentCommand, RecordPayment
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.cash_journal_repository import (
    CASH_JOURNAL_LIMIT_DEFAULT,
    CASH_JOURNAL_LIMIT_MAX,
    CASH_JOURNAL_LIMIT_MIN,
    CashJournalRepository,
)
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.cash_journal import (
    DESCRIPTION_MAX_LENGTH,
    CashJournalEntry,
)
from coiflink_api.domain.errors import (
    InvalidAdjustment,
    InvalidPaymentAmount,
    InvalidPaymentCurrency,
    InvalidPaymentMethod,
    PaymentNotAdjustable,
    PaymentNotFound,
    PaymentReferenceRequired,
)
from coiflink_api.domain.payment import (
    DEFAULT_CURRENCY,
    PAYMENT_METHOD_VALUES,
    REFERENCE_MAX_LENGTH,
    Payment,
)
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["payments"])

# Erreurs de validation du domaine → 422 (jamais `str(exc)` sur un refus RBAC).
_VALIDATION_ERRORS = (
    InvalidPaymentAmount,
    InvalidPaymentMethod,
    InvalidPaymentCurrency,
    PaymentReferenceRequired,
    InvalidAdjustment,
)


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `customers.py`).
# --------------------------------------------------------------------------- #
class CreatePaymentRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/payments` (US-5.1, #33).

    **Aucun** champ privilégié dans le corps : le `salon_id` vient de la portée,
    `recorded_by` du `Principal`, le `status` est imposé `VALIDATED`, `id`/
    `created_at` sont générés côté serveur. Un champ privilégié présent est
    **ignoré** (`extra="ignore"`). Le paiement doit référencer une prestation
    **ou** un rendez-vous (§8.2).
    """

    model_config = ConfigDict(extra="ignore")

    amount: decimal.Decimal = Field(examples=["5000.00"])
    payment_method: str = Field(examples=[PAYMENT_METHOD_VALUES[0]])
    appointment_id: uuid.UUID | None = Field(default=None)
    service_id: uuid.UUID | None = Field(default=None)
    client_id: uuid.UUID | None = Field(default=None)
    reference: str | None = Field(
        default=None, max_length=REFERENCE_MAX_LENGTH, examples=["REC-2026-0001"]
    )
    currency: str = Field(default=DEFAULT_CURRENCY, max_length=3, examples=[DEFAULT_CURRENCY])


class CreateAdjustmentRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/payments/{payment_id}/adjustments` (US-5.3, #34).

    `amount` est le **delta signé** de correction (`≠ 0`, ≤ 2 décimales) : il *peut*
    être négatif (correction à la baisse), à la différence d'un paiement.
    **`performed_by` n'est pas dans le corps** — il vient du `Principal`
    (non-répudiation §8.2). Un champ privilégié présent est **ignoré**
    (`extra="ignore"`).
    """

    model_config = ConfigDict(extra="ignore")

    amount: decimal.Decimal = Field(examples=["-500.00"])
    description: str | None = Field(
        default=None,
        max_length=DESCRIPTION_MAX_LENGTH,
        examples=["Erreur de saisie du montant"],
    )


class PaymentResponse(BaseModel):
    """Représentation d'un paiement renvoyée par l'API (§9.6)."""

    id: uuid.UUID
    salon_id: uuid.UUID
    amount: decimal.Decimal
    currency: str
    payment_method: str
    status: str
    recorded_by: uuid.UUID
    appointment_id: uuid.UUID | None
    service_id: uuid.UUID | None
    client_id: uuid.UUID | None
    reference: str | None
    created_at: datetime.datetime


class CashJournalEntryResponse(BaseModel):
    """Une opération du journal de caisse : horodatée + auteur (§8.2, §9.7).

    `amount` est **signé** (positif pour un `PAYMENT`, signé pour un `ADJUSTMENT`),
    sérialisé en chaîne décimale (`NUMERIC(12,2)`, jamais de flottant). `created_at`
    est l'**horodatage serveur** (affiché en `Africa/Abidjan` côté web).
    """

    id: uuid.UUID
    operation_type: str
    amount: decimal.Decimal
    currency: str
    transaction_id: uuid.UUID | None
    performed_by: uuid.UUID
    performed_by_name: str | None
    description: str | None
    created_at: datetime.datetime


class CashJournalPageResponse(BaseModel):
    """Réponse paginée de `GET /salons/{salon_id}/cash-journal` : items + total + bornes."""

    items: list[CashJournalEntryResponse]
    total: int
    limit: int
    offset: int


class AdjustmentResponse(BaseModel):
    """Réponse `201` d'une correction : la ligne `ADJUSTMENT` créée + statut du paiement.

    Le paiement d'origine **subsiste** (`status = ADJUSTED`, jamais supprimé) ; la
    correction est une **nouvelle** ligne de journal (§8.2).
    """

    entry: CashJournalEntryResponse
    payment: PaymentResponse


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_payment_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PaymentRepository:
    """Dépôt de paiements adossé à la session de la requête."""

    return SqlPaymentRepository(session)


def get_cash_journal_repository(
    session: Annotated[Session, Depends(get_session)],
) -> CashJournalRepository:
    """Dépôt du journal de caisse adossé à la session de la requête."""

    return SqlCashJournalEntryRepository(session)


def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité).

    FastAPI met en cache la dépendance `get_session` par requête : les dépôts
    métier et le journal d'audit partagent donc la **même** `Session`, d'où le
    commit/rollback conjoint de l'écriture et de sa trace.
    """

    return SqlAuditLog(session)


def _payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        salon_id=payment.salon_id,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        status=payment.status,
        recorded_by=payment.recorded_by,
        appointment_id=payment.appointment_id,
        service_id=payment.service_id,
        client_id=payment.client_id,
        reference=payment.reference,
        created_at=payment.created_at,
    )


def _entry_response(entry: CashJournalEntry) -> CashJournalEntryResponse:
    return CashJournalEntryResponse(
        id=entry.id,
        operation_type=entry.operation_type,
        amount=entry.amount,
        currency=entry.currency,
        transaction_id=entry.transaction_id,
        performed_by=entry.performed_by,
        performed_by_name=entry.performed_by_name,
        description=entry.description,
        created_at=entry.created_at,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un paiement (validé, inscrit au journal de caisse)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        422: {"description": "Montant, mode de paiement, devise ou référence invalides"},
    },
)
def record_payment(
    salon_id: uuid.UUID,
    payload: CreatePaymentRequest,
    payment_repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    cash_journal_repo: Annotated[CashJournalRepository, Depends(get_cash_journal_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[Principal, Depends(require_permission(Permission.PAYMENT_RECORD))],
) -> PaymentResponse:
    """Enregistre un paiement `VALIDATED` pour le salon de la portée (US-5.1, #33).

    Le `salon_id` vient du chemin (portée), `recorded_by` du `Principal` — jamais
    du corps. Inscrit une ligne `PAYMENT` au journal et journalise
    `PAYMENT_RECORDED` (§11.4) dans la même unité de travail, `metadata` **vide**.
    """

    try:
        payment = RecordPayment(payment_repo, cash_journal_repo, audit_log).execute(
            salon_id,
            PaymentCommand(
                amount=payload.amount,
                payment_method=payload.payment_method,
                appointment_id=payload.appointment_id,
                service_id=payload.service_id,
                client_id=payload.client_id,
                reference=payload.reference,
                currency=payload.currency or DEFAULT_CURRENCY,
            ),
            actor_user_id=principal.id,
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _payment_response(payment)


@router.get(
    "/{salon_id}/cash-journal",
    response_model=CashJournalPageResponse,
    summary="Journal de caisse horodaté du salon (paginé, plus récent d'abord)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
    },
)
def list_cash_journal(
    salon_id: uuid.UUID,
    cash_journal_repo: Annotated[CashJournalRepository, Depends(get_cash_journal_repository)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[Principal, Depends(require_permission(Permission.CASH_JOURNAL_READ))],
    limit: int = Query(
        default=CASH_JOURNAL_LIMIT_DEFAULT,
        ge=CASH_JOURNAL_LIMIT_MIN,
        le=CASH_JOURNAL_LIMIT_MAX,
    ),
    offset: int = Query(default=0, ge=0),
) -> CashJournalPageResponse:
    """Liste **seulement** les opérations du salon de la portée (isolation §11.2).

    Chaque opération est **horodatée** (`created_at`) et porte son **auteur**
    (`performed_by` + nom résolu). Lecture seule : aucune écriture, aucun audit.
    """

    page, total = ListCashJournal(cash_journal_repo).execute(salon_id, limit=limit, offset=offset)
    return CashJournalPageResponse(
        items=[_entry_response(entry) for entry in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{salon_id}/payments/{payment_id}/adjustments",
    response_model=AdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Corriger un paiement par une ligne d'ajustement (sans suppression)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (générique)"},
        404: {"description": "Paiement introuvable (portée déjà validée)"},
        409: {"description": "Paiement non corrigible (non validé / déjà ajusté)"},
        422: {"description": "Montant d'ajustement nul ou hors bornes"},
    },
)
def adjust_payment(
    salon_id: uuid.UUID,
    payment_id: uuid.UUID,
    payload: CreateAdjustmentRequest,
    payment_repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    cash_journal_repo: Annotated[CashJournalRepository, Depends(get_cash_journal_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[Principal, Depends(require_permission(Permission.PAYMENT_RECORD))],
) -> AdjustmentResponse:
    """Corrige le paiement `(salon_id, payment_id)` par une **ligne d'ajustement** (§8.2).

    Ne supprime ni ne réécrit **jamais** le paiement d'origine : insère une nouvelle
    ligne `ADJUSTMENT` (delta signé) et passe le paiement à `ADJUSTED`. Journalise
    `CASH_ADJUSTED` (§11.4) dans la même unité de travail, `metadata` **vide** (ni
    delta, ni motif). `404` (paiement hors salon/inconnu) est renvoyé **après**
    validation de portée (sans oracle).
    """

    try:
        entry, payment = AdjustPayment(payment_repo, cash_journal_repo, audit_log).execute(
            salon_id,
            payment_id,
            payload.amount,
            payload.description,
            actor_user_id=principal.id,
        )
    except _VALIDATION_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except PaymentNotAdjustable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PaymentNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AdjustmentResponse(entry=_entry_response(entry), payment=_payment_response(payment))


__all__ = ["router"]
