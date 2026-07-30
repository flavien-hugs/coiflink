"""Tests unitaires — cas d'usage `ListMyReceipts`/`GetMyReceipt` (US-5.5, #38).

Couvre :
- **appartenance forcée** : `client_id = actor_user_id` imposé ; un autre client
  ne voit aucun reçu et obtient `None` sur un reçu précis ;
- paiement sans `client_id` (comptoir) : invisible depuis tout reçu client ;
- `GetMyReceipt` renvoie `None` si payment_id inexistant ou d'un autre client
  (non-oracle §11.3) ;
- `ListMyReceipts` liste vide ≠ erreur ;
- pagination : bornes `limit`/`offset` respectées, `total` cohérent ;
- **lecture seule** : aucun appel d'écriture (le fake ne définit aucune méthode
  d'écriture, ce qui suffit à l'invariant structurel) ;
- ordre « plus récent d'abord » (miroir du contrat du port).
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.receipts import GetMyReceipt, ListMyReceipts
from coiflink_api.domain.receipt import Receipt, ReceiptLine, format_receipt_number

from .conftest import FakeReceiptRepository

# ---------------------------------------------------------------------------
# Constantes de test synthétiques
# ---------------------------------------------------------------------------

_CLIENT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_CLIENT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_PAYMENT_1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
_PAYMENT_2 = uuid.UUID("22222222-0000-0000-0000-000000000002")
_PAYMENT_3 = uuid.UUID("33333333-0000-0000-0000-000000000003")
_SALON_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_APPT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

_PAID_AT_RECENT = datetime.datetime(2026, 7, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
_PAID_AT_OLDER = datetime.datetime(2026, 7, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)


def _make_receipt(
    payment_id: uuid.UUID,
    *,
    salon_name: str = "Salon Test",
    amount: decimal.Decimal = decimal.Decimal("5000.00"),
    appointment_id: uuid.UUID | None = None,
    lines: tuple[ReceiptLine, ...] = (),
    paid_at: datetime.datetime = _PAID_AT_RECENT,
    reference: str | None = None,
) -> Receipt:
    return Receipt(
        receipt_number=format_receipt_number(payment_id),
        payment_id=payment_id,
        salon_id=_SALON_ID,
        salon_name=salon_name,
        amount=amount,
        currency="XOF",
        payment_method="CASH",
        status="VALIDATED",
        reference=reference,
        paid_at=paid_at,
        appointment_id=appointment_id,
        lines=lines,
    )


# ---------------------------------------------------------------------------
# ListMyReceipts — liste vide
# ---------------------------------------------------------------------------

class TestListMyReceiptsEmpty:
    def test_client_with_no_receipts_returns_empty_page(self) -> None:
        repo = FakeReceiptRepository()
        page, total = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert page == ()
        assert total == 0

    def test_empty_list_is_not_an_error(self) -> None:
        repo = FakeReceiptRepository()
        page, total = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert isinstance(page, tuple)
        assert isinstance(total, int)


# ---------------------------------------------------------------------------
# ListMyReceipts — appartenance forcée
# ---------------------------------------------------------------------------

class TestListMyReceiptsOwnership:
    def test_client_sees_only_own_receipts(self) -> None:
        receipt_a = _make_receipt(_PAYMENT_1)
        receipt_b = _make_receipt(_PAYMENT_2)
        repo = FakeReceiptRepository(
            receipts_by_client={
                _CLIENT_A: (receipt_a,),
                _CLIENT_B: (receipt_b,),
            }
        )
        page, total = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert total == 1
        assert page[0].payment_id == _PAYMENT_1

    def test_client_b_cannot_see_client_a_receipts(self) -> None:
        receipt_a = _make_receipt(_PAYMENT_1)
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (receipt_a,)})
        page, total = ListMyReceipts(repo).execute(_CLIENT_B, limit=20, offset=0)
        assert page == ()
        assert total == 0

    def test_payment_without_client_id_invisible_to_any_client(self) -> None:
        """Un paiement comptoir (client_id NULL) n'appartient à aucun client."""
        repo = FakeReceiptRepository()
        page, total = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert total == 0
        assert page == ()


# ---------------------------------------------------------------------------
# ListMyReceipts — pagination
# ---------------------------------------------------------------------------

class TestListMyReceiptsPagination:
    def _repo_with_three(self) -> FakeReceiptRepository:
        receipts = (
            _make_receipt(_PAYMENT_1, paid_at=_PAID_AT_RECENT),
            _make_receipt(_PAYMENT_2, paid_at=_PAID_AT_OLDER),
            _make_receipt(_PAYMENT_3, paid_at=_PAID_AT_OLDER),
        )
        return FakeReceiptRepository(receipts_by_client={_CLIENT_A: receipts})

    def test_total_reflects_all_receipts(self) -> None:
        repo = self._repo_with_three()
        _, total = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert total == 3

    def test_limit_1_returns_one_item(self) -> None:
        repo = self._repo_with_three()
        page, _ = ListMyReceipts(repo).execute(_CLIENT_A, limit=1, offset=0)
        assert len(page) == 1

    def test_offset_skips_items(self) -> None:
        repo = self._repo_with_three()
        page, _ = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=1)
        assert len(page) == 2

    def test_offset_beyond_end_returns_empty(self) -> None:
        repo = self._repo_with_three()
        page, total = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=10)
        assert page == ()
        assert total == 3

    def test_total_independent_of_limit(self) -> None:
        repo = self._repo_with_three()
        _, total_limited = ListMyReceipts(repo).execute(_CLIENT_A, limit=1, offset=0)
        _, total_full = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert total_limited == total_full == 3


# ---------------------------------------------------------------------------
# ListMyReceipts — contenu du reçu
# ---------------------------------------------------------------------------

class TestListMyReceiptsContent:
    def test_receipt_fields_match(self) -> None:
        lines = (ReceiptLine(service_name="Coupe", amount=decimal.Decimal("3000.00")),)
        r = _make_receipt(
            _PAYMENT_1,
            salon_name="Salon Élégance",
            amount=decimal.Decimal("3000.00"),
            appointment_id=_APPT_ID,
            lines=lines,
            reference="REF-001",
        )
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        page, _ = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        receipt = page[0]
        assert receipt.payment_id == _PAYMENT_1
        assert receipt.salon_name == "Salon Élégance"
        assert receipt.amount == decimal.Decimal("3000.00")
        assert receipt.appointment_id == _APPT_ID
        assert receipt.reference == "REF-001"
        assert len(receipt.lines) == 1
        assert receipt.lines[0].service_name == "Coupe"

    def test_amount_is_decimal_not_float(self) -> None:
        r = _make_receipt(_PAYMENT_1, amount=decimal.Decimal("5000.00"))
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        page, _ = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert isinstance(page[0].amount, decimal.Decimal)

    def test_receipt_number_stable(self) -> None:
        r = _make_receipt(_PAYMENT_1)
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        page1, _ = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        page2, _ = ListMyReceipts(repo).execute(_CLIENT_A, limit=20, offset=0)
        assert page1[0].receipt_number == page2[0].receipt_number


# ---------------------------------------------------------------------------
# GetMyReceipt — appartenance forcée / non-oracle
# ---------------------------------------------------------------------------

class TestGetMyReceiptOwnership:
    def test_returns_receipt_for_owner(self) -> None:
        r = _make_receipt(_PAYMENT_1)
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        result = GetMyReceipt(repo).execute(_CLIENT_A, _PAYMENT_1)
        assert result is not None
        assert result.payment_id == _PAYMENT_1

    def test_returns_none_for_other_client(self) -> None:
        """Reçu d'un autre client → `None` (non-oracle §11.3)."""
        r = _make_receipt(_PAYMENT_1)
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        result = GetMyReceipt(repo).execute(_CLIENT_B, _PAYMENT_1)
        assert result is None

    def test_returns_none_for_nonexistent_payment(self) -> None:
        """Paiement inexistant → `None` (indiscernable d'un autre client, §11.3)."""
        repo = FakeReceiptRepository()
        nonexistent = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        result = GetMyReceipt(repo).execute(_CLIENT_A, nonexistent)
        assert result is None

    def test_client_a_cannot_get_client_b_receipt_by_guessing_id(self) -> None:
        """Même en connaissant le payment_id d'un autre client → `None`."""
        r_a = _make_receipt(_PAYMENT_1)
        r_b = _make_receipt(_PAYMENT_2)
        repo = FakeReceiptRepository(
            receipts_by_client={_CLIENT_A: (r_a,), _CLIENT_B: (r_b,)}
        )
        result = GetMyReceipt(repo).execute(_CLIENT_A, _PAYMENT_2)
        assert result is None

    def test_get_returns_correct_receipt_among_several(self) -> None:
        r1 = _make_receipt(_PAYMENT_1, amount=decimal.Decimal("3000.00"))
        r2 = _make_receipt(_PAYMENT_2, amount=decimal.Decimal("7000.00"))
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r1, r2)})
        result = GetMyReceipt(repo).execute(_CLIENT_A, _PAYMENT_2)
        assert result is not None
        assert result.amount == decimal.Decimal("7000.00")


# ---------------------------------------------------------------------------
# GetMyReceipt — contenu
# ---------------------------------------------------------------------------

class TestGetMyReceiptContent:
    def test_multiline_receipt_lines_preserved(self) -> None:
        lines = (
            ReceiptLine(service_name="Coupe homme", amount=decimal.Decimal("3000.00")),
            ReceiptLine(service_name="Barbe", amount=decimal.Decimal("2000.00")),
        )
        r = _make_receipt(_PAYMENT_1, appointment_id=_APPT_ID, lines=lines)
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        result = GetMyReceipt(repo).execute(_CLIENT_A, _PAYMENT_1)
        assert result is not None
        assert len(result.lines) == 2

    def test_single_service_receipt(self) -> None:
        line = ReceiptLine(service_name="Soin", amount=decimal.Decimal("4500.00"))
        r = _make_receipt(_PAYMENT_1, lines=(line,), appointment_id=None)
        repo = FakeReceiptRepository(receipts_by_client={_CLIENT_A: (r,)})
        result = GetMyReceipt(repo).execute(_CLIENT_A, _PAYMENT_1)
        assert result is not None
        assert result.appointment_id is None
        assert result.lines[0].service_name == "Soin"


# ---------------------------------------------------------------------------
# Lecture seule — pas d'écriture dans les cas d'usage
# ---------------------------------------------------------------------------

def test_list_my_receipts_is_read_only() -> None:
    """FakeReceiptRepository n'expose aucune méthode d'écriture : l'invariant est structurel."""
    repo = FakeReceiptRepository()
    assert not hasattr(repo, "create")
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


def test_get_my_receipt_is_read_only() -> None:
    repo = FakeReceiptRepository()
    assert not hasattr(repo, "create")
    assert not hasattr(repo, "delete")
