"""Tests unitaires — cas d'usage journal de caisse & paiement (US-5.1/5.3, #33/#34).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.

Couvre :
- `ListCashJournal` : retourne (page, total) depuis le dépôt ; isolation par salon
  (entrées d'un autre salon absentes) ; pagination limit/offset ; aucun audit.
- `AdjustPayment` nominal : une ligne `ADJUSTMENT` créée (delta, `transaction_id =
  payment.id`, `performed_by = acteur`) ; paiement passé à `ADJUSTED` ; un audit
  `CASH_ADJUSTED` avec `metadata == {}` (ni delta, ni motif) ; description normalisée.
- `AdjustPayment` garde d'état : `PENDING`/`CANCELLED`/`ADJUSTED` → `PaymentNotAdjustable`
  sans écriture ni audit.
- `AdjustPayment` delta invalide : zéro / hors borne → `InvalidAdjustment` sans écriture.
- `AdjustPayment` paiement hors salon/inconnu → `PaymentNotFound` sans audit (isolation §11.2).
- Invariant append-only structurel : `FakeCashJournalRepository` n'expose pas `update`/`delete`.
- `RecordPayment` nominal : paiement `VALIDATED`, ligne `PAYMENT` au journal
  (`transaction_id = payment.id`, `performed_by = acteur`), audit `PAYMENT_RECORDED`
  avec `metadata == {}`.
- `RecordPayment` validation invalide : aucune écriture, aucun audit.
- `RecordPayment` cohérence (#33) : montant ≠ prix → `PaymentAmountMismatch` avant écriture ;
  prestation inconnue/inactive → `PaymentReferenceNotFound` avant écriture.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.application.cash_journal import AdjustPayment, ListCashJournal
from coiflink_api.application.payments import PaymentCommand, RecordPayment
from coiflink_api.domain.audit import ENTITY_TYPE_PAYMENT, AuditAction
from coiflink_api.domain.cash_journal import CashJournalEntry
from coiflink_api.domain.enums import CashOperationType, PaymentStatus
from coiflink_api.domain.errors import (
    InvalidAdjustment,
    InvalidPaymentAmount,
    InvalidPhone,
    MobileMoneyPhoneRequired,
    MobileMoneyReferenceRequired,
    PaymentAmountMismatch,
    PaymentNotAdjustable,
    PaymentNotFound,
    PaymentReferenceNotFound,
    PaymentReferenceRequired,
    QueueTicketAlreadyPaid,
)
from coiflink_api.domain.payment import Payment
from coiflink_api.domain.queue_ticket import QueueTicket
from coiflink_api.domain.service import Service

from .conftest import (
    FakeAuditLog,
    FakeCashJournalRepository,
    FakePaymentRepository,
    FakeQueueTicketRepository,
    FakeServiceRepository,
)

# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ACTOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_PAYMENT_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_SERVICE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_QUEUE_TICKET_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
_CREATED_AT = datetime.datetime(2026, 7, 28, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _service_repo_for(price: decimal.Decimal) -> FakeServiceRepository:
    """Dépôt de prestations seedé avec `_SERVICE_ID` **active** au prix voulu.

    La cohérence du montant (#33) résout le prix attendu depuis la prestation liée :
    ces tests `RecordPayment` (socle #34) doivent donc fournir une prestation dont le
    prix **égale** le montant du paiement pour rester nominaux.
    """

    repo = FakeServiceRepository()
    repo._services[_SERVICE_ID] = Service(
        id=_SERVICE_ID,
        salon_id=_SALON_ID,
        name="Coupe",
        description=None,
        price=price,
        duration_minutes=30,
        category=None,
        is_active=True,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )
    return repo


def _make_payment(
    *,
    status: str = PaymentStatus.VALIDATED.value,
    salon_id: uuid.UUID = _SALON_ID,
    payment_id: uuid.UUID = _PAYMENT_ID,
) -> Payment:
    return Payment(
        id=payment_id,
        salon_id=salon_id,
        amount=decimal.Decimal("5000.00"),
        currency="XOF",
        payment_method="CASH",
        status=status,
        recorded_by=_ACTOR_ID,
        service_id=_SERVICE_ID,
        queue_ticket_id=None,
        client_id=None,
        reference=None,
        mobile_money_phone=None,
        created_at=_CREATED_AT,
    )


def _make_journal_entry(salon_id: uuid.UUID = _SALON_ID) -> CashJournalEntry:
    return CashJournalEntry(
        id=uuid.uuid4(),
        salon_id=salon_id,
        operation_type=CashOperationType.PAYMENT.value,
        amount=decimal.Decimal("1000.00"),
        currency="XOF",
        performed_by=_ACTOR_ID,
        performed_by_name=None,
        transaction_id=_PAYMENT_ID,
        description=None,
        created_at=_CREATED_AT,
    )


# ---------------------------------------------------------------------------
# ListCashJournal
# ---------------------------------------------------------------------------


class TestListCashJournal:
    def test_returns_page_and_total(self) -> None:
        repo = FakeCashJournalRepository()
        repo._entries.append(_make_journal_entry())
        repo._entries.append(_make_journal_entry())

        page, total = ListCashJournal(repo).execute(_SALON_ID, limit=10, offset=0)

        assert total == 2
        assert len(page) == 2

    def test_empty_journal_returns_empty_page(self) -> None:
        repo = FakeCashJournalRepository()

        page, total = ListCashJournal(repo).execute(_SALON_ID, limit=10, offset=0)

        assert page == ()
        assert total == 0

    def test_isolation_entries_from_other_salon_excluded(self) -> None:
        """Seules les opérations du salon de la portée sont retournées (§11.2)."""
        repo = FakeCashJournalRepository()
        repo._entries.append(_make_journal_entry(salon_id=_OTHER_SALON_ID))

        page, total = ListCashJournal(repo).execute(_SALON_ID, limit=10, offset=0)

        assert total == 0
        assert len(page) == 0

    def test_pagination_limit_applied(self) -> None:
        repo = FakeCashJournalRepository()
        for _ in range(5):
            repo._entries.append(_make_journal_entry())

        page, _ = ListCashJournal(repo).execute(_SALON_ID, limit=2, offset=0)

        assert len(page) == 2

    def test_pagination_offset_applied(self) -> None:
        repo = FakeCashJournalRepository()
        for _ in range(5):
            repo._entries.append(_make_journal_entry())

        page, total = ListCashJournal(repo).execute(_SALON_ID, limit=2, offset=3)

        assert total == 5
        assert len(page) == 2

    def test_does_not_record_audit(self) -> None:
        """Une consultation de journal ne génère aucune entrée d'audit (lecture pure)."""
        repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        ListCashJournal(repo).execute(_SALON_ID, limit=10, offset=0)

        assert len(audit.recorded) == 0

    def test_total_counts_only_salon_entries(self) -> None:
        repo = FakeCashJournalRepository()
        repo._entries.append(_make_journal_entry(salon_id=_SALON_ID))
        repo._entries.append(_make_journal_entry(salon_id=_OTHER_SALON_ID))

        _, total = ListCashJournal(repo).execute(_SALON_ID, limit=10, offset=0)

        assert total == 1


# ---------------------------------------------------------------------------
# AdjustPayment
# ---------------------------------------------------------------------------


class TestAdjustPaymentNominal:
    def _run(
        self,
        payment: Payment | None = None,
        delta: decimal.Decimal = decimal.Decimal("-500.00"),
        description: str | None = "Erreur de saisie",
    ) -> tuple:
        p = payment or _make_payment()
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        entry, adjusted = AdjustPayment(payment_repo, journal_repo, audit).execute(
            _SALON_ID, p.id, delta, description, actor_user_id=_ACTOR_ID
        )
        return entry, adjusted, journal_repo, audit, payment_repo

    def test_journal_entry_operation_type_is_adjustment(self) -> None:
        entry, _, _, _, _ = self._run()
        assert entry.operation_type == CashOperationType.ADJUSTMENT.value

    def test_journal_entry_amount_matches_delta(self) -> None:
        delta = decimal.Decimal("-500.00")
        entry, _, _, _, _ = self._run(delta=delta)
        assert entry.amount == delta

    def test_journal_entry_transaction_id_is_payment_id(self) -> None:
        p = _make_payment()
        entry, _, _, _, _ = self._run(payment=p)
        assert entry.transaction_id == p.id

    def test_journal_entry_performed_by_is_actor(self) -> None:
        """Non-répudiation §8.2 : `performed_by` vient du principal."""
        entry, _, _, _, _ = self._run()
        assert entry.performed_by == _ACTOR_ID

    def test_payment_status_becomes_adjusted(self) -> None:
        _, adjusted, _, _, _ = self._run()
        assert adjusted.status == PaymentStatus.ADJUSTED.value

    def test_exactly_one_journal_entry_created(self) -> None:
        _, _, journal_repo, _, _ = self._run()
        assert len(journal_repo.appended) == 1

    def test_exactly_one_audit_entry_recorded(self) -> None:
        _, _, _, audit, _ = self._run()
        assert len(audit.recorded) == 1

    def test_audit_action_is_cash_adjusted(self) -> None:
        _, _, _, audit, _ = self._run()
        assert audit.recorded[0].action == AuditAction.CASH_ADJUSTED.value

    def test_audit_metadata_is_empty(self) -> None:
        """Entrée d'audit neutre — ni delta, ni motif, ni PII (§11.3/§11.4)."""
        _, _, _, audit, _ = self._run()
        assert audit.recorded[0].metadata == {}

    def test_audit_actor_user_id_is_correct(self) -> None:
        _, _, _, audit, _ = self._run()
        assert audit.recorded[0].actor_user_id == _ACTOR_ID

    def test_audit_entity_type_is_payment(self) -> None:
        _, _, _, audit, _ = self._run()
        assert audit.recorded[0].entity_type == ENTITY_TYPE_PAYMENT

    def test_audit_entity_id_is_payment_id(self) -> None:
        p = _make_payment()
        _, _, _, audit, _ = self._run(payment=p)
        assert audit.recorded[0].entity_id == p.id

    def test_audit_salon_id_is_correct(self) -> None:
        _, _, _, audit, _ = self._run()
        assert audit.recorded[0].salon_id == _SALON_ID

    def test_description_trimmed(self) -> None:
        entry, _, _, _, _ = self._run(description="  motif  ")
        assert entry.description == "motif"

    def test_empty_description_normalized_to_none(self) -> None:
        entry, _, _, _, _ = self._run(description="   ")
        assert entry.description is None

    def test_none_description_stays_none(self) -> None:
        entry, _, _, _, _ = self._run(description=None)
        assert entry.description is None

    def test_positive_delta_valid(self) -> None:
        """Un delta positif (correction à la hausse) est un ajustement valide."""
        entry, _, _, _, _ = self._run(delta=decimal.Decimal("200.00"))
        assert entry.amount == decimal.Decimal("200.00")


class TestAdjustPaymentGuardStatus:
    @pytest.mark.parametrize("status", [
        PaymentStatus.PENDING.value,
        PaymentStatus.CANCELLED.value,
        PaymentStatus.ADJUSTED.value,
    ])
    def test_non_validated_status_raises_not_adjustable(self, status: str) -> None:
        p = _make_payment(status=status)
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotAdjustable):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

    @pytest.mark.parametrize("status", [
        PaymentStatus.PENDING.value,
        PaymentStatus.CANCELLED.value,
    ])
    def test_non_adjustable_no_journal_entry(self, status: str) -> None:
        p = _make_payment(status=status)
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotAdjustable):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

        assert len(journal_repo.appended) == 0

    @pytest.mark.parametrize("status", [
        PaymentStatus.PENDING.value,
        PaymentStatus.ADJUSTED.value,
    ])
    def test_non_adjustable_no_audit(self, status: str) -> None:
        p = _make_payment(status=status)
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotAdjustable):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

        assert len(audit.recorded) == 0


class TestAdjustPaymentInvalidDelta:
    def test_zero_delta_raises(self) -> None:
        p = _make_payment()
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(InvalidAdjustment):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("0"), None, actor_user_id=_ACTOR_ID
            )

    def test_invalid_delta_no_journal_entry(self) -> None:
        p = _make_payment()
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(InvalidAdjustment):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("0"), None, actor_user_id=_ACTOR_ID
            )

        assert len(journal_repo.appended) == 0

    def test_invalid_delta_no_audit(self) -> None:
        p = _make_payment()
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(InvalidAdjustment):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("0"), None, actor_user_id=_ACTOR_ID
            )

        assert len(audit.recorded) == 0


class TestAdjustPaymentIsolation:
    def test_unknown_payment_raises_not_found(self) -> None:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotFound):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, uuid.uuid4(), decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

    def test_payment_from_other_salon_raises_not_found(self) -> None:
        """Isolation §11.2 : paiement d'un autre salon = indiscernable de l'inexistant."""
        p = _make_payment(salon_id=_OTHER_SALON_ID)
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotFound):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

    def test_cross_salon_no_audit_recorded(self) -> None:
        """Aucun audit ne fuit sur un accès inter-salons refusé."""
        p = _make_payment(salon_id=_OTHER_SALON_ID)
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotFound):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

        assert len(audit.recorded) == 0

    def test_cross_salon_no_journal_entry(self) -> None:
        p = _make_payment(salon_id=_OTHER_SALON_ID)
        payment_repo = FakePaymentRepository(payments=[p])
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()

        with pytest.raises(PaymentNotFound):
            AdjustPayment(payment_repo, journal_repo, audit).execute(
                _SALON_ID, p.id, decimal.Decimal("-100.00"), None, actor_user_id=_ACTOR_ID
            )

        assert len(journal_repo.appended) == 0


class TestAdjustPaymentAppendOnly:
    def test_fake_cash_journal_has_no_update_method(self) -> None:
        """L'invariant append-only est structurel : le port ne déclare pas update."""
        repo = FakeCashJournalRepository()
        assert not hasattr(repo, "update"), "update ne doit pas exister sur le port"

    def test_fake_cash_journal_has_no_delete_method(self) -> None:
        repo = FakeCashJournalRepository()
        assert not hasattr(repo, "delete"), "delete ne doit pas exister sur le port"

    def test_fake_payment_repo_has_no_delete_method(self) -> None:
        """Un paiement validé n'est jamais supprimé (§8.2)."""
        repo = FakePaymentRepository()
        assert not hasattr(repo, "delete"), "delete ne doit pas exister sur le port"


# ---------------------------------------------------------------------------
# RecordPayment
# ---------------------------------------------------------------------------


class TestRecordPaymentNominal:
    def _run(
        self,
        *,
        amount: decimal.Decimal = decimal.Decimal("5000.00"),
        payment_method: str = "CASH",
    ) -> tuple:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=amount,
            payment_method=payment_method,
            service_id=_SERVICE_ID,
        )
        payment = RecordPayment(
            payment_repo,
            journal_repo,
            audit,
            _service_repo_for(amount),
            FakeQueueTicketRepository(),
        ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        return payment, payment_repo, journal_repo, audit

    def test_payment_salon_id_from_scope(self) -> None:
        payment, _, _, _ = self._run()
        assert payment.salon_id == _SALON_ID

    def test_payment_status_is_validated(self) -> None:
        payment, _, _, _ = self._run()
        assert payment.status == PaymentStatus.VALIDATED.value

    def test_recorded_by_from_actor_not_body(self) -> None:
        """Non-répudiation §8.2 : `recorded_by` vient toujours du principal."""
        payment, _, _, _ = self._run()
        assert payment.recorded_by == _ACTOR_ID

    def test_journal_payment_entry_appended(self) -> None:
        payment, _, journal_repo, _ = self._run()
        assert len(journal_repo.appended) == 1
        appended = journal_repo.appended[0]
        assert appended.operation_type == CashOperationType.PAYMENT.value

    def test_journal_entry_transaction_id_is_payment_id(self) -> None:
        payment, _, journal_repo, _ = self._run()
        assert journal_repo.appended[0].transaction_id == payment.id

    def test_journal_entry_performed_by_is_actor(self) -> None:
        _, _, journal_repo, _ = self._run()
        assert journal_repo.appended[0].performed_by == _ACTOR_ID

    def test_journal_entry_amount_equals_payment_amount(self) -> None:
        payment, _, journal_repo, _ = self._run(amount=decimal.Decimal("3000.00"))
        assert journal_repo.appended[0].amount == payment.amount

    def test_audit_payment_recorded_once(self) -> None:
        _, _, _, audit = self._run()
        assert len(audit.recorded) == 1
        assert audit.recorded[0].action == AuditAction.PAYMENT_RECORDED.value

    def test_audit_metadata_is_empty(self) -> None:
        """Ni montant, ni mode, ni client au journal d'audit (§11.3/§11.4)."""
        _, _, _, audit = self._run()
        assert audit.recorded[0].metadata == {}

    def test_audit_actor_is_correct(self) -> None:
        _, _, _, audit = self._run()
        assert audit.recorded[0].actor_user_id == _ACTOR_ID

    def test_audit_salon_id_is_correct(self) -> None:
        _, _, _, audit = self._run()
        assert audit.recorded[0].salon_id == _SALON_ID


class TestRecordPaymentValidation:
    def test_negative_amount_raises_no_payment_created(self) -> None:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("-100.00"),
            payment_method="CASH",
            service_id=_SERVICE_ID,
        )

        with pytest.raises(InvalidPaymentAmount):
            RecordPayment(
                payment_repo,
                journal_repo,
                audit,
                FakeServiceRepository(),
                FakeQueueTicketRepository(),
            ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0

    def test_missing_reference_raises_no_writes(self) -> None:
        """Un paiement sans prestation ni ticket est refusé avant toute écriture (§8.2)."""
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("1000.00"),
            payment_method="CASH",
        )

        with pytest.raises(PaymentReferenceRequired):
            RecordPayment(
                payment_repo,
                journal_repo,
                audit,
                FakeServiceRepository(),
                FakeQueueTicketRepository(),
            ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0


class TestRecordPaymentMobileMoney:
    """Mobile Money exige téléphone ET numéro de transaction (§8.2, migration 0019)."""

    def _run(self, **overrides: object) -> tuple:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        fields = {
            "amount": decimal.Decimal("5000.00"),
            "payment_method": "MOBILE_MONEY_MANUAL",
            "service_id": _SERVICE_ID,
            "reference": "MM-TX-0001",
            "mobile_money_phone": "0700000000",
        }
        fields.update(overrides)
        cmd = PaymentCommand(**fields)  # type: ignore[arg-type]
        payment = RecordPayment(
            payment_repo,
            journal_repo,
            audit,
            _service_repo_for(fields["amount"]),  # type: ignore[arg-type]
            FakeQueueTicketRepository(),
        ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)
        return payment, payment_repo, journal_repo, audit

    def test_phone_and_reference_present_creates_payment(self) -> None:
        payment, payment_repo, _, _ = self._run()
        assert len(payment_repo.created) == 1
        assert payment.mobile_money_phone == "+2250700000000"
        assert payment.reference == "MM-TX-0001"

    def test_missing_phone_raises_no_writes(self) -> None:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="MOBILE_MONEY_MANUAL",
            service_id=_SERVICE_ID,
            reference="MM-TX-0001",
        )

        with pytest.raises(MobileMoneyPhoneRequired):
            RecordPayment(
                payment_repo,
                journal_repo,
                audit,
                _service_repo_for(decimal.Decimal("5000.00")),
                FakeQueueTicketRepository(),
            ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0

    def test_missing_reference_raises_no_writes(self) -> None:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="MOBILE_MONEY_MANUAL",
            service_id=_SERVICE_ID,
            mobile_money_phone="0700000000",
        )

        with pytest.raises(MobileMoneyReferenceRequired):
            RecordPayment(
                payment_repo,
                journal_repo,
                audit,
                _service_repo_for(decimal.Decimal("5000.00")),
                FakeQueueTicketRepository(),
            ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0

    def test_malformed_phone_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            self._run(mobile_money_phone="abc")

    def test_cash_payment_ignores_a_provided_phone(self) -> None:
        """Un téléphone fourni hors Mobile Money est toujours ignoré (jamais persisté)."""
        payment, _, _, _ = self._run(
            payment_method="CASH", reference=None, mobile_money_phone="0700000000"
        )
        assert payment.mobile_money_phone is None


# ---------------------------------------------------------------------------
# RecordPayment — cohérence du montant (#33, §5.3/§8.2)
# ---------------------------------------------------------------------------


def _make_inactive_service_repo() -> FakeServiceRepository:
    """Dépôt seedé avec `_SERVICE_ID` **désactivée** (price 5000.00)."""
    repo = FakeServiceRepository()
    repo._services[_SERVICE_ID] = Service(
        id=_SERVICE_ID,
        salon_id=_SALON_ID,
        name="Coupe",
        description=None,
        price=decimal.Decimal("5000.00"),
        duration_minutes=30,
        category=None,
        is_active=False,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )
    return repo


class TestRecordPaymentCoherence:
    """Cohérence du montant (#33) : PaymentAmountMismatch / PaymentReferenceNotFound.

    Toutes les erreurs de cohérence sont levées **avant** toute écriture : ni
    `payments`, ni `cash_journal`, ni `audit_logs` ne sont modifiés.
    """

    def _record(
        self,
        payment_repo: FakePaymentRepository,
        journal_repo: FakeCashJournalRepository,
        audit: FakeAuditLog,
        service_repo: FakeServiceRepository,
        cmd: PaymentCommand,
    ) -> None:
        RecordPayment(
            payment_repo,
            journal_repo,
            audit,
            service_repo,
            FakeQueueTicketRepository(),
        ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

    def test_amount_mismatch_raises(self) -> None:
        """Montant saisi ≠ prix de la prestation → PaymentAmountMismatch (§5.3/§8.2)."""
        service_repo = _service_repo_for(decimal.Decimal("3000.00"))
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            service_id=_SERVICE_ID,
        )
        with pytest.raises(PaymentAmountMismatch):
            self._record(FakePaymentRepository(), FakeCashJournalRepository(), FakeAuditLog(), service_repo, cmd)

    def test_amount_mismatch_no_writes(self) -> None:
        service_repo = _service_repo_for(decimal.Decimal("3000.00"))
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            service_id=_SERVICE_ID,
        )
        with pytest.raises(PaymentAmountMismatch):
            self._record(payment_repo, journal_repo, audit, service_repo, cmd)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0

    def test_unknown_service_raises_reference_not_found(self) -> None:
        """Prestation inconnue → PaymentReferenceNotFound, indiscernable de hors-salon (§11.2)."""
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            service_id=uuid.uuid4(),
        )
        with pytest.raises(PaymentReferenceNotFound):
            self._record(FakePaymentRepository(), FakeCashJournalRepository(), FakeAuditLog(), FakeServiceRepository(), cmd)

    def test_unknown_service_no_writes(self) -> None:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            service_id=uuid.uuid4(),
        )
        with pytest.raises(PaymentReferenceNotFound):
            self._record(payment_repo, journal_repo, audit, FakeServiceRepository(), cmd)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0

    def test_inactive_service_raises_reference_not_found(self) -> None:
        """Prestation désactivée → PaymentReferenceNotFound (pas d'oracle actif/inactif §11.2)."""
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            service_id=_SERVICE_ID,
        )
        with pytest.raises(PaymentReferenceNotFound):
            self._record(FakePaymentRepository(), FakeCashJournalRepository(), FakeAuditLog(), _make_inactive_service_repo(), cmd)

    def test_inactive_service_no_writes(self) -> None:
        payment_repo = FakePaymentRepository()
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            service_id=_SERVICE_ID,
        )
        with pytest.raises(PaymentReferenceNotFound):
            self._record(payment_repo, journal_repo, audit, _make_inactive_service_repo(), cmd)

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0


# ---------------------------------------------------------------------------
# RecordPayment — garde anti double-encaissement d'un ticket (§8.2)
# ---------------------------------------------------------------------------


def _make_ticket_payment(
    *,
    queue_ticket_id: uuid.UUID = _QUEUE_TICKET_ID,
    salon_id: uuid.UUID = _SALON_ID,
    status: str = PaymentStatus.VALIDATED.value,
) -> Payment:
    """Un paiement déjà rattaché à `queue_ticket_id` (aucune prestation directe)."""

    return Payment(
        id=uuid.uuid4(),
        salon_id=salon_id,
        amount=decimal.Decimal("5000.00"),
        currency="XOF",
        payment_method="CASH",
        status=status,
        recorded_by=_ACTOR_ID,
        service_id=None,
        queue_ticket_id=queue_ticket_id,
        client_id=None,
        reference=None,
        mobile_money_phone=None,
        created_at=_CREATED_AT,
    )


def _make_queue_ticket(
    *,
    ticket_id: uuid.UUID = _QUEUE_TICKET_ID,
    salon_id: uuid.UUID = _SALON_ID,
) -> QueueTicket:
    """Ticket `done` portant `_SERVICE_ID` — résout un montant attendu de 5000.00."""

    return QueueTicket(
        id=ticket_id,
        salon_id=salon_id,
        ticket_number=1,
        issued_date=datetime.date(2026, 7, 28),
        customer_profile_id=None,
        service_ids=(_SERVICE_ID,),
        status="done",
        hairdresser_id=None,
        estimated_wait_minutes=10,
        created_at=_CREATED_AT,
        called_at=None,
        started_at=_CREATED_AT,
        completed_at=_CREATED_AT,
        cancellation_reason=None,
    )


class TestRecordPaymentAlreadyPaidTicket:
    """Second encaissement d'un ticket déjà couvert → `QueueTicketAlreadyPaid` (§8.2).

    Miroir de `TestRecordPaymentCoherence` : la garde est vérifiée **avant** toute
    écriture (ni `payments`, ni `cash_journal`, ni `audit_logs`).
    """

    def _record(
        self,
        payment_repo: FakePaymentRepository,
        journal_repo: FakeCashJournalRepository,
        audit: FakeAuditLog,
        service_repo: FakeServiceRepository,
        tickets_repo: FakeQueueTicketRepository,
        cmd: PaymentCommand,
    ) -> None:
        RecordPayment(
            payment_repo,
            journal_repo,
            audit,
            service_repo,
            tickets_repo,
        ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

    def test_second_payment_on_paid_ticket_raises(self) -> None:
        payment_repo = FakePaymentRepository(payments=[_make_ticket_payment()])
        tickets_repo = FakeQueueTicketRepository()
        tickets_repo.seed(_make_queue_ticket())
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            queue_ticket_id=_QUEUE_TICKET_ID,
        )
        with pytest.raises(QueueTicketAlreadyPaid):
            self._record(
                payment_repo,
                FakeCashJournalRepository(),
                FakeAuditLog(),
                _service_repo_for(decimal.Decimal("5000.00")),
                tickets_repo,
                cmd,
            )

    def test_second_payment_on_paid_ticket_no_writes(self) -> None:
        payment_repo = FakePaymentRepository(payments=[_make_ticket_payment()])
        tickets_repo = FakeQueueTicketRepository()
        tickets_repo.seed(_make_queue_ticket())
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            queue_ticket_id=_QUEUE_TICKET_ID,
        )
        with pytest.raises(QueueTicketAlreadyPaid):
            self._record(
                payment_repo,
                journal_repo,
                audit,
                _service_repo_for(decimal.Decimal("5000.00")),
                tickets_repo,
                cmd,
            )

        assert len(payment_repo.created) == 0
        assert len(journal_repo.appended) == 0
        assert len(audit.recorded) == 0

    def test_first_payment_on_fresh_ticket_still_succeeds(self) -> None:
        """Pas de faux positif : un ticket sans paiement existant encaisse normalement."""
        payment_repo = FakePaymentRepository()
        tickets_repo = FakeQueueTicketRepository()
        tickets_repo.seed(_make_queue_ticket())
        journal_repo = FakeCashJournalRepository()
        audit = FakeAuditLog()
        cmd = PaymentCommand(
            amount=decimal.Decimal("5000.00"),
            payment_method="CASH",
            queue_ticket_id=_QUEUE_TICKET_ID,
        )

        payment = RecordPayment(
            payment_repo,
            journal_repo,
            audit,
            _service_repo_for(decimal.Decimal("5000.00")),
            tickets_repo,
        ).execute(_SALON_ID, cmd, actor_user_id=_ACTOR_ID)

        assert payment.status == PaymentStatus.VALIDATED.value
        assert len(payment_repo.created) == 1
        assert len(journal_repo.appended) == 1
        assert len(audit.recorded) == 1
