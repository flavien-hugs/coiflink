"""Cas d'usage : **enregistrement d'un paiement** (US-5.1, #33 ; socle de #34).

Tranche applicative hexagonale calquée sur #28 : ce cas d'usage ne dépend que de
**ports** (`PaymentRepository`, `CashJournalRepository`, `AuditLog`) — aucune
dépendance FastAPI/SQLAlchemy. Il orchestre le domaine (`domain/payment.py`,
`domain/cash_journal.py`, `domain/audit.py`) et laisse l'adapter entrant traduire
les erreurs en HTTP.

Trois invariants structurants (§8.2 « Encaissement ») :

- **`salon_id`/`recorded_by` imposés** : le salon vient de la portée validée
  (`require_salon_scope`), l'auteur du `Principal` authentifié ; ni l'un ni l'autre
  n'est lu du corps de requête (non-répudiation).
- **Une ligne `PAYMENT` par paiement validé** : après création du `Payment`
  (`VALIDATED`), le cas d'usage **append** une opération `PAYMENT` au journal de
  caisse (montant positif, `performed_by = recorded_by`, `transaction_id =
  payment.id`) **via le même port** que #34. Tout paiement validé a ainsi
  exactement une ligne `PAYMENT` au journal (critère « chaque paiement apparaît
  horodaté + auteur »).
- **Journalisation §11.4 dans la même unité de travail** : la création enregistre
  une `AuditEntry` **neutre** (`metadata` vide — ni montant, ni mode, ni client) via
  le port `AuditLog`, dans la **même `Session`** que les écritures métier —
  commit/rollback atomique.
"""

from __future__ import annotations

import decimal
import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.cash_journal_repository import CashJournalRepository
from coiflink_api.application.ports.payment_repository import PaymentRepository
from coiflink_api.application.ports.queue_ticket_repository import QueueTicketRepository
from coiflink_api.application.ports.service_repository import ServiceRepository
from coiflink_api.domain.audit import ENTITY_TYPE_PAYMENT, AuditAction, AuditEntry
from coiflink_api.domain.cash_journal import CashJournalToAppend
from coiflink_api.domain.enums import CashOperationType
from coiflink_api.domain.errors import PaymentReferenceNotFound, QueueTicketAlreadyPaid
from coiflink_api.domain.payment import (
    DEFAULT_CURRENCY,
    Payment,
    PaymentToCreate,
    expected_amount_for_prices,
    normalize_reference,
    require_mobile_money_reference,
    require_reference_present,
    validate_amount,
    validate_amount_matches,
    validate_currency,
    validate_mobile_money_phone,
    validate_payment_method,
)


@dataclass(frozen=True)
class PaymentCommand:
    """Champs saisissables d'un paiement (§8.2 : « montant + mode + prestation/ticket »).

    Ni `salon_id`, ni `recorded_by`, ni `status` : le salon vient de la portée,
    l'auteur du principal, le statut est imposé `VALIDATED`. Le paiement doit
    référencer une prestation **ou** un ticket walk-in. `client_id`/`reference`/
    `currency` sont optionnels — sauf `reference`/`mobile_money_phone`, tous deux
    **obligatoires** pour `MOBILE_MONEY_MANUAL` (§8.2, migration 0019).
    """

    amount: decimal.Decimal
    payment_method: str
    service_id: uuid.UUID | None = None
    queue_ticket_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    reference: str | None = None
    mobile_money_phone: str | None = None
    currency: str = DEFAULT_CURRENCY


class RecordPayment:
    """Enregistre un paiement validé, l'inscrit au journal et journalise (§8.2/§11.4).

    Séquence : validation domaine (montant borné, mode, référence présente),
    **résolution du montant attendu** puis vérification de cohérence (§5.3/§8.2 :
    « le montant correspond à la prestation »), le tout **avant** toute écriture →
    `payment_repo.create(...)` (`VALIDATED`) → `cash_journal_repo.append(PAYMENT,
    +montant, performed_by=recorded_by, transaction_id=payment.id)` →
    `audit.record(PAYMENT_RECORDED)`. Les trois écritures partagent la **même
    Session** (atomicité). Un paiement incohérent est rejeté **avant** toute écriture
    (ni `payments`, ni `cash_journal`, ni `audit_logs`). Aucune PII/montant au
    journal d'audit.

    Le montant attendu vient de sources **salon-scopées**, jamais d'un champ soumis :
    somme des `Service.price` **actuels** des prestations du ticket walk-in lié
    (résolution en direct, aucun gel de prix côté ticket), ou `Service.price` de la
    prestation active liée. Une référence inexistante ou hors salon est
    indiscernable (`PaymentReferenceNotFound`, aucun oracle §11.2).
    """

    def __init__(
        self,
        payment_repo: PaymentRepository,
        cash_journal_repo: CashJournalRepository,
        audit_log: AuditLog,
        service_repo: ServiceRepository,
        queue_ticket_repo: QueueTicketRepository,
    ) -> None:
        self._payment_repo = payment_repo
        self._cash_journal_repo = cash_journal_repo
        self._audit_log = audit_log
        self._service_repo = service_repo
        self._queue_ticket_repo = queue_ticket_repo

    def execute(
        self,
        salon_id: uuid.UUID,
        command: PaymentCommand,
        *,
        actor_user_id: uuid.UUID,
    ) -> Payment:
        # Validation domaine AVANT toute écriture (aucun paiement ni trace si invalide).
        amount = validate_amount(command.amount)
        method = validate_payment_method(command.payment_method)
        currency = validate_currency(command.currency)
        require_reference_present(command.service_id, command.queue_ticket_id)
        reference = normalize_reference(command.reference)
        # Mobile Money exige téléphone ET numéro de transaction (§8.2, migration
        # 0019) — le téléphone retombe sur `None` pour tout autre mode.
        mobile_money_phone = validate_mobile_money_phone(method, command.mobile_money_phone)
        require_mobile_money_reference(method, reference)

        # Un ticket déjà couvert par un paiement VALIDATED/ADJUSTED ne peut pas être
        # encaissé une seconde fois (§8.2) — vérifié AVANT toute écriture, comme les
        # autres gardes de cette méthode.
        if command.queue_ticket_id is not None and self._payment_repo.has_paid_payment(
            salon_id, command.queue_ticket_id
        ):
            raise QueueTicketAlreadyPaid("Ce ticket a déjà été encaissé.")

        # Cohérence du montant (§5.3/§8.2, cœur de #33) : résoudre le prix attendu à
        # partir de la référence salon-scopée, puis exiger l'égalité stricte. Toujours
        # AVANT la moindre écriture — un paiement incohérent ne laisse aucune trace.
        expected = self._resolve_expected_amount(salon_id, command)
        validate_amount_matches(amount, expected)

        payment = self._payment_repo.create(
            PaymentToCreate(
                salon_id=salon_id,
                amount=amount,
                payment_method=method,
                recorded_by=actor_user_id,
                service_id=command.service_id,
                queue_ticket_id=command.queue_ticket_id,
                client_id=command.client_id,
                currency=currency,
                reference=reference,
                mobile_money_phone=mobile_money_phone,
            )
        )

        # Une ligne PAYMENT au journal, via le MÊME port que la correction (#34) :
        # montant positif, auteur = celui qui a encaissé, liée à la transaction.
        self._cash_journal_repo.append(
            CashJournalToAppend(
                salon_id=salon_id,
                operation_type=CashOperationType.PAYMENT.value,
                amount=payment.amount,
                performed_by=actor_user_id,
                transaction_id=payment.id,
                description=None,
            )
        )

        self._audit_log.record(
            AuditEntry(
                action=AuditAction.PAYMENT_RECORDED.value,
                actor_user_id=actor_user_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_PAYMENT,
                entity_id=payment.id,
                # `metadata` **vide** : ni montant, ni mode, ni client au journal (§11.3/§11.4).
                metadata={},
            )
        )
        return payment

    def _resolve_expected_amount(
        self, salon_id: uuid.UUID, command: PaymentCommand
    ) -> decimal.Decimal:
        """Calcule le **montant attendu** de la référence (ticket prioritaire, §5.3/§8.2).

        - `queue_ticket_id` fourni → montant attendu = somme des `Service.price`
          **actuels** des prestations du ticket (résolution en direct — un ticket
          walk-in ne fige pas de prix à l'émission ; le délai entre émission et
          encaissement est de toute façon la même journée).
        - `service_id` seul → montant attendu = `Service.price` de la prestation
          **active** du salon.

        Une référence inexistante, hors salon, ou (pour une prestation seule)
        désactivée est **indiscernable** et lève `PaymentReferenceNotFound` (aucun
        oracle d'existence inter-salons, §11.2). Aucune valeur d'un autre salon n'est
        jamais lue (filtres `salon_id` des dépôts).
        """

        if command.queue_ticket_id is not None:
            ticket = self._queue_ticket_repo.get(salon_id, command.queue_ticket_id)
            if ticket is None:
                raise PaymentReferenceNotFound(
                    "Prestation ou ticket introuvable pour ce salon."
                )
            prices: list[decimal.Decimal] = []
            for service_id in ticket.service_ids:
                service = self._service_repo.find_by_id(salon_id, service_id)
                if service is None:
                    raise PaymentReferenceNotFound(
                        "Prestation ou ticket introuvable pour ce salon."
                    )
                prices.append(service.price)
            return expected_amount_for_prices(prices)

        service = self._service_repo.find_by_id(salon_id, command.service_id)
        if service is None or not service.is_active:
            raise PaymentReferenceNotFound(
                "Prestation ou ticket introuvable pour ce salon."
            )
        return service.price


__all__ = ["PaymentCommand", "RecordPayment"]
