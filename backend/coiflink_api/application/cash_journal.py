"""Cas d'usage : **journal de caisse horodaté & correction** (US-5.3, #34).

Tranche applicative hexagonale : ces cas d'usage ne dépendent que de **ports**
(`CashJournalRepository`, `PaymentRepository`, `AuditLog`) — aucune dépendance
FastAPI/SQLAlchemy. Ils matérialisent le critère d'acceptation #34 :

> Chaque paiement apparaît horodaté + auteur ; suppression interdite ; correction =
> ligne d'ajustement.

- `ListCashJournal` : **lecture** paginée du journal (horodatage + auteur + type +
  montant signé + devise + transaction + motif), du plus récent au plus ancien.
  Aucune écriture, aucun audit — une consultation reste bornée par la permission
  `CASH_JOURNAL_READ`.
- `AdjustPayment` : **correction par ajustement** (§8.2). Ne supprime ni ne réécrit
  jamais le paiement d'origine ; **insère** une ligne `ADJUSTMENT` (delta signé) et
  passe le paiement à `ADJUSTED` (mutation de statut, jamais un delete), le tout
  journalisé (`CASH_ADJUSTED`) dans la **même unité de travail** (atomicité).
"""

from __future__ import annotations

import decimal
import uuid

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.cash_journal_repository import CashJournalRepository
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.domain.audit import ENTITY_TYPE_PAYMENT, AuditAction, AuditEntry
from coiflink_api.domain.cash_journal import (
    CashJournalEntry,
    CashJournalToAppend,
    normalize_description,
    validate_adjustment_amount,
)
from coiflink_api.domain.enums import CashOperationType, PaymentStatus
from coiflink_api.domain.errors import PaymentNotAdjustable
from coiflink_api.domain.payment import Payment


class ListCashJournal:
    """Liste paginée des opérations de caisse d'un salon (lecture — pas d'audit).

    Chaque opération porte son **horodatage** (`created_at`) et son **auteur**
    (`performed_by` + nom résolu), satisfaisant « chaque paiement apparaît horodaté
    + auteur ». Lecture pure : aucune écriture, aucun audit (une consultation de
    journal n'est pas une action §11.4 ici — la lecture reste bornée par la
    permission `CASH_JOURNAL_READ`).
    """

    def __init__(self, cash_journal_repo: CashJournalRepository) -> None:
        self._cash_journal_repo = cash_journal_repo

    def execute(
        self, salon_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[tuple[CashJournalEntry, ...], int]:
        """Retourne `(page, total)` — les opérations les plus récentes d'abord."""

        page = self._cash_journal_repo.list_for_salon(
            salon_id, limit=limit, offset=offset
        )
        total = self._cash_journal_repo.count_for_salon(salon_id)
        return page, total


class AdjustPayment:
    """Corrige un paiement validé par une **ligne d'ajustement** (§8.2, US-5.3).

    Cœur de #34. Ne supprime **jamais** le paiement d'origine (« un paiement validé
    n'est jamais supprimé ») : la correction est une **nouvelle** opération.

    Séquence :

    1. `payment_repo.get(salon_id, payment_id)` — `PaymentNotFound` (→ `404`) si hors
       salon/inconnu (isolation §11.2, aucun oracle) ;
    2. **garde métier** : le paiement doit être `VALIDATED`, sinon `PaymentNotAdjustable`
       (→ `409`) — on ne corrige pas un `PENDING`/`CANCELLED`/déjà `ADJUSTED` ;
    3. `validate_adjustment_amount(delta)` — `InvalidAdjustment` (→ `422`) si nul/hors
       borne (delta signé autorisé, mais jamais nul) ;
    4. `cash_journal_repo.append(ADJUSTMENT, amount=delta, performed_by=acteur,
       transaction_id=payment.id, description=motif)` — **nouvelle ligne**, jamais
       une modification ;
    5. `payment_repo.mark_adjusted(salon_id, payment_id)` — statut `→ ADJUSTED` (pas
       de delete) ;
    6. `audit.record(CASH_ADJUSTED)` — **neutre** (ni delta, ni motif) ;

    toutes les écritures partagent la **même Session** (atomicité `flush()` sans
    `commit()`, piloté par `get_session`). La validation du delta précède toute
    écriture ; la garde d'état précède l'`append` → aucune ligne fantôme.
    """

    def __init__(
        self,
        payment_repo: PaymentRepository,
        cash_journal_repo: CashJournalRepository,
        audit_log: AuditLog,
    ) -> None:
        self._payment_repo = payment_repo
        self._cash_journal_repo = cash_journal_repo
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        payment_id: uuid.UUID,
        delta: decimal.Decimal,
        description: str | None,
        *,
        actor_user_id: uuid.UUID,
    ) -> tuple[CashJournalEntry, Payment]:
        # 1. Résout le paiement DANS le salon (404 après portée si hors salon/inconnu).
        payment = self._payment_repo.get(salon_id, payment_id)

        # 2. Garde métier : seul un paiement VALIDATED est corrigible (§8.2).
        if payment.status != PaymentStatus.VALIDATED.value:
            raise PaymentNotAdjustable("Ce paiement ne peut pas être corrigé.")

        # 3. Validation du delta AVANT toute écriture (nul/hors borne → 422).
        amount = validate_adjustment_amount(delta)
        motif = normalize_description(description)

        # 4. Nouvelle ligne ADJUSTMENT (append-only) — jamais une réécriture.
        entry = self._cash_journal_repo.append(
            CashJournalToAppend(
                salon_id=salon_id,
                operation_type=CashOperationType.ADJUSTMENT.value,
                amount=amount,
                performed_by=actor_user_id,
                transaction_id=payment.id,
                description=motif,
            )
        )

        # 5. Statut du paiement d'origine → ADJUSTED (mutation de statut, pas de delete).
        adjusted_payment = self._payment_repo.mark_adjusted(salon_id, payment_id)

        # 6. Journalisation §11.4 « Correction de caisse » — entrée NEUTRE (ni delta, ni motif).
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.CASH_ADJUSTED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_PAYMENT,
                entity_id=payment.id,
                metadata={},
            )
        )
        return entry, adjusted_payment


__all__ = ["ListCashJournal", "AdjustPayment"]
